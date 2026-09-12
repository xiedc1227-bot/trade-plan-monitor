"""Transactional persistence participants for explicit-rules-v1 decisions."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_plan_monitor.decision.explicit_rules import (
    ExplicitEvaluationResult,
    ExplicitRuleStateSnapshot,
)
from trade_plan_monitor.state.models import (
    ExplicitEvaluationLedger,
    ExplicitRuleOccurrenceState,
)


class ExplicitDecisionStorageError(RuntimeError):
    code = "EXPLICIT_DECISION_STORAGE_ERROR"


class ExplicitEvaluationIdentityConflictError(ExplicitDecisionStorageError):
    code = "EXPLICIT_EVALUATION_IDENTITY_CONFLICT"


class ExplicitRuleStateConflictError(ExplicitDecisionStorageError):
    code = "EXPLICIT_RULE_STATE_CONFLICT"


class ExplicitEvaluationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    result: ExplicitEvaluationResult
    created: bool


class ExplicitDecisionRepository:
    """Store one result and every proposed repeat transition in the caller transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def states(
        self,
        *,
        plan_hash: str,
        symbol: str,
        activation_revision: int,
    ) -> tuple[ExplicitRuleStateSnapshot, ...]:
        rows = self._session.scalars(
            select(ExplicitRuleOccurrenceState)
            .where(
                ExplicitRuleOccurrenceState.plan_hash == plan_hash,
                ExplicitRuleOccurrenceState.symbol == symbol,
                ExplicitRuleOccurrenceState.activation_revision == activation_revision,
            )
            .order_by(ExplicitRuleOccurrenceState.rule_id)
        ).all()
        return tuple(_state_from_row(row) for row in rows)

    def get(
        self,
        *,
        plan_hash: str,
        symbol: str,
        target_bucket_end: datetime,
        activation_revision: int,
    ) -> ExplicitEvaluationResult | None:
        row = self._session.get(
            ExplicitEvaluationLedger,
            (
                plan_hash,
                symbol,
                target_bucket_end.isoformat(),
                "explicit-rules-v1",
                activation_revision,
            ),
        )
        if row is None:
            return None
        return _result_from_row(row)

    def persist(self, result: ExplicitEvaluationResult) -> ExplicitEvaluationRecord:
        if type(result) is not ExplicitEvaluationResult:
            raise TypeError("result must be an ExplicitEvaluationResult")
        identity = (
            result.plan_hash,
            result.symbol,
            result.target_bucket_end.isoformat(),
            result.execution_version,
            result.activation_revision,
        )
        existing = self._session.get(ExplicitEvaluationLedger, identity)
        if existing is not None:
            stored = _result_from_row(existing)
            if stored != result:
                raise ExplicitEvaluationIdentityConflictError(
                    "explicit evaluation identity already has different semantics"
                )
            return ExplicitEvaluationRecord(result=stored, created=False)

        for rule_result in result.rule_results:
            transition = rule_result.state_transition
            if transition is None:
                continue
            state_identity = (
                result.plan_hash,
                result.symbol,
                result.activation_revision,
                transition.rule_id,
            )
            row = self._session.get(ExplicitRuleOccurrenceState, state_identity)
            if row is None:
                if transition.expected_revision != 0:
                    raise ExplicitRuleStateConflictError("explicit rule state is absent")
                row = ExplicitRuleOccurrenceState(
                    plan_hash=result.plan_hash,
                    symbol=result.symbol,
                    activation_revision=result.activation_revision,
                    rule_id=transition.rule_id,
                    revision=transition.next_revision,
                    has_emitted=True,
                    last_emitted_bucket_end=transition.last_emitted_bucket_end.isoformat(),
                )
                self._session.add(row)
            else:
                if row.revision != transition.expected_revision:
                    raise ExplicitRuleStateConflictError("explicit rule state revision is stale")
                row.revision = transition.next_revision
                row.has_emitted = True
                row.last_emitted_bucket_end = transition.last_emitted_bucket_end.isoformat()

        row = ExplicitEvaluationLedger(
            plan_hash=result.plan_hash,
            symbol=result.symbol,
            target_value=result.target_bucket_end.isoformat(),
            execution_version=result.execution_version,
            activation_revision=result.activation_revision,
            result_hash=result.result_hash,
            result_json=result.model_dump_json(round_trip=True),
            inventory_revision=result.inventory_revision,
            manual_event_risk_revision=result.manual_event_risk_revision,
            evaluated_at=result.evaluated_at.isoformat(),
        )
        self._session.add(row)
        self._session.flush()
        return ExplicitEvaluationRecord(result=result, created=True)


def _state_from_row(row: ExplicitRuleOccurrenceState) -> ExplicitRuleStateSnapshot:
    return ExplicitRuleStateSnapshot(
        rule_id=row.rule_id,
        activation_revision=row.activation_revision,
        revision=row.revision,
        has_emitted=row.has_emitted,
        last_emitted_bucket_end=datetime.fromisoformat(row.last_emitted_bucket_end),
    )


def _result_from_row(row: ExplicitEvaluationLedger) -> ExplicitEvaluationResult:
    try:
        result = ExplicitEvaluationResult.model_validate_json(row.result_json)
    except (TypeError, ValueError):
        raise ExplicitDecisionStorageError("stored explicit result is invalid") from None
    expected: Mapping[str, object] = {
        "plan_hash": row.plan_hash,
        "symbol": row.symbol,
        "target_bucket_end": row.target_value,
        "execution_version": row.execution_version,
        "activation_revision": row.activation_revision,
        "result_hash": row.result_hash,
        "inventory_revision": row.inventory_revision,
        "manual_event_risk_revision": row.manual_event_risk_revision,
        "evaluated_at": row.evaluated_at,
    }
    actual = {
        "plan_hash": result.plan_hash,
        "symbol": result.symbol,
        "target_bucket_end": result.target_bucket_end.isoformat(),
        "execution_version": result.execution_version,
        "activation_revision": result.activation_revision,
        "result_hash": result.result_hash,
        "inventory_revision": result.inventory_revision,
        "manual_event_risk_revision": result.manual_event_risk_revision,
        "evaluated_at": result.evaluated_at.isoformat(),
    }
    if actual != expected:
        raise ExplicitDecisionStorageError("stored explicit result identity is invalid")
    return result


__all__ = [
    "ExplicitDecisionRepository",
    "ExplicitDecisionStorageError",
    "ExplicitEvaluationIdentityConflictError",
    "ExplicitEvaluationRecord",
    "ExplicitRuleStateConflictError",
]
