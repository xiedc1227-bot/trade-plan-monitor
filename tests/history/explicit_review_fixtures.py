"""Frozen schema3/mapping-v1 fixture builders for historical read regressions only."""

from datetime import datetime
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

from trade_plan_monitor.ai.models import (
    BindingKind,
    BindingOrigin,
    BindingUnit,
    ClauseDisposition,
    ExplicitPlanDraft,
    FieldBinding,
    PlanMapping,
)
from trade_plan_monitor.ai.review import (
    server_source_clauses,
)
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_NOW = datetime(2026, 9, 12, 16, 0, tzinfo=_SHANGHAI)
_PROVIDER_ID = UUID("04f3e4f5-7b55-4d61-a9ea-119d0db5c9a7")
_EXTRACTION_ID = UUID("06e3613f-2aa9-481a-8b7e-b6d66230f09d")
_SOURCE = (
    "003043.SZ 已有可卖100股 最高300股 五分钟完成收盘9.80到10.00元含端点"
    "并且成交量不少于前5根已完成五分钟K线算术平均值1.5倍买入100股 "
    "五分钟完成收盘10.80到11.00元含端点卖出100股 五分钟完成收盘低于9.50元风险提醒 "
    "人工选择手动有效 每条规则每次激活只提醒一次 同时交易冲突阻止两者 风险冲突仅保留风险"
)


class _Runtime:
    async def start(self) -> object:
        return object()

    async def stop(self) -> None:
        return None


def _draft_payload(*, complete: bool = True) -> dict[str, object]:
    repeat = {"mode": "ONCE_PER_ACTIVATION"} if complete else None
    return {
        "schema_version": 3,
        "execution_mode": "EXPLICIT_RULES",
        "execution_version": "explicit-rules-v1",
        "plan_id": "synthetic-r11-api",
        "version": 1,
        "symbol": "003043.SZ",
        "name": "SYNTHETIC R11 API",
        "market": "SZSE",
        "metadata": {},
        "activation": {"mode": "MANUAL"} if complete else None,
        "position": {
            "inventory_scope": "ALL_REGISTERED",
            "lot_size": 100,
            "max_qty": 300,
        },
        "monitoring": {"timeframe_minutes": 5, "indicator_formula_version": "ta-v1"},
        "rules": [
            {
                "rule_id": "buy-100",
                "condition": {
                    "type": "ALL",
                    "conditions": [
                        {
                            "type": "COMPLETED_CLOSE_IN_RANGE",
                            "low_fen": 980,
                            "high_fen": 1000,
                            "include_low": True,
                            "include_high": True,
                        },
                        {
                            "type": "VOLUME_TO_MEAN_GTE",
                            "window_bars": 5,
                            "minimum_ratio": "1.5",
                            "history_scope": ("CONTIGUOUS_TRADING_BARS" if complete else None),
                        },
                    ],
                },
                "action": {"type": "BUY", "quantity": 100},
                "confirmation": {
                    "kind": "COMPLETED_BAR_CLOSE",
                    "timeframe_minutes": 5,
                },
                "repeat_policy": repeat,
                "safety_conditions": None,
            },
            {
                "rule_id": "sell-100",
                "condition": {
                    "type": "COMPLETED_CLOSE_IN_RANGE",
                    "low_fen": 1080,
                    "high_fen": 1100,
                    "include_low": True,
                    "include_high": True,
                },
                "action": {
                    "type": "SELL",
                    "quantity": 100,
                    "inventory_scope": "ALL_REGISTERED",
                },
                "confirmation": {
                    "kind": "COMPLETED_BAR_CLOSE",
                    "timeframe_minutes": 5,
                },
                "repeat_policy": repeat,
                "safety_conditions": None,
            },
            {
                "rule_id": "risk-950",
                "condition": {"type": "COMPLETED_CLOSE_BELOW", "price_fen": 950},
                "action": {"type": "RISK_ALERT"},
                "confirmation": {
                    "kind": "COMPLETED_BAR_CLOSE",
                    "timeframe_minutes": 5,
                },
                "repeat_policy": repeat,
                "safety_conditions": None,
            },
        ],
        "conflict_policy": (
            {"trade_conflict": "BLOCK_BOTH", "risk_conflict": "RISK_ONLY"} if complete else None
        ),
    }


def _scalar_paths(value: object, path: str = "") -> list[tuple[str, object]]:
    if isinstance(value, dict):
        return [
            item
            for key, child in value.items()
            for item in _scalar_paths(child, f"{path}.{key}" if path else key)
        ]
    if isinstance(value, list):
        return [
            item
            for index, child in enumerate(value)
            for item in _scalar_paths(child, f"{path}[{index}]")
        ]
    return [] if value is None else [(path, value)]


def _logical_paths(value: object, path: str = "") -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    if isinstance(value, dict):
        if value.get("type") in {"ALL", "ANY"}:
            result.append((path, str(value["type"])))
        for key, child in value.items():
            result.extend(_logical_paths(child, f"{path}.{key}" if path else key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            result.extend(_logical_paths(child, f"{path}[{index}]"))
    return result


def _unit(path: str) -> BindingUnit:
    if path.endswith("_fen"):
        return BindingUnit.FEN
    if path.endswith("quantity") or path.endswith("max_qty") or path.endswith("lot_size"):
        return BindingUnit.SHARES
    if path.endswith("window_bars"):
        return BindingUnit.BARS
    if path.endswith("timeframe_minutes"):
        return BindingUnit.MINUTES
    if path.endswith("ratio"):
        return BindingUnit.RATIO
    return BindingUnit.NONE


def _is_contract(path: str) -> bool:
    return path in {
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
    } or path.endswith(".rule_id")


def _mapping(draft: ExplicitPlanDraft) -> PlanMapping:
    [clause] = server_source_clauses(_SOURCE)
    data = draft.model_dump(mode="json")
    source_paths: list[str] = []
    bindings: list[FieldBinding] = []
    for path, value in _scalar_paths(data):
        if _is_contract(path):
            bindings.append(
                FieldBinding(
                    path=path,
                    value=value,
                    unit=_unit(path),
                    origin=BindingOrigin.CONTRACT,
                    contract_id="explicit-rules-v1",
                )
            )
        else:
            source_paths.append(path)
            bindings.append(
                FieldBinding(
                    path=path,
                    value=value,
                    unit=_unit(path),
                    origin=BindingOrigin.SOURCE,
                    clause_ids=(clause.clause_id,),
                )
            )
    for path, value in _logical_paths(data):
        source_paths.append(path)
        bindings.append(
            FieldBinding(
                path=path,
                value=value,
                unit=BindingUnit.NONE,
                origin=BindingOrigin.SOURCE,
                binding_kind=BindingKind.STRUCTURE,
                clause_ids=(clause.clause_id,),
            )
        )
    return PlanMapping(
        source_clauses=(
            clause.model_copy(
                update={
                    "disposition": ClauseDisposition.MAPPED,
                    "paths": tuple(source_paths),
                }
            ),
        ),
        field_bindings=tuple(bindings),
        user_supplements=(),
    )


def _app(database_path: Path) -> tuple[object, PersistentPlanWebLifecycle]:
    lifecycle = PersistentPlanWebLifecycle(database_path=database_path, clock=lambda: _NOW)
    return create_app(runtime_factory=_Runtime, plan_lifecycle_factory=lambda: lifecycle), lifecycle


def _confirmation_resolutions(detail: dict[str, object]) -> list[dict[str, object]]:
    supplements = {
        item["path"]: item["supplementId"] for item in detail["mapping"]["userSupplements"]
    }
    resolutions = []
    for issue in detail["requiredReviewIssues"]:
        resolution = issue["allowedResolutions"][0]
        item = {"issueId": issue["issueId"], "resolution": resolution}
        if resolution == "CONFIRM_MAPPING":
            item["bindingPath"] = issue["bindingPath"]
        elif resolution == "CONFIRM_POLICY":
            item["supplementId"] = supplements.get(issue["path"])
        resolutions.append(item)
    return resolutions
