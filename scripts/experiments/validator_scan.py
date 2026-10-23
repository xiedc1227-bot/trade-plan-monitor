"""Isolated P0 only: unchanged model policy, incremental encoding and scan permits.

iterencode tokens are NOT guaranteed bounded. Conservative input admission remains.
No production module imports this file.
"""

import json
from collections import deque
from contextlib import contextmanager
from hashlib import sha256
from threading import Condition
from time import monotonic, perf_counter, thread_time
from types import SimpleNamespace

from scripts.experiments.evidence_representation import OrderedScan
from scripts.experiments.global_evidence_budget import BudgetUnavailable

from trade_plan_monitor.market_index import canonical
from trade_plan_monitor.market_index.models import MarketIndexBar, MarketIndexSnapshot
from trade_plan_monitor.state.index_evidence import HEAD_FIELDS, PAYLOAD_FIELDS
from trade_plan_monitor.state.projections import (
    MarketIndexSnapshotRecord,
    ProjectionError,
    ProjectionMissingDependencyError,
    _market_index_snapshot_rank,
    _market_index_values,
)


def pieces(value):
    encoder = json.JSONEncoder(
        ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    )
    for token in encoder.iterencode(value):
        for offset in range(0, len(token), 8192):
            yield token[offset : offset + 8192].encode("utf-8")


def digest(domain, value):
    hashed = sha256(domain)
    for chunk in pieces(value):
        hashed.update(chunk)
    return hashed.hexdigest()


def verified(snapshot, observe=lambda *args: None):
    if type(snapshot) is not MarketIndexSnapshot:
        raise TypeError("exact snapshot required")
    bars = snapshot.five_minute_bars + snapshot.official_daily_bars
    if type(bars) is not tuple or any(type(bar) is not MarketIndexBar for bar in bars):
        raise TypeError("exact bars required")
    if type(snapshot.fact_requests) is not tuple:
        raise TypeError("exact requests required")
    start, cpu = perf_counter(), thread_time()
    value = canonical.canonical_value(snapshot)
    observe("normalize", perf_counter() - start, thread_time() - cpu)
    start, cpu = perf_counter(), thread_time()
    normalized = value["five_minute_bars"] + value["official_daily_bars"]
    ordered = [
        item
        for _, item in sorted(
            zip(bars, normalized, strict=True),
            key=lambda pair: (pair[0].interval.value, pair[0].bar_at),
        )
    ]
    if snapshot.bar_set_hash != digest(b"market-index-bars-v1\0", ordered):
        raise ValueError("bar hash mismatch")
    requests = sorted(value["fact_requests"], key=canonical._encode_canonical_value)
    if snapshot.request_set_hash != digest(b"market-index-requests-v1\0", requests):
        raise ValueError("request hash mismatch")
    if snapshot.formula_definition_hash != canonical.FORMULA_DEFINITION_HASH:
        raise ValueError("formula hash mismatch")
    if any(
        f.formula_definition_hash != snapshot.formula_definition_hash
        for f in snapshot.indicator_facts
    ):
        raise ValueError("fact formula mismatch")
    if snapshot.snapshot_hash != digest(
        b"market-index-snapshot-v1\0", {k: v for k, v in value.items() if k != "snapshot_hash"}
    ):
        raise ValueError("snapshot hash mismatch")
    observe("encode_hash", perf_counter() - start, thread_time() - cpu)
    return value


def literal_equal(value, raw):
    offset = 0
    for chunk in pieces(value):
        if raw[offset : offset + len(chunk)] != chunk:
            return False
        offset += len(chunk)
    return offset == len(raw)


def record(candidate, observe):
    head = SimpleNamespace(**dict(zip(HEAD_FIELDS, candidate.head, strict=True)))
    if candidate.payload is None:
        raise ProjectionMissingDependencyError("missing immutable snapshot")
    row = SimpleNamespace(**dict(zip(PAYLOAD_FIELDS, candidate.payload, strict=True)))
    try:
        if not candidate.json_is_text or type(row.snapshot_json) is not bytes:
            raise ValueError("stored JSON must be TEXT captured as bytes")
        start, cpu = perf_counter(), thread_time()
        snapshot = MarketIndexSnapshot.model_validate_json(row.snapshot_json)
        observe("parse", perf_counter() - start, thread_time() - cpu)
        value = verified(snapshot, observe)
        start, cpu = perf_counter(), thread_time()
        values = _market_index_values(snapshot, row.provider_content_revision, row.snapshot_json)
        valid = (
            all(getattr(row, name) == expected for name, expected in values.items())
            and literal_equal(value, row.snapshot_json)
            and snapshot.cache_key.provider_content_revision == row.provider_content_revision
        )
        observe("literal", perf_counter() - start, thread_time() - cpu)
        if not valid or (
            snapshot.mapping_version != head.mapping_version
            or snapshot.index_code.value != head.index_code
            or snapshot.decision_cutoff.isoformat() != head.decision_cutoff
            or snapshot.request_set_hash != head.request_set_hash
            or row.provider_content_revision != head.provider_content_revision
        ):
            raise ValueError("literal/scalar/head mismatch")
    except (TypeError, ValueError) as error:
        raise ProjectionError("Stored market-index snapshot is invalid") from error
    return MarketIndexSnapshotRecord(
        snapshot=snapshot, provider_content_revision=row.provider_content_revision
    )


def latest(candidates, codes, observe=lambda *args: None):
    selected = {}
    try:
        for candidate in candidates:
            current = record(candidate, observe)
            previous = selected.get(current.snapshot.index_code)
            if previous is None or _market_index_snapshot_rank(current.snapshot) > (
                _market_index_snapshot_rank(previous.snapshot)
            ):
                selected[current.snapshot.index_code] = current
            del current, previous
    finally:
        close = getattr(candidates, "close", None)
        if close is not None:
            close()
    return tuple(selected[code] for code in codes if code in selected)


class ScanGate:
    """FIFO CPU permits; byte debt is owned by the existing ledger, not this gate."""

    def __init__(self, slots=2):
        if type(slots) is not int or not 1 <= slots <= 8:
            raise ValueError("slots must be in 1..8")
        self.slots, self.active, self.peak = slots, 0, 0
        self.condition, self.queue = Condition(), deque()

    @contextmanager
    def enter(self, scan):
        ticket, granted = object(), False
        with self.condition:
            self.queue.append(ticket)
            self.condition.notify_all()
            try:
                while True:
                    scan.check()
                    if scan.budget.closing:
                        raise BudgetUnavailable("storage admission closed")
                    if self.queue[0] is ticket and self.active < self.slots:
                        self.active += 1
                        self.peak = max(self.peak, self.active)
                        granted = True
                        break
                    self.condition.wait(min(0.025, max(0, scan.deadline - monotonic())))
            finally:
                self.queue.remove(ticket)
                self.condition.notify_all()
        try:
            yield
        finally:
            if granted:
                with self.condition:
                    self.active -= 1
                    self.condition.notify_all()


class LimitedScan(OrderedScan):
    def __init__(self, *args, gate=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.gate = gate if gate is not None else ScanGate()

    @contextmanager
    def cursor(self, query, parameters, lease):
        # All byte leases precede this permit. Never wrap flight/cohort waits.
        start, cpu = perf_counter(), thread_time()
        with self.gate.enter(self):
            self.stats["permitWaitSeconds"] = (
                self.stats.get("permitWaitSeconds", 0) + perf_counter() - start
            )
            opened, used = perf_counter(), thread_time()
            try:
                with super().cursor(query, parameters, lease) as cursor:
                    yield cursor
            finally:
                self.stats["cursorWallSeconds"] = (
                    self.stats.get("cursorWallSeconds", 0) + perf_counter() - opened
                )
                self.stats["cursorCpuSeconds"] = (
                    self.stats.get("cursorCpuSeconds", 0) + thread_time() - used
                )
        self.stats["stageCpuSeconds"] = self.stats.get("stageCpuSeconds", 0) + thread_time() - cpu
