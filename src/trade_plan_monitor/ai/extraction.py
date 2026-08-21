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
    AIProviderConfig,
    AIUsageSnapshot,
    PlanExtractionOutput,
    PlanExtractionResult,
    PlanExtractionStatus,
    UnmappedText,
)
from trade_plan_monitor.ai.prompts import build_plan_extraction_prompt
from trade_plan_monitor.ai.provider import (
    AIProvider,
    AIProviderError,
    PlanExtractionRequest,
    RawAIResponse,
)
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
    """Internal sentinel whose detail must never cross the extraction boundary."""


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
        )

    try:
        raw = await provider.extract_plan(request)
    except AIProviderError:
        return _failure_result(
            request_id=request_id,
            config=config,
            source_text_sha256=source_text_sha256,
            status=PlanExtractionStatus.PROVIDER_ERROR,
            issue_code="AI_PROVIDER_ERROR",
            issue_path="provider",
            issue_message="AI provider extraction failed.",
        )

    if (
        raw.request_id != request_id
        or raw.provider_id != config.provider_id
        or raw.finish_reason != "stop"
    ):
        return _failure_result(
            request_id=request_id,
            config=config,
            source_text_sha256=source_text_sha256,
            status=PlanExtractionStatus.INVALID_OUTPUT,
            issue_code="AI_OUTPUT_INVALID",
            issue_path="draft",
            issue_message="AI output did not satisfy the extraction contract.",
            raw=raw,
        )

    try:
        output = _parse_untrusted_output(raw.content)
    except UnicodeError, ValueError, RecursionError, ValidationError:
        return _failure_result(
            request_id=request_id,
            config=config,
            source_text_sha256=source_text_sha256,
            status=PlanExtractionStatus.INVALID_OUTPUT,
            issue_code="AI_OUTPUT_INVALID",
            issue_path="draft",
            issue_message="AI output did not satisfy the extraction contract.",
            raw=raw,
        )

    evidence_issue = _validate_provenance(output, source_text)
    if evidence_issue is not None:
        return _failure_result(
            request_id=request_id,
            config=config,
            source_text_sha256=source_text_sha256,
            status=PlanExtractionStatus.INVALID_OUTPUT,
            issue_code=evidence_issue.code,
            issue_path=evidence_issue.path,
            issue_message=evidence_issue.message,
            raw=raw,
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
        model=raw.model,
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
        status=PlanExtractionStatus.SUCCEEDED,
    )


def _parse_untrusted_output(content: str) -> PlanExtractionOutput:
    if len(content.encode("utf-8")) > MAX_EXTRACTION_OUTPUT_BYTES:
        raise _UntrustedOutputError("output byte limit exceeded")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise _UntrustedOutputError("duplicate JSON key")
            result[key] = value
        return result

    def reject_non_finite(value: str) -> None:
        raise _UntrustedOutputError(f"non-finite number: {value}")

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
    return PlanExtractionOutput.model_validate_json(normalized)


def _enforce_json_budget(value: object) -> None:
    stack: list[tuple[object, int]] = [(value, 1)]
    nodes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > MAX_EXTRACTION_JSON_NODES:
            raise _UntrustedOutputError("JSON node limit exceeded")
        if depth > MAX_EXTRACTION_JSON_DEPTH:
            raise _UntrustedOutputError("JSON depth limit exceeded")
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
) -> PlanExtractionResult:
    return PlanExtractionResult(
        request_id=request_id,
        provider_id=config.provider_id,
        model=raw.model if raw is not None else config.model,
        prompt_version=config.prompt_version,
        source_text_sha256=source_text_sha256,
        draft=None,
        validation_issues=(_blocking_error(issue_code, issue_path, issue_message),),
        usage=_usage_snapshot(raw) if raw is not None else None,
        status=status,
    )


__all__ = [
    "MAX_EXTRACTION_JSON_DEPTH",
    "MAX_EXTRACTION_JSON_NODES",
    "MAX_EXTRACTION_OUTPUT_BYTES",
    "MIN_FIELD_EVIDENCE_CHARS",
    "extract_plan",
]
