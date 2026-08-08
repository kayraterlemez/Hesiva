from collections.abc import Iterator
from datetime import date, datetime, time
from pathlib import Path

import pytest
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session

from hesiva.database.base import Base
from hesiva.database.engine import create_sqlite_engine
from hesiva.models import Customer, Transaction
from hesiva.read_models import CustomerSummary, CustomerSummarySort
from hesiva.repositories import CustomerRepository, TransactionRepository
from hesiva.services import CustomerSummaryService


@pytest.fixture
def database(tmp_path: Path) -> Iterator[tuple[Engine, Session]]:
    engine = create_sqlite_engine(tmp_path / "customer-summaries.db")
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
    registered_on: date | None = None,
    archived_at: datetime | None = None,
) -> Customer:
    return CustomerRepository(session).add(
        Customer(
            full_name=full_name,
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
            description="Summary transaction",
            amount_kurus=amount_kurus,
            voided_at=voided_at,
        )
    )


def summary_service(session: Session) -> CustomerSummaryService:
    return CustomerSummaryService(CustomerRepository(session))


def test_summaries_use_active_transactions_and_preserve_signed_balances(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    no_activity = add_customer(session, "No Activity")
    debt_customer = add_customer(session, "Debt Customer")
    mixed_customer = add_customer(session, "Mixed Customer")
    overpaid_customer = add_customer(session, "Overpaid Customer")
    archived_customer = add_customer(
        session,
        "Archived Customer",
        archived_at=datetime(2026, 8, 1),
    )

    add_transaction(
        session,
        debt_customer,
        amount_kurus=200_000,
        transaction_date=date(2026, 8, 1),
    )
    add_transaction(
        session,
        mixed_customer,
        amount_kurus=500_000,
        transaction_date=date(2026, 8, 1),
        transaction_time=time(9),
    )
    add_transaction(
        session,
        mixed_customer,
        amount_kurus=-200_000,
        transaction_date=date(2026, 8, 2),
        transaction_time=time(10),
    )
    add_transaction(
        session,
        mixed_customer,
        amount_kurus=900_000,
        transaction_date=date(2026, 8, 3),
        transaction_time=time(11),
        voided_at=datetime(2026, 8, 4),
    )
    add_transaction(
        session,
        overpaid_customer,
        amount_kurus=100_000,
        transaction_date=date(2026, 8, 1),
    )
    add_transaction(
        session,
        overpaid_customer,
        amount_kurus=-300_000,
        transaction_date=date(2026, 8, 2),
    )
    add_transaction(
        session,
        archived_customer,
        amount_kurus=800_000,
        transaction_date=date(2026, 8, 5),
    )

    summaries = summary_service(session).list_customer_summaries(sort=CustomerSummarySort.NAME)
    by_id = {summary.customer_id: summary for summary in summaries}

    assert all(isinstance(summary, CustomerSummary) for summary in summaries)
    assert archived_customer.id not in by_id
    assert by_id[no_activity.id].balance_kurus == 0
    assert by_id[no_activity.id].last_transaction_date is None
    assert by_id[no_activity.id].last_transaction_time is None
    assert by_id[debt_customer.id].balance_kurus == 200_000
    assert by_id[mixed_customer.id].balance_kurus == 300_000
    assert by_id[mixed_customer.id].last_transaction_date == date(2026, 8, 2)
    assert by_id[mixed_customer.id].last_transaction_time == time(10)
    assert by_id[overpaid_customer.id].balance_kurus == -200_000


def test_latest_transaction_reverses_null_time_and_id_ordering(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    customer = add_customer(session, "Latest Selection")
    null_time_customer = add_customer(session, "Only Null Time")
    add_transaction(
        session,
        customer,
        amount_kurus=100,
        transaction_date=date(2026, 8, 6),
        transaction_time=time(12),
    )
    add_transaction(
        session,
        customer,
        amount_kurus=200,
        transaction_date=date(2026, 8, 7),
    )
    add_transaction(
        session,
        customer,
        amount_kurus=300,
        transaction_date=date(2026, 8, 7),
        transaction_time=time(8),
    )
    add_transaction(
        session,
        customer,
        amount_kurus=400,
        transaction_date=date(2026, 8, 7),
        transaction_time=time(8),
    )
    add_transaction(
        session,
        customer,
        amount_kurus=500,
        transaction_date=date(2026, 8, 8),
        transaction_time=time(9),
        voided_at=datetime(2026, 8, 8, 10),
    )
    add_transaction(
        session,
        null_time_customer,
        amount_kurus=600,
        transaction_date=date(2026, 8, 9),
    )

    summaries = summary_service(session).list_customer_summaries(sort=CustomerSummarySort.NAME)
    by_id = {summary.customer_id: summary for summary in summaries}

    assert by_id[customer.id].last_transaction_date == date(2026, 8, 7)
    assert by_id[customer.id].last_transaction_time == time(8)
    assert by_id[null_time_customer.id].last_transaction_date == date(2026, 8, 9)
    assert by_id[null_time_customer.id].last_transaction_time is None


def test_highest_debt_sort_uses_raw_signed_balance_and_deterministic_ties(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    balances = (
        ("Highest", 800_000),
        ("Same Debt", 200_000),
        ("Same Debt", 200_000),
        ("Zero", None),
        ("Small Overpayment", -100_000),
        ("Large Overpayment", -300_000),
    )
    customers: list[Customer] = []
    for name, balance in balances:
        customer = add_customer(session, name)
        customers.append(customer)
        if balance is not None:
            add_transaction(
                session,
                customer,
                amount_kurus=balance,
                transaction_date=date(2026, 8, 1),
            )

    summaries = summary_service(session).list_customer_summaries(
        sort=CustomerSummarySort.HIGHEST_DEBT
    )

    assert [summary.balance_kurus for summary in summaries] == [
        800_000,
        200_000,
        200_000,
        0,
        -100_000,
        -300_000,
    ]
    assert [summary.customer_id for summary in summaries[1:3]] == [
        customers[1].id,
        customers[2].id,
    ]


def test_last_transaction_sort_puts_recent_activity_first_and_no_activity_last(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    no_activity = add_customer(session, "No Activity")
    older = add_customer(session, "Older")
    alpha_tie = add_customer(session, "Alpha Tie")
    beta_tie = add_customer(session, "Beta Tie")
    null_time = add_customer(session, "Null Time")

    add_transaction(
        session,
        older,
        amount_kurus=100,
        transaction_date=date(2026, 8, 1),
        transaction_time=time(12),
    )
    for customer in (alpha_tie, beta_tie):
        add_transaction(
            session,
            customer,
            amount_kurus=100,
            transaction_date=date(2026, 8, 3),
            transaction_time=time(9),
        )
    add_transaction(
        session,
        null_time,
        amount_kurus=100,
        transaction_date=date(2026, 8, 3),
    )

    summaries = summary_service(session).list_customer_summaries(
        sort=CustomerSummarySort.LAST_TRANSACTION
    )

    assert [summary.customer_id for summary in summaries] == [
        alpha_tie.id,
        beta_tie.id,
        null_time.id,
        older.id,
        no_activity.id,
    ]


def test_registered_on_sort_is_descending_with_nulls_last_and_stable_ties(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    newest_alpha = add_customer(session, "Alpha", registered_on=date(2026, 8, 5))
    newest_beta = add_customer(session, "Beta", registered_on=date(2026, 8, 5))
    older = add_customer(session, "Older", registered_on=date(2020, 1, 1))
    unknown_alpha = add_customer(session, "Unknown Alpha")
    unknown_beta = add_customer(session, "Unknown Beta")

    summaries = summary_service(session).list_customer_summaries(
        sort=CustomerSummarySort.REGISTERED_ON
    )

    assert [summary.customer_id for summary in summaries] == [
        newest_alpha.id,
        newest_beta.id,
        older.id,
        unknown_alpha.id,
        unknown_beta.id,
    ]
    assert [summary.registered_on for summary in summaries] == [
        date(2026, 8, 5),
        date(2026, 8, 5),
        date(2020, 1, 1),
        None,
        None,
    ]


def test_name_sort_and_search_preserve_existing_database_contract(
    database: tuple[Engine, Session],
) -> None:
    _, session = database
    first_duplicate = add_customer(session, "Alpha Match")
    second_duplicate = add_customer(session, "Alpha Match")
    zulu_match = add_customer(session, "Zulu Match")
    unrelated = add_customer(session, "Unrelated")
    service = summary_service(session)

    matches = service.list_customer_summaries(
        query="  Match  ",
        sort=CustomerSummarySort.NAME,
    )
    all_summaries = service.list_customer_summaries(
        query="   ",
        sort=CustomerSummarySort.NAME,
    )

    assert [summary.customer_id for summary in matches] == [
        first_duplicate.id,
        second_duplicate.id,
        zulu_match.id,
    ]
    assert [summary.customer_id for summary in all_summaries] == [
        first_duplicate.id,
        second_duplicate.id,
        unrelated.id,
        zulu_match.id,
    ]


def test_customer_summary_query_count_does_not_scale_with_customer_count(
    database: tuple[Engine, Session],
) -> None:
    engine, session = database
    for customer_number in range(12):
        customer = add_customer(session, f"Customer {customer_number:02d}")
        add_transaction(
            session,
            customer,
            amount_kurus=(customer_number + 1) * 100,
            transaction_date=date(2026, 8, 1),
        )
        add_transaction(
            session,
            customer,
            amount_kurus=-50,
            transaction_date=date(2026, 8, 2),
        )
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
        summaries = summary_service(session).list_customer_summaries()
    finally:
        event.remove(engine, "before_cursor_execute", count_selects)

    assert len(summaries) == 12
    assert len(select_statements) == 1
