from dataclasses import dataclass
from datetime import date

from PySide6.QtCore import QDate, Signal, Qt
from PySide6.QtWidgets import (
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from hesiva.read_models import ReminderSummary, StartupReminderSummary
from hesiva.ui.presentation import format_date


@dataclass(frozen=True, slots=True)
class ReminderFormValues:
    """The two required reminder values exposed by the frozen V1 dialogs."""

    remind_on: date
    note: str


class StartupReminderSummaryDialog(QDialog):
    """One non-destructive startup summary for application-wide due reminders."""

    def __init__(
        self,
        summary: StartupReminderSummary,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("startupReminderSummaryDialog")
        self.setWindowTitle("Hatırlatmalar")
        self.setModal(True)
        self.setMinimumWidth(430)

        heading = QLabel("Hatırlatmalar", self)
        heading.setObjectName("startupReminderHeading")
        heading.setProperty("dialogHeading", True)

        self.overdue_count_label = QLabel(
            f"{summary.overdue_count} gecikmiş hatırlatma",
            self,
        )
        self.overdue_count_label.setObjectName("startupOverdueCountLabel")
        self.overdue_count_label.setProperty("reminderState", "overdue")
        self.today_count_label = QLabel(
            f"{summary.today_count} bugün yapılacak hatırlatma",
            self,
        )
        self.today_count_label.setObjectName("startupTodayCountLabel")
        self.today_count_label.setProperty("reminderState", "today")
        question = QLabel("Hatırlatmaları görüntülemek ister misiniz?", self)
        question.setWordWrap(True)

        buttons = QDialogButtonBox(self)
        self.open_button = buttons.addButton(
            "Hatırlatmaları Aç",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self.open_button.setObjectName("openStartupRemindersButton")
        self.close_button = buttons.addButton(
            "Kapat",
            QDialogButtonBox.ButtonRole.RejectRole,
        )
        self.close_button.setObjectName("closeStartupRemindersButton")
        self.open_button.clicked.connect(self.accept)
        self.close_button.clicked.connect(self.reject)
        self.close_button.setDefault(True)
        self.close_button.setFocus()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)
        layout.addWidget(heading)
        layout.addWidget(self.overdue_count_label)
        layout.addWidget(self.today_count_label)
        layout.addSpacing(4)
        layout.addWidget(question)
        layout.addWidget(buttons)

        QWidget.setTabOrder(self.close_button, self.open_button)


class ReminderFormDialog(QDialog):
    """Shared add/edit reminder form without persistence responsibilities."""

    save_requested = Signal()

    def __init__(
        self,
        title: str,
        *,
        initial_values: ReminderFormValues | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("reminderFormDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(500)

        self.date_input = QDateEdit(self)
        self.date_input.setObjectName("reminderDateInput")
        self.date_input.setCalendarPopup(True)
        self.date_input.setDisplayFormat("dd.MM.yyyy")
        self.date_input.setDate(
            QDate.currentDate()
            if initial_values is None
            else QDate(
                initial_values.remind_on.year,
                initial_values.remind_on.month,
                initial_values.remind_on.day,
            )
        )

        self.note_input = QPlainTextEdit(self)
        self.note_input.setObjectName("reminderNoteInput")
        self.note_input.setPlaceholderText("Hatırlatma notunu yazınız...")
        self.note_input.setMaximumHeight(110)
        if initial_values is not None:
            self.note_input.setPlainText(initial_values.note)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        form.addRow("Tarih: *", self.date_input)
        form.addRow("Not: *", self.note_input)

        self.error_label = QLabel("", self)
        self.error_label.setObjectName("reminderFormError")
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
        self.save_button.setObjectName("reminderSaveButton")
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

        QWidget.setTabOrder(self.date_input, self.note_input)
        QWidget.setTabOrder(self.note_input, self.save_button)
        self.date_input.setFocus()

    def values(self) -> ReminderFormValues:
        return ReminderFormValues(
            remind_on=self.date_input.date().toPython(),
            note=self.note_input.toPlainText(),
        )

    def show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.show()

    def _request_save(self) -> None:
        if not self.note_input.toPlainText().strip():
            self.show_error("Hatırlatma notu boş bırakılamaz.")
            self.note_input.setFocus()
            return
        self.error_label.hide()
        self.save_requested.emit()


def confirm_reminder_completion(parent: QWidget, reminder: ReminderSummary) -> bool:
    """Confirm completion while preserving the reminder record."""
    return _confirm_reminder_transition(
        parent,
        reminder,
        object_name="completeReminderConfirmation",
        title="Hatırlatmayı Tamamla",
        message="Bu hatırlatma tamamlandı olarak işaretlenecek.",
        action_text="Tamamlandı",
        destructive=False,
    )


def confirm_reminder_cancellation(parent: QWidget, reminder: ReminderSummary) -> bool:
    """Confirm cancellation without describing it as physical deletion."""
    return _confirm_reminder_transition(
        parent,
        reminder,
        object_name="cancelReminderConfirmation",
        title="Hatırlatmayı İptal Et",
        message="Bu hatırlatma iptal edilecek ve aktif listeden kaldırılacak.",
        action_text="İptal Et",
        destructive=True,
    )


def _confirm_reminder_transition(
    parent: QWidget,
    reminder: ReminderSummary,
    *,
    object_name: str,
    title: str,
    message: str,
    action_text: str,
    destructive: bool,
) -> bool:
    confirmation = QMessageBox(parent)
    confirmation.setObjectName(object_name)
    confirmation.setIcon(QMessageBox.Icon.Warning)
    confirmation.setWindowTitle(title)
    confirmation.setText(message)
    confirmation.setInformativeText(f"Tarih: {format_date(reminder.remind_on)}\n{reminder.note}")
    cancel_button = confirmation.addButton("Vazgeç", QMessageBox.ButtonRole.RejectRole)
    role = (
        QMessageBox.ButtonRole.DestructiveRole if destructive else QMessageBox.ButtonRole.AcceptRole
    )
    action_button = confirmation.addButton(action_text, role)
    confirmation.setDefaultButton(cancel_button)
    confirmation.setEscapeButton(cancel_button)
    confirmation.exec()
    return confirmation.clickedButton() is action_button
