"""Persistent market-index history assembled from immutable projection heads."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.models import (
    MarketIndexBar,
    MarketIndexInterval,
    MarketIndexSourceKind,
)
from trade_plan_monitor.market_index.snapshots import build_market_index_snapshot
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
from trade_plan_monitor.web.backtest_pagination import BacktestApiCursorSigner
from trade_plan_monitor.web.monitor_composition import create_monitor_composition
from trade_plan_monitor.web.persistent_market_index_history import (
    PersistentMarketIndexHistorySource,
)
from trade_plan_monitor.web.routers.market_indexes import SignedMarketIndexHistoryService

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_START = datetime(2026, 9, 10, 9, 30, tzinfo=_SHANGHAI)
_END = datetime(2026, 9, 10, 15, 0, tzinfo=_SHANGHAI)


def _bar(bar_at: datetime, *, close: str, revision: int) -> MarketIndexBar:
    close_points = Decimal(close)
    return MarketIndexBar(
        index_code=MarketIndexCode.SSE_COMPOSITE,
        interval=MarketIndexInterval.FIVE_MINUTE,
        bar_at=bar_at,
        open_points=close_points,
        high_points=close_points,
        low_points=close_points,
        close_points=close_points,
        volume=Decimal("1"),
        amount=Decimal("1"),
        observed_at=bar_at + timedelta(seconds=2),
        source_kind=MarketIndexSourceKind.PROVISIONAL,
        provider_revision=revision,
    )


def _daily_bar(observed_at: datetime, *, revision: int) -> MarketIndexBar:
    return MarketIndexBar(
        index_code=MarketIndexCode.SSE_COMPOSITE,
        interval=MarketIndexInterval.OFFICIAL_DAILY,
        bar_at=datetime(2026, 9, 9, 15, 0, tzinfo=_SHANGHAI),
        open_points=Decimal("3200"),
        high_points=Decimal("3200"),
        low_points=Decimal("3200"),
        close_points=Decimal("3200"),
        volume=Decimal("1"),
        amount=Decimal("1"),
        observed_at=observed_at,
        source_kind=MarketIndexSourceKind.OFFICIAL,
        provider_revision=revision,
    )


def test_persistent_history_replays_current_head_bars_in_time_order(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.sqlite3")
    upgrade_database(engine)
    session_factory = create_session_factory(engine)

    def unit_of_work_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory)

    try:
        with unit_of_work_factory() as work:
            for offset, close in ((5, "3210"), (10, "3220")):
                bar_at = _START + timedelta(minutes=offset)
                snapshot = build_market_index_snapshot(
                    index_code=MarketIndexCode.SSE_COMPOSITE,
                    decision_cutoff=bar_at,
                    requests=(),
                    five_minute_bars=(_bar(bar_at, close=close, revision=offset),),
                    official_daily_bars=(
                        _daily_bar(bar_at + timedelta(seconds=2), revision=offset),
                    ),
                    content_revision=offset,
                    observed_at=bar_at + timedelta(seconds=2),
                    observed_no_later_than=bar_at + timedelta(seconds=2),
                )
                work.projections.put_market_index_snapshot(
                    snapshot,
                    provider_content_revision=offset,
                )
                work.projections.advance_market_index_head(
                    snapshot,
                    provider_content_revision=offset,
                )
            work.commit()

        service = SignedMarketIndexHistoryService(
            source=PersistentMarketIndexHistorySource(unit_of_work_factory),
            cursor_signer=BacktestApiCursorSigner(b"i" * 32),
        )
        page = asyncio.run(
            service.list_market_index_bars(
                index_code=MarketIndexCode.SSE_COMPOSITE,
                interval=MarketIndexInterval.FIVE_MINUTE,
                start_at=_START,
                end_at=_END,
                limit=64,
                cursor=None,
            )
        )

        assert page is not None
        assert tuple(item.bar_at for item in page.items) == (
            _START + timedelta(minutes=5),
            _START + timedelta(minutes=10),
        )
        assert tuple(item.close_points for item in page.items) == (
            Decimal("3210"),
            Decimal("3220"),
        )
        assert page.has_more is False
    finally:
        engine.dispose()


def test_persistent_history_returns_no_anchor_when_no_bar_exists(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.sqlite3")
    upgrade_database(engine)
    session_factory = create_session_factory(engine)
    source = PersistentMarketIndexHistorySource(
        lambda: SqlAlchemyUnitOfWork(session_factory)
    )
    try:
        anchor = asyncio.run(
            source.capture_market_index_history(
                index_code=MarketIndexCode.SSE_COMPOSITE,
                interval=MarketIndexInterval.FIVE_MINUTE,
                start_at=_START,
                end_at=_END,
            )
        )
        assert anchor is None
    finally:
        engine.dispose()


def test_default_monitor_composition_wires_persistent_index_history(tmp_path: Path) -> None:
    composition = create_monitor_composition(
        config_path=tmp_path / "app.yaml",
        database_path=tmp_path / "monitor.sqlite3",
    )

    assert isinstance(
        composition.market_index_read_service,
        SignedMarketIndexHistoryService,
    )
