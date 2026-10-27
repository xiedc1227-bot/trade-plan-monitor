"""Bounded whole-source analysis; callers separately prove full or inherited coverage."""

import re
from collections import Counter
from dataclasses import dataclass, replace
from typing import Literal

from trade_plan_monitor.ai.daily_review import DailyMapping, semantic_values
from trade_plan_monitor.ai.source_boundaries import (
    partition_at,
    repeats_executable,
    source_partitions,
)
from trade_plan_monitor.ai.source_context import positive_context
from trade_plan_monitor.ai.source_control_models import SourceControlAnalysis
from trade_plan_monitor.ai.source_coverage_models import (
    COMPLETE_STATES,
    CoverageIssue,
    SourceObligation,
)
from trade_plan_monitor.ai.source_native_support import native_support_issues
from trade_plan_monitor.ai.source_obligations import (
    MISSING,
    bounded_clauses,
    declarations,
    source_scope,
    value_at,
)
from trade_plan_monitor.ai.source_policy_text import declaration_text_supported
from trade_plan_monitor.ai.source_risk_control_models import SourceRiskControlAnalysis
from trade_plan_monitor.ai.source_semantic_atoms import semantic_atoms
from trade_plan_monitor.ai.source_semantics import (
    declaration_relations,
    declared_paths,
    equal_declaration,
    relation_groups,
)
from trade_plan_monitor.ai.source_treatments import (
    deadline_supplement,
    missing_value_supplement,
    source_parts,
)
from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256
from trade_plan_monitor.domain.daily_scope import scope_hash
from trade_plan_monitor.domain.risk_scope import risk_identity


@dataclass(frozen=True, slots=True)
class SourceAnalysis:
    mapping: DailyMapping
    source_hash: str
    normalization_hash: str | None
    obligations: tuple[SourceObligation, ...]
    issues: tuple[CoverageIssue, ...]
    proven_paths: dict[str, frozenset[str]]
    authority_granted: Literal[False] = False


def _integrity(draft, mapping, clauses):
    mapping = DailyMapping.model_validate(mapping.model_dump())
    if mapping.candidate_content_hash != daily_draft_content_sha256(draft):
        raise ValueError("mapping candidate content changed")
    if len(mapping.clauses) != len(clauses) or any(
        any(getattr(actual, key) != getattr(expected, key)
            for key in ("clause_id", "start", "end", "excerpt"))
        for actual, expected in zip(mapping.clauses, clauses, strict=True)
    ):
        raise ValueError("source clause differs from exact original source")
    return mapping


def _risk_parts(source, parts, controls):
    if controls is None or not controls.controls:
        return parts
    result = []
    for part in parts:
        cuts = {part.start, part.end}
        for row in controls.controls:
            cuts.update(point for point in (row.start, row.end) if part.start < point < part.end)
        ordered = sorted(cuts)
        for start, end in zip(ordered, ordered[1:], strict=False):
            if source[start:end].strip(" 。；，,;、.!?！？\n\r\t"):
                result.append(replace(part, start=start, end=end, excerpt=source[start:end]))
    if len(result) > 4096 or any(count > 64 for count in Counter(
        row.clause_id for row in result).values()
    ):
        raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")
    return tuple(result)


def _cross_control_conflicts(controls, risk_controls):
    ordinals = {}
    for registry in (controls, risk_controls):
        if registry is None:
            continue
        for row in registry.controls:
            excerpt = row.excerpt
            normalized = excerpt[2:-2] if excerpt.startswith("**") and excerpt.endswith("**") else (
                excerpt)
            match = re.match(r"operations\[(0|[1-9][0-9]?)\][ \t]*=", normalized)
            if match:
                ordinals.setdefault(int(match[1]), []).append(row.control_id)
    return {identity for identities in ordinals.values() if len(identities) > 1
            for identity in identities}


def analyze_source(draft, mapping, source, *, normalization=None, controls=None,
                   risk_controls: SourceRiskControlAnalysis | None = None):
    """Classify every canonical span using server grammar, not AI background labels."""
    clauses = bounded_clauses(source)
    mapping = _integrity(draft, mapping, clauses)
    source_hash = scope_hash(source)
    if controls is not None:
        controls = SourceControlAnalysis.model_validate_json(controls.model_dump_json())
        if controls.source_hash != source_hash or controls.source_length != len(source) or any(
            source[row.start:row.end] != row.excerpt for row in controls.controls
        ):
            raise ValueError("source controls differ from the exact original source")
    if risk_controls is not None:
        risk_controls = SourceRiskControlAnalysis.model_validate_json(
            risk_controls.model_dump_json())
        if (risk_controls.source_hash != source_hash or risk_controls.source_length != len(source)
                or any(source[row.start:row.end] != row.excerpt for row in (
                    *risk_controls.controls, *risk_controls.unresolved))):
            raise ValueError("risk source controls differ from the exact original source")
    control_conflicts = _cross_control_conflicts(controls, risk_controls)
    values = semantic_values(draft)
    payload = draft.executable_payload()
    metadata = draft.model_dump(mode="json")
    parsed = declarations(source)
    human_sides = {}
    for declaration in parsed:
        if declaration.path.endswith(".side"):
            supplement = missing_value_supplement(declaration, draft, mapping)
            if supplement is not None:
                human_sides[declaration.path] = supplement.value
    partitions = source_partitions(source)
    groups = relation_groups(parsed, source_hash)
    proven_paths = {}
    obligations, issues = [], []
    parts = _risk_parts(source, source_parts(source, clauses), risk_controls)
    base_counts = Counter(row.clause_id for row in parts)
    expanded_counts = Counter()
    atom_cache, total_expanded = {}, 0
    normalization_hash = None
    if control_conflicts:
        issues.append(CoverageIssue(code="SOURCE_RELATION_MISMATCH",
            message="Independent source control registries repeat an operation ordinal."))
    if normalization is not None:
        from trade_plan_monitor.ai.source_normalization import validate_policy_preservation

        try:
            validate_policy_preservation(normalization, draft, source)
        except (ValueError, TypeError, RecursionError):
            issues.append(CoverageIssue(code="SOURCE_NORMALIZATION_LOSS",
                message="The original candidate or complete normalization trace is unproven."))
        else:
            normalization_hash = normalization.evidence_hash
    for clause in parts:
        control = None if controls is None else next((row for row in controls.controls
            if row.start <= clause.start < clause.end <= row.end), None)
        risk_control = None if risk_controls is None else next((
            row for row in risk_controls.controls
            if row.start <= clause.start < clause.end <= row.end), None)
        declaration = next((d for d in parsed
                            if d.start <= clause.start < clause.end <= d.end), None)
        path, group, meaning, relations = (), None, None, ()
        deadline = deadline_supplement(clause.excerpt, draft, mapping)
        if clause.excluded or clause.limited:
            kind, scope = ("UNKNOWN", "UNKNOWN") if clause.limited else ("SCOPE_EXCLUSION", "PLAN")
            state = "UNRESOLVED" if clause.limited else "SCOPE_EXCLUDED"
            meaning = canonical(dict(treatment="FUNDAMENTALS_REVIEWED_AT_PLAN_GENERATION"))
            if clause.limited:
                issues.append(CoverageIssue(code="SOURCE_COVERAGE_LIMIT_EXCEEDED",
                    path="source." + clause.clause_id, start=clause.start, end=clause.end,
                    message="Complete source partition exceeds the bounded obligation contract."))
        elif control is not None:
            kind, scope, state = "PREDICATE", control.scope, "MAPPED"
            group = control.control_id
            meaning = canonical(dict(treatment="REGISTERED_SOURCE_CONTROL",
                                     source_control=control.model_dump(mode="json")))
            if control.control_id in control_conflicts:
                state = "CONFLICT"
            if partition_at(partitions, clause.start) == "B":
                state = "CONFLICT"
                issues.append(CoverageIssue(code="SOURCE_RELATION_MISMATCH",
                    path="source." + clause.clause_id, start=clause.start, end=clause.end,
                    message="A new background control cannot authorize executable policy."))
        elif risk_control is not None:
            kind, scope, state = "PREDICATE", "RISK", "MAPPED"
            group = risk_control.control_id
            meaning = canonical(dict(treatment="REGISTERED_SOURCE_RISK_CONTROL",
                                     source_risk_control=risk_control.model_dump(mode="json")))
            if (risk_control.control_id in control_conflicts
                    or partition_at(partitions, clause.start) == "B"):
                state = "CONFLICT"
                issues.append(CoverageIssue(code="SOURCE_RELATION_MISMATCH",
                    path="source." + clause.clause_id, start=clause.start, end=clause.end,
                    message="A conflicting or background risk control cannot supply policy."))
            if risk_control.action == "MODIFY":
                index = next((index for index, branch in enumerate(draft.risk_branches)
                              if risk_identity(branch) == risk_control.rule_id), None)
                actual = (None if index is None else
                          draft.risk_branches[index].model_dump(mode="json"))
                if canonical(actual) != canonical(risk_control.after.model_dump(mode="json")):
                    state = "CONFLICT"
                    issues.append(CoverageIssue(code="SOURCE_RELATION_MISMATCH",
                        path="risk_branches", start=clause.start, end=clause.end,
                        message="The full proposed risk branch differs from the exact control."))
                elif state == "MAPPED":
                    prefix = f"risk_branches[{index}].holding_scope."
                    path = tuple(own for own in values if own.startswith(prefix))
                    for proven in path:
                        proven_paths.setdefault(proven, set()).add(clause.clause_id)
        elif declaration is not None:
            actual = values.get(declaration.path, MISSING)
            if actual is MISSING:
                actual = value_at(payload, declaration.path)
            identity = declaration.path in {"plan_id", "version", "name"} or (
                declaration.path.startswith("metadata.")
            )
            if identity:
                actual = value_at(metadata, declaration.path)
            if identity:
                literal = declaration.path + " = " + canonical(declaration.value)
                matched = bool(positive_context(literal, metadata=metadata))
            else:
                matched = equal_declaration(declaration, values, payload)
            supplement = None if identity else missing_value_supplement(declaration, draft, mapping)
            matched = matched or supplement is not None
            treatment_declaration = (replace(declaration, value=supplement.value)
                                     if supplement is not None else declaration)
            text_supported = identity or declaration_text_supported(treatment_declaration, values)
            own, relations = declaration_relations(declaration, groups)
            kind = "CONTEXT" if identity else "RELATION" if own else "PREDICATE"
            scope = source_scope(declaration.path, payload, parsed, human_sides, values)
            state = ("CONTEXT_VERIFIED" if identity else "MAPPED") if matched else "CONFLICT"
            if supplement is not None:
                state = "MAPPED_WITH_REGISTERED_SUPPLEMENT"
            if not text_supported:
                state = "UNRESOLVED" if matched else "CONFLICT"
                scope = "UNKNOWN"
                issues.append(CoverageIssue(code="SOURCE_CONTEXT_UNVERIFIED",
                    path=declaration.path, start=clause.start, end=clause.end,
                    message="Policy prose has no complete registered executable meaning."))
            in_background = partition_at(partitions, clause.start) == "B" and not identity
            partition_conflict = in_background and not repeats_executable(
                declaration, parsed, partitions)
            if partition_conflict:
                state = "CONFLICT"
                issues.append(CoverageIssue(code="SOURCE_RELATION_MISMATCH",
                    path=declaration.path, start=clause.start, end=clause.end,
                    message="A new policy in background cannot supply executable A authority."))
            path, group = (declaration.path,), own or declaration.group_id
            meaning = canonical(dict(path=declaration.path, value=declaration.value))
            if isinstance(declaration.value, (dict, list)) and declaration.value:
                meaning = canonical(dict(path=declaration.path,
                    treatment="COMPLETE_JSON_DECLARATION", source_start=declaration.start,
                    source_end=declaration.end, container_hash=declaration.group_id))
            if supplement is not None:
                meaning = canonical(dict(path=declaration.path, value=declaration.value,
                    supplement=supplement.model_dump(mode="json")))
            if matched and text_supported and not identity and not partition_conflict:
                for proven in declared_paths(declaration, values):
                    proven_paths.setdefault(proven, set()).add(clause.clause_id)
            if not matched:
                issues.append(CoverageIssue(code="SOURCE_RELATION_MISMATCH",
                    path=declaration.path, start=clause.start, end=clause.end,
                    message="The complete source declaration differs from the candidate."))
        elif deadline is not None and partition_at(partitions, clause.start) == "A":
            kind, state = "PREDICATE", "MAPPED_WITH_REGISTERED_SUPPLEMENT"
            scope = source_scope(deadline.path, payload, parsed, human_sides, values)
            path = (deadline.path,)
            meaning = canonical(dict(treatment="REGISTERED_DEADLINE_CONVERSION",
                supplement=deadline.model_dump(mode="json")))
        else:
            treatment = positive_context(clause.excerpt, metadata=metadata)
            kind, scope = ("CONTEXT", "PLAN") if treatment else ("UNKNOWN", "UNKNOWN")
            state = "CONTEXT_VERIFIED" if treatment else "UNRESOLVED"
            meaning = None if treatment is None else canonical(dict(treatment=treatment))
            if not treatment:
                issues.append(CoverageIssue(code="SOURCE_CONTEXT_UNVERIFIED",
                    path="source." + clause.clause_id, start=clause.start, end=clause.end,
                    message="This source span has no proven complete policy or context treatment."))
        if meaning is not None and len(meaning) > 8192 or len(relations) > 64:
            kind, scope, state, meaning, relations = "UNKNOWN", "UNKNOWN", "UNRESOLVED", None, ()
            issues.append(CoverageIssue(code="SOURCE_COVERAGE_LIMIT_EXCEEDED",
                path="source." + clause.clause_id, start=clause.start, end=clause.end,
                message="The complete source meaning exceeds the bounded evidence contract."))
        obligations.append(SourceObligation.build(source_hash=source_hash,
            clause_id=clause.clause_id, start=clause.start, end=clause.end,
            excerpt=source[clause.start:clause.end], kind=kind, scope=scope, state=state,
            semantics_json=meaning, group_id=group, relation_ids=relations, paths=path))

        if (control is None and risk_control is None
                and declaration is not None and kind == "PREDICATE"
                and isinstance(declaration.value, (dict, list)) and declaration.value):
            try:
                if declaration.group_id not in atom_cache:
                    atom_cache[declaration.group_id] = "SOURCE_COVERAGE_UNSUPPORTED"
                    atom_cache[declaration.group_id] = semantic_atoms(source, declaration)
                atoms = atom_cache[declaration.group_id]
                if isinstance(atoms, str):
                    raise ValueError(atoms)
                atoms = tuple(atom for atom in atoms if atom.start < clause.end
                              and atom.end > clause.start)
                if (base_counts[clause.clause_id] + expanded_counts[clause.clause_id]
                        + len(atoms) > 64 or len(parts) + total_expanded + len(atoms) > 4096):
                    raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")
                expanded = []
                for atom in atoms:
                    begin, end = max(atom.start, clause.start), min(atom.end, clause.end)
                    atom_text_supported = atom.kind == "RELATION" or declaration_text_supported(
                        replace(declaration, path=atom.path, value=atom.value), values)
                    expanded.append(SourceObligation.build(source_hash=source_hash,
                        clause_id=clause.clause_id, start=begin, end=end,
                        excerpt=source[begin:end], kind=atom.kind,
                        scope=(source_scope(atom.path, payload, parsed, human_sides, values)
                               if atom_text_supported else "UNKNOWN"), state=state,
                        semantics_json=canonical(dict(path=atom.path, value=atom.value)),
                        group_id=atom.group_id, relation_ids=atom.relation_ids,
                        paths=(atom.path,)))
            except (ValueError, TypeError, RecursionError) as error:
                code = ("SOURCE_COVERAGE_LIMIT_EXCEEDED" if
                        str(error) == "SOURCE_COVERAGE_LIMIT_EXCEEDED"
                        else "SOURCE_COVERAGE_UNSUPPORTED")
                atom_cache[declaration.group_id] = code
                issues.append(CoverageIssue(code=code,
                    path="source." + clause.clause_id, start=clause.start, end=clause.end,
                    message="The complete native source graph is unproven within its contract."))
            else:
                obligations.extend(expanded)
                expanded_counts[clause.clause_id] += len(expanded)
                total_expanded += len(expanded)

    native_issues = native_support_issues(payload, source, parsed)
    issues.extend(native_issues)
    if native_issues:
        obligations = [row.model_copy(update={"state": "UNSUPPORTED"}) if (
            row.state in COMPLETE_STATES and any(
                path == issue.path or issue.path.startswith(path + ".")
                or path.startswith(issue.path + ".")
                for path in row.paths for issue in native_issues
            )
        ) else row for row in obligations]
    return SourceAnalysis(mapping=mapping, source_hash=source_hash,
        normalization_hash=normalization_hash, obligations=tuple(obligations), issues=tuple(issues),
        proven_paths={path: frozenset(ids) for path, ids in proven_paths.items()})
