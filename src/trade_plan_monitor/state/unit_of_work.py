"""Explicit SQLAlchemy unit-of-work lifecycle for local strategy state."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from trade_plan_monitor.state.repositories import (
    EpisodeRepository,
    EvaluationRepository,
    HealthRepository,
    IdempotencyRepository,
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
    def evaluations(self) -> EvaluationRepository: ...

    @property
    def health(self) -> HealthRepository: ...

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
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or (lambda: str(uuid4()))
        self._session: Session | None = None
        self._plans: PlanRepository | None = None
        self._idempotency: IdempotencyRepository | None = None
        self._positions: PositionRepository | None = None
        self._episodes: EpisodeRepository | None = None
        self._risk: RiskRepository | None = None
        self._evaluations: EvaluationRepository | None = None
        self._health: HealthRepository | None = None

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
    def evaluations(self) -> EvaluationRepository:
        if self._evaluations is None:
            raise RuntimeError("Unit of work is not active")
        return self._evaluations

    @property
    def health(self) -> HealthRepository:
        if self._health is None:
            raise RuntimeError("Unit of work is not active")
        return self._health

    def __enter__(self) -> SqlAlchemyUnitOfWork:
        if self._session is not None:
            raise RuntimeError("Unit of work cannot be re-entered")
        self._session = self._session_factory()
        self._session.begin()
        self._plans = PlanRepository(
            self._session,
            clock=self._clock,
            id_factory=self._id_factory,
        )
        self._idempotency = IdempotencyRepository(self._session, clock=self._clock)
        self._positions = PositionRepository(
            self._session,
            clock=self._clock,
            id_factory=self._id_factory,
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
        self._evaluations = EvaluationRepository(self._session)
        self._health = HealthRepository(self._session)
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
            self._evaluations = None
            self._health = None

    def _require_session(self) -> Session:
        if self._session is None:
            raise RuntimeError("Unit of work is not active")
        return self._session


__all__ = ["SqlAlchemyUnitOfWork", "UnitOfWork"]
