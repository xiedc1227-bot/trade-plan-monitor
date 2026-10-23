"""Contracts for the isolated validator/scan experiment."""

import json
from dataclasses import replace

import pytest
import test_global_evidence_admission as reference
from scripts.experiments.global_evidence_budget import Budget, BudgetUnavailable
from scripts.experiments.validator_scan import LimitedScan, ScanGate, latest

from trade_plan_monitor.state.projections import ProjectionError, _latest_index_records


def test_full_equivalence():
    rows = reference.inputs()
    assert latest(iter(rows), reference.DASHBOARD_INDEX_CODES) == _latest_index_records(
        iter(rows), reference.DASHBOARD_INDEX_CODES
    )


@pytest.mark.parametrize(
    "field",
    [
        "bar_set_hash",
        "request_set_hash",
        "snapshot_hash",
        "formula_definition_hash",
        "display_name",
        "observed_at",
    ],
)
def test_hash_or_scalar_tamper(field):
    rows = list(reference.inputs())
    payload = list(rows[0].payload)
    value = json.loads(payload[9])
    value[field] = value[field] + 1 if type(value[field]) is int else "changed"
    payload[9] = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    rows[0] = replace(rows[0], payload=tuple(payload))
    for verify in (latest, _latest_index_records):
        with pytest.raises(ProjectionError):
            verify(iter(rows), reference.DASHBOARD_INDEX_CODES)


@pytest.mark.parametrize("damage", ["space", "invalid", "blob", "missing", "head"])
def test_literal_rejection(damage):
    rows = list(reference.inputs())
    payload = list(rows[0].payload)
    if damage == "missing":
        rows[0] = replace(rows[0], payload=None)
    elif damage == "head":
        head = list(rows[0].head)
        head[4] += 1
        rows[0] = replace(rows[0], head=tuple(head))
    else:
        payload[9] = (
            payload[9] + b" "
            if damage == "space"
            else b"\xff"
            if damage == "invalid"
            else payload[9]
        )
        rows[0] = replace(rows[0], payload=tuple(payload), json_is_text=damage != "blob")
    for verify in (latest, _latest_index_records):
        with pytest.raises((ProjectionError, UnicodeError)):
            verify(iter(rows), reference.DASHBOARD_INDEX_CODES)


@pytest.mark.parametrize("slots", [1, 2])
def test_funded_cohort_without_permit_deadlock(tmp_path, monkeypatch, slots):
    import test_evidence_representation as cohort

    gate = ScanGate(slots)

    class Scanner(LimitedScan):
        def __init__(self, *a, **kw):
            super().__init__(*a, gate=gate, **kw)

    monkeypatch.setattr(cohort, "OrderedScan", Scanner)
    cohort.test_funded_collection_cohort_precedes_fast_proof(tmp_path)
    assert gate.active == 0 and not gate.queue


@pytest.mark.parametrize(
    "case",
    [
        "test_real_scan_is_literal_and_query_requires_live_lease",
        "test_expired_or_cancelled_reader_does_not_execute_payload",
        "test_actual_valid_large_row_exposes_availability_gate",
        "test_changed_snapshot_releases_comparison_and_revalidates",
        "test_observer_cancellation_keeps_physical_lease_and_storage_fence",
        "test_child_cleanup_debt_is_not_refunded_by_global_ledger",
    ],
)
def test_scan_contract(tmp_path, monkeypatch, case):
    monkeypatch.setattr(reference, "Scan", LimitedScan)
    getattr(reference, case)(tmp_path)


def test_cleanup_failure_retains_debt(tmp_path, monkeypatch):
    import test_evidence_representation as cohort

    cohort.test_failed_cursor_cleanup_keeps_budget(tmp_path, monkeypatch, LimitedScan)


@pytest.mark.parametrize("reason", ["cancel", "deadline", "stop"])
def test_waiter_revoked(reason):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from time import monotonic

    gate, budget = ScanGate(1), Budget()

    class Reader:
        cancelled = Event()
        deadline = monotonic() + 10

        def check(self):
            if self.cancelled.is_set() or monotonic() >= self.deadline:
                raise BudgetUnavailable("revoked")

    reader = Reader()
    reader.budget = budget
    with gate.enter(reader), ThreadPoolExecutor(1) as pool:
        future = pool.submit(lambda: enter_waiter(gate, reader))
        with gate.condition:
            assert gate.condition.wait_for(lambda: len(gate.queue) == 1, 2)
        if reason == "cancel":
            reader.cancelled.set()
        elif reason == "deadline":
            reader.deadline = 0
        else:
            budget.stop()
        with pytest.raises(BudgetUnavailable):
            future.result(timeout=2)
    assert gate.active == 0 and not gate.queue


def enter_waiter(gate, reader):
    with gate.enter(reader):
        raise AssertionError("revoked waiter entered")


@pytest.mark.parametrize("column", range(19))
def test_every_selected_scalar_is_checked(column):
    row = reference.inputs(1)[0]
    fields = list(row.head if column < 7 else row.payload)
    offset = column if column < 7 else column - 7
    original = fields[offset]
    fields[offset] = (
        original + 1
        if type(original) is int
        else (original + b" " if type(original) is bytes else original + "x")
    )
    row = replace(row, **{"head" if column < 7 else "payload": tuple(fields)})
    # updated_at is intentionally not a model identity field in the reference.
    # Require identical acceptance, including that legacy boundary.
    outcomes = []
    for verify in (latest, _latest_index_records):
        try:
            outcomes.append(verify(iter((row,)), reference.DASHBOARD_INDEX_CODES))
        except ProjectionError:
            outcomes.append(None)
    assert outcomes[0] == outcomes[1]


def test_canonical_emitter_preserves_unicode_escapes_and_eof():
    from hashlib import sha256

    from scripts.experiments.validator_scan import digest, literal_equal, pieces

    from trade_plan_monitor.market_index.canonical import _encode_canonical_value

    value = {"中文😀": ['\\"\n\x00', "x" * 20000, None, True, -5]}
    raw = _encode_canonical_value(value).encode("utf-8")
    assert b"".join(pieces(value)) == raw
    assert digest(b"domain\0", value) == sha256(b"domain\0" + raw).hexdigest()
    assert literal_equal(value, raw)
    assert not literal_equal(value, raw + b" ")
    assert not literal_equal(value, raw[:-1])


def test_permit_bound_and_storage_stop_while_active():
    from threading import Event
    from time import monotonic

    gate, budget = ScanGate(1), Budget()

    class Reader:
        deadline = monotonic() + 5
        cancelled = Event()

        def check(self):
            pass

    reader = Reader()
    reader.budget = budget
    with gate.enter(reader):
        budget.stop()
        assert gate.active == 1
        with pytest.raises(BudgetUnavailable), gate.enter(reader):
            pass
    assert gate.active == 0 and gate.peak == 1 and not gate.queue


def test_rich_requests_and_rehashed_fact_formula():
    from scripts.experiments.validator_scan import pieces, verified
    from tests.unit import test_single_canonical_verification as contract

    from trade_plan_monitor.market_index import canonical

    snapshot = contract.snapshot.__wrapped__()
    assert b"".join(pieces(verified(snapshot))).decode() == (
        canonical.verified_market_index_snapshot_json(snapshot)
    )
    for field in ("bar_set_hash", "request_set_hash", "snapshot_hash", "formula_definition_hash"):
        with pytest.raises(ValueError):
            verified(snapshot.model_copy(update={field: "0" * 64}))
    fact = snapshot.indicator_facts[0].model_copy(update={"formula_definition_hash": "f" * 64})
    payload = snapshot.model_dump(mode="python", round_trip=True, exclude={"snapshot_hash"})
    payload["indicator_facts"] = (fact, *snapshot.indicator_facts[1:])
    changed = snapshot.model_copy(
        update={
            "indicator_facts": payload["indicator_facts"],
            "snapshot_hash": canonical.market_index_snapshot_hash(payload),
        }
    )
    with pytest.raises(ValueError):
        verified(changed)


@pytest.mark.parametrize("reason", ["cancel", "deadline"])
def test_prepaid_revocation(tmp_path, monkeypatch, reason):
    import test_evidence_representation as cohort

    monkeypatch.setattr(cohort, "OrderedScan", LimitedScan)
    cohort.test_prepaid_follower_loses_admission_without_leaking_credit(tmp_path, reason)


def test_permit_waits_until_physical_slot_release():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from time import monotonic

    gate, budget, entered = ScanGate(1), Budget(), Event()

    class Reader:
        deadline = monotonic() + 5

        def check(self):
            pass

    reader = Reader()
    reader.budget = budget

    def waiter():
        with gate.enter(reader):
            entered.set()

    with ThreadPoolExecutor(1) as pool:
        with gate.enter(reader):
            future = pool.submit(waiter)
            with gate.condition:
                assert gate.condition.wait_for(lambda: len(gate.queue) == 1, 2)
            assert not entered.is_set() and gate.active == 1
        future.result(timeout=2)
    assert entered.is_set() and gate.active == 0 and gate.peak == 1


@pytest.mark.parametrize("field", ["bar_set_hash", "request_set_hash", "formula_definition_hash"])
def test_rehashed_domain_tamper_still_rejected(field):
    from scripts.experiments.validator_scan import verified
    from tests.unit import test_single_canonical_verification as contract

    from trade_plan_monitor.market_index import canonical

    snapshot = contract.snapshot.__wrapped__()
    payload = snapshot.model_dump(mode="python", round_trip=True, exclude={"snapshot_hash"})
    payload[field] = "0" * 64
    changed = snapshot.model_copy(
        update={
            field: payload[field],
            "snapshot_hash": canonical.market_index_snapshot_hash(payload),
        }
    )
    for verify in (verified, canonical.verified_market_index_snapshot_json):
        with pytest.raises(ValueError):
            verify(changed)
