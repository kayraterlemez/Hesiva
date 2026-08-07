from sqlalchemy.orm import Session

from hesiva.models._timestamps import utc_now
from hesiva.models.animal import Animal
from hesiva.models.customer import Customer
from hesiva.repositories.animal_repository import AnimalRepository
from hesiva.repositories.customer_repository import CustomerRepository
from hesiva.services._text import normalize_optional_text
from hesiva.services.exceptions import (
    AnimalNotFoundError,
    CustomerNotFoundError,
    InvalidStateTransitionError,
)


class AnimalService:
    """Apply animal rules and own animal write transactions."""

    def __init__(
        self,
        session: Session,
        animal_repository: AnimalRepository,
        customer_repository: CustomerRepository,
    ) -> None:
        self._session = session
        self._animal_repository = animal_repository
        self._customer_repository = customer_repository

    def create_animal(
        self,
        customer_id: int,
        *,
        ear_tag: str | None = None,
        name: str | None = None,
        species: str | None = None,
        notes: str | None = None,
    ) -> Animal:
        customer = self._get_customer(customer_id)
        if customer.archived_at is not None:
            raise InvalidStateTransitionError("An archived customer cannot receive a new animal.")

        animal = Animal(
            customer_id=customer.id,
            ear_tag=normalize_optional_text(ear_tag, "ear_tag"),
            name=normalize_optional_text(name, "name"),
            species=normalize_optional_text(species, "species"),
            notes=normalize_optional_text(notes, "notes"),
        )
        try:
            self._animal_repository.add(animal)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return animal

    def update_animal(
        self,
        animal_id: int,
        *,
        ear_tag: str | None = None,
        name: str | None = None,
        species: str | None = None,
        notes: str | None = None,
    ) -> Animal:
        animal = self.get_animal(animal_id)
        normalized_ear_tag = normalize_optional_text(ear_tag, "ear_tag")
        normalized_name = normalize_optional_text(name, "name")
        normalized_species = normalize_optional_text(species, "species")
        normalized_notes = normalize_optional_text(notes, "notes")

        try:
            animal.ear_tag = normalized_ear_tag
            animal.name = normalized_name
            animal.species = normalized_species
            animal.notes = normalized_notes
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return animal

    def archive_animal(self, animal_id: int) -> Animal:
        animal = self.get_animal(animal_id)

        try:
            if animal.archived_at is None:
                animal.archived_at = utc_now()
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return animal

    def get_animal(self, animal_id: int) -> Animal:
        animal = self._animal_repository.get_by_id(animal_id)
        if animal is None:
            raise AnimalNotFoundError(f"Animal {animal_id} was not found.")
        return animal

    def list_for_customer(
        self,
        customer_id: int,
        *,
        include_archived: bool = False,
    ) -> list[Animal]:
        self._get_customer(customer_id)
        return self._animal_repository.list_for_customer(
            customer_id,
            include_archived=include_archived,
        )

    def _get_customer(self, customer_id: int) -> Customer:
        customer = self._customer_repository.get_by_id(customer_id)
        if customer is None:
            raise CustomerNotFoundError(f"Customer {customer_id} was not found.")
        return customer
