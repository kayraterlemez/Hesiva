from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hesiva.database.base import Base
from hesiva.models._timestamps import utc_now

if TYPE_CHECKING:
    from hesiva.models.animal import Animal
    from hesiva.models.reminder import Reminder
    from hesiva.models.transaction import Transaction


class Customer(Base):
    """A person or business whose account is tracked by Hesiva."""

    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    legacy_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    registered_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    full_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    animals: Mapped[list[Animal]] = relationship(
        back_populates="customer",
        passive_deletes="all",
    )
    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="customer",
        passive_deletes="all",
    )
    reminders: Mapped[list[Reminder]] = relationship(
        back_populates="customer",
        passive_deletes="all",
    )
