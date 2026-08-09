import hashlib
import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from argon2 import PasswordHasher  # noqa: E402
from argon2.low_level import Type  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
)

from hesiva.application import create_application_context  # noqa: E402
from hesiva.composition import ApplicationContext  # noqa: E402
from hesiva.ui.backup_dialogs import BackupDialog  # noqa: E402
from hesiva.ui.auth_dialogs import PasswordChangeDialog  # noqa: E402
from hesiva.ui.main_window import MainWindow  # noqa: E402
from hesiva.ui.settings_dialogs import AboutDialog, SettingsDialog  # noqa: E402
from hesiva.version import get_application_version  # noqa: E402


@pytest.fixture(scope="module")
def application() -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        assert isinstance(existing, QApplication)
        return existing
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
def context(tmp_path: Path, fast_hasher: PasswordHasher) -> Iterator[ApplicationContext]:
    application_context = create_application_context(
        tmp_path / "application-data",
        password_hasher=fast_hasher,
    )
    application_context.authentication.create_initial_password("eski", "eski")
    application_context.authentication.mark_setup_complete()
    try:
        yield application_context
    finally:
        application_context.close()


@pytest.fixture
def window(
    application: QApplication,
    context: ApplicationContext,
) -> Iterator[MainWindow]:
    main_window = MainWindow(context)
    main_window.show()
    application.processEvents()
    try:
        yield main_window
    finally:
        main_window.close()
        application.processEvents()


def _run_modal_action(
    action: Callable[[], None],
    dialog_type: type[QDialog],
    operation: Callable[[QDialog], None],
) -> None:
    def drive_dialog() -> None:
        dialog = next(
            widget
            for widget in QApplication.topLevelWidgets()
            if isinstance(widget, dialog_type) and widget.isVisible()
        )
        operation(dialog)

    QTimer.singleShot(0, drive_dialog)
    action()


def _visible_text(dialog: QDialog) -> str:
    labels = [label.text() for label in dialog.findChildren(QLabel)]
    buttons = [button.text() for button in dialog.findChildren(QPushButton)]
    inputs = [field.text() for field in dialog.findChildren(QLineEdit)]
    return "\n".join([*labels, *buttons, *inputs])


def test_settings_dialog_contains_only_locked_v1_scope(
    application: QApplication,
    context: ApplicationContext,
) -> None:
    settings = context.settings.get_settings()
    dialog = SettingsDialog(settings)

    assert dialog.windowTitle() == "Ayarlar"
    assert dialog.change_password_button.text() == "Parola Değiştir"
    assert dialog.change_backup_location_button.text() == "Konumu Değiştir"
    assert dialog.backup_location_input.text() == str(
        context._backup_service.default_backup_directory
    )
    assert dialog.backup_location_input.isReadOnly()
    assert dialog.version_label.text() == f"Sürüm: {get_application_version()}"
    assert dialog.findChildren(QLineEdit) == [dialog.backup_location_input]
    visible_text = _visible_text(dialog)
    assert context.configuration_store.load().password_hash not in visible_text
    assert "Güvenlik" in visible_text
    assert "Yedekleme" in visible_text
    for excluded in ("Tema", "Dil", "Bulut", "Otomatik Güncelle", "Parola Sıfırla"):
        assert excluded not in visible_text

    dialog.deleteLater()
    application.processEvents()


def test_settings_menu_change_persists_and_immediately_seeds_manual_backup(
    window: MainWindow,
    context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preferred = tmp_path / "preferred-backups"
    preferred.mkdir()
    monkeypatch.setattr(
        "hesiva.ui.main_window.QFileDialog.getExistingDirectory",
        lambda *_args, **_kwargs: str(preferred),
    )

    def change_location(base_dialog: QDialog) -> None:
        dialog = base_dialog
        assert isinstance(dialog, SettingsDialog)
        dialog.change_backup_location_button.click()
        assert dialog.backup_location_input.text() == str(preferred)
        dialog.accept()

    _run_modal_action(window.settings_action.trigger, SettingsDialog, change_location)

    assert context.configuration_store.load().backup_destination_directory == str(preferred)
    assert context.authentication.verify_password("eski")
    assert list(preferred.iterdir()) == []

    def inspect_backup_dialog(base_dialog: QDialog) -> None:
        dialog = base_dialog
        assert isinstance(dialog, BackupDialog)
        assert dialog.destination_directory == preferred
        dialog.reject()

    _run_modal_action(window.backup_action.trigger, BackupDialog, inspect_backup_dialog)


def test_settings_location_cancel_changes_nothing(
    window: MainWindow,
    context: ApplicationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = context.configuration_store.path.read_bytes()
    monkeypatch.setattr(
        "hesiva.ui.main_window.QFileDialog.getExistingDirectory",
        lambda *_args, **_kwargs: "",
    )

    def cancel_location(base_dialog: QDialog) -> None:
        dialog = base_dialog
        assert isinstance(dialog, SettingsDialog)
        dialog.change_backup_location_button.click()
        dialog.reject()

    _run_modal_action(window.settings_action.trigger, SettingsDialog, cancel_location)

    assert context.configuration_store.path.read_bytes() == before


def test_settings_password_change_uses_existing_authenticated_flow(
    window: MainWindow,
    context: ApplicationContext,
    fast_hasher: PasswordHasher,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "hesiva.ui.main_window.QMessageBox.information",
        lambda *_args, **_kwargs: QMessageBox.Ok,
    )

    def change_password(base_dialog: QDialog) -> None:
        settings_dialog = base_dialog
        assert isinstance(settings_dialog, SettingsDialog)

        def submit_password_change() -> None:
            password_dialog = next(
                widget
                for widget in QApplication.topLevelWidgets()
                if isinstance(widget, PasswordChangeDialog) and widget.isVisible()
            )
            password_dialog.current_password_input.setText("eski")
            password_dialog.new_password_input.setText("yeni")
            password_dialog.confirmation_input.setText("yeni")
            password_dialog.change_button.click()

        QTimer.singleShot(0, submit_password_change)
        settings_dialog.change_password_button.click()
        settings_dialog.accept()

    _run_modal_action(window.settings_action.trigger, SettingsDialog, change_password)

    assert context.authentication.verify_password("yeni")
    assert not context.authentication.verify_password("eski")
    reopened = create_application_context(
        context.database_path.parent,
        password_hasher=fast_hasher,
    )
    try:
        assert reopened.authentication.verify_password("yeni")
        assert not reopened.authentication.verify_password("eski")
    finally:
        reopened.close()


def test_unavailable_preference_reports_manual_backup_failure_without_fallback(
    window: MainWindow,
    context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unavailable = tmp_path / "removed-drive"
    unavailable.mkdir()
    context.settings.update_backup_destination_directory(unavailable)
    unavailable.rmdir()
    monkeypatch.setattr(
        "hesiva.ui.main_window.QFileDialog.getSaveFileName",
        lambda *_args, **_kwargs: (
            str(unavailable / "manual.zip"),
            "Hesiva Yedeği (*.zip)",
        ),
    )
    displayed_error = ""

    def attempt_backup(base_dialog: QDialog) -> None:
        nonlocal displayed_error
        dialog = base_dialog
        assert isinstance(dialog, BackupDialog)
        assert dialog.destination_directory == unavailable
        dialog.create_button.click()
        displayed_error = dialog.error_label.text()
        dialog.reject()

    _run_modal_action(window.backup_action.trigger, BackupDialog, attempt_backup)

    assert "Yedekleme konumu kullanılamıyor" in displayed_error
    assert not context._backup_service.default_backup_directory.exists()
    assert not (unavailable / "manual.zip").exists()


def test_about_menu_uses_authoritative_version_without_unapproved_claims_or_writes(
    window: MainWindow,
    context: ApplicationContext,
) -> None:
    database_digest = hashlib.sha256(context.database_path.read_bytes()).hexdigest()
    config_bytes = context.configuration_store.path.read_bytes()
    captured_text = ""

    def inspect_about(base_dialog: QDialog) -> None:
        nonlocal captured_text
        dialog = base_dialog
        assert isinstance(dialog, AboutDialog)
        captured_text = _visible_text(dialog)
        assert dialog.findChildren(QLineEdit) == []
        dialog.accept()

    _run_modal_action(window.about_action.trigger, AboutDialog, inspect_about)

    assert "Hesiva" in captured_text
    assert f"Sürüm {get_application_version()}" in captured_text
    assert "Veteriner müşteri hesap ve bakiye takip uygulaması." in captured_text
    for excluded in (
        "Build 2026.08",
        "Tüm hakları saklıdır",
        "MIT",
        "GPL",
        "bulut",
        "şifreleme",
    ):
        assert excluded not in captured_text
    assert hashlib.sha256(context.database_path.read_bytes()).hexdigest() == database_digest
    assert context.configuration_store.path.read_bytes() == config_bytes


def test_about_uses_supplied_authoritative_version_without_an_internal_literal(
    application: QApplication,
) -> None:
    dialog = AboutDialog("9.8.7")

    assert dialog.version_label.text() == "Sürüm 9.8.7"

    dialog.deleteLater()
    application.processEvents()


def test_final_menu_has_single_settings_password_and_about_entries(
    window: MainWindow,
) -> None:
    menus = {menu.title(): menu for menu in window.menuBar().findChildren(QMenu)}

    assert [action.text() for action in menus["Ayarlar"].actions()] == ["Ayarlar..."]
    assert [action.text() for action in menus["Yardım"].actions()] == ["Hakkında"]
    all_actions = [action.text() for menu in menus.values() for action in menu.actions()]
    assert all_actions.count("Ayarlar...") == 1
    assert all_actions.count("Hakkında") == 1
    assert "Parola Değiştir" not in all_actions
    for preserved in (
        "Yedekleme ve Veri Güvenliği",
        "Eski Verileri İçe Aktar...",
        "Hesap Özeti",
        "Aylık Özet",
        "Yıllık Özet",
    ):
        assert preserved in all_actions
