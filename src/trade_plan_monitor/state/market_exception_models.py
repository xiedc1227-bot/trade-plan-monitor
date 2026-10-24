"""Closed, digest-checked occurrence projections and immutable human events."""

from datetime import date, datetime, time
from typing import Annotated, Literal

from pydantic import Field, model_validator

from trade_plan_monitor.decision.unified_conditions import UnifiedConditionEvidence
from trade_plan_monitor.domain.daily_plan_models import DailyValue, PositiveWholeQty
from trade_plan_monitor.domain.market_exception_models import ExceptionRoute
from trade_plan_monitor.market_data.models import ShanghaiDatetime
from trade_plan_monitor.state.daily_repository import daily_hash

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[str, Field(min_length=1, max_length=128)]
Revision = Annotated[int, Field(strict=True, ge=1)]
State = Literal[
    "PENDING", "APPROVED", "REJECTED", "REVOKED", "EXPIRED", "INVALIDATED", "CONSUMED"
]
TRANSITIONS = {
    "PENDING": frozenset({"APPROVED", "REJECTED", "EXPIRED", "INVALIDATED"}),
    "APPROVED": frozenset({"CONSUMED", "REVOKED", "EXPIRED", "INVALIDATED"}),
}


class ExceptionBinding(DailyValue):
    occurrence_id: Digest
    symbol: str = Field(pattern=r"^\d{6}\.(SH|SZ|BJ)$")
    lineage: Identifier
    rule_id: Identifier
    plan_version_id: Identifier
    review_id: Identifier
    activation_revision: Revision
    content_hash: Digest
    route: ExceptionRoute
    decision_session: date
    evidence_cutoff: ShanghaiDatetime
    execution_date: date
    expires_at: ShanghaiDatetime
    evidence_hash: Digest
    consumed_hash: Digest
    grid_hash: Digest
    base_quantity: PositiveWholeQty
    minimum: Annotated[int, Field(strict=True, gt=0)]
    increment: Annotated[int, Field(strict=True, gt=0)]

    @model_validator(mode="after")
    def coherent(self):
        if not self.decision_session < self.execution_date:
            raise ValueError("exception requires the next exchange session")
        if (self.expires_at.date() != self.execution_date
                or self.expires_at.time() != time(15)
                or self.evidence_cutoff < datetime.combine(
                    self.decision_session, time(15), self.evidence_cutoff.tzinfo)
                or self.evidence_cutoff >= self.expires_at):
            raise ValueError("exception window or evidence cutoff is invalid")
        return self


class ExceptionSignalSeed(DailyValue):
    signal_id: Digest
    basis_id: Identifier
    evidence_fingerprint: Digest
    evidence: tuple[UnifiedConditionEvidence, ...] = Field(min_length=1, max_length=1)
    occurrence_mode: Literal["ONCE_PER_RULE", "AFTER_RULE_COMPLETED"] | None = None


class ExceptionCandidate(DailyValue):
    version: Literal["market-linkage-exception-candidate-v1"] = (
        "market-linkage-exception-candidate-v1")
    candidate_id: Digest
    binding: ExceptionBinding
    binding_hash: Digest
    created_at: ShanghaiDatetime
    state: State
    approval_id: Digest | None
    frozen_quantity: PositiveWholeQty | None
    last_event_id: Digest | None
    signal_seed: ExceptionSignalSeed | None = Field(
        default=None, exclude_if=lambda value: value is None)
    projection_hash: Digest

    @model_validator(mode="after")
    def coherent(self):
        if self.binding_hash != daily_hash("exception-binding-v1", self.binding.model_dump(
                mode="json")):
            raise ValueError("exception binding hash mismatch")
        if self.candidate_id != daily_hash("exception-candidate-id-v1", {
                "occurrence_id": self.binding.occurrence_id}):
            raise ValueError("exception candidate identity hash mismatch")
        if self.projection_hash != daily_hash(self.version, self.model_dump(
                mode="json", exclude={"projection_hash"})):
            raise ValueError("exception projection hash mismatch")
        if not self.binding.evidence_cutoff <= self.created_at < self.binding.expires_at:
            raise ValueError("candidate receipt outside its original evidence window")
        if (self.approval_id is None) != (self.frozen_quantity is None):
            raise ValueError("approval identity and frozen quantity are inseparable")
        if self.state in {"APPROVED", "REVOKED", "CONSUMED"} and self.approval_id is None:
            raise ValueError("approved lifecycle requires frozen authority")
        if self.state in {"PENDING", "REJECTED"} and self.approval_id is not None:
            raise ValueError("unapproved candidate cannot contain authority")
        if (self.state == "PENDING") != (self.last_event_id is None):
            raise ValueError("candidate state must retain transition evidence")
        if self.frozen_quantity is not None:
            q, b = self.frozen_quantity, self.binding
            if q > b.base_quantity or q < b.minimum or (q-b.minimum) % b.increment:
                raise ValueError("frozen quantity violates source ceiling or grid")
            if b.route == "WEAK_MINIMUM" and (
                    q != b.minimum or b.base_quantity >= 2*b.minimum):
                raise ValueError("weak exception must be the exact minimum")
        if (self.signal_seed is not None
                and self.signal_seed.signal_id != self.binding.occurrence_id):
            raise ValueError("candidate seed must retain its independent occurrence")
        return self


class ExceptionEvent(DailyValue):
    version: Literal["market-linkage-exception-authorization-v1"] = (
        "market-linkage-exception-authorization-v1")
    event_id: Digest
    candidate_id: Digest
    binding_hash: Digest
    command_id: Identifier
    request_hash: Digest
    from_state: State
    to_state: State
    expected_revision: Revision
    received_at: ShanghaiDatetime
    reason: str = Field(min_length=1, max_length=2000)
    quantity: PositiveWholeQty | None
    approval_id: Digest | None
    preview_hash: Digest | None
    event_hash: Digest

    @model_validator(mode="after")
    def coherent(self):
        if self.to_state not in TRANSITIONS.get(self.from_state, ()):
            raise ValueError("illegal exception lifecycle transition")
        if self.event_id != daily_hash("exception-event-id-v1", {
                "candidate_id": self.candidate_id, "to_state": self.to_state}):
            raise ValueError("exception event identity hash mismatch")
        if self.event_hash != daily_hash(self.version, self.model_dump(
                mode="json", exclude={"event_hash"})):
            raise ValueError("exception event hash mismatch")
        if (self.approval_id is None) != (self.quantity is None):
            raise ValueError("event authority must be complete")
        if self.to_state == "APPROVED" and (
                self.approval_id != self.event_id or self.quantity is None
                or self.preview_hash is None):
            raise ValueError("approval requires exact preview and quantity")
        if self.from_state == "APPROVED" and self.approval_id is None:
            raise ValueError("approved transitions retain authority evidence")
        if self.from_state == "PENDING" and self.to_state != "APPROVED" and (
                self.quantity is not None or self.preview_hash is not None):
            raise ValueError("unapproved transitions cannot contain authority")
        return self


def seal_candidate(payload):
    payload = dict(payload)
    payload.pop("projection_hash", None)
    payload["projection_hash"] = daily_hash(
        "market-linkage-exception-candidate-v1", payload)
    return ExceptionCandidate.model_validate(payload)


class ExceptionCandidateResource(DailyValue):
    candidate: ExceptionCandidate
    revision: Revision
    blockers: tuple[str, ...] = Field(default=(), exclude_if=lambda value: not value)


def new_candidate(binding, now, *, signal_seed=None):
    payload = dict(
        version="market-linkage-exception-candidate-v1",
        candidate_id=daily_hash("exception-candidate-id-v1", {
            "occurrence_id": binding.occurrence_id}),
        binding=binding.model_dump(mode="json"),
        binding_hash=daily_hash("exception-binding-v1", binding.model_dump(mode="json")),
        created_at=now.isoformat(), state="PENDING", approval_id=None,
        frozen_quantity=None, last_event_id=None,
    )
    if signal_seed is not None:
        payload["signal_seed"] = signal_seed.model_dump(mode="json")
    return seal_candidate(payload)


def transition_candidate(candidate, *, to_state, command_id, expected_revision, now,
                         reason, quantity=None, preview_hash=None, request_hash=None):
    """Construct evidence only; the repository checks the current locked projection."""
    event_id = daily_hash("exception-event-id-v1", {
        "candidate_id": candidate.candidate_id, "to_state": to_state})
    approval_id = event_id if to_state == "APPROVED" else candidate.approval_id
    frozen = quantity if to_state == "APPROVED" else candidate.frozen_quantity
    payload = dict(
        version="market-linkage-exception-authorization-v1", event_id=event_id,
        candidate_id=candidate.candidate_id, binding_hash=candidate.binding_hash,
        command_id=command_id, from_state=candidate.state, to_state=to_state,
        expected_revision=expected_revision, received_at=now.isoformat(), reason=reason,
        quantity=frozen, approval_id=approval_id, preview_hash=preview_hash,
    )
    payload["request_hash"] = request_hash or daily_hash("exception-system-transition-v1", payload)
    payload["event_hash"] = daily_hash(payload["version"], payload)
    event = ExceptionEvent.model_validate(payload)
    updated = seal_candidate(candidate.model_dump(mode="json") | dict(
        state=to_state, approval_id=approval_id, frozen_quantity=frozen, last_event_id=event_id))
    return updated, event
