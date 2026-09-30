"""Read-only D5 presentation from immutable sources and fresh committed facts."""

from sqlalchemy import func, select

from trade_plan_monitor.domain.plan_models import activation_is_eligible_on
from trade_plan_monitor.notifications.current_delivery import (
    _active_explicit,
    _current_bucket,
    _inventory_revision_matches,
    _manual_risk_revision_matches,
)
from trade_plan_monitor.notifications.delivery_eligibility import (
    DeliveryClass,
    DeliveryEligibilityRepository,
)
from trade_plan_monitor.notifications.identity import alert_dedup_key
from trade_plan_monitor.notifications.models import ExplicitAlertEvent, build_explicit_alert_payload
from trade_plan_monitor.notifications.outbox import _event_from_row
from trade_plan_monitor.notifications.recovery_eligibility import (
    RecoveryDeliveryStatus,
    classify_explicit_risk_delivery,
)
from trade_plan_monitor.state.explicit_rules import ExplicitDecisionRepository
from trade_plan_monitor.state.models import AlertEvent as AlertRow
from trade_plan_monitor.state.projections import ProjectionError


def _latest_source_event(session, *, symbol, plan_hash, predicates):
    """Read one applicable source, independently of total retained alert history."""
    row = session.scalar(
        select(AlertRow)
        .where(
            func.json_extract(AlertRow.payload_json, "$.symbol") == symbol,
            func.json_extract(AlertRow.payload_json, "$.plan_hash") == plan_hash,
            *predicates,
        )
        .order_by(AlertRow.sequence.desc())
        .limit(1)
    )
    return None if row is None else _event_from_row(row)


def _explicit_source(session, plan, result, rule, events, now):
    for event in events:
        if type(event) is not ExplicitAlertEvent or (
            event.activation_revision != result.activation_revision
            or event.rule_id != rule.rule_id
            or event.signal_type != rule.action.type
        ):
            continue
        original = ExplicitDecisionRepository(session).get(
            plan_hash=event.plan_hash,
            symbol=event.symbol,
            target_bucket_end=event.target_bucket_end,
            activation_revision=event.activation_revision,
        )
        if original is None:
            raise ProjectionError("Alert original result is missing")
        payload = event.model_dump(
            mode="python",
            exclude={
                "sequence",
                "message_text",
                "created_at",
                "acknowledged_at",
            },
        )
        if not any(
            build_explicit_alert_payload(
                event_id=event.event_id,
                plan=plan,
                result=original,
                signal=intent,
            ).model_dump(mode="python")
            == payload
            for intent in original.signal_intents
        ):
            raise ProjectionError("Alert original intent does not match persisted source")
        if original.evaluated_at > now or event.created_at > now:
            raise ProjectionError("Alert original result is in the future")
        return event, dict(
            event_id=event.event_id,
            result_hash=original.result_hash,
            evaluated_at=original.evaluated_at,
            data_cutoff=original.target_bucket_end,
        )
    return None, None


def _validate_receipt_observation(receipt, now):
    if receipt is not None and (
        receipt.updated_at > now
        or (receipt.source_cutoff is not None and receipt.source_cutoff > now)
        or (receipt.barrier is not None and receipt.barrier.observed_at > now)
    ):
        raise ProjectionError("Delivery evidence is newer than observation")


def explicit_rule_eligibility(*, session, plan, result, generation, barrier, now, current):
    """Never initialize/expire/classify a receipt; all writes belong to dispatch."""
    active = _active_explicit(session, plan.symbol, now)
    fresh = _inventory_revision_matches(session, result) and _manual_risk_revision_matches(
        session, result
    )
    receipts = DeliveryEligibilityRepository(session, clock=lambda: now)
    entries = []
    for rule in result.rule_results:
        event = _latest_source_event(
            session, symbol=plan.symbol, plan_hash=result.plan_hash,
            predicates=(
                func.json_extract(AlertRow.payload_json, "$.payload_schema_version")
                == "explicit-rule-alert-v1",
                func.json_extract(AlertRow.payload_json, "$.activation_revision")
                == result.activation_revision,
                func.json_extract(AlertRow.payload_json, "$.rule_id") == rule.rule_id,
                func.json_extract(AlertRow.payload_json, "$.signal_type") == rule.action.type,
            ),
        )
        events = () if event is None else (event,)
        event, source = _explicit_source(session, plan, result, rule, events, now)
        receipt = None if event is None else receipts.get(event.event_id)
        _validate_receipt_observation(receipt, now)
        reason = "NO_CURRENT_SIGNAL"
        deadline = None
        if not current:
            reason = "CACHED_RESULT"
        elif event is not None:
            if not fresh or receipt is None:
                reason = "CURRENT_STATE_UNVERIFIED"
            elif barrier is None:
                reason = "RECOVERY_HOLD"
            elif rule.action.type == "RISK_ALERT":
                if receipt.delivery_class is not DeliveryClass.STATE_RISK:
                    raise ProjectionError("Risk source has incompatible delivery class")
                decision = classify_explicit_risk_delivery(
                    event,
                    active=active,
                    latest=result,
                    barrier=barrier,
                    target_bucket_end=result.target_bucket_end,
                    runtime_generation=generation,
                    now=now,
                )
                reason = (
                    None
                    if decision.status is RecoveryDeliveryStatus.ELIGIBLE
                    else "RISK_NO_LONGER_VALID"
                    if decision.status is RecoveryDeliveryStatus.SUPPRESS
                    else "RECOVERY_HOLD"
                )
            elif receipt.delivery_class is not DeliveryClass.INTRADAY_ACTIONABLE:
                raise ProjectionError("Intraday source has incompatible delivery class")
            elif receipt.expires_at is None or receipt.source_cutoff != event.target_bucket_end:
                reason = "CURRENT_STATE_UNVERIFIED"
            elif now >= receipt.expires_at:
                reason = "INTRADAY_EXPIRED"
            elif (
                active is None
                or active.activation_revision != result.activation_revision
                or not activation_is_eligible_on(plan.activation, now.date())
                or _current_bucket(session, plan, now) != event.target_bucket_end
                or source["result_hash"] != result.result_hash
                or barrier.symbol != result.symbol
                or barrier.plan_hash != result.plan_hash
                or barrier.activation_revision != result.activation_revision
                or barrier.runtime_generation != generation
                or barrier.target_bucket_end != result.target_bucket_end
                or barrier.reconciled_through != result.target_bucket_end
                or barrier.pending_obligations != 0
                or barrier.observed_at > now
                or barrier.observed_at < result.evaluated_at
            ):
                reason = "CURRENT_STATE_UNVERIFIED"
            else:
                reason, deadline = None, receipt.expires_at
            if receipt is not None and receipt.status is RecoveryDeliveryStatus.SUPPRESS:
                reason = (
                    "RISK_NO_LONGER_VALID"
                    if receipt.delivery_class is DeliveryClass.STATE_RISK
                    else "INTRADAY_EXPIRED"
                    if receipt.reason == "SOURCE_EXPIRED"
                    else "CURRENT_STATE_UNVERIFIED"
                )
                deadline = None
        entries.append(
            dict(
                rule_id=rule.rule_id,
                action=rule.action.type,
                current_actionable=reason is None,
                reason_code=reason,
                actionable_until=deadline if reason is None else None,
                source_alert=source,
            )
        )
    return tuple(entries)


def legacy_eligibility(*, session, plan, result, generation, barrier, now, current):
    """Project an existing legacy reminder without turning state risk into expiry."""
    from trade_plan_monitor.decision.models import IntradayEvaluationIdentity
    from trade_plan_monitor.notifications.current_delivery import _active_legacy
    from trade_plan_monitor.notifications.legacy_current_delivery import read_legacy_delivery_facts
    from trade_plan_monitor.notifications.legacy_recovery_eligibility import (
        classify_legacy_risk_delivery,
    )
    from trade_plan_monitor.notifications.models import build_alert_payload
    from trade_plan_monitor.runtime.historical_close_evidence import LegacyHistoricalCloseReader
    from trade_plan_monitor.state.models import PendingOfficialClose, RiskState
    from trade_plan_monitor.state.position_inventory_history import (
        PositionInventoryHistoryReader,
        ProvenInventoryHistory,
    )

    if not current or barrier is None:
        return False, None
    active = _active_legacy(session, plan.symbol, now)
    if active is None:
        return False, None
    # Intraday reminders have an exact current intent identity. State-risk
    # reminders can originate before a later WAIT result, so inspect the newest
    # source of each risk stage and retain the existing origin/classifier guards.
    events = {}
    if result.signal_intent is not None:
        row = session.scalar(select(AlertRow).where(
            AlertRow.dedup_key == alert_dedup_key(result.signal_intent),
        ))
        if row is not None:
            event = _event_from_row(row)
            events[event.event_id] = event
    for signal in ("RISK_BREACH", "RISK_EXIT_READY", "RISK_EXIT_PENDING_SETTLEMENT"):
        event = _latest_source_event(
            session, symbol=plan.symbol, plan_hash=result.snapshot.plan_hash,
            predicates=(
                func.json_extract(AlertRow.payload_json, "$.signal_type") == signal,
                func.julianday(func.json_extract(AlertRow.payload_json, "$.evaluated_at"))
                >= func.julianday(active.activated_at.isoformat()),
            ),
        )
        if event is not None:
            events[event.event_id] = event
    receipts = DeliveryEligibilityRepository(session, clock=lambda: now)
    for event in sorted(events.values(), key=lambda value: value.sequence, reverse=True):
        if type(event) is ExplicitAlertEvent:
            continue
        receipt = receipts.get(event.event_id)
        _validate_receipt_observation(receipt, now)
        if receipt is None or receipt.status is RecoveryDeliveryStatus.SUPPRESS:
            continue
        if receipt.delivery_class is DeliveryClass.STATE_RISK:
            facts = read_legacy_delivery_facts(
                session, event_id=event.event_id, now=now, runtime_generation=generation
            )
            if facts is None or facts.target_bucket_end != barrier.target_bucket_end:
                continue
            classified = classify_legacy_risk_delivery(
                facts.origin,
                active=facts.active,
                current=facts.current,
                barrier=barrier,
                target_bucket_end=facts.target_bucket_end,
                runtime_generation=generation,
                now=now,
            )
            if classified.status is RecoveryDeliveryStatus.ELIGIBLE:
                return True, None
            continue
        if (
            receipt.expires_at is None
            or now >= receipt.expires_at
            or event.created_at > now
            or receipt.source_cutoff > now
        ):
            continue
        active = _active_legacy(session, plan.symbol, now)
        identity = result.evaluation_identity
        if active is None or (
            active.activation_revision != barrier.activation_revision
            or active.activated_at > event.evaluated_at
            or type(identity) is not IntradayEvaluationIdentity
            or _current_bucket(session, plan, now) != identity.bucket_end
        ):
            continue
        if (
            session.scalar(
                select(PendingOfficialClose).where(PendingOfficialClose.symbol == plan.symbol)
            )
            is not None
        ):
            continue
        if LegacyHistoricalCloseReader.missing_targets_in_session(session, plan.symbol, now) != ():
            continue
        inventory = PositionInventoryHistoryReader.read_in_session(
            session, plan.symbol, cutoff=event.evaluated_at, observed_at=now
        )
        if type(inventory) is not ProvenInventoryHistory or (
            inventory.inventory_revision != inventory.current_revision
        ):
            continue
        risk = session.get(RiskState, plan.symbol)
        if risk is not None and (
            risk.plan_hash != event.plan_hash
            or risk.status != result.snapshot.risk.status.value
            or risk.revision != result.snapshot.risk.revision
        ):
            continue
        rebuilt = build_alert_payload(event_id=event.event_id, plan=plan, result=result)
        if rebuilt.model_dump(mode="python") == event.model_dump(
            mode="python",
            exclude={
                "sequence",
                "message_text",
                "created_at",
                "acknowledged_at",
            },
        ):
            return True, receipt.expires_at
    return False, None
