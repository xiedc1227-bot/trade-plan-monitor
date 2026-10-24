"""Typed incomplete Schema 4 candidates never inherit strategy defaults."""

import json
from hashlib import sha256
from typing import Literal

from pydantic import Field, ValidationError

from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.daily_plan_models import (
    DailyActivation,
    DailyCondition,
    DailyExecutionPolicy,
    DailyMetadata,
    DailyMonitoring,
    DailyTradePlan,
    DailyTradingRules,
    DailyValidity,
    DailyValue,
    Fen,
    Identifier,
    IndependentSignal,
    PositiveQty,
    PositiveWholeQty,
    RiskKind,
    Text,
    WholeQty,
)


class DailyDraftZone(DailyValue):
    low_fen: Fen | None
    high_fen: Fen | None
    include_low: bool | None = Field(strict=True)
    include_high: bool | None = Field(strict=True)


class DailyDraftLevels(DailyValue):
    low_buy: DailyDraftZone
    pressure: DailyDraftZone
    risk_line_fen: Fen | None
    risk_comparison: Literal["LT", "LTE"] | None


class DailyDraftPosition(DailyValue):
    max_qty: PositiveWholeQty | None
    core_target_qty: WholeQty | None
    tactical_target_qty: WholeQty | None
    allocation_provenance: Literal["EXISTING_CONFIRMED", "PROPOSED"] | None
    allocation_evidence: Text | None


class DailyDraftRule(DailyValue):
    status: Literal["ENABLED", "DISABLED"] | None
    side: Literal["BUY", "SELL"]
    reason: Text | None
    rule_id: Identifier | None
    zone: Literal["LOW_BUY", "PRESSURE"] | None
    quantity: PositiveWholeQty | None
    bucket: Literal["TACTICAL"] | None
    price_structure: DailyCondition | None
    volume_or_candle: DailyCondition | None
    technical: DailyCondition | None
    prerequisites: tuple[DailyCondition, ...] | None
    validity: DailyValidity | None
    invalidation: Literal["RISK_OR_REVIEWED_INVALIDATION"] | None
    independent_signal: IndependentSignal | None


class DailyDraftRisk(DailyValue):
    kind: RiskKind
    involves_core: bool | None = Field(strict=True)
    scope_evidence: Text | None
    target_core_qty: WholeQty | None
    target_tactical_qty: WholeQty | None
    priority: int | None = Field(strict=True, ge=1, le=3)
    evidence_mode: Literal["TWO_OFFICIAL_CLOSES", "STRUCTURE_AND_DETERIORATION"] | None
    suspension_confirmation_policy: Literal["RESUME_FIRST_CLOSE", "RESTART_ADJACENT_PAIR"] | None


class DailyPlanDraft(DailyValue):
    schema_version: Literal[4] = 4
    execution_mode: Literal["DAILY_CLOSE_PLAN"] = "DAILY_CLOSE_PLAN"
    execution_version: Literal["daily-close-v1"] = "daily-close-v1"
    plan_id: Identifier
    version: PositiveQty
    symbol: str = Field(pattern=r"^[0-9]{6}\.(?:SH|SZ|BJ)$")
    name: str = Field(min_length=1, max_length=100)
    market: Literal["SSE", "SZSE", "BSE"]
    metadata: DailyMetadata
    activation: DailyActivation | None
    levels: DailyDraftLevels
    position: DailyDraftPosition
    trading_rules: DailyTradingRules = Field(default_factory=DailyTradingRules)
    monitoring: DailyMonitoring | None
    ordinary_rules: tuple[DailyDraftRule, ...] = Field(min_length=2, max_length=2)
    risk_branches: tuple[DailyDraftRisk, ...] = Field(min_length=2, max_length=2)
    execution_policy: DailyExecutionPolicy | None

    def executable_payload(self):
        data = self.model_dump(mode="json")
        for rule in data["ordinary_rules"]:
            if rule["status"] == "DISABLED":
                for key in tuple(rule):
                    if key not in {"status", "side", "reason"}:
                        rule.pop(key)
            elif rule["status"] == "ENABLED":
                rule.pop("reason")
        return data

    def to_executable(self) -> DailyTradePlan | None:
        try:
            return DailyTradePlan.model_validate(self.executable_payload())
        except ValidationError:
            return None

    @classmethod
    def from_executable(cls, plan):
        data = plan.model_dump(mode="json")
        for rule in data["ordinary_rules"]:
            for key in DailyDraftRule.model_fields:
                rule.setdefault(key, None)
        for risk in data["risk_branches"]:
            risk.setdefault("suspension_confirmation_policy", None)
        return cls.model_validate(data)


def daily_draft_json(draft) -> str:
    executable = draft.to_executable()
    data = (
        executable.model_dump(mode="json")
        if executable is not None
        else draft.model_dump(mode="json")
    )
    return json.dumps(
        data, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")
    )


def load_daily_draft_json(document):
    from trade_plan_monitor.domain.plan_codec import (
        _normalize_document,
        _reject_duplicate_json_keys,
        _reject_json_constant,
        _validate_data_tree,
    )

    raw = json.loads(
        _normalize_document(document),
        object_pairs_hook=_reject_duplicate_json_keys,
        parse_constant=_reject_json_constant,
    )
    if isinstance(raw, dict) and raw.get("schema_version") == 6:
        from trade_plan_monitor.domain.market_linkage_validation import MarketLinkedPlanDraft

        _validate_data_tree(raw)
        return MarketLinkedPlanDraft.model_validate(raw)
    if isinstance(raw, dict) and raw.get("schema_version") == 5:
        from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
        from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft

        _validate_data_tree(raw)
        try:
            return UnifiedPlanDraft.from_executable(UnifiedTradePlan.model_validate(raw))
        except ValidationError:
            return UnifiedPlanDraft.model_validate(raw)
    if not isinstance(raw, dict) or raw.get("schema_version") != 4:
        raise ValueError("not a Schema 4 draft")
    if obsolete_daily_document(raw):
        raise ValueError(
            "DAILY_DRAFT_OBSOLETE: re-extract the preserved source "
            "and review a new technical-only draft"
        )
    _validate_data_tree(raw)
    try:
        return DailyPlanDraft.from_executable(DailyTradePlan.model_validate(raw))
    except ValidationError:
        return DailyPlanDraft.model_validate(raw)


def obsolete_daily_document(document):
    """Detect unpublished development contracts without converting or dropping data."""
    raw = json.loads(document) if isinstance(document, str) else document
    if not isinstance(raw, dict) or raw.get("schema_version") != 4:
        return False

    if set(raw.get("trading_rules") or {}) & {
        "buy_min_qty",
        "buy_increment",
        "sell_increment",
        "odd_lot_liquidation",
        "evidence",
        "as_of",
    }:
        return True

    def contains(value):
        if isinstance(value, dict):
            return any(contains(child) for child in value.values())
        if isinstance(value, list):
            return any(contains(child) for child in value)
        return isinstance(value, str) and value in {
            "FUNDAMENTAL_INVALIDATION",
            "ANNOUNCEMENT_CHECK",
            "OFFICIAL_THESIS_INVALIDATION",
            "FUNDAMENTAL_THEN_SEVERE_THEN_ORDINARY",
        }

    return contains(raw)


def daily_draft_sha256(draft):
    return sha256(daily_draft_json(draft).encode()).hexdigest()


def daily_draft_content_sha256(draft):
    data = draft.executable_payload()
    for key in ("plan_id", "version", "name", "metadata"):
        data.pop(key)
    domain = {4: "daily-plan-review-content-v1", 5: "plan-review-content-v2",
              6: "plan-review-content-v3"}[draft.schema_version]
    return daily_hash(domain, data)


def daily_draft_issues(draft):
    """Validation is rerun server-side; a missing field cannot be dismissed by acknowledgement."""
    if draft.schema_version in {5, 6}:
        from trade_plan_monitor.domain.unified_plan_validation import unified_plan_issues

        return unified_plan_issues(draft)
    try:
        DailyTradePlan.model_validate(draft.executable_payload())
        return ()
    except ValidationError as error:
        return tuple(
            {
                "path": ".".join(str(x) for x in e["loc"]),
                "code": "DAILY_PARAMETER_REQUIRED"
                if e["input"] is None
                else "DAILY_PARAMETER_INVALID",
                "reason": "Supply the reviewed parameter and its source or human evidence.",
            }
            for e in error.errors(include_url=False, include_context=False, include_input=True)
        )
