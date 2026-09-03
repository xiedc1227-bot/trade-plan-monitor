"""Focused transport contracts for backtest data commands and dataset reads."""

from __future__ import annotations

import ast
import inspect
from collections.abc import Mapping
from typing import cast

import pytest
from fastapi.testclient import TestClient

from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.backtest_schemas import (
    BacktestDatasetFiltersView,
    BacktestDatasetPage,
    BacktestDatasetVerificationCommand,
    BacktestDatasetView,
    BacktestDataSyncCommand,
    BacktestReferenceMarketCoverageView,
)
from trade_plan_monitor.web.errors import ApiError
from trade_plan_monitor.web.routers import backtest_data
from trade_plan_monitor.web.routers.backtest_data import (
    BacktestJobSubmissionOutcome,
    router,
)
from trade_plan_monitor.web.schemas import ApiErrorCode, MutationContext

_DATASET_HASH = "a" * 64
_OTHER_DATASET_HASH = "b" * 64
_CURSOR = "anchor.signature"
_JOB_ID = "job-data-001"
_MISSING = object()
_HEADERS = {"Idempotency-Key": "data-command-001"}


def _scope_payload() -> dict[str, object]:
    return {
        "symbols": ["600000.SH", "000001.SZ"],
        "start": "2026-08-01",
        "end": "2026-08-02",
        "warmupStart": "2026-07-01",
        "historicalProfile": "TUSHARE_STK_MINS_241_END_V1",
        "adjustmentPolicy": "NONE",
    }


def _canonical_scope_payload() -> dict[str, object]:
    scope = _scope_payload()
    scope["symbols"] = ["000001.SZ", "600000.SH"]
    return scope


def _dataset_payload(
    *,
    dataset_hash: str = _DATASET_HASH,
    created_at: str = "2026-08-28T10:00:00.000000+08:00",
) -> dict[str, object]:
    return {
        "datasetHash": dataset_hash,
        "schemaVersion": "backtest-dataset-v1",
        "scope": _scope_payload(),
        "coverage": {
            "symbolCount": 2,
            "tradingDayCount": 2,
            "calendarRowCount": 4,
            "minuteDayCount": 4,
            "minuteBarCount": 968,
            "dailyLimitRowCount": 4,
            "dailyBarRowCount": 4,
            "blockers": [],
        },
        "createdAt": created_at,
        "verifiedAt": "2026-08-28T10:01:00.000000+08:00",
    }


def _dataset(*, dataset_hash: str = _DATASET_HASH) -> BacktestDatasetView:
    return BacktestDatasetView.model_validate(_dataset_payload(dataset_hash=dataset_hash))


def _receipt_payload(
    *,
    kind: str,
    status: str = "QUEUED",
    job_id: str = _JOB_ID,
) -> dict[str, object]:
    attempt = 0 if status == "QUEUED" else 1
    return {
        "jobId": job_id,
        "kind": kind,
        "status": status,
        "runId": None,
        "datasetHash": None,
        "attempt": attempt,
        "revision": 0 if status == "QUEUED" else 1,
        "reused": False,
        "submittedAt": "2026-08-28T10:00:00.000000+08:00",
    }


def _outcome(
    *,
    kind: str,
    status: str = "QUEUED",
    location: str | None = None,
    retry_after: int | None = 2,
    receipt: object | None = None,
) -> BacktestJobSubmissionOutcome:
    value = _receipt_payload(kind=kind, status=status) if receipt is None else receipt
    return BacktestJobSubmissionOutcome(
        receipt=value,
        location=f"/api/v1/backtest-jobs/{_JOB_ID}" if location is None else location,
        retry_after_seconds=retry_after,
    )


class _FakeReadService:
    def __init__(self, *, item: object | None = None) -> None:
        self.item = _dataset() if item is None else item
        self.list_calls: list[tuple[BacktestDatasetFiltersView, int, str | None]] = []
        self.get_calls: list[str] = []
        self.coverage_calls: list[tuple[str, str]] = []
        self.page_override: object | None = None

    async def list_datasets(
        self,
        *,
        filters: BacktestDatasetFiltersView,
        limit: int,
        cursor: str | None,
    ) -> object:
        self.list_calls.append((filters, limit, cursor))
        if self.page_override is not None:
            return self.page_override
        items = [] if self.item is _MISSING else [self.item]
        return BacktestDatasetPage.model_validate(
            {
                "filters": filters.canonical_payload(),
                "items": [
                    value.model_dump(mode="json", by_alias=True)
                    if isinstance(value, BacktestDatasetView)
                    else value
                    for value in items
                ],
                "limit": limit,
                "nextCursor": None,
                "hasMore": False,
                "highWatermark": _CURSOR,
            }
        )

    async def get_dataset(self, *, dataset_hash: str) -> object | None:
        self.get_calls.append(dataset_hash)
        return None if self.item is _MISSING else self.item

    async def get_reference_market_coverage(
        self,
        *,
        dataset_hash: str,
        plan_version_id: str,
    ) -> object:
        self.coverage_calls.append((dataset_hash, plan_version_id))
        return BacktestReferenceMarketCoverageView.model_validate(
            {
                "planVersionId": plan_version_id,
                "datasetHash": dataset_hash,
                "binding": {
                    "selection": "AUTO_BOARD",
                    "mappingVersion": "board-index-map-v1",
                    "indexCode": "000001.SH",
                    "displayName": "上证指数",
                    "board": "SSE_MAIN",
                },
                "required": True,
                "conditionPaths": ["entry.condition"],
                "requiredFiveMinuteCount": 0,
                "availableFiveMinuteCount": 0,
                "requiredOfficialDayCount": 20,
                "availableOfficialDayCount": 22,
                "warmupStart": "2026-07-01",
                "warmupEnd": "2026-08-01",
                "coverageStatus": "AVAILABLE",
                "blockers": [],
                "marketIndexDataHash": "c" * 64,
                "indexRequirementHash": "d" * 64,
                "formulaDefinitionHash": "e" * 64,
            }
        )


class _FakeOperationService:
    def __init__(
        self,
        *,
        sync_outcome: object | None = None,
        verification_outcome: object | None = None,
    ) -> None:
        self.sync_outcome = sync_outcome or _outcome(kind="DATA_SYNC")
        self.verification_outcome = verification_outcome or _outcome(kind="DATASET_VERIFY")
        self.sync_calls: list[tuple[BacktestDataSyncCommand, MutationContext]] = []
        self.verification_calls: list[
            tuple[BacktestDatasetVerificationCommand, MutationContext]
        ] = []

    async def submit_data_sync(
        self,
        *,
        command: BacktestDataSyncCommand,
        context: MutationContext,
    ) -> object:
        self.sync_calls.append((command, context))
        if isinstance(self.sync_outcome, Exception):
            raise self.sync_outcome
        return self.sync_outcome

    async def submit_dataset_verification(
        self,
        *,
        command: BacktestDatasetVerificationCommand,
        context: MutationContext,
    ) -> object:
        self.verification_calls.append((command, context))
        if isinstance(self.verification_outcome, Exception):
            raise self.verification_outcome
        return self.verification_outcome


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


def test_submit_data_sync_requires_literal_network_authorization() -> None:
    service = _FakeOperationService()
    client = _client(operation_service=service)
    body = {"scope": _scope_payload(), "refresh": False, "allowNetwork": True}

    response = client.post("/api/v1/backtest-data-syncs", json=body, headers=_HEADERS)

    assert response.status_code == 202
    command, context = service.sync_calls.pop()
    assert command.allow_network is True
    assert command.refresh is False
    assert command.scope.symbols == ("000001.SZ", "600000.SH")
    assert context.idempotency_key == _HEADERS["Idempotency-Key"]
    assert context.request_id == response.headers["X-Request-ID"]
    assert response.headers["Location"] == f"/api/v1/backtest-jobs/{_JOB_ID}"
    assert response.headers["Retry-After"] == "2"
    assert response.json() == _receipt_payload(kind="DATA_SYNC")


def test_reference_market_coverage_is_plan_specific_and_read_only() -> None:
    service = _FakeReadService()
    client = _client(read_service=service)

    response = client.get(
        f"/api/v1/backtest-datasets/{_DATASET_HASH}/reference-market-coverage",
        params={"planVersionId": "4c623c8c-ca26-4cd8-8cb2-08cd5e61be93"},
    )

    assert response.status_code == 200
    assert service.coverage_calls == [(_DATASET_HASH, "4c623c8c-ca26-4cd8-8cb2-08cd5e61be93")]
    assert response.json()["conditionPaths"] == ["entry.condition"]
    assert response.json()["requiredFiveMinuteCount"] == 0
    assert response.json()["coverageStatus"] == "AVAILABLE"


@pytest.mark.parametrize("authorization", [_MISSING, False, "true", 1])
def test_submit_data_sync_rejects_missing_or_non_literal_network_authorization(
    authorization: object,
) -> None:
    service = _FakeOperationService()
    client = _client(operation_service=service)
    body = {"scope": _scope_payload(), "refresh": False}
    if authorization is not _MISSING:
        body["allowNetwork"] = authorization

    response = client.post("/api/v1/backtest-data-syncs", json=body, headers=_HEADERS)

    _assert_error(response, status=422, code="VALIDATION_ERROR")
    assert service.sync_calls == []


@pytest.mark.parametrize(
    ("extra_field", "value"),
    [
        ("token", "secret-token"),
        ("providerUrl", "https://provider.invalid"),
        ("databasePath", "C:/private/backtest.sqlite3"),
        ("planPath", "C:/private/plan.json"),
        ("reportPath", "C:/private/report.json"),
    ],
)
def test_submit_data_sync_rejects_secret_provider_and_path_fields(
    extra_field: str,
    value: str,
) -> None:
    service = _FakeOperationService()
    client = _client(operation_service=service)
    body = {
        "scope": _scope_payload(),
        "refresh": True,
        "allowNetwork": True,
        extra_field: value,
    }

    response = client.post("/api/v1/backtest-data-syncs", json=body, headers=_HEADERS)

    _assert_error(response, status=422, code="VALIDATION_ERROR")
    assert service.sync_calls == []
    assert value not in response.text


def test_submit_dataset_verification_is_a_closed_local_command() -> None:
    service = _FakeOperationService()
    client = _client(operation_service=service)

    response = client.post(
        "/api/v1/backtest-dataset-verifications",
        json={"scope": _scope_payload()},
        headers=_HEADERS,
    )

    assert response.status_code == 202
    command, context = service.verification_calls.pop()
    assert command.model_dump(mode="json", by_alias=True) == {"scope": _canonical_scope_payload()}
    assert context.request_id == response.headers["X-Request-ID"]
    assert service.sync_calls == []
    assert response.headers["Location"] == f"/api/v1/backtest-jobs/{_JOB_ID}"
    assert response.headers["Retry-After"] == "2"
    assert response.json() == _receipt_payload(kind="DATASET_VERIFY")


def test_submit_dataset_verification_rejects_network_authorization() -> None:
    service = _FakeOperationService()
    client = _client(operation_service=service)

    response = client.post(
        "/api/v1/backtest-dataset-verifications",
        json={"scope": _scope_payload(), "allowNetwork": True},
        headers=_HEADERS,
    )

    _assert_error(response, status=422, code="VALIDATION_ERROR")
    assert service.verification_calls == []


@pytest.mark.parametrize(
    "path",
    ["/api/v1/backtest-data-syncs", "/api/v1/backtest-dataset-verifications"],
)
def test_data_commands_require_a_strict_idempotency_key(path: str) -> None:
    service = _FakeOperationService()
    client = _client(operation_service=service)
    body: Mapping[str, object] = (
        {"scope": _scope_payload(), "refresh": False, "allowNetwork": True}
        if path.endswith("syncs")
        else {"scope": _scope_payload()}
    )

    missing = client.post(path, json=body)
    invalid = client.post(path, json=body, headers={"Idempotency-Key": "bad key"})

    _assert_error(missing, status=422, code="VALIDATION_ERROR")
    _assert_error(invalid, status=422, code="VALIDATION_ERROR")
    assert service.sync_calls == []
    assert service.verification_calls == []


@pytest.mark.parametrize(
    ("path", "kind", "body"),
    [
        (
            "/api/v1/backtest-data-syncs",
            "DATA_SYNC",
            {"scope": _scope_payload(), "refresh": False, "allowNetwork": True},
        ),
        (
            "/api/v1/backtest-dataset-verifications",
            "DATASET_VERIFY",
            {"scope": _scope_payload()},
        ),
    ],
)
def test_data_commands_accept_terminal_receipts_without_retry_header(
    path: str,
    kind: str,
    body: Mapping[str, object],
) -> None:
    terminal = _outcome(kind=kind, status="COMPLETED", retry_after=None)
    service = _FakeOperationService(
        sync_outcome=terminal,
        verification_outcome=terminal,
    )

    response = _client(operation_service=service).post(path, json=body, headers=_HEADERS)

    assert response.status_code == 202
    assert response.headers["Location"] == f"/api/v1/backtest-jobs/{_JOB_ID}"
    assert "Retry-After" not in response.headers
    assert response.json()["status"] == "COMPLETED"


@pytest.mark.parametrize(
    ("outcome", "path", "body"),
    [
        (
            _outcome(kind="DATASET_VERIFY"),
            "/api/v1/backtest-data-syncs",
            {"scope": _scope_payload(), "refresh": False, "allowNetwork": True},
        ),
        (
            _outcome(kind="DATA_SYNC"),
            "/api/v1/backtest-dataset-verifications",
            {"scope": _scope_payload()},
        ),
        (
            _outcome(kind="DATA_SYNC", location="/api/v1/backtest-jobs/wrong"),
            "/api/v1/backtest-data-syncs",
            {"scope": _scope_payload(), "refresh": False, "allowNetwork": True},
        ),
        (
            _outcome(kind="DATA_SYNC", retry_after=None),
            "/api/v1/backtest-data-syncs",
            {"scope": _scope_payload(), "refresh": False, "allowNetwork": True},
        ),
    ],
)
def test_data_commands_reject_mismatched_service_receipts_and_headers(
    outcome: object,
    path: str,
    body: Mapping[str, object],
) -> None:
    service = _FakeOperationService(
        sync_outcome=outcome,
        verification_outcome=outcome,
    )

    response = _client(operation_service=service).post(path, json=body, headers=_HEADERS)

    _assert_error(response, status=500, code="INTERNAL_ERROR")
    assert "wrong" not in response.text


def test_data_commands_revalidate_and_redact_service_receipts() -> None:
    receipt = _receipt_payload(kind="DATA_SYNC")
    receipt["providerToken"] = "provider-secret"
    service = _FakeOperationService(sync_outcome=_outcome(kind="DATA_SYNC", receipt=receipt))

    response = _client(operation_service=service).post(
        "/api/v1/backtest-data-syncs",
        json={"scope": _scope_payload(), "refresh": False, "allowNetwork": True},
        headers=_HEADERS,
    )

    _assert_error(response, status=500, code="INTERNAL_ERROR")
    assert "provider-secret" not in response.text


def test_list_datasets_normalizes_filters_and_preserves_cursor_intent() -> None:
    service = _FakeReadService(item=_MISSING)
    client = _client(read_service=service)

    response = client.get(
        "/api/v1/backtest-datasets",
        params={
            "symbol": "000001.SZ",
            "startOnOrAfter": "2026-08-01",
            "endOnOrBefore": "2026-08-02",
            "historicalProfile": "TUSHARE_STK_MINS_241_END_V1",
            "adjustmentPolicy": "NONE",
            "limit": "37",
            "cursor": _CURSOR,
        },
    )

    assert response.status_code == 200
    filters, limit, cursor = service.list_calls.pop()
    assert filters.canonical_payload() == {
        "symbol": "000001.SZ",
        "startOnOrAfter": "2026-08-01",
        "endOnOrBefore": "2026-08-02",
        "historicalProfile": "TUSHARE_STK_MINS_241_END_V1",
        "adjustmentPolicy": "NONE",
    }
    assert (limit, cursor) == (37, _CURSOR)
    assert response.json()["filters"] == filters.canonical_payload()


@pytest.mark.parametrize(
    "params",
    [
        {"symbol": "000001.BJ"},
        {"startOnOrAfter": "2026-08-03", "endOnOrBefore": "2026-08-02"},
        {"historicalProfile": "OTHER"},
        {"adjustmentPolicy": "FORWARD"},
        {"limit": "0"},
        {"limit": "101"},
        {"cursor": "not-a-signed-cursor"},
    ],
)
def test_list_datasets_rejects_malformed_queries_before_service(
    params: Mapping[str, str],
) -> None:
    service = _FakeReadService(item=_MISSING)

    response = _client(read_service=service).get(
        "/api/v1/backtest-datasets",
        params=params,
    )

    _assert_error(response, status=422, code="VALIDATION_ERROR")
    assert service.list_calls == []


def test_list_datasets_revalidates_filter_and_limit_echoes() -> None:
    service = _FakeReadService(item=_MISSING)
    service.page_override = {
        "filters": {
            "symbol": None,
            "startOnOrAfter": None,
            "endOnOrBefore": None,
            "historicalProfile": None,
            "adjustmentPolicy": None,
        },
        "items": [],
        "limit": 99,
        "nextCursor": None,
        "hasMore": False,
        "highWatermark": _CURSOR,
    }

    response = _client(read_service=service).get(
        "/api/v1/backtest-datasets",
        params={"symbol": "000001.SZ", "limit": "20"},
    )

    _assert_error(response, status=500, code="INTERNAL_ERROR")


def test_list_datasets_revalidates_order_and_private_service_fields() -> None:
    service = _FakeReadService(item=_MISSING)
    newest = _dataset_payload(
        dataset_hash=_DATASET_HASH,
        created_at="2026-08-28T10:00:00.000000+08:00",
    )
    older = _dataset_payload(
        dataset_hash=_OTHER_DATASET_HASH,
        created_at="2026-08-27T10:00:00.000000+08:00",
    )
    older["manifestPath"] = "C:/private/manifest.json"
    service.page_override = {
        "filters": {
            "symbol": None,
            "startOnOrAfter": None,
            "endOnOrBefore": None,
            "historicalProfile": None,
            "adjustmentPolicy": None,
        },
        "items": [newest, older],
        "limit": 20,
        "nextCursor": None,
        "hasMore": False,
        "highWatermark": _CURSOR,
    }

    response = _client(read_service=service).get("/api/v1/backtest-datasets")

    _assert_error(response, status=500, code="INTERNAL_ERROR")
    assert "C:/private/manifest.json" not in response.text


def test_get_dataset_returns_only_the_bounded_public_projection() -> None:
    service = _FakeReadService()

    response = _client(read_service=service).get(f"/api/v1/backtest-datasets/{_DATASET_HASH}")

    assert response.status_code == 200
    assert service.get_calls == [_DATASET_HASH]
    assert response.json() == _dataset().model_dump(mode="json", by_alias=True)
    assert set(response.json()) == {
        "datasetHash",
        "schemaVersion",
        "scope",
        "coverage",
        "createdAt",
        "verifiedAt",
    }


def test_get_dataset_returns_not_found_without_disclosing_lookup_context() -> None:
    service = _FakeReadService(item=_MISSING)

    response = _client(read_service=service).get(f"/api/v1/backtest-datasets/{_DATASET_HASH}")

    _assert_error(response, status=404, code="NOT_FOUND")
    assert _DATASET_HASH not in response.text


@pytest.mark.parametrize(
    "service_value",
    [
        _dataset(dataset_hash=_OTHER_DATASET_HASH),
        {**_dataset_payload(), "membership": ["private-row-id"]},
        {**_dataset_payload(), "providerBody": {"code": 0}},
        {**_dataset_payload(), "artifactPath": "C:/private/artifact"},
    ],
)
def test_get_dataset_rejects_mismatched_or_private_service_output(
    service_value: object,
) -> None:
    response = _client(read_service=_FakeReadService(item=service_value)).get(
        f"/api/v1/backtest-datasets/{_DATASET_HASH}"
    )

    _assert_error(response, status=500, code="INTERNAL_ERROR")
    assert "private" not in response.text


def test_missing_data_services_return_service_unavailable() -> None:
    client = _client()

    missing_list = client.get("/api/v1/backtest-datasets")
    missing_detail = client.get(f"/api/v1/backtest-datasets/{_DATASET_HASH}")
    missing_sync = client.post(
        "/api/v1/backtest-data-syncs",
        json={"scope": _scope_payload(), "refresh": False, "allowNetwork": True},
        headers=_HEADERS,
    )
    missing_verification = client.post(
        "/api/v1/backtest-dataset-verifications",
        json={"scope": _scope_payload()},
        headers=_HEADERS,
    )

    for response in (missing_list, missing_detail, missing_sync, missing_verification):
        _assert_error(response, status=503, code="SERVICE_UNAVAILABLE")


def test_service_errors_are_preserved_as_fixed_public_envelopes() -> None:
    service = _FakeOperationService(
        sync_outcome=ApiError(ApiErrorCode.CONFLICT),
    )

    response = _client(operation_service=service).post(
        "/api/v1/backtest-data-syncs",
        json={"scope": _scope_payload(), "refresh": False, "allowNetwork": True},
        headers=_HEADERS,
    )

    _assert_error(response, status=409, code="CONFLICT")


def test_rate_limited_service_error_preserves_required_retry_after() -> None:
    service = _FakeOperationService(
        sync_outcome=ApiError(
            ApiErrorCode.RATE_LIMITED,
            retry_after_seconds=2,
        ),
    )

    response = _client(operation_service=service).post(
        "/api/v1/backtest-data-syncs",
        json={"scope": _scope_payload(), "refresh": False, "allowNetwork": True},
        headers=_HEADERS,
    )

    _assert_error(response, status=429, code="RATE_LIMITED")
    assert response.headers["Retry-After"] == "2"


def test_router_imports_no_provider_replay_or_persistence_implementation() -> None:
    tree = ast.parse(inspect.getsource(backtest_data))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom))

    assert not any(
        forbidden in imported
        for imported in imports
        for forbidden in ("tushare", "provider", "replay", "repository", "coordinator")
    )
