from collections.abc import Iterator
from datetime import date, datetime, time
from pathlib import Path

import pytest
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session

from hesiva.database.base import Base
from hesiva.database.engine import create_sqlite_engine
from hesiva.models import Customer, Transaction
from hesiva.read_models import CustomerDetail, CustomerSummarySort
from hesiva.repositories import CustomerRepository, TransactionRepository
from hesiva.services import CustomerDetailService, CustomerNotFoundError, CustomerSummaryService


@pytest.fixture
def database(tmp_path: Path) -> Iterator[tuple[Engine, Session]]:
    engine = create_sqlite_engine(tmp_path / "customer-details.db")
    Base.metadata.create_all(engine)

    try:
        with Session(engine) as session:
            yield engine, session
    finally:
        engine.dispose()


def add_customer(
    session: Session,
    full_name: str,
    *,
    phone: str | None = None,
    address: str | None = None,
    notes: str | None = None,
    registered_on: date | None = None,
    archived_at: datetime | None = None,
) -> Customer:
    return CustomerRepository(session).add(
        Customer(
            full_name=full_name,
            phone=phone,
            address=address,
            notes=notes,
            registered_on=registered_on,
            archived_at=archived_at,
        )
    )


def add_transaction(
    session: Session,
    customer: Customer,
    *,
    amount_kurus: int,
    transaction_date: date,
    transaction_time: time | None = None,
    voided_at: datetime | None = None,
) -> Transaction:
    return TransactionRepository(session).add(
        Transaction(
            customer=customer,
            transaction_date=transaction_date,
            transaction_time=transaction_time,
            description="Detail transaction",
            amount_kurus=amount_kurus,
            voided_at=voided_at,
        )
    )


def detail_service(session: Session) -> CustomerDetailService:
    return CustomerDetailService(CustomerRepository(session))


def test_active_customer_without_transactions_returns_scalar_fields_and_zero_totals(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    customer = add_customer(
        session,
        "Detailed Customer",
        phone="0258 123 45 67",
        address="Merkez Mahallesi",
        notes="Aylık ödeme yapar.",
        registered_on=date(2022, 1, 14),
    )

    detail = detail_service(session).get_customer_detail(customer.id)

    assert detail == CustomerDetail(
        customer_id=customer.id,
        full_name="Detailed Customer",
        phone="0258 123 45 67",
        address="Merkez Mahallesi",
        notes="Aylık ödeme yapar.",
        registered_on=date(2022, 1, 14),
        total_debt_kurus=0,
        total_payment_kurus=0,
        balance_kurus=0,
        last_transaction_date=None,
        last_transaction_time=None,
    )
    assert not hasattr(detail, "_sa_instance_state")


def test_detail_aggregates_mixed_activity_and_excludes_voided_transactions(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    customer = add_customer(session, "Mixed Account")
    add_transaction(
        session,
        customer,
        amount_kurus=500_000,
        transaction_date=date(2026, 8, 1),
    )
    add_transaction(
        session,
        customer,
        amount_kurus=200_000,
        transaction_date=date(2026, 8, 2),
    )
    add_transaction(
        session,
        customer,
        amount_kurus=-300_000,
        transaction_date=date(2026, 8, 2),
        transaction_time=time(10, 15),
    )
    add_transaction(
        session,
        customer,
        amount_kurus=900_000,
        transaction_date=date(2026, 8, 3),
        transaction_time=time(11),
        voided_at=datetime(2026, 8, 3, 12),
    )

    detail = detail_service(session).get_customer_detail(customer.id)

    assert detail.total_debt_kurus == 700_000
    assert detail.total_payment_kurus == 300_000
    assert detail.balance_kurus == 400_000
    assert detail.last_transaction_date == date(2026, 8, 2)
    assert detail.last_transaction_time == time(10, 15)


def test_detail_preserves_negative_overpayment_and_null_time_ordering(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    customer = add_customer(session, "Overpaid Account")
    add_transaction(
        session,
        customer,
        amount_kurus=500_000,
        transaction_date=date(2026, 8, 4),
        transaction_time=time(9),
    )
    add_transaction(
        session,
        customer,
        amount_kurus=-600_000,
        transaction_date=date(2026, 8, 5),
    )
    add_transaction(
        session,
        customer,
        amount_kurus=-100,
        transaction_date=date(2026, 8, 5),
        transaction_time=time(8),
    )

    detail = detail_service(session).get_customer_detail(customer.id)

    assert detail.total_debt_kurus == 500_000
    assert detail.total_payment_kurus == 600_100
    assert detail.balance_kurus == -100_100
    assert detail.last_transaction_date == date(2026, 8, 5)
    assert detail.last_transaction_time == time(8)


def test_missing_optional_fields_are_preserved_as_none(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    customer = add_customer(session, "Minimal Customer")

    detail = detail_service(session).get_customer_detail(customer.id)

    assert detail.phone is None
    assert detail.address is None
    assert detail.notes is None
    assert detail.registered_on is None


def test_missing_and_archived_customers_are_rejected_by_active_detail_api(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    archived = add_customer(
        session,
        "Archived Customer",
        archived_at=datetime(2026, 8, 1),
    )
    service = detail_service(session)

    with pytest.raises(CustomerNotFoundError):
        service.get_customer_detail(999)
    with pytest.raises(CustomerNotFoundError):
        service.get_customer_detail(archived.id)


def test_customer_summary_and_detail_share_balance_and_last_transaction_semantics(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    customer = add_customer(session, "Consistent Customer")
    add_transaction(
        session,
        customer,
        amount_kurus=350_000,
        transaction_date=date(2026, 8, 6),
        transaction_time=time(14, 30),
    )
    add_transaction(
        session,
        customer,
        amount_kurus=-50_000,
        transaction_date=date(2026, 8, 7),
    )
    repository = CustomerRepository(session)

    summary = CustomerSummaryService(repository).list_customer_summaries(
        sort=CustomerSummarySort.NAME
    )[0]
    detail = CustomerDetailService(repository).get_customer_detail(customer.id)

    assert detail.balance_kurus == summary.balance_kurus
    assert detail.last_transaction_date == summary.last_transaction_date
    assert detail.last_transaction_time == summary.last_transaction_time


def test_customer_detail_uses_one_select_statement(
    database: tuple[Engine, Session],
) -> None:
    engine, session = database
    customer = add_customer(session, "One Query Customer")
    add_transaction(
        session,
        customer,
        amount_kurus=100_000,
        transaction_date=date(2026, 8, 8),
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
        detail = detail_service(session).get_customer_detail(customer_id)
    finally:
        event.remove(engine, "before_cursor_execute", count_selects)

    assert detail.customer_id == customer_id
    assert len(select_statements) == 1
