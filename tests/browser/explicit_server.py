"""Isolated R12 browser server: real Web/SQLite/scheduler, fake provider boundaries.

Run with the Playwright explicit-sqlite spec. No active plan, review or inventory
is seeded. The test-only control route advances only clock/market input facts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from datetime import timedelta
from pathlib import Path

import httpx
import pandas as pd
import uvicorn
from fastapi import Request
from tests.integration.test_explicit_plan_review_api import _draft_payload
from tests.integration.test_explicit_runtime_production import (
    ENDPOINT,
    TARGET,
    _ExplicitPipelineSDK,
)
from tests.integration.test_source_treatment_review_api import SOURCE, _literal_mapping

import trade_plan_monitor.runtime.production as production
import trade_plan_monitor.web.ai_service as ai_service
import trade_plan_monitor.web.monitor_composition as monitoring
from trade_plan_monitor.ai.models import ExplicitPlanDraft
from trade_plan_monitor.live_profiles import create_stock_certification, write_live_certification
from trade_plan_monitor.market_data.models import ProviderCapabilities, ProviderCapabilityStatus
from trade_plan_monitor.market_data.sessions import SourceTimeLabel
from trade_plan_monitor.state.database import create_sqlite_engine, upgrade_database
from trade_plan_monitor.web.ai_service import ConfiguredAIWebLifecycle
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle


class ControlledClock:
    def __init__(self):
        self.current = TARGET - timedelta(seconds=45)
        self.changed = asyncio.Event()
        self.deadlines = []

    def now(self):
        return self.current

    async def sleep_until(self, deadline):
        self.deadlines.append(deadline.isoformat())
        while self.current < deadline:
            self.changed.clear()
            await self.changed.wait()
        await asyncio.sleep(0)

    def advance(self, current):
        if current < self.current:
            raise ValueError("test clock cannot go backwards")
        self.current = current
        self.changed.set()


class MarketSDK(_ExplicitPipelineSDK):
    def __init__(self, clock):
        super().__init__(current_volume=59)
        self.clock = clock

    def __getattr__(self, name):
        if name not in {"rt_min", "rt_min_daily"}:
            return super().__getattr__(name)

        def request(**kwargs):
            self.calls.append(name)
            # Fixed minute tape: previous five completed volumes average 200.
            # The oldest 299 rolls out when the next 299 rolls in: mean stays 200.
            volumes = [100, 299, 175, 175, 175, 176, 299, 300, 100, 100, 100]
            prices = [990] * 8 + [1080, 949, 990]
            start = TARGET.replace(hour=9, minute=30)
            end = self.clock.now().replace(second=0, microsecond=0)
            rows = []
            for offset in range(int((end - start).total_seconds() // 60)):
                bucket, minute = divmod(offset, 5)
                volume = volumes[bucket] if bucket < len(volumes) else 100
                price = prices[bucket] if bucket < len(prices) else 990
                value = f"{price / 100:.2f}"
                rows.append(
                    {
                        "ts_code": "003043.SZ",
                        "freq": "1MIN",
                        "time": (start + timedelta(minutes=offset)).strftime("%Y-%m-%d %H:%M:%S"),
                        "open": value,
                        "high": value,
                        "low": value,
                        "close": value,
                        "vol": str(volume // 5 + (volume % 5 if minute == 4 else 0)),
                        "amount": "0",
                    }
                )
            return pd.DataFrame(rows[-1:] if name == "rt_min" else rows)

        return request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    assert args.port != 8765
    root = Path(tempfile.mkdtemp(prefix="tpm-r12-browser-")).resolve()
    database = root / "monitor.sqlite3"
    config = root / "config" / "app.yaml"
    config.parent.mkdir()
    config.write_text(
        "tushare:\n  api_url: https://example.test\n  token: offline-test-token\n"
        "ai:\n  profile: OPENAI_COMPATIBLE\n  display_name: R12 isolated AI\n"
        "  base_url: https://ai.example.test\n  model: isolated-literal-v3\n"
        "  api_key: offline-test-key\n  max_retries: 0\n",
        encoding="utf-8",
    )
    clock = ControlledClock()
    sdk = MarketSDK(clock)
    engine = create_sqlite_engine(database)
    upgrade_database(engine)
    # Seed calendar and prior completed bars only; all plans/reviews/inventory
    # are created later through ordinary browser controls.
    from tests.integration.test_explicit_runtime_production import _work

    with _work(engine) as work:
        from datetime import date

        from trade_plan_monitor.market_data.models import TradingDay

        work.references.upsert_trading_days(
            (
                TradingDay(
                    exchange="SZSE",
                    cal_date=TARGET.date(),
                    is_open=True,
                    previous_trade_date=date(2026, 9, 11),
                ),
            )
        )
        from decimal import Decimal

        from trade_plan_monitor.market_data.models import MinuteBar

        work.history.upsert_minutes(
            tuple(
                MinuteBar(
                    symbol="003043.SZ",
                    bar_end=TARGET - timedelta(minutes=offset),
                    open_fen=990,
                    high_fen=990,
                    low_fen=990,
                    close_fen=990,
                    volume_shares=59,
                    amount_yuan=Decimal("0"),
                    received_at=clock.now(),
                )
                for offset in (4, 3, 2, 1)
            )
        )
        for index, volume in enumerate((299, 175, 175, 175, 176)):
            from decimal import Decimal

            from trade_plan_monitor.market_data.aggregation import FiveMinuteBar

            work.history.upsert_five_minute(
                **FiveMinuteBar(
                    symbol="003043.SZ",
                    bar_end=TARGET - timedelta(minutes=(5 - index) * 5),
                    open_fen=990,
                    high_fen=990,
                    low_fen=990,
                    close_fen=990,
                    volume_shares=volume,
                    amount_yuan=Decimal("0"),
                ).model_dump()
            )
        work.commit()
    engine.dispose()
    evidence = create_stock_certification(
        observed_at=clock.now(),
        endpoint_url=ENDPOINT,
        capabilities=ProviderCapabilities(
            **{key: ProviderCapabilityStatus.READY for key in ProviderCapabilities.model_fields}
        ),
        source_time_label=SourceTimeLabel.START,
    )
    write_live_certification(root / "data/live-certification/tushare-stock-live.json", evidence)
    draft = ExplicitPlanDraft.model_validate_json(json.dumps(_draft_payload(complete=False)))
    mapping = _literal_mapping(draft)
    output = {
        "draft": draft.model_dump(mode="json"),
        "mapping_version": "plan-mapping-v1",
        "source_clauses": [item.model_dump(mode="json") for item in mapping.source_clauses],
        "field_bindings": [item.model_dump(mode="json") for item in mapping.field_bindings],
        "assumptions": [],
        "warnings": [],
    }
    ai_requests = []

    def fake_ai(request):
        assert request.url.host == "ai.example.test"
        body = json.loads(request.content)
        assert json.dumps(SOURCE, ensure_ascii=False) in body["messages"][-1]["content"]
        ai_requests.append({"path": request.url.path, "model": body["model"]})
        return httpx.Response(
            200,
            json={
                "id": "r12-offline",
                "object": "chat.completion",
                "created": 1,
                "model": "isolated-literal-v3",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(output, ensure_ascii=False),
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200},
            },
        )

    production.create_tushare_client = lambda _config: sdk
    monitoring.SystemClock = lambda: clock
    ai_service._now = clock.now
    plans = PersistentPlanWebLifecycle(database_path=database, clock=clock.now)
    ai = ConfiguredAIWebLifecycle(
        config_path=config,
        review_store=plans,
        client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(fake_ai), trust_env=False
        ),
    )
    composition = monitoring.create_monitor_composition(config_path=config, database_path=database)
    app = create_app(
        runtime_factory=lambda: composition,
        plan_lifecycle_factory=lambda: plans,
        ai_lifecycle_factory=lambda: ai,
        bind_port=args.port,
        static_directory=Path(__file__).resolve().parents[2] / "web/dist",
    )
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning")
    )

    @app.post("/_test/shutdown")
    async def shutdown():
        server.should_exit = True
        return {"stopping": True}

    @app.get("/_test/isolation")
    async def isolation():
        return {
            "root": str(root),
            "database": str(database),
            "config": str(config),
            "provider": "IN_PROCESS_FAKE",
            "now": clock.now().isoformat(),
            "sdkCalls": sdk.calls,
            "aiRequests": ai_requests,
            "deadlines": clock.deadlines,
        }

    @app.post("/_test/advance")
    async def advance(request: Request):
        from datetime import datetime

        body = await request.json()
        target = datetime.fromisoformat(body["now"])
        while clock.now() < target:
            clock.advance(min(clock.now() + timedelta(minutes=1), target))
            for _ in range(1000):
                await asyncio.sleep(0.01)
                if clock.deadlines and datetime.fromisoformat(clock.deadlines[-1]) > clock.now():
                    break
            else:
                raise RuntimeError("scheduler did not complete the released deadline")
        return {"now": clock.now().isoformat()}

    spa = next(route for route in app.router.routes if getattr(route, "name", None) == "local-spa")
    app.router.routes.remove(spa)
    app.router.routes.append(spa)

    print(json.dumps({"port": args.port, "root": str(root), "database": str(database)}), flush=True)
    server.run()


if __name__ == "__main__":
    main()
