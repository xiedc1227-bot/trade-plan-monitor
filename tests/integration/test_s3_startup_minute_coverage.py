"""Actual startup coverage: safety controls and enabled recovery/cutoff regressions."""

import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager, closing
from datetime import datetime, timedelta
from decimal import Decimal

import httpx
import pandas as pd
import pytest
import requests
from test_live_pipeline_acceptance import (
    NOW,
    ControlledClock,
    OfflineSDK,
    VirtualPace,
    _activate_plans,
    _write_configuration_and_evidence,
)
from tests.integration.current_activation_fixture import current_sample_plan, seed_current

from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.market_data.models import MinuteBar
from trade_plan_monitor.market_data.sessions import expected_minute_ends
from trade_plan_monitor.notifications.channels import ChannelDeliveryResult, DeliveryChannel
from trade_plan_monitor.runtime.health import RuntimeServiceStatus
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import RuntimeLiveness
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

SYMBOL = "003043.SZ"
CUTOFF = NOW.replace(second=0)
FIRST_END = NOW.replace(hour=9, minute=31, second=0)
FIFTH_DUE = NOW.replace(minute=5, second=12)
PROGRESS_BOUND = NOW.replace(minute=10, second=12)
BUSINESS_TABLES = (
    "evaluation_ledger",
    "evaluation_result",
    "symbol_decision_head",
    "risk_state",
    "alert_event",
    "delivery_attempt",
    "pending_official_close",
)


def _prefix(cutoff):
    return tuple(end for end in expected_minute_ends(cutoff.date(), is_open=True) if end <= cutoff)


class _DeadlineClock(ControlledClock):
    """Park each real scheduler wait until the test releases its actual deadline."""

    def __init__(self, current):
        super().__init__(current)
        self.waits = asyncio.Queue()
        self.parked = None
        self.released = 0

    async def sleep_until(self, deadline):
        self.sleep_calls.append(deadline)
        permit = asyncio.get_running_loop().create_future()
        await self.waits.put((deadline, permit))
        await permit

    async def park(self, *, failed=lambda: False):
        while self.waits.empty():
            if failed():
                return False
            await asyncio.sleep(0.005)
        self.parked = await self.waits.get()
        return True

    async def drive(
        self,
        through,
        *,
        stop_when=lambda: False,
        failed=lambda: False,
        after_wake=lambda: None,
    ):
        while self.parked[0] <= through and not stop_when():
            deadline, permit = self.parked
            assert self.released < 64, "fixture wake guard exceeded"
            self.released += 1
            self.current = max(self.current, deadline)
            permit.set_result(None)
            # The next requested sleep proves the preceding scheduled work returned.
            if not await self.park(failed=failed):
                return
            after_wake()


class _CoverageSDK(OfflineSDK):
    def __init__(self, clock, mode):
        super().__init__(clock, (SYMBOL,))
        self.mode = mode
        self.phase = "startup"
        self.history_available = False
        self.trace = []

    def __getattr__(self, name):
        request = super().__getattr__(name)

        def recorded(**kwargs):
            self.trace.append(
                {
                    "sequence": len(self.trace) + 1,
                    "endpoint": name,
                    "phase": self.phase,
                    "entered_at": self.clock.now().isoformat(),
                }
            )
            return request(**kwargs)

        return recorded

    def _stock_minutes(self, name, kwargs):
        if name == "rt_min":
            return super()._stock_minutes(name, kwargs)
        if self.mode == "crossed-cutoff" and self.phase == "startup":
            assert self.clock.now() == NOW.replace(second=59)
            # Market time only: no wall-time sleep or replacement of the real timeout.
            self.clock.current = NOW.replace(minute=1, second=13)
        frame = super()._stock_minutes(name, kwargs)
        if self.mode == "future":
            future = frame.iloc[-1].to_dict()
            # START label: raw 10:00 becomes bar_end 10:01, incomplete at 10:00:15.
            future["time"] = CUTOFF.strftime("%Y-%m-%d %H:%M:%S")
            return pd.concat((frame, pd.DataFrame([future])), ignore_index=True)
        if self.history_available or self.mode in {"full", "crossed-cutoff"}:
            return frame
        if self.mode in {"empty", "persisted"}:
            return frame.iloc[:0].copy()  # Preserve the real adapter's required schema.
        assert self.mode == "partial"
        missing_source = (FIRST_END - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
        return frame.loc[frame["time"] != missing_source].reset_index(drop=True)

    def entries(self, endpoint):
        return tuple(item for item in self.trace if item["endpoint"] == endpoint)


def _snapshot(database):
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        state = {
            name: tuple(dict(row) for row in db.execute(f"SELECT * FROM {name} ORDER BY rowid"))
            for name in BUSINESS_TABLES
        }
        for kind in ("EVALUATION", "SIGNAL", "RISK"):
            query = "SELECT * FROM daily_plan_record WHERE kind=?"
            if kind == "EVALUATION":
                query += " AND json_extract(payload_json, '$.minute_target') IS NOT NULL"
            state["current_" + kind.lower()] = tuple(
                dict(row)
                for row in db.execute(
                    query + " ORDER BY id",
                    (kind,),
                )
            )
        state["minutes"] = tuple(
            row[0]
            for row in db.execute(
                "SELECT bar_end FROM minute_bar WHERE symbol=? ORDER BY bar_end",
                (SYMBOL,),
            )
        )
        state["risk_audits"] = tuple(
            dict(row)
            for row in db.execute(
                "SELECT * FROM audit_log WHERE action='RISK_STATE_UPDATED' ORDER BY rowid",
            )
        )
    return state


def _seed(root, *, persisted):
    database = root / "monitor.sqlite3"
    seed_clock = ControlledClock(NOW.replace(hour=9, minute=0, second=0))
    plan = current_sample_plan()
    _activate_plans(database, seed_clock, ())
    seed_current(root, plan=plan, clock=seed_clock)
    engine = create_sqlite_engine(database)
    sessions = create_session_factory(engine)
    try:
        if persisted:
            with SqlAlchemyUnitOfWork(sessions, clock=seed_clock.now) as work:
                work.history.upsert_minutes(
                    tuple(
                        MinuteBar(
                            symbol=SYMBOL,
                            bar_end=end,
                            open_fen=6400,
                            high_fen=6410,
                            low_fen=6390,
                            close_fen=6405,
                            volume_shares=1000,
                            amount_yuan=Decimal("64000"),
                            received_at=NOW,
                        )
                        for end in _prefix(CUTOFF)
                    )
                )
                work.commit()
        with sessions.begin() as session:
            session.add(
                RuntimeLiveness(
                    id=1,
                    schema_version=1,
                    revision=0,
                    last_alive_at=seed_clock.now().isoformat(),
                )
            )
    finally:
        engine.dispose()
    return database, plan


class _Run:
    def __init__(self, root, monkeypatch, mode, observed_at):
        import trade_plan_monitor.runtime.production as production
        import trade_plan_monitor.web.monitor_composition as composition_module

        self.database, self.plan = _seed(root, persisted=mode == "persisted")
        self.config = _write_configuration_and_evidence(
            root,
            observed_at=observed_at,
            include_index=False,
        )
        self.clock = _DeadlineClock(observed_at)
        self.sdk = _CoverageSDK(self.clock, mode)
        self.sent = []
        self.composition = None
        self.module = composition_module
        real_controller = composition_module.create_live_tushare_request_controller

        def controller_factory(*, clock, require_repository_binding=False):
            pace = VirtualPace()
            return real_controller(
                clock=clock,
                monotonic=pace.monotonic,
                pace_sleep=pace.sleep,
                require_repository_binding=require_repository_binding,
            )

        def forbid_http(*_args, **_kwargs):
            raise AssertionError("offline startup coverage must never access HTTP")

        monkeypatch.setattr(requests.Session, "request", forbid_http)
        monkeypatch.setattr(httpx.Client, "send", forbid_http)
        monkeypatch.setattr(httpx.AsyncClient, "send", forbid_http)
        monkeypatch.setattr(composition_module, "SystemClock", lambda: self.clock)
        monkeypatch.setattr(
            composition_module,
            "create_live_tushare_request_controller",
            controller_factory,
        )
        monkeypatch.setattr(production, "create_tushare_client", lambda _config: self.sdk)

    async def start(self):
        sent = self.sent

        class FakeChannel:
            channel = DeliveryChannel.IN_APP
            enabled = True

            async def deliver(self, event):
                sent.append(str(event.event_id))
                return ChannelDeliveryResult(channel=self.channel, delivered=True, retryable=False)

        self.composition = self.module.create_monitor_composition(
            config_path=self.config,
            database_path=self.database,
        )
        self.composition._runtime._dispatcher._channels = (FakeChannel(),)
        health = await self.composition.start()
        assert health.status is RuntimeServiceStatus.RUNNING, health
        await self.clock.park()
        assert self.clock.released == 0
        assert self.sdk.entries("rt_min") == (), self.sdk.trace

    def state(self):
        return _snapshot(self.database)

    def runner_failed(self):
        return self.composition.health().degraded_reason == "RUNTIME_RUNNER_FAILED"

    async def stop(self):
        if self.composition is not None:
            await asyncio.wait_for(self.composition.stop(), timeout=10)

    async def restart(self):
        await self.stop()
        self.clock = _DeadlineClock(self.clock.now() + timedelta(seconds=1))
        self.sdk = _CoverageSDK(self.clock, "persisted")
        await self.start()


@asynccontextmanager
async def _running(root, monkeypatch, mode, *, observed_at=NOW):
    async with asyncio.timeout(45):  # Real watchdog; not a production recovery guarantee.
        run = _Run(root, monkeypatch, mode, observed_at)
        try:
            await run.start()
            yield run
        finally:
            await run.stop()


def _assert_startup_minutes(run, expected, *, require_fetch=True):
    assert run.state()["minutes"] == tuple(end.isoformat() for end in expected), run.sdk.trace
    entries = run.sdk.entries("rt_min_daily")
    if require_fetch:
        assert len(entries) == 1, run.sdk.trace
    assert all(
        entry["phase"] == "startup" and entry["entered_at"] == NOW.isoformat() for entry in entries
    ), run.sdk.trace


async def _assert_safe_incomplete(run):
    state = run.state()
    assert all(state[name] == () for name in (*BUSINESS_TABLES, "risk_audits")), state
    assert state["current_signal"] == state["current_risk"] == ()
    for row in state["current_evaluation"]:
        snapshot = json.loads(row["payload_json"])
        assert snapshot["signals"] == snapshot["risks"] == []
        assert snapshot["next_action"] == "WAIT_FOR_VERIFIED_INPUT_OR_NEXT_SESSION"
        assert snapshot["risk_action"]["status"] != "RISK_EXIT"
    assert run.sent == []
    detail = await run.composition.read_service.get_symbol(symbol=SYMBOL)
    assert detail.reason.value == "AWAITING_FIRST_EVALUATION", detail


def _assert_decision_timing(result, *, observed_evaluation_at):
    target = datetime.fromisoformat(result["target_value"])
    evaluated_at = datetime.fromisoformat(result["evaluated_at"])
    assert evaluated_at == observed_evaluation_at, "evaluation time must match actual observation"
    assert timedelta(0) <= evaluated_at - target <= timedelta(seconds=90), (
        "decision target must be inside the existing 90-second freshness window"
    )


def _assert_current_decision(run, *, target=None, expected_evaluated_at=None):
    state = run.state()
    records = state["current_evaluation"]
    immutable = [row for row in records if not row["id"].startswith("evaluation-head-")]
    assert len(immutable) == 1, (state, run.sdk.trace)
    (record,) = immutable
    canonical = json.loads(record["payload_json"])
    assert canonical["symbol"] == SYMBOL and canonical["plan_hash"] == plan_sha256(run.plan)
    assert canonical["content_hash"] and canonical["review_id"]
    target_value = canonical["minute_target"]
    if target is not None:
        assert target_value == target.isoformat()
    assert CUTOFF.isoformat() < target_value <= run.clock.now().isoformat()
    _assert_decision_timing(
        {"target_value": target_value, "evaluated_at": canonical["evaluated_at"]},
        observed_evaluation_at=(
            run.clock.now() if expected_evaluated_at is None else expected_evaluated_at
        ),
    )
    (head,) = [row for row in records if row["id"] == "evaluation-head-" + SYMBOL]
    assert head["payload_json"] == record["payload_json"]
    assert canonical["activation_revision"] == 1
    assert canonical["minute_prefix"][-1]["bar_end"] == target_value
    assert canonical["five_minute_bars"][-1]["bar_end"] == target_value
    assert canonical["five_minute_bars"][-1]["close_fen"] == 6405
    if canonical["quote"] is not None:
        assert canonical["quote"]["quote_at"] == target_value
        assert canonical["quote"]["price_fen"] == 6405
    assert set(end.isoformat() for end in _prefix(datetime.fromisoformat(target_value))).issubset(
        state["minutes"],
    )
    assert state["evaluation_ledger"] == state["evaluation_result"] == ()
    assert state["symbol_decision_head"] == state["pending_official_close"] == ()


def test_current_decision_oracle_accepts_a_fresh_actual_evaluation():
    _assert_decision_timing(
        {
            "target_value": FIFTH_DUE.replace(second=0).isoformat(),
            "evaluated_at": FIFTH_DUE.isoformat(),
        },
        observed_evaluation_at=FIFTH_DUE,
    )


@pytest.mark.parametrize(
    ("evaluated_at", "message"),
    ((PROGRESS_BOUND, "90-second freshness"), (FIFTH_DUE, "actual observation")),
    ids=("late-replay", "backdated-evaluation"),
)
def test_current_decision_oracle_rejects_old_targets(evaluated_at, message):
    # Synthetic oracle input only: no production evaluator or stored result is replaced.
    with pytest.raises(AssertionError, match=message):
        _assert_decision_timing(
            {
                "target_value": FIFTH_DUE.replace(second=0).isoformat(),
                "evaluated_at": evaluated_at.isoformat(),
            },
            observed_evaluation_at=PROGRESS_BOUND,
        )


@pytest.mark.parametrize("mode", ("empty", "partial"), ids=("A-empty", "B-missing-0931"))
def test_incomplete_startup_never_commits_a_decision_from_complete_later_buckets(
    tmp_path,
    monkeypatch,
    mode,
):
    async def scenario():
        async with _running(tmp_path, monkeypatch, mode) as run:
            _assert_startup_minutes(run, () if mode == "empty" else _prefix(CUTOFF)[1:])
            await _assert_safe_incomplete(run)
            run.sdk.phase = "scheduled-safety"  # History deliberately stays unavailable.
            await run.clock.drive(FIFTH_DUE, failed=run.runner_failed)
            assert len(run.sdk.entries("rt_min")) == 5, run.sdk.trace
            assert FIRST_END.isoformat() not in run.state()["minutes"]
            await _assert_safe_incomplete(run)

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ("empty", "partial"), ids=("A-empty", "B-missing-0931"))
def test_incomplete_startup_is_not_promoted_to_a_runtime_runner_fault(tmp_path, monkeypatch, mode):
    async def scenario():
        async with _running(tmp_path, monkeypatch, mode) as run:
            _assert_startup_minutes(run, () if mode == "empty" else _prefix(CUTOFF)[1:])
            run.sdk.phase = "scheduled-incomplete"
            await run.clock.drive(FIFTH_DUE, failed=run.runner_failed)
            boundary_health = run.composition.health()
            await _assert_safe_incomplete(run)
            assert boundary_health.degraded_reason != "RUNTIME_RUNNER_FAILED", (
                boundary_health,
                run.sdk.trace,
            )

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ("empty", "partial"), ids=("A-empty", "B-missing-0931"))
def test_incomplete_startup_autonomously_reacquires_its_missing_prefix(
    tmp_path,
    monkeypatch,
    mode,
):
    async def scenario():
        async with _running(tmp_path, monkeypatch, mode) as run:
            _assert_startup_minutes(run, () if mode == "empty" else _prefix(CUTOFF)[1:])
            initial_generation = run.composition.health().runtime_generation
            await _assert_safe_incomplete(run)

            def assert_same_owner():
                health = run.composition.health()
                assert health.runtime_generation == initial_generation, (health, run.sdk.trace)
                assert health.degraded_reason != "RUNTIME_RUNNER_FAILED", (health, run.sdk.trace)

            run.sdk.phase = "scheduled-progress"
            run.sdk.history_available = True
            await run.clock.drive(
                FIFTH_DUE - timedelta(microseconds=1),
                stop_when=lambda: FIRST_END.isoformat() in run.state()["minutes"],
                failed=run.runner_failed,
                after_wake=assert_same_owner,
            )
            assert_same_owner()
            missing = set(end.isoformat() for end in _prefix(CUTOFF)) - set(run.state()["minutes"])
            assert not missing, (
                f"startup prefix never recovered by {PROGRESS_BOUND.isoformat()}",
                sorted(missing),
                run.sdk.trace,
            )
            # Facts are repaired, but only the next legitimate market evaluation
            # may make the public read model actionable or create business state.
            await _assert_safe_incomplete(run)
            assert any(
                entry["phase"] == "scheduled-progress" for entry in run.sdk.entries("rt_min_daily")
            ), run.sdk.trace
            await run.clock.drive(
                FIFTH_DUE,
                failed=run.runner_failed,
                after_wake=assert_same_owner,
            )
            assert_same_owner()
            _assert_current_decision(
                run,
                target=FIFTH_DUE.replace(second=0),
                expected_evaluated_at=FIFTH_DUE,
            )

    asyncio.run(scenario())


def test_real_provider_filters_a_truly_future_row_beside_the_complete_prefix(tmp_path, monkeypatch):
    async def scenario():
        async with _running(tmp_path, monkeypatch, "future") as run:
            _assert_startup_minutes(run, _prefix(CUTOFF))
            assert (CUTOFF + timedelta(minutes=1)).isoformat() not in run.state()["minutes"]

    asyncio.run(scenario())


def test_startup_never_persists_rows_newer_than_its_frozen_acquisition_cutoff(
    tmp_path,
    monkeypatch,
):
    async def scenario():
        async with _running(
            tmp_path,
            monkeypatch,
            "crossed-cutoff",
            observed_at=NOW.replace(second=59),
        ) as run:
            entries = run.sdk.entries("rt_min_daily")
            assert len(entries) == 1 and entries[0]["phase"] == "startup", run.sdk.trace
            assert entries[0]["entered_at"] == NOW.replace(second=59).isoformat(), run.sdk.trace
            assert run.clock.now() == NOW.replace(minute=1, second=13)
            assert run.clock.released == 0 and run.sdk.entries("rt_min") == ()
            actual = run.state()["minutes"]
            assert set(end.isoformat() for end in _prefix(CUTOFF)).issubset(actual)
            assert actual == tuple(end.isoformat() for end in _prefix(CUTOFF)), (
                "response-time normalization must not advance the frozen startup cutoff",
                actual,
                run.sdk.trace,
            )

    asyncio.run(scenario())


def test_a_new_real_acquisition_can_accept_the_now_completed_minute(tmp_path, monkeypatch):
    async def scenario():
        later = NOW.replace(minute=1, second=13)
        async with _running(tmp_path, monkeypatch, "full", observed_at=later) as run:
            assert run.state()["minutes"] == tuple(
                end.isoformat() for end in _prefix(later.replace(second=0))
            )
            entries = run.sdk.entries("rt_min_daily")
            assert len(entries) == 1 and entries[0]["entered_at"] == later.isoformat()
            assert run.sdk.entries("rt_min") == ()

    asyncio.run(scenario())


def test_persisted_complete_prefix_survives_empty_startup_and_repeated_startup(
    tmp_path,
    monkeypatch,
):
    async def scenario():
        async with _running(tmp_path, monkeypatch, "persisted") as run:
            _assert_startup_minutes(run, _prefix(CUTOFF), require_fetch=False)
            run.sdk.phase = "scheduled-complete-control"
            await run.clock.drive(FIFTH_DUE)
            _assert_current_decision(run, target=FIFTH_DUE.replace(second=0))
            before = run.state()
            evaluated_at = run.clock.now()
            sent = tuple(run.sent)
            await run.restart()
            assert run.state() == before
            assert tuple(run.sent) == sent
            _assert_current_decision(
                run,
                target=FIFTH_DUE.replace(second=0),
                expected_evaluated_at=evaluated_at,
            )

    asyncio.run(scenario())
