"""Isolated R12 browser server: real Web/SQLite/scheduler, fake provider boundaries.

Run with the Playwright explicit-sqlite spec. No active plan, review or inventory
is seeded at startup. Test controls advance clock/market facts or install a real
legacy sibling through the existing domain repositories.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import tempfile
from contextlib import ExitStack, closing
from datetime import datetime, timedelta
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
from trade_plan_monitor.web.app import create_app, create_production_app
from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle


class ControlledClock:
    def __init__(self):
        self.current = TARGET - timedelta(seconds=45)
        self.changed = asyncio.Event()
        self.deadlines = []
        self.monotonic_time = 0.0

    def now(self):
        return self.current

    def monotonic(self):
        return self.monotonic_time

    async def sleep_until(self, deadline):
        self.deadlines.append(deadline.isoformat())
        while self.current < deadline:
            self.changed.clear()
            await self.changed.wait()
        await asyncio.sleep(0)

    def advance(self, current):
        if current < self.current:
            raise ValueError("test clock cannot go backwards")
        self.monotonic_time += (current - self.current).total_seconds()
        self.current = current
        self.changed.set()


def _seed_legacy_index_history(work):
    """Retain unavailable legacy chart history without granting live proof."""
    from decimal import Decimal

    from trade_plan_monitor.market_index.identity import MarketIndexCode
    from trade_plan_monitor.market_index.models import (
        MarketIndexBar,
        MarketIndexHealth,
        MarketIndexInterval,
        MarketIndexSourceKind,
    )
    from trade_plan_monitor.market_index.snapshots import build_market_index_snapshot

    cutoff = TARGET - timedelta(minutes=10)
    for code in ("000001.SH", "399001.SZ", "399006.SZ", "000688.SH"):
        bar = MarketIndexBar(
            index_code=MarketIndexCode(code),
            interval=MarketIndexInterval.FIVE_MINUTE,
            bar_at=cutoff,
            open_points=Decimal("1000"),
            high_points=Decimal("1000"),
            low_points=Decimal("1000"),
            close_points=Decimal("1000"),
            volume=Decimal("1"),
            amount=Decimal("1"),
            observed_at=cutoff + timedelta(seconds=2),
            source_kind=MarketIndexSourceKind.PROVISIONAL,
            provider_revision=1,
        )
        snapshot = build_market_index_snapshot(
            index_code=bar.index_code,
            decision_cutoff=cutoff,
            requests=(),
            five_minute_bars=(bar,),
            official_daily_bars=(),
            content_revision=1,
            observed_at=bar.observed_at,
            observed_no_later_than=bar.observed_at,
        )
        assert snapshot.health is MarketIndexHealth.BLOCKED
        assert not snapshot.indicator_facts
        work.projections.put_market_index_snapshot(snapshot, provider_content_revision=1)
        work.projections.advance_market_index_head(snapshot, provider_content_revision=1)


class MarketSDK(_ExplicitPipelineSDK):
    def __init__(self, clock, *, repeat_probe_tape=False, persistent_risk_tape=False):
        super().__init__(current_volume=59)
        self.clock = clock
        self.repeat_probe_tape = repeat_probe_tape
        self.persistent_risk_tape = persistent_risk_tape
        self.minute_cutoff = None
        self.legacy_sibling_enabled = False

    def __getattr__(self, name):
        if self.legacy_sibling_enabled and name in {"stk_limit", "daily"}:
            from tests.integration.test_live_pipeline_acceptance import OfflineSDK

            reference_sdk = OfflineSDK(self.clock, ("600000.SH",))

            def reference_request(**kwargs):
                self.calls.append(name)
                return getattr(reference_sdk, name)(**kwargs)

            return reference_request
        if self.legacy_sibling_enabled and name == "stk_mins":
            def missing_history(**kwargs):
                self.calls.append(name)
                return pd.DataFrame(columns=(
                    "ts_code", "trade_time", "open", "high", "low", "close", "vol", "amount",
                ))

            return missing_history
        if name not in {"rt_min", "rt_min_daily"}:
            return super().__getattr__(name)

        def request(**kwargs):
            self.calls.append(name)
            # Fixed minute tape: previous five completed volumes average 200.
            # The oldest 299 rolls out when the next 299 rolls in: mean stays 200.
            volumes = [100, 299, 175, 175, 175, 176, 299, 300, 100, 100, 100]
            prices = [990] * 8 + [1080, 949, 990]
            if self.persistent_risk_tape:
                prices[10:] = [949]
            if self.repeat_probe_tape:
                # Separate synthetic restart probe: a later qualifying BUY bar.
                volumes.append(301)
                prices.append(990)
            start = TARGET.replace(hour=9, minute=30)
            end = self.clock.now().replace(second=0, microsecond=0)
            if self.minute_cutoff is not None:
                end = min(end, self.minute_cutoff)
            rows = []
            for offset in range(int((end - start).total_seconds() // 60)):
                bucket, minute = divmod(offset, 5)
                volume = volumes[bucket] if bucket < len(volumes) else 100
                price = prices[bucket] if bucket < len(prices) else (
                    949 if self.persistent_risk_tape else 990
                )
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
    parser.add_argument("--resume-root", type=Path)
    parser.add_argument("--initial-now", type=datetime.fromisoformat)
    parser.add_argument("--repeat-probe-tape", action="store_true")
    parser.add_argument("--persistent-risk-tape", action="store_true")
    parser.add_argument("--monitor-contract-version", type=int, choices=(1, 2), default=1)
    parser.add_argument("--normal-entry", action="store_true")
    args = parser.parse_args()
    if args.normal_entry:
        args.monitor_contract_version = 2
    assert args.port != 8765
    root = (
        args.resume_root.resolve()
        if args.resume_root
        else Path(tempfile.mkdtemp(prefix="tpm-r12-browser-")).resolve()
    )
    if args.resume_root:
        assert root.parent == Path(tempfile.gettempdir()).resolve()
        assert root.name.startswith("tpm-r12-browser-")
        assert (root / "monitor.sqlite3").is_file()
    database = root / "monitor.sqlite3"
    config = root / "config" / "app.yaml"
    config.parent.mkdir(exist_ok=True)
    config.write_text(
        "tushare:\n  api_url: https://example.test\n  token: offline-test-token\n"
        "ai:\n  profile: OPENAI_COMPATIBLE\n  display_name: R12 isolated AI\n"
        "  base_url: https://ai.example.test\n  model: isolated-literal-v3\n"
        "  api_key: offline-test-key\n  max_retries: 0\n",
        encoding="utf-8",
    )
    clock = ControlledClock()
    if args.initial_now:
        assert args.initial_now.tzinfo is not None
        clock.current = args.initial_now
    if args.persistent_risk_tape:
        assert args.monitor_contract_version == 2
    sdk = MarketSDK(
        clock, repeat_probe_tape=args.repeat_probe_tape,
        persistent_risk_tape=args.persistent_risk_tape,
    )
    engine = create_sqlite_engine(database)
    upgrade_database(engine)
    # Seed calendar and prior completed bars only; all plans/reviews/inventory
    # are created later through ordinary browser controls.
    from tests.integration.test_explicit_runtime_production import _work

    if not args.resume_root:
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
            if args.monitor_contract_version == 1 and not args.normal_entry:
                _seed_legacy_index_history(work)
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
    stall_requested = False
    stall_entered, stall_release = asyncio.Event(), asyncio.Event()
    original_deadline = monitoring._ProductionRuntimeState.run_deadline

    async def controlled_deadline(state, deadline):
        nonlocal stall_requested
        if stall_requested:
            stall_requested = False
            owner = state._progress_owner()
            token = owner.begin_progress_step(timeout_seconds=15)
            stall_entered.set()
            await stall_release.wait()
            owner.complete_progress_step(token, next_wake_at=clock.now() + timedelta(seconds=30))
        return await original_deadline(state, deadline)

    if args.monitor_contract_version == 2:
        monitoring._ProductionRuntimeState.run_deadline = controlled_deadline
    ai_service._now = clock.now
    app_resources = ExitStack()
    if args.normal_entry:
        import trade_plan_monitor.web.plan_service as plan_service

        class ControlledPlanLifecycle(PersistentPlanWebLifecycle):
            def __init__(self, *, database_path, clock=None):
                super().__init__(database_path=database_path, clock=clock or sdk.clock.now)

        # Replace external transport and observation clocks, retaining normal
        # production factories, installed assets, and all owned lifespans.
        plan_service.PersistentPlanWebLifecycle = ControlledPlanLifecycle
        ai_service._default_client = lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(fake_ai), trust_env=False,
        )
        os.chdir(root)
        composition = None
        app = app_resources.enter_context(create_production_app(
            config_path=config, database_path=database, bind_port=args.port,
        ))
    else:
        plans = PersistentPlanWebLifecycle(database_path=database, clock=clock.now)
        ai = ConfiguredAIWebLifecycle(
            config_path=config,
            review_store=plans,
            client_factory=lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(fake_ai), trust_env=False
            ),
        )
        composition = monitoring.create_monitor_composition(
            config_path=config, database_path=database,
            monitor_contract_version=args.monitor_contract_version,
            progress_monotonic=clock.monotonic,
        )
        if args.monitor_contract_version == 2:
            # Only this offline fixture accelerates observation traffic.
            composition.websocket_service._heartbeat_interval_seconds = 0.2
        app = create_app(
            runtime_factory=lambda: composition,
            plan_lifecycle_factory=lambda: plans,
            ai_lifecycle_factory=lambda: ai,
            read_service=composition.read_service if args.monitor_contract_version == 2 else None,
            monitor_contract_version=args.monitor_contract_version,
            bind_port=args.port,
            static_directory=Path(__file__).resolve().parents[2] / (
                "web/dist-runtime-status"
                if args.monitor_contract_version == 2 else "web/dist-legacy-test"
            ),
        )

    def owned_composition():
        return app.state.runtime_lifecycle if args.normal_entry else composition
    server = uvicorn.Server(
        uvicorn.Config(
            app, host="127.0.0.1", port=args.port,
            log_level="info" if args.normal_entry else "warning",
        )
    )

    @app.post("/_test/shutdown")
    async def shutdown():
        stall_release.set()
        server.should_exit = True
        return {"stopping": True}

    @app.get("/_test/isolation")
    async def isolation():
        return {
            "root": str(root),
            "pid": os.getpid(),
            "resumed": bool(args.resume_root),
            "database": str(database),
            "config": str(config),
            "provider": "IN_PROCESS_FAKE",
            "entry": "NORMAL_PRODUCTION" if args.normal_entry else "INJECTED_FIXTURE",
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
            following = min(clock.now() + timedelta(minutes=1), target)
            if (args.normal_entry or args.monitor_contract_version == 1) and clock.deadlines:
                # Both installed and legacy owners can recover before a market duty.
                # Release each real installed wake instead of jumping over it.
                installed = datetime.fromisoformat(clock.deadlines[-1])
                if clock.now() < installed < following:
                    following = installed
            clock.advance(following)
            for _ in range(1000):
                await asyncio.sleep(0.01)
                if clock.deadlines and datetime.fromisoformat(clock.deadlines[-1]) > clock.now():
                    break
            else:
                raise RuntimeError("scheduler did not complete the released deadline")
        return {"now": clock.now().isoformat()}

    @app.get("/_test/source-truth")
    async def source_truth():
        if not args.normal_entry:
            raise RuntimeError("source truth probe requires the normal entry")
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
            return {
                table: sorted(connection.execute(f'SELECT * FROM "{table}"'), key=repr)
                for table in (
                    "active_plan", "plan_activation_state", "plan_version", "alert_event",
                )
            }

    @app.post("/_test/stall")
    async def stall():
        nonlocal stall_requested
        if args.monitor_contract_version != 2 or stall_entered.is_set():
            raise RuntimeError("isolated owner stall is unavailable")
        stall_requested = True
        owner = owned_composition()._runtime
        due = owner._scheduler.next_deadline(after=owner._last_deadline_at)
        if due is None:
            raise RuntimeError("isolated owner has no scheduled unit")
        clock.advance(max(clock.now(), due.due_at))
        await asyncio.wait_for(stall_entered.wait(), 10)
        clock.advance(clock.now() + timedelta(seconds=16))
        return {"state": "STALLED", "now": clock.now().isoformat()}

    @app.post("/_test/release")
    async def release():
        stall_release.set()
        return {"released": True}

    @app.post("/_test/legacy-sibling")
    async def legacy_sibling():
        if args.monitor_contract_version != 2:
            raise RuntimeError("isolated mixed-family control is unavailable")
        from trade_plan_monitor.domain.plan_codec import load_plan_yaml
        from trade_plan_monitor.domain.plan_validation import (
            ALL_MARKET_EVIDENCE,
            validate_trade_plan,
        )

        source = (
            Path(__file__).resolve().parents[2]
            / "config/plans/003043.SZ.sample.yaml"
        ).read_text(encoding="utf-8")
        source = source.replace("003043.SZ", "600000.SH").replace("SZSE", "SSE")
        source = source.replace("huaya-smart", "isolated-legacy-sibling")
        plan = load_plan_yaml(source)
        with owned_composition()._legacy_maintenance_factory() as work:
            work.plans.save_draft(plan, source_text=source)
            work.plans.activate(
                plan,
                expected_revision=0,
                validation=validate_trade_plan(
                    plan, available_market_evidence=ALL_MARKET_EVIDENCE,
                ),
            )
            work.commit()
        sdk.legacy_sibling_enabled = True
        return {"symbol": plan.symbol, "planFamily": "LEGACY_LOW_BUY"}

    @app.post("/_test/hold-minute-cutoff")
    async def hold_minute_cutoff():
        if args.monitor_contract_version != 2:
            raise RuntimeError("isolated minute cutoff control is unavailable")
        sdk.minute_cutoff = clock.now().replace(second=0, microsecond=0)
        return {"cutoff": sdk.minute_cutoff.isoformat()}

    @app.post("/_test/release-minute-cutoff")
    async def release_minute_cutoff():
        sdk.minute_cutoff = None
        return {"released": True}

    spa = next(route for route in app.router.routes if getattr(route, "name", None) == "local-spa")
    app.router.routes.remove(spa)
    app.router.routes.append(spa)

    print(json.dumps({"port": args.port, "root": str(root), "database": str(database)}), flush=True)
    try:
        server.run()
    finally:
        app_resources.close()


if __name__ == "__main__":
    main()
