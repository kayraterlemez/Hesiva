from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cari.database.base import Base
from cari.models._timestamps import utc_now

if TYPE_CHECKING:
    from cari.models.customer import Customer
    from cari.models.transaction import Transaction


class Animal(Base):
    """An optional animal belonging to one customer."""

    __tablename__ = "animals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("customers.id"),
        nullable=False,
        index=True,
    )
    ear_tag: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    species: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    customer: Mapped[Customer] = relationship(back_populates="animals")
    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="animal",
        passive_deletes="all",
    )
