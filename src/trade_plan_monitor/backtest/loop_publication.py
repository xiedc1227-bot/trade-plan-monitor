"""Typed loop staging and snapshot verification behind existing atomic publication."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from hashlib import sha256
from zoneinfo import ZoneInfo

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.control import CancellationToken
from trade_plan_monitor.backtest.jobs.models import LoopInputReference
from trade_plan_monitor.backtest.loop_account import LoopAccountState
from trade_plan_monitor.backtest.loop_input_store import StoredLoopInput
from trade_plan_monitor.backtest.loop_report import (
    LOOP_REPORT_VERSION,
    SCHEDULED_LOOP_REPORT_VERSION,
    LoopAccountDiscrepancy,
    LoopAuditEvent,
    LoopPlanTransition,
    MonitorLoopReport,
    ScheduledMonitorLoopReport,
    decode_loop_event,
    decode_loop_report,
    project_loop_valuation,
    verify_loop_events,
)
from trade_plan_monitor.backtest.results import (
    BacktestDetailKind,
    BacktestDetailRecord,
    BacktestFillRecord,
    BacktestResultStore,
    BacktestRunStatus,
    BacktestRunSummary,
    _canonical_json,
    _load_detail_row,
    _load_fill_row,
)
from trade_plan_monitor.domain.plan_hash import plan_sha256


def loop_equity_points(report, events) -> tuple[BacktestDetailRecord, ...]:
    """Project opening and last daily valuations only after the full audit verifies."""
    if not isinstance(report, ScheduledMonitorLoopReport):
        raise ValueError("continuous equity requires a scheduled report")
    daily = {}

    def checked():
        for event in events:
            if event.payload.kind == "VALUATION":
                point = event.payload.valuation
                daily[point.at.astimezone(ZoneInfo("Asia/Shanghai")).date()] = (
                    event.event_id, point,
                )
                if len(daily) >= 2000:
                    raise ValueError("daily equity must not exceed 2,000 points")
            yield event

    verify_loop_events(report, checked())
    opening_id = sha256(f"monitor-loop-opening-equity-v1\0{report.run_id}".encode()).hexdigest()
    values = [(opening_id, report.opening_valuation), *daily.values()]
    records = []
    for snapshot_id, point in sorted(values, key=lambda value: (value[1].at, value[0])):
        payload = {
            "schema_version": "unified-research-equity-v1",
            "snapshot_id": snapshot_id,
            "run_id": report.run_id,
            "marked_at": point.at.isoformat(),
            "position_quantity": point.position_quantity,
            "valuation_valid": point.valuation_valid,
            "blockers": list(point.blockers),
        }
        for field, value in (
            ("mark_price_fen", point.price_fen), ("cash_fen", point.cash_fen),
            ("market_value_fen", point.market_value_fen), ("equity_fen", point.equity_fen),
        ):
            payload[field] = None if value is None else str(value)
        records.append(BacktestDetailRecord(
            detail_id=snapshot_id, run_id=report.run_id, kind=BacktestDetailKind.DAILY_EQUITY,
            event_at=point.at, payload=payload,
        ))
    return tuple(records)


def report_summary(stored: StoredLoopInput, report: MonitorLoopReport) -> BacktestRunSummary:
    """Keep only bounded lookup/coverage fields in the existing summary envelope."""
    run, plan = stored.run_input, stored.run_input.schedule.entries[0].version.snapshot
    return BacktestRunSummary(
        run_id=run.run_id,
        plan_sha256=plan_sha256(plan),
        dataset_hash=run.dataset_hash,
        status=BacktestRunStatus.COMPLETED,
        completed_at=run.boundary.evidence_cutoff,
        event_start=run.boundary.started_at.date(),
        event_end=run.boundary.resolved_end_date,
        symbols=(plan.symbol,),
        coverage={
            "fillCount": report.cycle.fills,
            "decisionCount": report.event_count,
            "signalCount": 0,
            "outcomeCount": 0,
            "dailyEquityCount": 0,
        },
        assumptions={
            "reportSchemaVersion": report.schema_version,
            "reportHash": report.report_hash,
            "inputReference": json.loads(canonical_json(stored.reference)),
        },
        formula_versions={
            "indicator": plan.monitoring.indicator_formula_version
            if plan.monitoring is not None
            else "daily-ta-v2",
            "execution": run.costs.formula_version,
            "runner": run.run_formula_version,
            "report": report.schema_version,
        },
        final_metrics=json.loads(canonical_json(report.metrics)),
        blockers=report.metrics.blockers,
    )


def validate_reference_summary(summary: BacktestRunSummary, reference: LoopInputReference) -> None:
    if (
        summary.run_id != reference.run_id
        or summary.dataset_hash != reference.dataset_hash
        or summary.assumptions.get("reportSchemaVersion") not in {
            LOOP_REPORT_VERSION, SCHEDULED_LOOP_REPORT_VERSION,
        }
        or summary.assumptions.get("inputReference") != json.loads(canonical_json(reference))
    ):
        raise ValueError("summary identity must match frozen loop input reference")


def validate_report_input(stored: StoredLoopInput, report: MonitorLoopReport) -> None:
    run = stored.run_input
    selected = run.schedule.select(run.boundary.started_at)
    from trade_plan_monitor.backtest.loop_input import ScheduledLoopInput

    scheduled = isinstance(run, ScheduledLoopInput)
    if (isinstance(report, ScheduledMonitorLoopReport) != scheduled or (
        report.run_id, report.input_hash, report.dataset_hash, report.symbol, report.boundary,
    ) != (run.run_id, run.input_hash, run.dataset_hash, run.schedule.symbol, run.boundary)):
        raise ValueError("report does not match frozen loop input")
    if scheduled:
        if report.schedule != run.schedule:
            raise ValueError("report schedule does not match frozen loop input")
    elif (report.plan_hash, report.authority_id) != (
        selected.version.plan_hash, selected.authority_id,
    ):
        raise ValueError("report does not match frozen loop input")
    opening = run.initial_account.opening_mark
    expected = project_loop_valuation(
        LoopAccountState.from_opening(run.initial_account),
        at=run.boundary.started_at,
        price_fen=None if opening is None else opening.price_fen,
        price_at=None if opening is None else opening.price_at,
        available_at=None if opening is None else opening.available_at,
    )
    if report.opening_valuation != expected:
        raise ValueError("report opening valuation does not match frozen input")


def audit_record(event: LoopAuditEvent) -> BacktestDetailRecord:
    return BacktestDetailRecord(
        detail_id=f"loop-{event.sequence:06d}-{event.run_id[:16]}",
        run_id=event.run_id,
        kind=BacktestDetailKind.DECISION,
        event_at=event.at,
        payload=json.loads(canonical_json(event)),
    )


def fill_record(event: LoopAuditEvent) -> BacktestFillRecord | None:
    if event.payload.kind != "EXECUTED" or event.payload.attempt.receipt is None:
        return None
    receipt = event.payload.attempt.receipt
    return BacktestFillRecord(
        fill_id=sha256(("monitor-loop-stored-fill-v1\0" + event.run_id + "\0"
                        + receipt.authority_receipt.simulation_id).encode()).hexdigest(),
        run_id=event.run_id,
        filled_at=event.at,
        payload={
            "schema_version": "monitor-loop-fill-v1",
            "event_id": event.event_id,
            "receipt": json.loads(canonical_json(receipt)),
        },
    )


def stage_loop_report(
    store: BacktestResultStore,
    *,
    reference: LoopInputReference,
    report: MonitorLoopReport,
    events: Iterable[LoopAuditEvent],
    cancellation_token: CancellationToken | None = None,
) -> BacktestRunSummary:
    """A failed source can leave staged rows, never a materialized partial result."""
    token = cancellation_token or CancellationToken()
    token.raise_if_cancelled("RUN_REPORT_HANDOFF")
    report = decode_loop_report(report.model_dump_json())
    stored = store.get_loop_input(reference)
    validate_report_input(stored, report)
    summary = report_summary(stored, report)
    store.record_loop_run(
        summary, reference=reference, report=report, retention_at=datetime.now(UTC)
    )
    details, fills = [], []

    def flush():
        if details:
            store.record_details(report.run_id, details)
            details.clear()
        if fills:
            store.record_fills(report.run_id, fills)
            fills.clear()

    def checked():
        for value in events:
            token.raise_if_cancelled("RUN_REPORT_HANDOFF")
            event = decode_loop_event(value.model_dump_json())
            details.append(audit_record(event))
            fill = fill_record(event)
            if fill is not None:
                fills.append(fill)
            if len(details) == 100:
                flush()
            yield event

    verify_loop_events(report, checked())
    token.raise_if_cancelled("RUN_REPORT_HANDOFF")
    flush()
    # Verify the actual stored snapshot, including an incomplete/conflicting prior retry.
    store.verify_job_publication(report.run_id, expected_report_hash=report.report_hash)
    return summary


def verify_loop_publication(store, connection, summary, reference, *, materialized):
    """Bind report, copied facts and every typed row in the caller's read snapshot."""
    stored = store._get_loop_input_participant(connection, reference)
    report = store.loop_input_store.load_report(summary.assumptions["reportHash"])
    validate_report_input(stored, report)
    if summary.model_copy(update={"pinned": False}) != report_summary(stored, report):
        raise ValueError("stored loop summary does not match immutable report")
    if materialized:
        # Existing verified publication metadata survives optional-detail expiry.
        return report
    expected_fills = {}
    account = LoopAccountState.from_opening(stored.run_input.initial_account)
    day_index = {day.trade_date: index for index, day in enumerate(stored.dataset.days)}
    current_date, minutes = None, {}
    mismatches, blocked_rules = (), ()

    def account_context(at):
        selected = stored.run_input.schedule.select(at)
        context = None if selected is None else selected.version.account_context
        differences = []
        if context is not None:
            for bucket, stated in (("CORE", context.core_qty), ("TACTICAL", context.tactical_qty)):
                actual = (sum(lot.quantity for lot in account.lots if lot.bucket == bucket)
                          if account.inventory_known else None)
                if stated is not None and stated != actual:
                    differences.append(LoopAccountDiscrepancy(
                        bucket=bucket, stated_qty=stated, actual_qty=actual,
                    ))
        return tuple(differences), context.dependent_rule_ids if differences else ()

    if isinstance(report, ScheduledMonitorLoopReport):
        mismatches, blocked_rules = account_context(report.boundary.started_at)

    def checked():
        nonlocal account, current_date, minutes, mismatches, blocked_rules
        cursor = connection.execute(
            "SELECT detail_id, run_id, kind, event_at, content_domain, content_hash, payload_json "
            "FROM backtest_detail WHERE run_id = ? ORDER BY detail_id",
            (reference.run_id,),
        )
        while rows := cursor.fetchmany(1000):
            for row in rows:
                detail = _load_detail_row(tuple(row), expected_run_id=reference.run_id)
                event = decode_loop_event(canonical_json(detail.payload))
                if detail != audit_record(event):
                    raise ValueError("loop audit row identity mismatch")
                payload = event.payload
                if isinstance(payload, LoopPlanTransition):
                    if payload.kind == "REPLACED":
                        mismatches, blocked_rules = account_context(payload.at)
                    if (payload.context_mismatches, payload.blocked_rule_ids) != (
                        mismatches, blocked_rules,
                    ):
                        raise ValueError("loop transition context does not match account")
                if payload.kind == "EXECUTED":
                    minute = payload.attempt.minute
                    if current_date != minute.bar_end.date():
                        current_date = minute.bar_end.date()
                        index = day_index.get(current_date)
                        if index is None:
                            raise ValueError("loop execution day is outside frozen input")
                        day = store.loop_input_store._read_day(stored, index)
                        minutes = {(bar.bar_end, bar.received_at): bar for bar in day.minutes}
                    if minutes.get((minute.bar_end, minute.received_at)) != minute:
                        raise ValueError("loop execution minute does not match frozen input")
                    receipt = payload.attempt.receipt
                    if receipt is not None:
                        account = _verify_settlement(account, receipt, stored.run_input.costs)
                        fill = fill_record(event)
                        simulation_id = receipt.authority_receipt.simulation_id
                        if simulation_id in expected_fills:
                            raise ValueError("loop fill identity is repeated")
                        legacy = fill.model_copy(update={"fill_id": simulation_id})
                        expected_fills[simulation_id] = {
                            candidate.fill_id: sha256(
                                _canonical_json(candidate, version="v2").encode()
                            ).hexdigest() for candidate in (fill, legacy)
                        }
                elif payload.kind == "STATE" and payload.account != account:
                    raise ValueError("loop state does not match preceding settlement")
                elif payload.kind == "VALUATION":
                    point = payload.valuation
                    if point != project_loop_valuation(
                        account,
                        at=point.at,
                        price_fen=point.price_fen,
                        price_at=point.price_at,
                        available_at=point.available_at,
                    ):
                        raise ValueError("loop valuation does not match preceding settlement")
                yield event

    verify_loop_events(report, checked())
    if account != report.final_account:
        raise ValueError("loop final account does not match committed trail")
    cursor = connection.execute(
        "SELECT fill_id, run_id, filled_at, content_domain, content_hash, payload_json "
        "FROM backtest_fill WHERE run_id = ? ORDER BY fill_id",
        (reference.run_id,),
    )
    while rows := cursor.fetchmany(1000):
        for row in rows:
            fill = _load_fill_row(tuple(row), expected_run_id=reference.run_id)
            simulation_id = fill.payload.get("receipt", {}).get("authority_receipt", {}).get(
                "simulation_id"
            )
            expected = expected_fills.pop(simulation_id, {})
            if (
                expected.get(fill.fill_id)
                != sha256(_canonical_json(fill, version="v2").encode()).hexdigest()
            ):
                raise ValueError("loop fill ledger does not match audit trail")
    if expected_fills:
        raise ValueError("loop fill ledger is incomplete")
    return report


def _verify_settlement(before, receipt, costs):
    """Verify money continuity without creating an alternate execution authority."""
    after, settlement = receipt.account, receipt.settlement
    buy = settlement.side == "BUY"
    cash_delta = (
        -settlement.notional_fen if buy else settlement.notional_fen
    ) - settlement.total_fees_fen
    old_quantity = sum(lot.quantity for lot in before.lots)
    new_quantity = sum(lot.quantity for lot in after.lots)
    released = receipt.released_cost_fen
    expected_pnl = before.realized_pnl_fen
    if not buy:
        expected_pnl = (
            None
            if expected_pnl is None or released is None
            else expected_pnl + cash_delta - released
        )
    if (
        receipt.costs != costs
        or before.cash.kind != "KNOWN"
        or after.cash.kind != "KNOWN"
        or after.revision != before.revision + 1
        or after.inventory_known != before.inventory_known
        or after.cash.balance_fen != before.cash.balance_fen + cash_delta
        or after.paid_fees_fen != before.paid_fees_fen + settlement.total_fees_fen
        or new_quantity != old_quantity + (settlement.quantity if buy else -settlement.quantity)
        or after.realized_pnl_fen != expected_pnl
    ):
        raise ValueError("loop settlement does not continue preceding account")
    if before.accounting_cost_fen is not None and after.accounting_cost_fen is not None:
        delta = settlement.notional_fen + settlement.total_fees_fen if buy else -released
        if after.accounting_cost_fen != before.accounting_cost_fen + delta:
            raise ValueError("loop settlement accounting cost mismatch")
    return after
