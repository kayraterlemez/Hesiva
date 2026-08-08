from collections.abc import Iterator
from datetime import date, datetime, time
from pathlib import Path

import pytest
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session

from hesiva.database.base import Base
from hesiva.database.engine import create_sqlite_engine
from hesiva.models import Customer, Transaction
from hesiva.repositories import CustomerRepository, ReportRepository, TransactionRepository
from hesiva.services import CustomerNotFoundError, ReportService, ValidationError


@pytest.fixture
def database(tmp_path: Path) -> Iterator[tuple[Engine, Session]]:
    engine = create_sqlite_engine(tmp_path / "reports.db")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            yield engine, session
    finally:
        engine.dispose()


def add_customer(
    session: Session,
    full_name: str = "Report Customer",
    *,
    phone: str | None = None,
    archived_at: datetime | None = None,
) -> Customer:
    return CustomerRepository(session).add(
        Customer(full_name=full_name, phone=phone, archived_at=archived_at)
    )


def add_transaction(
    session: Session,
    customer: Customer,
    *,
    amount_kurus: int,
    transaction_date: date,
    transaction_time: time | None = None,
    description: str = "Movement",
    voided_at: datetime | None = None,
) -> Transaction:
    return TransactionRepository(session).add(
        Transaction(
            customer=customer,
            amount_kurus=amount_kurus,
            transaction_date=transaction_date,
            transaction_time=transaction_time,
            description=description,
            voided_at=voided_at,
        )
    )


def report_service(session: Session) -> ReportService:
    return ReportService(ReportRepository(session))


def test_empty_customer_statement_returns_identity_and_zero_values(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    customer = add_customer(session, phone="0258 000 00 00")

    report = report_service(session).get_customer_statement(
        customer.id,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
    )

    assert (report.customer_id, report.full_name, report.phone) == (
        customer.id,
        "Report Customer",
        "0258 000 00 00",
    )
    assert report.rows == ()
    assert (
        report.opening_balance_kurus,
        report.total_debt_kurus,
        report.total_payment_kurus,
        report.current_balance_kurus,
    ) == (0, 0, 0, 0)


def test_statement_filters_period_and_continues_from_opening_balance(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    customer = add_customer(session)
    add_transaction(
        session,
        customer,
        amount_kurus=100_000,
        transaction_date=date(2025, 12, 31),
        description="Opening debt",
    )
    null_time = add_transaction(
        session,
        customer,
        amount_kurus=200_000,
        transaction_date=date(2026, 1, 1),
        description="Period debt",
    )
    payment = add_transaction(
        session,
        customer,
        amount_kurus=-50_000,
        transaction_date=date(2026, 1, 1),
        transaction_time=time(9),
        description="Payment",
    )
    same_time = add_transaction(
        session,
        customer,
        amount_kurus=25_000,
        transaction_date=date(2026, 1, 1),
        transaction_time=time(9),
        description="ID tie break",
    )
    add_transaction(
        session,
        customer,
        amount_kurus=999_000,
        transaction_date=date(2026, 1, 2),
        description="Voided",
        voided_at=datetime(2026, 1, 3, 10),
    )
    add_transaction(
        session,
        customer,
        amount_kurus=300_000,
        transaction_date=date(2026, 2, 1),
        description="After period",
    )

    report = report_service(session).get_customer_statement(
        customer.id,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
    )

    assert [row.transaction_id for row in report.rows] == [same_time.id, payment.id, null_time.id]
    assert [row.running_balance_kurus for row in report.rows] == [275_000, 250_000, 300_000]
    assert report.opening_balance_kurus == 100_000
    assert report.total_debt_kurus == 225_000
    assert report.total_payment_kurus == 50_000
    assert report.current_balance_kurus == 575_000
    assert all(not hasattr(row, "_sa_instance_state") for row in report.rows)


def test_statement_overpayment_remains_signed_and_voided_rows_are_absent(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    customer = add_customer(session)
    add_transaction(
        session,
        customer,
        amount_kurus=50_000,
        transaction_date=date(2026, 3, 1),
    )
    add_transaction(
        session,
        customer,
        amount_kurus=-70_000,
        transaction_date=date(2026, 3, 2),
    )
    add_transaction(
        session,
        customer,
        amount_kurus=10_000,
        transaction_date=date(2026, 3, 3),
        voided_at=datetime(2026, 3, 4),
    )

    report = report_service(session).get_customer_statement(
        customer.id,
        period_start=date(2026, 3, 1),
        period_end=date(2026, 3, 31),
    )

    assert len(report.rows) == 2
    assert report.total_debt_kurus == 50_000
    assert report.total_payment_kurus == 70_000
    assert report.current_balance_kurus == -20_000
    assert report.rows[0].running_balance_kurus == -20_000


def test_statement_rejects_missing_archived_and_invalid_periods(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    archived = add_customer(session, archived_at=datetime(2026, 1, 1))
    service = report_service(session)

    with pytest.raises(CustomerNotFoundError):
        service.get_customer_statement(
            999,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
    with pytest.raises(CustomerNotFoundError):
        service.get_customer_statement(
            archived.id,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
    with pytest.raises(ValidationError):
        service.get_customer_statement(
            archived.id,
            period_start=date(2026, 2, 1),
            period_end=date(2026, 1, 31),
        )


def test_monthly_summary_uses_calendar_boundaries_and_excludes_voids(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    first = add_customer(session, "First")
    second = add_customer(session, "Second")
    add_transaction(session, first, amount_kurus=20_000, transaction_date=date(2025, 12, 31))
    add_transaction(session, first, amount_kurus=50_000, transaction_date=date(2026, 1, 1))
    add_transaction(session, second, amount_kurus=-70_000, transaction_date=date(2026, 1, 31))
    add_transaction(session, second, amount_kurus=90_000, transaction_date=date(2026, 2, 1))
    add_transaction(
        session,
        first,
        amount_kurus=999_000,
        transaction_date=date(2026, 1, 15),
        voided_at=datetime(2026, 1, 16),
    )

    january = report_service(session).get_monthly_summary(year=2026, month=1)
    december = report_service(session).get_monthly_summary(year=2025, month=12)

    assert (january.debt_kurus, january.payment_kurus, january.net_kurus) == (
        50_000,
        70_000,
        -20_000,
    )
    assert (december.debt_kurus, december.payment_kurus, december.net_kurus) == (
        20_000,
        0,
        20_000,
    )
    assert all(type(value) is int for value in (january.debt_kurus, january.payment_kurus))


def test_empty_month_and_invalid_month_are_handled(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    service = report_service(session)

    assert service.get_monthly_summary(year=2024, month=2).net_kurus == 0
    with pytest.raises(ValidationError):
        service.get_monthly_summary(year=2026, month=13)


def test_yearly_summary_excludes_adjacent_years_and_has_all_months(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    customer = add_customer(session)
    add_transaction(session, customer, amount_kurus=10_000, transaction_date=date(2023, 12, 31))
    add_transaction(session, customer, amount_kurus=50_000, transaction_date=date(2024, 2, 29))
    add_transaction(session, customer, amount_kurus=-60_000, transaction_date=date(2024, 12, 31))
    add_transaction(session, customer, amount_kurus=70_000, transaction_date=date(2025, 1, 1))
    add_transaction(
        session,
        customer,
        amount_kurus=999_000,
        transaction_date=date(2024, 6, 1),
        voided_at=datetime(2024, 6, 2),
    )

    report = report_service(session).get_yearly_summary(year=2024)

    assert (report.debt_kurus, report.payment_kurus, report.net_kurus) == (
        50_000,
        60_000,
        -10_000,
    )
    assert [row.month for row in report.months] == list(range(1, 13))
    assert (report.months[1].debt_kurus, report.months[1].net_kurus) == (50_000, 50_000)
    assert (report.months[11].payment_kurus, report.months[11].net_kurus) == (
        60_000,
        -60_000,
    )
    assert report.months[5].net_kurus == 0


def test_empty_year_returns_twelve_zero_rows(database: tuple[Engine, Session]) -> None:
    _, session = database
    report = report_service(session).get_yearly_summary(year=2026)

    assert len(report.months) == 12
    assert all(
        (row.debt_kurus, row.payment_kurus, row.net_kurus) == (0, 0, 0) for row in report.months
    )


def test_report_query_counts_are_bounded(database: tuple[Engine, Session]) -> None:
    engine, session = database
    customer = add_customer(session)
    for day in range(1, 9):
        add_transaction(
            session,
            customer,
            amount_kurus=day * 1_000,
            transaction_date=date(2026, 1, day),
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
        service = report_service(session)
        service.get_customer_statement(
            customer_id,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        assert len(select_statements) == 2
        select_statements.clear()
        service.get_monthly_summary(year=2026, month=1)
        assert len(select_statements) == 1
        select_statements.clear()
        service.get_yearly_summary(year=2026)
        assert len(select_statements) == 1
    finally:
        event.remove(engine, "before_cursor_execute", count_selects)
