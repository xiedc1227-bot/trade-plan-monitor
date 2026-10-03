"""Real process kills preserve business intent and the existing uncertain-send claim."""

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
from sqlalchemy import Engine, event, text
from test_live_pipeline_acceptance import ControlledClock, VirtualPace
from test_s3_missed_close_kill_restart import (
    AFTER_CLOSE,
    SOURCE_CLOSE,
    SYMBOL,
    CurrentCloseSDK,
    _assert_history_preserved,
    _assert_one_close,
    _inventory_bytes,
    _kill_owned,
    _seed,
    _snapshot,
)

from trade_plan_monitor.notifications.channels import ChannelDeliveryResult, DeliveryChannel
from trade_plan_monitor.notifications.dispatcher import (
    DEFAULT_CLAIM_LEASE,
    NotificationDispatcher,
)
from trade_plan_monitor.runtime.health import RuntimeServiceStatus
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork


def _state(root):
    result = _snapshot(root)
    database = (root / "monitor.sqlite3").resolve()
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        result["eligibility"] = tuple(
            dict(row)
            for row in connection.execute(
                "SELECT * FROM alert_delivery_eligibility ORDER BY event_id",
            )
        )
    return result


def _markers(root):
    path = root / "external-markers.jsonl"
    if not path.exists():
        return ()
    return tuple(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())


def _business(state):
    return {
        key: value
        for key, value in state.items()
        if key not in {"delivery_attempt", "eligibility", "current_evaluations"}
    }


def _attempt(state, channel):
    (row,) = (row for row in state["delivery_attempt"] if row["channel"] == channel)
    assert row["attempt"] == 1
    assert row["event_id"] == state["alert_event"][0]["id"]
    return row


def _notification_child(root, phase, observed_at, reports):
    """Pause real transaction/send boundaries; only the parent can release by killing."""
    import httpx
    import requests

    import trade_plan_monitor.runtime.production as production
    import trade_plan_monitor.web.monitor_composition as monitor_composition

    def forbid_network(*_args, **_kwargs):
        raise AssertionError("notification crash acceptance must remain offline")

    requests.Session.request = forbid_network
    httpx.Client.send = forbid_network
    httpx.AsyncClient.send = forbid_network
    base = Path(root)
    clock = ControlledClock(observed_at)
    blocked = Event()  # Local only: a killed child never leaves a shared Event lock held.

    def pause(**facts):
        reports.send({"phase": phase, "pid": os.getpid(), "calls": tuple(sdk.calls), **facts})
        blocked.wait()
        raise AssertionError("a killed transaction boundary must never return")

    class FakeSDK(CurrentCloseSDK):
        def _stock_minutes(self, name, kwargs):
            frame = super()._stock_minutes(name, kwargs)
            minutes = frame["time"].map(lambda value: datetime.fromisoformat(value).time())
            return frame.loc[
                minutes.map(
                    lambda value: (
                        time(9, 30) <= value < time(11, 30) or time(13) <= value < time(15)
                    )
                )
            ].reset_index(drop=True)

    sdk = FakeSDK(clock, (SYMBOL,), official_closes={SOURCE_CLOSE.date(): "60.00"})

    class FakeExternalChannel:
        channel = DeliveryChannel.CONSOLE
        enabled = True

        async def deliver(self, notification):
            with (base / "external-markers.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(
                    json.dumps(
                        {
                            "event_id": str(notification.event_id),
                            "signal_type": str(notification.signal_type),
                            "symbol": notification.symbol,
                            "trading_date": notification.trading_date.isoformat(),
                            "observed_at": clock.now().isoformat(),
                            "pid": os.getpid(),
                        }
                    )
                    + "\n"
                )
                stream.flush()
                os.fsync(stream.fileno())
            return ChannelDeliveryResult(
                channel=self.channel,
                delivered=True,
                retryable=False,
                response_code=200,
            )

    real_controller = monitor_composition.create_live_tushare_request_controller

    def controller_factory(*, clock, require_repository_binding=False):
        pace = VirtualPace()
        return real_controller(
            clock=clock,
            monotonic=pace.monotonic,
            pace_sleep=pace.sleep,
            require_repository_binding=require_repository_binding,
        )

    monitor_composition.SystemClock = lambda: clock
    monitor_composition.create_live_tushare_request_controller = controller_factory
    production.create_tushare_client = lambda _configuration: sdk

    original_commit = SqlAlchemyUnitOfWork.commit

    def observed_business_commit(work):
        if phase in {"business-uncommitted", "business-committed"}:
            session = work._require_session()
            alert_id = session.scalar(text("SELECT id FROM alert_event LIMIT 1"))
            if alert_id is not None:
                # This is the first alert: the real official-close UoW has staged every row.
                counts = {"alert_event": session.scalar(text("SELECT count(*) FROM alert_event"))}
                assert counts == {"alert_event": 1}
                assert session.scalar(text("SELECT count(*) FROM alert_delivery_eligibility")) == 0
                assert (
                    session.scalar(
                        text("SELECT count(*) FROM daily_plan_record WHERE kind='EVALUATION'")
                    )
                    == 2
                )
                assert session.scalar(text("SELECT count(*) FROM risk_state")) == 0
                assert session.scalar(text("SELECT count(*) FROM pending_official_close")) == 0
                committed_before = _state(base)
                if phase == "business-committed":
                    original_commit(work)
                pause(event_id=alert_id, transaction_rows=counts, committed_before=committed_before)
        return original_commit(work)

    SqlAlchemyUnitOfWork.commit = observed_business_commit
    original_finalize = NotificationDispatcher._finalize_claim
    finalizing_console = False

    def after_receipt_update(connection, _cursor, statement, _parameters, _context, _many):
        if (
            phase == "receipt-uncommitted"
            and finalizing_console
            and statement.lstrip().upper().startswith("UPDATE DELIVERY_ATTEMPT ")
        ):
            row = (
                connection.execute(
                    text(
                        "SELECT id, event_id, status FROM delivery_attempt WHERE channel='CONSOLE'",
                    )
                )
                .mappings()
                .one()
            )
            assert row["status"] == "DELIVERED"
            assert len(_markers(base)) == 1
            pause(event_id=row["event_id"], attempt_id=row["id"], staged_status=row["status"])

    event.listen(Engine, "after_cursor_execute", after_receipt_update)

    def observed_finalize(dispatcher, claim, result, completed_at):
        nonlocal finalizing_console
        finalizing_console = claim.channel is DeliveryChannel.CONSOLE
        try:
            receipt = original_finalize(dispatcher, claim, result, completed_at)
            if phase == "receipt-committed" and finalizing_console:
                assert receipt is not None and receipt.status.value == "DELIVERED"
                pause(event_id=str(claim.event_id), attempt_id=claim.id)
            return receipt
        finally:
            finalizing_console = False

    NotificationDispatcher._finalize_claim = observed_finalize

    async def scenario():
        composition = monitor_composition.create_monitor_composition(
            config_path=base / "config/app.yaml",
            database_path=base / "monitor.sqlite3",
        )
        dispatcher = composition._runtime._dispatcher
        # Keep the mandatory real IN_APP channel and all production delivery admission.
        dispatcher._channels = (*dispatcher._channels, FakeExternalChannel())
        try:
            health = await composition.start()
            assert health.status is RuntimeServiceStatus.RUNNING, health
            if phase != "restart":
                current = _state(base)["current_evaluations"]
                facts = [
                    {
                        k: json.loads(row["payload_json"]).get(k)
                        for k in ("official_trade_date", "data_blockers", "alerts")
                    }
                    for row in current
                ]
                print(f"MISSED_CRASH_FACTS {facts!r}", flush=True)
                raise AssertionError(f"startup missed requested crash window: {phase}")
            while not clock.sleep_calls:
                await asyncio.sleep(0)
            reports.send(
                {
                    "phase": phase,
                    "pid": os.getpid(),
                    "status": health.status.value,
                    "next_sleep": clock.sleep_calls[0].isoformat(),
                    "calls": tuple(sdk.calls),
                }
            )
        finally:
            await composition.stop()

    try:
        asyncio.run(scenario())
    except BaseException as error:
        reports.send({"error": repr(error), "phase": phase, "pid": os.getpid()})
        raise
    finally:
        reports.close()


def _run_child(root, phase, observed_at):
    context = get_context("spawn")
    receive, send = context.Pipe(duplex=False)
    process = context.Process(
        target=_notification_child,
        args=(str(root), phase, observed_at, send),
    )
    process.start()
    send.close()
    try:
        assert receive.poll(30), f"child {process.pid} did not reach {phase}"
        report = receive.recv()
        assert "error" not in report, report
        assert report["pid"] == process.pid and report["phase"] == phase
        observed = _state(root)
        markers = _markers(root)
        if phase == "restart":
            process.join(timeout=30)
            assert not process.is_alive() and process.exitcode == 0
            assert report["status"] == "RUNNING"
            assert datetime.fromisoformat(report["next_sleep"]) > observed_at
        else:
            _kill_owned(process)
            assert process.exitcode != 0, "crash window must not execute normal stop"
            assert _state(root) == observed
            assert _markers(root) == markers
        return report, observed, markers
    finally:
        _kill_owned(process)
        receive.close()
        process.close()


@pytest.mark.parametrize(
    "phase",
    (
        "business-uncommitted",
        "business-committed",
        "receipt-uncommitted",
        "receipt-committed",
    ),
)
def test_composition_kill_windows_preserve_intent_and_uncertain_claim(tmp_path, phase):
    plan = _seed(tmp_path)
    inventory = _inventory_bytes(tmp_path)
    assert inventory[0] and inventory[1] == ()
    initial = _state(tmp_path)
    assert all(not rows for rows in initial.values())
    first, killed, external = _run_child(tmp_path, phase, AFTER_CLOSE)
    assert {"trade_cal", "daily"}.issubset({name for name, _kwargs in first["calls"]})
    if phase.startswith("business-"):
        preceding = first["committed_before"]
        assert all(not rows for rows in preceding.values())
    if phase == "business-uncommitted":
        assert killed == first["committed_before"]
    else:
        _assert_one_close(killed, plan)
        assert killed["alert_event"][0]["id"] == first["event_id"]
    if phase.startswith("business-"):
        assert killed["delivery_attempt"] == external == ()
        if phase == "business-committed":
            assert killed["eligibility"] == ()
    else:
        assert len(killed["delivery_attempt"]) == 2
        assert _attempt(killed, "IN_APP")["status"] == "DELIVERED"
        console = _attempt(killed, "CONSOLE")
        assert console["id"] == first["attempt_id"]
        assert console["status"] == ("CLAIMED" if phase == "receipt-uncommitted" else "DELIVERED")
        assert len(external) == 1 and external[0]["event_id"] == first["event_id"]
        assert external[0]["pid"] == first["pid"]
        if phase == "receipt-uncommitted":
            assert console["next_retry_at"] == (AFTER_CLOSE + DEFAULT_CLAIM_LEASE).isoformat()
            assert console["delivered_at"] is None and console["response_code"] is None
        else:
            assert console["next_retry_at"] is None and console["response_code"] == 200
            assert console["delivered_at"] == AFTER_CLOSE.isoformat()

    # A live claim is not retried just because its process died.
    _, early, early_external = _run_child(tmp_path, "restart", AFTER_CLOSE + timedelta(seconds=30))
    _assert_one_close(early, plan)
    if phase != "business-uncommitted":
        assert _business(early) == _business(killed)
    if phase == "receipt-uncommitted":
        assert _attempt(early, "CONSOLE") == _attempt(killed, "CONSOLE")
        assert early_external == external
    else:
        assert _attempt(early, "CONSOLE")["status"] == "DELIVERED"
        assert len(early_external) == 1
        if phase == "receipt-committed":
            assert early["delivery_attempt"] == killed["delivery_attempt"]
            assert early_external == external

    # Equality reclaims the same durable id/attempt; an uncertain external effect may repeat.
    recovery_report, recovered, recovered_external = _run_child(
        tmp_path,
        "restart",
        AFTER_CLOSE + DEFAULT_CLAIM_LEASE,
    )
    assert _business(recovered) == _business(early)
    assert len(recovered["delivery_attempt"]) == 2
    assert _attempt(recovered, "IN_APP")["status"] == "DELIVERED"
    delivered = _attempt(recovered, "CONSOLE")
    assert delivered["status"] == "DELIVERED" and delivered["next_retry_at"] is None
    assert delivered["delivered_at"] is not None
    if phase == "receipt-uncommitted":
        assert delivered["id"] == first["attempt_id"]
        assert len(recovered_external) == 2
        assert delivered["delivered_at"] == (AFTER_CLOSE + DEFAULT_CLAIM_LEASE).isoformat()
        assert delivered["response_code"] == 200
        assert recovered_external[-1]["pid"] == recovery_report["pid"]
    else:
        assert recovered["delivery_attempt"] == early["delivery_attempt"]
        assert recovered_external == early_external
    assert all(
        marker["event_id"] == recovered["alert_event"][0]["id"]
        and marker["signal_type"] == "REMINDER"
        and marker["symbol"] == SYMBOL
        and marker["trading_date"] == SOURCE_CLOSE.date().isoformat()
        for marker in recovered_external
    )

    _run_child(tmp_path, "restart", AFTER_CLOSE + DEFAULT_CLAIM_LEASE + timedelta(seconds=1))
    _assert_history_preserved(recovered, _state(tmp_path))
    assert _markers(tmp_path) == recovered_external
    assert _inventory_bytes(tmp_path) == inventory
