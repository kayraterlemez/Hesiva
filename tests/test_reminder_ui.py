import os
from collections.abc import Callable, Iterator
from datetime import date, timedelta
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QComboBox,
    QDateEdit,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QTimeEdit,
    QWidget,
)

from hesiva.application import create_application_context  # noqa: E402
from hesiva.composition import ApplicationContext  # noqa: E402
from hesiva.read_models import ReminderSummary  # noqa: E402
from hesiva.services import ReminderService, ValidationError  # noqa: E402
from hesiva.ui import reminder_dialogs  # noqa: E402
from hesiva.ui.main_window import MainWindow  # noqa: E402
from hesiva.ui.reminder_dialogs import ReminderFormDialog  # noqa: E402

WindowFactory = Callable[[], MainWindow]


@pytest.fixture(scope="session")
def application() -> QApplication:
    existing_application = QApplication.instance()
    if existing_application is not None:
        assert isinstance(existing_application, QApplication)
        return existing_application
    return QApplication([])


@pytest.fixture
def application_context(tmp_path: Path) -> Iterator[ApplicationContext]:
    context = create_application_context(tmp_path / "reminder-ui-data")
    try:
        yield context
    finally:
        context.close()


@pytest.fixture
def window_factory(
    application: QApplication,
    application_context: ApplicationContext,
) -> Iterator[WindowFactory]:
    windows: list[MainWindow] = []

    def create_window() -> MainWindow:
        window = MainWindow(application_context)
        window.show()
        application.processEvents()
        windows.append(window)
        return window

    yield create_window

    for window in windows:
        window.close()
    application.processEvents()


def item_for_customer(customer_list: QListWidget, customer_id: int) -> QListWidgetItem:
    for row in range(customer_list.count()):
        item = customer_list.item(row)
        if item.data(Qt.ItemDataRole.UserRole) == customer_id:
            return item
    raise AssertionError(f"Customer {customer_id} is not visible")


def reminder_ids(window: MainWindow) -> list[int]:
    return [
        window.reminder_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        for row in range(window.reminder_table.rowCount())
    ]


def row_for_reminder(window: MainWindow, reminder_id: int) -> int:
    return reminder_ids(window).index(reminder_id)


def set_dialog_date(dialog: ReminderFormDialog, value: date) -> None:
    dialog.date_input.setDate(QDate(value.year, value.month, value.day))


def test_reminder_form_has_exact_required_fields_and_rejects_blank_note(
    application: QApplication,
) -> None:
    dialog = ReminderFormDialog("Yeni Hatırlatma")
    requests: list[bool] = []
    dialog.save_requested.connect(lambda: requests.append(True))

    assert dialog.findChild(QDateEdit, "reminderDateInput") is dialog.date_input
    assert dialog.findChild(QPlainTextEdit, "reminderNoteInput") is dialog.note_input
    assert dialog.findChild(QTimeEdit) is None
    assert dialog.findChild(QComboBox) is None
    labels = " ".join(label.text() for label in dialog.findChildren(QLabel))
    assert "Tarih: *" in labels
    assert "Not: *" in labels
    assert not any(
        forbidden in labels for forbidden in ("Hayvan", "Randevu", "Tekrar", "Saat", "Bildirim")
    )

    QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
    application.processEvents()
    assert requests == []
    assert dialog.error_label.text() == "Hatırlatma notu boş bırakılamaz."

    dialog.note_input.setPlainText("  Geçerli not  ")
    QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
    application.processEvents()
    assert requests == [True]
    assert dialog.values().note == "  Geçerli not  "
    dialog.close()


def test_customer_switching_replaces_reminder_state_and_uses_ids(
    application_context: ApplicationContext,
    window_factory: WindowFactory,
) -> None:
    today = date.today()
    with application_context.services() as services:
        first_customer = services.customer.create_customer("First Reminder Owner")
        second_customer = services.customer.create_customer("Second Reminder Owner")
        first = services.reminder.create_reminder(first_customer.id, today, "Same note")
        second = services.reminder.create_reminder(first_customer.id, today, "Same note")
        third = services.reminder.create_reminder(second_customer.id, today, "Same note")
        first_customer_id = first_customer.id
        second_customer_id = second_customer.id
        first_ids = [first.id, second.id]
        third_id = third.id

    window = window_factory()
    window.customer_list.setCurrentItem(item_for_customer(window.customer_list, first_customer_id))
    assert reminder_ids(window) == first_ids
    assert window.today_reminder_count_label.text() == "Bugün Yapılacak: 2 Hatırlatma"
    assert all(
        isinstance(record, ReminderSummary) for record in window._reminder_summaries_by_id.values()
    )
    assert not hasattr(window, "_session")

    window.reminder_table.selectRow(1)
    assert window._selected_reminder_id() == first_ids[1]
    assert window.edit_reminder_button.isEnabled()
    assert window.complete_reminder_button.isEnabled()
    assert window.cancel_reminder_button.isEnabled()

    window.customer_list.setCurrentItem(item_for_customer(window.customer_list, second_customer_id))
    assert reminder_ids(window) == [third_id]
    assert window._selected_reminder_id() is None
    assert not window.edit_reminder_button.isEnabled()

    window.customer_list.setCurrentItem(None)
    assert window.reminder_table.rowCount() == 0
    assert not window.add_reminder_button.isEnabled()
    assert not window.show_inactive_reminders_checkbox.isEnabled()


def test_selected_customer_reminders_roll_over_at_local_midnight(
    application: QApplication,
    application_context: ApplicationContext,
) -> None:
    current_date = [date(2026, 8, 13)]
    with application_context.services() as services:
        customer = services.customer.create_customer("Midnight Reminder Owner")
        reminder = services.reminder.create_reminder(
            customer.id,
            current_date[0] + timedelta(days=1),
            "Gece yarısı yenilenecek",
        )
        customer_id = customer.id
        reminder_id = reminder.id

    window = MainWindow(application_context, date_provider=lambda: current_date[0])
    window.show()
    application.processEvents()
    window.customer_list.setCurrentItem(item_for_customer(window.customer_list, customer_id))
    window.reminder_table.selectRow(row_for_reminder(window, reminder_id))

    assert window.reminder_table.item(0, 2).text() == "1 gün kaldı"
    assert window.today_reminder_count_label.text() == "Bugün Yapılacak: 0 Hatırlatma"
    assert window._reminder_rollover_timer.isSingleShot()
    assert window._reminder_rollover_timer.isActive()

    current_date[0] += timedelta(days=1)
    window._refresh_reminders_after_date_rollover()

    assert window.reminder_table.item(0, 2).text() == "Bugün"
    assert window.today_reminder_count_label.text() == "Bugün Yapılacak: 1 Hatırlatma"
    assert window._selected_reminder_id() == reminder_id
    assert window._reminder_rollover_timer.isActive()
    window.close()


def test_add_edit_complete_cancel_and_inactive_visibility_workflow(
    application: QApplication,
    application_context: ApplicationContext,
    window_factory: WindowFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    today = date.today()
    with application_context.services() as services:
        customer = services.customer.create_customer("Reminder Workflow Owner")
        overdue = services.reminder.create_reminder(
            customer.id,
            today - timedelta(days=1),
            "Geciken hatırlatma",
        )
        customer_id = customer.id
        overdue_id = overdue.id

    window = window_factory()
    window.customer_list.setCurrentItem(item_for_customer(window.customer_list, customer_id))
    assert reminder_ids(window) == [overdue_id]
    assert window.reminder_table.item(0, 2).text() == "Gecikti"
    assert window.today_reminder_count_label.text() == "Bugün Yapılacak: 0 Hatırlatma"

    def add_future() -> None:
        dialog = application.activeModalWidget()
        assert isinstance(dialog, ReminderFormDialog)
        set_dialog_date(dialog, today + timedelta(days=3))
        dialog.note_input.setPlainText("Gelecek hatırlatma")
        QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)

    QTimer.singleShot(0, add_future)
    window._open_add_reminder_dialog()

    def add_today() -> None:
        dialog = application.activeModalWidget()
        assert isinstance(dialog, ReminderFormDialog)
        set_dialog_date(dialog, today)
        dialog.note_input.setPlainText("Bugünkü hatırlatma")
        QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)

    QTimer.singleShot(0, add_today)
    window._open_add_reminder_dialog()

    with application_context.services() as services:
        active = services.reminder.list_records_for_customer(customer_id)
    future_id = next(
        reminder.reminder_id for reminder in active if reminder.note == "Gelecek hatırlatma"
    )
    today_id = next(
        reminder.reminder_id for reminder in active if reminder.note == "Bugünkü hatırlatma"
    )
    assert reminder_ids(window) == [overdue_id, today_id, future_id]
    assert window.reminder_table.item(row_for_reminder(window, today_id), 2).text() == "Bugün"
    assert (
        window.reminder_table.item(row_for_reminder(window, future_id), 2).text() == "3 gün kaldı"
    )
    assert window.today_reminder_count_label.text() == "Bugün Yapılacak: 1 Hatırlatma"

    window.reminder_table.selectRow(row_for_reminder(window, future_id))

    def edit_future_to_today() -> None:
        dialog = application.activeModalWidget()
        assert isinstance(dialog, ReminderFormDialog)
        assert dialog.values().remind_on == today + timedelta(days=3)
        assert dialog.values().note == "Gelecek hatırlatma"
        set_dialog_date(dialog, today)
        dialog.note_input.setPlainText("Güncellenmiş hatırlatma")
        QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)

    QTimer.singleShot(0, edit_future_to_today)
    window._open_edit_reminder_dialog()

    assert window._selected_reminder_id() == future_id
    assert window.reminder_table.item(row_for_reminder(window, future_id), 1).text() == (
        "Güncellenmiş hatırlatma"
    )
    assert window.today_reminder_count_label.text() == "Bugün Yapılacak: 2 Hatırlatma"

    completed_confirmations: list[int] = []
    monkeypatch.setattr(
        reminder_dialogs,
        "confirm_reminder_completion",
        lambda _parent, reminder: completed_confirmations.append(reminder.reminder_id) or True,
    )
    window._complete_selected_reminder()
    assert completed_confirmations == [future_id]
    assert future_id not in reminder_ids(window)
    assert window.today_reminder_count_label.text() == "Bugün Yapılacak: 1 Hatırlatma"

    window.reminder_table.selectRow(row_for_reminder(window, today_id))
    cancelled_confirmations: list[int] = []
    monkeypatch.setattr(
        reminder_dialogs,
        "confirm_reminder_cancellation",
        lambda _parent, reminder: cancelled_confirmations.append(reminder.reminder_id) or True,
    )
    window._cancel_selected_reminder()
    assert cancelled_confirmations == [today_id]
    assert reminder_ids(window) == [overdue_id]
    assert window.today_reminder_count_label.text() == "Bugün Yapılacak: 0 Hatırlatma"

    window.show_inactive_reminders_checkbox.setChecked(True)
    application.processEvents()
    assert reminder_ids(window) == [overdue_id, future_id, today_id]
    assert window.reminder_table.item(row_for_reminder(window, future_id), 2).text() == (
        "Tamamlandı"
    )
    assert window.reminder_table.item(row_for_reminder(window, today_id), 2).text() == (
        "İptal Edildi"
    )
    assert window.today_reminder_count_label.text() == "Bugün Yapılacak: 0 Hatırlatma"

    window.reminder_table.selectRow(row_for_reminder(window, future_id))
    assert not window.edit_reminder_button.isEnabled()
    assert not window.complete_reminder_button.isEnabled()
    assert not window.cancel_reminder_button.isEnabled()

    with application_context.services() as services:
        all_records = services.reminder.list_records_for_customer(
            customer_id,
            include_inactive=True,
        )
    assert len(all_records) == 3
    completed = next(record for record in all_records if record.reminder_id == future_id)
    cancelled = next(record for record in all_records if record.reminder_id == today_id)
    assert completed.completed_at is not None
    assert completed.cancelled_at is None
    assert cancelled.cancelled_at is not None
    assert cancelled.completed_at is None


@pytest.mark.parametrize(
    ("confirmation", "action_text"),
    (
        (reminder_dialogs.confirm_reminder_completion, "Tamamlandı"),
        (reminder_dialogs.confirm_reminder_cancellation, "İptal Et"),
    ),
)
def test_reminder_confirmations_use_safe_cancel_default(
    application: QApplication,
    confirmation: Callable[[QWidget, ReminderSummary], bool],
    action_text: str,
) -> None:
    reminder = ReminderSummary(
        reminder_id=1,
        customer_id=1,
        remind_on=date.today(),
        note="Onay testi",
        completed_at=None,
        cancelled_at=None,
    )
    interaction: dict[str, object] = {}

    def inspect_and_cancel() -> None:
        message_box = application.activeModalWidget()
        assert isinstance(message_box, QMessageBox)
        interaction["default"] = message_box.defaultButton().text()
        interaction["buttons"] = sorted(button.text() for button in message_box.buttons())
        cancel = next(button for button in message_box.buttons() if button.text() == "Vazgeç")
        QTest.mouseClick(cancel, Qt.MouseButton.LeftButton)

    QTimer.singleShot(0, inspect_and_cancel)
    accepted = confirmation(QWidget(), reminder)

    assert not accepted
    assert interaction == {
        "default": "Vazgeç",
        "buttons": sorted(["Vazgeç", action_text]),
    }


def test_reminder_service_failure_keeps_add_dialog_usable(
    application: QApplication,
    application_context: ApplicationContext,
    window_factory: WindowFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with application_context.services() as services:
        customer = services.customer.create_customer("Reminder Failure Owner")
        customer_id = customer.id
    window = window_factory()
    window.customer_list.setCurrentItem(item_for_customer(window.customer_list, customer_id))
    interaction: dict[str, object] = {}

    def reject_create(_service: ReminderService, *_args: object, **_kwargs: object) -> object:
        raise ValidationError("Rejected")

    monkeypatch.setattr(ReminderService, "create_reminder", reject_create)

    def attempt_and_close() -> None:
        dialog = application.activeModalWidget()
        assert isinstance(dialog, ReminderFormDialog)
        dialog.note_input.setPlainText("Geçerli görünen not")
        QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
        interaction["visible"] = dialog.isVisible()
        interaction["error"] = dialog.error_label.text()
        dialog.reject()

    QTimer.singleShot(0, attempt_and_close)
    window._open_add_reminder_dialog()

    assert interaction == {
        "visible": True,
        "error": "Hatırlatma kaydedilemedi. Lütfen alanları kontrol edin.",
    }
    assert window.reminder_table.rowCount() == 0


def test_reminder_read_failure_is_distinct_from_empty_state(
    application_context: ApplicationContext,
    window_factory: WindowFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with application_context.services() as services:
        customer = services.customer.create_customer("Reminder Read Failure Owner")
        customer_id = customer.id

    def reject_read(_service: ReminderService, *_args: object, **_kwargs: object) -> object:
        raise RuntimeError("technical detail")

    monkeypatch.setattr(ReminderService, "list_records_for_customer", reject_read)
    window = window_factory()
    window.customer_list.setCurrentItem(item_for_customer(window.customer_list, customer_id))

    assert window.reminder_list_stack.currentWidget() is window.reminder_error_state
    assert window.reminder_count_label.text() == "Toplam Hatırlatma: -"
    assert window.today_reminder_count_label.text() == "Bugün Yapılacak: -"
    assert window.customer_detail_stack.currentWidget() is window.customer_detail_shell
