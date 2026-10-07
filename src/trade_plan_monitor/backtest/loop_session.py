"""Fresh private SQLite monitor state with frozen authority, virtual time and no sink."""

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.loop_account import ACCOUNT_METADATA, LoopAccountParticipant
from trade_plan_monitor.backtest.loop_input import MonitorLoopInput
from trade_plan_monitor.backtest.plan_schedule import require_loop_timestamp
from trade_plan_monitor.backtest.reminder_capture import CAPTURE_METADATA, ReminderCapture
from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.plan_codec import dump_plan_json
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
    PlanSource,
    PlanVersion,
    TradingCalendar,
)
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


class LoopSession:
    def __init__(self, directory: Path, run_input: MonitorLoopInput, calendar):
        self.run_input = MonitorLoopInput.model_validate_json(run_input.model_dump_json())
        boundary = self.run_input.boundary
        self.run_input.schedule.preflight(
            calendar, started_at=boundary.started_at, evidence_cutoff=boundary.evidence_cutoff
        )
        self.selection = self.run_input.schedule.select(boundary.started_at)
        self.plan = self.selection.version.snapshot
        self.now = boundary.started_at
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
        except BaseException:
            self.engine.dispose()
            raise

    def identity(self, namespace, key="") -> UUID:
        return UUID(
            sha256(
                canonical_json(
                    {"authority": self.selection.authority_id, "namespace": namespace, "key": key}
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
            work._plans = _LoopPlans(work.plans, self.details)
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
                    plan_id=self.plan.plan_id,
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
        with self.work() as work:
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

    def evaluate(self, inputs: DailyRuntimeInputs):
        inputs = DailyRuntimeInputs.model_validate(inputs.model_dump())
        selected = self.run_input.schedule.select(inputs.evaluated_at)
        if selected is not None and selected.authority_id != self.selection.authority_id:
            raise ValueError("LOOP_PLAN_AUTHORITY_UNAVAILABLE")
        self.set_time(inputs.evaluated_at)
        with self.work() as work:
            work.history.upsert_minutes(inputs.minute_prefix)
            for bar in inputs.five_minute_bars:
                work.history.upsert_five_minute(**bar.model_dump())
            work.commit()
        return self.runtime.run_inputs(
            plan=self.plan, inputs=inputs, allow_ineligible_observation=True
        )

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
