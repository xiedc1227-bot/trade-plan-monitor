"""Fixed offline acceptance orchestration for the production backtest surface."""

from __future__ import annotations

import ast
import ctypes
import gc
import importlib.util
import json
import math
import os
import re
import sqlite3
import sys
import tracemalloc
from collections.abc import Callable
from contextlib import AbstractContextManager
from functools import cache
from pathlib import Path
from threading import Event, Thread
from time import perf_counter
from types import ModuleType

from fastapi.testclient import TestClient

from trade_plan_monitor.backtest import reporting
from trade_plan_monitor.backtest.control import CancellationToken
from trade_plan_monitor.backtest.dataset import exchange_for_symbol
from trade_plan_monitor.backtest.jobs.models import BacktestRunJobRequest
from trade_plan_monitor.backtest.jobs.repository import BacktestJobRepository
from trade_plan_monitor.backtest.market_store import BacktestMarketStore
from trade_plan_monitor.backtest.pagination import HmacCursorSigner
from trade_plan_monitor.backtest.reporting import persist_report
from trade_plan_monitor.backtest.result_service import (
    BacktestDetailFilters,
    BacktestResultService,
)
from trade_plan_monitor.backtest.results import (
    BacktestDetailKind,
    BacktestDetailRecord,
    BacktestResultStore,
)
from trade_plan_monitor.backtest.run_input import BacktestRunInput
from trade_plan_monitor.decision.models import EvaluationContext, EvaluationResult
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.backtest_export import PreparedBacktestExport
from trade_plan_monitor.web.backtest_schemas import BacktestRunView
from trade_plan_monitor.web.routers.backtest_data import BacktestJobSubmissionOutcome
from trade_plan_monitor.web.routers.backtest_runs import BacktestRunSubmissionOutcome

_ROOT = Path(__file__).resolve().parents[2]
_REPORTS = (
    _ROOT / "docs/verification/backtest-acceptance.md",
    _ROOT / "docs/verification/backtest-acceptance.zh-CN.md",
)
_RUNNER_TEST = _ROOT / "tests/integration/test_backtest_runner.py"
_RESULT_QUERY_TEST = _ROOT / "tests/integration/test_backtest_result_queries.py"
_EXPORT_TEST = _ROOT / "tests/integration/test_backtest_exports.py"
_PLAN_VERSION_ID = "4c623c8c-ca26-4cd8-8cb2-08cd5e61be93"
_DATASET_HASH = "a" * 64
_RUN_ID = "b" * 64
_REPORT_HASH = "c" * 64
_PLAN_HASH = "d" * 64
_REQUEST_HASH = "e" * 64
_SHANGHAI_CREATED = "2026-08-30T10:00:00.000000+08:00"
_SHANGHAI_STARTED = "2026-08-30T10:00:30.000000+08:00"
_SHANGHAI_FINISHED = "2026-08-30T10:01:00.000000+08:00"
_MIB = 1_024 * 1_024
_CAPACITY_SYMBOLS = (
    "000001.SZ",
    "000002.SZ",
    "000333.SZ",
    "002415.SZ",
    "003043.SZ",
    "300750.SZ",
    "600000.SH",
    "600519.SH",
    "601318.SH",
    "688981.SH",
)

_PRIOR_PYTHON_EVIDENCE = (
    (
        "MIGRATION-ROLLBACK",
        "tests/integration/test_backtest_migrations.py",
        "test_migration_decision_is_bound_to_source_and_verified_backup_facts",
    ),
    (
        "MIGRATION-IDENTITY",
        "tests/integration/test_backtest_migrations.py",
        "test_market_metadata_migration_preserves_all_identity_bearing_rows",
    ),
    (
        "BACKUP-RESTORE",
        "tests/integration/test_sqlite_backup.py",
        "test_verified_backup_restores_to_a_readable_database",
    ),
    (
        "CANCEL-FIRST-RACE",
        "tests/integration/test_backtest_job_coordinator.py",
        "test_atomic_completion_gives_cancellation_first_one_terminal_and_no_partial_result",
    ),
    (
        "PUBLICATION-FIRST-RACE",
        "tests/integration/test_backtest_job_coordinator.py",
        "test_atomic_completion_gives_publication_first_one_terminal_and_visible_result",
    ),
    (
        "RECOVERY-FENCING",
        "tests/integration/test_backtest_job_leases.py",
        "test_recovery_has_exactly_three_claim_generations_and_fences_stale_tokens",
    ),
    (
        "REPLAY-RESTART",
        "tests/integration/test_backtest_runner.py",
        "test_midrun_cancellation_and_restart_replay_from_the_frozen_beginning",
    ),
    (
        "RETENTION-BOUND",
        "tests/integration/test_backtest_retention.py",
        "test_result_cleanup_consumes_only_caller_budget_and_never_vacuums",
    ),
    (
        "WAL-SNAPSHOT",
        "tests/integration/test_backtest_result_queries.py",
        "test_detail_page_uses_one_wal_snapshot_during_partial_cleanup",
    ),
    (
        "EXPORT-BOUNDS",
        "tests/integration/test_backtest_export_api.py",
        "test_disconnect_stops_before_pulling_the_next_chunk_and_closes_iterator",
    ),
    (
        "EVENT-LOOP-ISOLATION",
        "tests/integration/test_backtest_job_coordinator.py",
        "test_blocking_job_keeps_event_loop_responsive_and_heartbeats_on_one_owned_thread",
    ),
    (
        "PRODUCTION-PLAN-ISOLATION",
        "tests/integration/test_backtest_production_composition.py",
        "test_production_factory_is_lazy_and_run_replay_reuses_one_plan_snapshot",
    ),
)

_REPORT_TOKENS = (
    "BT050-JOURNEY",
    "BT050-TWO-SYMBOL",
    "BT050-RESOURCE",
    "LIVE-STATE-ZERO-DIFF",
    "NOTIFICATION-ZERO-CALLS",
    "BROWSER-CHROMIUM-ONLY",
    "NVDA",
    "BC01",
    "T058",
    "T059",
    "C24",
) + tuple(item[0] for item in _PRIOR_PYTHON_EVIDENCE)


def _receipt(
    *,
    job_id: str,
    kind: str,
    dataset_hash: str | None,
    run_id: str | None,
) -> dict[str, object]:
    return {
        "jobId": job_id,
        "kind": kind,
        "status": "QUEUED",
        "runId": run_id,
        "datasetHash": dataset_hash,
        "attempt": 0,
        "revision": 0,
        "reused": False,
        "submittedAt": _SHANGHAI_CREATED,
    }


def _completed_job(
    *,
    job_id: str,
    kind: str,
    dataset_hash: str | None = None,
    run_id: str | None = None,
) -> dict[str, object]:
    if kind == "DATA_SYNC":
        result: dict[str, object] = {
            "kind": kind,
            "calendarRows": 2,
            "minuteDays": 2,
            "dailyLimitRows": 2,
            "dailyBarRows": 2,
            "networkCalls": 0,
        }
    elif kind == "DATASET_VERIFY":
        result = {
            "kind": kind,
            "ready": True,
            "datasetHash": dataset_hash,
            "coverage": {
                "symbolCount": 1,
                "tradingDayCount": 2,
                "calendarRowCount": 2,
                "minuteDayCount": 2,
                "minuteBarCount": 480,
                "dailyLimitRowCount": 2,
                "dailyBarRowCount": 2,
                "blockers": [],
            },
            "blockers": [],
        }
    else:
        result = {
            "kind": kind,
            "runId": run_id,
            "reportHash": _REPORT_HASH,
            "reused": False,
        }
    return {
        "jobId": job_id,
        "kind": kind,
        "status": "COMPLETED",
        "requestHash": _REQUEST_HASH,
        "runId": run_id,
        "datasetHash": dataset_hash,
        "progress": {
            "phase": "TERMINAL",
            "completedUnits": 1,
            "totalUnits": 1,
            "unit": "ITEMS",
            "updatedAt": _SHANGHAI_FINISHED,
        },
        "result": result,
        "attempt": 1,
        "revision": 1,
        "createdAt": _SHANGHAI_CREATED,
        "startedAt": _SHANGHAI_STARTED,
        "updatedAt": _SHANGHAI_FINISHED,
        "finishedAt": _SHANGHAI_FINISHED,
        "cancelRequestedAt": None,
        "reused": False,
        "errorCode": None,
        "errorMessage": None,
    }


def _run_payload(*, pinned: bool, revision: int) -> dict[str, object]:
    return {
        "runId": _RUN_ID,
        "reportHash": _REPORT_HASH,
        "planVersionId": _PLAN_VERSION_ID,
        "planHash": _PLAN_HASH,
        "datasetHash": _DATASET_HASH,
        "symbol": "003043.SZ",
        "status": "COMPLETED",
        "eventStart": "2026-08-20",
        "eventEnd": "2026-08-21",
        "completedAt": _SHANGHAI_FINISHED,
        "pinned": pinned,
        "revision": revision,
        "fillCount": 2,
        "metrics": {
            "initialCashFen": "1000000",
            "initialEquityFen": "1000000",
            "finalCashFen": "1000000",
            "finalEquityFen": "1000000",
            "totalReturn": "0",
            "maximumDrawdown": "0",
            "tradeCount": 2,
            "winningSellCount": 1,
            "winRate": "0.5",
            "turnoverFen": "200000",
            "totalCostFen": "0",
            "realizedPnlFen": "0",
            "unrealizedPnlFen": "0",
            "blockedCount": 0,
            "skippedCount": 0,
        },
        "availability": {
            "decisionDetails": "AVAILABLE",
            "signalDetails": "AVAILABLE",
            "executionOutcomeDetails": "AVAILABLE",
            "equitySeries": "AVAILABLE",
        },
        "initialCashFen": "1000000",
        "coverage": {
            "eventStart": "2026-08-20",
            "eventEnd": "2026-08-21",
            "tradingDayCount": 2,
            "decisionCount": 98,
            "signalCount": 2,
            "orderCount": 2,
            "fillCount": 2,
            "outcomeCount": 2,
            "equityPointCount": 2,
        },
        "assumptions": {
            "eventRiskAssumption": "NO_EVENT_RISK",
            "executionConfig": {
                "commissionRate": "0.0003",
                "minimumCommissionFen": "500",
                "stampDutyRate": "0.0005",
                "transferFeeRate": "0.00001",
                "buySlippageBps": "1.25",
                "sellSlippageBps": "2",
            },
            "executionConfigHash": "f" * 64,
            "priceAdjustmentPolicy": "NONE",
            "historicalProfile": "TUSHARE_STK_MINS_241_END_V1",
        },
        "formulaVersions": {
            "runFormulaVersion": "backtest-run-v2",
            "reportSchemaVersion": "backtest-report-v2",
            "executionFormulaVersion": "execution-model-v1",
            "metricFormulaVersion": "backtest-metrics-v1",
        },
        "limitations": [
            "DAILY_EQUITY_DRAWDOWN_SAMPLING",
            "SIMULATED_EXECUTION_NO_BROKER",
        ],
    }


class _StatefulFakeBacktestService:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.jobs: dict[str, dict[str, object]] = {}
        self.run = BacktestRunView.model_validate(_run_payload(pinned=False, revision=2))
        self.provider_calls = 0
        self.notification_calls = 0
        self.websocket_calls = 0
        self.live_state = {
            "plans": 3,
            "positions": 2,
            "strategyStates": 4,
            "alerts": 5,
            "outbox": 0,
            "monitorEvents": 7,
        }

    async def submit_data_sync(self, *, command, context) -> BacktestJobSubmissionOutcome:
        assert command.allow_network is True
        assert command.refresh is False
        assert context.idempotency_key == "bt050-sync-intent"
        self.calls.append("sync")
        job_id = "bt050-sync-job"
        self.jobs[job_id] = _completed_job(job_id=job_id, kind="DATA_SYNC")
        return BacktestJobSubmissionOutcome(
            receipt=_receipt(
                job_id=job_id,
                kind="DATA_SYNC",
                dataset_hash=None,
                run_id=None,
            ),
            location=f"/api/v1/backtest-jobs/{job_id}",
            retry_after_seconds=2,
        )

    async def submit_dataset_verification(
        self,
        *,
        command,
        context,
    ) -> BacktestJobSubmissionOutcome:
        assert command.scope.symbols == ("003043.SZ",)
        assert context.idempotency_key == "bt050-verify-intent"
        self.calls.append("verify")
        job_id = "bt050-verify-job"
        self.jobs[job_id] = _completed_job(
            job_id=job_id,
            kind="DATASET_VERIFY",
            dataset_hash=_DATASET_HASH,
        )
        return BacktestJobSubmissionOutcome(
            receipt=_receipt(
                job_id=job_id,
                kind="DATASET_VERIFY",
                dataset_hash=_DATASET_HASH,
                run_id=None,
            ),
            location=f"/api/v1/backtest-jobs/{job_id}",
            retry_after_seconds=2,
        )

    async def submit_run(self, *, command, context) -> BacktestRunSubmissionOutcome:
        assert command.dataset_hash == _DATASET_HASH
        assert command.initial_lots == ()
        assert context.idempotency_key == "bt050-run-intent"
        self.calls.append("submit")
        job_id = "bt050-run-job"
        self.jobs[job_id] = _completed_job(
            job_id=job_id,
            kind="BACKTEST_RUN",
            dataset_hash=_DATASET_HASH,
            run_id=_RUN_ID,
        )
        return BacktestRunSubmissionOutcome(
            receipt=_receipt(
                job_id=job_id,
                kind="BACKTEST_RUN",
                dataset_hash=_DATASET_HASH,
                run_id=_RUN_ID,
            ),
            location=f"/api/v1/backtest-jobs/{job_id}",
            retry_after_seconds=2,
        )

    async def get_job(self, *, job_id: str) -> dict[str, object] | None:
        label = {
            "bt050-sync-job": "poll:sync-job",
            "bt050-verify-job": "poll:verify-job",
            "bt050-run-job": "poll:run-job",
        }[job_id]
        self.calls.append(label)
        return self.jobs.get(job_id)

    async def get_run(self, *, run_id: str) -> BacktestRunView | None:
        self.calls.append("result")
        return self.run if run_id == _RUN_ID else None

    async def pin_run(self, *, run_id: str, command, context) -> BacktestRunView:
        assert run_id == _RUN_ID
        assert command.pinned is True
        assert command.expected_revision == 2
        assert context.idempotency_key == "bt050-pin-intent"
        self.calls.append("pin")
        self.run = BacktestRunView.model_validate(_run_payload(pinned=True, revision=3))
        return self.run

    async def prepare_export(
        self,
        *,
        run_id: str,
        export_kind: str,
        cancelled: Callable[[], bool],
    ) -> PreparedBacktestExport | None:
        assert run_id == _RUN_ID
        assert export_kind == "SUMMARY_JSON"
        assert cancelled() is False
        self.calls.append("export")
        body = json.dumps(
            {
                "schemaVersion": "backtest-report-summary-v2",
                "runId": _RUN_ID,
                "reportHash": _REPORT_HASH,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        return PreparedBacktestExport(
            run_id=_RUN_ID,
            export_kind="SUMMARY_JSON",
            schema_version="backtest-report-summary-v2",
            chunks=iter((body,)),
        )


class _AcceptanceRuntimeLifecycle:
    async def start(self) -> dict[str, object]:
        return {"status": "READY", "acceptance": "BT050"}

    async def stop(self) -> None:
        return None


def _scope_payload() -> dict[str, object]:
    return {
        "symbols": ["003043.SZ"],
        "start": "2026-08-20",
        "end": "2026-08-21",
        "warmupStart": "2026-06-01",
        "historicalProfile": "TUSHARE_STK_MINS_241_END_V1",
        "adjustmentPolicy": "NONE",
    }


def test_fake_production_journey_is_complete_offline_and_live_state_is_unchanged() -> None:
    service = _StatefulFakeBacktestService()
    before = json.dumps(service.live_state, sort_keys=True, separators=(",", ":"))
    app = create_app(
        runtime_factory=_AcceptanceRuntimeLifecycle,
        backtest_read_service=service,
        backtest_operation_service=service,
    )

    with TestClient(app) as client:
        sync = client.post(
            "/api/v1/backtest-data-syncs",
            headers={"Idempotency-Key": "bt050-sync-intent"},
            json={"scope": _scope_payload(), "refresh": False, "allowNetwork": True},
        )
        assert sync.status_code == 202
        assert sync.headers["location"] == "/api/v1/backtest-jobs/bt050-sync-job"
        assert sync.headers["retry-after"] == "2"
        assert client.get(sync.headers["location"]).json()["status"] == "COMPLETED"

        verify = client.post(
            "/api/v1/backtest-dataset-verifications",
            headers={"Idempotency-Key": "bt050-verify-intent"},
            json={"scope": _scope_payload()},
        )
        assert verify.status_code == 202
        assert client.get(verify.headers["location"]).json()["datasetHash"] == _DATASET_HASH

        submit = client.post(
            "/api/v1/backtest-runs",
            headers={"Idempotency-Key": "bt050-run-intent"},
            json={
                "planVersionId": _PLAN_VERSION_ID,
                "datasetHash": _DATASET_HASH,
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
            },
        )
        assert submit.status_code == 202
        run_job = client.get(submit.headers["location"])
        assert run_job.json()["result"]["runId"] == _RUN_ID

        result = client.get(f"/api/v1/backtest-runs/{_RUN_ID}")
        assert result.status_code == 200
        assert result.json()["fillCount"] == 2
        pinned = client.patch(
            f"/api/v1/backtest-runs/{_RUN_ID}",
            headers={"Idempotency-Key": "bt050-pin-intent"},
            json={"pinned": True, "expectedRevision": 2},
        )
        assert pinned.status_code == 200
        assert (pinned.json()["pinned"], pinned.json()["revision"]) == (True, 3)

        exported = client.get(f"/api/v1/backtest-runs/{_RUN_ID}/exports/SUMMARY_JSON")
        assert exported.status_code == 200
        assert exported.headers["cache-control"] == "no-store"
        assert exported.json() == {
            "schemaVersion": "backtest-report-summary-v2",
            "runId": _RUN_ID,
            "reportHash": _REPORT_HASH,
        }

    after = json.dumps(service.live_state, sort_keys=True, separators=(",", ":"))
    assert service.calls == [
        "sync",
        "poll:sync-job",
        "verify",
        "poll:verify-job",
        "submit",
        "poll:run-job",
        "result",
        "pin",
        "export",
    ]
    assert before == after
    assert (service.provider_calls, service.notification_calls, service.websocket_calls) == (
        0,
        0,
        0,
    )


@cache
def _load_runner_evidence_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_bt050_runner_evidence", _RUNNER_TEST)
    if spec is None or spec.loader is None:
        raise AssertionError("the tracked runner evidence module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@cache
def _load_result_query_evidence_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_bt050_query_evidence", _RESULT_QUERY_TEST)
    if spec is None or spec.loader is None:
        raise AssertionError("the tracked result-query evidence module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@cache
def _load_export_evidence_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_bt050_export_evidence", _EXPORT_TEST)
    if spec is None or spec.loader is None:
        raise AssertionError("the tracked export evidence module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("page_fault_count", ctypes.c_ulong),
        ("peak_working_set_size", ctypes.c_size_t),
        ("working_set_size", ctypes.c_size_t),
        ("quota_peak_paged_pool_usage", ctypes.c_size_t),
        ("quota_paged_pool_usage", ctypes.c_size_t),
        ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
        ("quota_non_paged_pool_usage", ctypes.c_size_t),
        ("pagefile_usage", ctypes.c_size_t),
        ("peak_pagefile_usage", ctypes.c_size_t),
    ]


def _working_set_bytes() -> int:
    if os.name == "nt":
        counters = _ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_ProcessMemoryCounters),
            ctypes.c_ulong,
        ]
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        handle = kernel32.GetCurrentProcess()
        if not psapi.GetProcessMemoryInfo(
            handle,
            ctypes.byref(counters),
            counters.cb,
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(counters.working_set_size)
    statm = Path("/proc/self/statm")
    if statm.is_file():
        resident_pages = int(statm.read_text(encoding="ascii").split()[1])
        return resident_pages * os.sysconf("SC_PAGE_SIZE")
    raise AssertionError("working-set measurement is unsupported on this acceptance host")


class _WorkingSetProbe(AbstractContextManager["_WorkingSetProbe"]):
    def __init__(self) -> None:
        self._baseline = _working_set_bytes()
        self._peak = self._baseline
        self._stop = Event()
        self._thread = Thread(target=self._sample, name="bt050-working-set", daemon=True)

    @property
    def delta_bytes(self) -> int:
        return max(0, self._peak - self._baseline)

    def __enter__(self) -> _WorkingSetProbe:
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        assert not self._thread.is_alive()
        self._peak = max(self._peak, _working_set_bytes())

    def _sample(self) -> None:
        while not self._stop.wait(0.01):
            self._peak = max(self._peak, _working_set_bytes())


def _checkpoint_market_wal(database: Path) -> None:
    with sqlite3.connect(database) as connection:
        row = connection.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
    assert row is not None and row[0] == 0


def _sqlite_domain_bytes(database: Path) -> int:
    paths = (database, Path(f"{database}-wal"))
    return sum(path.stat().st_size for path in paths if path.exists())


def _emit_measurement(values: dict[str, object]) -> None:
    if os.environ.get("BT050_REPORT_METRICS") == "1":
        sys.stdout.write(f"BT050-METRICS {json.dumps(values, sort_keys=True)}\n")


def _percentile(samples: tuple[float, ...], percentile: float) -> float:
    ordered = tuple(sorted(samples))
    return ordered[max(0, math.ceil(len(ordered) * percentile) - 1)]


def _measure_operation(operation: Callable[[], object]) -> tuple[tuple[float, ...], object]:
    result: object = None
    for _ in range(5):
        result = operation()
    samples = []
    for _ in range(30):
        started = perf_counter()
        result = operation()
        samples.append((perf_counter() - started) * 1_000)
    return tuple(samples), result


def _sample_summary(samples: tuple[float, ...]) -> dict[str, float]:
    return {
        "p50": _percentile(samples, 0.50),
        "p95": _percentile(samples, 0.95),
        "max": max(samples),
    }


def test_twenty_day_replay_meets_latency_working_set_and_wal_budgets(tmp_path) -> None:
    evidence = _load_runner_evidence_module()
    market_path = tmp_path / "functional-market.sqlite3"
    results_path = tmp_path / "functional-results.sqlite3"
    store = BacktestMarketStore(market_path)
    dataset_hash = evidence._seed_twenty_trading_day_dataset(store)
    source = evidence._FrozenReaderSource(store)

    with _WorkingSetProbe() as memory:
        started = perf_counter()
        report = evidence.OfflineBacktestRunner(source).run(
            plan=evidence._plan(),
            dataset_hash=dataset_hash,
            initial_cash_fen=10_000_000,
            execution_config=evidence._execution_config(),
            manual_event_risk=False,
        )
        elapsed_seconds = perf_counter() - started
        result_store = BacktestResultStore(results_path)
        persist_report(result_store, report)

    _checkpoint_market_wal(market_path)
    result_store.checkpoint_wal()
    assert len(report.decisions) == 980
    assert len(report.daily_equity) == 20
    assert source.open_count == 1
    assert elapsed_seconds <= 30
    assert memory.delta_bytes <= 512 * _MIB
    market_bytes = _sqlite_domain_bytes(market_path)
    result_bytes = _sqlite_domain_bytes(results_path)
    assert market_bytes <= 64 * _MIB
    assert result_bytes <= 32 * _MIB
    _emit_measurement(
        {
            "elapsedSeconds": elapsed_seconds,
            "marketDatabaseAndWalBytes": market_bytes,
            "resultDatabaseAndWalBytes": result_bytes,
            "workingSetDeltaBytes": memory.delta_bytes,
        }
    )


def test_twenty_day_replay_meets_traced_heap_budget(tmp_path) -> None:
    evidence = _load_runner_evidence_module()
    store = BacktestMarketStore(tmp_path / "traced-functional-market.sqlite3")
    dataset_hash = evidence._seed_twenty_trading_day_dataset(store)
    source = evidence._FrozenReaderSource(store)
    tracemalloc.start(1)
    baseline_bytes, _baseline_peak = tracemalloc.get_traced_memory()
    try:
        report = evidence.OfflineBacktestRunner(source).run(
            plan=evidence._plan(),
            dataset_hash=dataset_hash,
            initial_cash_fen=10_000_000,
            execution_config=evidence._execution_config(),
            manual_event_risk=False,
        )
        current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    del current_bytes
    traced_heap_delta = max(0, peak_bytes - baseline_bytes)
    assert len(report.decisions) == 980
    assert len(report.daily_equity) == 20
    assert traced_heap_delta <= 256 * _MIB
    _emit_measurement({"tracedHeapDeltaBytes": traced_heap_delta})


def _capacity_plan(evidence: ModuleType, symbol: str):
    values = evidence._plan().model_dump(mode="python", round_trip=True)
    values.update(
        {
            "symbol": symbol,
            "market": exchange_for_symbol(symbol),
            "name": f"容量验收 {symbol}",
        }
    )
    return evidence.TradePlan.model_validate(values)


def _seed_one_year_capacity_dataset(store: BacktestMarketStore) -> str:
    evidence = _load_runner_evidence_module()
    trade_dates = []
    cursor = evidence.TRADE_DATE
    while len(trade_dates) < 252:
        if cursor.weekday() < 5:
            trade_dates.append(cursor)
        cursor -= evidence.timedelta(days=1)
    trade_dates.reverse()
    start = trade_dates[0]
    end = trade_dates[-1]
    warmup_start = start - evidence.timedelta(days=400)
    exchanges = tuple(sorted({exchange_for_symbol(symbol) for symbol in _CAPACITY_SYMBOLS}))
    previous_open = {exchange: warmup_start - evidence.timedelta(days=3) for exchange in exchanges}
    calendar = []
    daily = []
    cursor = warmup_start
    while cursor <= end:
        is_open = cursor.weekday() < 5
        for exchange in exchanges:
            calendar.append(
                evidence.TradingDay(
                    exchange=exchange,
                    cal_date=cursor,
                    is_open=is_open,
                    previous_trade_date=previous_open[exchange],
                )
            )
        if is_open:
            for symbol in _CAPACITY_SYMBOLS:
                close_fen = 6_400 + (cursor - warmup_start).days
                daily.append(
                    evidence.DailyBar(
                        symbol=symbol,
                        trade_date=cursor,
                        open_fen=close_fen,
                        high_fen=close_fen + 2,
                        low_fen=close_fen - 2,
                        close_fen=close_fen,
                        volume_shares=2_000_000,
                        amount_yuan=evidence.Decimal(close_fen * 20_000),
                        is_official=True,
                        received_at=evidence.datetime.combine(
                            cursor,
                            evidence.time(15, 20),
                            evidence.SHANGHAI,
                        ),
                    )
                )
            for exchange in exchanges:
                previous_open[exchange] = cursor
        cursor += evidence.timedelta(days=1)
    store.record_trading_days(tuple(calendar))
    store.record_daily_bars(tuple(daily))

    minute_count = 0
    for symbol in _CAPACITY_SYMBOLS:
        for trade_date in trade_dates:
            close_fen = 6_400 + (trade_date - warmup_start).days
            minutes = tuple(
                evidence.MinuteBar(
                    symbol=symbol,
                    bar_end=bar_end,
                    open_fen=close_fen,
                    high_fen=close_fen + 1,
                    low_fen=close_fen - 1,
                    close_fen=close_fen,
                    volume_shares=1_000,
                    amount_yuan=evidence.Decimal(close_fen * 10),
                    received_at=bar_end + evidence.timedelta(seconds=12),
                )
                for bar_end in evidence.expected_minute_ends(trade_date, is_open=True)
            )
            minute_count += len(minutes)
            store.record_minute_batch(
                evidence.HistoricalMinuteBatch(
                    symbol=symbol,
                    trade_date=trade_date,
                    contract_version=evidence.PROFILE,
                    bars=minutes,
                    opening_special=evidence.HistoricalOpeningSpecial(
                        symbol=symbol,
                        source_time=evidence.datetime.combine(
                            trade_date,
                            evidence.time(9, 30),
                            evidence.SHANGHAI,
                        ),
                        open_fen=close_fen,
                        high_fen=close_fen + 1,
                        low_fen=close_fen - 1,
                        close_fen=close_fen,
                        volume_shares=500,
                        amount_yuan=evidence.Decimal(close_fen * 5),
                    ),
                )
            )
            store.record_daily_limits(
                (
                    evidence.DailyLimit(
                        symbol=symbol,
                        trade_date=trade_date,
                        up_limit_fen=close_fen * 11 // 10,
                        down_limit_fen=close_fen * 9 // 10,
                        received_at=evidence.datetime.combine(
                            trade_date,
                            evidence.time(9, 30),
                            evidence.SHANGHAI,
                        ),
                    ),
                )
            )

    assert minute_count == 604_800
    frozen = store.freeze_dataset(
        evidence.DatasetScope(
            symbols=_CAPACITY_SYMBOLS,
            start=start,
            end=end,
            warmup_start=warmup_start,
            historical_profile=evidence.PROFILE,
        )
    )
    assert frozen.ready is True
    assert frozen.dataset_hash is not None
    return frozen.dataset_hash


def test_ten_symbol_252_day_replays_meet_capacity_budgets(tmp_path) -> None:
    evidence = _load_runner_evidence_module()
    market_path = tmp_path / "capacity-ten-symbol.sqlite3"
    results_path = tmp_path / "capacity-ten-symbol-results.sqlite3"
    store = BacktestMarketStore(market_path)
    dataset_hash = _seed_one_year_capacity_dataset(store)
    manifest = store.dataset_manifest(dataset_hash)
    result_store = BacktestResultStore(results_path)
    elapsed_samples: list[float] = []
    run_ids: list[str] = []

    def cancel_at_deadline(completed_event: Event, token: CancellationToken) -> None:
        if not completed_event.wait(120):
            token.cancel()

    with _WorkingSetProbe() as memory:
        for symbol in _CAPACITY_SYMBOLS:
            plan = _capacity_plan(evidence, symbol)
            cancellation = evidence.CancellationToken()
            completed = Event()

            watchdog = Thread(
                target=cancel_at_deadline,
                args=(completed, cancellation),
                name="bt050-capacity-deadline",
                daemon=True,
            )
            watchdog.start()
            started = perf_counter()
            try:
                result = evidence.OfflineBacktestRunner(store).run(
                    plan=plan,
                    dataset_hash=dataset_hash,
                    initial_cash_fen=10_000_000,
                    execution_config=evidence._execution_config(),
                    manual_event_risk=False,
                    cancellation_token=cancellation,
                )
                elapsed_seconds = perf_counter() - started
            finally:
                completed.set()
                watchdog.join(timeout=5)
            assert not watchdog.is_alive()
            assert not isinstance(result, evidence.BacktestCancellationResult), (
                f"252-day replay for {symbol} exceeded 120 seconds; "
                f"observed {elapsed_seconds:.6f} seconds"
            )
            assert len(result.decisions) == 252 * 49
            assert len(result.daily_equity) == 252
            assert elapsed_seconds <= 120
            run_input = BacktestRunInput.create(
                plan=plan,
                manifest=manifest,
                initial_cash_fen=10_000_000,
                initial_lots=(),
                execution_config=evidence._execution_config(),
                manual_event_risk=False,
            )
            assert result.run_id == run_input.run_id
            persist_report(result_store, result, run_input=run_input)
            elapsed_samples.append(elapsed_seconds)
            run_ids.append(result.run_id)
            del result

    assert len(set(run_ids)) == len(_CAPACITY_SYMBOLS)
    _checkpoint_market_wal(market_path)
    result_store.checkpoint_wal()
    market_bytes = _sqlite_domain_bytes(market_path)
    result_bytes = _sqlite_domain_bytes(results_path)
    _emit_measurement(
        {
            "capacityMarketDatabaseAndWalBytes": market_bytes,
            "capacityResultDatabaseAndWalBytes": result_bytes,
            "capacityReplayElapsedSeconds": elapsed_samples,
            "capacityWorkingSetDeltaBytes": memory.delta_bytes,
        }
    )
    assert memory.delta_bytes <= 768 * _MIB
    assert market_bytes <= 512 * _MIB
    assert result_bytes <= 192 * _MIB


def test_252_day_replay_from_ten_symbol_dataset_meets_traced_heap_budget(tmp_path) -> None:
    evidence = _load_runner_evidence_module()
    store = BacktestMarketStore(tmp_path / "traced-capacity-ten-symbol.sqlite3")
    dataset_hash = _seed_one_year_capacity_dataset(store)
    plan = _capacity_plan(evidence, _CAPACITY_SYMBOLS[0])
    tracemalloc.start(1)
    baseline_bytes, _baseline_peak = tracemalloc.get_traced_memory()
    try:
        result = evidence.OfflineBacktestRunner(store).run(
            plan=plan,
            dataset_hash=dataset_hash,
            initial_cash_fen=10_000_000,
            execution_config=evidence._execution_config(),
            manual_event_risk=False,
        )
        current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    del current_bytes
    traced_heap_delta = max(0, peak_bytes - baseline_bytes)
    assert not isinstance(result, evidence.BacktestCancellationResult)
    assert len(result.decisions) == 252 * 49
    assert len(result.daily_equity) == 252
    assert traced_heap_delta <= 384 * _MIB
    _emit_measurement({"capacityTracedHeapDeltaBytes": traced_heap_delta})


def test_each_fixture_symbol_has_stable_buy_and_t1_exit_bytes(tmp_path) -> None:
    evidence = _load_runner_evidence_module()
    store = BacktestMarketStore(tmp_path / "two-symbol-20d.sqlite3")
    dataset_hash, fixture = evidence._seed_two_symbol_replay_dataset(store)
    source = evidence._FrozenReaderSource(store)
    buy_date = evidence.date.fromisoformat(str(fixture["start"]))
    sell_date = buy_date + evidence.timedelta(days=1)

    def actionable(context: EvaluationContext) -> EvaluationResult:
        return evidence._actionable_fixture_for_dates(
            context,
            buy_date=buy_date,
            sell_date=sell_date,
        )

    for symbol_fixture in fixture["symbols"]:
        runner = evidence.OfflineBacktestRunner(source, evaluator=actionable)
        arguments = {
            "plan": evidence._plan_for_fixture_symbol(symbol_fixture),
            "dataset_hash": dataset_hash,
            "initial_cash_fen": 10_000_000,
            "execution_config": evidence._execution_config(),
            "manual_event_risk": False,
        }
        first = runner.run(**arguments)
        repeated = runner.run(**arguments)
        assert first.canonical_json() == repeated.canonical_json()
        assert tuple(fill.side.value for fill in first.fills) == ("BUY", "SELL")
        assert first.fills[1].filled_at.date() > first.fills[0].filled_at.date()
        assert len(first.daily_equity) == 2
        timestamps = re.findall(r'\d{4}-\d{2}-\d{2}T[^"\\]+', first.canonical_json())
        assert timestamps
        assert all(timestamp.endswith("+08:00") for timestamp in timestamps)


def _large_detail(
    evidence: ModuleType,
    run_id: str,
    kind: BacktestDetailKind,
    index: int,
) -> BacktestDetailRecord:
    return BacktestDetailRecord(
        detail_id=evidence._hash(f"{run_id}:{kind.value}:{index}"),
        run_id=run_id,
        kind=kind,
        event_at=evidence.datetime(2026, 8, 20, 9, 30, tzinfo=evidence._SHANGHAI)
        + evidence.timedelta(microseconds=index),
        payload={"index": index, "kind": kind.value},
    )


def _seed_cancelled_jobs(
    database: Path,
    run_input: BacktestRunInput,
    repository: BacktestJobRepository,
) -> None:
    receipt = repository.submit(
        BacktestRunJobRequest(run_input=run_input),
        "bt050-query-template",
    )
    repository.request_cancel(receipt.job_id, "bt050-query-template-cancel")
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO backtest_job (
                job_id, kind, status, request_hash, operation_hash, request_json,
                run_id, dataset_hash, phase, progress_unit, completed_units,
                total_units, attempt, revision, membership_revision, created_at,
                started_at, updated_at, finished_at, cancel_requested_at, reused,
                result_json, error_code, error_message, network_authorized_at,
                request_id, claim_token, lease_expires_at, heartbeat_at,
                progress_updated_at
            )
            WITH RECURSIVE sequence(value) AS (
                SELECT 1
                UNION ALL
                SELECT value + 1 FROM sequence WHERE value < 9999
            )
            SELECT
                printf('%032x', sequence.value), template.kind, template.status,
                template.request_hash, template.operation_hash, template.request_json,
                template.run_id, template.dataset_hash, template.phase,
                template.progress_unit, template.completed_units, template.total_units,
                template.attempt, template.revision, template.membership_revision,
                template.created_at, template.started_at, template.updated_at,
                template.finished_at, template.cancel_requested_at, template.reused,
                template.result_json, template.error_code, template.error_message,
                template.network_authorized_at, template.request_id,
                template.claim_token, template.lease_expires_at,
                template.heartbeat_at, template.progress_updated_at
            FROM sequence
            CROSS JOIN backtest_job AS template
            WHERE template.job_id = ?
            """,
            (receipt.job_id,),
        )
        connection.commit()
        assert connection.execute("SELECT COUNT(*) FROM backtest_job").fetchone() == (10_000,)


def _seed_large_result_fixture(
    database: Path,
) -> tuple[BacktestResultStore, BacktestJobRepository, str]:
    query_evidence = _load_result_query_evidence_module()
    export_evidence = _load_export_evidence_module()
    repository = BacktestJobRepository(database)
    store = BacktestResultStore(database)
    label = "bt050-query-large-target"
    run_input = query_evidence._run_input(label)
    fills = tuple(export_evidence._fill(run_input.run_id, index) for index in range(100_000))
    details = tuple(
        _large_detail(query_evidence, run_input.run_id, kind, index)
        for kind, count in (
            (BacktestDetailKind.DECISION, 30_000),
            (BacktestDetailKind.SIGNAL, 30_000),
            (BacktestDetailKind.EXECUTION_OUTCOME, 30_000),
            (BacktestDetailKind.DAILY_EQUITY, 2_000),
        )
        for index in range(count)
    )
    materialized = query_evidence._materialize(
        store,
        label,
        completed_at=query_evidence.datetime(
            2026,
            8,
            24,
            15,
            tzinfo=query_evidence._SHANGHAI,
        ),
        fills=fills,
        details=details,
    )
    target_run_id = materialized[0].run_id
    del materialized, fills, details

    for batch in range(14):
        daily_label = f"bt050-query-daily-{batch:02d}"
        daily_input = query_evidence._run_input(daily_label)
        daily_details = tuple(
            _large_detail(
                query_evidence,
                daily_input.run_id,
                BacktestDetailKind.DAILY_EQUITY,
                batch * 2_000 + index,
            )
            for index in range(2_000)
        )
        materialized = query_evidence._materialize(
            store,
            daily_label,
            completed_at=query_evidence.datetime(
                2026,
                8,
                24,
                14,
                batch,
                tzinfo=query_evidence._SHANGHAI,
            ),
            details=daily_details,
        )
        del materialized, daily_details

    for index in range(985):
        empty_label = f"bt050-query-empty-{index:04d}"
        materialized = query_evidence._materialize(
            store,
            empty_label,
            completed_at=query_evidence.datetime(
                2026,
                8,
                23,
                12,
                tzinfo=query_evidence._SHANGHAI,
            )
            + query_evidence.timedelta(microseconds=index),
        )
        del materialized

    _seed_cancelled_jobs(database, run_input, repository)
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM backtest_run WHERE materialized = 1"
        ).fetchone() == (1_000,)
        assert connection.execute(
            "SELECT COUNT(*) FROM backtest_fill WHERE run_id = ?",
            (target_run_id,),
        ).fetchone() == (100_000,)
        for kind in (
            BacktestDetailKind.DECISION,
            BacktestDetailKind.SIGNAL,
            BacktestDetailKind.EXECUTION_OUTCOME,
            BacktestDetailKind.DAILY_EQUITY,
        ):
            assert connection.execute(
                "SELECT COUNT(*) FROM backtest_detail WHERE kind = ?",
                (kind.value,),
            ).fetchone() == (30_000,)
    store.checkpoint_wal()
    gc.collect()
    return store, repository, target_run_id


def _measure_export(
    store: BacktestResultStore,
    run_id: str,
) -> dict[str, float | int]:
    started = perf_counter()
    chunks = reporting.iter_export_fills(store, run_id, cancelled=lambda: False)
    try:
        first = next(chunks)
        first_byte_ms = (perf_counter() - started) * 1_000
        byte_count = len(first)
        maximum_chunk = len(first)
        for chunk in chunks:
            byte_count += len(chunk)
            maximum_chunk = max(maximum_chunk, len(chunk))
    finally:
        chunks.close()
    elapsed_seconds = perf_counter() - started
    return {
        "bytes": byte_count,
        "elapsedSeconds": elapsed_seconds,
        "firstByteMs": first_byte_ms,
        "maxChunkBytes": maximum_chunk,
        "throughputMiBPerSecond": byte_count / _MIB / elapsed_seconds,
    }


def test_large_queries_and_100k_export_meet_fixed_budgets(tmp_path) -> None:
    database = tmp_path / "query-large-results.sqlite3"
    store, repository, run_id = _seed_large_result_fixture(database)
    service = BacktestResultService(
        store=store,
        cursor_signer=HmacCursorSigner(b"q" * 32),
    )
    query_operations: dict[str, Callable[[], object]] = {
        "jobs": lambda: repository.query_jobs(limit=100),
        "runs": lambda: service.list_runs(limit=100),
        "fills": lambda: service.list_fills(run_id, limit=100),
        "decisions": lambda: service.list_details(
            run_id,
            limit=100,
            filters=BacktestDetailFilters(kind=BacktestDetailKind.DECISION),
        ),
        "signals": lambda: service.list_details(
            run_id,
            limit=100,
            filters=BacktestDetailFilters(kind=BacktestDetailKind.SIGNAL),
        ),
        "outcomes": lambda: service.list_details(
            run_id,
            limit=100,
            filters=BacktestDetailFilters(kind=BacktestDetailKind.EXECUTION_OUTCOME),
        ),
        "equity": lambda: service.get_equity_series(run_id),
    }
    query_samples: dict[str, tuple[float, ...]] = {}
    query_results: dict[str, object] = {}
    with _WorkingSetProbe() as query_memory:
        for name, operation in query_operations.items():
            samples, result = _measure_operation(operation)
            query_samples[name] = samples
            query_results[name] = result
    for name, samples in query_samples.items():
        assert _percentile(samples, 0.95) <= 250, f"{name} query exceeded 250 ms p95"
    assert query_memory.delta_bytes <= 32 * _MIB
    for name in ("runs", "fills", "decisions", "signals", "outcomes"):
        page = query_results[name]
        assert len(page.items) <= 100  # type: ignore[attr-defined]
        assert len(page.model_dump_json().encode("utf-8")) < 4 * _MIB  # type: ignore[attr-defined]
    assert len(query_results["equity"].items) == 2_000  # type: ignore[attr-defined]

    for _ in range(5):
        _measure_export(store, run_id)
    export_samples = []
    with _WorkingSetProbe() as export_memory:
        for _ in range(30):
            export_samples.append(_measure_export(store, run_id))
    first_byte_samples = tuple(float(item["firstByteMs"]) for item in export_samples)
    throughput_samples = tuple(float(item["throughputMiBPerSecond"]) for item in export_samples)
    assert _percentile(first_byte_samples, 0.95) <= 250
    assert min(throughput_samples) >= 5
    assert all(int(item["maxChunkBytes"]) <= 64 * 1_024 for item in export_samples)
    assert export_memory.delta_bytes <= 16 * _MIB

    store.checkpoint_wal()
    database_bytes = _sqlite_domain_bytes(database)
    assert database_bytes <= 384 * _MIB
    _emit_measurement(
        {
            "exportFirstByteMs": first_byte_samples,
            "exportMemoryDeltaBytes": export_memory.delta_bytes,
            "exportThroughputMiBPerSecond": throughput_samples,
            "queryDatabaseAndWalBytes": database_bytes,
            "queryMemoryDeltaBytes": query_memory.delta_bytes,
            "queryMilliseconds": query_samples,
            "querySummaries": {
                name: _sample_summary(samples) for name, samples in query_samples.items()
            },
        }
    )


def test_prior_evidence_manifest_and_bilingual_reports_fail_closed() -> None:
    for evidence_id, relative_path, test_name in _PRIOR_PYTHON_EVIDENCE:
        path = _ROOT / relative_path
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        functions = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert test_name in functions, f"{evidence_id} is missing {relative_path}::{test_name}"

    for browser_artifact in (
        "web/playwright.config.ts",
        "web/tests/e2e/backtests.spec.ts",
        "web/tests/e2e/accessibility.spec.ts",
    ):
        assert (_ROOT / browser_artifact).is_file()

    report_texts = tuple(path.read_text(encoding="utf-8") for path in _REPORTS)
    for token in _REPORT_TOKENS:
        assert all(token in report for report in report_texts), f"bilingual evidence omits {token}"
    for _evidence_id, relative_path, test_name in _PRIOR_PYTHON_EVIDENCE:
        node_id = f"{relative_path}::{test_name}"
        assert all(node_id in report for report in report_texts), (
            f"bilingual report omits {node_id}"
        )
    assert "Status: PASS" in report_texts[0]
    assert "状态：PASS" in report_texts[1]
