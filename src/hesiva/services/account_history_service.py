from hesiva.read_models import AccountHistoryRow
from hesiva.repositories.transaction_repository import TransactionRepository
from hesiva.services.exceptions import CustomerNotFoundError


class AccountHistoryService:
    """Expose one active customer's immutable financial history."""

    def __init__(self, transaction_repository: TransactionRepository) -> None:
        self._transaction_repository = transaction_repository

    def list_for_customer(self, customer_id: int) -> list[AccountHistoryRow]:
        rows = self._transaction_repository.list_active_customer_history(customer_id)
        if rows is None:
            raise CustomerNotFoundError(f"Customer {customer_id} was not found.")
        return rows
