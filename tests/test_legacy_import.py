import hashlib
import os
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import date, time
from pathlib import Path

import pytest
from sqlalchemy import func, select

from hesiva import data_limits
from hesiva.application import create_application_context
from hesiva.composition import ApplicationContext
from hesiva.financial_integrity import SQLITE_SIGNED_INTEGER_MAX
from hesiva.importers import exa as exa_module
from hesiva.importers import veresiye5_reader as reader_module
from hesiva.importers.exa import ExaFormatError, recover_frm1_database
from hesiva.importers.veresiye5_reader import LegacySourceError, read_legacy_import_plan
from hesiva.models import Customer, Transaction
from hesiva.repositories.legacy_import_repository import LegacyImportRepository
from hesiva.services import (
    LegacyImportDestinationNotEmptyError,
    LegacyImportError,
    LegacyImportSourceError,
)
from legacy_import_fixtures import (
    LegacyCustomerFixture,
    LegacyTransactionFixture,
    build_exa,
    create_default_source,
    create_legacy_edb,
)
import legacy_import_fixtures as fixture_module


@pytest.fixture
def application_context(tmp_path: Path) -> Iterator[ApplicationContext]:
    context = create_application_context(tmp_path / "destination")
    try:
        yield context
    finally:
        context.close()


def test_supported_exa_recovers_exact_frm1_without_changing_source(tmp_path: Path) -> None:
    source = create_default_source(tmp_path / "source.exa")
    source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    extraction = tmp_path / "private"
    extraction.mkdir(mode=0o700)

    recovered = recover_frm1_database(source, extraction)

    assert recovered.name == "Frm1.edb"
    assert recovered.read_bytes().startswith(b"SQLite format 3\x00")
    assert recovered.stat().st_mode & 0o777 == 0o600
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_digest
    assert not list(source.parent.glob("*.exa-wal"))
    assert not list(source.parent.glob("*.exa-shm"))
    assert not list(source.parent.glob("*.exa-journal"))


def test_oversized_exa_is_rejected_before_hashing_or_parsing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = create_default_source(tmp_path / "oversized.exa")
    monkeypatch.setattr(reader_module, "EXA_SOURCE_SIZE_LIMIT", source.stat().st_size - 1)

    def unexpected_operation(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("An oversized EXA must not be hashed or parsed.")

    monkeypatch.setattr(reader_module, "_source_digest", unexpected_operation)
    monkeypatch.setattr(reader_module, "recover_frm1_database", unexpected_operation)

    with pytest.raises(LegacySourceError, match="EXA source exceeds"):
        read_legacy_import_plan(source)


def test_exa_size_is_rechecked_before_the_final_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = create_default_source(tmp_path / "growing.exa")
    monkeypatch.setattr(reader_module, "EXA_SOURCE_SIZE_LIMIT", source.stat().st_size)
    real_read_database = reader_module._read_database
    real_source_digest = reader_module._source_digest
    digest_calls = 0

    def count_digest(path: Path, *, size_limit: int | None = None) -> str:
        nonlocal digest_calls
        digest_calls += 1
        return real_source_digest(path, size_limit=size_limit)

    def read_then_grow_source(database_path: Path, source_sha256: str):
        plan = real_read_database(database_path, source_sha256)
        with source.open("ab") as source_handle:
            source_handle.write(b"x")
        return plan

    monkeypatch.setattr(reader_module, "_source_digest", count_digest)
    monkeypatch.setattr(reader_module, "_read_database", read_then_grow_source)

    with pytest.raises(LegacySourceError, match="EXA source exceeds"):
        read_legacy_import_plan(source)

    assert digest_calls == 1


@pytest.mark.parametrize("kind", ["missing", "random", "truncated_header"])
def test_exa_rejects_missing_or_non_container_sources(kind: str, tmp_path: Path) -> None:
    source = tmp_path / "source.exa"
    if kind == "random":
        source.write_bytes(b"not an EXA container")
    elif kind == "truncated_header":
        source.write_bytes(b"\xba\x00\x00")
    extraction = tmp_path / "private"
    extraction.mkdir()

    with pytest.raises(ExaFormatError):
        recover_frm1_database(source, extraction)


def test_exa_rejects_invalid_file_list_and_missing_or_duplicate_frm1(tmp_path: Path) -> None:
    payload = b"SQLite format 3\x00synthetic"
    extraction = tmp_path / "private"
    extraction.mkdir()

    invalid_list = tmp_path / "invalid-list.exa"
    build_exa(
        invalid_list,
        ((b"C:\\Synthetic\\Frm1.edb", payload),),
        file_list_payload=b"unsupported listing",
    )
    with pytest.raises(ExaFormatError):
        recover_frm1_database(invalid_list, extraction)

    missing = tmp_path / "missing.exa"
    build_exa(missing, ((b"C:\\Synthetic\\Other.edb", payload),))
    with pytest.raises(ExaFormatError):
        recover_frm1_database(missing, extraction)

    duplicate = tmp_path / "duplicate.exa"
    build_exa(
        duplicate,
        (
            (b"C:\\First\\Frm1.edb", payload),
            (b"D:\\Second\\FRM1.EDB", payload),
        ),
    )
    with pytest.raises(ExaFormatError):
        recover_frm1_database(duplicate, extraction)
    assert not (extraction / "Frm1.edb").exists()


def test_exa_fdopen_failure_closes_descriptor_before_target_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = create_default_source(tmp_path / "fdopen-failure.exa")
    extraction = tmp_path / "private"
    extraction.mkdir()
    target = extraction / "Frm1.edb"
    real_open = os.open
    real_unlink = Path.unlink
    captured_descriptor: int | None = None
    descriptor_was_closed_before_unlink = False

    def capture_open(path: object, flags: int, mode: int = 0o777) -> int:
        nonlocal captured_descriptor
        descriptor = real_open(path, flags, mode)
        if Path(path) == target:
            captured_descriptor = descriptor
        return descriptor

    def fail_fdopen(_descriptor: int, _mode: str):
        raise OSError("synthetic fdopen failure")

    def observe_unlink(path: Path, *, missing_ok: bool = False) -> None:
        nonlocal descriptor_was_closed_before_unlink
        if path == target:
            assert captured_descriptor is not None
            with pytest.raises(OSError):
                os.fstat(captured_descriptor)
            descriptor_was_closed_before_unlink = True
        real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(exa_module.os, "open", capture_open)
    monkeypatch.setattr(exa_module.os, "fdopen", fail_fdopen)
    monkeypatch.setattr(Path, "unlink", observe_unlink)

    with pytest.raises(ExaFormatError, match="read safely"):
        recover_frm1_database(source, extraction)

    assert descriptor_was_closed_before_unlink
    assert not target.exists()


def test_exa_cleanup_failure_preserves_primary_format_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "invalid-trailing.exa"
    payload = b"SQLite format 3\x00synthetic"
    build_exa(
        source,
        ((b"C:\\Synthetic\\Frm1.edb", payload),),
        trailing=b"unexpected",
    )
    extraction = tmp_path / "private"
    extraction.mkdir()
    target = extraction / "Frm1.edb"
    real_unlink = Path.unlink

    def fail_target_unlink(path: Path, *, missing_ok: bool = False) -> None:
        if path == target:
            raise PermissionError("synthetic cleanup failure")
        real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fail_target_unlink)

    with pytest.raises(ExaFormatError, match="unexpected trailing") as captured:
        recover_frm1_database(source, extraction)

    assert any("PermissionError" in note for note in captured.value.__notes__)
    assert target.exists()


def test_exa_private_directory_cleanup_failure_cannot_be_reported_as_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = create_default_source(tmp_path / "cleanup-failure.exa")
    extraction = tmp_path / "private-cleanup-failure"

    class FailingTemporaryDirectory:
        def __init__(self, *, prefix: str) -> None:
            del prefix
            extraction.mkdir()
            self.name = str(extraction)

        def cleanup(self) -> None:
            raise PermissionError("synthetic private cleanup failure")

    monkeypatch.setattr(
        reader_module.tempfile,
        "TemporaryDirectory",
        FailingTemporaryDirectory,
    )

    with pytest.raises(LegacySourceError, match="Private legacy-import data"):
        read_legacy_import_plan(source)

    assert (extraction / "Frm1.edb").is_file()


@pytest.mark.parametrize(
    ("modifier", "build_options"),
    [
        (None, {"marker": b"BAD!"}),
        (None, {"flag": 1}),
        (None, {"declared_size_delta": 1}),
        (None, {"trailing": b"unexpected"}),
        ("truncate", {}),
        ("corrupt_zlib", {}),
    ],
)
def test_exa_rejects_bad_markers_flags_lengths_compression_and_trailing_data(
    modifier: str | None,
    build_options: dict[str, object],
    tmp_path: Path,
) -> None:
    source = tmp_path / "invalid.exa"
    payload = b"SQLite format 3\x00" + bytes(range(256)) * 8
    build_exa(source, ((b"C:\\Synthetic\\Frm1.edb", payload),), **build_options)
    if modifier == "truncate":
        source.write_bytes(source.read_bytes()[:-20])
    elif modifier == "corrupt_zlib":
        content = bytearray(source.read_bytes())
        first_zlib = content.index(b"\x78\x01")
        content[first_zlib + 2] ^= 0xFF
        source.write_bytes(content)
    extraction = tmp_path / "private"
    extraction.mkdir()

    with pytest.raises(ExaFormatError):
        recover_frm1_database(source, extraction)
    assert not (extraction / "Frm1.edb").exists()


def test_exa_rejects_aggregate_declared_member_size_before_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "aggregate-size.exa"
    payload = b"SQLite format 3\x00" + bytes(32)
    build_exa(
        source,
        (
            (b"C:\\Synthetic\\Frm1.edb", payload),
            (b"C:\\Synthetic\\Other.edb", payload),
        ),
    )
    extraction = tmp_path / "private"
    extraction.mkdir()
    monkeypatch.setattr(exa_module, "AGGREGATE_MEMBER_SIZE_LIMIT", len(payload) * 2 - 1)

    with pytest.raises(ExaFormatError, match="aggregate member-size"):
        recover_frm1_database(source, extraction)

    assert not (extraction / "Frm1.edb").exists()


def test_exa_rejects_pathological_declared_size_as_domain_error_without_source_change(
    tmp_path: Path,
) -> None:
    source = tmp_path / "pathological-declared-size.exa"
    payload = b"SQLite format 3\x00" + bytes(32)
    file_list = b"C:\\Synthetic\\Frm1.edb\t0=" + (b"9" * 5_000)
    build_exa(
        source,
        ((b"C:\\Synthetic\\Frm1.edb", payload),),
        file_list_payload=file_list,
    )
    source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    extraction = tmp_path / "private-pathological-size"
    extraction.mkdir()

    with pytest.raises(ExaFormatError, match="unsupported member size"):
        recover_frm1_database(source, extraction)
    with pytest.raises(LegacySourceError, match="unsupported member size"):
        read_legacy_import_plan(source)

    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_digest
    assert not (extraction / "Frm1.edb").exists()
    assert not list(source.parent.glob(f"{source.name}-*"))


def test_exa_rejects_a_single_record_that_expands_beyond_chunk_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "expanded-chunk.exa"
    payload = b"SQLite format 3\x00" + bytes(256)
    build_exa(
        source,
        ((b"C:\\Synthetic\\Frm1.edb", payload),),
        chunk_size=len(payload),
    )
    extraction = tmp_path / "private"
    extraction.mkdir()
    monkeypatch.setattr(exa_module, "DECOMPRESSED_CHUNK_LIMIT", len(payload) - 1)

    with pytest.raises(ExaFormatError, match="compressed record exceeds"):
        recover_frm1_database(source, extraction)

    assert not (extraction / "Frm1.edb").exists()


@pytest.mark.parametrize(
    ("limit_name", "limit", "message"),
    [
        ("AGGREGATE_COMPRESSED_SIZE_LIMIT", 1, "aggregate compressed-size"),
        ("COMPRESSED_RECORD_COUNT_LIMIT", 1, "too many compressed records"),
    ],
)
def test_exa_bounds_aggregate_compressed_input_and_record_count(
    limit_name: str,
    limit: int,
    message: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / f"{limit_name}.exa"
    payload = b"SQLite format 3\x00" + bytes(256)
    build_exa(source, ((b"C:\\Synthetic\\Frm1.edb", payload),), chunk_size=32)
    extraction = tmp_path / "private"
    extraction.mkdir()
    monkeypatch.setattr(exa_module, limit_name, limit)

    with pytest.raises(ExaFormatError, match=message):
        recover_frm1_database(source, extraction)

    assert not (extraction / "Frm1.edb").exists()


def test_preflight_maps_customers_transactions_cp1254_and_skip_policies(tmp_path: Path) -> None:
    source = create_default_source(tmp_path / "source.exa")

    plan = read_legacy_import_plan(source)

    assert plan.preflight.source_customer_count == 3
    assert plan.preflight.skipped_placeholder_customers == 1
    assert plan.preflight.eligible_customer_count == 2
    assert plan.preflight.source_data_count == 4
    assert plan.preflight.skipped_zero_movement_transactions == 1
    assert plan.preflight.eligible_transaction_count == 3
    assert plan.preflight.total_debt_kurus == 50_000
    assert plan.preflight.total_payment_kurus == 35_050
    assert plan.preflight.signed_net_kurus == 14_950
    assert plan.preflight.earliest_transaction_date == date(2024, 1, 1)
    assert plan.preflight.latest_transaction_date == date(2024, 2, 1)
    assert plan.preflight.stored_summary_matching_customers == 2
    assert plan.preflight.stored_summary_mismatching_customers == 0
    assert plan.customers[0].full_name == "Çağrı Şahin"
    assert plan.customers[0].phone == "0532 000 00 00"
    assert plan.customers[0].address == "Yol, Merkez, İzmir"
    assert plan.customers[0].notes == "Özel not"
    assert plan.customers[0].registered_on == date(2020, 1, 2)
    assert plan.customers[1].phone == "222"
    assert plan.customers[1].registered_on is None
    assert [record.legacy_id for record in plan.customers] == [42, 77]
    assert [record.amount_kurus for record in plan.transactions] == [50_000, -25_050, -10_000]
    assert plan.transactions[0].description == "İlaç & bakım"
    assert plan.transactions[0].transaction_time == time(9, 10, 11)
    assert plan.transactions[1].transaction_time is None


def test_direct_edb_is_read_immutable_and_creates_no_sqlite_sidecars(tmp_path: Path) -> None:
    source = create_default_source(tmp_path / "source.edb", as_exa=False)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    plan = read_legacy_import_plan(source)

    assert plan.preflight.eligible_customer_count == 2
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    assert not list(tmp_path.glob("source.edb-*"))


@pytest.mark.parametrize("sidecar_suffix", ["-wal", "-shm", "-journal"])
def test_direct_edb_rejects_preexisting_sqlite_sidecars(
    sidecar_suffix: str,
    tmp_path: Path,
) -> None:
    source = create_default_source(tmp_path / "source.edb", as_exa=False)
    sidecar = Path(f"{source}{sidecar_suffix}")
    sidecar.write_bytes(b"preserve this ambiguous sidecar")

    with pytest.raises(LegacySourceError, match="no SQLite sidecar"):
        read_legacy_import_plan(source)

    assert sidecar.read_bytes() == b"preserve this ambiguous sidecar"


def test_direct_edb_symlink_rejects_sidecars_next_to_resolved_database(tmp_path: Path) -> None:
    source = create_default_source(tmp_path / "source.edb", as_exa=False)
    alias = tmp_path / "alias.edb"
    try:
        alias.symlink_to(source)
    except OSError as error:
        pytest.skip(f"Symlinks are unavailable: {error}")
    Path(f"{source}-journal").write_bytes(b"ambiguous target sidecar")

    with pytest.raises(LegacySourceError, match="no SQLite sidecar"):
        read_legacy_import_plan(alias)


def test_direct_edb_rejects_hardlink_alias_that_can_hide_a_committed_wal(
    tmp_path: Path,
) -> None:
    source = create_default_source(tmp_path / "source.edb", as_exa=False)
    alias = tmp_path / "hardlink-alias.edb"
    try:
        os.link(source, alias)
    except OSError as error:
        pytest.skip(f"Hard links are unavailable: {error}")

    with closing(sqlite3.connect(source)) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute(
            "INSERT INTO ATemp (TurID, Aciklama) VALUES (?, CAST(? AS TEXT))",
            (2, sqlite3.Binary("WAL satırı".encode("cp1254"))),
        )
        writer.commit()
        assert Path(f"{source}-wal").is_file()
        assert not Path(f"{alias}-wal").exists()

        with pytest.raises(LegacySourceError, match="without hard-link aliases"):
            read_legacy_import_plan(alias)


def test_direct_edb_rejects_a_real_committed_wal_source(tmp_path: Path) -> None:
    source = create_default_source(tmp_path / "source.edb", as_exa=False)

    with closing(sqlite3.connect(source)) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute(
            "INSERT INTO ATemp (TurID, Aciklama) VALUES (?, CAST(? AS TEXT))",
            (2, sqlite3.Binary("WAL satırı".encode("cp1254"))),
        )
        writer.commit()
        assert Path(f"{source}-wal").is_file()

        with pytest.raises(LegacySourceError, match="no SQLite sidecar"):
            read_legacy_import_plan(source)


def test_direct_edb_rechecks_sidecars_after_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = create_default_source(tmp_path / "source.edb", as_exa=False)
    original_read_database = reader_module._read_database

    def read_then_create_sidecar(database_path: Path, source_sha256: str):
        plan = original_read_database(database_path, source_sha256)
        Path(f"{database_path}-journal").write_bytes(b"appeared during read")
        return plan

    monkeypatch.setattr(reader_module, "_read_database", read_then_create_sidecar)

    with pytest.raises(LegacySourceError, match="no SQLite sidecar"):
        read_legacy_import_plan(source)


def test_legacy_reader_explicitly_closes_connections_on_success_and_rejection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid = create_default_source(tmp_path / "valid.edb", as_exa=False)
    invalid = tmp_path / "invalid.edb"
    create_legacy_edb(
        invalid,
        customers=(),
        transactions=(),
        schema_override="CREATE TABLE CariKart (ID INTEGER PRIMARY KEY);",
    )
    real_connect = sqlite3.connect
    opened: list[sqlite3.Connection] = []
    closed: list[sqlite3.Connection] = []

    class TrackingConnection(sqlite3.Connection):
        def close(self) -> None:
            closed.append(self)
            super().close()

    def tracking_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        kwargs["factory"] = TrackingConnection
        connection = real_connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(reader_module.sqlite3, "connect", tracking_connect)

    read_legacy_import_plan(valid)
    with pytest.raises(LegacySourceError, match="schema"):
        read_legacy_import_plan(invalid)

    assert len(opened) == 2
    assert closed == opened


def test_legacy_fixture_explicitly_closes_its_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_connect = sqlite3.connect
    opened: list[sqlite3.Connection] = []
    closed: list[sqlite3.Connection] = []

    class TrackingConnection(sqlite3.Connection):
        def close(self) -> None:
            closed.append(self)
            super().close()

    def tracking_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        kwargs["factory"] = TrackingConnection
        connection = real_connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(fixture_module.sqlite3, "connect", tracking_connect)

    create_legacy_edb(
        tmp_path / "fixture.edb",
        customers=(LegacyCustomerFixture(1, "Müşteri"),),
        transactions=(),
    )

    assert len(opened) == 1
    assert closed == opened


def test_direct_edb_size_is_bounded_before_hashing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = create_default_source(tmp_path / "source.edb", as_exa=False)
    monkeypatch.setattr(reader_module, "LEGACY_DATABASE_SIZE_LIMIT", source.stat().st_size - 1)

    def unexpected_digest(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("An oversized direct database must not be hashed.")

    monkeypatch.setattr(reader_module, "_source_digest", unexpected_digest)

    with pytest.raises(LegacySourceError, match="size limit"):
        read_legacy_import_plan(source)


def test_legacy_database_row_count_is_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = create_default_source(tmp_path / "source.edb", as_exa=False)
    monkeypatch.setattr(reader_module, "LEGACY_ROW_COUNT_LIMIT", 7)

    with pytest.raises(LegacySourceError, match="row-count limit"):
        read_legacy_import_plan(source)


def test_legacy_text_cell_and_aggregate_sizes_are_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = create_default_source(tmp_path / "source.edb", as_exa=False)

    monkeypatch.setattr(reader_module, "LEGACY_TEXT_CELL_SIZE_LIMIT", 1)
    with pytest.raises(LegacySourceError, match="text value"):
        read_legacy_import_plan(source)

    monkeypatch.setattr(reader_module, "LEGACY_TEXT_CELL_SIZE_LIMIT", 16 * 1024 * 1024)
    monkeypatch.setattr(reader_module, "LEGACY_TEXT_AGGREGATE_SIZE_LIMIT", 1)
    with pytest.raises(LegacySourceError, match="aggregate supported size"):
        read_legacy_import_plan(source)


def test_sqlite_length_limit_rejects_oversized_legacy_text_before_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cell_limit = 4 * 1024
    source = tmp_path / "oversized-cell.edb"
    create_legacy_edb(
        source,
        customers=(LegacyCustomerFixture(1, "x" * (cell_limit * 2)),),
        transactions=(),
    )
    source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    real_consume = reader_module._TextBudget.consume

    def reject_materialized_oversized_value(
        budget: reader_module._TextBudget,
        value: object,
        field_name: str,
    ) -> None:
        if isinstance(value, bytes) and len(value) > cell_limit:
            raise AssertionError("oversized legacy text reached Python")
        real_consume(budget, value, field_name)

    monkeypatch.setattr(reader_module, "LEGACY_TEXT_CELL_SIZE_LIMIT", cell_limit)
    monkeypatch.setattr(
        reader_module._TextBudget,
        "consume",
        reject_materialized_oversized_value,
    )

    with pytest.raises(LegacySourceError, match="text value exceeds"):
        read_legacy_import_plan(source)

    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_digest
    assert not list(source.parent.glob(f"{source.name}-*"))


@pytest.mark.parametrize(
    "mapped_field",
    ("full_name", "phone", "address", "notes", "transaction_description"),
)
def test_legacy_mapped_text_obeys_destination_utf8_limit_before_import(
    mapped_field: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    customer_values: dict[str, object] = {"legacy_id": 1, "full_name": "Ali"}
    transactions: tuple[LegacyTransactionFixture, ...] = ()
    if mapped_field == "full_name":
        customer_values["full_name"] = "xxxxx"
    elif mapped_field == "phone":
        customer_values["gsm"] = "xxxxx"
    elif mapped_field == "address":
        customer_values["address"] = "ab"
        customer_values["district"] = "cd"
    elif mapped_field == "notes":
        customer_values["notes"] = "xxxxx"
    else:
        transactions = (
            LegacyTransactionFixture(
                legacy_id=1,
                customer_legacy_id=1,
                transaction_date="2026-08-13",
                transaction_time=None,
                description="xxxxx",
                debt=1,
                payment=0,
            ),
        )
    source = tmp_path / f"mapped-{mapped_field}.edb"
    create_legacy_edb(
        source,
        customers=(LegacyCustomerFixture(**customer_values),),
        transactions=transactions,
    )
    monkeypatch.setattr(data_limits, "PERSISTED_USER_TEXT_MAX_BYTES", 4)

    with pytest.raises(LegacySourceError, match="UTF-8 text size limit"):
        read_legacy_import_plan(source)


def test_final_source_recheck_does_not_mask_primary_reader_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "invalid.edb"
    create_legacy_edb(
        source,
        customers=(),
        transactions=(),
        schema_override="CREATE TABLE CariKart (ID INTEGER PRIMARY KEY);",
    )
    original_digest = reader_module._source_digest
    digest_calls = 0

    def fail_final_digest(path: Path, *, size_limit: int | None = None) -> str:
        nonlocal digest_calls
        digest_calls += 1
        if digest_calls == 2:
            raise LegacySourceError("synthetic final source recheck failure")
        return original_digest(path, size_limit=size_limit)

    monkeypatch.setattr(reader_module, "_source_digest", fail_final_digest)

    with pytest.raises(LegacySourceError, match="schema"):
        read_legacy_import_plan(source)

    assert digest_calls == 2


def test_final_source_recheck_failure_remains_blocking_after_successful_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = create_default_source(tmp_path / "source.edb", as_exa=False)
    original_digest = reader_module._source_digest
    digest_calls = 0

    def fail_final_digest(path: Path, *, size_limit: int | None = None) -> str:
        nonlocal digest_calls
        digest_calls += 1
        if digest_calls == 2:
            raise LegacySourceError("synthetic final source recheck failure")
        return original_digest(path, size_limit=size_limit)

    monkeypatch.setattr(reader_module, "_source_digest", fail_final_digest)

    with pytest.raises(LegacySourceError, match="final source recheck failure"):
        read_legacy_import_plan(source)

    assert digest_calls == 2


def test_all_turkish_cp1254_letters_round_trip_to_destination_unicode(
    application_context: ApplicationContext,
    tmp_path: Path,
) -> None:
    turkish_text = "Çç Ğğ İı Öö Şş Üü"
    source = tmp_path / "turkish.edb"
    create_legacy_edb(
        source,
        customers=(
            LegacyCustomerFixture(
                10,
                turkish_text,
                gsm=turkish_text,
                address=turkish_text,
                notes=turkish_text,
                debt=12.34,
                balance=12.34,
            ),
        ),
        transactions=(
            LegacyTransactionFixture(
                20,
                10,
                "2024-01-01",
                "12:34:56",
                turkish_text,
                12.34,
                None,
            ),
        ),
    )

    with application_context.services() as services:
        preflight = services.legacy_import.preflight(source)
        services.legacy_import.import_source(
            source,
            expected_source_sha256=preflight.source_sha256,
        )

    with application_context.session_factory() as session:
        customer = session.scalar(select(Customer))
        transaction = session.scalar(select(Transaction))
        assert customer is not None
        assert transaction is not None
        assert (customer.full_name, customer.phone, customer.address, customer.notes) == (
            turkish_text,
            turkish_text,
            turkish_text,
            turkish_text,
        )
        assert transaction.description == turkish_text


def test_customer_phone_address_and_optional_date_mapping_variants(tmp_path: Path) -> None:
    source = tmp_path / "mapping.edb"
    create_legacy_edb(
        source,
        customers=(
            LegacyCustomerFixture(
                1,
                "GSM",
                gsm=" 555 ",
                telephone="111",
                district=" İlçe ",
                province=" İl ",
            ),
            LegacyCustomerFixture(
                2,
                "Telefon",
                registered_on=None,
                telephone=" 222 ",
                address=" Adres ",
                province=" İl ",
            ),
            LegacyCustomerFixture(3, "İletişimsiz", registered_on=None),
        ),
        transactions=(),
    )

    plan = read_legacy_import_plan(source)

    assert [record.phone for record in plan.customers] == ["555", "222", None]
    assert [record.address for record in plan.customers] == [
        "İlçe, İl",
        "Adres, İl",
        None,
    ]
    assert plan.customers[1].registered_on is None


@pytest.mark.parametrize(
    ("debt", "payment", "expected_kurus"),
    [
        (7, None, 700),
        (7.5, None, 750),
        (7.25, None, 725),
        (None, 7, -700),
        (None, 7.5, -750),
        (None, 7.25, -725),
    ],
)
def test_supported_integer_and_real_money_converts_exactly_to_kurus(
    debt: int | float | None,
    payment: int | float | None,
    expected_kurus: int,
    tmp_path: Path,
) -> None:
    source = tmp_path / "money.edb"
    magnitude = abs(expected_kurus) / 100
    create_legacy_edb(
        source,
        customers=(
            LegacyCustomerFixture(
                1,
                "Müşteri",
                debt=magnitude if expected_kurus > 0 else 0,
                payment=magnitude if expected_kurus < 0 else 0,
                balance=magnitude if expected_kurus > 0 else -magnitude,
            ),
        ),
        transactions=(LegacyTransactionFixture(1, 1, "2024-01-01", None, "İşlem", debt, payment),),
    )

    plan = read_legacy_import_plan(source)

    assert plan.transactions[0].amount_kurus == expected_kurus


@pytest.mark.parametrize(
    ("debt", "payment"),
    [
        (SQLITE_SIGNED_INTEGER_MAX // 100 + 1, None),
        (None, SQLITE_SIGNED_INTEGER_MAX // 100 + 1),
    ],
)
def test_legacy_preflight_rejects_individual_amount_outside_exact_kurus_range(
    debt: int | None,
    payment: int | None,
    tmp_path: Path,
) -> None:
    source = tmp_path / "individual-overflow.edb"
    create_legacy_edb(
        source,
        customers=(LegacyCustomerFixture(1, "Müşteri"),),
        transactions=(
            LegacyTransactionFixture(
                1,
                1,
                "2024-01-01",
                None,
                "İşlem",
                debt,
                payment,
            ),
        ),
    )

    with pytest.raises(LegacySourceError, match="outside the supported exact financial range"):
        read_legacy_import_plan(source)


@pytest.mark.parametrize("side", ["debt", "payment"])
def test_legacy_preflight_rejects_cumulative_same_side_overflow(
    side: str,
    tmp_path: Path,
) -> None:
    source = tmp_path / f"aggregate-{side}-overflow.edb"
    nearly_maximum_lira = SQLITE_SIGNED_INTEGER_MAX // 100

    def movement(
        legacy_id: int,
        magnitude_lira: int,
    ) -> LegacyTransactionFixture:
        return LegacyTransactionFixture(
            legacy_id,
            1,
            "2024-01-01",
            None,
            "İşlem",
            magnitude_lira if side == "debt" else None,
            magnitude_lira if side == "payment" else None,
        )

    create_legacy_edb(
        source,
        customers=(LegacyCustomerFixture(1, "Müşteri"),),
        transactions=(movement(1, nearly_maximum_lira), movement(2, 1)),
    )

    with pytest.raises(LegacySourceError, match="active financial totals exceed"):
        read_legacy_import_plan(source)


def test_zero_movement_row_skips_without_inventing_required_financial_fields(
    tmp_path: Path,
) -> None:
    source = tmp_path / "zero.edb"
    create_legacy_edb(
        source,
        customers=(LegacyCustomerFixture(1, "Müşteri"),),
        transactions=(LegacyTransactionFixture(1, 1, None, None, None, None, None, None, None),),
    )

    plan = read_legacy_import_plan(source)

    assert plan.transactions == ()
    assert plan.preflight.skipped_zero_movement_transactions == 1


def test_description_precedence_uses_aciklama_then_tur_then_unvan(tmp_path: Path) -> None:
    source = tmp_path / "source.edb"
    create_legacy_edb(
        source,
        customers=(LegacyCustomerFixture(1, "Müşteri", debt=3, payment=0, balance=3),),
        transactions=(
            LegacyTransactionFixture(1, 1, "2024-01-01", None, " Açıklama ", 1, None),
            LegacyTransactionFixture(
                2,
                1,
                "2024-01-02",
                "01:02:03",
                " ",
                1,
                None,
                transaction_type=" Tür ",
            ),
            LegacyTransactionFixture(
                3,
                1,
                "2024-01-03",
                "04:05:06",
                None,
                1,
                None,
                transaction_type=" ",
                customer_title=" Ünvan ",
            ),
        ),
    )

    plan = read_legacy_import_plan(source)

    assert [record.description for record in plan.transactions] == ["Açıklama", "Tür", "Ünvan"]


def test_invalid_cp1254_and_blank_description_are_blocking(tmp_path: Path) -> None:
    invalid_encoding = tmp_path / "encoding.edb"
    create_legacy_edb(
        invalid_encoding,
        customers=(LegacyCustomerFixture(1, b"\x81"),),
        transactions=(),
    )
    with pytest.raises(LegacySourceError, match="Windows-1254"):
        read_legacy_import_plan(invalid_encoding)

    blank_description = tmp_path / "description.edb"
    create_legacy_edb(
        blank_description,
        customers=(LegacyCustomerFixture(1, "Müşteri", debt=1, balance=1),),
        transactions=(
            LegacyTransactionFixture(1, 1, "2024-01-01", None, None, 1, None, None, None),
        ),
    )
    with pytest.raises(LegacySourceError, match="description"):
        read_legacy_import_plan(blank_description)


@pytest.mark.parametrize(
    ("transaction_date", "transaction_time"),
    [
        ("01.01.2024", "01:02:03"),
        ("2024-01-01", "1:02:03"),
        ("2024-02-30", "01:02:03"),
        ("2024-01-01", "25:00:00"),
    ],
)
def test_dates_and_times_are_strict(
    transaction_date: str,
    transaction_time: str,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.edb"
    create_legacy_edb(
        source,
        customers=(LegacyCustomerFixture(1, "Müşteri", debt=1, balance=1),),
        transactions=(
            LegacyTransactionFixture(
                1,
                1,
                transaction_date,
                transaction_time,
                "İşlem",
                1,
                None,
            ),
        ),
    )

    with pytest.raises(LegacySourceError):
        read_legacy_import_plan(source)


@pytest.mark.parametrize(
    ("debt", "payment"),
    [
        (1.001, None),
        (1, 1),
        (-1, None),
        (None, -1),
        ("1,00", None),
    ],
)
def test_ambiguous_or_unsupported_money_is_blocking(
    debt: object,
    payment: object,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.edb"
    create_legacy_edb(
        source,
        customers=(LegacyCustomerFixture(1, "Müşteri", debt=0, payment=0, balance=0),),
        transactions=(LegacyTransactionFixture(1, 1, "2024-01-01", None, "İşlem", debt, payment),),
    )

    with pytest.raises(LegacySourceError):
        read_legacy_import_plan(source)


def test_nameless_meaningful_or_referenced_customer_is_blocking(tmp_path: Path) -> None:
    meaningful = tmp_path / "meaningful.edb"
    create_legacy_edb(
        meaningful,
        customers=(LegacyCustomerFixture(1, None, extra_field="Kod"),),
        transactions=(),
    )
    with pytest.raises(LegacySourceError, match="nameless"):
        read_legacy_import_plan(meaningful)

    referenced = tmp_path / "referenced.edb"
    create_legacy_edb(
        referenced,
        customers=(LegacyCustomerFixture(1, None),),
        transactions=(LegacyTransactionFixture(1, 1, "2024-01-01", None, "İşlem", 1, None),),
    )
    with pytest.raises(LegacySourceError, match="nameless"):
        read_legacy_import_plan(referenced)


@pytest.mark.parametrize("customer_id", [None, 999])
def test_null_or_orphan_customer_reference_is_blocking(
    customer_id: int | None,
    tmp_path: Path,
) -> None:
    source = tmp_path / "reference.edb"
    create_legacy_edb(
        source,
        customers=(LegacyCustomerFixture(1, "Müşteri"),),
        transactions=(
            LegacyTransactionFixture(1, customer_id, "2024-01-01", None, "İşlem", 1, None),
        ),
    )

    with pytest.raises(LegacySourceError):
        read_legacy_import_plan(source)


def test_missing_or_changed_required_schema_is_blocking(tmp_path: Path) -> None:
    source = tmp_path / "schema.edb"
    create_legacy_edb(
        source,
        customers=(),
        transactions=(),
        schema_override="CREATE TABLE CariKart (ID INTEGER PRIMARY KEY);",
    )

    with pytest.raises(LegacySourceError, match="schema"):
        read_legacy_import_plan(source)


def test_stored_summary_mismatch_is_warning_and_transaction_history_remains_truth(
    application_context: ApplicationContext,
    tmp_path: Path,
) -> None:
    source = tmp_path / "mismatch.edb"
    create_legacy_edb(
        source,
        customers=(
            LegacyCustomerFixture(
                5,
                "Müşteri",
                last_transaction_date="2099-12-31",
                debt=999,
                payment=0,
                balance=999,
            ),
        ),
        transactions=(LegacyTransactionFixture(8, 5, "2024-03-04", "05:06:07", "Borç", 10, None),),
    )

    with application_context.services() as services:
        preflight = services.legacy_import.preflight(source)
        assert preflight.stored_summary_compared_customers == 1
        assert preflight.stored_summary_matching_customers == 0
        assert preflight.stored_summary_mismatching_customers == 1
        assert len(preflight.warnings) == 1
        services.legacy_import.import_source(
            source,
            expected_source_sha256=preflight.source_sha256,
        )
    with application_context.services() as services:
        summary = services.customer_summary.list_customer_summaries()[0]
        assert summary.balance_kurus == 1_000
        assert summary.last_transaction_date == date(2024, 3, 4)
        assert summary.last_transaction_time == time(5, 6, 7)


def test_atomic_import_preserves_mapping_and_existing_hesiva_behavior(
    application_context: ApplicationContext,
    tmp_path: Path,
) -> None:
    source = create_default_source(tmp_path / "source.exa")
    source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    with application_context.services() as services:
        preflight = services.legacy_import.preflight(source)
    progress_phases: list[str] = []
    with application_context.services() as services:
        result = services.legacy_import.import_source(
            source,
            expected_source_sha256=preflight.source_sha256,
            progress=progress_phases.append,
        )

    assert result.imported_customer_count == 2
    assert result.imported_transaction_count == 3
    assert result.skipped_placeholder_customers == 1
    assert result.skipped_zero_movement_transactions == 1
    assert progress_phases == ["customers", "transactions", "verification"]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_digest
    with application_context.services() as services:
        summaries = services.customer_summary.list_customer_summaries()
        imported = services.customer.get_customer(summaries[0].customer_id)
        history = services.account_history.list_for_customer(imported.id)
        assert imported.legacy_id in {42, 77}
        assert imported.id != imported.legacy_id
        assert all(row.amount_kurus != 0 for row in history)
        assert all(row.animal_id is None for row in history)
    with application_context.session_factory() as session:
        customers = list(session.scalars(select(Customer).order_by(Customer.legacy_id)))
        transactions = list(session.scalars(select(Transaction).order_by(Transaction.legacy_id)))
        assert [customer.legacy_id for customer in customers] == [42, 77]
        assert [transaction.legacy_id for transaction in transactions] == [100, 101, 103]
        assert all(transaction.note is None for transaction in transactions)
        assert all(transaction.animal_id is None for transaction in transactions)


def test_imported_transactions_feed_existing_statement_monthly_and_yearly_reports(
    application_context: ApplicationContext,
    tmp_path: Path,
) -> None:
    source = create_default_source(tmp_path / "source.exa")
    with application_context.services() as services:
        preflight = services.legacy_import.preflight(source)
        services.legacy_import.import_source(
            source,
            expected_source_sha256=preflight.source_sha256,
        )
    with application_context.session_factory() as session:
        customer_id = session.scalar(select(Customer.id).where(Customer.legacy_id == 42))
    assert customer_id is not None
    with application_context.services() as services:
        statement = services.report.get_customer_statement(
            customer_id,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
        )
        monthly = services.report.get_monthly_summary(year=2024, month=1)
        yearly = services.report.get_yearly_summary(year=2024)
    assert (statement.total_debt_kurus, statement.total_payment_kurus) == (50_000, 25_050)
    assert (monthly.debt_kurus, monthly.payment_kurus, monthly.net_kurus) == (
        50_000,
        25_050,
        24_950,
    )
    assert (yearly.debt_kurus, yearly.payment_kurus, yearly.net_kurus) == (
        50_000,
        35_050,
        14_950,
    )


@pytest.mark.parametrize("business_kind", ["customer", "animal", "transaction", "reminder"])
def test_nonempty_destination_is_rejected_without_changes(
    business_kind: str,
    application_context: ApplicationContext,
    tmp_path: Path,
) -> None:
    source = create_default_source(tmp_path / "source.exa")
    with application_context.services() as services:
        customer = services.customer.create_customer("Existing")
        if business_kind == "animal":
            services.animal.create_animal(customer.id, name="Existing")
        elif business_kind == "transaction":
            services.transaction.create_debt(
                customer.id,
                transaction_date=date(2024, 1, 1),
                description="Existing",
                amount_kurus=100,
            )
        elif business_kind == "reminder":
            services.reminder.create_reminder(customer.id, date(2024, 1, 1), "Existing")

    with application_context.services() as services:
        with pytest.raises(LegacyImportDestinationNotEmptyError):
            services.legacy_import.preflight(source)
    with application_context.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Customer)) == 1


def test_insert_failure_rolls_back_every_legacy_record(
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = create_default_source(tmp_path / "source.exa")
    with application_context.services() as services:
        preflight = services.legacy_import.preflight(source)

    def fail_transactions(
        _repository: LegacyImportRepository,
        _rows: object,
    ) -> None:
        raise RuntimeError("synthetic insert failure")

    monkeypatch.setattr(LegacyImportRepository, "add_transactions", fail_transactions)
    with application_context.services() as services:
        with pytest.raises(LegacyImportError):
            services.legacy_import.import_source(
                source,
                expected_source_sha256=preflight.source_sha256,
            )

    with application_context.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Customer)) == 0
        assert session.scalar(select(func.count()).select_from(Transaction)) == 0


def test_customer_insert_failure_rolls_back_flushed_legacy_rows(
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = create_default_source(tmp_path / "source.exa")
    with application_context.services() as services:
        preflight = services.legacy_import.preflight(source)
    original_add_customers = LegacyImportRepository.add_customers

    def fail_after_customer_flush(
        repository: LegacyImportRepository,
        customers: object,
    ) -> dict[int, int]:
        original_add_customers(repository, customers)  # type: ignore[arg-type]
        raise RuntimeError("synthetic customer insert failure")

    monkeypatch.setattr(LegacyImportRepository, "add_customers", fail_after_customer_flush)
    with application_context.services() as services:
        with pytest.raises(LegacyImportError):
            services.legacy_import.import_source(
                source,
                expected_source_sha256=preflight.source_sha256,
            )

    with application_context.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Customer)) == 0
        assert session.scalar(select(func.count()).select_from(Transaction)) == 0


def test_verification_failure_rolls_back_all_inserted_legacy_rows(
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = create_default_source(tmp_path / "source.exa")
    with application_context.services() as services:
        preflight = services.legacy_import.preflight(source)

    def fail_verification(_repository: LegacyImportRepository) -> object:
        raise RuntimeError("synthetic verification failure")

    monkeypatch.setattr(LegacyImportRepository, "destination_snapshot", fail_verification)
    with application_context.services() as services:
        with pytest.raises(LegacyImportError):
            services.legacy_import.import_source(
                source,
                expected_source_sha256=preflight.source_sha256,
            )

    with application_context.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Customer)) == 0
        assert session.scalar(select(func.count()).select_from(Transaction)) == 0


def test_preflight_failure_writes_nothing_to_destination(
    application_context: ApplicationContext,
    tmp_path: Path,
) -> None:
    source = tmp_path / "invalid.exa"
    source.write_bytes(b"invalid")

    with application_context.services() as services:
        with pytest.raises(LegacyImportSourceError):
            services.legacy_import.preflight(source)

    with application_context.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Customer)) == 0
        assert session.scalar(select(func.count()).select_from(Transaction)) == 0


def test_source_change_between_preflight_and_import_is_rejected(
    application_context: ApplicationContext,
    tmp_path: Path,
) -> None:
    source = create_default_source(tmp_path / "source.exa")
    with application_context.services() as services:
        preflight = services.legacy_import.preflight(source)

    with application_context.services() as services:
        with pytest.raises(LegacyImportSourceError, match="değişti"):
            services.legacy_import.import_source(
                source,
                expected_source_sha256="0" * len(preflight.source_sha256),
            )

    with application_context.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Customer)) == 0
