"""Exercise R14's real app composition with simulated supplier transports only."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from scripts.r14_bounded_acceptance import (
    _MARKET_CAPS,
    Budget,
    BudgetDenied,
    MarketBudget,
    _create_guarded_app,
    _deactivate_isolated_plan,
    _guarded_market_factory,
    _recover_activated_symbol,
    _serve,
    approved_sources,
)
from tests.integration.test_explicit_plan_review_api import (
    _SOURCE as SYNTHETIC_SOURCE,
)
from tests.integration.test_explicit_plan_review_api import (
    _confirmation_resolutions,
    _draft_payload,
    _mapping,
)
from tests.integration.test_live_pipeline_acceptance import (
    ENDPOINT,
    ControlledClock,
    OfflineSDK,
    VirtualPace,
    _ready_stock_capabilities,
    _work_factory,
    _write_configuration_and_evidence,
)
from tests.integration.test_source_treatment_review_api import (
    FIXTURE as LITERAL_FIXTURE,
)
from tests.integration.test_source_treatment_review_api import (
    SOURCE as LITERAL_SOURCE,
)
from tests.integration.test_source_treatment_review_api import (
    _get_path,
    _literal_mapping,
)
from tests.unit.test_ai_plan_extraction_v4 import _partial_draft

from trade_plan_monitor.ai.models import (
    ExplicitPlanDraft,
    PlanExtractionResult,
    PlanExtractionStatus,
)
from trade_plan_monitor.ai.review import dump_explicit_plan_draft_json, server_source_clauses
from trade_plan_monitor.config import load_application_config
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.live_profiles import create_stock_certification, write_live_certification
from trade_plan_monitor.market_data.sessions import SourceTimeLabel
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.models import MarketIndexHealth
from trade_plan_monitor.runtime.clock import SHANGHAI
from trade_plan_monitor.runtime.market_indexes import ALWAYS_ON_INDEX_CODES
from trade_plan_monitor.runtime.production import ProductionMonitorPipeline
from trade_plan_monitor.runtime.request_control import create_live_tushare_request_controller
from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketSessionScheduler
from trade_plan_monitor.state.database import upgrade_database
from trade_plan_monitor.web.app import installed_web_assets
from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle


class QuerySDK(OfflineSDK):
    """Preserve the SDK's dynamic endpoint dispatch through its physical query method."""

    def query(self, name: str, fields: str = "", **kwargs: object):
        frame = OfflineSDK.__getattr__(self, name)(fields=fields, **kwargs)
        if name in {"rt_min", "rt_min_daily"}:
            frame["time"] = [
                (datetime.fromisoformat(value) + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
                for value in frame["time"]
            ]
        return frame

    def __getattr__(self, name: str):
        return lambda **kwargs: self.query(name, **kwargs)


@pytest.mark.parametrize("all_stale", [False, True], ids=["mixed", "all-stale"])
def test_simulated_scheduler_retries_only_lagging_physical_index_request(
    tmp_path: Path, monkeypatch, all_stale: bool
) -> None:
    """SIMULATED SDK frames enter production scheduling, adapter, and SQLite heads."""
    import trade_plan_monitor.runtime.production as production

    clock = ControlledClock(datetime(2026, 9, 14, 10, 25, 12, tzinfo=SHANGHAI))
    config = _write_configuration_and_evidence(
        tmp_path, observed_at=clock.now(), include_index=True
    )
    database = tmp_path / "monitor.sqlite3"
    engine, work_factory = _work_factory(database, clock)
    upgrade_database(engine)
    budget = Budget(total=60, per_key=_MARKET_CAPS, seconds=900)
    created_sdks: list[QuerySDK] = []

    class MixedPublicationSDK(QuerySDK):
        def _index_minutes(self, kwargs: dict[str, object]) -> pd.DataFrame:
            frame = super()._index_minutes(kwargs)
            if (
                all_stale or kwargs["ts_code"] == MarketIndexCode.STAR_50.value
            ) and self.clock.now().minute in ({25, 30, 35} if all_stale else {25}):
                cutoff = self.clock.now().replace(second=0, microsecond=0)
                frame = frame.loc[frame["time"] < cutoff.strftime("%Y-%m-%d %H:%M:%S")]
            return frame

    def make_client(_settings: object) -> QuerySDK:
        sdk = MixedPublicationSDK(clock, ())
        created_sdks.append(sdk)
        return sdk

    monkeypatch.setattr(
        production,
        "create_tushare_client",
        _guarded_market_factory(make_client, MarketBudget(budget)),
    )
    pace = VirtualPace()
    controller = create_live_tushare_request_controller(
        clock=clock, monotonic=pace.monotonic, pace_sleep=pace.sleep
    )
    pipeline = ProductionMonitorPipeline(
        configuration=load_application_config(config).tushare,
        certification_directory=tmp_path / "data/live-certification",
        stock_certification=create_stock_certification(
            observed_at=clock.now(),
            endpoint_url=ENDPOINT,
            capabilities=_ready_stock_capabilities(),
            source_time_label=SourceTimeLabel.START,
        ),
        clock=clock,
        request_controller=controller,
        unit_of_work_factory=work_factory,
        runtime_generation=uuid4(),
        publisher=lambda _event: None,
    )
    scheduler = MarketSessionScheduler(clock=clock, is_open_on=lambda _date: True)

    async def scenario() -> None:
        try:
            previous = None
            minutes = (25, 26, 30, 31, 35, 36) if all_stale else (25, 26, 27, 30)
            for minute in minutes:
                clock.current = datetime(2026, 9, 14, 10, minute, 12, tzinfo=SHANGHAI)
                deadline = scheduler.next_deadline(after=previous)
                assert deadline is not None and deadline.bar_end == clock.now().replace(second=0)
                assert await pipeline.run_deadline(deadline) == ()
                previous = deadline.due_at
                physical = budget.snapshot()["attempts"].get("rt_idx_min_daily", 0)
                expected = (
                    {25: 5, 26: 10, 30: 15, 31: 20, 35: 25, 36: 25}
                    if all_stale
                    else {25: 5, 26: 6, 27: 6, 30: 11}
                )
                assert physical == expected[minute]
                if minute == 25:
                    initial = dict(pipeline.index_service.latest_snapshots())
                    assert initial[MarketIndexCode.STAR_50].health is MarketIndexHealth.STALE
                    if not all_stale:
                        assert all(
                            snapshot.health is MarketIndexHealth.LIVE
                            for code, snapshot in initial.items()
                            if code is not MarketIndexCode.STAR_50
                        )
                if minute == 26:
                    assert (
                        pipeline.index_service.latest_snapshots()[MarketIndexCode.STAR_50].health
                        is MarketIndexHealth.LIVE
                    )
                    if not all_stale:
                        for code in set(ALWAYS_ON_INDEX_CODES) - {MarketIndexCode.STAR_50}:
                            assert pipeline.index_service.latest_snapshots()[code] is initial[code]
                            with work_factory() as work:
                                head = work.projections.get_market_index_head(
                                    mapping_version=initial[code].mapping_version,
                                    index_code=code,
                                    decision_cutoff=initial[code].decision_cutoff,
                                    request_set_hash=initial[code].request_set_hash,
                                )
                                assert head is not None
                                assert head.snapshot.snapshot_hash == initial[code].snapshot_hash
                    with work_factory() as work:
                        retried = pipeline.index_service.latest_snapshots()[MarketIndexCode.STAR_50]
                        head = work.projections.get_market_index_head(
                            mapping_version=retried.mapping_version,
                            index_code=MarketIndexCode.STAR_50,
                            decision_cutoff=retried.decision_cutoff,
                            request_set_hash=retried.request_set_hash,
                        )
                        assert head is not None
                        assert head.snapshot.snapshot_hash == retried.snapshot_hash
                if minute == 36:
                    assert all(
                        snapshot.health is MarketIndexHealth.BLOCKED
                        for snapshot in pipeline.index_service.latest_snapshots().values()
                    )
                    with work_factory() as work:
                        for snapshot in pipeline.index_service.latest_snapshots().values():
                            head = work.projections.get_market_index_head(
                                mapping_version=snapshot.mapping_version,
                                index_code=snapshot.index_code,
                                decision_cutoff=snapshot.decision_cutoff,
                                request_set_hash=snapshot.request_set_hash,
                            )
                            assert head is not None
                            assert head.snapshot.health is MarketIndexHealth.BLOCKED
            assert budget.snapshot()["deniedBeforeNetwork"] == (5 if all_stale else 0)
            assert budget.snapshot()["attempts"] == {
                "idx_mins": 5,
                "index_daily": 5,
                "rt_idx_min_daily": 25 if all_stale else 11,
            }
            index_sdk = created_sdks[1]
            realtime_codes = [
                kwargs["ts_code"] for name, kwargs in index_sdk.calls if name == "rt_idx_min_daily"
            ]
            assert len(realtime_codes) == (25 if all_stale else 11)
            if not all_stale:
                assert realtime_codes.count(MarketIndexCode.STAR_50.value) == 3
                assert all(
                    realtime_codes.count(code.value) == 2
                    for code in ALWAYS_ON_INDEX_CODES
                    if code is not MarketIndexCode.STAR_50
                )
            # Observed R14 pattern: 4 lag at 10:25, then all 5 at two later cutoffs.
            assert 5 + 4 + 5 + 5 + 5 + 5 == 29 > _MARKET_CAPS["rt_idx_min_daily"]
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())


def _write_end_label_stock_evidence(root: Path, observed_at: datetime) -> None:
    write_live_certification(
        root / "data/live-certification/tushare-stock-live.json",
        create_stock_certification(
            observed_at=observed_at,
            endpoint_url=ENDPOINT,
            capabilities=_ready_stock_capabilities(),
            source_time_label=SourceTimeLabel.END,
        ),
    )


@pytest.mark.parametrize(
    "r17_full_window", [False, True], ids=["r14-two-evaluations", "r17-full-window"]
)
def test_real_lifespan_api_review_scheduler_and_guards_are_wired_offline(
    tmp_path: Path, monkeypatch, r17_full_window: bool
) -> None:
    import trade_plan_monitor.runtime.production as production
    import trade_plan_monitor.web.monitor_composition as monitor_composition

    scenario_day = 15 if r17_full_window else 14
    clock = ControlledClock(datetime(2026, 9, scenario_day, 10, 12, tzinfo=SHANGHAI))
    config = _write_configuration_and_evidence(
        tmp_path, observed_at=clock.now(), include_index=True
    )
    _write_end_label_stock_evidence(tmp_path, clock.now())
    config.write_text(
        config.read_text("utf-8")
        + "ai:\n"
        + "  profile: DEEPSEEK\n"
        + "  model: deepseek-flash\n"
        + "  additional_models:\n"
        + "    - display_name: DeepSeek Pro\n"
        + "      model: deepseek-v4-pro\n"
        + "  api_key: offline-test-key\n",
        encoding="utf-8",
    )
    database = tmp_path / (
        "data/r17-acceptance/offline/monitor.sqlite3"
        if r17_full_window
        else "data/r14-acceptance/offline/monitor.sqlite3"
    )
    database.parent.mkdir(parents=True)
    original_database = tmp_path / "data/monitor.sqlite3"
    original_database.write_bytes(b"untouched-original-database-sentinel")
    plans = PersistentPlanWebLifecycle(database_path=database, clock=clock.now)
    ai_budget = Budget(total=3, per_key={key: 1 for key in approved_sources()}, seconds=900)
    if r17_full_window:
        from scripts.r17_bounded_acceptance import MARKET_CAPS
    else:
        MARKET_CAPS = _MARKET_CAPS
    market_budget = Budget(total=60, per_key=MARKET_CAPS, seconds=900)
    created_sdks: list[QuerySDK] = []
    configured_timeouts: list[int] = []

    class LaggedIndexSDK(QuerySDK):
        def _index_minutes(self, kwargs: dict[str, object]) -> pd.DataFrame:
            frame = super()._index_minutes(kwargs)
            if r17_full_window and self.clock.now().minute in {15, 20, 25}:
                cutoff = self.clock.now().replace(second=0, microsecond=0)
                return frame.loc[frame["time"] < cutoff.strftime("%Y-%m-%d %H:%M:%S")]
            return frame

    def make_client(settings: object) -> QuerySDK:
        configured_timeouts.append(settings.timeout_seconds)
        sdk = LaggedIndexSDK(clock, ("003043.SZ",))
        created_sdks.append(sdk)
        return sdk

    monkeypatch.setattr(
        production,
        "create_tushare_client",
        _guarded_market_factory(make_client, MarketBudget(market_budget)),
    )
    monkeypatch.setattr(monitor_composition, "SystemClock", lambda: clock)
    pace = VirtualPace()
    real_controller = monitor_composition.create_live_tushare_request_controller
    monkeypatch.setattr(
        monitor_composition,
        "create_live_tushare_request_controller",
        lambda *, clock: real_controller(
            clock=clock, monotonic=pace.monotonic, pace_sleep=pace.sleep
        ),
    )
    sources = approved_sources()
    sent: list[str] = []
    request_timeouts: list[dict[str, object]] = []

    def ai_handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        request_prompt = payload["messages"][0]["content"]
        case_id = next(key for key, (_, prompt) in sources.items() if prompt == request_prompt)
        sent.append(case_id)
        request_timeouts.append(dict(request.extensions["timeout"]))
        source = sources[case_id][0]
        if r17_full_window and case_id == "LITERAL":
            partial = ExplicitPlanDraft.model_validate_json(
                json.dumps(_draft_payload(complete=False))
            )
            literal_mapping = _literal_mapping(partial)
            draft_payload = partial.model_dump(mode="json")
            clauses = literal_mapping.source_clauses
            bindings = literal_mapping.field_bindings
        else:
            draft_payload = _partial_draft()
            clauses = server_source_clauses(source)
            bindings = ()
        content = {
            "draft": draft_payload,
            "mapping_version": "plan-mapping-v1",
            "source_clauses": [clause.model_dump(mode="json") for clause in clauses],
            "field_bindings": [binding.model_dump(mode="json") for binding in bindings],
            "assumptions": [],
            "warnings": [],
        }
        return httpx.Response(
            200,
            json={
                "id": "offline-r14",
                "object": "chat.completion",
                "created": 1,
                "model": "deepseek-v4-pro",
                "usage": {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200},
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": json.dumps(content)},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    with installed_web_assets() as assets:
        app = _create_guarded_app(
            config_path=config,
            database=database,
            plan_lifecycle=plans,
            ai_budget=ai_budget,
            static_directory=assets,
            ai_inner_transport=httpx.MockTransport(ai_handler),
        )
        with TestClient(app, base_url="http://127.0.0.1:18765") as client:
            assert client.get("/api/v1/ai-runtime").status_code == 200
            provider_id = client.get("/api/v1/ai-runtime").json()["providerId"]
            for case_id, (source, _) in sources.items():
                receipt = client.post(
                    "/api/v1/plan-extractions",
                    headers={"Idempotency-Key": f"offline-{case_id}"},
                    json={"providerId": provider_id, "sourceText": source, "expectedRevision": 0},
                )
                assert receipt.status_code == 202, receipt.text
                operation_id = receipt.json()["operationId"]
                for _ in range(100):
                    result = client.get(f"/api/v1/plan-extractions/{operation_id}")
                    if result.json()["status"] not in {"QUEUED", "RUNNING"}:
                        break
                assert result.json()["status"] == "SUCCEEDED", result.text

            # SIMULATED HTTP responses exercise the same bounded-launcher diagnostic path.
            diagnostic_path = database.with_suffix(".ai-extraction-diagnostics.jsonl")
            diagnostics = [
                json.loads(line) for line in diagnostic_path.read_text("utf-8").splitlines()
            ]
            assert len(diagnostics) == 3
            assert all(item["status"] == "SUCCEEDED" for item in diagnostics)
            assert all(item["model"] == "deepseek-v4-pro" for item in diagnostics)
            assert all(item["modelMatchesConfigured"] is True for item in diagnostics)

            runtime = app.state.runtime_lifecycle
            assert runtime._runtime._request_controller._in_cycle_retries == 0
            assert [
                type(channel).__name__ for channel in runtime._runtime._dispatcher._channels
            ] == ["InAppChannel"]
            scheduler = runtime._runtime._scheduler
            pipeline = runtime._runtime._run_deadline.__self__._pipeline
            assert pipeline is not None, app.state.runtime_startup

            async def run_due(at: datetime) -> None:
                clock.current = at
                deadline = scheduler.next_deadline()
                assert deadline is not None and deadline.kind is DeadlineKind.REALTIME_MINUTE
                assert deadline.bar_end == at.replace(second=0)
                await runtime._runtime._run_deadline(deadline)

            if r17_full_window:
                for minute in (12, 13, 14):
                    client.portal.call(
                        run_due, datetime(2026, 9, scenario_day, 10, minute, 12, tzinfo=SHANGHAI)
                    )
            client.portal.call(
                run_due, datetime(2026, 9, scenario_day, 10, 15, 12, tzinfo=SHANGHAI)
            )
            assert market_budget.snapshot()["attempts"].get("idx_mins") == 5
            if r17_full_window:
                assert all(
                    snapshot.health is not MarketIndexHealth.LIVE
                    for snapshot in pipeline.index_service.latest_snapshots().values()
                )
            clock.current = datetime(2026, 9, scenario_day, 10, 15, 30, tzinfo=SHANGHAI)

            # Explicitly synthetic, numeric-equivalent review. The three fixed AI
            # extractions above remain separate and are never passed off as this draft.
            draft_data = _draft_payload()
            if r17_full_window:
                draft_data["version"] = 2
                draft_data["activation"] = {
                    "mode": "TRADING_DAY",
                    "trading_day": "2026-09-15",
                }
            draft = ExplicitPlanDraft.model_validate_json(json.dumps(draft_data))
            review_source = LITERAL_SOURCE if r17_full_window else SYNTHETIC_SOURCE
            review_mapping = (
                _literal_mapping(draft, supplemented=True) if r17_full_window else _mapping(draft)
            )
            if r17_full_window:
                assert review_source == approved_sources()["LITERAL"][0]
                assert {item.path: item.value for item in review_mapping.user_supplements}[
                    "activation.trading_day"
                ] == "2026-09-15"
                for path, expected in LITERAL_FIXTURE["independentExpectedValues"].items():
                    if expected is not None:
                        assert _get_path(draft_data, path) == expected, path
            extraction_id = uuid4()
            extraction = PlanExtractionResult(
                request_id=extraction_id,
                provider_id=uuid4(),
                model="offline-simulated-review",
                prompt_version="plan-extract-v4",
                source_text_sha256=sha256(review_source.encode()).hexdigest(),
                draft=draft,
                mapping=review_mapping,
                usage=None,
                status=PlanExtractionStatus.SUCCEEDED,
            )
            client.portal.call(plans.record_plan_extraction, extraction)
            saved = client.post(
                "/api/v1/plan-drafts",
                headers={"Idempotency-Key": "offline-save"},
                json={
                    "extractionId": str(extraction_id),
                    "planJson": dump_explicit_plan_draft_json(draft),
                    "sourceText": review_source,
                    "expectedRevision": 0,
                },
            )
            assert saved.status_code == 200, saved.text
            detail = saved.json()
            resolutions = _confirmation_resolutions(detail)
            if r17_full_window:
                supplements = {
                    item["path"]: item["supplementId"]
                    for item in detail["mapping"]["userSupplements"]
                }
                resolutions = []
                for issue in detail["requiredReviewIssues"]:
                    kind = {
                        "SOURCE_MAPPING_REVIEW_REQUIRED": "CONFIRM_MAPPING",
                        "SOURCE_TREATMENT_REVIEW_REQUIRED": "CONFIRM_SOURCE_TREATMENT",
                        "USER_SUPPLEMENT_REVIEW_REQUIRED": "CONFIRM_POLICY",
                    }.get(issue["code"])
                    if kind is None:
                        continue
                    item = {"issueId": issue["issueId"], "resolution": kind}
                    if kind in {"CONFIRM_MAPPING", "CONFIRM_SOURCE_TREATMENT"}:
                        item["bindingPath"] = issue["bindingPath"]
                    else:
                        item["supplementId"] = supplements[issue["path"]]
                    resolutions.append(item)
            reviewed = client.post(
                "/api/v1/plan-review-confirmations",
                headers={"Idempotency-Key": "offline-review"},
                json={
                    "planVersionId": detail["id"],
                    "contentHash": detail["contentHash"],
                    "sourceHash": detail["sourceHash"],
                    "reviewEvidenceHash": detail["reviewEvidenceHash"],
                    "expectedRevision": 0,
                    "resolutions": resolutions,
                },
            )
            assert reviewed.status_code == 200, reviewed.text
            activation = client.post(
                "/api/v1/plan-activations",
                headers={"Idempotency-Key": "offline-activate"},
                json={
                    "planVersionId": detail["id"],
                    "reviewId": reviewed.json()["reviewId"],
                    "contentHash": detail["contentHash"],
                    "expectedRevision": 0,
                },
            )
            assert activation.status_code == 200, activation.text
            recovery = client.portal.call(_recover_activated_symbol, runtime, clock.now().date())
            assert recovery["mode"] == "TEST_TRIGGERED_PRODUCTION_RECOVERY"
            # 09:30–10:15 supplies nine complete historical five-minute buckets.
            assert recovery["persistedMinuteBars"] >= 45
            for minute in range(16, 27 if r17_full_window else 26):
                client.portal.call(
                    run_due,
                    datetime(2026, 9, scenario_day, 10, minute, 12, tzinfo=SHANGHAI),
                )
                if r17_full_window:
                    index_count = market_budget.snapshot()["attempts"].get("rt_idx_min_daily")
                    assert (
                        index_count
                        == {
                            16: 10,
                            17: 10,
                            18: 10,
                            19: 10,
                            20: 15,
                            21: 20,
                            22: 20,
                            23: 20,
                            24: 20,
                            25: 25,
                            26: 30,
                        }[minute]
                    )
                    if minute in {20, 25}:
                        assert all(
                            snapshot.health is not MarketIndexHealth.LIVE
                            for snapshot in pipeline.index_service.latest_snapshots().values()
                        )
                    if minute in {16, 21, 26}:
                        assert all(
                            snapshot.health is MarketIndexHealth.LIVE
                            for snapshot in pipeline.index_service.latest_snapshots().values()
                        )
            assert market_budget.snapshot()["deniedBeforeNetwork"] == 0
            expected_attempts = {
                "trade_cal": 3,
                "idx_mins": 5,
                "rt_idx_min_daily": 30 if r17_full_window else 15,
                "index_daily": 5,
                "rt_min_daily": 1,
                "rt_min": 11 if r17_full_window else 10,
            }
            assert market_budget.snapshot()["attempts"] == expected_attempts
            assert market_budget.snapshot()["totalAttempts"] == (55 if r17_full_window else 39)
            if r17_full_window:
                assert all(
                    snapshot.health is MarketIndexHealth.LIVE
                    for snapshot in pipeline.index_service.latest_snapshots().values()
                )
                assert (
                    len(
                        [
                            call
                            for sdk in created_sdks
                            for call in sdk.calls
                            if call[0] == "rt_idx_min_daily"
                        ]
                    )
                    == 30
                )
            plan = draft.to_executable()
            assert plan is not None
            with pipeline._work() as work:
                for minute in (20, 25):
                    assert (
                        work.explicit_rules.get(
                            plan_hash=plan_sha256(plan),
                            symbol="003043.SZ",
                            target_bucket_end=datetime(
                                2026, 9, scenario_day, 10, minute, tzinfo=SHANGHAI
                            ),
                            activation_revision=1,
                        )
                        is not None
                    )
            assert all(value == 15 for value in configured_timeouts)
            assert len(created_sdks) == 2
            assert sent == list(sources)
            assert ai_budget.snapshot()["totalAttempts"] == 3
            assert all(set(timeout.values()) == {30.0} for timeout in request_timeouts)
    assert asyncio.run(_deactivate_isolated_plan(database)) == "DEACTIVATED"
    assert asyncio.run(_deactivate_isolated_plan(database)) == "INACTIVE"
    assert original_database.read_bytes() == b"untouched-original-database-sentinel"


@pytest.mark.parametrize("cleanup_hangs", [False, True], ids=["normal-cleanup", "cleanup-timeout"])
def test_launcher_denial_exits_with_sanitized_audit_and_restores_factory(
    tmp_path: Path, monkeypatch, cleanup_hangs: bool
) -> None:
    import scripts.r14_bounded_acceptance as launcher
    import uvicorn

    import trade_plan_monitor.runtime.production as production
    import trade_plan_monitor.web.monitor_composition as monitor_composition

    clock = ControlledClock(datetime(2026, 9, 14, 10, 12, tzinfo=SHANGHAI))
    config = _write_configuration_and_evidence(
        tmp_path, observed_at=clock.now(), include_index=True
    )
    _write_end_label_stock_evidence(tmp_path, clock.now())
    config.write_text(
        config.read_text("utf-8")
        + "  connect_ip: 127.0.0.1\n"
        + "ai:\n"
        + "  profile: DEEPSEEK\n"
        + "  model: deepseek-flash\n"
        + "  additional_models:\n"
        + "    - display_name: DeepSeek Pro\n"
        + "      model: deepseek-v4-pro\n"
        + "  api_key: offline-test-key\n",
        encoding="utf-8",
    )
    sources = approved_sources()
    monkeypatch.setattr(launcher, "_ROOT", tmp_path)
    monkeypatch.setattr(launcher, "approved_sources", lambda: sources)
    monkeypatch.setattr(monitor_composition, "SystemClock", lambda: clock)
    created: list[QuerySDK] = []

    def original_factory(_settings: object) -> QuerySDK:
        sdk = QuerySDK(clock, ("003043.SZ",))
        created.append(sdk)
        return sdk

    monkeypatch.setattr(production, "create_tushare_client", original_factory)

    class LocalServer:
        def __init__(self, settings: uvicorn.Config) -> None:
            self.app = settings.app
            self.started = False
            self.should_exit = False

        async def serve(self, *, sockets: object) -> None:
            assert sockets
            async with self.app.router.lifespan_context(self.app):
                self.started = True
                runtime = self.app.state.runtime_lifecycle
                pipeline = runtime._runtime._run_deadline.__self__._pipeline
                assert pipeline is not None
                sdk = pipeline.provider._client._client
                with pytest.raises(BudgetDenied):
                    sdk.query("daily", ts_code="003043.SZ")
                assert self.should_exit

    import pytest

    monkeypatch.setattr(uvicorn, "Server", LocalServer)
    if cleanup_hangs:

        async def slow_deactivation(_database: Path) -> str:
            await asyncio.sleep(1)
            return "INACTIVE"

        monkeypatch.setattr(launcher, "_deactivate_isolated_plan", slow_deactivation)
        # The cleanup deadline is exhausted by the next clock observation.
        ticks = iter(range(0, 10_000, 20))
        monkeypatch.setattr(launcher, "monotonic", lambda: next(ticks))
    assert asyncio.run(_serve("r14-20260914-a")) == 1
    audit = json.loads(
        (tmp_path / "data/r14-acceptance/r14-20260914-a/audit.json").read_text("utf-8")
    )
    assert audit["status"] == "BUDGET_DENIED"
    assert audit["market"]["deniedBeforeNetwork"] == 1
    assert audit["market"]["attempts"] == {"trade_cal": 1}
    assert audit["isolatedPlanCleanup"] == ("FAILED" if cleanup_hangs else "INACTIVE")
    if cleanup_hangs:
        assert audit["cleanupErrorType"] == "TimeoutError"
    assert production.create_tushare_client is original_factory
    assert len(created) == 2


@pytest.mark.parametrize(
    "persistent_lag", [False, True], ids=["recover-next-minute", "persistent-failure"]
)
def test_r17_failed_ai_without_activation_keeps_index_budget_and_health(
    tmp_path: Path, monkeypatch, persistent_lag: bool
) -> None:
    """SIMULATED failed completions do not activate stock or erase index costs."""
    from scripts.r17_bounded_acceptance import MARKET_CAPS

    import trade_plan_monitor.runtime.production as production
    import trade_plan_monitor.web.monitor_composition as monitor_composition

    clock = ControlledClock(datetime(2026, 9, 15, 10, 12, tzinfo=SHANGHAI))
    config = _write_configuration_and_evidence(
        tmp_path, observed_at=clock.now(), include_index=True
    )
    _write_end_label_stock_evidence(tmp_path, clock.now())
    config.write_text(
        config.read_text("utf-8")
        + "ai:\n  profile: DEEPSEEK\n  model: deepseek-flash\n"
        + "  additional_models:\n    - display_name: DeepSeek Pro\n"
        + "      model: deepseek-v4-pro\n  api_key: offline-test-key\n",
        encoding="utf-8",
    )
    database = tmp_path / "data/r17-acceptance/failed-ai/monitor.sqlite3"
    database.parent.mkdir(parents=True)
    budget = Budget(total=60, per_key=MARKET_CAPS, seconds=900)
    ai_budget = Budget(total=3, per_key={key: 1 for key in approved_sources()}, seconds=900)

    class LagSDK(QuerySDK):
        def _index_minutes(self, kwargs: dict[str, object]) -> pd.DataFrame:
            frame = super()._index_minutes(kwargs)
            if persistent_lag or self.clock.now().minute in {15, 20, 25}:
                cutoff = self.clock.now().replace(
                    minute=self.clock.now().minute // 5 * 5,
                    second=0,
                    microsecond=0,
                )
                return frame.loc[frame["time"] < cutoff.strftime("%Y-%m-%d %H:%M:%S")]
            return frame

    created: list[LagSDK] = []

    def make_client(_settings: object) -> LagSDK:
        sdk = LagSDK(clock, ("003043.SZ",))
        created.append(sdk)
        return sdk

    monkeypatch.setattr(
        production,
        "create_tushare_client",
        _guarded_market_factory(make_client, MarketBudget(budget)),
    )
    monkeypatch.setattr(monitor_composition, "SystemClock", lambda: clock)
    pace = VirtualPace()
    real_controller = monitor_composition.create_live_tushare_request_controller
    monkeypatch.setattr(
        monitor_composition,
        "create_live_tushare_request_controller",
        lambda *, clock: real_controller(
            clock=clock, monotonic=pace.monotonic, pace_sleep=pace.sleep
        ),
    )
    plans = PersistentPlanWebLifecycle(database_path=database, clock=clock.now)
    sent: list[str] = []

    def invalid_response(request: httpx.Request) -> httpx.Response:
        prompt = json.loads(request.content)["messages"][0]["content"]
        sent.append(next(key for key, (_, value) in approved_sources().items() if value == prompt))
        return httpx.Response(
            200,
            json={
                "id": "offline-invalid",
                "object": "chat.completion",
                "created": 1,
                "model": "deepseek-v4-pro",
                "usage": {"prompt_tokens": 100, "completion_tokens": 1, "total_tokens": 101},
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "{invalid"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    with installed_web_assets() as assets:
        app = _create_guarded_app(
            config_path=config,
            database=database,
            plan_lifecycle=plans,
            ai_budget=ai_budget,
            static_directory=assets,
            ai_inner_transport=httpx.MockTransport(invalid_response),
        )
        with TestClient(app, base_url="http://127.0.0.1:18765") as client:
            provider_id = client.get("/api/v1/ai-runtime").json()["providerId"]
            for case_id, (source, _) in approved_sources().items():
                response = client.post(
                    "/api/v1/plan-extractions",
                    headers={"Idempotency-Key": f"r17-invalid-{case_id}"},
                    json={"providerId": provider_id, "sourceText": source, "expectedRevision": 0},
                )
                assert response.status_code == 202
                operation_id = response.json()["operationId"]
                for _ in range(100):
                    result = client.get(f"/api/v1/plan-extractions/{operation_id}").json()
                    if result["status"] not in {"QUEUED", "RUNNING"}:
                        break
                assert result["status"] == "INVALID_OUTPUT"
                assert result["diagnosticStatus"] == "RECORDED"
            runtime = app.state.runtime_lifecycle
            scheduler = runtime._runtime._scheduler
            pipeline = runtime._runtime._run_deadline.__self__._pipeline
            assert pipeline is not None
            for minute in range(12, 27):
                clock.current = datetime(2026, 9, 15, 10, minute, 12, tzinfo=SHANGHAI)
                deadline = scheduler.next_deadline()
                assert deadline.bar_end == clock.now().replace(second=0)
                client.portal.call(runtime._runtime._run_deadline, deadline)
            assert budget.snapshot()["attempts"] == {
                "trade_cal": 1,
                "idx_mins": 5,
                "index_daily": 5,
                "rt_idx_min_daily": 30,
            }
            assert budget.snapshot()["totalAttempts"] == 41
            assert budget.snapshot()["deniedBeforeNetwork"] == 0
            assert [name for sdk in created for name, _ in sdk.calls].count(
                "rt_idx_min_daily"
            ) == 30
            assert all(
                snapshot.health is not MarketIndexHealth.LIVE
                if persistent_lag
                else snapshot.health is MarketIndexHealth.LIVE
                for snapshot in pipeline.index_service.latest_snapshots().values()
            )

            async def activation_state():
                return await plans.get_plan_activation_state(symbol="003043.SZ")

            assert client.portal.call(activation_state).active is False
    diagnostics = [
        json.loads(line)
        for line in database.with_suffix(".ai-extraction-diagnostics.jsonl")
        .read_text("utf-8")
        .splitlines()
    ]
    assert len(diagnostics) == 3
    assert all(item["status"] == "INVALID_OUTPUT" for item in diagnostics)
    assert sent == list(approved_sources())
    assert ai_budget.snapshot()["totalAttempts"] == 3


def test_r17_missing_index_daily_cache_denies_extra_physical_starts(
    tmp_path: Path, monkeypatch
) -> None:
    """SIMULATED empty daily frames cannot convert a stale index into LIVE."""
    from scripts.r14_bounded_acceptance import _session_budgets
    from scripts.r17_bounded_acceptance import MARKET_CAPS

    import trade_plan_monitor.runtime.production as production

    clock = ControlledClock(datetime(2026, 9, 15, 10, 25, 12, tzinfo=SHANGHAI))
    config = _write_configuration_and_evidence(
        tmp_path, observed_at=clock.now(), include_index=True
    )
    database = tmp_path / "monitor.sqlite3"
    engine, work_factory = _work_factory(database, clock)
    upgrade_database(engine)
    stop_calls: list[bool] = []
    ai_budget, market_budget = _session_budgets(
        lambda: stop_calls.append(True), market_caps=MARKET_CAPS
    )

    class MissingDailySDK(QuerySDK):
        def _index_daily(self, kwargs: dict[str, object]) -> pd.DataFrame:
            return pd.DataFrame()

    created: list[MissingDailySDK] = []

    def make_client(_settings: object) -> MissingDailySDK:
        sdk = MissingDailySDK(clock, ())
        created.append(sdk)
        return sdk

    monkeypatch.setattr(
        production,
        "create_tushare_client",
        _guarded_market_factory(make_client, MarketBudget(market_budget)),
    )
    pace = VirtualPace()
    controller = create_live_tushare_request_controller(
        clock=clock, monotonic=pace.monotonic, pace_sleep=pace.sleep
    )
    pipeline = ProductionMonitorPipeline(
        configuration=load_application_config(config).tushare,
        certification_directory=tmp_path / "data/live-certification",
        stock_certification=create_stock_certification(
            observed_at=clock.now(),
            endpoint_url=ENDPOINT,
            capabilities=_ready_stock_capabilities(),
            source_time_label=SourceTimeLabel.START,
        ),
        clock=clock,
        request_controller=controller,
        unit_of_work_factory=work_factory,
        runtime_generation=uuid4(),
        publisher=lambda _event: None,
    )
    scheduler = MarketSessionScheduler(clock=clock, is_open_on=lambda _date: True)

    async def scenario() -> None:
        try:
            previous = None
            for minute in (25, 26, 30, 31):
                clock.current = datetime(2026, 9, 15, 10, minute, 12, tzinfo=SHANGHAI)
                deadline = scheduler.next_deadline(after=previous)
                assert deadline is not None
                try:
                    await pipeline.run_deadline(deadline)
                except BudgetDenied:
                    pass
                previous = deadline.due_at
                if market_budget.snapshot()["stopped"]:
                    break
            assert market_budget.snapshot()["deniedBeforeNetwork"] == 5
            assert market_budget.snapshot()["attempts"] == {
                "idx_mins": 5,
                "rt_idx_min_daily": 5,
                "index_daily": 5,
            }
            assert market_budget.snapshot()["attempts"].get("index_daily") == 5
            assert [name for sdk in created for name, _ in sdk.calls].count("index_daily") == 5
            assert stop_calls
            with pytest.raises(BudgetDenied):
                ai_budget.admit("LITERAL")
            assert all(
                snapshot.health is not MarketIndexHealth.LIVE
                for snapshot in pipeline.index_service.latest_snapshots().values()
            )
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())
