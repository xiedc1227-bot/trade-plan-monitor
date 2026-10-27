"""Deterministic update derivation; no provider I/O or business-state writes."""

import json

from trade_plan_monitor.ai.source_derivation import DerivationStage, SourceDerivationEvidence
from trade_plan_monitor.domain.daily_hash import canonical


def _inputs(source, context):
    from trade_plan_monitor.ai.plan_update_extraction import PlanUpdateContext
    from trade_plan_monitor.backtest.preparation_models import PreparationSource

    if not isinstance(source, PreparationSource) or not isinstance(context, PlanUpdateContext):
        raise ValueError("derivation requires the exact source and predecessor context")
    return (PreparationSource.model_validate(source.model_dump(mode="python")),
            PlanUpdateContext.model_validate(context.model_dump(mode="python")))


def _stage(phase, output):
    return DerivationStage.build(phase=phase, output_json=canonical(output.model_dump(mode="json")))


def expand_update_with_evidence(raw_json, source, context):
    """Record provider bytes separately from each complete derived update output."""
    from trade_plan_monitor.ai.extraction import _parse_untrusted_output
    from trade_plan_monitor.ai.plan_delta_wire import CompactDeltaOutput, expand_delta_output
    from trade_plan_monitor.ai.plan_update_extraction import (
        PlanUpdateExtractionOutput,
        validate_update_evidence,
    )
    from trade_plan_monitor.ai.preparation_wire import (
        CompactUpdateOutput,
        expand_compact_output,
        response_model,
    )

    source, context = _inputs(source, context)
    raw = json.loads(raw_json)
    if not isinstance(raw, dict):
        raise ValueError("unsupported derivation protocol")
    direct = raw.get("schema_version") == "monitor-loop-update-extraction-v1"
    model = PlanUpdateExtractionOutput if direct else response_model(update=True)
    parsed = _parse_untrusted_output(raw_json, prompt_version="monitor-loop-update-extract-v1",
        output_model=model)
    output = parsed if direct else parsed.root
    if isinstance(output, CompactDeltaOutput):
        output = expand_delta_output(output, context)
    stages = [_stage("DELTA_EXPANDED", output)]
    if isinstance(output, CompactUpdateOutput):
        output = expand_compact_output(output, source, context=context)
    if not isinstance(output, PlanUpdateExtractionOutput):
        raise ValueError("unsupported derivation protocol")
    validate_update_evidence(output, source, context)
    stages.append(_stage("SOURCE_NORMALIZED", output))
    evidence = SourceDerivationEvidence.build(kind="PREDECESSOR_PATCH",
        source_hash=source.source_hash, raw_json=raw_json,
        context_json=canonical(context.model_dump(mode="json")), base_hash=context.base_hash,
        stages=tuple(stages))
    return output, evidence


def _materialized_stage(output, context):
    from trade_plan_monitor.backtest.plan_updates import materialize_plan_update

    return _stage("MATERIALIZED", materialize_plan_update(context.snapshot, output))


def verify_update_derivation(evidence, source, context, expected_output):
    """Hashes prove correspondence only; current trusted authority is checked by T08."""
    source, context = _inputs(source, context)
    evidence = SourceDerivationEvidence.model_validate(evidence.model_dump(mode="json"))
    if (evidence.kind != "PREDECESSOR_PATCH" or evidence.source_hash != source.source_hash
            or evidence.context_json != canonical(context.model_dump(mode="json"))
            or evidence.base_hash != context.base_hash or len(evidence.stages) < 2):
        raise ValueError("source derivation binding is missing or stale")
    output, replayed = expand_update_with_evidence(evidence.raw_json, source, context)
    expected = canonical(expected_output.model_dump(mode="json"))
    if canonical(output.model_dump(mode="json")) != expected:
        raise ValueError("source derivation differs from the complete expected output")
    stages = replayed.stages
    if len(evidence.stages) == 3:
        stages += (_materialized_stage(output, context),)
    if evidence.stages != stages:
        raise ValueError("source derivation stage differs from deterministic replay")
    return output


def append_materialized_derivation(evidence, source, context, expected_output):
    output = verify_update_derivation(evidence, source, context, expected_output)
    stages = evidence.stages[:2] + (_materialized_stage(output, context),)
    return SourceDerivationEvidence.build(**(evidence.model_dump(mode="python", exclude={
        "evidence_hash", "raw_hash", "context_hash", "stages",
    }) | dict(stages=stages)))
