"""Offline production participant + public API against one real SQLite ledger."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from tests.unit.test_daily_review import reviewed_mapping
from tests.unit.test_unified_plan_domain import unified_payload

from trade_plan_monitor.domain.daily_plan_validation import daily_draft_json
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft
from trade_plan_monitor.market_data.daily_data import (
    CertifiedDailyBar,
    DailyExecutionQuote,
    DailySeries,
)
from trade_plan_monitor.runtime.daily_service import (
    DailyRuntimeEvaluationService,
    DailyRuntimeInputs,
    daily_delivery_allowed,
)
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle

SH = ZoneInfo("Asia/Shanghai")
SYMBOL = "601021.SH"
FRIDAY, TUESDAY, WEDNESDAY = date(2026, 9, 18), date(2026, 9, 22), date(2026, 9, 23)


class OfflineRuntime:
    def __init__(self, chain):
        self.chain = chain

    async def start(self):
        return object()

    async def stop(self):
        pass

    async def reevaluate_daily(self, version_id):
        return await self.chain.runtime.reevaluate_version(version_id)


class Chain:
    def __init__(
        self,
        tmp_path,
        *,
        bind_port=8765,
        static_directory=None,
        ai_service=None,
        read_service=None,
        ai_lifecycle_factory=None,
    ):
        self.now = datetime(2026, 9, 18, 16, tzinfo=SH)
        self.plans = PersistentPlanWebLifecycle(
            database_path=tmp_path / "daily.sqlite", clock=lambda: self.now
        )
        self.app = create_app(
            runtime_factory=lambda: OfflineRuntime(self),
            plan_lifecycle_factory=lambda: self.plans,
            bind_port=bind_port,
            static_directory=static_directory,
            ai_service=ai_service,
            read_service=read_service,
            ai_lifecycle_factory=ai_lifecycle_factory,
        )
        self.client = TestClient(self.app, base_url=f"http://127.0.0.1:{bind_port}")
        self.runtime = DailyRuntimeEvaluationService(
            self.plans._unit_of_work, clock=lambda: self.now
        )
        self.plan = UnifiedTradePlan.model_validate(unified_payload())

    def post(self, path, data, *, key=None, status=200):
        path = {
            "daily-plan-review-supplements": "plan-review-supplements",
            "daily-position-confirmations": "simulation-position-confirmations",
            "daily-plan-facts": "plan-facts",
            "daily-simulated-trades": "simulated-trades",
        }.get(path, path)
        response = self.client.post(
            "/api/v1/" + path, json=data, headers={"Idempotency-Key": key or uuid4().hex}
        )
        assert response.status_code == status, response.text
        return response.json()

    def activate(
        self,
        *,
        version=1,
        activation_revision=0,
        supplement_revision=0,
        plan_id=None,
        review=True,
        source="Synthetic human-reviewed supplements for this fixture.",
    ):
        self.plan = self.plan.model_copy(
            update={"version": version, **({"plan_id": plan_id} if plan_id else {})}
        )
        draft = UnifiedPlanDraft.from_executable(self.plan)
        mapping = reviewed_mapping(draft, source)
        from trade_plan_monitor.ai.daily_review import daily_source_clauses

        treatments = {}
        original_clauses = {c.clause_id: c for c in mapping.clauses}
        for c in daily_source_clauses(source):
            if c.exclusions:
                original = original_clauses[c.clause_id]
                if c.remainders:
                    c = c.model_copy(update={"disposition": "POLICY", "paths": original.paths,
                        "remainders": tuple(r.model_copy(update={"disposition": "POLICY",
                            "paths": original.paths}) for r in c.remainders)})
                treatments[c.clause_id] = c
        if treatments:
            mapping = mapping.model_copy(
                update={"clauses": tuple(treatments.get(c.clause_id, c) for c in mapping.clauses)}
            )
        self.post(
            "daily-plan-review-supplements",
            {
                "candidateJson": daily_draft_json(draft),
                "contentHash": mapping.candidate_content_hash,
                "supplements": [s.model_dump(mode="json") for s in mapping.supplements],
                "expectedRevision": supplement_revision,
            },
        )
        saved = self.post(
            "plan-drafts",
            {
                "planJson": daily_draft_json(draft),
                "sourceText": source,
                "dailyMapping": mapping.model_dump(mode="json"),
                "expectedRevision": activation_revision,
            },
        )
        assert not saved["canActivate"]
        if not review:
            self.version = saved
            return saved
        binding = {
            "planVersionId": saved["id"],
            "contentHash": saved["contentHash"],
            "sourceHash": saved["sourceHash"],
            "reviewEvidenceHash": saved["reviewEvidenceHash"],
        }
        reviewed = self.post("plan-review-confirmations", {**binding, "expectedRevision": 0})
        assert reviewed["canActivate"]
        active = self.post(
            "plan-activations",
            {
                **binding,
                "reviewId": reviewed["reviewId"],
                "reviewRevision": 1,
                "expectedRevision": activation_revision,
            },
        )
        self.version = saved
        return active

    def series(self, day=FRIDAY, close=3970):
        stamp = datetime.combine(day, datetime.min.time(), SH).replace(hour=16)
        bar = CertifiedDailyBar(
            bar_id="synthetic-" + str(day),
            symbol=SYMBOL,
            trade_date=day,
            open=Decimal(close),
            high=Decimal(close + 20),
            low=Decimal(close - 20),
            close=Decimal(close),
            volume_shares=1000,
            official=True,
            provider="offline",
            basis_id="offline-qfq",
            adjustment_as_of=day,
            received_at=stamp,
            available_at=stamp,
        )
        return DailySeries(
            symbol=SYMBOL,
            bars=(bar,),
            basis_id=bar.basis_id,
            adjustment_as_of=day,
            provider="offline",
            quote_comparable=True,
            session_dates=(day,),
            suspended_dates=(),
            cutoff=stamp,
        )

    def evaluate(self, *, series=None, official=None, price=None):
        quote = (
            None
            if price is None
            else DailyExecutionQuote(
                symbol=SYMBOL,
                price_fen=price,
                quote_at=self.now,
                available_at=self.now,
                evaluated_at=self.now,
                tradable=True,
                special_state_verified=True,
                liquidity_available=True,
            )
        )
        return self.runtime.run_inputs(
            plan=self.plan,
            inputs=DailyRuntimeInputs(
                evaluated_at=self.now,
                official_trade_date=official,
                series=series,
                session_dates=(FRIDAY, TUESDAY, WEDNESDAY),
                suspended_dates=(),
                quote=quote,
                data_blockers=(),
            ),
        )

    def position(self, core=100, tactical=0):
        return self.post("daily-position-confirmations", {"symbol": SYMBOL,
            "coreQty": core, "tacticalQty": tactical, "expectedRevision": 0})

    def simulate(self, signal, quantity=None, *, key=None, status=200):
        inventory = self.client.get("/api/v1/simulation-position-inventory",
            params={"symbol": SYMBOL, "asOfTradeDate": str(self.now.date())}).json()["snapshot"]
        return self.post("daily-simulated-trades", {"planVersionId": self.version["id"],
            "causeId": signal.get("signal_id", signal.get("cause_id")),
            "expectedCauseRevision": signal.get("revision", signal.get("cause_revision")),
            "expectedInventoryRevision": inventory["revision"],
            "quantity": signal.get("executable_qty", 0) if quantity is None else quantity},
            key=key, status=status)

    def facts(self):
        for kind in ("PRICE_STRUCTURE", "VOLUME_OR_CANDLE", "TECHNICAL"):
            self.post(
                "daily-plan-facts",
                {
                    "planVersionId": self.version["id"],
                    "contentHash": self.version["contentHash"],
                    "factId": "synthetic-" + kind,
                    "kind": kind,
                    "tradeDate": str(FRIDAY),
                    "evidence": "Synthetic complete official daily evidence independently verified",
                    "expectedRevision": 0,
                },
            )
        for kind in ("SEVERE_STRUCTURE", "SEVERE_DETERIORATION"):
            self.post("daily-plan-facts", {
                "planVersionId": self.version["id"],
                "contentHash": self.version["contentHash"],
                "factId": "reviewed-clear-" + kind,
                "kind": kind,
                "tradeDate": str(FRIDAY),
                "satisfied": False,
                "evidence": "Synthetic review found this severe predicate absent",
                "expectedRevision": 0,
            })


@pytest.fixture
def chain(tmp_path):
    chain = Chain(tmp_path)
    with chain.client:
        chain.activate()
        from trade_plan_monitor.state.models import TradingCalendar

        with chain.plans._unit_of_work() as work:
            for previous, day in (
                (date(2026, 9, 17), FRIDAY),
                (FRIDAY, TUESDAY),
                (TUESDAY, WEDNESDAY),
            ):
                work.daily.session.add(
                    TradingCalendar(
                        exchange="SSE", cal_date=day, is_open=True, previous_trade_date=previous
                    )
                )
            work.commit()
        yield chain


def test_daily_public_review_confirmation_next_session_and_expiry(chain):
    series = chain.series()
    first = chain.evaluate(series=series, official=FRIDAY)
    assert first.snapshot["signals"] == []
    chain.facts()
    confirmed = chain.evaluate(series=series, official=FRIDAY)
    signal = confirmed.snapshot["signals"][0]
    assert signal["execution_date"] == str(TUESDAY)
    assert signal["executable_qty"] == 0
    chain.now = datetime(2026, 9, 22, 10, tzinfo=SH)
    chain.position()
    ready = chain.evaluate(series=series, price=3970)
    assert ready.snapshot["signals"][0]["executable_qty"] == 100
    assert len(ready.event_ids) == 1
    view = chain.client.get("/api/v1/plan-runtime/" + SYMBOL)
    assert view.status_code == 200, view.text
    assert view.json()["snapshot"]["signals"][0]["state"] == "READY"
    with chain.plans._unit_of_work() as work:
        event = work.alerts.get(__import__("uuid").UUID(ready.event_ids[0]))
        assert daily_delivery_allowed(work.daily.session, event, chain.now)
    chain.now = chain.now.replace(hour=15)
    expired = chain.evaluate(series=series, price=3970)
    assert expired.snapshot["signals"][0]["state"] == "EXPIRED"
    assert expired.event_ids == ()
    with chain.plans._unit_of_work() as work:
        assert not daily_delivery_allowed(work.daily.session, event, chain.now)


def test_same_completed_date_can_reevaluate_current_quote_reentry(chain):
    series = chain.series()
    chain.evaluate(series=series, official=FRIDAY)
    chain.facts()
    chain.evaluate(series=series, official=FRIDAY)
    chain.now = datetime(2026, 9, 22, 10, tzinfo=SH)
    chain.position()
    outside = chain.evaluate(series=series, official=FRIDAY, price=4100)
    assert outside.snapshot["signals"][0]["executable_qty"] == 0
    chain.now += timedelta(minutes=1)
    inside = chain.evaluate(series=series, official=FRIDAY, price=3970)
    assert not inside.duplicate
    assert inside.snapshot["signals"][0]["executable_qty"] == 100


def ready_chain(chain):
    series = chain.series()
    chain.evaluate(series=series, official=FRIDAY)
    chain.facts()
    chain.evaluate(series=series, official=FRIDAY)
    chain.now = datetime(2026, 9, 22, 10, tzinfo=SH)
    chain.position()
    return series, chain.evaluate(series=series, price=3970)




def test_ordinary_rebound_below_line_confirms_then_executes_next_session(chain):
    first = chain.evaluate(series=chain.series(close=3800), official=FRIDAY)
    risk = next(r for r in first.snapshot["risks"] if r["kind"] == "ORDINARY_TECHNICAL")
    assert risk["status"] == "PENDING"
    chain.now = datetime(2026, 9, 22, 16, tzinfo=SH)
    second = chain.evaluate(series=chain.series(TUESDAY, close=3810), official=TUESDAY)
    risk = next(r for r in second.snapshot["risks"] if r["kind"] == "ORDINARY_TECHNICAL")
    assert risk["status"] == "CONFIRMED"
    assert risk["earliest_execution_date"] == str(WEDNESDAY)
    assert second.snapshot["risk_action"]["status"] == "WAITING"
    chain.now = datetime(2026, 9, 23, 10, tzinfo=SH)
    chain.position()
    execution = chain.evaluate(series=chain.series(TUESDAY, close=3810), price=3800)
    assert execution.snapshot["risk_action"]["core_qty"] == 100
    assert execution.snapshot["risk_action"]["status"] == "RISK_EXIT"


def official_proof(chain):
    return {
        "issuer": "Synthetic official exchange fixture",
        "documentTitle": "Offline verification fixture",
        "documentUrl": "https://example.invalid/offline-proof",
        "publishedAt": (chain.now - timedelta(minutes=2)).isoformat(),
        "verifiedAt": (chain.now - timedelta(minutes=1)).isoformat(),
        "applicableAssertion": (
            "Synthetic official fact explicitly verified by a human for this holding"
        ),
    }


def test_official_tradability_fact_immediately_reevaluates_without_fundamental_gate(chain):
    series, ready = ready_chain(chain)
    chain.now += timedelta(seconds=1)
    chain.post(
        "daily-plan-facts",
        {
            "planVersionId": chain.version["id"],
            "contentHash": chain.version["contentHash"],
            "factId": "official-tradability",
            "kind": "TRADABILITY",
            "tradeDate": str(TUESDAY),
            "expectedRevision": 0,
            "evidence": "Synthetic exchange tradability evidence independently verified",
            "officialEvidence": official_proof(chain),
        },
    )
    view = chain.client.get("/api/v1/plan-runtime/" + SYMBOL).json()["snapshot"]
    assert view["riskAction"]["status"] == "NONE"
    assert view["signals"][0]["executableQty"] == 100
    assert not any(
        "ANNOUNCEMENT" in b or "FUNDAMENTAL" in b for b in view["signals"][0]["blockers"]
    )


def test_queued_risk_quantity_is_rechecked_after_actual_inventory_changes(chain):
    series, _ = ready_chain(chain)
    for kind in ("SEVERE_STRUCTURE", "SEVERE_DETERIORATION"):
        chain.now += timedelta(seconds=1)
        chain.post(
            "daily-plan-facts",
            {
                "planVersionId": chain.version["id"],
                "contentHash": chain.version["contentHash"],
                "factId": "synthetic-" + kind,
                "kind": kind,
                "tradeDate": str(FRIDAY),
                "expectedRevision": 0,
                "evidence": "Synthetic complete technical failure independently verified",
            },
        )
    chain.evaluate(series=series, price=3970)
    with chain.plans._unit_of_work() as work:
        from sqlalchemy import select

        from trade_plan_monitor.state.models import AlertEvent

        rows = work.daily.session.scalars(select(AlertEvent)).all()
        events = [work.alerts.get(__import__("uuid").UUID(row.id)) for row in rows]
        risk = next(e for e in events if e.signal_type == "RISK_EXIT")
        assert daily_delivery_allowed(work.daily.session, risk, chain.now)
    chain.now = chain.now.replace(hour=15)
    assert chain.evaluate(series=series, price=3970).snapshot["risk_action"]["core_qty"] == 0
    with chain.plans._unit_of_work() as work:
        assert not daily_delivery_allowed(work.daily.session, risk, chain.now)


def test_real_sdk_normalizer_production_adapter_and_official_scheduler(chain):
    import asyncio
    from types import SimpleNamespace

    import pandas as pd

    from trade_plan_monitor.market_data.tushare import TushareMarketDataProvider
    from trade_plan_monitor.runtime.production import ProductionMonitorPipeline
    from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline
    from trade_plan_monitor.runtime.service import RuntimeDeadlineCoordinator

    calls = []

    class SDK:
        def daily(self, **kwargs):
            calls.append(("daily", kwargs))
            return pd.DataFrame(
                [
                    dict(
                        ts_code=SYMBOL,
                        trade_date="20260918",
                        open=39.7,
                        high=39.9,
                        low=39.5,
                        close=39.7,
                        vol=10,
                        amount=1,
                    )
                ]
            )

        def adj_factor(self, **kwargs):
            calls.append(("adj_factor", kwargs))
            return pd.DataFrame([dict(ts_code=SYMBOL, trade_date="20260918", adj_factor=1)])

    class Controller:
        async def execute(self, operation, operation_call, **kwargs):
            return operation_call()

    state = SimpleNamespace(
        _work=chain.plans._unit_of_work,
        _clock=SimpleNamespace(now=lambda: chain.now),
        _controller=Controller(),
        _daily_basis_cache={},
        _runtime_generation=uuid4(),
        is_open_on=lambda day: True,
    )
    state.provider = TushareMarketDataProvider(
        SDK(), now=lambda: chain.now, is_open_on=lambda day: True
    )

    async def prepare(plan, evaluated_at, official_trade_date, minutes):
        return await ProductionMonitorPipeline.prepare_daily_inputs(
            state, plan, evaluated_at, official_trade_date, minutes
        )

    daily = DailyRuntimeEvaluationService(
        chain.plans._unit_of_work, prepare_inputs=prepare, clock=lambda: chain.now
    )

    class EmptyLegacy:
        async def run_official_close_batch(self, *, plans, **kwargs):
            assert plans == ()
            return ()

    coordinator = object.__new__(RuntimeDeadlineCoordinator)
    coordinator._clock = state._clock
    coordinator._active_plans = lambda: (chain.plan,)
    coordinator._evaluation_service = EmptyLegacy()
    coordinator._explicit_evaluation_service = None
    coordinator._daily_evaluation_service = daily
    deadline = MarketDeadline(
        kind=DeadlineKind.OFFICIAL_CLOSE, trade_date=FRIDAY, due_at=chain.now, close_attempt=1
    )
    result = asyncio.run(coordinator.run_deadline(deadline))[0]
    assert result.snapshot["daily_evidence"]["provider"] == "Tushare"
    assert Decimal(result.snapshot["daily_evidence"]["bars"][0]["close"]) == Decimal(3970)
    assert result.snapshot["data_blockers"] == []
    assert [c[0] for c in calls] == ["daily", "adj_factor"]
    chain.facts()
    result = asyncio.run(coordinator.run_deadline(deadline))[0]
    assert len(result.snapshot["signals"]) == 1
    assert result.snapshot["signals"][0]["execution_date"] == str(TUESDAY)


def test_activation_change_and_admission_failure_roll_back_all_daily_state(chain):
    from sqlalchemy import func, select

    from trade_plan_monitor.state.daily_models import DailyRecord

    series = chain.series()
    with chain.plans._unit_of_work() as work:
        before = work.daily.session.scalar(select(func.count()).select_from(DailyRecord))
    inputs = DailyRuntimeInputs(
        evaluated_at=chain.now,
        official_trade_date=FRIDAY,
        series=series,
        session_dates=(FRIDAY, TUESDAY),
        suspended_dates=(),
        quote=None,
        data_blockers=(),
    )
    with pytest.raises(ValueError, match="activation changed"):
        chain.runtime.run_inputs(plan=chain.plan, inputs=inputs, expected_activation_revision=0)
    closed = DailyRuntimeEvaluationService(
        chain.plans._unit_of_work, commit_admission=lambda: False
    )
    with pytest.raises(ValueError, match="admission"):
        closed.run_inputs(plan=chain.plan, inputs=inputs)
    with chain.plans._unit_of_work() as work:
        assert work.daily.session.scalar(select(func.count()).select_from(DailyRecord)) == before


def test_late_runtime_admission_failure_rolls_back_staged_signal_and_complete_database(
    chain, monkeypatch,
):
    import sqlite3

    from trade_plan_monitor.state.daily_repository import DailyRepository

    ready_chain(chain)
    database = chain.plans._database_path

    def dump():
        with sqlite3.connect(database) as connection:
            return tuple(connection.iterdump())

    before = dump()
    staged = []
    original = DailyRepository.save

    def record_staging(self, *args, **kwargs):
        row = original(self, *args, **kwargs)
        staged.append((row["id"], row["kind"], row["revision"]))
        return row

    monkeypatch.setattr(DailyRepository, "save", record_staging)
    checks = []

    def admission():
        checks.append(len(staged))
        return len(checks) == 1

    chain.now += timedelta(seconds=5)
    guarded = DailyRuntimeEvaluationService(chain.plans._unit_of_work,
        commit_admission=admission)
    inputs = DailyRuntimeInputs(evaluated_at=chain.now, official_trade_date=FRIDAY,
        series=chain.series(), session_dates=(FRIDAY, TUESDAY, WEDNESDAY),
        suspended_dates=(), quote=DailyExecutionQuote(symbol=SYMBOL, price_fen=4500,
            quote_at=chain.now, available_at=chain.now, evaluated_at=chain.now,
            tradable=True, special_state_verified=True, liquidity_available=True),
        data_blockers=())
    with pytest.raises(RuntimeError, match="commit admission changed"):
        guarded.run_inputs(plan=chain.plan, inputs=inputs)
    assert len(checks) == 2 and checks[0] == 0 and checks[1] > 0
    assert {kind for _, kind, _ in staged} >= {"SIGNAL", "EVALUATION"}
    assert dump() == before
    guarded._admission = lambda: True
    retried = guarded.run_inputs(plan=chain.plan, inputs=inputs)
    assert not retried.duplicate
    assert retried.snapshot["signals"][0]["executable_qty"] == 0
