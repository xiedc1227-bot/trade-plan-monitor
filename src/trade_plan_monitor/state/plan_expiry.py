"""Atomic plan and pending-close expiry after a proven long interruption."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from hashlib import sha256

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from trade_plan_monitor.runtime.clock import SHANGHAI, _canonical_shanghai
from trade_plan_monitor.state.models import (
    ActivePlan,
    AlertDeliveryEligibility,
    AuditLog,
    PendingOfficialClose,
    RuntimeLiveness,
)
from trade_plan_monitor.state.repositories import PlanRepository, RepositoryError
from trade_plan_monitor.state.runtime_liveness import (
    InterruptionDecision,
    RuntimeLivenessError,
    classify_interruption,
    liveness_snapshot,
)

_MAX_ACTIVE_PLANS = 10
_EXPIRY_CAUSE = "OUTAGE_OVER_120_HOURS"


def expire_active_plans_after_interruption(
    session: Session,
    plans: PlanRepository,
    *,
    now: datetime,
    id_factory: Callable[[], str],
) -> tuple[str, ...]:
    """Expire all supported active plans or roll the entire attempt back."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    observed_at = _canonical_shanghai(now.astimezone(SHANGHAI))
    with session.begin_nested():
        locked = session.execute(
            update(RuntimeLiveness)
            .where(RuntimeLiveness.id == 1)
            .values(revision=RuntimeLiveness.revision)
            .execution_options(synchronize_session=False)
        )
        if locked.rowcount != 1:
            raise RuntimeLivenessError("runtime liveness is missing")
        try:
            liveness = liveness_snapshot(session.get(RuntimeLiveness, 1))
        except ValueError, TypeError:
            raise RuntimeLivenessError("invalid runtime liveness") from None
        if liveness is None:
            raise RuntimeLivenessError("runtime liveness is missing")
        decision = classify_interruption(liveness.last_alive_at, observed_at)
        if decision is InterruptionDecision.UNKNOWN:
            raise RuntimeLivenessError("runtime interruption cannot be established")
        if decision is InterruptionDecision.ELIGIBLE:
            return ()

        symbols = tuple(
            session.scalars(
                select(ActivePlan.symbol).order_by(ActivePlan.symbol).limit(_MAX_ACTIVE_PLANS + 1)
            ).all()
        )
        if len(symbols) > _MAX_ACTIVE_PLANS:
            raise RepositoryError("active plan count exceeds the supported runtime limit")
        suppressed = session.execute(
            update(AlertDeliveryEligibility)
            .where(AlertDeliveryEligibility.status != "SUPPRESS")
            .values(
                status="SUPPRESS",
                reason="ACTIVE_IDENTITY_INVALID",
                revision=AlertDeliveryEligibility.revision + 1,
                updated_at=observed_at.isoformat(),
            )
            .execution_options(synchronize_session=False)
        ).rowcount
        if symbols or suppressed:
            session.add(
                AuditLog(
                    id=id_factory(),
                    action="RUNTIME_INTERRUPTION_EXPIRED",
                    entity_type="RUNTIME",
                    entity_id="local",
                    before_hash=None,
                    after_hash=None,
                    details_json=json.dumps(
                        {
                            "cause": _EXPIRY_CAUSE,
                            "lastAliveAt": liveness.last_alive_at.isoformat(),
                            "observedAt": observed_at.isoformat(),
                            "suppressedReceipts": suppressed,
                            "symbols": symbols,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    created_at=observed_at.isoformat(),
                )
            )
        for symbol in symbols:
            active = plans.get_active(symbol)
            if active is None:
                raise RepositoryError("active plan disappeared during expiry")
            pending = session.scalar(
                select(PendingOfficialClose).where(PendingOfficialClose.symbol == symbol)
            )
            if pending is not None:
                details = {
                    "cause": _EXPIRY_CAUSE,
                    "formulaVersion": pending.formula_version,
                    "planHash": pending.plan_hash,
                    "symbol": symbol,
                    "tradeDate": pending.trade_date.isoformat(),
                }
                session.add(
                    AuditLog(
                        id=id_factory(),
                        action="OFFICIAL_CLOSE_EXPIRED",
                        entity_type="PENDING_OFFICIAL_CLOSE",
                        entity_id=symbol,
                        before_hash=sha256(pending.pending_json.encode("utf-8")).hexdigest(),
                        after_hash=None,
                        details_json=json.dumps(details, sort_keys=True, separators=(",", ":")),
                        created_at=observed_at.isoformat(),
                    )
                )
                session.delete(pending)
                session.flush()
            plans.deactivate(
                symbol,
                expected_revision=active.revision,
                cause=_EXPIRY_CAUSE,
            )
        return symbols
