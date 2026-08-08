from hesiva.read_models import CustomerDetail
from hesiva.repositories.customer_repository import CustomerRepository
from hesiva.services.exceptions import CustomerNotFoundError


class CustomerDetailService:
    """Expose one active customer's read-only General-tab detail."""

    def __init__(self, customer_repository: CustomerRepository) -> None:
        self._customer_repository = customer_repository

    def get_customer_detail(self, customer_id: int) -> CustomerDetail:
        detail = self._customer_repository.get_active_detail(customer_id)
        if detail is None:
            raise CustomerNotFoundError(f"Customer {customer_id} was not found.")
        return detail
