"""Private derivation evidence preserves wire origins without inventing a raw draft."""

import json

import pytest
from tests.unit.test_plan_delta_wire import delta
from tests.unit.test_plan_update_bindings import prior_review
from tests.unit.test_source_coverage_baseline import _baseline

from trade_plan_monitor.ai.plan_delta_wire import expand_delta_output
from trade_plan_monitor.ai.plan_update_extraction import PlanUpdateContext
from trade_plan_monitor.ai.preparation_wire import expand_compact_output
from trade_plan_monitor.ai.update_review import context_from_review
from trade_plan_monitor.backtest.plan_updates import materialize_plan_update
from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.domain.daily_scope import scope_hash

_MIB = 1024 * 1024


def _models():
    from trade_plan_monitor.ai.source_derivation import DerivationStage, SourceDerivationEvidence

    return DerivationStage, SourceDerivationEvidence


@pytest.fixture(scope="module")
def patch_images():
    source, patch = delta("总持仓最多500股。", values={"max_qty": 500})
    context = context_from_review(prior_review(), "b" * 64)
    expanded = expand_delta_output(patch, context)
    normalized = expand_compact_output(expanded, source, context=context)
    materialized = materialize_plan_update(context.snapshot, normalized)
    raw = json.dumps(patch.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
    assert "draft" not in json.loads(raw)
    return {
        "source": source.text, "raw_json": raw, "context_json": canonical(
            context.model_dump(mode="json")), "base_hash": context.base_hash,
        "outputs": tuple(canonical(value.model_dump(mode="json"))
                         for value in (expanded, normalized, materialized)),
    }


def _patch(patch_images, *, phases=None, **updates):
    Stage, Evidence = _models()
    phases = phases if phases is not None else (
        "DELTA_EXPANDED", "SOURCE_NORMALIZED", "MATERIALIZED",
    )
    values = {
        "kind": "PREDECESSOR_PATCH", "source_hash": scope_hash(patch_images["source"]),
        "raw_json": patch_images["raw_json"], "context_json": patch_images["context_json"],
        "base_hash": patch_images["base_hash"],
        "stages": tuple(Stage.build(phase=phase, output_json=output)
                        for phase, output in zip(phases, patch_images["outputs"], strict=False)),
    }
    return Evidence.build(**(values | updates))


def _full(**updates):
    Stage, Evidence = _models()
    draft, source, mapping = _baseline()
    raw = json.dumps({
        "draft": draft.model_dump(mode="json"),
        "clauses": [clause.model_dump(mode="json") for clause in mapping.clauses],
        "bindings": [binding.model_dump(mode="json") for binding in mapping.bindings],
        "assumptions": [], "warnings": [],
    }, ensure_ascii=False, indent=2) + "\n"
    values = {
        "kind": "FULL_DRAFT", "source_hash": scope_hash(source), "raw_json": raw,
        "context_json": None, "base_hash": None,
        "stages": (Stage.build(phase="SOURCE_NORMALIZED", output_json=canonical(
            json.loads(raw))),),
    }
    return Evidence.build(**(values | updates))


def _rehash(value):
    value["evidence_hash"] = daily_hash("source-derivation-v1", {
        key: item for key, item in value.items() if key != "evidence_hash"
    })
    return value


def test_full_draft_evidence_preserves_actual_raw_bytes_and_derives_all_hashes():
    _, Evidence = _models()
    evidence = _full()
    assert evidence.version == "source-derivation-v1"
    assert evidence.materialization_version == "predecessor-materialization-v1"
    assert evidence.kind == "FULL_DRAFT"
    assert evidence.raw_json != canonical(json.loads(evidence.raw_json))
    assert evidence.raw_json.endswith("\n")
    assert evidence.raw_hash == scope_hash(evidence.raw_json)
    assert evidence.context_json is evidence.context_hash is evidence.base_hash is None
    assert evidence.authority_granted is False
    assert evidence.evidence_hash == daily_hash(evidence.version, evidence.model_dump(
        mode="json", exclude={"evidence_hash"}))
    assert Evidence.model_validate_json(evidence.model_dump_json()) == evidence


def test_patch_evidence_binds_raw_operations_and_the_exact_context_without_claiming_a_raw_draft(
    patch_images,
):
    _, Evidence = _models()
    evidence = _patch(patch_images)
    assert evidence.kind == "PREDECESSOR_PATCH"
    assert evidence.raw_json == patch_images["raw_json"]
    assert "draft" not in json.loads(evidence.raw_json)
    assert evidence.raw_hash == scope_hash(patch_images["raw_json"])
    assert evidence.context_json == patch_images["context_json"]
    assert evidence.context_hash == scope_hash(patch_images["context_json"])
    assert evidence.base_hash == json.loads(evidence.context_json)["base_hash"]
    assert [stage.phase for stage in evidence.stages] == [
        "DELTA_EXPANDED", "SOURCE_NORMALIZED", "MATERIALIZED",
    ]
    assert [stage.output_hash for stage in evidence.stages] == [
        scope_hash(output) for output in patch_images["outputs"]
    ]
    assert evidence.authority_granted is False
    assert Evidence.model_validate_json(evidence.model_dump_json()) == evidence


def test_raw_whitespace_changes_evidence_even_when_json_meaning_is_unchanged(patch_images):
    original = _patch(patch_images)
    compact = _patch(patch_images, raw_json=canonical(json.loads(original.raw_json)))
    assert json.loads(original.raw_json) == json.loads(compact.raw_json)
    assert original.raw_hash != compact.raw_hash
    assert original.evidence_hash != compact.evidence_hash


@pytest.mark.parametrize("count", [1, 2, 3])
def test_patch_can_record_a_complete_valid_prefix_without_claiming_later_stages(
    patch_images, count,
):
    phases = ("DELTA_EXPANDED", "SOURCE_NORMALIZED", "MATERIALIZED")[:count]
    evidence = _patch(patch_images, phases=phases)
    assert tuple(stage.phase for stage in evidence.stages) == phases
    assert evidence.authority_granted is False


def test_full_draft_allows_its_two_registered_stages():
    Stage, _ = _models()
    initial = _full()
    evidence = _full(stages=(*initial.stages, Stage.build(
        phase="MATERIALIZED", output_json=initial.stages[0].output_json)))
    assert [stage.phase for stage in evidence.stages] == ["SOURCE_NORMALIZED", "MATERIALIZED"]


@pytest.mark.parametrize("phases", [
    (), ("SOURCE_NORMALIZED",), ("MATERIALIZED",),
    ("DELTA_EXPANDED", "MATERIALIZED"),
    ("DELTA_EXPANDED", "DELTA_EXPANDED"),
    ("SOURCE_NORMALIZED", "DELTA_EXPANDED"),
    ("DELTA_EXPANDED", "MATERIALIZED", "SOURCE_NORMALIZED"),
])
def test_patch_rejects_missing_skipped_repeated_or_reordered_stages(patch_images, phases):
    with pytest.raises(ValueError):
        _patch(patch_images, phases=phases)


@pytest.mark.parametrize("phases", [(), ("DELTA_EXPANDED",), ("MATERIALIZED",)])
def test_full_draft_cannot_claim_patch_or_missing_normalization_stages(phases):
    Stage, _ = _models()
    initial = _full()
    stages = tuple(Stage.build(phase=phase, output_json=initial.stages[0].output_json)
                   for phase in phases)
    with pytest.raises(ValueError):
        _full(stages=stages)


@pytest.mark.parametrize("replacement", [None, {}, [], {"operations": []},
    {"schema_version": "monitor-loop-delta-wire-v1"},
    {"schema_version": "monitor-loop-delta-wire-v1", "operations": {}},
])
def test_patch_requires_an_original_wire_schema_and_operations_array(patch_images, replacement):
    with pytest.raises(ValueError):
        _patch(patch_images, raw_json=canonical(replacement))


def test_an_explicit_empty_operations_array_is_an_unchanged_patch_not_a_full_draft(patch_images):
    raw = json.loads(patch_images["raw_json"])
    raw["operations"] = []
    evidence = _patch(patch_images, raw_json=canonical(raw), phases=("DELTA_EXPANDED",))
    assert json.loads(evidence.raw_json)["operations"] == []
    assert evidence.kind == "PREDECESSOR_PATCH" and evidence.authority_granted is False


@pytest.mark.parametrize("replacement", [{}, {"draft": None}, {"draft": []}, {"operations": []}])
def test_full_draft_requires_the_actual_provider_draft_object(replacement):
    with pytest.raises(ValueError):
        _full(raw_json=canonical(replacement))


@pytest.mark.parametrize("updates", [
    {"context_json": None}, {"base_hash": None}, {"base_hash": "f" * 64},
    {"context_json": "{}"},
])
def test_patch_requires_a_structural_context_and_matching_base_hash(patch_images, updates):
    with pytest.raises(ValueError):
        _patch(patch_images, **updates)


def test_context_cannot_drop_the_predecessor_snapshot(patch_images):
    context = json.loads(patch_images["context_json"])
    context.pop("snapshot")
    with pytest.raises(ValueError):
        _patch(patch_images, context_json=canonical(context))


def test_full_draft_cannot_silently_acquire_predecessor_context(patch_images):
    with pytest.raises(ValueError):
        _full(context_json=patch_images["context_json"], base_hash=patch_images["base_hash"])


@pytest.mark.parametrize("field", [
    "source_hash", "raw_hash", "context_hash", "base_hash", "evidence_hash",
])
def test_direct_hash_tampering_is_rejected(patch_images, field):
    _, Evidence = _models()
    evidence = _patch(patch_images)
    forged = evidence.model_dump(mode="json")
    forged[field] = "f" * 64
    with pytest.raises(ValueError):
        Evidence.model_validate(forged)


@pytest.mark.parametrize("field", ["raw_json", "context_json"])
def test_rehashing_the_envelope_cannot_hide_a_forged_raw_or_context_hash(patch_images, field):
    _, Evidence = _models()
    evidence = _patch(patch_images)
    forged = evidence.model_dump(mode="json")
    data = json.loads(forged[field])
    if field == "raw_json":
        data["operations"][0]["values"]["max_qty"] += 100
    else:
        data["snapshot"]["version"] += 1
    forged[field] = canonical(data)
    with pytest.raises(ValueError):
        Evidence.model_validate(_rehash(forged))


def test_rehashing_the_envelope_cannot_hide_a_forged_stage_output_hash(patch_images):
    _, Evidence = _models()
    forged = _patch(patch_images).model_dump(mode="json")
    forged["stages"][0]["output_json"] = canonical({"draft": {"version": 999}})
    with pytest.raises(ValueError):
        Evidence.model_validate(_rehash(forged))


def test_stage_self_validation_rechecks_its_own_exact_output_hash(patch_images):
    Stage, _ = _models()
    stage = Stage.build(phase="DELTA_EXPANDED", output_json=patch_images["outputs"][0])
    assert stage.output_hash == scope_hash(stage.output_json)
    forged = stage.model_dump(mode="json") | {"output_hash": "f" * 64}
    with pytest.raises(ValueError):
        Stage.model_validate(forged)


@pytest.mark.parametrize("invalid", [' {"draft":{}}', '{"b": 2, "a": 1}', '[]', 'null'])
def test_stage_requires_a_canonical_complete_json_object(invalid):
    Stage, _ = _models()
    with pytest.raises(ValueError):
        Stage.build(phase="SOURCE_NORMALIZED", output_json=invalid)


def test_context_requires_canonical_bytes_without_reformatting_them(patch_images):
    spaced = json.dumps(json.loads(patch_images["context_json"]), indent=2)
    assert spaced != patch_images["context_json"]
    with pytest.raises(ValueError):
        _patch(patch_images, context_json=spaced)


@pytest.mark.parametrize("raw", ['{"draft":{},"draft":{}}', '{"draft":{"x":NaN}}', '{'])
def test_raw_json_rejects_duplicate_keys_nonfinite_numbers_and_invalid_syntax(raw):
    with pytest.raises(ValueError):
        _full(raw_json=raw)


def test_raw_limit_counts_exact_utf8_bytes_and_preserves_the_legal_boundary():
    original = _full()
    compact = canonical(json.loads(original.raw_json))
    raw = compact + " " * (_MIB - len(compact.encode("utf-8")))
    evidence = _full(raw_json=raw)
    assert len(evidence.raw_json.encode("utf-8")) == _MIB
    assert evidence.raw_json == raw
    with pytest.raises(ValueError, match="(?i)limit|byte|mib|large|too_long|at most"):
        _full(raw_json=raw + " ")
    unicode_raw = canonical({"draft": {}, "padding": "中" * (_MIB // 2)})
    assert len(unicode_raw) < _MIB < len(unicode_raw.encode("utf-8"))
    with pytest.raises(ValueError, match="(?i)limit|byte|mib|large"):
        _full(raw_json=unicode_raw)


def test_stage_limit_is_utf8_bytes_and_never_silently_truncates():
    Stage, _ = _models()
    output = canonical({"draft": {}, "padding": "中" * (_MIB // 2)})
    assert len(output) < _MIB < len(output.encode("utf-8"))
    with pytest.raises(ValueError, match="(?i)limit|byte|mib|large"):
        Stage.build(phase="SOURCE_NORMALIZED", output_json=output)


def test_context_limit_is_utf8_bytes_not_a_character_count(patch_images):
    context = json.loads(patch_images["context_json"])
    context["snapshot"]["name"] = "中" * (_MIB // 2)
    output = canonical(context)
    assert len(output) < _MIB < len(output.encode("utf-8"))
    with pytest.raises(ValueError, match="(?i)limit|byte|mib|large"):
        _patch(patch_images, context_json=output)


def test_total_evidence_limit_counts_the_full_serialized_envelope(patch_images):
    Stage, _ = _models()
    context = json.loads(patch_images["context_json"])
    context["evidence"] = [{
        "path": "position.max_qty", "source_id": "first", "source_hash": "a" * 64,
        "clause_id": "synthetic-bounded-prior-evidence", "start": 0, "end": 512,
        "excerpt": "\\" * 512,
    }] * 200
    context_json = canonical(context)
    # Structural context validity is separate from T08's authoritative trust check.
    PlanUpdateContext.model_validate_json(context_json)
    assert len(context_json.encode("utf-8")) <= _MIB
    raw_json = patch_images["raw_json"] + "\t" * (
        _MIB - len(patch_images["raw_json"].encode("utf-8")))
    stages = []
    for phase, original in zip(("DELTA_EXPANDED", "SOURCE_NORMALIZED", "MATERIALIZED"),
                               patch_images["outputs"], strict=True):
        output = json.loads(original)
        output["padding"] = ""
        output["padding"] = "\\" * ((_MIB - len(canonical(output).encode("utf-8"))) // 2)
        output_json = canonical(output)
        assert len(output_json.encode("utf-8")) <= _MIB
        stages.append(Stage.build(phase=phase, output_json=output_json))
    envelope = {
        "kind": "PREDECESSOR_PATCH", "source_hash": scope_hash(patch_images["source"]),
        "raw_json": raw_json, "context_json": context_json, "base_hash": context["base_hash"],
        "stages": [stage.model_dump(mode="json") for stage in stages],
    }
    assert len(canonical(envelope).encode("utf-8")) > 8 * _MIB
    with pytest.raises(ValueError, match="(?i)limit|byte|mib|large"):
        _patch(patch_images, raw_json=raw_json, context_json=context_json, stages=tuple(stages))


def test_more_than_eight_stages_is_rejected(patch_images):
    Stage, _ = _models()
    stage = Stage.build(phase="DELTA_EXPANDED", output_json=patch_images["outputs"][0])
    with pytest.raises(ValueError):
        _patch(patch_images, stages=(stage,) * 9)


def test_even_a_rehashed_private_evidence_cannot_grant_authority(patch_images):
    _, Evidence = _models()
    forged = _patch(patch_images).model_dump(mode="json") | {"authority_granted": True}
    with pytest.raises(ValueError):
        Evidence.model_validate(_rehash(forged))
