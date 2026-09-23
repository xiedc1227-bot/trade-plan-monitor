"""Explicit SQLAlchemy unit-of-work lifecycle for local strategy state."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from trade_plan_monitor.notifications.outbox import (
    DEFAULT_REPLAY_RETENTION,
    AlertOutbox,
)
from trade_plan_monitor.state.events import MonitorEventLog
from trade_plan_monitor.state.explicit_rules import ExplicitDecisionRepository
from trade_plan_monitor.state.legacy_plan_invalidation import (
    LegacyPlanPreview,
    invalidate_legacy_plans,
    preview_legacy_invalidation,
)
from trade_plan_monitor.state.plan_expiry import expire_active_plans_after_interruption
from trade_plan_monitor.state.projections import ProjectionRepository
from trade_plan_monitor.state.repositories import (
    EpisodeRepository,
    EvaluationRepository,
    HealthRepository,
    IdempotencyRepository,
    ManualEventRiskRepository,
    MarketHistoryRepository,
    MarketReferenceRepository,
    PlanRepository,
    PositionRepository,
    RiskRepository,
)


class UnitOfWork(Protocol):
    """Persistence boundary used by application services without SQLAlchemy coupling."""

    @property
    def plans(self) -> PlanRepository: ...

    @property
    def idempotency(self) -> IdempotencyRepository: ...

    @property
    def positions(self) -> PositionRepository: ...

    @property
    def episodes(self) -> EpisodeRepository: ...

    @property
    def risk(self) -> RiskRepository: ...

    @property
    def manual_event_risk(self) -> ManualEventRiskRepository: ...

    @property
    def evaluations(self) -> EvaluationRepository: ...

    @property
    def explicit_rules(self) -> ExplicitDecisionRepository: ...

    @property
    def projections(self) -> ProjectionRepository: ...

    @property
    def health(self) -> HealthRepository: ...

    @property
    def alerts(self) -> AlertOutbox: ...

    @property
    def events(self) -> MonitorEventLog: ...

    @property
    def history(self) -> MarketHistoryRepository: ...

    @property
    def references(self) -> MarketReferenceRepository: ...

    def expire_active_plans_after_interruption(self) -> tuple[str, ...]: ...

    def invalidate_legacy_plans(self, *, expected_fingerprint: str) -> tuple[str, ...]: ...

    def preview_legacy_invalidation(self) -> LegacyPlanPreview: ...

    def __enter__(self) -> UnitOfWork: ...

    def __exit__(
        self,
        error_type: type[BaseException] | None,
        error: BaseException | None,
        traceback: object | None,
    ) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class SqlAlchemyUnitOfWork:
    """Own one short transaction and the repositories that participate in it."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
        replay_retention: timedelta = DEFAULT_REPLAY_RETENTION,
    ) -> None:
        if not isinstance(replay_retention, timedelta) or replay_retention <= timedelta(0):
            raise ValueError("replay_retention must be a positive timedelta")
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or (lambda: str(uuid4()))
        self._replay_retention = replay_retention
        self._session: Session | None = None
        self._plans: PlanRepository | None = None
        self._idempotency: IdempotencyRepository | None = None
        self._positions: PositionRepository | None = None
        self._episodes: EpisodeRepository | None = None
        self._risk: RiskRepository | None = None
        self._manual_event_risk: ManualEventRiskRepository | None = None
        self._evaluations: EvaluationRepository | None = None
        self._explicit_rules: ExplicitDecisionRepository | None = None
        self._projections: ProjectionRepository | None = None
        self._health: HealthRepository | None = None
        self._alerts: AlertOutbox | None = None
        self._events: MonitorEventLog | None = None
        self._history: MarketHistoryRepository | None = None
        self._references: MarketReferenceRepository | None = None

    @property
    def plans(self) -> PlanRepository:
        if self._plans is None:
            raise RuntimeError("Unit of work is not active")
        return self._plans

    @property
    def idempotency(self) -> IdempotencyRepository:
        if self._idempotency is None:
            raise RuntimeError("Unit of work is not active")
        return self._idempotency

    @property
    def positions(self) -> PositionRepository:
        if self._positions is None:
            raise RuntimeError("Unit of work is not active")
        return self._positions

    @property
    def episodes(self) -> EpisodeRepository:
        if self._episodes is None:
            raise RuntimeError("Unit of work is not active")
        return self._episodes

    @property
    def risk(self) -> RiskRepository:
        if self._risk is None:
            raise RuntimeError("Unit of work is not active")
        return self._risk

    @property
    def manual_event_risk(self) -> ManualEventRiskRepository:
        if self._manual_event_risk is None:
            raise RuntimeError("Unit of work is not active")
        return self._manual_event_risk

    @property
    def evaluations(self) -> EvaluationRepository:
        if self._evaluations is None:
            raise RuntimeError("Unit of work is not active")
        return self._evaluations

    @property
    def explicit_rules(self) -> ExplicitDecisionRepository:
        if self._explicit_rules is None:
            raise RuntimeError("Unit of work is not active")
        return self._explicit_rules

    @property
    def projections(self) -> ProjectionRepository:
        if self._projections is None:
            raise RuntimeError("Unit of work is not active")
        return self._projections

    @property
    def health(self) -> HealthRepository:
        if self._health is None:
            raise RuntimeError("Unit of work is not active")
        return self._health

    @property
    def alerts(self) -> AlertOutbox:
        if self._alerts is None:
            raise RuntimeError("Unit of work is not active")
        return self._alerts

    @property
    def events(self) -> MonitorEventLog:
        if self._events is None:
            raise RuntimeError("Unit of work is not active")
        return self._events

    @property
    def history(self) -> MarketHistoryRepository:
        if self._history is None:
            raise RuntimeError("Unit of work is not active")
        return self._history

    @property
    def references(self) -> MarketReferenceRepository:
        if self._references is None:
            raise RuntimeError("Unit of work is not active")
        return self._references

    def expire_active_plans_after_interruption(self) -> tuple[str, ...]:
        """Resolve the five-day gate in the same transaction as plan expiry."""

        return expire_active_plans_after_interruption(
            self._require_session(),
            self.plans,
            now=self._clock(),
            id_factory=self._id_factory,
        )

    def invalidate_legacy_plans(self, *, expected_fingerprint: str) -> tuple[str, ...]:
        """Apply one reviewed legacy invalidation in this unit of work."""

        return invalidate_legacy_plans(
            self._require_session(),
            self.plans,
            expected_fingerprint=expected_fingerprint,
            now=self._clock(),
            id_factory=self._id_factory,
        )

    def preview_legacy_invalidation(self) -> LegacyPlanPreview:
        """Read the exact active legacy identities without exposing a session."""

        return preview_legacy_invalidation(self._require_session())

    def __enter__(self) -> SqlAlchemyUnitOfWork:
        if self._session is not None:
            raise RuntimeError("Unit of work cannot be re-entered")
        self._session = self._session_factory()
        self._session.begin()
        self._events = MonitorEventLog(
            self._session,
            clock=self._clock,
            replay_retention=self._replay_retention,
        )
        self._plans = PlanRepository(
            self._session,
            clock=self._clock,
            id_factory=self._id_factory,
            events=self._events,
        )
        self._idempotency = IdempotencyRepository(self._session, clock=self._clock)
        self._positions = PositionRepository(
            self._session,
            clock=self._clock,
            id_factory=self._id_factory,
            events=self._events,
        )
        self._episodes = EpisodeRepository(
            self._session,
            clock=self._clock,
            id_factory=self._id_factory,
        )
        self._risk = RiskRepository(
            self._session,
            clock=self._clock,
            id_factory=self._id_factory,
        )
        self._manual_event_risk = ManualEventRiskRepository(
            self._session,
            clock=self._clock,
            id_factory=self._id_factory,
        )
        self._evaluations = EvaluationRepository(self._session)
        self._explicit_rules = ExplicitDecisionRepository(self._session)
        self._projections = ProjectionRepository(self._session)
        self._health = HealthRepository(
            self._session,
            clock=self._clock,
            events=self._events,
        )
        self._alerts = AlertOutbox(
            self._session,
            clock=self._clock,
            id_factory=self._id_factory,
            replay_retention=self._replay_retention,
            events=self._events,
        )
        self._history = MarketHistoryRepository(self._session)
        self._references = MarketReferenceRepository(self._session)
        return self

    def commit(self) -> None:
        self._require_session().commit()

    def rollback(self) -> None:
        self._require_session().rollback()

    def __exit__(
        self,
        _error_type: type[BaseException] | None,
        _error: BaseException | None,
        _traceback: object | None,
    ) -> None:
        session = self._require_session()
        try:
            if session.in_transaction():
                session.rollback()
        finally:
            session.close()
            self._session = None
            self._plans = None
            self._idempotency = None
            self._positions = None
            self._episodes = None
            self._risk = None
            self._manual_event_risk = None
            self._evaluations = None
            self._explicit_rules = None
            self._projections = None
            self._health = None
            self._alerts = None
            self._events = None
            self._history = None
            self._references = None

    def _require_session(self) -> Session:
        if self._session is None:
            raise RuntimeError("Unit of work is not active")
        return self._session


__all__ = ["SqlAlchemyUnitOfWork", "UnitOfWork"]
