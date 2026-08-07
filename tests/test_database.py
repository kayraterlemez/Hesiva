from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cari.database.engine import create_sqlite_engine
from cari.database.session import create_session_factory


def test_engine_connects_to_explicit_temporary_database(tmp_path: Path) -> None:
    database_path = tmp_path / "engine.db"
    engine = create_sqlite_engine(database_path)

    try:
        assert not database_path.exists()

        with engine.connect() as connection:
            assert connection.scalar(text("SELECT 1")) == 1

        assert database_path.is_file()
    finally:
        engine.dispose()


def test_engine_rejects_relative_database_path() -> None:
    with pytest.raises(ValueError, match="must be absolute"):
        create_sqlite_engine(Path("cari.db"))


def test_engine_enforces_sqlite_foreign_keys(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "foreign-keys.db")

    try:
        with engine.connect() as first_connection, engine.connect() as second_connection:
            assert first_connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            assert second_connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1

        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
            connection.exec_driver_sql(
                "CREATE TABLE child (parent_id INTEGER NOT NULL REFERENCES parent(id))"
            )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.exec_driver_sql("INSERT INTO child (parent_id) VALUES (1)")
    finally:
        engine.dispose()


def test_session_factory_creates_independent_caller_owned_sessions(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "sessions.db")
    session_factory = create_session_factory(engine)

    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE session_test (value INTEGER NOT NULL)")

        with session_factory() as first_session, session_factory() as second_session:
            assert isinstance(first_session, Session)
            assert first_session is not second_session
            first_session.execute(text("INSERT INTO session_test (value) VALUES (1)"))

        with session_factory() as verification_session:
            row_count = verification_session.scalar(text("SELECT COUNT(*) FROM session_test"))

        assert row_count == 0
    finally:
        engine.dispose()
