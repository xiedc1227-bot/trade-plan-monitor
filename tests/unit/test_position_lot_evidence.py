"""Adversarial single-record decoding, independent of database authority."""

import json
from dataclasses import FrozenInstanceError
from datetime import date, datetime
from hashlib import sha256

import pytest
from pydantic import ValidationError

from trade_plan_monitor.state.position_lot_evidence import (
    LotMutationUnknownReason,
    UnknownLotMutation,
    ValidatedLotMutation,
    decode_position_lot_mutation,
)


def snapshot(**changes):
    return {
        "id": "local-lot",
        "symbol": "830001.BJ",
        "bucket": "TACTICAL",
        "quantity": 14,
        "remaining_qty": 14,
        "acquired_trade_date": "2026-09-11",
        "cost_fen": 123,
        "related_alert_id": "local-alert",
        "closed_at": None,
    } | changes


def independent_hash(value):
    names = {
        "remaining_qty": "remainingQty",
        "acquired_trade_date": "acquiredTradeDate",
        "cost_fen": "costFen",
        "related_alert_id": "relatedAlertId",
        "closed_at": "closedAt",
    }
    payload = {names.get(key, key): item for key, item in value.items()}
    if payload["closedAt"] is not None:
        payload["closedAt"] = datetime.fromisoformat(payload["closedAt"]).isoformat()
    return sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def arguments(*, before=None, after=None, quantity=14, effective="2026-09-11"):
    after = snapshot() if after is None else after
    return dict(
        action="POSITION_BUY_RECORDED" if before is None else "POSITION_REDUCTION_RECORDED",
        entity_type="POSITION_LOT",
        entity_id=after["id"],
        before_hash=None if before is None else independent_hash(before),
        after_hash=independent_hash(after),
        created_at="2026-09-22T10:30:00+08:00",
        details_json=json.dumps(
            {
                "symbol": after["symbol"],
                "bucket": after["bucket"],
                "quantity": quantity,
                "recoveryEvidence": {
                    "schemaVersion": 1,
                    "effectiveTradeDate": effective,
                    "before": before,
                    "after": after,
                },
            }
        ),
    )


def replace_detail(args, path, value):
    data = json.loads(args["details_json"])
    target = data
    for name in path[:-1]:
        target = target[name]
    target[path[-1]] = value
    return args | {"details_json": json.dumps(data)}


def invalid(args):
    result = decode_position_lot_mutation(**args)
    assert isinstance(result, UnknownLotMutation)
    assert result.status == "UNKNOWN"
    assert result.reason is LotMutationUnknownReason.INVALID_EVIDENCE


def test_buy_preserves_non_uuid_bj_custom_board_lot_and_is_immutable():
    args = arguments()
    original = args.copy()
    result = decode_position_lot_mutation(**args)
    assert isinstance(result, ValidatedLotMutation)
    assert result.status == "VALID"
    assert result.before is None
    assert result.after.id == "local-lot"
    assert result.after.remaining_qty == result.quantity == 14
    assert result.effective_trade_date == date(2026, 9, 11)
    assert result.created_at.isoformat() == args["created_at"]
    assert args == original
    assert result == decode_position_lot_mutation(**args)
    with pytest.raises(FrozenInstanceError):
        result.quantity = 2
    with pytest.raises(ValidationError):
        result.after.remaining_qty = 2


@pytest.mark.parametrize(
    "remaining,closed",
    [
        (7, None),
        (0, "2026-09-22T02:29:59+00:00"),
        (0, "2026-09-22T10:31:00+08:00"),
        (0, "2026-09-21T23:00:00-04:00"),
    ],
)
def test_reduction_hash_keeps_offset_without_clock_ordering(remaining, closed):
    before = snapshot()
    after = snapshot(remaining_qty=remaining, closed_at=closed)
    args = arguments(before=before, after=after, quantity=14 - remaining, effective="2026-09-14")
    result = decode_position_lot_mutation(**args)
    assert isinstance(result, ValidatedLotMutation)
    assert result.before.remaining_qty == 14
    assert result.after_hash == independent_hash(after)
    if closed:
        assert result.after.closed_at.isoformat() == closed


@pytest.mark.parametrize(
    "field,value",
    [
        ("action", "POSITION_UPDATED"),
        ("entity_type", "POSITION"),
        ("entity_id", "other"),
        ("entity_id", " local-lot"),
        ("after_hash", "0" * 64),
        ("after_hash", None),
        ("before_hash", "0" * 64),
        ("created_at", "2026-09-22T10:30:00"),
        ("created_at", 123),
    ],
)
def test_invalid_row_metadata(field, value):
    invalid(arguments() | {field: value})


@pytest.mark.parametrize(
    "path,value",
    [
        (("symbol",), "003043.SZ"),
        (("bucket",), "CORE"),
        (("quantity",), True),
        (("quantity",), "14"),
        (("quantity",), 14.0),
        (("quantity",), 0),
        (("quantity",), -1),
        (("recoveryEvidence", "effectiveTradeDate"), "20260911"),
        (("recoveryEvidence", "effectiveTradeDate"), "2026-02-30"),
        (("recoveryEvidence", "effectiveTradeDate"), "2026-09-12"),
        (("recoveryEvidence", "schemaVersion"), True),
        (("recoveryEvidence", "schemaVersion"), 1.0),
        (("recoveryEvidence", "schemaVersion"), "1"),
        (("recoveryEvidence", "after"), []),
        (("recoveryEvidence",), None),
    ],
)
def test_invalid_nested_fields(path, value):
    invalid(replace_detail(arguments(), path, value))


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", ""),
        ("id", "x" * 129),
        ("id", " padded"),
        ("related_alert_id", "x" * 37),
        ("related_alert_id", 1),
        ("symbol", "830001.bj"),
        ("symbol", "830001.US"),
        ("bucket", "OTHER"),
        ("quantity", True),
        ("quantity", "14"),
        ("quantity", 14.0),
        ("quantity", 0),
        ("remaining_qty", True),
        ("remaining_qty", 15),
        ("remaining_qty", -1),
        ("remaining_qty", 7),
        ("cost_fen", False),
        ("cost_fen", 0),
        ("cost_fen", 1.5),
        ("acquired_trade_date", "20260911"),
        ("acquired_trade_date", "2026-02-30"),
        ("closed_at", "2026-09-22T10:30:00+08:00"),
    ],
)
def test_invalid_snapshot_even_with_recomputed_hash(field, value):
    invalid(arguments(after=snapshot(**{field: value})))


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", "other"),
        ("symbol", "003043.SZ"),
        ("bucket", "CORE"),
        ("quantity", 21),
        ("cost_fen", 124),
        ("related_alert_id", None),
        ("acquired_trade_date", "2026-09-10"),
        ("remaining_qty", 8),
    ],
)
def test_reduction_preserves_immutable_fields_and_exact_delta(field, value):
    invalid(
        arguments(
            before=snapshot(),
            after=snapshot(remaining_qty=7, **{field: value})
            if field != "remaining_qty"
            else snapshot(remaining_qty=value),
            quantity=7,
            effective="2026-09-14",
        )
    )


@pytest.mark.parametrize(
    "before,after,quantity,effective",
    [
        (snapshot(), snapshot(remaining_qty=7), 7, "2026-09-11"),
        (snapshot(), snapshot(remaining_qty=7), 7, "2026-09-10"),
        (snapshot(), snapshot(remaining_qty=0), 14, "2026-09-14"),
        (snapshot(), snapshot(remaining_qty=0, closed_at="2026-09-22T10:30:00"), 14, "2026-09-14"),
        (
            snapshot(closed_at="2026-09-22T10:30:00+08:00"),
            snapshot(remaining_qty=7),
            7,
            "2026-09-14",
        ),
        (
            snapshot(remaining_qty=0, closed_at="2026-09-22T10:30:00+08:00"),
            snapshot(remaining_qty=0, closed_at="2026-09-22T10:30:00+08:00"),
            7,
            "2026-09-14",
        ),
    ],
)
def test_reduction_state_and_t1_invariants(before, after, quantity, effective):
    invalid(arguments(before=before, after=after, quantity=quantity, effective=effective))


@pytest.mark.parametrize("path", [(), ("recoveryEvidence",), ("recoveryEvidence", "after")])
@pytest.mark.parametrize("extra", [True, False])
def test_exact_object_fields(path, extra):
    args = arguments()
    data = json.loads(args["details_json"])
    target = data
    for key in path:
        target = target[key]
    if extra:
        target["unexpected"] = 1
    else:
        target.pop(next(iter(target)))
    invalid(args | {"details_json": json.dumps(data)})


@pytest.mark.parametrize(
    "raw",
    [
        None,
        b"{}",
        [],
        "null",
        "[]",
        "{",
        "NaN",
        '{"x":Infinity}',
        '{"x":-Infinity}',
        "[" * 2000 + "]" * 2000,
        '"\\ud800"',
    ],
)
def test_malformed_json_and_non_text(raw):
    invalid(arguments() | {"details_json": raw})


@pytest.mark.parametrize(
    "fragment", ['"quantity": 14', '"schemaVersion": 1', '"remaining_qty": 14']
)
def test_duplicate_keys_at_every_depth(fragment):
    args = arguments()
    invalid(
        args | {"details_json": args["details_json"].replace(fragment, fragment + ", " + fragment)}
    )


def test_payload_limit_is_utf8_bytes_before_json_parse(monkeypatch):
    args = arguments()
    raw = args["details_json"]
    assert isinstance(
        decode_position_lot_mutation(
            **(args | {"details_json": raw + " " * (16384 - len(raw.encode()))})
        ),
        ValidatedLotMutation,
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("oversized/nontext input reached JSON parsing")

    monkeypatch.setattr("trade_plan_monitor.state.position_lot_evidence.json.loads", forbidden)
    for raw in (" " * 16385, "中" * 5462, b"{}", "\ud800"):
        invalid(args | {"details_json": raw})


def test_legacy_missing_and_unsupported_version_are_distinct():
    args = arguments()
    legacy = json.loads(args["details_json"])
    legacy.pop("recoveryEvidence")
    result = decode_position_lot_mutation(**(args | {"details_json": json.dumps(legacy)}))
    assert result.reason is LotMutationUnknownReason.MISSING_EVIDENCE
    for version in (0, 2, -1):
        result = decode_position_lot_mutation(
            **replace_detail(args, ("recoveryEvidence", "schemaVersion"), version)
        )
        assert result.reason is LotMutationUnknownReason.UNSUPPORTED_VERSION
    with pytest.raises(FrozenInstanceError):
        result.reason = LotMutationUnknownReason.INVALID_EVIDENCE


def test_calendar_boundary_is_date_relation_only():
    before = snapshot(acquired_trade_date="2024-02-29")
    after = before | {"remaining_qty": 7}
    result = decode_position_lot_mutation(
        **arguments(before=before, after=after, quantity=7, effective="2024-03-01")
    )
    assert isinstance(result, ValidatedLotMutation)


@pytest.mark.parametrize("length", [64, 128])
def test_writer_compatible_long_lot_identifiers(length):
    assert isinstance(
        decode_position_lot_mutation(**arguments(after=snapshot(id="x" * length))),
        ValidatedLotMutation,
    )


@pytest.mark.parametrize("timestamp", ["2026-09-22T02:30:00Z", "2026-09-22T02:30:00.123456+00:00"])
def test_utc_json_timestamp_preserves_existing_hash_representation(timestamp):
    args = arguments(
        before=snapshot(),
        after=snapshot(remaining_qty=0, closed_at=timestamp),
        quantity=14,
        effective="2026-09-14",
    )
    assert isinstance(decode_position_lot_mutation(**args), ValidatedLotMutation)


@pytest.mark.parametrize(
    "timestamp",
    ["2026-09-22 10:30:00+08:00", "2026-09-22x10:30:00+08:00", "20260922T10:30:00+08:00"],
)
def test_timestamp_must_use_existing_iso_representation(timestamp):
    invalid(arguments() | {"created_at": timestamp})


@pytest.mark.parametrize(
    "field,value",
    [("before_hash", None), ("before_hash", "0" * 64), ("action", "POSITION_BUY_RECORDED")],
)
def test_reduction_requires_matching_before_hash_and_action(field, value):
    invalid(
        arguments(
            before=snapshot(), after=snapshot(remaining_qty=7), quantity=7, effective="2026-09-14"
        )
        | {field: value}
    )


def test_same_instant_different_offset_cannot_borrow_the_original_hash():
    args = arguments(
        before=snapshot(),
        after=snapshot(remaining_qty=0, closed_at="2026-09-22T10:30:00+08:00"),
        quantity=14,
        effective="2026-09-14",
    )
    invalid(
        replace_detail(
            args, ("recoveryEvidence", "after", "closed_at"), "2026-09-22T02:30:00+00:00"
        )
    )


@pytest.mark.parametrize("field,value", [("quantity", True), ("symbol", "bad"), ("bucket", "bad")])
def test_malformed_legacy_details_do_not_report_merely_missing_evidence(field, value):
    args = arguments()
    data = json.loads(args["details_json"])
    data.pop("recoveryEvidence")
    data[field] = value
    invalid(args | {"details_json": json.dumps(data)})
