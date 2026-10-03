"""Shared current-plan production fixture for notification and numeric-oracle checks."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from tests.integration.test_daily_plan_chain import Chain
from tests.integration.test_explicit_runtime_production import (
    ENDPOINT,
    PIPELINE_NOW,
    PREPARED_AT,
    TARGET,
    _ExplicitPipelineSDK,
    _PipelineClock,
)
from tests.unit.test_unified_plan_domain import unified_payload

from trade_plan_monitor.config import load_application_config
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.live_profiles import create_stock_certification, write_live_certification
from trade_plan_monitor.market_data.aggregation import FiveMinuteBar
from trade_plan_monitor.market_data.models import (
    MinuteBar,
    ProviderCapabilities,
    ProviderCapabilityStatus,
    TradingDay,
)
from trade_plan_monitor.market_data.sessions import SourceTimeLabel
from trade_plan_monitor.runtime.production import ProductionMonitorPipeline
from trade_plan_monitor.runtime.request_control import create_live_tushare_request_controller
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import TradingCalendar
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork


def current_three_rule_plan(*, overlapping_risk=False):
    raw = unified_payload()
    raw.update(symbol="003043.SZ", market="SZSE", levels=None, monitoring=None,
               risk_branches=[])
    base = raw["ordinary_rules"][0]
    base.update(zone=None, confirmation={"kind": "COMPLETED_BAR_CLOSE",
        "timeframe_minutes": 5}, execution_window="CURRENT_SESSION")
    base["condition"] = {"type": "ALL", "conditions": [
        {"type": "MINUTE_CLOSE_IN_RANGE", "timeframe_minutes": 5,
         "low_fen": 980, "high_fen": 1000,
         "include_low": True, "include_high": True},
        {"type": "MINUTE_VOLUME_TO_MEAN_GTE", "timeframe_minutes": 5,
         "window_bars": 5, "minimum_ratio": "1.5",
         "history_scope": "CONTIGUOUS_TRADING_BARS"},
    ]}
    sell = {**base, "side": "SELL", "rule_id": "sell-100",
            "condition": {"type": "MINUTE_CLOSE_IN_RANGE", "timeframe_minutes": 5,
                "low_fen": 1080, "high_fen": 1100,
                "include_low": True, "include_high": True}}
    raw["ordinary_rules"] = [base, sell]
    raw["alert_rules"] = [{"kind": "RISK_ALERT", "rule_id": "risk-below-950",
        "condition": {"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5,
                      "price_fen": 1200 if overlapping_risk else 950},
        "confirmation": {"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5}}]
    raw["position"].update(core_target_qty=0, tactical_target_qty=100)
    return UnifiedTradePlan.model_validate(raw)


def replace_current_plan(tmp_path, *, at=PIPELINE_NOW):
    """Activate a reviewed successor without carrying old alert authority forward."""
    chain = Chain(tmp_path)
    raw = current_three_rule_plan().model_dump(mode="json")
    raw["ordinary_rules"][0]["condition"]["conditions"][0].update(
        low_fen=1080, high_fen=1100)
    chain.plan = UnifiedTradePlan.model_validate(raw)
    chain.now = at
    with chain.client:
        chain.activate(version=2, activation_revision=1,
            source="Synthetic reviewed successor with changed minute price boundary.")
    return chain.plan


def current_pipeline_fixture(tmp_path, monkeypatch, *, current_volume,
                             current_close_fen=990, prior_minute_volume=60,
                             seed_inventory=True, overlapping_risk=False, plan=None,
                             activation_at=PREPARED_AT, seed_tradability=True):
    import trade_plan_monitor.runtime.production as production

    chain = Chain(tmp_path)
    chain.plan = plan or current_three_rule_plan(overlapping_risk=overlapping_risk)
    chain.now = datetime(2026, 9, 11, 16, tzinfo=TARGET.tzinfo)
    with chain.client:
        with chain.plans._unit_of_work() as transaction:
            transaction.daily.session.add_all((
                TradingCalendar(exchange="SZSE", cal_date=date(2026, 9, 11),
                    is_open=True, previous_trade_date=date(2026, 9, 10)),
                TradingCalendar(exchange="SZSE", cal_date=TARGET.date(),
                    is_open=True, previous_trade_date=date(2026, 9, 11)),
            ))
            transaction.commit()
        if seed_inventory:
            chain.post("simulation-position-confirmations", {
                "symbol": chain.plan.symbol, "coreQty": 0, "tacticalQty": 100,
                "expectedRevision": 0})
        chain.now = activation_at
        chain.activate(source="Synthetic reviewed minute BUY, SELL, and risk reminder rules.")
        chain.now = PREPARED_AT
        if seed_tradability:
            chain.post("plan-facts", {
            "planVersionId": chain.version["id"],
            "contentHash": chain.version["contentHash"],
            "factId": "current-tradability", "kind": "TRADABILITY",
            "tradeDate": str(TARGET.date()),
            "evidence": "Synthetic complete verified tradability and liquidity review",
            "officialEvidence": {
                "issuer": "Synthetic exchange evidence fixture",
                "documentTitle": "Verified tradeability fixture",
                "documentUrl": "https://example.test/tradability",
                "publishedAt": PREPARED_AT.isoformat(),
                "verifiedAt": PREPARED_AT.isoformat(),
                "applicableAssertion": "Synthetic official evidence verifies current tradability",
            },
            "expectedRevision": 0,
            })
    database = tmp_path / "daily.sqlite"
    engine = create_sqlite_engine(database)
    sessions = create_session_factory(engine)
    clock = _PipelineClock(PIPELINE_NOW)

    def work():
        return SqlAlchemyUnitOfWork(sessions, clock=clock.now)

    with work() as transaction:
        transaction.references.upsert_trading_days((TradingDay(exchange="SZSE",
            cal_date=TARGET.date(), is_open=True, previous_trade_date=date(2026, 9, 11)),))
        for index, volume in enumerate((100, 100, 100, 100, 600)):
            bucket_end = TARGET - timedelta(minutes=(5-index)*5)
            transaction.history.upsert_five_minute(**FiveMinuteBar(
                symbol=chain.plan.symbol, bar_end=bucket_end,
                open_fen=990, high_fen=990, low_fen=990, close_fen=990,
                volume_shares=volume, amount_yuan=Decimal("0"),
            ).model_dump())
            transaction.history.upsert_minutes(tuple(MinuteBar(
                symbol=chain.plan.symbol, bar_end=bucket_end-timedelta(minutes=offset),
                open_fen=990, high_fen=990, low_fen=990, close_fen=990,
                volume_shares=volume // 5, amount_yuan=Decimal("0"),
                received_at=TARGET + timedelta(seconds=2),
            ) for offset in (4, 3, 2, 1, 0)))
        transaction.history.upsert_minutes(tuple(MinuteBar(symbol=chain.plan.symbol,
            bar_end=TARGET-timedelta(minutes=offset), open_fen=990, high_fen=990,
            low_fen=990, close_fen=990, volume_shares=prior_minute_volume,
            amount_yuan=Decimal("0"),
            received_at=TARGET + timedelta(seconds=2)) for offset in (4, 3, 2, 1)))
        transaction.commit()
    config = tmp_path / "config-current" / "app.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(f"tushare:\n  api_url: {ENDPOINT}\n  token: offline-test-token\n")
    certification_directory = tmp_path / "data" / "live-certification"
    evidence = create_stock_certification(observed_at=PIPELINE_NOW,
        endpoint_url=ENDPOINT,
        capabilities=ProviderCapabilities(**{
            key: ProviderCapabilityStatus.READY
            for key in ProviderCapabilities.model_fields}),
        source_time_label=SourceTimeLabel.START)
    write_live_certification(certification_directory / "tushare-stock-live.json", evidence)
    sdk = _ExplicitPipelineSDK(current_volume=current_volume,
        current_close_fen=current_close_fen)
    monkeypatch.setattr(production, "create_tushare_client", lambda _config: sdk)

    def build_pipeline():
        controller = create_live_tushare_request_controller(clock=clock)
        published = []
        pipeline = ProductionMonitorPipeline(
            configuration=load_application_config(config).tushare,
            certification_directory=certification_directory,
            stock_certification=evidence,
            clock=clock, request_controller=controller,
            unit_of_work_factory=work, runtime_generation=uuid4(),
            publisher=published.append,
            recovery_session_factory=sessions,
        )
        return controller, pipeline, published

    controller, pipeline, published = build_pipeline()
    return engine, work, chain.plan, sdk, build_pipeline, controller, pipeline, published
