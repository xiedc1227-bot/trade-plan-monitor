"""Translate frozen evidence into private commands; never import a live grant."""

from typing import Literal

from pydantic import Field, model_validator

from trade_plan_monitor.backtest.exception_replay_input import FrozenExceptionEvent
from trade_plan_monitor.backtest.models import Sha256Hex
from trade_plan_monitor.backtest.research_input import ResearchTimestamp, ResearchValue
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.runtime.market_exceptions import (
    apply_exception_decision,
    current_exception_authority,
)
from trade_plan_monitor.state.market_exception_models import ExceptionCandidate
from trade_plan_monitor.state.market_exception_repository import ExceptionRepository
from trade_plan_monitor.state.market_exception_service import (
    ExceptionAuthorityError,
    ExceptionDecisionCommand,
    ExceptionPreviewCommand,
    ExceptionRevocationCommand,
    preview_exception,
    revoke_exception,
)


class ExceptionReplayOutcome(ResearchValue):
    schema_version: Literal["exception-replay-outcome-v1"] = "exception-replay-outcome-v1"
    envelope_hash: Sha256Hex
    source_event_id: Sha256Hex
    provenance: Literal["RECORDED_LOCAL", "RESEARCH_SCENARIO"]
    at: ResearchTimestamp
    status: Literal["APPLIED", "BLOCKED", "VERIFIED"]
    blockers: tuple[str, ...] = Field(max_length=10)
    candidate_id: Sha256Hex
    private_event_id: Sha256Hex | None = None

    @model_validator(mode="after")
    def consistent(self):
        if (self.status == "BLOCKED") != bool(self.blockers) or (
            self.status == "BLOCKED"
        ) != (self.private_event_id is None):
            raise ValueError("exception outcome status and private receipt disagree")
        return self


class ExceptionExecutionRequestOutcome(ResearchValue):
    operation_id: str
    at: ResearchTimestamp
    status: Literal["REQUESTED", "BLOCKED"]
    blockers: tuple[str, ...] = Field(max_length=10)
    intent_id: Sha256Hex | None = None

    @model_validator(mode="after")
    def consistent(self):
        if (self.status == "BLOCKED") != bool(self.blockers) or (
            self.status == "BLOCKED"
        ) != (self.intent_id is None):
            raise ValueError("exception request status and intent disagree")
        return self


def validate_exception_outcomes(events, outcomes, cutoff):
    expected = tuple((e.envelope_hash, e.event.event_id, e.provenance,
                      e.event.received_at, e.candidate.candidate_id)
                     for e in events if e.event.received_at <= cutoff)
    actual = tuple((o.envelope_hash, o.source_event_id, o.provenance, o.at, o.candidate_id)
                   for o in outcomes or ())
    if expected != actual:
        raise ValueError("exception outcomes do not match frozen source events")


def apply_frozen_exception(session, frozen):
    """The caller has already evaluated only evidence available at this clock tick."""
    frozen = FrozenExceptionEvent.model_validate_json(frozen.model_dump_json())
    source, event = frozen.candidate, frozen.event
    status, blockers, private_event = "BLOCKED", (), None
    try:
        if session.now != event.received_at:
            raise ExceptionAuthorityError("EXCEPTION_REPLAY_RECEIPT_TIME_MISMATCH")
        if frozen.plan_hash != plan_sha256(session.plan):
            raise ExceptionAuthorityError("EXCEPTION_REPLAY_PLAN_MISMATCH")
        with session.work() as work:
            row = ExceptionRepository(work.daily).get(source.candidate_id)
            if row is None:
                raise ExceptionAuthorityError("EXCEPTION_REPLAY_CANDIDATE_MISSING")
            candidate = ExceptionCandidate.model_validate(row["payload"])
            # Private review/version IDs are intentionally different. Every economic
            # binding, original window and consumed fact must still match exactly.
            excluded = {"plan_version_id", "review_id", "activation_revision", "evidence_hash"}
            if candidate.binding.model_dump(exclude=excluded) != source.binding.model_dump(
                exclude=excluded
            ):
                raise ExceptionAuthorityError("EXCEPTION_REPLAY_BINDING_MISMATCH")
            if event.to_state in {"CONSUMED", "INVALIDATED", "EXPIRED"}:
                # A recorded fill/termination cannot manufacture an execution or a
                # changed market fact. It only asserts the result of shared services.
                if candidate.state != event.to_state:
                    raise ExceptionAuthorityError("EXCEPTION_REPLAY_TERMINAL_NOT_REPRODUCED")
                status = "VERIFIED"
                private_event = candidate.last_event_id
            else:
                if (
                    candidate.state != event.from_state
                    or row["revision"] != event.expected_revision
                ):
                    raise ExceptionAuthorityError("EXCEPTION_REPLAY_STATE_MISMATCH")
                command_id = "frozen-" + frozen.envelope_hash
                if event.to_state == "REVOKED":
                    if candidate.frozen_quantity != event.quantity:
                        raise ExceptionAuthorityError("EXCEPTION_REPLAY_QUANTITY_MISMATCH")
                    receipt = revoke_exception(
                        work.daily,
                        ExceptionRevocationCommand(
                            command_id=command_id,
                            approval_id=candidate.approval_id,
                            expected_revision=row["revision"],
                            reason=event.reason,
                        ),
                        now=session.now,
                    )
                else:
                    shown = None
                    if event.to_state == "APPROVED":
                        shown = preview_exception(
                            work.daily,
                            ExceptionPreviewCommand(
                                candidate_id=candidate.candidate_id,
                                expected_revision=row["revision"],
                                proposed_quantity=(
                                    event.quantity
                                    if source.binding.route == "BROKEN_STRONG"
                                    else None
                                ),
                            ),
                            current=lambda c: current_exception_authority(work, c, session.now),
                            now=session.now,
                        )
                        if shown.quantity != event.quantity:
                            raise ExceptionAuthorityError("EXCEPTION_REPLAY_QUANTITY_MISMATCH")
                    receipt = apply_exception_decision(
                        work,
                        ExceptionDecisionCommand(
                            command_id=command_id,
                            candidate_id=candidate.candidate_id,
                            expected_revision=row["revision"],
                            reason=event.reason,
                            decision="APPROVE" if shown is not None else "REJECT",
                            preview_id=None if shown is None else shown.preview_id,
                            preview_hash=None if shown is None else shown.preview_hash,
                        ),
                        now=session.now,
                    )
                private_event = receipt.event.event_id
                status = "APPLIED"
            work.commit()
    except ExceptionAuthorityError as error:
        blockers = (error.reason,)
    return ExceptionReplayOutcome(
        envelope_hash=frozen.envelope_hash,
        source_event_id=event.event_id,
        provenance=frozen.provenance,
        at=session.now,
        status=status,
        blockers=blockers,
        candidate_id=source.candidate_id,
        private_event_id=private_event,
    )
