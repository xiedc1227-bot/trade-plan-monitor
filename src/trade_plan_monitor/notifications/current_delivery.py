"""Fresh, transaction-scoped send admission for recovered alerts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, time, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_plan_monitor.decision.models import IntradayEvaluationIdentity
from trade_plan_monitor.domain.plan_codec import load_plan_json
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import (
    ExplicitTradePlan,
    TradePlan,
    activation_is_eligible_on,
)
from trade_plan_monitor.market_data.sessions import expected_minute_ends
from trade_plan_monitor.notifications.channels import NotificationEvent
from trade_plan_monitor.notifications.legacy_current_delivery import (
    _active_legacy,
    read_legacy_delivery_facts,
)
from trade_plan_monitor.notifications.models import (
    build_alert_payload,
    build_explicit_alert_payload,
)
from trade_plan_monitor.notifications.recovery_eligibility import (
    ActiveExplicitPlan,
    RecoveryBarrierEvidence,
    RecoveryDeliveryStatus,
)
from trade_plan_monitor.notifications.recovery_provenance import (
    LegacyAlertOriginReader,
    ProvenLegacyAlertOrigin,
)
from trade_plan_monitor.runtime.clock import SHANGHAI, _canonical_shanghai
from trade_plan_monitor.runtime.historical_close_evidence import LegacyHistoricalCloseReader
from trade_plan_monitor.state.activation_history import read_activation_history
from trade_plan_monitor.state.explicit_rules import ExplicitDecisionRepository
from trade_plan_monitor.state.models import (
    ActivePlan,
    ManualEventRisk,
    PendingOfficialClose,
    PlanActivationState,
    PlanVersion,
    PositionInventoryConfirmation,
    PositionInventoryState,
    RiskState,
    TradingCalendar,
)
from trade_plan_monitor.state.position_inventory_history import (
    PositionInventoryHistoryReader,
    ProvenInventoryHistory,
)
from trade_plan_monitor.state.projections import ProjectionError, ProjectionRepository


class CurrentDeliveryAdmission:
    """Read committed authority on each channel attempt, including after its claim.

    A receipt records the last classification, never a reusable send permit. The
    dispatcher calls this again just before I/O. No transaction spans that I/O.
    """

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        runtime_generation: Callable[[], UUID | None],
    ) -> None:
        if not callable(session_factory) or not callable(runtime_generation):
            raise TypeError("delivery admission requires callable state and generation readers")
        self._sessions = session_factory
        self._generation = runtime_generation

    def __call__(self, event: NotificationEvent, now: datetime) -> bool:
        observed = _canonical_shanghai(now)
        generation = self._generation()
        if type(generation) is not UUID:
            return False
        with self._sessions.begin() as session:
            from trade_plan_monitor.notifications.daily_models import (
                DailyAlertEvent,
                ObsoleteDailyAlertEvent,
            )

            if type(event) is ObsoleteDailyAlertEvent:
                return False
            if type(event) is DailyAlertEvent:
                from trade_plan_monitor.runtime.daily_service import daily_delivery_allowed

                return daily_delivery_allowed(session, event, observed)
            # Historical event codecs remain readable, but only the current
            # condition-plan family may produce a live channel send.
            return False

    def _legacy_actionable(self, session, repository, receipt, event, observed) -> bool:
        if receipt.expires_at is None:
            return False
        if observed >= receipt.expires_at:
            repository.expire_actionable(event.event_id, expected_revision=receipt.revision)
            return False
        if event.created_at > observed or receipt.source_cutoff > observed:
            return False
        try:
            history = read_activation_history(session, event.symbol)
        except (ValueError, TypeError, RecursionError):
            return False
        origin = next(
            (boundary for boundary in reversed(history) if boundary.sequence < event.sequence),
            None,
        )
        active = _active_legacy(session, event.symbol, observed)
        if origin is None or active is None:
            return False
        plan = active.plan
        if (
            origin.revision != active.activation_revision
            or origin.plan_version_id != active.plan_version_id
            or plan.plan_id != event.plan_id or plan.version != event.plan_version
            or plan_sha256(plan) != event.plan_hash
        ):
            repository.suppress_invalidated_identity(
                event.event_id, plan_id=event.plan_id,
                plan_version=event.plan_version, plan_hash=event.plan_hash,
                symbol=event.symbol,
            )
            return False
        if not activation_is_eligible_on(plan.activation, observed.date()):
            return False
        target = _current_bucket(session, plan, observed)
        if target is None or session.scalar(select(PendingOfficialClose).where(
            PendingOfficialClose.symbol == event.symbol,
        )) is not None:
            return False
        try:
            if LegacyHistoricalCloseReader.missing_targets_in_session(
                session, event.symbol, observed,
            ) != ():
                return False
            head = ProjectionRepository(session).get_decision_head(event.symbol)
            if head is None or head.activation_revision != active.activation_revision:
                return False
            result = head.result
            if type(result.evaluation_identity) is not IntradayEvaluationIdentity or (
                result.evaluation_identity.bucket_end != target
                or result.snapshot.evaluated_at > observed
            ):
                return False
            source_inventory = PositionInventoryHistoryReader.read_in_session(
                session, event.symbol, cutoff=event.evaluated_at, observed_at=observed,
            )
            if type(source_inventory) is not ProvenInventoryHistory or (
                source_inventory.inventory_revision != source_inventory.current_revision
            ):
                return False
            risk = session.get(RiskState, event.symbol)
            if risk is not None and (
                risk.plan_hash != event.plan_hash
                or risk.status != result.snapshot.risk.status.value
                or risk.revision != result.snapshot.risk.revision
            ):
                return False
            rebuilt = build_alert_payload(event_id=event.event_id, plan=plan, result=result)
        except (ValueError, TypeError, RecursionError, ProjectionError):
            return False
        return rebuilt.model_dump(mode="python") == event.model_dump(
            mode="python", exclude={"sequence", "message_text", "created_at", "acknowledged_at"},
        )

    def _explicit_actionable(self, session, repository, receipt, event, observed) -> bool:
        if receipt.expires_at is None:
            return False
        if observed >= receipt.expires_at:
            repository.expire_actionable(event.event_id, expected_revision=receipt.revision)
            return False
        if event.created_at > observed or event.target_bucket_end > observed:
            return False
        active = _active_explicit(session, event.symbol, observed)
        if active is None:
            return False
        plan = active.plan
        if (
            active.activation_revision != event.activation_revision
            or plan.plan_id != event.plan_id or plan.version != event.plan_version
            or plan_sha256(plan) != event.plan_hash
        ):
            repository.suppress_invalidated_identity(
                event.event_id, plan_id=event.plan_id,
                plan_version=event.plan_version, plan_hash=event.plan_hash,
                symbol=event.symbol,
            )
            return False
        if not activation_is_eligible_on(plan.activation, observed.date()) or (
            _current_bucket(session, plan, observed) != event.target_bucket_end
        ):
            return False
        latest = ExplicitDecisionRepository(session).get(
            plan_hash=event.plan_hash, symbol=event.symbol,
            target_bucket_end=event.target_bucket_end,
            activation_revision=event.activation_revision,
        )
        if latest is None or latest.evaluated_at > observed or (
            not _inventory_revision_matches(session, latest)
        ) or (
            not _manual_risk_revision_matches(session, latest)
        ):
            return False
        payload = event.model_dump(
            mode="python", exclude={"sequence", "message_text", "created_at", "acknowledged_at"},
        )
        return any(
            build_explicit_alert_payload(
                event_id=event.event_id, plan=plan, result=latest, signal=signal,
            ).model_dump(mode="python") == payload
            for signal in latest.signal_intents
        )

    def _legacy_risk(
        self, session, repository, revision, event, observed, generation,
    ) -> bool:
        try:
            facts = read_legacy_delivery_facts(
                session, event_id=event.event_id, now=observed,
                runtime_generation=generation,
            )
        except (ValueError, TypeError, RecursionError, ProjectionError):
            return False
        if facts is None:
            active_row = session.get(ActivePlan, event.symbol)
            active = None if active_row is None else _active_legacy(session, event.symbol, observed)
            if active_row is None or active is not None:
                origin = LegacyAlertOriginReader(lambda: session).read_in_session(
                    session, event.event_id,
                )
                if type(origin) is ProvenLegacyAlertOrigin and (
                    active_row is None or (
                        active.plan_version_id != origin.plan_version_id
                        or active.activation_revision != origin.activation_revision
                    )
                ):
                    repository.suppress_invalidated_identity(
                        event.event_id, plan_id=event.plan_id,
                        plan_version=event.plan_version, plan_hash=event.plan_hash,
                        symbol=event.symbol,
                    )
            return False
        decision = repository.classify_legacy_risk(
            event.event_id, expected_revision=revision,
            origin=facts.origin, active=facts.active, current=facts.current,
            barrier=facts.barrier, target_bucket_end=facts.target_bucket_end,
            runtime_generation=generation, now=observed,
        )
        return decision.status is RecoveryDeliveryStatus.ELIGIBLE

    def _explicit_risk(
        self, session, repository, revision, event, observed, generation,
    ) -> bool:
        active = _active_explicit(session, event.symbol, observed)
        if active is None and session.get(ActivePlan, event.symbol) is not None:
            return False
        target = _current_bucket(session, active.plan if active is not None else None, observed)
        if target is None:
            # An invalidated identity is still classifiable without current calendar data.
            if active is not None:
                return False
            target = event.target_bucket_end
        latest = None
        barrier = None
        if active is not None:
            latest = ExplicitDecisionRepository(session).get(
                plan_hash=plan_sha256(active.plan), symbol=event.symbol,
                target_bucket_end=target, activation_revision=active.activation_revision,
            )
            if latest is not None and not _inventory_revision_matches(session, latest):
                latest = None
            if latest is not None and not _manual_risk_revision_matches(session, latest):
                latest = None
            barrier = RecoveryBarrierEvidence(
                symbol=event.symbol, plan_hash=plan_sha256(active.plan),
                activation_revision=active.activation_revision,
                runtime_generation=generation, target_bucket_end=target,
                reconciled_through=target if latest is not None else None,
                pending_obligations=0 if latest is not None else 1,
                observed_at=observed,
            )
        decision = repository.classify_explicit_risk(
            event.event_id, expected_revision=revision, active=active, latest=latest,
            barrier=barrier, target_bucket_end=target,
            runtime_generation=generation,
        )
        return decision.status is RecoveryDeliveryStatus.ELIGIBLE


def _active_explicit(session: Session, symbol: str, now: datetime) -> ActiveExplicitPlan | None:
    active = session.get(ActivePlan, symbol)
    if active is None:
        return None
    version = session.get(PlanVersion, active.plan_version_id)
    state = session.get(PlanActivationState, symbol)
    if (
        version is None or state is None or state.plan_version_id != active.plan_version_id
        or state.revision != active.revision or version.status != "ACTIVE"
        or version.symbol != symbol
    ):
        return None
    plan = load_plan_json(version.payload_json)
    if type(plan) is not ExplicitTradePlan or plan_sha256(plan) != version.plan_hash:
        return None
    return ActiveExplicitPlan(
        plan=plan, activation_revision=active.revision,
        activated_at=datetime.fromisoformat(active.activated_at), observed_at=now,
    )


def _current_bucket(
    session: Session, plan: ExplicitTradePlan | TradePlan | None, now: datetime,
) -> datetime | None:
    if plan is None:
        return None
    start = now.date() - timedelta(days=7)
    rows = session.scalars(select(TradingCalendar).where(
        TradingCalendar.exchange == plan.market,
        TradingCalendar.cal_date >= start,
        TradingCalendar.cal_date <= now.date(),
    ).order_by(TradingCalendar.cal_date)).all()
    by_date = {row.cal_date: row for row in rows}
    today = by_date.get(now.date())
    if today is None:
        return None
    if today.is_open:
        minutes = expected_minute_ends(now.date(), is_open=True)
        completed = [minute for minute in minutes if minute <= now and minute.minute % 5 == 0]
        if completed:
            return completed[-1]
    day = now.date() - timedelta(days=1)
    while day >= start:
        row = by_date.get(day)
        if row is None:
            return None
        if row.is_open:
            return datetime.combine(day, time(15), SHANGHAI)
        day -= timedelta(days=1)
    return None


def _inventory_revision_matches(session: Session, result) -> bool:
    state = session.get(PositionInventoryState, result.symbol)
    confirmation = session.get(PositionInventoryConfirmation, result.symbol)
    if state is None or confirmation is None or not confirmation.complete_registration:
        return False
    if confirmation.inventory_revision != state.revision:
        return False
    if result.inventory_revision is not None and result.inventory_revision != state.revision:
        return False
    return True


def _manual_risk_revision_matches(session: Session, result) -> bool:
    if result.manual_event_risk_revision is None:
        return True
    row = session.get(ManualEventRisk, result.symbol)
    return (
        row is not None and row.plan_hash == result.plan_hash
        and row.revision == result.manual_event_risk_revision
    )
