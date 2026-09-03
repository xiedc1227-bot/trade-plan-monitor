"""Deterministic union and history sizing for plan-owned index fact requests."""

from __future__ import annotations

from trade_plan_monitor.domain.plan_models import (
    AllCondition,
    AnyCondition,
    IndexCloseGteMaCondition,
    IndexCloseLteMaCondition,
    IndexMaNonDecreasingCondition,
    IndexMaNonIncreasingCondition,
    IndexReturnGteCondition,
    IndexReturnLteCondition,
    TradePlan,
)
from trade_plan_monitor.market_index.canonical import canonical_json
from trade_plan_monitor.market_index.models import (
    MarketIndexFactRequest,
    ReturnFactRequest,
    ReturnWindow,
    SmaFactRequest,
    SmaLookbackFactRequest,
)

IndexCondition = (
    IndexCloseGteMaCondition
    | IndexCloseLteMaCondition
    | IndexMaNonDecreasingCondition
    | IndexMaNonIncreasingCondition
    | IndexReturnGteCondition
    | IndexReturnLteCondition
)
_INDEX_CONDITION_CLASSES = (
    IndexCloseGteMaCondition,
    IndexCloseLteMaCondition,
    IndexMaNonDecreasingCondition,
    IndexMaNonIncreasingCondition,
    IndexReturnGteCondition,
    IndexReturnLteCondition,
)


def iter_plan_index_conditions(plan: TradePlan) -> tuple[tuple[str, IndexCondition], ...]:
    """Return every index leaf in stable stored plan-path order."""

    if not isinstance(plan, TradePlan):
        raise TypeError("plan must be a TradePlan")
    leaves: list[tuple[str, IndexCondition]] = []

    def visit(node: object, path: str) -> None:
        if isinstance(node, _INDEX_CONDITION_CLASSES):
            leaves.append((path, node))
            return
        if isinstance(node, (AllCondition, AnyCondition)):
            for index, child in enumerate(node.conditions):
                visit(child, f"{path}.conditions[{index}]")

    for policy_name in ("entry", "reduction", "risk", "blockers"):
        visit(getattr(plan, policy_name).condition, f"{policy_name}.condition")
    return tuple(leaves)


def fact_request_for_index_condition(
    condition: IndexCondition,
) -> MarketIndexFactRequest:
    """Translate one approved plan leaf into one plan-neutral fact request."""

    if isinstance(condition, (IndexCloseGteMaCondition, IndexCloseLteMaCondition)):
        return SmaFactRequest(period=condition.period)
    if isinstance(
        condition,
        (IndexMaNonDecreasingCondition, IndexMaNonIncreasingCondition),
    ):
        return SmaLookbackFactRequest(
            period=condition.period,
            lookback=condition.lookback,
        )
    if isinstance(condition, (IndexReturnGteCondition, IndexReturnLteCondition)):
        return ReturnFactRequest(
            window=condition.window,
            window_size=condition.window_size,
        )
    raise TypeError("condition must be one approved market-index leaf")


def plan_index_fact_requests(plan: TradePlan) -> tuple[MarketIndexFactRequest, ...]:
    """Derive the exact deduplicated reusable fact set required by one plan."""

    return union_fact_requests(
        tuple(
            fact_request_for_index_condition(condition)
            for _path, condition in iter_plan_index_conditions(plan)
        )
    )


def union_fact_requests(
    *groups: tuple[MarketIndexFactRequest, ...],
) -> tuple[MarketIndexFactRequest, ...]:
    """Return the order-independent exact union of several plan request sets."""

    unique: dict[str, MarketIndexFactRequest] = {}
    for group in groups:
        if type(group) is not tuple:
            raise TypeError("market-index request groups must be tuples")
        for request in group:
            key = canonical_json(request)
            unique[key] = request
    return tuple(unique[key] for key in sorted(unique))


def required_bar_counts(
    requests: tuple[MarketIndexFactRequest, ...],
) -> tuple[int, int]:
    """Return exact minimum `(five-minute, official-daily)` history counts."""

    if type(requests) is not tuple:
        raise TypeError("market-index requests must be a tuple")
    five_minute_count = 1
    official_daily_count = 1
    for request in requests:
        if isinstance(request, SmaFactRequest):
            official_daily_count = max(official_daily_count, request.period)
        elif isinstance(request, SmaLookbackFactRequest):
            official_daily_count = max(
                official_daily_count,
                request.period + request.lookback,
            )
        elif isinstance(request, ReturnFactRequest):
            required = request.window_size + 1
            if request.window is ReturnWindow.FIVE_MINUTE_BUCKETS:
                five_minute_count = max(five_minute_count, required)
            else:
                official_daily_count = max(official_daily_count, required)
        else:  # pragma: no cover - closed request union
            raise TypeError("unsupported market-index fact request")
    return five_minute_count, official_daily_count


__all__ = [
    "fact_request_for_index_condition",
    "iter_plan_index_conditions",
    "plan_index_fact_requests",
    "required_bar_counts",
    "union_fact_requests",
]
