from collections.abc import Iterator
from datetime import date, time
from pathlib import Path

import pytest
from sqlalchemy import Engine, event, func, select
from sqlalchemy.orm import Session

from hesiva.database.base import Base
from hesiva.database.engine import create_sqlite_engine
from hesiva.models import Animal, Customer, Reminder, Transaction
from hesiva.repositories import (
    AnimalRepository,
    CustomerRepository,
    ReminderRepository,
    TransactionRepository,
)
from hesiva.services import (
    AnimalNotFoundError,
    AnimalService,
    CustomerNotFoundError,
    CustomerService,
    InvalidAnimalOwnershipError,
    InvalidStateTransitionError,
    ReminderNotFoundError,
    ReminderService,
    TransactionNotFoundError,
    TransactionService,
    ValidationError,
)


@pytest.fixture
def database(tmp_path: Path) -> Iterator[tuple[Engine, Session]]:
    engine = create_sqlite_engine(tmp_path / "services.db")
    Base.metadata.create_all(engine)

    try:
        with Session(engine) as session:
            yield engine, session
    finally:
        engine.dispose()


def customer_service(session: Session) -> CustomerService:
    return CustomerService(session, CustomerRepository(session))


def animal_service(session: Session) -> AnimalService:
    return AnimalService(
        session,
        AnimalRepository(session),
        CustomerRepository(session),
    )


def transaction_service(session: Session) -> TransactionService:
    return TransactionService(
        session,
        TransactionRepository(session),
        CustomerRepository(session),
        AnimalRepository(session),
    )


def reminder_service(session: Session) -> ReminderService:
    return ReminderService(
        session,
        ReminderRepository(session),
        CustomerRepository(session),
    )


def test_customer_service_creates_normalized_customer_and_commits(
    database: tuple[Engine, Session],
) -> None:
    engine, session = database
    service = customer_service(session)

    customer = service.create_customer(
        "  Test Customer  ",
        phone="   ",
        address="  Test Address  ",
        notes=None,
        registered_on=date(2026, 8, 7),
    )

    assert customer.full_name == "Test Customer"
    assert customer.phone is None
    assert customer.address == "Test Address"
    assert customer.notes is None
    assert customer.registered_on == date(2026, 8, 7)
    assert customer.legacy_id is None

    with Session(engine) as verification_session:
        assert verification_session.get(Customer, customer.id) is not None


def test_customer_service_rejects_empty_name_without_partial_commit(
    database: tuple[Engine, Session],
) -> None:
    engine, session = database
    service = customer_service(session)

    with pytest.raises(ValidationError):
        service.create_customer("   ")

    with Session(engine) as verification_session:
        assert verification_session.scalar(select(func.count()).select_from(Customer)) == 0


def test_customer_service_allows_duplicates_searches_and_lists_deterministically(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    service = customer_service(session)
    first = service.create_customer("Same Name")
    second = service.create_customer("Same Name")
    alpha = service.create_customer("Alpha Match")

    assert service.search_customers("  Match  ") == [alpha]
    assert service.list_active_customers() == [alpha, first, second]


def test_customer_service_updates_without_overwriting_legacy_id(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    repository = CustomerRepository(session)
    customer = repository.add(Customer(full_name="Imported Customer", legacy_id=42))
    session.commit()
    service = CustomerService(session, repository)

    updated = service.update_customer(
        customer.id,
        full_name="  Updated Customer  ",
        phone="  05000000000  ",
        address="   ",
        notes="  Updated note  ",
        registered_on=date(2020, 1, 2),
    )

    assert updated.full_name == "Updated Customer"
    assert updated.phone == "05000000000"
    assert updated.address is None
    assert updated.notes == "Updated note"
    assert updated.registered_on == date(2020, 1, 2)
    assert updated.legacy_id == 42


def test_customer_service_missing_customer_operations_raise_clear_error(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    service = customer_service(session)

    with pytest.raises(CustomerNotFoundError):
        service.get_customer(999)
    with pytest.raises(CustomerNotFoundError):
        service.update_customer(999, full_name="Missing")
    with pytest.raises(CustomerNotFoundError):
        service.archive_customer(999)


def test_customer_service_archive_is_idempotent_and_preserves_record(
    database: tuple[Engine, Session],
) -> None:
    engine, session = database
    service = customer_service(session)
    customer = service.create_customer("Archived Customer")

    service.archive_customer(customer.id)
    archived_at = customer.archived_at
    service.archive_customer(customer.id)

    assert archived_at is not None
    assert customer.archived_at == archived_at
    assert service.list_active_customers() == []
    with Session(engine) as verification_session:
        assert verification_session.get(Customer, customer.id) is not None


def test_animal_service_creates_optional_animal_for_active_customer(
    database: tuple[Engine, Session],
) -> None:
    engine, session = database
    customer = customer_service(session).create_customer("Animal Owner")
    service = animal_service(session)

    animal = service.create_animal(
        customer.id,
        ear_tag="   ",
        name=None,
        species="  Cattle  ",
        notes="   ",
    )

    assert animal.ear_tag is None
    assert animal.name is None
    assert animal.species == "Cattle"
    assert animal.notes is None
    assert service.get_animal(animal.id) is animal
    assert service.list_for_customer(customer.id) == [animal]
    with Session(engine) as verification_session:
        assert verification_session.get(Animal, animal.id) is not None


def test_animal_service_rejects_missing_or_archived_customer(
    database: tuple[Engine, Session],
) -> None:
    engine, session = database
    service = animal_service(session)

    with pytest.raises(CustomerNotFoundError):
        service.create_animal(999, name="Missing owner")

    customer = customer_service(session).create_customer("Archived Owner")
    customer_service(session).archive_customer(customer.id)
    with pytest.raises(InvalidStateTransitionError):
        service.create_animal(customer.id, name="Archived owner's animal")

    with Session(engine) as verification_session:
        assert verification_session.scalar(select(func.count()).select_from(Animal)) == 0


def test_animal_service_updates_archives_and_preserves_record(
    database: tuple[Engine, Session],
) -> None:
    engine, session = database
    customer = customer_service(session).create_customer("Animal Owner")
    service = animal_service(session)
    animal = service.create_animal(customer.id, name="Old Name", ear_tag="TAG-1")

    updated = service.update_animal(
        animal.id,
        name="  New Name  ",
        ear_tag="   ",
        species="  Sheep  ",
        notes="  Test note  ",
    )
    service.archive_animal(animal.id)
    archived_at = animal.archived_at
    service.archive_animal(animal.id)

    assert updated.name == "New Name"
    assert updated.ear_tag is None
    assert updated.species == "Sheep"
    assert updated.notes == "Test note"
    assert archived_at is not None
    assert animal.archived_at == archived_at
    assert service.list_for_customer(customer.id) == []
    assert service.list_for_customer(customer.id, include_archived=True) == [animal]
    with Session(engine) as verification_session:
        assert verification_session.get(Animal, animal.id) is not None


def test_animal_service_missing_animal_and_customer_list_raise_clear_errors(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    service = animal_service(session)

    with pytest.raises(AnimalNotFoundError):
        service.get_animal(999)
    with pytest.raises(AnimalNotFoundError):
        service.update_animal(999, name="Missing")
    with pytest.raises(AnimalNotFoundError):
        service.archive_animal(999)
    with pytest.raises(CustomerNotFoundError):
        service.list_for_customer(999)


def test_transaction_service_creates_debt_and_payment_with_expected_signs(
    database: tuple[Engine, Session],
) -> None:
    engine, session = database
    customer = customer_service(session).create_customer("Transaction Customer")
    service = transaction_service(session)

    debt = service.create_debt(
        customer.id,
        transaction_date=date(2026, 8, 7),
        transaction_time=time(9, 30),
        description="  Test debt  ",
        amount_kurus=150000,
        note="   ",
    )
    payment = service.create_payment(
        customer.id,
        transaction_date=date(2026, 8, 8),
        description="  Test payment  ",
        amount_kurus=30000,
    )

    assert debt.amount_kurus == 150000
    assert debt.transaction_time == time(9, 30)
    assert debt.description == "Test debt"
    assert debt.note is None
    assert debt.animal_id is None
    assert payment.amount_kurus == -30000
    assert service.get_transaction(debt.id) is debt
    assert service.list_for_customer(customer.id) == [debt, payment]
    with Session(engine) as verification_session:
        assert verification_session.get(Transaction, payment.id) is not None


@pytest.mark.parametrize(
    ("method_name", "amount_kurus"),
    [
        ("create_debt", 0),
        ("create_debt", -1),
        ("create_payment", 0),
        ("create_payment", -1),
    ],
)
def test_transaction_service_rejects_nonpositive_magnitudes(
    database: tuple[Engine, Session],
    method_name: str,
    amount_kurus: int,
) -> None:
    engine, session = database
    customer = customer_service(session).create_customer("Transaction Customer")
    service = transaction_service(session)
    create_transaction = getattr(service, method_name)

    with pytest.raises(ValidationError):
        create_transaction(
            customer.id,
            transaction_date=date(2026, 8, 7),
            description="Invalid amount",
            amount_kurus=amount_kurus,
        )

    with Session(engine) as verification_session:
        assert verification_session.scalar(select(func.count()).select_from(Transaction)) == 0


def test_transaction_service_rejects_invalid_description_date_and_customers(
    database: tuple[Engine, Session],
) -> None:
    engine, session = database
    service = transaction_service(session)
    customer = customer_service(session).create_customer("Active Customer")

    with pytest.raises(ValidationError):
        service.create_debt(
            customer.id,
            transaction_date=date(2026, 8, 7),
            description="   ",
            amount_kurus=100,
        )
    with pytest.raises(ValidationError):
        service.create_debt(
            customer.id,
            transaction_date=None,
            description="Invalid date",
            amount_kurus=100,
        )
    with pytest.raises(CustomerNotFoundError):
        service.create_debt(
            999,
            transaction_date=date(2026, 8, 7),
            description="Missing customer",
            amount_kurus=100,
        )

    customer_service(session).archive_customer(customer.id)
    with pytest.raises(InvalidStateTransitionError):
        service.create_debt(
            customer.id,
            transaction_date=date(2026, 8, 7),
            description="Archived customer",
            amount_kurus=100,
        )

    with Session(engine) as verification_session:
        assert verification_session.scalar(select(func.count()).select_from(Transaction)) == 0


def test_transaction_service_enforces_animal_ownership_and_archive_state(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    first_customer = customer_service(session).create_customer("First Customer")
    second_customer = customer_service(session).create_customer("Second Customer")
    animals = animal_service(session)
    owned_animal = animals.create_animal(first_customer.id, name="Owned Animal")
    other_animal = animals.create_animal(second_customer.id, name="Other Animal")
    archived_animal = animals.create_animal(first_customer.id, name="Archived Animal")
    animals.archive_animal(archived_animal.id)
    service = transaction_service(session)

    valid_transaction = service.create_debt(
        first_customer.id,
        animal_id=owned_animal.id,
        transaction_date=date(2026, 8, 7),
        description="Owned animal transaction",
        amount_kurus=100,
    )

    assert valid_transaction.animal_id == owned_animal.id
    with pytest.raises(InvalidAnimalOwnershipError):
        service.create_debt(
            first_customer.id,
            animal_id=other_animal.id,
            transaction_date=date(2026, 8, 7),
            description="Wrong animal owner",
            amount_kurus=100,
        )
    with pytest.raises(InvalidStateTransitionError):
        service.create_debt(
            first_customer.id,
            animal_id=archived_animal.id,
            transaction_date=date(2026, 8, 7),
            description="Archived animal",
            amount_kurus=100,
        )
    with pytest.raises(AnimalNotFoundError):
        service.create_debt(
            first_customer.id,
            animal_id=999,
            transaction_date=date(2026, 8, 7),
            description="Missing animal",
            amount_kurus=100,
        )

    assert service.list_for_customer(first_customer.id) == [valid_transaction]


def test_transaction_service_voids_without_deleting_and_preserves_first_void(
    database: tuple[Engine, Session],
) -> None:
    engine, session = database
    customer = customer_service(session).create_customer("Void Customer")
    service = transaction_service(session)
    transaction = service.create_debt(
        customer.id,
        transaction_date=date(2026, 8, 7),
        description="Incorrect debt",
        amount_kurus=50000,
    )

    service.void_transaction(transaction.id, "  Entry error  ")

    assert transaction.voided_at is not None
    assert transaction.void_reason == "Entry error"
    assert service.list_for_customer(customer.id) == []
    assert service.list_for_customer(customer.id, include_voided=True) == [transaction]
    with pytest.raises(InvalidStateTransitionError):
        service.void_transaction(transaction.id, "Different reason")

    with Session(engine) as verification_session:
        persisted = verification_session.get(Transaction, transaction.id)
        assert persisted is not None
        assert persisted.void_reason == "Entry error"


def test_transaction_service_calculates_active_signed_balance_and_credit(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    service = transaction_service(session)
    customer = customer_service(session).create_customer("Balance Customer")
    empty_customer = customer_service(session).create_customer("Empty Customer")
    credit_customer = customer_service(session).create_customer("Credit Customer")

    service.create_debt(
        customer.id,
        transaction_date=date(2026, 8, 7),
        description="First debt",
        amount_kurus=150000,
    )
    voided_debt = service.create_debt(
        customer.id,
        transaction_date=date(2026, 8, 8),
        description="Second debt",
        amount_kurus=50000,
    )
    service.create_payment(
        customer.id,
        transaction_date=date(2026, 8, 9),
        description="Payment",
        amount_kurus=30000,
    )

    assert service.calculate_balance(customer.id) == 170000
    service.void_transaction(voided_debt.id, None)
    assert service.calculate_balance(customer.id) == 120000
    assert service.calculate_balance(empty_customer.id) == 0

    service.create_debt(
        credit_customer.id,
        transaction_date=date(2026, 8, 7),
        description="Debt",
        amount_kurus=50000,
    )
    service.create_payment(
        credit_customer.id,
        transaction_date=date(2026, 8, 8),
        description="Overpayment",
        amount_kurus=70000,
    )
    assert service.calculate_balance(credit_customer.id) == -20000

    with pytest.raises(CustomerNotFoundError):
        service.calculate_balance(999)


def test_transaction_service_missing_read_operations_raise_clear_errors(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    service = transaction_service(session)

    with pytest.raises(TransactionNotFoundError):
        service.get_transaction(999)
    with pytest.raises(TransactionNotFoundError):
        service.void_transaction(999, "Missing")
    with pytest.raises(CustomerNotFoundError):
        service.list_for_customer(999)


def test_transaction_service_rolls_back_when_commit_fails_after_repository_write(
    database: tuple[Engine, Session],
) -> None:
    engine, session = database
    customer = customer_service(session).create_customer("Transaction Customer")
    service = transaction_service(session)

    def fail_commit(_session: Session) -> None:
        raise RuntimeError("Synthetic commit failure")

    event.listen(session, "before_commit", fail_commit, once=True)

    with pytest.raises(RuntimeError, match="Synthetic commit failure"):
        service.create_debt(
            customer.id,
            transaction_date=date(2026, 8, 7),
            description="Rolled back transaction",
            amount_kurus=100,
        )

    assert not session.in_transaction()
    with Session(engine) as verification_session:
        assert verification_session.get(Customer, customer.id) is not None
        assert verification_session.scalar(select(func.count()).select_from(Transaction)) == 0


def test_reminder_service_creates_normalized_reminder_and_commits(
    database: tuple[Engine, Session],
) -> None:
    engine, session = database
    customer = customer_service(session).create_customer("Reminder Customer")
    service = reminder_service(session)

    reminder = service.create_reminder(customer.id, date(2026, 8, 8), "  Call customer  ")

    assert reminder.note == "Call customer"
    assert service.get_reminder(reminder.id) is reminder
    assert service.list_for_customer(customer.id) == [reminder]
    with Session(engine) as verification_session:
        assert verification_session.get(Reminder, reminder.id) is not None


def test_reminder_service_rejects_missing_customer_empty_note_and_invalid_date(
    database: tuple[Engine, Session],
) -> None:
    engine, session = database
    service = reminder_service(session)

    with pytest.raises(CustomerNotFoundError):
        service.create_reminder(999, date(2026, 8, 8), "Missing customer")

    customer = customer_service(session).create_customer("Reminder Customer")
    with pytest.raises(ValidationError):
        service.create_reminder(customer.id, date(2026, 8, 8), "   ")
    with pytest.raises(ValidationError):
        service.create_reminder(customer.id, None, "Invalid date")

    with Session(engine) as verification_session:
        assert verification_session.scalar(select(func.count()).select_from(Reminder)) == 0


def test_reminder_service_complete_and_cancel_transitions_preserve_records(
    database: tuple[Engine, Session],
) -> None:
    engine, session = database
    customer = customer_service(session).create_customer("Reminder Customer")
    service = reminder_service(session)
    completed = service.create_reminder(customer.id, date(2026, 8, 8), "Complete me")
    cancelled = service.create_reminder(customer.id, date(2026, 8, 9), "Cancel me")

    service.complete_reminder(completed.id)
    completed_at = completed.completed_at
    service.complete_reminder(completed.id)
    service.cancel_reminder(cancelled.id)
    cancelled_at = cancelled.cancelled_at
    service.cancel_reminder(cancelled.id)

    assert completed_at is not None
    assert completed.completed_at == completed_at
    assert completed.cancelled_at is None
    assert cancelled_at is not None
    assert cancelled.cancelled_at == cancelled_at
    assert cancelled.completed_at is None
    with pytest.raises(InvalidStateTransitionError):
        service.cancel_reminder(completed.id)
    with pytest.raises(InvalidStateTransitionError):
        service.complete_reminder(cancelled.id)

    with Session(engine) as verification_session:
        assert verification_session.get(Reminder, completed.id) is not None
        assert verification_session.get(Reminder, cancelled.id) is not None


def test_reminder_service_due_list_excludes_completed_and_cancelled(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    customer = customer_service(session).create_customer("Reminder Customer")
    service = reminder_service(session)
    overdue = service.create_reminder(customer.id, date(2026, 8, 6), "Overdue")
    due_today = service.create_reminder(customer.id, date(2026, 8, 7), "Due today")
    future = service.create_reminder(customer.id, date(2026, 8, 8), "Future")
    completed = service.create_reminder(customer.id, date(2026, 8, 5), "Completed")
    cancelled = service.create_reminder(customer.id, date(2026, 8, 5), "Cancelled")
    service.complete_reminder(completed.id)
    service.cancel_reminder(cancelled.id)

    assert service.list_due(date(2026, 8, 7)) == [overdue, due_today]
    assert service.list_for_customer(customer.id) == [overdue, due_today, future]
    assert service.list_for_customer(customer.id, include_inactive=True) == [
        completed,
        cancelled,
        overdue,
        due_today,
        future,
    ]


def test_reminder_service_missing_operations_raise_clear_errors(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    service = reminder_service(session)

    with pytest.raises(ReminderNotFoundError):
        service.get_reminder(999)
    with pytest.raises(ReminderNotFoundError):
        service.complete_reminder(999)
    with pytest.raises(ReminderNotFoundError):
        service.cancel_reminder(999)
    with pytest.raises(CustomerNotFoundError):
        service.list_for_customer(999)
