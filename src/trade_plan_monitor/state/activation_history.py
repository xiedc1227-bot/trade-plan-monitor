"""Bounded read-only proof of the persisted activation event/audit chain."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trade_plan_monitor.state.events import (
    MAX_EVENT_REPLAY_LIMIT,
    MAX_PUBLIC_SEQUENCE,
    MonitorEvent,
    MonitorEventType,
    monitor_event_id,
)
from trade_plan_monitor.state.events import _event_from_row as _monitor_from_row
from trade_plan_monitor.state.models import (
    ActivePlan,
    AuditLog,
    MonitorSequence,
    PlanActivationState,
)
from trade_plan_monitor.state.models import MonitorEvent as MonitorRow

_BOUNDARIES = (MonitorEventType.PLAN_ACTIVATED, MonitorEventType.PLAN_DEACTIVATED)
_ACTIONS = ("PLAN_ACTIVATED", "PLAN_DEACTIVATED")


class MissingActivationEvidence(ValueError):
    pass


class ActivationHistoryLimit(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ActivationBoundary:
    revision: int
    plan_version_id: str | None
    occurred_at: datetime
    sequence: int


def _require(agreement: bool) -> None:
    if not agreement:
        raise ValueError("Historical evidence does not agree")


def monitor_query():
    # Truncate before loading/parsing, not after fetching an unbounded historical blob.
    return select(
        MonitorRow.id,
        MonitorRow.sequence,
        MonitorRow.event_type,
        MonitorRow.schema_version,
        MonitorRow.aggregate_id,
        MonitorRow.occurred_at,
        func.substr(MonitorRow.payload_json, 1, 4097).label("payload_json"),
    )


def monitor_from_row(row) -> MonitorEvent:
    if row is None:
        raise MissingActivationEvidence()
    _require(len(row.payload_json) <= 4096)
    return _monitor_from_row(row)


def read_monitor_highwater(session: Session) -> int:
    states = session.scalars(select(MonitorSequence).limit(2)).all()
    if not states:
        raise MissingActivationEvidence()
    _require(len(states) == 1 and states[0].singleton_id == 1)
    highwater = states[0].last_sequence
    _require(type(highwater) is int and 0 <= highwater <= MAX_PUBLIC_SEQUENCE)
    # The owned SQLite snapshot keeps this global maximum coherent with every
    # subsequently read publication, alert, and activation boundary sequence.
    retained_maximum = session.scalar(select(func.max(MonitorRow.sequence)))
    _require(
        retained_maximum is None
        or (type(retained_maximum) is int and 0 < retained_maximum <= highwater)
    )
    return highwater


def read_activation_history(session: Session, symbol: str) -> tuple[ActivationBoundary, ...]:
    """Validate the bounded event/audit chain and current persisted pointers.

    The caller owns a fresh no_autoflush read snapshot and must first call
    read_monitor_highwater in that same snapshot. This helper owns no transaction.
    """
    rows = session.execute(
        monitor_query()
        .where(
            MonitorRow.aggregate_id == symbol,
            MonitorRow.event_type.in_([item.value for item in _BOUNDARIES]),
        )
        .order_by(MonitorRow.sequence)
        .limit(MAX_EVENT_REPLAY_LIMIT + 1)
    ).all()
    audits = session.execute(
        select(
            AuditLog.id,
            AuditLog.action,
            AuditLog.before_hash,
            AuditLog.after_hash,
            AuditLog.created_at,
            func.substr(AuditLog.details_json, 1, 4097).label("details_json"),
        )
        .where(
            AuditLog.entity_type == "ACTIVE_PLAN",
            AuditLog.entity_id == symbol,
            AuditLog.action.in_(_ACTIONS),
        )
        .limit(MAX_EVENT_REPLAY_LIMIT + 1)
    ).all()
    if max(len(rows), len(audits)) > MAX_EVENT_REPLAY_LIMIT:
        raise ActivationHistoryLimit()
    if not rows or not audits:
        raise MissingActivationEvidence()
    _require(len(rows) == len(audits))
    by_revision = {}
    for audit in audits:
        _require(len(audit.details_json) <= 4096)
        details = json.loads(audit.details_json)
        _require(isinstance(details, dict) and (
            set(details) == {"symbol", "revision", "planVersionId"}
            or audit.action == "PLAN_DEACTIVATED"
            and set(details) == {"symbol", "revision", "planVersionId", "cause"}
            and details["cause"] in {"OUTAGE_OVER_120_HOURS", "MANUAL_LEGACY_INVALIDATION"}))
        revision = details["revision"]
        _require(
            type(revision) is int
            and revision > 0
            and revision not in by_revision
            and details["symbol"] == symbol
            and isinstance(details["planVersionId"], str)
        )
        by_revision[revision] = (audit, details["planVersionId"])
    previous_hash, active_version = None, None
    history = []
    for revision, row in enumerate(rows, start=1):
        boundary = monitor_from_row(row)
        _require(boundary.payload.revision == revision and revision in by_revision)
        audit, plan_version_id = by_revision[revision]
        activating = boundary.event_type is MonitorEventType.PLAN_ACTIVATED
        _require(
            audit.action == (_ACTIONS[0] if activating else _ACTIONS[1])
            and audit.created_at == boundary.occurred_at.isoformat()
            and audit.before_hash == previous_hash
            and boundary.event_id
            == monitor_event_id(boundary.event_type, symbol, str(revision))
        )
        _require(
            boundary.payload.entity_id == (plan_version_id if activating else symbol)
        )
        if not activating:
            _require(active_version == plan_version_id)
        active_version = plan_version_id if activating else None
        snapshot = {
            "planVersionId": active_version,
            "revision": revision,
            "symbol": symbol,
            "activatedAt" if activating else "changedAt": audit.created_at,
        }
        digest = sha256(
            json.dumps(
                snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        _require(audit.after_hash == digest)
        previous_hash = digest
        history.append(ActivationBoundary(
            revision, active_version, boundary.occurred_at, boundary.sequence,
        ))
    tip = session.get(PlanActivationState, symbol)
    active = session.get(ActivePlan, symbol)
    if tip is None:
        raise MissingActivationEvidence()
    _require(
        tip.revision == len(rows)
        and tip.plan_version_id == active_version
        and tip.changed_at == boundary.occurred_at.isoformat()
    )
    if active_version is None:
        _require(active is None)
    else:
        _require(
            active is not None
            and active.plan_version_id == active_version
            and active.revision == tip.revision
            and active.activated_at == tip.changed_at
        )
    return tuple(history)


@dataclass(frozen=True, slots=True)
class BuySuspensionContext:
    """Actual activation predecessor and original guard owner, within one SQL snapshot."""

    activation_revision: int
    predecessor: object | None = None
    owner: object | None = None
    birth_revision: int | None = None
    strategy_effective_from: datetime | None = None


def suspension_plan(details):
    from trade_plan_monitor.domain.daily_plan_validation import load_daily_draft_json
    from trade_plan_monitor.domain.plan_codec import load_plan_json

    return (load_daily_draft_json(details.payload_json).to_executable()
            if details.daily_mapping is not None else load_plan_json(details.payload_json))


def guard_owner_hash(context):
    from trade_plan_monitor.domain.daily_hash import daily_hash

    owner = context.owner
    return daily_hash("buy-suspension-owner-binding-v1", dict(
        id=owner.id, plan_hash=owner.plan_hash, content_hash=owner.content_hash,
        source_hash=owner.source_hash, review_id=owner.review_id,
        review_revision=owner.review_revision, birth_revision=context.birth_revision,
        definition=suspension_plan(owner).buy_suspension.model_dump(mode="json")))


def resolve_buy_suspension_context(repo, symbol, *, work=None):
    """Follow only the bounded actual activation chain; never source independence flags.

    Deactivation preserves the last selected owner. A verified installed replacement
    starts a new context; old dormant/unrelated records are not scanned as global bans.
    The caller owns its transaction and, for mutations, the existing symbol writer.
    """
    from trade_plan_monitor.state.daily_models import DailyRecord
    from trade_plan_monitor.state.daily_repository import DailyRepository
    from trade_plan_monitor.state.daily_state_models import DailyReviewBinding

    if not hasattr(repo, "_session"):
        adapter = getattr(repo, "_buy_suspension_context", None)
        _require(work is not None and callable(adapter))
        context = adapter(work, symbol)
        _require(isinstance(context, BuySuspensionContext) and context.owner is None
                 and context.strategy_effective_from is None)
        return context
    session = repo._session
    with session.no_autoflush:
        _require(not any(isinstance(row, (ActivePlan, PlanActivationState))
            and row.symbol == symbol for row in (*session.new, *session.dirty, *session.deleted)))
        state = session.scalar(select(PlanActivationState).where(
            PlanActivationState.symbol == symbol).execution_options(populate_existing=True))
        active = session.scalar(select(ActivePlan).where(
            ActivePlan.symbol == symbol).execution_options(populate_existing=True))
        if state is None or state.revision == 0:
            _require(active is None)
            _require(session.scalar(monitor_query().where(MonitorRow.aggregate_id == symbol,
                MonitorRow.event_type.in_([item.value for item in _BOUNDARIES])).limit(1)) is None)
            _require(session.scalar(select(DailyRecord.id).where(DailyRecord.symbol == symbol,
                DailyRecord.kind == "BUY_SUSPENSION").limit(1)) is None)
            return BuySuspensionContext(0)
        read_monitor_highwater(session)
        history = read_activation_history(session, symbol)
        context = BuySuspensionContext(0)
        daily = DailyRepository(session, clock=repo._clock, id_factory=None)
        for boundary in history:
            if boundary.plan_version_id is None:
                context = BuySuspensionContext(boundary.revision, context.predecessor,
                    context.owner, context.birth_revision, context.strategy_effective_from)
                continue
            details = repo.get_version_details(boundary.plan_version_id)
            _require(details is not None and details.symbol == symbol)
            plan = suspension_plan(details)
            _require(plan is not None)
            guard = getattr(plan, "buy_suspension", None)
            raw = daily.get("review-" + details.id)
            review = None if raw is None else DailyReviewBinding.model_validate(raw["payload"])
            receipt = None if review is None else review.buy_suspension_replacement
            if guard is not None or receipt is not None:
                _require(review is not None and review.confirmed)
                _require((review.plan_version_id, review.content_hash, review.source_hash,
                    review.evidence_hash, review.review_id, review.review_revision) == (
                    details.id, details.content_hash, details.source_hash,
                    details.review_evidence_hash, details.review_id, details.review_revision))
            repeated = context.predecessor is not None and context.predecessor.id == details.id
            if receipt is not None and not repeated:
                old = context.predecessor
                _require(old is not None and context.owner is not None)
                _require((receipt.predecessor_plan_version_id, receipt.predecessor_plan_hash,
                    receipt.predecessor_content_hash, receipt.predecessor_source_hash,
                    receipt.predecessor_review_id, receipt.predecessor_review_revision,
                    receipt.predecessor_activation_revision,
                    receipt.predecessor_guard_owner_plan_version_id,
                    receipt.predecessor_guard_owner_hash, receipt.new_plan_hash,
                    receipt.new_guard, receipt.predecessor_guard,
                    receipt.predecessor_plan_id, receipt.predecessor_plan_version,
                    receipt.new_plan_id, receipt.new_plan_version, receipt.confirmed_at,
                    ) == (old.id, old.plan_hash, old.content_hash,
                    old.source_hash, old.review_id, old.review_revision,
                    context.activation_revision,
                    context.owner.id, guard_owner_hash(context), details.plan_hash, guard,
                    suspension_plan(context.owner).buy_suspension, old.plan_id, old.version,
                    details.plan_id, details.version, details.review_confirmed_at))
                context = BuySuspensionContext(boundary.revision, details,
                    details if guard is not None else None,
                    boundary.revision if guard is not None else None,
                    receipt.intent.strategy_effective_from)
            elif context.owner is not None:
                _require(guard == suspension_plan(context.owner).buy_suspension)
                context = BuySuspensionContext(boundary.revision, details, context.owner,
                    context.birth_revision, context.strategy_effective_from)
            else:
                context = BuySuspensionContext(boundary.revision, details,
                    details if guard is not None else None,
                    boundary.revision if guard is not None else None,
                    context.strategy_effective_from)
        return context
