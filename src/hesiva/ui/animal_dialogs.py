from dataclasses import dataclass

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from hesiva.read_models import AnimalSummary
from hesiva.ui.presentation import format_animal_identity

SPECIES_SUGGESTIONS = ("Sığır", "Koyun", "Keçi", "At")


@dataclass(frozen=True, slots=True)
class AnimalFormValues:
    """The four optional animal fields exposed by the frozen V1 dialogs."""

    ear_tag: str
    name: str
    species: str
    notes: str


class AnimalFormDialog(QDialog):
    """Shared add/edit animal form without persistence responsibilities."""

    save_requested = Signal()

    def __init__(
        self,
        title: str,
        *,
        initial_values: AnimalFormValues | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("animalFormDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(500)

        values = initial_values or AnimalFormValues("", "", "", "")
        self.ear_tag_input = QLineEdit(values.ear_tag, self)
        self.ear_tag_input.setObjectName("animalEarTagInput")
        self.ear_tag_input.setPlaceholderText("örn: 34 TR 000")

        self.name_input = QLineEdit(values.name, self)
        self.name_input.setObjectName("animalNameInput")
        self.name_input.setPlaceholderText("İsteğe bağlı")

        self.species_input = QComboBox(self)
        self.species_input.setObjectName("animalSpeciesInput")
        self.species_input.setEditable(True)
        self.species_input.addItems(SPECIES_SUGGESTIONS)
        self.species_input.setCurrentIndex(-1)
        self.species_input.lineEdit().setPlaceholderText("Seçiniz veya yazınız...")
        if values.species:
            self.species_input.setEditText(values.species)

        self.notes_input = QPlainTextEdit(values.notes, self)
        self.notes_input.setObjectName("animalNotesInput")
        self.notes_input.setPlaceholderText("İsteğe bağlı")
        self.notes_input.setMaximumHeight(100)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        form.addRow("Küpe No:", self.ear_tag_input)
        form.addRow("Ad:", self.name_input)
        form.addRow("Tür:", self.species_input)
        form.addRow("Notlar:", self.notes_input)

        self.error_label = QLabel("", self)
        self.error_label.setObjectName("animalFormError")
        self.error_label.setProperty("errorMessage", True)
        self.error_label.setWordWrap(True)
        self.error_label.hide()

        buttons = QDialogButtonBox(self)
        self.cancel_button = buttons.addButton(
            "İptal",
            QDialogButtonBox.ButtonRole.RejectRole,
        )
        self.save_button = buttons.addButton(
            "Kaydet",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self.save_button.setObjectName("animalSaveButton")
        self.save_button.setProperty("primary", True)
        self.save_button.setDefault(True)
        self.cancel_button.clicked.connect(self.reject)
        self.save_button.clicked.connect(self._request_save)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        layout.addWidget(buttons)

        QWidget.setTabOrder(self.ear_tag_input, self.name_input)
        QWidget.setTabOrder(self.name_input, self.species_input)
        QWidget.setTabOrder(self.species_input, self.notes_input)
        QWidget.setTabOrder(self.notes_input, self.save_button)
        self.ear_tag_input.setFocus()

    def values(self) -> AnimalFormValues:
        return AnimalFormValues(
            ear_tag=self.ear_tag_input.text(),
            name=self.name_input.text(),
            species=self.species_input.currentText(),
            notes=self.notes_input.toPlainText(),
        )

    def show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.show()

    def _request_save(self) -> None:
        self.error_label.hide()
        self.save_requested.emit()


class ArchivedAnimalsDialog(QDialog):
    """Customer-scoped archived-animal browser with an unarchive request."""

    unarchive_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("archivedAnimalsDialog")
        self.setWindowTitle("Arşivlenmiş Hayvanlar")
        self.setModal(True)
        self.resize(600, 420)

        self.content_stack = QStackedWidget(self)
        self.empty_label = QLabel("Arşivlenmiş hayvan bulunmuyor.", self.content_stack)
        self.empty_label.setObjectName("archivedAnimalEmptyState")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setProperty("emptyStateTitle", True)
        self.animal_list = QListWidget(self.content_stack)
        self.animal_list.setObjectName("archivedAnimalList")
        self.content_stack.addWidget(self.empty_label)
        self.content_stack.addWidget(self.animal_list)

        self.error_label = QLabel("", self)
        self.error_label.setObjectName("archivedAnimalError")
        self.error_label.setProperty("errorMessage", True)
        self.error_label.setWordWrap(True)
        self.error_label.hide()

        buttons = QDialogButtonBox(self)
        self.close_button = buttons.addButton(
            "Kapat",
            QDialogButtonBox.ButtonRole.RejectRole,
        )
        self.unarchive_button = buttons.addButton(
            "Geri Aç",
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        self.unarchive_button.setObjectName("unarchiveAnimalButton")
        self.unarchive_button.setProperty("primary", True)
        self.unarchive_button.setEnabled(False)
        self.close_button.setDefault(True)
        self.close_button.clicked.connect(self.reject)
        self.unarchive_button.clicked.connect(self._request_unarchive)
        self.animal_list.currentItemChanged.connect(self._selection_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        heading = QLabel("Arşivlenmiş Hayvanlar", self)
        heading.setProperty("dialogHeading", True)
        layout.addWidget(heading)
        layout.addWidget(self.content_stack, 1)
        layout.addWidget(self.error_label)
        layout.addWidget(buttons)

    def set_animals(self, animals: list[AnimalSummary]) -> None:
        self.animal_list.clear()
        for animal in animals:
            item = QListWidgetItem(
                f"{format_animal_identity(animal.ear_tag, animal.name, animal.species)}\n"
                f"Küpe No: {animal.ear_tag or '-'}  •  Ad: {animal.name or '-'}  •  "
                f"Tür: {animal.species or '-'}\nNot: {animal.notes or '-'}"
            )
            item.setData(Qt.ItemDataRole.UserRole, animal.animal_id)
            self.animal_list.addItem(item)

        self.content_stack.setCurrentWidget(self.animal_list if animals else self.empty_label)
        self.unarchive_button.setEnabled(False)
        self.error_label.hide()

    def show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.show()

    def _selection_changed(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        self.unarchive_button.setEnabled(current is not None)

    def _request_unarchive(self) -> None:
        current = self.animal_list.currentItem()
        if current is not None:
            self.unarchive_requested.emit(current.data(Qt.ItemDataRole.UserRole))


def confirm_animal_archive(parent: QWidget, animal_label: str) -> bool:
    """Ask for animal archive confirmation with cancellation as the safe default."""
    confirmation = QMessageBox(parent)
    confirmation.setObjectName("archiveAnimalConfirmation")
    confirmation.setIcon(QMessageBox.Icon.Warning)
    confirmation.setWindowTitle("Hayvanı Arşivle")
    confirmation.setText(f"{animal_label} arşivlensin mi?")
    confirmation.setInformativeText(
        "Hayvan aktif listeden kaldırılacak. Bu hayvana bağlı geçmiş hesap "
        "hareketleri silinmeyecek."
    )
    cancel_button = confirmation.addButton("Vazgeç", QMessageBox.ButtonRole.RejectRole)
    archive_button = confirmation.addButton("Arşivle", QMessageBox.ButtonRole.DestructiveRole)
    confirmation.setDefaultButton(cancel_button)
    confirmation.setEscapeButton(cancel_button)
    confirmation.exec()
    return confirmation.clickedButton() is archive_button
