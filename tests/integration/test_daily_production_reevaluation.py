"""Public daily mutations immediately reevaluate the actual production participant."""

from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from test_daily_plan_chain import FRIDAY, SH, SYMBOL, TUESDAY, WEDNESDAY, Chain, official_proof
from test_live_pipeline_acceptance import (
    ControlledClock,
    OfflineSDK,
    VirtualPace,
    _write_configuration_and_evidence,
)
from tests.unit.test_unified_plan_domain import unified_payload

import trade_plan_monitor.runtime.production as production
import trade_plan_monitor.web.monitor_composition as monitor_composition
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.runtime.request_control import create_live_tushare_request_controller
from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline
from trade_plan_monitor.state.models import TradingCalendar
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle


class ProductionDailyChain:
    """Reuse review/data fixtures, while letting the production factory own runtime wiring."""

    activate = Chain.activate
    post = Chain.post
    series = Chain.series
    evaluate = Chain.evaluate
    position = Chain.position

    def __init__(self, tmp_path, monkeypatch, *, sdk_type=OfflineSDK, initial_now=None):
        self.clock = ControlledClock(initial_now or datetime(2026, 9, 18, 16, tzinfo=SH))
        assert not callable(self.clock)
        self.sdk = sdk_type(self.clock, (SYMBOL,))
        monkeypatch.setattr(production, "create_tushare_client", lambda config: self.sdk)
        monkeypatch.setattr(monitor_composition, "SystemClock", lambda: self.clock)

        def controller_factory(*, clock, require_repository_binding=False):
            pace = VirtualPace()
            return create_live_tushare_request_controller(
                clock=clock,
                monotonic=pace.monotonic,
                pace_sleep=pace.sleep,
                require_repository_binding=require_repository_binding,
            )

        monkeypatch.setattr(
            monitor_composition, "create_live_tushare_request_controller", controller_factory
        )
        self.config = _write_configuration_and_evidence(
            tmp_path, observed_at=self.now, include_index=False
        )
        self.database = tmp_path / "daily-production.sqlite3"
        self.compose()
        self.plan = UnifiedTradePlan.model_validate(unified_payload())

    def compose(self):
        self.plans = PersistentPlanWebLifecycle(database_path=self.database, clock=self.clock.now)
        self.composition = monitor_composition.create_monitor_composition(
            config_path=self.config, database_path=self.database
        )
        self.app = create_app(
            runtime_factory=lambda: self.composition,
            plan_lifecycle_factory=lambda: self.plans,
        )
        self.client = TestClient(self.app, base_url="http://127.0.0.1:8765")

    @property
    def now(self):
        return self.clock.now()

    @now.setter
    def now(self, value):
        self.clock.current = value

    def current(self):
        response = self.client.get("/api/v1/plan-runtime/" + SYMBOL)
        assert response.status_code == 200, response.text
        view = response.json()
        assert view["status"] == "CURRENT"
        assert view["snapshot"]["planVersionId"] == self.version["id"]
        assert datetime.fromisoformat(view["evaluatedAt"]) == self.now
        assert datetime.fromisoformat(view["snapshot"]["evaluatedAt"]) == self.now
        return view["snapshot"]

    def fact(self, kind, *, official=False, satisfied=True):
        return self.post(
            "daily-plan-facts",
            {
                "planVersionId": self.version["id"],
                "contentHash": self.version["contentHash"],
                "factId": "production-" + kind,
                "kind": kind,
                "satisfied": satisfied,
                "tradeDate": str(self.now.date() if official else FRIDAY),
                "evidence": "Synthetic independently verified production regression evidence",
                "expectedRevision": 0,
                **({"officialEvidence": official_proof(self)} if official else {}),
            },
        )

    def assert_persisted(self, receipt, kind):
        with self.plans._unit_of_work() as work:
            record = work.daily.get(receipt["id"])
            assert record is not None
            assert record["kind"] == kind
            assert record["revision"] == receipt["revision"]


@pytest.fixture
def production_chain(tmp_path, monkeypatch):
    chain = ProductionDailyChain(tmp_path, monkeypatch)
    with chain.client:
        state = chain.composition._runtime._run_deadline.__self__
        assert isinstance(state._pipeline, production.ProductionMonitorPipeline)
        # This is the service constructed by ProductionMonitorPipeline; no service/clock override.
        chain.runtime = state._pipeline.daily_evaluations
        assert chain.app.state.runtime_lifecycle is chain.composition
        chain.activate()
        with chain.plans._unit_of_work() as work:
            # The synthetic review fixture treats Monday as an exchange holiday.
            holiday = work.daily.session.get(TradingCalendar, ("SSE", date(2026, 9, 21)))
            if holiday is not None:
                holiday.is_open = False
            for previous, day in (
                (date(2026, 9, 17), FRIDAY),
                (FRIDAY, TUESDAY),
                (TUESDAY, WEDNESDAY),
            ):
                existing = work.daily.session.get(TradingCalendar, ("SSE", day))
                if existing is None:
                    work.daily.session.add(
                        TradingCalendar(
                            exchange="SSE", cal_date=day, is_open=True,
                            previous_trade_date=previous,
                        )
                    )
            work.commit()
        yield chain


def test_fact_position_and_simulation_refresh_current_snapshot_through_production(production_chain):
    chain = production_chain
    # Only certified input acquisition is seeded. All commands and immediate reevals use production.
    series = chain.series()
    first = chain.evaluate(series=series, official=FRIDAY)
    assert first.snapshot["signals"] == []
    for kind in ("PRICE_STRUCTURE", "VOLUME_OR_CANDLE", "TECHNICAL"):
        chain.now += timedelta(seconds=1)
        receipt = chain.fact(kind)
        chain.assert_persisted(receipt, "FACT")
        current = chain.current()
    for kind in ("SEVERE_STRUCTURE", "SEVERE_DETERIORATION"):
        chain.now += timedelta(seconds=1)
        chain.assert_persisted(chain.fact(kind, satisfied=False), "FACT")
        current = chain.current()
    assert len(current["signals"]) == 1
    assert current["signals"][0]["executionDate"] == str(TUESDAY)

    chain.now = datetime(2026, 9, 22, 10, tzinfo=SH)
    receipt = chain.position()
    chain.assert_persisted(receipt, "POSITION")
    current = chain.current()
    assert current["inventory"]["totalQty"] == 100
    assert current["inventory"]["coreQty"] == 100
    assert current["inventory"]["tacticalQty"] == 0

    chain.evaluate(series=series, price=3970)
    chain.now += timedelta(seconds=1)
    receipt = chain.fact("TRADABILITY", official=True)
    chain.assert_persisted(receipt, "FACT")
    current = chain.current()
    signal = current["signals"][0]
    assert signal["state"] == "READY"
    assert signal["executableQty"] == 100

    chain.now += timedelta(seconds=1)
    receipt = chain.post("daily-simulated-trades", {
        "planVersionId": chain.version["id"], "causeId": signal["signalId"],
        "expectedCauseRevision": signal["revision"],
        "expectedInventoryRevision": current["inventory"]["revision"], "quantity": 100})
    with chain.plans._unit_of_work() as work:
        assert work.daily.get(receipt["simulationId"])["kind"] == "SIMULATION"
    current = chain.current()
    assert current["inventory"]["totalQty"] == 200
    assert current["inventory"]["coreQty"] == 100
    assert current["inventory"]["tacticalQty"] == 100
    assert current["signals"][0]["simulatedQty"] == 100
    assert current["signals"][0]["state"] == "SIMULATED"
    assert current["signals"][0]["executableQty"] == 0


class DailyRecoverySDK(OfflineSDK):
    """Return official bars/factors through the real SDK normalization boundary."""

    @staticmethod
    def _calendar(kwargs):
        frame = OfflineSDK._calendar(kwargs)
        frame.loc[frame.cal_date == "20260921", "is_open"] = 0
        frame.loc[frame.cal_date == "20260922", "pretrade_date"] = "20260918"
        return frame

    def _stock_daily(self, kwargs):
        frame = super()._stock_daily(kwargs)
        frame = frame.loc[frame.trade_date != "20260921"].copy()
        for column in ("open", "high", "low", "close"):
            frame[column] = "39.70"
            frame.loc[frame.trade_date == "20260918", column] = "38.00"
            frame.loc[frame.trade_date == "20260922", column] = "38.10"
        return frame

    def adj_factor(self, **kwargs):
        self.calls.append(("adj_factor", dict(kwargs)))
        start = date.fromisoformat(kwargs["start_date"])
        end = date.fromisoformat(kwargs["end_date"])
        return pd.DataFrame([
            {"ts_code": kwargs["ts_code"], "trade_date": (start + timedelta(days=i)).strftime(
                "%Y%m%d"
            ), "adj_factor": "1"}
            for i in range((end - start).days + 1)
        ])


def assert_recovered_official_risk(chain):
    current = chain.current()
    ordinary = next(r for r in current["risks"] if r["kind"] == "ORDINARY_TECHNICAL")
    assert ordinary["status"] == "CONFIRMED", current["dataBlockers"]
    assert ordinary["confirmedTradeDate"] == str(TUESDAY)
    assert ordinary["earliestExecutionDate"] == str(WEDNESDAY)
    assert current["officialTradeDate"] == str(TUESDAY)
    assert current["dailyEvidence"]["adjustment_as_of"] == str(WEDNESDAY)
    assert "CURRENT_QUOTE_BASIS_UNVERIFIED" not in current["dataBlockers"]
    assert any(name == "daily" and call["end_date"] == TUESDAY.strftime("%Y%m%d")
               for name, call in chain.sdk.calls), chain.sdk.calls
    assert any(name == "adj_factor" and call["end_date"] == WEDNESDAY.strftime("%Y%m%d")
               for name, call in chain.sdk.calls)


@pytest.mark.parametrize("recovery_entry", ["startup", "realtime_deadline"])
def test_production_recovers_missed_close_on_current_qfq_basis(
    tmp_path, monkeypatch, recovery_entry,
):
    chain = ProductionDailyChain(
        tmp_path, monkeypatch, sdk_type=DailyRecoverySDK,
        initial_now=datetime(2026, 9, 18, 14, tzinfo=SH),
    )
    with chain.client:
        chain.activate()
        state = chain.composition._runtime._run_deadline.__self__
        assert isinstance(state._pipeline, production.ProductionMonitorPipeline)
        chain.now = datetime(2026, 9, 18, 16, tzinfo=SH)
        deadline = MarketDeadline(
            kind=DeadlineKind.OFFICIAL_CLOSE, trade_date=FRIDAY,
            due_at=chain.now, close_attempt=1,
        )
        chain.client.portal.call(state.run_deadline, deadline)
        current = chain.current()
        ordinary = next(r for r in current["risks"] if r["kind"] == "ORDINARY_TECHNICAL")
        assert ordinary["status"] == "PENDING", (current["dataBlockers"], chain.sdk.calls)
        if recovery_entry == "realtime_deadline":
            chain.now = datetime(2026, 9, 23, 10, tzinfo=SH)
            chain.sdk.calls.clear()
            deadline = MarketDeadline(
                kind=DeadlineKind.REALTIME_MINUTE, trade_date=WEDNESDAY,
                due_at=chain.now, bar_end=chain.now,
            )
            chain.client.portal.call(state.run_deadline, deadline)
            assert_recovered_official_risk(chain)
            return
    chain.now = datetime(2026, 9, 23, 10, tzinfo=SH)
    _write_configuration_and_evidence(tmp_path, observed_at=chain.now, include_index=False)
    chain.sdk.calls.clear()
    chain.compose()
    # No run_inputs, run_target or recovery helper is invoked: lifespan performs real startup.
    with chain.client:
        assert_recovered_official_risk(chain)
