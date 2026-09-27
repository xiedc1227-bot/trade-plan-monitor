"""S3-05 index retry survives a clean OS restart and real scheduler wake."""

import asyncio
import json
import os
import sqlite3
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timedelta
from multiprocessing import get_context
from pathlib import Path

import pytest
import test_explicit_runtime_production as explicit_fixture
from test_live_pipeline_acceptance import (
    NOW,
    ControlledClock,
    OfflineSDK,
    VirtualPace,
    _activate_plans,
    _plan,
    _write_configuration_and_evidence,
)

from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import ExplicitTradePlan
from trade_plan_monitor.market_data.models import TradingDay
from trade_plan_monitor.notifications.channels import ChannelDeliveryResult, DeliveryChannel
from trade_plan_monitor.runtime.health import RuntimeServiceStatus
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import RuntimeLiveness
from trade_plan_monitor.state.repositories import ManualEventRiskStatus
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

CUTOFF = NOW.replace(second=0)
FIRST_START = CUTOFF - timedelta(seconds=30)
SECOND_START = CUTOFF + timedelta(seconds=20)
NEXT_CUTOFF = CUTOFF + timedelta(minutes=5)
DEPENDENT = "003043.SZ"
INDEPENDENT = "300001.SZ"
BUSINESS_TABLES = (
    "evaluation_ledger", "evaluation_result", "explicit_evaluation_ledger",
    "alert_event", "delivery_attempt", "symbol_decision_head",
)


class _SteppedClock(ControlledClock):
    """Release only the sleep chosen by the actual scheduler, never invent deadlines."""

    def __init__(self, current):
        super().__init__(current)
        self.waiting = asyncio.Queue()

    async def sleep_until(self, deadline):
        self.sleep_calls.append(deadline)
        release = asyncio.Event()
        await self.waiting.put((deadline, release))
        await release.wait()
        self.current = max(self.current, deadline)


def _seed(root, monkeypatch):
    dependent = _plan(
        plan_id="s3-required-index", symbol=DEPENDENT, market="SZSE",
        condition={"type": "INDEX_CLOSE_GTE_MA", "index_role": "BOARD_REFERENCE", "period": 2},
    )
    database = root / "monitor.sqlite3"
    clock = ControlledClock(NOW.replace(hour=9, minute=0, second=0))
    _activate_plans(database, clock, (dependent,))
    payload = explicit_fixture._plan(active_date=NOW.date()).model_dump(
        mode="python", round_trip=True,
    )
    payload.update(plan_id="s3-independent", symbol=INDEPENDENT, name="S3 independent")
    payload["rules"][0]["condition"] = {
        "type": "COMPLETED_CLOSE_IN_RANGE", "low_fen": 6000, "high_fen": 6500,
        "include_low": True, "include_high": True,
    }
    independent = ExplicitTradePlan.model_validate(payload)
    monkeypatch.setattr(explicit_fixture, "PREPARED_AT", NOW - timedelta(minutes=30))
    engine = create_sqlite_engine(database)
    sessions = create_session_factory(engine)
    try:
        explicit_fixture._seed_active(engine, independent)
        with SqlAlchemyUnitOfWork(sessions, clock=clock.now) as work:
            work.references.upsert_trading_days(tuple(
                TradingDay(exchange=exchange, cal_date=NOW.date(), is_open=True,
                           previous_trade_date=NOW.date() - timedelta(days=1))
                for exchange in ("SSE", "SZSE")
            ))
            work.manual_event_risk.upsert(
                symbol=DEPENDENT, plan_hash=plan_sha256(dependent),
                status=ManualEventRiskStatus.CLEAR, expires_on=NOW.date(), expected_revision=0,
            )
            work.positions.confirm_inventory(
                symbol=INDEPENDENT, as_of_trade_date=NOW.date(), total_quantity=100,
                sellable_quantity=100, included_lot_ids=(), complete_registration=True,
                expected_revision=0,
            )
            work.commit()
        with sessions.begin() as session:
            session.add(RuntimeLiveness(
                id=1, schema_version=1, revision=0, last_alive_at=clock.now().isoformat(),
            ))
    finally:
        engine.dispose()
    _write_configuration_and_evidence(root, observed_at=FIRST_START, include_index=True)
    return dependent, independent


def _read_state(root):
    database = (root / "monitor.sqlite3").resolve()
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        return {name: tuple(dict(row) for row in connection.execute(
            f"SELECT * FROM {name} ORDER BY rowid",
        )) for name in (*BUSINESS_TABLES, "market_index_snapshot",
                        "market_index_snapshot_head", "market_index_recovery_state")}


def test_seed_has_real_mixed_activation_and_no_prebuilt_retry(tmp_path, monkeypatch):
    dependent, independent = _seed(tmp_path, monkeypatch)
    assert dependent.schema_version == 2 and independent.schema_version == 3
    assert all(not rows for rows in _read_state(tmp_path).values())


def _composition_child(root, phase, required_code, reports):
    import httpx
    import requests
    from requests import ConnectionError as ProviderConnectionError

    import trade_plan_monitor.runtime.production as production
    import trade_plan_monitor.web.monitor_composition as monitor_composition

    def forbid_network(*_args, **_kwargs):
        raise AssertionError("offline S3-05 must never access HTTP")

    requests.Session.request = forbid_network
    httpx.Client.send = forbid_network
    httpx.AsyncClient.send = forbid_network
    base = Path(root)
    clock = _SteppedClock(FIRST_START if phase == "failure" else SECOND_START)

    class FakeSDK(OfflineSDK):
        def _index_minutes(self, kwargs):
            if phase == "failure" and kwargs["ts_code"] == required_code:
                raise ProviderConnectionError("offline required-index failure")
            return super()._index_minutes(kwargs)

    sdk = FakeSDK(clock, (DEPENDENT, INDEPENDENT))
    delivered = []

    class FakeChannel:
        channel = DeliveryChannel.IN_APP
        enabled = True

        async def deliver(self, event):
            delivered.append({"symbol": event.symbol, "event_id": str(event.event_id)})
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
        # Replace only transport; keep enforce_current_plan and CurrentDeliveryAdmission.
        composition._runtime._dispatcher._channels = (FakeChannel(),)
        stages = {}

        def capture():
            state = composition._runtime._probe_capabilities.__self__
            return {
                "state": _read_state(base), "calls": tuple(sdk.calls),
                "delivered": tuple(delivered), "now": clock.now().isoformat(),
                "status": composition.health().status.value,
                "generation": str(composition._runtime.runtime_generation),
                "retry_at": state.next_index_recovery_at(),
            }

        async def next_sleep():
            return await asyncio.wait_for(clock.waiting.get(), timeout=20)

        try:
            health = await composition.start()
            assert health.status is RuntimeServiceStatus.RUNNING, health
            pending = await next_sleep()
            stages["startup"] = capture()
            stages["first_sleep"] = pending[0]
            pending[1].set()
            pending = await next_sleep()
            stages["first_wake"] = capture()
            if phase == "restart":
                # Let normal minute wakes run up to the next five-minute decision cutoff.
                for _ in range(10):
                    if clock.now() >= NEXT_CUTOFF + timedelta(seconds=12):
                        break
                    pending[1].set()
                    pending = await next_sleep()
                else:
                    raise AssertionError("scheduler did not reach next legal five-minute cutoff")
                stages["next_market"] = capture()
            stages["sleeps"] = tuple(clock.sleep_calls)
        finally:
            await composition.stop()
        stages["stopped"] = composition.health().status.value
        return stages

    try:
        result = asyncio.run(scenario())
        reports.send({"pid": os.getpid(), "phase": phase, **result})
    except BaseException as error:
        reports.send({"pid": os.getpid(), "error": repr(error)})
        raise
    finally:
        reports.close()


def _run_process(root, phase, required_code):
    context = get_context("spawn")
    receive, send = context.Pipe(duplex=False)
    process = context.Process(
        target=_composition_child, args=(str(root), phase, required_code, send),
    )
    process.start()
    send.close()
    try:
        assert receive.poll(60), f"S3-05 {phase} child {process.pid} did not report"
        report = receive.recv()
        assert "error" not in report, report
        process.join(timeout=15)
        assert not process.is_alive(), "composition.stop() did not allow clean OS exit"
        assert process.exitcode == 0 and report["pid"] == process.pid
        assert report["stopped"] == "STOPPED"
        return report
    finally:
        if process.is_alive():
            process.kill()  # Failure cleanup only, not the scenario's clean-stop mechanism.
            process.join(timeout=10)
        assert not process.is_alive(), f"owned child {process.pid} did not exit"
        receive.close()
        process.close()


def _index_head(state, code, cutoff):
    heads = [row for row in state["market_index_snapshot_head"]
             if row["index_code"] == code and row["decision_cutoff"] == cutoff.isoformat()]
    head, = heads
    row, = [item for item in state["market_index_snapshot"]
            if item["snapshot_hash"] == head["snapshot_hash"]]
    return json.loads(row["snapshot_json"]), head


def _legacy_result(state, cutoff, plan):
    row, = [item for item in state["evaluation_result"]
            if item["symbol"] == DEPENDENT and item["target_value"] == cutoff.isoformat()]
    assert row["plan_hash"] == plan_sha256(plan)
    return json.loads(row["result_json"])


def _index_evidence(conditions):
    for item in conditions:
        if item.get("index_evidence") is not None:
            yield item["index_evidence"]
        yield from _index_evidence(item.get("children", ()))


def _assert_index_only(before, after, required_code):
    calls = after["calls"][len(before["calls"]):]
    assert calls and all(name in {"idx_mins", "rt_idx_min_daily", "index_daily"}
                         for name, _ in calls), "stock SDK entered index-only retry"
    assert all(kwargs["ts_code"] == required_code for _, kwargs in calls)
    assert after["delivered"] == before["delivered"] == (), "index-only retry sent an alert"
    for table in BUSINESS_TABLES:
        assert after["state"][table] == before["state"][table], table


def _assert_unique_targets(state):
    for table in ("evaluation_ledger", "evaluation_result", "explicit_evaluation_ledger"):
        identity = ("plan_hash", "symbol", "target_value") + (
            ("activation_revision", "execution_version") if table == "explicit_evaluation_ledger"
            else ("evaluation_kind", "formula_version")
        )
        keys = [tuple(row[key] for key in identity) for row in state[table]]
        assert len(keys) == len(set(keys)), table


def test_required_index_retry_survives_clean_process_restart_via_scheduler(tmp_path, monkeypatch):
    dependent, independent = _seed(tmp_path, monkeypatch)
    required_code = dependent.reference_market.index_code.value
    first = _run_process(tmp_path, "failure", required_code)
    failed = first["first_wake"]
    assert first["first_sleep"] == CUTOFF + timedelta(seconds=12)
    assert failed["status"] == "RUNNING"
    assert failed["generation"] == first["startup"]["generation"]
    assert [event["symbol"] for event in failed["delivered"]] == [INDEPENDENT]
    result = _legacy_result(failed["state"], CUTOFF, dependent)
    assert result["snapshot"]["signal_type"] == "BLOCKED_DATA"
    assert result["snapshot"]["reference_market"]["health"] == "BLOCKED"
    assert result["signal_intent"] is None
    evidence, = _index_evidence(result["snapshot"]["condition_evidence"])
    assert evidence["outcome"] == "MISSING_INPUT"
    explicit, = failed["state"]["explicit_evaluation_ledger"]
    assert explicit["symbol"] == INDEPENDENT and explicit["plan_hash"] == plan_sha256(independent)
    assert explicit["activation_revision"] == 1 and explicit["target_value"] == CUTOFF.isoformat()
    assert len(failed["state"]["alert_event"]) == len(failed["state"]["delivery_attempt"]) == 1
    assert failed["state"]["delivery_attempt"][0]["status"] == "DELIVERED"
    assert failed["state"]["delivery_attempt"][0]["attempt"] == 1
    failed_snapshot, failed_head = _index_head(failed["state"], required_code, CUTOFF)
    assert failed_snapshot["health"] == "BLOCKED"
    assert "PROVIDER_UNAVAILABLE" in failed_snapshot["issues"]
    heads = failed["state"]["market_index_snapshot_head"]
    assert len(heads) == 5
    for head in heads:
        if head["index_code"] != required_code:
            snapshot, _ = _index_head(failed["state"], head["index_code"], CUTOFF)
            assert snapshot["health"] == "LIVE"
    retry, = failed["state"]["market_index_recovery_state"]
    assert retry["index_code"] == required_code and retry["decision_cutoff"] == CUTOFF.isoformat()
    assert retry["attempts"] == 0 and retry["due_at"] == failed["retry_at"].isoformat()
    assert _read_state(tmp_path) == failed["state"], "clean stop changed business/retry evidence"

    second = _run_process(tmp_path, "restart", required_code)
    assert first["pid"] != second["pid"]
    startup, recovered, market = (second[key] for key in ("startup", "first_wake", "next_market"))
    assert startup["generation"] != failed["generation"]
    assert startup["retry_at"] == failed["retry_at"] == second["first_sleep"]
    assert startup["state"]["market_index_recovery_state"] == (retry,)
    assert _index_head(startup["state"], required_code, CUTOFF)[1] == failed_head
    for table in BUSINESS_TABLES:
        assert startup["state"][table] == failed["state"][table], table
    _assert_index_only(startup, recovered, required_code)
    # Negative oracle controls mutate copied observations, never product state or policy.
    for violation in ("stock", "evaluation_result", "alert_event", "send"):
        changed = deepcopy(recovered)
        if violation == "stock":
            changed["calls"] += (("rt_min", {"ts_code": DEPENDENT}),)
        elif violation == "send":
            changed["delivered"] += ({"symbol": INDEPENDENT},)
        else:
            changed["state"][violation] += (deepcopy(changed["state"][violation][0]),)
        with pytest.raises(AssertionError):
            _assert_index_only(startup, changed, required_code)
    snapshot, head = _index_head(recovered["state"], required_code, CUTOFF)
    assert snapshot["health"] == "LIVE"
    assert datetime.fromisoformat(snapshot["decision_cutoff"]) == CUTOFF
    assert head["snapshot_hash"] != failed_head["snapshot_hash"]
    assert recovered["retry_at"] is None and not recovered["state"]["market_index_recovery_state"]
    assert market["status"] == "RUNNING"
    assert market["generation"] == recovered["generation"] == startup["generation"]
    assert market["now"] == (NEXT_CUTOFF + timedelta(seconds=12)).isoformat()
    result = _legacy_result(market["state"], NEXT_CUTOFF, dependent)
    assert result["snapshot"]["reference_market"]["health"] == "LIVE"
    assert result["snapshot"]["signal_type"] != "BLOCKED_DATA"
    assert any(name == "rt_min" for name, _ in market["calls"][len(recovered["calls"]):])
    assert all(event["symbol"] != INDEPENDENT for event in market["delivered"])
    for table in ("alert_event", "delivery_attempt"):
        for original in failed["state"][table]:
            assert original in market["state"][table], table
    assert [row for row in market["state"]["alert_event"]
            if json.loads(row["payload_json"])["symbol"] == INDEPENDENT] == list(
        failed["state"]["alert_event"],
    )
    original_event_id = failed["state"]["alert_event"][0]["id"]
    assert failed["delivered"][0]["event_id"] == original_event_id
    assert [row for row in market["state"]["delivery_attempt"]
            if row["event_id"] == original_event_id] == list(failed["state"]["delivery_attempt"])
    assert explicit in market["state"]["explicit_evaluation_ledger"]
    _assert_unique_targets(market["state"])
