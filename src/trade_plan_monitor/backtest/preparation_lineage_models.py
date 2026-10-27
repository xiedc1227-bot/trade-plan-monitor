"""Explicit reuse placements; self-consistency never authenticates a parent review."""

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, TypeAdapter, field_validator, model_validator

from trade_plan_monitor.ai.source_assurance_binding import CandidateBinding
from trade_plan_monitor.ai.source_coverage_models import MAX_PROOF_BYTES, Hash
from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.preparation_models import (
    PreparedPlanCompositionInput,
    SingleSourcePreparationInput,
)
from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.domain.daily_plan_models import DailyValue, Identifier
from trade_plan_monitor.market_data.models import ShanghaiDatetime

Revision = Annotated[int, Field(strict=True, ge=1, le=9_007_199_254_740_991)]
ItemIndex = Annotated[int, Field(strict=True, ge=0, le=511)]
_IDENTIFIER = TypeAdapter(Identifier)
_CREATION_REVISION = TypeAdapter(Annotated[int, Field(strict=True, ge=1, le=1)])
_SELECTION_ORDER = TypeAdapter(tuple[ItemIndex, ...])


def lineage_key(preparation_id):
    """One immutable creation slot, independent of command, clock and parent content."""
    if type(preparation_id) is not str:
        raise ValueError("lineage preparation identity must be a string")
    return daily_hash("preparation-lineage-key-v1", dict(
        preparation_id=_IDENTIFIER.validate_python(preparation_id)))


class LineagePlacement(DailyValue):
    consumer_item_index: ItemIndex
    owner_binding: CandidateBinding
    owner_revision: Revision
    owner_review_revision: Revision
    owner_review_hash: Hash
    owner_manifest_hash: Hash
    owner_proof_hash: Hash
    leaf_owner_binding: CandidateBinding
    leaf_assurance_hash: Hash
    leaf_current_review_hash: Hash
    leaf_manifest_hash: Hash

    @model_validator(mode="after")
    def exact_source(self):
        excluded = {"preparation_id", "item_index"}
        if self.owner_binding.model_dump(exclude=excluded) != (
            self.leaf_owner_binding.model_dump(exclude=excluded)
        ):
            raise ValueError("lineage leaf differs from the exact copied source/candidate")
        if self.owner_binding == self.leaf_owner_binding and (
            self.owner_proof_hash, self.owner_review_hash, self.owner_manifest_hash
        ) != (self.leaf_assurance_hash, self.leaf_current_review_hash, self.leaf_manifest_hash):
            raise ValueError("direct original lineage owner has contradictory evidence hashes")
        return self


class PreparationLineage(DailyValue):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    version: Literal["preparation-lineage-v1"] = "preparation-lineage-v1"
    kind: Literal["LINEAGE"] = "LINEAGE"
    operation: Literal["CREATE_SINGLE", "COMPOSE_REVIEWED"]
    preparation_id: Identifier
    command_id: Identifier = Field(strict=True)
    command_request_hash: Hash = Field(strict=True)
    command_json: str = Field(strict=True, min_length=2, max_length=1024 * 1024)
    created_revision: int = Field(default=1, strict=True, ge=1, le=1)
    creation_response_hash: Hash = Field(strict=True)
    selection_order: tuple[ItemIndex, ...] = Field(min_length=1, max_length=256)
    placements: tuple[LineagePlacement, ...] = Field(min_length=1, max_length=256)
    created_at: ShanghaiDatetime
    authority_granted: Literal[False] = False
    evidence_key: Hash
    evidence_hash: Hash

    @field_validator("command_json")
    @classmethod
    def command_bytes(cls, value):
        if len(value.encode("utf-8")) > 1024 * 1024:
            raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")
        return value

    def command(self):
        model = (SingleSourcePreparationInput if self.operation == "CREATE_SINGLE"
                 else PreparedPlanCompositionInput)
        return model.model_validate_json(self.command_json)

    def intent(self):
        return self.model_dump(mode="json", exclude={"created_at", "evidence_hash"})

    @model_validator(mode="after")
    def verify(self):
        if self.evidence_key != lineage_key(self.preparation_id):
            raise ValueError("lineage identity differs")
        command = self.command()
        if (command.preparation_id != self.preparation_id
                or self.command_json != canonical_json(command)):
            raise ValueError("lineage command differs from its exact canonical typed input")
        if tuple(row.consumer_item_index for row in self.placements) != tuple(
            range(len(self.placements))
        ) or any(self.preparation_id in {
            row.owner_binding.preparation_id, row.leaf_owner_binding.preparation_id}
                 for row in self.placements):
            raise ValueError("lineage consumer positions differ or directly refer to themselves")
        if self.operation == "CREATE_SINGLE":
            reference = command.reviewed_base
            if reference is None or self.selection_order != (0,) or len(self.placements) >= 256:
                raise ValueError("single lineage requires one explicit parent and a new tail")
            if any((row.owner_binding.preparation_id, row.owner_manifest_hash,
                    row.owner_binding.item_index) != (
                    reference.preparation_id, reference.manifest_hash, index)
                    for index, row in enumerate(self.placements)):
                raise ValueError("single lineage differs from its exact complete parent prefix")
        else:
            if sorted(self.selection_order) != list(range(len(command.plans))) or (
                len(self.placements) != len(command.plans)
            ):
                raise ValueError("composition lineage selection is not a complete permutation")
            if any((row.owner_binding.preparation_id, row.owner_manifest_hash) != (
                    command.plans[selected].preparation_id, command.plans[selected].manifest_hash)
                    for row, selected in zip(self.placements, self.selection_order, strict=True)):
                raise ValueError("composition placement differs from the original selected owner")
        payload = self.model_dump(mode="json", exclude={"evidence_hash"})
        if len(canonical(self.model_dump(mode="json")).encode("utf-8")) > MAX_PROOF_BYTES:
            raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")
        if self.evidence_hash != daily_hash(self.version, payload):
            raise ValueError("lineage evidence hash differs")
        return self

    @classmethod
    def build(cls, **values):
        # Keep strict admission types intact before JSON serialization can coerce bytes.
        for name in ("preparation_id", "command_id", "command_request_hash", "command_json",
                     "creation_response_hash"):
            if type(values.get(name)) is not str:
                raise ValueError("lineage string fields require exact strings")
        _CREATION_REVISION.validate_python(values.get("created_revision", 1))
        _SELECTION_ORDER.validate_python(values.get("selection_order"))
        unsigned = cls.model_construct(**values, evidence_key=lineage_key(values["preparation_id"]),
                                       evidence_hash="")
        payload = unsigned.model_dump(mode="json", exclude={"evidence_hash"})
        return cls.model_validate(payload | {
            "evidence_hash": daily_hash(unsigned.version, payload)})
