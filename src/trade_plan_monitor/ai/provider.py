"""Stable provider contracts for bounded, untrusted AI responses."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Protocol, Self, runtime_checkable
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from trade_plan_monitor.ai.models import AIProviderConfig

ProviderModelName = Annotated[str, StringConstraints(min_length=1, max_length=200)]
FinishReason = Annotated[str, StringConstraints(min_length=1, max_length=64)]
PromptText = Annotated[str, StringConstraints(min_length=1, max_length=200_000)]
RawContent = Annotated[str, StringConstraints(min_length=1, max_length=1_048_576)]


class _ProviderValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class AIProviderOperation(StrEnum):
    """Stable, non-sensitive operation names exposed by provider failures."""

    TEST_CONNECTION = "test_connection"
    EXTRACT_PLAN = "extract_plan"


class AIProviderErrorCode(StrEnum):
    """Closed error categories that never contain provider response text."""

    AUTHENTICATION = "AUTHENTICATION"
    RATE_LIMITED = "RATE_LIMITED"
    TRANSIENT = "TRANSIENT"
    TIMEOUT = "TIMEOUT"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    RESPONSE_TOO_LARGE = "RESPONSE_TOO_LARGE"
    UNSAFE_REDIRECT = "UNSAFE_REDIRECT"
    CONFIGURATION = "CONFIGURATION"
    REJECTED = "REJECTED"


class AIProviderError(RuntimeError):
    """Sanitized provider failure suitable for ordinary application boundaries."""

    def __init__(
        self,
        code: AIProviderErrorCode,
        operation: AIProviderOperation,
        *,
        attempts: int,
    ) -> None:
        if not 0 <= attempts <= 3:
            raise ValueError("attempts must be between 0 and 3")
        self.code = code
        self.operation = operation
        self.attempts = attempts
        super().__init__(f"AI provider {operation.value} failed ({code.value})")


class AIUsage(_ProviderValue):
    """Optional token counts reported by an untrusted provider response."""

    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class PlanExtractionRequest(_ProviderValue):
    """Complete bounded prompt ready for transport by an ``AIProvider``."""

    request_id: UUID
    config: AIProviderConfig
    prompt: PromptText

    @field_validator("prompt")
    @classmethod
    def reject_blank_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("prompt must not be blank")
        return value

    @model_validator(mode="after")
    def enforce_configured_input_limit(self) -> Self:
        if len(self.prompt) > self.config.max_input_chars:
            raise ValueError("prompt exceeds config max_input_chars")
        return self


class ProviderTestResult(_ProviderValue):
    """Successful connection receipt with no response content or credential data."""

    provider_id: UUID
    model: ProviderModelName
    connected: Literal[True]
    attempts: int = Field(ge=1, le=3)


class RawAIResponse(_ProviderValue):
    """Validated transport envelope containing still-untrusted model text."""

    request_id: UUID
    provider_id: UUID
    model: ProviderModelName
    content: RawContent
    finish_reason: FinishReason
    usage: AIUsage | None
    attempts: int = Field(ge=1, le=3)


@runtime_checkable
class AIProvider(Protocol):
    """Internal asynchronous provider boundary used by plan drafting."""

    async def test_connection(self, config: AIProviderConfig) -> ProviderTestResult: ...

    async def extract_plan(self, request: PlanExtractionRequest) -> RawAIResponse: ...


__all__ = [
    "AIProvider",
    "AIProviderError",
    "AIProviderErrorCode",
    "AIProviderOperation",
    "AIUsage",
    "PlanExtractionRequest",
    "ProviderTestResult",
    "RawAIResponse",
]
