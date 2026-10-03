"""Typed current research outcomes, separate from legacy strategy evaluations."""

from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Literal

from pydantic import Field, field_validator, model_validator

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.models import ExecutionConfig, Sha256Hex
from trade_plan_monitor.backtest.research_input import ResearchValue
from trade_plan_monitor.decision.unified_conditions import UnifiedConditionEvidence
from trade_plan_monitor.state.daily_state_models import (
    DailyInventoryView,
    DailyRiskAction,
    DailyRiskState,
    DailyRuleReminderState,
    DailySignalState,
)


class ResearchConditionEvidence(UnifiedConditionEvidence):
    session_dates: tuple[date, ...] = ()
    children: tuple[ResearchConditionEvidence, ...] = ()


class ResearchRuleEvidence(ResearchValue):
    rule_id: str
    evidence: ResearchConditionEvidence

    @field_validator("evidence", mode="before")
    @classmethod
    def normalize_evidence(cls, value):
        return (
            value.model_dump(mode="python")
            if isinstance(value, UnifiedConditionEvidence)
            else value
        )


class ResearchOperationOutcome(ResearchValue):
    schema_version: Literal["unified-research-operation-v1"] = "unified-research-operation-v1"
    operation_id: str
    at: datetime
    kind: Literal["FACT", "DEACTIVATE", "REPLACE", "SIMULATE", "REASSESS"]
    status: Literal["APPLIED", "BLOCKED", "REPLAYED"]
    blockers: tuple[str, ...] = Field(max_length=20)
    cause_id: str | None = None
    quantity: int | None = None
    simulation_id: str | None = None
    side: Literal["BUY", "SELL"] | None = None
    monitor_price_fen: int | None = Field(default=None, gt=0)
    inventory_before: DailyInventoryView
    inventory_after: DailyInventoryView
    valuation: ResearchOperationValuation | None = None


class ResearchOperationValuation(ResearchValue):
    schema_version: Literal["explicit-simulation-valuation-v1"] = "explicit-simulation-valuation-v1"
    status: Literal["PROJECTED", "BLOCKED"]
    blockers: tuple[str, ...]
    research_price_fen: int = Field(gt=0)
    notional_fen: int = Field(gt=0)
    fees_fen: int = Field(ge=0)
    cash_delta_fen: int
    cash_after_fen: int | None


class ResearchEquity(ResearchValue):
    schema_version: Literal["unified-research-equity-v1"] = "unified-research-equity-v1"
    snapshot_id: Sha256Hex
    marked_at: datetime
    mark_price_fen: int | None
    cash_fen: int | None
    position_quantity: int | None
    market_value_fen: int | None
    equity_fen: int | None
    valuation_valid: bool
    blockers: tuple[str, ...]


class ResearchMetrics(ResearchValue):
    schema_version: Literal["explicit-simulation-metrics-v1"] = "explicit-simulation-metrics-v1"
    initial_cash_fen: int
    initial_equity_fen: int | None
    final_cash_fen: int | None
    final_equity_fen: int | None
    total_return: Decimal | None
    total_cost_fen: int
    trade_count: int
    blocked_count: int
    valuation_valid: bool


class ResearchDecisionEvent(ResearchValue):
    schema_version: Literal["unified-research-decision-v1"] = "unified-research-decision-v1"
    event_id: Sha256Hex
    at: datetime
    evaluation_id: Sha256Hex | None
    official_trade_date: str | None
    minute_target: datetime | None
    signals: tuple[DailySignalState, ...] = Field(max_length=500)
    risks: tuple[DailyRiskState, ...] = Field(max_length=2)
    alerts: tuple[ResearchReminder, ...] = Field(max_length=10)
    resulting_signals: tuple[DailySignalState, ...] = Field(max_length=500)
    resulting_risks: tuple[DailyRiskState, ...] = Field(max_length=2)
    risk_action: DailyRiskAction
    conditions: tuple[ResearchRuleEvidence, ...] = Field(max_length=12)
    blockers: tuple[str, ...] = Field(max_length=20)
    inventory_before: DailyInventoryView
    inventory_after: DailyInventoryView


class ResearchReminder(DailyRuleReminderState):
    evidence: tuple[ResearchConditionEvidence, ...] = Field(max_length=1)


class _UnifiedReplayPayload(ResearchValue):
    schema_version: Literal["backtest-report-v3"] = "backtest-report-v3"
    status: Literal["COMPLETED"] = "COMPLETED"
    run_id: Sha256Hex
    plan_hash: Sha256Hex
    dataset_hash: Sha256Hex
    symbol: str
    start: date
    end: date
    execution_config: ExecutionConfig
    current_events: tuple[ResearchDecisionEvent, ...] = Field(max_length=70000)
    operations: tuple[ResearchOperationOutcome, ...] = Field(max_length=10000)
    final_inventory: DailyInventoryView
    daily_equity: tuple[ResearchEquity, ...] = Field(max_length=2000)
    metrics: ResearchMetrics
    limitations: tuple[str, ...] = Field(max_length=30)


class UnifiedReplayReport(_UnifiedReplayPayload):
    report_hash: Sha256Hex

    @property
    def fills(self):
        return ()

    @property
    def decisions(self):
        return self.current_events

    @property
    def signals(self):
        return ()

    @property
    def outcomes(self):
        return self.operations

    @classmethod
    def build(cls, **values):
        payload = _UnifiedReplayPayload.model_validate(values)
        normalized = payload.model_dump(mode="python")
        digest = sha256(("backtest-report-v3\0" + canonical_json(normalized)).encode()).hexdigest()
        return cls(report_hash=digest, **normalized)

    @model_validator(mode="after")
    def integrity(self):
        expected = sha256(
            (
                "backtest-report-v3\0"
                + canonical_json(self.model_dump(mode="python", exclude={"report_hash"}))
            ).encode()
        ).hexdigest()
        if self.report_hash != expected:
            raise ValueError("current report hash mismatch")
        return self
