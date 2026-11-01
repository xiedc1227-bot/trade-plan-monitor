"""Closed readiness observations; these values confer no business authority.

The read owner supplies observations and its own expiry policies. Nothing here
reads storage, samples a clock, evaluates a predicate or verifies a human fact.
"""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from trade_plan_monitor.decision.models import EvaluationTarget
from trade_plan_monitor.market_data.models import ShanghaiDatetime
from trade_plan_monitor.web.schemas import ApiValue

Reference = Annotated[str, Field(min_length=1, max_length=256)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Revision = Annotated[int, Field(ge=0, le=2**53 - 1)]
ReadinessAxis = Literal[
    "SOURCE_COVERAGE", "REVIEW_ACTIVATION", "RUNTIME_OWNERSHIP",
    "DATA_EVALUATION", "INVENTORY_CAPITAL", "NOTIFICATION_DELIVERY",
]
AxisState = Literal["PASS", "WAIT", "BLOCKED", "UNKNOWN", "NOT_APPLICABLE"]
RuleState = Literal[
    "CONDITION_TRUE", "CONDITION_FALSE", "WAITING_OFFICIAL_CONFIRMATION",
    "AWAITING_FIRST_EVALUATION", "MISSING_INPUT", "BLOCKED", "UNKNOWN",
]
ReadinessReason = Literal[
    "SOURCE_REVIEW_REQUIRED", "SAFETY_BLOCKED", "CONFIGURATION_BLOCKED",
    "MISSING_DATA", "STALE_DATA", "UNDEFINED_RULE", "HUMAN_EVIDENCE_REQUIRED",
    "EXPECTED_CONFIRMATION", "SERVICE_PENDING", "AWAITING_FIRST_EVALUATION",
    "AUTHORITY_UNAVAILABLE", "CONTEXT_CHANGED", "TARGET_MISMATCH",
    "EVIDENCE_EXPIRED", "DELIVERY_UNVERIFIED", "UPGRADE_REQUIRED",
    "DEPENDENCY_UNVERIFIED",
]
SummaryState = Literal[
    "READY_FOR_MONITORING", "WAITING_EXPECTED_CONFIRMATION", "WAITING_REQUIRED_SERVICE",
    "NEEDS_REVIEW", "BLOCKED", "UNKNOWN",
]
OwnerKind = Literal["ORDINARY_RULE", "ALERT_RULE", "RISK_BRANCH"]


class ReadinessContext(ApiValue):
    """Admitted read context, not every referenced evidence's original plan owner.

    Existing binding values confer no permission. Original risk ownership can
    differ from this read's active version and remains in the evidence references.
    """

    plan_version_id: UUID
    content_hash: Digest
    source_hash: Digest | None
    coverage_hash: Digest | None
    review_receipt_hash: Digest | None
    activation_revision: Annotated[int, Field(ge=1, le=2**53 - 1)] | None
    runtime_generation: UUID | None
    inventory_revision: Revision | None = None
    book_revision: Revision | None = None


class ReadinessObservation(ApiValue):
    """An observation made in context, with references retaining original owners.

    Evidence references may identify an original PlanVersion and its persisted
    risk/evaluation records. T17's existing owned read/proof paths resolve and
    verify those originals; context equality only prevents mixing read snapshots.
    """

    context: ReadinessContext
    availability: Literal["CURRENT", "CACHED", "UNAVAILABLE", "PERSISTED_ONLY"]
    observed_at: ShanghaiDatetime
    as_of: ShanghaiDatetime | None
    expires_at: ShanghaiDatetime | None
    evidence_refs: tuple[Reference, ...] = Field(min_length=1, max_length=128)
    provider: Reference | None = None
    price_basis: Reference | None = None
    formula_version: Reference | None = None
    calendar_reference: Reference | None = None

    @model_validator(mode="after")
    def ordered_times(self) -> Self:
        if self.as_of is not None and self.as_of > self.observed_at:
            raise ValueError("evidence as-of cannot follow its observation")
        return self


class AxisReadiness(ApiValue):
    axis: ReadinessAxis
    state: AxisState
    reason: ReadinessReason | None = None
    observation: ReadinessObservation | None = None

    @model_validator(mode="after")
    def state_evidence(self) -> Self:
        if self.state in {"PASS", "NOT_APPLICABLE"}:
            if self.reason is not None:
                raise ValueError("passing/inapplicable axes cannot carry a failure reason")
        elif self.reason is None:
            raise ValueError("nonpassing axes need an exact reason")
        if self.state == "PASS" and self.observation is None:
            raise ValueError("PASS requires an owned observation")
        if self.state == "WAIT" and self.reason not in {
            "EXPECTED_CONFIRMATION", "SERVICE_PENDING",
        }:
            raise ValueError("WAIT requires an established kind of expected wait")
        if self.state == "NOT_APPLICABLE" and self.axis != "INVENTORY_CAPITAL":
            raise ValueError("only exact inventory/capital dependencies may be inapplicable")
        return self


class InventoryRequirements(ApiValue):
    """Exact rule dependencies, independent of whether a money predicate passes."""

    inventory: bool = False
    sellability: bool = False
    quote: bool = False
    simulation_book: bool = False
    cost_basis: bool = False
    fees: bool = False
    economics: bool = False

    @property
    def required(self) -> bool:
        return any(self.model_dump().values())


class ConditionReadiness(ApiValue):
    condition_path: Annotated[str, Field(min_length=1, max_length=512)]
    state: Literal["CONDITION_TRUE", "CONDITION_FALSE", "MISSING_INPUT", "BLOCKED", "UNKNOWN"]
    reason: ReadinessReason | None = None
    evidence_refs: tuple[Reference, ...] = Field(default=(), max_length=128)

    @model_validator(mode="after")
    def complete_leaf_evidence(self) -> Self:
        if self.state in {"CONDITION_TRUE", "CONDITION_FALSE"}:
            if self.reason is not None or not self.evidence_refs:
                raise ValueError("complete leaves require evidence and no missing-input reason")
        elif self.reason is None:
            raise ValueError("incomplete leaves require an exact cause")
        return self


class ExpectedConfirmation(ApiValue):
    """A current owner's calendar schedule, never inferred from a wait string."""

    target: EvaluationTarget
    expected_at: ShanghaiDatetime
    calendar_reference: Reference
    prior_inputs_complete: bool
    observation: ReadinessObservation


class ReadinessExecutionState(ApiValue):
    """Preserve existing execution facts without calculating or granting eligibility."""

    approved_quantity: Revision | None = None
    consumed: bool | None = None
    execution_window: Literal["CURRENT_SESSION", "NEXT_EXCHANGE_SESSION_ONLY"] | None = None
    window_state: Literal["OPEN", "CLOSED", "UNKNOWN"] = "UNKNOWN"
    eligible: bool | None = None
    reason: Reference | None = None


class RuleReadinessFacts(ApiValue):
    owner_kind: OwnerKind
    owner_id: Annotated[str, Field(min_length=1, max_length=128)]
    side: Literal["BUY", "SELL"] | None
    requirements: InventoryRequirements
    expected_target: EvaluationTarget | None
    evaluated_target: EvaluationTarget | None
    evaluated_at: ShanghaiDatetime | None
    observation: ReadinessObservation | None
    root_outcome: Literal["SATISFIED", "UNSATISFIED", "MISSING_INPUT"] | None
    leaves: tuple[ConditionReadiness, ...] = Field(max_length=50)
    expected_confirmation: ExpectedConfirmation | None = None
    execution: ReadinessExecutionState = Field(default_factory=ReadinessExecutionState)

    @model_validator(mode="after")
    def exact_owner_and_leaves(self) -> Self:
        if (self.owner_kind == "ALERT_RULE") != (self.side is None):
            raise ValueError("alerts have no trade side; trade/risk rules need their actual side")
        if self.owner_kind == "RISK_BRANCH" and self.side != "SELL":
            raise ValueError("technical risk retains its SELL scope")
        if self.owner_kind == "ALERT_RULE" and self.requirements.required:
            raise ValueError("alert-only rules cannot acquire inventory/capital dependencies")
        paths = tuple(leaf.condition_path for leaf in self.leaves)
        if len(paths) != len(set(paths)):
            raise ValueError("condition paths must be unique within their actual rule")
        return self


class ReadinessSnapshot(ApiValue):
    computed_at: ShanghaiDatetime
    context: ReadinessContext
    scope: Literal["ALERT_ONLY", "TRADE_RULES", "MIXED"]
    axes: tuple[AxisReadiness, ...] = Field(min_length=6, max_length=6)
    rules: tuple[RuleReadinessFacts, ...] = Field(min_length=1, max_length=76)

    @model_validator(mode="after")
    def complete_scope(self) -> Self:
        if len({axis.axis for axis in self.axes}) != 6:
            raise ValueError("all six axes must appear exactly once")
        owners = tuple((rule.owner_kind, rule.owner_id) for rule in self.rules)
        if len(owners) != len(set(owners)):
            raise ValueError("rule owners must be unique")
        alerts = any(rule.owner_kind == "ALERT_RULE" for rule in self.rules)
        trades = any(rule.owner_kind != "ALERT_RULE" for rule in self.rules)
        scope = "MIXED" if alerts and trades else "ALERT_ONLY" if alerts else "TRADE_RULES"
        if self.scope != scope:
            raise ValueError("declared scope must match the actual included rule owners")
        if sum(len(rule.leaves) for rule in self.rules) > 50:
            raise ValueError("current native condition leaf limit is fifty")
        return self


class RuleReadiness(ApiValue):
    facts: RuleReadinessFacts
    state: RuleState
    reason: ReadinessReason | None = None


class ReadinessAssessment(ApiValue):
    contract_version: Literal["plan-monitor-readiness-v1"] = "plan-monitor-readiness-v1"
    authority_granted: Literal[False] = False
    snapshot: ReadinessSnapshot
    axes: tuple[AxisReadiness, ...] = Field(min_length=6, max_length=6)
    rules: tuple[RuleReadiness, ...] = Field(min_length=1, max_length=76)
    summary: SummaryState
    fresh_until: ShanghaiDatetime | None

    @field_validator("authority_granted", mode="before")
    @classmethod
    def literal_false_only(cls, value):
        if value is not False:
            raise ValueError("readiness grants no authority")
        return value
