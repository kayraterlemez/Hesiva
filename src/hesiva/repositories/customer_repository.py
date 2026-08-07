from sqlalchemy import select
from sqlalchemy.orm import Session

from hesiva.models.customer import Customer


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
