from datetime import date, time

from sqlalchemy.orm import Session

from hesiva.financial_integrity import (
    FinancialIntegrityError,
    validate_positive_magnitude,
)
from hesiva.models._timestamps import utc_now
from hesiva.models.animal import Animal
from hesiva.models.customer import Customer
from hesiva.models.transaction import Transaction
from hesiva.repositories.animal_repository import AnimalRepository
from hesiva.repositories.customer_repository import CustomerRepository
from hesiva.repositories.transaction_repository import TransactionRepository
from hesiva.services._text import normalize_optional_text, normalize_required_text
from hesiva.services.exceptions import (
    AnimalNotFoundError,
    CustomerNotFoundError,
    InvalidAnimalOwnershipError,
    InvalidStateTransitionError,
    TransactionNotFoundError,
    ValidationError,
)


class TransactionService:
    """Apply financial movement rules and own transaction write boundaries."""

    def __init__(
        self,
        session: Session,
        transaction_repository: TransactionRepository,
        customer_repository: CustomerRepository,
        animal_repository: AnimalRepository,
    ) -> None:
        self._session = session
        self._transaction_repository = transaction_repository
        self._customer_repository = customer_repository
        self._animal_repository = animal_repository

    def create_debt(
        self,
        customer_id: int,
        *,
        transaction_date: date,
        description: str,
        amount_kurus: int,
        animal_id: int | None = None,
        transaction_time: time | None = None,
        note: str | None = None,
    ) -> Transaction:
        amount_magnitude = self._validate_amount_magnitude(amount_kurus)
        return self._create_transaction(
            customer_id=customer_id,
            animal_id=animal_id,
            transaction_date=transaction_date,
            transaction_time=transaction_time,
            description=description,
            amount_kurus=amount_magnitude,
            note=note,
        )

    def create_payment(
        self,
        customer_id: int,
        *,
        transaction_date: date,
        description: str,
        amount_kurus: int,
        animal_id: int | None = None,
        transaction_time: time | None = None,
        note: str | None = None,
    ) -> Transaction:
        amount_magnitude = self._validate_amount_magnitude(amount_kurus)
        return self._create_transaction(
            customer_id=customer_id,
            animal_id=animal_id,
            transaction_date=transaction_date,
            transaction_time=transaction_time,
            description=description,
            amount_kurus=-amount_magnitude,
            note=note,
        )

    def get_transaction(self, transaction_id: int) -> Transaction:
        transaction = self._transaction_repository.get_by_id(transaction_id)
        if transaction is None:
            raise TransactionNotFoundError(f"Transaction {transaction_id} was not found.")
        return transaction

    def list_for_customer(
        self,
        customer_id: int,
        *,
        include_voided: bool = False,
    ) -> list[Transaction]:
        self._get_customer(customer_id)
        return self._transaction_repository.list_for_customer(
            customer_id,
            include_voided=include_voided,
        )

    def void_transaction(self, transaction_id: int, reason: str | None) -> Transaction:
        transaction = self.get_transaction(transaction_id)
        if transaction.voided_at is not None:
            raise InvalidStateTransitionError("The transaction is already voided.")

        normalized_reason = normalize_optional_text(reason, "reason")
        try:
            transaction.voided_at = utc_now()
            transaction.void_reason = normalized_reason
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return transaction

    def calculate_balance(self, customer_id: int) -> int:
        self._get_customer(customer_id)
        return self._transaction_repository.sum_active_amounts_for_customer(customer_id)

    def _create_transaction(
        self,
        *,
        customer_id: int,
        animal_id: int | None,
        transaction_date: date,
        transaction_time: time | None,
        description: str,
        amount_kurus: int,
        note: str | None,
    ) -> Transaction:
        customer = self._get_customer(customer_id)
        if customer.archived_at is not None:
            raise InvalidStateTransitionError(
                "An archived customer cannot receive a new transaction."
            )
        if type(transaction_date) is not date:
            raise ValidationError("transaction_date must be a date.")
        if transaction_time is not None and type(transaction_time) is not time:
            raise ValidationError("transaction_time must be a time or None.")

        animal = self._get_transaction_animal(animal_id, customer)
        transaction = Transaction(
            customer_id=customer.id,
            animal_id=None if animal is None else animal.id,
            transaction_date=transaction_date,
            transaction_time=transaction_time,
            description=normalize_required_text(description, "description"),
            amount_kurus=amount_kurus,
            note=normalize_optional_text(note, "note"),
        )

        try:
            self._transaction_repository.active_financial_totals().including(amount_kurus)
        except FinancialIntegrityError as error:
            raise ValidationError(
                "amount_kurus exceeds the supported exact financial range."
            ) from error

        try:
            self._transaction_repository.add(transaction)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return transaction

    def _get_customer(self, customer_id: int) -> Customer:
        customer = self._customer_repository.get_by_id(customer_id)
        if customer is None:
            raise CustomerNotFoundError(f"Customer {customer_id} was not found.")
        return customer

    def _get_transaction_animal(
        self,
        animal_id: int | None,
        customer: Customer,
    ) -> Animal | None:
        if animal_id is None:
            return None

        animal = self._animal_repository.get_by_id(animal_id)
        if animal is None:
            raise AnimalNotFoundError(f"Animal {animal_id} was not found.")
        if animal.customer_id != customer.id:
            raise InvalidAnimalOwnershipError(
                f"Animal {animal_id} does not belong to customer {customer.id}."
            )
        if animal.archived_at is not None:
            raise InvalidStateTransitionError(
                "An archived animal cannot be used for a new transaction."
            )
        return animal

    @staticmethod
    def _validate_amount_magnitude(amount_kurus: int) -> int:
        try:
            return validate_positive_magnitude(amount_kurus)
        except FinancialIntegrityError as error:
            raise ValidationError("amount_kurus must be a positive integer magnitude.") from error
