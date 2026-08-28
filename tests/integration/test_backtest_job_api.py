"""Focused transport contracts for backtest job reads and cancellation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import pytest
from fastapi.testclient import TestClient

from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.backtest_schemas import (
    BacktestJobFiltersView,
    BacktestJobPage,
    BacktestJobView,
)
from trade_plan_monitor.web.errors import ApiError
from trade_plan_monitor.web.routers.backtest_jobs import (
    BacktestJobCancellationCommand,
    BacktestJobCancellationOutcome,
    router,
)
from trade_plan_monitor.web.schemas import ApiErrorCode, MutationContext

_JOB_ID = "job-001"
_HASH = "a" * 64
_DATASET_HASH = "b" * 64
_CURSOR = "anchor.signature"
_MISSING = object()


def _job_payload(
    status: str,
    *,
    job_id: str = _JOB_ID,
    attempt: int | None = None,
) -> dict[str, object]:
    terminal = status in {"COMPLETED", "FAILED", "CANCELLED"}
    active = status in {"RUNNING", "CANCEL_REQUESTED"}
    claimed = active or status in {"COMPLETED", "FAILED"}
    resolved_attempt = (1 if claimed else 0) if attempt is None else attempt
    created_at = "2026-08-28T10:00:00.000000+08:00"
    started_at = "2026-08-28T10:01:00.000000+08:00" if resolved_attempt else None
    progress_at = (
        "2026-08-28T10:00:00.000000+08:00"
        if status == "QUEUED"
        else "2026-08-28T10:02:00.000000+08:00"
    )
    updated_at = (
        "2026-08-28T10:00:00.000000+08:00"
        if status == "QUEUED"
        else "2026-08-28T10:03:00.000000+08:00"
    )
    finished_at = updated_at if terminal else None
    cancelled = status in {"CANCEL_REQUESTED", "CANCELLED"}
    result: dict[str, object] | None = None
    if status == "COMPLETED":
        result = {
            "kind": "DATA_SYNC",
            "calendarRows": 2,
            "minuteDays": 1,
            "dailyLimitRows": 1,
            "dailyBarRows": 1,
            "networkCalls": 0,
        }
    return {
        "jobId": job_id,
        "kind": "DATA_SYNC",
        "status": status,
        "requestHash": _HASH,
        "runId": None,
        "datasetHash": None,
        "progress": {
            "phase": "TERMINAL"
            if terminal
            else ("QUEUED" if status == "QUEUED" else "SYNCING_DATA"),
            "completedUnits": 0,
            "totalUnits": 1,
            "unit": "ITEMS",
            "updatedAt": progress_at,
        },
        "result": result,
        "attempt": resolved_attempt,
        "revision": 1 if status != "QUEUED" else 0,
        "createdAt": created_at,
        "startedAt": started_at,
        "updatedAt": updated_at,
        "finishedAt": finished_at,
        "cancelRequestedAt": ("2026-08-28T10:02:00.000000+08:00" if cancelled else None),
        "reused": False,
        "errorCode": (
            "BACKTEST_OPERATION_FAILED"
            if status == "FAILED"
            else "BACKTEST_OPERATION_CANCELLED"
            if status == "CANCELLED"
            else None
        ),
        "errorMessage": (
            "The job failed."
            if status == "FAILED"
            else "The job was cancelled."
            if status == "CANCELLED"
            else None
        ),
    }


def _job(status: str, *, job_id: str = _JOB_ID, attempt: int | None = None) -> BacktestJobView:
    return BacktestJobView.model_validate(_job_payload(status, job_id=job_id, attempt=attempt))


def _cancellation_outcome(
    status: str,
    *,
    status_code: int,
    attempt: int | None = None,
    job_id: str = _JOB_ID,
    location: str | None = None,
    retry_after: int | None = None,
) -> BacktestJobCancellationOutcome:
    return BacktestJobCancellationOutcome(
        job=_job(status, job_id=job_id, attempt=attempt),
        status_code=status_code,
        location=location,
        retry_after_seconds=retry_after,
    )


class _FakeReadService:
    def __init__(self, *, item: object | None = None) -> None:
        self.item = _job("RUNNING") if item is None else item
        self.list_calls: list[tuple[BacktestJobFiltersView, int, str | None]] = []
        self.get_calls: list[str] = []
        self.page_override: object | None = None

    async def list_jobs(
        self,
        *,
        filters: BacktestJobFiltersView,
        limit: int,
        cursor: str | None,
    ) -> object:
        self.list_calls.append((filters, limit, cursor))
        if self.page_override is not None:
            return self.page_override
        items = () if self.item is _MISSING else (self.item,)
        return BacktestJobPage.model_validate(
            {
                "filters": filters.canonical_payload(),
                "items": [
                    value.model_dump(mode="json", by_alias=True)
                    if isinstance(value, BacktestJobView)
                    else value
                    for value in items
                ],
                "limit": limit,
                "nextCursor": None,
                "hasMore": False,
                "highWatermark": _CURSOR,
            }
        )

    async def get_job(self, *, job_id: str) -> object | None:
        self.get_calls.append(job_id)
        return None if self.item is _MISSING else self.item


class _FakeOperationService:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome
        self.calls: list[tuple[BacktestJobCancellationCommand, MutationContext]] = []

    async def request_cancel(
        self,
        *,
        command: BacktestJobCancellationCommand,
        context: MutationContext,
    ) -> object:
        self.calls.append((command, context))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


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
    assert payload["error"]["requestId"] == typed_response.headers["X-Request-ID"]  # type: ignore[attr-defined]


def test_list_jobs_normalizes_closed_filters_and_preserves_cursor_intent() -> None:
    service = _FakeReadService(item=_MISSING)
    client = _client(read_service=service)

    response = client.get(
        "/api/v1/backtest-jobs",
        params=[
            ("kind", "BACKTEST_RUN"),
            ("kind", "DATA_SYNC"),
            ("kind", "BACKTEST_RUN"),
            ("status", "RUNNING"),
            ("status", "QUEUED"),
            ("runId", _HASH),
            ("datasetHash", _DATASET_HASH),
            ("createdFrom", "2026-08-01T09:30:00+08:00"),
            ("createdTo", "2026-08-28T15:00:00.123456+08:00"),
            ("limit", "37"),
            ("cursor", _CURSOR),
        ],
    )

    assert response.status_code == 200
    filters, limit, cursor = service.list_calls.pop()
    assert filters.canonical_payload() == {
        "kind": ["BACKTEST_RUN", "DATA_SYNC"],
        "status": ["QUEUED", "RUNNING"],
        "runId": _HASH,
        "datasetHash": _DATASET_HASH,
        "createdFrom": "2026-08-01T09:30:00.000000+08:00",
        "createdTo": "2026-08-28T15:00:00.123456+08:00",
    }
    assert (limit, cursor) == (37, _CURSOR)
    assert response.json()["filters"] == filters.canonical_payload()


def test_list_jobs_revalidates_service_filter_and_limit_echoes() -> None:
    service = _FakeReadService(item=_MISSING)
    service.page_override = {
        "filters": {
            "kind": None,
            "status": None,
            "runId": None,
            "datasetHash": None,
            "createdFrom": None,
            "createdTo": None,
        },
        "items": [],
        "limit": 99,
        "nextCursor": None,
        "hasMore": False,
        "highWatermark": _CURSOR,
    }

    response = _client(read_service=service).get("/api/v1/backtest-jobs?limit=20")

    _assert_error(response, status=500, code="INTERNAL_ERROR")


@pytest.mark.parametrize(
    "query",
    (
        "?limit=0",
        "?limit=101",
        "?createdFrom=2026-08-28T10:00:00Z",
        "?createdFrom=2026-08-28T10:00:00.000000%2B00:00",
        "?kind=UNKNOWN",
        "?cursor=unsigned-offset",
    ),
)
def test_list_jobs_rejects_invalid_query_before_service(query: str) -> None:
    service = _FakeReadService(item=_MISSING)

    response = _client(read_service=service).get(f"/api/v1/backtest-jobs{query}")

    _assert_error(response, status=422, code="VALIDATION_ERROR")
    assert service.list_calls == []


def test_get_job_returns_only_a_revalidated_matching_resource() -> None:
    service = _FakeReadService(item=_job("RUNNING"))

    response = _client(read_service=service).get(f"/api/v1/backtest-jobs/{_JOB_ID}")

    assert response.status_code == 200
    assert response.json()["jobId"] == _JOB_ID
    assert service.get_calls == [_JOB_ID]


def test_get_job_missing_resource_returns_the_canonical_404() -> None:
    service = _FakeReadService(item=_MISSING)

    response = _client(read_service=service).get(f"/api/v1/backtest-jobs/{_JOB_ID}")

    _assert_error(response, status=404, code="NOT_FOUND")


@pytest.mark.parametrize(
    "unsafe_item",
    (
        _job_payload("RUNNING", job_id="different-job"),
        _job_payload("RUNNING") | {"providerToken": "must-not-leak"},
    ),
)
def test_get_job_fails_closed_on_mismatched_or_extra_service_output(
    unsafe_item: Mapping[str, object],
) -> None:
    service = _FakeReadService(item=unsafe_item)

    response = _client(read_service=service).get(f"/api/v1/backtest-jobs/{_JOB_ID}")

    _assert_error(response, status=500, code="INTERNAL_ERROR")
    assert "must-not-leak" not in response.text


@pytest.mark.parametrize(
    ("current_status", "outcome", "expected_status", "expected_location", "expected_retry"),
    (
        ("QUEUED", _cancellation_outcome("CANCELLED", status_code=200, attempt=0), 200, None, None),
        (
            "RUNNING",
            _cancellation_outcome(
                "CANCEL_REQUESTED",
                status_code=202,
                location=f"/api/v1/backtest-jobs/{_JOB_ID}",
                retry_after=2,
            ),
            202,
            f"/api/v1/backtest-jobs/{_JOB_ID}",
            "2",
        ),
        (
            "CANCEL_REQUESTED",
            _cancellation_outcome(
                "CANCEL_REQUESTED",
                status_code=202,
                location=f"/api/v1/backtest-jobs/{_JOB_ID}",
                retry_after=2,
            ),
            202,
            f"/api/v1/backtest-jobs/{_JOB_ID}",
            "2",
        ),
        (
            "CANCELLED",
            _cancellation_outcome("CANCELLED", status_code=200, attempt=0),
            200,
            None,
            None,
        ),
        ("COMPLETED", ApiError(ApiErrorCode.CONFLICT), 409, None, None),
        ("FAILED", ApiError(ApiErrorCode.CONFLICT), 409, None, None),
    ),
)
def test_cancellation_matrix_preserves_application_outcome_and_canonical_headers(
    current_status: str,
    outcome: object,
    expected_status: int,
    expected_location: str | None,
    expected_retry: str | None,
) -> None:
    service = _FakeOperationService(outcome)

    response = _client(operation_service=service).post(
        "/api/v1/backtest-job-cancellations",
        json={"jobId": _JOB_ID},
        headers={"Idempotency-Key": f"cancel-{current_status.lower()}"},
    )

    assert response.status_code == expected_status
    assert response.headers.get("Location") == expected_location
    assert response.headers.get("Retry-After") == expected_retry
    assert len(service.calls) == 1
    command, context = service.calls[0]
    assert command.job_id == _JOB_ID
    assert context.idempotency_key == f"cancel-{current_status.lower()}"
    assert len(context.request_id) == 32
    if expected_status in {200, 202}:
        assert response.json()["jobId"] == _JOB_ID
    else:
        assert response.json()["error"]["code"] == "CONFLICT"


@pytest.mark.parametrize(
    ("body", "headers"),
    (
        ({"jobId": _JOB_ID}, {}),
        ({"jobId": _JOB_ID}, {"Idempotency-Key": "bad key"}),
        ({"jobId": _JOB_ID, "extra": True}, {"Idempotency-Key": "cancel-extra"}),
        ({"jobId": "../unsafe"}, {"Idempotency-Key": "cancel-unsafe"}),
    ),
)
def test_cancellation_rejects_invalid_command_or_idempotency_before_service(
    body: dict[str, object],
    headers: dict[str, str],
) -> None:
    service = _FakeOperationService(_cancellation_outcome("CANCELLED", status_code=200, attempt=0))

    response = _client(operation_service=service).post(
        "/api/v1/backtest-job-cancellations",
        json=body,
        headers=headers,
    )

    _assert_error(response, status=422, code="VALIDATION_ERROR")
    assert service.calls == []


@pytest.mark.parametrize(
    "outcome",
    (
        _job("CANCELLED", attempt=0),
        _cancellation_outcome("CANCELLED", status_code=202, attempt=0),
        _cancellation_outcome(
            "CANCEL_REQUESTED",
            status_code=202,
            location=f"/api/v1/backtest-jobs/{_JOB_ID}",
            retry_after=None,
        ),
        _cancellation_outcome(
            "CANCEL_REQUESTED",
            status_code=202,
            location="/api/v1/backtest-jobs/different-job",
            retry_after=2,
        ),
    ),
)
def test_cancellation_fails_closed_if_service_returns_a_noncanonical_outcome(
    outcome: object,
) -> None:
    service = _FakeOperationService(outcome)

    response = _client(operation_service=service).post(
        "/api/v1/backtest-job-cancellations",
        json={"jobId": _JOB_ID},
        headers={"Idempotency-Key": "cancel-invalid-success"},
    )

    _assert_error(response, status=500, code="INTERNAL_ERROR")


def test_cancellation_fails_closed_on_mismatched_or_extra_service_output() -> None:
    service = _FakeOperationService(
        BacktestJobCancellationOutcome(
            job=_job_payload("CANCELLED", job_id="different-job") | {"claimToken": "secret"},
            status_code=200,
            location=None,
            retry_after_seconds=None,
        )
    )

    response = _client(operation_service=service).post(
        "/api/v1/backtest-job-cancellations",
        json={"jobId": _JOB_ID},
        headers={"Idempotency-Key": "cancel-unsafe-output"},
    )

    _assert_error(response, status=500, code="INTERNAL_ERROR")
    assert "secret" not in response.text


def test_missing_services_fail_closed_without_cross_service_work() -> None:
    operation = _FakeOperationService(
        _cancellation_outcome("CANCELLED", status_code=200, attempt=0)
    )
    read = _FakeReadService(item=_MISSING)

    missing_read = _client(operation_service=operation).get("/api/v1/backtest-jobs")
    missing_operation = _client(read_service=read).post(
        "/api/v1/backtest-job-cancellations",
        json={"jobId": _JOB_ID},
        headers={"Idempotency-Key": "cancel-missing-service"},
    )

    _assert_error(missing_read, status=503, code="SERVICE_UNAVAILABLE")
    _assert_error(missing_operation, status=503, code="SERVICE_UNAVAILABLE")
    assert operation.calls == []
    assert read.list_calls == []
    assert read.get_calls == []
