from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import inspect

from trade_plan_monitor.market_data.models import DailyBar, DailyLimit, MinuteBar, TradingDay
from trade_plan_monitor.market_data.reconciliation import (
    CloseReconciliationStatus,
    reconcile_daily_close,
)
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.repositories import (
    MarketDataIdentityConflictError,
    MarketHistoryRepository,
    MarketReferenceRepository,
    RepositoryError,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _time(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 8, 21, hour, minute, second, tzinfo=SHANGHAI)


def _minute_bar(
    *,
    symbol: str = "003043.SZ",
    minute: int = 31,
    close_fen: int = 6_430,
    high_fen: int = 6_450,
    received_at: datetime | None = None,
    amount_yuan: Decimal = Decimal("8079200.50"),
) -> MinuteBar:
    bar_end = _time(9, minute)
    return MinuteBar(
        symbol=symbol,
        bar_end=bar_end,
        open_fen=6_400,
        high_fen=high_fen,
        low_fen=6_380,
        close_fen=close_fen,
        volume_shares=125_600,
        amount_yuan=amount_yuan,
        received_at=received_at or bar_end + timedelta(seconds=12),
    )


def _daily_bar(
    *,
    official: bool,
    close_fen: int,
    received_at: datetime,
) -> DailyBar:
    return DailyBar(
        symbol="003043.SZ",
        trade_date=date(2026, 8, 21),
        open_fen=6_400,
        high_fen=6_900,
        low_fen=6_350,
        close_fen=close_fen,
        volume_shares=52_515_277,
        amount_yuan=Decimal("460697377.25"),
        is_official=official,
        received_at=received_at,
    )


def _repositories(tmp_path: Path):
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    upgrade_database(engine)
    return engine, create_session_factory(engine)


def test_minute_upserts_are_idempotent_reordered_and_survive_restart(
    tmp_path: Path,
) -> None:
    engine, sessions = _repositories(tmp_path)
    first = _minute_bar(minute=31, amount_yuan=Decimal("8079200.50"))
    second = _minute_bar(minute=32, close_fen=6_440, amount_yuan=Decimal("9000000.01"))

    try:
        with sessions.begin() as session:
            history = MarketHistoryRepository(session)
            history.upsert_minutes([second, first, first])

        with sessions.begin() as session:
            history = MarketHistoryRepository(session)
            history.upsert_minutes([first, second])

        with sessions() as session:
            history = MarketHistoryRepository(session)
            persisted = history.list_minutes(
                "003043.SZ",
                start=_time(9, 31),
                end=_time(9, 32),
            )
            latest = history.get_latest_quote("003043.SZ")

        assert persisted == (first, second)
        assert persisted[0].amount_yuan == Decimal("8079200.50")
        assert persisted[0].volume_shares == 125_600
        assert persisted[0].bar_end == _time(9, 31)
        assert persisted[0].received_at == _time(9, 31, 12)
        assert latest is not None
        assert latest.symbol == "003043.SZ"
        assert latest.price_fen == 6_440
        assert latest.bar_end == _time(9, 32)
        assert latest.received_at == _time(9, 32, 12)
    finally:
        engine.dispose()


def test_latest_quote_ignores_older_bars_and_accepts_newer_same_bar_correction(
    tmp_path: Path,
) -> None:
    engine, sessions = _repositories(tmp_path)
    current = _minute_bar(minute=32, close_fen=6_440)
    older = _minute_bar(minute=31, close_fen=6_420, received_at=_time(9, 35))
    corrected = _minute_bar(
        minute=32,
        close_fen=6_460,
        high_fen=6_500,
        received_at=_time(9, 34),
    )

    try:
        with sessions.begin() as session:
            history = MarketHistoryRepository(session)
            history.upsert_minutes([current])
            history.upsert_minutes([older])
            assert history.get_latest_quote("003043.SZ").price_fen == 6_440
            history.upsert_minutes([corrected])
            latest = history.get_latest_quote("003043.SZ")

        assert latest is not None
        assert latest.price_fen == 6_460
        assert latest.bar_end == corrected.bar_end
        assert latest.received_at == corrected.received_at
    finally:
        engine.dispose()


def test_equal_receipt_minute_conflict_cannot_corrupt_history_or_latest_quote(
    tmp_path: Path,
) -> None:
    engine, sessions = _repositories(tmp_path)
    original = _minute_bar(minute=32, close_fen=6_440)
    conflicting = original.model_copy(update={"close_fen": 6_445})

    try:
        with sessions.begin() as session:
            MarketHistoryRepository(session).upsert_minutes([original])

        with pytest.raises(MarketDataIdentityConflictError):
            with sessions.begin() as session:
                MarketHistoryRepository(session).upsert_minutes([conflicting])

        with sessions() as session:
            history = MarketHistoryRepository(session)
            assert history.list_minutes(
                "003043.SZ",
                start=_time(9, 32),
                end=_time(9, 32),
            ) == (original,)
            assert history.get_latest_quote("003043.SZ").price_fen == original.close_fen
    finally:
        engine.dispose()


def test_partial_minute_batch_persists_only_validated_healthy_symbols(
    tmp_path: Path,
) -> None:
    engine, sessions = _repositories(tmp_path)
    healthy = [
        _minute_bar(symbol="003043.SZ"),
        _minute_bar(symbol="600519.SH", close_fen=6_440),
    ]

    try:
        with sessions.begin() as session:
            MarketHistoryRepository(session).upsert_minutes(healthy)

        with sessions() as session:
            history = MarketHistoryRepository(session)
            for symbol, expected in (
                ("003043.SZ", (healthy[0],)),
                ("600519.SH", (healthy[1],)),
                ("000001.SZ", ()),
            ):
                assert (
                    history.list_minutes(
                        symbol,
                        start=_time(9, 31),
                        end=_time(9, 31),
                    )
                    == expected
                )
    finally:
        engine.dispose()


def test_five_minute_upserts_are_ordered_idempotent_and_fail_closed_on_conflict(
    tmp_path: Path,
) -> None:
    engine, sessions = _repositories(tmp_path)

    try:
        with sessions.begin() as session:
            history = MarketHistoryRepository(session)
            later = history.upsert_five_minute(
                symbol="003043.SZ",
                bar_end=_time(9, 40),
                formula_version="ta-v1",
                open_fen=6_440,
                high_fen=6_500,
                low_fen=6_420,
                close_fen=6_480,
                volume_shares=620_000,
                amount_yuan=Decimal("40000000.25"),
            )
            earlier = history.upsert_five_minute(
                symbol="003043.SZ",
                bar_end=_time(9, 35),
                formula_version="ta-v1",
                open_fen=6_400,
                high_fen=6_470,
                low_fen=6_380,
                close_fen=6_440,
                volume_shares=600_000,
                amount_yuan=Decimal("39000000.50"),
            )
            assert history.upsert_five_minute(**earlier.model_dump(mode="python")) == earlier

        with sessions.begin() as session:
            history = MarketHistoryRepository(session)
            assert history.list_five_minute(
                "003043.SZ",
                start=_time(9, 35),
                end=_time(9, 40),
                formula_version="ta-v1",
            ) == (earlier, later)
            with pytest.raises(MarketDataIdentityConflictError):
                history.upsert_five_minute(
                    **{
                        **earlier.model_dump(mode="python"),
                        "close_fen": 6_450,
                    }
                )
    finally:
        engine.dispose()


def test_five_minute_upsert_rejects_non_boundary_or_non_session_end(
    tmp_path: Path,
) -> None:
    engine, sessions = _repositories(tmp_path)

    try:
        with sessions.begin() as session:
            history = MarketHistoryRepository(session)
            for invalid_end in (_time(9, 36), _time(12, 0)):
                with pytest.raises(ValueError, match="five-minute|session"):
                    history.upsert_five_minute(
                        symbol="003043.SZ",
                        bar_end=invalid_end,
                        formula_version="ta-v1",
                        open_fen=6_400,
                        high_fen=6_470,
                        low_fen=6_380,
                        close_fen=6_440,
                        volume_shares=600_000,
                        amount_yuan=Decimal("39000000.50"),
                    )
    finally:
        engine.dispose()


def test_market_history_reads_require_explicit_bounded_ranges(tmp_path: Path) -> None:
    engine, sessions = _repositories(tmp_path)

    try:
        with sessions() as session:
            history = MarketHistoryRepository(session)
            with pytest.raises(TypeError):
                history.list_minutes("003043.SZ")
            with pytest.raises(TypeError):
                history.list_five_minute("003043.SZ")
            with pytest.raises(TypeError):
                history.list_daily_bars("003043.SZ")
    finally:
        engine.dispose()


def test_market_history_read_fails_closed_over_repository_row_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, sessions = _repositories(tmp_path)

    try:
        with sessions.begin() as session:
            history = MarketHistoryRepository(session)
            history.upsert_minutes([_minute_bar(minute=31), _minute_bar(minute=32)])

        monkeypatch.setattr(MarketHistoryRepository, "_MAX_READ_ROWS", 1)
        with sessions() as session:
            with pytest.raises(RepositoryError, match="read limit"):
                MarketHistoryRepository(session).list_minutes(
                    "003043.SZ",
                    start=_time(9, 31),
                    end=_time(9, 32),
                )
    finally:
        engine.dispose()


def test_daily_upserts_keep_provisional_and_official_rows_separate(
    tmp_path: Path,
) -> None:
    engine, sessions = _repositories(tmp_path)
    provisional = _daily_bar(official=False, close_fen=6_650, received_at=_time(15, 0, 12))
    official = _daily_bar(official=True, close_fen=6_671, received_at=_time(15, 20))
    corrected = _daily_bar(official=True, close_fen=6_680, received_at=_time(15, 30))

    try:
        with sessions.begin() as session:
            history = MarketHistoryRepository(session)
            history.upsert_daily_bars([official, provisional, provisional])
            history.upsert_daily_bars([corrected, official])

        with sessions() as session:
            persisted = MarketHistoryRepository(session).list_daily_bars(
                "003043.SZ",
                start=date(2026, 8, 21),
                end=date(2026, 8, 21),
            )

        assert persisted == (provisional, corrected)
        assert persisted[1].amount_yuan == Decimal("460697377.25")
        assert persisted[1].volume_shares == 52_515_277
    finally:
        engine.dispose()


def test_daily_close_reconcile_recovers_pending_after_restart_and_is_idempotent(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "monitor.db"
    provisional = _daily_bar(official=False, close_fen=6_650, received_at=_time(15, 0, 12))
    official = _daily_bar(official=True, close_fen=6_671, received_at=_time(17, 0))

    first_engine = create_sqlite_engine(database_path)
    upgrade_database(first_engine)
    first_sessions = create_session_factory(first_engine)
    try:
        with first_sessions.begin() as session:
            MarketHistoryRepository(session).upsert_daily_bars([provisional, provisional])
        with first_sessions() as session:
            persisted = MarketHistoryRepository(session).list_daily_bars(
                provisional.symbol,
                start=provisional.trade_date,
                end=provisional.trade_date,
            )
        before_restart = reconcile_daily_close(
            symbol=provisional.symbol,
            current_trade_date=provisional.trade_date,
            daily_bars=persisted,
        )
        assert before_restart.status is CloseReconciliationStatus.CLOSE_PENDING
        assert before_restart.advance_close_risk is False
    finally:
        first_engine.dispose()

    restarted_engine = create_sqlite_engine(database_path)
    restarted_sessions = create_session_factory(restarted_engine)
    try:
        with restarted_sessions() as session:
            persisted_pending = MarketHistoryRepository(session).list_daily_bars(
                provisional.symbol,
                start=provisional.trade_date,
                end=provisional.trade_date,
            )
        recovered_pending = reconcile_daily_close(
            symbol=provisional.symbol,
            current_trade_date=provisional.trade_date,
            daily_bars=persisted_pending,
        )
        assert recovered_pending == before_restart

        with restarted_sessions.begin() as session:
            MarketHistoryRepository(session).upsert_daily_bars([official, official])
        with restarted_sessions() as session:
            reconciled_rows = MarketHistoryRepository(session).list_daily_bars(
                provisional.symbol,
                start=provisional.trade_date,
                end=provisional.trade_date,
            )
        reconciled = reconcile_daily_close(
            symbol=provisional.symbol,
            current_trade_date=provisional.trade_date,
            daily_bars=reconciled_rows,
        )

        assert reconciled_rows == (provisional, official)
        assert reconciled.status is CloseReconciliationStatus.OFFICIAL_READY
        assert reconciled.advance_close_risk is True
        assert reconciled.close_delta_fen == 21
        assert reconciled.official_bar == official
        assert reconciled == reconcile_daily_close(
            symbol=provisional.symbol,
            current_trade_date=provisional.trade_date,
            daily_bars=reconciled_rows,
        )
    finally:
        restarted_engine.dispose()


def test_calendar_and_daily_limit_upserts_are_idempotent_and_reordered(
    tmp_path: Path,
) -> None:
    engine, sessions = _repositories(tmp_path)
    days = [
        TradingDay(
            exchange="SSE",
            cal_date=date(2026, 8, 22),
            is_open=False,
            previous_trade_date=date(2026, 8, 21),
        ),
        TradingDay(
            exchange="SSE",
            cal_date=date(2026, 8, 21),
            is_open=True,
            previous_trade_date=date(2026, 8, 20),
        ),
    ]
    limits = [
        DailyLimit(
            symbol="600519.SH",
            trade_date=date(2026, 8, 21),
            up_limit_fen=160_000,
            down_limit_fen=130_000,
            received_at=_time(9, 0),
        ),
        DailyLimit(
            symbol="003043.SZ",
            trade_date=date(2026, 8, 21),
            up_limit_fen=7_200,
            down_limit_fen=5_900,
            received_at=_time(9, 0),
        ),
    ]

    try:
        with sessions.begin() as session:
            reference = MarketReferenceRepository(session)
            reference.upsert_trading_days([*days, days[0]])
            reference.upsert_daily_limits([*limits, limits[0]])
            reference.upsert_trading_days(list(reversed(days)))
            reference.upsert_daily_limits(list(reversed(limits)))

        with sessions() as session:
            reference = MarketReferenceRepository(session)
            assert reference.list_trading_days(
                "SSE", date(2026, 8, 21), date(2026, 8, 22)
            ) == tuple(reversed(days))
            assert reference.list_daily_limits(date(2026, 8, 21)) == tuple(
                sorted(limits, key=lambda item: item.symbol)
            )
    finally:
        engine.dispose()


def test_calendar_later_authoritative_fetch_can_correct_same_date(tmp_path: Path) -> None:
    engine, sessions = _repositories(tmp_path)
    initial = TradingDay(
        exchange="SSE",
        cal_date=date(2026, 8, 24),
        is_open=False,
        previous_trade_date=date(2026, 8, 21),
    )
    corrected = initial.model_copy(update={"is_open": True})

    try:
        with sessions.begin() as session:
            reference = MarketReferenceRepository(session)
            reference.upsert_trading_days([initial])
            reference.upsert_trading_days([corrected])

        with sessions() as session:
            assert MarketReferenceRepository(session).list_trading_days(
                "SSE",
                date(2026, 8, 24),
                date(2026, 8, 24),
            ) == (corrected,)
    finally:
        engine.dispose()


def test_daily_limit_newer_receipt_wins_and_stale_replay_is_harmless(
    tmp_path: Path,
) -> None:
    engine, sessions = _repositories(tmp_path)
    initial = DailyLimit(
        symbol="003043.SZ",
        trade_date=date(2026, 8, 21),
        up_limit_fen=7_200,
        down_limit_fen=5_900,
        received_at=_time(9, 0),
    )
    corrected = initial.model_copy(
        update={
            "up_limit_fen": 7_210,
            "received_at": _time(9, 1),
        }
    )

    try:
        with sessions.begin() as session:
            reference = MarketReferenceRepository(session)
            reference.upsert_daily_limits([initial])
            reference.upsert_daily_limits([corrected])
            reference.upsert_daily_limits([initial])

        with sessions() as session:
            assert MarketReferenceRepository(session).list_daily_limits(date(2026, 8, 21)) == (
                corrected,
            )
    finally:
        engine.dispose()


def test_market_batches_reject_unbounded_iterators_and_oversized_lists(
    tmp_path: Path,
) -> None:
    engine, sessions = _repositories(tmp_path)
    bar = _minute_bar()

    try:
        with sessions.begin() as session:
            history = MarketHistoryRepository(session)
            with pytest.raises(TypeError, match="list or tuple"):
                history.upsert_minutes(iter([bar]))
            with pytest.raises(ValueError, match="1000"):
                history.upsert_minutes([bar] * 1_001)
    finally:
        engine.dispose()


def test_latest_quote_is_the_only_quote_table(tmp_path: Path) -> None:
    engine, _sessions = _repositories(tmp_path)

    try:
        quote_tables = sorted(
            table_name for table_name in inspect(engine).get_table_names() if "quote" in table_name
        )
        assert quote_tables == ["latest_quote"]
    finally:
        engine.dispose()
