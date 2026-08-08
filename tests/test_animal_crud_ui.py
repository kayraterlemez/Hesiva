import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QComboBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QWidget,
)

from hesiva.application import create_application_context  # noqa: E402
from hesiva.composition import ApplicationContext  # noqa: E402
from hesiva.read_models import AnimalSummary  # noqa: E402
from hesiva.services import AnimalService, ValidationError  # noqa: E402
from hesiva.ui import animal_dialogs  # noqa: E402
from hesiva.ui.animal_dialogs import (  # noqa: E402
    AnimalFormDialog,
    ArchivedAnimalsDialog,
)
from hesiva.ui.financial_dialogs import DebtTransactionDialog  # noqa: E402
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
    context = create_application_context(tmp_path / "animal-crud-data")
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


def animal_ids(window: MainWindow) -> list[int]:
    return [
        window.animal_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        for row in range(window.animal_table.rowCount())
    ]


def test_animal_form_has_only_optional_v1_fields_and_accepts_free_text_species(
    application: QApplication,
) -> None:
    dialog = AnimalFormDialog("Hayvan Ekle")
    requests: list[bool] = []
    dialog.save_requested.connect(lambda: requests.append(True))

    assert dialog.findChild(QLineEdit, "animalEarTagInput") is dialog.ear_tag_input
    assert dialog.findChild(QLineEdit, "animalNameInput") is dialog.name_input
    assert dialog.findChild(QComboBox, "animalSpeciesInput") is dialog.species_input
    assert dialog.findChild(QPlainTextEdit, "animalNotesInput") is dialog.notes_input
    assert dialog.species_input.isEditable()
    labels = " ".join(label.text() for label in dialog.findChildren(QLabel))
    assert "*" not in labels
    assert not any(
        forbidden in labels for forbidden in ("Irk", "Cinsiyet", "Doğum", "Teşhis", "Tedavi", "Aşı")
    )

    QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
    application.processEvents()
    assert requests == [True]
    assert dialog.values().ear_tag == ""
    assert dialog.values().name == ""
    assert dialog.values().species == ""
    assert dialog.values().notes == ""

    dialog.species_input.setEditText("Alpaka")
    assert dialog.values().species == "Alpaka"
    dialog.close()


def test_customer_switching_replaces_animal_state_and_uses_stable_ids(
    application_context: ApplicationContext,
    window_factory: WindowFactory,
) -> None:
    with application_context.services() as services:
        first_customer = services.customer.create_customer("First Owner")
        second_customer = services.customer.create_customer("Second Owner")
        first = services.animal.create_animal(
            first_customer.id,
            ear_tag="DUPLICATE",
            name="Same Name",
        )
        second = services.animal.create_animal(
            first_customer.id,
            ear_tag="DUPLICATE",
            name="Same Name",
        )
        third = services.animal.create_animal(
            second_customer.id,
            ear_tag="DUPLICATE",
            name="Same Name",
        )
        first_customer_id = first_customer.id
        second_customer_id = second_customer.id
        first_ids = [first.id, second.id]
        third_id = third.id

    window = window_factory()
    window.customer_list.setCurrentItem(item_for_customer(window.customer_list, first_customer_id))
    assert animal_ids(window) == first_ids
    assert window.animal_count_label.text() == "Toplam Kayıt: 2 hayvan"
    assert all(
        isinstance(record, AnimalSummary) for record in window._animal_summaries_by_id.values()
    )
    assert not hasattr(window, "_session")

    window.animal_table.selectRow(1)
    assert window._selected_animal_id() == second.id
    assert window.edit_animal_button.isEnabled()
    assert window.archive_animal_button.isEnabled()

    window.customer_list.setCurrentItem(item_for_customer(window.customer_list, second_customer_id))
    assert animal_ids(window) == [third_id]
    assert window._selected_animal_id() is None
    assert not window.edit_animal_button.isEnabled()
    assert not window.archive_animal_button.isEnabled()

    window.customer_list.setCurrentItem(None)
    assert window.animal_table.rowCount() == 0
    assert not window.add_animal_button.isEnabled()
    assert not window.archived_animals_button.isEnabled()


def test_completely_blank_animal_form_creates_nullable_optional_fields(
    application: QApplication,
    application_context: ApplicationContext,
    window_factory: WindowFactory,
) -> None:
    with application_context.services() as services:
        customer = services.customer.create_customer("Blank Animal Owner")
        customer_id = customer.id
    window = window_factory()
    window.customer_list.setCurrentItem(item_for_customer(window.customer_list, customer_id))

    def save_blank_form() -> None:
        dialog = application.activeModalWidget()
        assert isinstance(dialog, AnimalFormDialog)
        assert dialog.values().ear_tag == ""
        assert dialog.values().name == ""
        assert dialog.values().species == ""
        assert dialog.values().notes == ""
        QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)

    QTimer.singleShot(0, save_blank_form)
    window._open_add_animal_dialog()

    assert window.animal_table.rowCount() == 1
    assert [window.animal_table.item(0, column).text() for column in range(4)] == [
        "-",
        "-",
        "-",
        "-",
    ]
    with application_context.services() as services:
        records = services.animal.list_active_records(customer_id)
    assert len(records) == 1
    assert records[0].ear_tag is None
    assert records[0].name is None
    assert records[0].species is None
    assert records[0].notes is None


def test_add_edit_archive_history_and_unarchive_workflow(
    application: QApplication,
    application_context: ApplicationContext,
    window_factory: WindowFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with application_context.services() as services:
        customer = services.customer.create_customer("Animal Workflow Owner")
        other_customer = services.customer.create_customer("Other Owner")
        unrelated = services.animal.create_animal(other_customer.id, name="Unrelated")
        customer_id = customer.id
        unrelated_id = unrelated.id

    window = window_factory()
    window.customer_list.setCurrentItem(item_for_customer(window.customer_list, customer_id))
    assert window.animal_list_stack.currentWidget() is window.animal_empty_state
    assert window.add_animal_button.isEnabled()
    assert window.archived_animals_button.isEnabled()

    def add_animal() -> None:
        dialog = application.activeModalWidget()
        assert isinstance(dialog, AnimalFormDialog)
        dialog.ear_tag_input.setText("34 TR 123")
        dialog.name_input.setText("Sarıkız")
        dialog.species_input.setEditText("Sığır")
        dialog.notes_input.setPlainText("İlk not")
        QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)

    QTimer.singleShot(0, add_animal)
    window._open_add_animal_dialog()

    assert window.animal_table.rowCount() == 1
    animal_id = animal_ids(window)[0]
    assert window._selected_animal_id() == animal_id
    assert [window.animal_table.item(0, column).text() for column in range(4)] == [
        "34 TR 123",
        "Sarıkız",
        "Sığır",
        "İlk not",
    ]

    def edit_animal() -> None:
        dialog = application.activeModalWidget()
        assert isinstance(dialog, AnimalFormDialog)
        assert dialog.values().ear_tag == "34 TR 123"
        assert dialog.values().name == "Sarıkız"
        assert dialog.values().species == "Sığır"
        assert dialog.values().notes == "İlk not"
        assert "Müşteri" not in " ".join(label.text() for label in dialog.findChildren(QLabel))
        dialog.ear_tag_input.setText("34 TR 456")
        dialog.name_input.setText("Benekli")
        dialog.species_input.setEditText("Serbest Tür")
        dialog.notes_input.setPlainText("Güncel not")
        QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)

    QTimer.singleShot(0, edit_animal)
    window._open_edit_animal_dialog()

    assert animal_ids(window) == [animal_id]
    assert window._selected_animal_id() == animal_id
    assert [window.animal_table.item(0, column).text() for column in range(4)] == [
        "34 TR 456",
        "Benekli",
        "Serbest Tür",
        "Güncel not",
    ]

    def create_debt_for_animal() -> None:
        dialog = application.activeModalWidget()
        assert isinstance(dialog, DebtTransactionDialog)
        selectable_ids = [
            dialog.animal_combo.itemData(index) for index in range(dialog.animal_combo.count())
        ]
        assert selectable_ids == [None, animal_id]
        dialog.date_input.setDate(QDate(2026, 8, 9))
        dialog.description_input.setText("Hayvana bağlı borç")
        dialog.amount_input.setText("100")
        dialog.animal_combo.setCurrentIndex(dialog.animal_combo.findData(animal_id))
        QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)

    QTimer.singleShot(0, create_debt_for_animal)
    window._open_debt_transaction_dialog()
    assert window.account_history_table.item(0, 3).text() == "34 TR 456 — Benekli"
    window.animal_table.selectRow(0)

    monkeypatch.setattr(
        animal_dialogs,
        "confirm_animal_archive",
        lambda _parent, _label: False,
    )
    window._archive_selected_animal()
    assert animal_ids(window) == [animal_id]

    monkeypatch.setattr(
        animal_dialogs,
        "confirm_animal_archive",
        lambda _parent, _label: True,
    )
    window._archive_selected_animal()
    assert window.animal_table.rowCount() == 0
    assert window.animal_list_stack.currentWidget() is window.animal_empty_state
    assert window.account_history_table.item(0, 3).text() == "34 TR 456 — Benekli"

    excluded_options: list[int | None] = []

    def inspect_archived_exclusion() -> None:
        dialog = application.activeModalWidget()
        assert isinstance(dialog, DebtTransactionDialog)
        excluded_options.extend(
            dialog.animal_combo.itemData(index) for index in range(dialog.animal_combo.count())
        )
        dialog.reject()

    QTimer.singleShot(0, inspect_archived_exclusion)
    window._open_debt_transaction_dialog()
    assert excluded_options == [None]

    archived_interaction: dict[str, object] = {}

    def unarchive_animal() -> None:
        dialog = application.activeModalWidget()
        assert isinstance(dialog, ArchivedAnimalsDialog)
        archived_interaction["ids"] = [
            dialog.animal_list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(dialog.animal_list.count())
        ]
        archived_interaction["text"] = dialog.animal_list.item(0).text()
        dialog.animal_list.setCurrentRow(0)
        QTest.mouseClick(dialog.unarchive_button, Qt.MouseButton.LeftButton)
        archived_interaction["remaining"] = dialog.animal_list.count()
        dialog.reject()

    QTimer.singleShot(0, unarchive_animal)
    window._open_archived_animals_dialog()

    assert archived_interaction["ids"] == [animal_id]
    assert unrelated_id not in archived_interaction["ids"]
    assert "34 TR 456 — Benekli" in archived_interaction["text"]
    assert archived_interaction["remaining"] == 0
    assert animal_ids(window) == [animal_id]
    assert window._selected_animal_id() == animal_id

    included_options: list[int | None] = []

    def inspect_unarchived_inclusion() -> None:
        dialog = application.activeModalWidget()
        assert isinstance(dialog, DebtTransactionDialog)
        included_options.extend(
            dialog.animal_combo.itemData(index) for index in range(dialog.animal_combo.count())
        )
        dialog.reject()

    QTimer.singleShot(0, inspect_unarchived_inclusion)
    window._open_debt_transaction_dialog()
    assert included_options == [None, animal_id]

    with application_context.services() as services:
        records = services.animal.list_active_records(customer_id)
        transactions = services.transaction.list_for_customer(customer_id)
    assert [record.animal_id for record in records] == [animal_id]
    assert records[0].customer_id == customer_id
    assert len(transactions) == 1
    assert transactions[0].animal_id == animal_id


def test_archive_confirmation_uses_safe_cancel_default(application: QApplication) -> None:
    interaction: dict[str, object] = {}

    def inspect_and_cancel() -> None:
        confirmation = application.activeModalWidget()
        assert isinstance(confirmation, QMessageBox)
        interaction["default"] = confirmation.defaultButton().text()
        interaction["buttons"] = sorted(button.text() for button in confirmation.buttons())
        cancel = next(button for button in confirmation.buttons() if button.text() == "Vazgeç")
        QTest.mouseClick(cancel, Qt.MouseButton.LeftButton)

    QTimer.singleShot(0, inspect_and_cancel)
    accepted = animal_dialogs.confirm_animal_archive(QWidget(), "Adsız hayvan")

    assert not accepted
    assert interaction == {"default": "Vazgeç", "buttons": ["Arşivle", "Vazgeç"]}


def test_animal_write_failure_keeps_dialog_open_and_does_not_refresh_success(
    application: QApplication,
    application_context: ApplicationContext,
    window_factory: WindowFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with application_context.services() as services:
        customer = services.customer.create_customer("Failure Owner")
        customer_id = customer.id
    window = window_factory()
    window.customer_list.setCurrentItem(item_for_customer(window.customer_list, customer_id))
    interaction: dict[str, object] = {}

    def reject_create(_service: AnimalService, *_args: object, **_kwargs: object) -> object:
        raise ValidationError("Rejected")

    monkeypatch.setattr(AnimalService, "create_animal", reject_create)

    def attempt_and_close() -> None:
        dialog = application.activeModalWidget()
        assert isinstance(dialog, AnimalFormDialog)
        dialog.name_input.setText("Still usable")
        QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
        interaction["visible"] = dialog.isVisible()
        interaction["error"] = dialog.error_label.text()
        dialog.reject()

    QTimer.singleShot(0, attempt_and_close)
    window._open_add_animal_dialog()

    assert interaction == {
        "visible": True,
        "error": "Hayvan kaydedilemedi. Lütfen yeniden deneyin.",
    }
    assert window.animal_table.rowCount() == 0


def test_animal_read_failure_is_distinct_from_empty_state(
    application_context: ApplicationContext,
    window_factory: WindowFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with application_context.services() as services:
        customer = services.customer.create_customer("Read Failure Owner")
        customer_id = customer.id

    def reject_read(_service: AnimalService, _customer_id: int) -> object:
        raise RuntimeError("technical detail")

    monkeypatch.setattr(AnimalService, "list_active_records", reject_read)
    window = window_factory()
    window.customer_list.setCurrentItem(item_for_customer(window.customer_list, customer_id))

    assert window.animal_list_stack.currentWidget() is window.animal_error_state
    assert window.animal_count_label.text() == "Toplam Kayıt: -"
    assert window.customer_detail_stack.currentWidget() is window.customer_detail_shell
