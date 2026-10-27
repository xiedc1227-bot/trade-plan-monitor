"""Pure alias construction; sealed lineage and actual review authority are external.

An alias changes only the consumer placement of an existing aggregate. It does
not create an input, human operation, review receipt or SQL registration.
"""

from trade_plan_monitor.ai.source_assurance_binding import CandidateBinding
from trade_plan_monitor.ai.source_candidate_models import (
    PrefixAssuranceRef,
    SourceCandidateAssurance,
    source_prefix_hash,
)
from trade_plan_monitor.ai.source_reuse_models import AssuranceReuseRef


def build_reuse_alias(
    original: SourceCandidateAssurance,
    *,
    binding: CandidateBinding,
    prefix: tuple[PrefixAssuranceRef, ...] = (),
    lineage_hash: str,
    current_review_hash: str,
    manifest_hash: str,
) -> SourceCandidateAssurance:
    """Preserve leaf provenance while placing a proof in a consumer prefix.

    All hash arguments identify evidence that the caller must independently
    authenticate in the authoritative transaction. Shape validation here cannot
    authenticate a source, a review or a persisted lineage command.
    """
    original = SourceCandidateAssurance.model_validate_json(original.model_dump_json())
    binding = CandidateBinding.model_validate_json(binding.model_dump_json())
    prefix = tuple(PrefixAssuranceRef.model_validate_json(row.model_dump_json()) for row in prefix)
    placement = {"preparation_id", "item_index"}
    if binding.model_dump(exclude=placement) != original.binding.model_dump(exclude=placement):
        raise ValueError("reuse alias changes original binding coordinates")
    if len(prefix) != binding.item_index or any(
        row.binding.preparation_id != binding.preparation_id or row.binding.item_index != index
        for index, row in enumerate(prefix)
    ):
        raise ValueError("reuse alias requires the exact consumer prefix")
    direct = AssuranceReuseRef(
        original_owner_binding=original.binding,
        original_assurance_hash=original.evidence_hash,
        original_current_review_hash=current_review_hash,
        original_manifest_hash=manifest_hash,
        lineage_hash=lineage_hash,
    )
    reference = direct if original.reuse_ref is None else original.reuse_ref.model_copy(
        update={"lineage_hash": direct.lineage_hash})
    values = {name: getattr(original, name) for name in type(original).model_fields
              if name not in {"evidence_hash", "status"}} | {
        "binding": binding,
        "prefix": prefix,
        "prefix_hash": source_prefix_hash(prefix, binding),
        "parent_hash": (None if binding.independent or not prefix else prefix[-1].assurance_hash),
        "reuse_ref": reference,
    }
    return SourceCandidateAssurance.build(**values)
