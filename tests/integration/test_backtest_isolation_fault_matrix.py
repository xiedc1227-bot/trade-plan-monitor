"""Windows offline public boundaries; no provider configuration or user stores."""

import asyncio
import json
from functools import partial
from pathlib import Path
from threading import Event
from threading import enumerate as threads
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient
from tests.integration.test_backtest_thread_recovery import request
from tests.integration.test_monitor_loop_production_composition import (
    NOW,
    ORIGIN,
    environment,
    post,
    wait,
)

from trade_plan_monitor.backtest.jobs.repository import BacktestJobRepository
from trade_plan_monitor.backtest.service_config import BacktestServiceConfig
from trade_plan_monitor.backtest.service_lifecycle import LazyBacktestLifecycle

FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures/monitor-loop/isolation.json").read_text()
)


def owned_threads():
    return {thread.ident for thread in threads() if thread.name.startswith("backtest-")}


def test_public_dormant_monitor_schema_status_and_unused_stop_create_no_work(tmp_path, monkeypatch):
    app, ai, runtime, calls = environment(tmp_path, monkeypatch)
    before_threads = owned_threads()
    files = {path.name: path.stat().st_mtime_ns for path in tmp_path.iterdir()}
    with TestClient(app, base_url=ORIGIN) as client:
        for _ in range(10):
            assert client.get("/api/v1/backtest-service").json()["state"] == "NOT_INITIALIZED"
            assert client.get("/api/v1/plan-versions").status_code == 200
            assert client.get("/openapi.json").status_code == 200
        assert calls["factory"] == 0 and not ai.calls
        assert owned_threads() == before_threads
        assert {path.name: path.stat().st_mtime_ns for path in tmp_path.iterdir()} == files
        value = client.get("/api/v1/backtest-service").json()
        assert (
            post(
                client,
                "/api/v1/backtest-service/stop-requests",
                {
                    "epoch": value["epoch"],
                    "expectedRevision": value["revision"],
                },
                "unused-stop",
            ).status_code
            == 202
        )
        wait(client, "/api/v1/backtest-service", lambda value: value["state"] == "STOPPED")
        assert not runtime.stopped
    assert calls["factory"] == 0 and runtime.stopped
    assert owned_threads() == before_threads


def test_concurrent_real_metadata_and_history_never_authorize_backlog(tmp_path, monkeypatch):
    app, ai, runtime, calls = environment(tmp_path, monkeypatch)
    repository = BacktestJobRepository(tmp_path / "results.sqlite3", clock=lambda: NOW)
    old = repository.submit(request(), "old", request_id="1" * 32)
    with TestClient(app, base_url=ORIGIN) as client:
        manager = app.state.backtest_lifecycle

        async def first_use():
            values = await asyncio.gather(*(manager.ensure() for _ in range(20)))
            assert all(value is values[0] for value in values)

        client.portal.call(first_use)
        assert calls["factory"] == 1
        assert client.get("/api/v1/backtest-jobs/" + old.job_id).json()["status"] == "QUEUED"
        assert client.get("/api/v1/backtest-runs").json()["items"] == []
        assert client.get("/api/v1/backtest-service").json()["authorizedJobIds"] == []
        client.portal.call(partial(manager.ensure, execution=True))
        sleep(0.1)
        assert repository.get(old.job_id).status.value == "QUEUED"
        value = client.get("/api/v1/backtest-service").json()
        assert (
            post(
                client,
                "/api/v1/backtest-service/recovery-requests",
                {
                    "epoch": value["epoch"],
                    "expectedRevision": value["revision"],
                    "action": "RESUME_JOBS",
                    "resumeJobIds": [old.job_id],
                },
                "selected",
            ).status_code
            == 202
        )
        terminal = wait(
            client,
            "/api/v1/backtest-jobs/" + old.job_id,
            lambda row: row["status"] in {"COMPLETED", "FAILED"},
        )
        assert terminal["status"] == "FAILED"  # Real adapter has no external provider config.
        assert len(repository.list_jobs()) == 1 and not ai.calls and not runtime.stopped
        assert len(owned_threads()) <= FIXTURE["maximum_backtest_threads"]
    assert runtime.stopped


def test_four_sequential_public_native_runs_keep_distinct_stored_fill_keys(
    tmp_path,
    monkeypatch,
):
    from scripts.verify_backtest_thread_load import prepare

    app, _ai, runtime, _calls = environment(tmp_path, monkeypatch)
    keys, causes = [], []
    with TestClient(app, base_url=ORIGIN) as client:
        manifest = prepare(client, tmp_path)
        for delay in range(4):
            accepted = post(
                client,
                "/api/v1/backtest-runs",
                {
                    "preparationId": "load",
                    "manifestHash": manifest,
                    "response": {"mode": "FOLLOW_REMINDERS", "responseDelaySeconds": delay},
                    "costs": {
                        "commissionRate": "0.0003",
                        "minimumCommissionFen": 500,
                        "stampDutyRate": "0.0005",
                        "transferFeeRate": "0.00001",
                        "buySlippageFen": 1,
                        "sellSlippageFen": 1,
                    },
                },
                f"sequence-{delay}",
            )
            assert accepted.status_code == 202
            receipt = accepted.json()
            terminal = wait(
                client,
                "/api/v1/backtest-jobs/" + receipt["jobId"],
                lambda row: row["status"] in {"COMPLETED", "FAILED"},
            )
            assert terminal["status"] == "COMPLETED", terminal
            page = client.get("/api/v1/backtest-runs/" + receipt["runId"] + "/fills").json()
            fill = page["items"][0]
            assert fill["fillId"] == fill["receipt"]["authority_receipt"]["simulation_id"]
            keys.append(
                app.state.backtest_lifecycle._instance.read_service._result_store.list_fills(
                    receipt["runId"]
                )[0].fill_id
            )
            causes.append(fill["fillId"])
        assert len(set(keys)) == 4 and len(set(causes)) < 4
        assert not runtime.stopped


@pytest.mark.parametrize("late_failure", [False, True])
def test_late_factory_timeout_stop_and_repair_cannot_replace_owned_work(
    tmp_path,
    monkeypatch,
    late_failure,
):
    app, ai, runtime, calls = environment(tmp_path, monkeypatch)
    entered, release = Event(), Event()
    with TestClient(app, base_url=ORIGIN) as client:
        original = app.state.backtest_lifecycle._factory

        def held():
            entered.set()
            assert release.wait(5)
            if late_failure:
                raise OSError("private late factory defect")
            return original()

        manager = LazyBacktestLifecycle(
            held,
            config=BacktestServiceConfig(
                request_wait_seconds=0.01,
                initialization_watchdog_seconds=0.03,
                shutdown_wait_seconds=0.01,
            ),
        )
        app.state.backtest_lifecycle = manager
        try:
            assert client.get("/api/v1/backtest-datasets").status_code == 503
            assert entered.is_set()
            deadline = monotonic() + 2
            while manager.snapshot.state.value != "DEGRADED":
                assert monotonic() < deadline
                sleep(0.01)
            value = client.get("/api/v1/backtest-service").json()
            assert value["physicallyDrained"] is False
            assert (
                post(
                    client,
                    "/api/v1/backtest-service/recovery-requests",
                    {
                        "epoch": value["epoch"],
                        "expectedRevision": value["revision"],
                        "action": "RETRY_PREPARATION",
                        "resumeJobIds": [],
                    },
                    "forbidden-replacement",
                ).status_code
                == 409
            )
            assert client.get("/api/v1/plan-versions").status_code == 200
            assert not runtime.stopped and not ai.calls
            assert (
                post(
                    client,
                    "/api/v1/backtest-service/stop-requests",
                    {
                        "epoch": value["epoch"],
                        "expectedRevision": value["revision"],
                    },
                    "stop-held",
                ).status_code
                == 202
            )
        finally:
            release.set()
            client.portal.call(manager.wait_for_drain)
        assert manager.snapshot.physically_drained
        assert calls["factory"] == (0 if late_failure else 1)
        assert not runtime.stopped
    assert runtime.stopped


def test_wal_probe_handles_disappearance_but_preserves_real_io_failure(tmp_path):
    from scripts.verify_backtest_thread_load import wal_bytes

    kept = tmp_path / "kept.sqlite3-wal"
    gone = tmp_path / "gone.sqlite3-wal"
    kept.write_bytes(b"remaining WAL")
    gone.write_bytes(b"checkpointed WAL")

    class CheckpointRace:
        def rglob(self, pattern):
            assert pattern == "*-wal"
            paths = (kept, gone)
            gone.unlink()
            return paths

    assert wal_bytes(CheckpointRace()) == len(b"remaining WAL")

    class UnreadablePath:
        def stat(self):
            raise PermissionError("probe must preserve an unreadable file")

    class UnreadableRoot:
        def rglob(self, pattern):
            return (UnreadablePath(),)

    with pytest.raises(PermissionError, match="unreadable"):
        wal_bytes(UnreadableRoot())


def test_real_sqlite_busy_preserves_http_intent_and_nonbusy_error(tmp_path, monkeypatch):
    import sqlite3

    from scripts.verify_backtest_thread_load import prepare

    app, _ai, runtime, _calls = environment(tmp_path, monkeypatch)
    with TestClient(app, base_url=ORIGIN) as client:
        manifest = prepare(client, tmp_path)
        service = app.state.backtest_lifecycle._instance.read_service
        original = service._repository.claim_run_submission
        database = tmp_path / "controlled-lock.sqlite3"
        blocker = sqlite3.connect(database)
        blocker.execute("CREATE TABLE marker (value INTEGER)")
        blocker.commit()
        blocker.execute("BEGIN IMMEDIATE")

        def locked_claim(*args, **kwargs):
            with sqlite3.connect(database, timeout=0.01) as connection:
                connection.execute("BEGIN IMMEDIATE")
            return original(*args, **kwargs)

        monkeypatch.setattr(service._repository, "claim_run_submission", locked_claim)
        body = {
            "preparationId": "load",
            "manifestHash": manifest,
            "response": {"mode": "FOLLOW_REMINDERS", "responseDelaySeconds": 0},
            "costs": {
                "commissionRate": "0.0003",
                "minimumCommissionFen": 500,
                "stampDutyRate": "0.0005",
                "transferFeeRate": "0.00001",
                "buySlippageFen": 1,
                "sellSlippageFen": 1,
            },
        }
        try:
            response = post(client, "/api/v1/backtest-runs", body, "locked-intent")
            assert response.status_code == 503 and response.headers["Retry-After"] == "1"
            assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
            assert "controlled-lock" not in response.text
            assert service._repository.list_jobs() == ()
            assert client.get("/api/v1/plan-versions").status_code == 200 and not runtime.stopped
        finally:
            blocker.rollback()
            blocker.close()
        response = post(client, "/api/v1/backtest-runs", body, "locked-intent")
        assert response.status_code == 202, response.text
        terminal = wait(
            client,
            "/api/v1/backtest-jobs/" + response.json()["jobId"],
            lambda row: row["status"] in {"COMPLETED", "FAILED"},
        )
        assert terminal["status"] == "COMPLETED" and len(service._repository.list_jobs()) == 1

        def wrong_sql():
            with sqlite3.connect(database) as connection:
                connection.execute("SELECT * FROM missing_table")

        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            client.portal.call(partial(service._run_sync, wrong_sql))


@pytest.mark.parametrize("legacy", [False, True])
def test_monitor_transaction_checks_legacy_history_once_without_losing_guard(
    tmp_path, monkeypatch, legacy,
):
    from sqlalchemy import update
    from tests.integration.test_daily_plan_chain import FRIDAY, SYMBOL, Chain

    from trade_plan_monitor.state.daily_accounting import DailyAccounting
    from trade_plan_monitor.state.daily_models import DailyRecord

    chain = Chain(tmp_path)
    with chain.client:
        chain.activate()
        chain.evaluate(series=chain.series(), official=FRIDAY)
        if legacy:
            with chain.plans._unit_of_work() as work:
                row = work.daily.get("evaluation-head-" + SYMBOL)
                payload = row["payload"]
                payload["inventory"]["orders"] = []
                work.daily.session.execute(
                    update(DailyRecord).where(DailyRecord.id == row["id"])
                    .values(payload_json=json.dumps(payload))
                )
                work.commit()
        checked = []
        original = DailyAccounting.legacy_reason

        def observed(accounting, symbol):
            checked.append(symbol)
            return original(accounting, symbol)

        monkeypatch.setattr(DailyAccounting, "legacy_reason", observed)
        result = chain.evaluate(series=chain.series(), official=FRIDAY)
        assert checked == [SYMBOL]
        if legacy:
            assert result.snapshot["status"] == "UNSUPPORTED"
            assert result.snapshot["reason"] == "DAILY_SIMULATION_LEGACY_DATA_UNSUPPORTED"
            assert result.event_ids == ()
        else:
            assert result.snapshot["inventory"]["symbol"] == SYMBOL
            assert result.snapshot.get("status") != "UNSUPPORTED"


def test_load_controller_never_admits_after_nominal_phase_deadline(monkeypatch):
    from scripts import verify_backtest_thread_load as load

    monkeypatch.setattr(load, "monotonic", lambda: 600.0)

    def forbidden(*args, **kwargs):
        raise AssertionError("no new experiment after the measurement deadline")

    monkeypatch.setattr(load, "post", forbidden)
    result = load.replay_load(object(), "manifest", Event(), deadline=600.0)
    assert result["completed_runs"] == 0
    assert result["admission_p95_ms"] is None
