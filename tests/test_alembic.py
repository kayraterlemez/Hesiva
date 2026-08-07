from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.engine import URL

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_alembic_environment_uses_src_layout_and_temporary_database(tmp_path: Path) -> None:
    alembic_config = Config(PROJECT_ROOT / "alembic.ini")
    script_directory = ScriptDirectory.from_config(alembic_config)

    assert Path(script_directory.dir) == PROJECT_ROOT / "src" / "cari" / "database" / "migrations"
    assert alembic_config.get_main_option("sqlalchemy.url") == "sqlite://"

    database_path = tmp_path / "alembic.db"
    database_url = URL.create("sqlite+pysqlite", database=str(database_path))
    alembic_config.set_main_option(
        "sqlalchemy.url", database_url.render_as_string(hide_password=False)
    )

    command.upgrade(alembic_config, "head")

    assert database_path.is_file()
