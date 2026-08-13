from datetime import date

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from hesiva.models.customer import Customer
from hesiva.models.reminder import Reminder
from hesiva.read_models import ReminderSummary, StartupReminderSummary


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

    def get_startup_summary(self, reference_date: date) -> StartupReminderSummary:
        """Return application-wide due counts and the earliest active-customer target."""
        active_due_conditions = (
            Reminder.completed_at.is_(None),
            Reminder.cancelled_at.is_(None),
            Reminder.remind_on <= reference_date,
        )
        focus = (
            select(
                Reminder.id.label("reminder_id"),
                Reminder.customer_id,
            )
            .join(Customer, Customer.id == Reminder.customer_id)
            .where(
                *active_due_conditions,
                Customer.archived_at.is_(None),
            )
            .order_by(Reminder.remind_on, Reminder.id)
            .limit(1)
            .cte("startup_reminder_focus")
        )
        statement = select(
            func.sum(case((Reminder.remind_on < reference_date, 1), else_=0)).label(
                "overdue_count"
            ),
            func.sum(case((Reminder.remind_on == reference_date, 1), else_=0)).label("today_count"),
            select(focus.c.customer_id).scalar_subquery().label("focus_customer_id"),
            select(focus.c.reminder_id).scalar_subquery().label("focus_reminder_id"),
        ).where(*active_due_conditions)
        row = self._session.execute(statement).one()
        return StartupReminderSummary(
            overdue_count=row.overdue_count or 0,
            today_count=row.today_count or 0,
            focus_customer_id=row.focus_customer_id,
            focus_reminder_id=row.focus_reminder_id,
        )

    def list_summary_records(
        self,
        customer_id: int,
        *,
        include_inactive: bool = False,
    ) -> list[ReminderSummary]:
        statement = select(
            Reminder.id.label("reminder_id"),
            Reminder.customer_id,
            Reminder.remind_on,
            Reminder.note,
            Reminder.completed_at,
            Reminder.cancelled_at,
        ).where(Reminder.customer_id == customer_id)
        if not include_inactive:
            statement = statement.where(
                Reminder.completed_at.is_(None),
                Reminder.cancelled_at.is_(None),
            )
        statement = statement.order_by(Reminder.remind_on, Reminder.id)
        return [
            ReminderSummary(
                reminder_id=row.reminder_id,
                customer_id=row.customer_id,
                remind_on=row.remind_on,
                note=row.note,
                completed_at=row.completed_at,
                cancelled_at=row.cancelled_at,
            )
            for row in self._session.execute(statement)
        ]
