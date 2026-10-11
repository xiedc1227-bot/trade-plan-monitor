"""Only complete typed trails publish with their frozen input and existing claim token."""

import json
import sqlite3
from datetime import datetime
from hashlib import sha256
from unittest.mock import patch

import pytest
from tests.integration.test_monitor_loop_cycle import frames
from tests.integration.test_monitor_loop_input_store import frozen_case, scheduled_frozen_case
from tests.unit.test_monitor_loop_schedule import at

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.control import BacktestOperationCancelled, CancellationToken
from trade_plan_monitor.backtest.dataset import DatasetScope
from trade_plan_monitor.backtest.jobs.models import BacktestRunJobResult, MonitorLoopJobRequest
from trade_plan_monitor.backtest.jobs.repository import BacktestJobRepository
from trade_plan_monitor.backtest.loop_dataset import LoopDatasetRequest
from trade_plan_monitor.backtest.loop_publication import stage_loop_report
from trade_plan_monitor.backtest.loop_report import (
    LOOP_REPORT_VERSION,
    LoopReportWriter,
    MonitorLoopReport,
)
from trade_plan_monitor.backtest.loop_runner import LoopRunner
from trade_plan_monitor.backtest.loop_session import LoopSession
from trade_plan_monitor.backtest.market_store import BacktestMarketStore
from trade_plan_monitor.backtest.plan_schedule import LoopEndBoundary
from trade_plan_monitor.backtest.results import (
    BacktestResultStore,
    ResultConflictError,
    _content_hash,
    _domain_bytes,
)


def test_scheduled_report_codec_preserves_legacy_type():
    from trade_plan_monitor.backtest.loop_report import (
        ScheduledMonitorLoopReport,
        decode_loop_report,
    )

    assert not issubclass(ScheduledMonitorLoopReport, MonitorLoopReport)
    with pytest.raises(ValueError):
        decode_loop_report('{"schema_version":"unknown"}')


def scheduled_audit_case(directory, *, value=None, observed=None):
    from tests.integration.test_monitor_loop_plan_switch import (
        continuity_calendar,
        continuity_fixture,
        continuity_frames,
        continuity_input,
        observation,
    )

    value = continuity_input() if value is None else value
    if observed is None:
        observed = []
        for boundary in continuity_fixture()["expected"]["version_boundaries"]:
            now = datetime.fromisoformat(boundary["at"])
            observed.extend((observation(now), *continuity_frames(now.date().isoformat())))
    events = []
    with LoopSession(directory, value, continuity_calendar()) as session:
        writer = LoopReportWriter(session, sink=events.append)
        cycle = LoopRunner(session, report_writer=writer).run(observed)
        report = writer.finish(cycle)
    return report, events


@pytest.fixture(scope="module")
def scheduled_audit(tmp_path_factory):
    return scheduled_audit_case(tmp_path_factory.mktemp("scheduled-audit"))


def rehash_scheduled_report(report, **changes):
    from trade_plan_monitor.backtest.loop_report import ScheduledMonitorLoopReport

    values = report.model_dump(mode="python", exclude={"report_hash"}) | changes
    return ScheduledMonitorLoopReport(
        **values,
        report_hash=sha256(("backtest-report-v5\0" + canonical_json(values)).encode()).hexdigest(),
    )


def rehash_scheduled_trail(report, raw_events):
    """Attacker recomputes every event/cause and aggregate hash; semantic checks remain."""
    from trade_plan_monitor.backtest.loop_report import ScheduledLoopAuditEvent

    events, identities = [], {}
    digest = sha256(b"monitor-loop-event-set-v2\0")
    for sequence, original in enumerate(raw_events, 1):
        values = dict(original)
        old_id = values.pop("event_id")
        values["sequence"] = sequence
        values["cause_event_id"] = identities.get(
            values["cause_event_id"], values["cause_event_id"]
        )
        causal = {key: value for key, value in values.items() if key != "run_id"}
        event_id = sha256(("monitor-loop-event-v2\0" + canonical_json(causal)).encode()).hexdigest()
        identities[old_id] = event_id
        event = ScheduledLoopAuditEvent(**values, event_id=event_id)
        raw = canonical_json(event).encode()
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
        events.append(event)
    return rehash_scheduled_report(
        report, event_count=len(events), event_set_hash=digest.hexdigest()
    ), events


def test_scheduled_report_preserves_literal_four_version_account_and_round_trip(scheduled_audit):
    from trade_plan_monitor.backtest.loop_report import (
        decode_loop_event,
        decode_loop_report,
        verify_loop_events,
    )

    report, events = scheduled_audit
    verify_loop_events(report, iter(events))
    assert report.final_account.cash.balance_fen == 1_019_000
    assert report.final_account.lots == ()
    assert report.metrics.realized_pnl_fen == 19_000
    assert report.metrics.paid_fees_fen == 1_000
    assert report.cycle.fills == 2
    assert [item.payload.version_id for item in events if item.payload.kind == "REPLACED"] == [
        "p2",
        "p3",
        "p4",
    ]
    assert decode_loop_report(canonical_json(report)) == report
    assert all(decode_loop_event(canonical_json(event)) == event for event in events)
    with pytest.raises(ValueError):
        MonitorLoopReport.model_validate_json(canonical_json(report))


@pytest.mark.parametrize("tamper", ["authority", "missing_transition"])
def test_scheduled_rehashed_audit_cannot_forge_authority_or_omit_switch(scheduled_audit, tamper):
    from trade_plan_monitor.backtest.loop_report import verify_loop_events

    report, events = scheduled_audit
    values = [item.model_dump(mode="python") for item in events]
    if tamper == "authority":
        target = next(item for item in values if item["payload"]["kind"] == "EVALUATED")
        target["authority_id"] = "f" * 64
    else:
        index = next(
            index for index, item in enumerate(values) if item["payload"]["kind"] == "REPLACED"
        )
        values.pop(index)
    changed, trail = rehash_scheduled_trail(report, values)
    with pytest.raises(ValueError, match="AUTHORITY|TRANSITION"):
        verify_loop_events(changed, iter(trail))


def test_scheduled_expiry_report_finishes_with_no_authority_and_closes_pending(tmp_path):
    from tests.integration.test_monitor_loop_plan_switch import (
        continuity_frames,
        continuity_input,
        observation,
    )
    from tests.unit.test_monitor_loop_schedule import scheduled_row, version

    from trade_plan_monitor.backtest.loop_report import verify_loop_events

    value = continuity_input()
    first = value.schedule.entries[0]
    plan = first.version.snapshot.model_copy(
        update={
            "activation": {
                "mode": "TRADING_DAY",
                "trading_day": first.effective_trade_date,
            }
        }
    )
    value = value.model_copy(
        update={
            "schedule": value.schedule.model_copy(
                update={"entries": (scheduled_row(value=version(plan=plan)),)}
            ),
            "response": value.response.model_copy(update={"response_delay_seconds": 86_400}),
        }
    )
    report, events = scheduled_audit_case(
        tmp_path,
        value=value,
        observed=(
            *continuity_frames("2026-08-20"),
            observation(at(21)),
        ),
    )
    verify_loop_events(report, events)
    (ended,) = [event for event in events if event.payload.kind == "NO_AUTHORITY"]
    assert len(ended.payload.closed_intent_ids) == 1
    assert all(
        event.authority_id is None and event.version_id is None
        for event in events
        if event.at >= ended.at
    )
    assert report.cycle.fills == report.cycle.unfilled_intents == 0
    assert report.final_account.cash.balance_fen == 1_000_000


def test_scheduled_future_context_does_not_change_prior_causal_events(tmp_path):
    from tests.integration.test_monitor_loop_plan_switch import continuity_frames, continuity_input

    value = continuity_input()
    last = value.schedule.entries[-1]
    changed_last = last.model_copy(
        update={
            "version": last.version.model_copy(
                update={
                    "account_context": last.version.account_context.model_copy(
                        update={
                            "tactical_qty": 500,
                            "evidence": "Synthetic changed future holding claim.",
                        }
                    ),
                }
            )
        }
    )
    changed = value.model_copy(
        update={
            "schedule": value.schedule.model_copy(
                update={
                    "entries": (*value.schedule.entries[:-1], changed_last),
                }
            )
        }
    )
    reports = []
    for name, current in (("original", value), ("future", changed)):
        reports.append(
            scheduled_audit_case(
                tmp_path / name, value=current, observed=tuple(continuity_frames("2026-08-20"))
            )
        )
    (first, first_events), (second, second_events) = reports
    assert first.run_id != second.run_id and first.report_hash != second.report_hash
    assert first.final_account == second.final_account
    assert [event.event_id for event in first_events] == [event.event_id for event in second_events]
    assert [event.authority_id for event in first_events] == [
        event.authority_id for event in second_events
    ]


def test_scheduled_rehashed_trail_cannot_skip_intervening_versions(tmp_path):
    from tests.integration.test_monitor_loop_plan_switch import observation

    from trade_plan_monitor.backtest.loop_report import verify_loop_events

    report, events = scheduled_audit_case(tmp_path, observed=(observation(at(25)),))
    values = [
        event.model_dump(mode="python")
        for event in events
        if not (event.payload.kind == "REPLACED" and event.payload.version_id in {"p2", "p3"})
    ]
    for item in values:
        if item["payload"]["kind"] == "REPLACED":
            item["payload"]["from_version_id"] = "p1"
            item["cause_event_id"] = None
    changed, trail = rehash_scheduled_trail(report, values)
    with pytest.raises(ValueError, match="TRANSITION"):
        verify_loop_events(changed, trail)


def test_scheduled_frozen_input_replays_to_one_published_report(tmp_path):
    from trade_plan_monitor.backtest.loop_replay import run_frozen_loop

    _, market, prepared, run_input, dataset = scheduled_frozen_case(tmp_path)
    repository = BacktestJobRepository(tmp_path / "results.sqlite3", clock=lambda: at(26, 16))
    store = BacktestResultStore(repository.database_path)
    reference = store.record_loop_input(
        prepared=prepared,
        run_input=run_input,
        dataset=dataset,
        market_source=market,
    )
    receipt = repository.submit(MonitorLoopJobRequest(input_reference=reference), "scheduled")
    claim = repository.claim_next()
    report = run_frozen_loop(
        store, reference, cancellation_token=CancellationToken(), progress_callback=lambda _: None
    )
    assert report.schema_version == "backtest-report-v5"
    assert report.schedule == prepared.schedule
    assert "plan_hash" not in report.model_dump() and "authority_id" not in report.model_dump()
    from trade_plan_monitor.backtest.loop_publication import validate_report_input

    rows = report.schedule.entries
    foreign_last = rows[-1].model_copy(
        update={
            "version": rows[-1].version.model_copy(update={"version_id": "foreign-version"}),
        }
    )
    foreign = rehash_scheduled_report(
        report,
        schedule=report.schedule.model_copy(
            update={
                "entries": (*rows[:-1], foreign_last),
            }
        ),
    )
    with pytest.raises(ValueError, match="input|schedule"):
        validate_report_input(store.get_loop_input(reference), foreign)
    assert repository.complete(
        claim.job_id,
        claim.claim_token.get_secret_value(),
        BacktestRunJobResult(run_id=reference.run_id, report_hash=report.report_hash, reused=False),
    )
    assert repository.get(receipt.job_id).status.value == "COMPLETED"
    assert BacktestResultStore(store.database_path).get_loop_report(reference.run_id) == report


def publication_case(tmp_path):
    with (
        patch("tests.integration.test_plan_preparation_review.NOW", at(24, 9, 43, 12)),
        patch("tests.integration.test_monitor_loop_input_store.NOW", at(24, 9, 43, 12)),
    ):
        _, original_market, prepared, run_input, dataset = frozen_case(tmp_path)
    market = BacktestMarketStore(tmp_path / "loop-market.sqlite3")
    calendar = original_market.current_trading_day("SZSE", at(24).date())
    market.record_trading_days((calendar,))
    symbol = prepared.version.snapshot.symbol
    source = []
    for frame in frames(day=24):
        minute = frame.minute.model_copy(update={"symbol": symbol})
        limit = frame.daily_limit.model_copy(
            update={"symbol": symbol, "received_at": at(24, 9, 30)}
        )
        runtime = frame.runtime.model_copy(
            update={
                "quote": frame.runtime.quote.model_copy(update={"symbol": symbol}),
                "minute_prefix": tuple(
                    bar.model_copy(update={"symbol": symbol}) for bar in frame.runtime.minute_prefix
                ),
                "five_minute_bars": tuple(
                    bar.model_copy(update={"symbol": symbol})
                    for bar in frame.runtime.five_minute_bars
                ),
                "trading_calendar": (calendar,),
                "session_dates": (calendar.cal_date,),
            }
        )
        source.append(
            frame.model_copy(update={"runtime": runtime, "minute": minute, "daily_limit": limit})
        )
    market.record_completed_loop_minutes(
        tuple(frame.minute for frame in source), historical_profile=dataset.scope.historical_profile
    )
    market.record_daily_limits((source[0].daily_limit,))
    boundary = LoopEndBoundary.resolve(started_at=at(24), submitted_at=at(24, 9, 43, 12))
    frozen = market.freeze_loop_dataset(
        LoopDatasetRequest(
            scope=DatasetScope(
                symbols=(symbol,),
                start=at(24).date(),
                end=at(24).date(),
                warmup_start=at(24).date(),
                historical_profile=dataset.scope.historical_profile,
            ),
            schedule=prepared.schedule,
            boundary=boundary,
        )
    )
    assert frozen.ready
    value = run_input.model_copy(
        update={"dataset_hash": frozen.manifest.dataset_hash, "boundary": boundary}
    )
    BacktestJobRepository(tmp_path / "results.sqlite3")
    store = BacktestResultStore(tmp_path / "results.sqlite3")
    reference = store.record_loop_input(
        prepared=prepared, run_input=value, dataset=frozen.manifest, market_source=market
    )
    events = []
    with LoopSession(tmp_path / "private", value, (calendar,)) as session:
        writer = LoopReportWriter(session, sink=events.append)
        cycle = LoopRunner(session, report_writer=writer).run(source)
        report = writer.finish(cycle)
    assert report.cycle.fills == 1
    return store, reference, report, events


def test_existing_job_token_publishes_frozen_report_and_fill_atomically(tmp_path):
    store, reference, report, events = publication_case(tmp_path)
    repository = BacktestJobRepository(store.database_path)
    receipt = repository.submit(MonitorLoopJobRequest(input_reference=reference), "one")
    claim = repository.claim_next()
    stage_loop_report(store, reference=reference, report=report, events=iter(events))
    assert store.get_run(reference.run_id) is None
    assert repository.complete(
        claim.job_id,
        claim.claim_token.get_secret_value(),
        BacktestRunJobResult(run_id=reference.run_id, report_hash=report.report_hash, reused=False),
    )
    assert repository.get(receipt.job_id).status.value == "COMPLETED"
    assert store.get_loop_report(reference.run_id) == report
    assert len(store.list_details(reference.run_id)) == report.event_count
    assert len(store.list_fills(reference.run_id)) == report.cycle.fills
    assert BacktestResultStore(store.database_path).get_loop_report(reference.run_id) == report


@pytest.mark.parametrize("failure", ["cancel", "write", "missing"])
def test_partial_trail_has_no_completed_result(tmp_path, failure):
    store, reference, report, events = publication_case(tmp_path)
    token = CancellationToken()

    def faulty():
        for index, event in enumerate(events):
            if index == 5:
                if failure == "write":
                    raise OSError("synthetic audit source failure")
                if failure == "cancel":
                    token.cancel()
                if failure == "missing":
                    continue
            yield event

    with pytest.raises((ValueError, OSError, BacktestOperationCancelled)):
        stage_loop_report(
            store, reference=reference, report=report, events=faulty(), cancellation_token=token
        )
    assert store.get_run(reference.run_id) is None
    with pytest.raises((ValueError, RuntimeError)):
        store.verify_job_publication(reference.run_id, expected_report_hash=report.report_hash)


def test_report_with_rehashed_foreign_input_is_rejected_before_staging(tmp_path):
    store, reference, report, events = publication_case(tmp_path)
    values = report.model_dump(mode="python", exclude={"report_hash"}) | {"input_hash": "f" * 64}
    foreign = MonitorLoopReport(
        report_hash=sha256(
            (LOOP_REPORT_VERSION + "\0" + canonical_json(values)).encode()
        ).hexdigest(),
        **values,
    )
    with pytest.raises(ValueError, match="input"):
        stage_loop_report(store, reference=reference, report=foreign, events=iter(events))
    with sqlite3.connect(store.database_path) as connection:
        assert connection.execute("SELECT count(*) FROM backtest_run").fetchone()[0] == 0


def test_stage_revision_and_report_artifact_corruption_prevent_publication(tmp_path):
    store, reference, report, events = publication_case(tmp_path)
    stage_loop_report(store, reference=reference, report=report, events=iter(events))
    proof = store.verify_job_publication(reference.run_id, expected_report_hash=report.report_hash)
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            "DELETE FROM backtest_detail WHERE detail_id = ?",
            (f"loop-{events[-1].sequence:06d}-{reference.run_id[:16]}",),
        )
    with pytest.raises(ResultConflictError):
        store.publish_verified_publication(proof)
    assert store.get_run(reference.run_id) is None
    store.loop_input_store.report_path(report.report_hash).write_bytes(b"damaged")
    with pytest.raises(RuntimeError):
        store.verify_job_publication(reference.run_id, expected_report_hash=report.report_hash)


def test_rehashed_fill_payload_still_has_to_match_typed_audit(tmp_path):
    store, reference, report, events = publication_case(tmp_path)
    stage_loop_report(store, reference=reference, report=report, events=events)
    with sqlite3.connect(store.database_path) as connection:
        domain, raw = connection.execute(
            "SELECT content_domain, payload_json FROM backtest_fill"
        ).fetchone()
        values = json.loads(raw)
        values["payload"]["receipt"]["request_key"] = "synthetic-foreign-request"
        altered = canonical_json(values)
        connection.execute(
            "UPDATE backtest_fill SET payload_json = ?, content_hash = ?",
            (altered, _content_hash(_domain_bytes(domain), altered)),
        )
    with pytest.raises(ValueError, match="fill ledger"):
        store.verify_job_publication(reference.run_id, expected_report_hash=report.report_hash)
    assert store.get_run(reference.run_id) is None


def test_legacy_staged_fill_is_exactly_verified_and_replayed_without_duplicate(tmp_path):
    from trade_plan_monitor.backtest import loop_publication as publication

    store, reference, report, events = publication_case(tmp_path)
    original = publication.fill_record

    def legacy_fill(event):
        fill = original(event)
        if fill is None:
            return None
        return fill.model_copy(
            update={
                "fill_id": event.payload.attempt.receipt.authority_receipt.simulation_id,
            }
        )

    with patch.object(publication, "fill_record", legacy_fill):
        stage_loop_report(store, reference=reference, report=report, events=events)
    stage_loop_report(store, reference=reference, report=report, events=events)
    proof = store.verify_job_publication(reference.run_id, expected_report_hash=report.report_hash)
    store.publish_verified_publication(proof)
    assert len(store.list_fills(reference.run_id)) == 1
    assert store.list_fills(reference.run_id)[0].fill_id == next(
        event.payload.attempt.receipt.authority_receipt.simulation_id
        for event in events
        if event.payload.kind == "EXECUTED" and event.payload.attempt.receipt is not None
    )
