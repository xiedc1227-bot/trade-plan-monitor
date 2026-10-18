"""Bounded corrections of representation errors, never guesses at business facts."""

import json
import re

REPAIR_ERRORS = frozenset(
    {
        "AI_FIELD_EVIDENCE_INVALID",
        "AI_OUTPUT_INVALID",
        "INVALID_OUTPUT",
        "INVALID_UPDATE_EVIDENCE",
        "AI_REPAIR_REQUIRED",
        "AI_CHANGE_IDENTITY_CONFLICT",
        "AI_FIELD_PATH_INVALID",
        "AI_EMPTY_CHANGE",
        "AI_AMBIGUITY_REFERENCE_INVALID",
        "AI_RISK_APPLICABILITY_REQUIRED",
    }
)
PROCESSING_ISSUES = frozenset(
    {
        "AI_COMPUTABLE_CONDITION_UNEXPANDED",
        "DAILY_SOURCE_BINDING_REQUIRED",
        "DAILY_SOURCE_CLAUSE_REQUIRED",
        "UPDATE_CHANGE_ASSESSMENT_REQUIRED",
        "UPDATE_WITHDRAWAL_SCOPE_REQUIRED",
        "UPDATE_WITHDRAWAL_CONTEXT_ONLY",
        "UPDATE_SCOPE_DIRECTION_REQUIRED",
        "UPDATE_MATERIALIZATION_REQUIRED",
        "UPDATE_RETENTION_EVIDENCE_REQUIRED",
        "UPDATE_OPERATION_EVIDENCE_REQUIRED",
        "UPDATE_SOURCE_BINDING_REQUIRED",
    }
)


def correction_feedback(candidate):
    """Only server issue codes and machine paths enter corrective instructions."""
    if candidate is None:
        return ()
    # Genuine ambiguity is a business question, not permission to rewrite its
    # unsupported source coverage until the model happens to pick an answer.
    ambiguous_paths = {
        issue.partition(": ")[2]
        for issue in candidate.issues
        if issue.startswith("SOURCE_CONTENT_AMBIGUOUS: ")
    }
    result = []
    for issue in candidate.issues:
        code, _, path = issue.partition(": ")
        if path in ambiguous_paths:
            continue
        structural_missing = code == "PLAN_PARAMETER_REQUIRED" and path.endswith(
            (".independent_signal", ".confirmation", ".execution_window")
        )
        if code not in PROCESSING_ISSUES and not structural_missing:
            continue
        safe_path = path if re.fullmatch(r"[A-Za-z0-9_.\[\]-]{1,256}", path) else ""
        result.append(code + (": " + safe_path if safe_path else ""))
    return tuple(dict.fromkeys(result))[:64]


def correction_context(result):
    """Carry the prior proposal as untrusted data so correction does not start over."""
    output = getattr(result, "output", None) or result
    draft = getattr(output, "draft", None)
    if draft is None:
        return None
    value = {"draft": draft.model_dump(mode="json")}
    operations = getattr(output, "operations", None)
    if operations is not None:
        value["operations"] = [op.model_dump(mode="json") for op in operations]
    mapping = getattr(output, "daily_mapping", None)
    clauses = getattr(output, "clauses", ()) or getattr(mapping, "clauses", ())
    groups = {}
    for clause in clauses:
        meaning = getattr(clause, "semantic_role", None)
        if meaning is None:
            continue
        disposition = "BACKGROUND" if clause.disposition == "CONTEXT" else clause.disposition
        key = (meaning, disposition, clause.reason)
        groups.setdefault(key, []).append(clause.clause_id)
    value["clause_groups"] = [
        dict(clause_ids=ids, meaning=key[0], disposition=key[1], reason=key[2])
        for key, ids in groups.items()
    ]
    if operations is not None and not any(c.remainders or c.exclusions for c in clauses):
        # A focused risk correction reuses prior field attribution losslessly.
        # Group repeated references rather than copying every bound value/span.
        compact_groups = {}
        for clause in clauses:
            meaning = clause.semantic_role or "COMMENTARY"
            disposition = "BACKGROUND" if clause.disposition == "CONTEXT" else clause.disposition
            compact_groups.setdefault((meaning, disposition), []).append(clause.clause_id)
        value["clause_groups"] = [dict(clause_ids=ids, meaning=key[0], disposition=key[1],
            reason="Previous unapproved classification; rechecked against the exact source.")
            for key, ids in compact_groups.items()]
        refs = {}
        for binding in output.bindings:
            if binding.clause_ids:
                refs.setdefault(tuple(binding.clause_ids), []).append(binding.path)
        value["binding_groups"] = [dict(clause_ids=ids, paths=paths)
                                   for ids, paths in refs.items()]
        value["warnings"] = [w.model_dump(mode="json") for w in output.warnings]
        value["risk_scope_correction"] = any(op.target == "risk_branches"
            and (op.intent == "CONTEXT" or op.scope_assessment == "PARTIAL_RULE")
            for op in operations)
        if output.assumptions:
            value.pop("binding_groups")  # A focused correction cannot remove assumptions.
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return encoded if len(encoded) <= 32000 else None
