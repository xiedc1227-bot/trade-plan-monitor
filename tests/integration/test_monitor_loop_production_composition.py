"""Complete mounted composition with fake AI and market facts, never trade scripts.

The browser starts this module as a loopback server in its own temporary directory.
"""

import asyncio
import json
from functools import partial
from pathlib import Path
from threading import Event
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient
from tests.integration.test_backtest_market_store import PROFILE
from tests.integration.test_monitor_loop_cycle import frames
from tests.integration.test_plan_preparation_api import FakeAI
from tests.integration.test_plan_preparation_review import review_command
from tests.unit.test_ai_plan_extraction_v4 import _config
from tests.unit.test_monitor_loop_schedule import at, calendar

from trade_plan_monitor.ai.daily_review import daily_contract_bindings, semantic_values
from trade_plan_monitor.ai.loop_plan_extraction import extract_loop_plan
from trade_plan_monitor.ai.provider import (
    AIProviderError,
    AIProviderErrorCode,
    AIProviderOperation,
    RawAIResponse,
)
from trade_plan_monitor.ai.review import server_source_clauses
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
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.routers.plans import PlanVersionPage

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((ROOT / "web/tests/fixtures/monitor-loop.json").read_text(encoding="utf-8"))
BASE = "/api/v1/backtest-preparations"
ORIGIN = "http://127.0.0.1:8765"
NOW = at(20, 9, 43, 12)
CONTINUITY = json.loads((ROOT / "tests/fixtures/monitor_loop_continuity.json").read_text(
    encoding="utf-8",
))


def continuity_sources():
    """Full synthetic plans plus explicit field spellings, never reviewed authority."""
    sources = []
    for item in CONTINUITY["sources"]:
        draft = UnifiedPlanDraft.model_validate_json(json.dumps(item["snapshot"]))
        fields = semantic_values(draft)
        text = item["text"] + "\n完整替换此前计划。\n" + "\n".join(
            f"{path}={str(value).lower() if isinstance(value, bool) else value}"
            for path, value in fields.items()
            if not isinstance(value, bool) or path.endswith((".include_low", ".include_high"))
        )
        if not sources:
            text += "\n实际持仓0股。账户现金余额10000元。账户快照2026-08-20T09:00:00+08:00。\n"
        else:
            text += f"\n原文所述核心仓持仓0股。原文所述机动仓持仓{item['stated_quantity']}股。\n"
        sources.append({key: item[key] for key in (
            "source_id", "authored_at", "available_at", "effective_trade_date",
        )} | {"text": text})
    return sources


def continuity_output(index, text):
    from tests.unit.test_monitor_loop_extraction import fact

    draft = UnifiedPlanDraft.model_validate_json(json.dumps(
        CONTINUITY["sources"][index]["snapshot"],
    ))
    values = semantic_values(draft)
    clauses = server_source_clauses(text)
    bindings = [binding.model_dump(mode="json") for binding in daily_contract_bindings(draft)]
    bound = {binding["path"] for binding in bindings}
    for path, value in values.items():
        if path in bound or isinstance(value, bool) and not path.endswith(
            (".include_low", ".include_high"),
        ):
            continue
        literal = f"{path}={str(value).lower() if isinstance(value, bool) else value}"
        start = text.index(literal)
        end = start + len(literal)
        selected = [clause.clause_id for clause in clauses if clause.start < end
                    and clause.end > start]
        bindings.append({"path": path, "value": value, "origin": "SOURCE", "unit": "JSON",
                         "clause_ids": selected, "supplement_id": None})
    output = {"schema_version": "monitor-loop-extraction-v1",
              "draft": draft.model_dump(mode="json"),
              "clauses": [clause.model_dump(mode="json") | {
                  "disposition": "POLICY", "paths": [binding["path"] for binding in bindings
                      if clause.clause_id in binding["clause_ids"]] or ["symbol"],
                  "reason": "Complete synthetic plan and explicit canonical policy spellings.",
              } for clause in clauses], "bindings": bindings, "assumptions": [], "warnings": []}
    if index == 0:
        output["opening_account"] = {
            "inventory_quantity": fact(text, "实际持仓0股", 0), "lots": [],
            "cash_fen": fact(text, "账户现金余额10000元", 1_000_000),
            "snapshot_at": fact(text, "账户快照2026-08-20T09:00:00+08:00",
                                "2026-08-20T09:00:00+08:00"),
        }
    else:
        output.update(schema_version="monitor-loop-update-extraction-v1", scope="FULL_REPLACEMENT",
                      scope_clause_ids=[clause.clause_id for clause in clauses
                                        if "完整替换此前计划" in clause.excerpt],
                      retain_unmentioned=False, operations=[], account_context={
                          "core_qty": fact(text, "原文所述核心仓持仓0股", 0),
                          "tactical_qty": fact(text,
                              f"原文所述机动仓持仓{CONTINUITY['sources'][index]['stated_quantity']}股",
                              CONTINUITY["sources"][index]["stated_quantity"]),
                          "dependent_rule_ids": [], "dependency_clause_ids": [],
                      })
    return output


def test_complete_continuity_source_crosses_real_extraction_boundary():
    from uuid import uuid4

    from trade_plan_monitor.backtest.preparation_models import PreparationSource

    raw = continuity_sources()[0]
    source = PreparationSource.model_validate_json(json.dumps(raw))

    class Provider:
        async def extract_plan(self, request):
            return RawAIResponse(request_id=request.request_id,
                                 provider_id=request.config.provider_id, model=request.config.model,
                                 content=json.dumps(continuity_output(0, source.text)),
                                 finish_reason="stop", attempts=1, usage=None)

    result = asyncio.run(extract_loop_plan(request_id=uuid4(), source=source,
                                          config=_config().model_copy(update={
                                              "max_input_chars": 150_000,
                                          }), provider=Provider()))
    assert result.status.value == "SUCCEEDED", result.diagnostic
    assert not result.validation_issues, [
        (item.code, item.path) for item in result.validation_issues
    ]


def test_complete_continuity_followup_materializes_all_explicit_empty_sections():
    from uuid import uuid4

    from tests.unit.test_plan_update_bindings import prior_review

    from trade_plan_monitor.ai.plan_update_extraction import extract_plan_update
    from trade_plan_monitor.ai.update_review import context_from_review, materialize_extraction
    from trade_plan_monitor.backtest.preparation_models import PreparationSource
    from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan

    source = PreparationSource.model_validate_json(json.dumps(continuity_sources()[1]))
    base = prior_review(UnifiedTradePlan.model_validate_json(json.dumps(
        CONTINUITY["sources"][0]["snapshot"],
    )))
    context = context_from_review(base, base.evidence_hash)

    class Provider:
        async def extract_plan(self, request):
            return RawAIResponse(request_id=request.request_id,
                                 provider_id=request.config.provider_id, model=request.config.model,
                                 content=json.dumps(continuity_output(1, source.text)),
                                 finish_reason="stop", attempts=1, usage=None)

    result = asyncio.run(extract_plan_update(request_id=uuid4(), source=source, context=context,
                                            config=_config().model_copy(update={
                                                "max_input_chars": 150_000,
                                            }), provider=Provider()))
    assert result.status.value == "SUCCEEDED", result.diagnostic
    candidate = materialize_extraction(base, context.base_hash, source, result)
    assert candidate.review.issues == ()


@pytest.mark.parametrize("clause", [
    "Use partial fills for each trade.", "No cash, partial fills allowed.",
    "如果不使用部分成交则改变交易数量。",
])
def test_continuity_actual_or_conditional_unsupported_execution_stays_blocked(clause):
    from uuid import uuid4

    from trade_plan_monitor.backtest.preparation_models import PreparationSource

    raw = continuity_sources()[0]
    raw["text"] = raw["text"].replace(
        "No recorded future transactions, partial fills, external fundamentals or "
        "discretionary conditions.", clause,
    )
    source = PreparationSource.model_validate_json(json.dumps(raw))

    class Provider:
        async def extract_plan(self, request):
            return RawAIResponse(request_id=request.request_id,
                                 provider_id=request.config.provider_id, model=request.config.model,
                                 content=json.dumps(continuity_output(0, source.text)),
                                 finish_reason="stop", attempts=1, usage=None)

    result = asyncio.run(extract_loop_plan(request_id=uuid4(), source=source,
                                          config=_config().model_copy(update={
                                              "max_input_chars": 150_000,
                                          }), provider=Provider()))
    assert result.status.value == "SUCCEEDED", result.diagnostic
    assert any(issue.code == "LOOP_SOURCE_UNSUPPORTED" for issue in result.validation_issues)


class BrowserAI(FakeAI):
    def __init__(self, mode):
        super().__init__()
        self.mode = mode
        self.source_calls = []
        self.retry_entered = Event()
        self.release_retry = Event()

    def call(self, identity, source, token, *, context=None):
        self.calls.append(identity)
        self.entered.set()
        if self.mode == "unknown":
            self.ended.set()
            return None
        outer = self
        if self.mode.startswith("continuity"):
            source_index = next(index for index, item in enumerate(CONTINUITY["sources"])
                                if source.text.startswith(item["text"]))
            self.source_calls.append(source_index)
            if self.mode == "continuity-retry" and source_index == 1 and (
                self.source_calls.count(1) == 2
            ):
                self.retry_entered.set()
                assert self.release_retry.wait(30), "fixture retry was not released"

        class Provider:
            async def extract_plan(self, request):
                if outer.mode.startswith("continuity"):
                    index = next(index for index, item in enumerate(CONTINUITY["sources"])
                                 if source.text.startswith(item["text"]))
                    if outer.mode == "continuity-retry" and index == 1 and (
                        outer.source_calls.count(1) == 1
                    ):
                        raise AIProviderError(AIProviderErrorCode.RATE_LIMITED,
                                              AIProviderOperation.EXTRACT_PLAN, attempts=1)
                    content = continuity_output(index, source.text)
                    return RawAIResponse(
                        request_id=request.request_id, provider_id=request.config.provider_id,
                        model=request.config.model, content=json.dumps(content, ensure_ascii=False),
                        finish_reason="stop", attempts=1, usage=None,
                    )
                if len(outer.calls) == 1 and outer.mode != "auto-data":
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
            if self.mode.startswith("continuity"):
                from trade_plan_monitor.ai.plan_update_extraction import extract_plan_update

                operation = extract_plan_update if context is not None else extract_loop_plan
                return asyncio.run(operation(
                    request_id=identity, source=source,
                    config=_config().model_copy(update={"max_input_chars": 150_000}),
                    provider=Provider(), **({"context": context} if context is not None else {}),
                ))
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
    now = (at(25, 9, 38, 12) if mode.startswith("continuity") else
           at(21, 16) if mode == "auto-data" else NOW)

    def prune_at_fixture_time(self, *, as_of, batch_size=1000):
        # All fake time domains agree: real maintenance must not expire this fixture.
        return real_prune(self, as_of=now, batch_size=batch_size)

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
    data_calls = []
    if mode == "auto-data":
        from tests.integration.automatic_data_provider import bind_provider
        data_calls = bind_provider(monkeypatch, market)
    if mode.startswith("continuity"):
        from datetime import datetime

        from tests.integration.test_backtest_market_store import _daily, _minute_batch
        from tests.integration.test_monitor_loop_plan_switch import continuity_calendar

        from trade_plan_monitor.market_data.models import DailyLimit, MinuteBar

        market.record_trading_days(continuity_calendar())
        actual = [MinuteBar.model_validate_json(json.dumps(bar))
                  for bar in CONTINUITY["minute_bars"]]
        for source_row in CONTINUITY["sources"]:
            day = datetime.fromisoformat(source_row["effective_trade_date"]).date()
            literal = {bar.bar_end: bar for bar in actual if bar.bar_end.date() == day}
            last = list(literal.values())[-1]
            complete = _minute_batch(symbol=CONTINUITY["symbol"], trade_date=day)
            observations = tuple(literal.get(bar.bar_end, bar.model_copy(update={
                "open_fen": last.close_fen, "high_fen": last.close_fen,
                "low_fen": last.close_fen, "close_fen": last.close_fen,
            })) for bar in complete.bars if bar.received_at <= now)
            market.record_completed_loop_minutes(observations, historical_profile=PROFILE)
            if day < now.date():
                market.record_daily_bars((_daily().model_copy(update={
                    "symbol": CONTINUITY["symbol"], "trade_date": day,
                    "open_fen": observations[0].open_fen, "high_fen": 1500, "low_fen": 900,
                    "close_fen": last.close_fen,
                    "received_at": datetime.combine(day, at(20, 15, 20).timetz()),
                }),))
        market.record_daily_limits(tuple(DailyLimit.model_validate_json(json.dumps(item)).model_copy(
            update={"received_at": datetime.combine(
                datetime.fromisoformat(item["trade_date"]).date(), at(20, 9, 30).timetz(),
            )},
        ) for item in CONTINUITY["daily_limits"]))
    monkeypatch.setattr(
        composition_module,
        "BacktestJobRepository",
        partial(BacktestJobRepository, clock=lambda: now),
    )
    monkeypatch.setattr(
        composition_module, "PreparationStore", partial(PreparationStore, clock=lambda: now)
    )
    monkeypatch.setattr("trade_plan_monitor.backtest.automatic_data.now", lambda: now)
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
            "sourceCalls": ai.source_calls,
            "retryEntered": ai.retry_entered.is_set(),
            "dataCalls": list(data_calls),
        }

    @app.get("/fixture/continuity-sources")
    async def source_inputs():
        return {"sources": continuity_sources(), "expected": CONTINUITY["expected"]}

    @app.post("/fixture/release-retry")
    async def release_retry():
        ai.release_retry.set()
        return {"released": True}

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


def test_complete_continuity_sources_cross_stored_predecessor_revalidation(tmp_path, monkeypatch):
    from tests.integration.test_plan_preparation_review import collection_review_command

    app, ai, _, _ = environment(tmp_path, monkeypatch, mode="continuity")
    sources = continuity_sources()
    with TestClient(app, base_url=ORIGIN) as client:
        created = post(client, BASE, {"input": {
            "schema_version": "backtest-preparation-v2", "preparation_id": "four",
            "sources": sources,
        }}, "create-four")
        assert created.status_code == 201, created.text
        extracted = post(client, BASE + "/four/extractions", {
            "schemaVersion": "backtest-preparation-v2", "expectedRevision": 1,
            "sourceId": sources[0]["source_id"], "expectedSourceRevision": 1,
            "expectedBaseHash": None,
        }, "extract-four")
        assert extracted.status_code == 202, extracted.text
        ready = wait(client, BASE + "/four", lambda value: value["workPhase"] is None)
        assert ready["status"] == "CANDIDATE", ready
        assert [item["validation"] for item in ready["items"]] == ["VALID"] * 4
        assert len(ai.calls) == 4
        record = PreparationStore(tmp_path / "preparation.sqlite3").get("four")
        reviewed = post(client, BASE + "/four/reviews", {
            "schemaVersion": "backtest-preparation-v2", "kind": "CHAIN_REVIEW",
            "review": collection_review_command(record, account=None).model_dump(mode="json"),
        }, "review-four")
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json()["account"]["snapshot_at"] == "2026-08-20T09:00:00+08:00"


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
    parser.add_argument("--mode", choices=(
        "retry", "unknown", "continuity", "continuity-retry", "auto-data",
    ), default="retry")
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
            ai.release_retry.set()
            server.should_exit = True
            return {"accepted": True}

        server.run()
        (args.root / "terminal.json").write_text(
            json.dumps({"monitorStopped": runtime.stopped}), encoding="utf-8"
        )
    finally:
        patches.undo()
