from datetime import date

from sqlalchemy.orm import Session

from hesiva.models._timestamps import utc_now
from hesiva.models.customer import Customer
from hesiva.models.reminder import Reminder
from hesiva.repositories.customer_repository import CustomerRepository
from hesiva.repositories.reminder_repository import ReminderRepository
from hesiva.services._text import normalize_required_text
from hesiva.services.exceptions import (
    CustomerNotFoundError,
    InvalidStateTransitionError,
    ReminderNotFoundError,
    ValidationError,
)


class ReminderService:
    """Apply reminder lifecycle rules and own reminder write boundaries."""

    def __init__(
        self,
        session: Session,
        reminder_repository: ReminderRepository,
        customer_repository: CustomerRepository,
    ) -> None:
        self._session = session
        self._reminder_repository = reminder_repository
        self._customer_repository = customer_repository

    def create_reminder(self, customer_id: int, remind_on: date, note: str) -> Reminder:
        customer = self._get_customer(customer_id)
        if type(remind_on) is not date:
            raise ValidationError("remind_on must be a date.")

        reminder = Reminder(
            customer_id=customer.id,
            remind_on=remind_on,
            note=normalize_required_text(note, "note"),
        )
        try:
            self._reminder_repository.add(reminder)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return reminder

    def get_reminder(self, reminder_id: int) -> Reminder:
        reminder = self._reminder_repository.get_by_id(reminder_id)
        if reminder is None:
            raise ReminderNotFoundError(f"Reminder {reminder_id} was not found.")
        return reminder

    def list_for_customer(
        self,
        customer_id: int,
        *,
        include_inactive: bool = False,
    ) -> list[Reminder]:
        self._get_customer(customer_id)
        return self._reminder_repository.list_for_customer(
            customer_id,
            include_inactive=include_inactive,
        )

    def list_due(self, on_or_before: date) -> list[Reminder]:
        if type(on_or_before) is not date:
            raise ValidationError("on_or_before must be a date.")
        return self._reminder_repository.list_due(on_or_before)

    def complete_reminder(self, reminder_id: int) -> Reminder:
        reminder = self.get_reminder(reminder_id)
        if reminder.cancelled_at is not None:
            raise InvalidStateTransitionError("A cancelled reminder cannot be completed.")

        try:
            if reminder.completed_at is None:
                reminder.completed_at = utc_now()
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return reminder

    def cancel_reminder(self, reminder_id: int) -> Reminder:
        reminder = self.get_reminder(reminder_id)
        if reminder.completed_at is not None:
            raise InvalidStateTransitionError("A completed reminder cannot be cancelled.")

        try:
            if reminder.cancelled_at is None:
                reminder.cancelled_at = utc_now()
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return reminder

    def _get_customer(self, customer_id: int) -> Customer:
        customer = self._customer_repository.get_by_id(customer_id)
        if customer is None:
            raise CustomerNotFoundError(f"Customer {customer_id} was not found.")
        return customer
