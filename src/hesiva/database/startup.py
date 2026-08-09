import logging
import os
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from io import StringIO
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.engine import URL

from hesiva.database.durability import sync_parent_directory
from hesiva.models import model_metadata

MIGRATION_DIRECTORY = Path(__file__).resolve().parent / "migrations"
REQUIRED_MIGRATION_RESOURCES = (
    "env.py",
    "script.py.mako",
    "versions",
)
ALEMBIC_VERSION_TABLE = "alembic_version"
LOGGER = logging.getLogger(__name__)


class DatabaseState(StrEnum):
    MISSING = "missing"
    CURRENT = "current"
    OUTDATED = "outdated"
    INVALID = "invalid"


@dataclass(frozen=True)
class DatabaseStatus:
    state: DatabaseState
    head_revision: str
    current_revision: str | None = None
    detail: str | None = None


class DatabaseStartupError(Exception):
    """Base exception for safe database startup failures."""


class DatabaseOutdatedError(DatabaseStartupError):
    """Raised when an existing database requires a safeguarded migration."""


class InvalidDatabaseError(DatabaseStartupError):
    """Raised when an existing file is not a valid Hesiva database."""


class DatabaseInitializationError(DatabaseStartupError):
    """Raised when a missing database cannot be initialized safely."""


def create_alembic_config(database_path: Path) -> Config:
    """Return Alembic configuration for one explicit SQLite database path."""
    resolved_path = database_path.expanduser()
    if not resolved_path.is_absolute():
        raise ValueError("The SQLite database path must be absolute.")

    database_url = URL.create("sqlite+pysqlite", database=str(resolved_path))
    config = Config(stdout=StringIO())
    config.set_main_option("script_location", _escape_config_value(str(get_migration_directory())))
    config.set_main_option(
        "sqlalchemy.url",
        _escape_config_value(database_url.render_as_string(hide_password=False)),
    )
    return config


def get_migration_head() -> str:
    """Return the single migration head bundled with this Hesiva version."""
    config = _create_script_config()
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise DatabaseStartupError("Hesiva requires exactly one Alembic migration head.")
    return heads[0]


def get_migration_directory() -> Path:
    """Return and validate source-tree or frozen Alembic resources."""
    missing = [
        name for name in REQUIRED_MIGRATION_RESOURCES if not (MIGRATION_DIRECTORY / name).exists()
    ]
    if missing:
        raise DatabaseStartupError("Required Hesiva migration resources are unavailable.")
    return MIGRATION_DIRECTORY


def inspect_database(database_path: Path) -> DatabaseStatus:
    """Classify a database without creating or migrating it."""
    resolved_path = database_path.expanduser()
    if not resolved_path.is_absolute():
        raise ValueError("The SQLite database path must be absolute.")

    head_revision = get_migration_head()
    if not resolved_path.exists():
        return DatabaseStatus(DatabaseState.MISSING, head_revision)
    if not resolved_path.is_file():
        return DatabaseStatus(
            DatabaseState.INVALID,
            head_revision,
            detail="The database path is not a regular file.",
        )

    try:
        with _connect_read_only(resolved_path) as connection:
            integrity_result = connection.execute("PRAGMA quick_check").fetchone()
            if integrity_result != ("ok",):
                return DatabaseStatus(
                    DatabaseState.INVALID,
                    head_revision,
                    detail="SQLite integrity verification failed.",
                )

            table_names = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
                if not row[0].startswith("sqlite_")
            }
            if ALEMBIC_VERSION_TABLE not in table_names:
                return DatabaseStatus(
                    DatabaseState.INVALID,
                    head_revision,
                    detail="The Alembic version table is missing.",
                )

            revision_rows = connection.execute(
                f"SELECT version_num FROM {ALEMBIC_VERSION_TABLE}"
            ).fetchall()
    except (OSError, sqlite3.DatabaseError) as error:
        return DatabaseStatus(
            DatabaseState.INVALID,
            head_revision,
            detail=f"SQLite could not read the database: {error}",
        )

    if len(revision_rows) > 1:
        return DatabaseStatus(
            DatabaseState.INVALID,
            head_revision,
            detail="The database contains multiple Alembic revisions.",
        )

    current_revision = None if not revision_rows else revision_rows[0][0]
    if current_revision == head_revision:
        expected_tables = set(model_metadata.tables) | {ALEMBIC_VERSION_TABLE}
        if table_names != expected_tables:
            return DatabaseStatus(
                DatabaseState.INVALID,
                head_revision,
                current_revision,
                "The database tables do not match the current Hesiva schema.",
            )
        if not _schema_matches_metadata(resolved_path):
            return DatabaseStatus(
                DatabaseState.INVALID,
                head_revision,
                current_revision,
                "The database schema does not match the current Hesiva migration.",
            )
        return DatabaseStatus(DatabaseState.CURRENT, head_revision, current_revision)

    if current_revision is None:
        if table_names == {ALEMBIC_VERSION_TABLE}:
            return DatabaseStatus(DatabaseState.OUTDATED, head_revision)
        return DatabaseStatus(
            DatabaseState.INVALID,
            head_revision,
            detail="The unversioned database contains unexpected tables.",
        )

    if not _is_known_ancestor(current_revision, head_revision):
        return DatabaseStatus(
            DatabaseState.INVALID,
            head_revision,
            current_revision,
            "The database revision is not recognized by this Hesiva version.",
        )

    return DatabaseStatus(DatabaseState.OUTDATED, head_revision, current_revision)


def prepare_database(database_path: Path) -> DatabaseStatus:
    """Initialize a missing database or validate an existing database for startup."""
    status = inspect_database(database_path)
    if status.state is DatabaseState.MISSING:
        return initialize_database_to_head(database_path)
    if status.state is DatabaseState.CURRENT:
        return status
    if status.state is DatabaseState.OUTDATED:
        raise DatabaseOutdatedError(
            "The Hesiva database requires migration, but automatic upgrades are disabled "
            "until recovery backups are implemented."
        )
    raise InvalidDatabaseError(
        "The existing database is not a valid current Hesiva database and was left unchanged."
    )


def initialize_database_to_head(database_path: Path) -> DatabaseStatus:
    """Migrate a temporary database to head and publish it without replacement."""
    resolved_path = database_path.expanduser()
    if not resolved_path.is_absolute():
        raise ValueError("The SQLite database path must be absolute.")
    if resolved_path.exists():
        raise DatabaseInitializationError("The final database path already exists.")
    if not resolved_path.parent.is_dir():
        raise DatabaseInitializationError("The application data directory does not exist.")

    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{resolved_path.name}.",
        suffix=".initializing",
        dir=resolved_path.parent,
    )
    os.close(file_descriptor)
    temporary_path = Path(temporary_name)

    try:
        command.upgrade(create_alembic_config(temporary_path), "head")
        status = inspect_database(temporary_path)
        if status.state is not DatabaseState.CURRENT:
            raise DatabaseInitializationError(
                "The newly migrated database did not pass schema verification."
            )

        with temporary_path.open("rb") as temporary_file:
            os.fsync(temporary_file.fileno())
        _publish_without_replacement(temporary_path, resolved_path)
        _sync_parent_directory(resolved_path)
        return status
    except DatabaseInitializationError:
        raise
    except Exception as error:
        raise DatabaseInitializationError(
            "Hesiva could not initialize the new database; the final path was left untouched."
        ) from error
    finally:
        _remove_temporary_database_files(temporary_path)


def _connect_read_only(database_path: Path) -> sqlite3.Connection:
    database_uri = f"{database_path.resolve().as_uri()}?mode=ro"
    return sqlite3.connect(database_uri, uri=True)


def _schema_matches_metadata(database_path: Path) -> bool:
    try:
        command.check(create_alembic_config(database_path))
    except Exception:
        return False
    return True


def _is_known_ancestor(current_revision: str, head_revision: str) -> bool:
    try:
        script_directory = ScriptDirectory.from_config(_create_script_config())
        if script_directory.get_revision(current_revision) is None:
            return False
        revisions = script_directory.iterate_revisions(head_revision, current_revision)
        list(revisions)
    except Exception:
        return False
    return True


def _publish_without_replacement(temporary_path: Path, final_path: Path) -> None:
    try:
        if sys.platform == "win32":
            temporary_path.rename(final_path)
        else:
            os.link(temporary_path, final_path)
    except FileExistsError as error:
        raise DatabaseInitializationError(
            "The final database path appeared during initialization and was not replaced."
        ) from error
    except OSError as error:
        raise DatabaseInitializationError(
            "The initialized database could not be published safely."
        ) from error


def _sync_parent_directory(database_path: Path) -> None:
    try:
        sync_parent_directory(database_path)
    except OSError as error:
        raise DatabaseInitializationError(
            "The database was published, but its parent directory could not be synced."
        ) from error


def _remove_temporary_database_files(temporary_path: Path) -> None:
    for path in (
        temporary_path,
        Path(f"{temporary_path}-journal"),
        Path(f"{temporary_path}-shm"),
        Path(f"{temporary_path}-wal"),
    ):
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            LOGGER.warning("Could not remove temporary database file %s: %s", path, error)


def _escape_config_value(value: str) -> str:
    return value.replace("%", "%%")


def _create_script_config() -> Config:
    config = Config(stdout=StringIO())
    config.set_main_option("script_location", _escape_config_value(str(get_migration_directory())))
    return config
