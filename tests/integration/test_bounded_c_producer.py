"""Experiment contracts; no production adapter is installed."""

import json
from threading import Event
from time import monotonic

import pytest
from scripts.experiments.bounded_c_producer import Producer, normalize
from scripts.experiments.global_evidence_budget import Budget, BudgetUnavailable


def test_literal_and_logical_bound():
    value = normalize({"array": ['中文😀\\"\n' * 1000] * 80, "empty": [], "n": None})
    producer = Producer(Budget(), target=65536)
    chunks = list(producer.pieces(value))
    assert (
        b"".join(chunks)
        == json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    )
    assert max(map(len, chunks)) <= 65536
    assert producer.budget.used == 0


@pytest.mark.parametrize("reason", ["cancel", "deadline", "budget"])
def test_rejection_before_encoding(reason):
    cancelled = Event()
    if reason == "cancel":
        cancelled.set()
    producer = Producer(
        Budget(limit=1 if reason == "budget" else 64 * 1024 * 1024),
        cancelled=cancelled,
        deadline=monotonic() - 1 if reason == "deadline" else monotonic() + 15,
    )
    with pytest.raises(BudgetUnavailable):
        list(producer.pieces(normalize({"x": "valid"})))
    assert producer.calls == 0 and producer.budget.used == 0


def test_chunk_keeps_lease_until_consumer_releases():
    producer = Producer(Budget())
    iterator = producer.pieces(normalize({"x": "value"}))
    next(iterator)
    assert producer.budget.used > 0
    iterator.close()
    assert producer.budget.used == 0


@pytest.mark.parametrize("field", range(19))
def test_every_raw_field_differential(field):
    from dataclasses import replace

    import test_global_evidence_admission as reference
    from scripts.experiments.c_validator import latest

    from trade_plan_monitor.state.projections import _latest_index_records

    row = reference.inputs(1)[0]
    original = (row,)
    assert latest(iter(original), reference.DASHBOARD_INDEX_CODES) == (
        _latest_index_records(iter(original), reference.DASHBOARD_INDEX_CODES)
    )
    values = list((*row.head, *row.payload))
    value = values[field]
    values[field] = (
        value + 1 if type(value) is int else value + (b" " if type(value) is bytes else "x")
    )
    changed = replace(row, head=tuple(values[:7]), payload=tuple(values[7:]))

    def outcome(verify):
        try:
            return verify(iter((changed,)), reference.DASHBOARD_INDEX_CODES)
        except Exception as error:
            return type(error)

    assert outcome(latest) == outcome(_latest_index_records)


@pytest.mark.parametrize("field", ["bar_set_hash", "request_set_hash", "formula_definition_hash"])
def test_rehashed_root_cannot_hide_domain_tamper(field):
    from dataclasses import replace

    import test_global_evidence_admission as reference
    from scripts.experiments.c_validator import latest

    from trade_plan_monitor.market_index import canonical
    from trade_plan_monitor.state.index_evidence import HEAD_FIELDS, PAYLOAD_FIELDS
    from trade_plan_monitor.state.projections import ProjectionError

    row = reference.inputs(1)[0]
    value = json.loads(row.payload[9])
    value[field] = "0" * 64
    value["snapshot_hash"] = canonical.market_index_snapshot_hash(
        {k: v for k, v in value.items() if k != "snapshot_hash"}
    )
    # Keep all redundant identities coherent: only the domain check can reject this.
    head = dict(zip(HEAD_FIELDS, row.head, strict=True))
    payload = dict(zip(PAYLOAD_FIELDS, row.payload, strict=True))
    for key in ("snapshot_hash", "request_set_hash", "bar_set_hash", "formula_definition_hash"):
        payload[key] = value[key]
        if key in head:
            head[key] = value[key]
    payload["snapshot_json"] = canonical.canonical_json(value).encode()
    with pytest.raises(ProjectionError):
        latest(
            iter(
                (
                    replace(
                        row,
                        head=tuple(head[k] for k in HEAD_FIELDS),
                        payload=tuple(payload[k] for k in PAYLOAD_FIELDS),
                    ),
                )
            ),
            reference.DASHBOARD_INDEX_CODES,
        )


def test_parallel_producers_do_not_share_context():
    from concurrent.futures import ThreadPoolExecutor

    import test_global_evidence_admission as reference
    from scripts.experiments.c_validator import latest

    rows = reference.inputs(4)
    expected = latest(iter(rows), reference.DASHBOARD_INDEX_CODES)
    budgets = [Budget() for _ in range(8)]
    with ThreadPoolExecutor(8) as pool:
        futures = [
            pool.submit(latest, iter(rows), reference.DASHBOARD_INDEX_CODES, budget=b)
            for b in budgets
        ]
        assert all(f.result(timeout=15) == expected for f in futures)
    assert all(b.used == 0 for b in budgets)


def test_cancel_mid_production_releases_current_buffer():
    cancelled, budget = Event(), Budget()
    producer = Producer(budget, target=65536, cancelled=cancelled)
    iterator = producer.pieces(normalize(["x" * 10000] * 100))
    next(iterator)
    next(iterator)
    cancelled.set()
    with pytest.raises(BudgetUnavailable):
        list(iterator)
    assert budget.used == 0


def test_cleanup_debt_prevents_new_production():
    budget = Budget()
    lease = budget.acquire(100, "driver")

    def fail():
        raise OSError("cursor cleanup failed")

    with pytest.raises(OSError):
        lease.close(fail)
    with pytest.raises(BudgetUnavailable):
        list(Producer(budget).pieces(normalize({"x": 1})))
    assert budget.used == 100 and budget.closing


def test_invalidated_size_fences_and_retains_debt():
    budget = Budget()
    value = normalize({"x": "small"})
    value["x"] = "changed" * 1000
    with pytest.raises(BudgetUnavailable):
        list(Producer(budget).pieces(value))
    assert budget.closing and budget.used > 0


def test_storage_stop_prevents_next_encoding_unit():
    budget = Budget()
    producer = Producer(budget, target=65536)
    iterator = producer.pieces(normalize(["x" * 10000] * 100))
    next(iterator)
    next(iterator)
    calls = producer.calls
    budget.stop()
    with pytest.raises(BudgetUnavailable):
        list(iterator)
    assert producer.calls == calls and budget.used == 0
