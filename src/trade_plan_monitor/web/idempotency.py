"""Shared canonical idempotency helpers for local Web mutations."""

from __future__ import annotations

import json
from collections.abc import Mapping
from hashlib import sha256
from http import HTTPStatus
from typing import cast

from pydantic import BaseModel, ValidationError

from trade_plan_monitor.state.models import IdempotencyStatus
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
from trade_plan_monitor.web.schemas import MutationContext


def claim_replay[ModelT: BaseModel](
    work: SqlAlchemyUnitOfWork,
    *,
    context: MutationContext,
    request_hash: str,
    model_type: type[ModelT],
) -> ModelT | None:
    """Claim one intent or validate and return its completed canonical replay."""

    claim = work.idempotency.claim(context.idempotency_key, request_hash)
    if claim.status != IdempotencyStatus.COMPLETED:
        return None
    if claim.response_code != int(HTTPStatus.OK) or claim.response_json is None:
        raise RuntimeError("persisted idempotency response is invalid")
    try:
        return model_type.model_validate_json(claim.response_json)
    except TypeError, ValueError, ValidationError:
        raise RuntimeError("persisted idempotency response is invalid") from None


def complete_replay(
    work: SqlAlchemyUnitOfWork,
    *,
    context: MutationContext,
    request_hash: str,
    response: BaseModel,
) -> None:
    """Persist the validated public response in the mutation transaction."""

    work.idempotency.complete(
        context.idempotency_key,
        request_hash,
        response_code=int(HTTPStatus.OK),
        response=cast(
            Mapping[str, object],
            response.model_dump(mode="json", by_alias=True),
        ),
    )


def operation_hash(operation: str, command: object) -> str:
    """Hash a typed API command with its operation identity."""

    model_dump = getattr(command, "model_dump", None)
    if not callable(model_dump):
        raise TypeError("command must be an API value")
    payload = {
        "command": model_dump(mode="json", by_alias=True),
        "operation": operation,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


__all__ = ["claim_replay", "complete_replay", "operation_hash"]
