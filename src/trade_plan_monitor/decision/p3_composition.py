"""Schema9 composes source quantity, market routes and whole capital predicates."""

from typing import Literal

from pydantic import model_validator

from trade_plan_monitor.decision.confirmation_selection import ConfirmationSelection
from trade_plan_monitor.decision.market_exception_decision import MarketExceptionDecision
from trade_plan_monitor.decision.market_exception_policy import select_exception
from trade_plan_monitor.decision.market_linkage import linked_market_facts
from trade_plan_monitor.decision.p2_composition import prepare_p2_rule
from trade_plan_monitor.decision.p2_economics import EconomicsResult, calculate_economics
from trade_plan_monitor.decision.p2_sizing import SizingResult
from trade_plan_monitor.decision.p3_capital import (
    BoundedCapacity,
    CapitalAssessment,
    ShareCapacity,
    UnknownCapacity,
    assess_capital,
)
from trade_plan_monitor.decision.quantity_policy import quantity_preflight
from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.daily_plan_models import DailyValue, PositiveWholeQty, WholeQty
from trade_plan_monitor.domain.market_exception_models import ExceptionRoute
from trade_plan_monitor.domain.p2_policy_models import SafeFen
from trade_plan_monitor.state.market_exception_models import ExceptionEvent


class CapitalCalculation(DailyValue):
    formula_version: Literal["capital-market-calculation-v1"] = "capital-market-calculation-v1"
    base_quantity: PositiveWholeQty
    factor: Literal["1", "0.5"] | None
    ceiling: SafeFen | None
    minimum: SafeFen | None
    increment: SafeFen | None
    candidate_quantity: WholeQty | None
    share_capacity: ShareCapacity
    capital: CapitalAssessment
    authorized_quantity: WholeQty
    route: ExceptionRoute | None
    approval: ExceptionEvent | None
    blockers: tuple[str, ...]
    calculation_hash: str

    @model_validator(mode="after")
    def consistent_calculation(self):
        if self.calculation_hash != daily_hash(self.formula_version,
                self.model_dump(mode="json", exclude={"calculation_hash"})):
            raise ValueError("capital calculation hash mismatch")
        if self.route is None:
            if self.approval is not None:
                raise ValueError("ordinary calculation cannot consume exception authority")
            regime = ("NORMAL_TRANSITION" if self.factor == "1" else
                      "WEAK" if self.factor == "0.5" else "UNKNOWN")
            factor, ceiling, candidate, _ = quantity_preflight(
                self.base_quantity, regime, self.minimum, self.increment)
            if (factor, ceiling, candidate) != (
                    self.factor, self.ceiling, self.candidate_quantity):
                raise ValueError("capital calculation changed selected market quantity")
        else:
            candidate = (self.minimum if self.route == "WEAK_MINIMUM" else None)
            if self.approval is not None:
                candidate = self.approval.quantity
                if (self.approval.to_state != "APPROVED" or candidate is None
                        or self.minimum is None or self.increment is None
                        or not self.minimum <= candidate <= self.base_quantity
                        or not self.increment or (candidate-self.minimum) % self.increment):
                    raise ValueError("capital exception violates exact approved quantity")
            if (self.factor is not None or self.ceiling != self.base_quantity
                    or candidate != self.candidate_quantity
                    or self.route == "WEAK_MINIMUM" and (
                        candidate != self.minimum or self.base_quantity >= 2*self.minimum)):
                raise ValueError("capital exception cannot infer or resize quantity")
        if self.capital.share_capacity != self.share_capacity:
            raise ValueError("capital and share capacity differ")
        if self.capital.quantity != (self.candidate_quantity or None):
            raise ValueError("capital predicate covers a different quantity")
        expected = (self.candidate_quantity if self.candidate_quantity and not self.blockers
                    and (self.route is None or self.approval is not None) else 0)
        if self.authorized_quantity != expected:
            raise ValueError("capital authority differs from whole selected quantity")
        if self.authorized_quantity and (
                self.capital.outcome != "PASS" or isinstance(self.share_capacity, UnknownCapacity)
                or isinstance(self.share_capacity, BoundedCapacity)
                and self.authorized_quantity > self.share_capacity.remaining_qty):
            raise ValueError("capital authority exceeds current eligibility")
        return self


class CapitalMarketDecision(MarketExceptionDecision):
    version: Literal["capital-market-evidence-v1"] = "capital-market-evidence-v1"
    calculation: CapitalCalculation


class P3Decision(DailyValue):
    sizing: SizingResult
    economics: EconomicsResult | None
    decision: CapitalMarketDecision | None


def seal_capital_calculation(raw):
    raw = dict(raw)
    raw.pop("calculation_hash", None)
    return CapitalCalculation.model_validate(raw | {
        "calculation_hash": daily_hash("capital-market-calculation-v1", raw)})


def seal_capital_decision(raw):
    raw = dict(raw)
    raw.pop("evidence_hash", None)
    return CapitalMarketDecision.model_validate(raw | {
        "evidence_hash": daily_hash("capital-market-evidence-v1", raw)})


def evaluate_p3_market(plan, rule, *, retained_basis_fen=None, book_revision=None, **inputs):
    effective, sizing = prepare_p2_rule(plan, rule, series=inputs["series"],
        decision_session=inputs["decision_session"], cutoff=inputs["cutoff"])
    if effective is None:
        return P3Decision(sizing=sizing, economics=None, decision=None)
    facts = linked_market_facts(plan, effective, **inputs)
    market, grid = facts["market"], facts["grid"]
    minimum, increment = (None, None) if grid is None else (grid.minimum, grid.increment)
    factor, ceiling, candidate, error = quantity_preflight(
        sizing.q0, market.regime, minimum, increment)
    eligibility = select_exception(regime=market.regime,
        strength="UNKNOWN" if facts["strength"] is None else facts["strength"].strength,
        base_quantity=sizing.q0, minimum=minimum, increment=increment,
        confirmation=facts["outcome"], risk=inputs["risk"],
        permissions=effective.market_policy.exception_routes)
    selection = facts["selection"]
    if eligibility.route is not None:
        factor, ceiling = None, sizing.q0
        candidate = minimum if eligibility.route == "WEAK_MINIMUM" else None
        reasons = [*eligibility.blockers, "EXCEPTION_APPROVAL_REQUIRED"]
        selection = ConfirmationSelection(group=eligibility.group, needs_strength=True,
            blocker=eligibility.blockers[0] if eligibility.blockers else None)
    else:
        reasons = [code for code in (selection.blocker, error) if code]
        if facts["outcome"] != "SATISFIED":
            reasons.append("CONFIRMATION_UNKNOWN" if facts["outcome"] == "MISSING_INPUT"
                           else "CONFIRMATION_UNMET")
        if inputs["risk"] != "UNSATISFIED":
            reasons.append("HIGHER_PRIORITY_RISK" if inputs["risk"] == "SATISFIED"
                           else "RISK_INPUT_UNKNOWN")
    close = sizing.close_fen
    price = int(close) if close is not None and close == int(close) else None
    inventory = inputs["inventory"]
    capital = assess_capital(plan.position, quantity=candidate, price_fen=price,
        total_qty=inventory["total_qty"] if inventory["known"] else None,
        retained_basis_fen=retained_basis_fen, symbol=plan.symbol,
        session=inputs["decision_session"], inventory_revision=inventory.get("revision"),
        book_revision=book_revision, phase="CONFIRMATION")
    economics = calculate_economics(rule.pretrade_policy.economics,
        quantity=candidate, entry_fen=price, symbol=plan.symbol, session=inputs["decision_session"])
    reasons.extend(capital.blockers)
    reasons.extend(economics.blockers)
    calculation = seal_capital_calculation(dict(
        formula_version="capital-market-calculation-v1", base_quantity=sizing.q0,
        factor=factor, ceiling=ceiling, minimum=minimum, increment=increment,
        candidate_quantity=candidate, share_capacity=capital.share_capacity.model_dump(mode="json"),
        capital=capital.model_dump(mode="json"), authorized_quantity=candidate
        if candidate and not reasons and eligibility.route is None else 0,
        route=eligibility.route, approval=None, blockers=list(dict.fromkeys(reasons))))
    decision = seal_capital_decision(dict(version="capital-market-evidence-v1",
        rule_id=rule.rule_id, content_hash=facts["content_hash"],
        decision_session=str(inputs["decision_session"]),
        evidence_cutoff=inputs["cutoff"].isoformat(),
        market=market.model_dump(mode="json"),
        strength=None if facts["strength"] is None else facts["strength"].model_dump(mode="json"),
        selection=selection.model_dump(mode="json"),
        calculation=calculation.model_dump(mode="json"),
        quantity_rules=None if grid is None else grid.model_dump(mode="json"),
        confirmation=[p.model_dump(mode="json") for p in facts["proofs"]],
        approval_binding=None, consumed_hash=daily_hash("capital-consumed-v1", {
            "market": facts["consumed"], "route": eligibility.route,
            "policy": rule.pretrade_policy.model_dump(mode="json"),
            "sizing": sizing.model_dump(mode="json"),
            "limit": plan.position.limit.model_dump(mode="json")})))
    return P3Decision(sizing=sizing, economics=economics, decision=decision)
