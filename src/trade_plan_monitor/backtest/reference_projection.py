"""Shared public projection of decision-time reference-index evidence."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel

from trade_plan_monitor.backtest.canonical import canonical_decimal
from trade_plan_monitor.backtest.time import SHANGHAI, format_shanghai_datetime
from trade_plan_monitor.decision.models import (
    ConditionEvidence,
    EvaluationResult,
    IndexConditionEvidence,
)


def project_decision_reference_market(
    result: EvaluationResult,
) -> dict[str, object] | None:
    """Return only persisted path evidence; never join or recompute index data."""

    if not isinstance(result, EvaluationResult):
        raise TypeError("result must be an EvaluationResult")
    evidence = _index_evidence_for_result(result)
    reference = result.snapshot.reference_market
    if not evidence or reference is None:
        return None
    snapshot_hashes = {item.snapshot_hash for item in evidence if item.snapshot_hash is not None}
    data_cutoffs = {item.data_cutoff for item in evidence if item.data_cutoff is not None}
    index_codes = {item.index_code for item in evidence}
    if len(snapshot_hashes) > 1 or len(data_cutoffs) > 1 or index_codes != {reference.index_code}:
        raise RuntimeError("persisted decision contains mixed index snapshot identities")
    if snapshot_hashes and snapshot_hashes != {reference.snapshot_hash}:
        raise RuntimeError("persisted decision index snapshot hash is inconsistent")
    if data_cutoffs and data_cutoffs != {reference.data_at}:
        raise RuntimeError("persisted decision index cutoff is inconsistent")
    return {
        "indexCode": reference.index_code.value,
        "snapshotHash": reference.snapshot_hash,
        "dataAt": (
            None
            if reference.data_at is None
            else format_shanghai_datetime(reference.data_at.astimezone(SHANGHAI))
        ),
        "health": reference.health.value,
        "evidence": [_public_value(item) for item in evidence],
    }


def _index_evidence_for_result(
    result: EvaluationResult,
) -> tuple[IndexConditionEvidence, ...]:
    values: list[IndexConditionEvidence] = []

    def visit(value: ConditionEvidence) -> None:
        if value.index_evidence is not None:
            values.append(value.index_evidence)
        for child in value.children:
            visit(child)

    for evidence in result.snapshot.condition_evidence:
        if isinstance(evidence, ConditionEvidence):
            visit(evidence)
    return tuple(sorted(values, key=lambda item: item.plan_path))


def _public_value(value: object) -> object:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="python", round_trip=True)
    if isinstance(value, Mapping):
        return {_camel_key(key): _public_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_public_value(item) for item in value]
    if isinstance(value, datetime):
        return format_shanghai_datetime(value.astimezone(SHANGHAI))
    if type(value) is date:
        return value.isoformat()
    if isinstance(value, Decimal):
        return canonical_decimal(value)
    if isinstance(value, Enum):
        return value.value
    return value


def _camel_key(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("public projection keys must be strings")
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


__all__ = ["project_decision_reference_market"]
