"""Complete mounted composition with fake AI and market facts, never trade scripts.

The browser starts this module as a loopback server in its own temporary directory.
"""

import asyncio
import json
from functools import partial
from pathlib import Path
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient
from tests.integration.test_backtest_market_store import PROFILE
from tests.integration.test_monitor_loop_cycle import frames
from tests.integration.test_plan_preparation_api import FakeAI
from tests.integration.test_plan_preparation_review import review_command
from tests.unit.test_ai_plan_extraction_v4 import _config
from tests.unit.test_monitor_loop_schedule import at, calendar

from trade_plan_monitor.ai.loop_plan_extraction import extract_loop_plan
from trade_plan_monitor.ai.provider import (
    AIProviderError,
    AIProviderErrorCode,
    AIProviderOperation,
    RawAIResponse,
)
from trade_plan_monitor.backtest import composition as composition_module
from trade_plan_monitor.backtest.composition import create_backtest_composition_factory
from trade_plan_monitor.backtest.jobs.maintenance import BacktestJobMaintenance
from trade_plan_monitor.backtest.jobs.repository import BacktestJobRepository
from trade_plan_monitor.backtest.loop_input import KnownLoopCash, LoopAccountInput, LoopInitialLot
from trade_plan_monitor.backtest.loop_report import (
    LoopAuditEvent,
    MonitorLoopReport,
    verify_loop_events,
)
from trade_plan_monitor.backtest.market_store import BacktestMarketStore
from trade_plan_monitor.backtest.preparation_store import PreparationStore
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.routers.plans import PlanVersionPage

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((ROOT / "web/tests/fixtures/monitor-loop.json").read_text(encoding="utf-8"))
BASE = "/api/v1/backtest-preparations"
ORIGIN = "http://127.0.0.1:8765"
NOW = at(20, 9, 43, 12)


class BrowserAI(FakeAI):
    def __init__(self, mode):
        super().__init__()
        self.mode = mode

    def call(self, identity, source, token):
        self.calls.append(identity)
        self.entered.set()
        if self.mode == "unknown":
            self.ended.set()
            return None
        outer = self

        class Provider:
            async def extract_plan(self, request):
                if len(outer.calls) == 1:
                    raise AIProviderError(
                        AIProviderErrorCode.RATE_LIMITED,
                        AIProviderOperation.EXTRACT_PLAN,
                        attempts=1,
                    )
                return RawAIResponse(
                    request_id=request.request_id,
                    provider_id=request.config.provider_id,
                    model=request.config.model,
                    content=json.dumps(FIXTURE["ai_output"], ensure_ascii=False),
                    finish_reason="stop",
                    attempts=1,
                    usage=None,
                )

        try:
            return asyncio.run(
                extract_loop_plan(
                    request_id=identity, source=source, config=_config(), provider=Provider()
                )
            )
        finally:
            self.ended.set()


class Runtime:
    def __init__(self):
        self.started = self.stopped = False

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True


class EmptyPlanCatalog:
    async def list_plan_versions(self, **query):
        return PlanVersionPage(items=(), total=0, limit=query["limit"], offset=query["offset"])


def environment(root, monkeypatch, *, mode="retry", fail_first=False, port=8765):
    """Seed market observations only; no reviewed preparation or expected trades."""
    assert set(FIXTURE) == {"fixture_version", "source", "ai_output", "cutoff", "expected"}
    real_prune = BacktestJobMaintenance.prune

    def prune_at_fixture_time(self, *, as_of, batch_size=1000):
        # All fake time domains agree: real maintenance must not expire this fixture.
        return real_prune(self, as_of=NOW, batch_size=batch_size)

    monkeypatch.setattr(BacktestJobMaintenance, "prune", prune_at_fixture_time)
    root.mkdir(parents=True, exist_ok=True)
    market = BacktestMarketStore(root / "market.sqlite3")
    market.record_trading_days(
        tuple(day.model_copy(update={"exchange": "SZSE"}) for day in calendar())
    )
    source = list(frames())
    market.record_completed_loop_minutes(
        tuple(frame.minute.model_copy(update={"symbol": "002240.SZ"}) for frame in source),
        historical_profile=PROFILE,
    )
    market.record_daily_limits(
        (
            source[0].daily_limit.model_copy(
                update={"symbol": "002240.SZ", "received_at": at(20, 9, 30)}
            ),
        )
    )
    monkeypatch.setattr(
        composition_module,
        "BacktestJobRepository",
        partial(BacktestJobRepository, clock=lambda: NOW),
    )
    monkeypatch.setattr(
        composition_module, "PreparationStore", partial(PreparationStore, clock=lambda: NOW)
    )
    factory = create_backtest_composition_factory(
        config_path=root / "absent.yaml",
        plan_snapshot_reader=None,
        market_database=market.database_path,
        results_database=root / "results.sqlite3",
        cursor_key_path=root / "cursor.key",
        preparation_database=root / "preparation.sqlite3",
    )
    calls = {"factory": 0}

    def activate():
        calls["factory"] += 1
        if fail_first and calls["factory"] == 1:
            raise OSError("synthetic private first-use failure")
        return factory()

    ai, runtime = BrowserAI(mode), Runtime()
    app = create_app(
        runtime_factory=lambda: runtime,
        backtest_lifecycle_factory=activate,
        ai_lifecycle_factory=lambda: ai,
        plan_service=EmptyPlanCatalog(),
        bind_port=port,
    )

    @app.get("/fixture/counters")
    async def counters():
        return {
            **calls,
            "extractions": len(ai.calls),
            "monitorStarted": runtime.started,
            "monitorStopped": runtime.stopped,
        }

    return app, ai, runtime, calls


def post(client, path, body, key):
    return client.post(path, json=body, headers={"Origin": ORIGIN, "Idempotency-Key": key})


def wait(client, path, predicate):
    deadline = monotonic() + 10
    while monotonic() < deadline:
        response = client.get(path)
        if response.status_code == 200 and predicate(response.json()):
            return response.json()
        sleep(0.02)
    pytest.fail(f"Expected public state not reached at {path}: {response.text}")


def test_mounted_upload_retry_review_worker_and_causal_result_use_only_market_facts(
    tmp_path, monkeypatch
):
    app, ai, runtime, calls = environment(tmp_path, monkeypatch)
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/api/v1/backtest-service").json()["state"] == "NOT_INITIALIZED"
        assert calls["factory"] == 0 and not (tmp_path / "preparation.sqlite3").exists()
        source = FIXTURE["source"]
        assert (
            post(
                client, BASE, {"input": {"preparation_id": "one", "sources": [source]}}, "create"
            ).status_code
            == 201
        )
        assert (
            post(
                client, BASE + "/one/extractions", {"expectedRevision": 1}, "extract-one"
            ).status_code
            == 202
        )
        failed = wait(
            client,
            BASE + "/one",
            lambda value: value["status"] == "FAILED" and value["workPhase"] is None,
        )
        assert failed["attempts"][-1]["retryable"]
        assert (
            post(
                client,
                BASE + "/one/extractions",
                {"expectedRevision": failed["revision"]},
                "extract-two",
            ).status_code
            == 202
        )
        wait(
            client,
            BASE + "/one",
            lambda value: value["status"] == "CANDIDATE" and value["workPhase"] is None,
        )
        store = PreparationStore(tmp_path / "preparation.sqlite3", clock=lambda: NOW)
        record = store.get("one")
        account = LoopAccountInput(
            snapshot_at=at(),
            inventory_known=True,
            cash=KnownLoopCash(balance_fen=500000),
            lots=(
                LoopInitialLot(
                    lot_key="source-core",
                    bucket="CORE",
                    quantity=100,
                    cost_basis_fen=401050,
                    acquired_trade_date=at(19).date(),
                    sellable_quantity=100,
                    evidence=source["text"],
                ),
            ),
            opening_mark=None,
            evidence=source["text"],
        )
        command = review_command(record, account=account)
        reviewed = post(
            client, BASE + "/one/reviews", {"review": command.model_dump(mode="json")}, "review"
        )
        assert reviewed.status_code == 200, reviewed.text
        frozen = reviewed.json()
        progress = client.get(BASE + "/one").json()
        assert progress["candidate"]["candidateHash"] == frozen["manifestHash"]
        assert progress["candidate"]["candidateHash"] != record.candidate.candidate_hash
        payload = {
            "preparationId": "one",
            "manifestHash": frozen["manifestHash"],
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
        accepted = post(client, "/api/v1/backtest-runs", payload, "run")
        assert accepted.status_code == 202, accepted.text
        receipt = accepted.json()
        terminal = wait(
            client,
            f"/api/v1/backtest-jobs/{receipt['jobId']}",
            lambda value: value["status"] in {"COMPLETED", "FAILED"},
        )
        assert terminal["status"] == "COMPLETED", terminal
        run = client.get(f"/api/v1/backtest-runs/{receipt['runId']}").json()
        details = client.get(
            f"/api/v1/backtest-runs/{receipt['runId']}/details?kind=DECISION&limit=100"
        ).json()
        report = MonitorLoopReport.model_validate_json(json.dumps(run["report"]))
        verify_loop_events(
            report,
            [
                LoopAuditEvent.model_validate_json(json.dumps(row["event"]))
                for row in details["items"]
            ],
        )
        assert report.cycle.fills == FIXTURE["expected"]["fills"]
        assert report.final_account.cash.balance_fen == FIXTURE["expected"]["cash_fen"]
        assert report.final_inventory.total_qty == FIXTURE["expected"]["inventory_qty"]
        assert len(ai.calls) == 2 and runtime.started and not runtime.stopped
        results = app.state.backtest_lifecycle._instance.read_service._result_store
        copied = results.get_loop_input_reference(
            receipt["runId"]
        )
        assert copied.run_id == report.run_id and "operations" not in payload
    assert runtime.stopped


def test_first_use_failure_and_explicit_control_preserve_same_public_create_intent(
    tmp_path, monkeypatch
):
    app, ai, runtime, calls = environment(tmp_path, monkeypatch, fail_first=True)
    with TestClient(app, base_url=ORIGIN) as client:
        body = {"input": {"preparation_id": "one", "sources": [FIXTURE["source"]]}}
        assert post(client, BASE, body, "original").status_code == 503
        value = client.get("/api/v1/backtest-service").json()
        assert calls["factory"] == 1 and value["state"] == "DEGRADED"
        assert client.get("/fixture/counters").json()["monitorStopped"] is False
        control = post(
            client,
            "/api/v1/backtest-service/recovery-requests",
            {
                "epoch": value["epoch"],
                "expectedRevision": value["revision"],
                "action": "RETRY_PREPARATION",
                "resumeJobIds": [],
            },
            "repair",
        )
        assert control.status_code == 202
        wait(client, "/api/v1/backtest-service", lambda value: value["state"] == "READ_READY")
        assert post(client, BASE, body, "original").status_code == 201
        assert calls["factory"] == 2 and not ai.calls and not runtime.stopped


if __name__ == "__main__":
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--web-port", type=int, required=True)
    parser.add_argument("--mode", choices=("retry", "unknown"), default="retry")
    parser.add_argument("--fail-first", action="store_true")
    args = parser.parse_args()
    assert args.root.resolve().is_relative_to(Path(__import__("tempfile").gettempdir()).resolve())
    patches = pytest.MonkeyPatch()
    try:
        application, ai, runtime, calls = environment(
            args.root, patches, mode=args.mode, fail_first=args.fail_first, port=args.web_port
        )
        server = uvicorn.Server(
            uvicorn.Config(
                application,
                host="127.0.0.1",
                port=args.port,
                log_config=None,
                access_log=False,
                ws="none",
            )
        )

        @application.post("/fixture/shutdown")
        async def shutdown():
            server.should_exit = True
            return {"accepted": True}

        server.run()
        (args.root / "terminal.json").write_text(
            json.dumps({"monitorStopped": runtime.stopped}), encoding="utf-8"
        )
    finally:
        patches.undo()
