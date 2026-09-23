"""Durable evidence for the five-day runtime-interruption admission decision."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from trade_plan_monitor.runtime.clock import _canonical_shanghai
from trade_plan_monitor.state.models import ActivePlan, RuntimeLiveness

MAX_INTERRUPTION = timedelta(hours=120)


class RuntimeLivenessError(RuntimeError):
    """Liveness evidence is invalid or changed; no automatic admission is safe."""


class InterruptionDecision(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class LivenessSnapshot:
    revision: int
    last_alive_at: datetime


def classify_interruption(last_alive_at: datetime | None, now: datetime) -> InterruptionDecision:
    """Classify only observed local downtime, never an inferred last startup."""

    observed_now = _canonical_shanghai(now)
    if last_alive_at is None:
        return InterruptionDecision.UNKNOWN
    observed_last = _canonical_shanghai(last_alive_at)
    if observed_last > observed_now:
        return InterruptionDecision.UNKNOWN
    return (
        InterruptionDecision.EXPIRED
        if observed_now - observed_last > MAX_INTERRUPTION
        else InterruptionDecision.ELIGIBLE
    )


class RuntimeLivenessRepository:
    """Own the singleton heartbeat; initialization is safe only without active plans."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def load(self) -> LivenessSnapshot | None:
        try:
            with self._session_factory() as session:
                return liveness_snapshot(session.get(RuntimeLiveness, 1))
        except Exception:
            raise RuntimeLivenessError("invalid runtime liveness") from None

    def initialize_empty(self, now: datetime) -> LivenessSnapshot:
        """Initialize a fresh installation; legacy active plans must be reviewed."""

        observed_at = _canonical_shanghai(now)
        try:
            with self._session_factory.begin() as session:
                if session.get(RuntimeLiveness, 1) is not None:
                    raise RuntimeLivenessError("runtime liveness already initialized")
                if session.scalar(select(ActivePlan.symbol).limit(1)) is not None:
                    raise RuntimeLivenessError("active plans lack runtime liveness evidence")
                session.add(
                    RuntimeLiveness(
                        id=1,
                        schema_version=1,
                        revision=0,
                        last_alive_at=observed_at.isoformat(),
                    )
                )
            return LivenessSnapshot(0, observed_at)
        except RuntimeLivenessError:
            raise
        except Exception:
            raise RuntimeLivenessError("invalid runtime liveness") from None

    def touch(self, now: datetime, *, expected_revision: int) -> LivenessSnapshot:
        """Advance only the observed revision; a stale owner cannot write over it."""

        if type(expected_revision) is not int or expected_revision < 0:
            raise RuntimeLivenessError("invalid expected liveness revision")
        observed_at = _canonical_shanghai(now)
        try:
            with self._session_factory.begin() as session:
                row = session.get(RuntimeLiveness, 1)
                current = liveness_snapshot(row)
                if current is None or current.revision != expected_revision:
                    raise RuntimeLivenessError("runtime liveness changed")
                if observed_at < current.last_alive_at:
                    raise RuntimeLivenessError("runtime clock moved backwards")
                if observed_at == current.last_alive_at:
                    return current
                row.revision += 1
                row.last_alive_at = observed_at.isoformat()
                next_revision = row.revision
            return LivenessSnapshot(next_revision, observed_at)
        except RuntimeLivenessError:
            raise
        except Exception:
            raise RuntimeLivenessError("invalid runtime liveness") from None


def liveness_snapshot(row: RuntimeLiveness | None) -> LivenessSnapshot | None:
    if row is None:
        return None
    if row.schema_version != 1 or type(row.revision) is not int or row.revision < 0:
        raise ValueError("invalid runtime liveness metadata")
    timestamp = _canonical_shanghai(datetime.fromisoformat(row.last_alive_at))
    if row.last_alive_at != timestamp.isoformat():
        raise ValueError("noncanonical runtime liveness timestamp")
    return LivenessSnapshot(row.revision, timestamp)
