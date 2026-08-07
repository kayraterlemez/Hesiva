from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from cari.models.transaction import Transaction


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
