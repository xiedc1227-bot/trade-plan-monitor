"""Synthetic P3 plans with actual source review, activation and accounting."""

from contextlib import contextmanager
from datetime import datetime, time, timedelta
from uuid import UUID

from sqlalchemy.orm import sessionmaker
from tests.integration.test_daily_plan_chain import FRIDAY, SH, TUESDAY, WEDNESDAY
from tests.integration.test_market_exception_runtime import exception_inputs
from tests.integration.test_market_linkage_review import source_mapping
from tests.unit.test_p3_composition import inputs_for

from trade_plan_monitor.domain.market_linkage_validation import P3PlanDraft
from trade_plan_monitor.domain.plan_validation import PlanValidationResult
from trade_plan_monitor.runtime.daily_service import DailyRuntimeEvaluationService
from trade_plan_monitor.state.daily_accounting import DailyAccounting
from trade_plan_monitor.state.daily_review_store import confirm_daily_review, save_daily_draft
from trade_plan_monitor.state.models import TradingCalendar
from trade_plan_monitor.state.source_coverage_store import SourceCoverageStore
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
from trade_plan_monitor.web.routers.plans import PlanReviewConfirmationCommand


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
        self.factory = sessionmaker(engine, expire_on_commit=False)
        self.runtime = DailyRuntimeEvaluationService(self.work, clock=lambda: self.now)
        # This isolated accounting harness emits no notifications.
        self.runtime._enqueue = lambda *args, **kwargs: None
        with self.work() as work:
            draft = P3PlanDraft.from_executable(self.plan)
            source, mapping = source_mapping(draft)
            # Keep the harness's established version/review IDs. Only identity
            # generation changes; source analysis and every authority guard run.
            identities = iter(("90000000-0000-4000-8000-000000000002",
                               self.version_id, "private-reviewed"))
            original_identity = work.plans._id_factory
            work.plans._id_factory = lambda: next(identities)
            version_id = save_daily_draft(work, draft, mapping=mapping, source_text=source,
                                         clock=lambda: self.now)
            if version_id != self.version_id:
                raise ValueError("The synthetic fixture version identity changed")
            details = work.plans.get_version_details(version_id)
            coverage = SourceCoverageStore(work.daily.session).latest(version_id)
            confirm_daily_review(work, PlanReviewConfirmationCommand(
                plan_version_id=UUID(version_id), content_hash=details.content_hash,
                source_hash=details.source_hash, review_evidence_hash=details.review_evidence_hash,
                coverage_evidence_hash=coverage.assessment.evidence_hash,
                coverage_rules_version=coverage.assessment.rules_version,
                expected_revision=0), clock=lambda: self.now)
            work.plans._id_factory = original_identity
            self.active = work.plans.activate(self.plan, expected_revision=0,
                validation=PlanValidationResult(issues=()))
            self.details = work.plans.get_version_details(version_id)
            history = tuple(FRIDAY-timedelta(days=i) for i in reversed(range(60)))
            for previous, day in zip((history[0]-timedelta(days=1), *history, TUESDAY),
                                     (*history, TUESDAY, WEDNESDAY), strict=True):
                work.daily.session.add(TradingCalendar(exchange="SSE", cal_date=day,
                    is_open=True, previous_trade_date=previous))
            work.daily.session.flush()
            DailyAccounting(work.daily).initialize(symbol=self.plan.symbol, core_qty=0,
                tactical_qty=quantity, expected_revision=0, now=self.now)
            work.commit()

    @contextmanager
    def work(self):
        with SqlAlchemyUnitOfWork(self.factory, clock=lambda: self.now) as work:
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
