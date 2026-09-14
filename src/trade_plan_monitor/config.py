"""Typed application configuration for one local personal installation."""

from collections.abc import Mapping
from ipaddress import ip_address
from pathlib import Path
from typing import Literal, Self
from uuid import UUID, uuid5

import yaml
from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    ValidationError,
    field_validator,
    model_validator,
)

from trade_plan_monitor.ai.models import (
    AIProviderConfig,
    AIProviderProfile,
    SecretReference,
)


class _ConfigurationModel(BaseModel):
    """Apply strict boundary validation to every configuration section."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        strict=True,
        str_strip_whitespace=True,
    )

    def model_copy(
        self,
        *,
        update: Mapping[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        """Copy public configuration without bypassing field invariants."""

        if not update:
            return super().model_copy(deep=deep)
        values = self.model_dump(mode="python", round_trip=True)
        values.update(update)
        return type(self).model_validate(values)


class WebConfiguration(_ConfigurationModel):
    """Local-only Web listener configuration."""

    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)


class TushareConfiguration(_ConfigurationModel):
    """Tushare transport settings with one directly configured token."""

    api_url: AnyHttpUrl | None = None
    connect_ip: str | None = Field(default=None, min_length=1, max_length=45)
    timeout_seconds: int = Field(default=30, ge=1, le=120)
    token: str | None = Field(default=None, min_length=1, max_length=8_192)

    @model_validator(mode="wrap")
    @classmethod
    def remove_validation_inputs(
        cls,
        value: object,
        handler: ModelWrapValidatorHandler[Self],
    ) -> Self:
        return _validate_without_inputs(value, handler)

    @field_validator("api_url")
    @classmethod
    def require_safe_api_url(cls, value: AnyHttpUrl | None) -> AnyHttpUrl | None:
        if value is None:
            return None
        if len(str(value)) > 2_048:
            raise ValueError("api_url must not exceed 2048 characters")
        if value.username is not None or value.password is not None:
            raise ValueError("api_url must not contain embedded credentials")
        if value.query is not None or value.fragment is not None:
            raise ValueError("api_url must not contain a query or fragment")
        if value.scheme != "https":
            raise ValueError("api_url must use HTTPS")
        return value

    @field_validator("connect_ip")
    @classmethod
    def require_literal_connect_ip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if "%" in value:
            raise ValueError("connect_ip must be an unscoped IP literal")
        address = None
        try:
            address = ip_address(value)
        except ValueError:
            pass
        if address is None:
            raise ValueError("connect_ip must be an IP literal")
        if address.is_unspecified or address.is_multicast:
            raise ValueError("connect_ip must identify a unicast address")
        return str(address)

    @model_validator(mode="after")
    def require_endpoint_for_connect_ip(self) -> Self:
        if self.connect_ip is not None and self.api_url is None:
            raise ValueError("connect_ip requires an HTTPS api_url for TLS verification")
        return self


class AIModelConfiguration(_ConfigurationModel):
    """One additional model exposed through the configured AI transport."""

    display_name: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[^\x00-\x1f\x7f]+$",
    )
    model: str = Field(
        min_length=1,
        max_length=200,
        pattern=r"^[^\s\x00-\x1f\x7f]+$",
    )


class AIConfiguration(_ConfigurationModel):
    """Configurable AI transport with DeepSeek as the built-in default."""

    profile: AIProviderProfile = Field(default=AIProviderProfile.DEEPSEEK, strict=False)
    display_name: str = Field(
        default="DeepSeek",
        min_length=1,
        max_length=100,
        pattern=r"^[^\x00-\x1f\x7f]+$",
    )
    base_url: AnyHttpUrl = Field(
        default="https://api.deepseek.com",
        validate_default=True,
    )
    model: str = Field(
        default="deepseek-flash",
        min_length=1,
        max_length=200,
        pattern=r"^[^\s\x00-\x1f\x7f]+$",
    )
    api_key: str | None = Field(default=None, min_length=1, max_length=8_192)
    timeout_seconds: int = Field(default=30, ge=1, le=120)
    max_retries: int = Field(default=2, ge=0, le=2)
    max_input_chars: int = Field(default=50_000, ge=1, le=200_000)
    max_output_tokens: int = Field(default=4_096, ge=1, le=16_384)
    temperature: float = Field(default=0, ge=0, le=0.3)
    additional_models: tuple[AIModelConfiguration, ...] = Field(
        default=(),
        max_length=9,
    )

    @model_validator(mode="wrap")
    @classmethod
    def remove_validation_inputs(
        cls,
        value: object,
        handler: ModelWrapValidatorHandler[Self],
    ) -> Self:
        return _validate_without_inputs(value, handler)

    @field_validator("base_url")
    @classmethod
    def require_safe_base_url(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if len(str(value)) > 2_048:
            raise ValueError("base_url must not exceed 2048 characters")
        if value.username is not None or value.password is not None:
            raise ValueError("base_url must not contain embedded credentials")
        if value.query is not None or value.fragment is not None:
            raise ValueError("base_url must not contain a query or fragment")
        if value.scheme == "http" and not _is_explicit_loopback(value.host):
            raise ValueError("base_url must use HTTPS unless the host is loopback")
        return value

    @field_validator("additional_models", mode="before")
    @classmethod
    def normalize_additional_models(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def require_unique_models(self) -> Self:
        models = (self.model, *(model.model for model in self.additional_models))
        if len(set(models)) != len(models):
            raise ValueError("configured AI model identifiers must be unique")
        return self

    def to_provider_config(self) -> AIProviderConfig | None:
        """Build the existing non-secret provider contract when AI is configured."""

        configs = self.to_provider_configs()
        return configs[0] if configs else None

    def to_provider_configs(self) -> tuple[AIProviderConfig, ...]:
        """Build every configured model using one shared, write-only credential."""

        if self.api_key is None:
            return ()
        primary_id = UUID("00000000-0000-4000-8000-0000000000d5")
        identity_namespace = UUID("00000000-0000-4000-8000-0000000000a1")
        secret_ref = SecretReference(key="ai/provider/configured-default")
        models = (
            (primary_id, self.display_name, self.model),
            *(
                (
                    uuid5(identity_namespace, model.model),
                    model.display_name,
                    model.model,
                )
                for model in self.additional_models
            ),
        )
        return tuple(
            AIProviderConfig(
                provider_id=provider_id,
                display_name=display_name,
                base_url=self.base_url,
                model=model,
                secret_ref=secret_ref,
                timeout_seconds=self.timeout_seconds,
                max_retries=self.max_retries,
                max_input_chars=self.max_input_chars,
                max_output_tokens=self.max_output_tokens,
                temperature=self.temperature,
            )
            for provider_id, display_name, model in models
        )


class ApplicationConfiguration(_ConfigurationModel):
    """Top-level configuration accepted by the local application."""

    web: WebConfiguration = Field(default_factory=WebConfiguration)
    tushare: TushareConfiguration = Field(default_factory=TushareConfiguration)
    ai: AIConfiguration = Field(default_factory=AIConfiguration)

    @model_validator(mode="wrap")
    @classmethod
    def remove_validation_inputs(
        cls,
        value: object,
        handler: ModelWrapValidatorHandler[Self],
    ) -> Self:
        return _validate_without_inputs(value, handler)


def _validate_without_inputs[Model](
    value: object,
    handler: ModelWrapValidatorHandler[Model],
) -> Model:
    safe_error: ValidationError | None = None
    try:
        return handler(value)
    except ValidationError as error:
        safe_error = _validation_error_without_inputs(error)
    if safe_error is not None:
        raise safe_error
    raise AssertionError("validation boundary completed without a result")


def _validation_error_without_inputs(error: ValidationError) -> ValidationError:
    line_errors = error.errors(include_url=False)
    for line_error in line_errors:
        line_error.pop("input", None)
    return ValidationError.from_exception_data(
        error.title,
        line_errors,
        hide_input=True,
    )


def _is_explicit_loopback(host: str) -> bool:
    normalized = host.casefold().strip("[]")
    if normalized == "localhost":
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False


def load_application_config(path: str | Path) -> ApplicationConfiguration:
    """Load one safe YAML document and validate the complete application schema."""

    with Path(path).open(encoding="utf-8") as stream:
        raw_config = yaml.safe_load(stream)

    return ApplicationConfiguration.model_validate({} if raw_config is None else raw_config)


__all__ = [
    "AIConfiguration",
    "AIModelConfiguration",
    "ApplicationConfiguration",
    "TushareConfiguration",
    "WebConfiguration",
    "load_application_config",
]
