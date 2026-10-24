"""Versioned eligibility evidence and explicitly granted frozen calculations."""

from typing import Literal

from pydantic import model_validator

from trade_plan_monitor.decision.confirmation_selection import (
    ConfirmationSelection,
    evaluate_confirmation,
)
from trade_plan_monitor.decision.market_exception_policy import select_exception
from trade_plan_monitor.decision.market_linkage import (
    MarketLinkageDecision,
    evaluate_market_linkage,
)
from trade_plan_monitor.decision.quantity_policy import QuantityCalculation
from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.market_exception_models import ExceptionRoute
from trade_plan_monitor.state.market_exception_models import ExceptionBinding, ExceptionEvent


class ExceptionCalculation(QuantityCalculation):
    formula_version: Literal["market-linkage-calculation-v2"] = "market-linkage-calculation-v2"
    route: ExceptionRoute | None
    approval: ExceptionEvent | None

    @model_validator(mode="after")
    def consistent_calculation(self):
        if self.calculation_hash != daily_hash(self.formula_version, self.model_dump(
                mode="json", exclude={"calculation_hash"})):
            raise ValueError("exception calculation hash mismatch")
        if self.route is None:
            if self.approval is not None:
                raise ValueError("ordinary calculation cannot consume exception authority")
            raw = self.model_dump(mode="json", exclude={"route", "approval", "calculation_hash"})
            raw["formula_version"] = "market-linkage-calculation-v1"
            raw["calculation_hash"] = daily_hash(raw["formula_version"], raw)
            QuantityCalculation.model_validate(raw)
            return self
        if self.factor is not None or self.ceiling != self.base_quantity:
            raise ValueError("exception uses an explicit quantity within Q0")
        candidate = (self.minimum if self.route == "WEAK_MINIMUM" else None)
        if self.approval is not None:
            if self.approval.to_state != "APPROVED":
                raise ValueError("only an approval event grants authority")
            candidate = self.approval.quantity
        if candidate != self.candidate_quantity:
            raise ValueError("exception quantity cannot be inferred or changed")
        if self.authorized_quantity != (
                candidate if self.approval is not None and not self.blockers else 0):
            raise ValueError("positive exception quantity requires exact approval")
        if self.approval is not None:
            if (candidate is None or self.minimum is None or self.increment is None
                    or not self.minimum <= candidate <= self.base_quantity
                    or (candidate-self.minimum) % self.increment
                    or self.capacity is None or candidate > self.capacity):
                raise ValueError("approved exception violates grid, ceiling or capacity")
            if self.route == "WEAK_MINIMUM" and (
                    candidate != self.minimum or self.base_quantity >= 2*self.minimum):
                raise ValueError("weak exception is exact below-minimum substitution")
        return self


class MarketExceptionDecision(MarketLinkageDecision):
    version: Literal["market-linkage-evidence-v2"] = "market-linkage-evidence-v2"
    calculation: ExceptionCalculation
    approval_binding: ExceptionBinding | None

    @model_validator(mode="after")
    def verify_evidence(self):
        if self.evidence_hash != daily_hash(self.version, self.model_dump(
                mode="json", exclude={"evidence_hash"})):
            raise ValueError("market exception evidence hash mismatch")
        event, binding = self.calculation.approval, self.approval_binding
        if (event is None) != (binding is None):
            raise ValueError("approval and occurrence binding are inseparable")
        if event is not None and (
                event.binding_hash != daily_hash("exception-binding-v1", binding.model_dump(
                    mode="json"))
                or binding.rule_id != self.rule_id or binding.content_hash != self.content_hash
                or binding.consumed_hash != self.consumed_hash
                or binding.decision_session != self.decision_session
                or binding.route != self.calculation.route
                or binding.base_quantity != self.calculation.base_quantity
                or binding.minimum != self.calculation.minimum
                or binding.increment != self.calculation.increment
                or self.quantity_rules is None
                or binding.grid_hash != self.quantity_rules.content_hash
                or not binding.evidence_cutoff <= event.received_at < binding.expires_at):
            raise ValueError("approval does not authorize this exact decision")
        return self


def _seal_calculation(raw):
    raw = dict(raw)
    raw.pop("calculation_hash", None)
    raw["calculation_hash"] = daily_hash("market-linkage-calculation-v2", raw)
    return ExceptionCalculation.model_validate(raw)


def _seal_decision(raw):
    raw = dict(raw)
    raw.pop("evidence_hash", None)
    raw["evidence_hash"] = daily_hash("market-linkage-evidence-v2", raw)
    return MarketExceptionDecision.model_validate(raw)


def evaluate_market_exception(plan, rule, **inputs):
    ordinary = evaluate_market_linkage(plan, rule, **inputs)
    grid = ordinary.quantity_rules
    # Confirmation components are shared with P0, including exact D/adjacent-session rules.
    outcome, _ = evaluate_confirmation(
        plan, rule, ordinary.selection.group, series=inputs["series"],
        facts=inputs.get("facts", ()),
        decision_session=inputs["decision_session"], risk=inputs["risk"])
    eligibility = select_exception(
        regime=ordinary.market.regime,
        strength="UNKNOWN" if ordinary.strength is None else ordinary.strength.strength,
        base_quantity=rule.quantity_policy.base_quantity,
        minimum=None if grid is None else grid.minimum,
        increment=None if grid is None else grid.increment,
        confirmation=outcome, risk=inputs["risk"], permissions=rule.market_policy.exception_routes)
    calculation = ordinary.calculation.model_dump(mode="json") | dict(
        formula_version="market-linkage-calculation-v2", route=eligibility.route, approval=None)
    selection = ordinary.selection
    if eligibility.route is not None:
        selection = ConfirmationSelection(group=eligibility.group, needs_strength=True,
            blocker=eligibility.blockers[0] if eligibility.blockers else None)
        calculation.update(factor=None, ceiling=calculation["base_quantity"],
            candidate_quantity=(None if eligibility.route == "BROKEN_STRONG"
                                else calculation["minimum"]), authorized_quantity=0,
            blockers=[*eligibility.blockers, "EXCEPTION_APPROVAL_REQUIRED"])
    raw = ordinary.model_dump(mode="json") | dict(
        version="market-linkage-evidence-v2", approval_binding=None,
        calculation=_seal_calculation(calculation).model_dump(mode="json"),
        selection=selection.model_dump(mode="json"),
        consumed_hash=daily_hash("market-linkage-consumed-v2", {
            "base": ordinary.consumed_hash, "route": eligibility.route}))
    return _seal_decision(raw)


def grant_exception(decision, candidate, event, *, capacity):
    """Called only after a repository-verified explicit event in the same transaction."""
    decision = MarketExceptionDecision.model_validate_json(decision.model_dump_json())
    if (candidate.state != "APPROVED" or candidate.approval_id != event.event_id
            or event.candidate_id != candidate.candidate_id
            or candidate.binding.consumed_hash != decision.consumed_hash
            or candidate.binding.route != decision.calculation.route
            or decision.selection.blocker is not None):
        raise ValueError("exception grant does not match current eligible occurrence")
    calculation = decision.calculation.model_dump(mode="json") | dict(
        candidate_quantity=event.quantity, authorized_quantity=event.quantity,
        capacity=capacity, blockers=[], approval=event.model_dump(mode="json"))
    return _seal_decision(decision.model_dump(mode="json") | dict(
        calculation=_seal_calculation(calculation).model_dump(mode="json"),
        approval_binding=candidate.binding.model_dump(mode="json")))


def parse_linkage_decision(value):
    model = (MarketExceptionDecision if value.get("version") == "market-linkage-evidence-v2"
             else MarketLinkageDecision)
    return model.model_validate(value)
