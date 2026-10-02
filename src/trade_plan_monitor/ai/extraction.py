"""Bounded parsing and validation for untrusted AI plan output.

JSON is preflighted with Python's duplicate-key and non-finite hooks, then validated
through Pydantic's JSON-aware strict model path:
https://docs.python.org/3.14/library/json.html
https://docs.pydantic.dev/latest/concepts/json/
"""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Final
from uuid import UUID

from pydantic import ValidationError

from trade_plan_monitor.ai.models import (
    DIAGNOSTIC_SCHEMA_FIELDS,
    AIProviderConfig,
    AIUsageSnapshot,
    ExtractionDiagnostic,
    PlanExtractionOutput,
    PlanExtractionOutputV4,
    PlanExtractionResult,
    PlanExtractionStatus,
    UnmappedText,
)
from trade_plan_monitor.ai.prompts import (
    PLAN_EXTRACTION_PROMPT_V4,
    PLAN_EXTRACTION_PROMPT_V5,
    PLAN_EXTRACTION_PROMPT_V6,
    build_plan_extraction_prompt,
)
from trade_plan_monitor.ai.provider import (
    AIProvider,
    AIProviderError,
    PlanExtractionRequest,
    RawAIResponse,
)
from trade_plan_monitor.ai.review import MappingValidationError, build_server_review_snapshot
from trade_plan_monitor.domain.plan_validation import (
    ALL_MARKET_EVIDENCE,
    DraftReviewIssue,
    ReviewIssueKind,
    ValidationIssue,
    ValidationSeverity,
    validate_trade_plan,
)

MAX_EXTRACTION_OUTPUT_BYTES: Final = 1_048_576
MAX_EXTRACTION_JSON_NODES: Final = 10_000
MAX_EXTRACTION_JSON_DEPTH: Final = 64
MIN_FIELD_EVIDENCE_CHARS: Final = 4


class _UntrustedOutputError(ValueError):
    """Internal closed category; never carry untrusted content across the boundary."""

    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


async def extract_plan(
    *,
    request_id: UUID,
    source_text: str,
    config: AIProviderConfig,
    provider: AIProvider,
) -> PlanExtractionResult:
    """Extract one review-only draft without persistence or activation side effects."""

    prompt = build_plan_extraction_prompt(
        source_text,
        prompt_version=config.prompt_version,
    )
    source_text_bytes: bytes | None = None
    try:
        source_text_bytes = source_text.encode("utf-8")
    except UnicodeEncodeError:
        pass
    if source_text_bytes is None:
        raise ValueError("source_text must be valid UTF-8")
    source_text_sha256 = sha256(source_text_bytes).hexdigest()
    try:
        request = PlanExtractionRequest(
            request_id=request_id,
            config=config,
            prompt=prompt,
        )
    except ValidationError:
        return _failure_result(
            request_id=request_id,
            config=config,
            source_text_sha256=source_text_sha256,
            status=PlanExtractionStatus.INVALID_OUTPUT,
            issue_code="AI_INPUT_TOO_LARGE",
            issue_path="source_text",
            issue_message="The source text and extraction schema exceed the input limit.",
            stage="request",
            reason="INPUT_LIMIT",
        )

    try:
        raw = await provider.extract_plan(request)
    except AIProviderError as error:
        return _failure_result(
            request_id=request_id,
            config=config,
            source_text_sha256=source_text_sha256,
            status=PlanExtractionStatus.PROVIDER_ERROR,
            issue_code="AI_PROVIDER_ERROR",
            issue_path="provider",
            issue_message="AI provider extraction failed.",
            stage="provider",
            reason="PROVIDER_ERROR",
            provider_error_code=error.code.value,
            transient_kind=(
                error.transient_kind.value if error.transient_kind is not None else None
            ),
            attempts=error.attempts,
            timeout_kind=(error.timeout_kind.value if error.timeout_kind is not None else None),
            timeout_elapsed_ms=error.timeout_elapsed_ms,
        )

    if raw.request_id != request_id or raw.provider_id != config.provider_id:
        return _failure_result(
            request_id=request_id,
            config=config,
            source_text_sha256=source_text_sha256,
            status=PlanExtractionStatus.INVALID_OUTPUT,
            issue_code="AI_OUTPUT_INVALID",
            issue_path="draft",
            issue_message="AI output did not satisfy the extraction contract.",
            raw=raw,
            stage="response",
            reason="ENVELOPE_MISMATCH",
        )

    if raw.finish_reason != "stop":
        truncated = raw.finish_reason == "length"
        return _failure_result(
            request_id=request_id,
            config=config,
            source_text_sha256=source_text_sha256,
            status=PlanExtractionStatus.INVALID_OUTPUT,
            issue_code="AI_OUTPUT_TRUNCATED" if truncated else "AI_OUTPUT_INVALID",
            issue_path="draft",
            issue_message=(
                "AI output was truncated before completion; no draft was created."
                if truncated
                else "AI output did not satisfy the extraction contract."
            ),
            raw=raw,
            stage="response",
            reason="FINISH_REASON",
        )

    try:
        output = _parse_untrusted_output(raw.content, prompt_version=config.prompt_version)
    except _UntrustedOutputError as error:
        return _failure_result(
            request_id=request_id,
            config=config,
            source_text_sha256=source_text_sha256,
            status=PlanExtractionStatus.INVALID_OUTPUT,
            issue_code="AI_OUTPUT_INVALID",
            issue_path="draft",
            issue_message="AI output did not satisfy the extraction contract.",
            raw=raw,
            stage="json",
            reason=error.category,
        )
    except json.JSONDecodeError:
        return _failure_result(
            request_id=request_id,
            config=config,
            source_text_sha256=source_text_sha256,
            status=PlanExtractionStatus.INVALID_OUTPUT,
            issue_code="AI_OUTPUT_INVALID",
            issue_path="draft",
            issue_message="AI output did not satisfy the extraction contract.",
            raw=raw,
            stage="json",
            reason="JSON_SYNTAX",
        )
    except ValidationError as error:
        return _failure_result(
            request_id=request_id,
            config=config,
            source_text_sha256=source_text_sha256,
            status=PlanExtractionStatus.INVALID_OUTPUT,
            issue_code="AI_OUTPUT_INVALID",
            issue_path="draft",
            issue_message="AI output did not satisfy the extraction contract.",
            raw=raw,
            stage="schema",
            reason="SCHEMA",
            diagnostic_path=_safe_schema_path(error),
            schema_error_type=_safe_schema_error_type(error),
        )
    except UnicodeError:
        return _failure_result(
            request_id=request_id,
            config=config,
            source_text_sha256=source_text_sha256,
            status=PlanExtractionStatus.INVALID_OUTPUT,
            issue_code="AI_OUTPUT_INVALID",
            issue_path="draft",
            issue_message="AI output did not satisfy the extraction contract.",
            raw=raw,
            stage="json",
            reason="JSON_ENCODING",
        )
    except RecursionError:
        return _failure_result(
            request_id=request_id,
            config=config,
            source_text_sha256=source_text_sha256,
            status=PlanExtractionStatus.INVALID_OUTPUT,
            issue_code="AI_OUTPUT_INVALID",
            issue_path="draft",
            issue_message="AI output did not satisfy the extraction contract.",
            raw=raw,
            stage="json",
            reason="JSON_RECURSION",
        )
    except ValueError:
        return _failure_result(
            request_id=request_id,
            config=config,
            source_text_sha256=source_text_sha256,
            status=PlanExtractionStatus.INVALID_OUTPUT,
            issue_code="AI_OUTPUT_INVALID",
            issue_path="draft",
            issue_message="AI output did not satisfy the extraction contract.",
            raw=raw,
            stage="json",
            reason="JSON_OTHER",
        )

    from trade_plan_monitor.ai.daily_extraction import DailyExtractionOutput, DailyExtractionResult

    if isinstance(output, DailyExtractionOutput):
        try:
            snapshot = output.review(source_text)
        except TypeError, ValueError, RecursionError:
            return _failure_result(
                request_id=request_id,
                config=config,
                source_text_sha256=source_text_sha256,
                status=PlanExtractionStatus.INVALID_OUTPUT,
                issue_code="AI_FIELD_EVIDENCE_INVALID",
                issue_path="mapping",
                issue_message="Daily source mapping is invalid.",
                raw=raw,
                stage="mapping",
                reason="MAPPING",
            )
        return DailyExtractionResult(
            request_id=request_id,
            provider_id=raw.provider_id,
            model=config.model,
            prompt_version=config.prompt_version,
            source_text_sha256=source_text_sha256,
            draft=output.draft,
            daily_mapping=snapshot.mapping,
            assumptions=output.assumptions,
            warnings=output.warnings,
            validation_issues=tuple(
                _blocking_warning(i.code, i.path, i.reason) for i in snapshot.issues
            ),
            usage=_usage_snapshot(raw),
            diagnostic=_diagnostic(
                stage="completed", reason="NONE", raw=raw, configured_model=config.model
            ),
            status=PlanExtractionStatus.SUCCEEDED,
        )

    if isinstance(output, PlanExtractionOutputV4):
        try:
            mapping = output.to_mapping()
            snapshot = build_server_review_snapshot(
                source_text=source_text,
                draft=output.draft,
                mapping=mapping,
            )
        except (TypeError, UnicodeError, ValueError, RecursionError) as error:
            return _failure_result(
                request_id=request_id,
                config=config,
                source_text_sha256=source_text_sha256,
                status=PlanExtractionStatus.INVALID_OUTPUT,
                issue_code="AI_FIELD_EVIDENCE_INVALID",
                issue_path="mapping",
                issue_message="AI mapping did not match the submitted source and current draft.",
                raw=raw,
                stage="mapping",
                reason="MAPPING",
                diagnostic_path=(
                    error.path
                    if isinstance(error, MappingValidationError)
                    else _safe_schema_path(error)
                    if isinstance(error, ValidationError)
                    else "mapping"
                ),
                schema_error_type=(
                    _safe_schema_error_type(error) if isinstance(error, ValidationError) else None
                ),
            )
        validation_issues = tuple(
            _blocking_warning(issue.code, issue.path, issue.reason)
            for issue in snapshot.required_issues
        )
        return PlanExtractionResult(
            request_id=request_id,
            provider_id=raw.provider_id,
            model=config.model,
            prompt_version=config.prompt_version,
            source_text_sha256=source_text_sha256,
            draft=output.draft,
            mapping=mapping,
            assumptions=output.assumptions,
            warnings=output.warnings,
            validation_issues=validation_issues,
            usage=_usage_snapshot(raw),
            diagnostic=_diagnostic(
                stage="completed", reason="NONE", raw=raw, configured_model=config.model
            ),
            status=PlanExtractionStatus.SUCCEEDED,
        )

    evidence_issue = _validate_provenance(output, source_text)
    if evidence_issue is not None:
        return _failure_result(
            request_id=request_id,
            config=config,
            source_text_sha256=source_text_sha256,
            status=PlanExtractionStatus.INVALID_OUTPUT,
            issue_code=evidence_issue.code,
            issue_path=_safe_path(evidence_issue.path),
            issue_message=evidence_issue.message,
            raw=raw,
            stage="evidence",
            reason="FIELD_EVIDENCE",
            diagnostic_path=_safe_path(evidence_issue.path),
        )

    unmapped_text = tuple(
        UnmappedText(
            path=issue.path,
            excerpt=issue.excerpt,
            reason=issue.reason,
            material=True,
            start=issue.start,
            end=issue.end,
        )
        for issue in output.unmapped_text
    )
    review_issues = (
        *(
            DraftReviewIssue(
                kind=ReviewIssueKind.ASSUMPTION,
                path=issue.path,
                material=issue.material,
            )
            for issue in output.assumptions
        ),
        *(
            DraftReviewIssue(
                kind=ReviewIssueKind.WARNING,
                path=issue.path,
                material=issue.material,
            )
            for issue in output.warnings
        ),
        *(
            DraftReviewIssue(
                kind=ReviewIssueKind.UNMAPPED_TEXT,
                path=issue.path,
                material=True,
            )
            for issue in unmapped_text
        ),
    )
    validation = validate_trade_plan(
        output.draft,
        available_market_evidence=ALL_MARKET_EVIDENCE,
        review_issues=review_issues,
    )
    return PlanExtractionResult(
        request_id=request_id,
        provider_id=raw.provider_id,
        model=config.model,
        prompt_version=config.prompt_version,
        source_text_sha256=source_text_sha256,
        draft=output.draft,
        evidence=output.evidence,
        assumptions=output.assumptions,
        warnings=output.warnings,
        unmapped_text=unmapped_text,
        validation_issues=(
            *validation.issues,
            _blocking_warning(
                "AI_EVIDENCE_REVIEW_REQUIRED",
                "draft",
                "Review AI field evidence before activation.",
            ),
        ),
        usage=_usage_snapshot(raw),
        diagnostic=_diagnostic(
            stage="completed", reason="NONE", raw=raw, configured_model=config.model
        ),
        status=PlanExtractionStatus.SUCCEEDED,
    )


def _parse_untrusted_output(
    content: str,
    *,
    prompt_version: str,
) -> PlanExtractionOutput | PlanExtractionOutputV4:
    if len(content.encode("utf-8")) > MAX_EXTRACTION_OUTPUT_BYTES:
        raise _UntrustedOutputError("JSON_BUDGET")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise _UntrustedOutputError("JSON_DUPLICATE_KEY")
            result[key] = value
        return result

    def reject_non_finite(value: str) -> None:
        raise _UntrustedOutputError("JSON_NON_FINITE")

    parsed = json.loads(
        content,
        object_pairs_hook=reject_duplicates,
        parse_constant=reject_non_finite,
    )
    _enforce_json_budget(parsed)
    normalized = json.dumps(
        parsed,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    if prompt_version == "plan-extract-v7":
        from trade_plan_monitor.ai.daily_extraction import DailyExtractionOutput

        return DailyExtractionOutput.model_validate_json(normalized)
    model = (
        PlanExtractionOutputV4
        if prompt_version
        in {
            PLAN_EXTRACTION_PROMPT_V4,
            PLAN_EXTRACTION_PROMPT_V5,
            PLAN_EXTRACTION_PROMPT_V6,
        }
        else PlanExtractionOutput
    )
    return model.model_validate_json(normalized)


def _enforce_json_budget(value: object) -> None:
    stack: list[tuple[object, int]] = [(value, 1)]
    nodes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > MAX_EXTRACTION_JSON_NODES:
            raise _UntrustedOutputError("JSON_BUDGET")
        if depth > MAX_EXTRACTION_JSON_DEPTH:
            raise _UntrustedOutputError("JSON_BUDGET")
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)


def _validate_provenance(
    output: PlanExtractionOutput,
    source_text: str,
) -> ValidationIssue | None:
    required_paths = set(_leaf_paths(output.draft.model_dump(mode="json", exclude_none=True)))
    supplied_paths = [item.path for item in output.evidence]
    supplied_path_set = set(supplied_paths)

    missing = sorted(required_paths - supplied_path_set)
    if missing:
        return _blocking_error(
            "AI_FIELD_EVIDENCE_MISSING",
            missing[0],
            "Every draft field requires source evidence.",
        )
    if len(supplied_paths) != len(supplied_path_set) or supplied_path_set != required_paths:
        return _blocking_error(
            "AI_FIELD_EVIDENCE_INVALID",
            "evidence",
            "Field evidence must map exactly once to each draft field.",
        )
    for evidence in output.evidence:
        if len(evidence.excerpt) < MIN_FIELD_EVIDENCE_CHARS or not _excerpt_matches_source(
            source_text,
            evidence.excerpt,
            evidence.start,
            evidence.end,
        ):
            return _blocking_error(
                "AI_FIELD_EVIDENCE_INVALID",
                evidence.path,
                "Field evidence must point to the submitted source text.",
            )
    for unmapped in output.unmapped_text:
        if not _excerpt_matches_source(
            source_text,
            unmapped.excerpt,
            unmapped.start,
            unmapped.end,
        ):
            return _blocking_error(
                "AI_FIELD_EVIDENCE_INVALID",
                unmapped.path,
                "Unmapped text must point to the submitted source text.",
            )
    return None


def _leaf_paths(value: object, path: str = "") -> tuple[str, ...]:
    if isinstance(value, dict):
        return tuple(
            leaf_path
            for key, child in value.items()
            for leaf_path in _leaf_paths(child, f"{path}.{key}" if path else str(key))
        )
    if isinstance(value, list):
        return tuple(
            leaf_path
            for index, child in enumerate(value)
            for leaf_path in _leaf_paths(child, f"{path}[{index}]")
        )
    return (path,)


def _excerpt_matches_source(
    source_text: str,
    excerpt: str,
    start: int | None,
    end: int | None,
) -> bool:
    if start is None or end is None:
        return excerpt in source_text
    return end <= len(source_text) and source_text[start:end] == excerpt


def _usage_snapshot(raw: RawAIResponse) -> AIUsageSnapshot | None:
    if raw.usage is None:
        return None
    return AIUsageSnapshot(
        prompt_tokens=raw.usage.prompt_tokens,
        completion_tokens=raw.usage.completion_tokens,
        total_tokens=raw.usage.total_tokens,
    )


def _blocking_error(code: str, path: str, message: str) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        path=path,
        severity=ValidationSeverity.ERROR,
        message=message,
        activation_blocking=True,
    )


def _blocking_warning(code: str, path: str, message: str) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        path=path,
        severity=ValidationSeverity.WARNING,
        message=message,
        activation_blocking=True,
    )


def _failure_result(
    *,
    request_id: UUID,
    config: AIProviderConfig,
    source_text_sha256: str,
    status: PlanExtractionStatus,
    issue_code: str,
    issue_path: str,
    issue_message: str,
    raw: RawAIResponse | None = None,
    stage: str,
    reason: str,
    provider_error_code: str | None = None,
    transient_kind: str | None = None,
    attempts: int | None = None,
    timeout_kind: str | None = None,
    timeout_elapsed_ms: int | None = None,
    diagnostic_path: str = "unknown",
    schema_error_type: str | None = None,
) -> PlanExtractionResult:
    return PlanExtractionResult(
        request_id=request_id,
        provider_id=config.provider_id,
        model=config.model,
        prompt_version=config.prompt_version,
        source_text_sha256=source_text_sha256,
        draft=None,
        validation_issues=(_blocking_error(issue_code, issue_path, issue_message),),
        usage=_usage_snapshot(raw) if raw is not None else None,
        diagnostic=_diagnostic(
            stage=stage,
            reason=reason,
            path=diagnostic_path,
            provider_error_code=provider_error_code,
            transient_kind=transient_kind,
            schema_error_type=schema_error_type,
            attempts=attempts,
            timeout_kind=timeout_kind,
            timeout_elapsed_ms=timeout_elapsed_ms,
            raw=raw,
            configured_model=config.model,
        ),
        status=status,
    )


_SAFE_PATHS: Final = frozenset(
    {
        "source_text",
        "provider",
        "draft",
        "mapping",
        "mapping_version",
        "source_clauses",
        "field_bindings",
        "evidence",
        "assumptions",
        "warnings",
        "unmapped_text",
    }
)
_SAFE_SCHEMA_ERROR_TYPES: Final = frozenset(
    {
        "missing",
        "extra_forbidden",
        "literal_error",
        "enum",
        "string_pattern_mismatch",
        "string_too_short",
        "string_too_long",
        "int_type",
        "int_parsing",
        "greater_than",
        "greater_than_equal",
        "less_than",
        "less_than_equal",
        "bool_type",
        "model_type",
        "union_tag_invalid",
        "value_error",
        "assertion_error",
        "json_invalid",
        "field_binding_clause_ids_not_unique",
        "field_binding_source_reference_invalid",
        "field_binding_user_supplement_reference_invalid",
        "field_binding_contract_reference_invalid",
        "field_binding_contract_path_forbidden",
        "field_binding_structure_value_invalid",
    }
)


_SAFE_SCHEMA_FIELDS: Final = DIAGNOSTIC_SCHEMA_FIELDS
_SAFE_SCHEMA_VARIANTS: Final = frozenset({"BUY", "SELL", "RISK"})


def _safe_path(value: str) -> str:
    head = value.split(".", 1)[0].split("[", 1)[0]
    return head if head in _SAFE_PATHS else "unknown"


def _safe_schema_path(error: ValidationError) -> str:
    locations = error.errors(include_input=False, include_context=False, include_url=False)
    if not locations or not locations[0]["loc"]:
        return "unknown"
    path = ""
    for segment in locations[0]["loc"][:12]:
        if isinstance(segment, str):
            if segment in _SAFE_SCHEMA_VARIANTS:
                candidate = path + (".variant" if path else "variant")
                if len(candidate) > 160:
                    break
                path = candidate
                continue
            if segment not in _SAFE_SCHEMA_FIELDS:
                candidate = path + (".unknown" if path else "unknown")
                if len(candidate) <= 160:
                    path = candidate
                break
            candidate = path + (f".{segment}" if path else segment)
        elif isinstance(segment, int) and 0 <= segment <= 255:
            candidate = path + f"[{segment}]"
        else:
            candidate = path + (".unknown" if path else "unknown")
            if len(candidate) <= 160:
                path = candidate
            break
        if len(candidate) > 160:
            break
        path = candidate
    return path or "unknown"


def _safe_schema_error_type(error: ValidationError) -> str:
    errors = error.errors(include_input=False, include_context=False, include_url=False)
    if not errors:
        return "other"
    kind = errors[0]["type"]
    return kind if kind in _SAFE_SCHEMA_ERROR_TYPES else "other"


def _diagnostic(
    *,
    stage: str,
    reason: str,
    path: str = "unknown",
    provider_error_code: str | None = None,
    transient_kind: str | None = None,
    schema_error_type: str | None = None,
    attempts: int | None = None,
    timeout_kind: str | None = None,
    timeout_elapsed_ms: int | None = None,
    raw: RawAIResponse | None = None,
    configured_model: str,
) -> ExtractionDiagnostic:
    finish_reason = "unknown"
    if raw is not None:
        finish_reason = (
            raw.finish_reason
            if raw.finish_reason in {"stop", "length", "content_filter", "tool_calls"}
            else "other"
        )
    return ExtractionDiagnostic(
        stage=stage,
        reason=reason,
        path=path,
        provider_error_code=provider_error_code,
        transient_kind=transient_kind,
        schema_error_type=schema_error_type,
        timeout_kind=timeout_kind,
        timeout_elapsed_ms=timeout_elapsed_ms,
        finish_reason=finish_reason,
        model_matches_configured=(raw.model == configured_model if raw is not None else None),
        attempts=raw.attempts if raw is not None else attempts,
    )


__all__ = [
    "MAX_EXTRACTION_JSON_DEPTH",
    "MAX_EXTRACTION_JSON_NODES",
    "MAX_EXTRACTION_OUTPUT_BYTES",
    "MIN_FIELD_EVIDENCE_CHARS",
    "extract_plan",
]
