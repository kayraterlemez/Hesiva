from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from hesiva.models.customer import Customer
from hesiva.models.transaction import Transaction
from hesiva.read_models import CustomerSummary, CustomerSummarySort


class CustomerRepository:
    """Persist and query customers using a caller-owned session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, customer: Customer) -> Customer:
        """Add and flush a customer without committing the caller's transaction."""
        self._session.add(customer)
        self._session.flush()
        return customer

    def get_by_id(self, customer_id: int) -> Customer | None:
        return self._session.get(Customer, customer_id)

    def get_by_legacy_id(self, legacy_id: int) -> Customer | None:
        statement = select(Customer).where(Customer.legacy_id == legacy_id)
        return self._session.execute(statement).scalar_one_or_none()

    def search_by_name(self, query: str) -> list[Customer]:
        statement = (
            select(Customer)
            .where(Customer.full_name.contains(query, autoescape=True))
            .order_by(Customer.full_name, Customer.id)
        )
        return list(self._session.scalars(statement).all())

    def list_active(self) -> list[Customer]:
        statement = (
            select(Customer)
            .where(Customer.archived_at.is_(None))
            .order_by(Customer.full_name, Customer.id)
        )
        return list(self._session.scalars(statement).all())

    def list_archived(self) -> list[Customer]:
        statement = (
            select(Customer)
            .where(Customer.archived_at.is_not(None))
            .order_by(Customer.full_name, Customer.id)
        )
        return list(self._session.scalars(statement).all())

    def list_active_summaries(
        self,
        *,
        query: str = "",
        sort: CustomerSummarySort = CustomerSummarySort.HIGHEST_DEBT,
    ) -> list[CustomerSummary]:
        balance_by_customer = (
            select(
                Transaction.customer_id.label("customer_id"),
                func.sum(Transaction.amount_kurus).label("balance_kurus"),
            )
            .where(Transaction.voided_at.is_(None))
            .group_by(Transaction.customer_id)
            .subquery()
        )
        ranked_transactions = (
            select(
                Transaction.customer_id.label("customer_id"),
                Transaction.transaction_date.label("transaction_date"),
                Transaction.transaction_time.label("transaction_time"),
                func.row_number()
                .over(
                    partition_by=Transaction.customer_id,
                    order_by=(
                        Transaction.transaction_date.desc(),
                        Transaction.transaction_time.desc().nulls_last(),
                        Transaction.id.desc(),
                    ),
                )
                .label("latest_rank"),
            )
            .where(Transaction.voided_at.is_(None))
            .subquery()
        )
        balance_kurus = func.coalesce(balance_by_customer.c.balance_kurus, 0).label("balance_kurus")
        statement = (
            select(
                Customer.id.label("customer_id"),
                Customer.full_name,
                balance_kurus,
                Customer.registered_on,
                ranked_transactions.c.transaction_date.label("last_transaction_date"),
                ranked_transactions.c.transaction_time.label("last_transaction_time"),
            )
            .outerjoin(
                balance_by_customer,
                balance_by_customer.c.customer_id == Customer.id,
            )
            .outerjoin(
                ranked_transactions,
                and_(
                    ranked_transactions.c.customer_id == Customer.id,
                    ranked_transactions.c.latest_rank == 1,
                ),
            )
            .where(Customer.archived_at.is_(None))
        )
        if query:
            statement = statement.where(Customer.full_name.contains(query, autoescape=True))

        if sort is CustomerSummarySort.HIGHEST_DEBT:
            statement = statement.order_by(balance_kurus.desc(), Customer.full_name, Customer.id)
        elif sort is CustomerSummarySort.NAME:
            statement = statement.order_by(Customer.full_name, Customer.id)
        elif sort is CustomerSummarySort.LAST_TRANSACTION:
            statement = statement.order_by(
                ranked_transactions.c.transaction_date.desc().nulls_last(),
                ranked_transactions.c.transaction_time.desc().nulls_last(),
                Customer.full_name,
                Customer.id,
            )
        elif sort is CustomerSummarySort.REGISTERED_ON:
            statement = statement.order_by(
                Customer.registered_on.desc().nulls_last(),
                Customer.full_name,
                Customer.id,
            )
        else:
            raise ValueError(f"Unsupported customer summary sort: {sort!r}")

        rows = self._session.execute(statement)
        return [
            CustomerSummary(
                customer_id=row.customer_id,
                full_name=row.full_name,
                balance_kurus=int(row.balance_kurus),
                registered_on=row.registered_on,
                last_transaction_date=row.last_transaction_date,
                last_transaction_time=row.last_transaction_time,
            )
            for row in rows
        ]
