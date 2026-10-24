"""Shared linked decision path for production and frozen replay adapters."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import model_validator

from trade_plan_monitor.decision.confirmation_selection import (
    ConfirmationSelection,
    evaluate_confirmation,
    select_confirmation,
)
from trade_plan_monitor.decision.market_regime import MarketRegimeEvidence, classify_market_regime
from trade_plan_monitor.decision.quantity_policy import (
    QuantityCalculation,
    calculate_quantity,
    quantity_preflight,
)
from trade_plan_monitor.decision.relative_strength import (
    RelativeStrengthEvidence,
    evaluate_relative_strength,
)
from trade_plan_monitor.decision.unified_conditions import UnifiedConditionEvidence
from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.daily_plan_models import DailyValue
from trade_plan_monitor.domain.market_quantity_rules import MarketQuantityRules, official_buy_grid
from trade_plan_monitor.domain.plan_hash import daily_plan_content_sha256
from trade_plan_monitor.market_index.canonical import (
    canonical_decimal,
    canonical_value,
    linked_index_content_hash,
)
from trade_plan_monitor.market_index.formulas import calculate_linked_index_facts


class MarketLinkageDecision(DailyValue):
    version: Literal["market-linkage-evidence-v1"] = "market-linkage-evidence-v1"
    rule_id: str
    content_hash: str
    decision_session: date
    evidence_cutoff: datetime
    market: MarketRegimeEvidence
    strength: RelativeStrengthEvidence | None
    selection: ConfirmationSelection
    calculation: QuantityCalculation
    quantity_rules: MarketQuantityRules | None
    confirmation: tuple[UnifiedConditionEvidence, ...]
    consumed_hash: str
    evidence_hash: str

    @model_validator(mode="after")
    def verify_evidence(self):
        expected = daily_hash(
            "market-linkage-evidence-v1", self.model_dump(mode="json", exclude={"evidence_hash"})
        )
        if self.evidence_hash != expected:
            raise ValueError("market linkage evidence hash mismatch")
        return self


def _stock_content(series):
    """Retain adjusted prices/basis, excluding refetch receipts and derived IDs."""
    if series is None:
        return []
    return [canonical_value(bar.model_dump(mode="python", exclude={
        "bar_id", "received_at", "available_at", "adjustment_as_of",
    })) for bar in series.bars]


def _confirmation_content(proof):
    """Receipt-derived bar IDs remain in audit evidence, not event continuity."""
    value = proof.model_dump(mode="json", exclude={"bar_ids", "children"})
    value["operands"] = [_operand_content(operand) for operand in proof.operands]
    value["children"] = [_confirmation_content(child) for child in proof.children]
    return value


def _operand_content(value):
    try:
        number = Decimal(value)
    except InvalidOperation:
        return value
    return canonical_decimal(number) if number.is_finite() else value


def evaluate_market_linkage(
    plan,
    rule,
    *,
    series,
    index_bars,
    session_dates,
    decision_session,
    cutoff,
    facts=(),
    inventory,
    risk,
):
    index_facts = calculate_linked_index_facts(
        reference_market=plan.reference_market,
        bars=index_bars,
        session_dates=session_dates,
        decision_session=decision_session,
        evidence_cutoff=cutoff,
    )
    market = classify_market_regime(index_facts)
    grid = official_buy_grid(plan.symbol, decision_session)
    minimum, increment = (None, None) if grid is None else (grid.minimum, grid.increment)
    _, _, candidate, preflight_error = quantity_preflight(
        rule.quantity_policy.base_quantity, market.regime, minimum, increment
    )
    available = (
        None
        if preflight_error in {"MARKET_RULES_UNKNOWN", "MARKET_INPUT_UNKNOWN"}
        else bool(candidate)
    )
    selection = select_confirmation(regime=market.regime, ordinary_quantity_available=available)
    strength = None
    if selection.needs_strength:
        strength = evaluate_relative_strength(
            series=series,
            index_bars=index_bars,
            reference_market=plan.reference_market,
            session_dates=session_dates,
            decision_session=decision_session,
            cutoff=cutoff,
        )
        selection = select_confirmation(
            regime=market.regime, ordinary_quantity_available=available, strength=strength.strength
        )
    outcome, proofs = evaluate_confirmation(
        plan,
        rule,
        selection.group,
        series=series,
        facts=facts,
        decision_session=decision_session,
        risk=risk,
    )
    capacity = plan.position.max_qty - inventory["total_qty"] if inventory["known"] else None
    calculation = calculate_quantity(
        base_quantity=rule.quantity_policy.base_quantity,
        regime=market.regime,
        minimum=minimum,
        increment=increment,
        capacity=capacity,
        condition=outcome,
        risk=risk,
        route_blocker=selection.blocker,
    )
    content_hash = daily_plan_content_sha256(plan)
    # Exclude observation wall clock and inventory eligibility: neither changes
    # an unchanged independent event or permits resizing an existing signal.
    consumed = dict(
        content_hash=content_hash,
        rule_id=rule.rule_id,
        decision_session=str(decision_session),
        index_content=linked_index_content_hash(tuple(
            bar for bar in index_bars
            if bar.bar_at.date() <= decision_session and bar.observed_at <= cutoff
        )),
        stock=_stock_content(series),
        confirmation=[_confirmation_content(p) for p in proofs],
        grid=None if grid is None else grid.content_hash,
        strength=None if strength is None else canonical_value(strength.model_dump(
            mode="python", exclude={"cutoff", "source_hashes"})),
        selection=selection.model_dump(mode="json"),
    )
    payload = dict(
        version="market-linkage-evidence-v1",
        rule_id=rule.rule_id,
        content_hash=content_hash,
        decision_session=decision_session,
        evidence_cutoff=cutoff,
        market=market,
        strength=strength,
        selection=selection,
        calculation=calculation,
        quantity_rules=grid,
        confirmation=proofs,
        consumed_hash=daily_hash("market-linkage-consumed-v1", consumed),
    )
    unsigned = MarketLinkageDecision.model_construct(**payload, evidence_hash="")
    return MarketLinkageDecision(
        **payload,
        evidence_hash=daily_hash(
            "market-linkage-evidence-v1",
            unsigned.model_dump(mode="json", exclude={"evidence_hash"}),
        ),
    )
