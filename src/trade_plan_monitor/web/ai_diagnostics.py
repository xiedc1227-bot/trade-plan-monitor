"""Small local sidecar for content-free AI extraction receipts."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from trade_plan_monitor.ai.models import PlanExtractionResult

MAX_DIAGNOSTIC_RECORD_BYTES = 2_048
MAX_DIAGNOSTIC_FILE_BYTES = 1_048_576
MAX_DIAGNOSTIC_RECORDS = 512


def ensure_diagnostic_sink(path: Path) -> None:
    """Probe sidecar writability for the caller's startup policy."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
    os.close(descriptor)


def diagnostic_path_for_database(database_path: Path) -> Path:
    """Keep diagnostics in the same access-controlled directory as the selected DB."""

    return database_path.with_suffix(".ai-extraction-diagnostics.jsonl")


def append_extraction_diagnostic(
    path: Path,
    *,
    result: PlanExtractionResult,
    configured_model: str,
    completed_at: datetime,
) -> None:
    """Persist closed metadata only; never serialize the result or provider envelope."""

    diagnostic = result.diagnostic
    if diagnostic is None:
        raise ValueError("extraction diagnostic is missing")
    usage = result.usage
    safe_usage = None
    if (
        usage is not None
        and max(usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) <= 1_000_000_000
    ):
        safe_usage = {
            "promptTokens": usage.prompt_tokens,
            "completionTokens": usage.completion_tokens,
            "totalTokens": usage.total_tokens,
        }
    record = {
        "version": 1,
        "operationId": str(result.request_id),
        "sourceTextSha256": result.source_text_sha256,
        "providerId": str(result.provider_id),
        "model": configured_model,
        "promptVersion": result.prompt_version,
        "completedAt": completed_at.isoformat(),
        "status": result.status.value,
        "stage": diagnostic.stage,
        "reason": diagnostic.reason,
        "path": diagnostic.path,
        "schemaErrorType": diagnostic.schema_error_type,
        "providerErrorCode": diagnostic.provider_error_code,
        "finishReason": diagnostic.finish_reason,
        "modelMatchesConfigured": diagnostic.model_matches_configured,
        "attempts": diagnostic.attempts,
        "usage": safe_usage,
    }
    payload = (json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n").encode()
    if len(payload) > MAX_DIAGNOSTIC_RECORD_BYTES:
        raise ValueError("extraction diagnostic exceeds record limit")
    path.parent.mkdir(parents=True, exist_ok=True)
    previous: list[bytes] = []
    if path.exists():
        with path.open("rb") as stream:
            size = path.stat().st_size
            stream.seek(max(0, size - MAX_DIAGNOSTIC_FILE_BYTES))
            chunk = stream.read(MAX_DIAGNOSTIC_FILE_BYTES)
        lines = chunk.splitlines(keepends=True)
        if size > MAX_DIAGNOSTIC_FILE_BYTES:
            lines = lines[1:]
        previous = [line for line in lines if len(line) <= MAX_DIAGNOSTIC_RECORD_BYTES]
    kept: list[bytes] = []
    total = len(payload)
    for line in reversed(previous):
        if len(kept) >= MAX_DIAGNOSTIC_RECORDS - 1 or total + len(line) > MAX_DIAGNOSTIC_FILE_BYTES:
            break
        kept.append(line)
        total += len(line)
    replacement = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    try:
        descriptor = os.open(replacement, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.writelines(reversed(kept))
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(replacement, path)
    finally:
        replacement.unlink(missing_ok=True)
