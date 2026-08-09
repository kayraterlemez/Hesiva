import copy
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from argon2 import extract_parameters
from argon2.exceptions import InvalidHashError
from argon2.low_level import Type

from hesiva.database.durability import sync_parent_directory

CONFIG_FORMAT_VERSION = 1


class ConfigurationError(Exception):
    """Base exception for persistent Hesiva configuration failures."""


class ConfigurationNotFoundError(ConfigurationError):
    """Raised when the configuration file is legitimately absent."""


class InvalidConfigurationError(ConfigurationError):
    """Raised when configuration contents do not match the V1 contract."""


class ConfigurationWriteError(ConfigurationError):
    """Raised when an atomic configuration publication cannot complete."""


class ConfigurationRollbackError(ConfigurationWriteError):
    """Raised when publication and restoration of prior configuration both fail."""


@dataclass(frozen=True, slots=True)
class ApplicationConfiguration:
    """Validated configuration value retained only by infrastructure/services."""

    _payload: dict[str, Any]

    @classmethod
    def from_payload(cls, payload: Any) -> "ApplicationConfiguration":
        if not isinstance(payload, dict):
            raise InvalidConfigurationError("The Hesiva configuration root is invalid.")
        format_version = payload.get("format_version")
        if type(format_version) is not int or format_version != CONFIG_FORMAT_VERSION:
            raise InvalidConfigurationError("The Hesiva configuration version is invalid.")
        authentication = payload.get("authentication")
        if not isinstance(authentication, dict):
            raise InvalidConfigurationError("The authentication configuration is invalid.")
        password_hash = authentication.get("password_hash")
        if not isinstance(password_hash, str) or not password_hash.strip():
            raise InvalidConfigurationError("The stored password hash is invalid.")
        try:
            parameters = extract_parameters(password_hash)
        except (InvalidHashError, ValueError) as error:
            raise InvalidConfigurationError("The stored password hash is invalid.") from error
        if (
            parameters.type is not Type.ID
            or parameters.version != 19
            or parameters.time_cost < 1
            or parameters.memory_cost < 8 * parameters.parallelism
            or parameters.parallelism < 1
            or parameters.hash_len < 4
            or parameters.salt_len < 8
        ):
            raise InvalidConfigurationError("The stored password hash is not Argon2id.")
        if type(authentication.get("setup_complete")) is not bool:
            raise InvalidConfigurationError("The setup completion state is invalid.")
        return cls(copy.deepcopy(payload))

    @classmethod
    def new(cls, password_hash: str, *, setup_complete: bool) -> "ApplicationConfiguration":
        return cls.from_payload(
            {
                "format_version": CONFIG_FORMAT_VERSION,
                "authentication": {
                    "password_hash": password_hash,
                    "setup_complete": setup_complete,
                },
            }
        )

    @property
    def password_hash(self) -> str:
        return self._payload["authentication"]["password_hash"]

    @property
    def setup_complete(self) -> bool:
        return self._payload["authentication"]["setup_complete"]

    def with_authentication(
        self,
        *,
        password_hash: str | None = None,
        setup_complete: bool | None = None,
    ) -> "ApplicationConfiguration":
        payload = copy.deepcopy(self._payload)
        authentication = payload["authentication"]
        if password_hash is not None:
            authentication["password_hash"] = password_hash
        if setup_complete is not None:
            authentication["setup_complete"] = setup_complete
        return self.from_payload(payload)

    def to_payload(self) -> dict[str, Any]:
        return copy.deepcopy(self._payload)

    def to_bytes(self) -> bytes:
        return (
            json.dumps(self._payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")


class ConfigurationStore:
    """Validate and durably publish the single application-data config.json."""

    def __init__(self, path: Path) -> None:
        resolved_path = path.expanduser()
        if not resolved_path.is_absolute():
            raise ValueError("The configuration path must be absolute.")
        self.path = resolved_path

    def load(self) -> ApplicationConfiguration:
        try:
            payload_bytes = self.path.read_bytes()
        except FileNotFoundError as error:
            raise ConfigurationNotFoundError("The Hesiva configuration does not exist.") from error
        except OSError as error:
            raise InvalidConfigurationError("The Hesiva configuration cannot be read.") from error
        return self.parse_bytes(payload_bytes)

    @staticmethod
    def parse_bytes(payload_bytes: bytes) -> ApplicationConfiguration:
        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise InvalidConfigurationError("The Hesiva configuration is malformed.") from error
        return ApplicationConfiguration.from_payload(payload)

    def save(self, configuration: ApplicationConfiguration) -> None:
        validated = ApplicationConfiguration.from_payload(configuration.to_payload())
        previous_bytes: bytes | None
        try:
            previous_bytes = self.path.read_bytes()
        except FileNotFoundError:
            previous_bytes = None
        except OSError as error:
            raise ConfigurationWriteError(
                "The prior Hesiva configuration could not be preserved."
            ) from error

        staged_path = self.stage(validated, suffix=".config.json")
        published = False
        try:
            os.replace(staged_path, self.path)
            published = True
            self._set_private_permissions(self.path)
            sync_parent_directory(self.path)
        except Exception as error:
            staged_path.unlink(missing_ok=True)
            if published:
                try:
                    self._restore_previous(previous_bytes)
                except Exception as rollback_error:
                    raise ConfigurationRollbackError(
                        "Configuration publication and rollback both failed."
                    ) from rollback_error
            raise ConfigurationWriteError(
                "The Hesiva configuration could not be published durably."
            ) from error

    def stage(
        self,
        configuration: ApplicationConfiguration,
        *,
        suffix: str,
    ) -> Path:
        """Write and fsync a validated same-directory candidate without publishing it."""
        validated = ApplicationConfiguration.from_payload(configuration.to_payload())
        file_descriptor, name = tempfile.mkstemp(
            prefix=".hesiva-",
            suffix=suffix,
            dir=self.path.parent,
        )
        staged_path = Path(name)
        try:
            if os.name == "posix":
                os.fchmod(file_descriptor, 0o600)
            with os.fdopen(file_descriptor, "wb") as file_handle:
                file_handle.write(validated.to_bytes())
                file_handle.flush()
                os.fsync(file_handle.fileno())
        except Exception:
            try:
                os.close(file_descriptor)
            except OSError:
                pass
            staged_path.unlink(missing_ok=True)
            raise
        return staged_path

    def _restore_previous(self, previous_bytes: bytes | None) -> None:
        if previous_bytes is None:
            self.path.unlink(missing_ok=True)
            sync_parent_directory(self.path)
            return
        previous = self.parse_bytes(previous_bytes)
        rollback_path = self.stage(previous, suffix=".config-rollback.json")
        try:
            os.replace(rollback_path, self.path)
            self._set_private_permissions(self.path)
            sync_parent_directory(self.path)
        finally:
            rollback_path.unlink(missing_ok=True)

    @staticmethod
    def _set_private_permissions(path: Path) -> None:
        if os.name == "posix":
            path.chmod(0o600)
