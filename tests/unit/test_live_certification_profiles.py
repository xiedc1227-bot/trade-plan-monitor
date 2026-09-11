"""Durable, sanitized stock/index certification profile contracts."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from trade_plan_monitor.live_profiles import (
    CERTIFICATION_MAX_AGE,
    StockLiveCertification,
    create_index_certification,
    create_stock_certification,
    load_index_certification,
    load_stock_certification,
    write_live_certification,
)
from trade_plan_monitor.market_data.models import (
    ProviderCapabilities,
    ProviderCapabilityStatus,
)
from trade_plan_monitor.market_data.sessions import SourceTimeLabel
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.tushare import (
    TushareMarketIndexCapabilityStatus,
    TushareMarketIndexSourceTimeLabel,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
OBSERVED_AT = datetime(2026, 9, 7, 10, 15, tzinfo=SHANGHAI)
ENDPOINT = "https://api.quicksync.cn"


def _stock_profile() -> StockLiveCertification:
    return create_stock_certification(
        observed_at=OBSERVED_AT,
        endpoint_url=ENDPOINT,
        capabilities=ProviderCapabilities(
            realtime_minutes=ProviderCapabilityStatus.READY,
            current_day_minutes=ProviderCapabilityStatus.READY,
            trading_calendar=ProviderCapabilityStatus.READY,
            daily_limits=ProviderCapabilityStatus.READY,
            daily_bars=ProviderCapabilityStatus.READY,
        ),
        source_time_label=SourceTimeLabel.END,
    )


def test_stock_profile_round_trip_is_hash_checked_and_secret_free(tmp_path: Path) -> None:
    path = tmp_path / "stock.json"
    profile = _stock_profile()

    write_live_certification(path, profile)
    loaded = load_stock_certification(
        path,
        now=OBSERVED_AT + timedelta(hours=1),
        endpoint_url=ENDPOINT,
    )

    assert loaded == profile
    assert loaded is not None and loaded.ready
    document = path.read_text(encoding="utf-8")
    assert "TUSHARE_TOKEN" not in document
    assert "authorization" not in document.casefold()
    assert "secret" not in document.casefold()


def test_stock_profile_expires_at_the_exact_freshness_boundary(tmp_path: Path) -> None:
    path = tmp_path / "stock.json"
    profile = _stock_profile()
    write_live_certification(path, profile)

    assert (
        load_stock_certification(
            path,
            now=OBSERVED_AT + CERTIFICATION_MAX_AGE,
            endpoint_url=ENDPOINT,
        )
        == profile
    )
    assert (
        load_stock_certification(
            path,
            now=OBSERVED_AT + CERTIFICATION_MAX_AGE + timedelta(microseconds=1),
            endpoint_url=ENDPOINT,
        )
        is None
    )


def test_modified_profile_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "stock.json"
    write_live_certification(path, _stock_profile())
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["sourceTimeLabel"] = "START"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert load_stock_certification(path, now=OBSERVED_AT, endpoint_url=ENDPOINT) is None


def test_index_profile_is_independent_and_can_defer_bse_50(
    tmp_path: Path,
) -> None:
    path = tmp_path / "index.json"
    profile = create_index_certification(
        observed_at=OBSERVED_AT,
        endpoint_url=ENDPOINT,
        capabilities={
            code: (
                TushareMarketIndexCapabilityStatus.DEFERRED
                if code is MarketIndexCode.BSE_50
                else TushareMarketIndexCapabilityStatus.READY
            )
            for code in MarketIndexCode
        },
        source_time_label=TushareMarketIndexSourceTimeLabel.END,
    )
    write_live_certification(path, profile)

    loaded = load_index_certification(
        path,
        now=OBSERVED_AT + timedelta(hours=1),
        endpoint_url=ENDPOINT,
    )

    assert loaded == profile
    assert loaded is not None and loaded.ready_indexes == frozenset(
        code for code in MarketIndexCode if code is not MarketIndexCode.BSE_50
    )
    assert load_stock_certification(path, now=OBSERVED_AT, endpoint_url=ENDPOINT) is None


def test_legacy_index_profile_remains_valid_without_turnover_benchmark(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy-index.json"
    profile = create_index_certification(
        observed_at=OBSERVED_AT,
        endpoint_url=ENDPOINT,
        capabilities={
            code: (
                TushareMarketIndexCapabilityStatus.DEFERRED
                if code is MarketIndexCode.BSE_50
                else TushareMarketIndexCapabilityStatus.READY
            )
            for code in MarketIndexCode
        },
        source_time_label=TushareMarketIndexSourceTimeLabel.END,
    )
    payload = profile.model_dump(mode="json", by_alias=True)
    del payload["capabilities"][MarketIndexCode.SHENZHEN_A_SHARE.value]
    payload_without_hash = {
        key: value for key, value in payload.items() if key != "evidenceHash"
    }
    encoded = json.dumps(
        payload_without_hash,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    payload["evidenceHash"] = sha256(encoded).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_index_certification(
        path,
        now=OBSERVED_AT + timedelta(hours=1),
        endpoint_url=ENDPOINT,
    )

    assert loaded is not None
    assert MarketIndexCode.SHENZHEN_A_SHARE not in loaded.capabilities
    assert MarketIndexCode.SHENZHEN_A_SHARE not in loaded.ready_indexes


def test_index_certification_rejects_ready_bse_50_while_live_scope_is_deferred() -> None:
    with pytest.raises(ValueError, match="BSE 50 live index is deferred"):
        create_index_certification(
            observed_at=OBSERVED_AT,
            endpoint_url=ENDPOINT,
            capabilities={
                code: TushareMarketIndexCapabilityStatus.READY for code in MarketIndexCode
            },
            source_time_label=TushareMarketIndexSourceTimeLabel.END,
        )
