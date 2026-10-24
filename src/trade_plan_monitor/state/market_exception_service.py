"""Explicit commands against server-owned current authority, in caller transactions."""

from typing import Literal

from pydantic import Field, model_validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import OperationalError

from trade_plan_monitor.decision.market_exception_policy import validate_exception_quantity
from trade_plan_monitor.domain.daily_plan_models import DailyValue, PositiveWholeQty, Qty
from trade_plan_monitor.market_data.models import ShanghaiDatetime
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.daily_repository import daily_hash
from trade_plan_monitor.state.market_exception_models import (
    Digest,
    ExceptionCandidate,
    ExceptionEvent,
    Identifier,
    Revision,
    seal_candidate,
    transition_candidate,
)
from trade_plan_monitor.state.market_exception_repository import ExceptionRepository


class ExceptionAuthorityError(ValueError):
    def __init__(self, reason, *, status=409):
        super().__init__(reason)
        self.reason, self.status = reason, status


class ExceptionAuthorityContext(DailyValue):
    """Constructed only by the owned runtime adapter, never accepted from an API."""

    binding_hash: Digest
    inventory_revision: Qty
    evaluation_revision: Qty
    authority_hash: Digest
    capacity: int | None = Field(strict=True)
    blockers: tuple[str, ...]


class ExceptionPreviewCommand(DailyValue):
    candidate_id: Digest
    expected_revision: Revision
    proposed_quantity: int | None = Field(default=None, strict=True, ge=0, le=9_007_199_254_740_991)


class ExceptionDecisionCommand(DailyValue):
    command_id: Identifier
    candidate_id: Digest
    expected_revision: Revision
    decision: Literal["APPROVE", "REJECT"]
    reason: str = Field(min_length=1, max_length=2000)
    preview_id: Digest | None = None
    preview_hash: Digest | None = None

    @model_validator(mode="after")
    def coherent(self):
        if self.decision == "APPROVE":
            if self.preview_id is None or self.preview_hash is None:
                raise ValueError("approval requires an exact preview")
        elif self.preview_id is not None or self.preview_hash is not None:
            raise ValueError("rejection cannot carry a preview")
        return self


class ExceptionRevocationCommand(DailyValue):
    command_id: Identifier
    approval_id: Digest
    expected_revision: Revision
    reason: str = Field(min_length=1, max_length=2000)


class ExceptionPreview(DailyValue):
    version: Literal["market-linkage-exception-preview-v1"] = "market-linkage-exception-preview-v1"
    preview_id: Digest
    candidate_id: Digest
    expected_revision: Revision
    binding_hash: Digest
    current: ExceptionAuthorityContext
    proposed_quantity: int | None = Field(strict=True)
    quantity: PositiveWholeQty
    created_at: ShanghaiDatetime
    preview_hash: Digest

    @model_validator(mode="after")
    def coherent(self):
        if self.binding_hash != self.current.binding_hash:
            raise ValueError("preview authority binding mismatch")
        value = self.model_dump(mode="json", exclude={"preview_hash", "preview_id"})
        if self.preview_hash != daily_hash(self.version, value):
            raise ValueError("preview hash mismatch")
        if self.preview_id != daily_hash("exception-preview-id-v1", self.preview_hash):
            raise ValueError("preview identity mismatch")
        return self


class ExceptionReceipt(DailyValue):
    candidate: ExceptionCandidate
    revision: Revision
    event: ExceptionEvent


def lock_authority(daily, identity):
    """Acquire the write fence before reading a snapshot that might become stale."""
    try:
        daily.session.execute(update(DailyRecord).where(DailyRecord.id == identity).values(
            revision=DailyRecord.revision))
    except OperationalError as error:
        if getattr(error.orig, "sqlite_errorcode", 0) & 255 in {5, 6}:
            raise ExceptionAuthorityError("EXCEPTION_CONCURRENT_COMMAND") from error
        raise
    daily.session.expire_all()


def _candidate(daily, candidate_id, expected_revision, now, allowed=("PENDING",)):
    lock_authority(daily, candidate_id)
    repo = ExceptionRepository(daily)
    row = repo.get(candidate_id)
    if row is None:
        raise ExceptionAuthorityError("EXCEPTION_NOT_FOUND", status=404)
    candidate = ExceptionCandidate.model_validate(row["payload"])
    if row["revision"] != expected_revision:
        raise ExceptionAuthorityError("EXCEPTION_REVISION_CONFLICT")
    if candidate.state not in allowed:
        raise ExceptionAuthorityError("EXCEPTION_TERMINAL_OR_ALREADY_DECIDED")
    if not candidate.created_at <= now < candidate.binding.expires_at:
        raise ExceptionAuthorityError("EXCEPTION_WINDOW_EXPIRED")
    return candidate


def _current(candidate, current):
    context = ExceptionAuthorityContext.model_validate(current(candidate).model_dump())
    if context.binding_hash != candidate.binding_hash:
        raise ExceptionAuthorityError("EXCEPTION_CURRENT_BINDING_CHANGED")
    if context.blockers:
        raise ExceptionAuthorityError(context.blockers[0])
    return context


def _quantity(candidate, context, proposed):
    b = candidate.binding
    result = validate_exception_quantity(
        route=b.route, base_quantity=b.base_quantity, minimum=b.minimum, increment=b.increment,
        capacity=context.capacity, proposed_quantity=proposed)
    if result.blockers:
        raise ExceptionAuthorityError(result.blockers[0], status=(
            422 if result.blockers[0].startswith("EXCEPTION_QUANTITY") else 409))
    return result.candidate_quantity


def preview_exception(daily, command, *, current, now):
    candidate = _candidate(daily, command.candidate_id, command.expected_revision, now)
    context = _current(candidate, current)
    quantity = _quantity(candidate, context, command.proposed_quantity)
    payload = dict(
        version="market-linkage-exception-preview-v1", candidate_id=candidate.candidate_id,
        expected_revision=command.expected_revision, binding_hash=candidate.binding_hash,
        current=context.model_dump(mode="json"), proposed_quantity=command.proposed_quantity,
        quantity=quantity, created_at=now.isoformat())
    payload["preview_hash"] = daily_hash(payload["version"], payload)
    payload["preview_id"] = daily_hash("exception-preview-id-v1", payload["preview_hash"])
    preview = ExceptionPreview.model_validate(payload)
    existing = daily.get(preview.preview_id)
    if existing is None:
        daily.save(preview.preview_id, kind="EXCEPTION_PREVIEW", symbol=candidate.binding.symbol,
                   lineage=candidate.binding.lineage, payload=preview.model_dump(mode="json"),
                   expected_revision=0)
    elif existing["payload"] != preview.model_dump(mode="json"):
        raise ExceptionAuthorityError("EXCEPTION_PREVIEW_CONFLICT")
    return preview


def _replay(daily, command):
    request_hash = daily_hash("exception-command-v1", command.model_dump(mode="json"))
    row = daily.session.scalar(select(DailyRecord).where(
        DailyRecord.kind == "EXCEPTION_EVENT",
        func.json_extract(DailyRecord.payload_json, "$.command_id") == command.command_id))
    if row is None:
        return None, request_hash
    event = ExceptionEvent.model_validate(daily.get(row.id)["payload"])
    if event.request_hash != request_hash:
        raise ExceptionAuthorityError("EXCEPTION_COMMAND_REUSE_CONFLICT")
    candidate = ExceptionCandidate.model_validate(
        ExceptionRepository(daily).get(event.candidate_id)["payload"])
    # Return the original receipt, never reinterpret a replay as a new approval.
    frozen = seal_candidate(candidate.model_dump(mode="json") | dict(
        state=event.to_state, approval_id=event.approval_id, frozen_quantity=event.quantity,
        last_event_id=event.event_id))
    return ExceptionReceipt(candidate=frozen, revision=event.expected_revision+1, event=event), None


def decide_exception(daily, command, *, current, now):
    lock_authority(daily, command.candidate_id)
    replay, request_hash = _replay(daily, command)
    if replay is not None:
        return replay
    candidate = _candidate(daily, command.candidate_id, command.expected_revision, now)
    replay, request_hash = _replay(daily, command)
    if replay is not None:
        return replay
    context = _current(candidate, current)
    quantity = None
    if command.decision == "APPROVE":
        row = daily.get(command.preview_id)
        if row is None or row["kind"] != "EXCEPTION_PREVIEW":
            raise ExceptionAuthorityError("EXCEPTION_PREVIEW_NOT_FOUND", status=404)
        preview = ExceptionPreview.model_validate(row["payload"])
        if (preview.candidate_id != candidate.candidate_id
                or preview.preview_hash != command.preview_hash
                or preview.expected_revision != command.expected_revision
                or preview.current != context or preview.created_at > now):
            raise ExceptionAuthorityError("EXCEPTION_PREVIEW_STALE")
        quantity = _quantity(candidate, context, preview.proposed_quantity)
        if quantity != preview.quantity:
            raise ExceptionAuthorityError("EXCEPTION_PREVIEW_QUANTITY_CHANGED")
    updated, event = transition_candidate(
        candidate, to_state="APPROVED" if command.decision == "APPROVE" else "REJECTED",
        command_id=command.command_id, expected_revision=command.expected_revision,
        now=now, reason=command.reason, quantity=quantity, preview_hash=command.preview_hash,
        request_hash=request_hash)
    row = ExceptionRepository(daily).transition(
        updated, event, expected_revision=command.expected_revision)
    return ExceptionReceipt(candidate=updated, revision=row["revision"], event=event)


def revoke_exception(daily, command, *, now):
    lock_authority(daily, command.approval_id)
    replay, request_hash = _replay(daily, command)
    if replay is not None:
        return replay
    row = daily.get(command.approval_id)
    if row is None or row["kind"] != "EXCEPTION_EVENT":
        raise ExceptionAuthorityError("EXCEPTION_APPROVAL_NOT_FOUND", status=404)
    approval = ExceptionEvent.model_validate(row["payload"])
    if approval.to_state != "APPROVED" or approval.event_id != command.approval_id:
        raise ExceptionAuthorityError("EXCEPTION_APPROVAL_NOT_FOUND", status=404)
    candidate = _candidate(daily, approval.candidate_id, command.expected_revision, now,
                           allowed=("APPROVED",))
    if candidate.approval_id != command.approval_id:
        raise ExceptionAuthorityError("EXCEPTION_FOREIGN_APPROVAL")
    updated, event = transition_candidate(
        candidate, to_state="REVOKED", command_id=command.command_id,
        expected_revision=command.expected_revision, now=now, reason=command.reason,
        request_hash=request_hash)
    row = ExceptionRepository(daily).transition(
        updated, event, expected_revision=command.expected_revision)
    return ExceptionReceipt(candidate=updated, revision=row["revision"], event=event)


def terminate_exception(daily, candidate_id, *, state, reason, now):
    """Owned runtime expiry/invalidation; cannot create or undo a grant."""
    if state not in {"EXPIRED", "INVALIDATED"}:
        raise ValueError("invalid system termination")
    lock_authority(daily, candidate_id)
    repo = ExceptionRepository(daily)
    row = repo.get(candidate_id)
    if row is None:
        raise ExceptionAuthorityError("EXCEPTION_NOT_FOUND", status=404)
    candidate = ExceptionCandidate.model_validate(row["payload"])
    daily.lock_symbol(candidate.binding.symbol)
    daily.session.expire_all()
    row = repo.get(candidate_id)
    candidate = ExceptionCandidate.model_validate(row["payload"])
    if candidate.state not in {"PENDING", "APPROVED"}:
        return row
    if state == "EXPIRED" and now < candidate.binding.expires_at:
        raise ValueError("cannot expire before the original close")
    if now < candidate.created_at:
        raise ValueError("cannot backdate termination")
    updated, event = transition_candidate(
        candidate, to_state=state, command_id="system-" + daily_hash(
            "exception-system-command-v1", {"candidate_id": candidate_id, "state": state}),
        expected_revision=row["revision"], now=now, reason=reason)
    return repo.transition(updated, event, expected_revision=row["revision"])
