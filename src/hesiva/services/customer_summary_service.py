from hesiva.read_models import CustomerSummary, CustomerSummarySort
from hesiva.repositories.customer_repository import CustomerRepository


class CustomerSummaryService:
    """Expose active customer-list summaries without leaking persistence rows."""

    def __init__(self, customer_repository: CustomerRepository) -> None:
        self._customer_repository = customer_repository

    def list_customer_summaries(
        self,
        *,
        query: str = "",
        sort: CustomerSummarySort = CustomerSummarySort.HIGHEST_DEBT,
    ) -> list[CustomerSummary]:
        return self._customer_repository.list_active_summaries(
            query=query.strip(),
            sort=sort,
        )
