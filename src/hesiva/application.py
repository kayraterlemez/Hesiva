import logging
import sys
from pathlib import Path

from argon2 import PasswordHasher
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from hesiva.composition import ApplicationContext, build_application_context
from hesiva.database.paths import (
    ensure_application_data_directory,
    get_application_data_directory,
    get_production_database_path,
)
from hesiva.database.startup import DatabaseStartupError, prepare_database
from hesiva.services import AuthenticationError, AuthenticationState
from hesiva.ui.auth_dialogs import (
    DatabaseChoiceDialog,
    InitialPasswordDialog,
    LoginDialog,
    SetupChoice,
)
from hesiva.ui.legacy_import_dialog import LegacyImportDialog
from hesiva.ui.main_window import MainWindow

LOGGER = logging.getLogger(__name__)


class ApplicationStartupError(Exception):
    """Raised when Hesiva cannot prepare its local application infrastructure."""


def create_application_context(
    application_data_directory: Path | None = None,
    *,
    password_hasher: PasswordHasher | None = None,
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
        return build_application_context(database_path, password_hasher=password_hasher)
    except DatabaseStartupError as error:
        raise ApplicationStartupError(str(error)) from error
    except Exception as error:
        raise ApplicationStartupError("Hesiva could not open its local database safely.") from error


def run_startup_flow(application_context: ApplicationContext) -> MainWindow | None:
    """Run the authenticated startup state machine and return an allowed main window."""
    state = application_context.authentication.authentication_state()
    if state is AuthenticationState.INVALID:
        _show_invalid_authentication_state()
        return None

    if state is AuthenticationState.ABSENT:
        if not _business_database_is_empty(application_context):
            _show_invalid_authentication_state()
            return None
        password_dialog = InitialPasswordDialog(application_context.authentication)
        accepted = password_dialog.exec() == QDialog.DialogCode.Accepted
        password_dialog.deleteLater()
        if not accepted:
            return None
        if not _complete_first_run(application_context):
            return None
        return MainWindow(application_context)

    login_dialog = LoginDialog(application_context.authentication)
    authenticated = login_dialog.exec() == QDialog.DialogCode.Accepted
    login_dialog.deleteLater()
    if not authenticated:
        return None

    if state is AuthenticationState.INCOMPLETE:
        if _business_database_is_empty(application_context):
            if not _complete_first_run(application_context):
                return None
        elif not _finalize_setup(application_context):
            return None

    return MainWindow(application_context)


def _business_database_is_empty(application_context: ApplicationContext) -> bool:
    try:
        with application_context.services() as services:
            return services.legacy_import.is_destination_empty()
    except Exception as error:
        raise ApplicationStartupError(
            "Hesiva could not determine the existing data state safely."
        ) from error


def _complete_first_run(application_context: ApplicationContext) -> bool:
    """Complete or resume the frozen empty/import choice without another login."""
    if not _business_database_is_empty(application_context):
        return _finalize_setup(application_context)

    while True:
        choice_dialog = DatabaseChoiceDialog()
        accepted = choice_dialog.exec() == QDialog.DialogCode.Accepted
        choice = choice_dialog.choice
        choice_dialog.deleteLater()
        if not accepted or choice is None:
            return False
        if choice is SetupChoice.EMPTY:
            return _finalize_setup(application_context)

        import_dialog = LegacyImportDialog(application_context)
        import_dialog.exec()
        import_succeeded = import_dialog.import_result is not None
        import_dialog.deleteLater()
        if import_succeeded:
            return _finalize_setup(application_context)


def _finalize_setup(application_context: ApplicationContext) -> bool:
    try:
        application_context.authentication.mark_setup_complete()
    except AuthenticationError:
        LOGGER.exception("Hesiva setup completion configuration could not be published")
        QMessageBox.critical(
            None,
            "Kurulum Tamamlanamadı",
            "Kurulum durumu güvenli şekilde kaydedilemedi. Veriler silinmedi. "
            "Hesiva'yı yeniden açıp parolanızla devam edin.",
        )
        return False
    return True


def _show_invalid_authentication_state() -> None:
    LOGGER.error("Hesiva startup blocked by missing or invalid authentication state")
    QMessageBox.critical(
        None,
        "Kimlik Doğrulama Hatası",
        "Hesiva kimlik doğrulama bilgileri eksik veya geçersiz. "
        "Mevcut veriler değiştirilmedi ve uygulama güvenli olarak açılmadı.",
    )


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

    try:
        main_window = run_startup_flow(application_context)
        if main_window is None:
            return 0
        main_window.show()
        return application.exec()
    except ApplicationStartupError as error:
        LOGGER.error("Hesiva authenticated startup failed: %s", error)
        QMessageBox.critical(None, "Hesiva Startup Error", str(error))
        return 1
    except Exception:
        LOGGER.exception("Unexpected error during authenticated Hesiva startup")
        QMessageBox.critical(
            None,
            "Hesiva Startup Error",
            "Hesiva güvenli şekilde açılamadı. Mevcut veriler değiştirilmedi.",
        )
        return 1
    finally:
        application_context.close()
