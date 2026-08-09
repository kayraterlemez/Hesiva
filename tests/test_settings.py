import json
import tomllib
from collections.abc import Iterator
from importlib.metadata import PackageNotFoundError
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from argon2.low_level import Type

from hesiva.application import create_application_context
from hesiva.composition import ApplicationContext
from hesiva.configuration import (
    ApplicationConfiguration,
    ConfigurationStore,
    InvalidConfigurationError,
)
from hesiva.services import (
    AuthenticationState,
    BackupPathError,
    SettingsService,
    ValidationError,
)
from hesiva.version import get_application_version


@pytest.fixture
def fast_hasher() -> PasswordHasher:
    return PasswordHasher(
        time_cost=1,
        memory_cost=1024,
        parallelism=1,
        hash_len=16,
        salt_len=8,
        type=Type.ID,
    )


@pytest.fixture
def application_context(
    tmp_path: Path,
    fast_hasher: PasswordHasher,
) -> Iterator[ApplicationContext]:
    context = create_application_context(tmp_path / "application-data", password_hasher=fast_hasher)
    context.authentication.create_initial_password("parola", "parola")
    context.authentication.mark_setup_complete()
    try:
        yield context
    finally:
        context.close()


def _configuration_payload(password_hash: str) -> dict[str, object]:
    return {
        "format_version": 1,
        "authentication": {
            "password_hash": password_hash,
            "setup_complete": True,
        },
    }


def test_missing_and_null_backup_configuration_use_established_default(
    tmp_path: Path,
    fast_hasher: PasswordHasher,
) -> None:
    default_directory = tmp_path / "application-data" / "backups"
    store = ConfigurationStore(tmp_path / "config.json")
    payload = _configuration_payload(fast_hasher.hash("parola"))
    store.save(ApplicationConfiguration.from_payload(payload))
    settings = SettingsService(store, default_directory)

    destination, uses_default = settings.resolve_backup_destination_directory()
    assert (destination, uses_default) == (default_directory, True)

    payload["backup"] = {"destination_directory": None}
    store.save(ApplicationConfiguration.from_payload(payload))
    destination, uses_default = settings.resolve_backup_destination_directory()
    assert (destination, uses_default) == (default_directory, True)


def test_absolute_configured_destination_is_preferred_without_creating_files(
    application_context: ApplicationContext,
    tmp_path: Path,
) -> None:
    destination = tmp_path / "external-backups"
    destination.mkdir()

    application_context.settings.update_backup_destination_directory(destination)

    settings = application_context.settings.get_settings()
    assert settings.backup_destination_directory == destination
    assert not settings.uses_default_backup_destination
    assert application_context.prepare_manual_backup_directory() == destination
    assert list(destination.iterdir()) == []
    assert not application_context._backup_service.default_backup_directory.exists()


@pytest.mark.parametrize(
    "backup",
    [
        [],
        "invalid",
        {},
        {"destination_directory": ""},
        {"destination_directory": "   "},
        {"destination_directory": "relative/backups"},
        {"destination_directory": 42},
    ],
)
def test_malformed_backup_configuration_is_rejected(
    backup: object,
    fast_hasher: PasswordHasher,
) -> None:
    payload = _configuration_payload(fast_hasher.hash("parola"))
    payload["backup"] = backup

    with pytest.raises(InvalidConfigurationError, match="backup"):
        ApplicationConfiguration.from_payload(payload)


def test_cross_platform_absolute_path_is_structurally_valid_when_unavailable(
    fast_hasher: PasswordHasher,
) -> None:
    payload = _configuration_payload(fast_hasher.hash("parola"))
    payload["backup"] = {"destination_directory": r"C:\Hesiva\Backups"}

    configuration = ApplicationConfiguration.from_payload(payload)

    assert configuration.backup_destination_directory == r"C:\Hesiva\Backups"


def test_settings_update_rejects_relative_blank_and_missing_directories(
    application_context: ApplicationContext,
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationError, match="mutlak"):
        application_context.settings.update_backup_destination_directory(Path(""))
    with pytest.raises(ValidationError, match="mevcut değil"):
        application_context.settings.update_backup_destination_directory(tmp_path / "missing")


def test_settings_update_preserves_authentication_and_unrelated_fields(
    tmp_path: Path,
    fast_hasher: PasswordHasher,
) -> None:
    store = ConfigurationStore(tmp_path / "config.json")
    password_hash = fast_hasher.hash("parola")
    store.save(
        ApplicationConfiguration.from_payload(
            {
                "format_version": 1,
                "authentication": {
                    "password_hash": password_hash,
                    "setup_complete": True,
                    "future_authentication_value": "preserve",
                },
                "backup": {
                    "destination_directory": None,
                    "future_backup_value": "preserve",
                },
                "future_top_level_value": {"preserve": True},
            }
        )
    )
    destination = tmp_path / "preferred"
    destination.mkdir()
    settings = SettingsService(store, tmp_path / "default")

    settings.update_backup_destination_directory(destination)

    payload = store.load().to_payload()
    assert payload["authentication"]["password_hash"] == password_hash
    assert payload["authentication"]["setup_complete"] is True
    assert payload["authentication"]["future_authentication_value"] == "preserve"
    assert payload["backup"]["destination_directory"] == str(destination)
    assert payload["backup"]["future_backup_value"] == "preserve"
    assert payload["future_top_level_value"] == {"preserve": True}


def test_unavailable_configured_destination_does_not_block_startup_or_fall_back(
    tmp_path: Path,
    fast_hasher: PasswordHasher,
) -> None:
    data_directory = tmp_path / "application-data"
    preferred = tmp_path / "removable-drive"
    preferred.mkdir()
    context = create_application_context(data_directory, password_hasher=fast_hasher)
    context.authentication.create_initial_password("parola", "parola")
    context.authentication.mark_setup_complete()
    context.settings.update_backup_destination_directory(preferred)
    context.close()
    preferred.rmdir()

    reopened = create_application_context(data_directory, password_hasher=fast_hasher)
    try:
        assert reopened.authentication.authentication_state() is AuthenticationState.COMPLETE
        assert reopened.authentication.verify_password("parola")
        assert reopened.prepare_manual_backup_directory() == preferred
        with pytest.raises(BackupPathError, match="does not exist"):
            reopened.create_backup(preferred / "manual.zip")
        assert not reopened._backup_service.default_backup_directory.exists()
    finally:
        reopened.close()


def test_backup_restore_preserves_preference_and_keeps_safety_backup_local(
    tmp_path: Path,
    fast_hasher: PasswordHasher,
) -> None:
    source_directory = tmp_path / "source"
    restored_preference = tmp_path / "source-removable-drive"
    restored_preference.mkdir()
    source = create_application_context(source_directory, password_hasher=fast_hasher)
    source.authentication.create_initial_password("source", "source")
    source.authentication.mark_setup_complete()
    source.settings.update_backup_destination_directory(restored_preference)
    archive = tmp_path / "source.zip"
    source.create_backup(archive)
    source.close()
    restored_preference.rmdir()

    target_directory = tmp_path / "target"
    target = create_application_context(target_directory, password_hasher=fast_hasher)
    target.authentication.create_initial_password("target", "target")
    target.authentication.mark_setup_complete()
    try:
        result = target.restore_backup(archive)

        assert target.settings.get_settings().backup_destination_directory == restored_preference
        assert result.safety_backup_path.parent == target._backup_service.default_backup_directory
        assert result.safety_backup_path.is_file()
    finally:
        target.close()


def test_runtime_version_matches_pyproject_project_metadata() -> None:
    project_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    payload = tomllib.loads(project_path.read_text(encoding="utf-8"))

    assert get_application_version() == payload["project"]["version"]


def test_runtime_version_falls_back_to_source_project_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    payload = tomllib.loads(project_path.read_text(encoding="utf-8"))
    monkeypatch.setattr(
        "hesiva.version.version",
        lambda _name: (_ for _ in ()).throw(PackageNotFoundError()),
    )

    assert get_application_version() == payload["project"]["version"]


def test_new_configuration_serializes_locked_backup_shape(
    tmp_path: Path,
    fast_hasher: PasswordHasher,
) -> None:
    store = ConfigurationStore(tmp_path / "config.json")
    store.save(ApplicationConfiguration.new(fast_hasher.hash("parola"), setup_complete=True))

    payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert payload["backup"] == {"destination_directory": None}
