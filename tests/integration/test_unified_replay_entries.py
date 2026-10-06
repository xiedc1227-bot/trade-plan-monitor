"""Real temporary HTTP/job/results entries for reviewed current replay."""

import time
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from tests.integration.test_daily_plan_chain import Chain, OfflineRuntime
from tests.integration.test_unified_replay import fixture

from trade_plan_monitor.backtest.composition import create_backtest_composition_factory
from trade_plan_monitor.web.app import create_app


@pytest.mark.parametrize("cancel", [False, True])
def test_reviewed_inactive_current_api_job_read_export_uses_frozen_input(
    tmp_path, monkeypatch, cancel
):
    store, dataset_hash, plan, frozen = fixture(tmp_path)
    chain = Chain(tmp_path)
    chain.plan = plan
    factory = create_backtest_composition_factory(
        config_path=tmp_path / "absent.yaml",
        plan_snapshot_reader=chain.plans,
        market_database=tmp_path / "market.sqlite",
        results_database=tmp_path / "results.sqlite",
        cursor_key_path=tmp_path / "cursor.key",
    )
    app = create_app(
        runtime_factory=lambda: OfflineRuntime(chain),
        plan_lifecycle_factory=lambda: chain.plans,
        backtest_lifecycle_factory=factory,
    )
    chain.client = TestClient(app, base_url="http://127.0.0.1:8765")
    entered, release = Event(), Event()
    if cancel:
        from trade_plan_monitor.backtest.research_runner import _Replay

        evaluate = _Replay.evaluate

        def pause_after_event(self, *args):
            evaluate(self, *args)
            if not entered.is_set():
                entered.set()
                assert release.wait(10), "test failed to release worker"

        monkeypatch.setattr(_Replay, "evaluate", pause_after_event)
    with chain.client as client:
        saved = chain.activate(review=False)
        base_command = {
            "planVersionId": saved["id"],
            "datasetHash": dataset_hash,
            "initialCashFen": 1_000_000,
            "initialLots": [],
            "eventRiskAssumption": "NO_EVENT_RISK",
            "executionConfig": {
                "commissionRate": "0.0003",
                "minimumCommissionFen": 500,
                "stampDutyRate": "0.0005",
                "transferFeeRate": "0.00001",
                "buySlippageBps": "1",
                "sellSlippageBps": "1",
            },
            "researchInput": frozen.model_dump(mode="json"),
        }
        unreviewed = client.post(
            "/api/v1/backtest-runs", json=base_command, headers={"Idempotency-Key": uuid4().hex}
        )
        assert unreviewed.status_code in {409, 422}, unreviewed.text
        binding = {key: saved[key] for key in ("contentHash", "sourceHash", "reviewEvidenceHash")}
        binding["planVersionId"] = saved["id"]
        reviewed = chain.post("plan-review-confirmations", {**binding, "expectedRevision": 0})
        assert reviewed["canActivate"]
        with chain.plans._unit_of_work() as work:
            assert work.plans.get_active(plan.symbol) is None
        command = {
            "planVersionId": saved["id"],
            "datasetHash": dataset_hash,
            "initialCashFen": 1_000_000,
            "initialLots": [],
            "eventRiskAssumption": "NO_EVENT_RISK",
            "executionConfig": {
                "commissionRate": "0.0003",
                "minimumCommissionFen": 500,
                "stampDutyRate": "0.0005",
                "transferFeeRate": "0.00001",
                "buySlippageBps": "1",
                "sellSlippageBps": "1",
            },
            "researchInput": frozen.model_dump(mode="json"),
        }
        missing = client.post(
            "/api/v1/backtest-runs",
            json={key: value for key, value in command.items() if key != "researchInput"},
            headers={"Idempotency-Key": uuid4().hex},
        )
        assert missing.status_code == 409, missing.text
        wrong = {
            **command,
            "researchInput": {
                **command["researchInput"],
                "review": {**command["researchInput"]["review"], "content_hash": "f" * 64},
            },
        }
        response = client.post(
            "/api/v1/backtest-runs", json=wrong, headers={"Idempotency-Key": uuid4().hex}
        )
        assert response.status_code == 409, response.text
        key = uuid4().hex
        response = client.post(
            "/api/v1/backtest-runs", json=command, headers={"Idempotency-Key": key}
        )
        assert response.status_code == 202, response.text
        job_id = response.json()["jobId"]
        again = client.post("/api/v1/backtest-runs", json=command, headers={"Idempotency-Key": key})
        assert again.status_code == 202, again.text
        assert again.json()["jobId"] == job_id
        if cancel:
            try:
                assert entered.wait(5), "worker did not evaluate a current event"
                cancelled = client.post(
                    "/api/v1/backtest-job-cancellations",
                    json={"jobId": job_id},
                    headers={"Idempotency-Key": uuid4().hex},
                )
                assert cancelled.status_code == 202, cancelled.text
            finally:
                release.set()

        # A worker has frozen the reviewed request; later live plan reads must be unreachable.
        def no_live_lookup(*args, **kwargs):
            raise AssertionError("worker must not reopen live plan authority")

        monkeypatch.setattr(chain.plans, "get_plan_version", no_live_lookup)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            job = client.get(f"/api/v1/backtest-jobs/{job_id}").json()
            if job["status"] not in {"QUEUED", "RUNNING", "CANCEL_REQUESTED"}:
                break
            time.sleep(0.02)
        if cancel:
            assert job["status"] == "CANCELLED", job
            assert job["result"] is None
            assert client.get("/api/v1/backtest-runs").json()["items"] == []
            return
        assert job["status"] == "COMPLETED", job
        run_id = job["result"]["runId"]
        for suffix in ("", "/details?kind=DECISION", "/equity-series"):
            response = client.get(f"/api/v1/backtest-runs/{run_id}{suffix}")
            assert response.status_code == 200, response.text
        detail = client.get(f"/api/v1/backtest-runs/{run_id}/details?kind=DECISION").json()
        assert (
            detail["items"][0]["researchDecision"]["schema_version"]
            == "unified-research-decision-v1"
        )
        export = client.get(f"/api/v1/backtest-runs/{run_id}/exports/SUMMARY_JSON")
        assert export.status_code == 200, export.text
        assert export.json()["schemaVersion"] == "backtest-report-summary-v4"
