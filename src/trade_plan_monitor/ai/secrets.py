"""Write-only public secret management with masked status responses.

Pydantic masks ``SecretStr`` during JSON serialization:
https://docs.pydantic.dev/latest/api/types/#pydantic.types.SecretStr
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import StrEnum
from typing import Literal, Protocol, Self, runtime_checkable

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

from trade_plan_monitor.ai.models import (
    SecretReference,
    _validation_error_without_inputs,
)


class _SecretValue(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        strict=True,
    )


class SecretSource(StrEnum):
    """Non-sensitive source of a configured-secret status."""

    NONE = "NONE"
    STORE = "STORE"
    ENVIRONMENT = "ENVIRONMENT"


class SecretWrite(_SecretValue):
    """Transient replacement input whose representations remain masked."""

    value: SecretStr = Field(min_length=1, max_length=8_192)

    @model_validator(mode="wrap")
    @classmethod
    def remove_validation_inputs(
        cls,
        value: object,
        handler: ModelWrapValidatorHandler[Self],
    ) -> Self:
        safe_error: ValidationError | None = None
        try:
            return handler(value)
        except ValidationError as error:
            safe_error = _validation_error_without_inputs(error)
        if safe_error is not None:
            raise safe_error
        raise AssertionError("validation boundary completed without a result")

    @field_validator("value")
    @classmethod
    def reject_blank_secret(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("secret value must not be blank")
        return value


class SecretStatus(_SecretValue):
    """Public receipt containing configuration metadata but no secret value."""

    configured: bool
    source: SecretSource
    masked_value: Literal["********"] | None
    generation: int = Field(ge=0)

    @model_validator(mode="after")
    def require_consistent_masked_state(self) -> Self:
        if self.configured != (self.source is not SecretSource.NONE):
            raise ValueError("configured and source must describe the same state")
        expected_mask = "********" if self.configured else None
        if self.masked_value != expected_mask:
            raise ValueError("masked_value must reflect configured state")
        if self.source is SecretSource.STORE and self.generation < 1:
            raise ValueError("stored secrets must have a positive generation")
        if self.source is not SecretSource.STORE and self.generation != 0:
            raise ValueError("only stored secrets have a positive generation")
        return self


@runtime_checkable
class SecretStore(Protocol):
    """Public management capability: replace a secret or inspect masked status."""

    def replace(self, reference: SecretReference, secret: SecretWrite) -> SecretStatus: ...

    def status(self, reference: SecretReference) -> SecretStatus: ...


class InMemorySecretStore:
    """Process-local implementation used until an OS credential adapter is selected."""

    def __init__(self, *, environment: Mapping[str, str] | None = None) -> None:
        self._environment = os.environ if environment is None else environment
        self._values: dict[str, SecretStr] = {}
        self._generations: dict[str, int] = {}

    def replace(self, reference: SecretReference, secret: SecretWrite) -> SecretStatus:
        self._values[reference.key] = secret.value
        generation = self._generations.get(reference.key, 0) + 1
        self._generations[reference.key] = generation
        return _configured_status(SecretSource.STORE, generation=generation)

    def status(self, reference: SecretReference) -> SecretStatus:
        if reference.key in self._values:
            return _configured_status(
                SecretSource.STORE,
                generation=self._generations[reference.key],
            )
        if self._environment_value(reference) is not None:
            return _configured_status(SecretSource.ENVIRONMENT)
        return SecretStatus(
            configured=False,
            source=SecretSource.NONE,
            masked_value=None,
            generation=0,
        )

    def _materialize(self, reference: SecretReference) -> SecretStr:
        """Resolve material for runtime composition without widening `SecretStore`."""

        stored_value = self._values.get(reference.key)
        if stored_value is not None:
            return stored_value
        environment_value = self._environment_value(reference)
        if environment_value is not None:
            return environment_value
        raise RuntimeError("AI secret is not configured")

    def _environment_value(self, reference: SecretReference) -> SecretStr | None:
        environment_name = reference.environment_variable
        if environment_name is None:
            return None
        value = self._environment.get(environment_name)
        if not isinstance(value, str) or not value.strip():
            return None
        return SecretStr(value)


def _configured_status(source: SecretSource, *, generation: int = 0) -> SecretStatus:
    return SecretStatus(
        configured=True,
        source=source,
        masked_value="********",
        generation=generation,
    )


__all__ = [
    "InMemorySecretStore",
    "SecretSource",
    "SecretStatus",
    "SecretStore",
    "SecretWrite",
]
