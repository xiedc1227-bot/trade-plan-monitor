"""Complete change semantics shared by separately authorized AI and human protocols."""

import json
import re
from dataclasses import dataclass

from trade_plan_monitor.ai.daily_review import DailyMapping, semantic_values
from trade_plan_monitor.ai.plan_update_extraction import (
    PlanUpdateContext,
    PlanUpdateExtractionOutput,
)
from trade_plan_monitor.ai.source_candidate_models import SourceCandidateAssurance
from trade_plan_monitor.ai.source_change_models import SourceOperationProof
from trade_plan_monitor.ai.source_change_scopes import inherit_change_scopes
from trade_plan_monitor.ai.source_controls import parse_source_controls
from trade_plan_monitor.ai.source_coverage_core import analyze_source
from trade_plan_monitor.ai.source_coverage_models import CoverageIssue, SourceObligation
from trade_plan_monitor.ai.source_risk_controls import parse_source_risk_controls
from trade_plan_monitor.ai.source_risk_table_coverage import build_risk_table_coverage
from trade_plan_monitor.ai.update_review import (
    PlanCandidateReview,
    build_update_review,
    context_from_review,
)
from trade_plan_monitor.backtest.plan_updates import materialize_plan_update
from trade_plan_monitor.backtest.preparation_models import PreparationSource
from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256
from trade_plan_monitor.domain.market_linkage_validation import CurrentPlanDraft
from trade_plan_monitor.domain.risk_scope import risk_identity


@dataclass(frozen=True, slots=True)
class SourceChangeAnalysis:
    """Semantic evidence only: no completeness verdict, provider claim or authority."""

    mapping: DailyMapping
    draft: CurrentPlanDraft
    source_hash: str
    source_binding_hash: str
    content_hash: str
    mapping_hash: str
    review_evidence_hash: str
    base_hash: str
    parent_assurance_hash: str
    parent_verified: bool
    obligations: tuple[SourceObligation, ...]
    operations: tuple[SourceOperationProof, ...]
    changed_paths: tuple[str, ...]
    head_issues: tuple[CoverageIssue, ...]
    tail_issues: tuple[CoverageIssue, ...]


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


def _risk_matches(control, change):
    action = (change.action == control.action or control.action == "MODIFY"
              and change.action == "RETAIN" and control.before_hash == control.after_hash)
    return action and (change.target, change.rule_id,
        daily_hash("source-operation-value-v1", change.before),
        daily_hash("source-operation-value-v1", change.after)) == (
        control.target, control.rule_id, control.before_hash, control.after_hash)


def analyze_source_changes(
    source: PreparationSource, output: PlanUpdateExtractionOutput, reviewed: PlanCandidateReview,
    complete_mapping: DailyMapping, *, context: PlanUpdateContext, base_review: PlanCandidateReview,
    verified_parent: SourceCandidateAssurance,
) -> SourceChangeAnalysis:
    """Check the complete source, mapping, predecessor and actual materialized writes.

    Callers separately establish extraction or human command provenance. The
    complete historical verifier is rerun with the supplied mapping; none of its
    issues is filtered to manufacture a partial completeness result.
    """
    verified_parent = SourceCandidateAssurance.model_validate_json(
        verified_parent.model_dump_json())
    reviewed = PlanCandidateReview.model_validate_json(reviewed.model_dump_json())
    if (context != context_from_review(base_review, verified_parent.binding.candidate_hash)
            or verified_parent.binding.review_evidence_hash != base_review.evidence_hash
            or verified_parent.content_hash != daily_draft_content_sha256(base_review.draft)
            or verified_parent.binding.source_id != base_review.source_id
            or verified_parent.binding.source_binding_hash != base_review.source_hash):
        raise ValueError("current update context differs from the verified exact parent")
    expected = build_update_review(base_review, source, output, mapping=complete_mapping)
    if reviewed != expected:
        raise ValueError("current materialization differs from its exact source and predecessor")
    merged = materialize_plan_update(context.snapshot, output)
    if merged.draft != reviewed.draft:
        raise ValueError("current review draft differs from the complete materialization")
    controls = parse_source_controls(source, base_review, verified_parent)
    risk_controls = (parse_source_risk_controls(source, base_review, verified_parent)
                     if verified_parent.coverage_complete else None)
    risk_tables = (build_risk_table_coverage(source, base_review, verified_parent)
                   if verified_parent.coverage_complete else None)
    all_risks = (*(() if risk_controls is None else risk_controls.controls),
                 *(() if risk_tables is None else
                   tuple(row.scope_control for row in risk_tables.analysis.groups)))
    analysis = analyze_source(output.draft, complete_mapping, source.text,
                              controls=controls, risk_controls=risk_controls,
                              risk_tables=risk_tables)
    obligations, scope_issues = inherit_change_scopes(
        analysis.obligations, output.draft, base_review, verified_parent, source=source.text)
    issues = [*analysis.issues, *scope_issues, *controls.issues]
    if risk_controls is not None:
        issues.extend(risk_controls.issues)

    def issue(message, path="source", code="SOURCE_COVERAGE_REQUIRED"):
        issues.append(CoverageIssue(code=code, path=path, message=message))

    if not verified_parent.coverage_complete:
        issue("Current inherited authority requires the complete current predecessor proof.")
    if reviewed.issues:
        issue("The original materialized candidate remains unresolved.", "draft")
    head_issues = tuple(issues)
    issues = []
    before, proposed, final = (semantic_values(value) for value in (
        base_review.draft, output.draft, merged.draft))
    surviving_changed = set()
    for path, value in final.items():
        old = corresponding_path(path, merged.draft, base_review.draft)
        if old not in before or type(value) is not type(before[old]) or value != before[old]:
            surviving_changed.add(path)
    removed = {path for path in before if corresponding_path(
        path, base_review.draft, merged.draft) not in final}
    for path in analysis.proven_paths:
        actual = corresponding_path(path, output.draft, merged.draft)
        if (actual not in final or type(proposed[path]) is not type(final[actual])
                or proposed[path] != final[actual]):
            issue("A current-source policy declaration was not applied to the final candidate.",
                  path, "SOURCE_RELATION_MISMATCH")
    selected = {bound.original_path for bound in reviewed.bindings
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
    control_rows, risk_rows = {}, {}
    for row in obligations:
        meaning = None if row.semantics_json is None else json.loads(row.semantics_json)
        if isinstance(meaning, dict) and meaning.get("treatment") == "REGISTERED_SOURCE_CONTROL":
            control_rows.setdefault(meaning["source_control"]["control_id"], []).append(row)
        if (isinstance(meaning, dict)
                and meaning.get("treatment") == "REGISTERED_SOURCE_RISK_CONTROL"):
            risk_rows.setdefault(meaning["source_risk_control"]["control_id"], []).append(row)
    for control in controls.controls:
        if control.target == "plan":
            valid = (all(change.action == "RETAIN" for change in merged.changes)
                     if control.action == "NO_NEW_INSTRUCTIONS"
                     else output.retain_unmentioned is True)
        else:
            valid = any((change.target, change.rule_id, change.action,
                         daily_hash("source-operation-value-v1", change.before)) == (
                         control.target, control.rule_id, control.action, control.before_hash)
                        for change in merged.changes)
        if not valid:
            issue("The complete source control was not applied to its exact predecessor target.",
                  control.target, "SOURCE_RELATION_MISMATCH")
    for control in all_risks:
        if not any(_risk_matches(control, change) for change in merged.changes):
            issue("The exact full risk control was not applied to its predecessor branch.",
                  control.target, "SOURCE_RELATION_MISMATCH")
    proofs, changed = [], set()
    for change in merged.changes:
        # Compute each operation in its own stable-rule coordinates. Removed
        # siblings never donate their old index to a surviving modified rule.
        paths = set()
        if change.action == "REVOKE":
            paths.update(path for path in removed if _in_target(path, change, base_review.draft))
        elif change.action != "RETAIN":
            paths.update(path for path in surviving_changed
                         if _in_target(path, change, merged.draft))
            if change.action == "MODIFY":
                paths.update(mapped for path in removed
                    if _in_target(path, change, base_review.draft)
                    and (mapped := corresponding_path(
                        path, base_review.draft, merged.draft)) is not None)
        if change.action != "RETAIN" and change.target in surviving_changed | removed:
            paths.add(change.target)
        paths = tuple(sorted(paths))
        changed.update(paths)
        linked = set()
        matching_risks = [control for control in all_risks if _risk_matches(control, change)]
        linked.update(row.obligation_id for control in matching_risks
                      for row in risk_rows.get(control.control_id, ()))
        if change.action != "RETAIN":
            if change.action == "REVOKE":
                matching = [control for control in controls.controls if (
                    control.target, control.rule_id, control.action, control.before_hash) == (
                    change.target, change.rule_id, "REVOKE",
                    daily_hash("source-operation-value-v1", change.before))]
                linked.update(row.obligation_id for control in matching
                              for row in control_rows.get(control.control_id, ()))
                if not linked:
                    issue("Removing a rule requires independent whole-rule cancellation evidence.",
                          change.target)
            for path in (() if change.action == "REVOKE" else paths):
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
            origin="PRODUCT_RETENTION" if change.action == "RETAIN" and not matching_risks
            else "SOURCE"))
    return SourceChangeAnalysis(mapping=analysis.mapping, draft=merged.draft,
        source_hash=source.source_hash, source_binding_hash=source.binding_hash,
        content_hash=daily_draft_content_sha256(merged.draft),
        mapping_hash=daily_hash("source-coverage-mapping-v1",
                               analysis.mapping.model_dump(mode="json")),
        review_evidence_hash=reviewed.evidence_hash, base_hash=context.base_hash,
        parent_assurance_hash=verified_parent.evidence_hash,
        parent_verified=verified_parent.coverage_complete, obligations=obligations,
        operations=tuple(proofs), changed_paths=tuple(sorted(changed)),
        head_issues=head_issues, tail_issues=tuple(issues))
