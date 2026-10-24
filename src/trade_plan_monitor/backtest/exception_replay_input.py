"""Explicit frozen source events; none of these values is live execution authority."""

from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_core import to_jsonable_python

from trade_plan_monitor.backtest.models import Sha256Hex
from trade_plan_monitor.backtest.research_input import (
    ResearchSimulation,
    ResearchValue,
    UnifiedResearchInput,
)
from trade_plan_monitor.decision.market_exception_decision import MarketExceptionDecision
from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.plan_hash import daily_plan_content_sha256, plan_sha256
from trade_plan_monitor.state.market_exception_models import (
    ExceptionCandidate,
    ExceptionEvent,
    transition_candidate,
)


class FrozenExceptionEvent(ResearchValue):
    schema_version: Literal["frozen-exception-event-v1"] = "frozen-exception-event-v1"
    plan_hash: Sha256Hex
    provenance: Literal["RECORDED_LOCAL", "RESEARCH_SCENARIO"]
    order: int = Field(ge=0, le=10000)
    candidate: ExceptionCandidate
    decision: MarketExceptionDecision
    event: ExceptionEvent
    envelope_hash: Sha256Hex

    @field_validator("candidate", "decision", "event", mode="before")
    @classmethod
    def revalidate(cls, value, info):
        model = {
            "candidate": ExceptionCandidate,
            "decision": MarketExceptionDecision,
            "event": ExceptionEvent,
        }[info.field_name]
        return (
            model.model_validate_json(value.model_dump_json())
            if isinstance(value, model)
            else value
        )

    @classmethod
    def build(cls, **values):
        values.setdefault("schema_version", "frozen-exception-event-v1")
        values.pop("envelope_hash", None)
        return cls(
            **values,
            envelope_hash=daily_hash("frozen-exception-event-v1", to_jsonable_python(values)),
        )

    @model_validator(mode="after")
    def bound(self):
        c, e, d = self.candidate, self.event, self.decision
        b = c.binding
        if self.envelope_hash != daily_hash(
            self.schema_version, self.model_dump(mode="json", exclude={"envelope_hash"})
        ):
            raise ValueError("frozen exception envelope hash mismatch")
        if (
            e.candidate_id != c.candidate_id
            or e.binding_hash != c.binding_hash
            or e.from_state != c.state
            or d.evidence_hash != b.evidence_hash
            or d.consumed_hash != b.consumed_hash
            or d.content_hash != b.content_hash
            or d.rule_id != b.rule_id
            or d.decision_session != b.decision_session
            or d.evidence_cutoff != b.evidence_cutoff
            or d.calculation.route != b.route
            or d.selection.blocker is not None
            or d.quantity_rules is None
            or d.quantity_rules.content_hash != b.grid_hash
            or d.calculation.base_quantity != b.base_quantity
            or c.signal_seed is None
        ):
            raise ValueError("frozen exception source binding mismatch")
        if e.received_at < max(c.created_at, b.evidence_cutoff):
            raise ValueError("frozen exception event precedes admissible evidence")
        if e.to_state == "EXPIRED":
            if e.received_at < b.expires_at:
                raise ValueError("frozen exception expiry is premature")
        elif e.to_state != "INVALIDATED" and e.received_at >= b.expires_at:
            raise ValueError("frozen exception event is outside its original window")
        _, expected = transition_candidate(
            c,
            to_state=e.to_state,
            command_id=e.command_id,
            expected_revision=e.expected_revision,
            now=e.received_at,
            reason=e.reason,
            quantity=e.quantity if e.to_state == "APPROVED" else None,
            preview_hash=e.preview_hash,
            request_hash=e.request_hash,
        )
        if expected != e:
            raise ValueError("frozen exception event does not match source transition")
        return self


class ExceptionReplayProgram(ResearchValue):
    schema_version: Literal["exception-replay-program-v1"] = "exception-replay-program-v1"
    exception_authorization_events: tuple[FrozenExceptionEvent, ...] = Field(
        default=(), max_length=10000
    )
    operations: tuple[ResearchSimulation, ...] = Field(default=(), max_length=10000)

    @model_validator(mode="after")
    def ordered(self):
        events = self.exception_authorization_events
        keys = tuple((row.event.received_at, row.order) for row in events)
        if (
            keys != tuple(sorted(set(keys)))
            or len({r.event.event_id for r in events}) != len(events)
            or len({r.event.command_id for r in events}) != len(events)
        ):
            raise ValueError("frozen exception events require unique ordered identities")
        prior = {}
        for row in events:
            previous = prior.get(row.candidate.candidate_id)
            if previous is None:
                if row.event.from_state != "PENDING" or row.event.expected_revision != 1:
                    raise ValueError(
                        "frozen exception stream requires its original pending transition"
                    )
            elif (
                row.event.expected_revision != previous.event.expected_revision + 1
                or row.candidate.last_event_id != previous.event.event_id
                or row.event.from_state != previous.event.to_state
                or row.candidate.binding != previous.candidate.binding
                or row.plan_hash != previous.plan_hash
                or row.provenance != previous.provenance
                or row.candidate.frozen_quantity != previous.event.quantity
            ):
                raise ValueError("frozen exception stream has a broken transition chain")
            prior[row.candidate.candidate_id] = row
        op_keys = tuple((o.at, o.order) for o in self.operations)
        if op_keys != tuple(sorted(set(op_keys))) or len(
            {o.operation_id for o in self.operations}
        ) != len(self.operations):
            raise ValueError("exception execution operations require unique ordered identities")
        if any(o.risk_kind is not None for o in self.operations):
            raise ValueError("exception program executes only explicit rule occurrences")
        if set(keys) & set(op_keys):
            raise ValueError("authorization and execution require distinct same-time order")
        return self

    @property
    def provenances(self):
        return tuple(sorted({row.provenance for row in self.exception_authorization_events}))

    def validate_scope(self, *, plans, started_at):
        by_hash = {plan_sha256(plan): plan for plan in plans if plan.schema_version == 7}
        for row in self.exception_authorization_events:
            plan = by_hash.get(row.plan_hash)
            if (
                plan is None
                or plan.plan_id != row.candidate.binding.lineage
                or plan.symbol != row.candidate.binding.symbol
                or daily_plan_content_sha256(plan) != row.candidate.binding.content_hash
            ):
                raise ValueError("frozen exception plan identity mismatch")
            if row.event.received_at < started_at:
                raise ValueError("frozen exception event precedes research start")
        if any(o.at < started_at for o in self.operations):
            raise ValueError("exception execution operation precedes research start")


class ExceptionResearchInput(UnifiedResearchInput):
    schema_version: Literal["unified-research-input-v2"] = "unified-research-input-v2"
    exception_authorization_events: tuple[FrozenExceptionEvent, ...] = Field(
        default=(), max_length=10000
    )

    @model_validator(mode="after")
    def event_stream(self):
        ExceptionReplayProgram(
            exception_authorization_events=self.exception_authorization_events,
        )
        if {(e.event.received_at, e.order) for e in self.exception_authorization_events} & {
            (o.at, o.order) for o in self.operations
        }:
            raise ValueError("authorization and execution require distinct same-time order")
        if any(
            row.event.received_at < self.started_at for row in self.exception_authorization_events
        ):
            raise ValueError("frozen exception event precedes research start")
        return self
