"""Prove current declarations and actual writes against an exact verified parent."""

import json
import re

from trade_plan_monitor.ai.daily_review import semantic_values
from trade_plan_monitor.ai.source_candidate_models import CandidateBinding, SourceCandidateAssurance
from trade_plan_monitor.ai.source_change_models import SourceChangeAssessment, SourceOperationProof
from trade_plan_monitor.ai.source_change_scopes import inherit_change_scopes
from trade_plan_monitor.ai.source_coverage_core import analyze_source
from trade_plan_monitor.ai.source_coverage_models import CoverageIssue
from trade_plan_monitor.ai.source_derivation_replay import verify_update_derivation
from trade_plan_monitor.ai.update_review import context_from_review, materialize_extraction
from trade_plan_monitor.backtest.plan_updates import materialize_plan_update
from trade_plan_monitor.backtest.preparation_models import CollectionPreparationCandidate
from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256
from trade_plan_monitor.domain.risk_scope import risk_identity
from trade_plan_monitor.state.source_coverage_values import CoverageInputs


def corresponding_path(path, before, after):
    """Map collection indices by stable identity, including removed/reordered rules."""
    match = re.match(r"^(ordinary_rules|risk_branches|alert_rules)\[(\d+)\](.*)$", path)
    if match is None:
        return path
    target, index, suffix = match.groups()
    old, new = getattr(before, target), getattr(after, target)
    if int(index) >= len(old):
        return None
    identity = risk_identity if target == "risk_branches" else lambda row: row.rule_id
    key = identity(old[int(index)])
    current = next((n for n, row in enumerate(new) if identity(row) == key), None)
    return None if current is None else f"{target}[{current}]{suffix}"


def _in_target(path, change, draft):
    if path == change.target:
        return True  # The exact [] sentinel belongs to the collection operation.
    if change.rule_id is None:
        return path == change.target or path.startswith(change.target + ".")
    rows = getattr(draft, change.target)
    identity = risk_identity if change.target == "risk_branches" else lambda row: row.rule_id
    index = next((n for n, row in enumerate(rows) if identity(row) == change.rule_id), None)
    prefix = f"{change.target}[{index}]"
    return index is not None and (path == prefix or path.startswith(prefix + "."))


def assess_source_changes(source, output, materialized, inputs, *, context, base_review,
                          verified_parent, binding):
    """This proof covers the whole current source and writes, never an invented full draft."""
    binding = CandidateBinding.model_validate_json(binding.model_dump_json())
    verified_parent = SourceCandidateAssurance.model_validate_json(
        verified_parent.model_dump_json())
    if inputs is not None:
        inputs = CoverageInputs.model_validate_json(inputs.model_dump_json())
    if (context != context_from_review(base_review, verified_parent.binding.candidate_hash)
            or verified_parent.binding.review_evidence_hash != base_review.evidence_hash
            or verified_parent.content_hash != daily_draft_content_sha256(base_review.draft)
            or verified_parent.binding.source_id != base_review.source_id
            or verified_parent.binding.source_binding_hash != base_review.source_hash):
        raise ValueError("current update context differs from the verified exact parent")
    candidate = CollectionPreparationCandidate(
        **materialized.to_preparation_candidate().model_dump(mode="python"),
        source_revision=binding.source_revision, source_hash=source.binding_hash,
        base_hash=context.base_hash)
    if (binding.independent or binding.preparation_id != verified_parent.binding.preparation_id
            or binding.item_index != verified_parent.binding.item_index + 1
            or binding.source_id == verified_parent.binding.source_id
            or binding.candidate_hash != candidate.candidate_hash
            or binding.attempt_id != str(materialized.extraction.request_id)):
        raise ValueError("current update belongs to another preparation/candidate/attempt")
    if (binding.source_id, binding.source_binding_hash, binding.review_evidence_hash,
        binding.inputs_hash, materialized.review.source_id, materialized.review.source_hash,
        materialized.extraction.base_hash, materialized.extraction.output.model_dump_json()) != (
        source.source_id, source.binding_hash, materialized.review.evidence_hash,
        None if inputs is None else inputs.evidence_hash, source.source_id, source.binding_hash,
        context.base_hash, output.model_dump_json(),
    ) or inputs is not None and (
        inputs.source_hash != source.source_hash
        or inputs.source_binding_hash != source.binding_hash
    ):
        raise ValueError("current update source/candidate/input binding differs")
    expected = materialize_extraction(base_review, context.base_hash, source,
                                     materialized.extraction)
    if materialized.review != expected.review:
        raise ValueError("current materialization differs from its exact source and predecessor")
    merged = materialize_plan_update(context.snapshot, output)
    analysis = analyze_source(output.draft, output.review(source.text).mapping, source.text)
    obligations, scope_issues = inherit_change_scopes(
        analysis.obligations, output.draft, base_review, verified_parent)
    issues = [*analysis.issues, *scope_issues]

    def issue(message, path="source", code="SOURCE_COVERAGE_REQUIRED"):
        issues.append(CoverageIssue(code=code, path=path, message=message))

    if not verified_parent.coverage_complete:
        issue("Current inherited authority requires the complete current predecessor proof.")
    if materialized.review.issues:
        issue("The original materialized candidate remains unresolved.", "draft")
    evidence = None if inputs is None else inputs.derivation
    raw_verified, full_supplied = False, False
    if inputs is not None:
        issues.extend(inputs.derivation_issues)
    if evidence is not None:
        try:
            if len(evidence.stages) != 3:
                raise ValueError("materialized derivation is incomplete")
            verify_update_derivation(evidence, source, context, output)
        except (ValueError, TypeError, RecursionError):
            issue("The original current-source delta or deterministic derivation is unproven.",
                  code="SOURCE_NORMALIZATION_LOSS")
        else:
            raw_verified = True
            full_supplied = isinstance(json.loads(evidence.raw_json).get("draft"), dict)
    else:
        issue("The observed provider delta is missing; a reconstructed full draft is not evidence.",
              code="SOURCE_NORMALIZATION_LOSS")
    before, proposed, final = (semantic_values(value) for value in (
        base_review.draft, output.draft, merged.draft))
    changed = set()
    for path, value in final.items():
        old = corresponding_path(path, merged.draft, base_review.draft)
        if old not in before or type(value) is not type(before[old]) or value != before[old]:
            changed.add(path)
    removed = {path for path in before if corresponding_path(
        path, base_review.draft, merged.draft) not in final}
    changed.update(removed)
    for path in analysis.proven_paths:
        actual = corresponding_path(path, output.draft, merged.draft)
        if (actual not in final or type(proposed[path]) is not type(final[actual])
                or proposed[path] != final[actual]):
            issue("A current-source policy declaration was not applied to the final candidate.",
                  path, "SOURCE_RELATION_MISMATCH")
    selected = {bound.original_path for bound in materialized.review.bindings
                if (bound.source_id, bound.source_hash) == (source.source_id, source.binding_hash)}
    for bound in analysis.mapping.bindings:
        if bound.path in selected and bound.origin in {
            "SOURCE", "SOURCE_INTERPRETATION", "SOURCE_SEMANTIC",
        } and (
            bound.path not in analysis.proven_paths or not set(bound.clause_ids)
            <= analysis.proven_paths[bound.path]
        ):
            issue("The current binding does not cite its independently proven exact declaration.",
                  bound.path, "SOURCE_RELATION_MISMATCH")
    proofs = []
    for change in merged.changes:
        # Reordered collection indices can name a removed rule and a retained
        # sibling. Retention never consumes the removed sibling's old paths.
        paths = (() if change.action == "RETAIN" else tuple(sorted(
            path for path in changed if _in_target(path, change, merged.draft)
            or _in_target(path, change, base_review.draft))))
        linked = set()
        if change.action != "RETAIN":
            if change.action == "REVOKE":
                issue("Removing a rule requires independent whole-rule cancellation evidence.",
                      change.target)
            for path in paths:
                proposed_path = corresponding_path(path, merged.draft, output.draft)
                clauses = analysis.proven_paths.get(proposed_path, frozenset())
                if not clauses or not clauses & set(change.clause_ids):
                    issue("An actual policy change has no complete current-source derivation.",
                          path)
                linked.update(row.obligation_id for row in obligations
                              if row.clause_id in clauses and any(
                                  proposed_path == own or proposed_path.startswith(own + ".")
                                  or proposed_path.startswith(own + "[") for own in row.paths))
        proofs.append(SourceOperationProof(target=change.target, rule_id=change.rule_id,
            action=change.action,
            before_hash=daily_hash("source-operation-value-v1", change.before),
            after_hash=daily_hash("source-operation-value-v1", change.after), changed_paths=paths,
            obligation_ids=tuple(sorted(linked)),
            origin="PRODUCT_RETENTION" if change.action == "RETAIN" else "SOURCE"))
    return SourceChangeAssessment.build(binding=binding, source_hash=source.source_hash,
        source_binding_hash=source.binding_hash,
        content_hash=daily_draft_content_sha256(merged.draft),
        mapping_hash=daily_hash("source-coverage-mapping-v1",
                               analysis.mapping.model_dump(mode="json")),
        review_evidence_hash=materialized.review.evidence_hash, base_hash=context.base_hash,
        parent_assurance_hash=verified_parent.evidence_hash,
        inputs_hash=None if inputs is None else inputs.evidence_hash,
        derivation_hash=None if evidence is None else evidence.evidence_hash,
        raw_delta_verified=raw_verified, provider_full_draft_supplied=full_supplied,
        full_draft_fidelity_verified=False, parent_verified=verified_parent.coverage_complete,
        operations=tuple(proofs), changed_paths=tuple(sorted(changed)),
        obligations=obligations, issues=tuple(issues))
