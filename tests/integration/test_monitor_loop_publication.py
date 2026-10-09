"""Only complete typed trails publish with their frozen input and existing claim token."""

import json
import sqlite3
from hashlib import sha256
from unittest.mock import patch

import pytest
from tests.integration.test_monitor_loop_cycle import frames
from tests.integration.test_monitor_loop_input_store import frozen_case
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
        return fill.model_copy(update={
            "fill_id": event.payload.attempt.receipt.authority_receipt.simulation_id,
        })

    with patch.object(publication, "fill_record", legacy_fill):
        stage_loop_report(store, reference=reference, report=report, events=events)
    stage_loop_report(store, reference=reference, report=report, events=events)
    proof = store.verify_job_publication(reference.run_id, expected_report_hash=report.report_hash)
    store.publish_verified_publication(proof)
    assert len(store.list_fills(reference.run_id)) == 1
    assert store.list_fills(reference.run_id)[0].fill_id == next(
        event.payload.attempt.receipt.authority_receipt.simulation_id for event in events
        if event.payload.kind == "EXECUTED" and event.payload.attempt.receipt is not None
    )
