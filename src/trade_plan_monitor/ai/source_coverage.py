"""Current source coverage is additional evidence, never a historical decoder."""

from dataclasses import replace

from trade_plan_monitor.ai.daily_review import DailyMapping, build_daily_review, semantic_values
from trade_plan_monitor.ai.source_boundaries import (
    partition_at,
    repeats_executable,
    source_partitions,
)
from trade_plan_monitor.ai.source_context import positive_context
from trade_plan_monitor.ai.source_coverage_models import (
    CoverageAssessment,
    CoverageIssue,
    SourceObligation,
)
from trade_plan_monitor.ai.source_obligations import (
    MISSING,
    bounded_clauses,
    declarations,
    source_scope,
    value_at,
)
from trade_plan_monitor.ai.source_policy_text import declaration_text_supported
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
from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256
from trade_plan_monitor.domain.daily_scope import scope_hash


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


def assess_source_coverage(draft, mapping, source, *, normalization=None, origin="AI_HISTORICAL"):
    """Classify every canonical span using server grammar, not AI background labels."""
    clauses = bounded_clauses(source)
    mapping = _integrity(draft, mapping, clauses)
    source_hash = scope_hash(source)
    values = semantic_values(draft)
    payload = draft.executable_payload()
    metadata = draft.model_dump(mode="json")
    parsed = declarations(source)
    partitions = source_partitions(source)
    groups = relation_groups(parsed, source_hash)
    proven_paths = {}
    obligations, issues = [], []
    normalization_hash = None
    if normalization is not None:
        from trade_plan_monitor.ai.source_normalization import validate_policy_preservation

        try:
            validate_policy_preservation(normalization, draft, source)
        except (ValueError, TypeError, RecursionError):
            issues.append(CoverageIssue(code="SOURCE_NORMALIZATION_LOSS",
                message="The original candidate or complete normalization trace is unproven."))
        else:
            normalization_hash = normalization.evidence_hash
    for clause in source_parts(source, clauses):
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
            scope = source_scope(declaration.path, payload)
            state = ("CONTEXT_VERIFIED" if identity else "MAPPED") if matched else "CONFLICT"
            if supplement is not None:
                state = "MAPPED_WITH_REGISTERED_SUPPLEMENT"
            if matched and not text_supported:
                state = "UNRESOLVED"
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
            kind, scope, state = ("PREDICATE", source_scope(deadline.path, payload),
                                  "MAPPED_WITH_REGISTERED_SUPPLEMENT")
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

    for binding in mapping.bindings:
        if (binding.origin in {"SOURCE", "SOURCE_INTERPRETATION", "SOURCE_SEMANTIC"}
                and (binding.path not in proven_paths or not set(binding.clause_ids)
                     <= proven_paths[binding.path])):
            issues.append(CoverageIssue(code="SOURCE_RELATION_MISMATCH", path=binding.path,
                message="Candidate policy lacks an independent complete source derivation."))

    # The old verifier still owns its field/provenance constraints. Its success
    # cannot waive the independent source obligations above.
    try:
        old = build_daily_review(draft, mapping, source)
    except ValueError as error:
        issues.append(CoverageIssue(code="SOURCE_COVERAGE_REQUIRED",
            message=str(error)[:512] or "Existing source evidence is invalid."))
    else:
        issues.extend(CoverageIssue(code=i.code, path=i.path[:512] or "draft",
            message=i.reason[:512]) for i in old.issues)
    return CoverageAssessment.build(source_hash=source_hash,
        content_hash=daily_draft_content_sha256(draft),
        mapping_hash=daily_hash("source-coverage-mapping-v1", mapping.model_dump(mode="json")),
        normalization_hash=normalization_hash,
        origin=origin, obligations=tuple(obligations), issues=tuple(issues))
