"""Bounded offline browser adapter for the existing actual runtime composition.

Only SDK inputs and the scheduler clock are controlled. Production owns source
review, evaluation, completion proofs, SQLite records and public GET responses.
"""

import argparse
import asyncio
import json
import socket
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Literal

import httpx
import pytest
from fastapi import Depends
from tests.browser.source_coverage_server import (
    DisabledAI,
    FixtureState,
    _loopback,
    _request_server_shutdown,
)
from tests.integration.current_activation_fixture import current_sample_plan
from tests.integration.test_market_linkage_review import source_mapping

from trade_plan_monitor.domain.daily_plan_validation import daily_draft_json, load_daily_draft_json
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.state.models import TradingCalendar
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.errors import ApiError, ApiErrorCode
from trade_plan_monitor.web.origin_guard import LocalSpaRoute
from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle
from trade_plan_monitor.web.routers.plans import PlanDraftCommand
from trade_plan_monitor.web.schemas import ApiValue, MutationContextDependency

PREFIX = "/_test/plan-readiness"
REPOSITORY = Path(__file__).resolve().parents[2]


class NextTarget(ApiValue):
    """No caller-selected time, proof, source, result or configuration."""


class SourceCase(ApiValue):
    scenario: Literal["repair", "contexts"]


def official_wait_plan():
    """Accepted mixed-current seam: daily comparison plus independent minute alert."""
    from tests.unit.test_unified_plan_domain import unified_payload

    raw = current_sample_plan().model_dump(mode="json")
    minute = raw["ordinary_rules"][0]["condition"]
    raw["ordinary_rules"][0].update(
        independent_signal={"mode": "ONCE_PER_RULE"},
        confirmation={"kind": "OFFICIAL_DAILY_CLOSE"},
        execution_window="NEXT_EXCHANGE_SESSION_ONLY",
        condition={
            "type": "DAILY_PRICE_COMPARE",
            "field": "close",
            "offset": 0,
            "comparator": "LT",
            "reference": {
                "mode": "FIXED",
                "value": "4000",
                "unit": "FEN",
                "as_of": "2026-09-07",
                "source": "fixture",
            },
        },
    )
    raw["alert_rules"] = [
        {
            "kind": "RISK_ALERT",
            "rule_id": "minute-alert",
            "condition": minute,
            "confirmation": {"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
        }
    ]
    raw["monitoring"] = unified_payload()["monitoring"]
    return UnifiedTradePlan.model_validate(raw)


class ReadinessFixture:
    prefix = PREFIX

    def __init__(self, root):
        self.root = root
        self.patch = pytest.MonkeyPatch()
        self.external_attempts = []
        self.version = None
        self.cycles = 0
        self.shutdown = None
        self.closed = False
        self.app = None
        self.case = None
        self.lifecycle = None
        self.source_cases = {}
        self.scenario = "automatic"
        self.manual_inputs = []
        self.calendar_backup = None
        self.calendar_restored = False
        self.notification_checks = 0
        self.notification_closed = False
        self.official_input_missing = False

    def guard_connections(self):
        def guard(native):
            def connect(instance, address):
                if not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1"}:
                    self.external_attempts.append("NON_LOOPBACK_CONNECTION")
                    raise AssertionError("Readiness browser fixture forbids external connections")
                return native(instance, address)

            return connect

        self.patch.setattr(socket.socket, "connect", guard(socket.socket.connect))
        self.patch.setattr(socket.socket, "connect_ex", guard(socket.socket.connect_ex))

    @property
    def readiness_path(self):
        return f"/api/v1/plan-versions/{self.version}/monitor-readiness"

    def inspect(self):
        runtime = self.case.composition._runtime
        _, _, plans = runtime._liveness_owner._pipeline.runtime_status_snapshot()
        proof = plans[0].completion
        return {
            "temporary": True,
            "root": str(self.root),
            "database": str(self.root / "monitor.sqlite3"),
            "planVersionId": self.version,
            "planUrl": f"/plans/{self.version}",
            "now": self.case.clock.now().isoformat(),
            "runtimeGeneration": str(runtime.runtime_generation),
            "completionResultHash": None if proof is None else proof.result_hash,
            "completionRecordId": (
                None if proof is None else getattr(proof.input_stamp, "immutable_record_id", None)
            ),
            "cycles": self.cycles,
            "sdkCalls": len(self.case.sdk.calls),
            "externalAttempts": list(self.external_attempts),
            "storage": FixtureState(self.root, self.lifecycle).snapshot(),
        }

    def restore_boundaries(self):
        self.patch.undo()


def create_fixture_app(root: Path, *, port=8765, static_directory=None, scenario="automatic"):
    if scenario not in {"automatic", "manual-leaves", "notifications", "official-wait"}:
        raise ValueError("Unknown fixed browser scenario")
    root = root.resolve()
    if not root.is_relative_to(REPOSITORY / ".pytest_cache"):
        raise ValueError("Use a fresh project-local .pytest_cache directory")
    if root.is_symlink() or root.exists() and any(root.iterdir()):
        raise ValueError("A fresh isolated readiness directory is required")
    root.mkdir(parents=True, exist_ok=True)
    state = ReadinessFixture(root)
    state.scenario = scenario
    try:
        state.guard_connections()
        # The reused fixture's scheduler imports neighboring test modules by
        # basename, as pytest does. Confine that lookup to this fixture lifetime.
        state.patch.syspath_prepend(str(REPOSITORY / "tests/integration"))
        from tests.integration.test_plan_readiness_profile_ownership import installed, start_current

        plan = None
        if scenario == "manual-leaves":
            raw = current_sample_plan().model_dump(mode="json")
            raw["alert_rules"] = []
            raw["ordinary_rules"][0]["condition"] = {
                "type": "ALL",
                "conditions": [
                    {
                        "type": "REVIEWED_FACT",
                        "fact_kind": "VOLUME_OR_CANDLE",
                        "validity_scope": "TRADE_DATE",
                        "evidence_requirement": requirement,
                    }
                    for requirement in ("成交不异常放大", "明显下影")
                ],
            }
            plan = UnifiedTradePlan.model_validate(raw)
        elif scenario == "notifications":
            raw = current_sample_plan().model_dump(mode="json")
            raw["alert_rules"] = [
                {
                    "kind": "RISK_ALERT",
                    "rule_id": identity,
                    "condition": {
                        "type": "MINUTE_CLOSE_BELOW",
                        "timeframe_minutes": 5,
                        "price_fen": 10000,
                    },
                    "confirmation": {"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
                }
                for identity in ("first-reminder", "second-reminder")
            ]
            raw["ordinary_rules"] = []
            plan = UnifiedTradePlan.model_validate(raw)
        if scenario == "official-wait":
            from tests.integration.test_live_pipeline_acceptance import NOW
            from tests.integration.test_s3_missed_close_kill_restart import CurrentCloseSDK

            state.case = installed(
                root,
                state.patch,
                2,
                plan=official_wait_plan(),
                sdk_factory=CurrentCloseSDK,
                activation_at=NOW.replace(day=7, hour=9, minute=0, second=0),
            )
        else:
            state.case = installed(root, state.patch, 2, plan=plan)
        if scenario == "notifications":
            dispatcher = state.case.composition._runtime._liveness_owner._dispatcher
            native_dispatch = dispatcher.dispatch_pending

            async def one_pending():
                return await native_dispatch(limit=1)

            state.patch.setattr(dispatcher, "dispatch_pending", one_pending)
        state.lifecycle = PersistentPlanWebLifecycle(
            database_path=root / "monitor.sqlite3",
            clock=state.case.clock.now,
        )
        app = create_app(
            runtime_factory=lambda: state.case.composition,
            read_service=state.case.composition.read_service,
            plan_lifecycle_factory=lambda: state.lifecycle,
            ai_service=DisabledAI(),
            monitor_contract_version=2,
            bind_port=port,
            static_directory=static_directory,
        )
        state.app = app
        app.state.readiness_fixture = state
        native_lifespan = app.router.lifespan_context

        @asynccontextmanager
        async def lifespan(application):
            try:
                async with native_lifespan(application):
                    if scenario == "manual-leaves":
                        active = await state.lifecycle.get_plan_activation_state(symbol=plan.symbol)
                        saved = await state.lifecycle.get_plan_version(
                            version_id=str(active.plan_version_id)
                        )
                        now = state.case.clock.now().isoformat()
                        # Fixed synthetic prerequisites use the public routes;
                        # neither condition A nor B is supplied here.
                        commands = [
                            (
                                "/simulation-position-confirmations",
                                {
                                    "symbol": plan.symbol,
                                    "coreQty": 0,
                                    "tacticalQty": 0,
                                    "expectedRevision": 0,
                                },
                            ),
                            (
                                "/plan-facts",
                                {
                                    "planVersionId": str(active.plan_version_id),
                                    "contentHash": saved.content_hash,
                                    "factId": "fixture-tradability",
                                    "kind": "TRADABILITY",
                                    "tradeDate": str(state.case.clock.now().date()),
                                    "evidence": (
                                        "Synthetic fixture official tradability prerequisite; "
                                        "not a technical leaf observation."
                                    ),
                                    "expectedRevision": 0,
                                    "officialEvidence": {
                                        "issuer": "Synthetic exchange evidence fixture",
                                        "documentTitle": (
                                            "Verified tradability prerequisite fixture"
                                        ),
                                        "documentUrl": "https://example.test/tradability",
                                        "publishedAt": now,
                                        "verifiedAt": now,
                                        "applicableAssertion": (
                                            "Synthetic fixture verifies only current tradability."
                                        ),
                                    },
                                },
                            ),
                        ]
                        async with httpx.ASGITransport(
                            app, client=("127.0.0.1", 50000)
                        ) as transport:
                            for index, (path, body) in enumerate(commands):
                                response = await transport.handle_async_request(
                                    httpx.Request(
                                        "POST",
                                        f"http://127.0.0.1:{port}/api/v1" + path,
                                        json=body,
                                        headers={
                                            "X-Monitor-Contract-Version": "2",
                                            "Idempotency-Key": (
                                                f"fixture-manual-prerequisite-{index}"
                                            ),
                                        },
                                    )
                                )
                                await response.aread()
                                if response.status_code != 200:
                                    raise AssertionError(response.text)
                                state.manual_inputs.append(response.json())
                    if scenario == "official-wait":
                        async with httpx.ASGITransport(
                            app, client=("127.0.0.1", 50000)
                        ) as transport:
                            response = await transport.handle_async_request(
                                httpx.Request(
                                    "POST",
                                    f"http://127.0.0.1:{port}/api/v1/simulation-position-confirmations",
                                    json={
                                        "symbol": state.case.plan.symbol,
                                        "coreQty": 0,
                                        "tacticalQty": 0,
                                        "expectedRevision": 0,
                                    },
                                    headers={
                                        "X-Monitor-Contract-Version": "2",
                                        "Idempotency-Key": "official-wait-zero-position",
                                    },
                                )
                            )
                            await response.aread()
                            if response.status_code != 200:
                                raise AssertionError(response.text)
                    async with asyncio.timeout(30):
                        state.version = await start_current(state.case)
                        # Let the next native minute duty perform its real
                        # notification storage check after pending maintenance.
                        # The first duty's original 1us service expiry is retained.
                        if scenario != "notifications":
                            await state.case.clock.drive(
                                state.case.clock.now() + timedelta(minutes=1)
                            )
                    state.cycles = 1
                    yield
            finally:
                state.closed = True
                state.restore_boundaries()

        app.router.lifespan_context = lifespan
        guards = [Depends(_loopback)]

        @app.get(PREFIX + "/inspect", dependencies=guards)
        async def inspect():
            return state.inspect()

        @app.post(PREFIX + "/next-target", dependencies=guards)
        async def next_target(command: NextTarget):
            if state.cycles != 1:
                raise ApiError(ApiErrorCode.CONFLICT)
            async with asyncio.timeout(30):
                await state.case.clock.drive(state.case.clock.now() + timedelta(minutes=5))
            state.cycles = 2
            return state.inspect()

        @app.post(PREFIX + "/calendar-loss", dependencies=guards)
        async def calendar_loss(command: NextTarget):
            if state.scenario != "automatic" or state.cycles != 1 or state.calendar_backup:
                raise ApiError(ApiErrorCode.CONFLICT)
            pipeline = state.case.composition._runtime._liveness_owner._pipeline
            inputs = pipeline.daily_evaluations._current_inputs[state.case.plan.symbol]
            closed = next(day for day in inputs.trading_calendar if not day.is_open)
            with state.lifecycle._unit_of_work() as work:
                row = work.daily.session.get(TradingCalendar, (closed.exchange, closed.cal_date))
                saved = {
                    key: getattr(row, key)
                    for key in ("exchange", "cal_date", "is_open", "previous_trade_date")
                }
                work.daily.session.delete(row)
                work.commit()
            state.calendar_backup = saved
            return {"calendarRow": saved, "inspection": state.inspect()}

        @app.post(PREFIX + "/notification-next-check", dependencies=guards)
        async def notification_next_check(command: NextTarget):
            if (
                scenario != "notifications"
                or state.notification_checks
                or state.notification_closed
            ):
                raise ApiError(ApiErrorCode.CONFLICT)
            async with asyncio.timeout(30):
                await state.case.clock.drive(state.case.clock.now() + timedelta(minutes=1))
            state.notification_checks = 1
            return state.inspect()

        @app.post(PREFIX + "/official-history-loss", dependencies=guards)
        async def official_history_loss(command: NextTarget):
            if scenario != "official-wait" or state.official_input_missing:
                raise ApiError(ApiErrorCode.CONFLICT)
            pipeline = state.case.composition._runtime._liveness_owner._pipeline
            inputs = pipeline.daily_evaluations._current_inputs[state.case.plan.symbol]
            day = inputs.series.bars[-1].trade_date
            native_daily = state.case.sdk.daily
            counts = {}

            def missing_prior(**kwargs):
                frame = native_daily(**kwargs)
                kept = frame.loc[frame["trade_date"].astype(str) != day.strftime("%Y%m%d")]
                counts.update(before=len(frame), after=len(kept), request=dict(kwargs))
                return kept.reset_index(drop=True)

            state.patch.setattr(state.case.sdk, "daily", missing_prior)
            prepared = await pipeline.prepare_daily_inputs(
                state.case.plan, state.case.clock.now(), day, inputs.minute_prefix
            )
            state.official_input_missing = True
            return {
                "removedTradeDate": day,
                "providerRows": counts,
                "preparedOfficialTradeDate": prepared.official_trade_date,
                "preparedSeriesLastDate": None
                if prepared.series is None
                else prepared.series.bars[-1].trade_date,
                "nativeDailyAdmissionPresent": pipeline._daily_source_current(
                    state.case.plan, state.case.clock.now()
                )
                is not None,
                "blockers": prepared.data_blockers,
            }

        @app.post(PREFIX + "/notification-close", dependencies=guards)
        async def notification_close(command: NextTarget):
            if (
                scenario != "notifications"
                or not state.notification_checks
                or state.notification_closed
            ):
                raise ApiError(ApiErrorCode.CONFLICT)
            state.case.composition._runtime._liveness_owner._dispatcher.begin_shutdown()
            state.notification_closed = True
            return state.inspect()

        @app.post(PREFIX + "/notification-expire", dependencies=guards)
        async def notification_expire(command: NextTarget):
            if (
                scenario != "notifications"
                or not state.notification_checks
                or state.notification_closed
            ):
                raise ApiError(ApiErrorCode.CONFLICT)
            service = state.case.composition._runtime._liveness_owner._notification_service
            state.case.clock.current = service.valid_until + timedelta(microseconds=1)
            state.notification_closed = True
            return state.inspect()

        @app.post(PREFIX + "/calendar-restore", dependencies=guards)
        async def calendar_restore(command: NextTarget):
            if (
                state.scenario != "automatic"
                or state.cycles != 1
                or state.calendar_backup is None
                or state.calendar_restored
            ):
                raise ApiError(ApiErrorCode.CONFLICT)
            with state.lifecycle._unit_of_work() as work:
                work.daily.session.add(TradingCalendar(**state.calendar_backup))
                work.commit()
            state.calendar_restored = True
            return {"calendarRow": state.calendar_backup, "inspection": state.inspect()}

        @app.get(PREFIX + "/manual-evidence", dependencies=guards)
        async def manual_evidence():
            if scenario != "manual-leaves":
                raise ApiError(ApiErrorCode.NOT_FOUND)
            pipeline = state.case.composition._runtime._liveness_owner._pipeline
            _, _, plans = pipeline.runtime_status_snapshot()
            proof = plans[0].completion
            identity = (
                None if proof is None else getattr(proof.input_stamp, "immutable_record_id", None)
            )
            consumed = pipeline.daily_evaluations._current_inputs.get(state.case.plan.symbol)
            alignment = None
            with state.lifecycle._unit_of_work() as work:
                head = work.daily.get("evaluation-head-" + state.case.plan.symbol)
                rows = work.daily.list(symbol=state.case.plan.symbol, kind="EVALUATION")
                evaluation = (
                    None
                    if head is None
                    else next(
                        (
                            row
                            for row in rows
                            if row["id"] != head["id"] and row["payload"] == head["payload"]
                        ),
                        None,
                    )
                )
                facts = work.daily.list(symbol=state.case.plan.symbol, kind="FACT")
                if consumed is not None and consumed.trading_calendar and head is not None:
                    from trade_plan_monitor.runtime.status_authority import (
                        _condition_sources,
                        _fingerprint,
                    )

                    calendar, minutes, bars = _condition_sources(
                        work.daily.session,
                        head["payload"],
                        consumed.trading_calendar[0].cal_date,
                        consumed.trading_calendar[-1].cal_date,
                    )
                    alignment = {
                        "consumedCalendarRows": len(consumed.trading_calendar),
                        "consumedClosedDays": sum(
                            not row.is_open for row in consumed.trading_calendar
                        ),
                        "consumedSessionRows": len(consumed.session_dates),
                        "sessionsMatchOnlyOpenDays": consumed.session_dates
                        == tuple(row.cal_date for row in consumed.trading_calendar if row.is_open),
                        "storedCalendarRows": len(calendar),
                        "storedClosedDays": sum(not row.is_open for row in calendar),
                        "calendarFingerprintMatches": _fingerprint(
                            "condition-calendar-v1", calendar
                        )
                        == _fingerprint("condition-calendar-v1", consumed.trading_calendar),
                        "minuteFingerprintMatches": _fingerprint("condition-minute-v1", minutes)
                        == _fingerprint("condition-minute-v1", consumed.minute_prefix),
                        "fiveMinuteFingerprintMatches": _fingerprint("condition-five-v1", bars)
                        == _fingerprint("condition-five-v1", consumed.five_minute_bars),
                    }
            return {
                "evaluationId": None if evaluation is None else evaluation["id"],
                "nativeCompletionRecordId": identity,
                "evaluation": None if evaluation is None else evaluation["payload"],
                "facts": facts,
                "prerequisiteReceipts": state.manual_inputs,
                "sourceAlignment": alignment,
            }

        @app.post(PREFIX + "/source-case", dependencies=guards)
        async def source_case(command: SourceCase, context: MutationContextDependency):
            if command.scenario in state.source_cases:
                return state.source_cases[command.scenario]
            path = "alert_rules[0].condition.price_fen"
            result = {"versionIds": [], "repairPath": path, "clauseId": None, "requirement": None}
            for index in range(1 if command.scenario == "repair" else 2):
                raw = state.case.plan.model_dump(mode="json")
                raw["version"] = 2 + index
                if index:
                    raw["alert_rules"][0]["condition"]["price_fen"] = 4500
                draft = load_daily_draft_json(json.dumps(raw))
                source, mapping = source_mapping(draft)
                clause = next(row for row in mapping.clauses if path in row.paths)
                if command.scenario == "repair":
                    mapping = mapping.model_copy(
                        update={
                            "clauses": tuple(
                                row.model_copy(
                                    update={
                                        "disposition": "CONTEXT",
                                        "paths": (),
                                        "semantic_role": "COMMENTARY",
                                        "reason": "Untrusted commentary proposal.",
                                    }
                                )
                                if row.clause_id == clause.clause_id
                                else row
                                for row in mapping.clauses
                            ),
                            "bindings": tuple(
                                binding for binding in mapping.bindings if binding.path != path
                            ),
                        }
                    )
                active = await state.lifecycle.get_plan_activation_state(symbol=draft.symbol)
                saved = await state.lifecycle.save_plan_draft(
                    command=PlanDraftCommand(
                        plan_json=daily_draft_json(draft),
                        source_text=source,
                        daily_mapping=mapping,
                        expected_revision=active.revision,
                    ),
                    context=context.model_copy(
                        update={
                            "idempotency_key": f"fixture-source-{command.scenario}-{index}",
                        }
                    ),
                )
                result["versionIds"].append(str(saved.id))
                if not index:
                    result.update(clauseId=clause.clause_id, requirement=clause.excerpt)
            state.source_cases[command.scenario] = result
            return result

        @app.post(PREFIX + "/shutdown", dependencies=guards)
        async def shutdown():
            if state.shutdown is not None:
                await state.shutdown()
            return {"shutdownRequested": state.shutdown is not None}

        for route in tuple(app.router.routes):
            if isinstance(route, LocalSpaRoute):
                app.router.routes.remove(route)
                app.router.routes.append(route)
        return app
    except BaseException:
        state.restore_boundaries()
        raise


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--scenario",
        choices=("automatic", "manual-leaves", "notifications", "official-wait"),
        default="automatic",
    )
    args = parser.parse_args()
    app = create_fixture_app(
        args.root, port=args.port, static_directory=REPOSITORY / "web/dist", scenario=args.scenario
    )
    state = app.state.readiness_fixture
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=args.port,
            log_level="warning",
        )
    )
    state.shutdown = lambda: _request_server_shutdown(server)
    try:
        server.run()
    finally:
        state.restore_boundaries()
    print(
        json.dumps(
            {
                "event": "READINESS_FIXTURE_CLOSED",
                "lifespanClosed": state.closed,
                "readOwnerOutstanding": state.case.composition.read_service.outstanding_work,
                "runtimeState": state.case.composition._runtime.progress_snapshot().state,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
