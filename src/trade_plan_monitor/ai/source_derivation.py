"""Private replayable input evidence, separate from provider-supplied draft fidelity."""

import json
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from trade_plan_monitor.ai.source_coverage_models import Hash
from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.domain.daily_plan_models import DailyValue
from trade_plan_monitor.domain.daily_scope import scope_hash

MAX_ITEM_BYTES = 1024 * 1024
MAX_EVIDENCE_BYTES = 8 * MAX_ITEM_BYTES
Document = Annotated[str, Field(min_length=1, max_length=MAX_ITEM_BYTES)]
Phase = Literal["DELTA_EXPANDED", "SOURCE_NORMALIZED", "MATERIALIZED"]


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate derivation JSON key")
        result[key] = value
    return result


def _invalid_number(value):
    raise ValueError("nonfinite derivation JSON")


def _object(document, *, canonical_required=False):
    if len(document.encode("utf-8")) > MAX_ITEM_BYTES:
        raise ValueError("derivation JSON byte limit exceeded")
    value = json.loads(document, object_pairs_hook=_unique, parse_constant=_invalid_number)
    if not isinstance(value, dict) or (canonical_required and canonical(value) != document):
        raise ValueError("derivation requires an exact canonical JSON object")
    return value


class DerivationStage(DailyValue):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    phase: Phase
    output_json: Document
    output_hash: Hash

    @field_validator("output_json")
    @classmethod
    def document(cls, value):
        _object(value, canonical_required=True)
        return value

    @model_validator(mode="after")
    def verify(self):
        if self.output_hash != scope_hash(self.output_json):
            raise ValueError("derivation stage output hash mismatch")
        return self

    @classmethod
    def build(cls, *, phase, output_json):
        return cls(phase=phase, output_json=output_json, output_hash=scope_hash(output_json))


class SourceDerivationEvidence(DailyValue):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    version: Literal["source-derivation-v1"] = "source-derivation-v1"
    materialization_version: Literal["predecessor-materialization-v1"] = (
        "predecessor-materialization-v1")
    kind: Literal["FULL_DRAFT", "PREDECESSOR_PATCH"]
    source_hash: Hash
    raw_json: Document
    raw_hash: Hash
    context_json: Document | None
    context_hash: Hash | None
    base_hash: Hash | None
    stages: tuple[DerivationStage, ...] = Field(min_length=1, max_length=8)
    authority_granted: Literal[False] = False
    evidence_hash: Hash

    @model_validator(mode="after")
    def verify(self):
        raw = _object(self.raw_json)
        if self.raw_hash != scope_hash(self.raw_json):
            raise ValueError("derivation raw input hash mismatch")
        if self.kind == "PREDECESSOR_PATCH":
            if (not isinstance(raw.get("schema_version"), str)
                    or not isinstance(raw.get("operations"), list)
                    or self.context_json is None or self.base_hash is None):
                raise ValueError("patch requires its original operations and predecessor context")
            context = _object(self.context_json, canonical_required=True)
            if (context.get("base_hash") != self.base_hash
                    or not isinstance(context.get("snapshot"), dict)
                    or self.context_hash != scope_hash(self.context_json)):
                raise ValueError("derivation predecessor binding mismatch")
            order = ("DELTA_EXPANDED", "SOURCE_NORMALIZED", "MATERIALIZED")
        else:
            if not isinstance(raw.get("draft"), dict) or any(value is not None for value in (
                self.context_json, self.context_hash, self.base_hash,
            )):
                raise ValueError("full draft requires its raw draft without predecessor context")
            order = ("SOURCE_NORMALIZED", "MATERIALIZED")
        if tuple(stage.phase for stage in self.stages) != order[:len(self.stages)]:
            raise ValueError("derivation stages must form a complete ordered prefix")
        payload = self.model_dump(mode="json", exclude={"evidence_hash"})
        if len(canonical(payload).encode("utf-8")) > MAX_EVIDENCE_BYTES:
            raise ValueError("derivation total byte limit exceeded")
        if self.evidence_hash != daily_hash(self.version, payload):
            raise ValueError("derivation evidence hash mismatch")
        return self

    @classmethod
    def build(cls, **values):
        values = values | dict(
            stages=tuple(DerivationStage.model_validate(row) for row in values["stages"]),
            raw_hash=scope_hash(values["raw_json"]),
            context_hash=(None if values.get("context_json") is None
                          else scope_hash(values["context_json"])),
        )
        unsigned = cls.model_construct(**values, evidence_hash="")
        return cls.model_validate(unsigned.model_dump(mode="json") | dict(
            evidence_hash=daily_hash(unsigned.version,
                unsigned.model_dump(mode="json", exclude={"evidence_hash"}))))
