from collections.abc import Iterator
from datetime import date, datetime, time
from pathlib import Path

import pytest
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session

from hesiva.database.base import Base
from hesiva.database.engine import create_sqlite_engine
from hesiva.models import Animal, Customer, Transaction
from hesiva.repositories import AnimalRepository, CustomerRepository, TransactionRepository
from hesiva.services import AccountHistoryService, CustomerNotFoundError


@pytest.fixture
def database(tmp_path: Path) -> Iterator[tuple[Engine, Session]]:
    engine = create_sqlite_engine(tmp_path / "account-history.db")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            yield engine, session
    finally:
        engine.dispose()


def add_customer(
    session: Session,
    full_name: str = "History Customer",
    *,
    archived_at: datetime | None = None,
) -> Customer:
    return CustomerRepository(session).add(Customer(full_name=full_name, archived_at=archived_at))


def add_transaction(
    session: Session,
    customer: Customer,
    *,
    amount_kurus: int,
    transaction_date: date,
    transaction_time: time | None = None,
    description: str = "Movement",
    animal: Animal | None = None,
    voided_at: datetime | None = None,
    void_reason: str | None = None,
) -> Transaction:
    return TransactionRepository(session).add(
        Transaction(
            customer=customer,
            animal=animal,
            transaction_date=transaction_date,
            transaction_time=transaction_time,
            description=description,
            amount_kurus=amount_kurus,
            voided_at=voided_at,
            void_reason=void_reason,
        )
    )


def history_service(session: Session) -> AccountHistoryService:
    return AccountHistoryService(TransactionRepository(session))


def test_customer_without_transactions_returns_empty_history(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    customer = add_customer(session)

    assert history_service(session).list_for_customer(customer.id) == []


def test_history_is_displayed_newest_first_with_chronological_running_balances(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    customer = add_customer(session)
    first = add_transaction(
        session,
        customer,
        amount_kurus=500_000,
        transaction_date=date(2026, 8, 1),
        description="Debt",
    )
    second = add_transaction(
        session,
        customer,
        amount_kurus=-200_000,
        transaction_date=date(2026, 8, 2),
        description="Payment",
    )
    third = add_transaction(
        session,
        customer,
        amount_kurus=100_000,
        transaction_date=date(2026, 8, 3),
        description="Later debt",
    )

    rows = history_service(session).list_for_customer(customer.id)

    assert [row.transaction_id for row in rows] == [third.id, second.id, first.id]
    assert [row.running_balance_kurus for row in rows] == [400_000, 300_000, 500_000]
    assert [row.amount_kurus for row in rows] == [100_000, -200_000, 500_000]


def test_overpayment_and_null_time_follow_authoritative_ordering(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    customer = add_customer(session)
    null_time = add_transaction(
        session,
        customer,
        amount_kurus=50_000,
        transaction_date=date(2026, 8, 4),
        description="Null time first chronologically",
    )
    morning = add_transaction(
        session,
        customer,
        amount_kurus=-70_000,
        transaction_date=date(2026, 8, 4),
        transaction_time=time(9),
        description="Timed payment",
    )
    later_same_time = add_transaction(
        session,
        customer,
        amount_kurus=-5_000,
        transaction_date=date(2026, 8, 4),
        transaction_time=time(9),
        description="Stable ID tie break",
    )

    rows = history_service(session).list_for_customer(customer.id)

    assert [row.transaction_id for row in rows] == [later_same_time.id, morning.id, null_time.id]
    assert [row.running_balance_kurus for row in rows] == [-25_000, -20_000, 50_000]


def test_voided_row_remains_visible_with_original_amount_and_contributes_zero(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    customer = add_customer(session)
    first = add_transaction(
        session,
        customer,
        amount_kurus=500_000,
        transaction_date=date(2026, 8, 1),
    )
    voided = add_transaction(
        session,
        customer,
        amount_kurus=-200_000,
        transaction_date=date(2026, 8, 2),
        voided_at=datetime(2026, 8, 5, 10),
        void_reason="Yanlış kayıt",
    )
    third = add_transaction(
        session,
        customer,
        amount_kurus=100_000,
        transaction_date=date(2026, 8, 3),
    )

    rows = history_service(session).list_for_customer(customer.id)

    assert [row.transaction_id for row in rows] == [third.id, voided.id, first.id]
    assert [row.running_balance_kurus for row in rows] == [600_000, 500_000, 500_000]
    assert rows[1].amount_kurus == -200_000
    assert rows[1].void_reason == "Yanlış kayıt"


def test_history_includes_plain_animal_data_even_when_animal_is_archived(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    customer = add_customer(session)
    animal = AnimalRepository(session).add(
        Animal(
            customer=customer,
            ear_tag="TR-42",
            name="Boncuk",
            species="Sığır",
            archived_at=datetime(2026, 8, 2),
        )
    )
    transaction = add_transaction(
        session,
        customer,
        animal=animal,
        amount_kurus=10_000,
        transaction_date=date(2026, 8, 1),
    )

    row = history_service(session).list_for_customer(customer.id)[0]

    assert row.transaction_id == transaction.id
    assert row.animal_id == animal.id
    assert (row.animal_ear_tag, row.animal_name, row.animal_species) == (
        "TR-42",
        "Boncuk",
        "Sığır",
    )
    assert not hasattr(row, "_sa_instance_state")


def test_missing_and_archived_customers_are_rejected(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    archived = add_customer(session, archived_at=datetime(2026, 8, 1))
    service = history_service(session)

    with pytest.raises(CustomerNotFoundError):
        service.list_for_customer(999)
    with pytest.raises(CustomerNotFoundError):
        service.list_for_customer(archived.id)


def test_history_retrieval_uses_one_select_statement(
    database: tuple[Engine, Session],
) -> None:
    engine, session = database
    customer = add_customer(session)
    animal = AnimalRepository(session).add(Animal(customer=customer, name="One Query"))
    for index in range(5):
        add_transaction(
            session,
            customer,
            animal=animal,
            amount_kurus=10_000,
            transaction_date=date(2026, 8, index + 1),
        )
    customer_id = customer.id
    session.commit()
    select_statements: list[str] = []

    def count_selects(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            select_statements.append(statement)

    event.listen(engine, "before_cursor_execute", count_selects)
    try:
        rows = history_service(session).list_for_customer(customer_id)
    finally:
        event.remove(engine, "before_cursor_execute", count_selects)

    assert len(rows) == 5
    assert len(select_statements) == 1
