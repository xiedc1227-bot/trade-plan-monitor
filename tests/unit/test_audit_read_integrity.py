"""Read diagnostics must retain typed, envelope and whole-stream proof gates."""

from datetime import UTC
from hashlib import sha256

import pytest
from tests.unit.test_monitor_loop_report import state
from tests.unit.test_monitor_loop_schedule import at

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.loop_publication import audit_record, decode_audit_record
from trade_plan_monitor.backtest.loop_report import (
    LoopAuditEvent,
    LoopValuationEvent,
    MonitorLoopReport,
    ScheduledLoopAuditEvent,
    ScheduledMonitorLoopReport,
    project_loop_valuation,
    verify_published_loop_event_set,
)
from trade_plan_monitor.backtest.results import BacktestDetailKind


def trail(scheduled, count=3):
    events = []
    version = 'monitor-loop-event-v2' if scheduled else 'monitor-loop-event-v1'
    for sequence in range(1, count+1):
        values = dict(schema_version=version, run_id='a'*64, sequence=sequence, at=at(),
                      cause_event_id=None, payload=LoopValuationEvent(
                          valuation=project_loop_valuation(state(), at=at())))
        if scheduled:
            values |= dict(version_id=None, authority_id=None)
        causal = {key: value for key, value in values.items() if key != 'run_id'}
        event_id = sha256((version+'\0'+canonical_json(causal)).encode()).hexdigest()
        cls = ScheduledLoopAuditEvent if scheduled else LoopAuditEvent
        events.append(cls(**values, event_id=event_id))
    domain = b'monitor-loop-event-set-v2\0' if scheduled else b'monitor-loop-event-set-v1\0'
    digest = sha256(domain)
    for event in events:
        raw = canonical_json(event).encode()
        digest.update(len(raw).to_bytes(8, 'big'))
        digest.update(raw)
    cls = ScheduledMonitorLoopReport if scheduled else MonitorLoopReport
    # The stream verifier uses only these fields. Production report loading stays validated.
    report = cls.model_construct(
        run_id='a'*64, event_count=count, event_set_hash=digest.hexdigest(),
    )
    return report, events


@pytest.mark.parametrize('scheduled', [False, True])
@pytest.mark.parametrize('count', [0, 1, 3])
def test_public_read_helpers_preserve_both_schemas_and_exact_bytes(scheduled, count):
    report, events = trail(scheduled, count)
    decoded = [decode_audit_record(audit_record(event)) for event in events]
    assert decoded == events
    assert [canonical_json(e) for e in decoded] == [canonical_json(e) for e in events]
    assert verify_published_loop_event_set(report, iter(decoded)) is None


@pytest.mark.parametrize('damage', ['row', 'run', 'kind', 'time', 'event_hash', 'missing',
                                   'extra', 'reordered', 'set_hash'])
@pytest.mark.parametrize('scheduled', [False, True])
def test_damaged_envelopes_and_streams_are_rejected(scheduled, damage):
    report, events = trail(scheduled)
    rows = [audit_record(event) for event in events]
    if damage in {'row', 'run', 'kind', 'time', 'event_hash'}:
        change = {
            'row': {'detail_id': 'different'}, 'run': {'run_id': 'b'*64},
            'kind': {'kind': BacktestDetailKind.DIAGNOSTIC}, 'time': {'event_at': at(20, 11)},
            'event_hash': {'payload': rows[0].payload | {'event_id': '0'*64}},
        }[damage]
        rows[0] = rows[0].model_copy(update=change)
    elif damage == 'missing':
        rows.pop()
    elif damage == 'extra':
        rows.append(rows[-1])
    elif damage == 'reordered':
        rows.reverse()
    elif damage == 'set_hash':
        report = type(report).model_construct(
            run_id=report.run_id, event_count=report.event_count, event_set_hash='0'*64,
        )
    with pytest.raises(ValueError):
        verify_published_loop_event_set(report, (decode_audit_record(row) for row in rows))


@pytest.mark.parametrize('scheduled', [False, True])
def test_typed_hash_and_canonical_time_equality_are_independent_gates(scheduled):
    _, events = trail(scheduled, 1)
    row = audit_record(events[0])
    assert decode_audit_record(row) == events[0]
    for payload in (
        row.payload | {'event_id': '0'*64},
        row.payload | {'at': events[0].at.isoformat(timespec='seconds')},
        row.payload | {'at': events[0].at.astimezone(UTC).isoformat()},
    ):
        with pytest.raises(ValueError):
            decode_audit_record(row.model_copy(update={'payload': payload}))


@pytest.mark.parametrize('damage', ['sequence', 'run', 'count'])
@pytest.mark.parametrize('scheduled', [False, True])
def test_membership_and_count_even_when_stream_digest_is_rehashed(scheduled, damage):
    report, events = trail(scheduled)
    if damage == 'sequence':
        events.reverse()
    digest = sha256(b'monitor-loop-event-set-v2\0' if scheduled
                    else b'monitor-loop-event-set-v1\0')
    for event in events:
        raw = canonical_json(event).encode()
        digest.update(len(raw).to_bytes(8, 'big'))
        digest.update(raw)
    altered = type(report).model_construct(
        run_id='b'*64 if damage == 'run' else report.run_id,
        event_count=report.event_count+1 if damage == 'count' else report.event_count,
        event_set_hash=digest.hexdigest(),
    )
    with pytest.raises(ValueError):
        verify_published_loop_event_set(altered, iter(events))
