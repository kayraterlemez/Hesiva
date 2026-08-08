from dataclasses import dataclass
from datetime import date

from PySide6.QtCore import QDate, Signal, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from hesiva.read_models import AccountHistoryRow, AnimalOption
from hesiva.ui.presentation import (
    MoneyInputError,
    format_animal_display,
    format_balance_kurus,
    format_date,
    format_money_kurus,
    parse_money_kurus,
)


@dataclass(frozen=True, slots=True)
class DebtFormValues:
    transaction_date: date
    description: str
    amount_kurus: int
    animal_id: int | None
    note: str


@dataclass(frozen=True, slots=True)
class PaymentFormValues:
    transaction_date: date
    description: str
    amount_kurus: int


class DebtTransactionDialog(QDialog):
    """Frozen V1 debt-entry form; persistence remains with MainWindow services."""

    save_requested = Signal()

    def __init__(
        self,
        customer_name: str,
        animal_options: list[AnimalOption],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("debtTransactionDialog")
        self.setWindowTitle("Yeni İşlem")
        self.setModal(True)
        self.setMinimumWidth(520)

        self.customer_input = QLineEdit(customer_name, self)
        self.customer_input.setObjectName("debtCustomerInput")
        self.customer_input.setReadOnly(True)

        self.date_input = QDateEdit(QDate.currentDate(), self)
        self.date_input.setObjectName("debtDateInput")
        self.date_input.setCalendarPopup(True)
        self.date_input.setDisplayFormat("dd.MM.yyyy")

        self.description_input = QLineEdit(self)
        self.description_input.setObjectName("debtDescriptionInput")
        self.description_input.setPlaceholderText("örn: Doğum + İlaç")

        self.amount_input = QLineEdit(self)
        self.amount_input.setObjectName("debtAmountInput")
        self.amount_input.setPlaceholderText("0,00")
        self.amount_input.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.animal_combo = QComboBox(self)
        self.animal_combo.setObjectName("debtAnimalCombo")
        self.animal_combo.addItem("Hayvan Yok", None)
        for animal in animal_options:
            self.animal_combo.addItem(
                format_animal_display(animal.ear_tag, animal.name, animal.species),
                animal.animal_id,
            )

        self.notes_input = QPlainTextEdit(self)
        self.notes_input.setObjectName("debtNotesInput")
        self.notes_input.setPlaceholderText("İsteğe bağlı")
        self.notes_input.setMaximumHeight(90)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        form.addRow("Müşteri:", self.customer_input)
        form.addRow("Tarih: *", self.date_input)
        form.addRow("Açıklama: *", self.description_input)
        form.addRow("Tutar: *", self.amount_input)
        form.addRow("Hayvan:", self.animal_combo)
        form.addRow("Notlar:", self.notes_input)

        self.error_label = _create_error_label(self, "debtFormError")
        button_box, self.cancel_button, self.save_button = _create_form_buttons(
            self,
            "Kaydet",
        )
        self.cancel_button.clicked.connect(self.reject)
        self.save_button.clicked.connect(self._request_save)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        layout.addWidget(button_box)
        self.description_input.setFocus()

    def values(self) -> DebtFormValues:
        return DebtFormValues(
            transaction_date=self.date_input.date().toPython(),
            description=self.description_input.text(),
            amount_kurus=parse_money_kurus(self.amount_input.text()),
            animal_id=self.animal_combo.currentData(),
            note=self.notes_input.toPlainText(),
        )

    def show_error(self, message: str) -> None:
        _show_error(self.error_label, message)

    def _request_save(self) -> None:
        if not self.description_input.text().strip():
            self.show_error("Açıklama boş bırakılamaz.")
            self.description_input.setFocus()
            return
        try:
            parse_money_kurus(self.amount_input.text())
        except MoneyInputError as error:
            self.show_error(str(error))
            self.amount_input.setFocus()
            return
        self.error_label.hide()
        self.save_requested.emit()


class PaymentDialog(QDialog):
    """Frozen V1 account-level payment form with a positive magnitude input."""

    save_requested = Signal()

    def __init__(
        self,
        customer_name: str,
        current_balance_kurus: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._current_balance_kurus = current_balance_kurus
        self.setObjectName("paymentDialog")
        self.setWindowTitle("Ödeme Al")
        self.setModal(True)
        self.setMinimumWidth(520)

        self.customer_input = QLineEdit(customer_name, self)
        self.customer_input.setObjectName("paymentCustomerInput")
        self.customer_input.setReadOnly(True)
        self.date_input = QDateEdit(QDate.currentDate(), self)
        self.date_input.setObjectName("paymentDateInput")
        self.date_input.setCalendarPopup(True)
        self.date_input.setDisplayFormat("dd.MM.yyyy")
        self.amount_input = QLineEdit(self)
        self.amount_input.setObjectName("paymentAmountInput")
        self.amount_input.setPlaceholderText("0,00")
        self.amount_input.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.description_input = QLineEdit("Tahsilat", self)
        self.description_input.setObjectName("paymentDescriptionInput")

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        form.addRow("Müşteri:", self.customer_input)
        form.addRow("Tarih: *", self.date_input)
        form.addRow("Tutar: *", self.amount_input)
        form.addRow("Açıklama: *", self.description_input)

        self.current_balance_value = QLabel(
            format_balance_kurus(current_balance_kurus),
            self,
        )
        self.current_balance_value.setObjectName("paymentCurrentBalance")
        self.after_balance_value = QLabel("-", self)
        self.after_balance_value.setObjectName("paymentAfterBalance")
        balance_form = QFormLayout()
        balance_form.addRow("Mevcut Bakiye:", self.current_balance_value)
        balance_form.addRow("Ödeme Sonrası Bakiye:", self.after_balance_value)

        self.error_label = _create_error_label(self, "paymentFormError")
        button_box, self.cancel_button, self.save_button = _create_form_buttons(
            self,
            "Ödemeyi Kaydet",
        )
        self.cancel_button.clicked.connect(self.reject)
        self.save_button.clicked.connect(self._request_save)
        self.amount_input.textChanged.connect(self._update_balance_preview)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addLayout(form)
        layout.addLayout(balance_form)
        layout.addWidget(self.error_label)
        layout.addWidget(button_box)
        self.amount_input.setFocus()

    def values(self) -> PaymentFormValues:
        return PaymentFormValues(
            transaction_date=self.date_input.date().toPython(),
            description=self.description_input.text(),
            amount_kurus=parse_money_kurus(self.amount_input.text()),
        )

    def show_error(self, message: str) -> None:
        _show_error(self.error_label, message)

    def _request_save(self) -> None:
        if not self.description_input.text().strip():
            self.show_error("Açıklama boş bırakılamaz.")
            self.description_input.setFocus()
            return
        try:
            parse_money_kurus(self.amount_input.text())
        except MoneyInputError as error:
            self.show_error(str(error))
            self.amount_input.setFocus()
            return
        self.error_label.hide()
        self.save_requested.emit()

    def _update_balance_preview(self, value: str) -> None:
        try:
            amount_kurus = parse_money_kurus(value)
        except MoneyInputError:
            self.after_balance_value.setText("-")
            return
        self.after_balance_value.setText(
            format_balance_kurus(self._current_balance_kurus - amount_kurus)
        )


class VoidTransactionDialog(QDialog):
    """History-preserving transaction void confirmation with an optional reason."""

    void_requested = Signal()

    def __init__(
        self,
        transaction: AccountHistoryRow,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("voidTransactionDialog")
        self.setWindowTitle("İşlemi İptal Et")
        self.setModal(True)
        self.setMinimumWidth(520)

        details = QFormLayout()
        details.addRow("Tarih:", QLabel(format_date(transaction.transaction_date), self))
        details.addRow("Açıklama:", QLabel(transaction.description, self))
        details.addRow(
            "Tutar:",
            QLabel(format_money_kurus(abs(transaction.amount_kurus)), self),
        )
        self.reason_input = QPlainTextEdit(self)
        self.reason_input.setObjectName("voidReasonInput")
        self.reason_input.setPlaceholderText("İsteğe bağlı iptal gerekçesi")
        self.reason_input.setMaximumHeight(90)
        details.addRow("İptal Nedeni:", self.reason_input)

        warning = QLabel(
            "İşlem geçmişten silinmeyecek ancak aktif bakiyeyi artık etkilemeyecek.",
            self,
        )
        warning.setWordWrap(True)
        warning.setProperty("warningMessage", True)

        self.error_label = _create_error_label(self, "voidFormError")

        button_box = QDialogButtonBox(self)
        self.cancel_button = button_box.addButton(
            "Vazgeç",
            QDialogButtonBox.ButtonRole.RejectRole,
        )
        self.void_button = button_box.addButton(
            "İşlemi İptal Et",
            QDialogButtonBox.ButtonRole.DestructiveRole,
        )
        self.void_button.setObjectName("confirmVoidButton")
        self.void_button.setProperty("destructive", True)
        self.cancel_button.setDefault(True)
        self.cancel_button.clicked.connect(self.reject)
        self.void_button.clicked.connect(self.void_requested.emit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addLayout(details)
        layout.addWidget(warning)
        layout.addWidget(self.error_label)
        layout.addWidget(button_box)

    def reason(self) -> str:
        return self.reason_input.toPlainText()

    def show_error(self, message: str) -> None:
        _show_error(self.error_label, message)


def _create_error_label(parent: QWidget, object_name: str) -> QLabel:
    label = QLabel("", parent)
    label.setObjectName(object_name)
    label.setProperty("errorMessage", True)
    label.setWordWrap(True)
    label.hide()
    return label


def _show_error(label: QLabel, message: str) -> None:
    label.setText(message)
    label.show()


def _create_form_buttons(
    parent: QWidget,
    save_text: str,
) -> tuple[QDialogButtonBox, QPushButton, QPushButton]:
    button_box = QDialogButtonBox(parent)
    cancel_button = button_box.addButton("İptal", QDialogButtonBox.ButtonRole.RejectRole)
    save_button = button_box.addButton(save_text, QDialogButtonBox.ButtonRole.AcceptRole)
    save_button.setProperty("primary", True)
    save_button.setDefault(True)
    return button_box, cancel_button, save_button
