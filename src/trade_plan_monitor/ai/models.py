"""Strict AI configuration, extraction, provenance, and result models.

Validation follows Pydantic URL/validator APIs and Python loopback semantics:
https://docs.pydantic.dev/latest/api/networks/
https://docs.pydantic.dev/latest/concepts/validators/
https://docs.pydantic.dev/latest/concepts/models/
https://docs.python.org/3/library/ipaddress.html#ipaddress.IPv4Address.is_loopback
"""

from __future__ import annotations

from enum import StrEnum
from ipaddress import ip_address
from typing import Annotated, Literal, Self
from uuid import UUID

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

from trade_plan_monitor.domain.plan_models import TradePlan
from trade_plan_monitor.domain.plan_validation import ValidationIssue

DisplayName = Annotated[
    str,
    StringConstraints(min_length=1, max_length=100, pattern=r"^[^\x00-\x1f\x7f]+$"),
]
ModelName = Annotated[
    str,
    StringConstraints(min_length=1, max_length=200, pattern=r"^[^\s\x00-\x1f\x7f]+$"),
]
PromptVersion = Annotated[
    str,
    StringConstraints(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$"),
]
SecretKeyReference = Annotated[
    str,
    StringConstraints(
        min_length=13,
        max_length=140,
        pattern=r"^ai/provider/[A-Za-z0-9_-]{1,128}$",
    ),
]
EnvironmentVariableName = Annotated[
    str,
    StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$"),
]
ExtractionPath = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_.\[\]-]+$",
    ),
]
EvidenceExcerpt = Annotated[str, StringConstraints(min_length=1, max_length=512)]
ExtractionMessage = Annotated[str, StringConstraints(min_length=1, max_length=512)]
SourceTextSha256 = Annotated[
    str,
    StringConstraints(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"),
]


class _AIValue(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        strict=True,
        str_strip_whitespace=True,
    )


class AIProviderType(StrEnum):
    """Provider contracts supported by the first release."""

    OPENAI_COMPATIBLE = "OPENAI_COMPATIBLE"


class SecretReference(_AIValue):
    """Non-secret store key with an optional environment fallback name."""

    key: SecretKeyReference
    environment_variable: EnvironmentVariableName | None = None


class AIProviderConfig(_AIValue):
    """Validated provider settings that never contain API-key material."""

    provider_id: UUID
    display_name: DisplayName
    provider_type: AIProviderType = AIProviderType.OPENAI_COMPATIBLE
    base_url: AnyHttpUrl
    model: ModelName
    secret_ref: SecretReference
    timeout_seconds: int = Field(default=30, ge=1, le=120)
    max_retries: int = Field(default=2, ge=0, le=2)
    max_input_chars: int = Field(default=50_000, ge=1, le=200_000)
    max_output_tokens: int = Field(default=4_096, ge=1, le=16_384)
    temperature: float = Field(default=0, ge=0, le=0.3)
    prompt_version: PromptVersion = "plan-extract-v1"
    allow_redirects: Literal[False] = False
    enabled: bool = True

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


class TradePlanDraft(TradePlan):
    """Validated, immutable plan candidate with no activation capability."""


class FieldEvidence(_AIValue):
    """One draft leaf mapped to a bounded source excerpt or exact location."""

    path: ExtractionPath
    excerpt: EvidenceExcerpt
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def require_complete_valid_location(self) -> FieldEvidence:
        if (self.start is None) != (self.end is None):
            raise ValueError("start and end must both be present or absent")
        if self.start is not None and self.end is not None and self.end <= self.start:
            raise ValueError("end must be greater than start")
        return self


class ExtractionIssue(_AIValue):
    """Bounded AI-reported assumption or warning awaiting user review."""

    path: ExtractionPath
    message: ExtractionMessage
    material: bool


class UnmappedText(_AIValue):
    """Unsupported source text that cannot become an executable condition."""

    path: ExtractionPath
    excerpt: EvidenceExcerpt
    reason: ExtractionMessage
    material: bool
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def require_complete_valid_location(self) -> UnmappedText:
        if (self.start is None) != (self.end is None):
            raise ValueError("start and end must both be present or absent")
        if self.start is not None and self.end is not None and self.end <= self.start:
            raise ValueError("end must be greater than start")
        return self


class PlanExtractionOutput(_AIValue):
    """Only JSON shape accepted from an untrusted AI provider."""

    draft: TradePlanDraft
    evidence: tuple[FieldEvidence, ...] = Field(max_length=10_000)
    assumptions: tuple[ExtractionIssue, ...] = Field(default=(), max_length=256)
    warnings: tuple[ExtractionIssue, ...] = Field(default=(), max_length=256)
    unmapped_text: tuple[UnmappedText, ...] = Field(default=(), max_length=256)


class PlanExtractionStatus(StrEnum):
    """Stable extraction outcomes; none grants activation authority."""

    SUCCEEDED = "SUCCEEDED"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    CANCELLED = "CANCELLED"


class AIUsageSnapshot(_AIValue):
    """Immutable copy of validated provider usage without transport coupling."""

    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class PlanExtractionResult(_AIValue):
    """Review-only extraction receipt with draft provenance and local issues."""

    request_id: UUID
    provider_id: UUID
    model: ModelName
    prompt_version: PromptVersion
    source_text_sha256: SourceTextSha256
    draft: TradePlanDraft | None
    evidence: tuple[FieldEvidence, ...] = ()
    assumptions: tuple[ExtractionIssue, ...] = ()
    warnings: tuple[ExtractionIssue, ...] = ()
    unmapped_text: tuple[UnmappedText, ...] = ()
    validation_issues: tuple[ValidationIssue, ...] = ()
    usage: AIUsageSnapshot | None
    status: PlanExtractionStatus

    @model_validator(mode="after")
    def enforce_status_payload_consistency(self) -> PlanExtractionResult:
        if self.status is PlanExtractionStatus.SUCCEEDED:
            if self.draft is None or not self.evidence:
                raise ValueError("a succeeded extraction requires a draft and evidence")
            return self
        if self.draft is not None or any(
            (self.evidence, self.assumptions, self.warnings, self.unmapped_text)
        ):
            raise ValueError("a non-succeeded extraction cannot expose draft content")
        return self


def _is_explicit_loopback(host: str) -> bool:
    normalized = host.casefold().strip("[]")
    if normalized == "localhost":
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False


def _validation_error_without_inputs(error: ValidationError) -> ValidationError:
    line_errors = error.errors(include_url=False)
    for line_error in line_errors:
        line_error.pop("input", None)
    return ValidationError.from_exception_data(
        error.title,
        line_errors,
        hide_input=True,
    )


__all__ = [
    "AIProviderConfig",
    "AIProviderType",
    "AIUsageSnapshot",
    "ExtractionIssue",
    "FieldEvidence",
    "PlanExtractionOutput",
    "PlanExtractionResult",
    "PlanExtractionStatus",
    "SecretReference",
    "TradePlanDraft",
    "UnmappedText",
]
