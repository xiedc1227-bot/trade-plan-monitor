from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.models import (
    MarketIndexBar,
    MarketIndexInterval,
    MarketIndexSourceKind,
)
from trade_plan_monitor.state.events import (
    MonitorEventDraft,
    MonitorEventPayload,
    MonitorEventType,
)
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.backtest_pagination import BacktestApiCursorSigner
from trade_plan_monitor.web.routers.dashboard import (
    DashboardResponse,
    IndexConditionProgressView,
    MarketIndexSnapshotView,
    SymbolReferenceMarketView,
)
from trade_plan_monitor.web.routers.market_indexes import (
    MarketIndexBarPage,
    MarketIndexHistoryAnchor,
    SignedMarketIndexHistoryService,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
AT = datetime(2026, 9, 2, 10, 35, tzinfo=SHANGHAI)
OBSERVED_AT = datetime(2026, 9, 2, 10, 35, 2, tzinfo=SHANGHAI)
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
CURSOR = "signed.cursor"


def _shared_snapshot() -> dict[str, object]:
    return {
        "indexCode": "000688.SH",
        "displayName": "科创50",
        "board": "STAR_MARKET",
        "closePoints": "1234.56",
        "priorClosePoints": "1220.11",
        "sessionChangeRatio": "0.011843",
        "completedBucketAt": AT.isoformat(),
        "observedAt": OBSERVED_AT.isoformat(),
        "health": "LIVE",
        "issues": [],
        "indicatorFacts": [
            {
                "formulaId": "SMA",
                "period": 20,
                "value": "1212.34",
                "unit": "POINTS",
                "sourceBarHash": HASH_B,
                "formulaDefinitionHash": HASH_C,
            }
        ],
        "mappedSymbolCount": 2,
        "mappingVersion": "board-index-map-v1",
        "revision": 42,
        "snapshotHash": HASH_A,
    }


def _blocked_shared_snapshot() -> dict[str, object]:
    snapshot = _shared_snapshot()
    snapshot.update(
        {
            "closePoints": None,
            "priorClosePoints": None,
            "sessionChangeRatio": None,
            "completedBucketAt": None,
            "health": "BLOCKED",
            "issues": ["PROVIDER_UNAVAILABLE"],
            "indicatorFacts": [],
        }
    )
    return snapshot


def _dashboard_payload() -> dict[str, object]:
    return {
        "sequence": 7,
        "runtimeGeneration": "11111111-1111-4111-8111-111111111111",
        "observedAt": OBSERVED_AT.isoformat(),
        "connectionStatus": "UNKNOWN",
        "dataAgeSeconds": None,
        "counts": {
            "actionable": 0,
            "lowZoneWatch": 0,
            "blocked": 0,
            "risk": 0,
            "stale": 0,
            "normal": 0,
        },
        "symbols": [],
        "marketIndexes": [_shared_snapshot()],
    }


class _MonitorReadService:
    async def get_dashboard(self) -> object:
        return deepcopy(_dashboard_payload())


class _MarketIndexReadService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def list_market_index_bars(self, **request: object) -> object:
        self.calls.append(request)
        return {
            "items": [
                {
                    "indexCode": "000688.SH",
                    "interval": "FIVE_MINUTE",
                    "barAt": AT.isoformat(),
                    "openPoints": "1230.1",
                    "highPoints": "1235.2",
                    "lowPoints": "1229.9",
                    "closePoints": "1234.56",
                    "volume": "1000",
                    "amount": None,
                    "observedAt": OBSERVED_AT.isoformat(),
                    "sourceKind": "PROVISIONAL",
                    "providerRevision": 3,
                }
            ],
            "limit": request["limit"],
            "nextCursor": CURSOR,
            "hasMore": True,
            "snapshotHash": HASH_A,
        }


def _index_bar(bar_at: datetime, revision: int) -> MarketIndexBar:
    return MarketIndexBar(
        index_code=MarketIndexCode.STAR_50,
        interval=MarketIndexInterval.FIVE_MINUTE,
        bar_at=bar_at,
        open_points=Decimal("1230.1"),
        high_points=Decimal("1235.2"),
        low_points=Decimal("1229.9"),
        close_points=Decimal("1234.56"),
        volume=Decimal("1000"),
        amount=None,
        observed_at=bar_at + timedelta(seconds=2),
        source_kind=MarketIndexSourceKind.PROVISIONAL,
        provider_revision=revision,
    )


class _HistorySource:
    def __init__(self) -> None:
        self.bars = (
            _index_bar(AT, 3),
            _index_bar(datetime(2026, 9, 2, 10, 40, tzinfo=SHANGHAI), 4),
        )
        self.snapshot_hashes: list[str] = []

    async def capture_market_index_history(self, **_request: object) -> object:
        return MarketIndexHistoryAnchor(
            high_water_at=self.bars[-1].bar_at,
            snapshot_hash=HASH_A,
        )

    async def read_market_index_history(self, **request: object) -> object:
        self.snapshot_hashes.append(str(request["snapshot_hash"]))
        after_at = request["after_at"]
        limit = int(request["limit"])
        return tuple(bar for bar in self.bars if after_at is None or bar.bar_at > after_at)[:limit]


def test_dashboard_keeps_shared_index_facts_plan_neutral() -> None:
    app = create_app(read_service=_MonitorReadService())

    response = TestClient(app).get("/api/v1/dashboard")

    assert response.status_code == 200
    item = response.json()["marketIndexes"][0]
    assert item["closePoints"] == "1234.56"
    assert item["indicatorFacts"][0]["period"] == 20
    forbidden = {"planId", "conditionProgress", "entryAllowed", "decisionEffect"}
    assert forbidden.isdisjoint(item)


def test_dashboard_serializes_required_nullable_fields_explicitly() -> None:
    class BlockedIndexReadService:
        async def get_dashboard(self) -> object:
            payload = _dashboard_payload()
            payload["marketIndexes"] = [_blocked_shared_snapshot()]
            return payload

    response = TestClient(create_app(read_service=BlockedIndexReadService())).get(
        "/api/v1/dashboard"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["dataAgeSeconds"] is None
    blocked = body["marketIndexes"][0]
    assert blocked["closePoints"] is None
    assert blocked["priorClosePoints"] is None
    assert blocked["sessionChangeRatio"] is None
    assert blocked["completedBucketAt"] is None


def test_shared_snapshot_requires_sorted_unique_items_and_canonical_identity() -> None:
    payload = _dashboard_payload()
    payload["marketIndexes"] = [_shared_snapshot(), _shared_snapshot()]
    with pytest.raises(ValidationError, match="unique"):
        DashboardResponse.model_validate_json(json.dumps(payload))

    payload = _shared_snapshot()
    payload["displayName"] = "创业板指"
    with pytest.raises(ValidationError, match="identity"):
        MarketIndexSnapshotView.model_validate_json(json.dumps(payload))


def test_plan_reference_progress_is_separate_and_zero_means_not_used() -> None:
    unused = SymbolReferenceMarketView.model_validate_json(
        json.dumps(
            {
                "indexCode": "000688.SH",
                "displayName": "科创50",
                "board": "STAR_MARKET",
                "mappingVersion": "board-index-map-v1",
                "snapshotHash": None,
                "dataAt": None,
                "health": "BLOCKED",
                "issues": ["PROVIDER_UNAVAILABLE"],
                "conditionProgress": {
                    "satisfied": 0,
                    "unsatisfied": 0,
                    "missing": 0,
                    "total": 0,
                },
            }
        )
    )
    assert unused.condition_progress.total == 0

    with pytest.raises(ValidationError, match="sum"):
        IndexConditionProgressView(
            satisfied=1,
            unsatisfied=1,
            missing=0,
            total=1,
        )


def test_index_history_route_passes_only_validated_bounded_query_to_service() -> None:
    service = _MarketIndexReadService()
    app = create_app(market_index_read_service=service)
    client = TestClient(app)

    response = client.get(
        "/api/v1/market-indexes/000688.SH/bars",
        params={
            "interval": "FIVE_MINUTE",
            "startAt": "2026-09-01T09:35:00+08:00",
            "endAt": "2026-09-02T15:00:00+08:00",
            "limit": 2000,
            "cursor": CURSOR,
        },
    )

    assert response.status_code == 200
    assert response.json()["snapshotHash"] == HASH_A
    assert response.json()["items"][0]["closePoints"] == "1234.56"
    assert service.calls == [
        {
            "index_code": "000688.SH",
            "interval": "FIVE_MINUTE",
            "start_at": datetime(2026, 9, 1, 9, 35, tzinfo=SHANGHAI),
            "end_at": datetime(2026, 9, 2, 15, 0, tzinfo=SHANGHAI),
            "limit": 2000,
            "cursor": CURSOR,
        }
    ]


def test_signed_history_service_freezes_snapshot_and_rejects_cursor_rebinding() -> None:
    source = _HistorySource()
    service = SignedMarketIndexHistoryService(
        source=source,
        cursor_signer=BacktestApiCursorSigner(b"i" * 32),
    )
    client = TestClient(create_app(market_index_read_service=service))
    params = {
        "interval": "FIVE_MINUTE",
        "startAt": "2026-09-02T10:30:00+08:00",
        "endAt": "2026-09-02T10:45:00+08:00",
        "limit": 1,
    }

    first = client.get("/api/v1/market-indexes/000688.SH/bars", params=params)

    assert first.status_code == 200
    first_body = first.json()
    assert first_body["hasMore"] is True
    assert first_body["snapshotHash"] == HASH_A
    assert first_body["items"][0]["barAt"] == AT.isoformat()

    second = client.get(
        "/api/v1/market-indexes/000688.SH/bars",
        params={**params, "cursor": first_body["nextCursor"]},
    )
    assert second.status_code == 200
    assert second.json()["hasMore"] is False
    assert second.json()["snapshotHash"] == HASH_A
    assert source.snapshot_hashes == [HASH_A, HASH_A]

    rebound = client.get(
        "/api/v1/market-indexes/000688.SH/bars",
        params={
            **params,
            "endAt": "2026-09-02T10:50:00+08:00",
            "cursor": first_body["nextCursor"],
        },
    )
    assert rebound.status_code == 422
    assert rebound.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    ("path", "params"),
    [
        (
            "/api/v1/market-indexes/999999.SH/bars",
            {
                "interval": "FIVE_MINUTE",
                "startAt": "2026-09-01T09:35:00+08:00",
                "endAt": "2026-09-02T15:00:00+08:00",
                "limit": 20,
            },
        ),
        (
            "/api/v1/market-indexes/000688.SH/bars",
            {
                "interval": "FIVE_MINUTE",
                "startAt": "2026-08-01T09:35:00+08:00",
                "endAt": "2026-09-02T15:00:00+08:00",
                "limit": 20,
            },
        ),
        (
            "/api/v1/market-indexes/000688.SH/bars",
            {
                "interval": "OFFICIAL_DAILY",
                "startAt": "2016-09-01T15:00:00+08:00",
                "endAt": "2026-09-02T15:00:00+08:00",
                "limit": 20,
            },
        ),
    ],
)
def test_index_history_rejects_unknown_identity_and_oversized_ranges(
    path: str,
    params: dict[str, object],
) -> None:
    service = _MarketIndexReadService()
    response = TestClient(create_app(market_index_read_service=service)).get(
        path,
        params=params,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert service.calls == []


def test_history_page_rejects_wrong_identity_order_and_cursor_shape() -> None:
    base = {
        "items": [
            {
                "indexCode": "000688.SH",
                "interval": "FIVE_MINUTE",
                "barAt": AT,
                "openPoints": Decimal("1230.1"),
                "highPoints": Decimal("1235.2"),
                "lowPoints": Decimal("1229.9"),
                "closePoints": Decimal("1234.56"),
                "volume": Decimal("1000"),
                "amount": None,
                "observedAt": OBSERVED_AT,
                "sourceKind": "PROVISIONAL",
                "providerRevision": 3,
            }
        ],
        "limit": 20,
        "nextCursor": CURSOR,
        "hasMore": True,
        "snapshotHash": HASH_A,
    }
    MarketIndexBarPage.model_validate_json(json.dumps(base, default=str))

    malformed = deepcopy(base)
    malformed["hasMore"] = False
    with pytest.raises(ValidationError, match="agree"):
        MarketIndexBarPage.model_validate_json(json.dumps(malformed, default=str))

    malformed = deepcopy(base)
    malformed["items"] = [base["items"][0], base["items"][0]]
    with pytest.raises(ValidationError, match="strictly increasing"):
        MarketIndexBarPage.model_validate_json(json.dumps(malformed, default=str))


def test_market_index_invalidation_has_exact_plan_neutral_payload() -> None:
    event = MonitorEventDraft(
        event_id=UUID(int=91),
        event_type=MonitorEventType.MARKET_INDEX_UPDATED,
        aggregate_id="000688.SH",
        payload=MonitorEventPayload(
            entity_id="000688.SH",
            revision=42,
            status="LIVE",
        ),
        occurred_at=OBSERVED_AT,
    )

    assert event.model_dump(mode="json", by_alias=True)["payload"] == {
        "entityId": "000688.SH",
        "symbol": None,
        "revision": 42,
        "status": "LIVE",
        "resultHash": None,
    }

    with pytest.raises(ValidationError, match="payload fields"):
        MonitorEventDraft(
            event_id=UUID(int=92),
            event_type=MonitorEventType.MARKET_INDEX_UPDATED,
            aggregate_id="000688.SH",
            payload=MonitorEventPayload(
                entity_id="000688.SH",
                symbol="688981.SH",
                revision=42,
                status="LIVE",
            ),
            occurred_at=OBSERVED_AT,
        )
