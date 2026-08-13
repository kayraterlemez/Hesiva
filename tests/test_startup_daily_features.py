import os
import shutil
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from argon2 import PasswordHasher  # noqa: E402
from argon2.low_level import Type  # noqa: E402
from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402
from sqlalchemy import event  # noqa: E402

from hesiva.application import create_application_context  # noqa: E402
from hesiva.composition import ApplicationContext  # noqa: E402
from hesiva.read_models import StartupReminderSummary  # noqa: E402
from hesiva.services import (  # noqa: E402
    AutomaticBackupService,
    AutomaticBackupStatus,
    BackupError,
    ReminderService,
)
from hesiva.ui import reminder_dialogs  # noqa: E402
from hesiva.ui.main_window import MainWindow  # noqa: E402
from hesiva.ui.reminder_dialogs import StartupReminderSummaryDialog  # noqa: E402


@pytest.fixture(scope="module")
def application() -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        assert isinstance(existing, QApplication)
        return existing
    return QApplication([])


@pytest.fixture
def application_context(tmp_path: Path) -> Iterator[ApplicationContext]:
    hasher = PasswordHasher(
        time_cost=1,
        memory_cost=1024,
        parallelism=1,
        hash_len=16,
        salt_len=8,
        type=Type.ID,
    )
    context = create_application_context(tmp_path / "app-data", password_hasher=hasher)
    context.authentication.create_initial_password("parola", "parola")
    context.authentication.mark_setup_complete()
    try:
        yield context
    finally:
        context.close()


def _automatic_files(context: ApplicationContext) -> list[Path]:
    backup_directory = context._backup_service.default_backup_directory
    return sorted(backup_directory.glob("hesiva_auto_*.zip"))


def _copy_valid_archive(source: Path, destination: Path) -> None:
    shutil.copyfile(source, destination)
    destination.chmod(0o600)


def _create_dated_backup(
    context: ApplicationContext,
    destination: Path,
    timestamp: datetime,
) -> None:
    context._backup_service.create_backup(destination, created_at=timestamp.astimezone())


def _customer_item(window: MainWindow, customer_id: int):
    for row in range(window.customer_list.count()):
        item = window.customer_list.item(row)
        if item.data(Qt.ItemDataRole.UserRole) == customer_id:
            return item
    raise AssertionError(f"Customer {customer_id} is not visible")


def test_daily_backup_uses_controlled_directory_and_one_verified_archive_per_day(
    application_context: ApplicationContext,
    tmp_path: Path,
) -> None:
    manual_directory = tmp_path / "manual-destination"
    manual_directory.mkdir()
    application_context.settings.update_backup_destination_directory(manual_directory)
    first_day = datetime(2026, 8, 13, 9, 15, 30).astimezone()
    database_before = application_context.database_path.read_bytes()
    configuration_before = application_context.configuration_store.path.read_bytes()

    first = AutomaticBackupService(application_context._backup_service).run_daily_backup(
        reference_datetime=first_day
    )
    second = AutomaticBackupService(application_context._backup_service).run_daily_backup(
        reference_datetime=first_day.replace(hour=17)
    )
    third = AutomaticBackupService(application_context._backup_service).run_daily_backup(
        reference_datetime=first_day + timedelta(days=1)
    )

    assert first.status is AutomaticBackupStatus.CREATED
    assert second.status is AutomaticBackupStatus.ALREADY_EXISTS
    assert second.backup_path == first.backup_path
    assert third.status is AutomaticBackupStatus.CREATED
    assert first.backup_path is not None
    assert third.backup_path is not None
    assert first.backup_path.parent == application_context.database_path.parent / "backups"
    assert third.backup_path.parent == first.backup_path.parent
    assert list(manual_directory.iterdir()) == []
    assert len(_automatic_files(application_context)) == 2
    assert application_context.validate_backup(first.backup_path) == first.metadata
    assert application_context.validate_backup(third.backup_path) == third.metadata
    assert application_context.database_path.read_bytes() == database_before
    assert application_context.configuration_store.path.read_bytes() == configuration_before


def test_corrupt_manual_and_safety_archives_do_not_count_as_today_auto_success(
    application_context: ApplicationContext,
) -> None:
    reference = datetime(2026, 8, 13, 10, 0, 0).astimezone()
    backup_directory = application_context.prepare_default_backup_directory()
    corrupt = backup_directory / "hesiva_auto_2026-08-13_08-00-00.zip"
    corrupt.write_bytes(b"not a backup")
    manual = backup_directory / "hesiva_backup_2026-08-13_08-00-00.zip"
    safety = backup_directory / "hesiva_safety_before_restore_2026-08-13_08-00-00.zip"
    application_context.create_backup(manual)
    _copy_valid_archive(manual, safety)

    result = AutomaticBackupService(application_context._backup_service).run_daily_backup(
        reference_datetime=reference
    )

    assert result.status is AutomaticBackupStatus.CREATED
    assert result.backup_path is not None
    assert result.backup_path.name == "hesiva_auto_2026-08-13_10-00-00.zip"
    assert corrupt.read_bytes() == b"not a backup"
    assert manual.is_file()
    assert safety.is_file()


def test_renamed_manual_or_hard_linked_archive_cannot_claim_auto_identity(
    application_context: ApplicationContext,
) -> None:
    reference = datetime(2026, 8, 13, 10, 0, 0).astimezone()
    backup_directory = application_context.prepare_default_backup_directory()
    manual = backup_directory / "hesiva_backup_seed.zip"
    application_context._backup_service.create_backup(
        manual,
        created_at=datetime(2026, 8, 12, 8, 0, 0).astimezone(),
    )
    renamed_manual = backup_directory / "hesiva_auto_2026-08-13_08-00-00.zip"
    _copy_valid_archive(manual, renamed_manual)
    hard_link = backup_directory / "hesiva_auto_2026-08-13_09-00-00.zip"
    os.link(manual, hard_link)

    result = AutomaticBackupService(application_context._backup_service).run_daily_backup(
        reference_datetime=reference
    )

    assert result.status is AutomaticBackupStatus.CREATED
    assert result.backup_path is not None
    assert result.backup_path.name == "hesiva_auto_2026-08-13_10-00-00.zip"
    assert renamed_manual.is_file()
    assert hard_link.is_file()
    assert manual.stat().st_nlink == 2


def test_retention_keeps_old_archive_when_metadata_does_not_match_auto_name(
    application_context: ApplicationContext,
) -> None:
    backup_directory = application_context.prepare_default_backup_directory()
    foreign = backup_directory / "hesiva_auto_2026-06-01_09-00-00.zip"
    application_context._backup_service.create_backup(
        foreign,
        created_at=datetime(2026, 8, 12, 8, 0, 0).astimezone(),
    )

    result = AutomaticBackupService(application_context._backup_service).run_daily_backup(
        reference_datetime=datetime(2026, 8, 13, 10, 0, 0).astimezone()
    )

    assert result.status is AutomaticBackupStatus.CREATED
    assert foreign.is_file()


def test_retention_removes_only_old_verified_auto_archives_after_new_success(
    application_context: ApplicationContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup_directory = application_context.prepare_default_backup_directory()
    seed = backup_directory / "hesiva_backup_seed.zip"
    application_context.create_backup(seed)
    old_auto = backup_directory / "hesiva_auto_2026-07-14_09-00-00.zip"
    recent_auto = backup_directory / "hesiva_auto_2026-07-15_09-00-00.zip"
    cleanup_failure = backup_directory / "hesiva_auto_2026-07-13_09-00-00.zip"
    invalid_old = backup_directory / "hesiva_auto_2026-07-01_09-00-00.zip"
    safety = backup_directory / "hesiva_safety_before_restore_2026-07-01_09-00-00.zip"
    unrelated = backup_directory / "customer-copy.zip"
    _create_dated_backup(
        application_context,
        old_auto,
        datetime(2026, 7, 14, 9, 0, 0).astimezone(),
    )
    _create_dated_backup(
        application_context,
        recent_auto,
        datetime(2026, 7, 15, 9, 0, 0).astimezone(),
    )
    _create_dated_backup(
        application_context,
        cleanup_failure,
        datetime(2026, 7, 13, 9, 0, 0).astimezone(),
    )
    for target in (safety, unrelated):
        _copy_valid_archive(seed, target)
    invalid_old.write_bytes(b"invalid")
    symlink = backup_directory / "hesiva_auto_2026-07-02_09-00-00.zip"
    symlink.symlink_to(seed)

    real_unlink = Path.unlink

    def fail_one_cleanup(path: Path, *args: object, **kwargs: object) -> None:
        if path == cleanup_failure:
            raise PermissionError("synthetic cleanup failure")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_one_cleanup)
    result = AutomaticBackupService(application_context._backup_service).run_daily_backup(
        reference_datetime=datetime(2026, 8, 13, 11, 0, 0).astimezone()
    )

    assert result.status is AutomaticBackupStatus.CREATED
    assert result.backup_path is not None and result.backup_path.is_file()
    assert not old_auto.exists()
    assert recent_auto.is_file()
    assert cleanup_failure.is_file()
    assert invalid_old.read_bytes() == b"invalid"
    assert safety.is_file()
    assert unrelated.is_file()
    assert symlink.is_symlink()
    assert seed.is_file()


def test_retention_does_not_run_when_today_already_has_success(
    application_context: ApplicationContext,
) -> None:
    backup_directory = application_context.prepare_default_backup_directory()
    today = backup_directory / "hesiva_auto_2026-08-13_09-00-00.zip"
    old = backup_directory / "hesiva_auto_2026-06-01_09-00-00.zip"
    _create_dated_backup(
        application_context,
        today,
        datetime(2026, 8, 13, 9, 0, 0).astimezone(),
    )
    _create_dated_backup(
        application_context,
        old,
        datetime(2026, 6, 1, 9, 0, 0).astimezone(),
    )

    result = AutomaticBackupService(application_context._backup_service).run_daily_backup(
        reference_datetime=datetime(2026, 8, 13, 12, 0, 0).astimezone()
    )

    assert result.status is AutomaticBackupStatus.ALREADY_EXISTS
    assert old.is_file()


def test_backup_failure_is_attempted_only_once_and_does_not_mutate_business_data(
    application_context: ApplicationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with application_context.services() as services:
        customer = services.customer.create_customer("Korunan müşteri")
        customer_id = customer.id
    backup_directory = application_context.prepare_default_backup_directory()
    old_auto = backup_directory / "hesiva_auto_2026-06-01_09-00-00.zip"
    _create_dated_backup(
        application_context,
        old_auto,
        datetime(2026, 6, 1, 9, 0, 0).astimezone(),
    )
    calls: list[Path] = []

    def fail_backup(path: Path, *, created_at: datetime | None = None) -> object:
        del created_at
        calls.append(path)
        raise BackupError("synthetic")

    monkeypatch.setattr(application_context._backup_service, "create_backup", fail_backup)
    service = AutomaticBackupService(application_context._backup_service)
    with pytest.raises(BackupError, match="synthetic"):
        service.run_daily_backup(reference_datetime=datetime(2026, 8, 13, 13, 0, 0).astimezone())
    second = service.run_daily_backup(
        reference_datetime=datetime(2026, 8, 13, 13, 5, 0).astimezone()
    )

    assert second.status is AutomaticBackupStatus.ALREADY_ATTEMPTED
    assert len(calls) == 1
    assert old_auto.is_file()
    with application_context.services() as services:
        summaries = services.customer_summary.list_customer_summaries()
    assert [summary.customer_id for summary in summaries] == [customer_id]


@pytest.mark.parametrize(
    ("offsets", "expected_overdue", "expected_today"),
    (([-2, -1], 2, 0), ([0, 0], 0, 2), ([-1, 0], 1, 1)),
)
def test_startup_summary_classifies_overdue_and_today_from_local_reference_date(
    application_context: ApplicationContext,
    offsets: list[int],
    expected_overdue: int,
    expected_today: int,
) -> None:
    reference = date(2026, 8, 13)
    with application_context.services() as services:
        customer = services.customer.create_customer("Yerel tarih sahibi")
        for index, offset in enumerate(offsets):
            services.reminder.create_reminder(
                customer.id,
                reference + timedelta(days=offset),
                f"Hatırlatma {index}",
            )
        summary = services.reminder.get_startup_summary(reference)

    assert summary.overdue_count == expected_overdue
    assert summary.today_count == expected_today


def test_startup_summary_query_counts_all_active_due_states_and_returns_plain_focus(
    application_context: ApplicationContext,
) -> None:
    reference = date(2026, 8, 13)
    with application_context.services() as services:
        archived_owner = services.customer.create_customer("Arşivlenen")
        active_owner = services.customer.create_customer("Aktif")
        services.reminder.create_reminder(
            archived_owner.id,
            reference - timedelta(days=2),
            "Arşivli gecikmiş",
        )
        focus = services.reminder.create_reminder(
            active_owner.id,
            reference - timedelta(days=1),
            "Aktif gecikmiş",
        )
        services.reminder.create_reminder(active_owner.id, reference, "Bugün")
        future = services.reminder.create_reminder(
            active_owner.id,
            reference + timedelta(days=1),
            "Gelecek",
        )
        completed = services.reminder.create_reminder(active_owner.id, reference, "Tamamlanan")
        cancelled = services.reminder.create_reminder(active_owner.id, reference, "İptal edilen")
        services.reminder.complete_reminder(completed.id)
        services.reminder.cancel_reminder(cancelled.id)
        services.customer.archive_customer(archived_owner.id)
        statements: list[str] = []

        def count_statement(*_args: object) -> None:
            statements.append("statement")

        event.listen(application_context.engine, "before_cursor_execute", count_statement)
        try:
            summary = services.reminder.get_startup_summary(reference)
        finally:
            event.remove(application_context.engine, "before_cursor_execute", count_statement)
        active_owner_id = active_owner.id
        focus_id = focus.id
        future_id = future.id

    assert summary == StartupReminderSummary(
        overdue_count=2,
        today_count=1,
        focus_customer_id=active_owner_id,
        focus_reminder_id=focus_id,
    )
    assert summary.total_count == 3
    assert len(statements) == 1
    assert not hasattr(summary, "_sa_instance_state")
    assert future_id != summary.focus_reminder_id


def test_startup_summary_dialog_has_safe_close_default_and_escape(
    application: QApplication,
) -> None:
    dialog = StartupReminderSummaryDialog(
        StartupReminderSummary(3, 2, 1, 1),
    )
    observed: dict[str, object] = {}

    def inspect_and_escape() -> None:
        observed["overdue"] = dialog.overdue_count_label.text()
        observed["today"] = dialog.today_count_label.text()
        observed["overdue_state"] = dialog.overdue_count_label.property("reminderState")
        observed["today_state"] = dialog.today_count_label.property("reminderState")
        observed["default"] = dialog.close_button.isDefault()
        observed["focus"] = dialog.focusWidget() is dialog.close_button
        QTest.keyClick(dialog, Qt.Key.Key_Escape)

    QTimer.singleShot(0, inspect_and_escape)
    result = dialog.exec()

    assert result == QDialog.DialogCode.Rejected
    assert observed == {
        "overdue": "3 gecikmiş hatırlatma",
        "today": "2 bugün yapılacak hatırlatma",
        "overdue_state": "overdue",
        "today_state": "today",
        "default": True,
        "focus": True,
    }
    dialog.deleteLater()
    application.processEvents()


def test_no_due_reminders_shows_no_startup_summary(
    application: QApplication,
    application_context: ApplicationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = date(2026, 8, 13)
    with application_context.services() as services:
        customer = services.customer.create_customer("Gelecek sahibi")
        services.reminder.create_reminder(
            customer.id,
            reference + timedelta(days=1),
            "Yarın",
        )
    monkeypatch.setattr(application_context, "run_automatic_backup", lambda **_kwargs: None)
    monkeypatch.setattr(
        reminder_dialogs,
        "StartupReminderSummaryDialog",
        lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected startup summary")),
    )
    window = MainWindow(application_context, date_provider=lambda: reference)
    window.show()
    application.processEvents()

    window.run_authenticated_startup_actions()

    assert window.isVisible()
    window.close()


def test_main_window_startup_summary_appears_once_and_opens_existing_reminder_ui(
    application: QApplication,
    application_context: ApplicationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = date(2026, 8, 13)
    with application_context.services() as services:
        later_owner = services.customer.create_customer("Sonraki")
        focus_owner = services.customer.create_customer("Önceki")
        later = services.reminder.create_reminder(later_owner.id, reference, "Bugün")
        focus = services.reminder.create_reminder(
            focus_owner.id,
            reference - timedelta(days=1),
            "Gecikmiş",
        )
        focus_owner_id = focus_owner.id
        focus_id = focus.id
        later_id = later.id
    monkeypatch.setattr(application_context, "run_automatic_backup", lambda **_kwargs: None)
    observed: list[StartupReminderSummary] = []

    class AcceptingDialog:
        def __init__(self, summary: StartupReminderSummary, _parent: object) -> None:
            observed.append(summary)

        def exec(self) -> QDialog.DialogCode:
            return QDialog.DialogCode.Accepted

        def deleteLater(self) -> None:
            pass

    monkeypatch.setattr(reminder_dialogs, "StartupReminderSummaryDialog", AcceptingDialog)
    window = MainWindow(application_context, date_provider=lambda: reference)
    window.show()
    application.processEvents()

    window.run_authenticated_startup_actions()
    window.run_authenticated_startup_actions()
    window._refresh_reminders_after_date_rollover()

    assert len(observed) == 1
    assert observed[0].overdue_count == 1
    assert observed[0].today_count == 1
    assert window._selected_customer_id == focus_owner_id
    assert window.customer_tabs.currentWidget() is window.reminders_tab
    assert window._selected_reminder_id() == focus_id
    with application_context.services() as services:
        assert services.reminder.get_reminder(focus_id).completed_at is None
        assert services.reminder.get_reminder(focus_id).cancelled_at is None
        assert services.reminder.get_reminder(later_id).completed_at is None
    window.close()


def test_startup_failures_warn_once_without_closing_main_window(
    application: QApplication,
    application_context: ApplicationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup_calls: list[bool] = []
    reminder_calls: list[bool] = []
    warnings: list[tuple[str, str]] = []

    def fail_backup(**_kwargs: object) -> None:
        backup_calls.append(True)
        raise BackupError("private/path detail")

    def fail_reminders(_service: ReminderService, _reference: date) -> object:
        reminder_calls.append(True)
        raise RuntimeError("SELECT private_detail")

    monkeypatch.setattr(application_context, "run_automatic_backup", fail_backup)
    monkeypatch.setattr(ReminderService, "get_startup_summary", fail_reminders)
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, message: warnings.append((title, message)) or QMessageBox.Ok,
    )
    window = MainWindow(application_context, date_provider=lambda: date(2026, 8, 13))
    window.show()
    application.processEvents()

    window.run_authenticated_startup_actions()
    window.run_authenticated_startup_actions()

    assert window.isVisible()
    assert backup_calls == [True]
    assert reminder_calls == [True]
    assert len(warnings) == 2
    assert "Otomatik yedek oluşturulamadı" in warnings[0][1]
    assert "manuel olarak yedeklemeniz" in warnings[0][1]
    assert "private" not in " ".join(message for _title, message in warnings)
    assert "SELECT" not in " ".join(message for _title, message in warnings)
    window.close()
