import copy
import json
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from argon2 import extract_parameters
from argon2.exceptions import InvalidHashError
from argon2.low_level import Type

from hesiva.authentication_policy import (
    ARGON2_ENCODED_HASH_LENGTH_LIMIT,
    ARGON2_HASH_LENGTH,
    ARGON2_MEMORY_COST_KIB,
    ARGON2_PARALLELISM,
    ARGON2_SALT_LENGTH,
    ARGON2_TIME_COST,
)
from hesiva.database.durability import sync_parent_directory

CONFIG_FORMAT_VERSION = 1
CONFIGURATION_SIZE_LIMIT = 4 * 1024 * 1024
_MISSING = object()


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
        try:
            _validate_json_domain(payload)
        except RecursionError as error:
            raise InvalidConfigurationError(
                "The Hesiva configuration is too deeply nested."
            ) from error
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
            encoded_password_hash = password_hash.encode("ascii")
        except UnicodeEncodeError as error:
            raise InvalidConfigurationError("The stored password hash is invalid.") from error
        if len(encoded_password_hash) > ARGON2_ENCODED_HASH_LENGTH_LIMIT:
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
            or parameters.time_cost > ARGON2_TIME_COST
            or parameters.memory_cost > ARGON2_MEMORY_COST_KIB
            or parameters.parallelism > ARGON2_PARALLELISM
            or parameters.hash_len > ARGON2_HASH_LENGTH
            or parameters.salt_len > ARGON2_SALT_LENGTH
        ):
            raise InvalidConfigurationError("The stored password hash is not Argon2id.")
        if type(authentication.get("setup_complete")) is not bool:
            raise InvalidConfigurationError("The setup completion state is invalid.")
        backup = payload.get("backup", _MISSING)
        if backup is not _MISSING:
            if not isinstance(backup, dict):
                raise InvalidConfigurationError("The backup configuration is invalid.")
            if "destination_directory" not in backup:
                raise InvalidConfigurationError("The backup destination configuration is invalid.")
            destination_directory = backup["destination_directory"]
            if destination_directory is not None:
                if (
                    not isinstance(destination_directory, str)
                    or not destination_directory.strip()
                    or "\0" in destination_directory
                    or not _is_absolute_path_on_supported_platform(destination_directory)
                ):
                    raise InvalidConfigurationError(
                        "The backup destination configuration is invalid."
                    )
        try:
            preserved_payload = copy.deepcopy(payload)
        except RecursionError as error:
            raise InvalidConfigurationError("The Hesiva configuration is too deeply nested.") from (
                error
            )
        return cls(preserved_payload)

    @classmethod
    def new(cls, password_hash: str, *, setup_complete: bool) -> "ApplicationConfiguration":
        return cls.from_payload(
            {
                "format_version": CONFIG_FORMAT_VERSION,
                "authentication": {
                    "password_hash": password_hash,
                    "setup_complete": setup_complete,
                },
                "backup": {"destination_directory": None},
            }
        )

    @property
    def password_hash(self) -> str:
        return self._payload["authentication"]["password_hash"]

    @property
    def setup_complete(self) -> bool:
        return self._payload["authentication"]["setup_complete"]

    @property
    def backup_destination_directory(self) -> str | None:
        backup = self._payload.get("backup")
        if backup is None:
            return None
        return backup["destination_directory"]

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

    def with_backup_destination_directory(
        self,
        destination_directory: str | Path | None,
    ) -> "ApplicationConfiguration":
        payload = copy.deepcopy(self._payload)
        backup = payload.setdefault("backup", {})
        backup["destination_directory"] = (
            None if destination_directory is None else str(destination_directory)
        )
        return self.from_payload(payload)

    def to_payload(self) -> dict[str, Any]:
        return copy.deepcopy(self._payload)

    def to_bytes(self) -> bytes:
        return (
            json.dumps(
                self._payload,
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")


def _is_absolute_path_on_supported_platform(value: str) -> bool:
    """Accept absolute POSIX or Windows paths without checking current availability."""
    return PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute()


class ConfigurationStore:
    """Validate and durably publish the single application-data config.json."""

    def __init__(self, path: Path) -> None:
        resolved_path = path.expanduser()
        if not resolved_path.is_absolute():
            raise ValueError("The configuration path must be absolute.")
        self.path = resolved_path

    def load(self) -> ApplicationConfiguration:
        try:
            with self.path.open("rb") as file_handle:
                payload_bytes = file_handle.read(CONFIGURATION_SIZE_LIMIT + 1)
        except FileNotFoundError as error:
            raise ConfigurationNotFoundError("The Hesiva configuration does not exist.") from error
        except OSError as error:
            raise InvalidConfigurationError("The Hesiva configuration cannot be read.") from error
        return self.parse_bytes(payload_bytes)

    @staticmethod
    def parse_bytes(payload_bytes: bytes) -> ApplicationConfiguration:
        if len(payload_bytes) > CONFIGURATION_SIZE_LIMIT:
            raise InvalidConfigurationError("The Hesiva configuration is too large.")
        try:
            payload = json.loads(
                payload_bytes.decode("utf-8"),
                parse_constant=_reject_nonstandard_json_constant,
                parse_float=_parse_finite_json_float,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as error:
            raise InvalidConfigurationError("The Hesiva configuration is malformed.") from error
        return ApplicationConfiguration.from_payload(payload)

    def save(self, configuration: ApplicationConfiguration) -> None:
        validated = ApplicationConfiguration.from_payload(configuration.to_payload())
        previous_bytes: bytes | None
        try:
            with self.path.open("rb") as file_handle:
                previous_bytes = file_handle.read(CONFIGURATION_SIZE_LIMIT + 1)
        except FileNotFoundError:
            previous_bytes = None
        except OSError as error:
            raise ConfigurationWriteError(
                "The prior Hesiva configuration could not be preserved."
            ) from error
        if previous_bytes is not None and len(previous_bytes) > CONFIGURATION_SIZE_LIMIT:
            raise ConfigurationWriteError("The prior Hesiva configuration is too large.")

        staged_path = self.stage(validated, suffix=".config.json")
        published = False
        try:
            os.replace(staged_path, self.path)
            published = True
            self._set_private_permissions(self.path)
            sync_parent_directory(self.path)
        except Exception as error:
            self._remove_staged_path(staged_path, primary_error=error)
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
            payload_bytes = validated.to_bytes()
            if len(payload_bytes) > CONFIGURATION_SIZE_LIMIT:
                raise ConfigurationWriteError("The Hesiva configuration is too large.")
            if os.name == "posix":
                os.fchmod(file_descriptor, 0o600)
            with os.fdopen(file_descriptor, "wb") as file_handle:
                file_handle.write(payload_bytes)
                file_handle.flush()
                os.fsync(file_handle.fileno())
        except Exception as error:
            try:
                os.close(file_descriptor)
            except OSError as cleanup_error:
                error.add_note(
                    "The configuration staging descriptor could not be closed cleanly: "
                    f"{type(cleanup_error).__name__}."
                )
            self._remove_staged_path(staged_path, primary_error=error)
            if isinstance(error, ConfigurationWriteError):
                raise
            raise ConfigurationWriteError(
                "The Hesiva configuration could not be staged safely."
            ) from error
        return staged_path

    def _restore_previous(self, previous_bytes: bytes | None) -> None:
        if previous_bytes is None:
            self.path.unlink(missing_ok=True)
            sync_parent_directory(self.path)
            return
        previous = self.parse_bytes(previous_bytes)
        rollback_path = self.stage(previous, suffix=".config-rollback.json")
        primary_error: BaseException | None = None
        try:
            os.replace(rollback_path, self.path)
            self._set_private_permissions(self.path)
            sync_parent_directory(self.path)
        except BaseException as error:
            primary_error = error
            raise
        finally:
            self._remove_staged_path(rollback_path, primary_error=primary_error)

    @staticmethod
    def _remove_staged_path(
        staged_path: Path,
        *,
        primary_error: BaseException | None,
    ) -> None:
        """Remove private staging without replacing a more important failure."""
        try:
            staged_path.unlink(missing_ok=True)
        except OSError as cleanup_error:
            if primary_error is not None:
                primary_error.add_note(
                    "A private configuration staging file could not be removed: "
                    f"{type(cleanup_error).__name__}."
                )
                return
            raise ConfigurationWriteError(
                "A private configuration staging file could not be removed safely."
            ) from cleanup_error

    @staticmethod
    def _set_private_permissions(path: Path) -> None:
        if os.name == "posix":
            path.chmod(0o600)


def _reject_nonstandard_json_constant(value: str) -> None:
    raise ValueError(f"Non-standard JSON numeric constant: {value}")


def _parse_finite_json_float(value: str) -> float:
    parsed_value = float(value)
    if not math.isfinite(parsed_value):
        raise ValueError("JSON numeric value is outside the finite range.")
    return parsed_value


def _validate_json_domain(value: object) -> None:
    """Reject values that cannot make a strict, round-trippable JSON document."""
    if value is None or type(value) in {bool, int}:
        return
    if type(value) is str:
        _validate_unicode_text(value)
        return
    if type(value) is float:
        if math.isfinite(value):
            return
        raise InvalidConfigurationError("The Hesiva configuration contains a non-finite number.")
    if isinstance(value, list):
        for item in value:
            _validate_json_domain(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise InvalidConfigurationError("The Hesiva configuration contains a non-text key.")
            _validate_unicode_text(key)
            _validate_json_domain(item)
        return
    raise InvalidConfigurationError("The Hesiva configuration contains an unsupported value.")


def _validate_unicode_text(value: str) -> None:
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise InvalidConfigurationError(
            "The Hesiva configuration contains invalid Unicode text."
        ) from error
