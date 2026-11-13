"""Bounded original notification facts, without send-time policy or history scans."""

import json
from dataclasses import dataclass
from datetime import date, datetime
from types import SimpleNamespace

from sqlalchemy import LargeBinary, case, cast, func, select
from sqlalchemy.exc import SQLAlchemyError

from trade_plan_monitor.decision.models import (
    IntradayEvaluationTarget,
    OfficialCloseEvaluationTarget,
)
from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.risk_scope import risk_identity
from trade_plan_monitor.notifications.channels import ChannelErrorCode, DeliveryChannel
from trade_plan_monitor.notifications.daily_models import DailyAlertEvent, daily_alert_key
from trade_plan_monitor.notifications.delivery_eligibility import DeliveryEligibilityRecord
from trade_plan_monitor.notifications.dispatcher import (
    DeliveryAttemptRecord,
    DeliveryAttemptStatus,
    _stored_datetime,
)
from trade_plan_monitor.notifications.outbox import OutboxError, _event_from_row
from trade_plan_monitor.runtime.status_authority import ConditionInputStamp, _fingerprint
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.daily_state_models import DailyRiskState, DailySignalState
from trade_plan_monitor.state.models import AlertDeliveryEligibility, AlertEvent, DeliveryAttempt
from trade_plan_monitor.state.source_action_reads import ActionOwnerReader

MAX_NOTIFICATION_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class NotificationRead:
    """Exact event and independent historical facts; no current eligibility."""

    event: DailyAlertEvent | None = None
    target: object = None
    classification: DeliveryEligibilityRecord | None = None
    attempts: tuple[DeliveryAttemptRecord, ...] = ()


class NotificationReader:
    """At most one indexed row per exact key and three exact latest attempts."""

    def __init__(self, work, *, now):
        self.reads = ActionOwnerReader(work)
        self.session = self.reads.session
        self.now = now
        self.binding = []
        self.bytes_left = MAX_NOTIFICATION_BYTES

    def row(self, model, *, criteria, order=None):
        """Cap SQL text before transfer, including malformed/oversized payloads."""
        self.reads._reject_pending(model, **criteria)
        columns = tuple(model.__table__.columns)
        expressions = []
        for column in columns:
            if column.type.python_type is str:
                length = func.length(cast(column, LargeBinary))
                cap = min(
                    self.bytes_left,
                    MAX_NOTIFICATION_BYTES if column.key == "payload_json" else 32768,
                )
                expressions.extend((case((length <= cap, column), else_=None), length))
            else:
                expressions.append(column)
        statement = select(*expressions).where(
            *(getattr(model, key) == value for key, value in criteria.items())
        )
        if order is not None:
            statement = statement.order_by(order)
        try:
            raw = self.session.execute(statement.limit(1)).first()
        except SQLAlchemyError:
            self.binding.append((model.__tablename__, tuple(criteria.items()), "UNAVAILABLE"))
            return None
        frozen = None if raw is None else tuple(raw)
        self.binding.append((model.__tablename__, tuple(criteria.items()), frozen))
        if raw is None:
            return None
        values, index, oversized = {}, 0, False
        for column in columns:
            value = raw[index]
            index += 1
            if column.type.python_type is str:
                length = raw[index]
                index += 1
                if length is not None:
                    self.bytes_left -= length
                    oversized |= value is None
            values[column.key] = value
        return None if oversized or self.bytes_left < 0 else SimpleNamespace(**values)

    def event(self, expected, *, target, produced_at=None):
        """Resolve a producer's native key, then check every original payload field."""
        key = daily_alert_key(
            expected["cause_id"],
            expected["plan_hash"],
            expected["signal_type"],
            expected["simulated_qty"],
            expected["quantity"],
            expected["risk_scope"],
            expected["confirmed_trade_date"],
        )
        row = self.row(AlertEvent, criteria={"dedup_key": key})
        if row is None:
            return NotificationRead()
        try:
            event = _event_from_row(row)
            fields = event.model_dump(mode="json")
            if (
                type(event) is not DailyAlertEvent
                or event.created_at > self.now
                or event.trading_date != event.evaluated_at.date()
                or produced_at is not None
                and event.evaluated_at > produced_at
                or any(
                    canonical(fields.get(key)) != canonical(value)
                    for key, value in expected.items()
                )
            ):
                return NotificationRead()
        except OutboxError, TypeError, ValueError, RecursionError:
            return NotificationRead()
        classification = self.classification(event)
        attempts = []
        for channel in DeliveryChannel:
            raw = self.row(
                DeliveryAttempt,
                criteria={"event_id": str(event.event_id), "channel": channel.value},
                order=DeliveryAttempt.attempt.desc(),
            )
            if raw is None:
                continue
            try:
                if (
                    type(raw.attempt) is not int
                    or not 1 <= raw.attempt <= 2**53 - 1
                    or type(raw.id) is not str
                    or not 1 <= len(raw.id) <= 256
                    or raw.response_code is not None
                    and (type(raw.response_code) is not int or not 100 <= raw.response_code <= 599)
                ):
                    continue
                from uuid import UUID

                attempt = DeliveryAttemptRecord(
                    id=raw.id,
                    event_id=UUID(raw.event_id),
                    channel=DeliveryChannel(raw.channel),
                    attempt=raw.attempt,
                    status=DeliveryAttemptStatus(raw.status),
                    response_code=raw.response_code,
                    next_retry_at=_stored_datetime(raw.next_retry_at),
                    delivered_at=_stored_datetime(raw.delivered_at),
                    error_code=None if raw.error_code is None else ChannelErrorCode(raw.error_code),
                )
                if (
                    attempt.event_id != event.event_id
                    or attempt.channel is not channel
                    or (attempt.status is DeliveryAttemptStatus.DELIVERED)
                    != (attempt.delivered_at is not None)
                    or attempt.status is DeliveryAttemptStatus.DELIVERED
                    and (attempt.error_code is not None or attempt.next_retry_at is not None)
                    or attempt.delivered_at is not None
                    and not event.created_at <= attempt.delivered_at <= self.now
                ):
                    continue
                attempts.append(attempt)
            except TypeError, ValueError:
                continue
        return NotificationRead(event, target, classification, tuple(attempts))

    def daily(self, identity):
        """The additional production/candidate lookup shares the SQL byte bound."""
        raw = self.row(DailyRecord, criteria={"id": identity})
        if raw is None:
            return None
        try:
            return self.reads.work.daily._value(raw)
        except TypeError, ValueError, RecursionError:
            return None

    def classification(self, event):
        raw = self.row(AlertDeliveryEligibility, criteria={"event_id": str(event.event_id)})
        if raw is None:
            return None
        try:
            fields = vars(raw).copy()
            fields["barrier"] = (
                None if fields["barrier_json"] is None else json.loads(fields["barrier_json"])
            )
            del fields["barrier_json"]
            record = DeliveryEligibilityRecord.model_validate_json(canonical(fields))
            if (
                record.event_id != event.event_id
                or not event.created_at <= record.updated_at <= self.now
                or record.barrier is not None
                and (
                    record.barrier.symbol,
                    record.barrier.plan_hash,
                    record.barrier.activation_revision,
                )
                != (event.symbol, event.plan_hash, event.activation_revision)
            ):
                return None
            return record
        except TypeError, ValueError, RecursionError:
            return None


def _target(source):
    if source["confirmation_kind"] == "COMPLETED_BAR_CLOSE":
        stamp = source.get("confirmed_at")
        if stamp is None or date.fromisoformat(source["confirmed_trade_date"]) != (
            datetime.fromisoformat(stamp).date()
        ):
            return None
        return IntradayEvaluationTarget(bucket_end=datetime.fromisoformat(stamp))
    return OfficialCloseEvaluationTarget(
        trade_date=date.fromisoformat(source["confirmed_trade_date"])
    )


def _common(plan, details, snapshot):
    return dict(
        plan_id=plan.plan_id,
        plan_version=plan.version,
        plan_hash=details.plan_hash,
        plan_version_id=details.id,
        review_id=details.review_id,
        activation_revision=snapshot["activation_revision"],
        symbol=plan.symbol,
        name=plan.name,
    )


def _ordinary(value, identity, side, snapshot):
    candidates = [item for item in snapshot["signals"] if item["rule_id"] == identity]
    if len(candidates) != 1:
        return None
    source = candidates[0]
    row = value.signals.get(source["signal_id"])
    if (
        row is None
        or row["kind"] != "SIGNAL"
        or row["symbol"] != value.plan.symbol
        or row["lineage"] != value.plan.plan_id
        or source["executable_qty"] <= 0
    ):
        return None
    original = DailySignalState.model_validate_json(canonical(source))
    current = DailySignalState.model_validate_json(
        canonical({**row["payload"], "revision": row["revision"]})
    )
    immutable = (
        "signal_id",
        "rule_id",
        "side",
        "bucket",
        "lineage",
        "planned_qty",
        "confirmed_trade_date",
        "execution_date",
        "evidence_fingerprint",
        "evidence",
        "plan_version_id",
        "review_id",
        "basis_id",
        "confirmation_kind",
        "execution_window",
        "confirmed_at",
        "occurrence_mode",
    )
    if (
        any(getattr(original, key) != getattr(current, key) for key in immutable)
        or original.side != side
        or original.lineage != value.plan.plan_id
        or original.plan_version_id != value.details.id
        or original.review_id != value.details.review_id
        or original.revision is None
        or row["revision"] < original.revision
    ):
        return None
    target = _target(source)
    if target is None:
        return None
    return dict(
        cause_id=source["signal_id"],
        signal_type=side,
        quantity=source["executable_qty"],
        simulated_qty=source["simulated_qty"],
        confirmed_trade_date=source["confirmed_trade_date"],
        execution_date=source["execution_date"],
        risk_scope=None,
        evidence=source["evidence"],
        rule_id=identity if value.plan.schema_version in {8, 9} else None,
        alert_kind=None,
    ), target


def _alert(value, identity, snapshot):
    candidates = [item for item in snapshot["alerts"] if item["rule_id"] == identity]
    if len(candidates) != 1:
        return None
    source = candidates[0]
    if source["outcome"] != "SATISFIED" or not source["cause_id"]:
        return None
    target = _target(source)
    if target is None:
        return None
    return dict(
        cause_id=source["cause_id"],
        signal_type="REMINDER",
        quantity=None,
        simulated_qty=0,
        confirmed_trade_date=source["confirmed_trade_date"],
        execution_date=None,
        risk_scope=None,
        evidence=source["evidence"],
        rule_id=identity,
        alert_kind=source["alert_kind"],
    ), target


def _risk(value, identity, snapshot):
    scope = snapshot["risk_action"]  # Original dict, including original nulls/omissions.
    if scope["status"] != "RISK_EXIT":
        return None
    candidates = [item for item in snapshot["risks"] if item.get("risk_id") == scope["cause_id"]]
    if len(candidates) != 1:
        return None
    source = candidates[0]
    row = value.risks.get(identity)
    original = DailyRiskState.model_validate_json(canonical(source))
    if (
        risk_identity(original) != identity
        or row is None
        or row["kind"] != "RISK"
        or row["symbol"] != value.plan.symbol
        or row["lineage"] != value.plan.symbol
        or original.risk_id != row["id"]
        or scope["cause_revision"] != row["revision"]
        or original.revision != row["revision"]
        or original.kind != scope["branch"]
        or original.status != "CONFIRMED"
        or original.confirmed_trade_date is None
    ):
        return None
    current = DailyRiskState.model_validate_json(
        canonical({**row["payload"], "revision": row["revision"]})
    )
    if current != original:
        return None
    quantities = [scope["core_qty"], scope["tactical_qty"]]
    quantity = None if any(item is None for item in quantities) else sum(quantities)
    if quantity == 0:
        return None
    # A severe branch's daily basis date is not its minute condition target.
    # Preserve no target unless the actual ordinary two-close confirmation proves it.
    target = None
    if original.kind == "ORDINARY_TECHNICAL":
        observed = [
            item
            for item in snapshot.get("risk_evaluations", ())
            if item["risk_identity"] == identity
            and item.get("ordinary_close") is not None
            and item["ordinary_close"]["close_date"] == source["confirmed_trade_date"]
        ]
        if len(observed) == 1 or (
            original.second_close_date == original.confirmed_trade_date
            and original.breach_trade_date is not None
            and original.breach_trade_date < original.confirmed_trade_date
        ):
            target = OfficialCloseEvaluationTarget(trade_date=original.confirmed_trade_date)
    return dict(
        cause_id=original.risk_id,
        signal_type="RISK_EXIT",
        quantity=quantity,
        simulated_qty=0,
        confirmed_trade_date=source["confirmed_trade_date"],
        execution_date=source["earliest_execution_date"],
        risk_scope=scope,
        evidence=[],
        rule_id=None,
        alert_kind=None,
    ), target


def _exception(reader, value, identity, snapshot):
    candidates = [
        item
        for item in snapshot.get("exception_candidates", ())
        if item["candidate"]["binding"]["rule_id"] == identity
    ]
    if len(candidates) != 1:
        return None
    source = candidates[0]
    candidate = source["candidate"]
    binding = candidate["binding"]
    row = reader.daily(candidate["candidate_id"])
    if (
        candidate["state"] != "PENDING"
        or row is None
        or row["kind"] != "EXCEPTION_CANDIDATE"
        or row["symbol"] != value.plan.symbol
        or row["lineage"] != value.plan.plan_id
        or row["revision"] != source["revision"]
        or row["payload"] != candidate
        or binding["plan_version_id"] != value.details.id
        or binding["review_id"] != value.details.review_id
        or binding["activation_revision"] != snapshot["activation_revision"]
        or binding["content_hash"] != value.details.content_hash
        or binding["lineage"] != value.plan.plan_id
        or binding["symbol"] != value.plan.symbol
    ):
        return None
    # The verified production snapshot must actually contain ordinary admission.
    if not snapshot.get("ordinary_evaluations") and not snapshot.get("market_linkage"):
        return None
    return dict(
        cause_id=candidate["candidate_id"],
        signal_type="REMINDER",
        quantity=None,
        simulated_qty=0,
        confirmed_trade_date=binding["decision_session"],
        execution_date=None,
        risk_scope=None,
        evidence=[binding],
        rule_id=identity,
        alert_kind="EXCEPTION_REVIEW",
    ), (OfficialCloseEvaluationTarget(trade_date=date.fromisoformat(binding["decision_session"])))


def read_owned_notifications(work, *, value, authority, now):
    """Production EVAL owns the version; a cause's birth never substitutes for it."""
    reader = NotificationReader(work, now=now)
    facts = {}
    proof = value.proof
    if (
        proof is None
        or type(proof.input_stamp) is not ConditionInputStamp
        or value.native is None
        or not value.active
        or authority is None
    ):
        return facts, ()
    produced_target = (
        IntradayEvaluationTarget(bucket_end=value.native.minute_target)
        if value.native.minute_target is not None
        else OfficialCloseEvaluationTarget(trade_date=value.native.official_trade_date)
        if value.native.official_trade_date is not None
        else None
    )
    if (
        proof.symbol != value.plan.symbol
        or proof.plan_family != "CONDITION_PLAN"
        or proof.target != produced_target
    ):
        return facts, ()
    row = reader.daily(proof.input_stamp.immutable_record_id)
    snapshot = None if row is None else row["payload"]
    if (
        row is None
        or row["id"].startswith("evaluation-head-")
        or row["kind"] != "EVALUATION"
        or row["revision"] != 1
        or row["created_at"] != row["updated_at"]
        or row["symbol"] != value.plan.symbol
        or row["lineage"] != value.plan.plan_id
        or len(canonical(snapshot).encode("utf-8")) > MAX_NOTIFICATION_BYTES
        or proof.result_hash != _fingerprint("condition-result-v1", snapshot)
        or (
            proof.plan_version_id,
            proof.plan_hash,
            proof.activation_revision,
            proof.runtime_generation,
            proof.configuration_revision,
        )
        != (
            value.details.id,
            value.details.plan_hash,
            value.activation_revision,
            authority.generation,
            authority.configuration_revision,
        )
        or snapshot["plan_version_id"] != value.details.id
        or snapshot["content_hash"] != value.details.content_hash
        or snapshot["review_id"] != value.details.review_id
        or snapshot["activation_revision"] != value.activation_revision
        or snapshot["runtime_generation"] != str(authority.generation)
        or snapshot != value.payload
    ):
        return facts, tuple(reader.binding)
    common = _common(value.plan, value.details, snapshot)
    for kind, identity, side, _rule in value.owners:
        try:
            if kind == "ORDINARY_RULE":
                ordinary = _ordinary(value, identity, side, snapshot)
                exception = _exception(reader, value, identity, snapshot)
                selected = (
                    ordinary if exception is None else exception if ordinary is None else None
                )
            elif kind == "ALERT_RULE":
                selected = _alert(value, identity, snapshot)
            else:
                selected = _risk(value, identity, snapshot)
            if selected is None:
                continue
            expected, target = selected
            side = expected["signal_type"]
            policy_rule = next(
                (
                    rule
                    for rule in value.plan.ordinary_rules
                    if hasattr(rule, "pretrade_policy")
                    and (
                        rule.rule_id == expected["rule_id"]
                        or expected["rule_id"] is None
                        and side == "BUY"
                    )
                ),
                None,
            )
            policy = side == "BUY" or expected["alert_kind"] == "EXCEPTION_REVIEW"
            expected.update(
                pretrade_mode=policy_rule.pretrade_policy.economics.mode
                if policy and policy_rule is not None
                else None,
                capital_mode=value.plan.position.limit.capital_policy.mode
                if policy and value.plan.schema_version == 9
                else None,
                next_step="REVIEW_RISK_EXIT"
                if side == "RISK_EXIT"
                else "REVIEW_ALERT"
                if side == "REMINDER"
                else "CONFIRM_SIMULATED_TRADE",
            )
            facts[(kind, identity)] = reader.event(
                {**common, **expected}, target=target, produced_at=value.native.evaluated_at
            )
        except KeyError, TypeError, ValueError, OutboxError, RecursionError:
            facts[(kind, identity)] = NotificationRead()
    return facts, tuple(reader.binding)
