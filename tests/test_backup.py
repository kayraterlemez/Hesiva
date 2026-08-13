import hashlib
import inspect
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from alembic import command
from argon2 import PasswordHasher
from argon2.low_level import Type

import hesiva.services.backup_service as backup_service_module
from hesiva import data_limits
from hesiva.application import ApplicationStartupError, create_application_context
from hesiva.composition import ApplicationContext
from hesiva.database.startup import (
    DatabaseState,
    create_alembic_config,
    get_migration_head,
    initialize_database_to_head,
    inspect_database,
)
from hesiva.financial_integrity import SQLITE_SIGNED_INTEGER_MAX
from hesiva.services import (
    BackupError,
    BackupPathError,
    BackupService,
    BackupValidationError,
    RestoreError,
    RestoreRecoveryError,
    RestoreRecoveryRequiredError,
    RestoreRollbackError,
)
from hesiva.services.backup_service import (
    BACKUP_FORMAT_VERSION,
    CONFIG_ARCHIVE_NAME,
    DATABASE_ARCHIVE_NAME,
    METADATA_ARCHIVE_NAME,
    RESTORE_JOURNAL_NAME,
)
from hesiva.version import get_application_version

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def fast_hasher() -> PasswordHasher:
    return PasswordHasher(
        time_cost=1,
        memory_cost=1024,
        parallelism=1,
        hash_len=16,
        salt_len=8,
        type=Type.ID,
    )


@pytest.fixture
def application_context(
    tmp_path: Path,
    fast_hasher: PasswordHasher,
) -> Iterator[ApplicationContext]:
    context = create_application_context(tmp_path / "live", password_hasher=fast_hasher)
    _configure_authentication(context, "live-password")
    try:
        yield context
    finally:
        context.close()


def _populate_representative_data(context: ApplicationContext, customer_name: str) -> int:
    with context.services() as services:
        customer = services.customer.create_customer(customer_name)
        animal = services.animal.create_animal(customer.id, name="Boncuk", species="İnek")
        services.transaction.create_debt(
            customer.id,
            transaction_date=date(2026, 8, 9),
            description="İlaç & bakım",
            amount_kurus=125_000,
            animal_id=animal.id,
        )
        services.reminder.create_reminder(customer.id, date(2026, 8, 10), "Kontrol")
        return customer.id


def _configure_authentication(context: ApplicationContext, password: str) -> None:
    context.authentication.create_initial_password(password, password)
    context.authentication.mark_setup_complete()


@contextmanager
def _archive_database(archive_path: Path, tmp_path: Path) -> Iterator[Path]:
    database_path = tmp_path / f"{archive_path.stem}.sqlite"
    with zipfile.ZipFile(archive_path, "r") as archive:
        with archive.open(DATABASE_ARCHIVE_NAME) as source, database_path.open("wb") as target:
            while chunk := source.read(1024 * 1024):
                target.write(chunk)
    try:
        yield database_path
    finally:
        database_path.unlink(missing_ok=True)


def _archive_config_payload(archive_path: Path) -> dict[str, object]:
    with zipfile.ZipFile(archive_path, "r") as archive:
        return json.loads(archive.read(CONFIG_ARCHIVE_NAME).decode("utf-8"))


def _customer_names(database_path: Path) -> list[str]:
    with closing(sqlite3.connect(database_path)) as connection:
        return [
            row[0]
            for row in connection.execute("SELECT full_name FROM customers ORDER BY id").fetchall()
        ]


def _write_database_archive(
    database_path: Path,
    archive_path: Path,
    configuration_bytes: bytes,
) -> None:
    database_bytes = database_path.read_bytes()
    metadata = {
        "application": "Hesiva",
        "application_version": get_application_version(),
        "backup_format_version": BACKUP_FORMAT_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "database_revision": _database_revision(database_path),
        "database_sha256": hashlib.sha256(database_bytes).hexdigest(),
        "database_size": len(database_bytes),
        "operating_system": "test",
    }
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(DATABASE_ARCHIVE_NAME, database_bytes)
        archive.writestr(CONFIG_ARCHIVE_NAME, configuration_bytes)
        archive.writestr(METADATA_ARCHIVE_NAME, json.dumps(metadata))


def _mutate_backup_database(
    valid_archive: Path,
    invalid_archive: Path,
    tmp_path: Path,
    mutation: str,
) -> None:
    with _archive_database(valid_archive, tmp_path) as database_path:
        with closing(sqlite3.connect(database_path)) as connection:
            with connection:
                connection.execute(mutation)
        with zipfile.ZipFile(valid_archive, "r") as archive:
            configuration_bytes = archive.read(CONFIG_ARCHIVE_NAME)
        _write_database_archive(
            database_path,
            invalid_archive,
            configuration_bytes,
        )


def _database_revision(database_path: Path) -> str:
    try:
        with closing(sqlite3.connect(database_path)) as connection:
            row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    except sqlite3.DatabaseError:
        return get_migration_head()
    return get_migration_head() if row is None else row[0]


def test_backup_uses_online_api_and_preserves_representative_data(
    application_context: ApplicationContext,
    tmp_path: Path,
) -> None:
    _populate_representative_data(application_context, "Dataset A")
    backup_path = tmp_path / "Hesiva_Yedek.zip"

    with application_context.engine.connect():
        metadata = application_context.create_backup(backup_path)

    assert metadata.database_revision == get_migration_head()
    assert backup_path.read_bytes().startswith(b"PK")
    with zipfile.ZipFile(backup_path) as archive:
        assert set(archive.namelist()) == {
            DATABASE_ARCHIVE_NAME,
            CONFIG_ARCHIVE_NAME,
            METADATA_ARCHIVE_NAME,
        }
        assert archive.testzip() is None
        config_payload = json.loads(archive.read(CONFIG_ARCHIVE_NAME).decode("utf-8"))
        assert config_payload["format_version"] == 1
        assert config_payload["authentication"]["setup_complete"] is True
        assert config_payload["authentication"]["password_hash"].startswith("$argon2id$")
        assert "live-password" not in archive.read(CONFIG_ARCHIVE_NAME).decode("utf-8")

    with _archive_database(backup_path, tmp_path) as database_path:
        assert inspect_database(database_path).state is DatabaseState.CURRENT
        with closing(sqlite3.connect(database_path)) as connection:
            assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            assert connection.execute("SELECT COUNT(*) FROM customers").fetchone() == (1,)
            assert connection.execute("SELECT COUNT(*) FROM transactions").fetchone() == (1,)
            assert connection.execute("SELECT COUNT(*) FROM animals").fetchone() == (1,)
            assert connection.execute("SELECT COUNT(*) FROM reminders").fetchone() == (1,)

    with application_context.services() as services:
        assert services.customer_summary.list_customer_summaries()[0].full_name == "Dataset A"


def test_backup_service_implementation_calls_sqlite_online_backup_api() -> None:
    source = inspect.getsource(BackupService._online_backup)
    module_source = inspect.getsource(inspect.getmodule(BackupService))

    assert "source_connection.backup(destination_connection)" in source
    assert "shutil.copy" not in module_source
    assert "copy2" not in module_source


def test_backup_rejects_live_path_and_failure_preserves_existing_target(
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = BackupService(
        application_context.database_path,
        application_context.configuration_store,
    )
    with pytest.raises(BackupPathError, match="live database"):
        service.create_backup(application_context.database_path)

    target = tmp_path / "existing.zip"
    target.write_bytes(b"existing backup")

    with pytest.raises(BackupPathError, match="not be overwritten"):
        service.create_backup(target)
    assert target.read_bytes() == b"existing backup"

    def fail_archive(*_args: object, **_kwargs: object) -> None:
        raise OSError("synthetic output failure")

    target.unlink()
    monkeypatch.setattr(service, "_write_archive", fail_archive)
    with pytest.raises(BackupError):
        service.create_backup(target)
    assert not target.exists()


def test_backup_rejects_reserved_application_data_destinations(
    application_context: ApplicationContext,
) -> None:
    service = application_context._backup_service
    reserved_paths = (
        application_context.configuration_store.path,
        service.restore_journal_path,
        application_context.application_data_lock.path,
        *service._live_sidecars(),
    )
    preserved_contents = {path: path.read_bytes() for path in reserved_paths if path.is_file()}

    for destination in reserved_paths:
        with pytest.raises(BackupPathError, match="application-data"):
            service.create_backup(destination)

    for path, contents in preserved_contents.items():
        assert path.read_bytes() == contents
    for path in reserved_paths:
        if path not in preserved_contents:
            assert not path.exists()


def test_backup_publication_rejects_target_created_after_initial_validation(
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "concurrent.zip"
    service = application_context._backup_service
    real_validate = service.validate_backup

    def create_competing_target(archive_path: Path):
        metadata = real_validate(archive_path)
        destination.write_bytes(b"other process backup")
        return metadata

    monkeypatch.setattr(service, "validate_backup", create_competing_target)

    with pytest.raises(BackupPathError, match="not be overwritten"):
        service.create_backup(destination)
    assert destination.read_bytes() == b"other process backup"


def test_interrupted_new_destination_is_not_reported_as_a_valid_backup(
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staged_path = tmp_path / "verified-staging.zip"
    destination = tmp_path / "interrupted-destination.zip"
    application_context.create_backup(staged_path)
    real_fdopen = os.fdopen

    class FailAfterFirstWrite:
        def __init__(self, descriptor: int, mode: str) -> None:
            self._file = real_fdopen(descriptor, mode)
            self._write_count = 0

        def __enter__(self) -> "FailAfterFirstWrite":
            self._file.__enter__()
            return self

        def __exit__(self, *args: object) -> object:
            return self._file.__exit__(*args)

        def write(self, payload: bytes) -> int:
            if self._write_count:
                raise OSError("synthetic destination write failure")
            self._write_count += 1
            return self._file.write(payload)

        def flush(self) -> None:
            self._file.flush()

        def fileno(self) -> int:
            return self._file.fileno()

    monkeypatch.setattr(backup_service_module, "COPY_BUFFER_SIZE", 64)
    with monkeypatch.context() as patcher:
        patcher.setattr(backup_service_module.os, "fdopen", FailAfterFirstWrite)
        with pytest.raises(OSError, match="destination write failure"):
            BackupService._publish_without_overwrite(staged_path, destination)

    assert 0 < destination.stat().st_size < staged_path.stat().st_size
    with pytest.raises(BackupValidationError):
        application_context.validate_backup(destination)


def test_backup_publication_syncs_completed_files_and_parent_directory(
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "durable.zip"
    synced_files: list[Path] = []
    synced_publications: list[Path] = []

    def record_file_sync(path: Path) -> None:
        assert path.is_file()
        synced_files.append(path)

    def record_parent_sync(path: Path) -> None:
        assert path.is_file()
        synced_publications.append(path)

    monkeypatch.setattr("hesiva.services.backup_service.sync_file", record_file_sync)
    monkeypatch.setattr(
        "hesiva.services.backup_service.sync_parent_directory",
        record_parent_sync,
    )

    application_context.create_backup(destination)

    assert len(synced_files) == 2
    assert synced_publications == [destination]
    if os.name == "posix":
        assert destination.stat().st_mode & 0o777 == 0o600


def test_default_backup_path_must_be_a_real_directory(
    application_context: ApplicationContext,
) -> None:
    backup_path = application_context._backup_service.default_backup_directory
    backup_path.write_bytes(b"not a directory")

    with pytest.raises(BackupPathError, match="real directory"):
        application_context.prepare_default_backup_directory()

    assert backup_path.read_bytes() == b"not a directory"


def test_invalid_archive_cleanup_is_explicit_before_validation_error_returns(
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup_path = tmp_path / "valid-before-forced-validation-error.zip"
    application_context.create_backup(backup_path)
    service = application_context._backup_service
    real_cleanup = service._cleanup_temporary_directory
    cleanup_observations: list[tuple[bool, type[BaseException] | None]] = []

    def fail_database_validation(_database_path: Path, _metadata: object) -> None:
        raise BackupValidationError("synthetic post-extraction validation failure")

    def track_cleanup(
        directory: tempfile.TemporaryDirectory[str],
        *,
        primary_error: BaseException | None,
    ) -> None:
        directory_path = Path(directory.name)
        assert directory_path.is_dir()
        real_cleanup(directory, primary_error=primary_error)
        cleanup_observations.append(
            (not directory_path.exists(), None if primary_error is None else type(primary_error))
        )

    monkeypatch.setattr(service, "_validate_metadata_database", fail_database_validation)
    monkeypatch.setattr(service, "_cleanup_temporary_directory", track_cleanup)

    with pytest.raises(BackupValidationError, match="post-extraction"):
        service.validate_backup(backup_path)

    assert cleanup_observations == [(True, BackupValidationError)]


@pytest.mark.parametrize("kind", ["missing", "empty", "text", "sqlite", "truncated"])
def test_restore_validation_rejects_unsafe_sources_before_touching_live_database(
    kind: str,
    application_context: ApplicationContext,
    tmp_path: Path,
) -> None:
    _populate_representative_data(application_context, "Untouched A")
    live_digest = hashlib.sha256(application_context.database_path.read_bytes()).hexdigest()
    candidate = tmp_path / f"{kind}.zip"
    if kind == "empty":
        candidate.touch()
    elif kind == "text":
        candidate.write_text("not a backup", encoding="utf-8")
    elif kind == "sqlite":
        unrelated = tmp_path / "unrelated.sqlite"
        with closing(sqlite3.connect(unrelated)) as connection, connection:
            connection.execute("CREATE TABLE unrelated (value TEXT)")
        _write_database_archive(
            unrelated,
            candidate,
            application_context.configuration_store.load().to_bytes(),
        )
    elif kind == "truncated":
        valid = tmp_path / "valid.zip"
        application_context.create_backup(valid)
        candidate.write_bytes(valid.read_bytes()[:100])

    with pytest.raises(BackupValidationError):
        application_context.validate_backup(candidate)

    assert hashlib.sha256(application_context.database_path.read_bytes()).hexdigest() == live_digest
    assert _customer_names(application_context.database_path) == ["Untouched A"]


@pytest.mark.parametrize(
    ("case_name", "mutation"),
    [
        (
            "trigger",
            "CREATE TRIGGER destructive_history AFTER INSERT ON transactions "
            "BEGIN DELETE FROM transactions WHERE id != NEW.id; END",
        ),
        ("foreign-key-orphan", "UPDATE transactions SET customer_id = 999999"),
        ("fractional-money", "UPDATE transactions SET amount_kurus = 125.5"),
        (
            "minimum-signed-integer-money",
            "UPDATE transactions SET amount_kurus = -9223372036854775808",
        ),
        (
            "active-debt-total-overflow",
            "INSERT INTO transactions (customer_id, animal_id, legacy_id, transaction_date, "
            "transaction_time, description, amount_kurus, note, created_at, updated_at, "
            "voided_at, void_reason) SELECT customer_id, NULL, NULL, transaction_date, NULL, "
            f"'Aggregate boundary', {SQLITE_SIGNED_INTEGER_MAX}, NULL, created_at, updated_at, "
            "NULL, NULL FROM transactions ORDER BY id LIMIT 1",
        ),
        ("invalid-date", "UPDATE transactions SET transaction_date = 'not-a-date'"),
        ("noncanonical-date", "UPDATE transactions SET transaction_date = '20260809'"),
        ("noncanonical-time", "UPDATE transactions SET transaction_time = '010203'"),
        (
            "noncanonical-datetime",
            "UPDATE transactions SET created_at = '2026-08-09T01:02:03+03:00'",
        ),
        (
            "cross-owner-animal",
            "UPDATE transactions SET animal_id = (SELECT id FROM animals ORDER BY id DESC LIMIT 1)",
        ),
        ("invalid-utf8-customer-name", "UPDATE customers SET full_name = CAST(x'80' AS TEXT)"),
    ],
)
def test_backup_validation_rejects_executable_or_semantically_invalid_databases(
    case_name: str,
    mutation: str,
    application_context: ApplicationContext,
    tmp_path: Path,
) -> None:
    first_customer_id = _populate_representative_data(application_context, "Dataset A")
    with application_context.services() as services:
        second_customer = services.customer.create_customer("Dataset B")
        services.animal.create_animal(second_customer.id, name="Other animal")
    valid_archive = tmp_path / f"valid-{case_name}.zip"
    invalid_archive = tmp_path / f"invalid-{case_name}.zip"
    application_context.create_backup(valid_archive)
    live_digest = hashlib.sha256(application_context.database_path.read_bytes()).hexdigest()
    config_digest = hashlib.sha256(
        application_context.configuration_store.path.read_bytes()
    ).hexdigest()
    _mutate_backup_database(valid_archive, invalid_archive, tmp_path, mutation)

    with pytest.raises(BackupValidationError):
        application_context.validate_backup(invalid_archive)
    with pytest.raises(BackupValidationError):
        application_context.restore_backup(invalid_archive)

    assert hashlib.sha256(application_context.database_path.read_bytes()).hexdigest() == live_digest
    assert (
        hashlib.sha256(application_context.configuration_store.path.read_bytes()).hexdigest()
        == config_digest
    )
    with application_context.services() as services:
        assert services.customer.get_customer(first_customer_id).full_name == "Dataset A"
    assert not application_context._backup_service.default_backup_directory.exists()


def test_backup_rejects_oversized_temporal_text_before_materializing_the_value(
    application_context: ApplicationContext,
    tmp_path: Path,
) -> None:
    _populate_representative_data(application_context, "Dataset A")
    valid_archive = tmp_path / "valid-temporal.zip"
    invalid_archive = tmp_path / "oversized-temporal.zip"
    application_context.create_backup(valid_archive)
    oversized_temporal = "2" * (data_limits.PERSISTED_USER_TEXT_MAX_BYTES + 1)

    with _archive_database(valid_archive, tmp_path) as database_path:
        with closing(sqlite3.connect(database_path)) as connection, connection:
            connection.execute(
                "UPDATE transactions SET created_at = ?",
                (oversized_temporal,),
            )

        class RejectTemporalMaterialization:
            def __init__(self, connection: sqlite3.Connection) -> None:
                self._connection = connection

            def execute(self, statement: str) -> sqlite3.Cursor:
                if 'CAST("created_at" AS BLOB)' in statement and 'FROM "transactions"' in statement:
                    raise AssertionError("oversized temporal text must not cross into Python")
                return self._connection.execute(statement)

        with closing(sqlite3.connect(database_path)) as connection:
            guarded_connection = RejectTemporalMaterialization(connection)
            assert BackupService._find_semantic_database_error(guarded_connection) == "transaction"

        with zipfile.ZipFile(valid_archive, "r") as archive:
            configuration_bytes = archive.read(CONFIG_ARCHIVE_NAME)
        _write_database_archive(database_path, invalid_archive, configuration_bytes)

    with pytest.raises(BackupValidationError, match="invalid transaction data"):
        application_context.validate_backup(invalid_archive)


def test_backup_validation_rejects_compressed_or_oversized_members(
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid_archive = tmp_path / "valid.zip"
    compressed_archive = tmp_path / "compressed.zip"
    application_context.create_backup(valid_archive)
    with (
        zipfile.ZipFile(valid_archive, "r") as source,
        zipfile.ZipFile(compressed_archive, "w", compression=zipfile.ZIP_DEFLATED) as target,
    ):
        for name in source.namelist():
            target.writestr(name, source.read(name))

    with pytest.raises(BackupValidationError, match="unsupported member"):
        application_context.validate_backup(compressed_archive)

    monkeypatch.setattr(
        "hesiva.services.backup_service.MAX_BACKUP_CONFIGURATION_BYTES",
        1,
    )
    with pytest.raises(BackupValidationError, match="oversized member"):
        application_context.validate_backup(valid_archive)


def test_backup_rejects_unbounded_central_directory_before_zipfile_materialization(
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_path = tmp_path / "too-many-members.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
        for index in range(4):
            archive.writestr(f"member-{index}", b"")

    def unexpected_zipfile_open(*args: object, **kwargs: object) -> None:
        raise AssertionError("ZipFile must not parse an invalid entry count")

    monkeypatch.setattr(backup_service_module.zipfile, "ZipFile", unexpected_zipfile_open)

    with pytest.raises(BackupValidationError, match="required Hesiva contents"):
        application_context.validate_backup(archive_path)


def test_backup_bounds_central_directory_before_zipfile_materialization(
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_path = tmp_path / "oversized-directory.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(DATABASE_ARCHIVE_NAME, b"database")
        archive.writestr(CONFIG_ARCHIVE_NAME, b"configuration")
        archive.writestr(METADATA_ARCHIVE_NAME, b"metadata")

    monkeypatch.setattr(backup_service_module, "MAX_BACKUP_CENTRAL_DIRECTORY_BYTES", 1)

    def unexpected_zipfile_open(*args: object, **kwargs: object) -> None:
        raise AssertionError("ZipFile must not parse an oversized directory")

    monkeypatch.setattr(backup_service_module.zipfile, "ZipFile", unexpected_zipfile_open)

    with pytest.raises(BackupValidationError, match="directory is too large"):
        application_context.validate_backup(archive_path)


@pytest.mark.skipif(
    os.name == "nt",
    reason="Windows prevents replacing an archive while its source handle is open.",
)
def test_backup_path_swap_after_preflight_cannot_change_open_archive(
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected_path = tmp_path / "selected.zip"
    replacement_path = tmp_path / "replacement.zip"
    service = application_context._backup_service
    original_metadata = service.create_backup(
        selected_path,
        created_at=datetime(2026, 8, 12, 10, 0, tzinfo=UTC),
    )
    replacement_metadata = service.create_backup(
        replacement_path,
        created_at=datetime(2026, 8, 13, 10, 0, tzinfo=UTC),
    )
    real_preflight = service._validate_zip_directory_envelope
    swapped = False

    def preflight_then_swap(
        archive_file: object,
        *,
        archive_size: int,
    ) -> None:
        nonlocal swapped
        real_preflight(archive_file, archive_size=archive_size)
        os.replace(replacement_path, selected_path)
        swapped = True

    monkeypatch.setattr(service, "_validate_zip_directory_envelope", preflight_then_swap)

    with pytest.raises(BackupValidationError, match="changed while it was being read"):
        service.validate_backup(selected_path)

    assert swapped
    assert original_metadata != replacement_metadata


def test_backup_directory_preflight_accepts_supported_zip64_envelope(
    application_context: ApplicationContext,
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "zip64-envelope.zip"
    original_metadata = application_context.create_backup(archive_path)
    archive_bytes = archive_path.read_bytes()
    record_offset = archive_bytes.rfind(
        backup_service_module.ZIP_END_OF_CENTRAL_DIRECTORY_SIGNATURE
    )
    assert record_offset >= 0
    (
        _signature,
        disk_number,
        directory_disk_number,
        entries_on_disk,
        total_entries,
        directory_size,
        directory_offset,
        comment_size,
    ) = backup_service_module.ZIP_END_OF_CENTRAL_DIRECTORY.unpack_from(
        archive_bytes,
        record_offset,
    )
    assert comment_size == 0
    zip64_record = backup_service_module.ZIP64_END_OF_CENTRAL_DIRECTORY.pack(
        backup_service_module.ZIP64_END_OF_CENTRAL_DIRECTORY_SIGNATURE,
        backup_service_module.ZIP64_END_OF_CENTRAL_DIRECTORY.size - 12,
        45,
        45,
        disk_number,
        directory_disk_number,
        entries_on_disk,
        total_entries,
        directory_size,
        directory_offset,
    )
    zip64_locator = backup_service_module.ZIP64_END_OF_CENTRAL_DIRECTORY_LOCATOR.pack(
        backup_service_module.ZIP64_END_OF_CENTRAL_DIRECTORY_LOCATOR_SIGNATURE,
        0,
        record_offset,
        1,
    )
    sentinel_record = backup_service_module.ZIP_END_OF_CENTRAL_DIRECTORY.pack(
        backup_service_module.ZIP_END_OF_CENTRAL_DIRECTORY_SIGNATURE,
        disk_number,
        directory_disk_number,
        backup_service_module.ZIP16_SENTINEL,
        backup_service_module.ZIP16_SENTINEL,
        backup_service_module.ZIP32_SENTINEL,
        backup_service_module.ZIP32_SENTINEL,
        0,
    )
    archive_path.write_bytes(
        archive_bytes[:record_offset] + zip64_record + zip64_locator + sentinel_record
    )

    assert application_context.validate_backup(archive_path) == original_metadata


@pytest.mark.parametrize(
    ("limit_target", "limit", "expected_category"),
    [
        ("hesiva.database.semantic_validation.MAX_BUSINESS_ROWS_PER_TABLE", 0, "row-count"),
        ("hesiva.data_limits.PERSISTED_USER_TEXT_MAX_BYTES", 3, "customer"),
    ],
)
def test_backup_validation_bounds_row_and_text_resources(
    limit_target: str,
    limit: int,
    expected_category: str,
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _populate_representative_data(application_context, "Dataset A")
    backup_path = tmp_path / f"bounded-{limit_target.rsplit('.', 1)[-1]}.zip"
    application_context.create_backup(backup_path)
    monkeypatch.setattr(limit_target, limit)

    with pytest.raises(BackupValidationError, match=expected_category):
        application_context.validate_backup(backup_path)


def test_validation_rejects_outdated_and_unknown_migration_databases(
    application_context: ApplicationContext,
    tmp_path: Path,
) -> None:
    outdated_database = tmp_path / "outdated.sqlite"
    command.stamp(create_alembic_config(outdated_database), "base")
    outdated_archive = tmp_path / "outdated.zip"
    config_bytes = application_context.configuration_store.load().to_bytes()
    _write_database_archive(outdated_database, outdated_archive, config_bytes)

    invalid_database = tmp_path / "unknown.sqlite"
    initialize_database_to_head(invalid_database)
    with closing(sqlite3.connect(invalid_database)) as connection, connection:
        connection.execute("UPDATE alembic_version SET version_num = 'unknown_revision'")
    invalid_archive = tmp_path / "unknown.zip"
    _write_database_archive(invalid_database, invalid_archive, config_bytes)

    with pytest.raises(BackupValidationError, match="older"):
        application_context.validate_backup(outdated_archive)
    with pytest.raises(BackupValidationError, match="current valid"):
        application_context.validate_backup(invalid_archive)


def test_restore_replaces_dataset_rebinds_context_and_preserves_source_and_safety_backup(
    application_context: ApplicationContext,
    fast_hasher: PasswordHasher,
    tmp_path: Path,
) -> None:
    _populate_representative_data(application_context, "Dataset A")
    source_context = create_application_context(
        tmp_path / "source-b",
        password_hasher=fast_hasher,
    )
    try:
        _configure_authentication(source_context, "source-password")
        _populate_representative_data(source_context, "Dataset B")
        source_backup = tmp_path / "dataset-b.zip"
        source_context.create_backup(source_backup)
    finally:
        source_context.close()
    source_digest = hashlib.sha256(source_backup.read_bytes()).hexdigest()

    result = application_context.restore_backup(source_backup)

    assert application_context.active_service_scopes == 0
    assert inspect_database(application_context.database_path).state is DatabaseState.CURRENT
    assert _customer_names(application_context.database_path) == ["Dataset B"]
    assert hashlib.sha256(source_backup.read_bytes()).hexdigest() == source_digest
    assert application_context.authentication.verify_password("source-password")
    assert not application_context.authentication.verify_password("live-password")
    assert result.safety_backup_path.is_file()
    assert application_context.validate_backup(result.safety_backup_path)
    with _archive_database(result.safety_backup_path, tmp_path) as safety_database:
        assert _customer_names(safety_database) == ["Dataset A"]
    safety_config = _archive_config_payload(result.safety_backup_path)
    assert fast_hasher.verify(
        safety_config["authentication"]["password_hash"],
        "live-password",
    )
    with application_context.services() as services:
        assert services.customer_summary.list_customer_summaries()[0].full_name == "Dataset B"


def test_restore_is_rejected_while_service_scope_is_active(
    application_context: ApplicationContext,
    tmp_path: Path,
) -> None:
    backup_path = tmp_path / "backup.zip"
    application_context.create_backup(backup_path)

    with application_context.services():
        with pytest.raises(RuntimeError, match="service scope"):
            application_context.restore_backup(backup_path)
    assert application_context.active_service_scopes == 0


def test_safety_backup_failure_leaves_live_database_untouched(
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _populate_representative_data(application_context, "Dataset A")
    source_backup = tmp_path / "source.zip"
    application_context.create_backup(source_backup)
    live_digest = hashlib.sha256(application_context.database_path.read_bytes()).hexdigest()

    def fail_safety_backup() -> Path:
        raise BackupError("synthetic safety failure")

    monkeypatch.setattr(
        application_context._backup_service, "_create_safety_backup", fail_safety_backup
    )

    with pytest.raises(BackupError, match="safety failure"):
        application_context.restore_backup(source_backup)
    assert hashlib.sha256(application_context.database_path.read_bytes()).hexdigest() == live_digest
    assert _customer_names(application_context.database_path) == ["Dataset A"]


def test_failure_before_atomic_replacement_reopens_original_database(
    application_context: ApplicationContext,
    fast_hasher: PasswordHasher,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _populate_representative_data(application_context, "Dataset A")
    source_context = create_application_context(
        tmp_path / "source-b",
        password_hasher=fast_hasher,
    )
    try:
        _configure_authentication(source_context, "source-password")
        _populate_representative_data(source_context, "Dataset B")
        source_backup = tmp_path / "source-b.zip"
        source_context.create_backup(source_backup)
    finally:
        source_context.close()

    real_replace = os.replace

    def fail_live_replace(source: Path, destination: Path) -> None:
        if Path(destination) == application_context.database_path:
            raise OSError("synthetic publication failure")
        real_replace(source, destination)

    monkeypatch.setattr("hesiva.services.backup_service.os.replace", fail_live_replace)

    with pytest.raises(RestoreError, match="before replacing"):
        application_context.restore_backup(source_backup)
    assert _customer_names(application_context.database_path) == ["Dataset A"]
    with application_context.services() as services:
        assert services.customer_summary.list_customer_summaries()[0].full_name == "Dataset A"


def test_post_replacement_reopen_failure_rolls_back_to_safety_backup(
    application_context: ApplicationContext,
    fast_hasher: PasswordHasher,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _populate_representative_data(application_context, "Dataset A")
    source_context = create_application_context(
        tmp_path / "source-b",
        password_hasher=fast_hasher,
    )
    try:
        _configure_authentication(source_context, "source-password")
        _populate_representative_data(source_context, "Dataset B")
        source_backup = tmp_path / "source-b.zip"
        source_context.create_backup(source_backup)
    finally:
        source_context.close()

    real_reopen = application_context._reopen_database_after_restore
    reopen_count = 0

    def fail_first_reopen() -> None:
        nonlocal reopen_count
        reopen_count += 1
        if reopen_count == 1:
            raise OSError("synthetic restored-open failure")
        real_reopen()

    monkeypatch.setattr(application_context, "_reopen_database_after_restore", fail_first_reopen)

    with pytest.raises(RestoreError, match="previous database was restored"):
        application_context.restore_backup(source_backup)
    assert reopen_count == 2
    assert _customer_names(application_context.database_path) == ["Dataset A"]
    assert application_context.authentication.verify_password("live-password")
    assert not application_context.authentication.verify_password("source-password")
    with application_context.services() as services:
        assert services.customer_summary.list_customer_summaries()[0].full_name == "Dataset A"


def test_rollback_failure_preserves_safety_backup_and_reports_severe_failure(
    application_context: ApplicationContext,
    fast_hasher: PasswordHasher,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _populate_representative_data(application_context, "Dataset A")
    source_context = create_application_context(
        tmp_path / "source-b",
        password_hasher=fast_hasher,
    )
    try:
        _configure_authentication(source_context, "source-password")
        _populate_representative_data(source_context, "Dataset B")
        source_backup = tmp_path / "source-b.zip"
        source_context.create_backup(source_backup)
    finally:
        source_context.close()

    def always_fail_reopen() -> None:
        raise OSError("synthetic reopen failure")

    monkeypatch.setattr(application_context, "_reopen_database_after_restore", always_fail_reopen)

    with pytest.raises(RestoreRollbackError) as error_info:
        application_context.restore_backup(source_backup)

    safety_path = error_info.value.safety_backup_path
    assert safety_path.is_file()
    assert BackupService(application_context.database_path).validate_backup(safety_path)
    assert inspect_database(application_context.database_path).state is DatabaseState.CURRENT
    assert _customer_names(application_context.database_path) == ["Dataset A"]


def test_existing_live_sidecar_aborts_before_replacement(
    application_context: ApplicationContext,
    tmp_path: Path,
) -> None:
    _populate_representative_data(application_context, "Dataset A")
    backup_path = tmp_path / "backup.zip"
    application_context.create_backup(backup_path)
    sidecar = Path(f"{application_context.database_path}-wal")
    sidecar.write_bytes(b"synthetic stale sidecar")
    try:
        with pytest.raises(RestoreError, match="before replacing"):
            application_context.restore_backup(backup_path)
        assert _customer_names(application_context.database_path) == ["Dataset A"]
    finally:
        sidecar.unlink(missing_ok=True)


def test_dangling_live_sidecar_aborts_before_replacement(
    application_context: ApplicationContext,
    tmp_path: Path,
) -> None:
    _populate_representative_data(application_context, "Dataset A")
    backup_path = tmp_path / "backup.zip"
    application_context.create_backup(backup_path)
    sidecar = Path(f"{application_context.database_path}-wal")
    try:
        sidecar.symlink_to(tmp_path / "missing-sidecar-target")
    except OSError as error:
        pytest.skip(f"Symbolic links are unavailable: {error}")

    try:
        with pytest.raises(RestoreError, match="before replacing"):
            application_context.restore_backup(backup_path)
        assert sidecar.is_symlink()
        assert _customer_names(application_context.database_path) == ["Dataset A"]
    finally:
        sidecar.unlink(missing_ok=True)


def test_backup_validation_rejects_malformed_authentication_config(
    application_context: ApplicationContext,
    tmp_path: Path,
) -> None:
    valid_path = tmp_path / "valid.zip"
    invalid_path = tmp_path / "invalid-config.zip"
    application_context.create_backup(valid_path)

    with (
        zipfile.ZipFile(valid_path, "r") as source,
        zipfile.ZipFile(
            invalid_path,
            "w",
            compression=zipfile.ZIP_STORED,
        ) as target,
    ):
        for name in source.namelist():
            payload = source.read(name)
            if name == CONFIG_ARCHIVE_NAME:
                payload = json.dumps(
                    {
                        "format_version": 1,
                        "authentication": {
                            "password_hash": "malformed",
                            "setup_complete": True,
                        },
                    }
                ).encode("utf-8")
            target.writestr(name, payload)

    with pytest.raises(BackupValidationError, match="configuration"):
        application_context.validate_backup(invalid_path)


@pytest.mark.parametrize("nonfinite_number", ("NaN", "Infinity", "-Infinity", "1e9999"))
def test_backup_configuration_uses_strict_configuration_parser(
    nonfinite_number: str,
    application_context: ApplicationContext,
    tmp_path: Path,
) -> None:
    valid_path = tmp_path / "valid.zip"
    invalid_path = tmp_path / f"invalid-number-{nonfinite_number.removeprefix('-')}.zip"
    application_context.create_backup(valid_path)

    with (
        zipfile.ZipFile(valid_path, "r") as source,
        zipfile.ZipFile(invalid_path, "w", compression=zipfile.ZIP_STORED) as target,
    ):
        for name in source.namelist():
            payload = source.read(name)
            if name == CONFIG_ARCHIVE_NAME:
                config_text = payload.decode("utf-8").rstrip()
                payload = (
                    config_text[:-1] + f', "future_numeric_value": {nonfinite_number}' + "}\n"
                ).encode("utf-8")
            target.writestr(name, payload)

    with pytest.raises(BackupValidationError, match="configuration"):
        application_context.validate_backup(invalid_path)


@pytest.mark.parametrize(
    "unknown_field",
    ('"future":"\\ud800"', '"\\ud800":"future"'),
    ids=("unknown-value", "unknown-key"),
)
def test_backup_configuration_rejects_lone_unicode_surrogates(
    unknown_field: str,
    application_context: ApplicationContext,
    tmp_path: Path,
) -> None:
    valid_path = tmp_path / "valid.zip"
    invalid_path = tmp_path / "invalid-unicode.zip"
    application_context.create_backup(valid_path)

    with (
        zipfile.ZipFile(valid_path, "r") as source,
        zipfile.ZipFile(invalid_path, "w", compression=zipfile.ZIP_STORED) as target,
    ):
        for name in source.namelist():
            payload = source.read(name)
            if name == CONFIG_ARCHIVE_NAME:
                config_text = payload.decode("utf-8").rstrip()
                payload = (config_text[:-1] + ", " + unknown_field + "}\n").encode("utf-8")
            target.writestr(name, payload)

    with pytest.raises(BackupValidationError, match="configuration"):
        application_context.validate_backup(invalid_path)


def test_backup_operations_never_log_password_hash(
    application_context: ApplicationContext,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    password_hash = application_context.configuration_store.load().password_hash

    application_context.create_backup(tmp_path / "private.zip")

    assert password_hash not in caplog.text


def test_config_publication_failure_rolls_back_database_and_configuration_pair(
    application_context: ApplicationContext,
    fast_hasher: PasswordHasher,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _populate_representative_data(application_context, "Dataset A")
    source_context = create_application_context(
        tmp_path / "source-b",
        password_hasher=fast_hasher,
    )
    try:
        _configure_authentication(source_context, "source-password")
        _populate_representative_data(source_context, "Dataset B")
        source_backup = tmp_path / "source-b.zip"
        source_context.create_backup(source_backup)
    finally:
        source_context.close()

    real_replace = os.replace
    config_publication_failures = 0

    def fail_first_config_publication(source: Path, destination: Path) -> None:
        nonlocal config_publication_failures
        if (
            Path(destination) == application_context.configuration_store.path
            and config_publication_failures == 0
        ):
            config_publication_failures += 1
            raise OSError("synthetic config publication failure")
        real_replace(source, destination)

    monkeypatch.setattr(
        "hesiva.services.backup_service.os.replace",
        fail_first_config_publication,
    )

    with pytest.raises(RestoreError, match="previous database was restored"):
        application_context.restore_backup(source_backup)

    assert config_publication_failures == 1
    assert _customer_names(application_context.database_path) == ["Dataset A"]
    assert application_context.authentication.verify_password("live-password")
    assert not application_context.authentication.verify_password("source-password")


@pytest.mark.parametrize("publish_config_before_crash", [False, True])
def test_startup_recovers_old_database_and_configuration_after_interrupted_restore(
    publish_config_before_crash: bool,
    fast_hasher: PasswordHasher,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SimulatedProcessDeath(BaseException):
        pass

    live_context = create_application_context(tmp_path / "live", password_hasher=fast_hasher)
    source_context = create_application_context(tmp_path / "source", password_hasher=fast_hasher)
    reopened_context: ApplicationContext | None = None
    try:
        _configure_authentication(live_context, "live-password")
        _populate_representative_data(live_context, "Dataset A")
        _configure_authentication(source_context, "source-password")
        _populate_representative_data(source_context, "Dataset B")
        source_backup = tmp_path / "source.zip"
        source_context.create_backup(source_backup)
        source_context.close()

        real_replace = os.replace

        def terminate_at_config_publication(source: Path, destination: Path) -> None:
            if Path(destination) == live_context.configuration_store.path:
                if publish_config_before_crash:
                    real_replace(source, destination)
                raise SimulatedProcessDeath
            real_replace(source, destination)

        with monkeypatch.context() as patcher:
            patcher.setattr(
                "hesiva.services.backup_service.os.replace",
                terminate_at_config_publication,
            )
            with pytest.raises(SimulatedProcessDeath):
                live_context.restore_backup(source_backup)

        journal_path = live_context.database_path.parent / RESTORE_JOURNAL_NAME
        assert journal_path.is_file()
        assert _customer_names(live_context.database_path) == ["Dataset B"]
        live_context.close()

        reopened_context = create_application_context(
            tmp_path / "live",
            password_hasher=fast_hasher,
        )
        assert _customer_names(reopened_context.database_path) == ["Dataset A"]
        assert reopened_context.authentication.verify_password("live-password")
        assert not reopened_context.authentication.verify_password("source-password")
        assert not journal_path.exists()
    finally:
        source_context.close()
        if reopened_context is not None:
            reopened_context.close()
        else:
            live_context.close()


@pytest.mark.parametrize("publish_config_before_crash", [False, True])
def test_real_process_exit_during_restore_recovers_pair_and_stale_lock(
    publish_config_before_crash: bool,
    fast_hasher: PasswordHasher,
    tmp_path: Path,
) -> None:
    live_directory = tmp_path / "live-process"
    live_context = create_application_context(live_directory, password_hasher=fast_hasher)
    source_context = create_application_context(
        tmp_path / "source-process",
        password_hasher=fast_hasher,
    )
    try:
        _configure_authentication(live_context, "live-password")
        _populate_representative_data(live_context, "Dataset A")
        _configure_authentication(source_context, "source-password")
        _populate_representative_data(source_context, "Dataset B")
        source_backup = tmp_path / "source-process.zip"
        source_context.create_backup(source_backup)
    finally:
        source_context.close()
        live_context.close()

    child_code = "\n".join(
        (
            "import os, sys",
            "from pathlib import Path",
            "import hesiva.services.backup_service as backup_module",
            "from hesiva.application import create_application_context",
            "context = create_application_context(Path(sys.argv[1]))",
            "config_path = context.configuration_store.path",
            "real_replace = backup_module.os.replace",
            "def crash_at_config(source, destination):",
            "    if Path(destination) == config_path:",
            "        if sys.argv[3] == '1':",
            "            real_replace(source, destination)",
            "        os._exit(79)",
            "    real_replace(source, destination)",
            "backup_module.os.replace = crash_at_config",
            "context.restore_backup(Path(sys.argv[2]))",
            "raise AssertionError('restore unexpectedly returned')",
        )
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            child_code,
            str(live_directory),
            str(source_backup),
            "1" if publish_config_before_crash else "0",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 79, result.stderr
    assert (live_directory / RESTORE_JOURNAL_NAME).is_file()
    assert _customer_names(live_directory / "hesiva.db") == ["Dataset B"]

    recovered = create_application_context(live_directory, password_hasher=fast_hasher)
    try:
        assert _customer_names(recovered.database_path) == ["Dataset A"]
        assert recovered.authentication.verify_password("live-password")
        assert not recovered.authentication.verify_password("source-password")
        assert not (live_directory / RESTORE_JOURNAL_NAME).exists()
    finally:
        recovered.close()


def test_marker_publication_failure_clears_marker_before_context_remains_writable(
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _populate_representative_data(application_context, "Dataset A")
    backup_path = tmp_path / "source.zip"
    application_context.create_backup(backup_path)
    service = application_context._backup_service
    real_set_permissions = service._set_private_permissions

    def fail_marker_permissions(path: Path) -> None:
        if path == service.restore_journal_path:
            raise PermissionError("synthetic marker permission failure")
        real_set_permissions(path)

    with monkeypatch.context() as patcher:
        patcher.setattr(service, "_set_private_permissions", fail_marker_permissions)
        with pytest.raises(RestoreRecoveryError) as error_info:
            application_context.restore_backup(backup_path)

    assert not isinstance(error_info.value, RestoreRecoveryRequiredError)
    assert not service.restore_journal_path.exists()
    assert application_context._database_available
    with application_context.services() as services:
        services.customer.create_customer("Safe after cleared marker")
        assert [
            summary.full_name for summary in services.customer_summary.list_customer_summaries()
        ] == ["Dataset A", "Safe after cleared marker"]


def test_unclearable_restore_marker_disables_context_until_startup_recovery(
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _populate_representative_data(application_context, "Dataset A")
    backup_path = tmp_path / "source.zip"
    application_context.create_backup(backup_path)
    service = application_context._backup_service
    marker_path = service.restore_journal_path
    real_set_permissions = service._set_private_permissions
    real_unlink = Path.unlink

    def fail_marker_permissions(path: Path) -> None:
        if path == marker_path:
            raise PermissionError("synthetic marker permission failure")
        real_set_permissions(path)

    def fail_marker_cleanup(path: Path, *args: object, **kwargs: object) -> None:
        if path == marker_path:
            raise PermissionError("synthetic marker cleanup failure")
        real_unlink(path, *args, **kwargs)

    with monkeypatch.context() as patcher:
        patcher.setattr(service, "_set_private_permissions", fail_marker_permissions)
        patcher.setattr(Path, "unlink", fail_marker_cleanup)
        with pytest.raises(RestoreRecoveryRequiredError, match="restart"):
            application_context.restore_backup(backup_path)

    assert marker_path.is_file()
    assert not application_context._database_available
    with pytest.raises(RuntimeError, match="temporarily unavailable"):
        with application_context.services():
            pass

    data_directory = application_context.database_path.parent
    application_context.close()
    recovered = create_application_context(data_directory)
    try:
        assert _customer_names(recovered.database_path) == ["Dataset A"]
        assert not marker_path.exists()
    finally:
        recovered.close()


def test_uncertain_marker_deletion_durability_disables_context_until_restart(
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _populate_representative_data(application_context, "Dataset A")
    backup_path = tmp_path / "source.zip"
    application_context.create_backup(backup_path)
    service = application_context._backup_service
    marker_path = service.restore_journal_path
    real_sync = backup_service_module.sync_parent_directory

    def fail_marker_directory_sync(path: Path) -> None:
        if path == marker_path:
            raise OSError("synthetic marker directory sync failure")
        real_sync(path)

    with monkeypatch.context() as patcher:
        patcher.setattr(
            backup_service_module,
            "sync_parent_directory",
            fail_marker_directory_sync,
        )
        with pytest.raises(RestoreRecoveryRequiredError, match="restart"):
            application_context.restore_backup(backup_path)

    assert not marker_path.exists()
    assert not application_context._database_available
    with pytest.raises(RuntimeError, match="temporarily unavailable"):
        with application_context.services():
            pass

    data_directory = application_context.database_path.parent
    application_context.close()
    recovered = create_application_context(data_directory)
    try:
        assert _customer_names(recovered.database_path) == ["Dataset A"]
    finally:
        recovered.close()


@pytest.mark.parametrize(
    "marker_remains",
    [False, True],
    ids=("unlink-succeeds-directory-sync-fails", "unlink-fails-marker-remains"),
)
def test_final_restore_marker_clear_failure_never_starts_unjournaled_rollback(
    marker_remains: bool,
    application_context: ApplicationContext,
    fast_hasher: PasswordHasher,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _populate_representative_data(application_context, "Dataset A")
    source_context = create_application_context(
        tmp_path / "source-final-marker",
        password_hasher=fast_hasher,
    )
    try:
        _configure_authentication(source_context, "source-password")
        _populate_representative_data(source_context, "Dataset B")
        source_backup = tmp_path / "source-final-marker.zip"
        source_context.create_backup(source_backup)
    finally:
        source_context.close()

    service = application_context._backup_service
    marker_path = service.restore_journal_path
    real_sync = backup_service_module.sync_parent_directory
    real_unlink = Path.unlink
    marker_sync_count = 0
    rollback_attempted = False

    def fail_only_final_marker_sync(path: Path) -> None:
        nonlocal marker_sync_count
        if path == marker_path:
            marker_sync_count += 1
            if marker_sync_count == 2:
                raise OSError("synthetic final marker directory sync failure")
        real_sync(path)

    def fail_final_marker_unlink(path: Path, *args: object, **kwargs: object) -> None:
        if path == marker_path:
            raise PermissionError("synthetic final marker unlink failure")
        real_unlink(path, *args, **kwargs)

    def record_rollback_attempt(*_args: object, **_kwargs: object) -> None:
        nonlocal rollback_attempted
        rollback_attempted = True
        raise AssertionError("a validated restored pair must not enter unjournaled rollback")

    with monkeypatch.context() as patcher:
        patcher.setattr(service, "_rollback_after_failed_restore", record_rollback_attempt)
        if marker_remains:
            patcher.setattr(Path, "unlink", fail_final_marker_unlink)
        else:
            patcher.setattr(
                backup_service_module,
                "sync_parent_directory",
                fail_only_final_marker_sync,
            )
        with pytest.raises(RestoreRecoveryRequiredError):
            application_context.restore_backup(source_backup)

    assert not rollback_attempted
    assert marker_path.exists() is marker_remains
    assert not application_context._database_available
    assert _customer_names(application_context.database_path) == ["Dataset B"]
    with pytest.raises(RuntimeError, match="temporarily unavailable"):
        with application_context.services():
            pass

    data_directory = application_context.database_path.parent
    application_context.close()
    recovered = create_application_context(data_directory, password_hasher=fast_hasher)
    try:
        expected_customer = "Dataset A" if marker_remains else "Dataset B"
        expected_password = "live-password" if marker_remains else "source-password"
        rejected_password = "source-password" if marker_remains else "live-password"
        assert _customer_names(recovered.database_path) == [expected_customer]
        assert recovered.authentication.verify_password(expected_password)
        assert not recovered.authentication.verify_password(rejected_password)
        assert not marker_path.exists()
    finally:
        recovered.close()


def test_invalid_restore_recovery_marker_blocks_startup_without_guessing(
    fast_hasher: PasswordHasher,
    tmp_path: Path,
) -> None:
    data_directory = tmp_path / "live"
    context = create_application_context(data_directory, password_hasher=fast_hasher)
    _configure_authentication(context, "live-password")
    _populate_representative_data(context, "Dataset A")
    live_digest = hashlib.sha256(context.database_path.read_bytes()).hexdigest()
    context.close()
    journal_path = data_directory / RESTORE_JOURNAL_NAME
    journal_path.write_text("{}", encoding="utf-8")

    with pytest.raises(ApplicationStartupError) as error_info:
        create_application_context(data_directory, password_hasher=fast_hasher)

    assert isinstance(error_info.value.__cause__, RestoreRecoveryError)
    assert journal_path.read_text(encoding="utf-8") == "{}"
    assert (
        hashlib.sha256(data_directory.joinpath("hesiva.db").read_bytes()).hexdigest() == live_digest
    )


def test_dangling_restore_recovery_marker_blocks_startup_and_releases_lock(
    fast_hasher: PasswordHasher,
    tmp_path: Path,
) -> None:
    data_directory = tmp_path / "live"
    context = create_application_context(data_directory, password_hasher=fast_hasher)
    context.close()
    journal_path = data_directory / RESTORE_JOURNAL_NAME
    try:
        journal_path.symlink_to(data_directory / "missing-recovery-target")
    except OSError as error:
        pytest.skip(f"Symbolic links are unavailable: {error}")

    for _attempt in range(2):
        with pytest.raises(ApplicationStartupError) as error_info:
            create_application_context(data_directory, password_hasher=fast_hasher)
        assert isinstance(error_info.value.__cause__, RestoreRecoveryError)
        assert journal_path.is_symlink()
