"""Closed persistent daily state graphs; quantities and provenance survive validation."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from trade_plan_monitor.ai.daily_review import DailySupplement
from trade_plan_monitor.decision.daily_conditions import DailyConditionEvidence
from trade_plan_monitor.decision.daily_risk import DailyRiskBirth, OrdinaryRiskCloseObservation
from trade_plan_monitor.decision.market_exception_decision import MarketExceptionDecision
from trade_plan_monitor.decision.market_linkage import MarketLinkageDecision
from trade_plan_monitor.decision.models import EvaluationTarget
from trade_plan_monitor.decision.p2_economics import EconomicsResult
from trade_plan_monitor.decision.p3_capital import CapitalAssessment
from trade_plan_monitor.decision.p3_composition import CapitalMarketDecision
from trade_plan_monitor.decision.unified_conditions import UnifiedConditionEvidence
from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.domain.daily_plan_models import (
    DailyValue,
    FactKind,
    Fen,
    Identifier,
    PositiveWholeQty,
    Qty,
    RiskKind,
    WholeQty,
)
from trade_plan_monitor.domain.daily_scope import require_technical_text
from trade_plan_monitor.domain.p2_evidence import FrozenPretrade
from trade_plan_monitor.domain.reviewed_fact_targets import ReviewedFactTarget
from trade_plan_monitor.domain.risk_scope import RiskHoldingScope, risk_identity
from trade_plan_monitor.domain.unified_plan_models import BuySuspensionDefinition, condition_leaves
from trade_plan_monitor.market_data.aggregation import (
    FiveMinuteBar,
    aggregate_five_minute_bar,
    expected_five_minute_ends,
)
from trade_plan_monitor.market_data.daily_data import DailyExecutionQuote, DailySeries
from trade_plan_monitor.market_data.models import AShareSymbol, MinuteBar, ShanghaiDatetime
from trade_plan_monitor.market_index.canonical import canonical_value
from trade_plan_monitor.market_index.models import MarketIndexSnapshot
from trade_plan_monitor.state.market_exception_models import ExceptionCandidateResource
from trade_plan_monitor.state.source_coverage_values import (
    BuySuspensionReplacementBinding,
    BuySuspensionReplacementIntent,
)

Digest = str


class BuySuspensionPriceBasis(DailyValue):
    """Private adapter input, not provider verification or registration authority.

    The adapter must obtain actual unadjusted stk_mins semantics and factors.
    Equality to the actual current anchor, not equality to 1, permits comparison.
    """

    source_contract: Literal["TUSHARE_STK_MINS_241_END_V1"]
    trade_date: date
    anchor_date: date
    trade_date_factor: Decimal = Field(gt=0, allow_inf_nan=False)
    anchor_factor: Decimal = Field(gt=0, allow_inf_nan=False)
    verified_at: ShanghaiDatetime

    @model_validator(mode="after")
    def dates(self):
        if not self.trade_date <= self.anchor_date <= self.verified_at.date():
            raise ValueError("suspension basis contains future or reversed dates")
        return self

    @property
    def comparable(self):
        return self.trade_date_factor == self.anchor_factor


class BuySuspensionCoverage(DailyValue):
    """Compact checked prefix; validity still requires the owning storage adapter."""

    through: ShanghaiDatetime
    content_hash: str = Field(strict=True, pattern=r"^[0-9a-f]{64}$")
    anchor_date: date | None
    anchor_factor: Decimal | None = Field(gt=0, allow_inf_nan=False)
    generation: Identifier

    @model_validator(mode="after")
    def actual_anchor_or_empty_calendar_interval(self):
        if (self.anchor_date is None) != (self.anchor_factor is None):
            raise ValueError("suspension coverage requires both actual anchor fields or neither")
        return self


class BuySuspensionTrigger(DailyValue):
    bar_end: ShanghaiDatetime
    close_fen: Fen
    source_hash: str = Field(strict=True, pattern=r"^[0-9a-f]{64}$")
    basis: BuySuspensionPriceBasis
    observed_at: ShanghaiDatetime

    @model_validator(mode="after")
    def actual_completed_observation(self):
        expected_five_minute_ends(self.bar_end)
        if (self.basis.trade_date != self.bar_end.date() or not self.basis.comparable
                or max(self.bar_end, self.basis.verified_at) > self.observed_at):
            raise ValueError("suspension trigger lacks a completed comparable observation")
        return self


class DailyBuySuspensionState(DailyValue):
    """One immutable original guard owner with resumable coverage and a durable latch."""

    model_config = ConfigDict(revalidate_instances="always")

    version: Literal["buy-suspension-state-v1"] = "buy-suspension-state-v1"
    symbol: AShareSymbol
    owner_plan_version_id: Identifier
    content_hash: str = Field(strict=True, pattern=r"^[0-9a-f]{64}$")
    source_hash: str = Field(strict=True, pattern=r"^[0-9a-f]{64}$")
    review_id: Identifier
    birth_activation_revision: int = Field(strict=True, gt=0, le=2**53 - 1)
    definition: BuySuspensionDefinition
    evaluated_at: ShanghaiDatetime
    target: ShanghaiDatetime
    coverage: BuySuspensionCoverage | None = None
    trigger: BuySuspensionTrigger | None = None
    blocker: Literal[
        "HISTORY_PENDING", "START_NOT_REACHED", "MINUTE_GAP", "CALENDAR_UNVERIFIED",
        "PRICE_BASIS_UNVERIFIED", "SOURCE_UNVERIFIED", "PROOF_INVALIDATED",
        "GENERATION_CHANGED", "BATCH_BUDGET_EXHAUSTED",
    ] | None = "HISTORY_PENDING"

    @model_validator(mode="after")
    def bounded_evidence(self):
        if (self.target > self.evaluated_at or self.target.minute % 5
                or self.target.second or self.target.microsecond):
            raise ValueError("suspension target must be an observed five-minute boundary")
        coverage = self.coverage
        if coverage is not None and self.blocker in {"PROOF_INVALIDATED", "GENERATION_CHANGED"}:
            raise ValueError("invalidated suspension proof cannot contribute checked coverage")
        if coverage is not None and (
                not self.definition.effective_from <= coverage.through <= self.target
                or coverage.through.minute % 5 or coverage.through.second
                or coverage.through.microsecond
                or coverage.anchor_date is not None
                and coverage.anchor_date > self.evaluated_at.date()):
            raise ValueError("suspension coverage exceeds its actual interval")
        trigger = self.trigger
        if (trigger is None and coverage is not None and coverage.through == self.target
                and self.blocker is not None):
            raise ValueError("unverified suspension cannot claim complete effective coverage")
        if trigger is not None and (
                trigger.bar_end - timedelta(minutes=5) < self.definition.effective_from
                or trigger.bar_end > self.target or trigger.observed_at > self.evaluated_at
                or trigger.close_fen >= self.definition.condition.price_fen):
            raise ValueError("suspension trigger does not satisfy its original guard")
        if (trigger is None and self.blocker is None
                and (coverage is None or coverage.through != self.target)):
            raise ValueError("clear suspension requires exact continuous target coverage")
        return self

    @property
    def outcome(self):
        if self.trigger is not None:
            return "LATCHED"
        return "UNVERIFIED" if self.blocker is not None else "CLEAR_THROUGH_TARGET"

    @property
    def unresolved_interval(self):
        start = self.definition.effective_from if self.coverage is None else self.coverage.through
        if start == self.target and self.coverage is not None:
            return None, None
        return start, self.target if self.target >= start else None

    @property
    def state_hash(self):
        return daily_hash(self.version, self.model_dump(mode="json"))

    @property
    def definition_hash(self):
        return daily_hash("buy-suspension-definition-v1", self.definition.model_dump(mode="json"))


class ReviewedFactObservation(DailyValue):
    """Private shape only; source hash is not SQL ownership or market truth."""

    model_config = ConfigDict(str_strip_whitespace=False, revalidate_instances="always")

    bar_end: ShanghaiDatetime
    source_hash: str = Field(strict=True, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def completed_boundary(self):
        expected_five_minute_ends(self.bar_end)
        return self


def reviewed_fact_observation_source_hash(minutes, aggregate):
    """Hash only one completed bucket's exact content, excluding receipt time.

    Revalidate typed values and reaggregate; availability, actual SQL head and
    native confirmation scope remain the registration/consumer's responsibility.
    """
    if (type(minutes) is not tuple or len(minutes) != 5
            or any(not isinstance(value, MinuteBar) for value in minutes)
            or not isinstance(aggregate, FiveMinuteBar)):
        raise ValueError("observation requires five typed minutes and one aggregate")
    ordered = tuple(sorted((MinuteBar.model_validate(value.model_dump(mode="python"))
                            for value in minutes), key=lambda value: value.bar_end))
    bar = FiveMinuteBar.model_validate(aggregate.model_dump(mode="python"))
    if aggregate_five_minute_bar(ordered, bucket_end=bar.bar_end, is_open=True) != bar:
        raise ValueError("observation minutes do not match the completed aggregate")
    return daily_hash("reviewed-fact-observation-v1", canonical_value({
        "minutes": [value.model_dump(mode="python", exclude={"received_at"}) for value in ordered],
        "aggregate": bar.model_dump(mode="python"),
    }))


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
    reviewed_fact_target: ReviewedFactTarget | None = Field(
        default=None, exclude_if=lambda value: value is None)
    reviewed_fact_observation: ReviewedFactObservation | None = Field(
        default=None, exclude_if=lambda value: value is None)

    @field_validator("reviewed_fact_observation", mode="before")
    @classmethod
    def supplied_observation(cls, value):
        if value is None:
            raise ValueError("an explicitly supplied reviewed fact observation cannot be null")
        return (value.model_dump(mode="python")
                if isinstance(value, ReviewedFactObservation) else value)

    @field_validator("reviewed_fact_target", mode="before")
    @classmethod
    def supplied_target(cls, value):
        if value is None:
            raise ValueError("an explicitly supplied reviewed fact target cannot be null")
        # Revalidate nested instances rather than trusting model_construct output.
        return value.model_dump(mode="python") if isinstance(value, ReviewedFactTarget) else value

    @model_validator(mode="after")
    def target_metadata(self):
        target = self.reviewed_fact_target
        if target is not None and (target.plan_version_id != self.plan_version_id
                                   or target.content_hash != self.content_hash):
            raise ValueError("reviewed fact target metadata differs from its FACT")
        return self

    @model_validator(mode="after")
    def observation_metadata(self):
        observation = self.reviewed_fact_observation
        if observation is not None and (
                self.reviewed_fact_target is None or observation.bar_end.date() != self.trade_date
                or not observation.bar_end <= self.verified_at <= self.available_at):
            raise ValueError("reviewed fact observation differs from target/date/availability")
        return self

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
    capital_execution: CapitalAssessment | None = Field(
        default=None, exclude_if=lambda v: v is None)
    pretrade: FrozenPretrade | None = Field(default=None, exclude_if=lambda v: v is None)
    pretrade_execution: EconomicsResult | None = Field(
        default=None, exclude_if=lambda v: v is None)
    market_linkage: (
        CapitalMarketDecision | MarketExceptionDecision | MarketLinkageDecision | None
    ) = Field(default=None, exclude_if=lambda v: v is None)
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

    def validate_pretrade_linkage(self):
        """Bind pretrade sizing to its full proof; report references validate after resolution."""
        if self.pretrade is not None and (
            self.market_linkage is None
            or self.pretrade.rule_id != self.rule_id
            or self.pretrade.decision_session != self.confirmed_trade_date
            or self.pretrade.content_hash != self.market_linkage.content_hash
            or self.pretrade.sizing.q0 != self.market_linkage.calculation.base_quantity
        ):
            raise ValueError("pretrade evidence differs from frozen signal authority")

    @model_validator(mode="after")
    def consumption(self):
        self.validate_pretrade_linkage()
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
    origin_evaluation_id: Identifier | None = Field(
        default=None, exclude_if=lambda v: v is None)
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
    buy_suspension_replacement_intent: (
        BuySuspensionReplacementIntent | None
    ) = Field(default=None, exclude_if=lambda value: value is None)
    buy_suspension_replacement: (
        BuySuspensionReplacementBinding | None
    ) = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def current(self):
        if self.confirmed != (self.review_id is not None) or self.review_revision != int(
            self.confirmed
        ):
            raise ValueError("review binding is inconsistent")
        intent = self.buy_suspension_replacement_intent
        if intent is not None and (intent.candidate_content_hash, intent.source_hash) != (
                self.content_hash, self.source_hash):
            raise ValueError("replacement intent differs from this exact review source")
        receipt = self.buy_suspension_replacement
        if receipt is not None and (
                not self.confirmed or intent is None or receipt.intent != intent
                or (receipt.new_plan_version_id, receipt.new_content_hash, receipt.new_source_hash,
                    receipt.new_review_id, receipt.new_review_revision) != (
                    self.plan_version_id, self.content_hash, self.source_hash,
                    self.review_id, self.review_revision)):
            raise ValueError("replacement receipt differs from this exact confirmed review")
        return self


class DailyHumanSupplementState(DailyValue):
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: Literal["EXPLICIT_HUMAN_OPERATION"]
    supplements: tuple[DailySupplement, ...]
    buy_suspension_replacement_intent: (
        BuySuspensionReplacementIntent | None
    ) = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def exact_intent_candidate(self):
        if (self.buy_suspension_replacement_intent is not None
                and self.buy_suspension_replacement_intent.candidate_content_hash
                != self.content_hash):
            raise ValueError("replacement intent belongs to another supplement candidate")
        return self


def validate_daily_payload(kind, value):
    models = {
        "BUY_SUSPENSION": DailyBuySuspensionState,
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
        from trade_plan_monitor.ai.plan_extraction import (
            BuySuspensionPlanExtractionResult,
            CurrentPlanExtractionResult,
        )
        from trade_plan_monitor.domain.daily_plan_validation import DailyPlanDraft

        class HistoricalExtractionEvidence(CurrentPlanExtractionResult):
            """Decode frozen Schema4 audit bytes without enabling an extraction workflow."""

            draft: DailyPlanDraft

        if (value.get("contract_version") == "plan-buy-suspension-extraction-v1"
                and value.get("prompt_version") == "plan-extract-v13"
                and value.get("draft", {}).get("schema_version") == 10):
            model = BuySuspensionPlanExtractionResult
        else:
            model = (
                CurrentPlanExtractionResult
                if value.get("draft", {}).get("schema_version") in {5, 6, 7, 8, 9}
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


class DailyOrdinaryEvaluation(DailyValue):
    """One actual existing confirmation evaluation, not an execution permission."""

    plan_version_id: Identifier
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_id: Identifier
    activation_revision: int = Field(strict=True, gt=0, le=2**53 - 1)
    rule_id: Identifier
    target: EvaluationTarget
    evaluated_at: ShanghaiDatetime
    evidence: UnifiedConditionEvidence


class DailyRiskEvaluation(DailyValue):
    """One actual risk observation; it neither creates nor reassigns a cause."""

    plan_version_id: Identifier
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_id: Identifier
    activation_revision: int = Field(strict=True, gt=0, le=2**53 - 1)
    risk_identity: Identifier
    kind: RiskKind
    target: EvaluationTarget | None
    evaluated_at: ShanghaiDatetime
    evidence: UnifiedConditionEvidence | None
    ordinary_close: OrdinaryRiskCloseObservation | None

    @model_validator(mode="after")
    def actual_kind_and_target(self):
        if self.kind == "ORDINARY_TECHNICAL":
            if (self.evidence is not None or self.ordinary_close is None
                    or self.ordinary_close.risk_identity != self.risk_identity
                    or self.target is None or self.target.kind != "OFFICIAL_CLOSE"
                    or self.target.trade_date != self.ordinary_close.close_date):
                raise ValueError("ordinary risk requires its exact actual close observation")
        elif self.evidence is None or self.ordinary_close is not None:
            raise ValueError("severe risk requires its original condition evidence")
        if self.target is None:
            if self.evidence is None or self.evidence.outcome != "MISSING_INPUT":
                raise ValueError("a missing risk target cannot certify a complete condition")
        elif self.target.kind == "INTRADAY":
            if self.target.bucket_end > self.evaluated_at:
                raise ValueError("risk minute observation follows evaluation")
        elif (datetime.combine(self.target.trade_date, time(15), self.evaluated_at.tzinfo)
                > self.evaluated_at):
            raise ValueError("risk observation precedes its official close")
        return self


class DailyEvaluationState(DailyValue):
    risk_evaluations: tuple[DailyRiskEvaluation, ...] | None = Field(
        default=None, min_length=1, max_length=64, exclude_if=lambda v: v is None)
    risk_births: tuple[DailyRiskBirth, ...] | None = Field(
        default=None, min_length=1, max_length=64, exclude_if=lambda v: v is None)
    ordinary_evaluations: tuple[DailyOrdinaryEvaluation, ...] | None = Field(
        default=None, min_length=1, max_length=2, exclude_if=lambda v: v is None)
    pretrade: tuple[FrozenPretrade, ...] | None = Field(
        default=None, max_length=2, exclude_if=lambda v: v is None)
    exception_candidates: tuple[ExceptionCandidateResource, ...] | None = Field(
        default=None, exclude_if=lambda v: v is None)
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

    market_linkage: tuple[
        CapitalMarketDecision | MarketExceptionDecision | MarketLinkageDecision, ...
    ] | None = Field(
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

    @field_validator("ordinary_evaluations", mode="before")
    @classmethod
    def ordinary_evaluations_json(cls, value):
        if value is None or not isinstance(value, tuple | list):
            return value
        return tuple(DailyOrdinaryEvaluation.model_validate_json(canonical(item))
                     if isinstance(item, dict) else item for item in value)

    @field_validator("risk_evaluations", "risk_births", mode="before")
    @classmethod
    def risk_facts_json(cls, value, info):
        if value is None or not isinstance(value, tuple | list):
            return value
        model = DailyRiskEvaluation if info.field_name == "risk_evaluations" else DailyRiskBirth
        return tuple(model.model_validate_json(canonical(item))
                     if isinstance(item, dict) else item for item in value)

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
        risk_rows, births = self.risk_evaluations or (), self.risk_births or ()
        for observations in (risk_rows, births):
            if len({row.risk_identity for row in observations}) != len(observations):
                raise ValueError("risk facts require unique native owners")
            for row in observations:
                if sum(risk_identity(risk) == row.risk_identity and risk.kind == row.kind
                       for risk in self.risks) != 1:
                    raise ValueError("risk fact crosses its native risk owner")
        for row in risk_rows:
            if (row.plan_version_id, row.content_hash, row.review_id, row.activation_revision,
                row.evaluated_at) != (self.plan_version_id, self.content_hash, self.review_id,
                                      self.activation_revision, self.evaluated_at):
                raise ValueError("risk observation crosses its actual evaluation owner")
            if row.target is not None:
                if row.target.kind == "INTRADAY":
                    if row.target.bucket_end != self.minute_target:
                        raise ValueError("risk minute observation crosses its actual target")
                elif (self.daily_evidence is None
                      or row.target.trade_date != self.daily_evidence.bars[-1].trade_date):
                    raise ValueError("risk official observation crosses its actual target")
            if row.ordinary_close is not None and (
                    row.ordinary_close.close_fen != self.daily_evidence.bars[-1].close
                    or row.ordinary_close.current_basis_id != self.daily_evidence.basis_id):
                raise ValueError("risk comparison differs from its actual daily input")
        birth_dates = ({bar.trade_date for bar in self.daily_evidence.bars}
                       if births and self.daily_evidence is not None else set())
        for birth in births:
            if (birth.close_date not in birth_dates
                    or datetime.combine(birth.close_date, time(15), self.evaluated_at.tzinfo)
                    > self.evaluated_at):
                raise ValueError("risk birth lacks its actual consumed daily close")
        rows = self.ordinary_evaluations or ()
        if len({row.rule_id for row in rows}) != len(rows):
            raise ValueError("ordinary observations require unique native owners")
        if sum(len(tuple(condition_leaves(row.evidence.condition))) for row in rows) > 50:
            raise ValueError("ordinary observations exceed the native condition leaf bound")
        if sum(len(tuple(condition_leaves(row.evidence.condition)))
               for row in (*rows, *risk_rows) if row.evidence is not None) > 50:
            raise ValueError("risk observations exceed the native condition leaf bound")
        for row in rows:
            if (row.plan_version_id, row.content_hash, row.review_id, row.activation_revision,
                row.evaluated_at) != (self.plan_version_id, self.content_hash, self.review_id,
                                      self.activation_revision, self.evaluated_at):
                raise ValueError("ordinary observation crosses its actual evaluation owner")
            if row.target.kind == "INTRADAY":
                if (row.target.bucket_end != self.minute_target
                        or row.target.bucket_end > self.evaluated_at):
                    raise ValueError("ordinary minute observation crosses its actual target")
            elif (self.daily_evidence is None
                  or row.target.trade_date != self.daily_evidence.bars[-1].trade_date
                  or row.target.trade_date > self.evaluated_at.date()):
                raise ValueError("ordinary official observation crosses its actual target")
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
