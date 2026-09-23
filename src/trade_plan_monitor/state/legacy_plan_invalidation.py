"""Preview and atomically invalidate legacy plans with no heartbeat evidence."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from string import hexdigits

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from trade_plan_monitor.runtime.clock import _canonical_shanghai
from trade_plan_monitor.state.models import (
    ActivePlan,
    AlertDeliveryEligibility,
    AuditLog,
    PendingOfficialClose,
    PlanVersion,
    RuntimeLiveness,
)
from trade_plan_monitor.state.repositories import PlanRepository, RepositoryError

_MAX_ACTIVE_PLANS = 10
_CAUSE = "MANUAL_LEGACY_INVALIDATION"
_AUDIT_ACTION = "LEGACY_PLANS_MANUALLY_INVALIDATED"


class LegacyPlanInvalidationConflict(RuntimeError):
    """The preview no longer matches, or the database is not eligible."""


class LegacyMaintenanceUnavailable(LegacyPlanInvalidationConflict):
    """This runtime generation is not in the dedicated blocked maintenance state."""


@dataclass(frozen=True, slots=True)
class LegacyPlanItem:
    symbol: str
    plan_version_id: str
    revision: int


@dataclass(frozen=True, slots=True)
class LegacyPlanPreview:
    plans: tuple[LegacyPlanItem, ...]
    fingerprint: str


def preview_legacy_invalidation(session: Session) -> LegacyPlanPreview:
    """Return only bounded active identities; never infer a missing last-alive time."""

    if session.get(RuntimeLiveness, 1) is not None:
        raise LegacyPlanInvalidationConflict("runtime liveness is present")
    rows = session.execute(
        select(
            ActivePlan.symbol, ActivePlan.plan_version_id, ActivePlan.revision, PlanVersion.status
        )
        .outerjoin(PlanVersion, PlanVersion.id == ActivePlan.plan_version_id)
        .order_by(ActivePlan.symbol)
        .limit(_MAX_ACTIVE_PLANS + 1)
    ).all()
    if len(rows) > _MAX_ACTIVE_PLANS:
        raise RepositoryError("active plan count exceeds the supported runtime limit")
    if any(row.status != "ACTIVE" for row in rows):
        raise LegacyPlanInvalidationConflict("active plan identity is inconsistent")
    plans = tuple(LegacyPlanItem(row.symbol, row.plan_version_id, row.revision) for row in rows)
    raw = json.dumps(
        [(item.symbol, item.plan_version_id, item.revision) for item in plans],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return LegacyPlanPreview(plans=plans, fingerprint=sha256(raw.encode("utf-8")).hexdigest())


def invalidate_legacy_plans(
    session: Session,
    plans: PlanRepository,
    *,
    expected_fingerprint: str,
    now: datetime,
    id_factory: Callable[[], str],
) -> tuple[str, ...]:
    """Commit the reviewed set only; caller must separately ensure runtime is stopped."""

    if len(expected_fingerprint) != 64 or any(ch not in hexdigits for ch in expected_fingerprint):
        raise ValueError("invalid preview fingerprint")
    observed_at = _canonical_shanghai(now)
    with session.begin_nested():
        # Serialize the read/decision with a concurrent local SQLite writer.
        session.execute(
            update(ActivePlan)
            .values(revision=ActivePlan.revision)
            .execution_options(synchronize_session=False)
        )
        preview = preview_legacy_invalidation(session)
        if not preview.plans:
            previous = session.scalar(
                select(AuditLog).where(
                    AuditLog.action == _AUDIT_ACTION,
                    AuditLog.before_hash == expected_fingerprint,
                )
            )
            if previous is None:
                raise LegacyPlanInvalidationConflict("there are no legacy plans to invalidate")
            return tuple(json.loads(previous.details_json)["symbols"])
        if preview.fingerprint != expected_fingerprint:
            raise LegacyPlanInvalidationConflict("active plans changed after preview")

        symbols = tuple(item.symbol for item in preview.plans)
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
        for item in preview.plans:
            pending = session.scalar(
                select(PendingOfficialClose).where(PendingOfficialClose.symbol == item.symbol)
            )
            if pending is not None:
                session.add(
                    AuditLog(
                        id=id_factory(),
                        action="OFFICIAL_CLOSE_MANUALLY_INVALIDATED",
                        entity_type="PENDING_OFFICIAL_CLOSE",
                        entity_id=item.symbol,
                        before_hash=sha256(pending.pending_json.encode("utf-8")).hexdigest(),
                        after_hash=None,
                        details_json=json.dumps(
                            {
                                "cause": _CAUSE,
                                "formulaVersion": pending.formula_version,
                                "planHash": pending.plan_hash,
                                "symbol": item.symbol,
                                "tradeDate": pending.trade_date.isoformat(),
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        created_at=observed_at.isoformat(),
                    )
                )
                session.delete(pending)
                session.flush()
            plans.deactivate(item.symbol, expected_revision=item.revision, cause=_CAUSE)
        session.add(
            AuditLog(
                id=id_factory(),
                action=_AUDIT_ACTION,
                entity_type="RUNTIME",
                entity_id="local",
                before_hash=expected_fingerprint,
                after_hash=None,
                details_json=json.dumps(
                    {
                        "cause": _CAUSE,
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
        return symbols
