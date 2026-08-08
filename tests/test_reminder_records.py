from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session

from hesiva.database.base import Base
from hesiva.database.engine import create_sqlite_engine
from hesiva.models import Customer, Reminder
from hesiva.read_models import ReminderSummary
from hesiva.repositories import CustomerRepository, ReminderRepository
from hesiva.services import (
    CustomerService,
    InvalidStateTransitionError,
    ReminderNotFoundError,
    ReminderService,
    ValidationError,
)
from hesiva.ui.presentation import (
    ReminderPresentationState,
    classify_reminder,
    count_active_reminders_today,
    format_reminder_status,
)


@pytest.fixture
def database(tmp_path: Path) -> Iterator[tuple[Engine, Session]]:
    engine = create_sqlite_engine(tmp_path / "reminder-records.db")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            yield engine, session
    finally:
        engine.dispose()


def reminder_service(session: Session) -> ReminderService:
    return ReminderService(
        session,
        ReminderRepository(session),
        CustomerRepository(session),
    )


def summary(
    reminder_id: int,
    remind_on: date,
    *,
    completed_at: datetime | None = None,
    cancelled_at: datetime | None = None,
) -> ReminderSummary:
    return ReminderSummary(
        reminder_id=reminder_id,
        customer_id=1,
        remind_on=remind_on,
        note=f"Reminder {reminder_id}",
        completed_at=completed_at,
        cancelled_at=cancelled_at,
    )


def test_plain_active_and_inactive_reads_filter_and_order_by_date_then_id(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    customers = CustomerRepository(session)
    reminders = ReminderRepository(session)
    customer = customers.add(Customer(full_name="Reminder Owner"))
    other = customers.add(Customer(full_name="Other Owner"))
    completed = reminders.add(
        Reminder(
            customer=customer,
            remind_on=date(2026, 8, 1),
            note="Same note",
            completed_at=datetime(2026, 8, 2),
        )
    )
    cancelled = reminders.add(
        Reminder(
            customer=customer,
            remind_on=date(2026, 8, 2),
            note="Cancelled",
            cancelled_at=datetime(2026, 8, 3),
        )
    )
    first = reminders.add(Reminder(customer=customer, remind_on=date(2026, 8, 5), note="Same note"))
    second = reminders.add(
        Reminder(customer=customer, remind_on=date(2026, 8, 5), note="Same note")
    )
    reminders.add(Reminder(customer=other, remind_on=date(2026, 8, 4), note="Other"))
    service = reminder_service(session)

    active = service.list_records_for_customer(customer.id)
    all_records = service.list_records_for_customer(customer.id, include_inactive=True)

    assert [record.reminder_id for record in active] == [first.id, second.id]
    assert [record.reminder_id for record in all_records] == [
        completed.id,
        cancelled.id,
        first.id,
        second.id,
    ]
    assert all(not hasattr(record, "_sa_instance_state") for record in all_records)
    assert all(record.customer_id == customer.id for record in all_records)


def test_reminder_presentation_classification_and_today_count_are_deterministic() -> None:
    reference_date = date(2026, 8, 9)
    overdue = summary(1, date(2026, 8, 8))
    today = summary(2, reference_date)
    future = summary(3, date(2026, 8, 12))
    completed_today = summary(4, reference_date, completed_at=datetime(2026, 8, 9, 9))
    cancelled_today = summary(5, reference_date, cancelled_at=datetime(2026, 8, 9, 10))

    assert classify_reminder(overdue, reference_date) is ReminderPresentationState.OVERDUE
    assert classify_reminder(today, reference_date) is ReminderPresentationState.TODAY
    assert classify_reminder(future, reference_date) is ReminderPresentationState.UPCOMING
    assert classify_reminder(completed_today, reference_date) is ReminderPresentationState.COMPLETED
    assert classify_reminder(cancelled_today, reference_date) is ReminderPresentationState.CANCELLED
    assert format_reminder_status(overdue, reference_date) == "Gecikti"
    assert format_reminder_status(today, reference_date) == "Bugün"
    assert format_reminder_status(future, reference_date) == "3 gün kaldı"
    assert format_reminder_status(completed_today, reference_date) == "Tamamlandı"
    assert format_reminder_status(cancelled_today, reference_date) == "İptal Edildi"
    assert (
        count_active_reminders_today(
            [overdue, today, future, completed_today, cancelled_today],
            reference_date,
        )
        == 1
    )


def test_active_reminder_update_is_full_form_and_preserves_lifecycle_timestamps(
    database: tuple[Engine, Session],
) -> None:
    engine, session = database
    customer = CustomerRepository(session).add(Customer(full_name="Edit Owner"))
    session.commit()
    service = reminder_service(session)
    reminder = service.create_reminder(customer.id, date(2026, 8, 9), "Old note")
    reminder_id = reminder.id

    with pytest.raises(ValidationError):
        service.update_reminder(
            reminder_id,
            remind_on=date(2026, 8, 10),
            note="   ",
        )

    updated = service.update_reminder(
        reminder_id,
        remind_on=date(2026, 8, 10),
        note="  New note  ",
    )

    assert updated.id == reminder_id
    assert updated.remind_on == date(2026, 8, 10)
    assert updated.note == "New note"
    assert updated.completed_at is None
    assert updated.cancelled_at is None
    with Session(engine) as verification_session:
        persisted = verification_session.get(Reminder, reminder_id)
        assert persisted is not None
        assert persisted.remind_on == date(2026, 8, 10)
        assert persisted.note == "New note"
        assert persisted.completed_at is None
        assert persisted.cancelled_at is None


def test_inactive_reminders_cannot_be_edited(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    customer = CustomerRepository(session).add(Customer(full_name="Inactive Owner"))
    session.commit()
    service = reminder_service(session)
    completed = service.create_reminder(customer.id, date(2026, 8, 9), "Complete")
    cancelled = service.create_reminder(customer.id, date(2026, 8, 10), "Cancel")
    service.complete_reminder(completed.id)
    service.cancel_reminder(cancelled.id)
    completed_at = completed.completed_at
    cancelled_at = cancelled.cancelled_at

    with pytest.raises(InvalidStateTransitionError):
        service.update_reminder(
            completed.id,
            remind_on=date(2026, 8, 11),
            note="Changed",
        )
    with pytest.raises(InvalidStateTransitionError):
        service.update_reminder(
            cancelled.id,
            remind_on=date(2026, 8, 11),
            note="Changed",
        )

    assert completed.completed_at == completed_at
    assert completed.cancelled_at is None
    assert cancelled.cancelled_at == cancelled_at
    assert cancelled.completed_at is None


def test_missing_reminder_update_raises_existing_not_found_error(
    database: tuple[Engine, Session],
) -> None:
    _, session = database

    with pytest.raises(ReminderNotFoundError):
        reminder_service(session).update_reminder(
            999,
            remind_on=date(2026, 8, 9),
            note="Missing",
        )


def test_reminder_creation_for_archived_customer_preserves_current_contract(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    customers = CustomerService(session, CustomerRepository(session))
    customer = customers.create_customer("Archived Reminder Owner")
    customers.archive_customer(customer.id)

    reminder = reminder_service(session).create_reminder(
        customer.id,
        date(2026, 8, 9),
        "Allowed by current contract",
    )

    assert reminder.customer_id == customer.id


def test_reminder_record_read_query_count_is_fixed(
    database: tuple[Engine, Session],
) -> None:
    engine, session = database
    customer = CustomerRepository(session).add(Customer(full_name="Query Count Owner"))
    repository = ReminderRepository(session)
    for day in range(1, 9):
        repository.add(
            Reminder(
                customer=customer,
                remind_on=date(2026, 8, day),
                note=f"Reminder {day}",
            )
        )
    customer_id = customer.id
    session.commit()
    selects: list[str] = []

    def count_selects(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    event.listen(engine, "before_cursor_execute", count_selects)
    try:
        records = reminder_service(session).list_records_for_customer(customer_id)
    finally:
        event.remove(engine, "before_cursor_execute", count_selects)

    assert len(records) == 8
    assert len(selects) == 2
