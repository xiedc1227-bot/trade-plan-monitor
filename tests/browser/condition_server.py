"""Isolated offline daily browser fixture; real APIs, SQLite and daily participant."""

import argparse
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import uvicorn
from pydantic_core import to_json
from tests.integration.test_daily_plan_chain import (
    FRIDAY,
    SH,
    SYMBOL,
    TUESDAY,
    WEDNESDAY,
    Chain,
    OfflineRuntime,
)
from tests.integration.test_unified_runtime import current_plan, minute_inputs
from tests.integration.test_web_api import _runtime_health_payload
from tests.unit.test_ai_plan_extraction_v4 import _config

from trade_plan_monitor.ai.composition import ConfiguredAIProviderBinding
from trade_plan_monitor.ai.daily_review import daily_contract_bindings
from trade_plan_monitor.ai.models import AIProviderProfile
from trade_plan_monitor.ai.provider import AIUsage, RawAIResponse
from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft
from trade_plan_monitor.market_data.aggregation import aggregate_five_minute_bar
from trade_plan_monitor.market_data.daily_data import DailyExecutionQuote
from trade_plan_monitor.market_data.models import MinuteBar
from trade_plan_monitor.runtime.status_authority import RuntimeReadAuthority
from trade_plan_monitor.state.models import TradingCalendar
from trade_plan_monitor.web.ai_service import ConfiguredAIWebLifecycle
from trade_plan_monitor.web.alert_service import PersistentAlertOperationService
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.routers.ai import ConfiguredAIRuntimeView
from trade_plan_monitor.web.routers.health import RuntimeHealthResponse
from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService
from trade_plan_monitor.web.runtime_status_websocket import RuntimeStatusEventStream


class NoNetworkAI(ConfiguredAIWebLifecycle):
    """Only the external provider is injected; the extraction lifecycle stays real."""

    async def start(self):
        config = _config().model_copy(update={"prompt_version": (
            "plan-extract-v11")})
        owner = self

        class Provider:
            async def extract_plan(self, request):
                raw = UnifiedPlanDraft.from_executable(owner.plan).model_dump(mode="json")
                output = {
                    "draft": raw,
                    "bindings": [b.model_dump(mode="json") for b in daily_contract_bindings(
                        UnifiedPlanDraft.from_executable(owner.plan))],
                    "clauses": [
                        {
                            "clause_id": c.clause_id,
                            "start": c.start,
                            "end": c.end,
                            "excerpt": c.excerpt,
                            "disposition": "UNRESOLVED",
                            "paths": [],
                            "reason": "Synthetic source needs independent human policy review",
                        }
                        for c in server_source_clauses(owner.source)
                    ],
                }
                return RawAIResponse(
                    request_id=request.request_id,
                    provider_id=config.provider_id,
                    model=config.model,
                    content=json.dumps(output),
                    finish_reason="stop",
                    usage=AIUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20),
                    attempts=1,
                )

        self._client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: (_ for _ in ()).throw(AssertionError("Network prohibited"))
            )
        )
        self._binding = ConfiguredAIProviderBinding(
            profile=AIProviderProfile.OPENAI_COMPATIBLE, config=config, provider=Provider()
        )
        self._bindings = {config.provider_id: self._binding}
        return {"provider": "OFFLINE_SYNTHETIC"}

    async def get_configured_ai(self):
        return ConfiguredAIRuntimeView(
            provider_id=self._binding.config.provider_id,
            display_name="离线人工补充测试",
            base_url="https://example.invalid",
            model="offline",
            configured=True,
            enabled=True,
            max_input_chars=200000,
            max_output_tokens=16384,
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--linked", action="store_true")
    parser.add_argument("--exception", choices=("WEAK_MINIMUM", "BROKEN_STRONG"))
    parser.add_argument("--p2", action="store_true")
    parser.add_argument("--p2-economics", choices=("REQUIRED", "PREVIEW_ONLY"), default="REQUIRED")
    args = parser.parse_args()
    with TemporaryDirectory(prefix="tpm-daily-browser-") as directory:
        root = Path(directory)
        ai = NoNetworkAI(config_path=root / "unused-offline.yaml")

        def health():
            raw = _runtime_health_payload()
            raw.update(
                observedAt=chain.now,
                startedAt=chain.now,
                lastCompletedMinute=None,
                lastCompletedMinuteAgeSeconds=None,
                latestEvaluationAt=None,
                latestEvaluationAgeSeconds=None,
                providers=[],
                nextPollAt=None,
            )
            return RuntimeHealthResponse.model_validate_json(to_json(raw))

        reader = RuntimeStatusReadService(
            lambda: chain.plans._session_factory(),
            lambda: RuntimeReadAuthority(
                token="offline-shell",
                lifecycle="STOPPED",
                progress=None,
                health=health(),
                owner_absent=True,
            ),
            clock=lambda: chain.now,
        )
        chain = Chain(
            root,
            bind_port=args.port,
            static_directory=None,
            ai_lifecycle_factory=lambda: ai,
            read_service=None,
        )
        plan_data = current_plan().model_dump(mode="json")
        plan_data["alert_rules"] = [
            {
                "kind": "RISK_ALERT",
                "rule_id": "five-minute-low-risk",
                "confirmation": {"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
                "condition": {
                    "type": "MINUTE_CLOSE_BELOW",
                    "timeframe_minutes": 5,
                    "price_fen": 950,
                },
            }
        ]
        chain.plan = UnifiedTradePlan.model_validate(plan_data)
        if args.linked:
            from tests.unit.test_market_linkage_contract import linked_payload

            from trade_plan_monitor.domain.market_linkage_models import MarketLinkedTradePlan
            linked = linked_payload()
            linked.update(risk_branches=[], alert_rules=plan_data["alert_rules"])
            linked["position"]["max_qty"] = 1000
            linked["ordinary_rules"][0].update(validity={"mode": "PLAN_ACTIVE"},
                independent_signal={"mode": "ONCE_PER_RULE"}, condition={
                    "type": "DAILY_PRICE_IN_RANGE", "field": "close", "offset": 0,
                    "range": linked["levels"]["low_buy"]})
            chain.plan = MarketLinkedTradePlan.model_validate(linked)
        if args.exception:
            from tests.unit.test_market_exception_contract import exception_payload

            from trade_plan_monitor.domain.market_exception_models import MarketExceptionTradePlan
            raw = exception_payload()
            chain.route = args.exception
            raw.update(risk_branches=[], alert_rules=plan_data["alert_rules"])
            raw["position"]["max_qty"] = 1000
            zone = dict(low_fen=100, high_fen=200, include_low=True, include_high=True)
            raw["levels"]["low_buy"] = zone
            raw["ordinary_rules"][0].update(validity={"mode": "PLAN_ACTIVE"},
                independent_signal={"mode": "ONCE_PER_RULE"}, condition={
                    "type": "DAILY_PRICE_IN_RANGE", "field": "close", "offset": 0,
                    "range": zone})
            raw["ordinary_rules"][0]["quantity_policy"]["base_quantity"] = (
                100 if chain.route == "WEAK_MINIMUM" else 500)
            chain.plan = MarketExceptionTradePlan.model_validate(raw)
        if args.p2:
            from tests.unit.test_p2_composition import fixture
            chain.plan, _ = fixture(200 if chain.route == "WEAK_MINIMUM" else 1000, chain.route)
            from tests.integration.test_p2_chain import with_economics
            chain.plan = with_economics(chain.plan, args.p2_economics)
        ai.plan = chain.plan
        ai.source = (
            "合成离线条件计划：日线收盘低于40元且完整5分钟收盘低于40元时，确认模拟买入100股。"
            "完整5分钟收盘低于9.50元只作风险提醒，不卖出，也不改变模拟持仓。"
            "公告与基本面仅在生成计划时由用户审核，不参与条件监控。"
        )
        if args.linked:
            from trade_plan_monitor.domain.market_linkage_definitions import (
                EXPANDED_LINKAGE_POLICY_ZH,
            )
            ai.source = "合成离线大盘联动计划，Q0 为 300 股。" + "。".join(
                EXPANDED_LINKAGE_POLICY_ZH.values()
            )
        if args.exception:
            from trade_plan_monitor.domain.market_linkage_definitions import (
                EXPANDED_EXCEPTION_POLICY_ZH,
            )
            ai.source = (
                "合成离线例外计划。weak_minimum PER_OCCURRENCE；"
                "broken_strong PER_OCCURRENCE；" + "。".join(
                    EXPANDED_EXCEPTION_POLICY_ZH.values())
            )
        ai._review_store = chain.plans
        app = create_app(
            runtime_factory=lambda: OfflineRuntime(chain),
            plan_lifecycle_factory=lambda: chain.plans,
            alert_service=PersistentAlertOperationService(
                unit_of_work_factory=chain.plans._unit_of_work, clock=lambda: chain.now,
            ),
            bind_port=args.port,
            static_directory=Path(__file__).resolve().parents[2] / "web/dist",
            ai_lifecycle_factory=lambda: ai,
            read_service=reader,
            websocket_service=RuntimeStatusEventStream(
                unit_of_work_factory=chain.plans._unit_of_work,
                read_service=reader,
                heartbeat_interval_seconds=1,
            ),
            monitor_contract_version=2,
        )
        chain.app = app
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning")
        )

        @app.get("/_test/isolation")
        def isolation():
            return {
                "root": str(root),
                "database": str(root / "daily.sqlite"),
                "provider": "OFFLINE_SYNTHETIC",
            }

        @app.post("/_test/setup")
        def setup():
            with chain.plans._unit_of_work() as work:
                pairs = (
                    (date(2026, 9, 17), FRIDAY),
                    (FRIDAY, TUESDAY),
                    (TUESDAY, WEDNESDAY),
                )
                if args.exception:
                    history = tuple(FRIDAY-timedelta(days=i) for i in reversed(range(60)))
                    pairs = zip((history[0]-timedelta(days=1), *history, TUESDAY),
                                (*history, TUESDAY, WEDNESDAY), strict=True)
                for previous, day in pairs:
                    work.daily.session.add(
                        TradingCalendar(
                            exchange="SSE", cal_date=day, is_open=True, previous_trade_date=previous
                        )
                    )
                work.commit()
            return {"source": ai.source}

        @app.post("/_test/confirm-close")
        def close():
            from trade_plan_monitor.domain.plan_codec import load_plan_json

            with chain.plans._unit_of_work() as work:
                active = work.plans.get_active(SYMBOL)
                details = work.plans.get_version_details(active.plan_version_id)
                chain.plan = load_plan_json(details.payload_json)
                chain.version = {"id": details.id, "contentHash": details.content_hash}
            if args.exception:
                from tests.integration.test_market_exception_runtime import exception_inputs
                return chain.runtime.run_inputs(
                    plan=chain.plan, inputs=exception_inputs(chain)).model_dump(mode="json")
            if args.linked:
                from tests.integration.test_market_linkage_runtime import linked_inputs
                return chain.runtime.run_inputs(
                    plan=chain.plan, inputs=linked_inputs(chain)
                ).model_dump(mode="json")
            chain.evaluate(series=chain.series(), official=FRIDAY)
            for kind in ("PRICE_STRUCTURE", "VOLUME_OR_CANDLE", "TECHNICAL"):
                chain.post(
                    "plan-facts",
                    {
                        "planVersionId": chain.version["id"],
                        "contentHash": chain.version["contentHash"],
                        "factId": "synthetic-" + kind,
                        "kind": kind,
                        "tradeDate": str(FRIDAY),
                        "evidence": (
                            "Synthetic complete official technical evidence "
                            "independently verified"
                        ),
                        "expectedRevision": 0,
                    },
                )
            return chain.evaluate(series=chain.series(), official=FRIDAY).model_dump(mode="json")

        @app.post("/_test/live")
        def live():
            chain.now = datetime(2026, 9, 22, 9, 35, tzinfo=SH)
            with chain.plans._unit_of_work() as work:
                active = work.plans.get_active(SYMBOL)
                details = work.plans.get_version_details(active.plan_version_id)
                from trade_plan_monitor.domain.plan_codec import load_plan_json

                chain.plan = load_plan_json(details.payload_json)
                chain.version = {"id": details.id, "contentHash": details.content_hash}
            if args.exception:
                from tests.integration.test_market_exception_runtime import exception_inputs
                return chain.runtime.run_inputs(
                    plan=chain.plan, inputs=exception_inputs(chain)).model_dump(mode="json")
            if args.linked:
                from tests.integration.test_market_linkage_runtime import linked_inputs
                return chain.runtime.run_inputs(
                    plan=chain.plan, inputs=linked_inputs(chain)
                ).model_dump(mode="json")
            return chain.runtime.run_inputs(
                plan=chain.plan, inputs=minute_inputs(chain, series=chain.series())
            ).model_dump(mode="json")

        @app.post("/_test/p2-quote/{price}")
        def p2_quote(price: int):
            from tests.integration.test_market_exception_runtime import exception_inputs
            if not args.p2:
                raise ValueError("P2 fixture required")
            chain.now += timedelta(seconds=1)
            inputs = exception_inputs(chain)
            inputs = inputs.model_copy(update={"quote": inputs.quote.model_copy(
                update={"price_fen": price})})
            return chain.runtime.run_inputs(plan=chain.plan, inputs=inputs).model_dump(mode="json")

        @app.post("/_test/exception-correction")
        def exception_correction():
            if not args.exception:
                raise ValueError("exception fixture required")
            from tests.integration.test_market_exception_runtime import exception_inputs
            return chain.runtime.run_inputs(plan=chain.plan,
                inputs=exception_inputs(chain, correction=True)).model_dump(mode="json")

        @app.post("/_test/linked-broken")
        def linked_broken():
            from tests.integration.test_market_linkage_runtime import linked_inputs

            from trade_plan_monitor.market_data.daily_data import DailySeries
            from trade_plan_monitor.market_index.snapshots import build_market_index_snapshot
            chain.now += timedelta(seconds=1)
            inputs = linked_inputs(chain)
            source = inputs.linked_index
            bars = []
            for i, bar in enumerate(source.official_daily_bars):
                points = Decimal(200-i-(2 if i == 59 else 0))
                bars.append(bar.model_copy(update={"open_points": points, "high_points": points+1,
                    "low_points": points-1, "close_points": points, "provider_revision": 2}))
            changed = build_market_index_snapshot(index_code=source.index_code,
                decision_cutoff=source.decision_cutoff, requests=source.fact_requests,
                five_minute_bars=source.five_minute_bars, official_daily_bars=tuple(bars),
                content_revision=2, observed_at=chain.now, observed_no_later_than=chain.now)
            base = inputs.series.bars[0]
            stock = tuple(
                base.model_copy(update={"bar_id": "linked-" + str(day), "trade_date": day})
                for day in inputs.session_dates
                if FRIDAY - timedelta(days=20) <= day <= FRIDAY
            )
            series = DailySeries.model_validate({**inputs.series.model_dump(),
                "bars": stock, "session_dates": inputs.session_dates})
            return chain.runtime.run_inputs(plan=chain.plan, inputs=inputs.model_copy(update={
                "linked_index": changed, "series": series})).model_dump(mode="json")

        @app.post("/_test/risk-reminder")
        def risk_reminder():
            chain.now = datetime(2026, 9, 22, 9, 35, 15, tzinfo=SH)
            baseline = minute_inputs(chain, series=chain.series())
            chain.now = datetime(2026, 9, 22, 9, 40, 15, tzinfo=SH)
            target = chain.now.replace(second=0)
            prefix = tuple(MinuteBar(
                symbol=SYMBOL, bar_end=target - timedelta(minutes=4 - index),
                open_fen=949, high_fen=949, low_fen=949, close_fen=949,
                volume_shares=100, amount_yuan=Decimal("0"), received_at=chain.now,
            ) for index in range(5))
            inputs = baseline.model_copy(update={
                "evaluated_at": chain.now,
                "minute_target": target,
                "minute_prefix": prefix,
                "five_minute_bars": (aggregate_five_minute_bar(
                    prefix, bucket_end=target, is_open=True,
                ),),
                "quote": DailyExecutionQuote(
                    symbol=SYMBOL, price_fen=949, quote_at=target,
                    available_at=chain.now, evaluated_at=chain.now,
                    tradable=True, special_state_verified=True, liquidity_available=True,
                ),
            })
            return chain.runtime.run_inputs(plan=chain.plan, inputs=inputs).model_dump(mode="json")

        @app.post("/_test/risk-close")
        def risk_close():
            chain.now = datetime(2026, 9, 22, 16, tzinfo=SH)
            return chain.evaluate(series=chain.series(TUESDAY), official=TUESDAY).model_dump(
                mode="json"
            )

        @app.post("/_test/risk-next-session")
        def risk_next_session():
            chain.now = datetime(2026, 9, 23, 10, tzinfo=SH)
            return chain.evaluate(series=chain.series(TUESDAY), price=3970).model_dump(mode="json")

        @app.post("/_test/expiry")
        def expiry():
            chain.now = chain.now.replace(hour=15, minute=0)
            return chain.evaluate(series=chain.series(TUESDAY), price=3970).model_dump(mode="json")

        @app.post("/_test/shutdown")
        def shutdown():
            server.should_exit = True
            return {"stopping": True}

        app.router.routes.sort(
            key=lambda route: not getattr(route, "path", "").startswith("/_test/")
        )
        server.run()


if __name__ == "__main__":
    main()
