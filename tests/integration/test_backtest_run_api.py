"""Focused transport contracts for completed runs and run mutations."""

from __future__ import annotations

import ast
import inspect
from collections.abc import Mapping
from typing import cast

import pytest
from fastapi.testclient import TestClient

from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.backtest_schemas import (
    BacktestRunCommand,
    BacktestRunFiltersView,
    BacktestRunPage,
    BacktestRunView,
)
from trade_plan_monitor.web.errors import ApiError
from trade_plan_monitor.web.routers import backtest_runs
from trade_plan_monitor.web.routers.backtest_runs import (
    BacktestRunPinCommand,
    BacktestRunSubmissionOutcome,
    router,
)
from trade_plan_monitor.web.schemas import ApiErrorCode, MutationContext

_PLAN_VERSION_ID = "4c623c8c-ca26-4cd8-8cb2-08cd5e61be93"
_OTHER_PLAN_VERSION_ID = "8a35983c-1c8a-497a-bc77-b1c278e181cf"
_DATASET_HASH = "a" * 64
_RUN_ID = "b" * 64
_OTHER_RUN_ID = "c" * 64
_REPORT_HASH = "d" * 64
_PLAN_HASH = "e" * 64
_CURSOR = "anchor.signature"
_JOB_ID = "job-run-001"
_HEADERS = {"Idempotency-Key": "run-command-001"}
_MISSING = object()


def _execution_input_payload() -> dict[str, object]:
    return {
        "commissionRate": "0.0003",
        "minimumCommissionFen": 500,
        "stampDutyRate": "0.0005",
        "transferFeeRate": "0.00001",
        "buySlippageBps": "1.25",
        "sellSlippageBps": "2",
    }


def _run_command_payload(
    *,
    plan_version_id: str = _PLAN_VERSION_ID,
) -> dict[str, object]:
    return {
        "planVersionId": plan_version_id,
        "datasetHash": _DATASET_HASH,
        "initialCashFen": 1_000_000,
        "initialLots": [],
        "executionConfig": _execution_input_payload(),
        "eventRiskAssumption": "NO_EVENT_RISK",
    }


def _availability_payload() -> dict[str, object]:
    return {
        "decisionDetails": "AVAILABLE",
        "signalDetails": "AVAILABLE",
        "executionOutcomeDetails": "EXPIRED",
        "equitySeries": "AVAILABLE",
    }


def _metrics_payload() -> dict[str, object]:
    return {
        "initialCashFen": "1000000",
        "initialEquityFen": "1000000",
        "finalCashFen": "899998",
        "finalEquityFen": "1019998",
        "totalReturn": "0.019998",
        "maximumDrawdown": "0.01",
        "tradeCount": 1,
        "winningSellCount": 0,
        "winRate": "0",
        "turnoverFen": "100000",
        "totalCostFen": "2",
        "realizedPnlFen": "0",
        "unrealizedPnlFen": "20000",
        "blockedCount": 0,
        "skippedCount": 1,
    }


def _execution_view_payload() -> dict[str, object]:
    return {
        "commissionRate": "0.0003",
        "minimumCommissionFen": "500",
        "stampDutyRate": "0.0005",
        "transferFeeRate": "0.00001",
        "buySlippageBps": "2.5",
        "sellSlippageBps": "3",
    }


def _run_summary_payload(
    *,
    run_id: str = _RUN_ID,
    plan_version_id: str | None = _PLAN_VERSION_ID,
    pinned: bool = False,
    revision: int = 2,
) -> dict[str, object]:
    return {
        "runId": run_id,
        "reportHash": _REPORT_HASH,
        "planVersionId": plan_version_id,
        "planHash": _PLAN_HASH,
        "datasetHash": _DATASET_HASH,
        "symbol": "000001.SZ",
        "status": "COMPLETED",
        "eventStart": "2024-01-02",
        "eventEnd": "2024-01-05",
        "completedAt": "2026-08-28T09:30:00.000000+08:00",
        "pinned": pinned,
        "revision": revision,
        "fillCount": 1,
        "metrics": _metrics_payload(),
        "availability": _availability_payload(),
    }


def _run_view_payload(
    *,
    run_id: str = _RUN_ID,
    pinned: bool = False,
    revision: int = 2,
) -> dict[str, object]:
    return _run_summary_payload(run_id=run_id, pinned=pinned, revision=revision) | {
        "initialCashFen": "1000000",
        "coverage": {
            "eventStart": "2024-01-02",
            "eventEnd": "2024-01-05",
            "tradingDayCount": 4,
            "decisionCount": 4,
            "signalCount": 1,
            "orderCount": 1,
            "fillCount": 1,
            "outcomeCount": 1,
            "equityPointCount": 4,
        },
        "assumptions": {
            "eventRiskAssumption": "NO_EVENT_RISK",
            "executionConfig": _execution_view_payload(),
            "executionConfigHash": "f" * 64,
            "priceAdjustmentPolicy": "NONE",
            "historicalProfile": "TUSHARE_STK_MINS_241_END_V1",
        },
        "formulaVersions": {
            "runFormulaVersion": "backtest-run-v1",
            "reportSchemaVersion": "backtest-report-v1",
            "executionFormulaVersion": "execution-model-v1",
            "metricFormulaVersion": "backtest-metrics-v1",
        },
        "limitations": [
            "DAILY_EQUITY_DRAWDOWN_SAMPLING",
            "NO_INTRADAY_EVENT_RISK",
        ],
    }


def _run_view(
    *,
    run_id: str = _RUN_ID,
    pinned: bool = False,
    revision: int = 2,
) -> BacktestRunView:
    return BacktestRunView.model_validate(
        _run_view_payload(run_id=run_id, pinned=pinned, revision=revision)
    )


def _receipt_payload(
    *,
    status: str = "QUEUED",
    reused: bool = False,
    run_id: str = _RUN_ID,
    dataset_hash: str = _DATASET_HASH,
) -> dict[str, object]:
    immediate_reuse = status == "COMPLETED" and reused
    return {
        "jobId": _JOB_ID,
        "kind": "BACKTEST_RUN",
        "status": status,
        "runId": run_id,
        "datasetHash": dataset_hash,
        "attempt": 0 if status == "QUEUED" or immediate_reuse else 1,
        "revision": 0 if status == "QUEUED" or immediate_reuse else 1,
        "reused": reused,
        "submittedAt": "2026-08-28T10:00:00.000000+08:00",
    }


def _submission_outcome(
    *,
    status: str = "QUEUED",
    reused: bool = False,
    receipt: object | None = None,
    location: str | None = None,
    retry_after: int | None = 2,
) -> BacktestRunSubmissionOutcome:
    value = _receipt_payload(status=status, reused=reused) if receipt is None else receipt
    return BacktestRunSubmissionOutcome(
        receipt=value,
        location=f"/api/v1/backtest-jobs/{_JOB_ID}" if location is None else location,
        retry_after_seconds=retry_after,
    )


class _FakeRunReadService:
    def __init__(self, *, item: object | None = None) -> None:
        self.item = _run_view() if item is None else item
        self.list_calls: list[tuple[BacktestRunFiltersView, int, str | None]] = []
        self.get_calls: list[str] = []
        self.page_override: object | None = None

    async def list_runs(
        self,
        *,
        filters: BacktestRunFiltersView,
        limit: int,
        cursor: str | None,
    ) -> object:
        self.list_calls.append((filters, limit, cursor))
        if self.page_override is not None:
            return self.page_override
        items = [] if self.item is _MISSING else [self.item]
        return BacktestRunPage.model_validate(
            {
                "filters": filters.canonical_payload(),
                "items": [
                    _run_summary_payload(
                        run_id=value.run_id,
                        plan_version_id=(
                            str(value.plan_version_id)
                            if value.plan_version_id is not None
                            else None
                        ),
                        pinned=value.pinned,
                        revision=value.revision,
                    )
                    if isinstance(value, BacktestRunView)
                    else value
                    for value in items
                ],
                "limit": limit,
                "nextCursor": None,
                "hasMore": False,
                "highWatermark": _CURSOR,
            }
        )

    async def get_run(self, *, run_id: str) -> object | None:
        self.get_calls.append(run_id)
        return None if self.item is _MISSING else self.item


class _FakeRunOperationService:
    def __init__(
        self,
        *,
        submission: object | None = None,
        pin_result: object | None = None,
    ) -> None:
        self.submission = submission or _submission_outcome()
        self.pin_result = _run_view(pinned=True, revision=3) if pin_result is None else pin_result
        self.submit_calls: list[tuple[BacktestRunCommand, MutationContext]] = []
        self.pin_calls: list[tuple[str, BacktestRunPinCommand, MutationContext]] = []
        self.plan_lookup_count = 0
        self._submitted_keys: set[str] = set()

    async def submit_run(
        self,
        *,
        command: BacktestRunCommand,
        context: MutationContext,
    ) -> object:
        self.submit_calls.append((command, context))
        if context.idempotency_key not in self._submitted_keys:
            self._submitted_keys.add(context.idempotency_key)
            self.plan_lookup_count += 1
        if isinstance(self.submission, Exception):
            raise self.submission
        return self.submission

    async def pin_run(
        self,
        *,
        run_id: str,
        command: BacktestRunPinCommand,
        context: MutationContext,
    ) -> object:
        self.pin_calls.append((run_id, command, context))
        if isinstance(self.pin_result, Exception):
            raise self.pin_result
        return self.pin_result


def _client(
    *,
    read_service: object = _MISSING,
    operation_service: object = _MISSING,
) -> TestClient:
    app = create_app()
    if read_service is not _MISSING:
        app.state.backtest_read_service = read_service
    if operation_service is not _MISSING:
        app.state.backtest_operation_service = operation_service
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def _assert_error(response: object, *, status: int, code: str) -> None:
    typed_response = cast(object, response)
    assert typed_response.status_code == status  # type: ignore[attr-defined]
    payload = typed_response.json()  # type: ignore[attr-defined]
    assert payload["error"]["code"] == code
    assert payload["error"]["message"]
    assert (
        payload["error"]["requestId"]
        == typed_response.headers[  # type: ignore[attr-defined]
            "X-Request-ID"
        ]
    )


def test_list_backtest_runs_normalizes_filters_and_preserves_cursor() -> None:
    service = _FakeRunReadService(item=_MISSING)
    response = _client(read_service=service).get(
        "/api/v1/backtest-runs",
        params={
            "symbol": "000001.SZ",
            "planVersionId": _PLAN_VERSION_ID.upper(),
            "datasetHash": _DATASET_HASH,
            "completedFrom": "2026-08-01T09:30:00+08:00",
            "completedTo": "2026-08-28T15:00:00.123456+08:00",
            "pinned": "false",
            "limit": "37",
            "cursor": _CURSOR,
        },
    )

    assert response.status_code == 200
    filters, limit, cursor = service.list_calls.pop()
    assert filters.canonical_payload() == {
        "symbol": "000001.SZ",
        "planVersionId": _PLAN_VERSION_ID,
        "datasetHash": _DATASET_HASH,
        "completedFrom": "2026-08-01T09:30:00.000000+08:00",
        "completedTo": "2026-08-28T15:00:00.123456+08:00",
        "pinned": False,
    }
    assert (limit, cursor) == (37, _CURSOR)
    assert response.json()["filters"] == filters.canonical_payload()


@pytest.mark.parametrize(
    "params",
    [
        {"symbol": "000001.BJ"},
        {"planVersionId": "not-a-uuid"},
        {"datasetHash": "A" * 64},
        {"completedFrom": "2026-08-01T09:30:00Z"},
        {
            "completedFrom": "2026-08-29T09:30:00+08:00",
            "completedTo": "2026-08-28T09:30:00+08:00",
        },
        {"pinned": "yes"},
        {"limit": "0"},
        {"cursor": "not-signed"},
    ],
)
def test_list_backtest_runs_rejects_invalid_queries_before_service(
    params: Mapping[str, str],
) -> None:
    service = _FakeRunReadService(item=_MISSING)
    response = _client(read_service=service).get("/api/v1/backtest-runs", params=params)
    _assert_error(response, status=422, code="VALIDATION_ERROR")
    assert service.list_calls == []


@pytest.mark.parametrize(
    "params",
    [
        [("unexpected", "x")],
        [("symbol", "000001.SZ"), ("symbol", "000001.SZ")],
        [("planVersionId", _PLAN_VERSION_ID), ("planVersionId", _PLAN_VERSION_ID)],
        [("datasetHash", _DATASET_HASH), ("datasetHash", _DATASET_HASH)],
        [
            ("completedFrom", "2026-08-01T09:30:00+08:00"),
            ("completedFrom", "2026-08-01T09:30:00+08:00"),
        ],
        [
            ("completedTo", "2026-08-28T15:00:00+08:00"),
            ("completedTo", "2026-08-28T15:00:00+08:00"),
        ],
        [("pinned", "true"), ("pinned", "true")],
        [("limit", "20"), ("limit", "30")],
        [("cursor", _CURSOR), ("cursor", _CURSOR)],
    ],
    ids=[
        "unknown",
        "symbol",
        "plan-version",
        "dataset-hash",
        "completed-from",
        "completed-to",
        "pinned",
        "limit",
        "cursor",
    ],
)
def test_list_backtest_runs_requires_a_closed_query_before_service(
    params: list[tuple[str, str]],
) -> None:
    service = _FakeRunReadService(item=_MISSING)
    response = _client(read_service=service).get("/api/v1/backtest-runs", params=params)

    _assert_error(response, status=422, code="VALIDATION_ERROR")
    assert service.list_calls == []


def test_list_backtest_runs_revalidates_page_filter_and_limit_echoes() -> None:
    service = _FakeRunReadService(item=_MISSING)
    service.page_override = {
        "filters": {
            "symbol": None,
            "planVersionId": None,
            "datasetHash": None,
            "completedFrom": None,
            "completedTo": None,
            "pinned": None,
        },
        "items": [],
        "limit": 99,
        "nextCursor": None,
        "hasMore": False,
        "highWatermark": _CURSOR,
    }
    response = _client(read_service=service).get(
        "/api/v1/backtest-runs", params={"symbol": "000001.SZ", "limit": "20"}
    )
    _assert_error(response, status=500, code="INTERNAL_ERROR")


def test_list_backtest_runs_rejects_private_service_rows() -> None:
    service = _FakeRunReadService(item=_MISSING)
    private = _run_summary_payload()
    private["resultPath"] = "C:/private/result.json"
    service.page_override = {
        "filters": {
            "symbol": None,
            "planVersionId": None,
            "datasetHash": None,
            "completedFrom": None,
            "completedTo": None,
            "pinned": None,
        },
        "items": [private],
        "limit": 20,
        "nextCursor": None,
        "hasMore": False,
        "highWatermark": _CURSOR,
    }
    response = _client(read_service=service).get("/api/v1/backtest-runs")
    _assert_error(response, status=500, code="INTERNAL_ERROR")
    assert "C:/private/result.json" not in response.text


def test_get_backtest_run_returns_completed_projection_and_not_found() -> None:
    service = _FakeRunReadService()
    client = _client(read_service=service)
    found = client.get(f"/api/v1/backtest-runs/{_RUN_ID}")
    service.item = _MISSING
    missing = client.get(f"/api/v1/backtest-runs/{_OTHER_RUN_ID}")
    assert found.status_code == 200
    assert found.json() == _run_view().model_dump(mode="json", by_alias=True)
    _assert_error(missing, status=404, code="NOT_FOUND")
    assert service.get_calls == [_RUN_ID, _OTHER_RUN_ID]


@pytest.mark.parametrize(
    "service_value",
    [
        _run_view(run_id=_OTHER_RUN_ID),
        {**_run_view_payload(), "providerPayload": {"code": 0}},
        {**_run_view_payload(), "reportPath": "C:/private/report.json"},
    ],
)
def test_get_backtest_run_rejects_mismatched_or_private_service_output(
    service_value: object,
) -> None:
    response = _client(read_service=_FakeRunReadService(item=service_value)).get(
        f"/api/v1/backtest-runs/{_RUN_ID}"
    )
    _assert_error(response, status=500, code="INTERNAL_ERROR")
    assert "private" not in response.text


def test_submit_backtest_run_returns_active_202_receipt_and_context() -> None:
    service = _FakeRunOperationService()
    response = _client(operation_service=service).post(
        "/api/v1/backtest-runs", json=_run_command_payload(), headers=_HEADERS
    )
    assert response.status_code == 202
    command, context = service.submit_calls.pop()
    assert str(command.plan_version_id) == _PLAN_VERSION_ID
    assert command.dataset_hash == _DATASET_HASH
    assert context.idempotency_key == _HEADERS["Idempotency-Key"]
    assert context.request_id == response.headers["X-Request-ID"]
    assert response.headers["Location"] == f"/api/v1/backtest-jobs/{_JOB_ID}"
    assert response.headers["Retry-After"] == "2"
    assert response.json() == _receipt_payload()
    assert service.plan_lookup_count == 1


def test_submit_backtest_run_same_key_replay_has_no_second_lookup() -> None:
    service = _FakeRunOperationService()
    client = _client(operation_service=service)
    first = client.post("/api/v1/backtest-runs", json=_run_command_payload(), headers=_HEADERS)
    replay = client.post("/api/v1/backtest-runs", json=_run_command_payload(), headers=_HEADERS)
    assert first.status_code == replay.status_code == 202
    assert first.json() == replay.json()
    assert len(service.submit_calls) == 2
    assert service.plan_lookup_count == 1


def test_submit_backtest_run_immediate_reuse_is_202_without_retry_header() -> None:
    service = _FakeRunOperationService(
        submission=_submission_outcome(status="COMPLETED", reused=True, retry_after=None)
    )
    response = _client(operation_service=service).post(
        "/api/v1/backtest-runs", json=_run_command_payload(), headers=_HEADERS
    )
    assert response.status_code == 202
    assert response.headers["Location"] == f"/api/v1/backtest-jobs/{_JOB_ID}"
    assert "Retry-After" not in response.headers
    assert response.json() == _receipt_payload(status="COMPLETED", reused=True)


@pytest.mark.parametrize(
    ("body_update", "headers"),
    [
        ({"planPath": "C:/private/plan.json"}, _HEADERS),
        ({"providerToken": "secret-token"}, _HEADERS),
        ({"initialCashFen": 1.5}, _HEADERS),
        ({"executionConfig": _execution_input_payload() | {"buySlippageBps": 1.25}}, _HEADERS),
        ({}, {}),
    ],
)
def test_submit_backtest_run_rejects_private_inexact_or_unkeyed_input(
    body_update: Mapping[str, object], headers: Mapping[str, str]
) -> None:
    service = _FakeRunOperationService()
    response = _client(operation_service=service).post(
        "/api/v1/backtest-runs",
        json=_run_command_payload() | dict(body_update),
        headers=headers,
    )
    _assert_error(response, status=422, code="VALIDATION_ERROR")
    assert service.submit_calls == []
    assert "secret-token" not in response.text
    assert "C:/private/plan.json" not in response.text


@pytest.mark.parametrize(
    "outcome",
    [
        _submission_outcome(receipt=_receipt_payload() | {"kind": "DATA_SYNC"}),
        _submission_outcome(receipt=_receipt_payload(dataset_hash="9" * 64)),
        _submission_outcome(location="/api/v1/backtest-jobs/wrong"),
        _submission_outcome(retry_after=None),
        _submission_outcome(receipt=_receipt_payload() | {"planPath": "private"}),
    ],
)
def test_submit_backtest_run_rejects_mismatched_service_outcome(outcome: object) -> None:
    response = _client(operation_service=_FakeRunOperationService(submission=outcome)).post(
        "/api/v1/backtest-runs", json=_run_command_payload(), headers=_HEADERS
    )
    _assert_error(response, status=500, code="INTERNAL_ERROR")
    assert "private" not in response.text
    assert "wrong" not in response.text


def test_submit_backtest_run_does_not_derive_run_id_from_plan_version_id() -> None:
    service = _FakeRunOperationService()
    client = _client(operation_service=service)
    first = client.post(
        "/api/v1/backtest-runs",
        json=_run_command_payload(plan_version_id=_PLAN_VERSION_ID),
        headers={"Idempotency-Key": "plan-a"},
    )
    second = client.post(
        "/api/v1/backtest-runs",
        json=_run_command_payload(plan_version_id=_OTHER_PLAN_VERSION_ID),
        headers={"Idempotency-Key": "plan-b"},
    )
    assert first.status_code == second.status_code == 202
    assert first.json()["runId"] == second.json()["runId"] == _RUN_ID
    assert [str(call[0].plan_version_id) for call in service.submit_calls] == [
        _PLAN_VERSION_ID,
        _OTHER_PLAN_VERSION_ID,
    ]


def test_pin_backtest_run_requires_revision_key_and_preserves_service_result() -> None:
    service = _FakeRunOperationService()
    response = _client(operation_service=service).patch(
        f"/api/v1/backtest-runs/{_RUN_ID}",
        json={"pinned": True, "expectedRevision": 2},
        headers={"Idempotency-Key": "pin-run-001"},
    )
    assert response.status_code == 200
    run_id, command, context = service.pin_calls.pop()
    assert run_id == _RUN_ID
    assert command.pinned is True and command.expected_revision == 2
    assert context.idempotency_key == "pin-run-001"
    assert context.request_id == response.headers["X-Request-ID"]
    assert response.json() == _run_view(pinned=True, revision=3).model_dump(
        mode="json", by_alias=True
    )


@pytest.mark.parametrize(
    ("body", "headers"),
    [
        ({"pinned": True}, {"Idempotency-Key": "pin-run-001"}),
        ({"pinned": True, "expectedRevision": -1}, {"Idempotency-Key": "pin-run-001"}),
        ({"pinned": 1, "expectedRevision": 2}, {"Idempotency-Key": "pin-run-001"}),
        (
            {"pinned": True, "expectedRevision": 2, "runId": _RUN_ID},
            {"Idempotency-Key": "pin-run-001"},
        ),
        ({"pinned": True, "expectedRevision": 2}, {}),
    ],
)
def test_pin_backtest_run_rejects_invalid_input_before_service(
    body: Mapping[str, object], headers: Mapping[str, str]
) -> None:
    service = _FakeRunOperationService()
    response = _client(operation_service=service).patch(
        f"/api/v1/backtest-runs/{_RUN_ID}", json=body, headers=headers
    )
    _assert_error(response, status=422, code="VALIDATION_ERROR")
    assert service.pin_calls == []


def test_pin_backtest_run_preserves_conflict_and_canonical_replay() -> None:
    conflict = _client(
        operation_service=_FakeRunOperationService(pin_result=ApiError(ApiErrorCode.CONFLICT))
    ).patch(
        f"/api/v1/backtest-runs/{_RUN_ID}",
        json={"pinned": True, "expectedRevision": 2},
        headers={"Idempotency-Key": "pin-conflict"},
    )
    replay_view = _run_view(pinned=True, revision=3)
    replay_client = _client(operation_service=_FakeRunOperationService(pin_result=replay_view))
    first = replay_client.patch(
        f"/api/v1/backtest-runs/{_RUN_ID}",
        json={"pinned": True, "expectedRevision": 2},
        headers={"Idempotency-Key": "pin-replay"},
    )
    replay = replay_client.patch(
        f"/api/v1/backtest-runs/{_RUN_ID}",
        json={"pinned": True, "expectedRevision": 2},
        headers={"Idempotency-Key": "pin-replay"},
    )
    _assert_error(conflict, status=409, code="CONFLICT")
    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()


@pytest.mark.parametrize(
    "pin_result",
    [
        _run_view(run_id=_OTHER_RUN_ID, pinned=True, revision=3),
        _run_view(pinned=False, revision=3),
        {**_run_view_payload(pinned=True, revision=3), "databasePath": "private"},
    ],
)
def test_pin_backtest_run_revalidates_identity_state_and_private_output(
    pin_result: object,
) -> None:
    response = _client(operation_service=_FakeRunOperationService(pin_result=pin_result)).patch(
        f"/api/v1/backtest-runs/{_RUN_ID}",
        json={"pinned": True, "expectedRevision": 2},
        headers={"Idempotency-Key": "pin-invalid"},
    )
    _assert_error(response, status=500, code="INTERNAL_ERROR")
    assert "private" not in response.text


def test_missing_backtest_run_services_fail_closed() -> None:
    client = _client()
    responses = (
        client.get("/api/v1/backtest-runs"),
        client.get(f"/api/v1/backtest-runs/{_RUN_ID}"),
        client.post("/api/v1/backtest-runs", json=_run_command_payload(), headers=_HEADERS),
        client.patch(
            f"/api/v1/backtest-runs/{_RUN_ID}",
            json={"pinned": True, "expectedRevision": 2},
            headers={"Idempotency-Key": "pin-missing"},
        ),
    )
    for response in responses:
        _assert_error(response, status=503, code="SERVICE_UNAVAILABLE")


def test_backtest_run_router_imports_no_plan_provider_replay_or_persistence() -> None:
    tree = ast.parse(inspect.getsource(backtest_runs))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom))
    assert "trade_plan_monitor.web.routers.plans" not in imports
    assert not any(
        forbidden in imported
        for imported in imports
        for forbidden in (
            "tushare",
            "provider",
            "replay",
            "repository",
            "coordinator",
        )
    )
