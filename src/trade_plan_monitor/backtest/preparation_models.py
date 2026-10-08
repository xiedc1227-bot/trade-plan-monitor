"""Strict, private persistence values for preparing one supplied plan."""

import json
from datetime import date
from decimal import Decimal
from hashlib import sha256
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from trade_plan_monitor.ai.extraction import (
    MAX_EXTRACTION_JSON_DEPTH,
    MAX_EXTRACTION_JSON_NODES,
    MAX_EXTRACTION_OUTPUT_BYTES,
)
from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.loop_input import (
    MAX_EXTRACTION_ATTEMPTS,
    LoopSource,
    LoopSourceBatch,
)
from trade_plan_monitor.backtest.models import Sha256Hex, StableIdentifier
from trade_plan_monitor.backtest.plan_schedule import LoopTimestamp
from trade_plan_monitor.backtest.research_input import ResearchValue

PREPARATION_DOMAIN = "backtest-preparation-v1"
PREPARATION_SCHEMA_VERSION = 1


class PreparationSource(LoopSource):
    authored_at: LoopTimestamp | None = None
    available_at: LoopTimestamp | None = None
    effective_trade_date: date | None = None

    @model_validator(mode="after")
    def dates_coherent(self) -> Self:
        if self.authored_at and self.available_at and self.authored_at > self.available_at:
            raise ValueError("source authoring follows availability")
        return self

    @property
    def binding_hash(self) -> str:
        return _hash("preparation-source-v1", self)


class SinglePlanPreparationInput(LoopSourceBatch):
    preparation_id: StableIdentifier
    sources: tuple[PreparationSource, ...] = Field(min_length=1, max_length=1)


def _hash(domain, value):
    return sha256(canonical_json({"domain": domain, "value": value}).encode()).hexdigest()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("candidate JSON contains duplicate keys")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("candidate JSON contains a non-finite constant")


class PreparationCandidateInput(ResearchValue):
    """Bounded opaque output; ML-T08 owns its complete-plan semantic contract."""

    payload_json: str = Field(min_length=2, max_length=MAX_EXTRACTION_OUTPUT_BYTES)
    validation: Literal["VALID", "INVALID", "UNRESOLVED"]
    evidence_hash: Sha256Hex
    issues: tuple[Annotated[str, Field(min_length=1, max_length=512)], ...] = Field(
        default=(), max_length=128,
    )

    @field_validator("payload_json")
    @classmethod
    def bounded_json(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_EXTRACTION_OUTPUT_BYTES:
            raise ValueError("candidate JSON exceeds extraction output limit")
        try:
            parsed = json.loads(
                value, parse_float=Decimal, parse_constant=_reject_constant,
                object_pairs_hook=_unique_object,
            )
        except (RecursionError, json.JSONDecodeError) as error:
            raise ValueError("candidate JSON is invalid") from error
        if not isinstance(parsed, dict):
            raise ValueError("candidate JSON must be an object")
        pending, nodes = [(parsed, 1)], 0
        while pending:
            item, depth = pending.pop()
            nodes += 1
            if nodes > MAX_EXTRACTION_JSON_NODES or depth > MAX_EXTRACTION_JSON_DEPTH:
                raise ValueError("candidate JSON exceeds extraction structure limits")
            if isinstance(item, dict):
                children = item.values()
            elif isinstance(item, list):
                children = item
            else:
                children = ()
            pending.extend((child, depth + 1) for child in children)
        encoded = canonical_json(parsed)
        if len(encoded.encode("utf-8")) > MAX_EXTRACTION_OUTPUT_BYTES:
            raise ValueError("canonical candidate exceeds extraction output limit")
        return encoded


class PreparationCandidate(PreparationCandidateInput):
    source_revision: int = Field(ge=1)
    source_hash: Sha256Hex

    @property
    def candidate_hash(self) -> str:
        return _hash("preparation-candidate-v1", self)


class PreparationAttempt(ResearchValue):
    attempt_id: StableIdentifier
    source_revision: int = Field(ge=1)
    source_hash: Sha256Hex
    status: Literal["RUNNING", "CANCEL_REQUESTED", "SUCCEEDED", "FAILED", "CANCELLED"]
    started_at: LoopTimestamp
    finished_at: LoopTimestamp | None = None
    error_code: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{0,127}$")] | None = None
    retryable: bool = False

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if (self.status in {"RUNNING", "CANCEL_REQUESTED"}) != (self.finished_at is None):
            raise ValueError("attempt completion time contradicts status")
        if self.finished_at is not None and self.finished_at < self.started_at:
            raise ValueError("attempt finished before it started")
        if (self.status == "FAILED") != (self.error_code is not None):
            raise ValueError("attempt error contradicts status")
        if self.retryable and self.status != "FAILED":
            raise ValueError("only a classified failure can be retryable")
        return self


class PreparationReview(ResearchValue):
    source_revision: int = Field(ge=1)
    candidate_revision: int = Field(ge=1)
    candidate_hash: Sha256Hex
    evidence_hash: Sha256Hex
    confirmed: Literal[True]
    reviewed_at: LoopTimestamp

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if type(value) is not bool or value is not True:
            raise ValueError("review requires explicit confirmed true")
        return value


class PreparationRecord(ResearchValue):
    schema_version: Literal["backtest-preparation-v1"] = PREPARATION_DOMAIN
    preparation_id: StableIdentifier
    revision: int = Field(ge=1)
    source: PreparationSource
    source_revision: int = Field(ge=1)
    status: Literal[
        "DRAFT", "EXTRACTING", "CANCEL_REQUESTED", "CANDIDATE", "REVIEWED", "FAILED", "CANCELLED"
    ] = "DRAFT"
    source_edit_pending: bool = False
    attempts: tuple[PreparationAttempt, ...] = Field(default=(), max_length=MAX_EXTRACTION_ATTEMPTS)
    candidate_revision: int = Field(default=0, ge=0)
    candidate: PreparationCandidate | None = None
    review_revision: int = Field(default=0, ge=0)
    review: PreparationReview | None = None
    created_at: LoopTimestamp
    updated_at: LoopTimestamp

    @model_validator(mode="after")
    def bindings_coherent(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("preparation update precedes creation")
        if len({attempt.attempt_id for attempt in self.attempts}) != len(self.attempts):
            raise ValueError("attempt identities must be unique")
        for attempt in self.attempts:
            superseded_pending = (
                attempt.status == "CANCEL_REQUESTED" and self.status == "CANCEL_REQUESTED"
                and attempt.source_revision < self.source_revision
            )
            if not superseded_pending and (attempt.source_revision, attempt.source_hash) != (
                self.source_revision, self.source.binding_hash,
            ):
                raise ValueError("attempt is bound to another source")
            if attempt.started_at > self.updated_at or (
                attempt.finished_at is not None and attempt.finished_at > self.updated_at
            ):
                raise ValueError("attempt is bound to a future time")
        if self.status == "DRAFT" and self.attempts:
            raise ValueError("draft cannot contain extraction attempts")
        if self.status == "FAILED" and (
            not self.attempts or self.attempts[-1].status != "FAILED"
        ):
            raise ValueError("failed preparation requires its classified attempt outcome")
        running = [attempt for attempt in self.attempts if attempt.finished_at is None]
        if bool(running) != (self.status in {"EXTRACTING", "CANCEL_REQUESTED"}) or len(running) > 1:
            raise ValueError("running attempt contradicts preparation status")
        if running and running[0] != self.attempts[-1]:
            raise ValueError("only the latest attempt can be running")
        if running and running[0].status != (
            "RUNNING" if self.status == "EXTRACTING" else "CANCEL_REQUESTED"
        ):
            raise ValueError("pending cancellation contradicts preparation status")
        if self.source_edit_pending and (
            self.status != "CANCEL_REQUESTED"
            or not running or running[0].source_revision >= self.source_revision
        ):
            raise ValueError("pending source edit requires a superseded unresolved attempt")
        if (self.candidate is not None) != (self.status in {"CANDIDATE", "REVIEWED"}):
            raise ValueError("candidate contradicts preparation status")
        if self.candidate is not None and (
            self.candidate.source_revision != self.source_revision
            or self.candidate.source_hash != self.source.binding_hash
            or self.candidate_revision == 0
            or not self.attempts or self.attempts[-1].status != "SUCCEEDED"
        ):
            raise ValueError("candidate is not bound to the completed source attempt")
        if (self.review is not None) != (self.status == "REVIEWED"):
            raise ValueError("review contradicts preparation status")
        if self.review is not None and (
            self.review_revision == 0 or self.candidate.validation != "VALID"
            or self.review.source_revision != self.source_revision
            or self.review.candidate_revision != self.candidate_revision
            or self.review.candidate_hash != self.candidate.candidate_hash
            or self.review.evidence_hash != self.candidate.evidence_hash
            or self.review.reviewed_at > self.updated_at
        ):
            raise ValueError("review is not bound to the exact valid candidate")
        return self
