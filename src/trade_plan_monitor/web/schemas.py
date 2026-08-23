"""Strict shared FastAPI schemas for the local application boundary."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from fastapi import Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field
from pydantic_core import to_json

from trade_plan_monitor.market_data.models import ShanghaiDatetime


def _to_camel(name: str) -> str:
    head, *tail = name.split("_")
    return head + "".join(part.capitalize() for part in tail)


class ApiValue(BaseModel):
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


class ErrorDetail(ApiValue):
    """One bounded validation location with no rejected input or raw exception data."""

    location: tuple[ErrorLocationPart, ...] = Field(min_length=1, max_length=16)
    code: ErrorDetailCode
    message: PublicMessage


class ErrorPayload(ApiValue):
    """The stable inner API error document."""

    code: ApiErrorCode
    message: PublicMessage
    details: tuple[ErrorDetail, ...] = Field(default=(), max_length=100)
    request_id: RequestId


class ErrorResponse(ApiValue):
    """The single public API error envelope."""

    error: ErrorPayload


class OperationKind(StrEnum):
    """Bounded asynchronous work accepted by the T037 command boundary."""

    PLAN_EXTRACTION = "PLAN_EXTRACTION"
    AI_PROVIDER_TEST = "AI_PROVIDER_TEST"


class OperationReceipt(ApiValue):
    """Immediate receipt proving that work was queued outside the request handler."""

    operation_id: UUID
    kind: OperationKind
    status: Literal["QUEUED"]
    submitted_at: ShanghaiDatetime


IdempotencyKey = Annotated[
    str,
    Field(
        strict=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
IdempotencyKeyHeader = Annotated[
    IdempotencyKey,
    Header(alias="Idempotency-Key"),
]


class MutationContext(ApiValue):
    """Stable correlation data required by an audited idempotent application command."""

    idempotency_key: IdempotencyKey
    request_id: RequestId


def get_mutation_context(
    request: Request,
    idempotency_key: IdempotencyKeyHeader,
) -> MutationContext:
    """Bind a required idempotency key to the server-generated audit correlation ID."""

    return MutationContext(
        idempotency_key=idempotency_key,
        request_id=request.state.request_id,
    )


MutationContextDependency = Annotated[
    MutationContext,
    Depends(get_mutation_context),
]


def validate_api_response[ApiValueT: ApiValue](
    value: object,
    model_type: type[ApiValueT],
) -> ApiValueT:
    """Strictly revalidate an application-service value before public serialization."""

    if isinstance(value, model_type):
        value = value.model_dump(mode="python", round_trip=True)
    return model_type.model_validate_json(to_json(value))


__all__ = [
    "ApiValue",
    "ApiErrorCode",
    "ErrorDetail",
    "ErrorPayload",
    "ErrorResponse",
    "MutationContext",
    "MutationContextDependency",
    "OperationKind",
    "OperationReceipt",
    "validate_api_response",
]
