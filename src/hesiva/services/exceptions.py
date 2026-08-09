class ServiceError(Exception):
    """Base exception for expected service-layer failures."""


class ValidationError(ServiceError):
    """Raised when application input violates a business validation rule."""


class CustomerNotFoundError(ServiceError):
    """Raised when a requested customer does not exist."""


class AnimalNotFoundError(ServiceError):
    """Raised when a requested animal does not exist."""


class TransactionNotFoundError(ServiceError):
    """Raised when a requested transaction does not exist."""


class ReminderNotFoundError(ServiceError):
    """Raised when a requested reminder does not exist."""


class InvalidAnimalOwnershipError(ServiceError):
    """Raised when an animal does not belong to a transaction's customer."""


class InvalidStateTransitionError(ServiceError):
    """Raised when a lifecycle transition conflicts with existing state."""


class LegacyImportError(ServiceError):
    """Raised when a legacy import cannot be completed safely."""


class LegacyImportSourceError(LegacyImportError):
    """Raised when a legacy source does not match the supported V1 contract."""


class LegacyImportDestinationNotEmptyError(LegacyImportError):
    """Raised when a legacy import targets a non-empty business database."""


class LegacyImportVerificationError(LegacyImportError):
    """Raised when destination reconciliation fails before commit."""
