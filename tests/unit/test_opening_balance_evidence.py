"""Single opening reduction evidence never grants historical inventory authority."""

import json
from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import date, datetime
from hashlib import sha256

import pytest

from trade_plan_monitor.state.opening_balance_evidence import (
    OpeningMutationUnknownReason,
    UnknownOpeningMutation,
    ValidatedOpeningMutation,
    decode_opening_balance_mutation,
)


def snapshot(**changes):
    return {
        "id": "opening-local",
        "symbol": "830001.BJ",
        "original_qty": 86,
        "remaining_qty": 86,
        "sellable_from": "2026-09-14",
        "confirmation_id": "确认-local",
        "revision": 0,
        "closed_at": None,
    } | changes


def legacy_hash(raw):
    payload = dict(raw)
    if payload["closed_at"] is not None:
        timestamp = datetime.fromisoformat(payload["closed_at"]).isoformat()
        payload["closed_at"] = timestamp[:-6] + "Z" if timestamp.endswith("+00:00") else timestamp
    return sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def arguments(*, before=None, after=None, quantity=7, board_lot=7, effective="2026-09-14"):
    before = snapshot() if before is None else before
    after = snapshot(remaining_qty=79, revision=1) if after is None else after
    return dict(
        action="POSITION_OPENING_BALANCE_REDUCTION_RECORDED",
        entity_type="POSITION_OPENING_BALANCE",
        entity_id=before["id"],
        before_hash=legacy_hash(before),
        after_hash=legacy_hash(after),
        created_at="2026-09-22T10:30:00+08:00",
        details_json=json.dumps(
            {
                "symbol": before["symbol"],
                "quantity": quantity,
                "recoveryEvidence": {
                    "schemaVersion": 1,
                    "effectiveTradeDate": effective,
                    "boardLot": board_lot,
                    "before": before,
                    "after": after,
                },
            },
            ensure_ascii=False,
        ),
    )


def change(args, path, value):
    details = json.loads(args["details_json"])
    target = details
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return args | {"details_json": json.dumps(details, ensure_ascii=False)}


def invalid(args):
    result = decode_opening_balance_mutation(**args)
    assert isinstance(result, UnknownOpeningMutation)
    assert result.status == "UNKNOWN"
    assert result.reason is OpeningMutationUnknownReason.INVALID_EVIDENCE


def test_valid_partial_is_immutable_preserves_odd_opening_and_same_day_sellability():
    args = arguments()
    untouched = deepcopy(args)
    result = decode_opening_balance_mutation(**args)
    assert isinstance(result, ValidatedOpeningMutation)
    assert result.status == "VALID"
    assert result.quantity == result.board_lot == 7
    assert result.effective_trade_date == result.before.sellable_from == date(2026, 9, 14)
    assert result.before.original_qty == result.before.remaining_qty == 86
    assert result.after.remaining_qty == 79
    assert result.after.revision == 1
    assert result.before.confirmation_id == "确认-local"
    assert result.created_at == args["created_at"]
    assert args == untouched
    assert decode_opening_balance_mutation(**args) == result
    with pytest.raises(FrozenInstanceError):
        result.quantity = 100
    with pytest.raises(FrozenInstanceError):
        result.after.remaining_qty = 0


@pytest.mark.parametrize(
    "closed_at",
    [
        "2026-09-22T02:29:59+00:00",
        "2026-09-22T02:29:59Z",
        "2026-09-22T10:31:00+08:00",
        "2026-09-13T23:00:00-04:00",
    ],
)
def test_full_closure_keeps_raw_timestamp_and_legacy_dto_hash_without_clock_order(closed_at):
    before = snapshot(remaining_qty=79, revision=1)
    after = snapshot(remaining_qty=0, revision=80, closed_at=closed_at)
    args = arguments(before=before, after=after, quantity=79, board_lot=1)
    result = decode_opening_balance_mutation(**args)
    assert isinstance(result, ValidatedOpeningMutation)
    assert result.after.closed_at == closed_at
    assert result.after_hash == legacy_hash(after)
    assert result.before.revision == 1
    assert result.after.revision == 80


def test_revision_is_per_operation_not_derived_from_original_quantity():
    result = decode_opening_balance_mutation(
        **arguments(
            before=snapshot(original_qty=100, remaining_qty=93, revision=1),
            after=snapshot(original_qty=100, remaining_qty=90, revision=2),
            quantity=3,
            board_lot=3,
        )
    )
    assert isinstance(result, ValidatedOpeningMutation)


@pytest.mark.parametrize(
    "key,value",
    [
        ("action", "POSITION_REDUCTION_RECORDED"),
        ("action", None),
        ("entity_type", "POSITION_LOT"),
        ("entity_id", "different"),
        ("entity_id", " opening-local "),
        ("entity_id", "x" * 37),
        ("before_hash", None),
        ("before_hash", "a" * 64),
        ("after_hash", "f" * 64),
        ("after_hash", "a" * 65),
        ("created_at", "2026-09-22T10:30:00"),
        ("created_at", "20260922T10:30:00+08:00"),
        ("created_at", "2026-09-22 10:30:00+08:00"),
        ("created_at", 1),
        ("created_at", "x" * 65),
        ("details_json", None),
        ("details_json", "[]"),
        ("details_json", "{broken"),
    ],
)
def test_invalid_metadata_is_unknown(key, value):
    invalid(arguments() | {key: value})


@pytest.mark.parametrize(
    "path,value",
    [
        (("quantity",), True),
        (("quantity",), 7.0),
        (("quantity",), "7"),
        (("quantity",), 0),
        (("quantity",), 8),
        (("symbol",), "003043.SZ"),
        (("recoveryEvidence", "schemaVersion"), True),
        (("recoveryEvidence", "schemaVersion"), "1"),
        (("recoveryEvidence", "boardLot"), 0),
        (("recoveryEvidence", "boardLot"), -1),
        (("recoveryEvidence", "boardLot"), True),
        (("recoveryEvidence", "boardLot"), 2),
        (("recoveryEvidence", "effectiveTradeDate"), "2026-09-13"),
        (("recoveryEvidence", "effectiveTradeDate"), "20260914"),
        (("recoveryEvidence", "before"), None),
        (("recoveryEvidence", "after"), []),
        (("recoveryEvidence", "before", "original_qty"), True),
        (("recoveryEvidence", "after", "revision"), 0),
        (("recoveryEvidence", "after", "closed_at"), "2026-09-22T10:30:00+08:00"),
        (("recoveryEvidence", "after", "confirmation_id"), "different"),
        (("recoveryEvidence", "after", "remaining_qty"), -1),
        (("recoveryEvidence", "before", "extra"), 1),
        (("recoveryEvidence", "extra"), 1),
        (("extra",), 1),
    ],
)
def test_corrupt_fields_cannot_become_valid(path, value):
    invalid(change(arguments(), path, value))


@pytest.mark.parametrize(
    "changes",
    [
        {"id": "other"},
        {"symbol": "003043.SZ"},
        {"confirmation_id": "other"},
        {"original_qty": 100},
        {"sellable_from": "2026-09-13"},
        {"remaining_qty": 78},
        {"revision": 2},
        {"remaining_qty": 0},
    ],
)
def test_recomputed_hash_cannot_hide_mutation_invariant_violation(changes):
    invalid(arguments(after=snapshot(remaining_qty=79, revision=1) | changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"original_qty": 0},
        {"remaining_qty": 0, "closed_at": "2026-09-22T00:00:00Z"},
        {"remaining_qty": 87},
        {"revision": -1},
        {"revision": True},
        {"confirmation_id": "x" * 129},
        {"confirmation_id": " padded "},
    ],
)
def test_invalid_before_with_consistent_hash_is_unknown(changes):
    invalid(arguments(before=snapshot() | changes))


def test_legacy_and_unsupported_are_distinct_unknowns_without_guessing():
    args = arguments()
    legacy = args | {"details_json": '{"quantity":7,"symbol":"830001.BJ"}'}
    result = decode_opening_balance_mutation(**legacy)
    assert result.reason is OpeningMutationUnknownReason.MISSING_EVIDENCE
    result = decode_opening_balance_mutation(
        **change(args, ("recoveryEvidence", "schemaVersion"), 2)
    )
    assert result.reason is OpeningMutationUnknownReason.UNSUPPORTED_VERSION
    invalid(legacy | {"action": "OTHER"})


@pytest.mark.parametrize(
    "raw",
    [
        '{"quantity":7,"quantity":7,"symbol":"830001.BJ"}',
        '{"quantity":NaN,"symbol":"830001.BJ"}',
        '{"quantity":Infinity,"symbol":"830001.BJ"}',
        "[" * 3000 + "]" * 3000,
        '"' + "\\ud800" + '"',
        "\ud800",
    ],
)
def test_malformed_duplicate_or_hostile_json_is_unknown(raw):
    invalid(arguments() | {"details_json": raw})


def test_byte_budget_is_exact_and_checked_before_json_parse(monkeypatch):
    args = arguments()
    raw = args["details_json"]
    at_limit = raw + " " * (16384 - len(raw.encode("utf-8")))
    assert isinstance(
        decode_opening_balance_mutation(**(args | {"details_json": at_limit})),
        ValidatedOpeningMutation,
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("oversized text must not reach JSON parser")

    monkeypatch.setattr(json, "loads", forbidden)
    invalid(args | {"details_json": at_limit + " "})
    invalid(args | {"details_json": "界" * 5500})
    invalid(args | {"details_json": "x" * 16385})
