import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

import hesiva.application as application_module
import hesiva.database.startup as startup_module
from hesiva.application import ApplicationStartupError, create_application_context
from hesiva.application_data_lock import APPLICATION_DATA_LOCK_FILENAME
from hesiva.database.startup import DatabaseState, initialize_database_to_head, inspect_database


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_application_context_exclusively_owns_data_until_close(tmp_path: Path) -> None:
    data_directory = tmp_path / "application-data"
    first = create_application_context(data_directory)
    try:
        with pytest.raises(ApplicationStartupError, match="already using"):
            create_application_context(data_directory)
    finally:
        first.close()

    reopened = create_application_context(data_directory)
    reopened.close()


def test_application_context_does_not_release_ownership_with_active_scope(tmp_path: Path) -> None:
    data_directory = tmp_path / "application-data"
    context = create_application_context(data_directory)
    try:
        with context.services():
            with pytest.raises(RuntimeError, match="active service scopes"):
                context.close()
            with pytest.raises(ApplicationStartupError, match="already using"):
                create_application_context(data_directory)
    finally:
        context.close()


def test_startup_failure_releases_application_data_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_directory = tmp_path / "application-data"
    real_builder = application_module.build_application_context

    def fail_context_build(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic context-build failure")

    monkeypatch.setattr(application_module, "build_application_context", fail_context_build)
    with pytest.raises(ApplicationStartupError, match="open its local database"):
        create_application_context(data_directory)

    monkeypatch.setattr(application_module, "build_application_context", real_builder)
    recovered = create_application_context(data_directory)
    recovered.close()


@pytest.mark.parametrize("link_kind", ["symbolic", "hard"])
def test_distinct_data_directories_cannot_alias_one_live_database(
    link_kind: str,
    tmp_path: Path,
) -> None:
    first_directory = tmp_path / "first"
    second_directory = tmp_path / "second"
    first = create_application_context(first_directory)
    second_directory.mkdir()
    alias_path = second_directory / first.database_path.name
    if link_kind == "symbolic":
        alias_path.symlink_to(first.database_path)
    else:
        os.link(first.database_path, alias_path)

    try:
        with pytest.raises(
            ApplicationStartupError,
            match="valid current Hesiva database|linked-file identity",
        ):
            create_application_context(second_directory)
        with first.services() as services:
            customer = services.customer.create_customer("Lock owner remains usable")
            assert customer.id is not None
    finally:
        first.close()


def test_crashed_process_ownership_is_recovered_without_waiting(tmp_path: Path) -> None:
    data_directory = tmp_path / "application-data"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    child_code = "\n".join(
        (
            "import os, sys",
            "from pathlib import Path",
            "from hesiva.application import create_application_context",
            "context = create_application_context(Path(sys.argv[1]))",
            'print("READY", flush=True)',
            "sys.stdin.readline()",
            "os._exit(71)",
        )
    )
    process = subprocess.Popen(
        [sys.executable, "-c", child_code, str(data_directory)],
        cwd=PROJECT_ROOT,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "READY"
        with pytest.raises(ApplicationStartupError, match="already using"):
            create_application_context(data_directory)

        assert process.stdin is not None
        process.stdin.write("exit without cleanup\n")
        process.stdin.flush()
        assert process.wait(timeout=10) == 71
        assert (data_directory / APPLICATION_DATA_LOCK_FILENAME).is_file()

        recovered = create_application_context(data_directory)
        recovered.close()
        assert not (data_directory / APPLICATION_DATA_LOCK_FILENAME).exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()


def test_startup_recovers_real_hot_rollback_journal_before_read_only_inspection(
    tmp_path: Path,
) -> None:
    data_directory = tmp_path / "application-data"
    context = create_application_context(data_directory)
    database_path = context.database_path
    context.close()

    old_notes = "old-committed-" + ("a" * 4096)
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("PRAGMA synchronous = FULL")
        connection.executemany(
            """
            INSERT INTO customers (full_name, notes, created_at, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            [(f"Customer {index}", old_notes) for index in range(512)],
        )
        connection.commit()

    child_code = "\n".join(
        (
            "import os, sqlite3, sys",
            "from pathlib import Path",
            "database_path = Path(sys.argv[1])",
            "connection = sqlite3.connect(database_path)",
            'connection.execute("PRAGMA journal_mode = DELETE")',
            'connection.execute("PRAGMA synchronous = FULL")',
            'connection.execute("PRAGMA cache_size = 5")',
            'connection.execute("BEGIN IMMEDIATE")',
            'connection.execute("UPDATE customers SET notes = ?", ("new-uncommitted-" + ("b" * 4096),))',
            'assert Path(f"{database_path}-journal").is_file()',
            "os._exit(73)",
        )
    )
    result = subprocess.run(
        [sys.executable, "-c", child_code, str(database_path)],
        cwd=PROJECT_ROOT,
        check=False,
    )
    journal_path = Path(f"{database_path}-journal")
    assert result.returncode == 73
    assert journal_path.is_file()
    assert inspect_database(database_path).state is DatabaseState.INVALID

    recovered = create_application_context(data_directory)
    try:
        with recovered.engine.connect() as connection:
            distinct_notes = (
                connection.execute(text("SELECT DISTINCT notes FROM customers")).scalars().all()
            )
        assert distinct_notes == [old_notes]
        assert inspect_database(database_path).state is DatabaseState.CURRENT
        assert not journal_path.exists()
    finally:
        recovered.close()


def test_startup_closes_raw_connection_and_disposes_migration_engines_before_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "hesiva.db"
    raw_connections: list[TrackingConnection] = []
    disposed_engines: list[Engine] = []
    real_connect = startup_module._connect_read_only
    real_dispose = Engine.dispose
    real_publish = startup_module._publish_without_replacement

    def tracking_connect(path: Path) -> "TrackingConnection":
        connection = TrackingConnection(real_connect(path))
        raw_connections.append(connection)
        return connection

    def tracking_dispose(engine: Engine, *args: object, **kwargs: object) -> None:
        disposed_engines.append(engine)
        real_dispose(engine, *args, **kwargs)

    def assert_closed_then_publish(temporary_path: Path, final_path: Path) -> None:
        assert raw_connections
        assert all(connection.closed for connection in raw_connections)
        assert len(disposed_engines) >= 2
        real_publish(temporary_path, final_path)

    monkeypatch.setattr(startup_module, "_connect_read_only", tracking_connect)
    monkeypatch.setattr(Engine, "dispose", tracking_dispose)
    monkeypatch.setattr(startup_module, "_publish_without_replacement", assert_closed_then_publish)

    initialize_database_to_head(database_path)

    assert inspect_database(database_path).state is DatabaseState.CURRENT


def test_database_inspection_closes_raw_connection_after_sqlite_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "hesiva.db"
    initialize_database_to_head(database_path)
    connection = FailingConnection()
    monkeypatch.setattr(startup_module, "_connect_read_only", lambda _path: connection)

    status = inspect_database(database_path)

    assert status.state is DatabaseState.INVALID
    assert connection.closed


class TrackingConnection:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self.closed = False

    def execute(self, *args: object, **kwargs: object):
        return self._connection.execute(*args, **kwargs)

    def close(self) -> None:
        self._connection.close()
        self.closed = True


class FailingConnection:
    def __init__(self) -> None:
        self.closed = False

    def execute(self, *_args: object, **_kwargs: object) -> None:
        raise sqlite3.DatabaseError("synthetic inspection failure")

    def close(self) -> None:
        self.closed = True
