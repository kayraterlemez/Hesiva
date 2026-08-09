import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from argon2 import PasswordHasher  # noqa: E402
from argon2.low_level import Type  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

from hesiva import application as application_module  # noqa: E402
from hesiva.application import create_application_context, run_startup_flow  # noqa: E402
from hesiva.composition import ApplicationContext  # noqa: E402
from hesiva.services import AuthenticationState, CredentialPersistenceError  # noqa: E402
from hesiva.ui.auth_dialogs import SetupChoice  # noqa: E402


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
    result = create_application_context(tmp_path / "app-data", password_hasher=fast_hasher)
    try:
        yield result
    finally:
        result.close()


class _DialogResult:
    def __init__(self, result: QDialog.DialogCode) -> None:
        self._result = result

    def exec(self) -> QDialog.DialogCode:
        return self._result

    def deleteLater(self) -> None:
        pass


def _install_main_window_spy(monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
    class FakeMainWindow:
        def __init__(self, _context: ApplicationContext) -> None:
            calls.append("main")

    monkeypatch.setattr(application_module, "MainWindow", FakeMainWindow)


def _install_login(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[str],
    *,
    result: QDialog.DialogCode = QDialog.DialogCode.Accepted,
) -> None:
    class FakeLoginDialog(_DialogResult):
        def __init__(self, _authentication: object) -> None:
            calls.append("login")
            super().__init__(result)

    monkeypatch.setattr(application_module, "LoginDialog", FakeLoginDialog)


def _install_choice(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[str],
    choice: SetupChoice | None,
    *,
    result: QDialog.DialogCode = QDialog.DialogCode.Accepted,
) -> None:
    class FakeChoiceDialog(_DialogResult):
        def __init__(self) -> None:
            calls.append("choice")
            self.choice = choice
            super().__init__(result)

    monkeypatch.setattr(application_module, "DatabaseChoiceDialog", FakeChoiceDialog)


def test_fresh_first_run_creates_password_then_empty_setup_without_redundant_login(
    application: QApplication,
    context: ApplicationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class FakeInitialPasswordDialog(_DialogResult):
        def __init__(self, authentication: object) -> None:
            calls.append("password")
            authentication.create_initial_password("parola", "parola")
            super().__init__(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(application_module, "InitialPasswordDialog", FakeInitialPasswordDialog)
    _install_choice(monkeypatch, calls, SetupChoice.EMPTY)
    _install_main_window_spy(monkeypatch, calls)
    monkeypatch.setattr(
        application_module,
        "LoginDialog",
        lambda *_args: (_ for _ in ()).throw(AssertionError("redundant login")),
    )

    window = run_startup_flow(context)

    assert window is not None
    assert calls == ["password", "choice", "main"]
    assert context.authentication.authentication_state() is AuthenticationState.COMPLETE


def test_cancelled_database_choice_keeps_durable_incomplete_credential(
    application: QApplication,
    context: ApplicationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeInitialPasswordDialog(_DialogResult):
        def __init__(self, authentication: object) -> None:
            authentication.create_initial_password("parola", "parola")
            super().__init__(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(application_module, "InitialPasswordDialog", FakeInitialPasswordDialog)
    _install_choice(
        monkeypatch,
        [],
        None,
        result=QDialog.DialogCode.Rejected,
    )

    assert run_startup_flow(context) is None
    assert context.authentication.authentication_state() is AuthenticationState.INCOMPLETE
    assert context.authentication.verify_password("parola")


def test_reopen_incomplete_setup_requires_login_then_resumes_choice(
    application: QApplication,
    context: ApplicationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context.authentication.create_initial_password("parola", "parola")
    calls: list[str] = []
    _install_login(monkeypatch, calls)
    _install_choice(monkeypatch, calls, SetupChoice.EMPTY)
    _install_main_window_spy(monkeypatch, calls)

    assert run_startup_flow(context) is not None
    assert calls == ["login", "choice", "main"]
    assert context.authentication.authentication_state() is AuthenticationState.COMPLETE


def test_wrong_or_cancelled_incomplete_login_blocks_setup_and_main_window(
    application: QApplication,
    context: ApplicationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context.authentication.create_initial_password("parola", "parola")
    calls: list[str] = []
    _install_login(monkeypatch, calls, result=QDialog.DialogCode.Rejected)
    _install_choice(monkeypatch, calls, SetupChoice.EMPTY)
    _install_main_window_spy(monkeypatch, calls)

    assert run_startup_flow(context) is None
    assert calls == ["login"]
    assert context.authentication.authentication_state() is AuthenticationState.INCOMPLETE


def test_complete_setup_always_gates_main_window_behind_login(
    application: QApplication,
    context: ApplicationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context.authentication.create_initial_password("parola", "parola")
    context.authentication.mark_setup_complete()
    calls: list[str] = []
    _install_login(monkeypatch, calls)
    _install_main_window_spy(monkeypatch, calls)

    assert run_startup_flow(context) is not None
    assert calls == ["login", "main"]


@pytest.mark.parametrize("malformed", [False, True])
def test_populated_database_without_usable_credential_is_blocked_without_modification(
    application: QApplication,
    context: ApplicationContext,
    monkeypatch: pytest.MonkeyPatch,
    malformed: bool,
) -> None:
    with context.services() as services:
        services.customer.create_customer("Korunan Müşteri")
    if malformed:
        context.configuration_store.path.write_text("{malformed", encoding="utf-8")
    database_before = context.database_path.read_bytes()
    errors: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda _parent, _title, message: errors.append(message) or QMessageBox.Ok,
    )
    monkeypatch.setattr(
        application_module,
        "InitialPasswordDialog",
        lambda *_args: (_ for _ in ()).throw(AssertionError("password creation offered")),
    )
    monkeypatch.setattr(
        application_module,
        "MainWindow",
        lambda *_args: (_ for _ in ()).throw(AssertionError("main window exposed")),
    )

    assert run_startup_flow(context) is None
    assert errors and "değiştirilmedi" in errors[0]
    assert context.database_path.read_bytes() == database_before
    with context.services() as services:
        assert services.customer_summary.list_customer_summaries()[0].full_name == "Korunan Müşteri"


def test_incomplete_credential_with_populated_database_finalizes_without_duplicate_import(
    application: QApplication,
    context: ApplicationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context.authentication.create_initial_password("parola", "parola")
    with context.services() as services:
        services.customer.create_customer("İçe Aktarılan")
    calls: list[str] = []
    _install_login(monkeypatch, calls)
    _install_main_window_spy(monkeypatch, calls)
    monkeypatch.setattr(
        application_module,
        "DatabaseChoiceDialog",
        lambda: (_ for _ in ()).throw(AssertionError("duplicate setup choice")),
    )
    monkeypatch.setattr(
        application_module,
        "LegacyImportDialog",
        lambda *_args: (_ for _ in ()).throw(AssertionError("duplicate import")),
    )

    assert run_startup_flow(context) is not None
    assert calls == ["login", "main"]
    assert context.authentication.authentication_state() is AuthenticationState.COMPLETE


def test_successful_import_path_marks_complete_only_after_import_result(
    application: QApplication,
    context: ApplicationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context.authentication.create_initial_password("parola", "parola")
    calls: list[str] = []
    _install_login(monkeypatch, calls)
    _install_choice(monkeypatch, calls, SetupChoice.LEGACY_IMPORT)
    _install_main_window_spy(monkeypatch, calls)

    class FakeImportDialog(_DialogResult):
        def __init__(self, application_context: ApplicationContext) -> None:
            calls.append("import")
            with application_context.services() as services:
                services.customer.create_customer("Sentetik İçe Aktarım")
            self.import_result = object()
            super().__init__(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(application_module, "LegacyImportDialog", FakeImportDialog)

    assert run_startup_flow(context) is not None
    assert calls == ["login", "choice", "import", "main"]
    assert context.authentication.authentication_state() is AuthenticationState.COMPLETE


def test_import_success_then_final_config_failure_has_no_false_success_and_recovers(
    application: QApplication,
    context: ApplicationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context.authentication.create_initial_password("parola", "parola")
    calls: list[str] = []
    _install_login(monkeypatch, calls)
    _install_choice(monkeypatch, calls, SetupChoice.LEGACY_IMPORT)
    _install_main_window_spy(monkeypatch, calls)

    class FakeImportDialog(_DialogResult):
        def __init__(self, application_context: ApplicationContext) -> None:
            with application_context.services() as services:
                services.customer.create_customer("Başarılı İçe Aktarım")
            self.import_result = object()
            super().__init__(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(application_module, "LegacyImportDialog", FakeImportDialog)
    real_mark_complete = context.authentication.mark_setup_complete
    monkeypatch.setattr(
        context.authentication,
        "mark_setup_complete",
        lambda: (_ for _ in ()).throw(CredentialPersistenceError("synthetic")),
    )
    monkeypatch.setattr(QMessageBox, "critical", lambda *_args: QMessageBox.Ok)

    assert run_startup_flow(context) is None
    assert context.authentication.authentication_state() is AuthenticationState.INCOMPLETE
    with context.services() as services:
        assert services.customer_summary.list_customer_summaries()[0].full_name == (
            "Başarılı İçe Aktarım"
        )

    monkeypatch.setattr(context.authentication, "mark_setup_complete", real_mark_complete)
    calls.clear()
    _install_login(monkeypatch, calls)
    _install_main_window_spy(monkeypatch, calls)

    assert run_startup_flow(context) is not None
    assert calls == ["login", "main"]
    assert context.authentication.authentication_state() is AuthenticationState.COMPLETE


def test_empty_choice_final_config_failure_remains_recoverable_and_empty(
    application: QApplication,
    context: ApplicationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context.authentication.create_initial_password("parola", "parola")
    _install_login(monkeypatch, [])
    _install_choice(monkeypatch, [], SetupChoice.EMPTY)
    monkeypatch.setattr(
        context.authentication,
        "mark_setup_complete",
        lambda: (_ for _ in ()).throw(CredentialPersistenceError("synthetic")),
    )
    monkeypatch.setattr(QMessageBox, "critical", lambda *_args: QMessageBox.Ok)

    assert run_startup_flow(context) is None
    assert context.authentication.authentication_state() is AuthenticationState.INCOMPLETE
    with context.services() as services:
        assert services.legacy_import.is_destination_empty()


def test_cancelled_import_keeps_incomplete_setup(
    application: QApplication,
    context: ApplicationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context.authentication.create_initial_password("parola", "parola")
    _install_login(monkeypatch, [])
    choices = iter((SetupChoice.LEGACY_IMPORT, None))

    class FakeChoiceDialog(_DialogResult):
        def __init__(self) -> None:
            self.choice = next(choices)
            result = (
                QDialog.DialogCode.Accepted
                if self.choice is not None
                else QDialog.DialogCode.Rejected
            )
            super().__init__(result)

    class FakeCancelledImport(_DialogResult):
        def __init__(self, _context: ApplicationContext) -> None:
            self.import_result = None
            super().__init__(QDialog.DialogCode.Rejected)

    monkeypatch.setattr(application_module, "DatabaseChoiceDialog", FakeChoiceDialog)
    monkeypatch.setattr(application_module, "LegacyImportDialog", FakeCancelledImport)

    assert run_startup_flow(context) is None
    assert context.authentication.authentication_state() is AuthenticationState.INCOMPLETE
    with context.services() as services:
        assert services.legacy_import.is_destination_empty()


def test_persisted_config_contains_no_reset_or_recovery_material(
    context: ApplicationContext,
) -> None:
    context.authentication.create_initial_password("parola", "parola")
    payload = json.loads(context.configuration_store.path.read_text(encoding="utf-8"))

    assert set(payload["authentication"]) == {"password_hash", "setup_complete"}
    serialized = json.dumps(payload).lower()
    assert "reset" not in serialized
    assert "recovery" not in serialized
    assert "hint" not in serialized


def test_main_closes_application_context_when_authentication_flow_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeApplication:
        def __init__(self, _arguments: list[str]) -> None:
            pass

    class FakeContext:
        closed = False

        def close(self) -> None:
            self.closed = True

    context = FakeContext()
    monkeypatch.setattr(application_module, "QApplication", FakeApplication)
    monkeypatch.setattr(application_module, "create_application_context", lambda: context)
    monkeypatch.setattr(application_module, "run_startup_flow", lambda _context: None)

    assert application_module.main() == 0
    assert context.closed
