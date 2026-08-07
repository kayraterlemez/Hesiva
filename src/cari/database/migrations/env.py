from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from cari.database.base import Base
from cari.database.engine import configure_sqlite_engine

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Future model modules must be imported before autogeneration so they register here.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without opening a database connection."""
    database_url = config.get_main_option("sqlalchemy.url")
    if not database_url:
        raise RuntimeError("Alembic requires an explicit SQLAlchemy database URL.")

    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations using a configured SQLite connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    configure_sqlite_engine(connectable)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
