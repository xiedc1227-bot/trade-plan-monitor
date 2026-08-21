"""Pure cross-field validation for immutable executable trade plans."""

from __future__ import annotations

from collections.abc import Iterator, Sequence, Set
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from trade_plan_monitor.domain.plan_models import (
    AllCondition,
    AnyCondition,
    ConditionNode,
    PriceLevels,
    PriceZone,
    TradePlan,
)

IssueCode = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Z][A-Z0-9_]*$",
    ),
]
IssuePath = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_.\[\]-]+$",
    ),
]
IssueMessage = Annotated[str, StringConstraints(min_length=1, max_length=512)]
StrictFlag = Annotated[bool, Field(strict=True)]
ZoneOwner = Literal["LOW_BUY", "PRESSURE"]


class _ValidationValue(BaseModel):
    """Close and freeze validation-boundary values."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_by_alias=True,
        validate_by_name=True,
        serialize_by_alias=True,
    )


class ValidationSeverity(StrEnum):
    """Severity levels with stable wire values."""

    ERROR = "ERROR"
    WARNING = "WARNING"


class MarketEvidence(StrEnum):
    """Provider-independent market-data capabilities used by Schema v1."""

    COMPLETED_5M_BARS = "COMPLETED_5M_BARS"
    DAILY_INDICATORS = "DAILY_INDICATORS"
    OFFICIAL_DAILY_BARS = "OFFICIAL_DAILY_BARS"
    TRADING_CALENDAR = "TRADING_CALENDAR"
    DAILY_PRICE_LIMITS = "DAILY_PRICE_LIMITS"


ALL_MARKET_EVIDENCE: frozenset[MarketEvidence] = frozenset(MarketEvidence)


class ReviewIssueKind(StrEnum):
    """Closed provenance-review issue kinds accepted from the AI boundary."""

    ASSUMPTION = "ASSUMPTION"
    WARNING = "WARNING"
    UNMAPPED_TEXT = "UNMAPPED_TEXT"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"


_ALWAYS_BLOCKING_REVIEW_KINDS = frozenset(
    {
        ReviewIssueKind.ASSUMPTION,
        ReviewIssueKind.WARNING,
        ReviewIssueKind.MISSING_EVIDENCE,
    }
)


class DraftReviewIssue(_ValidationValue):
    """Sanitized review state without arbitrary AI-generated display text."""

    kind: ReviewIssueKind
    path: IssuePath
    material: StrictFlag
    resolved: StrictFlag = False


class ValidationIssue(_ValidationValue):
    """One stable validation issue suitable for API serialization."""

    code: IssueCode
    path: IssuePath
    severity: ValidationSeverity
    message: IssueMessage
    activation_blocking: StrictFlag = Field(alias="activationBlocking")


class PlanValidationResult(_ValidationValue):
    """Validation issues plus derived save and activation decisions."""

    issues: tuple[ValidationIssue, ...] = ()

    @property
    def can_save(self) -> bool:
        """Return false when any semantic error makes the plan invalid."""

        return not any(issue.severity is ValidationSeverity.ERROR for issue in self.issues)

    @property
    def can_activate(self) -> bool:
        """Return false for save errors or unresolved activation blockers."""

        return self.can_save and not any(issue.activation_blocking for issue in self.issues)


_CONDITION_EVIDENCE: dict[str, frozenset[MarketEvidence]] = {
    "PRICE_IN_ZONE": frozenset({MarketEvidence.COMPLETED_5M_BARS}),
    "NO_NEW_LOW_FOR_BARS": frozenset({MarketEvidence.COMPLETED_5M_BARS}),
    "NON_DECREASING_CLOSE": frozenset({MarketEvidence.COMPLETED_5M_BARS}),
    "VOLUME_TO_PREVIOUS_LTE": frozenset({MarketEvidence.COMPLETED_5M_BARS}),
    "VOLUME_TO_MEDIAN_LTE": frozenset({MarketEvidence.COMPLETED_5M_BARS}),
    "MACD_HIST_IMPROVEMENT_GTE": frozenset({MarketEvidence.DAILY_INDICATORS}),
    "PRICE_RECLAIMS_INDICATOR": frozenset(
        {
            MarketEvidence.COMPLETED_5M_BARS,
            MarketEvidence.DAILY_INDICATORS,
        }
    ),
    "UPPER_WICK_RATIO_GTE": frozenset({MarketEvidence.COMPLETED_5M_BARS}),
    "RETREAT_FROM_SESSION_HIGH_GTE": frozenset({MarketEvidence.COMPLETED_5M_BARS}),
    "CLOSE_IN_BAR_LOWER_HALF": frozenset({MarketEvidence.COMPLETED_5M_BARS}),
    "CONSECUTIVE_CLOSES_BELOW_LEVEL": frozenset({MarketEvidence.COMPLETED_5M_BARS}),
    "OFFICIAL_CLOSE_BELOW_LEVEL": frozenset({MarketEvidence.OFFICIAL_DAILY_BARS}),
    "NEXT_TRADING_DAY_RECOVERY": frozenset(
        {
            MarketEvidence.OFFICIAL_DAILY_BARS,
            MarketEvidence.TRADING_CALENDAR,
        }
    ),
    "POSITION_BUCKET_AVAILABLE": frozenset(),
    "SELLABLE_QUANTITY_GTE": frozenset(),
    "MANUAL_EVENT_RISK_CLEAR": frozenset(),
    "DISTANCE_FROM_LIMIT_DOWN_GTE": frozenset(
        {
            MarketEvidence.COMPLETED_5M_BARS,
            MarketEvidence.DAILY_PRICE_LIMITS,
        }
    ),
    "LOWER_BAND_HITS_LTE": frozenset(
        {
            MarketEvidence.COMPLETED_5M_BARS,
            MarketEvidence.DAILY_INDICATORS,
        }
    ),
}


def _owned_fen_bounds(zone: PriceZone) -> tuple[int, int] | None:
    lowest_owned = zone.low_fen + (0 if zone.include_low else 1)
    highest_owned = zone.high_fen - (0 if zone.include_high else 1)
    if lowest_owned > highest_owned:
        return None
    return lowest_owned, highest_owned


def _zone_contains(zone: PriceZone, price_fen: int) -> bool:
    owned_bounds = _owned_fen_bounds(zone)
    if owned_bounds is None:
        return False
    return owned_bounds[0] <= price_fen <= owned_bounds[1]


def price_zone_owners(levels: PriceLevels, price_fen: int) -> tuple[ZoneOwner, ...]:
    """Return named actionable zones that own one exact integer-fen price."""

    if isinstance(price_fen, bool) or not isinstance(price_fen, int) or price_fen <= 0:
        raise ValueError("price_fen must be a positive integer")

    owners: list[ZoneOwner] = []
    if _zone_contains(levels.low_buy, price_fen):
        owners.append("LOW_BUY")
    if _zone_contains(levels.pressure, price_fen):
        owners.append("PRESSURE")
    return tuple(owners)


def _zones_overlap(left: PriceZone, right: PriceZone) -> bool:
    left_bounds = _owned_fen_bounds(left)
    right_bounds = _owned_fen_bounds(right)
    if left_bounds is None or right_bounds is None:
        return False
    return max(left_bounds[0], right_bounds[0]) <= min(left_bounds[1], right_bounds[1])


def _iter_leaf_conditions(
    node: ConditionNode,
    path: str,
) -> Iterator[tuple[str, ConditionNode]]:
    if isinstance(node, (AllCondition, AnyCondition)):
        for index, child in enumerate(node.conditions):
            yield from _iter_leaf_conditions(
                child,
                f"{path}.conditions[{index}]",
            )
        return
    yield path, node


def _error(code: str, path: str, message: str) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        path=path,
        severity=ValidationSeverity.ERROR,
        message=message,
        activation_blocking=True,
    )


def _warning(
    code: str,
    path: str,
    message: str,
    *,
    activation_blocking: bool,
) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        path=path,
        severity=ValidationSeverity.WARNING,
        message=message,
        activation_blocking=activation_blocking,
    )


def _validate_identity(plan: TradePlan) -> list[ValidationIssue]:
    suffix_to_market = {
        ".SH": "SSE",
        ".SZ": "SZSE",
        ".BJ": "BSE",
    }
    suffix = plan.symbol[-3:]
    expected_market = suffix_to_market[suffix]
    if plan.market == expected_market:
        return []
    return [
        _error(
            "SYMBOL_MARKET_MISMATCH",
            "market",
            f"Symbol suffix {suffix} requires market {expected_market}.",
        )
    ]


def _validate_position(plan: TradePlan) -> list[ValidationIssue]:
    target_qty = plan.position.core_target_qty + plan.position.tactical_target_qty
    if target_qty <= 0:
        return [
            _error(
                "POSITION_TARGET_EMPTY",
                "position",
                "Core and tactical target quantity must have a positive total.",
            )
        ]
    if target_qty > plan.position.max_qty:
        return [
            _error(
                "POSITION_TARGET_EXCEEDS_MAX",
                "position",
                "Core and tactical target quantity cannot exceed max_qty.",
            )
        ]
    return []


def _validate_levels(plan: TradePlan) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    levels = plan.levels
    low_buy_bounds = _owned_fen_bounds(levels.low_buy)
    pressure_bounds = _owned_fen_bounds(levels.pressure)

    for zone_name, owned_bounds in (
        ("low_buy", low_buy_bounds),
        ("pressure", pressure_bounds),
    ):
        if owned_bounds is None:
            issues.append(
                _error(
                    "PRICE_ZONE_EMPTY",
                    f"levels.{zone_name}",
                    "An actionable zone must own at least one integer-fen price.",
                )
            )

    if _zones_overlap(levels.low_buy, levels.pressure):
        issues.append(
            _error(
                "PRICE_ZONES_OVERLAP",
                "levels",
                "Low-buy and pressure zones cannot own the same price.",
            )
        )
    elif (
        low_buy_bounds is not None
        and pressure_bounds is not None
        and low_buy_bounds[0] > pressure_bounds[1]
    ):
        issues.append(
            _error(
                "PRICE_ZONE_ORDER_INVALID",
                "levels",
                "The low-buy zone must be below the pressure zone.",
            )
        )

    if levels.risk_line_fen >= levels.low_buy.low_fen:
        issues.append(
            _error(
                "RISK_LINE_NOT_BELOW_LOW_BUY",
                "levels.risk_line_fen",
                "The risk line must be below the low-buy zone.",
            )
        )

    if not _zone_contains(levels.pressure, levels.pressure_reference_fen):
        issues.append(
            _error(
                "PRESSURE_REFERENCE_OUTSIDE_ZONE",
                "levels.pressure_reference_fen",
                "The pressure reference must be owned by the pressure zone.",
            )
        )

    return issues


def _validate_market_evidence(
    plan: TradePlan,
    available_market_evidence: Set[MarketEvidence],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    policy_roots = (
        ("entry.condition", plan.entry.condition),
        ("reduction.condition", plan.reduction.condition),
        ("risk.condition", plan.risk.condition),
        ("blockers.condition", plan.blockers.condition),
    )

    for root_path, root in policy_roots:
        for path, condition in _iter_leaf_conditions(root, root_path):
            required = _CONDITION_EVIDENCE.get(condition.type)
            if required is None:
                issues.append(
                    _error(
                        "CONDITION_EVIDENCE_MAPPING_MISSING",
                        path,
                        f"Condition {condition.type} has no evidence capability mapping.",
                    )
                )
                continue
            for evidence in sorted(required - available_market_evidence):
                issues.append(
                    _warning(
                        "MARKET_EVIDENCE_UNAVAILABLE",
                        path,
                        f"Condition {condition.type} requires market evidence {evidence.value}.",
                        activation_blocking=True,
                    )
                )

    return issues


def _validate_review_issues(
    review_issues: Sequence[DraftReviewIssue],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for review_issue in review_issues:
        if review_issue.resolved:
            continue
        if review_issue.material:
            issues.append(
                _warning(
                    "UNRESOLVED_MATERIAL_AI_ISSUE",
                    review_issue.path,
                    "Resolve the material "
                    f"{review_issue.kind.value} review issue before activation.",
                    activation_blocking=True,
                )
            )
            continue
        if review_issue.kind in _ALWAYS_BLOCKING_REVIEW_KINDS:
            issues.append(
                _warning(
                    "UNRESOLVED_AI_REVIEW_ISSUE",
                    review_issue.path,
                    f"Resolve the {review_issue.kind.value} review issue before activation.",
                    activation_blocking=True,
                )
            )
            continue
        issues.append(
            _warning(
                "UNRESOLVED_AI_WARNING",
                review_issue.path,
                f"Review the unresolved non-material {review_issue.kind.value} issue.",
                activation_blocking=False,
            )
        )
    return issues


def validate_trade_plan(
    plan: TradePlan,
    *,
    available_market_evidence: Set[MarketEvidence],
    review_issues: Sequence[DraftReviewIssue] = (),
) -> PlanValidationResult:
    """Validate cross-field invariants and activation prerequisites."""

    evidence = frozenset(
        item if isinstance(item, MarketEvidence) else MarketEvidence(item)
        for item in available_market_evidence
    )
    issues = [
        *_validate_identity(plan),
        *_validate_position(plan),
        *_validate_levels(plan),
        *_validate_market_evidence(plan, evidence),
        *_validate_review_issues(review_issues),
    ]
    return PlanValidationResult(issues=tuple(issues))


__all__ = [
    "ALL_MARKET_EVIDENCE",
    "DraftReviewIssue",
    "MarketEvidence",
    "PlanValidationResult",
    "ReviewIssueKind",
    "ValidationIssue",
    "ValidationSeverity",
    "price_zone_owners",
    "validate_trade_plan",
]
