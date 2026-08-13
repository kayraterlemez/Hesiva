from sqlalchemy import Select, case, func, select
from sqlalchemy.orm import Session

from hesiva.financial_integrity import (
    ActiveFinancialTotals,
    calculate_active_financial_totals,
)
from hesiva.models.animal import Animal
from hesiva.models.customer import Customer
from hesiva.models.transaction import Transaction
from hesiva.read_models import AccountHistoryRow


class TransactionRepository:
    """Persist and query transactions using a caller-owned session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, transaction: Transaction) -> Transaction:
        """Add and flush a transaction without committing the caller's transaction."""
        self._session.add(transaction)
        self._session.flush()
        return transaction

    def get_by_id(self, transaction_id: int) -> Transaction | None:
        return self._session.get(Transaction, transaction_id)

    def get_by_legacy_id(self, legacy_id: int) -> Transaction | None:
        statement = select(Transaction).where(Transaction.legacy_id == legacy_id)
        return self._session.execute(statement).scalar_one_or_none()

    def list_for_customer(
        self,
        customer_id: int,
        *,
        include_voided: bool = False,
    ) -> list[Transaction]:
        statement = select(Transaction).where(Transaction.customer_id == customer_id)
        return self._list_history(statement, include_voided=include_voided)

    def list_for_animal(
        self,
        animal_id: int,
        *,
        include_voided: bool = False,
    ) -> list[Transaction]:
        statement = select(Transaction).where(Transaction.animal_id == animal_id)
        return self._list_history(statement, include_voided=include_voided)

    def sum_active_amounts_for_customer(self, customer_id: int) -> int:
        statement = select(func.coalesce(func.sum(Transaction.amount_kurus), 0)).where(
            Transaction.customer_id == customer_id,
            Transaction.voided_at.is_(None),
        )
        return int(self._session.scalar(statement))

    def active_financial_totals(self) -> ActiveFinancialTotals:
        statement = (
            select(Transaction.amount_kurus)
            .where(Transaction.voided_at.is_(None))
            .execution_options(yield_per=1000)
        )
        return calculate_active_financial_totals(self._session.scalars(statement))

    def list_active_customer_history(
        self,
        customer_id: int,
    ) -> list[AccountHistoryRow] | None:
        chronological_balance = func.sum(
            case(
                (Transaction.voided_at.is_(None), Transaction.amount_kurus),
                else_=0,
            )
        ).over(
            partition_by=Customer.id,
            order_by=(
                Transaction.transaction_date.asc(),
                Transaction.transaction_time.asc().nulls_first(),
                Transaction.id.asc(),
            ),
            rows=(None, 0),
        )
        statement = (
            select(
                Customer.id.label("customer_id"),
                Transaction.id.label("transaction_id"),
                Transaction.transaction_date,
                Transaction.transaction_time,
                Transaction.description,
                Transaction.animal_id,
                Animal.ear_tag.label("animal_ear_tag"),
                Animal.name.label("animal_name"),
                Animal.species.label("animal_species"),
                Transaction.amount_kurus,
                chronological_balance.label("running_balance_kurus"),
                Transaction.voided_at,
                Transaction.void_reason,
            )
            .select_from(Customer)
            .outerjoin(Transaction, Transaction.customer_id == Customer.id)
            .outerjoin(Animal, Animal.id == Transaction.animal_id)
            .where(
                Customer.id == customer_id,
                Customer.archived_at.is_(None),
            )
            .order_by(
                Transaction.transaction_date.desc().nulls_last(),
                Transaction.transaction_time.desc().nulls_last(),
                Transaction.id.desc().nulls_last(),
            )
        )
        rows = list(self._session.execute(statement))
        if not rows:
            return None
        return [
            AccountHistoryRow(
                transaction_id=row.transaction_id,
                transaction_date=row.transaction_date,
                transaction_time=row.transaction_time,
                description=row.description,
                animal_id=row.animal_id,
                animal_ear_tag=row.animal_ear_tag,
                animal_name=row.animal_name,
                animal_species=row.animal_species,
                amount_kurus=int(row.amount_kurus),
                running_balance_kurus=int(row.running_balance_kurus),
                voided_at=row.voided_at,
                void_reason=row.void_reason,
            )
            for row in rows
            if row.transaction_id is not None
        ]

    def _list_history(
        self,
        statement: Select[tuple[Transaction]],
        *,
        include_voided: bool,
    ) -> list[Transaction]:
        if not include_voided:
            statement = statement.where(Transaction.voided_at.is_(None))

        statement = statement.order_by(
            Transaction.transaction_date,
            Transaction.transaction_time.asc().nulls_first(),
            Transaction.id,
        )
        return list(self._session.scalars(statement).all())
