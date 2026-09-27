"""A real scheduled recovery cannot transfer old activation facts to a new owner.

The A07 clock/composition fixture is intentionally a same-batch dependency. Only
the offline SDK boundary is paused; recovery, evaluation and deadlines are real.
"""

import asyncio
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from threading import Event

from test_live_pipeline_acceptance import ControlledClock, OfflineSDK, _activate_plans
from test_s3_startup_minute_coverage import (
    BUSINESS_TABLES,
    CUTOFF,
    FIFTH_DUE,
    FIRST_END,
    NOW,
    SYMBOL,
    _CoverageSDK,
    _prefix,
    _Run,
)

from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_validation import ALL_MARKET_EVIDENCE, validate_trade_plan
from trade_plan_monitor.runtime.health import RuntimeServiceStatus
from trade_plan_monitor.runtime.scheduler import DeadlineKind
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork


class _IdentitySDK(_CoverageSDK):
    def __init__(self, clock, sibling):
        super().__init__(clock, "partial")
        self.stock_symbols = (SYMBOL, sibling)
        self.entered = Event()
        self.release = Event()
        self.repair_available = False
        self.stock_trace = []

    def _stock_minutes(self, name, kwargs):
        frame = OfflineSDK._stock_minutes(self, name, kwargs)
        symbol = str(kwargs["ts_code"])
        self.stock_trace.append((name, symbol, self.phase, self.clock.now()))
        if name == "rt_min" or symbol != SYMBOL:
            return frame
        if self.phase == "scheduled" and not self.entered.is_set():
            # Freeze the physical response before another connection reactivates
            # the identical plan. It includes the missing first minute.
            self.entered.set()
            assert self.release.wait(8), "test did not release the physical SDK"
            return frame
        if self.repair_available:
            return frame
        missing = (FIRST_END - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
        return frame.loc[frame["time"] != missing].reset_index(drop=True)


def _snapshot(database):
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        state = {
            name: tuple(dict(row) for row in db.execute(f"SELECT * FROM {name} ORDER BY rowid"))
            for name in (*BUSINESS_TABLES, "alert_delivery_eligibility",
                         "explicit_evaluation_ledger", "explicit_rule_occurrence_state")
        }
        for name in ("minute_bar", "latest_quote"):
            state[name] = tuple(dict(row) for row in db.execute(
                f"SELECT * FROM {name} WHERE symbol=? ORDER BY rowid", (SYMBOL,),
            ))
        state["risk_audits"] = tuple(dict(row) for row in db.execute(
            "SELECT * FROM audit_log WHERE action='RISK_STATE_UPDATED' ORDER BY rowid",
        ))
    return state


def _assert_no_first_decision(state):
    for name in ("evaluation_ledger", "evaluation_result", "symbol_decision_head", "risk_state",
                 "explicit_evaluation_ledger", "explicit_rule_occurrence_state"):
        assert not [row for row in state[name] if row["symbol"] == SYMBOL], (name, state[name])
    assert state["alert_event"] == state["alert_delivery_eligibility"] == ()
    assert state["delivery_attempt"] == state["risk_audits"] == ()


def test_scheduled_stock_recovery_reactivation_rejects_old_facts_and_resumes(
    tmp_path, monkeypatch,
):
    async def scenario():
        run = _Run(tmp_path, monkeypatch, "partial", NOW)
        sibling = run.plan.model_copy(update={
            "plan_id": "healthy-recovery-sibling", "symbol": "003044.SZ",
        })
        _activate_plans(
            run.database, ControlledClock(NOW.replace(hour=9, minute=0, second=0)), (sibling,),
        )
        run.sdk = _IdentitySDK(run.clock, sibling.symbol)
        engine = create_sqlite_engine(run.database)
        sessions = create_session_factory(engine)
        drive = None
        try:
            await run.start()
            generation = run.composition.health().runtime_generation
            assert len(run.sdk.entries("rt_min_daily")) == 1
            runtime = run.composition._runtime
            real_run_deadline = runtime._run_deadline
            pipeline = real_run_deadline.__self__._pipeline
            active_deadlines = {}

            async def observe_deadline(deadline):
                # Observe the real lifecycle's argument and owned task; forward
                # unchanged, without choosing or invoking a deadline ourselves.
                owner = asyncio.current_task()
                active_deadlines[owner] = deadline
                try:
                    return await real_run_deadline(deadline)
                finally:
                    del active_deadlines[owner]

            monkeypatch.setattr(runtime, "_run_deadline", observe_deadline)

            def assert_same_owner():
                health = run.composition.health()
                assert health.runtime_generation == generation, (health, run.sdk.stock_trace)
                assert health.status is RuntimeServiceStatus.RUNNING, health
                assert health.degraded_reason != "RUNTIME_RUNNER_FAILED", health

            run.sdk.phase = "scheduled"
            drive = asyncio.create_task(run.clock.drive(
                NOW.replace(minute=2, second=12),
                stop_when=run.sdk.entered.is_set, failed=run.runner_failed,
                after_wake=assert_same_owner,
            ))
            while not run.sdk.entered.is_set():
                assert not drive.done(), (
                    "real scheduler never entered the missing-prefix maintenance SDK",
                    run.sdk.stock_trace,
                )
                await asyncio.sleep(0.005)
            assert_same_owner()
            (owner, held_deadline), = active_deadlines.items()
            assert held_deadline.kind is DeadlineKind.STOCK_RECOVERY
            assert owner in runtime._work_tasks and not owner.done()
            held_scope, = (
                item for item in pipeline._stock_recovery_schedule.snapshot()
                if item.requirement.scope_key == f"stock-prefix:{SYMBOL}"
            )
            assert held_scope.in_progress
            before = _snapshot(run.database)
            assert before["minute_bar"] and before["latest_quote"]
            assert FIRST_END.isoformat() not in {row["bar_end"] for row in before["minute_bar"]}
            _assert_no_first_decision(before)
            reactivated_at = run.clock.now()
            assert reactivated_at > NOW
            with SqlAlchemyUnitOfWork(sessions, clock=run.clock.now) as work:
                original = work.plans.get_active(SYMBOL)
                work.plans.deactivate(SYMBOL, expected_revision=original.revision)
                replacement = work.plans.activate(
                    run.plan, expected_revision=original.revision + 1,
                    validation=validate_trade_plan(
                        run.plan, available_market_evidence=ALL_MARKET_EVIDENCE,
                    ),
                )
                work.commit()
            assert replacement.plan_version_id == original.plan_version_id
            assert replacement.revision == original.revision + 2
            assert replacement.activated_at == reactivated_at > NOW
            run.sdk.release.set()
            await drive
            assert_same_owner()
            # Exact rows include OHLC, received_at and latest_quote. No stale
            # response facts or business records may leak through the reactivation.
            assert _snapshot(run.database) == before

            await run.clock.drive(
                FIFTH_DUE, failed=run.runner_failed, after_wake=assert_same_owner,
            )
            assert_same_owner()
            interim = _snapshot(run.database)
            _assert_no_first_decision(interim)
            sibling_head, = (row for row in interim["symbol_decision_head"]
                             if row["symbol"] == sibling.symbol)
            assert sibling_head["activation_revision"] == 1
            sibling_result, = (row for row in interim["evaluation_result"]
                               if row["symbol"] == sibling.symbol)
            assert sibling_result["plan_hash"] == plan_sha256(sibling)
            assert sibling_result["result_hash"] == sibling_head["result_hash"]
            assert sibling_result["target_value"] == FIFTH_DUE.replace(second=0).isoformat()
            assert sibling_result["evaluated_at"] == FIFTH_DUE.isoformat()
            assert FIRST_END.isoformat() not in {row["bar_end"] for row in interim["minute_bar"]}

            run.sdk.repair_available = True
            run.sdk.phase = "fresh-recovery"
            next_market = FIFTH_DUE + timedelta(minutes=5)
            await run.clock.drive(
                next_market - timedelta(microseconds=1), failed=run.runner_failed,
                stop_when=lambda: FIRST_END.isoformat() in {
                    row["bar_end"] for row in _snapshot(run.database)["minute_bar"]
                },
                after_wake=assert_same_owner,
            )
            assert_same_owner()
            repaired = _snapshot(run.database)
            assert set(end.isoformat() for end in _prefix(CUTOFF)).issubset(
                row["bar_end"] for row in repaired["minute_bar"]
            )
            preserved = {row["bar_end"]: row for row in repaired["minute_bar"]}
            assert all(preserved[row["bar_end"]] == row for row in before["minute_bar"])
            assert any(
                name == "rt_min_daily" and symbol == SYMBOL and phase == "fresh-recovery"
                and entered_at >= FIFTH_DUE > reactivated_at
                for name, symbol, phase, entered_at in run.sdk.stock_trace
            ), run.sdk.stock_trace
            _assert_no_first_decision(repaired)
            await run.clock.drive(
                next_market, failed=run.runner_failed, after_wake=assert_same_owner,
            )
            assert_same_owner()
            final = _snapshot(run.database)
            result, = (row for row in final["evaluation_result"] if row["symbol"] == SYMBOL)
            head, = (row for row in final["symbol_decision_head"] if row["symbol"] == SYMBOL)
            ledger, = (row for row in final["evaluation_ledger"] if row["symbol"] == SYMBOL)
            assert head["activation_revision"] == replacement.revision
            assert result["plan_hash"] == head["plan_hash"] == plan_sha256(run.plan)
            assert result["result_hash"] == head["result_hash"] == ledger["result_hash"]
            assert result["evaluation_kind"] == "INTRADAY"
            assert result["formula_version"] == run.plan.monitoring.indicator_formula_version
            assert result["target_value"] == next_market.replace(second=0).isoformat()
            assert result["evaluated_at"] == next_market.isoformat()
            assert result["source_at"] == result["target_value"]
            snapshot = json.loads(result["result_json"])["snapshot"]
            assert snapshot["market_data_at"] == result["target_value"]
            assert snapshot["evaluated_at"] == result["evaluated_at"]
            assert snapshot["price_fen"] == 6405
            assert set(end.isoformat() for end in _prefix(next_market.replace(second=0))).issubset(
                row["bar_end"] for row in final["minute_bar"]
            )
            assert timedelta(0) <= (
                datetime.fromisoformat(result["evaluated_at"])
                - datetime.fromisoformat(result["target_value"])
            ) <= timedelta(seconds=90)
            assert sibling_result in final["evaluation_result"]
            assert final["alert_event"] == final["alert_delivery_eligibility"] == ()
            assert final["delivery_attempt"] == ()
            assert run.sent == []
        finally:
            run.sdk.release.set()
            if drive is not None and not drive.done():
                drive.cancel()
            await run.stop()
            if drive is not None:
                await asyncio.gather(drive, return_exceptions=True)
            engine.dispose()

    async def bounded():
        async with asyncio.timeout(45):
            await scenario()

    asyncio.run(bounded())
