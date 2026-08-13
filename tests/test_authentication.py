import json
import os
from pathlib import Path

import pytest
from argon2 import PasswordHasher, extract_parameters
from argon2.low_level import Type

from hesiva import configuration as configuration_module
from hesiva.configuration import (
    CONFIG_FORMAT_VERSION,
    ApplicationConfiguration,
    ConfigurationNotFoundError,
    ConfigurationStore,
    ConfigurationWriteError,
    InvalidConfigurationError,
)
from hesiva.services import (
    AuthenticationFailedError,
    AuthenticationService,
    AuthenticationState,
    CredentialPersistenceError,
    InvalidCredentialStateError,
    PasswordAlreadyConfiguredError,
    PasswordMismatchError,
    ValidationError,
    create_production_password_hasher,
)


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
def authentication(tmp_path: Path, fast_hasher: PasswordHasher) -> AuthenticationService:
    return AuthenticationService(ConfigurationStore(tmp_path / "config.json"), fast_hasher)


def test_production_hasher_uses_locked_argon2id_parameters() -> None:
    hasher = create_production_password_hasher()

    assert hasher.type is Type.ID
    assert hasher.time_cost == 3
    assert hasher.memory_cost == 65_536
    assert hasher.parallelism == 4
    assert hasher.hash_len == 32
    assert hasher.salt_len == 16


def test_absent_configuration_is_distinct_from_invalid_configuration(
    tmp_path: Path,
    fast_hasher: PasswordHasher,
) -> None:
    store = ConfigurationStore(tmp_path / "config.json")
    authentication = AuthenticationService(store, fast_hasher)

    with pytest.raises(ConfigurationNotFoundError):
        store.load()
    assert authentication.authentication_state() is AuthenticationState.ABSENT
    assert not authentication.has_password()

    store.path.write_text("{not-json", encoding="utf-8")
    assert authentication.authentication_state() is AuthenticationState.INVALID
    with pytest.raises(InvalidCredentialStateError):
        authentication.has_password()


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"format_version": True, "authentication": {}},
        {"format_version": 2, "authentication": {}},
        {"format_version": 1},
        {"format_version": 1, "authentication": []},
        {
            "format_version": 1,
            "authentication": {"password_hash": "", "setup_complete": False},
        },
        {
            "format_version": 1,
            "authentication": {"password_hash": "not-argon", "setup_complete": False},
        },
        {
            "format_version": 1,
            "authentication": {
                "password_hash": "$argon2i$v=19$m=8,t=1,p=1$bad$bad",
                "setup_complete": False,
            },
        },
        {
            "format_version": 1,
            "authentication": {"password_hash": "ignored", "setup_complete": 1},
        },
    ],
)
def test_configuration_validation_rejects_malformed_v1_contract(payload: object) -> None:
    with pytest.raises(InvalidConfigurationError):
        ApplicationConfiguration.from_payload(payload)


def test_configuration_rejects_a_valid_non_argon2id_hash() -> None:
    argon2i = PasswordHasher(
        time_cost=1,
        memory_cost=1024,
        parallelism=1,
        hash_len=16,
        salt_len=8,
        type=Type.I,
    )

    with pytest.raises(InvalidConfigurationError):
        ApplicationConfiguration.from_payload(
            {
                "format_version": 1,
                "authentication": {
                    "password_hash": argon2i.hash("synthetic"),
                    "setup_complete": True,
                },
            }
        )


def test_configuration_rejects_argon2id_parameters_above_locked_policy(
    fast_hasher: PasswordHasher,
) -> None:
    baseline_hash = fast_hasher.hash("synthetic")

    def with_costs(*, memory_cost: int, time_cost: int, parallelism: int) -> str:
        fields = baseline_hash.split("$")
        fields[3] = f"m={memory_cost},t={time_cost},p={parallelism}"
        return "$".join(fields)

    hostile_hashes = (
        with_costs(memory_cost=65_537, time_cost=1, parallelism=1),
        with_costs(memory_cost=1024, time_cost=4, parallelism=1),
        with_costs(memory_cost=1024, time_cost=1, parallelism=5),
        PasswordHasher(
            time_cost=1,
            memory_cost=1024,
            parallelism=1,
            hash_len=33,
            salt_len=8,
            type=Type.ID,
        ).hash("synthetic"),
        PasswordHasher(
            time_cost=1,
            memory_cost=1024,
            parallelism=1,
            hash_len=16,
            salt_len=17,
            type=Type.ID,
        ).hash("synthetic"),
    )

    for password_hash in hostile_hashes:
        with pytest.raises(InvalidConfigurationError):
            ApplicationConfiguration.from_payload(
                {
                    "format_version": 1,
                    "authentication": {
                        "password_hash": password_hash,
                        "setup_complete": True,
                    },
                }
            )


def test_configuration_rejects_oversized_hash_before_argon_parsing(
    fast_hasher: PasswordHasher,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    password_hash = fast_hasher.hash("synthetic") + "x" * 1024

    def unexpected_extract(_password_hash: str) -> object:
        raise AssertionError("Oversized hashes must be rejected before Argon parsing.")

    monkeypatch.setattr(configuration_module, "extract_parameters", unexpected_extract)

    with pytest.raises(InvalidConfigurationError, match="password hash"):
        ApplicationConfiguration.from_payload(
            {
                "format_version": 1,
                "authentication": {
                    "password_hash": password_hash,
                    "setup_complete": True,
                },
            }
        )


def test_configuration_size_is_bounded_before_json_parsing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ConfigurationStore(tmp_path / "config.json")
    store.path.write_bytes(b" " * 65)
    monkeypatch.setattr(configuration_module, "CONFIGURATION_SIZE_LIMIT", 64)

    def unexpected_json_loads(_payload: str) -> object:
        raise AssertionError("Oversized configuration must be rejected before JSON parsing.")

    monkeypatch.setattr(configuration_module.json, "loads", unexpected_json_loads)

    with pytest.raises(InvalidConfigurationError, match="too large"):
        store.load()
    with pytest.raises(InvalidConfigurationError, match="too large"):
        store.parse_bytes(b" " * 65)


def test_deeply_nested_configuration_is_rejected_as_invalid() -> None:
    nested_json = "[" * 10_000 + "null" + "]" * 10_000

    with pytest.raises(InvalidConfigurationError, match="malformed"):
        ConfigurationStore.parse_bytes(nested_json.encode("utf-8"))


def test_configuration_rejects_huge_json_integer_as_malformed(
    fast_hasher: PasswordHasher,
) -> None:
    password_hash = json.dumps(fast_hasher.hash("synthetic"))
    payload = (
        '{"format_version":1,"authentication":{"password_hash":'
        + password_hash
        + ',"setup_complete":true},"future":'
        + "9" * 4301
        + "}"
    )

    with pytest.raises(InvalidConfigurationError, match="malformed"):
        ConfigurationStore.parse_bytes(payload.encode("utf-8"))


@pytest.mark.parametrize("constant", ("NaN", "Infinity", "-Infinity", "1e9999", "-1e9999"))
def test_configuration_rejects_nonfinite_json_numbers(
    constant: str,
    fast_hasher: PasswordHasher,
) -> None:
    password_hash = json.dumps(fast_hasher.hash("synthetic"))
    payload = (
        '{"format_version":1,"authentication":{"password_hash":'
        + password_hash
        + ',"setup_complete":true},"future":'
        + constant
        + "}"
    )

    with pytest.raises(InvalidConfigurationError, match="malformed"):
        ConfigurationStore.parse_bytes(payload.encode("utf-8"))


@pytest.mark.parametrize("nonfinite_value", (float("nan"), float("inf"), -float("inf")))
def test_configuration_rejects_programmatic_nonfinite_unknown_values(
    nonfinite_value: float,
    fast_hasher: PasswordHasher,
) -> None:
    with pytest.raises(InvalidConfigurationError, match="non-finite"):
        ApplicationConfiguration.from_payload(
            {
                "format_version": 1,
                "authentication": {
                    "password_hash": fast_hasher.hash("synthetic"),
                    "setup_complete": True,
                },
                "future": {"nested": [nonfinite_value]},
            }
        )


@pytest.mark.parametrize(
    "unknown_field",
    ('"future":"\\ud800"', '"\\ud800":"future"'),
    ids=("unknown-value", "unknown-key"),
)
def test_configuration_parse_and_load_reject_lone_unicode_surrogates(
    unknown_field: str,
    fast_hasher: PasswordHasher,
    tmp_path: Path,
) -> None:
    password_hash = json.dumps(fast_hasher.hash("synthetic"))
    payload_bytes = (
        '{"format_version":1,"authentication":{"password_hash":'
        + password_hash
        + ',"setup_complete":true},'
        + unknown_field
        + "}"
    ).encode("utf-8")

    with pytest.raises(InvalidConfigurationError, match="invalid Unicode"):
        ConfigurationStore.parse_bytes(payload_bytes)

    store = ConfigurationStore(tmp_path / "config.json")
    store.path.write_bytes(payload_bytes)
    with pytest.raises(InvalidConfigurationError, match="invalid Unicode"):
        store.load()


def test_configuration_store_rejects_oversized_serialization_without_staging(
    tmp_path: Path,
    fast_hasher: PasswordHasher,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ConfigurationStore(tmp_path / "config.json")
    configuration = ApplicationConfiguration.from_payload(
        {
            "format_version": 1,
            "authentication": {
                "password_hash": fast_hasher.hash("synthetic"),
                "setup_complete": True,
            },
            "future": "preserve me",
        }
    )
    monkeypatch.setattr(configuration_module, "CONFIGURATION_SIZE_LIMIT", 1)

    with pytest.raises(ConfigurationWriteError, match="too large"):
        store.save(configuration)

    assert not store.path.exists()
    assert not list(tmp_path.glob(".hesiva-*"))


def test_initial_password_persists_exact_schema_without_plaintext_and_verifies(
    tmp_path: Path,
    fast_hasher: PasswordHasher,
) -> None:
    store = ConfigurationStore(tmp_path / "config.json")
    authentication = AuthenticationService(store, fast_hasher)

    authentication.create_initial_password("güvenli parola", "güvenli parola")

    payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert set(payload) == {"format_version", "authentication", "backup"}
    assert payload["format_version"] == CONFIG_FORMAT_VERSION
    assert set(payload["authentication"]) == {"password_hash", "setup_complete"}
    assert payload["authentication"]["setup_complete"] is False
    assert payload["authentication"]["password_hash"].startswith("$argon2id$")
    assert payload["backup"] == {"destination_directory": None}
    assert "güvenli parola" not in store.path.read_text(encoding="utf-8")
    assert authentication.authentication_state() is AuthenticationState.INCOMPLETE
    assert authentication.has_password()
    assert authentication.verify_password("güvenli parola")
    assert not authentication.verify_password("yanlış")


def test_password_policy_rejects_only_empty_and_mismatch_and_preserves_whitespace(
    authentication: AuthenticationService,
) -> None:
    with pytest.raises(ValidationError):
        authentication.create_initial_password("", "")
    with pytest.raises(PasswordMismatchError):
        authentication.create_initial_password("x", "y")

    authentication.create_initial_password("   ", "   ")
    assert authentication.verify_password("   ")
    assert not authentication.verify_password("")


def test_unicode_password_and_random_salts_work(
    fast_hasher: PasswordHasher, tmp_path: Path
) -> None:
    first_store = ConfigurationStore(tmp_path / "first.json")
    second_store = ConfigurationStore(tmp_path / "second.json")
    first = AuthenticationService(first_store, fast_hasher)
    second = AuthenticationService(second_store, fast_hasher)

    first.create_initial_password("İnek-Şifre-🐄", "İnek-Şifre-🐄")
    second.create_initial_password("İnek-Şifre-🐄", "İnek-Şifre-🐄")

    assert first.verify_password("İnek-Şifre-🐄")
    assert first_store.load().password_hash != second_store.load().password_hash
    assert extract_parameters(first_store.load().password_hash).type is Type.ID


def test_initial_creation_never_overwrites_existing_credential(
    authentication: AuthenticationService,
) -> None:
    authentication.create_initial_password("ilk", "ilk")

    with pytest.raises(PasswordAlreadyConfiguredError):
        authentication.create_initial_password("ikinci", "ikinci")

    assert authentication.verify_password("ilk")
    assert not authentication.verify_password("ikinci")


def test_setup_completion_is_atomic_and_idempotent(authentication: AuthenticationService) -> None:
    authentication.create_initial_password("parola", "parola")

    authentication.mark_setup_complete()
    authentication.mark_setup_complete()

    assert authentication.authentication_state() is AuthenticationState.COMPLETE
    assert authentication.verify_password("parola")


def test_password_change_preserves_setup_and_unknown_fields(
    tmp_path: Path,
    fast_hasher: PasswordHasher,
) -> None:
    store = ConfigurationStore(tmp_path / "config.json")
    old_hash = fast_hasher.hash("eski")
    store.save(
        ApplicationConfiguration.from_payload(
            {
                "format_version": 1,
                "authentication": {
                    "password_hash": old_hash,
                    "setup_complete": True,
                    "future_auth_value": "koru",
                },
                "backup": {
                    "destination_directory": "/synthetic/path",
                    "future_backup_value": "koru",
                },
            }
        )
    )
    authentication = AuthenticationService(store, fast_hasher)

    authentication.change_password("eski", "yeni", "yeni")

    payload = store.load().to_payload()
    assert payload["authentication"]["setup_complete"] is True
    assert payload["authentication"]["future_auth_value"] == "koru"
    assert payload["backup"]["destination_directory"] == "/synthetic/path"
    assert payload["backup"]["future_backup_value"] == "koru"
    assert not authentication.verify_password("eski")
    assert authentication.verify_password("yeni")


def test_failed_password_change_leaves_old_credential_valid(
    authentication: AuthenticationService,
) -> None:
    authentication.create_initial_password("eski", "eski")

    with pytest.raises(AuthenticationFailedError):
        authentication.change_password("yanlış", "yeni", "yeni")
    with pytest.raises(PasswordMismatchError):
        authentication.change_password("eski", "yeni", "başka")
    with pytest.raises(ValidationError):
        authentication.change_password("eski", "", "")

    assert authentication.verify_password("eski")


def test_replace_failure_during_change_preserves_old_hash(
    tmp_path: Path,
    fast_hasher: PasswordHasher,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ConfigurationStore(tmp_path / "config.json")
    authentication = AuthenticationService(store, fast_hasher)
    authentication.create_initial_password("eski", "eski")
    old_bytes = store.path.read_bytes()

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("synthetic replace failure")

    monkeypatch.setattr("hesiva.configuration.os.replace", fail_replace)
    with pytest.raises(CredentialPersistenceError):
        authentication.change_password("eski", "yeni", "yeni")

    assert store.path.read_bytes() == old_bytes
    assert authentication.verify_password("eski")
    assert not authentication.verify_password("yeni")


def test_parent_sync_failure_during_change_rolls_back_old_credential(
    tmp_path: Path,
    fast_hasher: PasswordHasher,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ConfigurationStore(tmp_path / "config.json")
    authentication = AuthenticationService(store, fast_hasher)
    authentication.create_initial_password("eski", "eski")
    old_bytes = store.path.read_bytes()
    sync_calls = 0

    def fail_first_sync(_path: Path) -> None:
        nonlocal sync_calls
        sync_calls += 1
        if sync_calls == 1:
            raise OSError("synthetic directory sync failure")

    monkeypatch.setattr("hesiva.configuration.sync_parent_directory", fail_first_sync)

    with pytest.raises(CredentialPersistenceError):
        authentication.change_password("eski", "yeni", "yeni")

    assert sync_calls == 2
    assert store.path.read_bytes() == old_bytes
    assert authentication.verify_password("eski")
    assert not authentication.verify_password("yeni")


def test_initial_write_failure_leaves_config_absent(
    tmp_path: Path,
    fast_hasher: PasswordHasher,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ConfigurationStore(tmp_path / "config.json")
    authentication = AuthenticationService(store, fast_hasher)
    monkeypatch.setattr(
        "hesiva.configuration.os.replace",
        lambda *_args: (_ for _ in ()).throw(OSError("synthetic failure")),
    )

    with pytest.raises(CredentialPersistenceError):
        authentication.create_initial_password("parola", "parola")

    assert not store.path.exists()
    assert authentication.authentication_state() is AuthenticationState.ABSENT


def test_config_write_syncs_file_and_parent_and_uses_private_permissions(
    tmp_path: Path,
    fast_hasher: PasswordHasher,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ConfigurationStore(tmp_path / "config.json")
    parent_syncs: list[Path] = []
    monkeypatch.setattr(
        "hesiva.configuration.sync_parent_directory",
        parent_syncs.append,
    )

    store.save(ApplicationConfiguration.new(fast_hasher.hash("x"), setup_complete=False))

    assert parent_syncs == [store.path]
    assert not list(tmp_path.glob(".hesiva-*"))
    if os.name == "posix":
        assert store.path.stat().st_mode & 0o777 == 0o600


def test_malformed_existing_hash_fails_verification_and_change_safely(
    tmp_path: Path,
    fast_hasher: PasswordHasher,
) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "authentication": {
                    "password_hash": "malformed",
                    "setup_complete": True,
                },
            }
        ),
        encoding="utf-8",
    )
    authentication = AuthenticationService(ConfigurationStore(path), fast_hasher)

    with pytest.raises(InvalidCredentialStateError):
        authentication.verify_password("anything")
    with pytest.raises(InvalidCredentialStateError):
        authentication.change_password("anything", "new", "new")


def test_configuration_store_reports_direct_write_error_without_partial_file(
    tmp_path: Path,
    fast_hasher: PasswordHasher,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ConfigurationStore(tmp_path / "config.json")
    monkeypatch.setattr(
        "hesiva.configuration.os.replace",
        lambda *_args: (_ for _ in ()).throw(OSError("synthetic failure")),
    )

    with pytest.raises(ConfigurationWriteError):
        store.save(ApplicationConfiguration.new(fast_hasher.hash("x"), setup_complete=False))
    assert not store.path.exists()


def test_configuration_cleanup_failure_does_not_mask_publication_error(
    tmp_path: Path,
    fast_hasher: PasswordHasher,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ConfigurationStore(tmp_path / "config.json")
    real_unlink = Path.unlink

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("primary publication failure")

    def fail_staged_unlink(path: Path, *, missing_ok: bool = False) -> None:
        if path.name.startswith(".hesiva-"):
            raise PermissionError("synthetic sharing violation")
        real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(configuration_module.os, "replace", fail_replace)
    monkeypatch.setattr(Path, "unlink", fail_staged_unlink)

    with pytest.raises(ConfigurationWriteError) as caught:
        store.save(ApplicationConfiguration.new(fast_hasher.hash("x"), setup_complete=False))

    assert isinstance(caught.value.__cause__, OSError)
    assert str(caught.value.__cause__) == "primary publication failure"
    assert any(
        "configuration staging file could not be removed" in note
        for note in caught.value.__cause__.__notes__
    )
    assert not store.path.exists()
