"""Immutable capital facts are independent of current budgets and research cash."""

import json
from typing import Annotated, ClassVar, Literal

from pydantic import BeforeValidator, Field, field_validator, model_validator

from trade_plan_monitor.backtest.exception_replay_input import (
    ExceptionReplayProgram,
    ExceptionResearchInput,
    FrozenExceptionEvent,
)
from trade_plan_monitor.backtest.models import Sha256Hex, StableIdentifier
from trade_plan_monitor.backtest.research_input import (
    ResearchTimestamp,
    ResearchValue,
    _confirmed,
    _shanghai,
)
from trade_plan_monitor.decision.p3_composition import CapitalMarketDecision
from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.daily_plan_models import PositiveWholeQty, Text
from trade_plan_monitor.domain.p2_policy_models import MAX_SAFE, SafeFen
from trade_plan_monitor.domain.plan_hash import daily_plan_content_sha256, plan_sha256
from trade_plan_monitor.state.p3_models import CapitalBookEvent


class OpeningLotReference(ResearchValue):
    kind: Literal["OPENING"] = "OPENING"
    lot_key: StableIdentifier


class BuySignalLotReference(ResearchValue):
    kind: Literal["BUY_SIGNAL"] = "BUY_SIGNAL"
    signal_id: Sha256Hex


class FrozenCapitalLot(ResearchValue):
    source_lot_id: StableIdentifier | None
    reference: Annotated[OpeningLotReference | BuySignalLotReference, Field(discriminator="kind")]
    bucket: Literal["CORE", "TACTICAL"]
    quantity: PositiveWholeQty
    retained_basis_fen: SafeFen

    @property
    def reference_key(self):
        return daily_hash("capital-lot-reference-v1", {
            "reference": self.reference.model_dump(mode="json"), "bucket": self.bucket})


class _FrozenCapitalContent(ResearchValue):
    schema_version: Literal["capital-opening-event-v1"] = "capital-opening-event-v1"
    source_event_id: StableIdentifier
    plan_hash: Sha256Hex
    symbol: str = Field(pattern=r"^[0-9]{6}\.(?:SH|SZ|BJ)$")
    provenance: Literal["RECORDED_LOCAL", "RESEARCH_SCENARIO"]
    observed_at: ResearchTimestamp
    received_at: ResearchTimestamp
    available_at: ResearchTimestamp
    order: int = Field(ge=0, le=10000)
    confirmed: Annotated[Literal[True], BeforeValidator(_confirmed)]
    source: Text
    excerpt: Text
    reason: Text
    lots: tuple[FrozenCapitalLot, ...] = Field(max_length=500)
    recorded_event: CapitalBookEvent | None

    _offset = field_validator("observed_at", "received_at", "available_at")(_shanghai)


class FrozenCapitalOpening(_FrozenCapitalContent):
    envelope_hash: Sha256Hex

    @classmethod
    def build(cls, **values):
        values.pop("envelope_hash", None)
        content = _FrozenCapitalContent.model_validate(values)
        raw = content.model_dump(mode="json")
        return cls.model_validate_json(json.dumps(raw | {
            "envelope_hash": daily_hash("capital-opening-event-v1", raw)}))

    @model_validator(mode="after")
    def bound(self):
        if self.envelope_hash != daily_hash(self.schema_version,
                self.model_dump(mode="json", exclude={"envelope_hash"})):
            raise ValueError("frozen capital envelope hash mismatch")
        if not self.observed_at <= self.received_at <= self.available_at:
            raise ValueError("frozen capital source time order is invalid")
        if (len({lot.reference_key for lot in self.lots}) != len(self.lots)
                or sum(lot.quantity for lot in self.lots) > MAX_SAFE
                or sum(lot.retained_basis_fen for lot in self.lots) > MAX_SAFE):
            raise ValueError("frozen capital lots require unique bounded whole inputs")
        event = self.recorded_event
        if self.provenance == "RESEARCH_SCENARIO":
            if event is not None:
                raise ValueError("scenario capital cannot masquerade as a recorded receipt")
        else:
            if event is None or (
                    event.kind not in {"OPENING", "RECONCILIATION"}
                    or event.event_hash != self.source_event_id or event.book.symbol != self.symbol
                    or event.received_at != self.received_at
                    or event.details.get("observed_at") != self.observed_at.isoformat()
                    or event.details.get("confirmed") is not True
                    or event.details.get("classification") != "HUMAN_CONFIRMED"
                    or any(event.details.get(name) != getattr(self, name)
                           for name in ("source", "excerpt", "reason"))):
                raise ValueError("recorded capital requires the exact reviewed opening receipt")
            keys = {(lot.source_lot_id, lot.bucket): (lot.quantity, lot.retained_basis_fen)
                    for lot in self.lots if lot.source_lot_id is not None}
            if len(keys) != len(self.lots) or keys != {
                    (lot.lot_id, lot.bucket): (lot.quantity, lot.retained_basis_fen)
                    for lot in event.book.lots}:
                raise ValueError("recorded capital lot costs differ from their source receipt")
        return self


class CapitalReplayProgram(ResearchValue):
    schema_version: Literal["capital-replay-program-v1"] = "capital-replay-program-v1"
    opening_events: tuple[FrozenCapitalOpening, ...] = Field(default=(), max_length=10000)

    @model_validator(mode="after")
    def ordered(self):
        events = self.opening_events
        keys = tuple((row.available_at, row.order) for row in events)
        if (keys != tuple(sorted(set(keys)))
                or len({row.source_event_id for row in events}) != len(events)
                or len({row.envelope_hash for row in events}) != len(events)):
            raise ValueError("capital source events require unique ordered identities")
        if len(self.model_dump_json().encode()) > 8*1024*1024:
            raise ValueError("capital program exceeds the existing8MiB input bound")
        return self

    @property
    def provenances(self):
        return tuple(sorted({row.provenance for row in self.opening_events}))

    def validate_scope(self, plans):
        by_hash = {plan_sha256(plan): plan for plan in plans if plan.schema_version == 9}
        for row in self.opening_events:
            plan = by_hash.get(row.plan_hash)
            if plan is None or plan.symbol != row.symbol or (
                    row.recorded_event is not None and row.recorded_event.details.get(
                        "content_hash") != daily_plan_content_sha256(plan)):
                raise ValueError("frozen capital plan/source binding mismatch")


class FrozenCapitalExceptionEvent(FrozenExceptionEvent):
    schema_version: Literal["capital-exception-event-v1"] = "capital-exception-event-v1"
    decision: CapitalMarketDecision


class CapitalExceptionReplayProgram(ExceptionReplayProgram):
    schema_version: Literal["capital-exception-program-v1"] = "capital-exception-program-v1"
    supported_plan_versions: ClassVar[tuple[int, ...]] = (7, 8, 9)
    exception_authorization_events: tuple[
        FrozenCapitalExceptionEvent | FrozenExceptionEvent, ...
    ] = Field(default=(), max_length=10000)

    def validate_scope(self, *, plans, started_at):
        super().validate_scope(plans=plans, started_at=started_at)
        by_hash = {plan_sha256(plan): plan for plan in plans}
        for row in self.exception_authorization_events:
            if (by_hash[row.plan_hash].schema_version == 9) != isinstance(
                    row, FrozenCapitalExceptionEvent):
                raise ValueError("capital exception source requires its exact schema9 proof")


class CapitalResearchInput(ExceptionResearchInput):
    schema_version: Literal["unified-research-input-v3"] = "unified-research-input-v3"
    program_type: ClassVar[type[ExceptionReplayProgram]] = CapitalExceptionReplayProgram
    exception_authorization_events: tuple[
        FrozenCapitalExceptionEvent | FrozenExceptionEvent, ...
    ] = Field(default=(), max_length=10000)
    capital_program: CapitalReplayProgram

    @model_validator(mode="after")
    def source_orders(self):
        budget = {(row.available_at, row.order) for row in self.capital_program.opening_events}
        other = {(row.at, row.order) for row in self.operations}
        other.update((row.event.received_at, row.order)
                     for row in self.exception_authorization_events)
        if budget & other:
            raise ValueError("capital, authorization and execution require distinct time/order")
        return self
