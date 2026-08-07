from cari.database.base import Base
from cari.models.animal import Animal
from cari.models.customer import Customer
from cari.models.reminder import Reminder
from cari.models.transaction import Transaction

model_metadata = Base.metadata

__all__ = ["Animal", "Customer", "Reminder", "Transaction", "model_metadata"]
