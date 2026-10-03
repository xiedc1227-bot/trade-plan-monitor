"""Daily risk obligations latch independently from ordinary windows and indicators."""

from datetime import date, datetime, time
from decimal import Decimal

from trade_plan_monitor.decision.daily_conditions import compare
from trade_plan_monitor.decision.daily_lifecycle import next_session


def _condition_evidence_ids(evidence):
    """Retain every leaf consumed by a nested severe-condition confirmation."""
    return list(dict.fromkeys((
        *evidence.bar_ids,
        *evidence.fact_ids,
        *(identity for child in evidence.children for identity in _condition_evidence_ids(child)),
    )))


def advance_daily_risks(
    plan,
    *,
    previous,
    close_date,
    close_fen,
    basis_id,
    session_dates,
    suspended_dates,
    facts,
    effective_start_date=None,
    allow_new_causes=True,
    severe_evidence=None,
):
    results = []
    by_kind = {r["kind"]: r for r in previous}
    for branch in sorted(plan.risk_branches, key=lambda b: b.priority):
        old = by_kind.get(branch.kind)
        cutover_at = (
            None
            if old is None or old.get("cause_cutover_at") is None
            else datetime.fromisoformat(old["cause_cutover_at"])
        )
        close_after_cutover = close_date is not None and (
            cutover_at is None
            or datetime.combine(close_date, time(15), cutover_at.tzinfo) > cutover_at
        )
        new_cause = (
            allow_new_causes
            and old is not None
            and old["status"] == "FULFILLED"
            and close_date is not None
            and close_after_cutover
        )
        state = (
            dict(old)
            if old is not None and old["status"] != "CLEAR" and not new_cause
            else {
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
            }
        )
        if old is not None:
            for field in (
                "reassessment_id",
                "cause_cutover_date",
                "consumed_evidence_ids",
                "fulfilled_at",
                "cause_cutover_at",
            ):
                if field in old:
                    state[field] = old[field]
        if not allow_new_causes and state["status"] not in {"PENDING", "CONFIRMED"}:
            results.append(state)
            continue
        if (
            state["status"] == "CLEAR"
            and effective_start_date is not None
            and close_date is not None
            and close_date < effective_start_date
        ):
            results.append(state)
            continue
        if close_date is not None and cutover_at is not None and not close_after_cutover:
            results.append(state)
            continue
        if state["status"] in {"CONFIRMED", "FULFILLED"}:
            if state["earliest_execution_date"] is None and state.get("confirmed_trade_date"):
                execution = next_session(
                    date.fromisoformat(state["confirmed_trade_date"]), session_dates
                )
                if execution is not None:
                    state["earliest_execution_date"] = str(execution)
                    state["blockers"] = []
            results.append(state)
            continue
        if branch.kind == "SEVERE_TECHNICAL" and close_date is not None:
            found = [
                next(
                    (
                        f
                        for f in facts
                        if f.get("kind") == kind
                        and f.get("verified") is True
                        and f.get("trade_date") == str(close_date)
                        and f.get("id") not in state.get("consumed_evidence_ids", ())
                    ),
                    None,
                )
                for kind in ("SEVERE_STRUCTURE", "SEVERE_DETERIORATION")
            ]
            quantitative = hasattr(branch, "condition")
            confirmed = (severe_evidence is not None and severe_evidence.outcome == "SATISFIED"
                if quantitative else all(found))
            if confirmed:
                execution = next_session(close_date, session_dates)
                state.update(
                    status="CONFIRMED",
                    confirmed_trade_date=str(close_date),
                    evidence_ids=(_condition_evidence_ids(severe_evidence)
                        if quantitative else [f["id"] for f in found]),
                    **({"technical_evidence": [severe_evidence.model_dump(mode="json")]}
                        if quantitative else {}),
                    earliest_execution_date=None if execution is None else str(execution),
                )
                if execution is None:
                    state["blockers"] = ["TRADING_CALENDAR_MISSING"]
        elif (
            branch.kind == "ORDINARY_TECHNICAL" and close_date is not None and close_fen is not None
        ):
            line = state.get("risk_line_fen", plan.levels.risk_line_fen)
            op = state.get("risk_comparison", plan.levels.risk_comparison)
            below = compare(Decimal(close_fen), op, Decimal(line))
            if state.get("basis_id", basis_id) != basis_id:
                state["blockers"] = ["PERSISTED_RISK_BASIS_EQUIVALENCE_REQUIRED"]
            elif state["status"] == "PENDING":
                expected = state.get("second_close_date")
                if expected is None:
                    day = next_session(
                        date.fromisoformat(state["breach_trade_date"]), session_dates
                    )
                    expected = None if day is None else str(day)
                    state["second_close_date"] = expected
                suspended_between = tuple(
                    d
                    for d in suspended_dates
                    if expected is not None and expected <= str(d) < str(close_date)
                )
                adjacent = expected == str(close_date)
                resumed = (
                    expected is not None
                    and expected < str(close_date)
                    and suspended_between
                    and all(
                        d in suspended_dates
                        for d in session_dates
                        if expected <= str(d) < str(close_date)
                    )
                )
                if adjacent or resumed:
                    if not below:
                        state["status"] = "OBSERVATION"
                    elif (
                        resumed
                        and state["suspension_confirmation_policy"] == "RESTART_ADJACENT_PAIR"
                    ):
                        second = next_session(close_date, session_dates)
                        state.update(
                            breach_trade_date=str(close_date),
                            second_close_date=None if second is None else str(second),
                        )
                    else:
                        execution = next_session(close_date, session_dates)
                        state.update(
                            status="CONFIRMED",
                            confirmed_trade_date=str(close_date),
                            earliest_execution_date=None if execution is None else str(execution),
                        )
                elif expected is not None and str(close_date) > expected:
                    state["blockers"] = ["NEXT_OFFICIAL_CLOSE_UNVERIFIED"]
            elif state["status"] in {"CLEAR", "OBSERVATION"} and below:
                second = next_session(close_date, session_dates)
                state.update(
                    status="PENDING",
                    breach_trade_date=str(close_date),
                    second_close_date=None if second is None else str(second),
                    risk_line_fen=line,
                    risk_comparison=op,
                    basis_id=basis_id,
                    suspension_confirmation_policy=branch.suspension_confirmation_policy,
                )
        results.append(state)
    return tuple(results)


def risk_execution(risks, *, plan, inventory, evaluated_at, tradable):
    """Combine targets by minimum retained amount; never weaken a latched obligation."""
    confirmed = [r for r in risks if r["status"] == "CONFIRMED"]
    eligible = [
        r
        for r in confirmed
        if r["earliest_execution_date"] is not None
        and r["earliest_execution_date"] <= str(evaluated_at.date())
    ]
    if not eligible:
        return {
            "status": "WAITING" if confirmed else "NONE",
            "core_qty": 0,
            "tactical_qty": 0,
            "unavailable_core_qty": 0,
            "unavailable_tactical_qty": 0,
            "blockers": [],
        }
    result = {
        "status": "RISK_EXIT",
        "branch": min(eligible, key=lambda r: r["priority"])["kind"],
        "blockers": [],
    }
    cause = min(eligible, key=lambda r: r["priority"])
    result["cause_id"] = cause.get("risk_id")
    result["cause_revision"] = cause.get("revision")
    for bucket in ("tactical", "core"):
        affected = [r for r in eligible if bucket != "core" or r["involves_core"]]
        actual = inventory.get(bucket + "_qty")
        target = min((r["target_" + bucket + "_qty"] for r in affected), default=actual)
        sellable = inventory.get("sellable_" + bucket)
        needed = None if actual is None else max(0, actual - target) if affected else 0
        executable = (
            None if needed is None or sellable is None
            else (min(needed, sellable) // 100) * 100 if tradable else 0
        )
        result[bucket + "_qty"] = executable
        result["unavailable_" + bucket + "_qty"] = (
            None if needed is None or executable is None else needed - executable
        )
        result["target_" + bucket + "_qty"] = target
    if not inventory["known"]:
        result["blockers"].append("POSITION_UNKNOWN_RISK_REMAINS_CONFIRMED")
    if not tradable:
        result["blockers"].append("WAIT_FOR_CERTIFIED_TRADABILITY")
    if any(inventory.get("sellable_" + b) is None for b in ("core", "tactical")):
        result["blockers"].append("SELLABLE_QUANTITY_UNKNOWN")
    return result
