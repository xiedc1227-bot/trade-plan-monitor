"""Daily commands share the normal plan lifecycle, idempotency store and inventory UOW."""

import json
from datetime import datetime

from trade_plan_monitor.decision.unified_conditions import requires_daily
from trade_plan_monitor.decision.unified_lifecycle import check_execution
from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.daily_plan_validation import (
    daily_draft_content_sha256,
    load_daily_draft_json,
)
from trade_plan_monitor.domain.plan_codec import load_plan_json
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.market_data.daily_data import DailySeries
from trade_plan_monitor.state.daily_accounting import DailyAccounting
from trade_plan_monitor.state.repositories import (
    PlanSaveBlockedError,
    PlanVersionNotFoundError,
    RevisionConflictError,
)
from trade_plan_monitor.web.idempotency import claim_replay, complete_replay
from trade_plan_monitor.web.routers.daily_plans import (
    DailyEvaluationApiView,
    DailyInventoryApiView,
    DailyInventoryResource,
    DailyMutationReceipt,
    DailyObsoleteRiskApiView,
    DailySimulationReceipt,
    DailyStateView,
)


def _declares_reviewed_fact(condition, kind):
    if condition.type in {"ALL", "ANY"}:
        return any(_declares_reviewed_fact(child, kind) for child in condition.conditions)
    return condition.type == "REVIEWED_FACT" and condition.fact_kind == kind


def _minute_reviewed_fact_scope(details, command, head, now):
    """A human fact may follow a certified completed minute confirmation."""
    if head is None or head["payload"].get("plan_version_id") != details.id:
        return False
    data = head["payload"]
    raw_target = data.get("minute_target")
    bars = data.get("five_minute_bars") or ()
    if raw_target is None or not bars or bars[-1].get("bar_end") != raw_target:
        return False
    target = datetime.fromisoformat(raw_target)
    if target.date() != command.trade_date or target > now:
        return False
    plan = load_plan_json(details.payload_json)
    if not isinstance(plan, UnifiedTradePlan):
        return False
    return any(
        rule.confirmation.kind == "COMPLETED_BAR_CLOSE"
        and not requires_daily(rule.condition)
        and _declares_reviewed_fact(rule.condition, command.kind)
        for rule in (*plan.ordinary_rules, *plan.alert_rules)
    )


def mutate_daily(lifecycle, *, operation_name, command, context, request_hash):
    operation = operation_name
    with lifecycle._unit_of_work() as work:
        from trade_plan_monitor.state.repositories import IdempotencyKeyReuseError

        try:
            replay = claim_replay(
                work,
                context=context,
                request_hash=request_hash,
                model_type=DailySimulationReceipt
                if operation == "SIMULATION"
                else DailyMutationReceipt,
            )
        except IdempotencyKeyReuseError:
            if operation in {"SIMULATION", "POSITION"}:
                _conflict("DAILY_SIMULATION_IDEMPOTENCY_CONFLICT")
            raise
        if replay is not None:
            return replay
        now = lifecycle._clock()
        try:
            if operation == "SUPPLEMENT":
                draft = load_daily_draft_json(command.candidate_json)
                digest = daily_draft_content_sha256(draft)
                if digest != command.content_hash:
                    raise ValueError("supplement candidate changed")
                from trade_plan_monitor.ai.daily_review import semantic_values

                values = semantic_values(draft)
                for item in command.supplements:
                    if (
                        item.candidate_content_hash != digest
                        or item.path not in values
                        or type(item.value) is not type(values[item.path])
                        or item.value != values[item.path]
                    ):
                        raise ValueError("supplement is not scoped to this current policy")
                identity = daily_hash(
                    "daily-human-supplements-v1", {"symbol": draft.symbol, "content_hash": digest}
                )
                work.daily.lock_symbol(draft.symbol)
                row = work.daily.save(
                    identity,
                    kind="DRAFT",
                    symbol=draft.symbol,
                    lineage=digest,
                    expected_revision=command.expected_revision,
                    payload={
                        "content_hash": digest,
                        "source": "EXPLICIT_HUMAN_OPERATION",
                        "supplements": [s.model_dump(mode="json") for s in command.supplements],
                    },
                )
            elif operation == "POSITION":
                accounting = DailyAccounting(work.daily)
                work.daily.lock_symbol(command.symbol)
                if accounting.legacy_reason(command.symbol):
                    _conflict("DAILY_SIMULATION_LEGACY_DATA_UNSUPPORTED")
                row = accounting.initialize(
                    symbol=command.symbol,
                    core_qty=command.core_qty,
                    tactical_qty=command.tactical_qty,
                    expected_revision=command.expected_revision,
                    now=now,
                )
            elif operation == "SIMULATION":
                result = _simulate(work, command, now)
                complete_replay(work, context=context, request_hash=request_hash, response=result)
                work.commit()
                return result
            else:
                details = work.plans.get_version_details(str(command.plan_version_id))
                if details is None:
                    raise PlanVersionNotFoundError("daily version was not found")
                if details.daily_mapping is None or details.content_hash != command.content_hash:
                    raise ValueError("fact requires the exact daily content binding")
                work.daily.lock_symbol(details.symbol)
                alert_only_fact = False
                if operation == "FACT":
                    fact_plan = load_plan_json(details.payload_json)
                    alert_only_fact = (isinstance(fact_plan, UnifiedTradePlan)
                        and bool(fact_plan.alert_rules) and not fact_plan.ordinary_rules
                        and not fact_plan.risk_branches)
                if (not alert_only_fact
                    and DailyAccounting(work.daily).legacy_reason(details.symbol)):
                    _conflict("DAILY_SIMULATION_LEGACY_DATA_UNSUPPORTED")
                if operation == "FACT":
                    if command.trade_date > now.date():
                        raise ValueError("future evidence is not available")
                    official = command.official_evidence
                    if (
                        official is not None
                        and not official.published_at <= official.verified_at <= now
                    ):
                        raise ValueError(
                            "official evidence publication/verification is future or inconsistent"
                        )
                    if command.signal_id is not None:
                        signal = work.daily.get(command.signal_id)
                        if (
                            signal is None
                            or signal["symbol"] != details.symbol
                            or signal["kind"] != "SIGNAL"
                        ):
                            raise ValueError("fact signal scope does not exist")
                    if command.kind not in {
                        "TRADABILITY",
                        "FULL_SESSION_SUSPENSION",
                        "INDEPENDENT_EVENT",
                        "SIGNAL_INVALIDATION",
                    }:
                        head = work.daily.get("evaluation-head-" + details.symbol)
                        series = (
                            None
                            if head is None or head["payload"].get("daily_evidence") is None
                            else DailySeries.model_validate(head["payload"]["daily_evidence"])
                        )
                        daily_match = series is not None and any(
                            b.trade_date == command.trade_date for b in series.bars
                        )
                        minute_match = _minute_reviewed_fact_scope(
                            details, command, head, now
                        )
                        if not daily_match and not minute_match:
                            raise ValueError(
                                "qualitative evidence requires its exact completed "
                                "confirmation period"
                            )
                    identity = daily_hash(
                        "daily-human-fact-v1",
                        {"symbol": details.symbol, "fact_id": command.fact_id},
                    )
                    row = work.daily.save(
                        identity,
                        kind="FACT",
                        symbol=details.symbol,
                        lineage=details.plan_id,
                        expected_revision=command.expected_revision,
                        payload={
                            "plan_version_id": details.id,
                            "content_hash": details.content_hash,
                            "kind": command.kind,
                            "trade_date": str(command.trade_date),
                            "signal_id": command.signal_id,
                            "evidence": command.evidence,
                            "verified": True,
                            "satisfied": command.satisfied,
                            "prior_signal_id": command.signal_id
                            if command.kind == "INDEPENDENT_EVENT"
                            else None,
                            "verified_at": now.isoformat(),
                            "available_at": now.isoformat(),
                            "official_evidence": None
                            if official is None
                            else official.model_dump(mode="json"),
                        },
                    )
                elif operation == "REASSESSMENT":
                    if (
                        details.symbol != command.symbol
                        or details.review_id is None
                        or details.daily_issues
                    ):
                        raise ValueError(
                            "risk reassessment requires a current reviewed daily policy"
                        )
                    official = command.removal_evidence
                    from trade_plan_monitor.domain.daily_scope import require_technical_text

                    require_technical_text(official)
                    risk = work.daily.get(command.risk_id)
                    if risk is None or risk["kind"] != "RISK" or risk["symbol"] != command.symbol:
                        raise ValueError("risk obligation was not found")
                    if risk["revision"] != command.expected_revision:
                        raise RevisionConflictError(risk["revision"])
                    plan = load_daily_draft_json(details.payload_json).to_executable()
                    branch = next(
                        b for b in plan.risk_branches if b.kind == risk["payload"]["kind"]
                    )
                    if (
                        branch.target_core_qty,
                        branch.target_tactical_qty,
                        branch.involves_core,
                        branch.scope_evidence,
                    ) != (
                        command.target_core_qty,
                        command.target_tactical_qty,
                        command.involves_core,
                        command.scope_evidence,
                    ):
                        raise ValueError("new risk scope/targets must match the reviewed policy")
                    identity = daily_hash(
                        "daily-risk-reassessment-v1",
                        {"risk": risk["id"], "revision": risk["revision"]},
                    )
                    row = work.daily.save(
                        identity,
                        kind="REASSESSMENT",
                        symbol=command.symbol,
                        lineage=details.plan_id,
                        expected_revision=0,
                        payload={
                            "prior_risk": risk,
                            "new_plan_version_id": details.id,
                            "content_hash": details.content_hash,
                            "removal_evidence": official,
                        },
                    )
                    work.daily.save(
                        risk["id"],
                        kind="RISK",
                        symbol=command.symbol,
                        lineage=risk["lineage"],
                        expected_revision=risk["revision"],
                        payload={
                            "kind": branch.kind,
                            "status": "CLEAR",
                            "priority": branch.priority,
                            "target_core_qty": branch.target_core_qty,
                            "target_tactical_qty": branch.target_tactical_qty,
                            "involves_core": branch.involves_core,
                            "scope_evidence": branch.scope_evidence,
                            "evidence_ids": [],
                            "earliest_execution_date": None,
                            "blockers": [],
                            "reassessment_id": identity,
                            "cause_cutover_date": str(now.date()),
                            "cause_cutover_at": now.isoformat(),
                            "consumed_evidence_ids": sorted(
                                set(risk["payload"].get("consumed_evidence_ids", ()))
                                | set(risk["payload"].get("evidence_ids", ()))
                            ),
                        },
                    )
                else:
                    raise ValueError("unsupported daily operation")
        except ValueError as error:
            raise PlanSaveBlockedError("Daily evidence or quantity is invalid") from error
        result = DailyMutationReceipt(id=row["id"], revision=row["revision"], recorded_at=now)
        complete_replay(work, context=context, request_hash=request_hash, response=result)
        work.commit()
        return result


def read_daily(lifecycle, *, symbol, trade_date):
    with lifecycle._unit_of_work() as work:
        accounting = DailyAccounting(work.daily)
        active = work.plans.get_active(symbol)
        active_plan = None
        if active is not None:
            details = work.plans.get_version_details(active.plan_version_id)
            if details is not None:
                active_plan = load_plan_json(details.payload_json)
        alert_only = (isinstance(active_plan, UnifiedTradePlan)
            and bool(active_plan.alert_rules) and not active_plan.ordinary_rules
            and not active_plan.risk_branches)
        if accounting.legacy_reason(symbol) and (trade_date is not None or not alert_only):
            reason = "DAILY_SIMULATION_LEGACY_DATA_UNSUPPORTED"
            if trade_date is not None:
                return DailyInventoryResource(
                    symbol=symbol,
                    evaluated_at=lifecycle._clock(),
                    status="UNSUPPORTED",
                    reason=reason,
                    snapshot=None,
                )
            return DailyStateView(
                symbol=symbol,
                evaluated_at=None,
                status="UNSUPPORTED",
                reason=reason,
                snapshot=None,
                risks=tuple(
                    DailyObsoleteRiskApiView.model_validate_json(json.dumps(v))
                    for v in accounting.obsolete_risks(symbol)
                ),
            )
        if trade_date is not None:
            view = DailyInventoryApiView.model_validate_json(
                json.dumps(DailyAccounting(work.daily).snapshot(symbol, trade_date))
            )
            return DailyInventoryResource(
                symbol=symbol, evaluated_at=lifecycle._clock(), status="CURRENT", snapshot=view
            )
        if active is not None:
            if not isinstance(active_plan, UnifiedTradePlan):
                return DailyStateView(
                    symbol=symbol,
                    evaluated_at=None,
                    status="UNSUPPORTED",
                    reason="PLAN_REVIEW_REQUIRED",
                    snapshot=None,
                )
        head = work.daily.get("evaluation-head-" + symbol)
        current = (
            head is not None
            and active is not None
            and head["payload"].get("plan_version_id") == active.plan_version_id
        )
        return DailyStateView(
            symbol=symbol,
            evaluated_at=None if head is None else datetime.fromisoformat(head["updated_at"]),
            status="CURRENT" if current else "AWAITING_EVALUATION" if active else "INACTIVE",
            snapshot=None
            if head is None
            else DailyEvaluationApiView.model_validate_json(
                __import__("json").dumps(head["payload"])
            ),
        )


def read_daily_supplements(lifecycle, *, candidate_json):
    from trade_plan_monitor.ai.daily_review import DailySupplement, semantic_values

    draft = load_daily_draft_json(candidate_json)
    digest = daily_draft_content_sha256(draft)
    values = semantic_values(draft)
    identity = daily_hash(
        "daily-human-supplements-v1", {"symbol": draft.symbol, "content_hash": digest}
    )
    with lifecycle._unit_of_work() as work:
        row = work.daily.get(identity)
        if row is None:
            return {"content_hash": digest, "revision": 0, "supplements": []}
        supplements = tuple(
            DailySupplement.model_validate(s) for s in row["payload"]["supplements"]
        )
        if any(
            s.candidate_content_hash != digest
            or s.path not in values
            or type(s.value) is not type(values[s.path])
            or s.value != values[s.path]
            for s in supplements
        ):
            raise ValueError("stored supplement differs from its exact candidate")
        return {
            "content_hash": digest,
            "revision": row["revision"],
            "supplements": [s.model_dump(mode="json") for s in supplements],
        }


def _conflict(reason):
    from trade_plan_monitor.web.errors import ApiError
    from trade_plan_monitor.web.schemas import ApiErrorCode, ErrorDetail

    raise ApiError(
        ApiErrorCode.CONFLICT,
        details=(
            ErrorDetail(
                location=("body", "causeId"),
                code=reason,
                message="Simulation authority is unavailable",
            ),
        ),
    )


def _simulate(work, command, now):
    """Recheck current authority and commit its complete effect in this same UOW."""
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
        _conflict("DAILY_SIMULATION_LEGACY_DATA_UNSUPPORTED")
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
        _conflict("DAILY_SIMULATION_CURRENT_REVIEW_REQUIRED")
    plan = load_plan_json(details.payload_json)
    if not isinstance(plan, UnifiedTradePlan):
        _conflict("PLAN_REVIEW_REQUIRED")
    state = head["payload"]
    if (
        state["plan_version_id"] != details.id
        or state["activation_revision"] != active.revision
        or state["review_id"] != review["payload"]["review_id"]
    ):
        _conflict("DAILY_SIMULATION_CURRENT_EVALUATION_REQUIRED")
    inventory = accounting.snapshot(symbol, now.date())
    if inventory["revision"] != command.expected_inventory_revision:
        raise RevisionConflictError(inventory["revision"])
    if not inventory["known"]:
        _conflict("DAILY_SIMULATION_POSITION_REQUIRED")
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
        _conflict("DAILY_SIMULATION_CURRENT_FACTS_REQUIRED")
    try:
        quote = DailyExecutionQuote.model_validate(
            {**(state.get("quote") or {}), "evaluated_at": now}
        )
    except ValueError:
        _conflict("DAILY_SIMULATION_CURRENT_QUOTE_REQUIRED")
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
    if cause["kind"] == "SIGNAL":
        signal = cause["payload"]
        if state["data_blockers"]:
            _conflict("DAILY_SIMULATION_CURRENT_EVALUATION_REQUIRED")
        if signal["plan_version_id"] != details.id or signal["state"] == "SIMULATED":
            _conflict("DAILY_SIMULATION_SIGNAL_CONSUMED_OR_REPLACED")
        checked = (
            check_execution if isinstance(plan, UnifiedTradePlan) else check_daily_execution
        )(
            plan,
            signal,
            inventory=inventory,
            quote_fen=quote.price_fen,
            evaluated_at=now,
            tradable=tradable,
            risk_blocked=any(r["status"] in {"PENDING", "OBSERVATION", "CONFIRMED"} for r in risks),
            risk_known=state.get("risk_input_known",
                state.get("daily_evidence") is not None or not plan.risk_branches),
        )
        if checked["executable_qty"] == 0 or any(
            "ORDINARY_CONFLICT_BLOCK_BOTH" in s["blockers"] for s in state["signals"]
        ):
            _conflict("DAILY_SIMULATION_SIGNAL_NOT_EXECUTABLE")
        quantity, side = checked["executable_qty"], checked["side"]
        quantities = {"TACTICAL": quantity}
        signal_id = cause["id"]
    else:
        action = risk_execution(
            risks, plan=plan, inventory=inventory, evaluated_at=now, tradable=tradable
        )
        if action.get("cause_id") != cause["id"] or action["status"] != "RISK_EXIT":
            _conflict("DAILY_SIMULATION_RISK_NOT_EXECUTABLE")
        quantities = {"CORE": action["core_qty"], "TACTICAL": action["tactical_qty"]}
        if any(q is None for q in quantities.values()) or not sum(quantities.values()):
            _conflict("DAILY_SIMULATION_RISK_NOT_EXECUTABLE")
        quantity, side = sum(quantities.values()), "SELL"
    if quantity != command.quantity:
        raise ValueError("simulation must consume the complete offered quantity")
    identity = str(uuid4())
    position = accounting.simulate(
        symbol=symbol,
        identity=identity,
        side=side,
        quantities=quantities,
        expected_revision=command.expected_inventory_revision,
        now=now,
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
            and inventory["tactical_qty"] <= risk["target_tactical_qty"]
            and (not risk["involves_core"] or inventory["core_qty"] <= risk["target_core_qty"])
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
    result = DailySimulationReceipt(
        simulation_id=identity,
        side=side,
        quantity=quantity,
        price_fen=quote.price_fen,
        simulated_at=now,
        inventory_revision=position["revision"],
        inventory=DailyInventoryApiView.model_validate(inventory),
        signal_id=signal_id,
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
        },
    )
    return result
