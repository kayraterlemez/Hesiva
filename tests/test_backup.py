import hashlib
import inspect
import json
import os
import sqlite3
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from alembic import command

from hesiva.application import create_application_context
from hesiva.composition import ApplicationContext
from hesiva.database.startup import (
    DatabaseState,
    create_alembic_config,
    get_migration_head,
    initialize_database_to_head,
    inspect_database,
)
from hesiva.services import (
    BackupError,
    BackupPathError,
    BackupService,
    BackupValidationError,
    RestoreError,
    RestoreRollbackError,
)
from hesiva.services.backup_service import (
    BACKUP_FORMAT_VERSION,
    CONFIG_ARCHIVE_NAME,
    DATABASE_ARCHIVE_NAME,
    METADATA_ARCHIVE_NAME,
)


@pytest.fixture
def application_context(tmp_path: Path) -> Iterator[ApplicationContext]:
    context = create_application_context(tmp_path / "live")
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


def _customer_names(database_path: Path) -> list[str]:
    with sqlite3.connect(database_path) as connection:
        return [
            row[0]
            for row in connection.execute("SELECT full_name FROM customers ORDER BY id").fetchall()
        ]


def _write_database_archive(database_path: Path, archive_path: Path) -> None:
    database_bytes = database_path.read_bytes()
    metadata = {
        "application": "Hesiva",
        "application_version": "0.1.0",
        "backup_format_version": BACKUP_FORMAT_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "database_revision": _database_revision(database_path),
        "database_sha256": hashlib.sha256(database_bytes).hexdigest(),
        "database_size": len(database_bytes),
        "operating_system": "test",
    }
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(DATABASE_ARCHIVE_NAME, database_bytes)
        archive.writestr(CONFIG_ARCHIVE_NAME, json.dumps({"format_version": 1}))
        archive.writestr(METADATA_ARCHIVE_NAME, json.dumps(metadata))


def _database_revision(database_path: Path) -> str:
    try:
        with sqlite3.connect(database_path) as connection:
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

    with _archive_database(backup_path, tmp_path) as database_path:
        assert inspect_database(database_path).state is DatabaseState.CURRENT
        with sqlite3.connect(database_path) as connection:
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
    service = BackupService(application_context.database_path)
    with pytest.raises(BackupPathError, match="live database"):
        service.create_backup(application_context.database_path)

    target = tmp_path / "existing.zip"
    target.write_bytes(b"existing backup")

    def fail_archive(*_args: object, **_kwargs: object) -> None:
        raise OSError("synthetic output failure")

    monkeypatch.setattr(service, "_write_archive", fail_archive)
    with pytest.raises(BackupError):
        service.create_backup(target)
    assert target.read_bytes() == b"existing backup"


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
        with sqlite3.connect(unrelated) as connection:
            connection.execute("CREATE TABLE unrelated (value TEXT)")
        _write_database_archive(unrelated, candidate)
    elif kind == "truncated":
        valid = tmp_path / "valid.zip"
        application_context.create_backup(valid)
        candidate.write_bytes(valid.read_bytes()[:100])

    with pytest.raises(BackupValidationError):
        application_context.validate_backup(candidate)

    assert hashlib.sha256(application_context.database_path.read_bytes()).hexdigest() == live_digest
    assert _customer_names(application_context.database_path) == ["Untouched A"]


def test_validation_rejects_outdated_and_unknown_migration_databases(
    application_context: ApplicationContext,
    tmp_path: Path,
) -> None:
    outdated_database = tmp_path / "outdated.sqlite"
    command.stamp(create_alembic_config(outdated_database), "base")
    outdated_archive = tmp_path / "outdated.zip"
    _write_database_archive(outdated_database, outdated_archive)

    invalid_database = tmp_path / "unknown.sqlite"
    initialize_database_to_head(invalid_database)
    with sqlite3.connect(invalid_database) as connection:
        connection.execute("UPDATE alembic_version SET version_num = 'unknown_revision'")
    invalid_archive = tmp_path / "unknown.zip"
    _write_database_archive(invalid_database, invalid_archive)

    with pytest.raises(BackupValidationError, match="older"):
        application_context.validate_backup(outdated_archive)
    with pytest.raises(BackupValidationError, match="current valid"):
        application_context.validate_backup(invalid_archive)


def test_restore_replaces_dataset_rebinds_context_and_preserves_source_and_safety_backup(
    application_context: ApplicationContext,
    tmp_path: Path,
) -> None:
    _populate_representative_data(application_context, "Dataset A")
    source_context = create_application_context(tmp_path / "source-b")
    try:
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
    assert result.safety_backup_path.is_file()
    assert application_context.validate_backup(result.safety_backup_path)
    with _archive_database(result.safety_backup_path, tmp_path) as safety_database:
        assert _customer_names(safety_database) == ["Dataset A"]
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
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _populate_representative_data(application_context, "Dataset A")
    source_context = create_application_context(tmp_path / "source-b")
    try:
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
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _populate_representative_data(application_context, "Dataset A")
    source_context = create_application_context(tmp_path / "source-b")
    try:
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
    with application_context.services() as services:
        assert services.customer_summary.list_customer_summaries()[0].full_name == "Dataset A"


def test_rollback_failure_preserves_safety_backup_and_reports_severe_failure(
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _populate_representative_data(application_context, "Dataset A")
    source_context = create_application_context(tmp_path / "source-b")
    try:
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
