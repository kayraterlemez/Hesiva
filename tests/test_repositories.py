from collections.abc import Iterator
from datetime import date, datetime, time
from pathlib import Path

import pytest
from sqlalchemy.exc import MultipleResultsFound
from sqlalchemy.orm import Session

from cari.database.base import Base
from cari.database.engine import create_sqlite_engine
from cari.models import Animal, Customer, Reminder, Transaction
from cari.repositories import (
    AnimalRepository,
    CustomerRepository,
    ReminderRepository,
    TransactionRepository,
)


@pytest.fixture
def database_session(tmp_path: Path) -> Iterator[Session]:
    engine = create_sqlite_engine(tmp_path / "repositories.db")
    Base.metadata.create_all(engine)

    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


def add_customer(session: Session, full_name: str = "Test Customer") -> Customer:
    return CustomerRepository(session).add(Customer(full_name=full_name))


def test_customer_repository_add_and_get_methods(database_session: Session) -> None:
    repository = CustomerRepository(database_session)
    customer = repository.add(Customer(full_name="Imported Customer", legacy_id=42))

    assert customer.id is not None
    assert repository.get_by_id(customer.id) is customer
    assert repository.get_by_id(999) is None


def test_customer_repository_get_by_legacy_id_returns_none_when_missing(
    database_session: Session,
) -> None:
    repository = CustomerRepository(database_session)

    assert repository.get_by_legacy_id(999) is None


def test_customer_repository_get_by_legacy_id_returns_single_match(
    database_session: Session,
) -> None:
    repository = CustomerRepository(database_session)
    customer = repository.add(Customer(full_name="Imported Customer", legacy_id=42))

    assert repository.get_by_legacy_id(42) is customer


def test_customer_repository_get_by_legacy_id_rejects_multiple_matches(
    database_session: Session,
) -> None:
    repository = CustomerRepository(database_session)
    repository.add(Customer(full_name="First Imported Customer", legacy_id=42))
    repository.add(Customer(full_name="Second Imported Customer", legacy_id=42))

    with pytest.raises(MultipleResultsFound):
        repository.get_by_legacy_id(42)


def test_customer_repository_search_supports_duplicate_names_and_is_ordered(
    database_session: Session,
) -> None:
    repository = CustomerRepository(database_session)
    first_duplicate = repository.add(Customer(full_name="Alpha Match"))
    second_duplicate = repository.add(Customer(full_name="Alpha Match"))
    zulu_match = repository.add(Customer(full_name="Zulu Match"))
    repository.add(Customer(full_name="Unrelated Customer"))

    assert repository.search_by_name("Match") == [
        first_duplicate,
        second_duplicate,
        zulu_match,
    ]


def test_customer_repository_separates_active_and_archived_customers(
    database_session: Session,
) -> None:
    repository = CustomerRepository(database_session)
    zulu_active = repository.add(Customer(full_name="Zulu Active"))
    alpha_archived = repository.add(
        Customer(full_name="Alpha Archived", archived_at=datetime(2026, 8, 1))
    )
    bravo_active = repository.add(Customer(full_name="Bravo Active"))
    beta_archived = repository.add(
        Customer(full_name="Beta Archived", archived_at=datetime(2026, 8, 2))
    )

    assert repository.list_active() == [bravo_active, zulu_active]
    assert repository.list_archived() == [alpha_archived, beta_archived]


def test_animal_repository_add_get_and_archive_filtering(database_session: Session) -> None:
    customer = add_customer(database_session)
    other_customer = add_customer(database_session, "Other Customer")
    repository = AnimalRepository(database_session)
    active_animal = repository.add(Animal(customer=customer, name="Active Animal"))
    archived_animal = repository.add(
        Animal(
            customer=customer,
            name="Archived Animal",
            archived_at=datetime(2026, 8, 1),
        )
    )
    repository.add(Animal(customer=other_customer, name="Other Animal"))

    assert repository.get_by_id(active_animal.id) is active_animal
    assert repository.get_by_id(999) is None
    assert repository.list_for_customer(customer.id) == [active_animal]
    assert repository.list_for_customer(customer.id, include_archived=True) == [
        active_animal,
        archived_animal,
    ]


def test_animal_repository_returns_all_duplicate_ear_tags(database_session: Session) -> None:
    first_customer = add_customer(database_session, "First Customer")
    second_customer = add_customer(database_session, "Second Customer")
    repository = AnimalRepository(database_session)
    first_animal = repository.add(Animal(customer=first_customer, ear_tag="TAG-1"))
    second_animal = repository.add(Animal(customer=second_customer, ear_tag="TAG-1"))
    repository.add(Animal(customer=first_customer, ear_tag="TAG-2"))

    assert repository.find_by_ear_tag("TAG-1") == [first_animal, second_animal]
    assert repository.find_by_ear_tag("MISSING") == []


def test_transaction_repository_gets_records_and_orders_active_history(
    database_session: Session,
) -> None:
    customer = add_customer(database_session)
    animal = AnimalRepository(database_session).add(Animal(customer=customer, name="Test Animal"))
    repository = TransactionRepository(database_session)
    voided = repository.add(
        Transaction(
            customer=customer,
            animal=animal,
            transaction_date=date(2026, 8, 5),
            transaction_time=time(10),
            description="Voided transaction",
            amount_kurus=100,
            voided_at=datetime(2026, 8, 6),
        )
    )
    previous_day = repository.add(
        Transaction(
            customer=customer,
            animal=animal,
            transaction_date=date(2026, 8, 6),
            transaction_time=time(12),
            description="Previous day",
            amount_kurus=200,
        )
    )
    null_time = repository.add(
        Transaction(
            customer=customer,
            animal=animal,
            transaction_date=date(2026, 8, 7),
            description="No transaction time",
            amount_kurus=300,
        )
    )
    first_same_time = repository.add(
        Transaction(
            customer=customer,
            animal=animal,
            legacy_id=73,
            transaction_date=date(2026, 8, 7),
            transaction_time=time(8),
            description="First same-time transaction",
            amount_kurus=400,
        )
    )
    second_same_time = repository.add(
        Transaction(
            customer=customer,
            animal=animal,
            transaction_date=date(2026, 8, 7),
            transaction_time=time(8),
            description="Second same-time transaction",
            amount_kurus=500,
        )
    )

    active_history = [previous_day, null_time, first_same_time, second_same_time]

    assert repository.get_by_id(previous_day.id) is previous_day
    assert repository.get_by_id(999) is None
    assert repository.list_for_customer(customer.id) == active_history
    assert repository.list_for_customer(customer.id, include_voided=True) == [
        voided,
        *active_history,
    ]
    assert repository.list_for_animal(animal.id) == active_history
    assert repository.list_for_animal(animal.id, include_voided=True) == [
        voided,
        *active_history,
    ]
    assert repository.sum_active_amounts_for_customer(customer.id) == 1400
    assert repository.sum_active_amounts_for_customer(999) == 0


def test_transaction_repository_get_by_legacy_id_returns_none_when_missing(
    database_session: Session,
) -> None:
    repository = TransactionRepository(database_session)

    assert repository.get_by_legacy_id(999) is None


def test_transaction_repository_get_by_legacy_id_returns_single_match(
    database_session: Session,
) -> None:
    customer = add_customer(database_session)
    repository = TransactionRepository(database_session)
    transaction = repository.add(
        Transaction(
            customer=customer,
            legacy_id=73,
            transaction_date=date(2026, 8, 7),
            description="Imported transaction",
            amount_kurus=100,
        )
    )

    assert repository.get_by_legacy_id(73) is transaction


def test_transaction_repository_get_by_legacy_id_rejects_multiple_matches(
    database_session: Session,
) -> None:
    customer = add_customer(database_session)
    repository = TransactionRepository(database_session)
    repository.add(
        Transaction(
            customer=customer,
            legacy_id=73,
            transaction_date=date(2026, 8, 7),
            description="First imported transaction",
            amount_kurus=100,
        )
    )
    repository.add(
        Transaction(
            customer=customer,
            legacy_id=73,
            transaction_date=date(2026, 8, 8),
            description="Second imported transaction",
            amount_kurus=200,
        )
    )

    with pytest.raises(MultipleResultsFound):
        repository.get_by_legacy_id(73)


def test_reminder_repository_filters_active_and_due_records_deterministically(
    database_session: Session,
) -> None:
    customer = add_customer(database_session)
    other_customer = add_customer(database_session, "Other Customer")
    repository = ReminderRepository(database_session)
    completed = repository.add(
        Reminder(
            customer=customer,
            remind_on=date(2026, 8, 5),
            note="Completed reminder",
            completed_at=datetime(2026, 8, 5),
        )
    )
    cancelled = repository.add(
        Reminder(
            customer=customer,
            remind_on=date(2026, 8, 6),
            note="Cancelled reminder",
            cancelled_at=datetime(2026, 8, 6),
        )
    )
    early = repository.add(
        Reminder(customer=customer, remind_on=date(2026, 8, 7), note="Early reminder")
    )
    first_same_day = repository.add(
        Reminder(customer=customer, remind_on=date(2026, 8, 8), note="First reminder")
    )
    second_same_day = repository.add(
        Reminder(customer=customer, remind_on=date(2026, 8, 8), note="Second reminder")
    )
    future = repository.add(
        Reminder(customer=customer, remind_on=date(2026, 8, 9), note="Future reminder")
    )
    other = repository.add(
        Reminder(
            customer=other_customer,
            remind_on=date(2026, 8, 4),
            note="Other customer reminder",
        )
    )

    customer_active = [early, first_same_day, second_same_day, future]

    assert repository.get_by_id(completed.id) is completed
    assert repository.get_by_id(999) is None
    assert repository.list_for_customer(customer.id) == customer_active
    assert repository.list_for_customer(customer.id, include_inactive=True) == [
        completed,
        cancelled,
        *customer_active,
    ]
    assert repository.list_active() == [other, *customer_active]
    assert repository.list_due(date(2026, 8, 8)) == [
        other,
        early,
        first_same_day,
        second_same_day,
    ]


def test_repository_adds_flush_without_committing_and_caller_can_roll_back(
    database_session: Session,
) -> None:
    customer_repository = CustomerRepository(database_session)
    animal_repository = AnimalRepository(database_session)
    transaction_repository = TransactionRepository(database_session)
    reminder_repository = ReminderRepository(database_session)

    customer = customer_repository.add(Customer(full_name="Uncommitted Customer"))
    animal = animal_repository.add(Animal(customer=customer, name="Uncommitted Animal"))
    transaction = transaction_repository.add(
        Transaction(
            customer=customer,
            animal=animal,
            transaction_date=date(2026, 8, 7),
            description="Uncommitted transaction",
            amount_kurus=100,
        )
    )
    reminder = reminder_repository.add(
        Reminder(
            customer=customer,
            remind_on=date(2026, 8, 8),
            note="Uncommitted reminder",
        )
    )
    record_ids = (customer.id, animal.id, transaction.id, reminder.id)

    assert all(record_id is not None for record_id in record_ids)
    assert database_session.in_transaction()

    database_session.rollback()

    assert customer_repository.get_by_id(customer.id) is None
    assert animal_repository.get_by_id(animal.id) is None
    assert transaction_repository.get_by_id(transaction.id) is None
    assert reminder_repository.get_by_id(reminder.id) is None
