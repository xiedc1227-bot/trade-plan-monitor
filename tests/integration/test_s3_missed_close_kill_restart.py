"""Actual composition discovers an unmarked missed close after a killed SDK worker."""

import asyncio
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, time, timedelta
from multiprocessing import get_context
from pathlib import Path
from threading import Event

import pytest
from test_live_pipeline_acceptance import (
    NOW,
    ControlledClock,
    OfflineSDK,
    VirtualPace,
    _activate_plans,
    _sample_plan,
    _write_configuration_and_evidence,
)

from trade_plan_monitor.decision.models import RiskStatus
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import TradingDayActivation
from trade_plan_monitor.market_data.models import TradingDay
from trade_plan_monitor.notifications.channels import ChannelDeliveryResult, DeliveryChannel
from trade_plan_monitor.runtime.health import RuntimeServiceStatus
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import RuntimeLiveness
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

SOURCE_CLOSE = NOW.replace(hour=15, minute=0, second=0)
CLOSE_DUE = SOURCE_CLOSE + timedelta(minutes=20)
AFTER_CLOSE = SOURCE_CLOSE + timedelta(hours=2, minutes=5)
SYMBOL = "003043.SZ"


class _SharedClock(ControlledClock):
    """Only the parent and its P1 child share this disposable clock value."""

    def __init__(self, shared, *, released_sleeps, release_through=None):
        self.shared = shared
        self.release_through = release_through
        super().__init__(self.current, released_sleeps=released_sleeps)

    async def sleep_until(self, deadline):
        if self.release_through is not None and deadline <= self.release_through:
            assert len(self.sleep_calls) < 8, "bounded pre-kill scheduler wake guard"
            self.sleep_calls.append(deadline)
            self.current = max(self.current, deadline)
            await asyncio.sleep(0)
            return
        await super().sleep_until(deadline)

    @property
    def current(self):
        return datetime.fromtimestamp(self.shared.value, tz=NOW.tzinfo)

    @current.setter
    def current(self, value):
        self.shared.value = value.timestamp()


def _composition_child(root, phase, shared_clock, sdk_entered, reports):
    """Patch external boundaries in every spawned interpreter before composition creation."""
    import httpx
    import requests

    import trade_plan_monitor.runtime.production as production
    import trade_plan_monitor.web.monitor_composition as monitor_composition

    def forbidden_network(*_args, **_kwargs):
        raise AssertionError("offline composition must never access HTTP")

    requests.Session.request = forbidden_network
    httpx.Client.send = forbidden_network
    httpx.AsyncClient.send = forbidden_network
    base = Path(root)
    clock = _SharedClock(
        shared_clock, released_sleeps=0 if phase == "restart" else 1,
        release_through=SOURCE_CLOSE + timedelta(seconds=12) if phase == "blocked" else None,
    )
    blocked = Event()  # Local thread event: never reuse a killed process's IPC wait lock.

    class FakeSDK(OfflineSDK):
        def _stock_minutes(self, name, kwargs):
            if phase == "blocked" and name == "rt_min":
                assert clock.now() == SOURCE_CLOSE + timedelta(seconds=12)
                sdk_entered.set()
                blocked.wait()  # Only this test's parent kills this child; no normal release.
                raise AssertionError("killed SDK boundary must never return")
            frame = super()._stock_minutes(name, kwargs)
            # The shared fake emits all wall minutes; provide actual exchange sessions here.
            minutes = frame["time"].map(lambda value: datetime.fromisoformat(value).time())
            return frame.loc[minutes.map(lambda value: (
                time(9, 30) <= value < time(11, 30) or time(13) <= value < time(15)
            ))].reset_index(drop=True)

    sdk = FakeSDK(clock, (SYMBOL,), official_closes={SOURCE_CLOSE.date(): "60.00"})

    class FakeChannel:
        channel = DeliveryChannel.IN_APP
        enabled = True

        async def deliver(self, event):
            with (base / "fake-deliveries.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({
                    "event_id": str(event.event_id),
                    "signal_type": event.signal_type.value,
                    "symbol": event.symbol,
                    "trading_date": event.trading_date.isoformat(),
                    "observed_at": clock.now().isoformat(),
                }) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            return ChannelDeliveryResult(channel=self.channel, delivered=True, retryable=False)

    real_controller = monitor_composition.create_live_tushare_request_controller

    def controller_factory(*, clock, require_repository_binding=False):
        pace = VirtualPace()
        return real_controller(
            clock=clock, monotonic=pace.monotonic, pace_sleep=pace.sleep,
            require_repository_binding=require_repository_binding,
        )

    monitor_composition.SystemClock = lambda: clock
    monitor_composition.create_live_tushare_request_controller = controller_factory
    production.create_tushare_client = lambda _configuration: sdk

    async def scenario():
        composition = monitor_composition.create_monitor_composition(
            config_path=base / "config/app.yaml", database_path=base / "monitor.sqlite3",
        )
        composition._runtime._dispatcher._channels = (FakeChannel(),)
        try:
            health = await composition.start()
            assert health.status is RuntimeServiceStatus.RUNNING, health
            if phase == "blocked":
                while clock.now() < AFTER_CLOSE:
                    await asyncio.sleep(0.005)
                assert sdk_entered.is_set()
            else:
                required_sleeps = 1 if phase == "restart" else 2
                while len(clock.sleep_calls) < required_sleeps:
                    await asyncio.sleep(0.005)
            reports.send({
                "phase": phase, "pid": os.getpid(), "now": clock.now().isoformat(),
                "sleeps": tuple(value.isoformat() for value in clock.sleep_calls),
                "calls": tuple(sdk.calls),
                "status": composition._runtime.health().status.value,
            })
            if phase != "restart":
                # Parent must kill P1, including the completed control.
                await asyncio.Event().wait()
        finally:
            await composition.stop()

    try:
        asyncio.run(scenario())
    except BaseException as error:
        reports.send({"error": repr(error), "phase": phase, "pid": os.getpid()})
        raise
    finally:
        reports.close()


def _seed(root):
    plan = _sample_plan().model_copy(update={
        "activation": TradingDayActivation(trading_day=SOURCE_CLOSE.date()),
    })
    database = root / "monitor.sqlite3"
    seed_clock = ControlledClock(NOW.replace(hour=9, minute=0, second=0))
    _activate_plans(database, seed_clock, (plan,))
    engine = create_sqlite_engine(database)
    sessions = create_session_factory(engine)
    try:
        with SqlAlchemyUnitOfWork(sessions, clock=seed_clock.now) as work:
            work.positions.record_buy(
                symbol=plan.symbol, bucket="CORE", quantity=200,
                acquired_trade_date=NOW.date() - timedelta(days=1), cost_fen=6300,
                board_lot=100, max_position_qty=200,
            )
            work.references.upsert_trading_days(tuple(
                TradingDay(
                    exchange=exchange, cal_date=NOW.date() + timedelta(days=offset),
                    is_open=True, previous_trade_date=NOW.date() + timedelta(days=previous),
                )
                for exchange in ("SSE", "SZSE") for offset, previous in ((-1, -4), (0, -1), (1, 0))
            ))
            work.commit()
        with sessions.begin() as session:
            session.add(RuntimeLiveness(
                id=1, schema_version=1, revision=0, last_alive_at=seed_clock.now().isoformat(),
            ))
    finally:
        engine.dispose()
    _write_configuration_and_evidence(
        root, observed_at=SOURCE_CLOSE - timedelta(minutes=1), include_index=False,
    )
    return plan


def _snapshot(root):
    database = (root / "monitor.sqlite3").resolve()
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        result = {name: tuple(dict(row) for row in connection.execute(f"SELECT * FROM {name}"))
                  for name in ("evaluation_ledger", "evaluation_result", "risk_state",
                               "alert_event", "delivery_attempt", "pending_official_close",
                               "symbol_decision_head")}
        result["risk_audits"] = tuple(dict(row) for row in connection.execute(
            "SELECT * FROM audit_log WHERE action='RISK_STATE_UPDATED' ORDER BY rowid",
        ))
    return result


def _deliveries(root):
    path = root / "fake-deliveries.jsonl"
    return tuple(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()) \
        if path.exists() else ()


def _kill_owned(process):
    """Only terminate the exact Process object created by this fixture."""
    if process.is_alive():
        process.kill()
        process.join(timeout=10)
    assert not process.is_alive(), f"owned child {process.pid} did not terminate"


def _run_process(root, phase, observed_at):
    context = get_context("spawn")
    shared_clock = context.Value("d", observed_at.timestamp())
    entered = context.Event()
    receive, send = context.Pipe(duplex=False)
    process = context.Process(
        target=_composition_child, args=(str(root), phase, shared_clock, entered, send),
    )
    process.start()
    send.close()
    try:
        if phase == "blocked":
            assert entered.wait(timeout=30), "fixture did not reach the scheduled rt_min SDK call"
            before = _snapshot(root)
            assert before["evaluation_ledger"] == before["evaluation_result"] == ()
            assert before["pending_official_close"] == ()
            shared_clock.value = AFTER_CLOSE.timestamp()
        assert receive.poll(30), f"fixture child {process.pid} failed to report phase {phase}"
        report = receive.recv()
        assert "error" not in report, f"fixture failure: {report}"
        assert report["pid"] == process.pid and report["status"] == "RUNNING"
        if phase != "restart":
            _kill_owned(process)
            assert process.exitcode != 0, "P1 must exit by force, not composition.stop()"
        else:
            process.join(timeout=30)
            assert not process.is_alive(), "restart composition did not stop"
            assert process.exitcode == 0
        return report
    finally:
        _kill_owned(process)
        receive.close()
        process.close()


def _assert_one_close(state, plan):
    assert len(state["evaluation_ledger"]) == len(state["evaluation_result"]) == 1, state
    result = state["evaluation_result"][0]
    assert result["symbol"] == plan.symbol and result["plan_hash"] == plan_sha256(plan)
    assert result["evaluation_kind"] == "OFFICIAL_CLOSE"
    assert result["target_value"] == SOURCE_CLOSE.date().isoformat()
    assert result["formula_version"] == plan.monitoring.indicator_formula_version
    assert result["source_at"] == SOURCE_CLOSE.isoformat()
    assert state["evaluation_ledger"][0]["result_hash"] == result["result_hash"]
    head, = state["symbol_decision_head"]
    assert head["activation_revision"] == 1 and head["result_hash"] == result["result_hash"]
    assert head["symbol"] == plan.symbol and head["plan_hash"] == plan_sha256(plan)
    risk, = state["risk_state"]
    assert risk["status"] == RiskStatus.BREACHED_PENDING_CONFIRMATION.value
    assert risk["breach_trade_date"] == result["target_value"]
    assert risk["revision"] == 1 and risk["plan_hash"] == plan_sha256(plan)
    # Stored risk/audit timestamps are write time; the official source is in the result.
    assert risk["updated_at"] == result["evaluated_at"] and risk["prior_close_fen"] == 6000
    snapshot = json.loads(result["result_json"])["snapshot"]
    assert snapshot["market_data_at"] == SOURCE_CLOSE.isoformat()
    assert snapshot["position"]["total_quantity"] == 200
    assert len(state["risk_audits"]) == len(state["alert_event"]) == 1
    alert = json.loads(state["alert_event"][0]["payload_json"])
    assert alert["signal_type"] == "RISK_BREACH"
    assert alert["trading_date"] == SOURCE_CLOSE.date().isoformat()
    assert state["pending_official_close"] == ()


@pytest.mark.parametrize("already_completed", (False, True), ids=("missed", "completed-control"))
@pytest.mark.parametrize("restart_day_offset", (0, 1), ids=("same-day", "next-day"))
def test_actual_composition_discovers_close_after_kill_and_deduplicates_restart(
    tmp_path, already_completed, restart_day_offset,
):
    plan = _seed(tmp_path)
    initial = _snapshot(tmp_path)
    assert all(not rows for rows in initial.values())
    phase = "completed" if already_completed else "blocked"
    first_clock = CLOSE_DUE - timedelta(seconds=30) if already_completed else (
        SOURCE_CLOSE - timedelta(seconds=30)
    )
    first = _run_process(tmp_path, phase, first_clock)
    killed_state = _snapshot(tmp_path)
    if already_completed:
        assert first["sleeps"][0] == CLOSE_DUE.isoformat()
        _assert_one_close(killed_state, plan)
    else:
        assert SOURCE_CLOSE.isoformat() in first["sleeps"]
        assert (SOURCE_CLOSE + timedelta(seconds=12)).isoformat() in first["sleeps"]
        assert len(first["sleeps"]) <= 8
        assert first["now"] == AFTER_CLOSE.isoformat()
        assert all(not rows for rows in killed_state.values())
        assert _deliveries(tmp_path) == ()

    # Only the start clock enters P2/P3. Production independently selects any missing close.
    restart_at = AFTER_CLOSE + timedelta(days=restart_day_offset)
    second = _run_process(tmp_path, "restart", restart_at)
    recovered = _snapshot(tmp_path)
    _assert_one_close(recovered, plan)
    assert datetime.fromisoformat(second["sleeps"][0]) > restart_at
    if already_completed:
        assert recovered["evaluation_result"] == killed_state["evaluation_result"]
        assert recovered["risk_state"] == killed_state["risk_state"]
        assert recovered["alert_event"] == killed_state["alert_event"]
    else:
        assert recovered["evaluation_result"][0]["evaluated_at"] == restart_at.isoformat()
    sent = _deliveries(tmp_path)
    assert all(row["signal_type"] == "RISK_BREACH" for row in sent)
    assert len({row["event_id"] for row in sent}) == len(sent) <= 1
    assert all(row["event_id"] == recovered["alert_event"][0]["id"]
               and row["symbol"] == plan.symbol
               and row["trading_date"] == SOURCE_CLOSE.date().isoformat() for row in sent)
    if already_completed or restart_day_offset == 0:
        assert len(sent) == 1  # Exercise the real dispatcher and fake channel, not only zero sends.

    _run_process(tmp_path, "restart", restart_at + timedelta(minutes=1))
    assert _snapshot(tmp_path) == recovered
    assert _deliveries(tmp_path) == sent
