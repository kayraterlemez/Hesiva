import sqlite3
import struct
import zlib
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class LegacyCustomerFixture:
    legacy_id: int
    full_name: str | bytes | None
    registered_on: str | bytes | None = "2020-01-02"
    gsm: str | bytes | None = None
    telephone: str | bytes | None = None
    address: str | bytes | None = None
    district: str | bytes | None = None
    province: str | bytes | None = None
    notes: str | bytes | None = None
    last_transaction_date: str | bytes | None = None
    debt: int | float | None = 0
    payment: int | float | None = 0
    balance: int | float | None = 0
    extra_field: str | bytes | None = None


@dataclass(frozen=True, slots=True)
class LegacyTransactionFixture:
    legacy_id: int
    customer_legacy_id: int | None
    transaction_date: str | bytes | None
    transaction_time: str | bytes | None
    description: str | bytes | None
    debt: int | float | None
    payment: int | float | None
    transaction_type: str | bytes | None = "İşlem"
    customer_title: str | bytes | None = "Müşteri"


def _encoded(value: str | bytes | None) -> sqlite3.Binary | None:
    if value is None:
        return None
    raw = value if isinstance(value, bytes) else value.encode("cp1254")
    return sqlite3.Binary(raw)


def create_legacy_edb(
    path: Path,
    *,
    customers: tuple[LegacyCustomerFixture, ...],
    transactions: tuple[LegacyTransactionFixture, ...],
    schema_override: str | None = None,
) -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
        if schema_override is not None:
            connection.executescript(schema_override)
            return
        connection.executescript(
            """
            CREATE TABLE CariKart (
                ID integer PRIMARY KEY AUTOINCREMENT NOT NULL,
                Tarih date,
                Kod char(25),
                Unvan char(100),
                Yetkili char(100),
                Gsm char(25),
                Tel char(25),
                Fax char(25),
                Adres char(250),
                il char(50),
                ilce char(50),
                VergiDaire char(25),
                VergiNo char(25),
                EPosta char(100),
                Web char(100),
                CLimit Money,
                Hesap char(5),
                CNot text,
                STarih date,
                Borc Money,
                Alacak Money,
                Bakiye Money
            );
            CREATE TABLE Data (
                ID integer PRIMARY KEY AUTOINCREMENT NOT NULL,
                Tarih date,
                Saat time,
                Tur char(25),
                Unvan char(100),
                Aciklama char(250),
                Borc Money,
                Alacak Money,
                CariKartID integer
            );
            CREATE TABLE ATemp (
                ID integer PRIMARY KEY AUTOINCREMENT NOT NULL,
                TurID integer,
                Aciklama char(250)
            );
            """
        )
        customer_sql = """
            INSERT INTO CariKart (
                ID, Tarih, Kod, Unvan, Yetkili, Gsm, Tel, Fax, Adres, il, ilce,
                VergiDaire, VergiNo, EPosta, Web, CLimit, Hesap, CNot, STarih,
                Borc, Alacak, Bakiye
            ) VALUES (
                ?, CAST(? AS TEXT), CAST(? AS TEXT), CAST(? AS TEXT), CAST(? AS TEXT),
                CAST(? AS TEXT), CAST(? AS TEXT), CAST(? AS TEXT), CAST(? AS TEXT),
                CAST(? AS TEXT), CAST(? AS TEXT), CAST(? AS TEXT), CAST(? AS TEXT),
                CAST(? AS TEXT), CAST(? AS TEXT), ?, CAST(? AS TEXT), CAST(? AS TEXT),
                CAST(? AS TEXT), ?, ?, ?
            )
        """
        for customer in customers:
            connection.execute(
                customer_sql,
                (
                    customer.legacy_id,
                    _encoded(customer.registered_on),
                    _encoded(customer.extra_field),
                    _encoded(customer.full_name),
                    None,
                    _encoded(customer.gsm),
                    _encoded(customer.telephone),
                    None,
                    _encoded(customer.address),
                    _encoded(customer.province),
                    _encoded(customer.district),
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    _encoded(customer.notes),
                    _encoded(customer.last_transaction_date),
                    customer.debt,
                    customer.payment,
                    customer.balance,
                ),
            )
        transaction_sql = """
            INSERT INTO Data (
                ID, Tarih, Saat, Tur, Unvan, Aciklama, Borc, Alacak, CariKartID
            ) VALUES (
                ?, CAST(? AS TEXT), CAST(? AS TEXT), CAST(? AS TEXT),
                CAST(? AS TEXT), CAST(? AS TEXT), ?, ?, ?
            )
        """
        for transaction in transactions:
            connection.execute(
                transaction_sql,
                (
                    transaction.legacy_id,
                    _encoded(transaction.transaction_date),
                    _encoded(transaction.transaction_time),
                    _encoded(transaction.transaction_type),
                    _encoded(transaction.customer_title),
                    _encoded(transaction.description),
                    transaction.debt,
                    transaction.payment,
                    transaction.customer_legacy_id,
                ),
            )
        connection.execute(
            "INSERT INTO ATemp (TurID, Aciklama) VALUES (?, CAST(? AS TEXT))",
            (1, _encoded("Sentetik açıklama")),
        )


def build_exa(
    path: Path,
    members: tuple[tuple[bytes, bytes], ...],
    *,
    marker: bytes = b"XEC2",
    flag: int = 0,
    footer: bytes = bytes(8),
    trailing: bytes = b"",
    file_list_payload: bytes | None = None,
    declared_size_delta: int = 0,
    chunk_size: int = 97,
) -> None:
    header = (
        "EXABilişim Yedek Dosyası\r\nProgram Adı = Veresiye 5\r\nSentetik test yedeği"
    ).encode("cp1254")
    listed = file_list_payload
    if listed is None:
        listed = b"\r\n".join(
            path_bytes
            + b"\t"
            + str(index).encode("ascii")
            + b"="
            + str(len(payload) + declared_size_delta).encode("ascii")
            for index, (path_bytes, payload) in enumerate(members)
        )
    output = bytearray()
    output.extend(struct.pack("<I", len(header)))
    output.extend(header)
    output.extend(struct.pack("<I", 0))
    output.extend(struct.pack("<I", len(members)))
    output.extend(struct.pack("<I", len(b"FILE:LIST")))
    output.extend(b"FILE:LIST")
    output.extend(bytes(3))
    output.extend(marker)
    output.extend(bytes((flag,)))
    compressed_list = zlib.compress(listed, level=1)
    output.extend(struct.pack("<I", len(compressed_list)))
    output.extend(compressed_list)
    for path_bytes, payload in members:
        output.extend(struct.pack("<I", 0))
        output.extend(struct.pack("<I", len(path_bytes)))
        output.extend(path_bytes)
        output.extend(bytes(3))
        output.extend(marker)
        output.extend(bytes((flag,)))
        for start in range(0, len(payload), chunk_size):
            compressed = zlib.compress(payload[start : start + chunk_size], level=1)
            output.extend(struct.pack("<I", len(compressed)))
            output.extend(compressed)
    output.extend(footer)
    output.extend(trailing)
    path.write_bytes(output)


def create_default_source(path: Path, *, as_exa: bool = True) -> Path:
    edb_path = path.with_suffix(".edb") if as_exa else path
    create_legacy_edb(
        edb_path,
        customers=(
            LegacyCustomerFixture(
                legacy_id=42,
                full_name="Çağrı Şahin",
                gsm=" 0532 000 00 00 ",
                telephone="111",
                address=" Yol ",
                district=" Merkez ",
                province=" İzmir ",
                notes=" Özel not ",
                debt=500,
                payment=250.5,
                balance=249.5,
            ),
            LegacyCustomerFixture(
                legacy_id=77,
                full_name="Çağrı Şahin",
                registered_on=None,
                telephone="222",
                debt=0,
                payment=100,
                balance=-100,
            ),
            LegacyCustomerFixture(
                legacy_id=99,
                full_name=None,
                registered_on=None,
                debt=0,
                payment=0,
                balance=0,
            ),
        ),
        transactions=(
            LegacyTransactionFixture(
                100,
                42,
                "2024-01-01",
                "09:10:11",
                "İlaç & bakım",
                500,
                None,
            ),
            LegacyTransactionFixture(
                101,
                42,
                "2024-01-02",
                None,
                "Tahsilat",
                None,
                250.5,
            ),
            LegacyTransactionFixture(
                102,
                42,
                "2024-01-03",
                "10:11:12",
                None,
                0,
                None,
                transaction_type="Sıfır kayıt",
            ),
            LegacyTransactionFixture(
                103,
                77,
                "2024-02-01",
                "11:12:13",
                "Ödeme",
                None,
                100,
            ),
        ),
    )
    if not as_exa:
        return edb_path
    build_exa(path, ((b"C:\\Synthetic\\Frm1.edb", edb_path.read_bytes()),))
    edb_path.unlink()
    return path
