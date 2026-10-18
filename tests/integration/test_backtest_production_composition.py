"""Production wiring and ownership tests for the focused backtest API slices."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from datetime import date
from functools import partial
from hashlib import sha256
from pathlib import Path
from threading import Event, Thread

import pytest
from fastapi.testclient import TestClient

import trade_plan_monitor.backtest.composition as backtest_composition
import trade_plan_monitor.backtest.cursor_key_security as cursor_key_security
import trade_plan_monitor.backtest.jobs.repository as job_repository
from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.composition import (
    BacktestComposition,
    _load_or_create_cursor_key,
    _read_cursor_key,
    create_backtest_composition_factory,
)
from trade_plan_monitor.backtest.cursor_key_security import (
    windows_cursor_key_acl_is_owner_only,
)
from trade_plan_monitor.backtest.dataset import DatasetManifest, DatasetScope
from trade_plan_monitor.backtest.jobs import BacktestJobCoordinator
from trade_plan_monitor.backtest.results import BacktestResultStore
from trade_plan_monitor.backtest.service_lifecycle import BacktestServiceUnavailable
from trade_plan_monitor.domain.plan_codec import (
    dump_plan_json,
    load_plan_json,
    load_plan_yaml,
)
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.market_data.historical_provider import HistoricalMinuteProfile
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.backtest_export import PreparedBacktestExport
from trade_plan_monitor.web.backtest_schemas import (
    BacktestDatasetVerificationCommand,
    BacktestRunCommand,
)
from trade_plan_monitor.web.errors import ApiError
from trade_plan_monitor.web.routers.backtest_jobs import BacktestJobCancellationCommand
from trade_plan_monitor.web.schemas import ApiErrorCode, MutationContext

_PLAN_VERSION_ID = "4c623c8c-ca26-4cd8-8cb2-08cd5e61be93"
_BACKTEST_PATHS = {
    "/api/v1/backtest-data-syncs",
    "/api/v1/backtest-dataset-verifications",
    "/api/v1/backtest-datasets",
    "/api/v1/backtest-datasets/{dataset_hash}",
    "/api/v1/backtest-jobs",
    "/api/v1/backtest-jobs/{job_id}",
    "/api/v1/backtest-job-cancellations",
    "/api/v1/backtest-runs",
    "/api/v1/backtest-runs/{run_id}",
    "/api/v1/backtest-runs/{run_id}/fills",
    "/api/v1/backtest-runs/{run_id}/details",
    "/api/v1/backtest-runs/{run_id}/equity-series",
    "/api/v1/backtest-runs/{run_id}/exports/{export_kind}",
}


class _Runtime:
    def __init__(self, events: list[str], *, fail_start: bool = False) -> None:
        self._events = events
        self._fail_start = fail_start

    async def start(self) -> dict[str, str]:
        self._events.append("runtime.start")
        if self._fail_start:
            raise RuntimeError("runtime start failed")
        return {"status": "READY"}

    async def stop(self) -> None:
        self._events.append("runtime.stop")


class _Coordinator:
    def __init__(self, events: list[str], *, fail_start: bool = False) -> None:
        self._events = events
        self._fail_start = fail_start

    async def start(self) -> None:
        self._events.append("backtest.start")
        if self._fail_start:
            raise RuntimeError("backtest start failed")

    async def shutdown(self) -> None:
        self._events.append("backtest.stop")


class _PlanSnapshotReader:
    def __init__(self) -> None:
        plan_path = Path("config/plans/003043.SZ.sample.yaml")
        plan = load_plan_yaml(plan_path.read_text(encoding="utf-8"))
        self._payload = {
            "id": _PLAN_VERSION_ID,
            "planId": plan.plan_id,
            "version": plan.version,
            "symbol": plan.symbol,
            "planHash": plan_sha256(plan),
            "status": "DRAFT",
            "planJson": dump_plan_json(plan),
            "sourceText": "华亚智能结构化交易计划",
            "reviewIssues": [],
            "validationIssues": [
                {
                    "code": "LEGACY_PLANS_REQUIRE_REVIEW",
                    "path": "draft",
                    "severity": "WARNING",
                    "activationBlocking": True,
                    "message": "Frozen historical plan is available only for isolated backtests.",
                }
            ],
            "obsoleteReason": "LEGACY_PLANS_REQUIRE_REVIEW",
            "canActivate": False,
            "revision": 0,
            "createdAt": "2026-08-29T09:30:00.000000+08:00",
        }
        self.calls: list[str] = []

    async def get_plan_version(self, *, version_id: str) -> object | None:
        self.calls.append(version_id)
        return self._payload if version_id == _PLAN_VERSION_ID else None


class _InvalidBacktestLifecycle:
    read_service = object()
    operation_service = object()

    async def start(self) -> None:
        raise AssertionError("invalid lifecycle must be rejected before startup")


def _run_command(dataset_hash: str) -> BacktestRunCommand:
    return BacktestRunCommand.model_validate(
        {
            "planVersionId": _PLAN_VERSION_ID,
            "datasetHash": dataset_hash,
            "initialCashFen": 1_000_000,
            "initialLots": [],
            "executionConfig": {
                "commissionRate": "0.0003",
                "minimumCommissionFen": 500,
                "stampDutyRate": "0.0005",
                "transferFeeRate": "0.00001",
                "buySlippageBps": "1.25",
                "sellSlippageBps": "2",
            },
            "eventRiskAssumption": "NO_EVENT_RISK",
        }
    )


def _verification_command() -> BacktestDatasetVerificationCommand:
    return BacktestDatasetVerificationCommand.model_validate(
        {
            "scope": {
                "symbols": ["003043.SZ"],
                "start": "2026-08-20",
                "end": "2026-08-21",
                "warmupStart": "2026-08-20",
                "historicalProfile": "TUSHARE_STK_MINS_241_END_V1",
                "adjustmentPolicy": "NONE",
            }
        }
    )


def _insert_empty_dataset(
    database_path: Path,
    *,
    symbols: tuple[str, ...] = ("003043.SZ",),
) -> str:
    scope = DatasetScope(
        symbols=symbols,
        start=date(2026, 8, 20),
        end=date(2026, 8, 21),
        warmup_start=date(2026, 8, 20),
        historical_profile=HistoricalMinuteProfile.TUSHARE_STK_MINS_241_END_V1,
    )
    identity = {
        "schema_version": "backtest-dataset-v1",
        "scope": scope.model_dump(mode="python", round_trip=True),
        "items": [],
    }
    dataset_hash = sha256(canonical_json(identity).encode("utf-8")).hexdigest()
    manifest = DatasetManifest(dataset_hash=dataset_hash, scope=scope, items=())
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO market_dataset (dataset_hash, manifest_json, created_at) VALUES (?, ?, ?)",
            (
                dataset_hash,
                canonical_json(manifest.model_dump(mode="python", round_trip=True)),
                "2026-08-29T09:00:00.000000+08:00",
            ),
        )
        connection.commit()
    return dataset_hash


def test_create_app_installs_backtest_routes_without_calling_lifecycle_factory() -> None:
    calls: list[str] = []

    def backtest_factory() -> BacktestComposition:
        calls.append("factory")
        return BacktestComposition(
            read_service=object(),
            operation_service=object(),
            coordinator=_Coordinator([]),
        )

    app = create_app(backtest_lifecycle_factory=backtest_factory)
    document = app.openapi()

    assert _BACKTEST_PATHS <= document["paths"].keys()
    assert calls == []


def test_installed_backtest_routes_fail_closed_without_services() -> None:
    response = TestClient(create_app(), raise_server_exceptions=False).get(
        "/api/v1/backtest-datasets",
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_composite_lifespan_installs_services_and_unwinds_in_reverse_order() -> None:
    events: list[str] = []
    read_service = object()
    operation_service = object()
    composition = BacktestComposition(
        read_service=read_service,
        operation_service=operation_service,
        coordinator=_Coordinator(events),
    )
    app = create_app(
        runtime_factory=lambda: _Runtime(events),
        backtest_lifecycle_factory=lambda: composition,
    )

    with TestClient(app) as client:
        assert events == ["runtime.start"]
        assert not hasattr(app.state, "backtest_read_service")
        prepared = client.portal.call(partial(app.state.backtest_lifecycle.ensure, execution=True))
        assert prepared.read_service is read_service
        assert prepared.operation_service is operation_service
        assert events == ["runtime.start", "backtest.start"]

    assert events == [
        "runtime.start",
        "backtest.start",
        "backtest.stop",
        "runtime.stop",
    ]
    assert not hasattr(app.state, "backtest_read_service")
    assert not hasattr(app.state, "backtest_operation_service")


def test_composite_lifespan_cleans_both_components_after_backtest_start_failure() -> None:
    events: list[str] = []
    composition = BacktestComposition(
        read_service=object(),
        operation_service=object(),
        coordinator=_Coordinator(events, fail_start=True),
    )
    app = create_app(
        runtime_factory=lambda: _Runtime(events),
        backtest_lifecycle_factory=lambda: composition,
    )

    with TestClient(app) as client:
        assert events == ["runtime.start"]
        with pytest.raises(BacktestServiceUnavailable):
            client.portal.call(partial(app.state.backtest_lifecycle.ensure, execution=True))
        assert events == ["runtime.start", "backtest.start"]
        assert client.get("/openapi.json").status_code == 200

    assert events == [
        "runtime.start",
        "backtest.start",
        "backtest.stop",
        "runtime.stop",
    ]
    assert not hasattr(app.state, "backtest_read_service")
    assert not hasattr(app.state, "backtest_operation_service")


def test_composite_lifespan_preserves_direct_services_and_original_validation_error() -> None:
    events: list[str] = []
    read_service = object()
    operation_service = object()
    app = create_app(
        runtime_factory=lambda: _Runtime(events),
        backtest_read_service=read_service,
        backtest_operation_service=operation_service,
    )

    with TestClient(app):
        pass

    assert app.state.backtest_read_service is read_service
    assert app.state.backtest_operation_service is operation_service
    assert events == ["runtime.start", "runtime.stop"]

    invalid_app = create_app(
        runtime_factory=lambda: _Runtime(events),
        backtest_lifecycle_factory=_InvalidBacktestLifecycle,
    )
    with TestClient(invalid_app) as client:
        assert client.get("/api/v1/backtest-datasets").status_code == 503
        assert events[-1] == "runtime.start"
    assert events[-2:] == ["runtime.start", "runtime.stop"]


@pytest.mark.parametrize("empty_wal_remnants", [False, True])
def test_real_production_composition_starts_and_stops_one_coordinator(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    empty_wal_remnants: bool,
) -> None:
    calls = {"start": 0, "shutdown": 0}
    original_start = BacktestJobCoordinator.start
    original_shutdown = BacktestJobCoordinator.shutdown

    async def counted_start(coordinator: BacktestJobCoordinator) -> None:
        calls["start"] += 1
        await original_start(coordinator)

    async def counted_shutdown(coordinator: BacktestJobCoordinator) -> None:
        calls["shutdown"] += 1
        await original_shutdown(coordinator)

    monkeypatch.setattr(BacktestJobCoordinator, "start", counted_start)
    monkeypatch.setattr(BacktestJobCoordinator, "shutdown", counted_shutdown)
    market_database = tmp_path / "market.sqlite3"
    results_database = tmp_path / "results.sqlite3"
    cursor_key_path = tmp_path / "cursor.key"
    if empty_wal_remnants:
        backtest_composition.BacktestMarketStore(market_database)
        job_repository.BacktestJobRepository(results_database)
        for database in (market_database, results_database):
            Path(f"{database}-wal").write_bytes(b"")
            Path(f"{database}-shm").write_bytes(bytes(32_768))
    factory = create_backtest_composition_factory(
        config_path=Path("config/app.yaml"),
        plan_snapshot_reader=_PlanSnapshotReader(),
        market_database=market_database,
        results_database=results_database,
        cursor_key_path=cursor_key_path,
    )
    app = create_app(
        runtime_factory=lambda: _Runtime([]),
        backtest_lifecycle_factory=factory,
    )

    with TestClient(app) as client:
        assert calls == {"start": 0, "shutdown": 0}
        assert client.get("/api/v1/backtest-datasets").status_code == 200
        assert market_database.is_file()
        assert results_database.is_file()
        assert cursor_key_path.is_file()
        for database in (market_database, results_database):
            assert not Path(f"{database}-wal").exists()
            assert not Path(f"{database}-shm").exists()
        assert calls == {"start": 0, "shutdown": 0}
        client.portal.call(partial(app.state.backtest_lifecycle.ensure, execution=True))
        assert calls == {"start": 1, "shutdown": 0}

    assert calls == {"start": 1, "shutdown": 1}


def test_production_coverage_keeps_stock_only_plan_not_required(tmp_path) -> None:
    market_database = tmp_path / "market.sqlite3"
    composition = create_backtest_composition_factory(
        config_path=Path("config/app.yaml"),
        plan_snapshot_reader=_PlanSnapshotReader(),
        market_database=market_database,
        results_database=tmp_path / "results.sqlite3",
        cursor_key_path=tmp_path / "cursor.key",
    )()
    dataset_hash = _insert_empty_dataset(market_database)

    coverage = asyncio.run(
        composition.read_service.get_reference_market_coverage(
            dataset_hash=dataset_hash,
            plan_version_id=_PLAN_VERSION_ID,
        )
    )

    assert coverage.required is False
    assert coverage.coverage_status == "NOT_REQUIRED"
    assert coverage.condition_paths == ()
    assert coverage.blockers == ()
    assert coverage.binding.index_code.value == "399001.SZ"
    asyncio.run(composition.stop())


@pytest.mark.skipif(os.name != "nt", reason="requires Windows file security APIs")
def test_cursor_key_uses_one_protected_owner_only_windows_acl(tmp_path) -> None:
    cursor_key_path = tmp_path / "cursor.key"

    key = _load_or_create_cursor_key(cursor_key_path)

    assert len(key) == 32
    assert windows_cursor_key_acl_is_owner_only(cursor_key_path)
    assert _read_cursor_key(cursor_key_path) == key
    assert windows_cursor_key_acl_is_owner_only(cursor_key_path)


@pytest.mark.skipif(os.name != "nt", reason="requires Windows file security APIs")
def test_cursor_key_creation_does_not_expose_secret_to_pre_acl_handle(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor_key_path = tmp_path / "cursor.key"
    verified_before_write: list[bool] = []
    original_verify = cursor_key_security._windows_handle_acl_is_owner_only
    original_write = cursor_key_security._write_windows_key

    def record_verified_acl(handle, advapi32, kernel32) -> bool:
        verified = original_verify(handle, advapi32, kernel32)
        verified_before_write.append(verified)
        return verified

    def require_verified_before_write(handle, key, kernel32) -> None:
        assert verified_before_write == [True]
        original_write(handle, key, kernel32)

    monkeypatch.setattr(
        cursor_key_security,
        "_windows_handle_acl_is_owner_only",
        record_verified_acl,
    )
    monkeypatch.setattr(cursor_key_security, "_write_windows_key", require_verified_before_write)

    key = _load_or_create_cursor_key(cursor_key_path)

    assert len(key) == 32
    assert verified_before_write == [True]


@pytest.mark.skipif(os.name != "nt", reason="requires Windows file security APIs")
def test_cursor_key_read_stays_bound_to_the_validated_file(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor_key_path = tmp_path / "cursor.key"
    original_key = b"o" * 32
    cursor_key_security.create_cursor_key_file(cursor_key_path, original_key)
    blocked_replacement: list[bool] = []
    original_read = cursor_key_security._read_windows_key_bytes

    def attempt_replace_while_handle_is_exclusive(handle, kernel32) -> bytes:
        replacement_path = tmp_path / "replacement.key"
        replacement_path.write_bytes(b"a" * 32)
        try:
            replacement_path.replace(cursor_key_path)
        except PermissionError:
            blocked_replacement.append(True)
        else:
            blocked_replacement.append(False)
        return original_read(handle, kernel32)

    monkeypatch.setattr(
        cursor_key_security,
        "_read_windows_key_bytes",
        attempt_replace_while_handle_is_exclusive,
    )

    assert _read_cursor_key(cursor_key_path) == original_key
    assert blocked_replacement == [True]


@pytest.mark.skipif(os.name != "nt", reason="requires Windows file security APIs")
def test_cursor_key_rejects_exposed_windows_acl_without_reusing_or_repairing_it(
    tmp_path,
) -> None:
    cursor_key_path = tmp_path / "cursor.key"
    exposed_key = b"e" * 32
    cursor_key_path.write_bytes(exposed_key)

    assert not windows_cursor_key_acl_is_owner_only(cursor_key_path)
    with pytest.raises(PermissionError, match="ACL is not owner-only"):
        _read_cursor_key(cursor_key_path)

    assert cursor_key_path.read_bytes() == exposed_key
    assert not windows_cursor_key_acl_is_owner_only(cursor_key_path)


@pytest.mark.skipif(os.name != "nt", reason="requires Windows file security APIs")
def test_cursor_key_read_retries_a_concurrent_exclusive_windows_creator(tmp_path) -> None:
    cursor_key_path = tmp_path / "cursor.key"
    key = b"c" * 32
    cursor_key_security.create_cursor_key_file(cursor_key_path, key)
    _, kernel32 = cursor_key_security._windows_libraries()
    handle = cursor_key_security._open_windows_file(
        cursor_key_path,
        desired_access=(cursor_key_security._GENERIC_READ | cursor_key_security._READ_CONTROL),
        creation_disposition=cursor_key_security._OPEN_EXISTING,
    )
    released = Event()

    def release_creator_handle() -> None:
        released.wait(0.05)
        cursor_key_security._close_windows_handle(handle, kernel32)

    releaser = Thread(target=release_creator_handle, name="cursor-key-test-releaser")
    releaser.start()
    try:
        assert cursor_key_security.read_cursor_key_file(cursor_key_path) == key
    finally:
        released.set()
        releaser.join(timeout=1.0)

    assert not releaser.is_alive()


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX ownership semantics")
def test_cursor_key_rejects_foreign_posix_owner_before_use(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor_key_path = tmp_path / "cursor.key"
    cursor_key_path.write_bytes(b"p" * 32)
    cursor_key_path.chmod(0o600)
    original_fstat = cursor_key_security.os.fstat

    class _ForeignMetadata:
        def __init__(self, metadata) -> None:
            self.st_mode = metadata.st_mode
            self.st_size = metadata.st_size
            self.st_uid = cursor_key_security.os.geteuid() + 1

    monkeypatch.setattr(
        cursor_key_security.os,
        "fstat",
        lambda descriptor: _ForeignMetadata(original_fstat(descriptor)),
    )

    with pytest.raises(PermissionError, match="not owned by the current user"):
        cursor_key_security.read_cursor_key_file(cursor_key_path)


def test_cursor_key_fails_closed_when_owner_only_permissions_cannot_be_applied(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    new_key_path = tmp_path / "new-cursor.key"
    existing_key_path = tmp_path / "existing-cursor.key"
    existing_key_path.write_bytes(b"k" * 32)

    def reject_create(_path: Path, _key: bytes) -> None:
        raise PermissionError("owner-only permissions unavailable")

    def reject_read(_path: Path) -> bytes:
        raise PermissionError("owner-only permissions unavailable")

    monkeypatch.setattr(backtest_composition, "create_cursor_key_file", reject_create)
    monkeypatch.setattr(backtest_composition, "read_cursor_key_file", reject_read)

    with pytest.raises(PermissionError, match="owner-only permissions unavailable"):
        _load_or_create_cursor_key(new_key_path)
    with pytest.raises(PermissionError, match="owner-only permissions unavailable"):
        _read_cursor_key(existing_key_path)

    assert not new_key_path.exists()
    assert existing_key_path.read_bytes() == b"k" * 32


def test_production_busy_operation_returns_conflict(tmp_path) -> None:
    composition = create_backtest_composition_factory(
        config_path=Path("config/app.yaml"),
        plan_snapshot_reader=None,
        market_database=tmp_path / "market.sqlite3",
        results_database=tmp_path / "results.sqlite3",
        cursor_key_path=tmp_path / "cursor.key",
    )()
    context = MutationContext(
        idempotency_key="queue-full-intent",
        request_id="5" * 32,
    )

    async def scenario() -> ApiError:
        from trade_plan_monitor.backtest.jobs import DatasetVerifyJobRequest
        composition.operation_service._repository.submit(
            DatasetVerifyJobRequest(
                scope=backtest_composition._scope_request(_verification_command().scope).model_copy(
                    update={"symbols": ("601021.SH",)}
                )
            ), "pending",
        )
        with pytest.raises(ApiError) as raised:
            await composition.operation_service.submit_dataset_verification(
                command=_verification_command(),
                context=context,
            )
        await composition.stop()
        return raised.value

    error = asyncio.run(scenario())

    assert error.code is ApiErrorCode.CONFLICT
    assert error.retry_after_seconds is None


def test_production_read_waits_for_overlap_without_starting_execution(tmp_path) -> None:
    composition = create_backtest_composition_factory(
        config_path=Path("config/app.yaml"), plan_snapshot_reader=None,
        market_database=tmp_path / "market.sqlite3", results_database=tmp_path / "results.sqlite3",
        cursor_key_path=tmp_path / "cursor.key",
    )()
    entered, release = Event(), Event()

    def slow_metadata():
        entered.set()
        assert release.wait(2)

    async def scenario():
        service = composition.read_service
        occupied = asyncio.create_task(service._run_sync(slow_metadata))
        try:
            while not entered.is_set():
                await asyncio.sleep(0)
            reads = [
                asyncio.create_task(service.get_job(job_id=f"missing-{index}"))
                for index in range(4)
            ]
            await asyncio.sleep(0)
            assert not any(read.done() for read in reads)
            release.set()
            await occupied
            assert await asyncio.gather(*reads) == [None] * 4
            assert not composition.authorized_job_ids
        finally:
            release.set()
            await composition.stop()
    asyncio.run(scenario())


def test_production_mutations_fail_closed_after_coordinator_failure(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    composition = create_backtest_composition_factory(
        config_path=Path("config/app.yaml"),
        plan_snapshot_reader=None,
        market_database=tmp_path / "market.sqlite3",
        results_database=tmp_path / "results.sqlite3",
        cursor_key_path=tmp_path / "cursor.key",
    )()

    def fail_health_check() -> None:
        raise RuntimeError("coordinator failed")

    monkeypatch.setattr(composition._coordinator, "raise_if_failed", fail_health_check)

    async def scenario() -> ApiError:
        with pytest.raises(ApiError) as raised:
            await composition.operation_service.submit_dataset_verification(
                command=_verification_command(),
                context=MutationContext(
                    idempotency_key="failed-coordinator-intent",
                    request_id="8" * 32,
                ),
            )
        await composition.stop()
        return raised.value

    error = asyncio.run(scenario())

    assert error.code is ApiErrorCode.SERVICE_UNAVAILABLE
    assert composition.operation_service._repository.list_jobs() == ()


def test_production_fill_export_uses_the_public_v2_schema_version(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(
        BacktestResultStore,
        "get_result_run",
        lambda _store, _run_id: SimpleNamespace(summary=SimpleNamespace(formula_versions={
            "report": "backtest-report-v1"})),
    )
    composition = create_backtest_composition_factory(
        config_path=Path("config/app.yaml"),
        plan_snapshot_reader=None,
        market_database=tmp_path / "market.sqlite3",
        results_database=tmp_path / "results.sqlite3",
        cursor_key_path=tmp_path / "cursor.key",
    )()

    async def scenario() -> PreparedBacktestExport | None:
        prepared = await composition.read_service.prepare_export(
            run_id="a" * 64,
            export_kind="FILLS_CSV",
            cancelled=lambda: False,
        )
        await composition.stop()
        return prepared

    prepared = asyncio.run(scenario())

    assert prepared is not None
    assert prepared.schema_version == "backtest-simulated-fills-v2"


def test_production_factory_is_lazy_and_run_replay_reuses_one_plan_snapshot(tmp_path) -> None:
    reader = _PlanSnapshotReader()
    market_database = tmp_path / "market.sqlite3"
    results_database = tmp_path / "results.sqlite3"
    cursor_key_path = tmp_path / "cursor.key"
    factory = create_backtest_composition_factory(
        config_path=Path("config/app.yaml"),
        plan_snapshot_reader=reader,
        market_database=market_database,
        results_database=results_database,
        cursor_key_path=cursor_key_path,
    )

    assert not market_database.exists()
    assert not results_database.exists()
    assert not cursor_key_path.exists()

    composition = factory()
    dataset_hash = _insert_empty_dataset(market_database)
    context = MutationContext(
        idempotency_key="same-run-intent",
        request_id="0" * 32,
    )

    async def scenario() -> tuple[object, object, object]:
        first = await composition.operation_service.submit_run(
            command=_run_command(dataset_hash),
            context=context,
        )
        replay = await composition.operation_service.submit_run(
            command=_run_command(dataset_hash),
            context=context,
        )
        job = await composition.read_service.get_job(job_id=first.receipt.job_id)
        await composition.stop()
        return first, replay, job

    first, replay, job = asyncio.run(scenario())

    assert first == replay
    assert job.job_id == first.receipt.job_id
    assert job.status == "QUEUED"
    assert reader.calls == [_PLAN_VERSION_ID]
    assert market_database.is_file()
    assert results_database.is_file()
    assert len(cursor_key_path.read_bytes()) == 32


def test_run_submission_freezes_plan_before_receipt_and_later_versions_do_not_rewrite_it(
    tmp_path,
) -> None:
    reader = _PlanSnapshotReader()
    market_database = tmp_path / "market.sqlite3"
    results_database = tmp_path / "results.sqlite3"
    composition = create_backtest_composition_factory(
        config_path=Path("config/app.yaml"),
        plan_snapshot_reader=reader,
        market_database=market_database,
        results_database=results_database,
        cursor_key_path=tmp_path / "cursor.key",
    )()
    dataset_hash = _insert_empty_dataset(market_database)
    context = MutationContext(
        idempotency_key="frozen-plan-intent",
        request_id="9" * 32,
    )
    original_payload = dict(reader._payload)

    async def scenario() -> tuple[object, object]:
        first = await composition.operation_service.submit_run(
            command=_run_command(dataset_hash),
            context=context,
        )
        successor_plan = load_plan_json(str(reader._payload["planJson"])).model_copy(
            update={"name": "华亚智能后续修改版", "version": 2}
        )
        reader._payload = {
            **reader._payload,
            "id": "58d27696-bffc-49b2-89f8-c34ec20f9806",
            "planHash": plan_sha256(successor_plan),
            "planJson": dump_plan_json(successor_plan),
            "version": successor_plan.version,
        }
        replay = await composition.operation_service.submit_run(
            command=_run_command(dataset_hash),
            context=context,
        )
        await composition.stop()
        return first, replay

    first, replay = asyncio.run(scenario())
    with sqlite3.connect(results_database) as connection:
        request_json = str(
            connection.execute(
                "SELECT request_json FROM backtest_job WHERE job_id = ?",
                (first.receipt.job_id,),
            ).fetchone()[0]
        )
    frozen_input = json.loads(request_json)["runInput"]

    assert replay == first
    assert reader.calls == [_PLAN_VERSION_ID]
    assert frozen_input["plan_version_id"] == _PLAN_VERSION_ID
    assert frozen_input["plan_sha256"] == original_payload["planHash"]
    assert frozen_input["plan_snapshot"] == json.loads(str(original_payload["planJson"]))
    assert frozen_input["plan_snapshot"] != json.loads(str(reader._payload["planJson"]))


def test_run_submission_accepts_a_verified_multi_symbol_dataset_containing_plan_symbol(
    tmp_path,
) -> None:
    reader = _PlanSnapshotReader()
    market_database = tmp_path / "market.sqlite3"
    composition = create_backtest_composition_factory(
        config_path=Path("config/app.yaml"),
        plan_snapshot_reader=reader,
        market_database=market_database,
        results_database=tmp_path / "results.sqlite3",
        cursor_key_path=tmp_path / "cursor.key",
    )()
    dataset_hash = _insert_empty_dataset(
        market_database,
        symbols=("000001.SZ", "003043.SZ"),
    )

    async def scenario() -> object:
        outcome = await composition.operation_service.submit_run(
            command=_run_command(dataset_hash),
            context=MutationContext(
                idempotency_key="multi-symbol-run-intent",
                request_id="7" * 32,
            ),
        )
        await composition.stop()
        return outcome

    outcome = asyncio.run(scenario())

    assert outcome.receipt.job_id
    assert reader.calls == [_PLAN_VERSION_ID]


def test_run_submission_claim_is_atomic_across_production_compositions(tmp_path) -> None:
    reader = _PlanSnapshotReader()
    market_database = tmp_path / "market.sqlite3"
    results_database = tmp_path / "results.sqlite3"
    cursor_key_path = tmp_path / "cursor.key"
    factory = create_backtest_composition_factory(
        config_path=Path("config/app.yaml"),
        plan_snapshot_reader=reader,
        market_database=market_database,
        results_database=results_database,
        cursor_key_path=cursor_key_path,
    )
    first_composition = factory()
    second_composition = factory()
    dataset_hash = _insert_empty_dataset(market_database)
    context = MutationContext(
        idempotency_key="cross-composition-run-intent",
        request_id="1" * 32,
    )

    async def scenario() -> tuple[object, object]:
        first, second = await asyncio.gather(
            first_composition.operation_service.submit_run(
                command=_run_command(dataset_hash),
                context=context,
            ),
            second_composition.operation_service.submit_run(
                command=_run_command(dataset_hash),
                context=context,
            ),
        )
        await first_composition.stop()
        await second_composition.stop()
        return first, second

    first, second = asyncio.run(scenario())

    assert first == second
    assert reader.calls == [_PLAN_VERSION_ID]


def test_run_submission_rejects_cross_operation_idempotency_key(tmp_path) -> None:
    reader = _PlanSnapshotReader()
    factory = create_backtest_composition_factory(
        config_path=Path("config/app.yaml"),
        plan_snapshot_reader=reader,
        market_database=tmp_path / "market.sqlite3",
        results_database=tmp_path / "results.sqlite3",
        cursor_key_path=tmp_path / "cursor.key",
    )
    composition = factory()
    context = MutationContext(
        idempotency_key="cross-operation-intent",
        request_id="2" * 32,
    )

    async def scenario() -> ApiError:
        await composition.operation_service.submit_dataset_verification(
            command=_verification_command(),
            context=context,
        )
        with pytest.raises(ApiError) as raised:
            await composition.operation_service.submit_run(
                command=_run_command("a" * 64),
                context=context,
            )
        await composition.stop()
        return raised.value

    error = asyncio.run(scenario())

    assert error.code is ApiErrorCode.CONFLICT
    assert reader.calls == []


def test_run_submission_rejects_cancellation_idempotency_key(tmp_path) -> None:
    reader = _PlanSnapshotReader()
    factory = create_backtest_composition_factory(
        config_path=Path("config/app.yaml"),
        plan_snapshot_reader=reader,
        market_database=tmp_path / "market.sqlite3",
        results_database=tmp_path / "results.sqlite3",
        cursor_key_path=tmp_path / "cursor.key",
    )
    composition = factory()
    submit_context = MutationContext(
        idempotency_key="job-for-cancellation",
        request_id="3" * 32,
    )
    cancel_context = MutationContext(
        idempotency_key="cancellation-intent",
        request_id="4" * 32,
    )

    async def scenario() -> ApiError:
        submitted = await composition.operation_service.submit_dataset_verification(
            command=_verification_command(),
            context=submit_context,
        )
        await composition.operation_service.request_cancel(
            command=BacktestJobCancellationCommand.model_validate(
                {"jobId": submitted.receipt.job_id}
            ),
            context=cancel_context,
        )
        with pytest.raises(ApiError) as raised:
            await composition.operation_service.submit_run(
                command=_run_command("a" * 64),
                context=cancel_context,
            )
        await composition.stop()
        return raised.value

    error = asyncio.run(scenario())

    assert error.code is ApiErrorCode.CONFLICT
    assert reader.calls == []


def test_cancellation_replay_keeps_the_original_job_response_after_acknowledgement(
    tmp_path,
) -> None:
    composition = create_backtest_composition_factory(
        config_path=Path("config/app.yaml"),
        plan_snapshot_reader=None,
        market_database=tmp_path / "market.sqlite3",
        results_database=tmp_path / "results.sqlite3",
        cursor_key_path=tmp_path / "cursor.key",
    )()
    submit_context = MutationContext(
        idempotency_key="running-job-for-cancel-replay",
        request_id="5" * 32,
    )
    cancel_context = MutationContext(
        idempotency_key="cancel-replay-after-ack",
        request_id="6" * 32,
    )

    async def scenario() -> tuple[object, object]:
        submitted = await composition.operation_service.submit_dataset_verification(
            command=_verification_command(),
            context=submit_context,
        )
        repository = composition.operation_service._repository
        claim = repository.claim_next()
        assert claim is not None
        first = await composition.operation_service.request_cancel(
            command=BacktestJobCancellationCommand.model_validate(
                {"jobId": submitted.receipt.job_id}
            ),
            context=cancel_context,
        )
        assert repository.acknowledge_cancel(
            claim.job_id,
            claim.claim_token.get_secret_value(),
        )
        replay = await composition.operation_service.request_cancel(
            command=BacktestJobCancellationCommand.model_validate(
                {"jobId": submitted.receipt.job_id}
            ),
            context=cancel_context,
        )
        await composition.stop()
        return first, replay

    first, replay = asyncio.run(scenario())

    assert first == replay
    assert first.status_code == 202
    assert first.job.status == "CANCEL_REQUESTED"


@pytest.mark.parametrize("additional_blocker", ["review-warning", "validation-blocker"])
def test_frozen_backtest_eligibility_does_not_ignore_unresolved_review(
    tmp_path, additional_blocker
):
    reader = _PlanSnapshotReader()
    if additional_blocker == "review-warning":
        reader._payload["reviewIssues"] = [
            {
                "kind": "WARNING",
                "path": "draft",
                "material": True,
                "resolved": False,
            }
        ]
    else:
        reader._payload["validationIssues"].append(
            {
                "code": "MISSING_MARKET_EVIDENCE",
                "path": "draft",
                "severity": "WARNING",
                "message": "Historical input is missing independently required evidence.",
                "activationBlocking": True,
            }
        )
    market_database = tmp_path / "market.sqlite3"
    composition = create_backtest_composition_factory(
        config_path=Path("config/app.yaml"),
        plan_snapshot_reader=reader,
        market_database=market_database,
        results_database=tmp_path / "results.sqlite3",
        cursor_key_path=tmp_path / "cursor.key",
    )()
    dataset_hash = _insert_empty_dataset(market_database)

    async def scenario():
        try:
            with pytest.raises(ApiError) as caught:
                await composition.operation_service.submit_run(
                    command=_run_command(dataset_hash),
                    context=MutationContext(
                        idempotency_key="blocked-frozen-backtest", request_id="a" * 32
                    ),
                )
            assert caught.value.code is ApiErrorCode.CONFLICT
        finally:
            await composition.stop()

    asyncio.run(scenario())
