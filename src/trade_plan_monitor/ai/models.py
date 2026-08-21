"""Non-secret AI provider configuration and safe public status models.

Validation follows Pydantic URL/validator APIs and Python loopback semantics:
https://docs.pydantic.dev/latest/api/networks/
https://docs.pydantic.dev/latest/concepts/validators/
https://docs.python.org/3/library/ipaddress.html#ipaddress.IPv4Address.is_loopback
"""

from __future__ import annotations

from enum import StrEnum
from ipaddress import ip_address
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, StringConstraints, field_validator

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


class _AIValue(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
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


def _is_explicit_loopback(host: str) -> bool:
    normalized = host.casefold().strip("[]")
    if normalized == "localhost":
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False


__all__ = ["AIProviderConfig", "AIProviderType", "SecretReference"]
