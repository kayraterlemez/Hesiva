from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError

from hesiva.database.engine import create_sqlite_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUSINESS_TABLES = {"animals", "customers", "reminders", "transactions"}
EXPECTED_INDEXES = {
    "animals": {"ix_animals_customer_id", "ix_animals_ear_tag"},
    "customers": {"ix_customers_full_name", "ix_customers_legacy_id"},
    "reminders": {"ix_reminders_customer_id", "ix_reminders_remind_on"},
    "transactions": {
        "ix_transactions_animal_id",
        "ix_transactions_customer_id",
        "ix_transactions_legacy_id",
        "ix_transactions_transaction_date",
    },
}


def create_alembic_config(database_path: Path) -> Config:
    alembic_config = Config(PROJECT_ROOT / "alembic.ini")
    database_url = URL.create("sqlite+pysqlite", database=str(database_path))
    alembic_config.set_main_option(
        "sqlalchemy.url", database_url.render_as_string(hide_password=False)
    )
    return alembic_config


def test_alembic_environment_uses_src_layout_and_temporary_database(tmp_path: Path) -> None:
    alembic_config = Config(PROJECT_ROOT / "alembic.ini")
    script_directory = ScriptDirectory.from_config(alembic_config)

    assert Path(script_directory.dir) == PROJECT_ROOT / "src" / "hesiva" / "database" / "migrations"
    assert alembic_config.get_main_option("sqlalchemy.url") == "sqlite://"

    database_path = tmp_path / "foundation.db"
    alembic_config = create_alembic_config(database_path)

    command.upgrade(alembic_config, "head")

    assert database_path.is_file()


def test_initial_migration_creates_expected_schema_and_enforces_check(tmp_path: Path) -> None:
    database_path = tmp_path / "upgrade.db"
    alembic_config = create_alembic_config(database_path)

    command.upgrade(alembic_config, "head")
    command.check(alembic_config)

    engine = create_sqlite_engine(database_path)
    try:
        inspector = inspect(engine)
        assert set(inspector.get_table_names()) == BUSINESS_TABLES | {"alembic_version"}

        for table_name, expected_indexes in EXPECTED_INDEXES.items():
            actual_indexes = {index["name"] for index in inspector.get_indexes(table_name)}
            assert actual_indexes == expected_indexes

        for table_name in {"animals", "reminders", "transactions"}:
            assert all(
                foreign_key["options"].get("ondelete") is None
                for foreign_key in inspector.get_foreign_keys(table_name)
            )

        check_constraints = inspector.get_check_constraints("transactions")
        assert len(check_constraints) == 1
        assert check_constraints[0]["name"] == "ck_transactions_amount_kurus_nonzero"
        assert check_constraints[0]["sqltext"] == "amount_kurus != 0"

        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                INSERT INTO customers (full_name, created_at, updated_at)
                VALUES ('Migration Customer', '2026-08-07 12:00:00', '2026-08-07 12:00:00')
                """
            )
            customer_id = connection.exec_driver_sql("SELECT last_insert_rowid()").scalar_one()

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    """
                    INSERT INTO transactions (
                        customer_id,
                        transaction_date,
                        description,
                        amount_kurus,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        customer_id,
                        "2026-08-07",
                        "Invalid migration movement",
                        0,
                        "2026-08-07 12:00:00",
                        "2026-08-07 12:00:00",
                    ),
                )
    finally:
        engine.dispose()


def test_initial_migration_downgrade_removes_business_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "downgrade.db"
    alembic_config = create_alembic_config(database_path)

    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")

    engine = create_sqlite_engine(database_path)
    try:
        assert BUSINESS_TABLES.isdisjoint(inspect(engine).get_table_names())
    finally:
        engine.dispose()
