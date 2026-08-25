"""Typed, non-secret application configuration."""

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

EnvironmentVariableName = Annotated[
    str,
    StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$"),
]


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


class EnvironmentSecretReference(_ConfigurationModel):
    """Reference a secret by environment-variable name without storing its value."""

    environment_variable: EnvironmentVariableName


class WebConfiguration(_ConfigurationModel):
    """Local-only Web listener configuration."""

    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)


class TushareConfiguration(_ConfigurationModel):
    """Non-secret Tushare transport settings and one token reference."""

    api_url: AnyHttpUrl | None = None
    timeout_seconds: int = Field(default=30, ge=1, le=120)

    token_ref: EnvironmentSecretReference = Field(
        default_factory=lambda: EnvironmentSecretReference(environment_variable="TUSHARE_TOKEN")
    )

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


class AIConfiguration(_ConfigurationModel):
    """Optional AI secret reference; provider settings arrive in a later task."""

    api_key_ref: EnvironmentSecretReference | None = None

    @model_validator(mode="wrap")
    @classmethod
    def remove_validation_inputs(
        cls,
        value: object,
        handler: ModelWrapValidatorHandler[Self],
    ) -> Self:
        return _validate_without_inputs(value, handler)


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


def load_application_config(path: str | Path) -> ApplicationConfiguration:
    """Load one safe YAML document and validate the complete application schema."""

    with Path(path).open(encoding="utf-8") as stream:
        raw_config = yaml.safe_load(stream)

    return ApplicationConfiguration.model_validate({} if raw_config is None else raw_config)


__all__ = [
    "AIConfiguration",
    "ApplicationConfiguration",
    "EnvironmentSecretReference",
    "TushareConfiguration",
    "WebConfiguration",
    "load_application_config",
]
