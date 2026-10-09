"""Latest thirty is one total cap; owned copies and unfinished work stay safe."""

import sqlite3
from datetime import datetime, timedelta

import pytest
from tests.integration.test_backtest_results import _detail, _fill, _materialize, _summary
from tests.integration.test_monitor_loop_publication import publication_case

from trade_plan_monitor.backtest.jobs.maintenance import BacktestJobMaintenance
from trade_plan_monitor.backtest.jobs.models import BacktestRunJobResult, MonitorLoopJobRequest
from trade_plan_monitor.backtest.jobs.repository import BacktestJobRepository
from trade_plan_monitor.backtest.loop_publication import stage_loop_report
from trade_plan_monitor.backtest.results import BacktestDetailKind, BacktestResultStore
from trade_plan_monitor.backtest.time import SHANGHAI


def drain(maintenance, now, budget=3):
    total = 0
    for _ in range(1000):
        result = maintenance.prune(as_of=now, batch_size=budget)
        assert result.deleted_count <= budget
        total += result.deleted_count
        if not result.has_more:
            return total
    pytest.fail("bounded cleanup did not finish")


def test_total_cap_deletes_oldest_pinned_runs_and_their_fills_in_bounded_passes(tmp_path):
    repository = BacktestJobRepository(tmp_path / "results.sqlite3")
    store = BacktestResultStore(repository.database_path)
    now = datetime.now(SHANGHAI)
    summaries = []
    for index in range(33):
        summary = _summary(
            f"run-{index}", completed_at=now - timedelta(hours=33 - index), pinned=index == 0
        )
        _materialize(
            store,
            summary,
            fills=(_fill(summary),),
            details=(_detail(summary, BacktestDetailKind.DECISION),),
        )
        summaries.append(summary)
    maintenance = BacktestJobMaintenance(repository=repository, results=store)
    assert drain(maintenance, now) == 9
    assert store.statistics().run_count == store.statistics().fill_count == 30
    assert store.statistics().detail_count == 30
    assert all(store.get_run(summary.run_id) is None for summary in summaries[:3])
    assert all(store.get_run(summary.run_id) == summary for summary in summaries[3:])


def test_ties_use_run_identity_and_mixed_offsets_compare_absolute_publication_time(tmp_path):
    repository = BacktestJobRepository(tmp_path / "results.sqlite3")
    store = BacktestResultStore(repository.database_path)
    now = datetime.now(SHANGHAI)
    summaries = [_summary(f"tie-{index}", completed_at=now) for index in range(31)]
    for summary in summaries:
        _materialize(store, summary)
    with sqlite3.connect(store.database_path) as connection:
        # Same instant in both canonical envelope timezones; microseconds remain significant.
        connection.execute(
            "UPDATE backtest_run SET created_at = ? WHERE run_id = ?",
            (now.isoformat(timespec="microseconds"), max(s.run_id for s in summaries)),
        )
    drain(BacktestJobMaintenance(repository=repository, results=store), now)
    assert {s.run_id for s in store.list_runs(limit=100)} == set(
        sorted(s.run_id for s in summaries)[1:]
    )


@pytest.mark.parametrize("state", ["QUEUED", "RUNNING", "CANCEL_REQUESTED", "RESERVATION"])
def test_copy_cleanup_does_not_race_unfinished_job_or_submission(tmp_path, state):
    store, reference, report, events = publication_case(tmp_path)
    repository = BacktestJobRepository(store.database_path)
    if state == "RESERVATION":
        repository.claim_run_submission('{"synthetic":"one"}', "reservation")
    else:
        receipt = repository.submit(MonitorLoopJobRequest(input_reference=reference), "one")
        if state != "QUEUED":
            repository.claim_next()
        if state == "CANCEL_REQUESTED":
            repository.request_cancel(receipt.job_id, "cancel")
    orphan = store.loop_input_store.root / ("day-" + "f" * 64 + ".json")
    orphan.write_bytes(b"synthetic orphan")
    maintenance = BacktestJobMaintenance(repository=repository, results=store)
    result = maintenance.prune(as_of=datetime.now(SHANGHAI) + timedelta(days=30), batch_size=1000)
    assert orphan.exists()
    assert store.get_loop_input(reference).run_input.run_id == reference.run_id
    assert result.deleted_count == 0


def test_owned_cleanup_removes_orphans_but_preserves_retained_report_and_shared_day(tmp_path):
    store, reference, report, events = publication_case(tmp_path)
    repository = BacktestJobRepository(store.database_path)
    repository.submit(MonitorLoopJobRequest(input_reference=reference), "one")
    claim = repository.claim_next()
    stage_loop_report(store, reference=reference, report=report, events=events)
    assert repository.complete(
        claim.job_id,
        claim.claim_token.get_secret_value(),
        BacktestRunJobResult(run_id=reference.run_id, report_hash=report.report_hash, reused=False),
    )
    root = store.loop_input_store.root
    unowned = root / "leave-me.json"
    unowned.write_bytes(b"outside object family")
    for index in range(7):
        (root / ("day-" + f"{index:064x}" + ".json")).write_bytes(b"synthetic orphan")
    before = store.get_loop_report(reference.run_id)
    assert (
        drain(
            BacktestJobMaintenance(repository=repository, results=store), datetime.now(SHANGHAI), 2
        )
        == 7
    )
    assert unowned.read_bytes() == b"outside object family"
    assert store.get_loop_report(reference.run_id) == before
    assert store.get_loop_input(reference).dataset.dataset_hash == reference.dataset_hash


def test_excess_loop_run_releases_its_report_and_input_objects_after_existing_grace(tmp_path):
    store, reference, report, events = publication_case(tmp_path)
    repository = BacktestJobRepository(store.database_path)
    repository.submit(MonitorLoopJobRequest(input_reference=reference), "one")
    claim = repository.claim_next()
    stage_loop_report(store, reference=reference, report=report, events=events)
    assert repository.complete(
        claim.job_id,
        claim.claim_token.get_secret_value(),
        BacktestRunJobResult(run_id=reference.run_id, report_hash=report.report_hash, reused=False),
    )
    now = datetime.now(SHANGHAI)
    stored = store.get_loop_input(reference)
    for index in range(31):
        _materialize(store, _summary(f"newer-{index}", completed_at=now + timedelta(minutes=index)))
    maintenance = BacktestJobMaintenance(repository=repository, results=store)
    drain(maintenance, now + timedelta(days=16), 7)
    assert store.statistics().run_count == 30
    assert store.get_loop_report(reference.run_id) is None
    assert not store.loop_input_store.bundle_path(reference).exists()
    assert not store.loop_input_store.report_path(report.report_hash).exists()
    assert all(not store.loop_input_store.day_path(value).exists() for value in stored.day_hashes)
    assert (store.loop_input_store.root / "owner.json").exists()
