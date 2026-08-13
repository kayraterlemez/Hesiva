import inspect
import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from argon2 import PasswordHasher  # noqa: E402
from argon2.low_level import Type  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

from hesiva.application import create_application_context  # noqa: E402
from hesiva.composition import ApplicationContext  # noqa: E402
from hesiva.services import BackupError, RestoreRecoveryRequiredError  # noqa: E402
from hesiva.ui.backup_dialogs import BackupDialog, RestoreConfirmationDialog  # noqa: E402
from hesiva.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def application() -> QApplication:
    existing_application = QApplication.instance()
    if existing_application is not None:
        assert isinstance(existing_application, QApplication)
        return existing_application
    return QApplication([])


@pytest.fixture
def fast_hasher() -> PasswordHasher:
    return PasswordHasher(
        time_cost=1,
        memory_cost=1024,
        parallelism=1,
        hash_len=16,
        salt_len=8,
        type=Type.ID,
    )


@pytest.fixture
def application_context(
    tmp_path: Path,
    fast_hasher: PasswordHasher,
) -> Iterator[ApplicationContext]:
    context = create_application_context(tmp_path / "ui-live", password_hasher=fast_hasher)
    context.authentication.create_initial_password("live-password", "live-password")
    context.authentication.mark_setup_complete()
    try:
        yield context
    finally:
        context.close()


@pytest.fixture
def main_window(
    application: QApplication,
    application_context: ApplicationContext,
) -> Iterator[MainWindow]:
    window = MainWindow(application_context)
    window.show()
    application.processEvents()
    try:
        yield window
    finally:
        window.close()
        application.processEvents()


def _run_backup_dialog(window: MainWindow, operation: Callable[[BackupDialog], None]) -> None:
    def drive_dialog() -> None:
        dialog = next(
            widget
            for widget in QApplication.topLevelWidgets()
            if isinstance(widget, BackupDialog) and widget.isVisible()
        )
        operation(dialog)

    QTimer.singleShot(0, drive_dialog)
    window.backup_action.trigger()


def test_backup_and_restore_dialogs_match_frozen_structure(
    application: QApplication,
    application_context: ApplicationContext,
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "valid.zip"
    metadata = application_context.create_backup(archive_path)
    backup_dialog = BackupDialog(tmp_path)
    confirmation = RestoreConfirmationDialog(metadata)

    assert backup_dialog.windowTitle() == "Yedekleme ve Veri Güvenliği"
    assert backup_dialog.location_input.text() == str(tmp_path)
    assert backup_dialog.change_location_button.text() == "Konumu Değiştir"
    assert backup_dialog.restore_button.text() == "Geri Yükle..."
    assert backup_dialog.create_button.text() == "Yedek Oluştur"
    assert confirmation.windowTitle() == "Yedekten Geri Yükle"
    assert confirmation.cancel_button.isDefault()
    assert not confirmation.restore_button.isDefault()
    assert not confirmation.restore_button.autoDefault()

    backup_dialog.deleteLater()
    confirmation.deleteLater()
    application.processEvents()


def test_file_menu_opens_backup_dialog_and_cancelled_save_is_harmless(
    main_window: MainWindow,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert main_window.backup_action.isEnabled()
    assert main_window.backup_action.text() == "Yedekleme ve Veri Güvenliği"
    monkeypatch.setattr(
        "hesiva.ui.main_window.QFileDialog.getSaveFileName",
        lambda *_args, **_kwargs: ("", ""),
    )

    def cancel_save(dialog: BackupDialog) -> None:
        dialog.create_button.click()
        dialog.reject()

    _run_backup_dialog(main_window, cancel_save)

    assert list(tmp_path.glob("*.zip")) == []


def test_backup_success_is_shown_only_after_real_archive_creation(
    main_window: MainWindow,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "manual-backup.zip"
    monkeypatch.setattr(
        "hesiva.ui.main_window.QFileDialog.getSaveFileName",
        lambda *_args, **_kwargs: (str(destination), "Hesiva Yedeği (*.zip)"),
    )
    displayed_message = ""

    def create_backup(dialog: BackupDialog) -> None:
        nonlocal displayed_message
        dialog.create_button.click()
        displayed_message = dialog.success_label.text()
        dialog.reject()

    _run_backup_dialog(main_window, create_backup)

    assert destination.is_file()
    assert displayed_message.startswith("Son Başarılı Yedek:")


def test_invalid_restore_is_rejected_before_destructive_confirmation(
    main_window: MainWindow,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid_path = tmp_path / "invalid.zip"
    invalid_path.write_text("not a backup", encoding="utf-8")
    monkeypatch.setattr(
        "hesiva.ui.main_window.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(invalid_path), "Hesiva Yedeği (*.zip)"),
    )

    def confirmation_must_not_open(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Invalid backup must not reach confirmation")

    monkeypatch.setattr(
        "hesiva.ui.main_window.backup_dialogs.RestoreConfirmationDialog",
        confirmation_must_not_open,
    )
    displayed_error = ""

    def attempt_restore(dialog: BackupDialog) -> None:
        nonlocal displayed_error
        dialog.restore_button.click()
        displayed_error = dialog.error_label.text()
        dialog.reject()

    _run_backup_dialog(main_window, attempt_restore)

    assert displayed_error.startswith("Geçersiz yedek dosyası")


def test_restore_confirmation_cancel_does_not_call_restore(
    main_window: MainWindow,
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_path = tmp_path / "valid.zip"
    application_context.create_backup(archive_path)
    monkeypatch.setattr(
        "hesiva.ui.main_window.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(archive_path), "Hesiva Yedeği (*.zip)"),
    )
    monkeypatch.setattr(
        RestoreConfirmationDialog,
        "exec",
        lambda _self: QDialog.DialogCode.Rejected,
    )

    def restore_must_not_run(_path: Path) -> None:
        raise AssertionError("Cancelled confirmation must not restore")

    monkeypatch.setattr(application_context, "restore_backup", restore_must_not_run)

    def cancel_confirmation(dialog: BackupDialog) -> None:
        dialog.restore_button.click()
        dialog.reject()

    _run_backup_dialog(main_window, cancel_confirmation)


def test_successful_restore_rebinds_window_to_restored_dataset(
    main_window: MainWindow,
    application_context: ApplicationContext,
    fast_hasher: PasswordHasher,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with application_context.services() as services:
        services.customer.create_customer("Dataset A")
    main_window.refresh_customer_summaries()

    source_context = create_application_context(
        tmp_path / "source-b",
        password_hasher=fast_hasher,
    )
    try:
        source_context.authentication.create_initial_password("source-password", "source-password")
        source_context.authentication.mark_setup_complete()
        with source_context.services() as services:
            services.customer.create_customer("Dataset B")
        archive_path = tmp_path / "dataset-b.zip"
        source_context.create_backup(archive_path)
    finally:
        source_context.close()

    monkeypatch.setattr(
        "hesiva.ui.main_window.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(archive_path), "Hesiva Yedeği (*.zip)"),
    )
    monkeypatch.setattr(
        RestoreConfirmationDialog,
        "exec",
        lambda _self: QDialog.DialogCode.Accepted,
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *_args, **_kwargs: QMessageBox.Ok)

    _run_backup_dialog(main_window, lambda dialog: dialog.restore_button.click())

    assert main_window.customer_list.count() == 1
    item = main_window.customer_list.item(0)
    row = main_window.customer_list.itemWidget(item)
    assert row is not None
    assert "Dataset B" in row.accessibleName()
    assert "Dataset A" not in row.accessibleName()
    assert main_window._selected_customer_id is None


def test_restore_failure_does_not_report_success(
    main_window: MainWindow,
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_path = tmp_path / "valid.zip"
    application_context.create_backup(archive_path)
    monkeypatch.setattr(
        "hesiva.ui.main_window.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(archive_path), "Hesiva Yedeği (*.zip)"),
    )
    monkeypatch.setattr(
        RestoreConfirmationDialog,
        "exec",
        lambda _self: QDialog.DialogCode.Accepted,
    )
    information_calls = 0

    def record_information(*_args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        nonlocal information_calls
        information_calls += 1
        return QMessageBox.Ok

    def fail_restore(_path: Path) -> None:
        raise BackupError("synthetic restore failure")

    monkeypatch.setattr(QMessageBox, "information", record_information)
    monkeypatch.setattr(application_context, "restore_backup", fail_restore)
    displayed_error = ""

    def attempt_restore(dialog: BackupDialog) -> None:
        nonlocal displayed_error
        dialog.restore_button.click()
        displayed_error = dialog.error_label.text()
        dialog.reject()

    _run_backup_dialog(main_window, attempt_restore)

    assert "Geri yükleme tamamlanamadı" in displayed_error
    assert information_calls == 0


def test_restore_recovery_required_closes_window_before_more_changes(
    application: QApplication,
    main_window: MainWindow,
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_path = tmp_path / "valid.zip"
    application_context.create_backup(archive_path)
    monkeypatch.setattr(
        "hesiva.ui.main_window.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(archive_path), "Hesiva Yedeği (*.zip)"),
    )
    monkeypatch.setattr(
        RestoreConfirmationDialog,
        "exec",
        lambda _self: QDialog.DialogCode.Accepted,
    )
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda _parent, title, message: messages.append((title, message)) or QMessageBox.Ok,
    )

    def require_recovery(_path: Path) -> None:
        raise RestoreRecoveryRequiredError("synthetic pending recovery")

    monkeypatch.setattr(application_context, "restore_backup", require_recovery)

    _run_backup_dialog(main_window, lambda dialog: dialog.restore_button.click())
    application.processEvents()

    assert not main_window.isVisible()
    assert messages == [
        (
            "Güvenli Yeniden Başlatma Gerekli",
            "Geri yükleme tamamlanamadı. Güvenli kurtarma sonraki açılışta "
            "tamamlanacaktır; yeni değişiklik yapılmaması için Hesiva şimdi kapanacak.",
        )
    ]


def test_main_window_contains_no_sqlite_or_database_file_manipulation() -> None:
    source = inspect.getsource(MainWindow)

    assert "sqlite3" not in source
    assert "os.replace" not in source
    assert "shutil" not in source
    assert ".backup(" not in source
