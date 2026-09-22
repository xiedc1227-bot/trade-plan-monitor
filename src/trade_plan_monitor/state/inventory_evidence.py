"""Validate stored inventory records, without granting history or replay authority."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from hashlib import sha256
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from trade_plan_monitor.state.opening_balance_evidence import (
    OpeningBalanceEvidenceSnapshot,
    _hash_text,
    _stored_timestamp,
)
from trade_plan_monitor.state.opening_balance_evidence import (
    _snapshot as _opening_snapshot,
)
from trade_plan_monitor.state.position_lot_evidence import (
    _date,
    _identifier,
    _object,
    _reject_constant,
    _require,
    _unique_object,
)
from trade_plan_monitor.state.repositories import _canonical_json, _symbol

MAX_INVENTORY_DETAILS_BYTES = 262144
MAX_MEMBER_JSON_BYTES = 65536
MAX_INVENTORY_MEMBERS = 1000
_CONFIRMATION_FIELDS = {
    "symbol", "confirmation_id", "as_of_trade_date", "confirmed_at", "inventory_revision",
    "total_qty", "sellable_qty", "included_lot_ids_json", "opening_balance_ids_json",
    "complete_registration",
}
_CONFIRMED = "POSITION_INVENTORY_CONFIRMED"
_CHANGED = "POSITION_INVENTORY_CHANGED"
_SOURCE_TYPES = {
    "POSITION_BUY_RECORDED": "POSITION_LOT",
    "POSITION_REDUCTION_RECORDED": "POSITION_LOT",
    "POSITION_OPENING_BALANCE_REDUCTION_RECORDED": "POSITION_OPENING_BALANCE",
}


class InventoryMutationUnknownReason(StrEnum):
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    UNSUPPORTED_VERSION = "UNSUPPORTED_VERSION"
    INVALID_EVIDENCE = "INVALID_EVIDENCE"
    EVIDENCE_LIMIT = "EVIDENCE_LIMIT"


@dataclass(frozen=True)
class InventoryConfirmationSnapshot:
    symbol: str
    confirmation_id: str
    as_of_trade_date: date
    confirmed_at: str
    inventory_revision: int
    total_qty: int
    sellable_qty: int
    included_lot_ids_json: str
    opening_balance_ids_json: str
    complete_registration: bool

    @property
    def included_lot_ids(self) -> tuple[str, ...]:
        return tuple(json.loads(self.included_lot_ids_json))

    @property
    def opening_balance_ids(self) -> tuple[str, ...]:
        return tuple(json.loads(self.opening_balance_ids_json))


@dataclass(frozen=True)
class InventoryMutationSource:
    id: str
    action: str
    entity_type: str
    entity_id: str


@dataclass(frozen=True)
class UnknownInventoryMutation:
    reason: InventoryMutationUnknownReason
    status: Literal["UNKNOWN"] = field(default="UNKNOWN", init=False)


@dataclass(frozen=True)
class ValidatedInventoryMutation:
    """One consistent row; all commit, source and history proof remains external."""

    audit_id: str
    action: str
    entity_id: str
    previous_revision: int
    next_revision: int
    before: InventoryConfirmationSnapshot | None
    after: InventoryConfirmationSnapshot | None
    created_opening_balance: OpeningBalanceEvidenceSnapshot | None
    source_audit: InventoryMutationSource | None
    effective_trade_date: date
    total_delta: int | None
    sync_outcome: str | None
    created_at: str
    status: Literal["VALID"] = field(default="VALID", init=False)


class _EvidenceLimit(ValueError):
    pass


def _json(value: object, maximum: int):
    _require(type(value) is str)
    if len(value) > maximum or len(value.encode("utf-8")) > maximum:
        raise _EvidenceLimit()
    return json.loads(value, object_pairs_hook=_unique_object, parse_constant=_reject_constant)


def _id(value: object) -> None:
    _identifier(value, 128)
    # JSON escapes can hide lone surrogates from the outer raw-byte budget check.
    value.encode("utf-8")


def _nonnegative(value: object) -> None:
    _require(type(value) is int and value >= 0)


def _members(value: object) -> tuple[str, ...]:
    members = _json(value, MAX_MEMBER_JSON_BYTES)
    _require(type(members) is list)
    if len(members) > MAX_INVENTORY_MEMBERS:
        raise _EvidenceLimit()
    for member in members:
        _id(member)
    _require(len(set(members)) == len(members))
    return tuple(members)


def _confirmation(value: object, symbol: str) -> InventoryConfirmationSnapshot | None:
    if value is None:
        return None
    raw = _object(value, _CONFIRMATION_FIELDS)
    _require(raw["symbol"] == symbol)
    _id(raw["confirmation_id"])
    _stored_timestamp(raw["confirmed_at"])
    for key in ("inventory_revision", "total_qty", "sellable_qty"):
        _nonnegative(raw[key])
    _require(raw["complete_registration"] is True and raw["sellable_qty"] <= raw["total_qty"])
    _members(raw["included_lot_ids_json"])
    _members(raw["opening_balance_ids_json"])
    return InventoryConfirmationSnapshot(**(raw | {
        "as_of_trade_date": _date(raw["as_of_trade_date"]),
    }))


def _advance(previous: object, following: object) -> None:
    _nonnegative(previous)
    _nonnegative(following)
    _require(following == previous + 1)


def _hash(value: object) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _confirmed(evidence, details, symbol, before_hash, after_hash, written):
    _object(evidence, {"schemaVersion", "previousInventoryRevision", "nextInventoryRevision",
                       "before", "after", "createdOpeningBalance"})
    previous, following = evidence["previousInventoryRevision"], evidence["nextInventoryRevision"]
    _advance(previous, following)
    before = _confirmation(evidence["before"], symbol)
    after = _confirmation(evidence["after"], symbol)
    effective = _date(details["asOfTradeDate"])
    _require(after is not None and before_hash is None)
    _require(after.inventory_revision == following and after.as_of_trade_date == effective)
    _require(after.confirmed_at == written)
    _require(after.total_qty % 100 == after.sellable_qty % 100 == 0)
    _require(after_hash == _hash({
        "confirmationId": after.confirmation_id, "inventoryRevision": following,
        "sellableQty": after.sellable_qty, "symbol": symbol, "totalQty": after.total_qty,
    }))
    opening = evidence["createdOpeningBalance"]
    if opening is not None:
        opening = _opening_snapshot(opening)
        _require(opening.symbol == symbol and opening.confirmation_id == after.confirmation_id)
        _require(opening.id in after.opening_balance_ids and opening.sellable_from == effective)
        _require(opening.original_qty == opening.remaining_qty > 0)
        _require(opening.revision == 0 and opening.closed_at is None)
        _require(opening.remaining_qty <= after.sellable_qty)
    return previous, following, before, after, opening, None, effective, None, None


def _changed(evidence, symbol, audit_id, before_hash, after_hash):
    _object(evidence, {"schemaVersion", "sourceAudit", "effectiveTradeDate", "totalDelta",
                       "syncOutcome", "before", "after"})
    source = _object(evidence["sourceAudit"], {"id", "action", "entityType", "entityId"})
    _id(source["id"])
    _id(source["entityId"])
    _require(type(source["action"]) is str and source["action"] in _SOURCE_TYPES)
    _require(source["entityType"] == _SOURCE_TYPES[source["action"]])
    _require(audit_id == str(uuid5(
        NAMESPACE_URL, "trade-plan-monitor:inventory-recovery:v1:" + source["id"],
    )))
    delta = evidence["totalDelta"]
    _require(type(delta) is int and delta != 0)
    _require((delta > 0) == (source["action"] == "POSITION_BUY_RECORDED"))
    old = _object(evidence["before"], {"inventoryRevision", "confirmation"})
    new = _object(evidence["after"], {"inventoryRevision", "confirmation"})
    previous, following = old["inventoryRevision"], new["inventoryRevision"]
    _advance(previous, following)
    before, after = _confirmation(old["confirmation"], symbol), _confirmation(
        new["confirmation"], symbol,
    )
    _require(before_hash == _hash(old) and after_hash == _hash(new))
    outcome = evidence["syncOutcome"]
    _require(type(outcome) is str and outcome in ("SYNCED", "MISSING", "STALE"))
    if outcome == "MISSING":
        _require(before is None and after is None)
    elif outcome == "STALE":
        _require(before is not None and before.inventory_revision != previous and before == after)
    else:
        _require(before is not None and after is not None and before.inventory_revision == previous)
        _require(after.inventory_revision == following)
        _require(after.total_qty == before.total_qty + delta)
        _require(after.sellable_qty == min(before.sellable_qty, after.total_qty))
        _require(all(
            getattr(before, key) == getattr(after, key)
            for key in _CONFIRMATION_FIELDS - {"inventory_revision", "total_qty", "sellable_qty"}
        ))
    origin = InventoryMutationSource(
        source["id"], source["action"], source["entityType"], source["entityId"],
    )
    return previous, following, before, after, None, origin, _date(
        evidence["effectiveTradeDate"],
    ), delta, outcome


def decode_inventory_mutation(
    *, audit_id: str, action: str, entity_type: str, entity_id: str,
    before_hash: str | None, after_hash: str, details_json: str, created_at: str,
) -> ValidatedInventoryMutation | UnknownInventoryMutation:
    """Check bounded untrusted records, preserving dates without choosing replay policy."""
    try:
        _id(audit_id)
        _require(type(action) is str and action in (_CONFIRMED, _CHANGED))
        _require(type(entity_type) is str and entity_type == "POSITION_INVENTORY")
        _symbol(entity_id)
        _hash_text(after_hash)
        if before_hash is not None:
            _hash_text(before_hash)
        _stored_timestamp(created_at)
        details = _json(details_json, MAX_INVENTORY_DETAILS_BYTES)
        _require(type(details) is dict)
        base = {"asOfTradeDate", "completeRegistration"} if action == _CONFIRMED else set()
        _object(details, base | ({"recoveryEvidence"} if "recoveryEvidence" in details else set()))
        if action == _CONFIRMED:
            _require(details["completeRegistration"] is True)
            _date(details["asOfTradeDate"])
            _require(before_hash is None)
        if "recoveryEvidence" not in details:
            return UnknownInventoryMutation(InventoryMutationUnknownReason.MISSING_EVIDENCE)
        evidence = details["recoveryEvidence"]
        _require(type(evidence) is dict and type(evidence.get("schemaVersion")) is int)
        if evidence["schemaVersion"] != 1:
            return UnknownInventoryMutation(InventoryMutationUnknownReason.UNSUPPORTED_VERSION)
        values = (
            _confirmed(evidence, details, entity_id, before_hash, after_hash, created_at)
            if action == _CONFIRMED else
            _changed(evidence, entity_id, audit_id, before_hash, after_hash)
        )
        return ValidatedInventoryMutation(audit_id, action, entity_id, *values, created_at)
    except _EvidenceLimit:
        return UnknownInventoryMutation(InventoryMutationUnknownReason.EVIDENCE_LIMIT)
    except ValueError, TypeError, RecursionError, OverflowError:
        return UnknownInventoryMutation(InventoryMutationUnknownReason.INVALID_EVIDENCE)
