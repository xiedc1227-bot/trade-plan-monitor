"""Closed persistent daily state graphs; quantities and provenance survive validation."""

from datetime import date
from typing import Literal

from pydantic import Field, field_validator, model_validator

from trade_plan_monitor.ai.daily_review import DailySupplement
from trade_plan_monitor.decision.daily_conditions import DailyConditionEvidence
from trade_plan_monitor.decision.market_linkage import MarketLinkageDecision
from trade_plan_monitor.decision.unified_conditions import UnifiedConditionEvidence
from trade_plan_monitor.domain.daily_plan_models import (
    DailyValue,
    FactKind,
    Fen,
    PositiveWholeQty,
    Qty,
    RiskKind,
    WholeQty,
)
from trade_plan_monitor.domain.daily_scope import require_technical_text
from trade_plan_monitor.domain.risk_scope import RiskHoldingScope
from trade_plan_monitor.market_data.aggregation import FiveMinuteBar
from trade_plan_monitor.market_data.daily_data import DailyExecutionQuote, DailySeries
from trade_plan_monitor.market_data.models import MinuteBar, ShanghaiDatetime
from trade_plan_monitor.market_index.models import MarketIndexSnapshot

Digest = str


class DailyOfficialProof(DailyValue):
    issuer: str = Field(min_length=1, max_length=200)
    document_title: str = Field(min_length=1, max_length=500)
    document_url: str = Field(pattern=r"^https://[^\s]+$", max_length=2000)
    published_at: ShanghaiDatetime
    verified_at: ShanghaiDatetime
    applicable_assertion: str = Field(min_length=20, max_length=2000)

    @model_validator(mode="after")
    def order(self):
        if self.published_at > self.verified_at:
            raise ValueError("official publication follows verification")
        return self


class DailyFactState(DailyValue):
    plan_version_id: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: FactKind
    trade_date: date
    signal_id: str | None
    prior_signal_id: str | None = None
    evidence: str = Field(min_length=20, max_length=2000)
    verified: Literal[True]
    satisfied: bool = Field(default=True, strict=True)
    verified_at: ShanghaiDatetime
    available_at: ShanghaiDatetime
    official_evidence: DailyOfficialProof | None

    @model_validator(mode="after")
    def proof(self):
        if not self.satisfied and self.kind in {
            "TRADABILITY",
            "FULL_SESSION_SUSPENSION",
            "INDEPENDENT_EVENT",
            "SIGNAL_INVALIDATION",
        }:
            raise ValueError("negative assertions apply only to technical condition facts")
        if self.kind not in {"TRADABILITY", "FULL_SESSION_SUSPENSION"}:
            require_technical_text(self.evidence)
            if self.official_evidence is not None:
                require_technical_text(self.official_evidence.applicable_assertion)
        if self.available_at < self.verified_at or self.trade_date > self.available_at.date():
            raise ValueError("fact is available before verification or applicable date")
        if (
            self.kind in {"TRADABILITY", "FULL_SESSION_SUSPENSION"}
            and self.official_evidence is None
        ):
            raise ValueError("official proof is required")
        if (
            self.official_evidence is not None
            and self.official_evidence.verified_at > self.verified_at
        ):
            raise ValueError("stored fact precedes actual manual verification")
        if self.kind == "INDEPENDENT_EVENT" and (
            self.signal_id is None or self.prior_signal_id != self.signal_id
        ):
            raise ValueError("independent event must identify its previous signal")
        return self


class DailySignalState(DailyValue):
    market_linkage: MarketLinkageDecision | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    occurrence_mode: Literal["ONCE_PER_RULE", "AFTER_RULE_COMPLETED"] | None = None
    signal_id: str
    rule_id: str
    side: Literal["BUY", "SELL"]
    bucket: Literal["TACTICAL"]
    lineage: str
    state: Literal[
        "CONFIRMED",
        "READY",
        "EXPIRED",
        "INVALIDATED",
        "SIMULATED",
    ]
    planned_qty: PositiveWholeQty
    simulated_qty: WholeQty
    confirmed_trade_date: date
    execution_date: date | None
    evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence: tuple[DailyConditionEvidence | UnifiedConditionEvidence, ...]
    plan_version_id: str
    review_id: str
    basis_id: str
    executable_qty: WholeQty
    blockers: tuple[str, ...]
    reset_trade_date: date | None = None
    risk_invalidated: bool = False
    confirmation_kind: Literal["OFFICIAL_DAILY_CLOSE", "COMPLETED_BAR_CLOSE"] = (
        "OFFICIAL_DAILY_CLOSE"
    )
    execution_window: Literal["NEXT_EXCHANGE_SESSION_ONLY", "CURRENT_SESSION"] = (
        "NEXT_EXCHANGE_SESSION_ONLY"
    )
    confirmed_at: ShanghaiDatetime | None = None
    revision: Qty | None = None

    @model_validator(mode="after")
    def consumption(self):
        if self.market_linkage is not None and (
            self.market_linkage.calculation.authorized_quantity != self.planned_qty
            or self.market_linkage.rule_id != self.rule_id
            or self.market_linkage.decision_session != self.confirmed_trade_date
        ):
            raise ValueError("linked signal differs from frozen calculation")
        if (
            self.simulated_qty not in {0, self.planned_qty}
            or self.executable_qty not in {0, self.planned_qty}
            or (self.state == "SIMULATED") != (self.simulated_qty == self.planned_qty)
            or self.risk_invalidated
            and self.executable_qty != 0
            or self.state in {"EXPIRED", "INVALIDATED", "SIMULATED"}
            and self.executable_qty != 0
            or self.execution_date is not None
            and (
                self.execution_date < self.confirmed_trade_date
                or self.execution_date == self.confirmed_trade_date
                and self.execution_window != "CURRENT_SESSION"
            )
        ):
            raise ValueError("stored signal has inconsistent atomic consumption/window")
        return self


class DailyRiskState(DailyValue):
    kind: RiskKind
    status: Literal["CLEAR", "PENDING", "OBSERVATION", "CONFIRMED", "FULFILLED"]
    priority: int = Field(strict=True, ge=1, le=3)
    target_core_qty: WholeQty
    target_tactical_qty: WholeQty
    involves_core: bool = Field(strict=True)
    scope_evidence: str
    evidence_ids: tuple[str, ...]
    earliest_execution_date: date | None
    blockers: tuple[str, ...]
    risk_id: str | None = None
    revision: Qty | None = None
    verified_at: ShanghaiDatetime | None = None
    confirmed_trade_date: date | None = None
    breach_trade_date: date | None = None
    second_close_date: date | None = None
    risk_line_fen: Fen | None = None
    risk_comparison: Literal["LT", "LTE"] | None = None
    basis_id: str | None = None
    suspension_confirmation_policy: (
        Literal["RESUME_FIRST_CLOSE", "RESTART_ADJACENT_PAIR"] | None
    ) = None
    reassessment_id: str | None = None
    cause_cutover_date: date | None = None
    cause_cutover_at: ShanghaiDatetime | None = None
    consumed_evidence_ids: tuple[str, ...] = ()
    fulfilled_at: ShanghaiDatetime | None = None
    technical_evidence: tuple[UnifiedConditionEvidence, ...] = ()
    rule_id: str | None = Field(default=None, exclude_if=lambda v: v is None)
    holding_scope: RiskHoldingScope | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def branch(self):
        priorities = {"SEVERE_TECHNICAL": 2, "ORDINARY_TECHNICAL": 3}
        if self.priority != priorities[self.kind]:
            raise ValueError("risk priority differs from its branch")
        if self.status == "PENDING" and (
            self.kind != "ORDINARY_TECHNICAL"
            or any(
                x is None
                for x in (
                    self.breach_trade_date,
                    self.risk_line_fen,
                    self.risk_comparison,
                    self.basis_id,
                    self.suspension_confirmation_policy,
                )
            )
        ):
            raise ValueError("pending risk lacks the original close confirmation proof")
        if self.status in {"CONFIRMED", "FULFILLED"}:
            if self.confirmed_trade_date is None:
                raise ValueError("technical confirmation lacks official close date")
        return self


class DailyObsoleteRisk(DailyValue):
    risk_id: str | None
    kind: RiskKind
    status: Literal["CLEAR", "PENDING", "OBSERVATION", "CONFIRMED", "FULFILLED"]
    confirmed_trade_date: date | None
    scope_evidence: str = Field(max_length=2000)


class RiskLotAllocation(DailyValue):
    id: str
    bucket: Literal["CORE", "TACTICAL"]
    quantity: PositiveWholeQty


class DailySimulationBatch(DailyValue):
    id: str
    bucket: Literal["CORE", "TACTICAL"]
    quantity: PositiveWholeQty
    acquired_trade_date: date
    baseline: bool = Field(strict=True)
    plan_version_id: str | None = Field(default=None, exclude_if=lambda v: v is None)


class DailyOpeningSimulationBatch(DailyValue):
    """Private replay facts; missing dates never become synthetic acquisitions."""

    origin: Literal["monitor-loop-opening-v1"]
    id: str
    bucket: Literal["CORE", "TACTICAL"]
    quantity: PositiveWholeQty
    acquired_trade_date: date | None
    observed_trade_date: date
    sellable_quantity: WholeQty | None

    @model_validator(mode="after")
    def consistent(self):
        if self.sellable_quantity is not None and self.sellable_quantity > self.quantity:
            raise ValueError("opening sellable quantity exceeds the lot")
        if self.acquired_trade_date is not None and (
            self.acquired_trade_date > self.observed_trade_date
            or self.acquired_trade_date == self.observed_trade_date
            and self.sellable_quantity not in (None, 0)
        ):
            raise ValueError("opening acquisition contradicts observed T+1 availability")
        return self


class DailyPositionState(DailyValue):
    simulation_version: Literal["daily-simulation-v1"]
    initialized_at: ShanghaiDatetime
    initial_core_qty: WholeQty
    initial_tactical_qty: WholeQty
    batches: tuple[DailySimulationBatch | DailyOpeningSimulationBatch, ...] = Field(max_length=500)


class DailySimulationState(DailyValue):
    simulation_version: Literal["daily-simulation-v1"]
    simulation_id: str
    plan_version_id: str
    cause_id: str
    cause_revision: Qty
    side: Literal["BUY", "SELL"]
    quantity: PositiveWholeQty
    price_fen: Fen
    simulated_at: ShanghaiDatetime
    inventory_revision: Qty
    inventory: DailyInventoryView
    signal_id: str | None
    lot_allocations: tuple[RiskLotAllocation, ...] = Field(
        default=(), max_length=500, exclude_if=lambda v: not v)


class DailyReviewBinding(DailyValue):
    confirmed: bool = Field(strict=True)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_id: str | None
    review_revision: Qty
    plan_version_id: str

    @model_validator(mode="after")
    def current(self):
        if self.confirmed != (self.review_id is not None) or self.review_revision != int(
            self.confirmed
        ):
            raise ValueError("review binding is inconsistent")
        return self


class DailyHumanSupplementState(DailyValue):
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: Literal["EXPLICIT_HUMAN_OPERATION"]
    supplements: tuple[DailySupplement, ...]


def validate_daily_payload(kind, value):
    models = {
        "FACT": DailyFactState,
        "SIGNAL": DailySignalState,
        "RISK": DailyRiskState,
        "SIMULATION": DailySimulationState,
        "POSITION": DailyPositionState,
        "REVIEW": DailyReviewBinding,
        "DRAFT": DailyHumanSupplementState,
    }
    model = models.get(kind)
    if model is not None:
        model.model_validate(value)
    elif kind == "EXTRACTION":
        from trade_plan_monitor.ai.plan_extraction import CurrentPlanExtractionResult
        from trade_plan_monitor.domain.daily_plan_validation import DailyPlanDraft

        class HistoricalExtractionEvidence(CurrentPlanExtractionResult):
            """Decode frozen Schema4 audit bytes without enabling an extraction workflow."""

            draft: DailyPlanDraft

        model = (
            CurrentPlanExtractionResult
            if value.get("draft", {}).get("schema_version") in {5, 6, 7}
            else HistoricalExtractionEvidence
        )
        model.model_validate(value)
    elif kind == "EVALUATION":
        validate_daily_evaluation(value)
    elif kind in {"EXCEPTION_CANDIDATE", "EXCEPTION_EVENT"}:
        from trade_plan_monitor.state.market_exception_models import (
            ExceptionCandidate,
            ExceptionEvent,
        )
        (ExceptionCandidate if kind == "EXCEPTION_CANDIDATE" else ExceptionEvent).model_validate(
            value)
    elif kind == "EXCEPTION_PREVIEW":
        from trade_plan_monitor.state.market_exception_service import ExceptionPreview
        ExceptionPreview.model_validate(value)
    elif kind == "REASSESSMENT":
        if not isinstance(value, dict) or set(value) != {
            "prior_risk",
            "new_plan_version_id",
            "content_hash",
            "removal_evidence",
        }:
            raise ValueError("invalid reassessment audit")
        DailyRiskState.model_validate(value["prior_risk"]["payload"])
        proof = value["removal_evidence"]
        if isinstance(proof, str):
            require_technical_text(proof)
        else:
            DailyOfficialProof.model_validate(proof)
    else:
        raise ValueError("unknown daily record kind")


class DailyInventoryView(DailyValue):
    symbol: str
    revision: Qty
    known: bool = Field(strict=True)
    total_qty: WholeQty | None
    core_qty: WholeQty | None
    tactical_qty: WholeQty | None
    sellable_core: WholeQty | None
    sellable_tactical: WholeQty | None

    @model_validator(mode="after")
    def total(self):
        if self.known:
            if (
                any(q is None for q in (self.total_qty, self.core_qty, self.tactical_qty))
                or self.core_qty + self.tactical_qty != self.total_qty
            ):
                raise ValueError("simulation inventory has inconsistent buckets")
        elif any(
            q is not None
            for q in (
                self.total_qty,
                self.core_qty,
                self.tactical_qty,
                self.sellable_core,
                self.sellable_tactical,
            )
        ):
            raise ValueError("uninitialized simulation cannot attest holdings")
        for side in ("core", "tactical"):
            actual, sellable = getattr(self, side + "_qty"), getattr(self, "sellable_" + side)
            if sellable is not None and (actual is None or sellable > actual):
                raise ValueError("simulation sellability exceeds its bucket")
        return self


DailySimulationState.model_rebuild()


class DailyRiskAction(DailyValue):
    status: Literal["WAITING", "NONE", "RISK_EXIT"]
    branch: RiskKind | None = None
    cause_id: str | None = None
    cause_revision: Qty | None = None
    core_qty: WholeQty | None
    tactical_qty: WholeQty | None
    unavailable_core_qty: WholeQty | None
    unavailable_tactical_qty: WholeQty | None
    target_core_qty: WholeQty | None = None
    target_tactical_qty: WholeQty | None = None
    blockers: tuple[str, ...]
    lot_allocations: tuple[RiskLotAllocation, ...] = Field(
        default=(), max_length=500, exclude_if=lambda v: not v)


class DailyFactRevision(DailyValue):
    id: str
    revision: Qty


class DailyRuleReminderState(DailyValue):
    rule_id: str
    alert_kind: Literal["RISK_ALERT"]
    cause_id: str | None
    outcome: Literal["SATISFIED", "UNSATISFIED", "MISSING_INPUT"]
    confirmation_kind: Literal["OFFICIAL_DAILY_CLOSE", "COMPLETED_BAR_CLOSE"]
    confirmed_trade_date: date | None
    confirmed_at: ShanghaiDatetime | None
    evidence: tuple[dict, ...] = Field(max_length=1)


class DailyEvaluationState(DailyValue):
    linked_index_source: MarketIndexSnapshot | None = Field(
        default=None, exclude_if=lambda v: v is None
    )

    @field_validator("linked_index_source", mode="before")
    @classmethod
    def index_source_json(cls, value):
        import json
        if isinstance(value, dict):
            return (MarketIndexSnapshot.model_validate_json(json.dumps(value))
                    if isinstance(value.get("decision_cutoff"), str)
                    else MarketIndexSnapshot.model_validate(value))
        return value

    market_linkage: tuple[MarketLinkageDecision, ...] | None = Field(
        default=None, max_length=2, exclude_if=lambda v: v is None)
    symbol: str
    plan_version_id: str
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_id: str
    activation_revision: Qty
    evaluated_at: ShanghaiDatetime
    official_trade_date: date | None
    inventory: DailyInventoryView
    fact_revisions: tuple[DailyFactRevision, ...]
    signals: tuple[DailySignalState, ...] = Field(max_length=500)
    alerts: tuple[DailyRuleReminderState, ...] = Field(default=(), max_length=10)
    risks: tuple[DailyRiskState, ...] = Field(max_length=64)
    risk_action: DailyRiskAction
    risk_input_known: bool | None = None
    data_blockers: tuple[str, ...]
    daily_evidence: DailySeries | None
    quote: DailyExecutionQuote | None
    minute_target: ShanghaiDatetime | None = None
    runtime_generation: str | None = None
    minute_prefix: tuple[MinuteBar, ...] = Field(default=(), max_length=240)
    five_minute_bars: tuple[FiveMinuteBar, ...] = Field(default=(), max_length=1000)
    next_action: Literal[
        "REVIEW_RISK_EXIT", "CONFIRM_SIMULATED_TRADE", "WAIT_FOR_VERIFIED_INPUT_OR_NEXT_SESSION"
    ]

    @field_validator("minute_prefix", "five_minute_bars", mode="before")
    @classmethod
    def market_json(cls, value, info):
        import json

        model = MinuteBar if info.field_name == "minute_prefix" else FiveMinuteBar
        return tuple(
            model.model_validate_json(json.dumps(v)) if isinstance(v, dict) else v for v in value
        )

    @model_validator(mode="after")
    def availability(self):
        if self.inventory.symbol != self.symbol:
            raise ValueError("evaluation inventory symbol mismatch")
        if self.daily_evidence is not None and (
            self.daily_evidence.symbol != self.symbol
            or self.daily_evidence.cutoff > self.evaluated_at
        ):
            raise ValueError("evaluation contains future or mismatched daily evidence")
        if self.quote is not None and (
            self.quote.symbol != self.symbol or self.quote.evaluated_at != self.evaluated_at
        ):
            raise ValueError("quote target does not match evaluation")
        if (
            self.official_trade_date is not None
            and self.official_trade_date > self.evaluated_at.date()
        ):
            raise ValueError("official close date follows evaluation")
        return self


def validate_daily_evaluation(value):
    DailyEvaluationState.model_validate(value)
