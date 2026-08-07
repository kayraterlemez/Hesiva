from sqlalchemy import select
from sqlalchemy.orm import Session

from hesiva.models.animal import Animal


class AnimalRepository:
    """Persist and query animals using a caller-owned session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, animal: Animal) -> Animal:
        """Add and flush an animal without committing the caller's transaction."""
        self._session.add(animal)
        self._session.flush()
        return animal

    def get_by_id(self, animal_id: int) -> Animal | None:
        return self._session.get(Animal, animal_id)

    def list_for_customer(
        self,
        customer_id: int,
        *,
        include_archived: bool = False,
    ) -> list[Animal]:
        statement = select(Animal).where(Animal.customer_id == customer_id)
        if not include_archived:
            statement = statement.where(Animal.archived_at.is_(None))

        statement = statement.order_by(Animal.id)
        return list(self._session.scalars(statement).all())

    def find_by_ear_tag(self, ear_tag: str) -> list[Animal]:
        statement = select(Animal).where(Animal.ear_tag == ear_tag).order_by(Animal.id)
        return list(self._session.scalars(statement).all())
