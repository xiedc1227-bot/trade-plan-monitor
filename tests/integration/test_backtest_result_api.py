"""Focused transport contracts for completed backtest result reads."""

from __future__ import annotations

import ast
import inspect
from collections.abc import Mapping
from typing import cast

import pytest
from fastapi.testclient import TestClient

from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.backtest_schemas import (
    BacktestDetailFiltersView,
    BacktestDetailPage,
    BacktestEquitySeries,
    BacktestFillPage,
)
from trade_plan_monitor.web.errors import ApiError
from trade_plan_monitor.web.routers import backtest_results
from trade_plan_monitor.web.routers.backtest_results import router
from trade_plan_monitor.web.schemas import ApiErrorCode

_RUN_ID = "b" * 64
_OTHER_RUN_ID = "c" * 64
_HASH = "a" * 64
_DATASET_HASH = "d" * 64
_REPORT_HASH = "e" * 64
_CURSOR = "anchor.signature"
_TIME = "2026-08-28T09:30:00.123456+08:00"
_MISSING = object()


def _fees_payload() -> dict[str, object]:
    return {
        "commissionFen": "1",
        "stampDutyFen": "0",
        "transferFeeFen": "1",
        "totalFen": "2",
    }


def _fill_payload(*, run_id: str = _RUN_ID) -> dict[str, object]:
    return {
        "fillId": "fill-001",
        "orderId": "order-001",
        "signalId": "signal-001",
        "runId": run_id,
        "planHash": _HASH,
        "datasetHash": _DATASET_HASH,
        "resultHash": _REPORT_HASH,
        "configHash": "f" * 64,
        "sourceBarId": "bar-001",
        "side": "BUY",
        "symbol": "000001.SZ",
        "bucket": "CORE",
        "targetLotId": None,
        "filledAt": _TIME,
        "requestedQuantity": 100,
        "quantity": 100,
        "priceFen": "1000",
        "notionalFen": "100000",
        "fees": _fees_payload(),
        "cashDeltaFen": "-100002",
        "costBasisReleasedFen": "0",
        "realizedPnlFen": None,
    }


def _signal_payload(*, run_id: str = _RUN_ID) -> dict[str, object]:
    return {
        "kind": "SIGNAL",
        "detailId": "signal-detail-001",
        "runId": run_id,
        "eventAt": _TIME,
        "signalId": "signal-001",
        "resultHash": _REPORT_HASH,
        "signalType": "BUY_CORE_READY",
        "symbol": "000001.SZ",
        "quantity": 100,
        "bucket": "CORE",
        "targetLotId": None,
        "causeId": "decision-001",
    }


def _equity_payload(*, run_id: str = _RUN_ID) -> dict[str, object]:
    return {
        "snapshotId": "snapshot-001",
        "runId": run_id,
        "symbol": "000001.SZ",
        "markedAt": _TIME,
        "markPriceFen": "1200",
        "cashFen": "899998",
        "positionQuantity": 100,
        "marketValueFen": "120000",
        "costBasisFen": "100002",
        "realizedPnlFen": "0",
        "unrealizedPnlFen": "19998",
        "totalCostFen": "2",
        "equityFen": "1019998",
    }


def _fill_page_payload(
    *,
    run_id: str = _RUN_ID,
    limit: int = 20,
) -> dict[str, object]:
    return {
        "filters": {},
        "items": [_fill_payload(run_id=run_id)],
        "limit": limit,
        "nextCursor": None,
        "hasMore": False,
        "highWatermark": _CURSOR,
    }


def _detail_page_payload(
    *,
    run_id: str = _RUN_ID,
    kind: str = "SIGNAL",
    availability: str = "AVAILABLE",
    limit: int = 20,
) -> dict[str, object]:
    return {
        "kind": kind,
        "availability": availability,
        "filters": {"kind": kind},
        "items": [_signal_payload(run_id=run_id)] if availability == "AVAILABLE" else [],
        "limit": limit,
        "nextCursor": None,
        "hasMore": False,
        "highWatermark": _CURSOR,
    }


def _equity_series_payload(
    *,
    run_id: str = _RUN_ID,
    availability: str = "AVAILABLE",
) -> dict[str, object]:
    return {
        "availability": availability,
        "items": [_equity_payload(run_id=run_id)] if availability == "AVAILABLE" else [],
    }


class _FakeResultReadService:
    def __init__(self) -> None:
        self.fill_result: object = BacktestFillPage.model_validate(_fill_page_payload())
        self.detail_result: object = BacktestDetailPage.model_validate(_detail_page_payload())
        self.equity_result: object = BacktestEquitySeries.model_validate(_equity_series_payload())
        self.fill_calls: list[tuple[str, int, str | None]] = []
        self.detail_calls: list[tuple[str, BacktestDetailFiltersView, int, str | None]] = []
        self.equity_calls: list[str] = []

    async def list_fills(
        self,
        *,
        run_id: str,
        limit: int,
        cursor: str | None,
    ) -> object:
        self.fill_calls.append((run_id, limit, cursor))
        if isinstance(self.fill_result, Exception):
            raise self.fill_result
        return self.fill_result

    async def list_details(
        self,
        *,
        run_id: str,
        filters: BacktestDetailFiltersView,
        limit: int,
        cursor: str | None,
    ) -> object:
        self.detail_calls.append((run_id, filters, limit, cursor))
        if isinstance(self.detail_result, Exception):
            raise self.detail_result
        return self.detail_result

    async def get_equity_series(self, *, run_id: str) -> object:
        self.equity_calls.append(run_id)
        if isinstance(self.equity_result, Exception):
            raise self.equity_result
        return self.equity_result


def _client(*, service: object = _MISSING) -> TestClient:
    app = create_app()
    if service is not _MISSING:
        app.state.backtest_read_service = service
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


def test_fills_adapter_preserves_bounded_pagination_and_empty_filters() -> None:
    service = _FakeResultReadService()
    service.fill_result = BacktestFillPage.model_validate(_fill_page_payload(limit=37))
    response = _client(service=service).get(
        f"/api/v1/backtest-runs/{_RUN_ID}/fills",
        params={"limit": "37", "cursor": _CURSOR},
    )

    assert response.status_code == 200
    assert service.fill_calls == [(_RUN_ID, 37, _CURSOR)]
    assert response.json() == _fill_page_payload(limit=37)


@pytest.mark.parametrize(
    ("run_id", "params"),
    [
        ("not-a-run", {}),
        (_RUN_ID, {"limit": "0"}),
        (_RUN_ID, {"limit": "101"}),
        (_RUN_ID, {"cursor": "not-signed"}),
        (_RUN_ID, {"kind": "SIGNAL"}),
    ],
)
def test_fills_adapter_rejects_invalid_query_before_service(
    run_id: str,
    params: Mapping[str, str],
) -> None:
    service = _FakeResultReadService()
    response = _client(service=service).get(f"/api/v1/backtest-runs/{run_id}/fills", params=params)
    _assert_error(response, status=422, code="VALIDATION_ERROR")
    assert service.fill_calls == []


@pytest.mark.parametrize(
    "service_value",
    [
        _fill_page_payload(limit=99),
        _fill_page_payload(run_id=_OTHER_RUN_ID),
        _fill_page_payload() | {"filters": {"status": "FAILED"}},
        _fill_page_payload() | {"resultPath": "C:/private/result.json"},
    ],
)
def test_fills_adapter_revalidates_echo_identity_and_closed_output(
    service_value: object,
) -> None:
    service = _FakeResultReadService()
    service.fill_result = service_value
    response = _client(service=service).get(f"/api/v1/backtest-runs/{_RUN_ID}/fills")
    _assert_error(response, status=500, code="INTERNAL_ERROR")
    assert "private" not in response.text


def test_details_adapter_requires_kind_and_preserves_normalized_filter() -> None:
    service = _FakeResultReadService()
    service.detail_result = BacktestDetailPage.model_validate(_detail_page_payload(limit=31))
    response = _client(service=service).get(
        f"/api/v1/backtest-runs/{_RUN_ID}/details",
        params={"kind": "SIGNAL", "limit": "31", "cursor": _CURSOR},
    )

    assert response.status_code == 200
    run_id, filters, limit, cursor = service.detail_calls.pop()
    assert run_id == _RUN_ID
    assert filters == BacktestDetailFiltersView(kind="SIGNAL")
    assert (limit, cursor) == (31, _CURSOR)
    assert response.json() == _detail_page_payload(limit=31)


@pytest.mark.parametrize("kind", ["DECISION", "SIGNAL", "EXECUTION_OUTCOME"])
def test_details_adapter_accepts_each_exact_public_kind(kind: str) -> None:
    service = _FakeResultReadService()
    service.detail_result = BacktestDetailPage.model_validate(
        _detail_page_payload(kind=kind, availability="NOT_RECORDED")
    )
    response = _client(service=service).get(
        f"/api/v1/backtest-runs/{_RUN_ID}/details", params={"kind": kind}
    )

    assert response.status_code == 200
    assert response.json()["kind"] == response.json()["filters"]["kind"] == kind
    assert service.detail_calls[0][1].kind == kind


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"kind": "DAILY_EQUITY"},
        {"kind": "DIAGNOSTIC"},
        {"kind": "signal"},
        {"kind": "SIGNAL", "limit": "0"},
        {"kind": "SIGNAL", "cursor": "not-signed"},
        {"kind": "SIGNAL", "status": "FAILED"},
    ],
)
def test_details_adapter_rejects_missing_internal_or_invalid_filters(
    params: Mapping[str, str],
) -> None:
    service = _FakeResultReadService()
    response = _client(service=service).get(
        f"/api/v1/backtest-runs/{_RUN_ID}/details", params=params
    )
    _assert_error(response, status=422, code="VALIDATION_ERROR")
    assert service.detail_calls == []


@pytest.mark.parametrize("availability", ["EXPIRED", "NOT_RECORDED"])
def test_details_adapter_preserves_exact_unavailable_empty_shape(
    availability: str,
) -> None:
    service = _FakeResultReadService()
    service.detail_result = BacktestDetailPage.model_validate(
        _detail_page_payload(availability=availability)
    )
    response = _client(service=service).get(
        f"/api/v1/backtest-runs/{_RUN_ID}/details", params={"kind": "SIGNAL"}
    )

    assert response.status_code == 200
    assert response.json() == _detail_page_payload(availability=availability)
    assert len(service.detail_calls) == 1


@pytest.mark.parametrize(
    "service_value",
    [
        _detail_page_payload(limit=99),
        _detail_page_payload(run_id=_OTHER_RUN_ID),
        _detail_page_payload() | {"kind": "DECISION"},
        _detail_page_payload() | {"filters": {"kind": "DECISION"}},
        _detail_page_payload() | {"items": [_signal_payload() | {"kind": "DECISION"}]},
        _detail_page_payload() | {"diagnostic": {"trace": "private"}},
    ],
)
def test_details_adapter_revalidates_kind_item_identity_and_closed_output(
    service_value: object,
) -> None:
    service = _FakeResultReadService()
    service.detail_result = service_value
    response = _client(service=service).get(
        f"/api/v1/backtest-runs/{_RUN_ID}/details", params={"kind": "SIGNAL"}
    )
    _assert_error(response, status=500, code="INTERNAL_ERROR")
    assert "private" not in response.text


def test_equity_adapter_returns_at_most_bounded_shanghai_series() -> None:
    service = _FakeResultReadService()
    response = _client(service=service).get(f"/api/v1/backtest-runs/{_RUN_ID}/equity-series")

    assert response.status_code == 200
    assert service.equity_calls == [_RUN_ID]
    assert response.json() == _equity_series_payload()
    assert response.json()["items"][0]["markedAt"].endswith("+08:00")


@pytest.mark.parametrize("params", [{"kind": "DAILY_EQUITY"}, {"cursor": _CURSOR}])
def test_equity_adapter_rejects_every_query_parameter(
    params: Mapping[str, str],
) -> None:
    service = _FakeResultReadService()
    response = _client(service=service).get(
        f"/api/v1/backtest-runs/{_RUN_ID}/equity-series", params=params
    )
    _assert_error(response, status=422, code="VALIDATION_ERROR")
    assert service.equity_calls == []


@pytest.mark.parametrize(
    ("resource", "params"),
    [
        ("fills", [("limit", "20"), ("limit", "30")]),
        ("details", [("kind", "SIGNAL"), ("kind", "DECISION")]),
    ],
)
def test_paginated_result_adapters_reject_repeated_query_parameters(
    resource: str,
    params: list[tuple[str, str]],
) -> None:
    service = _FakeResultReadService()
    response = _client(service=service).get(
        f"/api/v1/backtest-runs/{_RUN_ID}/{resource}", params=params
    )
    _assert_error(response, status=422, code="VALIDATION_ERROR")
    assert service.fill_calls == []
    assert service.detail_calls == []


@pytest.mark.parametrize("availability", ["EXPIRED", "NOT_RECORDED"])
def test_equity_adapter_preserves_exact_unavailable_empty_shape(
    availability: str,
) -> None:
    service = _FakeResultReadService()
    service.equity_result = BacktestEquitySeries.model_validate(
        _equity_series_payload(availability=availability)
    )
    response = _client(service=service).get(f"/api/v1/backtest-runs/{_RUN_ID}/equity-series")

    assert response.status_code == 200
    assert response.json() == _equity_series_payload(availability=availability)
    assert len(service.equity_calls) == 1


@pytest.mark.parametrize(
    "service_value",
    [
        _equity_series_payload(run_id=_OTHER_RUN_ID),
        _equity_series_payload() | {"reportPath": "C:/private/report.json"},
        {"availability": "AVAILABLE", "items": []},
        {"availability": "EXPIRED", "items": [_equity_payload()]},
    ],
)
def test_equity_adapter_revalidates_identity_availability_and_closed_output(
    service_value: object,
) -> None:
    service = _FakeResultReadService()
    service.equity_result = service_value
    response = _client(service=service).get(f"/api/v1/backtest-runs/{_RUN_ID}/equity-series")
    _assert_error(response, status=500, code="INTERNAL_ERROR")
    assert "private" not in response.text


@pytest.mark.parametrize("resource", ["fills", "details", "equity-series"])
def test_result_adapters_hide_staged_failed_cancelled_and_utc_v1_rows(
    resource: str,
) -> None:
    service = _FakeResultReadService()
    error = ApiError(ApiErrorCode.NOT_FOUND)
    service.fill_result = error
    service.detail_result = error
    service.equity_result = error
    params = {"kind": "SIGNAL"} if resource == "details" else None
    response = _client(service=service).get(
        f"/api/v1/backtest-runs/{_RUN_ID}/{resource}", params=params
    )
    _assert_error(response, status=404, code="NOT_FOUND")
    assert "FAILED" not in response.text
    assert "CANCELLED" not in response.text
    assert "backtest-run-summary-v1" not in response.text


def test_missing_result_service_fails_all_adapters_closed() -> None:
    client = _client()
    responses = (
        client.get(f"/api/v1/backtest-runs/{_RUN_ID}/fills"),
        client.get(f"/api/v1/backtest-runs/{_RUN_ID}/details", params={"kind": "SIGNAL"}),
        client.get(f"/api/v1/backtest-runs/{_RUN_ID}/equity-series"),
    )
    for response in responses:
        _assert_error(response, status=503, code="SERVICE_UNAVAILABLE")


def test_result_router_imports_no_jobs_provider_replay_or_persistence() -> None:
    tree = ast.parse(inspect.getsource(backtest_results))
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
        for forbidden in (
            "tushare",
            "provider",
            "replay",
            "repository",
            "coordinator",
            "backtest.jobs",
        )
    )
