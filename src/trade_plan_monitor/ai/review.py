"""Deterministic Schema-v3 draft identities and server-owned review snapshots."""

from __future__ import annotations

import json
import re
from hashlib import sha256
from typing import Final

from trade_plan_monitor.ai.models import (
    BindingKind,
    BindingOrigin,
    BindingUnit,
    ClauseDisposition,
    ExplicitPlanDraft,
    FieldBinding,
    PlanMapping,
    RequiredReviewIssue,
    ReviewResolutionKind,
    ServerReviewSnapshot,
    SourceClause,
)

_CLAUSE_BREAKS: Final = frozenset("。！？；;,，\n")
_AMBIGUOUS_TERMS: Final = ("企稳", "放量", "受阻")
_UNSUPPORTED_TERMS: Final = ("有效跌破",)
_SEQUENCING_PATTERN: Final = re.compile(r"(?:先.+(?:再|后|然后)|(?:之后|随后).+)")
_COMPLETED_FIVE_MINUTE_MARKERS: Final = ("已完成五分钟K线", "已完成5分钟K线")
_GLOBAL_FIVE_MINUTE_CONTEXT: Final = re.compile(
    r"(?:仅|只)(?:监控|使用|基于|按照)(?:已完成的?)?(?:五分钟|5分钟)K线"
)
_VOLUME_DEFINITION_RATIO: Final = re.compile(r"(?:不少于|大于等于|达到).+?[0-9]+(?:\.[0-9]+)?倍")
_VOLUME_DEFINITION_WINDOW: Final = re.compile(r"(?:此前|前)[0-9]+根")
_BREAKDOWN_DEFINITION_PRICE: Final = re.compile(r"低于[0-9]+(?:\.[0-9]+)?元")
_PATH_PART: Final = re.compile(r"(?:^|\.)([A-Za-z_][A-Za-z0-9_-]*)|\[([0-9]+)\]")
_TECHNICAL_PATHS: Final = frozenset(
    {
        "schema_version",
        "execution_mode",
        "execution_version",
        "plan_id",
        "version",
        "name",
        "market",
        "position.inventory_scope",
        "position.lot_size",
        "monitoring.indicator_formula_version",
    }
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def dump_explicit_plan_draft_json(draft: ExplicitPlanDraft) -> str:
    if not isinstance(draft, ExplicitPlanDraft):
        raise TypeError("draft must be an ExplicitPlanDraft")
    return _canonical_json(draft.model_dump(mode="json"))


def load_explicit_plan_draft_json(document: str | bytes) -> ExplicitPlanDraft:
    if not isinstance(document, str | bytes):
        raise TypeError("document must be text or bytes")
    if isinstance(document, bytes):
        document = document.decode("utf-8")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    json.loads(
        document,
        object_pairs_hook=reject_duplicates,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
    )
    return ExplicitPlanDraft.model_validate_json(document)


def explicit_draft_sha256(draft: ExplicitPlanDraft) -> str:
    """Hash the exact canonical partial document without relabeling legacy hashes."""

    return sha256(dump_explicit_plan_draft_json(draft).encode("utf-8")).hexdigest()


def explicit_draft_content_sha256(draft: ExplicitPlanDraft) -> str:
    """Hash current Schema-v3 meaning, excluding only E07 metadata fields."""

    if not isinstance(draft, ExplicitPlanDraft):
        raise TypeError("draft must be an ExplicitPlanDraft")
    content = draft.model_dump(mode="json")
    for field in ("version", "name", "metadata", "plan_id"):
        content.pop(field)
    preimage = b"plan-review-content-v1\x00" + _canonical_json(content).encode("utf-8")
    return sha256(preimage).hexdigest()


def server_source_clauses(source_text: str) -> tuple[SourceClause, ...]:
    """Split exact Unicode text into bounded, stable code-point spans."""

    if not isinstance(source_text, str) or not source_text.strip():
        raise ValueError("source_text must be non-blank text")
    source_text.encode("utf-8")
    spans: list[tuple[int, int]] = []
    start = 0
    for index, character in enumerate(source_text):
        if character in _CLAUSE_BREAKS:
            spans.append((start, index + 1))
            start = index + 1
    if start < len(source_text):
        spans.append((start, len(source_text)))
    clauses: list[SourceClause] = []
    for raw_start, raw_end in spans:
        while raw_start < raw_end and source_text[raw_start].isspace():
            raw_start += 1
        while raw_end > raw_start and source_text[raw_end - 1].isspace():
            raw_end -= 1
        if raw_start == raw_end:
            continue
        chunk_start = raw_start
        while chunk_start < raw_end:
            chunk_end = min(chunk_start + 512, raw_end)
            excerpt = source_text[chunk_start:chunk_end]
            clause_id = (
                "clause-"
                + sha256(
                    f"plan-source-clause-v1\x00{chunk_start}\x00{chunk_end}\x00{excerpt}".encode()
                ).hexdigest()[:16]
            )
            clauses.append(
                SourceClause(
                    clause_id=clause_id,
                    start=chunk_start,
                    end=chunk_end,
                    excerpt=excerpt,
                    disposition=ClauseDisposition.UNRESOLVED,
                    paths=(),
                )
            )
            chunk_start = chunk_end
    if not clauses:
        raise ValueError("source_text has no material clauses")
    return tuple(clauses)


def build_server_review_snapshot(
    *,
    draft: ExplicitPlanDraft,
    mapping: PlanMapping,
    source_text: str | None = None,
    source_text_sha256: str | None = None,
) -> ServerReviewSnapshot:
    """Validate a bidirectional map and derive all activation blockers server-side."""

    if not isinstance(draft, ExplicitPlanDraft):
        raise TypeError("draft must be an ExplicitPlanDraft")
    if not isinstance(mapping, PlanMapping):
        raise TypeError("mapping must be a PlanMapping")
    if source_text is not None:
        source_hash = sha256(source_text.encode("utf-8")).hexdigest()
        _validate_source_clauses(mapping, server_source_clauses(source_text))
    elif source_text_sha256 is not None and re.fullmatch(r"[0-9a-f]{64}", source_text_sha256):
        source_hash = source_text_sha256
    else:
        raise ValueError("exact source text or its validated SHA-256 is required")

    data = draft.model_dump(mode="json")
    issues: list[RequiredReviewIssue] = []
    clauses = {item.clause_id: item for item in mapping.source_clauses}
    supplements = {item.supplement_id: item for item in mapping.user_supplements}
    binding_by_identity = {(item.binding_kind, item.path): item for item in mapping.field_bindings}
    defined_terms = _supported_defined_terms(source_text or "")
    has_global_five_minute_context = bool(
        source_text and _GLOBAL_FIVE_MINUTE_CONTEXT.search(source_text)
    )

    for binding in mapping.field_bindings:
        actual = _resolve_path(data, binding.path)
        expected = actual.get("type") if binding.binding_kind is BindingKind.STRUCTURE else actual
        if binding.unit != _binding_unit_for_path(binding.path, binding.binding_kind):
            raise ValueError("field binding unit does not match the typed plan path")
        if binding.binding_kind is BindingKind.VALUE and isinstance(actual, dict | list):
            raise ValueError("value binding must address a scalar plan field")
        if type(expected) is not type(binding.value) or expected != binding.value:
            raise ValueError("field binding does not match the current typed draft value")
        if binding.origin is BindingOrigin.SOURCE:
            for clause_id in binding.clause_ids:
                clause = clauses.get(clause_id)
                if clause is None or clause.disposition.value != "MAPPED":
                    raise ValueError("SOURCE binding references a non-mapped clause")
                if binding.path not in clause.paths:
                    raise ValueError("SOURCE binding path is absent from its source clause")
        elif binding.origin is BindingOrigin.USER_SUPPLEMENT:
            supplement = supplements.get(binding.supplement_id or "")
            if (
                supplement is None
                or supplement.path != binding.path
                or type(supplement.value) is not type(binding.value)
                or supplement.value != binding.value
                or supplement.unit is not binding.unit
            ):
                raise ValueError("USER_SUPPLEMENT binding does not match its durable supplement")
        elif binding.path not in _TECHNICAL_PATHS and not binding.path.endswith(".rule_id"):
            raise ValueError("CONTRACT binding cannot supply a trading parameter")

    for path in _non_null_scalar_paths(data):
        if (BindingKind.VALUE, path) not in binding_by_identity:
            issues.append(
                _issue(
                    "UNMAPPED_PLAN_FIELD",
                    path,
                    "The current non-null plan field has no validated origin binding.",
                    allowed=(ReviewResolutionKind.REPLACED_BY_REVIEWED_CONTENT,),
                )
            )
    for path in _logical_paths(data):
        if (BindingKind.STRUCTURE, path) not in binding_by_identity:
            issues.append(
                _issue(
                    "UNMAPPED_PLAN_STRUCTURE",
                    path,
                    "The current ALL/ANY parent-child structure has no origin binding.",
                    allowed=(ReviewResolutionKind.REPLACED_BY_REVIEWED_CONTENT,),
                )
            )

    referenced_clause_paths = {
        (clause_id, binding.path)
        for binding in mapping.field_bindings
        if binding.origin is BindingOrigin.SOURCE
        for clause_id in binding.clause_ids
    }
    for clause in mapping.source_clauses:
        if clause.disposition.value == "MAPPED":
            for path in clause.paths:
                if (clause.clause_id, path) not in referenced_clause_paths:
                    issues.append(
                        _issue(
                            "UNMAPPED_MATERIAL_SOURCE",
                            path,
                            "A claimed source destination has no reciprocal current-value binding.",
                            clause_id=clause.clause_id,
                            allowed=(ReviewResolutionKind.REPLACED_BY_REVIEWED_CONTENT,),
                        )
                    )
            for binding in mapping.field_bindings:
                if (
                    binding.origin is BindingOrigin.SOURCE
                    and clause.clause_id in binding.clause_ids
                ):
                    issues.append(
                        _issue(
                            "SOURCE_MAPPING_REVIEW_REQUIRED",
                            binding.path,
                            "Review this source clause against the current typed value "
                            "and meaning.",
                            clause_id=clause.clause_id,
                            binding_path=binding.path,
                            allowed=(ReviewResolutionKind.CONFIRM_MAPPING,),
                        )
                    )
        else:
            code = (
                "UNRESOLVED_SEMANTICS"
                if clause.disposition.value == "UNRESOLVED"
                else "UNSUPPORTED_SEMANTICS"
            )
            issues.append(
                _issue(
                    code,
                    "source",
                    "The material source clause is not represented by supported current content.",
                    clause_id=clause.clause_id,
                    allowed=(ReviewResolutionKind.REPLACED_BY_REVIEWED_CONTENT,),
                )
            )
        issues.extend(
            _semantic_phrase_issues(
                clause,
                defined_terms=defined_terms,
                has_global_five_minute_context=has_global_five_minute_context,
            )
        )

    if source_text is not None and _SEQUENCING_PATTERN.search(source_text):
        issues.append(
            _issue(
                "UNSUPPORTED_SEMANTICS",
                "source",
                "The source requests unsupported cross-clause sequencing semantics.",
                allowed=(ReviewResolutionKind.REPLACED_BY_REVIEWED_CONTENT,),
            )
        )

    for path in _unresolved_required_paths(draft):
        issues.append(
            _issue(
                "UNRESOLVED_EXECUTION_POLICY",
                path,
                "A required executable value or policy remains unresolved.",
                allowed=(ReviewResolutionKind.CONFIRM_POLICY,),
            )
        )

    for binding in mapping.field_bindings:
        if binding.origin is BindingOrigin.USER_SUPPLEMENT:
            issues.append(
                _issue(
                    "USER_SUPPLEMENT_REVIEW_REQUIRED",
                    binding.path,
                    "Confirm the separately supplied current value or policy.",
                    binding_path=binding.path,
                    allowed=(ReviewResolutionKind.CONFIRM_POLICY,),
                )
            )

    required_issues = _unique_sorted_issues(issues)
    evidence_payload = {
        "mappingVersion": mapping.mapping_version,
        "sourceClauses": [item.model_dump(mode="json") for item in mapping.source_clauses],
        "fieldBindings": [item.model_dump(mode="json") for item in mapping.field_bindings],
        "userSupplements": [item.model_dump(mode="json") for item in mapping.user_supplements],
        "requiredIssues": [
            {
                "issueId": item.issue_id,
                "code": item.code,
                "path": item.path,
                "reason": item.reason,
                "clauseId": item.clause_id,
                "bindingPath": item.binding_path,
                "allowedResolutions": [value.value for value in item.allowed_resolutions],
            }
            for item in required_issues
        ],
    }
    evidence_hash = sha256(
        b"plan-review-evidence-v1\x00" + _canonical_json(evidence_payload).encode("utf-8")
    ).hexdigest()
    return ServerReviewSnapshot(
        source_hash=source_hash,
        content_hash=explicit_draft_content_sha256(draft),
        review_evidence_hash=evidence_hash,
        mapping=mapping,
        required_issues=required_issues,
        can_activate=draft.to_executable() is not None and not required_issues,
    )


def reconcile_plan_mapping(
    *,
    draft: ExplicitPlanDraft,
    mapping: PlanMapping,
) -> PlanMapping:
    """Drop stale value claims after an edit while retaining valid provenance."""

    data = draft.model_dump(mode="json")
    retained: list[FieldBinding] = []
    for binding in mapping.field_bindings:
        try:
            actual = _resolve_path(data, binding.path)
        except ValueError:
            continue
        expected = actual.get("type") if binding.binding_kind is BindingKind.STRUCTURE else actual
        if type(expected) is type(binding.value) and expected == binding.value:
            retained.append(binding)
    source_paths = {
        current_clause_id: {
            binding.path
            for binding in retained
            if binding.origin is BindingOrigin.SOURCE and current_clause_id in binding.clause_ids
        }
        for current_clause_id in (clause.clause_id for clause in mapping.source_clauses)
    }
    clauses = tuple(
        clause.model_copy(
            update={
                "disposition": (
                    ClauseDisposition.MAPPED
                    if source_paths[clause.clause_id]
                    else ClauseDisposition.UNRESOLVED
                ),
                "paths": tuple(
                    path for path in clause.paths if path in source_paths[clause.clause_id]
                ),
            }
        )
        for clause in mapping.source_clauses
    )
    return PlanMapping(
        mapping_version=mapping.mapping_version,
        source_clauses=clauses,
        field_bindings=tuple(retained),
        user_supplements=mapping.user_supplements,
    )


def _validate_source_clauses(
    mapping: PlanMapping,
    expected: tuple[SourceClause, ...],
) -> None:
    if len(mapping.source_clauses) != len(expected):
        raise ValueError("mapping must enumerate every server source clause")
    for actual, server in zip(mapping.source_clauses, expected, strict=True):
        if (
            actual.clause_id != server.clause_id
            or actual.start != server.start
            or actual.end != server.end
            or actual.excerpt != server.excerpt
        ):
            raise ValueError("mapping source clauses do not match the exact source text")


def _resolve_path(value: object, path: str) -> object:
    current = value
    cursor = 0
    for match in _PATH_PART.finditer(path):
        if match.start() != cursor:
            raise ValueError("binding path syntax is invalid")
        key, index = match.groups()
        if key is not None:
            if not isinstance(current, dict) or key not in current:
                raise ValueError("binding path does not exist in the current draft")
            current = current[key]
        else:
            item_index = int(index)
            if not isinstance(current, list) or item_index >= len(current):
                raise ValueError("binding path does not exist in the current draft")
            current = current[item_index]
        cursor = match.end()
    if cursor != len(path):
        raise ValueError("binding path syntax is invalid")
    return current


def _binding_unit_for_path(path: str, binding_kind: BindingKind) -> BindingUnit:
    if binding_kind is BindingKind.STRUCTURE:
        return BindingUnit.NONE
    leaf = path.rsplit(".", 1)[-1]
    if leaf.endswith("_fen"):
        return BindingUnit.FEN
    if leaf in {"quantity", "max_qty", "lot_size"}:
        return BindingUnit.SHARES
    if leaf == "window_bars":
        return BindingUnit.BARS
    if leaf == "timeframe_minutes":
        return BindingUnit.MINUTES
    if leaf == "minimum_ratio":
        return BindingUnit.RATIO
    return BindingUnit.NONE


def _non_null_scalar_paths(value: object, path: str = "") -> tuple[str, ...]:
    if isinstance(value, dict):
        return tuple(
            nested
            for key, child in value.items()
            for nested in _non_null_scalar_paths(child, f"{path}.{key}" if path else key)
        )
    if isinstance(value, list):
        return tuple(
            nested
            for index, child in enumerate(value)
            for nested in _non_null_scalar_paths(child, f"{path}[{index}]")
        )
    return () if value is None else (path,)


def _logical_paths(value: object, path: str = "") -> tuple[str, ...]:
    paths: list[str] = []
    if isinstance(value, dict):
        if value.get("type") in {"ALL", "ANY"}:
            paths.append(path)
        for key, child in value.items():
            paths.extend(_logical_paths(child, f"{path}.{key}" if path else key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_logical_paths(child, f"{path}[{index}]"))
    return tuple(paths)


def _unresolved_required_paths(draft: ExplicitPlanDraft) -> tuple[str, ...]:
    data = draft.model_dump(mode="json")
    paths = [
        "activation",
        "position.inventory_scope",
        "position.lot_size",
        "position.max_qty",
        "monitoring.timeframe_minutes",
        "monitoring.indicator_formula_version",
        "conflict_policy",
    ]
    unresolved = [path for path in paths if _resolve_path(data, path) is None]
    for index, rule in enumerate(data["rules"]):
        prefix = f"rules[{index}]"
        for suffix in ("condition", "confirmation", "repeat_policy"):
            path = f"{prefix}.{suffix}"
            if _resolve_path(data, path) is None:
                unresolved.append(path)
        unresolved.extend(_nested_null_paths(rule.get("condition"), f"{prefix}.condition"))
        unresolved.extend(_nested_null_paths(rule.get("action"), f"{prefix}.action"))
        unresolved.extend(_nested_null_paths(rule.get("confirmation"), f"{prefix}.confirmation"))
    if data["conflict_policy"] is not None:
        unresolved.extend(_nested_null_paths(data["conflict_policy"], "conflict_policy"))
    return tuple(sorted(set(unresolved)))


def _nested_null_paths(value: object, path: str) -> tuple[str, ...]:
    if isinstance(value, dict):
        return tuple(
            nested
            for key, child in value.items()
            if key != "safety_conditions"
            for nested in _nested_null_paths(child, f"{path}.{key}")
        )
    if isinstance(value, list):
        return tuple(
            nested
            for index, child in enumerate(value)
            for nested in _nested_null_paths(child, f"{path}[{index}]")
        )
    return (path,) if value is None else ()


def _supported_defined_terms(source_text: str) -> frozenset[str]:
    defined: set[str] = set()
    for clause in server_source_clauses(source_text) if source_text else ():
        excerpt = clause.excerpt
        has_completed_five_minutes = any(
            marker in excerpt for marker in _COMPLETED_FIVE_MINUTE_MARKERS
        )
        if (
            re.search(r"放量[”\"]?定义为", excerpt)
            and has_completed_five_minutes
            and "算术平均值" in excerpt
            and _VOLUME_DEFINITION_WINDOW.search(excerpt)
            and _VOLUME_DEFINITION_RATIO.search(excerpt)
        ):
            defined.add("放量")
        if (
            re.search(r"有效跌破[”\"]?定义为", excerpt)
            and has_completed_five_minutes
            and "收盘" in excerpt
            and _BREAKDOWN_DEFINITION_PRICE.search(excerpt)
        ):
            defined.add("有效跌破")
    return frozenset(defined)


def _semantic_phrase_issues(
    clause: SourceClause,
    *,
    defined_terms: frozenset[str],
    has_global_five_minute_context: bool,
) -> tuple[RequiredReviewIssue, ...]:
    issues: list[RequiredReviewIssue] = []
    for term in _AMBIGUOUS_TERMS:
        if term in clause.excerpt and term not in defined_terms:
            issues.append(
                _issue(
                    "UNRESOLVED_SEMANTICS",
                    "source",
                    f"The phrase {term} has no deterministic supported definition.",
                    clause_id=clause.clause_id,
                    allowed=(ReviewResolutionKind.REPLACED_BY_REVIEWED_CONTENT,),
                )
            )
    if any(
        term in clause.excerpt and term not in defined_terms for term in _UNSUPPORTED_TERMS
    ) or _SEQUENCING_PATTERN.search(clause.excerpt):
        issues.append(
            _issue(
                "UNSUPPORTED_SEMANTICS",
                "source",
                "The clause requests unsupported confirmation or sequencing semantics.",
                clause_id=clause.clause_id,
                allowed=(ReviewResolutionKind.REPLACED_BY_REVIEWED_CONTENT,),
            )
        )
    if (
        "收盘" in clause.excerpt
        and not has_global_five_minute_context
        and not any(marker in clause.excerpt for marker in ("五分钟", "5分钟", "5m", "5M"))
    ):
        issues.append(
            _issue(
                "UNSUPPORTED_SEMANTICS",
                "source",
                "An unqualified close does not select the supported five-minute confirmation.",
                clause_id=clause.clause_id,
                allowed=(ReviewResolutionKind.REPLACED_BY_REVIEWED_CONTENT,),
            )
        )
    return tuple(issues)


def _issue(
    code: str,
    path: str,
    reason: str,
    *,
    allowed: tuple[ReviewResolutionKind, ...],
    clause_id: str | None = None,
    binding_path: str | None = None,
) -> RequiredReviewIssue:
    identity = _canonical_json(
        {
            "bindingPath": binding_path,
            "clauseId": clause_id,
            "code": code,
            "path": path,
            "reason": reason,
        }
    )
    return RequiredReviewIssue(
        issue_id=(
            "issue-" + sha256(b"plan-review-issue-v1\x00" + identity.encode()).hexdigest()[:24]
        ),
        code=code,
        path=path,
        reason=reason,
        clause_id=clause_id,
        binding_path=binding_path,
        allowed_resolutions=allowed,
    )


def _unique_sorted_issues(
    issues: list[RequiredReviewIssue],
) -> tuple[RequiredReviewIssue, ...]:
    unique = {item.issue_id: item for item in issues}
    if len(unique) > 512:
        raise ValueError("server review issue limit exceeded")
    return tuple(sorted(unique.values(), key=lambda item: (item.path, item.code, item.issue_id)))


__all__ = [
    "build_server_review_snapshot",
    "dump_explicit_plan_draft_json",
    "explicit_draft_content_sha256",
    "explicit_draft_sha256",
    "load_explicit_plan_draft_json",
    "reconcile_plan_mapping",
    "server_source_clauses",
]
