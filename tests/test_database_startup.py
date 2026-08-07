import hashlib
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import inspect

from hesiva.database.engine import create_sqlite_engine
from hesiva.database.startup import (
    DatabaseInitializationError,
    DatabaseOutdatedError,
    DatabaseState,
    InvalidDatabaseError,
    create_alembic_config,
    get_migration_head,
    initialize_database_to_head,
    inspect_database,
    prepare_database,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TABLES = {"alembic_version", "animals", "customers", "reminders", "transactions"}


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_importing_startup_modules_does_not_create_production_data(tmp_path: Path) -> None:
    data_home = tmp_path / "xdg-data"
    environment = os.environ.copy()
    environment["XDG_DATA_HOME"] = str(data_home)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")

    subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import hesiva.application; import hesiva.composition; import hesiva.database.startup"
            ),
        ],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert not data_home.exists()
    assert not (tmp_path / "hesiva.db").exists()


def test_missing_database_is_classified_without_creating_it(tmp_path: Path) -> None:
    database_path = tmp_path / "missing.db"

    status = inspect_database(database_path)

    assert status.state is DatabaseState.MISSING
    assert status.current_revision is None
    assert status.head_revision == get_migration_head()
    assert not database_path.exists()


def test_missing_database_initializes_to_head_with_expected_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "hesiva.db"

    status = prepare_database(database_path)

    assert status.state is DatabaseState.CURRENT
    assert status.current_revision == status.head_revision == get_migration_head()
    assert inspect_database(database_path).state is DatabaseState.CURRENT

    engine = create_sqlite_engine(database_path)
    try:
        assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES
    finally:
        engine.dispose()


def test_current_database_does_not_run_initialization_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "current.db"
    initialize_database_to_head(database_path)
    digest_before = file_digest(database_path)

    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Alembic upgrade must not run for a current database.")

    monkeypatch.setattr("hesiva.database.startup.command.upgrade", fail_if_called)

    status = prepare_database(database_path)

    assert status.state is DatabaseState.CURRENT
    assert file_digest(database_path) == digest_before


def test_outdated_database_is_rejected_without_modification(tmp_path: Path) -> None:
    database_path = tmp_path / "outdated.db"
    command.stamp(create_alembic_config(database_path), "base")
    status = inspect_database(database_path)
    digest_before = file_digest(database_path)

    assert status.state is DatabaseState.OUTDATED
    assert status.current_revision is None

    with pytest.raises(DatabaseOutdatedError, match="automatic upgrades are disabled"):
        prepare_database(database_path)

    assert file_digest(database_path) == digest_before
    assert inspect_database(database_path).state is DatabaseState.OUTDATED


def test_unrelated_sqlite_database_is_rejected_without_overwrite(tmp_path: Path) -> None:
    database_path = tmp_path / "unrelated.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE unrelated (value TEXT NOT NULL)")
        connection.execute("INSERT INTO unrelated (value) VALUES ('preserve me')")
    digest_before = file_digest(database_path)

    status = inspect_database(database_path)

    assert status.state is DatabaseState.INVALID
    with pytest.raises(InvalidDatabaseError, match="left unchanged"):
        prepare_database(database_path)
    assert file_digest(database_path) == digest_before

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT value FROM unrelated").fetchone() == ("preserve me",)


def test_empty_existing_sqlite_file_is_invalid(tmp_path: Path) -> None:
    database_path = tmp_path / "empty.db"
    sqlite3.connect(database_path).close()

    assert inspect_database(database_path).state is DatabaseState.INVALID
    with pytest.raises(InvalidDatabaseError):
        prepare_database(database_path)


def test_corrupt_existing_file_is_invalid_and_unchanged(tmp_path: Path) -> None:
    database_path = tmp_path / "corrupt.db"
    database_path.write_bytes(b"not a SQLite database")
    digest_before = file_digest(database_path)

    assert inspect_database(database_path).state is DatabaseState.INVALID
    with pytest.raises(InvalidDatabaseError):
        prepare_database(database_path)
    assert file_digest(database_path) == digest_before


def test_failed_fresh_initialization_leaves_no_final_or_temporary_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "hesiva.db"

    def fail_upgrade(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("Synthetic migration failure")

    monkeypatch.setattr("hesiva.database.startup.command.upgrade", fail_upgrade)

    with pytest.raises(DatabaseInitializationError, match="final path was left untouched"):
        initialize_database_to_head(database_path)

    assert not database_path.exists()
    assert list(tmp_path.iterdir()) == []


def test_initialization_never_replaces_existing_file(tmp_path: Path) -> None:
    database_path = tmp_path / "hesiva.db"
    database_path.write_bytes(b"preserve existing file")
    digest_before = file_digest(database_path)

    with pytest.raises(DatabaseInitializationError, match="already exists"):
        initialize_database_to_head(database_path)

    assert file_digest(database_path) == digest_before


@pytest.mark.skipif(os.name != "posix", reason="POSIX directory durability behavior")
def test_fresh_initialization_syncs_parent_after_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "hesiva.db"
    synced_directories: list[Path] = []

    def record_directory_sync(published_database_path: Path) -> None:
        assert published_database_path.is_file()
        synced_directories.append(published_database_path.parent)

    monkeypatch.setattr(
        "hesiva.database.startup._sync_parent_directory",
        record_directory_sync,
    )

    initialize_database_to_head(database_path)

    assert synced_directories == [tmp_path]
    assert inspect_database(database_path).state is DatabaseState.CURRENT


@pytest.mark.skipif(os.name != "posix", reason="POSIX directory durability behavior")
def test_directory_sync_failure_is_reported_without_deleting_published_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "hesiva.db"

    def fail_directory_sync(_published_database_path: Path) -> None:
        raise DatabaseInitializationError("Synthetic directory sync failure")

    monkeypatch.setattr(
        "hesiva.database.startup._sync_parent_directory",
        fail_directory_sync,
    )

    with pytest.raises(DatabaseInitializationError, match="Synthetic directory sync failure"):
        initialize_database_to_head(database_path)

    assert database_path.is_file()
    assert inspect_database(database_path).state is DatabaseState.CURRENT


def test_python_module_starts_against_isolated_xdg_directory(tmp_path: Path) -> None:
    data_home = tmp_path / "xdg-data"
    database_path = data_home / "hesiva" / "hesiva.db"
    environment = os.environ.copy()
    environment["XDG_DATA_HOME"] = str(data_home)
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")

    process = subprocess.Popen(
        [sys.executable, "-m", "hesiva"],
        cwd=tmp_path,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                pytest.fail(f"Hesiva exited before reaching the event loop: {stdout!r} {stderr!r}")
            if (
                database_path.exists()
                and inspect_database(database_path).state is DatabaseState.CURRENT
            ):
                break
            time.sleep(0.05)
        else:
            pytest.fail("Hesiva did not initialize its isolated database before the timeout.")

        assert process.poll() is None
        assert database_path == data_home / "hesiva" / "hesiva.db"
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)
