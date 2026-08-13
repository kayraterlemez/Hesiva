from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from hesiva.database.engine import configure_sqlite_engine
from hesiva.models import model_metadata

config = context.config

if config.config_file_name is not None:
    # Alembic's CLI configuration must not disable loggers that the running
    # application or a longer-lived test process already owns.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = model_metadata


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
    try:
        configure_sqlite_engine(connectable)

        with connectable.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)

            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
