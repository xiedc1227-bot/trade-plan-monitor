"""Adversarial identity and structural checks for current-source change proofs.

These fixtures contain only local native declarations and no provider/database I/O.
The historical verifier remains untouched; current evidence must bind its own inputs.
"""

import json

import pytest
from tests.unit.test_plan_delta_wire import delta
from tests.unit.test_source_change_assurance import (
    _assemble,
    _assess,
    _case,
    _current_binding,
)

from trade_plan_monitor.ai.plan_delta_wire import CompactDeltaOutput
from trade_plan_monitor.ai.source_change_models import SourceChangeAssessment
from trade_plan_monitor.ai.source_derivation import SourceDerivationEvidence
from trade_plan_monitor.state.source_coverage_authority import extraction_inputs


def _result():
    source, output, materialized, inputs, context, base, parent, binding = _case()
    return _assess(source, output, materialized, inputs, context=context,
        base_review=base, verified_parent=parent, binding=binding)


def _rebuild(result, **changes):
    values = {name: getattr(result, name) for name in type(result).model_fields
              if name not in {"status", "evidence_hash"}}
    return SourceChangeAssessment.build(**(values | changes))


@pytest.mark.parametrize("field,value", [
    ("preparation_id", "other-preparation"),
    ("item_index", 0),
    ("candidate_hash", "c" * 64),
    ("source_revision", 2),
    ("attempt_id", "other-attempt"),
    ("independent", True),
])
def test_current_change_rejects_identity_inconsistent_with_actual_materialization(field, value):
    source, output, materialized, inputs, context, base, parent, binding = _case()
    binding = binding.model_copy(update={field: value})

    with pytest.raises(ValueError):
        _assess(source, output, materialized, inputs, context=context,
            base_review=base, verified_parent=parent, binding=binding)


def test_current_candidate_revision_is_in_the_change_evidence_identity():
    source, output, materialized, inputs, context, base, parent, binding = _case()
    original = _assess(source, output, materialized, inputs, context=context,
        base_review=base, verified_parent=parent, binding=binding)
    changed = _assess(source, output, materialized, inputs, context=context,
        base_review=base, verified_parent=parent,
        binding=binding.model_copy(update={"candidate_revision": 2}))

    assert original.evidence_hash != changed.evidence_hash


def test_global_changed_paths_cannot_outlive_their_operation():
    result = _result()
    assert result.changed_paths == ("position.max_qty",)
    operations = tuple(row for row in result.operations if row.action == "RETAIN")

    with pytest.raises(ValueError):
        _rebuild(result, operations=operations)


def test_changed_operation_cannot_silently_drop_its_actual_paths():
    result = _result()
    operations = tuple(row.model_copy(update={"changed_paths": ()})
                       if row.action == "MODIFY" else row for row in result.operations)

    with pytest.raises(ValueError):
        _rebuild(result, operations=operations)


def test_operation_paths_must_be_the_same_complete_global_diff():
    result = _result()

    with pytest.raises(ValueError):
        _rebuild(result, changed_paths=(*result.changed_paths, "position.core_target_qty"))


def test_actual_source_write_cannot_drop_all_of_its_obligation_links():
    result = _result()
    operations = tuple(row.model_copy(update={"obligation_ids": ()})
                       if row.action == "MODIFY" else row for row in result.operations)

    with pytest.raises(ValueError):
        _rebuild(result, operations=operations)


@pytest.mark.parametrize("field", ["inputs_hash", "derivation_hash"])
def test_verified_delta_requires_private_inputs_and_exact_derivation_identity(field):
    result = _result()
    assert result.raw_delta_verified is True

    with pytest.raises(ValueError):
        _rebuild(result, **{field: None})


def test_product_retention_cannot_claim_an_actual_current_write():
    result = _result()

    with pytest.raises(ValueError):
        operations = tuple(row.model_copy(update={"origin": "PRODUCT_RETENTION"})
                           if row.action == "MODIFY" else row for row in result.operations)
        _rebuild(result, operations=operations)


def test_parent_source_identity_cannot_be_reused_for_a_distinct_current_source():
    source, _, _, inputs, context, base, parent, _ = _case()
    source = source.model_copy(update={"source_id": parent.binding.source_id})
    patch = CompactDeltaOutput.model_validate_json(inputs.derivation.raw_json)
    source, output, materialized, inputs, context, base, parent, binding = _assemble(
        base, parent, source, patch, context)

    with pytest.raises(ValueError):
        _assess(source, output, materialized, inputs, context=context,
            base_review=base, verified_parent=parent, binding=binding)


def test_unreplayable_empty_draft_key_does_not_report_provider_full_plan_supplied():
    source, output, materialized, inputs, context, base, parent, _ = _case()
    original = inputs.derivation
    raw = json.loads(original.raw_json) | {"draft": {}}
    derivation = SourceDerivationEvidence.build(**(
        {name: getattr(original, name) for name in type(original).model_fields
         if name not in {"evidence_hash", "raw_hash", "context_hash"}}
        | {"raw_json": json.dumps(raw, ensure_ascii=False)}))
    extraction = materialized.extraction.model_copy(update={"source_derivation": derivation})
    materialized = materialized.model_copy(update={"extraction": extraction})
    inputs = extraction_inputs(materialized.extraction)
    binding = _current_binding(source, materialized, inputs, context, parent)

    result = _assess(source, output, materialized, inputs, context=context,
        base_review=base, verified_parent=parent, binding=binding)

    assert result.status == "BLOCKED"
    assert result.raw_delta_verified is False
    assert result.provider_full_draft_supplied is False


def test_empty_collection_cancellation_retains_an_inspectable_blocked_candidate():
    source, _, _, _, context, base, parent, _ = _case()
    text = "ordinary_rules = []"
    source = source.model_copy(update={"text": text})
    _, patch = delta(text, target="ordinary_rules", action="REVOKE",
                     rule_id=base.draft.ordinary_rules[0].rule_id)
    source, output, materialized, inputs, context, base, parent, binding = _assemble(
        base, parent, source, patch, context)
    assert materialized.review.draft.ordinary_rules == ()
    assert materialized.review.issues

    result = _assess(source, output, materialized, inputs, context=context,
        base_review=base, verified_parent=parent, binding=binding)

    assert result.status == "BLOCKED" and result.issues
    assert result.authority_granted is False
    assert result.content_hash


def test_source_retention_cannot_relabel_an_actual_write_as_unchanged():
    result = _result()

    with pytest.raises(ValueError):
        operations = tuple(row.model_copy(update={"action": "RETAIN"})
                           if row.action == "MODIFY" else row for row in result.operations)
        _rebuild(result, operations=operations)
