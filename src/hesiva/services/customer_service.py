from datetime import date

from sqlalchemy.orm import Session

from hesiva.models._timestamps import utc_now
from hesiva.models.customer import Customer
from hesiva.repositories.customer_repository import CustomerRepository
from hesiva.services._text import normalize_optional_text, normalize_required_text
from hesiva.services.exceptions import CustomerNotFoundError


class CustomerService:
    """Apply customer rules and own customer write transactions."""

    def __init__(self, session: Session, customer_repository: CustomerRepository) -> None:
        self._session = session
        self._customer_repository = customer_repository

    def create_customer(
        self,
        full_name: str,
        *,
        phone: str | None = None,
        address: str | None = None,
        notes: str | None = None,
        registered_on: date | None = None,
    ) -> Customer:
        customer = Customer(
            full_name=normalize_required_text(full_name, "full_name"),
            phone=normalize_optional_text(phone, "phone"),
            address=normalize_optional_text(address, "address"),
            notes=normalize_optional_text(notes, "notes"),
            registered_on=registered_on,
        )

        try:
            self._customer_repository.add(customer)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return customer

    def update_customer(
        self,
        customer_id: int,
        *,
        full_name: str,
        phone: str | None = None,
        address: str | None = None,
        notes: str | None = None,
        registered_on: date | None = None,
    ) -> Customer:
        customer = self.get_customer(customer_id)
        normalized_full_name = normalize_required_text(full_name, "full_name")
        normalized_phone = normalize_optional_text(phone, "phone")
        normalized_address = normalize_optional_text(address, "address")
        normalized_notes = normalize_optional_text(notes, "notes")

        try:
            customer.full_name = normalized_full_name
            customer.phone = normalized_phone
            customer.address = normalized_address
            customer.notes = normalized_notes
            customer.registered_on = registered_on
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return customer

    def archive_customer(self, customer_id: int) -> Customer:
        customer = self.get_customer(customer_id)

        try:
            if customer.archived_at is None:
                customer.archived_at = utc_now()
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return customer

    def unarchive_customer(self, customer_id: int) -> Customer:
        customer = self.get_customer(customer_id)

        try:
            if customer.archived_at is not None:
                customer.archived_at = None
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return customer

    def get_customer(self, customer_id: int) -> Customer:
        customer = self._customer_repository.get_by_id(customer_id)
        if customer is None:
            raise CustomerNotFoundError(f"Customer {customer_id} was not found.")
        return customer

    def search_customers(self, query: str) -> list[Customer]:
        return self._customer_repository.search_by_name(query.strip())

    def list_active_customers(self) -> list[Customer]:
        return self._customer_repository.list_active()
