"""Transport-independent whole-quantity simulation in caller-owned transactions."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from trade_plan_monitor.decision.unified_lifecycle import check_execution
from trade_plan_monitor.domain.daily_plan_models import PositiveWholeQty, Qty
from trade_plan_monitor.domain.risk_scope import blocks_new_entry, risk_fulfilled
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.market_data.models import ShanghaiDatetime
from trade_plan_monitor.state.daily_accounting import DailyAccounting
from trade_plan_monitor.state.daily_state_models import DailyInventoryView, RiskLotAllocation
from trade_plan_monitor.state.repositories import PlanVersionNotFoundError, RevisionConflictError


class _SimulationValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    def model_copy(self, *, update=None, deep=False):
        if not update:
            return super().model_copy(deep=deep)
        return type(self).model_validate({**self.model_dump(mode="python"), **update})


class SimulationCommand(_SimulationValue):
    plan_version_id: UUID
    cause_id: str = Field(min_length=1, max_length=128)
    expected_cause_revision: Qty
    expected_inventory_revision: Qty
    quantity: PositiveWholeQty


class SimulationReceipt(_SimulationValue):
    simulation_id: str
    side: Literal["BUY", "SELL"]
    quantity: PositiveWholeQty
    price_fen: int = Field(gt=0)
    simulated_at: ShanghaiDatetime
    inventory_revision: Qty
    inventory: DailyInventoryView
    signal_id: str | None
    lot_allocations: tuple[RiskLotAllocation, ...] = Field(
        default=(), max_length=500, exclude_if=lambda v: not v)


class SimulationAuthorityError(ValueError):
    """Closed business rejection which adapters map to their existing transport."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _reject(reason: str) -> None:
    raise SimulationAuthorityError(reason)


def simulate_inventory(
    work,
    command: SimulationCommand,
    now: datetime,
    *,
    identity_factory=None,
) -> SimulationReceipt:
    """Recheck and write effects in the caller-owned UOW, without committing it."""
    from datetime import time
    from uuid import uuid4

    from trade_plan_monitor.decision.daily_lifecycle import check_daily_execution
    from trade_plan_monitor.decision.daily_risk import risk_execution
    from trade_plan_monitor.domain.plan_codec import load_plan_json
    from trade_plan_monitor.market_data.daily_data import DailyExecutionQuote
    from trade_plan_monitor.state.daily_accounting import SIMULATION_VERSION
    from trade_plan_monitor.state.models import TradingCalendar

    details = work.plans.get_version_details(str(command.plan_version_id))
    if details is None:
        raise PlanVersionNotFoundError("daily version was not found")
    symbol = details.symbol
    work.daily.lock_symbol(symbol)
    accounting = DailyAccounting(work.daily)
    if accounting.legacy_reason(symbol):
        _reject("DAILY_SIMULATION_LEGACY_DATA_UNSUPPORTED")
    active = work.plans.get_active(symbol)
    review = work.daily.get("review-" + details.id)
    head = work.daily.get("evaluation-head-" + symbol)
    if (
        active is None
        or active.plan_version_id != details.id
        or review is None
        or not review["payload"]["confirmed"]
        or details.daily_issues
        or head is None
    ):
        _reject("DAILY_SIMULATION_CURRENT_REVIEW_REQUIRED")
    plan = load_plan_json(details.payload_json)
    if not isinstance(plan, UnifiedTradePlan):
        _reject("PLAN_REVIEW_REQUIRED")
    state = head["payload"]
    if (
        state["plan_version_id"] != details.id
        or state["activation_revision"] != active.revision
        or state["review_id"] != review["payload"]["review_id"]
    ):
        _reject("DAILY_SIMULATION_CURRENT_EVALUATION_REQUIRED")
    inventory = accounting.snapshot(symbol, now.date())
    if inventory["revision"] != command.expected_inventory_revision:
        raise RevisionConflictError(inventory["revision"])
    if not inventory["known"]:
        _reject("DAILY_SIMULATION_POSITION_REQUIRED")
    cause = work.daily.get(command.cause_id)
    if cause is None or cause["symbol"] != symbol or cause["kind"] not in {"SIGNAL", "RISK"}:
        raise PlanVersionNotFoundError("simulation cause was not found")
    if cause["revision"] != command.expected_cause_revision:
        raise RevisionConflictError(cause["revision"])
    if not accounting.evaluation_current(
        state,
        plan_version_id=details.id,
        content_hash=details.content_hash,
        inventory=inventory,
        now=now,
        require_daily_data=cause["kind"] == "SIGNAL",
    ):
        _reject("DAILY_SIMULATION_CURRENT_FACTS_REQUIRED")
    try:
        quote = DailyExecutionQuote.model_validate(
            {**(state.get("quote") or {}), "evaluated_at": now}
        )
    except ValueError:
        _reject("DAILY_SIMULATION_CURRENT_QUOTE_REQUIRED")
    current_day = work.daily.session.get(TradingCalendar, (plan.market, now.date()))
    clock = now.time().replace(tzinfo=None)
    tradable = (
        current_day is not None
        and current_day.is_open
        and (time(9, 30) <= clock < time(11, 30) or time(13) <= clock < time(15))
        and quote.tradable
        and quote.special_state_verified
        and quote.liquidity_available
    )
    risks = tuple(
        {**r["payload"], "revision": r["revision"]}
        for r in work.daily.list(symbol=symbol, kind="RISK")
    )
    signal_id = None
    lot_allocations = None
    lots = accounting.lots(symbol, now.date())
    if cause["kind"] == "SIGNAL":
        signal = cause["payload"]
        if state["data_blockers"]:
            _reject("DAILY_SIMULATION_CURRENT_EVALUATION_REQUIRED")
        if signal["plan_version_id"] != details.id or signal["state"] == "SIMULATED":
            _reject("DAILY_SIMULATION_SIGNAL_CONSUMED_OR_REPLACED")
        checked = (
            check_execution if isinstance(plan, UnifiedTradePlan) else check_daily_execution
        )(
            plan,
            signal,
            inventory=inventory,
            quote_fen=quote.price_fen,
            evaluated_at=now,
            tradable=tradable,
            risk_blocked=any(blocks_new_entry(r, now.date()) for r in risks),
            risk_known=state.get(
                "risk_input_known",
                state.get("daily_evidence") is not None or not plan.risk_branches,
            ),
        )
        if checked["executable_qty"] == 0 or any(
            "ORDINARY_CONFLICT_BLOCK_BOTH" in s["blockers"] for s in state["signals"]
        ):
            _reject("DAILY_SIMULATION_SIGNAL_NOT_EXECUTABLE")
        quantity, side = checked["executable_qty"], checked["side"]
        quantities = {"TACTICAL": quantity}
        signal_id = cause["id"]
    else:
        action = risk_execution(
            risks, plan=plan, inventory=inventory, evaluated_at=now, tradable=tradable, lots=lots
        )
        if action.get("cause_id") != cause["id"] or action["status"] != "RISK_EXIT":
            _reject("DAILY_SIMULATION_RISK_NOT_EXECUTABLE")
        quantities = {"CORE": action["core_qty"], "TACTICAL": action["tactical_qty"]}
        lot_allocations = action.get("lot_allocations")
        if action != state["risk_action"]:
            _reject("DAILY_SIMULATION_RISK_NOT_EXECUTABLE")
        if any(q is None for q in quantities.values()) or not sum(quantities.values()):
            _reject("DAILY_SIMULATION_RISK_NOT_EXECUTABLE")
        quantity, side = sum(quantities.values()), "SELL"
    if quantity != command.quantity:
        raise ValueError("simulation must consume the complete offered quantity")
    identity = str(uuid4()) if identity_factory is None else identity_factory()
    position = accounting.simulate(
        symbol=symbol,
        identity=identity,
        side=side,
        quantities=quantities,
        expected_revision=command.expected_inventory_revision,
        now=now,
        lot_allocations=lot_allocations,
        plan_version_id=details.id,
    )
    if signal_id is not None:
        work.daily.save(
            cause["id"],
            kind="SIGNAL",
            symbol=symbol,
            lineage=cause["lineage"],
            expected_revision=cause["revision"],
            payload={
                **checked,
                "state": "SIMULATED",
                "simulated_qty": quantity,
                "executable_qty": 0,
                "blockers": [],
            },
        )
    inventory = accounting.snapshot(symbol, now.date())
    for risk in risks:
        if (
            risk["status"] == "CONFIRMED"
            and risk_fulfilled(risk, inventory, accounting.lots(symbol, now.date()))
        ):
            current = work.daily.get(risk["risk_id"])
            work.daily.save(
                current["id"],
                kind="RISK",
                symbol=symbol,
                lineage=current["lineage"],
                expected_revision=current["revision"],
                payload={
                    **current["payload"],
                    "status": "FULFILLED",
                    "fulfilled_at": now.isoformat(),
                    "cause_cutover_date": str(now.date()),
                    "cause_cutover_at": now.isoformat(),
                    "consumed_evidence_ids": sorted(
                        set(risk.get("consumed_evidence_ids", ())) | set(risk["evidence_ids"])
                    ),
                },
            )
    result = SimulationReceipt(
        simulation_id=identity,
        side=side,
        quantity=quantity,
        price_fen=quote.price_fen,
        simulated_at=now,
        inventory_revision=position["revision"],
        inventory=DailyInventoryView.model_validate(inventory),
        signal_id=signal_id,
        lot_allocations=tuple(RiskLotAllocation.model_validate(a) for a in lot_allocations or ()),
    )
    work.daily.save(
        identity,
        kind="SIMULATION",
        symbol=symbol,
        lineage=details.plan_id,
        expected_revision=0,
        payload={
            "simulation_version": SIMULATION_VERSION,
            "simulation_id": identity,
            "plan_version_id": details.id,
            "cause_id": cause["id"],
            "cause_revision": cause["revision"],
            "side": side,
            "quantity": quantity,
            "price_fen": quote.price_fen,
            "simulated_at": now.isoformat(),
            "inventory_revision": position["revision"],
            "inventory": inventory,
            "signal_id": signal_id,
            **({"lot_allocations": lot_allocations} if lot_allocations else {}),
        },
    )
    return result
