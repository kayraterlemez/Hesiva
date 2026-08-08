import os
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QDateEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QWidget,
)

from hesiva.application import create_application_context  # noqa: E402
from hesiva.composition import ApplicationContext  # noqa: E402
from hesiva.read_models import ArchivedCustomer  # noqa: E402
from hesiva.services import CustomerService, ValidationError  # noqa: E402
from hesiva.ui import customer_dialogs  # noqa: E402
from hesiva.ui.customer_dialogs import (  # noqa: E402
    ArchivedCustomersDialog,
    CustomerFormDialog,
)
from hesiva.ui.main_window import MainWindow  # noqa: E402

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
    context = create_application_context(tmp_path / "customer-crud-application-data")
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


def visible_customer_ids(customer_list: QListWidget) -> list[int]:
    return [
        customer_list.item(row).data(Qt.ItemDataRole.UserRole)
        for row in range(customer_list.count())
    ]


def test_customer_form_has_only_frozen_business_fields_and_requires_name(
    application: QApplication,
) -> None:
    dialog = CustomerFormDialog("Yeni Müşteri")
    save_requests: list[bool] = []
    dialog.save_requested.connect(lambda: save_requests.append(True))

    assert dialog.findChild(QWidget, "customerFullNameInput") is dialog.full_name_input
    assert dialog.findChild(QWidget, "customerPhoneInput") is dialog.phone_input
    assert dialog.findChild(QWidget, "customerAddressInput") is dialog.address_input
    assert dialog.findChild(QWidget, "customerNotesInput") is dialog.notes_input
    assert dialog.findChild(QDateEdit) is None
    assert "Kayıt Tarihi" not in " ".join(
        widget.text() for widget in dialog.findChildren(QWidget) if hasattr(widget, "text")
    )

    QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
    assert save_requests == []
    assert dialog.error_label.text() == "Müşteri adı boş bırakılamaz."
    assert dialog.error_label.isVisibleTo(dialog)

    dialog.full_name_input.setText("  Yeni Müşteri  ")
    dialog.phone_input.setText(" 0532 000 00 00 ")
    dialog.address_input.setPlainText(" Adres ")
    dialog.notes_input.setPlainText(" Not ")
    QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
    application.processEvents()

    assert save_requests == [True]
    assert dialog.values().full_name == "  Yeni Müşteri  "
    assert dialog.values().phone == " 0532 000 00 00 "
    assert dialog.values().address == " Adres "
    assert dialog.values().notes == " Not "
    dialog.close()


def test_new_customer_uses_service_refreshes_and_does_not_invent_registered_on(
    application: QApplication,
    application_context: ApplicationContext,
    window_factory: WindowFactory,
) -> None:
    window = window_factory()
    assert window.new_customer_button.isEnabled()
    assert window.new_customer_action.isEnabled()
    assert window.archived_customers_action.isEnabled()
    assert not window.edit_customer_button.isEnabled()
    assert not window.archive_customer_button.isEnabled()
    interaction: dict[str, object] = {}

    def complete_dialog() -> None:
        dialog = application.activeModalWidget()
        interaction["dialog_type"] = type(dialog)
        interaction["has_date"] = dialog.findChild(QDateEdit) is not None
        assert isinstance(dialog, CustomerFormDialog)
        dialog.full_name_input.setText("  Manual Customer  ")
        dialog.phone_input.setText(" 0532 111 22 33 ")
        dialog.address_input.setPlainText("  Merkez  ")
        dialog.notes_input.setPlainText("  Optional note  ")
        QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)

    QTimer.singleShot(0, complete_dialog)
    window._open_new_customer_dialog()

    assert interaction == {"dialog_type": CustomerFormDialog, "has_date": False}
    assert window.customer_list.count() == 1
    customer_id = window.customer_list.currentItem().data(Qt.ItemDataRole.UserRole)
    assert window._selected_customer_id == customer_id
    assert window.edit_customer_button.isEnabled()
    assert window.archive_customer_button.isEnabled()
    assert window.customer_name_label.text() == "Manual Customer"
    assert window.general_phone_value.text() == "0532 111 22 33"
    assert window.general_address_value.text() == "Merkez"
    assert window.general_notes_value.text() == "Optional note"
    assert window.general_registered_on_value.text() == "-"

    with application_context.services() as services:
        detail = services.customer_detail.get_customer_detail(customer_id)
    assert detail.registered_on is None


def test_edit_populates_all_fields_and_preserves_read_only_registered_on(
    application: QApplication,
    application_context: ApplicationContext,
    window_factory: WindowFactory,
) -> None:
    with application_context.services() as services:
        customer = services.customer.create_customer(
            "Imported Customer",
            phone="111",
            address="Old Address",
            notes="Old Notes",
            registered_on=date(2018, 4, 12),
        )
        customer_id = customer.id

    window = window_factory()
    window.customer_list.setCurrentItem(item_for_customer(window.customer_list, customer_id))
    interaction: dict[str, object] = {}

    def complete_dialog() -> None:
        dialog = application.activeModalWidget()
        assert isinstance(dialog, CustomerFormDialog)
        interaction["initial"] = dialog.values()
        interaction["has_date"] = dialog.findChild(QDateEdit) is not None
        dialog.full_name_input.setText("Edited Customer")
        dialog.phone_input.setText("222")
        dialog.address_input.setPlainText("New Address")
        dialog.notes_input.setPlainText("New Notes")
        QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)

    QTimer.singleShot(0, complete_dialog)
    window._open_edit_customer_dialog()

    initial = interaction["initial"]
    assert initial.full_name == "Imported Customer"
    assert initial.phone == "111"
    assert initial.address == "Old Address"
    assert initial.notes == "Old Notes"
    assert interaction["has_date"] is False
    assert window._selected_customer_id == customer_id
    assert window.customer_list.currentItem().data(Qt.ItemDataRole.UserRole) == customer_id
    assert window.customer_name_label.text() == "Edited Customer"
    assert window.general_phone_value.text() == "222"
    assert window.general_address_value.text() == "New Address"
    assert window.general_notes_value.text() == "New Notes"
    assert window.general_registered_on_value.text() == "12.04.2018"

    with application_context.services() as services:
        detail = services.customer_detail.get_customer_detail(customer_id)
    assert detail.registered_on == date(2018, 4, 12)


def test_archive_requires_confirmation_and_preserves_duplicate_identity_and_history(
    application_context: ApplicationContext,
    window_factory: WindowFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with application_context.services() as services:
        first = services.customer.create_customer("Duplicate Customer", phone="first")
        second = services.customer.create_customer("Duplicate Customer", phone="second")
        transaction = services.transaction.create_debt(
            second.id,
            transaction_date=date(2026, 8, 9),
            description="Historical debt",
            amount_kurus=25_000,
        )
        first_id = first.id
        second_id = second.id
        transaction_id = transaction.id

    window = window_factory()
    window.customer_list.setCurrentItem(item_for_customer(window.customer_list, second_id))
    confirmations: list[str] = []

    def reject_archive(_parent: QWidget, full_name: str) -> bool:
        confirmations.append(full_name)
        return False

    monkeypatch.setattr(customer_dialogs, "confirm_customer_archive", reject_archive)
    window._archive_selected_customer()
    assert confirmations == ["Duplicate Customer"]
    assert second_id in visible_customer_ids(window.customer_list)

    monkeypatch.setattr(
        customer_dialogs,
        "confirm_customer_archive",
        lambda _parent, _full_name: True,
    )
    window._archive_selected_customer()

    assert visible_customer_ids(window.customer_list) == [first_id]
    assert window._selected_customer_id is None
    assert window.customer_detail_stack.currentWidget() is window.no_customer_selected_state
    with application_context.services() as services:
        archived = services.customer.get_customer(second_id)
        historical_transaction = services.transaction.get_transaction(transaction_id)
    assert archived.archived_at is not None
    assert historical_transaction.customer_id == second_id


def test_archive_confirmation_uses_safe_cancel_default(application: QApplication) -> None:
    interaction: dict[str, object] = {}

    def inspect_and_cancel() -> None:
        confirmation = application.activeModalWidget()
        assert isinstance(confirmation, QMessageBox)
        interaction["default"] = confirmation.defaultButton().text()
        interaction["buttons"] = sorted(button.text() for button in confirmation.buttons())
        cancel_button = next(
            button for button in confirmation.buttons() if button.text() == "Vazgeç"
        )
        QTest.mouseClick(cancel_button, Qt.MouseButton.LeftButton)

    QTimer.singleShot(0, inspect_and_cancel)
    accepted = customer_dialogs.confirm_customer_archive(QWidget(), "Safe Customer")

    assert not accepted
    assert interaction == {
        "default": "Vazgeç",
        "buttons": ["Arşivle", "Vazgeç"],
    }


def test_archived_dialog_lists_plain_records_and_unarchives_without_animal_cascade(
    application: QApplication,
    application_context: ApplicationContext,
    window_factory: WindowFactory,
) -> None:
    with application_context.services() as services:
        active = services.customer.create_customer("Active Customer")
        archived = services.customer.create_customer(
            "Archived Customer",
            phone="444",
            registered_on=date(2020, 5, 6),
        )
        animal = services.animal.create_animal(archived.id, name="Archived Animal")
        services.animal.archive_animal(animal.id)
        services.customer.archive_customer(archived.id)
        active_id = active.id
        archived_id = archived.id
        animal_id = animal.id
        archived_records = services.customer.list_archived_customers()

    assert archived_records == [
        ArchivedCustomer(
            customer_id=archived_id,
            full_name="Archived Customer",
            phone="444",
            registered_on=date(2020, 5, 6),
        )
    ]
    assert not hasattr(archived_records[0], "_sa_instance_state")
    interaction: dict[str, object] = {}
    window = window_factory()

    def unarchive_from_dialog() -> None:
        dialog = application.activeModalWidget()
        assert isinstance(dialog, ArchivedCustomersDialog)
        ids = visible_customer_ids(dialog.customer_list)
        interaction["ids"] = ids
        interaction["row_text"] = dialog.customer_list.item(0).text()
        dialog.customer_list.setCurrentRow(0)
        QTest.mouseClick(dialog.unarchive_button, Qt.MouseButton.LeftButton)
        interaction["remaining"] = dialog.customer_list.count()
        dialog.reject()

    QTimer.singleShot(0, unarchive_from_dialog)
    window._open_archived_customers_dialog()

    assert interaction["ids"] == [archived_id]
    assert active_id not in interaction["ids"]
    assert "Telefon: 444" in interaction["row_text"]
    assert "Kayıt Tarihi: 06.05.2020" in interaction["row_text"]
    assert interaction["remaining"] == 0
    assert archived_id in visible_customer_ids(window.customer_list)
    with application_context.services() as services:
        restored_customer = services.customer.get_customer(archived_id)
        still_archived_animal = services.animal.get_animal(animal_id)
    assert restored_customer.archived_at is None
    assert still_archived_animal.archived_at is not None


def test_service_validation_failure_keeps_form_usable_and_does_not_refresh_success(
    application: QApplication,
    window_factory: WindowFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_create(
        _service: CustomerService,
        _full_name: str,
        **_fields: object,
    ) -> object:
        raise ValidationError("Synthetic validation failure")

    monkeypatch.setattr(CustomerService, "create_customer", reject_create)
    window = window_factory()
    interaction: dict[str, object] = {}

    def submit_and_close() -> None:
        dialog = application.activeModalWidget()
        assert isinstance(dialog, CustomerFormDialog)
        dialog.full_name_input.setText("Rejected Customer")
        QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
        interaction["error"] = dialog.error_label.text()
        interaction["still_enabled"] = dialog.full_name_input.isEnabled()
        interaction["value"] = dialog.full_name_input.text()
        dialog.reject()

    QTimer.singleShot(0, submit_and_close)
    window._open_new_customer_dialog()

    assert interaction == {
        "error": "Lütfen gerekli alanları doğru şekilde doldurun.",
        "still_enabled": True,
        "value": "Rejected Customer",
    }
    assert window.customer_list.count() == 0
    assert window._selected_customer_id is None
