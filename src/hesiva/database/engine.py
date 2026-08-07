from pathlib import Path
from sqlite3 import Connection as SQLiteConnection

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import URL
from sqlalchemy.pool import ConnectionPoolEntry


def _enable_sqlite_foreign_keys(
    dbapi_connection: SQLiteConnection,
    _connection_record: ConnectionPoolEntry,
) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys = ON")
    finally:
        cursor.close()


def configure_sqlite_engine(engine: Engine) -> None:
    """Apply Hesiva's required SQLite connection configuration to an engine."""
    if engine.dialect.name != "sqlite":
        raise ValueError("Hesiva database engines must use SQLite.")

    if not event.contains(engine, "connect", _enable_sqlite_foreign_keys):
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)


def create_sqlite_engine(database_path: Path) -> Engine:
    """Create a lazily connected SQLite engine for an absolute database path."""
    resolved_path = database_path.expanduser()
    if not resolved_path.is_absolute():
        raise ValueError("The SQLite database path must be absolute.")

    database_url = URL.create("sqlite+pysqlite", database=str(resolved_path))
    engine = create_engine(database_url)
    configure_sqlite_engine(engine)
    return engine
