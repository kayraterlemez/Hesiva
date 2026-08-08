from dataclasses import dataclass

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
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

from hesiva.read_models import ArchivedCustomer
from hesiva.ui.presentation import format_date


@dataclass(frozen=True, slots=True)
class CustomerFormValues:
    """The four editable customer values exposed by the frozen V1 dialogs."""

    full_name: str
    phone: str
    address: str
    notes: str


class CustomerFormDialog(QDialog):
    """Shared New/Edit Customer form without persistence responsibilities."""

    save_requested = Signal()

    def __init__(
        self,
        title: str,
        *,
        initial_values: CustomerFormValues | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("customerFormDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(500)

        values = initial_values or CustomerFormValues("", "", "", "")
        self.full_name_input = QLineEdit(values.full_name, self)
        self.full_name_input.setObjectName("customerFullNameInput")
        self.full_name_input.setPlaceholderText("Ad Soyad giriniz...")
        self.full_name_input.setAccessibleName("Ad Soyad")

        self.phone_input = QLineEdit(values.phone, self)
        self.phone_input.setObjectName("customerPhoneInput")
        self.phone_input.setPlaceholderText("örn: 0532 123 4567")
        self.phone_input.setAccessibleName("Telefon")

        self.address_input = QPlainTextEdit(values.address, self)
        self.address_input.setObjectName("customerAddressInput")
        self.address_input.setPlaceholderText("Açık adres giriniz...")
        self.address_input.setAccessibleName("Adres")
        self.address_input.setMaximumHeight(82)

        self.notes_input = QPlainTextEdit(values.notes, self)
        self.notes_input.setObjectName("customerNotesInput")
        self.notes_input.setPlaceholderText("Müşteri hakkında notlar (isteğe bağlı)")
        self.notes_input.setAccessibleName("Notlar")
        self.notes_input.setMaximumHeight(100)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        form.addRow("Ad Soyad: *", self.full_name_input)
        form.addRow("Telefon:", self.phone_input)
        form.addRow("Adres:", self.address_input)
        form.addRow("Notlar:", self.notes_input)

        self.error_label = QLabel("", self)
        self.error_label.setObjectName("customerFormError")
        self.error_label.setProperty("errorMessage", True)
        self.error_label.setWordWrap(True)
        self.error_label.hide()

        button_box = QDialogButtonBox(self)
        button_box.setObjectName("customerFormButtons")
        self.cancel_button = button_box.addButton(
            "İptal",
            QDialogButtonBox.ButtonRole.RejectRole,
        )
        self.save_button = button_box.addButton(
            "Kaydet",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self.save_button.setObjectName("customerSaveButton")
        self.save_button.setProperty("primary", True)
        self.save_button.setDefault(True)
        self.cancel_button.clicked.connect(self.reject)
        self.save_button.clicked.connect(self._request_save)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        layout.addWidget(button_box)

        QWidget.setTabOrder(self.full_name_input, self.phone_input)
        QWidget.setTabOrder(self.phone_input, self.address_input)
        QWidget.setTabOrder(self.address_input, self.notes_input)
        QWidget.setTabOrder(self.notes_input, self.save_button)
        self.full_name_input.setFocus()

    def values(self) -> CustomerFormValues:
        return CustomerFormValues(
            full_name=self.full_name_input.text(),
            phone=self.phone_input.text(),
            address=self.address_input.toPlainText(),
            notes=self.notes_input.toPlainText(),
        )

    def show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.show()

    def _request_save(self) -> None:
        if not self.full_name_input.text().strip():
            self.show_error("Müşteri adı boş bırakılamaz.")
            self.full_name_input.setFocus()
            return
        self.error_label.hide()
        self.save_requested.emit()


class ArchivedCustomersDialog(QDialog):
    """Focused archived-customer browser with an explicit unarchive request."""

    unarchive_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("archivedCustomersDialog")
        self.setWindowTitle("Arşivlenmiş Müşteriler")
        self.setModal(True)
        self.resize(560, 420)

        self.content_stack = QStackedWidget(self)
        self.content_stack.setObjectName("archivedCustomerStack")
        self.empty_label = QLabel("Arşivlenmiş müşteri bulunmuyor.", self.content_stack)
        self.empty_label.setObjectName("archivedCustomerEmptyState")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setProperty("emptyStateTitle", True)
        self.customer_list = QListWidget(self.content_stack)
        self.customer_list.setObjectName("archivedCustomerList")
        self.customer_list.setAccessibleName("Arşivlenmiş müşteri listesi")
        self.content_stack.addWidget(self.empty_label)
        self.content_stack.addWidget(self.customer_list)

        self.error_label = QLabel("", self)
        self.error_label.setObjectName("archivedCustomerError")
        self.error_label.setProperty("errorMessage", True)
        self.error_label.setWordWrap(True)
        self.error_label.hide()

        button_box = QDialogButtonBox(self)
        self.close_button = button_box.addButton(
            "Kapat",
            QDialogButtonBox.ButtonRole.RejectRole,
        )
        self.unarchive_button = button_box.addButton(
            "Geri Aç",
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        self.unarchive_button.setObjectName("unarchiveCustomerButton")
        self.unarchive_button.setProperty("primary", True)
        self.unarchive_button.setEnabled(False)
        self.close_button.setDefault(True)
        self.close_button.clicked.connect(self.reject)
        self.unarchive_button.clicked.connect(self._request_unarchive)
        self.customer_list.currentItemChanged.connect(self._selection_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        heading = QLabel("Arşivlenmiş Müşteriler", self)
        heading.setProperty("dialogHeading", True)
        layout.addWidget(heading)
        layout.addWidget(self.content_stack, 1)
        layout.addWidget(self.error_label)
        layout.addWidget(button_box)

    def set_customers(self, customers: list[ArchivedCustomer]) -> None:
        self.customer_list.clear()
        for customer in customers:
            phone = customer.phone or "-"
            registered_on = format_date(customer.registered_on)
            item = QListWidgetItem(
                f"{customer.full_name}\nTelefon: {phone}  •  Kayıt Tarihi: {registered_on}"
            )
            item.setData(Qt.ItemDataRole.UserRole, customer.customer_id)
            self.customer_list.addItem(item)

        self.content_stack.setCurrentWidget(self.customer_list if customers else self.empty_label)
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
        current = self.customer_list.currentItem()
        if current is None:
            return
        self.unarchive_requested.emit(current.data(Qt.ItemDataRole.UserRole))


def confirm_customer_archive(parent: QWidget, full_name: str) -> bool:
    """Ask for an archive confirmation whose safe default is cancellation."""
    confirmation = QMessageBox(parent)
    confirmation.setObjectName("archiveCustomerConfirmation")
    confirmation.setIcon(QMessageBox.Icon.Warning)
    confirmation.setWindowTitle("Müşteriyi Arşivle")
    confirmation.setText(f"{full_name} arşivlensin mi?")
    confirmation.setInformativeText(
        "Müşteri aktif listeden kaldırılacak. Geçmiş işlemler, hayvanlar, "
        "hatırlatmalar ve hesap hareketleri korunacak."
    )
    cancel_button = confirmation.addButton("Vazgeç", QMessageBox.ButtonRole.RejectRole)
    archive_button = confirmation.addButton("Arşivle", QMessageBox.ButtonRole.DestructiveRole)
    confirmation.setDefaultButton(cancel_button)
    confirmation.setEscapeButton(cancel_button)
    confirmation.exec()
    return confirmation.clickedButton() is archive_button
