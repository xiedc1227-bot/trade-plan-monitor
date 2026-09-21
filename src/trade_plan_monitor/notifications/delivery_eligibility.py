"""Session-bound recovery receipts, isolated from immutable alert semantics.

These records are NOT send authorization. Future dispatch must re-read current
activation, generation, target and applicability immediately before channel I/O.
The caller owns transaction commit/rollback, including all audit writes.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from trade_plan_monitor.decision.explicit_rules import ExplicitEvaluationResult
from trade_plan_monitor.decision.models import Sha256Hex
from trade_plan_monitor.market_data.aggregation import five_minute_bucket_end
from trade_plan_monitor.market_data.models import ShanghaiDatetime
from trade_plan_monitor.notifications.models import ExplicitAlertEvent
from trade_plan_monitor.notifications.outbox import OutboxError, _event_from_row
from trade_plan_monitor.notifications.recovery_eligibility import (
    ActiveExplicitPlan,
    RecoveryBarrierEvidence,
    RecoveryDeliveryReason,
    RecoveryDeliveryStatus,
    classify_explicit_risk_delivery,
)
from trade_plan_monitor.runtime.clock import _canonical_shanghai
from trade_plan_monitor.state.models import AlertDeliveryEligibility as MetadataRow
from trade_plan_monitor.state.models import AlertEvent as AlertRow
from trade_plan_monitor.state.models import AuditLog, MonitorSequence

_ACTIONABLE_SIGNALS = frozenset(
    {
        "BUY_CORE_READY",
        "BUY_TACTICAL_READY",
        "PRESSURE_REDUCE_READY",
        "BUY",
        "SELL",
    }
)
_SUPPRESS_REASONS = frozenset(
    {
        "SOURCE_EXPIRED",
        "ACTIVE_IDENTITY_INVALID",
        "ACTIVATION_EXPIRED",
        "RISK_FALSE",
    }
)
_STATUS_REASONS = {
    RecoveryDeliveryStatus.SUPPRESS: _SUPPRESS_REASONS,
    RecoveryDeliveryStatus.ELIGIBLE: frozenset({"RISK_TRUE"}),
    RecoveryDeliveryStatus.HOLD: frozenset(
        {
            "RECOVERY_REQUIRED",
            "SOURCE_CUTOFF_UNKNOWN",
            *(
                reason.value
                for reason in RecoveryDeliveryReason
                if reason.value not in _SUPPRESS_REASONS and reason.value != "RISK_TRUE"
            ),
        }
    ),
}


class DeliveryClass(StrEnum):
    INTRADAY_ACTIONABLE = "INTRADAY_ACTIONABLE"
    STATE_RISK = "STATE_RISK"


class DeliveryMetadataError(RuntimeError):
    """Delivery metadata is unavailable or invalid; never permit through this fault."""


class DeliveryMetadataConflict(DeliveryMetadataError):
    """The decision revision is obsolete or the original event is terminally suppressed."""


class DeliveryEligibilityRecord(BaseModel):
    """Immutable historical classification with captured, not current, evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    event_id: UUID
    schema_version: int = Field(default=1, ge=1, le=1)
    revision: int = Field(ge=0)
    delivery_class: DeliveryClass
    source_cutoff: ShanghaiDatetime | None
    expires_at: ShanghaiDatetime | None
    status: RecoveryDeliveryStatus
    reason: str
    barrier: RecoveryBarrierEvidence | None = None
    result_hash: Sha256Hex | None = None
    updated_at: ShanghaiDatetime

    @model_validator(mode="after")
    def validate_receipt(self):
        expected_expiry = (
            self.source_cutoff + timedelta(seconds=90)
            if self.delivery_class is DeliveryClass.INTRADAY_ACTIONABLE
            and self.source_cutoff is not None
            else None
        )
        if self.reason not in _STATUS_REASONS[self.status] or self.expires_at != expected_expiry:
            raise ValueError("invalid delivery metadata")
        if self.reason == "SOURCE_EXPIRED" and (
            self.expires_at is None or self.updated_at < self.expires_at
        ):
            raise ValueError("expired receipt requires a reached actionable deadline")
        if self.reason in {"RISK_TRUE", "RISK_FALSE"} and (
            self.delivery_class is not DeliveryClass.STATE_RISK
            or self.barrier is None
            or self.result_hash is None
            or self.barrier.reconciled_through != self.barrier.target_bucket_end
            or self.barrier.pending_obligations != 0
            or self.barrier.observed_at > self.updated_at
            or self.barrier.observed_at < self.barrier.target_bucket_end
            or five_minute_bucket_end(self.barrier.target_bucket_end)
            != self.barrier.target_bucket_end
        ):
            raise ValueError("eligible receipt requires complete captured evidence")
        return self


class DeliveryEligibilityRepository:
    """Use inside the evaluator/reconciler's explicit transaction; never commits.

    SQLAlchemy transaction ownership: https://docs.sqlalchemy.org/en/20/orm/session_transaction.html
    Writer-before-read follows the local event repository's SQLite WAL discipline.
    Already-open stale snapshots remain visible database errors, not retry grants.
    """

    def __init__(self, session: Session, *, clock: Callable[[], datetime]) -> None:
        self._session = session
        self._clock = clock

    def get(self, event_id: UUID) -> DeliveryEligibilityRecord | None:
        self._validate_id(event_id)
        row = self._session.scalar(
            select(MetadataRow)
            .where(MetadataRow.event_id == str(event_id))
            .execution_options(populate_existing=True)
        )
        if row is None:
            return None
        try:
            record = DeliveryEligibilityRecord.model_validate_json(
                json.dumps(
                    {
                        "event_id": row.event_id,
                        "schema_version": row.schema_version,
                        "revision": row.revision,
                        "delivery_class": row.delivery_class,
                        "source_cutoff": row.source_cutoff,
                        "expires_at": row.expires_at,
                        "status": row.status,
                        "reason": row.reason,
                        "updated_at": row.updated_at,
                        "barrier": None
                        if row.barrier_json is None
                        else json.loads(row.barrier_json),
                        "result_hash": row.result_hash,
                    }
                )
            )
            event = self._event(event_id)
            delivery_class, source = self._source(event)
            if record.delivery_class != delivery_class or record.source_cutoff != source:
                raise ValueError("metadata source differs from canonical alert")
            if record.reason in RecoveryDeliveryReason._value2member_map_ and (
                type(event) is not ExplicitAlertEvent or event.signal_type != "RISK_ALERT"
            ):
                raise ValueError("classifier reason differs from canonical alert family")
            if record.reason in {"RISK_TRUE", "RISK_FALSE"} and (
                record.barrier.symbol != event.symbol
                or record.barrier.plan_hash != event.plan_hash
                or record.barrier.activation_revision != event.activation_revision
                or record.barrier.target_bucket_end < event.target_bucket_end
            ):
                raise ValueError("eligible receipt differs from canonical alert")
            return record
        except OutboxError, ValueError, TypeError, RecursionError:
            raise DeliveryMetadataError("Stored delivery metadata is invalid") from None

    def initialize(self, event_id: UUID) -> DeliveryEligibilityRecord:
        self._lock(event_id)
        existing = self.get(event_id)
        if existing is not None:
            return existing
        event = self._event(event_id)
        delivery_class, source = self._source(event)
        record = DeliveryEligibilityRecord(
            event_id=event_id,
            revision=0,
            delivery_class=delivery_class,
            source_cutoff=source,
            expires_at=(
                source + timedelta(seconds=90)
                if source is not None and delivery_class is DeliveryClass.INTRADAY_ACTIONABLE
                else None
            ),
            status=RecoveryDeliveryStatus.HOLD,
            reason="SOURCE_CUTOFF_UNKNOWN" if source is None else "RECOVERY_REQUIRED",
            updated_at=self._now(),
        )
        self._session.add(MetadataRow(**self._row_values(record)))
        self._audit(record)
        self._session.flush()
        return record

    def initialize_batch(self, *, limit: int = 100) -> tuple[DeliveryEligibilityRecord, ...]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        self._require_transaction()
        self._session.execute(
            update(MonitorSequence)
            .where(MonitorSequence.singleton_id == 1)
            .values(last_sequence=MonitorSequence.last_sequence)
        )
        ids = self._session.scalars(
            select(AlertRow.id)
            .outerjoin(MetadataRow, MetadataRow.event_id == AlertRow.id)
            .where(MetadataRow.event_id.is_(None))
            .order_by(AlertRow.sequence)
            .limit(limit)
        ).all()
        return tuple(self.initialize(UUID(event_id)) for event_id in ids)

    def expire_actionable(
        self,
        event_id: UUID,
        *,
        expected_revision: int,
    ) -> DeliveryEligibilityRecord:
        self._lock(event_id)
        current = self._expected(event_id, expected_revision)
        now = self._now()
        if current.status is RecoveryDeliveryStatus.SUPPRESS or (
            current.expires_at is None or now < current.expires_at
        ):
            return current
        return self._replace(
            current, status=RecoveryDeliveryStatus.SUPPRESS, reason="SOURCE_EXPIRED", updated_at=now
        )

    def _replace(self, current: DeliveryEligibilityRecord, **changes) -> DeliveryEligibilityRecord:
        record = DeliveryEligibilityRecord.model_validate(
            {
                **current.model_dump(mode="python"),
                **changes,
                "revision": current.revision + 1,
            }
        )
        result = self._session.execute(
            update(MetadataRow)
            .where(
                MetadataRow.event_id == str(current.event_id),
                MetadataRow.revision == current.revision,
                MetadataRow.status != RecoveryDeliveryStatus.SUPPRESS.value,
            )
            .values(**self._row_values(record))
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            raise DeliveryMetadataConflict("Delivery classification changed")
        self._audit(record)
        self._session.flush()
        return record

    def classify_explicit_risk(
        self,
        event_id: UUID,
        *,
        expected_revision: int,
        active: ActiveExplicitPlan | None,
        latest: ExplicitEvaluationResult | None,
        barrier: RecoveryBarrierEvidence | None,
        target_bucket_end: datetime,
        runtime_generation: UUID,
    ) -> DeliveryEligibilityRecord:
        """Record the existing pure policy using injected authoritative facts.

        ``active=None`` means proven absence, not a lookup failure. The caller
        must establish these facts coherently inside its transaction. Persisting
        them does not reconstruct a barrier or authorize later channel I/O.
        """
        self._lock(event_id)
        current = self._expected(event_id, expected_revision)
        if current.status is RecoveryDeliveryStatus.SUPPRESS:
            raise DeliveryMetadataConflict("Suppressed alert cannot be reclassified")
        event = self._event(event_id)
        if type(event) is not ExplicitAlertEvent or event.signal_type != "RISK_ALERT":
            raise ValueError("classification requires an explicit risk alert")
        now = self._now()
        decision = classify_explicit_risk_delivery(
            event,
            active=active,
            latest=latest,
            barrier=barrier,
            target_bucket_end=target_bucket_end,
            runtime_generation=runtime_generation,
            now=now,
        )
        return self._replace(
            current,
            status=decision.status,
            reason=decision.reason.value,
            barrier=barrier,
            result_hash=None if latest is None else latest.result_hash,
            updated_at=now,
        )

    def _expected(self, event_id, expected_revision):
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("expected_revision must be a nonnegative integer")
        current = self.get(event_id)
        if current is None or current.revision != expected_revision:
            raise DeliveryMetadataConflict("Delivery classification revision is stale")
        return current

    def _event(self, event_id):
        row = self._session.scalar(
            select(AlertRow)
            .where(AlertRow.id == str(event_id))
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise DeliveryMetadataError("Alert event is unavailable")
        return _event_from_row(row)

    def _lock(self, event_id):
        self._validate_id(event_id)
        self._require_transaction()
        result = self._session.execute(
            update(AlertRow)
            .where(AlertRow.id == str(event_id))
            .values(id=AlertRow.id)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            raise DeliveryMetadataError("Alert event is unavailable")

    def _require_transaction(self):
        if not self._session.in_transaction():
            raise DeliveryMetadataError("Delivery metadata requires a caller-owned transaction")

    @staticmethod
    def _validate_id(event_id):
        if type(event_id) is not UUID:
            raise TypeError("event_id must be a UUID")

    @staticmethod
    def _row_values(record):
        values = record.model_dump(mode="json", exclude={"barrier"})
        values["barrier_json"] = (
            None if record.barrier is None else record.barrier.model_dump_json()
        )
        return values

    def _audit(self, record):
        self._session.add(
            AuditLog(
                id=str(
                    uuid5(
                        NAMESPACE_URL, f"delivery-eligibility:{record.event_id}:{record.revision}"
                    )
                ),
                action="ALERT_DELIVERY_CLASSIFIED",
                entity_type="alert_delivery_eligibility",
                entity_id=str(record.event_id),
                before_hash=None,
                after_hash=None,
                details_json=record.model_dump_json(),
                created_at=record.updated_at.isoformat(),
            )
        )

    def _now(self):
        return _canonical_shanghai(self._clock())

    @staticmethod
    def _source(event):
        source = (
            event.target_bucket_end if type(event) is ExplicitAlertEvent else event.market_data_at
        )
        delivery_class = (
            DeliveryClass.INTRADAY_ACTIONABLE
            if event.signal_type in _ACTIONABLE_SIGNALS
            else DeliveryClass.STATE_RISK
        )
        return delivery_class, source
