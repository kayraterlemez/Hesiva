from enum import Enum

from argon2 import PasswordHasher
from argon2.exceptions import HashingError, VerificationError, VerifyMismatchError
from argon2.low_level import Type

from hesiva.authentication_policy import (
    ARGON2_HASH_LENGTH,
    ARGON2_MEMORY_COST_KIB,
    ARGON2_PARALLELISM,
    ARGON2_SALT_LENGTH,
    ARGON2_TIME_COST,
)
from hesiva.configuration import (
    ApplicationConfiguration,
    ConfigurationNotFoundError,
    ConfigurationStore,
    ConfigurationWriteError,
    InvalidConfigurationError,
)
from hesiva.services.exceptions import (
    AuthenticationFailedError,
    CredentialPersistenceError,
    InvalidCredentialStateError,
    PasswordAlreadyConfiguredError,
    PasswordMismatchError,
    ValidationError,
)


class AuthenticationState(Enum):
    """Non-secret startup classification of the persistent credential."""

    ABSENT = "absent"
    INCOMPLETE = "incomplete"
    COMPLETE = "complete"
    INVALID = "invalid"


def create_production_password_hasher() -> PasswordHasher:
    """Build the locked V1 Argon2id configuration without relying on defaults."""
    return PasswordHasher(
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_COST_KIB,
        parallelism=ARGON2_PARALLELISM,
        hash_len=ARGON2_HASH_LENGTH,
        salt_len=ARGON2_SALT_LENGTH,
        type=Type.ID,
    )


class AuthenticationService:
    """Own local password validation, hashing, verification, and credential updates."""

    def __init__(
        self,
        configuration_store: ConfigurationStore,
        password_hasher: PasswordHasher | None = None,
    ) -> None:
        self._configuration_store = configuration_store
        self._password_hasher = password_hasher or create_production_password_hasher()

    def authentication_state(self) -> AuthenticationState:
        try:
            configuration = self._configuration_store.load()
        except ConfigurationNotFoundError:
            return AuthenticationState.ABSENT
        except InvalidConfigurationError:
            return AuthenticationState.INVALID
        return (
            AuthenticationState.COMPLETE
            if configuration.setup_complete
            else AuthenticationState.INCOMPLETE
        )

    def has_password(self) -> bool:
        state = self.authentication_state()
        if state is AuthenticationState.INVALID:
            raise InvalidCredentialStateError("The stored authentication state is invalid.")
        return state in {AuthenticationState.INCOMPLETE, AuthenticationState.COMPLETE}

    def create_initial_password(self, password: str, confirmation: str) -> None:
        state = self.authentication_state()
        if state is AuthenticationState.INVALID:
            raise InvalidCredentialStateError("The stored authentication state is invalid.")
        if state is not AuthenticationState.ABSENT:
            raise PasswordAlreadyConfiguredError("A Hesiva password is already configured.")
        self._validate_new_password(password, confirmation)
        password_hash = self._hash_password(password)
        self._save(ApplicationConfiguration.new(password_hash, setup_complete=False))

    def verify_password(self, password: str) -> bool:
        configuration = self._load_valid_configuration()
        return self._verify(configuration, password)

    def _verify(self, configuration: ApplicationConfiguration, password: str) -> bool:
        try:
            return bool(self._password_hasher.verify(configuration.password_hash, password))
        except VerifyMismatchError:
            return False
        except VerificationError as error:
            raise InvalidCredentialStateError(
                "The stored authentication state is invalid."
            ) from error

    def change_password(
        self,
        current_password: str,
        new_password: str,
        confirmation: str,
    ) -> None:
        configuration = self._load_valid_configuration()
        if not self._verify(configuration, current_password):
            raise AuthenticationFailedError("The current password is incorrect.")
        self._validate_new_password(new_password, confirmation)
        new_hash = self._hash_password(new_password)
        self._save(configuration.with_authentication(password_hash=new_hash))

    def mark_setup_complete(self) -> None:
        configuration = self._load_valid_configuration()
        if configuration.setup_complete:
            return
        self._save(configuration.with_authentication(setup_complete=True))

    def _load_valid_configuration(self) -> ApplicationConfiguration:
        try:
            return self._configuration_store.load()
        except (ConfigurationNotFoundError, InvalidConfigurationError) as error:
            raise InvalidCredentialStateError(
                "The stored authentication state is missing or invalid."
            ) from error

    @staticmethod
    def _validate_new_password(password: str, confirmation: str) -> None:
        if password == "":
            raise ValidationError("Password cannot be empty.")
        if password != confirmation:
            raise PasswordMismatchError("Password confirmation does not match.")

    def _save(self, configuration: ApplicationConfiguration) -> None:
        try:
            self._configuration_store.save(configuration)
        except ConfigurationWriteError as error:
            raise CredentialPersistenceError(
                "The authentication configuration could not be saved safely."
            ) from error

    def _hash_password(self, password: str) -> str:
        try:
            return self._password_hasher.hash(password)
        except HashingError as error:
            raise CredentialPersistenceError(
                "The password could not be secured for storage."
            ) from error
