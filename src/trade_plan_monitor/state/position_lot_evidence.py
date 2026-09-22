"""Bounded single-audit consistency checks; not history or commit authority."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from trade_plan_monitor.state.repositories import (
    PositionLotRecord,
    _position_lot_hash,
    _symbol,
)

_SNAPSHOT_FIELDS = {
    "id",
    "symbol",
    "bucket",
    "quantity",
    "remaining_qty",
    "acquired_trade_date",
    "cost_fen",
    "related_alert_id",
    "closed_at",
}


class LotMutationUnknownReason(StrEnum):
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    UNSUPPORTED_VERSION = "UNSUPPORTED_VERSION"
    INVALID_EVIDENCE = "INVALID_EVIDENCE"


@dataclass(frozen=True)
class UnknownLotMutation:
    reason: LotMutationUnknownReason
    status: Literal["UNKNOWN"] = field(default="UNKNOWN", init=False)


@dataclass(frozen=True)
class ValidatedLotMutation:
    """Internally consistent evidence, with no database/replay/send permission."""

    action: str
    entity_id: str
    before_hash: str | None
    after_hash: str
    quantity: int
    effective_trade_date: date
    before: PositionLotRecord | None
    after: PositionLotRecord
    created_at: datetime
    status: Literal["VALID"] = field(default="VALID", init=False)


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("Invalid position-lot evidence")


def _object(value: object, keys: set[str]) -> dict:
    _require(type(value) is dict and value.keys() == keys)
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = dict(pairs)
    _require(len(result) == len(pairs))
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("Nonstandard JSON constant")


def _identifier(value: object, maximum: int) -> None:
    _require(type(value) is str and 0 < len(value) <= maximum and value == value.strip())


def _date(value: object) -> date:
    _require(type(value) is str)
    parsed = date.fromisoformat(value)
    _require(parsed.isoformat() == value)
    return parsed


def _timestamp(value: object) -> datetime:
    _require(type(value) is str)
    parsed = datetime.fromisoformat(value)
    _require(parsed.utcoffset() is not None)
    _require(parsed.isoformat() == (value[:-1] + "+00:00" if value.endswith("Z") else value))
    return parsed


def _snapshot(value: object) -> PositionLotRecord:
    raw = _object(value, _SNAPSHOT_FIELDS)
    _identifier(raw["id"], 128)
    _symbol(raw["symbol"])
    _require(type(raw["bucket"]) is str and raw["bucket"] in ("CORE", "TACTICAL"))
    for key in ("quantity", "cost_fen"):
        _require(type(raw[key]) is int and raw[key] > 0)
    remaining = raw["remaining_qty"]
    _require(type(remaining) is int and 0 <= remaining <= raw["quantity"])
    if raw["related_alert_id"] is not None:
        _identifier(raw["related_alert_id"], 36)
    acquired = _date(raw["acquired_trade_date"])
    closed = None if raw["closed_at"] is None else _timestamp(raw["closed_at"])
    _require((remaining == 0) == (closed is not None))
    return PositionLotRecord(**(raw | {"acquired_trade_date": acquired, "closed_at": closed}))


def decode_position_lot_mutation(
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    before_hash: str | None,
    after_hash: str,
    details_json: str,
    created_at: str,
) -> ValidatedLotMutation | UnknownLotMutation:
    """Decode one untrusted record without I/O or inferring missing history."""
    try:
        _require(type(details_json) is str and len(details_json) <= 16384)
        _require(len(details_json.encode("utf-8")) <= 16384)
        details = json.loads(
            details_json, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
        _require(type(details) is dict)
        _require(
            type(action) is str
            and action in ("POSITION_BUY_RECORDED", "POSITION_REDUCTION_RECORDED")
        )
        _require(type(entity_type) is str and entity_type == "POSITION_LOT")
        _identifier(entity_id, 128)
        written = _timestamp(created_at)
        keys = {"symbol", "bucket", "quantity"}
        _object(details, keys | ({"recoveryEvidence"} if "recoveryEvidence" in details else set()))
        quantity = details["quantity"]
        _require(type(quantity) is int and quantity > 0)
        _symbol(details["symbol"])
        _require(type(details["bucket"]) is str and details["bucket"] in ("CORE", "TACTICAL"))
        if "recoveryEvidence" not in details:
            return UnknownLotMutation(LotMutationUnknownReason.MISSING_EVIDENCE)
        evidence = _object(
            details["recoveryEvidence"], {"schemaVersion", "effectiveTradeDate", "before", "after"}
        )
        _require(type(evidence["schemaVersion"]) is int)
        if evidence["schemaVersion"] != 1:
            return UnknownLotMutation(LotMutationUnknownReason.UNSUPPORTED_VERSION)
        effective = _date(evidence["effectiveTradeDate"])
        after = _snapshot(evidence["after"])
        _require(
            after.id == entity_id
            and after.symbol == details["symbol"]
            and after.bucket == details["bucket"]
        )
        _require(type(after_hash) is str and _position_lot_hash(after) == after_hash)
        before = None if evidence["before"] is None else _snapshot(evidence["before"])
        if action == "POSITION_BUY_RECORDED":
            _require(before is None and before_hash is None)
            _require(after.quantity == after.remaining_qty == quantity and after.closed_at is None)
            _require(effective == after.acquired_trade_date)
        else:
            _require(before is not None and before.closed_at is None and before.remaining_qty > 0)
            _require(type(before_hash) is str and _position_lot_hash(before) == before_hash)
            _require(
                all(
                    getattr(before, key) == getattr(after, key)
                    for key in _SNAPSHOT_FIELDS - {"remaining_qty", "closed_at"}
                )
            )
            _require(before.remaining_qty - after.remaining_qty == quantity)
            _require(effective > before.acquired_trade_date)
        return ValidatedLotMutation(
            action, entity_id, before_hash, after_hash, quantity, effective, before, after, written
        )
    except ValueError, TypeError, RecursionError, OverflowError:
        return UnknownLotMutation(LotMutationUnknownReason.INVALID_EVIDENCE)
