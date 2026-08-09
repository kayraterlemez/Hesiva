"""Isolated end-to-end checks for a frozen Hesiva runtime.

This development-only entry point is built separately from the release artifact.
It exercises production APIs without adding a debug mode to the user executable.
"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from hesiva.application import apply_application_icon, create_application_context  # noqa: E402
from hesiva.database.paths import get_application_data_directory  # noqa: E402
from hesiva.ui.auth_dialogs import (  # noqa: E402
    DatabaseChoiceDialog,
    InitialPasswordDialog,
    LoginDialog,
    PasswordChangeDialog,
    SetupChoice,
)
from hesiva.ui.main_window import MainWindow  # noqa: E402
from hesiva.ui.report_output import write_report_pdf  # noqa: E402
from hesiva.ui.settings_dialogs import AboutDialog, SettingsDialog  # noqa: E402
from hesiva.version import get_application_version  # noqa: E402
from legacy_import_fixtures import create_default_source  # noqa: E402

INITIAL_PASSWORD = "paket-ilk-parola"
CHANGED_PASSWORD = "paket-yeni-parola"
MUTATED_PASSWORD = "paket-gecici-parola"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _exercise_first_run(application: QApplication, work_root: Path) -> tuple[int, Path]:
    expected_data_directory = Path(os.environ["XDG_DATA_HOME"]) / "hesiva"
    _require(
        get_application_data_directory() == expected_data_directory,
        "The packaged Linux user-data path does not honor XDG_DATA_HOME.",
    )
    context = create_application_context()
    try:
        _require(context.database_path.parent == expected_data_directory, "Unexpected DB path.")
        _require(context.database_path.name == "hesiva.db", "Unexpected DB filename.")

        initial = InitialPasswordDialog(context.authentication)
        initial.password_input.setText(INITIAL_PASSWORD)
        initial.confirmation_input.setText(INITIAL_PASSWORD)
        initial.continue_button.click()
        _require(initial.result() == QDialog.DialogCode.Accepted, "Initial password failed.")
        initial.deleteLater()

        choice = DatabaseChoiceDialog()
        choice.empty_button.click()
        _require(choice.choice is SetupChoice.EMPTY, "Empty first-run choice failed.")
        choice.deleteLater()
        context.authentication.mark_setup_complete()

        password_change = PasswordChangeDialog(context.authentication)
        password_change.current_password_input.setText(INITIAL_PASSWORD)
        password_change.new_password_input.setText(CHANGED_PASSWORD)
        password_change.confirmation_input.setText(CHANGED_PASSWORD)
        password_change.change_button.click()
        _require(
            password_change.result() == QDialog.DialogCode.Accepted,
            "Password change failed.",
        )
        password_change.deleteLater()
        _require(
            context.authentication.verify_password(CHANGED_PASSWORD),
            "Changed password cannot be verified.",
        )

        with context.services() as services:
            customer = services.customer.create_customer(
                "Paket Duman Testi",
                phone="000",
                notes="Yalnızca sentetik paket doğrulaması",
            )
            customer_id = customer.id
            services.transaction.create_debt(
                customer_id,
                transaction_date=date(2026, 8, 9),
                description="Sentetik borç",
                amount_kurus=125_050,
            )

        with context.services() as services:
            summary = services.customer_summary.list_customer_summaries()[0]
            statement = services.report.get_customer_statement(
                customer_id,
                period_start=date(2026, 1, 1),
                period_end=date(2026, 12, 31),
            )
        _require(summary.balance_kurus == 125_050, "Packaged balance is incorrect.")

        pdf_path = write_report_pdf(statement, work_root / "packaged-report.pdf")
        _require(pdf_path.read_bytes().startswith(b"%PDF-"), "Packaged PDF is invalid.")

        window = MainWindow(context)
        window.show()
        application.processEvents()
        _require(window.customer_list.count() == 1, "MainWindow did not load the customer.")
        _require("1 müşteri" in window.customer_count_label.text(), "Customer count is wrong.")

        settings = SettingsDialog(context.settings.get_settings(), window)
        settings.show()
        application.processEvents()
        _require(
            settings.version_label.text() == f"Sürüm: {get_application_version()}",
            "Settings version is incorrect.",
        )
        settings.close()

        about = AboutDialog(get_application_version(), window)
        about.show()
        application.processEvents()
        _require(about.product_name_label.text() == "Hesiva", "About product name is wrong.")
        _require(get_application_version() in about.version_label.text(), "About version is wrong.")
        about.close()
        window.close()
        application.processEvents()

        backup_path = work_root / "packaged-backup.zip"
        context.create_backup(backup_path)
        with context.services() as services:
            services.customer.create_customer("Yedekten Sonra Oluşturulan")
        context.authentication.change_password(
            CHANGED_PASSWORD,
            MUTATED_PASSWORD,
            MUTATED_PASSWORD,
        )
        context.restore_backup(backup_path)
        _require(
            context.authentication.verify_password(CHANGED_PASSWORD),
            "Restore did not restore the backed-up credential.",
        )
        _require(
            not context.authentication.verify_password(MUTATED_PASSWORD),
            "Restore retained the post-backup credential.",
        )
        with context.services() as services:
            restored = services.customer_summary.list_customer_summaries()
        _require(len(restored) == 1, "Restore did not restore the business snapshot.")

        if os.name == "posix":
            _require(expected_data_directory.stat().st_mode & 0o777 == 0o700, "Unsafe data mode.")
            _require(context.database_path.stat().st_mode & 0o777 == 0o600, "Unsafe DB mode.")
            _require(
                context.configuration_store.path.stat().st_mode & 0o777 == 0o600,
                "Unsafe config mode.",
            )
        return customer_id, expected_data_directory
    finally:
        context.close()


def _exercise_reopen(application: QApplication) -> None:
    context = create_application_context()
    try:
        login = LoginDialog(context.authentication)
        login.password_input.setText(CHANGED_PASSWORD)
        login.login_button.click()
        _require(login.result() == QDialog.DialogCode.Accepted, "Packaged login failed.")
        login.deleteLater()
        application.processEvents()
    finally:
        context.close()


def _exercise_legacy_import(work_root: Path) -> None:
    import_context = create_application_context(work_root / "import-data")
    try:
        source_path = create_default_source(work_root / "synthetic-source.exa")
        with import_context.services() as services:
            preflight = services.legacy_import.preflight(source_path)
            result = services.legacy_import.import_source(
                source_path,
                expected_source_sha256=preflight.source_sha256,
            )
        _require(result.imported_customer_count == 2, "Synthetic legacy customers failed.")
        _require(result.imported_transaction_count == 3, "Synthetic legacy rows failed.")
    finally:
        import_context.close()


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: HesivaRuntimeSmoke ABSOLUTE_WORK_DIRECTORY", file=sys.stderr)
        return 2
    work_root = Path(sys.argv[1]).resolve()
    work_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    application = QApplication.instance() or QApplication([])
    _require(apply_application_icon(application), "Packaged application icon is unavailable.")
    _require(not application.windowIcon().isNull(), "Packaged application icon is invalid.")
    _exercise_first_run(application, work_root)
    _exercise_reopen(application)
    _exercise_legacy_import(work_root)
    print(f"PACKAGED_SMOKE_OK version={get_application_version()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
