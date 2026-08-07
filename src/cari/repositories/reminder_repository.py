from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from cari.models.reminder import Reminder


class ReminderRepository:
    """Persist and query reminders using a caller-owned session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, reminder: Reminder) -> Reminder:
        """Add and flush a reminder without committing the caller's transaction."""
        self._session.add(reminder)
        self._session.flush()
        return reminder

    def get_by_id(self, reminder_id: int) -> Reminder | None:
        return self._session.get(Reminder, reminder_id)

    def list_for_customer(
        self,
        customer_id: int,
        *,
        include_inactive: bool = False,
    ) -> list[Reminder]:
        statement = select(Reminder).where(Reminder.customer_id == customer_id)
        if not include_inactive:
            statement = statement.where(
                Reminder.completed_at.is_(None),
                Reminder.cancelled_at.is_(None),
            )

        statement = statement.order_by(Reminder.remind_on, Reminder.id)
        return list(self._session.scalars(statement).all())

    def list_active(self) -> list[Reminder]:
        statement = (
            select(Reminder)
            .where(
                Reminder.completed_at.is_(None),
                Reminder.cancelled_at.is_(None),
            )
            .order_by(Reminder.remind_on, Reminder.id)
        )
        return list(self._session.scalars(statement).all())

    def list_due(self, on_or_before: date) -> list[Reminder]:
        statement = (
            select(Reminder)
            .where(
                Reminder.completed_at.is_(None),
                Reminder.cancelled_at.is_(None),
                Reminder.remind_on <= on_or_before,
            )
            .order_by(Reminder.remind_on, Reminder.id)
        )
        return list(self._session.scalars(statement).all())
