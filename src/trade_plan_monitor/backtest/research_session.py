"""Private SQLite monitor session: frozen research authority and no delivery sink."""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from uuid import UUID

from trade_plan_monitor.backtest.research_report import ResearchOperationOutcome
from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.plan_codec import dump_plan_json
from trade_plan_monitor.runtime.daily_service import DailyRuntimeEvaluationService
from trade_plan_monitor.state.daily_accounting import DailyAccounting
from trade_plan_monitor.state.daily_state_models import DailyInventoryView
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import Base, TradingCalendar
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork


@dataclass(frozen=True)
class _ResearchActive:
    plan_version_id: str
    activated_at: datetime
    revision: int = 1


@dataclass(frozen=True)
class _ResearchDetails:
    id: str
    symbol: str
    plan_id: str
    plan_hash: str
    content_hash: str
    payload_json: str
    review_id: str
    daily_issues: tuple = ()
    daily_mapping: object = True


class _ResearchPlans:
    def __init__(self, owner):
        self.owner = owner

    def get_active(self, symbol):
        return self.owner.active if symbol == self.owner.plan.symbol else None

    def get_version_details(self, version_id):
        return self.owner.details if version_id == self.owner.details.id else None


class _ResearchRuntime(DailyRuntimeEvaluationService):
    def _enqueue(self, *args, **kwargs):
        # Private adapter suppresses enqueueing; online behavior is untouched.
        return None


class ResearchSession:
    def __init__(self, directory, run_input, calendar):
        self.run_input = run_input
        self.plan = run_input.plan_snapshot
        self.now = run_input.research_input.started_at
        self._counter = 0
        self.engine = create_sqlite_engine(directory / "runtime.sqlite")
        Base.metadata.create_all(self.engine)
        self.factory = create_session_factory(self.engine)
        version_id = str(UUID(run_input.authority_id[:32]))
        review_id = str(UUID(sha256((run_input.authority_id + "review").encode()).hexdigest()[:32]))
        self.active = _ResearchActive(version_id, self.now)
        self.details = _ResearchDetails(
            version_id,
            self.plan.symbol,
            self.plan.plan_id,
            run_input.plan_sha256,
            run_input.research_input.review.content_hash,
            dump_plan_json(self.plan),
            review_id,
        )
        self.runtime = _ResearchRuntime(self.work, clock=lambda: self.now)
        with self.work() as work:
            for day in calendar:
                work.daily.session.add(TradingCalendar(**day.model_dump()))
            if run_input.research_input.inventory_known:
                lots = run_input.initial_lots
                work.daily.save(
                    "simulation-position-" + self.plan.symbol,
                    kind="POSITION",
                    symbol=self.plan.symbol,
                    lineage=self.plan.symbol,
                    expected_revision=0,
                    payload={
                        "simulation_version": "daily-simulation-v1",
                        "initialized_at": self.now.isoformat(),
                        "initial_core_qty": sum(
                            lot.quantity for lot in lots if lot.bucket == "CORE"
                        ),
                        "initial_tactical_qty": sum(
                            lot.quantity for lot in lots if lot.bucket == "TACTICAL"
                        ),
                        "batches": [
                            {
                                "id": lot.lot_key,
                                "bucket": lot.bucket,
                                "quantity": lot.quantity,
                                "acquired_trade_date": str(lot.acquired_trade_date),
                                "baseline": False,
                            }
                            for lot in lots
                        ],
                    },
                )
            work.daily.save(
                "review-" + version_id,
                kind="REVIEW",
                symbol=self.plan.symbol,
                lineage=self.plan.plan_id,
                expected_revision=0,
                payload={
                    "confirmed": True,
                    "content_hash": self.details.content_hash,
                    "source_hash": run_input.plan_sha256,
                    "evidence_hash": run_input.plan_sha256,
                    "review_id": review_id,
                    "review_revision": 1,
                    "plan_version_id": version_id,
                },
            )
            work.commit()

    def _id(self):
        self._counter += 1
        return str(
            UUID(
                sha256((self.run_input.authority_id + str(self._counter)).encode()).hexdigest()[:32]
            )
        )

    @contextmanager
    def work(self):
        with SqlAlchemyUnitOfWork(
            self.factory, clock=lambda: self.now, id_factory=self._id
        ) as work:
            work._plans = _ResearchPlans(self)
            yield work

    def inventory(self):
        with self.work() as work:
            return DailyAccounting(work.daily).snapshot(self.plan.symbol, self.now.date())

    def resolve_cause(self, *, rule_id=None, occurrence=None, risk_kind=None):
        with self.work() as work:
            if risk_kind is not None:
                return next(
                    (
                        row
                        for row in work.daily.list(symbol=self.plan.symbol, kind="RISK")
                        if row["payload"]["kind"] == risk_kind
                    ),
                    None,
                )
            if occurrence is None:
                return None
            index = 0
            for row in work.daily.iter_records(symbol=self.plan.symbol, kind="SIGNAL"):
                if row["payload"]["rule_id"] == rule_id:
                    index += 1
                    if index == occurrence:
                        return row
            return None

    def apply_evidence(self, operation, inputs):
        before = DailyInventoryView.model_validate(self.inventory())
        blockers = []
        try:
            if operation.kind == "FACT":
                if operation.fact_kind == "FULL_SESSION_SUSPENSION":
                    raise ValueError("RESEARCH_FULL_SESSION_SUSPENSION_UNSUPPORTED")
                from trade_plan_monitor.web.daily_service import _record_fact
                from trade_plan_monitor.web.routers.daily_plans import DailyFactCommand

                cause = self.resolve_cause(
                    rule_id=operation.rule_id, occurrence=operation.occurrence
                )
                if operation.rule_id is not None and cause is None:
                    raise ValueError("RESEARCH_FACT_SIGNAL_NOT_FOUND")
                with self.work() as work:
                    identity = daily_hash(
                        "daily-human-fact-v1",
                        {"symbol": self.plan.symbol, "fact_id": operation.fact_id},
                    )
                    prior = work.daily.get(identity)
                    command = DailyFactCommand(
                        plan_version_id=UUID(self.details.id),
                        content_hash=self.details.content_hash,
                        fact_id=operation.fact_id,
                        kind=operation.fact_kind,
                        trade_date=operation.trade_date,
                        signal_id=None if cause is None else cause["id"],
                        evidence=operation.evidence,
                        satisfied=operation.satisfied,
                        official_evidence=None
                        if operation.official_evidence is None
                        else operation.official_evidence.model_dump(mode="python"),
                        expected_revision=0 if prior is None else prior["revision"],
                    )
                    head = {
                        "payload": {
                            "plan_version_id": self.details.id,
                            "daily_evidence": None
                            if inputs.series is None
                            else inputs.series.model_dump(mode="python"),
                            "minute_target": None
                            if inputs.minute_target is None
                            else inputs.minute_target.isoformat(),
                            "five_minute_bars": [
                                bar.model_dump(mode="json") for bar in inputs.five_minute_bars
                            ],
                        }
                    }
                    _record_fact(work, self.details, command, self.now, evidence_head=head)
                    work.commit()
            elif operation.kind == "REPLACE":
                if operation.replacement_plan_hash == self.run_input.plan_sha256:
                    raise ValueError("RESEARCH_REPLACEMENT_REQUIRES_DISTINCT_REVIEWED_IDENTITY")
        except ValueError as error:
            reason = str(error)
            blockers = [
                reason
                if reason
                in {
                    "RESEARCH_FACT_SIGNAL_NOT_FOUND",
                    "RESEARCH_FULL_SESSION_SUSPENSION_UNSUPPORTED",
                    "RESEARCH_REPLACEMENT_REQUIRES_DISTINCT_REVIEWED_IDENTITY",
                }
                else "RESEARCH_FACT_OFFICIAL_PROOF_UNAVAILABLE"
                if "publication/verification" in reason
                else "RESEARCH_FACT_REJECTED"
            ]
        return ResearchOperationOutcome(
            operation_id=operation.operation_id,
            at=self.now,
            kind=operation.kind,
            status="BLOCKED" if blockers else "APPLIED",
            blockers=tuple(blockers),
            inventory_before=before,
            inventory_after=DailyInventoryView.model_validate(self.inventory()),
        )

    def close(self):
        self.engine.dispose()

    def apply_operation(self, operation, *, ended):
        from types import SimpleNamespace

        from trade_plan_monitor.state.simulation import (
            SimulationAuthorityError,
            SimulationCommand,
            simulate_inventory,
        )
        from trade_plan_monitor.web.daily_service import mutate_daily
        from trade_plan_monitor.web.errors import ApiError
        from trade_plan_monitor.web.idempotency import operation_hash
        from trade_plan_monitor.web.routers.daily_plans import (
            DailyRiskReassessmentCommand,
        )
        from trade_plan_monitor.web.schemas import MutationContext

        before = DailyInventoryView.model_validate(self.inventory())
        receipt, cause, blockers = None, None, []
        try:
            cause = self.resolve_cause(
                rule_id=getattr(operation, "rule_id", None),
                occurrence=getattr(operation, "occurrence", None),
                risk_kind=getattr(operation, "risk_kind", None),
            )
            if cause is None:
                raise ValueError("RESEARCH_OPERATION_CAUSE_NOT_FOUND")
            if operation.kind == "SIMULATE":
                if ended and cause["kind"] == "SIGNAL":
                    raise ValueError("ORDINARY_AUTHORITY_ENDED")
                command = SimulationCommand(
                    plan_version_id=UUID(self.details.id),
                    cause_id=cause["id"],
                    expected_cause_revision=cause["revision"],
                    expected_inventory_revision=before.revision,
                    quantity=operation.quantity,
                )
                identity = str(
                    UUID(
                        sha256(
                            (
                                self.run_input.authority_id
                                + ":simulation:"
                                + operation.operation_id
                            ).encode()
                        ).hexdigest()[:32]
                    )
                )
                with self.work() as work:
                    receipt = simulate_inventory(
                        work, command, self.now, identity_factory=lambda: identity,
                    )
                    work.commit()
            else:
                branch = next(
                    branch
                    for branch in self.plan.risk_branches
                    if branch.kind == operation.risk_kind
                )
                command = DailyRiskReassessmentCommand(
                    symbol=self.plan.symbol,
                    risk_id=cause["id"],
                    plan_version_id=UUID(self.details.id),
                    content_hash=self.details.content_hash,
                    expected_revision=cause["revision"],
                    removal_evidence=operation.removal_evidence,
                    target_core_qty=branch.target_core_qty,
                    target_tactical_qty=branch.target_tactical_qty,
                    involves_core=branch.involves_core,
                    scope_evidence=branch.scope_evidence,
                )
                context = MutationContext(
                    idempotency_key=operation.operation_id,
                    request_id=sha256(operation.operation_id.encode()).hexdigest()[:32],
                )
                mutate_daily(
                    SimpleNamespace(_unit_of_work=self.work, _clock=lambda: self.now),
                    operation_name="REASSESSMENT",
                    command=command,
                    context=context,
                    request_hash=operation_hash("REASSESSMENT", command),
                )
        except SimulationAuthorityError as error:
            blockers = [error.reason]
        except ApiError as error:
            blockers = [detail.code for detail in error.details]
        except ValueError as error:
            blockers = [
                "FULL_QUANTITY_REQUIRED"
                if "complete offered quantity" in str(error)
                else str(error)
                if str(error)
                in {
                    "ORDINARY_AUTHORITY_ENDED",
                    "RESEARCH_OPERATION_CAUSE_NOT_FOUND",
                }
                else "RESEARCH_OPERATION_REJECTED"
            ]
        return ResearchOperationOutcome(
            operation_id=operation.operation_id,
            at=self.now,
            kind=operation.kind,
            status="BLOCKED" if blockers else "APPLIED",
            blockers=tuple(blockers),
            cause_id=None if cause is None else cause["id"],
            quantity=getattr(operation, "quantity", None),
            simulation_id=None if receipt is None else receipt.simulation_id,
            side=None if receipt is None else receipt.side,
            monitor_price_fen=None if receipt is None else receipt.price_fen,
            inventory_before=before,
            inventory_after=DailyInventoryView.model_validate(self.inventory()),
        )
