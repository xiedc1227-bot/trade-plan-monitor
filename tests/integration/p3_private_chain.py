"""Private pre-admission harness; real UOW/runtime/accounting, no public Schema9 claim."""

from contextlib import contextmanager
from datetime import datetime, time, timedelta
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy.orm import sessionmaker
from tests.integration.test_daily_plan_chain import FRIDAY, SH, TUESDAY, WEDNESDAY
from tests.integration.test_market_exception_runtime import exception_inputs
from tests.unit.test_p3_composition import inputs_for

from trade_plan_monitor.domain.plan_hash import daily_plan_content_sha256, plan_sha256
from trade_plan_monitor.runtime.daily_service import DailyRuntimeEvaluationService
from trade_plan_monitor.state.daily_accounting import DailyAccounting
from trade_plan_monitor.state.models import TradingCalendar
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork


class PrivateChain:
    def __init__(self, engine, monkeypatch, *, mode="MARKET_VALUE_CAP", quantity=0, plan=None,
                 route="WEAK_MINIMUM"):
        self.now = datetime.combine(FRIDAY, time(16), SH)
        self.route = route
        self.plan = plan or inputs_for(mode=mode)[0]
        if mode == "OPEN_COST_CAP" and plan is None:
            raw = self.plan.model_dump(mode="json")
            raw["position"]["limit"]["capital_policy"]["buy_cost_schedule"].update(
                effective_from="2026-01-01", effective_through="2026-12-31")
            self.plan = type(self.plan).model_validate(raw)
        self.version_id = "90000000-0000-4000-8000-000000000001"
        self.active = SimpleNamespace(plan_version_id=self.version_id, revision=1,
                                      activated_at=self.now)
        self.details = SimpleNamespace(id=self.version_id, symbol=self.plan.symbol,
            plan_id=self.plan.plan_id, payload_json=self.plan.model_dump_json(), daily_issues=(),
            plan_hash=plan_sha256(self.plan), content_hash=daily_plan_content_sha256(self.plan))
        self.factory = sessionmaker(engine, expire_on_commit=False)
        # The executable boundary stays closed. Only this private harness supplies a strict model.
        from trade_plan_monitor.domain import plan_codec
        from trade_plan_monitor.runtime import market_exceptions
        original = plan_codec.load_plan_json
        def private_reader(raw):
            import json
            if json.loads(raw).get("schema_version") == 9:
                return type(self.plan).model_validate_json(raw)
            return original(raw)
        monkeypatch.setattr(plan_codec, "load_plan_json", private_reader)
        monkeypatch.setattr(market_exceptions, "load_plan_json", private_reader)
        self.runtime = DailyRuntimeEvaluationService(self.work, clock=lambda: self.now)
        # Notifications require the public immutable plan tables; their acceptance belongs to T17.
        self.runtime._enqueue = lambda *args, **kwargs: None
        with self.work() as work:
            history = tuple(FRIDAY-timedelta(days=i) for i in reversed(range(60)))
            for previous, day in zip((history[0]-timedelta(days=1), *history, TUESDAY),
                                     (*history, TUESDAY, WEDNESDAY), strict=True):
                work.daily.session.add(TradingCalendar(exchange="SSE", cal_date=day,
                    is_open=True, previous_trade_date=previous))
            work.daily.session.flush()
            DailyAccounting(work.daily).initialize(symbol=self.plan.symbol, core_qty=0,
                tactical_qty=quantity, expected_revision=0, now=self.now)
            work.daily.save("review-"+self.version_id, kind="REVIEW", symbol=self.plan.symbol,
                lineage=self.plan.plan_id, expected_revision=0, payload=dict(
                    confirmed=True, content_hash=self.details.content_hash, source_hash="a"*64,
                    evidence_hash="b"*64, review_id="private-reviewed", review_revision=1,
                    plan_version_id=self.version_id))
            work.commit()

    @contextmanager
    def work(self):
        with SqlAlchemyUnitOfWork(self.factory, clock=lambda: self.now) as work:
            work._plans = SimpleNamespace(get_active=lambda _: self.active,
                get_version_details=lambda _: self.details)
            yield work

    def evaluate(self, price=161):
        data = exception_inputs(self)
        if data.quote is not None:
            data = data.model_copy(update={"quote": data.quote.model_copy(
                update={"price_fen": price})})
        return self.runtime.run_inputs(plan=self.plan, inputs=data)

    def command(self, signal, quantity=None):
        from trade_plan_monitor.state.simulation import SimulationCommand
        with self.work() as work:
            row = work.daily.get(signal.get("signal_id", signal.get("cause_id")))
            inv = DailyAccounting(work.daily).snapshot(self.plan.symbol, self.now.date())
        return SimulationCommand(plan_version_id=UUID(self.version_id), cause_id=row["id"],
            expected_cause_revision=row["revision"], expected_inventory_revision=inv["revision"],
            quantity=quantity or signal["planned_qty"])


    def open_basis(self, basis, command_id="opening"):
        from trade_plan_monitor.state.p3_capital_repository import CapitalRepository
        from trade_plan_monitor.state.p3_capital_service import (
            CapitalInventoryLot,
            CapitalOpeningCommand,
            CapitalOpeningContext,
            CapitalOpeningLot,
            confirm_capital_opening,
        )
        with self.work() as work:
            account = DailyAccounting(work.daily)
            position = account._position(self.plan.symbol)
            batches = position["payload"]["batches"]
            lots = tuple(CapitalInventoryLot(lot_id=b["id"], bucket=b["bucket"],
                quantity=b["quantity"]) for b in batches)
            context = CapitalOpeningContext(plan_version_id=self.version_id,
                symbol=self.plan.symbol, content_hash=self.details.content_hash,
                review_binding_hash="a"*64, reviewed=True, inventory_known=True,
                inventory_revision=position["revision"], lots=lots, blockers=())
            book = CapitalRepository(work.daily.session).get(self.plan.symbol)
            command = CapitalOpeningCommand(plan_version_id=self.version_id,
                expected_inventory_revision=position["revision"],
                expected_book_revision=0 if book is None else book.revision,
                observed_at=self.now, source="Explicit synthetic opening source",
                excerpt="Reviewed cost of current retained simulation lot",
                reason="Explicit test reconciliation", confirmed=True,
                lots=tuple(CapitalOpeningLot(**lot.model_dump(), retained_basis_fen=basis)
                           for lot in lots))
            receipt = confirm_capital_opening(work.daily.session, command,
                command_id=command_id, now=self.now, current=lambda _: context)
            work.commit()
            return receipt
