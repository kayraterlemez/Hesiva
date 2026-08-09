import os
from collections.abc import Iterator
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from argon2 import PasswordHasher  # noqa: E402
from argon2.low_level import Type  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QMenu, QMessageBox  # noqa: E402

from hesiva.application import create_application_context  # noqa: E402
from hesiva.composition import ApplicationContext  # noqa: E402
from hesiva.ui import auth_dialogs  # noqa: E402
from hesiva.ui.auth_dialogs import (  # noqa: E402
    DatabaseChoiceDialog,
    InitialPasswordDialog,
    LoginDialog,
    PasswordChangeDialog,
    SetupChoice,
)
from hesiva.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def application() -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        assert isinstance(existing, QApplication)
        return existing
    return QApplication([])


@pytest.fixture
def context(tmp_path: Path) -> Iterator[ApplicationContext]:
    hasher = PasswordHasher(
        time_cost=1,
        memory_cost=1024,
        parallelism=1,
        hash_len=16,
        salt_len=8,
        type=Type.ID,
    )
    result = create_application_context(tmp_path / "app-data", password_hasher=hasher)
    try:
        yield result
    finally:
        result.close()


def test_initial_password_dialog_uses_hidden_exact_fields_and_validates(
    application: QApplication,
    context: ApplicationContext,
) -> None:
    dialog = InitialPasswordDialog(context.authentication)

    assert dialog.password_input.echoMode() is QLineEdit.EchoMode.Password
    assert dialog.confirmation_input.echoMode() is QLineEdit.EchoMode.Password
    assert dialog.continue_button.text() == "Devam Et"
    assert dialog.exit_button.text() == "Çıkış"
    dialog.password_input.setText("bir")
    dialog.confirmation_input.setText("iki")
    dialog.continue_button.click()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert "eşleşmiyor" in dialog.error_label.text()

    dialog.confirmation_input.setText("bir")
    dialog.continue_button.click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert context.authentication.verify_password("bir")
    dialog.deleteLater()
    application.processEvents()


def test_login_wrong_password_can_retry_successfully(
    application: QApplication,
    context: ApplicationContext,
) -> None:
    context.authentication.create_initial_password("doğru", "doğru")
    dialog = LoginDialog(context.authentication)

    assert dialog.password_input.echoMode() is QLineEdit.EchoMode.Password
    dialog.password_input.setText("yanlış")
    dialog.login_button.click()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert "yanlış" in dialog.error_label.text()
    dialog.password_input.setText("doğru")
    dialog.login_button.click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    dialog.deleteLater()
    application.processEvents()


def test_login_cancel_is_clean_rejection(
    application: QApplication,
    context: ApplicationContext,
) -> None:
    context.authentication.create_initial_password("parola", "parola")
    dialog = LoginDialog(context.authentication)

    dialog.exit_button.click()

    assert dialog.result() == QDialog.DialogCode.Rejected
    dialog.deleteLater()
    application.processEvents()


def test_password_change_dialog_requires_current_and_matching_new_passwords(
    application: QApplication,
    context: ApplicationContext,
) -> None:
    context.authentication.create_initial_password("eski", "eski")
    context.authentication.mark_setup_complete()
    dialog = PasswordChangeDialog(context.authentication)
    fields = (
        dialog.current_password_input,
        dialog.new_password_input,
        dialog.confirmation_input,
    )
    assert all(field.echoMode() is QLineEdit.EchoMode.Password for field in fields)

    dialog.current_password_input.setText("yanlış")
    dialog.new_password_input.setText("yeni")
    dialog.confirmation_input.setText("yeni")
    dialog.change_button.click()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert context.authentication.verify_password("eski")

    dialog.current_password_input.setText("eski")
    dialog.confirmation_input.setText("başka")
    dialog.change_button.click()
    assert dialog.result() != QDialog.DialogCode.Accepted

    dialog.confirmation_input.setText("yeni")
    dialog.change_button.click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert not context.authentication.verify_password("eski")
    assert context.authentication.verify_password("yeni")
    dialog.deleteLater()
    application.processEvents()


def test_database_choice_has_only_frozen_setup_choices(
    application: QApplication,
) -> None:
    dialog = DatabaseChoiceDialog()
    assert dialog.empty_button.text() == "Boş Veritabanıyla Başla"
    assert dialog.import_button.text() == "Eski Veresiye 5 Verilerini İçe Aktar"

    dialog.import_button.click()

    assert dialog.choice is SetupChoice.LEGACY_IMPORT
    assert dialog.result() == QDialog.DialogCode.Accepted
    dialog.deleteLater()
    application.processEvents()


def test_main_window_exposes_only_password_change_in_settings(
    application: QApplication,
    context: ApplicationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context.authentication.create_initial_password("eski", "eski")
    context.authentication.mark_setup_complete()
    window = MainWindow(context)
    window.show()
    application.processEvents()
    settings_menu = next(
        menu for menu in window.menuBar().findChildren(QMenu) if menu.title() == "Ayarlar"
    )
    assert [action.text() for action in settings_menu.actions()] == ["Parola Değiştir"]
    assert "reset" not in window.findChildren(QLineEdit)[0].objectName().lower()

    class FakeChangeDialog:
        def __init__(self, authentication: object, parent: object) -> None:
            assert authentication is context.authentication
            assert parent is window

        def exec(self) -> QDialog.DialogCode:
            return QDialog.DialogCode.Accepted

        def deleteLater(self) -> None:
            pass

    messages: list[str] = []
    monkeypatch.setattr(auth_dialogs, "PasswordChangeDialog", FakeChangeDialog)
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda _parent, _title, message: messages.append(message) or QMessageBox.Ok,
    )
    window.change_password_action.trigger()
    assert messages == ["Hesiva parolası başarıyla değiştirildi."]
    window.close()
    application.processEvents()
