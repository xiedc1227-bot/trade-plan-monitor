"""Inventory receipts retain raw evidence without granting historical authority."""

import json
from copy import deepcopy
from datetime import date
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

import pytest

from trade_plan_monitor.state.inventory_evidence import decode_inventory_mutation

SYMBOL = "003043.SZ"
STAMP = "2026-09-14T01:00:00+00:00"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return sha256(canonical(value).encode()).hexdigest()


def confirmation(**updates):
    return {
        "symbol": SYMBOL, "confirmation_id": "confirmation-1",
        "as_of_trade_date": "2026-09-14", "confirmed_at": STAMP,
        "inventory_revision": 1, "total_qty": 100, "sellable_qty": 100,
        "included_lot_ids_json": "[  ]", "opening_balance_ids_json": '[ "opening-1" ]',
        "complete_registration": True,
    } | updates


def confirmation_row():
    after = confirmation()
    return row(
        action="POSITION_INVENTORY_CONFIRMED", audit_id="audit-1", before_hash=None,
        after_hash=digest({"confirmationId": "confirmation-1", "inventoryRevision": 1,
                           "sellableQty": 100, "symbol": SYMBOL, "totalQty": 100}),
        details={
            "asOfTradeDate": "2026-09-14", "completeRegistration": True,
            "recoveryEvidence": {
                "schemaVersion": 1, "previousInventoryRevision": 0,
                "nextInventoryRevision": 1, "before": None, "after": after,
                "createdOpeningBalance": {
                    "id": "opening-1", "symbol": SYMBOL, "original_qty": 100,
                    "remaining_qty": 100, "sellable_from": "2026-09-14",
                    "confirmation_id": "confirmation-1", "revision": 0, "closed_at": None,
                },
            },
        },
    )


def row(*, action, audit_id, before_hash, after_hash, details):
    return dict(audit_id=audit_id, action=action, entity_type="POSITION_INVENTORY",
                entity_id=SYMBOL, before_hash=before_hash, after_hash=after_hash,
                details_json=canonical(details), created_at=STAMP)


def change_row(*, outcome="SYNCED", delta=-7):
    before = None if outcome == "MISSING" else confirmation(
        inventory_revision=0 if outcome == "STALE" else 1,
    )
    after = deepcopy(before)
    if outcome == "SYNCED":
        after.update(inventory_revision=2, total_qty=100 + delta,
                     sellable_qty=min(100, 100 + delta))
    before_state = {"inventoryRevision": 1, "confirmation": before}
    after_state = {"inventoryRevision": 2, "confirmation": after}
    return row(
        audit_id=str(uuid5(NAMESPACE_URL, "trade-plan-monitor:inventory-recovery:v1:source-1")),
        action="POSITION_INVENTORY_CHANGED", before_hash=digest(before_state),
        after_hash=digest(after_state),
        details={"recoveryEvidence": {
            "schemaVersion": 1,
            "sourceAudit": {"id": "source-1", "action": "POSITION_BUY_RECORDED"
                            if delta > 0 else "POSITION_OPENING_BALANCE_REDUCTION_RECORDED",
                            "entityType": "POSITION_LOT" if delta > 0
                            else "POSITION_OPENING_BALANCE", "entityId": "opening-1"},
            "effectiveTradeDate": "2026-09-14", "totalDelta": delta, "syncOutcome": outcome,
            "before": before_state, "after": after_state,
        }},
    )


def edit(value, path, replacement, *, rehash=False):
    result = deepcopy(value)
    details = json.loads(result["details_json"])
    target = details
    for component in path[:-1]:
        target = target[component]
    target[path[-1]] = replacement
    result["details_json"] = canonical(details)
    if rehash:
        result["before_hash"] = digest(details["recoveryEvidence"]["before"])
        result["after_hash"] = digest(details["recoveryEvidence"]["after"])
    return result


def test_confirmation_preserves_raw_strings_and_creation():
    result = decode_inventory_mutation(**confirmation_row())
    assert result.status == "VALID"
    assert (result.previous_revision, result.next_revision) == (0, 1)
    assert result.effective_trade_date == date(2026, 9, 14)
    assert result.after.confirmed_at == result.created_at == STAMP
    assert result.after.opening_balance_ids_json == '[ "opening-1" ]'
    assert result.after.opening_balance_ids == ("opening-1",)
    assert result.created_opening_balance.remaining_qty == 100
    assert result.source_audit is None
    with pytest.raises(AttributeError):
        result.after.total_qty = 0


@pytest.mark.parametrize("outcome", ["SYNCED", "MISSING", "STALE"])
@pytest.mark.parametrize("delta", [-7, 7])
def test_receipt_validates_all_outcomes_and_odd_quantities(outcome, delta):
    result = decode_inventory_mutation(**change_row(outcome=outcome, delta=delta))
    assert result.status == "VALID"
    assert result.sync_outcome == outcome
    assert (result.previous_revision, result.next_revision) == (1, 2)
    assert result.total_delta == delta
    if outcome == "SYNCED":
        assert result.after.total_qty == 100 + delta
        assert result.after.sellable_qty == min(100, 100 + delta)
    else:
        assert result.after == result.before


@pytest.mark.parametrize("field,value", [
    ("action", "UNKNOWN"), ("entity_type", "POSITION_LOT"), ("entity_id", "600000.SH"),
    ("audit_id", "wrong-derived-id"), ("before_hash", "0" * 64), ("after_hash", None),
    ("created_at", "2026-09-14T01:00:00"), ("created_at", "x" * 65),
])
def test_invalid_receipt_metadata_is_unknown(field, value):
    result = decode_inventory_mutation(**(change_row() | {field: value}))
    assert result.status == "UNKNOWN"
    assert result.reason == "INVALID_EVIDENCE"


@pytest.mark.parametrize("path,value", [
    (("totalDelta",), True), (("totalDelta",), 0), (("totalDelta",), 7),
    (("syncOutcome",), "STALE"), (("sourceAudit", "entityType"), "POSITION_LOT"),
    (("before", "inventoryRevision"), True), (("after", "inventoryRevision"), 3),
    (("after", "confirmation", "confirmation_id"), "other"),
    (("after", "confirmation", "confirmed_at"), "2026-09-14T01:00:01+00:00"),
    (("after", "confirmation", "total_qty"), 92),
    (("after", "confirmation", "sellable_qty"), 94),
    (("after", "confirmation", "complete_registration"), 1),
    (("after", "confirmation", "included_lot_ids_json"), '["same","same"]'),
    (("after", "confirmation", "opening_balance_ids_json"), "[NaN]"),
])
def test_recomputed_hashes_do_not_bypass_mutation_rules(path, value):
    altered = edit(change_row(), ("recoveryEvidence", *path), value, rehash=True)
    assert decode_inventory_mutation(**altered).status == "UNKNOWN"


@pytest.mark.parametrize("path,value", [
    (("nextInventoryRevision",), 2), (("after", "inventory_revision"), 0),
    (("after", "confirmed_at"), "2026-09-14T01:00:00Z"),
    (("after", "as_of_trade_date"), "2026-09-15"),
    (("createdOpeningBalance", "revision"), 1),
    (("createdOpeningBalance", "confirmation_id"), "other"),
    (("createdOpeningBalance", "remaining_qty"), 99),
    (("createdOpeningBalance", "sellable_from"), "2026-09-13"),
    (("after", "opening_balance_ids_json"), '[]'),
])
def test_confirmation_creation_bindings_are_required(path, value):
    assert decode_inventory_mutation(**edit(
        confirmation_row(), ("recoveryEvidence", *path), value,
    )).status == "UNKNOWN"


@pytest.mark.parametrize("details", ['{"recoveryEvidence":{},"recoveryEvidence":{}}',
                                      "NaN", "[]", "{" , '"' + "\\ud800" + '"',
                                      "[" * 1100 + "]" * 1100])
def test_hostile_json_is_bounded_unknown(details):
    result = decode_inventory_mutation(**(change_row() | {"details_json": details}))
    assert result.status == "UNKNOWN"
    assert result.reason == "INVALID_EVIDENCE"


@pytest.mark.parametrize("kind", ["outer", "member_bytes", "member_count"])
def test_evidence_budget_is_not_silent_truncation(kind):
    value = change_row()
    if kind == "outer":
        value["details_json"] = " " * 262145
    else:
        members = " " * 65537 if kind == "member_bytes" else canonical(
            [f"lot-{number}" for number in range(1001)],
        )
        value = edit(value, ("recoveryEvidence", "before", "confirmation",
                            "included_lot_ids_json"), members, rehash=True)
    result = decode_inventory_mutation(**value)
    assert result.status == "UNKNOWN"
    assert result.reason == "EVIDENCE_LIMIT"


def test_large_valid_member_list_is_not_given_the_fixed_opening_budget():
    members = canonical(["lot-" + str(number).zfill(30) for number in range(1000)])
    value = change_row()
    for side in ("before", "after"):
        value = edit(value, ("recoveryEvidence", side, "confirmation",
                            "included_lot_ids_json"), members, rehash=True)
    assert len(value["details_json"]) > 16384
    result = decode_inventory_mutation(**value)
    assert result.status == "VALID"
    assert len(result.after.included_lot_ids) == 1000


def test_absent_and_unsupported_evidence_are_distinct():
    missing = confirmation_row() | {"details_json": canonical({
        "asOfTradeDate": "2026-09-14", "completeRegistration": True,
    })}
    assert decode_inventory_mutation(**missing).reason == "MISSING_EVIDENCE"
    future = edit(confirmation_row(), ("recoveryEvidence", "schemaVersion"), 2)
    assert decode_inventory_mutation(**future).reason == "UNSUPPORTED_VERSION"


@pytest.mark.parametrize("kind", ["confirmation_member", "change_member", "source_entity", "audit"])
def test_json_escaped_surrogate_ids_cannot_pass_utf8_envelope_checks(kind):
    value = confirmation_row() if kind == "confirmation_member" else change_row()
    if kind == "audit":
        value = confirmation_row() | {"audit_id": "\ud800"}
    elif kind == "source_entity":
        details = json.loads(value["details_json"])
        details["recoveryEvidence"]["sourceAudit"]["entityId"] = "\ud800"
        value["details_json"] = json.dumps(details, ensure_ascii=True)
    else:
        members = json.dumps(["\ud800"], ensure_ascii=True)
        for side in (("after",) if kind == "confirmation_member" else ("before", "after")):
            path = ("recoveryEvidence", side)
            if kind == "change_member":
                path += ("confirmation",)
            value = edit(value, (*path, "included_lot_ids_json"), members,
                         rehash=kind == "change_member")
    result = decode_inventory_mutation(**value)
    assert result.status == "UNKNOWN"
    assert result.reason == "INVALID_EVIDENCE"
