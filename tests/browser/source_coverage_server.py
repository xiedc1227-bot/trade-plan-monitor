"""Offline FIELD engineering cases, not natural-language extraction acceptance.

Only new temporary SQLite files are used. Saves, supplements, coverage, review
and activation are production operations; no provider or trading engine exists.
"""

import argparse
import json
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import Depends, Request
from pydantic import Field
from pydantic_core import to_json
from tests.integration.test_market_linkage_review import source_mapping
from tests.integration.test_source_treatment_review_api import literal_draft
from tests.integration.test_web_api import _runtime_health_payload
from tests.unit.test_source_coverage_baseline import _append_as_context, _baseline

from trade_plan_monitor.domain.daily_plan_validation import daily_draft_json
from trade_plan_monitor.runtime.health import RuntimeServiceStatus
from trade_plan_monitor.runtime.status_authority import RuntimeReadAuthority
from trade_plan_monitor.state.source_coverage_store import SourceCoverageStore
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.errors import ApiError, ApiErrorCode
from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle
from trade_plan_monitor.web.routers.ai import AIProviderPage, ConfiguredAIRuntimeView
from trade_plan_monitor.web.routers.health import RuntimeHealthResponse
from trade_plan_monitor.web.routers.plans import PlanDraftCommand
from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService
from trade_plan_monitor.web.runtime_status_websocket import RuntimeStatusEventStream
from trade_plan_monitor.web.schemas import ApiValue, MutationContextDependency
from trade_plan_monitor.web.source_coverage_read import read_source_coverage

PREFIX = "/_test/source-coverage"
TURNOVER = "Only buy when turnover exceeds 3 percent."
MARKUP = 'Only buy when <img src=x onerror="window.__sourceFixtureXss=1"> 😀 confirms the signal.'
NOW = datetime(2026, 10, 28, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
TABLES = (
    "plan_source",
    "plan_version",
    "plan_review_provenance",
    "daily_plan_record",
    "audit_log",
    "request_idempotency",
    "plan_activation_state",
    "active_plan",
    "source_coverage_input",
    "source_coverage_assessment",
    "source_coverage_review",
    "position_lot",
    "evaluation_ledger",
    "alert_event",
    "delivery_attempt",
    "monitor_event",
    "monitor_sequence",
)


class SetupCommand(ApiValue):
    scenario: Literal["complete", "mislabelled", "missing-cap", "xss-emoji", "source-version"]
    generation: int = Field(default=1, strict=True, ge=1, le=2)


class ReassessCommand(ApiValue):
    expected_revision: int = Field(strict=True, ge=1)


class NoIO:
    """The fixture has no external capability; attempted use fails immediately."""

    def __init__(self):
        self.attempts = []

    def acquire_provider(self):
        self._deny("provider")

    def acquire_market_data(self):
        self._deny("market")

    def send_notification(self):
        self._deny("notification")

    def _deny(self, kind):
        self.attempts.append(kind)
        raise AssertionError("External I/O is prohibited in the source fixture")


class DisabledAI:
    async def get_configured_ai(self):
        return ConfiguredAIRuntimeView(
            provider_id="00000000-0000-4000-8000-0000000000d5",
            display_name="离线来源审核夹具（提取不可用）",
            base_url="https://example.invalid",
            model="offline-disabled",
            configured=False,
            enabled=False,
            max_input_chars=50000,
            max_output_tokens=4096,
        )

    async def list_ai_providers(self, *, offset, limit):
        return AIProviderPage(items=(), offset=offset, limit=limit, total=0)


def _health(now):
    value = _runtime_health_payload()
    value.update(
        status="STOPPED",
        readOnly=False,
        observedAt=now,
        startedAt=now,
        stoppedAt=now,
        lastCompletedMinute=None,
        lastCompletedMinuteAgeSeconds=None,
        latestEvaluationAt=None,
        latestEvaluationAgeSeconds=None,
        providers=[],
        nextPollAt=None,
    )
    value["executor"].update(activeCount=0, waitingCount=0)
    value["database"].update(
        status="UNVERIFIED", walStatus="UNVERIFIED", lastCheckpointAt=None, lastBackupAt=None
    )
    value["delivery"].update(status="UNVERIFIED")
    return RuntimeHealthResponse.model_validate_json(to_json(value))


class FixtureState:
    def __init__(self, root, lifecycle):
        self.root, self.lifecycle = root, lifecycle
        self.now = NOW
        self.created = {}
        self.no_io = NoIO()
        self.shutdown = None

    def snapshot(self):
        with self.lifecycle._session_factory() as session:
            connection = session.connection()
            result = {}
            for table in TABLES:
                rows = sorted(
                    tuple(row) for row in connection.exec_driver_sql(f'SELECT * FROM "{table}"')
                )
                result[table] = {
                    "count": len(rows),
                    "sha256": sha256(
                        json.dumps(rows, ensure_ascii=False, default=str).encode()
                    ).hexdigest(),
                }
            result["dailyKinds"] = dict(
                connection.exec_driver_sql(
                    "SELECT kind, COUNT(*) FROM daily_plan_record GROUP BY kind"
                ).all()
            )
            return result


def _payload(command):
    # These helpers DEFINE explicit synthetic FIELD sources, not an AI oracle.
    draft = literal_draft(complete=True) if command.scenario == "missing-cap" else _baseline()[0]
    raw = draft.model_dump(mode="json")
    raw.update(plan_id="source-browser-" + command.scenario, version=command.generation)
    if command.scenario == "missing-cap":
        raw["position"]["max_qty"] = None
    if command.scenario == "source-version":
        raw["position"]["limit"]["capital_policy"]["cap_fen"] += command.generation * 1000
    draft = type(draft).model_validate(raw)
    source, mapping = source_mapping(draft)
    if command.scenario == "missing-cap":
        # semantic_values omits this absent parameter. Preserve its explicit
        # original null rather than inventing a later provider value. The absent
        # candidate leaf cannot yet be a mapped path; the core still sees null.
        source, mapping = _append_as_context(
            source,
            mapping,
            "position.max_qty = null",
            semantic_role="COMMENTARY",
            misclassification=dict(
                disposition="CONTEXT",
                paths=[],
                reason="The original maximum is explicitly missing; no value is supplied.",
            ),
        )
    if command.scenario in {"mislabelled", "xss-emoji"}:
        source, mapping = _append_as_context(
            source,
            mapping,
            TURNOVER if command.scenario == "mislabelled" else MARKUP,
            semantic_role="COMMENTARY",
            misclassification=dict(
                disposition="CONTEXT", paths=[], reason="Proposed background is not authority."
            ),
        )
    return draft, source, mapping


def _loopback(request: Request):
    if (
        request.client is None
        or request.client.host not in {"127.0.0.1", "::1"}
        or request.url.hostname not in {"127.0.0.1", "::1"}
    ):
        raise ApiError(ApiErrorCode.FORBIDDEN)


def create_fixture_app(root: Path, *, port=8765, static_directory=None):
    """Construct without I/O; the real lifespan owns a fresh temporary database."""
    root = root.resolve()
    database = root / "source-coverage.sqlite3"
    if database.exists() or database.is_symlink():
        raise ValueError("A fresh temporary source-coverage database is required")
    state = FixtureState(root, None)
    lifecycle = PersistentPlanWebLifecycle(database_path=database, clock=lambda: state.now)
    state.lifecycle = lifecycle
    reader = RuntimeStatusReadService(
        lambda: lifecycle._session_factory(),
        lambda: RuntimeReadAuthority(
            token="fixture-stopped",
            lifecycle="STOPPED",
            progress=None,
            health=_health(state.now),
            owner_absent=True,
        ),
        clock=lambda: state.now,
    )

    class StoppedRuntime:
        async def start(self):
            return SimpleNamespace(status=RuntimeServiceStatus.STOPPED, read_only=False)

        async def stop(self):
            await reader.stop()

    app = create_app(
        runtime_factory=StoppedRuntime,
        plan_lifecycle_factory=lambda: lifecycle,
        ai_service=DisabledAI(),
        read_service=reader,
        monitor_contract_version=2,
        websocket_service=RuntimeStatusEventStream(
            unit_of_work_factory=lifecycle._unit_of_work,
            read_service=reader,
            heartbeat_interval_seconds=1,
        ),
        bind_port=port,
        static_directory=static_directory,
    )
    app.state.source_fixture = state
    app.state.source_fixture_lifecycle = lifecycle
    guards = [Depends(_loopback)]

    @app.get(PREFIX + "/isolation", dependencies=guards)
    def isolation():
        return {
            "temporary": True,
            "database": str(database),
            "root": str(root),
            "provider": "DISABLED_NO_IO",
            "createdVersionIds": list(state.created.values()),
        }

    @app.post(PREFIX + "/setup", dependencies=guards)
    async def setup(command: SetupCommand, context: MutationContextDependency):
        key = (command.scenario, command.generation)
        identity = state.created.get(key)
        if identity is None:
            draft, source, mapping = _payload(command)
            active = await lifecycle.get_plan_activation_state(symbol=draft.symbol)
            saved = await lifecycle.save_plan_draft(
                command=PlanDraftCommand(
                    plan_json=daily_draft_json(draft),
                    source_text=source,
                    daily_mapping=mapping,
                    expected_revision=0 if active is None else active.revision,
                ),
                context=context,
            )
            identity = state.created[key] = str(saved.id)
        return {
            "planVersionId": identity,
            "planUrl": "/plans/" + identity,
            "scenario": command.scenario,
            "generation": command.generation,
        }

    @app.get(PREFIX + "/inspect", dependencies=guards)
    def inspect():
        return {"storage": state.snapshot(), "externalAttempts": list(state.no_io.attempts)}

    @app.post(PREFIX + "/reassess/{version_id}", dependencies=guards)
    def reassess(version_id: str, command: ReassessCommand):
        if version_id not in state.created.values():
            raise ApiError(ApiErrorCode.NOT_FOUND)
        with lifecycle._unit_of_work() as work, work.daily.session.no_autoflush:
            fresh = read_source_coverage(work, version_id)
            if fresh is None or fresh.stored is None:
                raise ApiError(ApiErrorCode.CONFLICT)
            old = fresh.stored
            if old.revision != command.expected_revision:
                raise ApiError(ApiErrorCode.CONFLICT)
            now = state.now + timedelta(seconds=1)
            newer = SourceCoverageStore(work.daily.session).append(
                version_id,
                old.assessment,
                inputs=old.inputs,
                expected_revision=old.revision,
                command_id=f"browser-reassess-{version_id}-{old.revision}",
                now=now,
            )
            work.commit()
            state.now = now
        return {"coverageRevision": newer.revision, "coverageBundleHash": newer.evidence_hash}

    @app.post(PREFIX + "/shutdown", dependencies=guards)
    def shutdown():
        if state.shutdown is not None:
            state.shutdown()
        return {"shutdownRequested": state.shutdown is not None}

    return app


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="tpm-source-coverage-browser-") as directory:
        app = create_fixture_app(
            Path(directory),
            port=args.port,
            static_directory=Path(__file__).resolve().parents[2] / "web/dist",
        )
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning")
        )
        app.state.source_fixture.shutdown = lambda: setattr(server, "should_exit", True)
        server.run()


if __name__ == "__main__":
    main()
