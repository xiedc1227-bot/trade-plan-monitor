from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.backtest_schemas import (
    BacktestIndexConditionSummaryView,
    BacktestMarketIndexPointView,
    BacktestMarketIndexSeriesView,
    BacktestReferenceMarketBindingView,
    BacktestReferenceMarketView,
)
from trade_plan_monitor.web.routers.backtest_results import (
    downsample_market_index_points,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
RUN_ID = "1" * 64
DATASET_HASH = "2" * 64
DATA_HASH = "3" * 64
REQUIREMENT_HASH = "4" * 64
FORMULA_HASH = "5" * 64
SNAPSHOT_HASH = "6" * 64


def _reference_market() -> BacktestReferenceMarketView:
    summary = BacktestIndexConditionSummaryView.model_validate(
        {
            "planPath": "entry.condition.conditions[0]",
            "conditionType": "INDEX_CLOSE_GTE_MA",
            "parameters": {"period": 20},
            "formulaId": "SMA",
            "satisfiedCount": 3,
            "unsatisfiedCount": 1,
            "missingCount": 0,
            "applicableBranchCount": 4,
        }
    )
    return BacktestReferenceMarketView.model_validate(
        {
            "binding": {
                "selection": "AUTO_BOARD",
                "mappingVersion": "board-index-map-v1",
                "indexCode": "399001.SZ",
                "displayName": "深证成指",
                "board": "SZSE_MAIN",
            },
            "required": True,
            "conditionPaths": ["entry.condition.conditions[0]"],
            "warmupStart": "2026-07-30",
            "coverageStatus": "AVAILABLE",
            "blockers": [],
            "marketIndexDataHash": DATA_HASH,
            "indexRequirementHash": REQUIREMENT_HASH,
            "formulaDefinitionHash": FORMULA_HASH,
            "datasetHash": DATASET_HASH,
            "conditionSummaries": [summary.model_dump(mode="json", by_alias=True)],
        }
    )


def _point(day: int) -> BacktestMarketIndexPointView:
    return BacktestMarketIndexPointView.model_validate(
        {
            "tradeDate": date(2026, 8, day).isoformat(),
            "dataAt": datetime(2026, 8, day, 15, 0, tzinfo=SHANGHAI).isoformat(),
            "closePoints": str(3000 + day),
            "snapshotHash": SNAPSHOT_HASH,
            "indicatorFacts": [],
            "health": "LIVE",
            "issues": [],
        }
    )


class _SeriesService:
    def __init__(self, value: BacktestMarketIndexSeriesView) -> None:
        self.value = value
        self.requests: list[dict[str, object]] = []

    async def get_market_index_series(self, **request: object) -> object:
        self.requests.append(request)
        return self.value


def test_old_run_series_is_explicitly_empty_without_synthetic_history() -> None:
    service = _SeriesService(
        BacktestMarketIndexSeriesView.model_validate(
            {
                "runId": RUN_ID,
                "referenceMarket": None,
                "items": [],
                "healthTimeline": [],
                "conditionSummaries": [],
            }
        )
    )
    response = TestClient(create_app(backtest_read_service=service)).get(
        f"/api/v1/backtest-runs/{RUN_ID}/market-index-series"
    )

    assert response.status_code == 200
    assert response.json() == {
        "runId": RUN_ID,
        "referenceMarket": None,
        "items": [],
        "healthTimeline": [],
        "conditionSummaries": [],
    }


def test_index_series_preserves_backend_binding_hashes_and_path_counts() -> None:
    reference = _reference_market()
    summary = reference.condition_summaries[0]
    service = _SeriesService(
        BacktestMarketIndexSeriesView.model_validate(
            {
                "runId": RUN_ID,
                "referenceMarket": reference.model_dump(mode="json", by_alias=True),
                "items": [_point(1).model_dump(mode="json", by_alias=True)],
                "healthTimeline": [
                    {
                        "dataAt": "2026-08-01T15:00:00+08:00",
                        "health": "LIVE",
                        "issues": [],
                    }
                ],
                "conditionSummaries": [summary.model_dump(mode="json", by_alias=True)],
            }
        )
    )
    response = TestClient(create_app(backtest_read_service=service)).get(
        f"/api/v1/backtest-runs/{RUN_ID}/market-index-series",
        params={"startOn": "2026-08-01", "endOn": "2026-08-31", "limit": 128},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["referenceMarket"]["binding"] == {
        "selection": "AUTO_BOARD",
        "mappingVersion": "board-index-map-v1",
        "indexCode": "399001.SZ",
        "displayName": "深证成指",
        "board": "SZSE_MAIN",
    }
    assert body["conditionSummaries"][0]["planPath"] == ("entry.condition.conditions[0]")
    assert service.requests == [
        {
            "run_id": RUN_ID,
            "start_on": date(2026, 8, 1),
            "end_on": date(2026, 8, 31),
            "limit": 128,
        }
    ]


def test_series_query_is_closed_and_range_is_validated_before_service() -> None:
    empty = BacktestMarketIndexSeriesView.model_validate(
        {
            "runId": RUN_ID,
            "referenceMarket": None,
            "items": [],
            "healthTimeline": [],
            "conditionSummaries": [],
        }
    )
    service = _SeriesService(empty)
    client = TestClient(create_app(backtest_read_service=service))

    assert (
        client.get(f"/api/v1/backtest-runs/{RUN_ID}/market-index-series?limit=513").status_code
        == 422
    )
    assert (
        client.get(
            f"/api/v1/backtest-runs/{RUN_ID}/market-index-series"
            "?startOn=2026-09-01&endOn=2026-08-01"
        ).status_code
        == 422
    )
    assert (
        client.get(f"/api/v1/backtest-runs/{RUN_ID}/market-index-series?unknown=1").status_code
        == 422
    )
    assert service.requests == []


def test_display_downsampling_is_deterministic_and_preserves_first_and_last() -> None:
    points = tuple(_point(day) for day in range(1, 11))

    first = downsample_market_index_points(points, limit=4)
    second = downsample_market_index_points(points, limit=4)

    assert first == second
    assert first[0] is points[0]
    assert first[-1] is points[-1]
    assert tuple(point.trade_date.day for point in first) == (1, 4, 7, 10)
    assert all(isinstance(point.close_points, Decimal) for point in first)


def test_reference_binding_rejects_wrong_derived_display_identity() -> None:
    try:
        BacktestReferenceMarketBindingView.model_validate(
            {
                "selection": "AUTO_BOARD",
                "mappingVersion": "board-index-map-v1",
                "indexCode": "399001.SZ",
                "displayName": "上证指数",
                "board": "SZSE_MAIN",
            }
        )
    except ValueError:
        pass
    else:  # pragma: no cover - assertion branch
        raise AssertionError("wrong server binding identity must fail closed")
