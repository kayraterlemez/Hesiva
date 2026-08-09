import hashlib
import math
import re
import sqlite3
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal, InvalidOperation
from pathlib import Path

from hesiva.importers.exa import ExaFormatError, recover_frm1_database
from hesiva.read_models import LegacyImportPreflight


DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
TIME_PATTERN = re.compile(r"[0-9]{2}:[0-9]{2}:[0-9]{2}")

CARIKART_COLUMNS = (
    ("ID", "INTEGER", True, True),
    ("Tarih", "DATE", False, False),
    ("Kod", "CHAR(25)", False, False),
    ("Unvan", "CHAR(100)", False, False),
    ("Yetkili", "CHAR(100)", False, False),
    ("Gsm", "CHAR(25)", False, False),
    ("Tel", "CHAR(25)", False, False),
    ("Fax", "CHAR(25)", False, False),
    ("Adres", "CHAR(250)", False, False),
    ("il", "CHAR(50)", False, False),
    ("ilce", "CHAR(50)", False, False),
    ("VergiDaire", "CHAR(25)", False, False),
    ("VergiNo", "CHAR(25)", False, False),
    ("EPosta", "CHAR(100)", False, False),
    ("Web", "CHAR(100)", False, False),
    ("CLimit", "MONEY", False, False),
    ("Hesap", "CHAR(5)", False, False),
    ("CNot", "TEXT", False, False),
    ("STarih", "DATE", False, False),
    ("Borc", "MONEY", False, False),
    ("Alacak", "MONEY", False, False),
    ("Bakiye", "MONEY", False, False),
)
DATA_COLUMNS = (
    ("ID", "INTEGER", True, True),
    ("Tarih", "DATE", False, False),
    ("Saat", "TIME", False, False),
    ("Tur", "CHAR(25)", False, False),
    ("Unvan", "CHAR(100)", False, False),
    ("Aciklama", "CHAR(250)", False, False),
    ("Borc", "MONEY", False, False),
    ("Alacak", "MONEY", False, False),
    ("CariKartID", "INTEGER", False, False),
)
ATEMP_COLUMNS = (
    ("ID", "INTEGER", True, True),
    ("TurID", "INTEGER", False, False),
    ("Aciklama", "CHAR(250)", False, False),
)

CARIKART_TEXT_COLUMNS = tuple(
    name
    for name, declared_type, _, _ in CARIKART_COLUMNS
    if declared_type != "INTEGER" and declared_type != "MONEY"
)
DATA_TEXT_COLUMNS = tuple(
    name for name, declared_type, _, _ in DATA_COLUMNS if declared_type not in {"INTEGER", "MONEY"}
)
PLACEHOLDER_TEXT_COLUMNS = (
    "Tarih",
    "Kod",
    "Yetkili",
    "Gsm",
    "Tel",
    "Fax",
    "Adres",
    "il",
    "ilce",
    "VergiDaire",
    "VergiNo",
    "EPosta",
    "Web",
    "CNot",
    "Hesap",
    "STarih",
)
PLACEHOLDER_MONEY_COLUMNS = ("CLimit", "Borc", "Alacak", "Bakiye")


class LegacySourceError(Exception):
    """Raised when a legacy database violates the supported V1 source contract."""


@dataclass(frozen=True, slots=True)
class LegacyCustomerRecord:
    legacy_id: int
    full_name: str
    phone: str | None
    address: str | None
    notes: str | None
    registered_on: date | None


@dataclass(frozen=True, slots=True)
class LegacyTransactionRecord:
    legacy_id: int
    customer_legacy_id: int
    transaction_date: date
    transaction_time: time | None
    description: str
    amount_kurus: int


@dataclass(frozen=True, slots=True)
class LegacyCustomerFinancialExpectation:
    customer_legacy_id: int
    debt_kurus: int
    payment_kurus: int
    signed_net_kurus: int


@dataclass(frozen=True, slots=True)
class LegacyImportPlan:
    source_sha256: str
    customers: tuple[LegacyCustomerRecord, ...]
    transactions: tuple[LegacyTransactionRecord, ...]
    per_customer: tuple[LegacyCustomerFinancialExpectation, ...]
    preflight: LegacyImportPreflight


def _source_digest(path: Path) -> str:
    try:
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    except OSError as error:
        raise LegacySourceError("The selected legacy source could not be read safely.") from error


def _decode_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, bytes):
        raise LegacySourceError(f"Legacy {field_name} does not use the supported text storage.")
    try:
        return value.decode("cp1254")
    except UnicodeDecodeError as error:
        raise LegacySourceError(f"Legacy {field_name} is not valid Windows-1254 text.") from error


def _normalize_text(value: object, field_name: str) -> str | None:
    decoded = _decode_text(value, field_name)
    if decoded is None:
        return None
    normalized = decoded.strip()
    return normalized or None


def _parse_date(value: object, field_name: str, *, required: bool) -> date | None:
    normalized = _normalize_text(value, field_name)
    if normalized is None:
        if required:
            raise LegacySourceError(f"Legacy {field_name} is required.")
        return None
    if DATE_PATTERN.fullmatch(normalized) is None:
        raise LegacySourceError(f"Legacy {field_name} is not a supported YYYY-MM-DD date.")
    try:
        return date.fromisoformat(normalized)
    except ValueError as error:
        raise LegacySourceError(f"Legacy {field_name} contains an invalid date.") from error


def _parse_time(value: object, field_name: str) -> time | None:
    normalized = _normalize_text(value, field_name)
    if normalized is None:
        return None
    if TIME_PATTERN.fullmatch(normalized) is None:
        raise LegacySourceError(f"Legacy {field_name} is not a supported HH:MM:SS time.")
    try:
        return time.fromisoformat(normalized)
    except ValueError as error:
        raise LegacySourceError(f"Legacy {field_name} contains an invalid time.") from error


def _parse_money_decimal(value: object, field_name: str) -> Decimal | None:
    if value is None:
        return None
    if type(value) is int:
        result = Decimal(value)
    elif type(value) is float:
        if not math.isfinite(value):
            raise LegacySourceError(f"Legacy {field_name} contains a non-finite amount.")
        result = Decimal(str(value))
    else:
        raise LegacySourceError(f"Legacy {field_name} does not use supported numeric storage.")
    if result != 0 and max(0, -result.normalize().as_tuple().exponent) > 2:
        raise LegacySourceError(f"Legacy {field_name} has more than two decimal places.")
    return result


def _money_to_kurus(value: Decimal, field_name: str) -> int:
    scaled = value * 100
    try:
        integral = scaled.to_integral_exact()
    except InvalidOperation as error:
        raise LegacySourceError(f"Legacy {field_name} cannot be converted exactly.") from error
    if scaled != integral:
        raise LegacySourceError(f"Legacy {field_name} cannot be converted exactly.")
    return int(integral)


def _validate_schema(
    connection: sqlite3.Connection,
    table: str,
    expected_columns: tuple[tuple[str, str, bool, bool], ...],
) -> None:
    rows = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    actual = []
    for row in rows:
        name = _decode_text(row[1], f"{table} column name")
        declared_type = _decode_text(row[2], f"{table}.{name} declared type")
        actual.append((name, (declared_type or "").upper(), bool(row[3]), bool(row[5])))
    if tuple(actual) != expected_columns:
        raise LegacySourceError(f"Legacy table {table} does not match the supported V1 schema.")


def _validate_text_encoding(connection: sqlite3.Connection) -> None:
    for table, columns in (
        ("CariKart", CARIKART_TEXT_COLUMNS),
        ("Data", DATA_TEXT_COLUMNS),
        ("ATemp", ("Aciklama",)),
    ):
        projection = ", ".join(f'"{column}"' for column in columns)
        for row in connection.execute(f'SELECT {projection} FROM "{table}"'):
            for column, value in zip(columns, row, strict=True):
                _decode_text(value, f"{table}.{column}")


def _is_empty_placeholder(row: sqlite3.Row, linked_data_rows: int) -> bool:
    if linked_data_rows != 0:
        return False
    if any(
        _normalize_text(row[field], f"CariKart.{field}") is not None
        for field in PLACEHOLDER_TEXT_COLUMNS
    ):
        return False
    return all(
        (value := _parse_money_decimal(row[field], f"CariKart.{field}")) is None or value == 0
        for field in PLACEHOLDER_MONEY_COLUMNS
    )


def _require_legacy_id(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise LegacySourceError(f"Legacy {field_name} must be an integer.")
    return value


def _read_database(database_path: Path, source_sha256: str) -> LegacyImportPlan:
    try:
        with database_path.open("rb") as stream:
            sqlite_magic = stream.read(16)
    except OSError as error:
        raise LegacySourceError("The selected legacy database could not be read safely.") from error
    if sqlite_magic != b"SQLite format 3\x00":
        raise LegacySourceError("The selected legacy database is not SQLite 3.")
    uri = f"{database_path.resolve().as_uri()}?mode=ro&immutable=1"
    try:
        with sqlite3.connect(uri, uri=True) as connection:
            connection.text_factory = bytes
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
            if [row[0] for row in integrity_rows] != [b"ok"]:
                raise LegacySourceError("The legacy database failed its integrity check.")
            _validate_schema(connection, "CariKart", CARIKART_COLUMNS)
            _validate_schema(connection, "Data", DATA_COLUMNS)
            _validate_schema(connection, "ATemp", ATEMP_COLUMNS)
            _validate_text_encoding(connection)
            return _read_rows(connection, source_sha256)
    except LegacySourceError:
        raise
    except sqlite3.Error as error:
        raise LegacySourceError("The legacy database could not be read safely.") from error


def _read_rows(connection: sqlite3.Connection, source_sha256: str) -> LegacyImportPlan:
    customer_rows = connection.execute("SELECT * FROM CariKart ORDER BY ID").fetchall()
    data_rows = connection.execute("SELECT * FROM Data ORDER BY ID").fetchall()
    source_customer_count = len(customer_rows)
    source_data_count = len(data_rows)

    customer_ids = [_require_legacy_id(row["ID"], "CariKart.ID") for row in customer_rows]
    transaction_ids = [_require_legacy_id(row["ID"], "Data.ID") for row in data_rows]
    if len(set(customer_ids)) != len(customer_ids):
        raise LegacySourceError("The legacy source contains duplicate customer IDs.")
    if len(set(transaction_ids)) != len(transaction_ids):
        raise LegacySourceError("The legacy source contains duplicate transaction IDs.")

    customer_id_set = set(customer_ids)
    linked_counts: Counter[int] = Counter()
    for row in data_rows:
        customer_id = _require_legacy_id(row["CariKartID"], "Data.CariKartID")
        if customer_id not in customer_id_set:
            raise LegacySourceError("The legacy source contains an orphan customer reference.")
        linked_counts[customer_id] += 1

    customers: list[LegacyCustomerRecord] = []
    skipped_placeholders = 0
    stored_summaries: dict[int, tuple[int | None, int | None, int | None]] = {}
    for row in customer_rows:
        legacy_id = _require_legacy_id(row["ID"], "CariKart.ID")
        full_name = _normalize_text(row["Unvan"], "CariKart.Unvan")
        if full_name is None:
            if _is_empty_placeholder(row, linked_counts[legacy_id]):
                skipped_placeholders += 1
                continue
            raise LegacySourceError("A nameless legacy customer contains meaningful data.")

        gsm = _normalize_text(row["Gsm"], "CariKart.Gsm")
        telephone = _normalize_text(row["Tel"], "CariKart.Tel")
        address_parts = [
            value
            for field in ("Adres", "ilce", "il")
            if (value := _normalize_text(row[field], f"CariKart.{field}")) is not None
        ]
        stored_summary_values: list[int | None] = []
        for field in ("Borc", "Alacak", "Bakiye"):
            value = _parse_money_decimal(row[field], f"CariKart.{field}")
            stored_summary_values.append(
                None if value is None else _money_to_kurus(value, f"CariKart.{field}")
            )
        stored_summaries[legacy_id] = tuple(stored_summary_values)
        customers.append(
            LegacyCustomerRecord(
                legacy_id=legacy_id,
                full_name=full_name,
                phone=gsm or telephone,
                address=", ".join(address_parts) or None,
                notes=_normalize_text(row["CNot"], "CariKart.CNot"),
                registered_on=_parse_date(row["Tarih"], "CariKart.Tarih", required=False),
            )
        )

    imported_customer_ids = {customer.legacy_id for customer in customers}
    transactions: list[LegacyTransactionRecord] = []
    skipped_zero = 0
    per_customer_values: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    transaction_dates: list[date] = []
    for row in data_rows:
        legacy_id = _require_legacy_id(row["ID"], "Data.ID")
        customer_legacy_id = _require_legacy_id(row["CariKartID"], "Data.CariKartID")
        if customer_legacy_id not in imported_customer_ids:
            raise LegacySourceError("A transaction references a skipped or unknown customer.")
        debt = _parse_money_decimal(row["Borc"], "Data.Borc") or Decimal(0)
        payment = _parse_money_decimal(row["Alacak"], "Data.Alacak") or Decimal(0)
        if debt < 0 or payment < 0:
            raise LegacySourceError("A legacy transaction contains a negative source side.")
        if debt > 0 and payment > 0:
            raise LegacySourceError("A legacy transaction contains both debt and payment.")
        if debt == 0 and payment == 0:
            skipped_zero += 1
            continue
        transaction_date = _parse_date(row["Tarih"], "Data.Tarih", required=True)
        assert transaction_date is not None
        transaction_time = _parse_time(row["Saat"], "Data.Saat")
        description = next(
            (
                value
                for field in ("Aciklama", "Tur", "Unvan")
                if (value := _normalize_text(row[field], f"Data.{field}")) is not None
            ),
            None,
        )
        if description is None:
            raise LegacySourceError("A legacy transaction has no usable description.")
        amount_kurus = (
            _money_to_kurus(debt, "Data.Borc")
            if debt > 0
            else -_money_to_kurus(payment, "Data.Alacak")
        )
        transactions.append(
            LegacyTransactionRecord(
                legacy_id=legacy_id,
                customer_legacy_id=customer_legacy_id,
                transaction_date=transaction_date,
                transaction_time=transaction_time,
                description=description,
                amount_kurus=amount_kurus,
            )
        )
        if amount_kurus > 0:
            per_customer_values[customer_legacy_id][0] += amount_kurus
        else:
            per_customer_values[customer_legacy_id][1] += -amount_kurus
        transaction_dates.append(transaction_date)

    per_customer = tuple(
        LegacyCustomerFinancialExpectation(
            customer_legacy_id=customer.legacy_id,
            debt_kurus=per_customer_values[customer.legacy_id][0],
            payment_kurus=per_customer_values[customer.legacy_id][1],
            signed_net_kurus=(
                per_customer_values[customer.legacy_id][0]
                - per_customer_values[customer.legacy_id][1]
            ),
        )
        for customer in customers
    )
    expected_by_id = {value.customer_legacy_id: value for value in per_customer}
    compared = 0
    matching = 0
    for customer_legacy_id, summary in stored_summaries.items():
        if any(value is None for value in summary):
            continue
        compared += 1
        expected = expected_by_id[customer_legacy_id]
        if summary == (
            expected.debt_kurus,
            expected.payment_kurus,
            expected.signed_net_kurus,
        ):
            matching += 1
    mismatching = compared - matching
    warnings = ()
    if mismatching:
        warnings = (
            "Bazı eski müşteri özetleri işlem geçmişiyle uyuşmuyor; işlem geçmişi esas alındı.",
        )

    total_debt = sum(value.debt_kurus for value in per_customer)
    total_payment = sum(value.payment_kurus for value in per_customer)
    preflight = LegacyImportPreflight(
        source_sha256=source_sha256,
        source_customer_count=source_customer_count,
        skipped_placeholder_customers=skipped_placeholders,
        eligible_customer_count=len(customers),
        source_data_count=source_data_count,
        skipped_zero_movement_transactions=skipped_zero,
        eligible_transaction_count=len(transactions),
        total_debt_kurus=total_debt,
        total_payment_kurus=total_payment,
        signed_net_kurus=total_debt - total_payment,
        earliest_transaction_date=min(transaction_dates, default=None),
        latest_transaction_date=max(transaction_dates, default=None),
        stored_summary_compared_customers=compared,
        stored_summary_matching_customers=matching,
        stored_summary_mismatching_customers=mismatching,
        warnings=warnings,
    )
    return LegacyImportPlan(
        source_sha256=source_sha256,
        customers=tuple(customers),
        transactions=tuple(transactions),
        per_customer=per_customer,
        preflight=preflight,
    )


def read_legacy_import_plan(source_path: Path) -> LegacyImportPlan:
    """Read and validate one supported EXA or advanced direct EDB source."""
    source = source_path.expanduser()
    if not source.is_file():
        raise LegacySourceError("The selected legacy source does not exist.")
    suffix = source.suffix.casefold()
    if suffix not in {".exa", ".edb"}:
        raise LegacySourceError("Select a supported Veresiye 5 .exa or .edb source.")
    digest_before = _source_digest(source)
    try:
        if suffix == ".exa":
            with tempfile.TemporaryDirectory(prefix="hesiva-legacy-import-") as directory:
                temporary_directory = Path(directory)
                temporary_directory.chmod(0o700)
                database_path = recover_frm1_database(source, temporary_directory)
                plan = _read_database(database_path, digest_before)
        else:
            plan = _read_database(source, digest_before)
    except ExaFormatError as error:
        raise LegacySourceError(str(error)) from error
    finally:
        if _source_digest(source) != digest_before:
            raise LegacySourceError("The legacy source changed while it was being read.")
    return plan
