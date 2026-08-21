from uuid import UUID

import pytest
from pydantic import ValidationError

from trade_plan_monitor.ai.models import (
    AIProviderConfig,
    AIProviderType,
    SecretReference,
)
from trade_plan_monitor.ai.secrets import (
    InMemorySecretStore,
    SecretSource,
    SecretStatus,
    SecretStore,
    SecretWrite,
)
from trade_plan_monitor.state.models import AIProviderConfiguration

_PROVIDER_ID = UUID("8db1318f-7182-4c43-9f1f-e260d46f3f0d")


def _config_values() -> dict[str, object]:
    return {
        "provider_id": _PROVIDER_ID,
        "display_name": "Local OpenAI-compatible service",
        "provider_type": AIProviderType.OPENAI_COMPATIBLE,
        "base_url": "https://ai.example.com/v1",
        "model": "example-chat-model",
        "secret_ref": SecretReference(
            key="ai/provider/8db1318f-7182-4c43-9f1f-e260d46f3f0d",
            environment_variable="MONITOR_AI_API_KEY",
        ),
    }


def test_ai_config_uses_bounded_non_secret_defaults() -> None:
    config = AIProviderConfig(**_config_values())

    assert config.timeout_seconds == 30
    assert config.max_retries == 2
    assert config.max_input_chars == 50_000
    assert config.max_output_tokens == 4_096
    assert config.temperature == 0
    assert config.prompt_version == "plan-extract-v1"
    assert config.allow_redirects is False
    assert config.enabled is True
    serialized = config.model_dump_json()
    assert "MONITOR_AI_API_KEY" in serialized
    assert "api-key-value" not in serialized


@pytest.mark.parametrize(
    "base_url",
    [
        "https://ai.example.com/v1",
        "http://localhost:11434/v1",
        "http://127.0.0.2:8000/v1",
        "http://[::1]:8000/v1",
    ],
)
def test_ai_config_accepts_https_or_explicit_loopback_url(base_url: str) -> None:
    config = AIProviderConfig(**(_config_values() | {"base_url": base_url}))

    assert str(config.base_url) == base_url


@pytest.mark.parametrize(
    "base_url",
    [
        "http://ai.example.com/v1",
        "http://0.0.0.0:8000/v1",
        "ftp://ai.example.com/v1",
        "https://user:password@ai.example.com/v1",
        "https://ai.example.com/v1?redirect=http://127.0.0.1",
        "https://ai.example.com/v1#fragment",
    ],
)
def test_ai_config_rejects_unsafe_url(base_url: str) -> None:
    with pytest.raises(ValidationError):
        AIProviderConfig(**(_config_values() | {"base_url": base_url}))


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("timeout_seconds", 0),
        ("timeout_seconds", 121),
        ("max_retries", -1),
        ("max_retries", 3),
        ("max_input_chars", 0),
        ("max_input_chars", 200_001),
        ("max_output_tokens", 0),
        ("max_output_tokens", 16_385),
        ("temperature", -0.01),
        ("temperature", 0.31),
        ("allow_redirects", True),
    ],
)
def test_ai_config_rejects_values_outside_resource_bounds(
    field_name: str,
    invalid_value: object,
) -> None:
    with pytest.raises(ValidationError):
        AIProviderConfig(**(_config_values() | {field_name: invalid_value}))


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("display_name", ""),
        ("display_name", "unsafe\nname"),
        ("display_name", "x" * 101),
        ("provider_type", "UNKNOWN"),
        ("model", ""),
        ("model", "x" * 201),
        ("prompt_version", "unsafe prompt version"),
    ],
)
def test_ai_config_rejects_invalid_provider_and_model_fields(
    field_name: str,
    invalid_value: object,
) -> None:
    with pytest.raises(ValidationError):
        AIProviderConfig(**(_config_values() | {field_name: invalid_value}))


def test_secret_store_public_contract_is_write_and_status_only() -> None:
    public_members = {name for name in vars(SecretStore) if not name.startswith("_")}

    assert public_members == {"replace", "status"}


def test_secret_write_and_replacement_return_masked_status_only() -> None:
    reference = SecretReference(
        key="ai/provider/replacement-test",
        environment_variable="MONITOR_AI_API_KEY",
    )
    store = InMemorySecretStore(environment={})

    first = store.replace(reference, SecretWrite(value="first-api-key"))
    second = store.replace(reference, SecretWrite(value="second-api-key"))

    assert first.configured is True
    assert first.source is SecretSource.STORE
    assert first.generation == 1
    assert second.generation == 2
    assert second.masked_value == "********"
    combined_output = f"{first!r}{second!r}{first.model_dump_json()}{second.model_dump_json()}"
    assert "first-api-key" not in combined_output
    assert "second-api-key" not in combined_output


def test_secret_status_uses_environment_reference_as_fallback() -> None:
    reference = SecretReference(
        key="ai/provider/environment-test",
        environment_variable="MONITOR_AI_API_KEY",
    )
    store = InMemorySecretStore(environment={"MONITOR_AI_API_KEY": "environment-key"})

    status = store.status(reference)

    assert status.configured is True
    assert status.source is SecretSource.ENVIRONMENT
    assert status.generation == 0
    assert status.masked_value == "********"
    assert "environment-key" not in repr(status)
    assert "environment-key" not in status.model_dump_json()


def test_secret_status_ignores_blank_environment_fallback() -> None:
    reference = SecretReference(
        key="ai/provider/blank-environment-test",
        environment_variable="MONITOR_AI_API_KEY",
    )

    status = InMemorySecretStore(environment={"MONITOR_AI_API_KEY": "   "}).status(reference)

    assert status.configured is False
    assert status.source is SecretSource.NONE


def test_secret_runtime_materialization_prefers_replacement_then_environment() -> None:
    reference = SecretReference(
        key="ai/provider/runtime-test",
        environment_variable="MONITOR_AI_API_KEY",
    )
    store = InMemorySecretStore(environment={"MONITOR_AI_API_KEY": "environment-key"})

    environment_value = store._materialize(reference)
    store.replace(reference, SecretWrite(value="replacement-key"))
    replacement_value = store._materialize(reference)

    assert environment_value.get_secret_value() == "environment-key"
    assert replacement_value.get_secret_value() == "replacement-key"


def test_stored_secret_takes_precedence_over_environment_fallback() -> None:
    reference = SecretReference(
        key="ai/provider/precedence-test",
        environment_variable="MONITOR_AI_API_KEY",
    )
    store = InMemorySecretStore(environment={"MONITOR_AI_API_KEY": "environment-key"})

    store.replace(reference, SecretWrite(value="stored-key"))
    status = store.status(reference)

    assert status.source is SecretSource.STORE
    assert status.generation == 1
    assert "stored-key" not in status.model_dump_json()


def test_missing_secret_has_unconfigured_masked_state() -> None:
    reference = SecretReference(key="ai/provider/missing-test")

    status = InMemorySecretStore(environment={}).status(reference)

    assert status.configured is False
    assert status.source is SecretSource.NONE
    assert status.masked_value is None
    assert status.generation == 0


@pytest.mark.parametrize("value", ["", "x" * 8_193])
def test_secret_write_rejects_empty_or_oversized_values(value: str) -> None:
    with pytest.raises(ValidationError):
        SecretWrite(value=value)


def test_ai_config_rejects_url_longer_than_persistence_bound() -> None:
    oversized_url = "https://ai.example.com/" + ("x" * 2_100)

    with pytest.raises(ValidationError):
        AIProviderConfig(**(_config_values() | {"base_url": oversized_url}))


def test_secret_write_rejects_whitespace_only_value() -> None:
    with pytest.raises(ValidationError):
        SecretWrite(value="   ")


def test_secret_status_rejects_stored_source_without_positive_generation() -> None:
    with pytest.raises(ValidationError):
        SecretStatus(
            configured=True,
            source=SecretSource.STORE,
            masked_value="********",
            generation=0,
        )


def test_ai_config_persistence_contains_references_but_no_secret_value_column() -> None:
    column_names = set(AIProviderConfiguration.__table__.columns.keys())

    assert column_names == {
        "id",
        "display_name",
        "provider_type",
        "base_url",
        "model_name",
        "key_ref",
        "environment_variable",
        "timeout_seconds",
        "max_retries",
        "max_input_chars",
        "max_output_tokens",
        "temperature_milli",
        "prompt_version",
        "enabled",
        "revision",
        "created_at",
        "updated_at",
    }
    assert (
        not {
            "api_key",
            "authorization",
            "credential",
            "password",
            "secret_value",
            "token",
        }
        & column_names
    )
