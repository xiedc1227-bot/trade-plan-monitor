"""Bounded opening-reduction consistency checks, not historical inventory proof."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Literal

from trade_plan_monitor.state.position_lot_evidence import (
    _date,
    _identifier,
    _object,
    _reject_constant,
    _require,
    _timestamp,
    _unique_object,
)
from trade_plan_monitor.state.repositories import OpeningBalanceRecord, _canonical_json, _symbol

_SNAPSHOT_FIELDS = {
    "id",
    "symbol",
    "original_qty",
    "remaining_qty",
    "sellable_from",
    "confirmation_id",
    "revision",
    "closed_at",
}
_MUTABLE_FIELDS = {"remaining_qty", "revision", "closed_at"}


class OpeningMutationUnknownReason(StrEnum):
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    UNSUPPORTED_VERSION = "UNSUPPORTED_VERSION"
    INVALID_EVIDENCE = "INVALID_EVIDENCE"


@dataclass(frozen=True)
class OpeningBalanceEvidenceSnapshot:
    """A validated stored row; keep closure text distinct from legacy DTO JSON."""

    id: str
    symbol: str
    original_qty: int
    remaining_qty: int
    sellable_from: date
    confirmation_id: str
    revision: int
    closed_at: str | None


@dataclass(frozen=True)
class UnknownOpeningMutation:
    reason: OpeningMutationUnknownReason
    status: Literal["UNKNOWN"] = field(default="UNKNOWN", init=False)


@dataclass(frozen=True)
class ValidatedOpeningMutation:
    """One consistent mutation, with no database, replay or delivery authority."""

    action: str
    entity_id: str
    before_hash: str
    after_hash: str
    quantity: int
    board_lot: int
    effective_trade_date: date
    before: OpeningBalanceEvidenceSnapshot
    after: OpeningBalanceEvidenceSnapshot
    created_at: str
    status: Literal["VALID"] = field(default="VALID", init=False)


def _stored_timestamp(value: object) -> None:
    _require(type(value) is str and len(value) <= 64)
    _timestamp(value)


def _hash_text(value: object) -> None:
    _require(type(value) is str and len(value) == 64)
    _require(all(character in "0123456789abcdef" for character in value))


def _snapshot(value: object) -> OpeningBalanceEvidenceSnapshot:
    raw = _object(value, _SNAPSHOT_FIELDS)
    _identifier(raw["id"], 36)
    _identifier(raw["confirmation_id"], 128)
    _symbol(raw["symbol"])
    original, remaining, revision = (
        raw[key] for key in ("original_qty", "remaining_qty", "revision")
    )
    _require(type(original) is int and original > 0)
    _require(type(remaining) is int and 0 <= remaining <= original)
    _require(type(revision) is int and revision >= 0)
    if raw["closed_at"] is not None:
        _stored_timestamp(raw["closed_at"])
    _require((remaining == 0) == (raw["closed_at"] is not None))
    return OpeningBalanceEvidenceSnapshot(**(raw | {"sellable_from": _date(raw["sellable_from"])}))


def _legacy_hash(snapshot: OpeningBalanceEvidenceSnapshot) -> str:
    # The writer hashes DTO JSON, which normalizes UTC; the new raw evidence does not.
    closed = None if snapshot.closed_at is None else datetime.fromisoformat(snapshot.closed_at)
    record = OpeningBalanceRecord(**(asdict(snapshot) | {"closed_at": closed}))
    return sha256(_canonical_json(record.model_dump(mode="json")).encode("utf-8")).hexdigest()


def decode_opening_balance_mutation(
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    before_hash: str,
    after_hash: str,
    details_json: str,
    created_at: str,
) -> ValidatedOpeningMutation | UnknownOpeningMutation:
    """Validate one bounded untrusted row without inferring its source or history."""
    try:
        _require(type(details_json) is str and len(details_json) <= 16384)
        _require(len(details_json.encode("utf-8")) <= 16384)
        _require(type(action) is str and action == "POSITION_OPENING_BALANCE_REDUCTION_RECORDED")
        _require(type(entity_type) is str and entity_type == "POSITION_OPENING_BALANCE")
        _identifier(entity_id, 36)
        _hash_text(before_hash)
        _hash_text(after_hash)
        _stored_timestamp(created_at)
        details = json.loads(
            details_json,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
        _require(type(details) is dict)
        keys = {"quantity", "symbol"}
        _object(details, keys | ({"recoveryEvidence"} if "recoveryEvidence" in details else set()))
        quantity = details["quantity"]
        _require(type(quantity) is int and quantity > 0)
        _symbol(details["symbol"])
        if "recoveryEvidence" not in details:
            return UnknownOpeningMutation(OpeningMutationUnknownReason.MISSING_EVIDENCE)
        evidence = _object(
            details["recoveryEvidence"],
            {
                "schemaVersion",
                "effectiveTradeDate",
                "boardLot",
                "before",
                "after",
            },
        )
        _require(type(evidence["schemaVersion"]) is int)
        if evidence["schemaVersion"] != 1:
            return UnknownOpeningMutation(OpeningMutationUnknownReason.UNSUPPORTED_VERSION)
        board_lot = evidence["boardLot"]
        _require(type(board_lot) is int and board_lot > 0 and quantity % board_lot == 0)
        effective = _date(evidence["effectiveTradeDate"])
        before, after = _snapshot(evidence["before"]), _snapshot(evidence["after"])
        _require(before.id == after.id == entity_id)
        _require(before.symbol == after.symbol == details["symbol"])
        _require(before.remaining_qty > 0 and before.closed_at is None)
        _require(
            all(
                getattr(before, key) == getattr(after, key)
                for key in _SNAPSHOT_FIELDS - _MUTABLE_FIELDS
            )
        )
        _require(before.remaining_qty - after.remaining_qty == quantity)
        _require(after.revision == before.revision + quantity // board_lot)
        _require(effective >= before.sellable_from)
        _require(_legacy_hash(before) == before_hash and _legacy_hash(after) == after_hash)
        return ValidatedOpeningMutation(
            action,
            entity_id,
            before_hash,
            after_hash,
            quantity,
            board_lot,
            effective,
            before,
            after,
            created_at,
        )
    except ValueError, TypeError, RecursionError, OverflowError:
        return UnknownOpeningMutation(OpeningMutationUnknownReason.INVALID_EVIDENCE)
