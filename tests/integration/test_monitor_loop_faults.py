"""Actual transaction boundaries and worker failures retain single-task authority."""

import pytest
from sqlalchemy import select
from tests.integration.test_monitor_loop_account import command, funded
from tests.integration.test_monitor_loop_publication import publication_case
from tests.integration.test_monitor_loop_worker import worker_case
from tests.integration.test_unified_simulation_transactions import ledger_dump
from tests.unit.test_monitor_loop_schedule import calendar

from trade_plan_monitor.backtest import application, loop_replay
from trade_plan_monitor.backtest.control import CancellationToken
from trade_plan_monitor.backtest.jobs import repository as job_module
from trade_plan_monitor.backtest.jobs.models import BacktestRunJobResult, MonitorLoopJobRequest
from trade_plan_monitor.backtest.jobs.repository import BacktestJobRepository, JobAdmissionError
from trade_plan_monitor.backtest.loop_account import RECEIPT_TABLE
from trade_plan_monitor.backtest.loop_publication import stage_loop_report
from trade_plan_monitor.backtest.loop_session import LoopSession
from trade_plan_monitor.backtest.results import BacktestResultStore
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork


def test_account_commit_failure_rolls_back_entire_ledger_and_retry_commits_once(
    tmp_path, monkeypatch
):
    with LoopSession(tmp_path, funded(), calendar()) as loop:
        offered = command(loop)
        before = ledger_dump(tmp_path / "loop-runtime.sqlite")
        original = SqlAlchemyUnitOfWork.commit

        def fail(work):
            if work.daily.session.scalar(select(RECEIPT_TABLE.c.request_key)) is not None:
                raise RuntimeError("injected account commit failure")
            original(work)

        monkeypatch.setattr(SqlAlchemyUnitOfWork, "commit", fail)
        with pytest.raises(RuntimeError, match="account commit failure"):
            loop.execute(offered, request_key="commit-retry")
        assert ledger_dump(tmp_path / "loop-runtime.sqlite") == before
        with loop.work() as work:
            assert work.daily.get(offered.cause_id)["payload"]["state"] == "READY"
        monkeypatch.setattr(SqlAlchemyUnitOfWork, "commit", original)
        receipt = loop.execute(offered, request_key="commit-retry")
        assert receipt.account.cash.balance_fen == 102396
        assert loop.execute(offered, request_key="commit-retry") == receipt
        assert loop.account() == receipt.account


@pytest.mark.parametrize("boundary", ["materialized", "job_updated"])
def test_publication_late_failure_rolls_back_result_and_job_then_allows_same_claim_retry(
    tmp_path, monkeypatch, boundary
):
    store, reference, report, events = publication_case(tmp_path)
    repository = BacktestJobRepository(store.database_path)
    repository.submit(MonitorLoopJobRequest(input_reference=reference), "run")
    claim = repository.claim_next()
    stage_loop_report(store, reference=reference, report=report, events=events)
    result = BacktestRunJobResult(
        run_id=reference.run_id, report_hash=report.report_hash, reused=False
    )
    before = ledger_dump(store.database_path)
    if boundary == "materialized":
        target, name = BacktestResultStore, "materialize_verified_publication"
    else:
        target, name = job_module, "_expire_job_idempotency"
    original = getattr(target, name)

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected publication commit failure")

    monkeypatch.setattr(target, name, fail)
    with pytest.raises(RuntimeError, match="publication commit failure"):
        repository.complete(claim.job_id, claim.claim_token.get_secret_value(), result)
    assert ledger_dump(store.database_path) == before
    assert store.get_run(reference.run_id) is None
    assert repository.get(claim.job_id).status.value == "RUNNING"
    with pytest.raises(JobAdmissionError, match="unfinished"):
        repository.claim_run_submission('{"new":"work"}', "other")
    monkeypatch.setattr(target, name, original)
    assert repository.complete(claim.job_id, claim.claim_token.get_secret_value(), result)
    assert store.get_loop_report(reference.run_id) == report


def test_native_worker_fault_cleans_private_state_and_retry_calls_no_external_service(
    tmp_path, monkeypatch
):
    import httpx

    from trade_plan_monitor.ai.openai_compatible import OpenAICompatibleProvider
    from trade_plan_monitor.notifications.dispatcher import NotificationDispatcher

    store, reference, operations, repository, _ = worker_case(tmp_path)
    calls = {"configuration": 0, "market": 0, "ai": 0, "notifications": 0, "http": 0}

    def guard(name):
        def forbidden(*args, **kwargs):
            calls[name] += 1
            raise AssertionError(f"native replay called {name}")

        return forbidden

    for target, name, kind in (
        (application, "load_application_config", "configuration"),
        (application, "create_tushare_client", "market"),
        (OpenAICompatibleProvider, "extract_plan", "ai"),
        (NotificationDispatcher, "dispatch_pending", "notifications"),
        (NotificationDispatcher, "dispatch_event", "notifications"),
        (httpx.Client, "request", "http"),
        (httpx.AsyncClient, "request", "http"),
    ):
        monkeypatch.setattr(target, name, guard(kind))
    claim = repository.claim_next()
    original = loop_replay.LoopRunner.run

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected worker handoff failure")

    monkeypatch.setattr(loop_replay.LoopRunner, "run", fail)
    with pytest.raises(RuntimeError, match="worker handoff failure"):
        operations.execute(
            claim, cancellation_token=CancellationToken(), progress_callback=lambda _: None
        )
    assert store.get_run(reference.run_id, include_unmaterialized=True) is None
    assert not tuple(tmp_path.glob(".loop-worker-*"))
    assert repository.get(claim.job_id).status.value == "RUNNING"
    with pytest.raises(JobAdmissionError, match="unfinished"):
        repository.claim_run_submission('{"new":"work"}', "other")
    monkeypatch.setattr(loop_replay.LoopRunner, "run", original)
    result = operations.execute(
        claim, cancellation_token=CancellationToken(), progress_callback=lambda _: None
    )
    assert repository.complete(claim.job_id, claim.claim_token.get_secret_value(), result)
    assert store.get_loop_report(reference.run_id).cycle.fills == 1
    assert not tuple(tmp_path.glob(".loop-worker-*"))
    assert calls == {name: 0 for name in calls}
