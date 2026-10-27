"""Narrow inherited scope evidence for current exact ordinary-rule leaves."""

import json
import re
from collections import Counter

from trade_plan_monitor.ai.daily_review import semantic_values
from trade_plan_monitor.ai.source_candidate_models import SourceCandidateAssurance
from trade_plan_monitor.ai.source_coverage_models import CoverageIssue, SourceObligation
from trade_plan_monitor.ai.source_native_support import unsupported_native_paths
from trade_plan_monitor.ai.source_obligations import bounded_clauses, declarations, value_at
from trade_plan_monitor.ai.source_policy_text import declaration_text_supported
from trade_plan_monitor.ai.source_semantic_atoms import semantic_atoms
from trade_plan_monitor.ai.source_semantics import (
    declaration_relations,
    equal_declaration,
    relation_groups,
)
from trade_plan_monitor.ai.update_review import PlanCandidateReview
from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256
from trade_plan_monitor.domain.daily_scope import scope_hash

_LEAF = re.compile(r"ordinary_rules\[(\d+)\]\..+")
_SOURCE_ORIGINS = frozenset({"SOURCE", "SOURCE_INTERPRETATION", "SOURCE_SEMANTIC"})


def _parent_identity(base_review, verified_parent):
    parent = SourceCandidateAssurance.model_validate_json(verified_parent.model_dump_json())
    base = PlanCandidateReview.model_validate_json(base_review.model_dump_json())
    if (parent.binding.review_evidence_hash, parent.content_hash,
        parent.binding.source_id, parent.binding.source_binding_hash) != (
        base.evidence_hash, daily_draft_content_sha256(base.draft),
        base.source_id, base.source_hash,
    ):
        raise ValueError("inherited scope differs from the exact verified predecessor")
    return base, parent


def _exact_leaf(row, values, payload):
    if (row.state != "MAPPED" or row.scope != "UNKNOWN" or row.kind != "PREDICATE"
            or len(row.paths) != 1 or row.semantics_json is None):
        return None
    path = row.paths[0]
    match = _LEAF.fullmatch(path)
    if match is None or path not in values:
        return None
    actual = value_at(payload, path)
    meaning = json.loads(row.semantics_json)
    if isinstance(actual, (dict, list)) or canonical(meaning) != canonical({
        "path": path, "value": actual,
    }):
        return None
    own = declarations(row.excerpt)
    if (len(own) != 1 or own[0].path != path
            or canonical(own[0].value) != canonical(actual)
            or not declaration_text_supported(own[0], values)):
        return None
    return int(match[1]), meaning


def _side_owner(base, parent, index, side):
    path = f"ordinary_rules[{index}].side"
    owner = next((row for row in parent.owners if row.path == path), None)
    bound = next((row for row in base.bindings if row.path == path), None)
    if (owner is None or bound is None or not owner.obligation_ids
            or owner.origin not in {"CURRENT", "BASE", "HUMAN"}
            or bound.binding.origin not in _SOURCE_ORIGINS | {"HUMAN_SUPPLEMENT"}
            or bound.binding.value != side or owner.original_path != bound.original_path
            or owner.source_id != bound.source_id
            or owner.source_binding_hash != bound.source_hash):
        return None
    current_proof = owner.proof_hash == parent.source_assessment.evidence_hash
    supplied = bound.binding.origin == "HUMAN_SUPPLEMENT"
    human = (owner.origin == "HUMAN" or supplied or current_proof
             and parent.source_assessment.origin == "HUMAN")
    if human and not owner.human_receipt_hash:
        return None
    if current_proof and (human_hash := getattr(
        parent.source_assessment, "human_operation_hash", None
    )) is not None and owner.human_receipt_hash != human_hash:
        return None
    # Current source links are available in full and must include the actual side.
    # An inherited owner already belongs to the complete verified parent graph.
    if current_proof:
        rows = {row.obligation_id: row for row in parent.source_assessment.obligations}
        if not any((row := rows.get(identity)) is not None
                   and row.state == ("MAPPED_WITH_REGISTERED_SUPPLEMENT" if supplied else "MAPPED")
                   and row.scope == side
                   and (not supplied or row.semantics_json == canonical(dict(
                       path=owner.original_path, value=None,
                       supplement=bound.supplement.model_dump(mode="json"))))
                   and owner.original_path in row.paths for identity in owner.obligation_ids):
            return None
    return owner


def _current_sides(obligations):
    sides = {}
    for row in obligations:
        meaning = None if row.semantics_json is None else json.loads(row.semantics_json)
        if (row.kind != "PREDICATE" or not isinstance(meaning, dict)
                or set(meaning) != {"path", "value"} or not isinstance(meaning["path"], str)):
            continue
        match = re.fullmatch(r"ordinary_rules\[(\d+)\]\.side", meaning["path"])
        if match is not None:
            sides.setdefault(int(match[1]), set()).add(canonical(meaning["value"]))
    return sides


def _source_key(row):
    return (row.source_hash, row.clause_id, row.start, row.end, row.excerpt, row.kind,
            row.paths, row.semantics_json, row.group_id, row.relation_ids)


def _complete_source_rows(source, values, payload):
    """Independently reconstruct admitted containers/relations from the whole source."""
    if isinstance(source, str) and len(source) > 150_000:
        raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")
    clauses = bounded_clauses(source)
    parsed, digest = declarations(source), scope_hash(source)
    groups = relation_groups(parsed, digest)
    unsupported = unsupported_native_paths(payload)
    expected, counts = {}, Counter()
    for declaration in parsed:
        match = _LEAF.fullmatch(declaration.path)
        own, relations = declaration_relations(declaration, groups)
        container = isinstance(declaration.value, (dict, list)) and bool(declaration.value)
        if (match is None or not (container or own)
                or not equal_declaration(declaration, values, payload)
                or not declaration_text_supported(declaration, values)
                or any(path == declaration.path or path.startswith(declaration.path + ".")
                       or path.startswith(declaration.path + "[") for path in unsupported)):
            continue
        meaning = (dict(path=declaration.path, treatment="COMPLETE_JSON_DECLARATION",
                        source_start=declaration.start, source_end=declaration.end,
                        container_hash=declaration.group_id)
                   if container else dict(path=declaration.path, value=declaration.value))
        atoms = semantic_atoms(source, declaration) if container and not own else ()
        for clause in clauses:
            if not declaration.start <= clause.start < clause.end <= declaration.end:
                continue
            rows = [(clause.start, clause.end, "RELATION" if own else "PREDICATE",
                     declaration.path, meaning, own or declaration.group_id, relations)]
            rows.extend((max(atom.start, clause.start), min(atom.end, clause.end), atom.kind,
                         atom.path, dict(path=atom.path, value=atom.value), atom.group_id,
                         atom.relation_ids) for atom in atoms
                        if atom.start < clause.end and atom.end > clause.start)
            counts[clause.clause_id] += len(rows)
            if counts[clause.clause_id] > 64 or len(expected) + len(rows) > 4096:
                raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")
            for start, end, kind, path, atom_meaning, group, parents in rows:
                semantics = canonical(atom_meaning)
                if len(semantics) > 8192 or len(parents) > 64:
                    raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")
                key = (digest, clause.clause_id, start, end, source[start:end], kind,
                       (path,), semantics, group, parents)
                expected[key] = (int(match[1]), dict(declaration=dict(
                    path=declaration.path, value=declaration.value, start=declaration.start,
                    end=declaration.end, group_id=declaration.group_id), obligation=atom_meaning))
    return expected


def inherit_change_scopes(
    obligations, proposed_draft, base_review, verified_parent, *, source=None,
):
    """Add parent-side evidence only to independently proven complete declarations.

    Container atoms and relations require the full original source; excerpts and
    self-signed mapped labels cannot supply that evidence. This helper does not
    establish coverage or authority. Human provenance comes from the complete parent.
    """
    original = tuple(obligations)
    base, parent = _parent_identity(base_review, verified_parent)
    issues = []

    def issue(code, message, row=None):
        issues.append(CoverageIssue(code=code,
            path="source" if row is None else row.paths[0],
            start=None if row is None else row.start, end=None if row is None else row.end,
            message=message))

    if len(original) > 4096 or any(count > 64 for count in Counter(
        row.clause_id for row in original).values()
    ):
        issue("SOURCE_COVERAGE_LIMIT_EXCEEDED", "Complete scope evidence exceeds its bound.")
        return original, tuple(issues)
    if not parent.coverage_complete or base.issues:
        issue("SOURCE_COVERAGE_REQUIRED", "Inherited scope requires the complete current parent.")
        return original, tuple(issues)
    values, payload = semantic_values(proposed_draft), proposed_draft.executable_payload()
    try:
        source_rows = {} if source is None else _complete_source_rows(source, values, payload)
    except (ValueError, TypeError, RecursionError) as error:
        code = ("SOURCE_COVERAGE_LIMIT_EXCEEDED" if isinstance(error, RecursionError)
                or str(error) == "SOURCE_COVERAGE_LIMIT_EXCEEDED" else "SOURCE_COVERAGE_REQUIRED")
        issue(code, "The complete original source scope graph is unproven within its bound.")
        return original, tuple(issues)
    by_id = {rule.rule_id: index for index, rule in enumerate(base.draft.ordinary_rules)}
    current_sides = _current_sides(original)
    enriched = []
    for old in original:
        SourceObligation.model_validate_json(old.model_dump_json())
        eligible = _exact_leaf(old, values, payload)
        if eligible is None and old.state == "MAPPED" and old.scope == "UNKNOWN":
            eligible = source_rows.get(_source_key(old))
        if eligible is None:
            enriched.append(old)
            continue
        current_index, source_meaning = eligible
        current = proposed_draft.ordinary_rules[current_index]
        index = by_id.get(current.rule_id)
        side = None if index is None else base.draft.ordinary_rules[index].side
        owner = None if index is None else _side_owner(base, parent, index, side)
        if owner is None or side != current.side or any(
            value != canonical(side) for value in current_sides.get(current_index, ())
        ):
            issue("SOURCE_COVERAGE_REQUIRED",
                "The same stable rule has no matching independently proven parent side.", old)
            enriched.append(old)
            continue
        meaning = canonical(dict(source_meaning=source_meaning, inherited_scope=dict(
            parent_assurance_hash=parent.evidence_hash, rule_id=current.rule_id,
            side=side, side_owner=owner.model_dump(mode="json"))))
        if len(meaning) > 8192:
            issue("SOURCE_COVERAGE_LIMIT_EXCEEDED",
                "Complete inherited scope meaning exceeds its bound.", old)
            enriched.append(old)
            continue
        enriched.append(SourceObligation.build(**(
            old.model_dump(mode="python", exclude={"obligation_id"})
            | {"scope": side, "semantics_json": meaning})))
    return tuple(enriched), tuple(issues)
