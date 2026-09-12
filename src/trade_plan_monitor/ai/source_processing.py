"""Finite, server-owned routing of mixed prose; never writes actual inventory."""

from __future__ import annotations

import re
from hashlib import sha256
from itertools import pairwise

from trade_plan_monitor.ai.models import (
    ExplicitPlanDraft,
    InventorySourceTreatment,
    PlanMapping,
    ProductSourceTreatment,
    SourceClause,
    SourceProcessing,
    SourceSpan,
)

_INVENTORY = re.compile(r"(?P<symbol>[0-9]{6}\.(?:SZ|SH|BJ))当前持仓(?P<qty>0|[1-9][0-9]*)股，")
_SETTLED = "均为测试日前已持有且当日可卖；"
_NO_FILL = "提醒及确认收到提醒不代表成交，"
_NO_CHANGE = "未登记成交时持仓不变。"
_MIXED_MARKERS = ("当前持仓", "均为测试日前", "提醒及确认收到提醒", "未登记成交时")


def _span(clause: SourceClause, *, offset: int = 0, length: int | None = None) -> SourceSpan:
    end = clause.end if length is None else clause.start + offset + length
    return SourceSpan(
        clause_id=clause.clause_id,
        start=clause.start + offset,
        end=end,
        excerpt=clause.excerpt[offset : None if length is None else offset + length],
    )


def derive_source_processing(source_text: str, *, symbol: str) -> SourceProcessing:
    from trade_plan_monitor.ai.review import server_source_clauses

    clauses = server_source_clauses(source_text)
    treatments: list[InventorySourceTreatment | ProductSourceTreatment] = []
    for first, second in pairwise(clauses):
        if source_text[first.end : second.start].strip():
            continue
        identity = (
            "treatment-"
            + sha256(
                f"source-processing-v1\x00{first.start}\x00{second.end}\x00"
                f"{source_text[first.start : second.end]}".encode()
            ).hexdigest()[:24]
        )
        inventory = _INVENTORY.fullmatch(first.excerpt)
        if inventory and second.excerpt == _SETTLED and inventory["symbol"] == symbol:
            quantity = int(inventory["qty"])
            if quantity > 9_007_199_254_740_991:
                continue
            treatments.append(
                InventorySourceTreatment(
                    treatment_id=identity,
                    spans=(_span(first, offset=len(symbol)), _span(second)),
                    symbol_span=_span(first, length=len(symbol)),
                    symbol=symbol,
                    total_quantity=quantity,
                    sellable_quantity=quantity,
                )
            )
        elif first.excerpt == _NO_FILL and second.excerpt == _NO_CHANGE:
            treatments.append(
                ProductSourceTreatment(
                    treatment_id=identity,
                    spans=(_span(first), _span(second)),
                )
            )
    return SourceProcessing(treatments=tuple(treatments))


def upgrade_source_mapping(
    *, draft: ExplicitPlanDraft, mapping: PlanMapping, source_text: str
) -> PlanMapping:
    expected = derive_source_processing(source_text, symbol=draft.symbol)
    if mapping.source_processing is not None and mapping.source_processing != expected:
        raise ValueError("source processing does not match exact server-derived treatment records")
    return mapping.model_copy(
        update={"mapping_version": "plan-mapping-v2", "source_processing": expected}
    )


def looks_like_unhandled_mixed_source(clause: SourceClause) -> bool:
    # A normal volume clause contains 成交量; max position is an executable policy.
    excerpt = clause.excerpt.replace("成交量", "")
    if re.fullmatch(r"(?:最大计划持仓|最大持仓|最高)[0-9]+股[。；,，]?", excerpt):
        return False
    return any(marker in excerpt for marker in _MIXED_MARKERS)
