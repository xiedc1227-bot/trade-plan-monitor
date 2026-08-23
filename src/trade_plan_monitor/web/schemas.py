"""Strict shared FastAPI response schemas for the local application boundary."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field


def _to_camel(name: str) -> str:
    head, *tail = name.split("_")
    return head + "".join(part.capitalize() for part in tail)


class _ApiValue(BaseModel):
    """Keep public API values closed, immutable, strict, and alias-compatible."""

    model_config = ConfigDict(
        alias_generator=_to_camel,
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        strict=True,
    )

    def model_copy(
        self,
        *,
        update: Mapping[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        if not update:
            return super().model_copy(deep=deep)
        values = self.model_dump(mode="python", round_trip=True)
        values.update(update)
        return type(self).model_validate(values)


class ApiErrorCode(StrEnum):
    """Stable public error categories owned by the FastAPI adapter."""

    BAD_REQUEST = "BAD_REQUEST"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    CONFLICT = "CONFLICT"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    RATE_LIMITED = "RATE_LIMITED"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


ErrorLocationPart = (
    Annotated[str, Field(strict=True, min_length=1, max_length=64)]
    | Annotated[
        int,
        Field(strict=True, ge=0),
    ]
)
ErrorDetailCode = Annotated[
    str,
    Field(strict=True, min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$"),
]
PublicMessage = Annotated[str, Field(strict=True, min_length=1, max_length=256)]
RequestId = Annotated[
    str,
    Field(strict=True, min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$"),
]


class ErrorDetail(_ApiValue):
    """One bounded validation location with no rejected input or raw exception data."""

    location: tuple[ErrorLocationPart, ...] = Field(min_length=1, max_length=16)
    code: ErrorDetailCode
    message: PublicMessage


class ErrorPayload(_ApiValue):
    """The stable inner API error document."""

    code: ApiErrorCode
    message: PublicMessage
    details: tuple[ErrorDetail, ...] = Field(default=(), max_length=100)
    request_id: RequestId


class ErrorResponse(_ApiValue):
    """The single public API error envelope."""

    error: ErrorPayload


__all__ = [
    "ApiErrorCode",
    "ErrorDetail",
    "ErrorPayload",
    "ErrorResponse",
]
