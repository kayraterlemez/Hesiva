from collections.abc import Iterator
from datetime import date, time
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cari.database.base import Base
from cari.database.engine import create_sqlite_engine
from cari.models import Animal, Customer, Reminder, Transaction

EXPECTED_COLUMNS = {
    "animals": {
        "id",
        "customer_id",
        "ear_tag",
        "name",
        "species",
        "notes",
        "created_at",
        "updated_at",
        "archived_at",
    },
    "customers": {
        "id",
        "legacy_id",
        "registered_on",
        "full_name",
        "phone",
        "address",
        "notes",
        "created_at",
        "updated_at",
        "archived_at",
    },
    "reminders": {
        "id",
        "customer_id",
        "remind_on",
        "note",
        "created_at",
        "updated_at",
        "completed_at",
        "cancelled_at",
    },
    "transactions": {
        "id",
        "customer_id",
        "animal_id",
        "legacy_id",
        "transaction_date",
        "transaction_time",
        "description",
        "amount_kurus",
        "note",
        "created_at",
        "updated_at",
        "voided_at",
        "void_reason",
    },
}
REQUIRED_COLUMNS = {
    "animals": {"id", "customer_id", "created_at", "updated_at"},
    "customers": {"id", "full_name", "created_at", "updated_at"},
    "reminders": {"id", "customer_id", "remind_on", "note", "created_at", "updated_at"},
    "transactions": {
        "id",
        "customer_id",
        "transaction_date",
        "description",
        "amount_kurus",
        "created_at",
        "updated_at",
    },
}


@pytest.fixture
def database_session(tmp_path: Path) -> Iterator[Session]:
    engine = create_sqlite_engine(tmp_path / "models.db")
    Base.metadata.create_all(engine)

    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


def add_customer(session: Session, full_name: str = "Test Customer") -> Customer:
    customer = Customer(full_name=full_name)
    session.add(customer)
    session.flush()
    return customer


def test_base_metadata_contains_exact_documented_business_schema() -> None:
    assert set(Base.metadata.tables) == set(EXPECTED_COLUMNS)

    for table_name, expected_columns in EXPECTED_COLUMNS.items():
        table = Base.metadata.tables[table_name]
        assert set(table.columns.keys()) == expected_columns
        for column in table.columns:
            assert column.nullable is (column.name not in REQUIRED_COLUMNS[table_name])


def test_model_foreign_keys_match_documented_structure() -> None:
    foreign_keys = {
        (
            foreign_key.parent.table.name,
            foreign_key.parent.name,
            foreign_key.column.table.name,
            foreign_key.column.name,
        )
        for table in Base.metadata.tables.values()
        for foreign_key in table.foreign_keys
    }

    assert foreign_keys == {
        ("animals", "customer_id", "customers", "id"),
        ("reminders", "customer_id", "customers", "id"),
        ("transactions", "animal_id", "animals", "id"),
        ("transactions", "customer_id", "customers", "id"),
    }


def test_customer_insert_allows_duplicate_names_and_nullable_legacy_fields(
    database_session: Session,
) -> None:
    database_session.add_all(
        [
            Customer(full_name="Duplicate Name"),
            Customer(full_name="Duplicate Name"),
        ]
    )
    database_session.commit()

    customers = database_session.scalars(select(Customer).order_by(Customer.id)).all()

    assert len(customers) == 2
    assert all(customer.full_name == "Duplicate Name" for customer in customers)
    assert all(customer.legacy_id is None for customer in customers)
    assert all(customer.registered_on is None for customer in customers)
    assert all(customer.archived_at is None for customer in customers)
    assert all(customer.created_at is not None for customer in customers)
    assert all(customer.updated_at is not None for customer in customers)
    assert all(customer.created_at.tzinfo is None for customer in customers)
    assert all(customer.updated_at.tzinfo is None for customer in customers)


def test_customer_preserves_registered_on_and_legacy_id(database_session: Session) -> None:
    customer = Customer(
        full_name="Imported Customer",
        legacy_id=42,
        registered_on=date(2018, 4, 12),
    )
    database_session.add(customer)
    database_session.commit()

    assert customer.legacy_id == 42
    assert customer.registered_on == date(2018, 4, 12)


def test_animal_requires_an_existing_customer(database_session: Session) -> None:
    database_session.add(Animal(customer_id=999))

    with pytest.raises(IntegrityError):
        database_session.flush()


def test_duplicate_animal_ear_tags_are_allowed(database_session: Session) -> None:
    customer = add_customer(database_session)
    database_session.add_all(
        [
            Animal(customer=customer, ear_tag="TAG-1"),
            Animal(customer=customer, ear_tag="TAG-1"),
        ]
    )
    database_session.commit()

    assert len(customer.animals) == 2
    assert all(animal.archived_at is None for animal in customer.animals)


def test_transaction_requires_an_existing_customer(database_session: Session) -> None:
    database_session.add(
        Transaction(
            customer_id=999,
            transaction_date=date(2026, 8, 7),
            description="Test debt",
            amount_kurus=100,
        )
    )

    with pytest.raises(IntegrityError):
        database_session.flush()


def test_transaction_accepts_positive_amount_without_animal_or_time(
    database_session: Session,
) -> None:
    customer = add_customer(database_session)
    transaction = Transaction(
        customer=customer,
        transaction_date=date(2026, 8, 7),
        description="Test debt",
        amount_kurus=150000,
    )
    database_session.add(transaction)
    database_session.commit()

    assert transaction.amount_kurus == 150000
    assert transaction.animal_id is None
    assert transaction.transaction_time is None
    assert transaction.legacy_id is None
    assert transaction.voided_at is None


def test_transaction_rejects_zero_amount(database_session: Session) -> None:
    customer = add_customer(database_session)
    database_session.add(
        Transaction(
            customer=customer,
            transaction_date=date(2026, 8, 7),
            description="Invalid movement",
            amount_kurus=0,
        )
    )

    with pytest.raises(IntegrityError):
        database_session.flush()


def test_transaction_accepts_negative_amount(database_session: Session) -> None:
    customer = add_customer(database_session)
    transaction = Transaction(
        customer=customer,
        transaction_date=date(2026, 8, 7),
        description="Test payment",
        amount_kurus=-30000,
    )
    database_session.add(transaction)
    database_session.commit()

    assert transaction.amount_kurus == -30000


def test_transaction_preserves_legacy_id_and_time(database_session: Session) -> None:
    customer = add_customer(database_session)
    transaction = Transaction(
        customer=customer,
        legacy_id=73,
        transaction_date=date(2020, 5, 4),
        transaction_time=time(9, 15),
        description="Imported movement",
        amount_kurus=25000,
    )
    database_session.add(transaction)
    database_session.commit()

    assert transaction.legacy_id == 73
    assert transaction.transaction_time == time(9, 15)


def test_reminder_requires_an_existing_customer(database_session: Session) -> None:
    database_session.add(
        Reminder(
            customer_id=999,
            remind_on=date(2026, 8, 8),
            note="Test reminder",
        )
    )

    with pytest.raises(IntegrityError):
        database_session.flush()


def test_relationships_and_event_timestamps_are_nullable(database_session: Session) -> None:
    customer = Customer(full_name="Related Customer")
    animal = Animal(customer=customer, ear_tag="TAG-2")
    transaction = Transaction(
        customer=customer,
        animal=animal,
        transaction_date=date(2026, 8, 7),
        description="Related transaction",
        amount_kurus=50000,
    )
    reminder = Reminder(
        customer=customer,
        remind_on=date(2026, 8, 8),
        note="Related reminder",
    )
    database_session.add(customer)
    database_session.commit()

    assert customer.animals == [animal]
    assert customer.transactions == [transaction]
    assert customer.reminders == [reminder]
    assert animal.customer is customer
    assert animal.transactions == [transaction]
    assert transaction.customer is customer
    assert transaction.animal is animal
    assert reminder.customer is customer
    assert customer.archived_at is None
    assert animal.archived_at is None
    assert transaction.voided_at is None
    assert reminder.completed_at is None
    assert reminder.cancelled_at is None


def test_customer_cannot_be_deleted_while_transaction_exists(
    database_session: Session,
) -> None:
    customer = Customer(full_name="Customer With History")
    transaction = Transaction(
        customer=customer,
        transaction_date=date(2026, 8, 7),
        description="Historical transaction",
        amount_kurus=10000,
    )
    database_session.add(customer)
    database_session.commit()
    customer_id = customer.id
    transaction_id = transaction.id

    database_session.delete(customer)
    with pytest.raises(IntegrityError):
        database_session.flush()
    database_session.rollback()

    persisted_transaction = database_session.get(Transaction, transaction_id)

    assert database_session.get(Customer, customer_id) is not None
    assert persisted_transaction is not None
    assert persisted_transaction.customer_id == customer_id


def test_animal_cannot_be_deleted_while_transaction_exists(
    database_session: Session,
) -> None:
    customer = Customer(full_name="Animal Owner")
    animal = Animal(customer=customer, ear_tag="TAG-HISTORY")
    transaction = Transaction(
        customer=customer,
        animal=animal,
        transaction_date=date(2026, 8, 7),
        description="Animal-linked transaction",
        amount_kurus=20000,
    )
    database_session.add(customer)
    database_session.commit()
    animal_id = animal.id
    transaction_id = transaction.id

    database_session.delete(animal)
    with pytest.raises(IntegrityError):
        database_session.flush()
    database_session.rollback()

    persisted_transaction = database_session.get(Transaction, transaction_id)

    assert database_session.get(Animal, animal_id) is not None
    assert persisted_transaction is not None
    assert persisted_transaction.animal_id == animal_id


def test_customer_cannot_be_deleted_while_reminder_exists(
    database_session: Session,
) -> None:
    customer = Customer(full_name="Customer With Reminder")
    reminder = Reminder(
        customer=customer,
        remind_on=date(2026, 8, 8),
        note="Historical reminder",
    )
    database_session.add(customer)
    database_session.commit()
    customer_id = customer.id
    reminder_id = reminder.id

    database_session.delete(customer)
    with pytest.raises(IntegrityError):
        database_session.flush()
    database_session.rollback()

    persisted_reminder = database_session.get(Reminder, reminder_id)

    assert database_session.get(Customer, customer_id) is not None
    assert persisted_reminder is not None
    assert persisted_reminder.customer_id == customer_id
