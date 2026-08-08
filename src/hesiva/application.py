import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from hesiva.composition import ApplicationContext, build_application_context
from hesiva.database.paths import (
    ensure_application_data_directory,
    get_application_data_directory,
    get_production_database_path,
)
from hesiva.database.startup import DatabaseStartupError, prepare_database
from hesiva.ui.main_window import MainWindow

LOGGER = logging.getLogger(__name__)


class ApplicationStartupError(Exception):
    """Raised when Hesiva cannot prepare its local application infrastructure."""


def create_application_context(
    application_data_directory: Path | None = None,
) -> ApplicationContext:
    """Prepare the production database and construct application dependencies."""
    data_directory = (
        get_application_data_directory()
        if application_data_directory is None
        else application_data_directory
    )
    try:
        ensure_application_data_directory(data_directory)
    except OSError as error:
        raise ApplicationStartupError(
            "Hesiva could not create or access its application data directory."
        ) from error

    database_path = get_production_database_path(data_directory)
    try:
        prepare_database(database_path)
        return build_application_context(database_path)
    except DatabaseStartupError as error:
        raise ApplicationStartupError(str(error)) from error
    except Exception as error:
        raise ApplicationStartupError("Hesiva could not open its local database safely.") from error


def main() -> int:
    """Start the Hesiva desktop application."""
    application = QApplication(sys.argv)
    try:
        application_context = create_application_context()
    except ApplicationStartupError as error:
        LOGGER.error("Hesiva startup failed: %s", error)
        QMessageBox.critical(None, "Hesiva Startup Error", str(error))
        return 1
    except Exception:
        LOGGER.exception("Unexpected error during Hesiva startup")
        QMessageBox.critical(
            None,
            "Hesiva Startup Error",
            "Hesiva could not start safely. No existing database was replaced.",
        )
        return 1

    main_window = MainWindow(application_context)
    main_window.show()

    try:
        return application.exec()
    finally:
        application_context.close()
