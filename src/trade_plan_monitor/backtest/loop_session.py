"""Fresh private SQLite monitor state with frozen authority, virtual time and no sink."""

from bisect import bisect_right
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, time
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.loop_account import ACCOUNT_METADATA, LoopAccountParticipant
from trade_plan_monitor.backtest.loop_input import (
    MonitorLoopInput,
    ScheduledLoopInput,
    decode_monitor_loop_input_json,
)
from trade_plan_monitor.backtest.loop_report import LoopAccountDiscrepancy, LoopPlanTransition
from trade_plan_monitor.backtest.plan_schedule import require_loop_timestamp
from trade_plan_monitor.backtest.reminder_capture import CAPTURE_METADATA, ReminderCapture
from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.plan_codec import dump_plan_json
from trade_plan_monitor.domain.plan_validation import PlanValidationResult
from trade_plan_monitor.notifications.outbox import AlertNotFoundError
from trade_plan_monitor.runtime.daily_service import (
    DailyRuntimeEvaluationService,
    DailyRuntimeInputs,
)
from trade_plan_monitor.state.daily_accounting import DailyAccounting
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import (
    ActivePlan,
    Base,
    MonitorSequence,
    PlanActivationState,
    PlanSource,
    PlanVersion,
    TradingCalendar,
)
from trade_plan_monitor.state.repositories import PlanRepository
from trade_plan_monitor.state.simulation import SimulationAuthorityError
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork


@dataclass(frozen=True)
class _LoopVersionDetails:
    id: str
    plan_id: str
    symbol: str
    plan_hash: str
    content_hash: str
    review_id: str
    payload_json: str
    daily_issues: tuple = ()


class _LoopPlans:
    """Frozen review adapter; active binding remains in the actual private database."""

    def __init__(self, plans, details):
        self.plans, self.details = plans, details

    def get_active(self, symbol):
        return self.plans.get_active(symbol)

    def get_version_details(self, version_id):
        return self.details if version_id == self.details.id else None


class _LoopActivationPlans(PlanRepository):
    """Map a frozen version to a private key without rewriting its source snapshot."""

    def __init__(self, *args, plan, storage_plan_id, **kwargs):
        super().__init__(*args, **kwargs)
        self.plan, self.storage_plan_id = plan, storage_plan_id

    def get_version(self, plan_id, version):
        if (plan_id, version) != (self.plan.plan_id, self.plan.version):
            return None
        return super().get_version(self.storage_plan_id, version)


class LoopSession:
    def __init__(self, directory: Path, run_input: MonitorLoopInput | ScheduledLoopInput, calendar):
        self.run_input = decode_monitor_loop_input_json(run_input.model_dump_json())
        boundary = self.run_input.boundary
        self.run_input.schedule.preflight(
            calendar, started_at=boundary.started_at, evidence_cutoff=boundary.evidence_cutoff
        )
        self.selection = self.run_input.schedule.select(boundary.started_at)
        self.plan = self.selection.version.snapshot
        self.now = boundary.started_at
        self._transition_points = ()
        if isinstance(self.run_input, ScheduledLoopInput):
            points = {
                max(datetime.combine(row.effective_trade_date, time.min, self.now.tzinfo),
                    row.version.available_at)
                for row in self.run_input.schedule.entries
            }
            points.update(
                datetime.combine(day.cal_date, time(9, 30), self.now.tzinfo)
                for day in calendar if day.is_open and day.exchange == self.plan.market
            )
            self._transition_points = tuple(sorted(
                point for point in points if self.now < point <= boundary.evidence_cutoff
            ))
        self._authority_available = True
        self._lifecycle_day = self.now.date()
        self.context_mismatches = self.blocked_rule_ids = ()
        self._counter = 0
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "loop-runtime.sqlite"
        if path.exists():
            raise ValueError("LOOP_SESSION_REQUIRES_FRESH_PRIVATE_DATABASE")
        self.engine = create_sqlite_engine(path)
        try:
            Base.metadata.create_all(self.engine)
            CAPTURE_METADATA.create_all(self.engine)
            ACCOUNT_METADATA.create_all(self.engine)
            self.factory = create_session_factory(self.engine)
            version_id, review_id = str(self.identity("version")), str(self.identity("review"))
            self.details = _LoopVersionDetails(
                id=version_id,
                plan_id=self.plan.plan_id,
                symbol=self.plan.symbol,
                plan_hash=self.selection.version.plan_hash,
                content_hash=self.selection.version.review.content_hash,
                review_id=review_id,
                payload_json=dump_plan_json(self.plan),
            )
            self.runtime = DailyRuntimeEvaluationService(
                self.work,
                clock=lambda: self.now,
                event_id_factory=lambda key: self.identity("reminder", key),
            )
            self._seed(calendar)
            if isinstance(self.run_input, ScheduledLoopInput):
                self._compare_account_context()
        except BaseException:
            self.engine.dispose()
            raise

    def identity(self, namespace, key="") -> UUID:
        authority = self.selection.authority_id
        if isinstance(self.run_input, ScheduledLoopInput) and namespace in {
            "version", "review", "manifest",
        }:
            authority = self.selection.version.causal_hash
        return UUID(
            sha256(
                canonical_json(
                    {"authority": authority, "namespace": namespace, "key": key}
                ).encode()
            ).hexdigest()[:32]
        )

    def _id(self):
        self._counter += 1
        return str(self.identity("audit", str(self._counter)))

    @contextmanager
    def work(self):
        with SqlAlchemyUnitOfWork(
            self.factory, clock=lambda: self.now, id_factory=self._id
        ) as work:
            plans = work.plans
            if isinstance(self.run_input, ScheduledLoopInput):
                plans = _LoopActivationPlans(
                    work.daily.session, clock=lambda: self.now, id_factory=self._id,
                    events=work.events, plan=self.plan, storage_plan_id=self.details.id,
                )
            work._plans = _LoopPlans(plans, self.details)
            yield work

    def _seed(self, calendar):
        source_id = str(self.identity("manifest"))
        # This is a reviewed manifest, explicitly not the unavailable original source text.
        manifest = canonical_json(
            {
                "kind": "FROZEN_REVIEWED_LOOP_VERSION",
                "version": self.selection.version.model_dump(mode="json"),
            }
        )
        with self.work() as work:
            session = work.daily.session
            session.add(MonitorSequence(singleton_id=1, last_sequence=0))
            session.add_all([TradingCalendar(**day.model_dump()) for day in calendar])
            session.add(
                PlanSource(
                    id=source_id,
                    source_text=manifest,
                    source_hash=sha256(manifest.encode()).hexdigest(),
                    created_at=self.now.isoformat(),
                )
            )
            session.flush()
            session.add(
                PlanVersion(
                    id=self.details.id,
                    plan_id=(self.details.id if isinstance(self.run_input, ScheduledLoopInput)
                             else self.plan.plan_id),
                    version=self.plan.version,
                    symbol=self.plan.symbol,
                    plan_hash=self.details.plan_hash,
                    status="ACTIVE",
                    payload_json=dump_plan_json(self.plan),
                    source_id=source_id,
                    revision=1,
                    created_at=self.now.isoformat(),
                )
            )
            session.flush()
            session.add(
                ActivePlan(
                    symbol=self.plan.symbol,
                    plan_version_id=self.details.id,
                    activated_at=self.selection.activated_at.isoformat(),
                    revision=1,
                )
            )
            if isinstance(self.run_input, ScheduledLoopInput):
                session.add(PlanActivationState(
                    symbol=self.plan.symbol, plan_version_id=self.details.id, revision=1,
                    changed_at=self.selection.activated_at.isoformat(),
                ))
            opening = self.run_input.initial_account
            LoopAccountParticipant(work).initialize(opening)
            if opening.inventory_known:
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
                            lot.quantity for lot in opening.lots if lot.bucket == "CORE"
                        ),
                        "initial_tactical_qty": sum(
                            lot.quantity for lot in opening.lots if lot.bucket == "TACTICAL"
                        ),
                        "batches": [
                            {
                                "origin": "monitor-loop-opening-v1",
                                "id": lot.lot_key,
                                "bucket": lot.bucket,
                                "quantity": lot.quantity,
                                "acquired_trade_date": None
                                if lot.acquired_trade_date is None
                                else str(lot.acquired_trade_date),
                                "observed_trade_date": str(opening.snapshot_at.date()),
                                "sellable_quantity": lot.sellable_quantity,
                            }
                            for lot in opening.lots
                        ],
                    },
                )
            work.daily.save(
                "review-" + self.details.id,
                kind="REVIEW",
                symbol=self.plan.symbol,
                lineage=self.plan.plan_id,
                expected_revision=0,
                payload={
                    "confirmed": True,
                    "content_hash": self.details.content_hash,
                    "source_hash": daily_hash(
                        "monitor-loop-source-binding-v1",
                        {"source_hashes": self.selection.version.source_hashes},
                    ),
                    "evidence_hash": self.selection.version.evidence_hash,
                    "review_id": self.details.review_id,
                    "review_revision": 1,
                    "plan_version_id": self.details.id,
                },
            )
            work.commit()

    def inventory(self):
        with self.work() as work:
            return DailyAccounting(work.daily).snapshot(self.plan.symbol, self.now.date())

    def account(self):
        with self.work() as work:
            return LoopAccountParticipant(work).state()

    def execute(self, command, *, request_key):
        if self.run_input.response.mode == "OBSERVE_ONLY":
            raise ValueError("LOOP_OBSERVE_ONLY")
        if isinstance(self.run_input, ScheduledLoopInput):
            selected = self.run_input.schedule.select(self.now)
            if selected is not None and selected.authority_id != self.selection.authority_id:
                raise SimulationAuthorityError("LOOP_CURRENT_AUTHORITY_MISSING")
        with self.work() as work:
            cause = work.daily.get(command.cause_id)
            if cause is not None and cause["kind"] == "SIGNAL":
                if not self._authority_available or (
                    isinstance(self.run_input, ScheduledLoopInput) and selected is None
                ):
                    raise SimulationAuthorityError("PLAN_ACTIVATION_WINDOW_ENDED")
                if cause["payload"]["rule_id"] in self.blocked_rule_ids:
                    raise SimulationAuthorityError("LOOP_ACCOUNT_CONTEXT_INCOMPATIBLE")
            receipt = LoopAccountParticipant(work).apply(
                command,
                request_key=request_key,
                costs=self.run_input.costs,
                now=self.now,
                identity_factory=lambda: str(self.identity("fill", request_key)),
            )
            work.commit()
            return receipt

    def set_time(self, now):
        now = require_loop_timestamp(now)
        if not self.now <= now <= self.run_input.boundary.evidence_cutoff:
            raise ValueError("LOOP_TIME_OUTSIDE_FROZEN_INTERVAL")
        self.now = now

    def _compare_account_context(self):
        context = self.selection.version.account_context
        inventory = self.inventory()
        mismatches = []
        if context is not None:
            for bucket, stated in (("CORE", context.core_qty), ("TACTICAL", context.tactical_qty)):
                actual = inventory[bucket.lower() + "_qty"] if inventory["known"] else None
                if stated is not None and stated != actual:
                    mismatches.append(LoopAccountDiscrepancy(
                        bucket=bucket, stated_qty=stated, actual_qty=actual,
                    ))
        self.context_mismatches = tuple(mismatches)
        self.blocked_rule_ids = context.dependent_rule_ids if mismatches else ()

    def _activate_selection(self, selected):
        """Use the shared activation transaction; the existing ledger/risk rows stay in place."""
        before = self.selection, self.plan, self.details, self.now, self._counter
        self.selection, self.plan = selected, selected.version.snapshot
        self.now = selected.activated_at
        self.details = _LoopVersionDetails(
            id=str(self.identity("version")), plan_id=self.plan.plan_id, symbol=self.plan.symbol,
            plan_hash=selected.version.plan_hash, content_hash=selected.version.review.content_hash,
            review_id=str(self.identity("review")), payload_json=dump_plan_json(self.plan),
        )
        try:
            with self.work() as work:
                session = work.daily.session
                if session.get(PlanVersion, self.details.id) is None:
                    manifest = canonical_json({
                        "kind": "FROZEN_REVIEWED_LOOP_VERSION",
                        "version": selected.version.model_dump(mode="json"),
                    })
                    source_id = str(self.identity("manifest"))
                    session.add(PlanSource(
                        id=source_id, source_text=manifest,
                        source_hash=sha256(manifest.encode()).hexdigest(),
                        created_at=self.now.isoformat(),
                    ))
                    session.flush()
                    session.add(PlanVersion(
                        id=self.details.id, plan_id=self.details.id, version=self.plan.version,
                        symbol=self.plan.symbol, plan_hash=self.details.plan_hash, status="DRAFT",
                        payload_json=self.details.payload_json, source_id=source_id, revision=1,
                        created_at=self.now.isoformat(),
                    ))
                    session.flush()
                    work.daily.save(
                        "review-" + self.details.id, kind="REVIEW", symbol=self.plan.symbol,
                        lineage=self.plan.plan_id, expected_revision=0,
                        payload={
                            "confirmed": True, "content_hash": self.details.content_hash,
                            "source_hash": daily_hash("monitor-loop-source-binding-v1", {
                                "source_hashes": selected.version.source_hashes,
                            }),
                            "evidence_hash": selected.version.evidence_hash,
                            "review_id": self.details.review_id, "review_revision": 1,
                            "plan_version_id": self.details.id,
                        },
                    )
                active = work.plans.get_active(self.plan.symbol)
                work.plans.plans.activate(
                    self.plan, expected_revision=active.revision,
                    validation=PlanValidationResult(issues=()),
                )
                work.commit()
        except BaseException:
            self.selection, self.plan, self.details, self.now, self._counter = before
            raise
        self._compare_account_context()

    def advance(self, now) -> tuple[LoopPlanTransition, ...]:
        """Traverse all intervening boundaries, including days without market frames."""
        now = require_loop_timestamp(now)
        if not self.now <= now <= self.run_input.boundary.evidence_cutoff:
            raise ValueError("LOOP_TIME_OUTSIDE_FROZEN_INTERVAL")
        if not isinstance(self.run_input, ScheduledLoopInput):
            self.set_time(now)
            return ()
        # Each frame visits only crossed boundaries, rather than rescanning the full calendar.
        start, end = (bisect_right(self._transition_points, value) for value in (self.now, now))
        points = self._transition_points[start:end]
        if not points or points[-1] != now:
            points = (*points, now)
        transitions = []
        for point in points:
            selected = self.run_input.schedule.select(point)
            previous = self.selection.version.version_id
            changed = selected is not None and selected.authority_id != self.selection.authority_id
            new_day = point.date() != self._lifecycle_day
            available = selected is not None
            if changed:
                self._activate_selection(selected)
            self.now = point
            if changed or new_day or available != self._authority_available:
                transitions.append(LoopPlanTransition(
                    kind="REPLACED" if changed else "CONTINUED" if available else "NO_AUTHORITY",
                    at=point, from_version_id=previous,
                    version_id=None if selected is None else selected.version.version_id,
                    authority_id=None if selected is None else selected.authority_id,
                    context_mismatches=self.context_mismatches,
                    blocked_rule_ids=self.blocked_rule_ids,
                ))
            self._authority_available = available
            self._lifecycle_day = point.date()
        return tuple(transitions)

    def _block_incompatible_signals(self, result):
        if not self.blocked_rule_ids:
            return result
        signals = []
        with self.work() as work:
            for signal in result.snapshot["signals"]:
                if (signal["plan_version_id"] == self.details.id
                    and signal["rule_id"] in self.blocked_rule_ids
                    and signal["state"] not in {"SIMULATED", "EXPIRED", "INVALIDATED"}):
                    row = work.daily.get(signal["signal_id"])
                    payload = {**row["payload"], "executable_qty": 0, "blockers": [
                        *dict.fromkeys((*signal["blockers"], "LOOP_ACCOUNT_CONTEXT_INCOMPATIBLE")),
                    ]}
                    if payload != row["payload"]:
                        row = work.daily.save(
                            row["id"], kind="SIGNAL", symbol=self.plan.symbol,
                            lineage=row["lineage"], payload=payload,
                            expected_revision=row["revision"],
                        )
                    signal = {**payload, "revision": row["revision"]}
                signals.append(signal)
            work.commit()
        return result.model_copy(update={"snapshot": {**result.snapshot, "signals": signals}})

    def evaluate(self, inputs: DailyRuntimeInputs):
        inputs = DailyRuntimeInputs.model_validate(inputs.model_dump())
        if isinstance(self.run_input, ScheduledLoopInput):
            self.advance(inputs.evaluated_at)
        selected = self.run_input.schedule.select(inputs.evaluated_at)
        if selected is not None and selected.authority_id != self.selection.authority_id:
            raise ValueError("LOOP_PLAN_AUTHORITY_UNAVAILABLE")
        self.set_time(inputs.evaluated_at)
        with self.work() as work:
            work.history.upsert_minutes(inputs.minute_prefix)
            for bar in inputs.five_minute_bars:
                work.history.upsert_five_minute(**bar.model_dump())
            work.commit()
        result = self.runtime.run_inputs(
            plan=self.plan, inputs=inputs, allow_ineligible_observation=True,
            ordinary_authority_ended=not self._authority_available,
        )
        return self._block_incompatible_signals(result)

    def capture(self, event_ids, *, at=None):
        if len(event_ids) > 50:
            raise ValueError("LOOP_REMINDER_BATCH_TOO_LARGE")
        if at is not None:
            self.set_time(at)
        with self.work() as work:
            work.daily.lock_symbol(self.plan.symbol)
            capture = ReminderCapture(work, limit=self.run_input.limits.max_reminders)
            results = []
            for identity in event_ids:
                try:
                    event = work.alerts.get(UUID(identity))
                except AlertNotFoundError as error:
                    raise ValueError("LOOP_REMINDER_NOT_FOUND") from error
                results.append(capture.capture(event, self.now))
            work.commit()
            return tuple(results)

    def reminders(self, *, after_sequence=0, limit=100):
        with self.work() as work:
            return ReminderCapture(work, limit=self.run_input.limits.max_reminders).page(
                after_sequence=after_sequence, limit=limit
            )

    def __enter__(self):
        return self

    def __exit__(self, *error):
        self.engine.dispose()
