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

import pytest
from fastapi import Depends
from tests.browser.source_coverage_server import (
    DisabledAI,
    FixtureState,
    _loopback,
    _request_server_shutdown,
)

from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.errors import ApiError, ApiErrorCode
from trade_plan_monitor.web.origin_guard import LocalSpaRoute
from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle
from trade_plan_monitor.web.schemas import ApiValue

PREFIX = "/_test/plan-readiness"
REPOSITORY = Path(__file__).resolve().parents[2]


class NextTarget(ApiValue):
    """No caller-selected time, proof, source, result or configuration."""


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
            "cycles": self.cycles,
            "sdkCalls": len(self.case.sdk.calls),
            "externalAttempts": list(self.external_attempts),
            "storage": FixtureState(self.root, self.lifecycle).snapshot(),
        }

    def restore_boundaries(self):
        self.patch.undo()


def create_fixture_app(root: Path, *, port=8765, static_directory=None):
    root = root.resolve()
    if not root.is_relative_to(REPOSITORY / ".pytest_cache"):
        raise ValueError("Use a fresh project-local .pytest_cache directory")
    if root.is_symlink() or root.exists() and any(root.iterdir()):
        raise ValueError("A fresh isolated readiness directory is required")
    root.mkdir(parents=True, exist_ok=True)
    state = ReadinessFixture(root)
    try:
        state.guard_connections()
        # The reused fixture's scheduler imports neighboring test modules by
        # basename, as pytest does. Confine that lookup to this fixture lifetime.
        state.patch.syspath_prepend(str(REPOSITORY / "tests/integration"))
        from tests.integration.test_plan_readiness_profile_ownership import installed, start_current

        state.case = installed(root, state.patch, 2)
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
                    async with asyncio.timeout(30):
                        state.version = await start_current(state.case)
                        # Let the next native minute duty perform its real
                        # notification storage check after pending maintenance.
                        # The first duty's original 1us service expiry is retained.
                        await state.case.clock.drive(state.case.clock.now() + timedelta(minutes=1))
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
    args = parser.parse_args()
    app = create_fixture_app(args.root, port=args.port, static_directory=REPOSITORY / "web/dist")
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
