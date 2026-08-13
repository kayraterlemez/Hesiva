import hashlib
import os
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import inspect

import hesiva.database.startup as startup_module
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
from hesiva.financial_integrity import SQLITE_SIGNED_INTEGER_MAX

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


@pytest.mark.parametrize(
    ("case_name", "mutation"),
    (
        (
            "persistent-trigger",
            "CREATE TRIGGER discard_history AFTER INSERT ON transactions "
            "BEGIN DELETE FROM transactions WHERE id != NEW.id; END",
        ),
        (
            "persistent-view",
            "CREATE VIEW customer_names AS SELECT full_name FROM customers",
        ),
    ),
)
def test_startup_rejects_unsupported_executable_schema_objects(
    case_name: str,
    mutation: str,
    tmp_path: Path,
) -> None:
    database_path = tmp_path / f"{case_name}.db"
    initialize_database_to_head(database_path)
    with closing(sqlite3.connect(database_path)) as connection, connection:
        connection.execute(mutation)
    digest_before = file_digest(database_path)

    status = inspect_database(database_path)

    assert status.state is DatabaseState.INVALID
    assert status.detail == "The database contains unsupported schema objects."
    with pytest.raises(InvalidDatabaseError):
        prepare_database(database_path)
    assert file_digest(database_path) == digest_before


@pytest.mark.parametrize(
    ("case_name", "mutation"),
    (
        ("invalid-utf8", "UPDATE customers SET full_name = CAST(x'80' AS TEXT) WHERE id = 1"),
        ("invalid-date", "UPDATE transactions SET transaction_date = 'not-a-date' WHERE id = 1"),
        (
            "dual-reminder-state",
            "UPDATE reminders SET completed_at = updated_at, cancelled_at = updated_at WHERE id = 1",
        ),
        ("cross-owner-animal", "UPDATE transactions SET animal_id = 2 WHERE id = 1"),
    ),
)
def test_startup_rejects_semantically_invalid_business_data_without_modification(
    case_name: str,
    mutation: str,
    tmp_path: Path,
) -> None:
    database_path = tmp_path / f"invalid-{case_name}.db"
    initialize_database_to_head(database_path)
    timestamp = "2026-08-13 12:00:00.000000"
    with closing(sqlite3.connect(database_path)) as connection, connection:
        connection.executemany(
            "INSERT INTO customers (full_name, created_at, updated_at) VALUES (?, ?, ?)",
            (("Customer A", timestamp, timestamp), ("Customer B", timestamp, timestamp)),
        )
        connection.executemany(
            "INSERT INTO animals (customer_id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ((1, "Animal A", timestamp, timestamp), (2, "Animal B", timestamp, timestamp)),
        )
        connection.execute(
            "INSERT INTO transactions (customer_id, animal_id, transaction_date, description, "
            "amount_kurus, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (1, 1, "2026-08-13", "Valid transaction", 100, timestamp, timestamp),
        )
        connection.execute(
            "INSERT INTO reminders (customer_id, remind_on, note, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (1, "2026-08-14", "Valid reminder", timestamp, timestamp),
        )
        connection.execute(mutation)
    digest_before = file_digest(database_path)

    with pytest.raises(InvalidDatabaseError, match="invalid business data"):
        prepare_database(database_path)

    assert file_digest(database_path) == digest_before
    assert not list(tmp_path.glob(f"{database_path.name}-*"))


def test_startup_rejects_foreign_key_orphans_without_modification(tmp_path: Path) -> None:
    database_path = tmp_path / "foreign-key-orphan.db"
    initialize_database_to_head(database_path)
    timestamp = "2026-08-13 10:00:00.000000"
    with closing(sqlite3.connect(database_path)) as connection, connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute(
            "INSERT INTO transactions (customer_id, transaction_date, description, "
            "amount_kurus, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (999_999, "2026-08-13", "Orphan", 100, timestamp, timestamp),
        )
    digest_before = file_digest(database_path)

    status = inspect_database(database_path)

    assert status.state is DatabaseState.INVALID
    assert status.detail == "The database contains invalid foreign-key relationships."
    with pytest.raises(InvalidDatabaseError):
        prepare_database(database_path)
    assert file_digest(database_path) == digest_before


@pytest.mark.parametrize("link_kind", ["symbolic", "hard"])
def test_startup_rejects_linked_database_identity_without_opening_target(
    link_kind: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_path = tmp_path / "target.db"
    linked_path = tmp_path / "linked.db"
    initialize_database_to_head(target_path)
    target_digest = file_digest(target_path)
    if link_kind == "symbolic":
        linked_path.symlink_to(target_path)
    else:
        os.link(target_path, linked_path)

    opened: list[Path] = []

    def record_open(path: Path) -> sqlite3.Connection:
        opened.append(path)
        raise AssertionError("linked database must be rejected before SQLite opens it")

    monkeypatch.setattr(startup_module, "_connect_read_write", record_open)

    status = inspect_database(linked_path)
    with pytest.raises(InvalidDatabaseError):
        prepare_database(linked_path)

    assert status.state is DatabaseState.INVALID
    expected_detail = (
        "The database path is not a regular file."
        if link_kind == "symbolic"
        else "The database file has an unsupported linked-file identity."
    )
    assert status.detail == expected_detail
    assert opened == []
    assert file_digest(target_path) == target_digest


def test_startup_does_not_hide_unsupported_hard_link_as_outdated_database(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "hesiva.db"
    initialize_database_to_head(database_path)
    alias_path = tmp_path / "unrelated-alias.db"
    os.link(database_path, alias_path)

    with pytest.raises(InvalidDatabaseError, match="linked-file identity"):
        prepare_database(database_path)

    assert alias_path.is_file()
    assert database_path.stat().st_nlink == 2


def test_startup_completes_interrupted_posix_hard_link_publication(tmp_path: Path) -> None:
    database_path = tmp_path / "hesiva.db"
    staging_path = tmp_path / ".hesiva.db.crash123.initializing"
    initialize_database_to_head(staging_path)
    digest_before = file_digest(staging_path)
    os.link(staging_path, database_path)
    assert database_path.stat().st_nlink == 2

    status = prepare_database(database_path)

    assert status.state is DatabaseState.CURRENT
    assert not staging_path.exists()
    assert database_path.stat().st_nlink == 1
    assert file_digest(database_path) == digest_before


def _insert_financial_rows(
    database_path: Path,
    rows: tuple[tuple[int, str | None], ...],
) -> None:
    timestamp = "2026-08-13 10:00:00.000000"
    with closing(sqlite3.connect(database_path)) as connection, connection:
        customer_id = connection.execute(
            "INSERT INTO customers (full_name, created_at, updated_at) VALUES (?, ?, ?)",
            ("Financial Boundary Customer", timestamp, timestamp),
        ).lastrowid
        connection.executemany(
            "INSERT INTO transactions (customer_id, transaction_date, description, "
            "amount_kurus, created_at, updated_at, voided_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                (
                    customer_id,
                    "2026-08-13",
                    f"Boundary movement {index}",
                    amount_kurus,
                    timestamp,
                    timestamp,
                    voided_at,
                )
                for index, (amount_kurus, voided_at) in enumerate(rows, start=1)
            ),
        )


@pytest.mark.parametrize(
    "active_amounts",
    [
        (SQLITE_SIGNED_INTEGER_MAX, 1),
        (-SQLITE_SIGNED_INTEGER_MAX, -1),
        (-(1 << 63),),
    ],
    ids=("debt-side-total", "payment-side-total", "minimum-signed-integer"),
)
def test_startup_rejects_preexisting_unsafe_financial_values_without_modification(
    active_amounts: tuple[int, ...],
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "unsafe-financial.db"
    initialize_database_to_head(database_path)
    _insert_financial_rows(
        database_path,
        tuple((amount_kurus, None) for amount_kurus in active_amounts),
    )
    digest_before = file_digest(database_path)

    with pytest.raises(InvalidDatabaseError, match="exact SQLite aggregation range"):
        prepare_database(database_path)

    assert file_digest(database_path) == digest_before
    assert not list(tmp_path.glob("unsafe-financial.db-*"))


def test_startup_financial_validation_excludes_voided_transactions(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "voided-financial.db"
    initialize_database_to_head(database_path)
    _insert_financial_rows(
        database_path,
        (
            (SQLITE_SIGNED_INTEGER_MAX, None),
            (SQLITE_SIGNED_INTEGER_MAX, "2026-08-13 11:00:00.000000"),
        ),
    )
    digest_before = file_digest(database_path)

    status = prepare_database(database_path)

    assert status.state is DatabaseState.CURRENT
    assert file_digest(database_path) == digest_before
    assert not list(tmp_path.glob("voided-financial.db-*"))


def test_startup_rejects_voided_minimum_integer_without_modification(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "voided-minimum-integer.db"
    initialize_database_to_head(database_path)
    _insert_financial_rows(
        database_path,
        ((-(1 << 63), "2026-08-13 11:00:00.000000"),),
    )
    digest_before = file_digest(database_path)

    with pytest.raises(InvalidDatabaseError, match="exact SQLite aggregation range"):
        prepare_database(database_path)

    assert file_digest(database_path) == digest_before
    assert not list(tmp_path.glob("voided-minimum-integer.db-*"))


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
    with closing(sqlite3.connect(database_path)) as connection, connection:
        connection.execute("CREATE TABLE unrelated (value TEXT NOT NULL)")
        connection.execute("INSERT INTO unrelated (value) VALUES ('preserve me')")
    digest_before = file_digest(database_path)

    status = inspect_database(database_path)

    assert status.state is DatabaseState.INVALID
    with pytest.raises(InvalidDatabaseError, match="left unchanged"):
        prepare_database(database_path)
    assert file_digest(database_path) == digest_before

    with closing(sqlite3.connect(database_path)) as connection:
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
