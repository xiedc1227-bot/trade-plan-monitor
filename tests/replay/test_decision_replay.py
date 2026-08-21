from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from trade_plan_monitor.decision.engine import canonical_result_json, evaluate
from trade_plan_monitor.decision.models import (
    ActionableSignalType,
    DailyIndicatorProvenance,
    DailyIndicatorSnapshot,
    DataHealthSnapshot,
    DataHealthStatus,
    EpisodeStatus,
    EvaluationContext,
    EvaluationResult,
    IntradayEvaluationTarget,
    LowZoneEpisodeSnapshot,
    PositionLotSnapshot,
    RiskStateSnapshot,
    RiskStatus,
    SignalType,
)
from trade_plan_monitor.domain.plan_codec import load_plan_yaml
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.market_data.aggregation import FiveMinuteBar
from trade_plan_monitor.market_data.indicators import IndicatorPoint, IndicatorSeries
from trade_plan_monitor.market_data.models import DailyBar, DailyLimit, MinuteBar, TradingDay
from trade_plan_monitor.market_data.reconciliation import reconcile_daily_close

SHANGHAI = ZoneInfo("Asia/Shanghai")
SYMBOL = "003043.SZ"
TRADE_DATE = date(2026, 8, 7)
PREVIOUS_TRADE_DATE = date(2026, 8, 6)
SAMPLE_PATH = Path(__file__).resolve().parents[2] / "config" / "plans" / "003043.SZ.sample.yaml"


def _bar(
    bar_end: datetime,
    *,
    close_fen: int = 6400,
    low_fen: int = 6380,
    volume_shares: int = 100,
) -> FiveMinuteBar:
    return FiveMinuteBar(
        symbol=SYMBOL,
        bar_end=bar_end,
        open_fen=close_fen,
        high_fen=max(close_fen, 6420),
        low_fen=low_fen,
        close_fen=close_fen,
        volume_shares=volume_shares,
        amount_yuan=Decimal(volume_shares),
    )


def _bars() -> tuple[FiveMinuteBar, ...]:
    start = datetime(2026, 8, 7, 9, 35, tzinfo=SHANGHAI)
    return tuple(_bar(start + timedelta(minutes=5 * index)) for index in range(21))


def _point(bar_at: date | datetime, *, histogram: float = -0.08) -> IndicatorPoint:
    return IndicatorPoint(
        bar_at=bar_at,
        ema10_yuan=64.0,
        ema12_yuan=64.0,
        ema26_yuan=64.0,
        macd_yuan=0.0,
        macd_signal_yuan=0.0,
        macd_histogram_yuan=histogram,
        boll_middle_yuan=64.0,
        boll_upper_yuan=64.5,
        boll_lower_yuan=63.5,
        rsi14=50.0,
        atr14_yuan=0.5,
        ma20_yuan=64.0,
        ma50_yuan=None if isinstance(bar_at, datetime) else 64.0,
        ma200_yuan=None if isinstance(bar_at, datetime) else 64.0,
    )


def _five_minute_indicators(bars: tuple[FiveMinuteBar, ...]) -> IndicatorSeries:
    return IndicatorSeries(
        symbol=SYMBOL,
        points=tuple(_point(bar.bar_end, histogram=0.0) for bar in bars),
    )


def _daily_indicators() -> IndicatorSeries:
    return IndicatorSeries(
        symbol=SYMBOL,
        points=(
            _point(PREVIOUS_TRADE_DATE, histogram=-0.10),
            _point(TRADE_DATE, histogram=-0.08),
        ),
    )


def _current_bucket_minutes(bar: FiveMinuteBar) -> tuple[MinuteBar, ...]:
    ends = tuple(bar.bar_end - timedelta(minutes=offset) for offset in range(4, -1, -1))
    previous_close = max(bar.low_fen, min(bar.high_fen, bar.close_fen - 1))
    closes = (bar.open_fen, bar.open_fen, bar.open_fen, previous_close, bar.close_fen)
    return tuple(
        MinuteBar(
            symbol=bar.symbol,
            bar_end=bar_end,
            open_fen=bar.open_fen if index == 0 else closes[index - 1],
            high_fen=bar.high_fen if index == 4 else max(closes[index - 1], close),
            low_fen=bar.low_fen if index == 4 else min(closes[index - 1], close),
            close_fen=close,
            volume_shares=bar.volume_shares if index == 4 else 0,
            amount_yuan=bar.amount_yuan if index == 4 else Decimal("0"),
            received_at=bar_end,
        )
        for index, (bar_end, close) in enumerate(zip(ends, closes, strict=True))
    )


def _current_day_minutes(bars: tuple[FiveMinuteBar, ...]) -> tuple[MinuteBar, ...]:
    return tuple(minute for bar in bars for minute in _current_bucket_minutes(bar))


def _official_history_bar() -> DailyBar:
    return DailyBar(
        symbol=SYMBOL,
        trade_date=PREVIOUS_TRADE_DATE,
        open_fen=6400,
        high_fen=6420,
        low_fen=6380,
        close_fen=6400,
        volume_shares=2_000,
        amount_yuan=Decimal("128000"),
        is_official=True,
        received_at=datetime(2026, 8, 6, 15, 30, tzinfo=SHANGHAI),
    )


def _provisional_bar(received_at: datetime) -> DailyBar:
    return DailyBar(
        symbol=SYMBOL,
        trade_date=TRADE_DATE,
        open_fen=6400,
        high_fen=6420,
        low_fen=6380,
        close_fen=6400,
        volume_shares=2_100,
        amount_yuan=Decimal("134400"),
        is_official=False,
        received_at=received_at,
    )


def _context() -> EvaluationContext:
    plan = load_plan_yaml(SAMPLE_PATH.read_text(encoding="utf-8"))
    plan_hash = plan_sha256(plan)
    bars = _bars()
    target = IntradayEvaluationTarget(bucket_end=bars[-1].bar_end)
    provisional = _provisional_bar(target.bucket_end)
    reconciliation = reconcile_daily_close(
        symbol=SYMBOL,
        current_trade_date=TRADE_DATE,
        daily_bars=(provisional,),
    )
    return EvaluationContext(
        evaluated_at=target.bucket_end + timedelta(minutes=1),
        target=target,
        plan=plan,
        plan_hash=plan_hash,
        plan_active=True,
        activated_at=datetime(2026, 8, 7, 9, 0, tzinfo=SHANGHAI),
        current_day_minutes=_current_day_minutes(bars),
        complete_5m_bars=bars,
        official_daily_bars=(_official_history_bar(),),
        five_minute_indicators=_five_minute_indicators(bars),
        daily_indicator_snapshot=DailyIndicatorSnapshot(
            series=_daily_indicators(),
            provenance=DailyIndicatorProvenance.PROVISIONAL,
            source_as_of=target.bucket_end,
            source_bar=provisional,
        ),
        close_reconciliation=reconciliation,
        trading_calendar=(
            TradingDay(
                exchange="SZSE",
                cal_date=TRADE_DATE,
                is_open=True,
                previous_trade_date=PREVIOUS_TRADE_DATE,
            ),
        ),
        daily_limit=DailyLimit(
            symbol=SYMBOL,
            trade_date=TRADE_DATE,
            up_limit_fen=7200,
            down_limit_fen=6000,
            received_at=datetime(2026, 8, 7, 9, 31, tzinfo=SHANGHAI),
        ),
        data_health=DataHealthSnapshot(
            symbol=SYMBOL,
            status=DataHealthStatus.LIVE,
            latest_bar_end=target.bucket_end,
            data_age_seconds=60,
            required_data_complete=True,
            fresh=True,
        ),
        positions=(),
        low_zone_episode=LowZoneEpisodeSnapshot(
            episode_id="episode-replay-001",
            plan_hash=plan_hash,
            symbol=SYMBOL,
            started_at=datetime(2026, 8, 7, 9, 31, tzinfo=SHANGHAI),
            episode_low_fen=6380,
            bars_since_low=2,
            last_processed_bucket_end=target.bucket_end - timedelta(minutes=5),
            status=EpisodeStatus.ACTIVE,
            alerted_signal=None,
        ),
        risk_state=RiskStateSnapshot(
            symbol=SYMBOL,
            plan_hash=plan_hash,
            status=RiskStatus.CLEAR,
            breach_trade_date=None,
            prior_close_fen=6400,
            revision=0,
            updated_at=datetime(2026, 8, 7, 9, 30, tzinfo=SHANGHAI),
        ),
        manual_event_risk=False,
    )


def _next_bucket_end(current: datetime) -> datetime:
    if (current.hour, current.minute) == (11, 30):
        return current.replace(hour=13, minute=5)
    return current + timedelta(minutes=5)


def _append_bar(
    context: EvaluationContext,
    *,
    close_fen: int,
    low_fen: int,
) -> EvaluationContext:
    target_end = _next_bucket_end(context.target.bucket_end)
    bar = _bar(target_end, close_fen=close_fen, low_fen=low_fen)
    bars = (*context.complete_5m_bars, bar)
    snapshot = context.daily_indicator_snapshot
    assert snapshot is not None
    source = snapshot.source_bar.model_copy(
        update={
            "high_fen": max(snapshot.source_bar.high_fen, bar.high_fen),
            "low_fen": min(snapshot.source_bar.low_fen, bar.low_fen),
            "close_fen": bar.close_fen,
            "received_at": target_end,
        }
    )
    reconciliation = reconcile_daily_close(
        symbol=SYMBOL,
        current_trade_date=TRADE_DATE,
        daily_bars=(source,),
    )
    evaluated_at = target_end + timedelta(minutes=1)
    return context.model_copy(
        update={
            "evaluated_at": evaluated_at,
            "target": IntradayEvaluationTarget(bucket_end=target_end),
            "current_day_minutes": (
                *context.current_day_minutes,
                *_current_bucket_minutes(bar),
            ),
            "complete_5m_bars": bars,
            "five_minute_indicators": _five_minute_indicators(bars),
            "daily_indicator_snapshot": snapshot.model_copy(
                update={
                    "source_as_of": target_end,
                    "source_bar": reconciliation.provisional_bar,
                }
            ),
            "close_reconciliation": reconciliation,
            "data_health": DataHealthSnapshot(
                symbol=SYMBOL,
                status=DataHealthStatus.LIVE,
                latest_bar_end=target_end,
                data_age_seconds=60,
                required_data_complete=True,
                fresh=True,
            ),
        }
    )


def _round_trip_context(context: EvaluationContext) -> EvaluationContext:
    return EvaluationContext.model_validate_json(context.model_dump_json(round_trip=True))


def _resume_episode(
    context: EvaluationContext,
    result: EvaluationResult,
) -> EvaluationContext:
    return _round_trip_context(
        context.model_copy(update={"low_zone_episode": result.snapshot.episode})
    )


def test_duplicate_valid_entry_and_restart_are_byte_stable_and_do_not_realert() -> None:
    context = _context()

    first = evaluate(context)
    duplicate = evaluate(_round_trip_context(context))

    assert first.snapshot.signal_type is SignalType.BUY_CORE_READY
    assert first.signal_intent is not None
    assert first.signal_intent.signal_type is ActionableSignalType.BUY_CORE_READY
    assert canonical_result_json(first) == canonical_result_json(duplicate)
    assert first.result_hash == duplicate.result_hash
    assert first.evaluation_identity == duplicate.evaluation_identity
    assert first.signal_intent.cause_id == duplicate.signal_intent.cause_id

    restarted = _resume_episode(context, first)
    same_target = evaluate(restarted)
    assert same_target.signal_intent is None
    assert same_target.transitions == ()
    assert same_target.snapshot.episode is not None
    assert same_target.snapshot.episode.status is EpisodeStatus.ALERTED

    next_target = _append_bar(restarted, close_fen=6400, low_fen=6380)
    advanced = evaluate(next_target)
    assert advanced.signal_intent is None
    assert advanced.snapshot.episode is not None
    assert advanced.snapshot.episode.status is EpisodeStatus.ALERTED
    assert advanced.snapshot.episode.last_processed_bucket_end == next_target.target.bucket_end


def test_continuous_decline_replay_resets_once_per_bucket_across_json_restart() -> None:
    context = _context()
    assert context.low_zone_episode is not None
    context = context.model_copy(
        update={
            "low_zone_episode": context.low_zone_episode.model_copy(
                update={"episode_low_fen": 6400, "bars_since_low": 1}
            )
        }
    )

    first = evaluate(context)
    assert first.snapshot.signal_type is SignalType.LOW_ZONE_WATCH
    assert first.signal_intent is None
    assert first.snapshot.episode is not None
    assert first.snapshot.episode.episode_low_fen == 6380
    assert first.snapshot.episode.bars_since_low == 0
    assert first.snapshot.episode.last_processed_bucket_end == context.target.bucket_end

    restarted = _resume_episode(context, first)
    second_context = _append_bar(restarted, close_fen=6380, low_fen=6379)
    second = evaluate(second_context)
    assert second.snapshot.signal_type is SignalType.LOW_ZONE_WATCH
    assert second.signal_intent is None
    assert second.snapshot.episode is not None
    assert second.snapshot.episode.episode_low_fen == 6379
    assert second.snapshot.episode.bars_since_low == 0
    assert second.snapshot.episode.last_processed_bucket_end == second_context.target.bucket_end

    second_replay = EvaluationResult.model_validate_json(canonical_result_json(second))
    assert canonical_result_json(second_replay) == canonical_result_json(second)
    same_target_context = _resume_episode(second_context, second_replay)
    same_target = evaluate(same_target_context)
    assert same_target.signal_intent is None
    assert same_target.transitions == ()
    assert same_target.snapshot.episode == second_replay.snapshot.episode
    third_context = _append_bar(
        same_target_context,
        close_fen=6379,
        low_fen=6378,
    )
    third = evaluate(third_context)
    assert third.snapshot.episode is not None
    assert third.snapshot.episode.episode_low_fen == 6378
    assert third.snapshot.episode.bars_since_low == 0
    assert third.snapshot.episode.last_processed_bucket_end == third_context.target.bucket_end


def test_stale_then_recovered_context_fails_closed_before_one_restart_safe_entry() -> None:
    base = _context()
    stale = base.model_copy(
        update={
            "data_health": base.data_health.model_copy(
                update={"status": DataHealthStatus.STALE, "fresh": False}
            )
        }
    )

    blocked = evaluate(stale)
    blocked_replay = evaluate(_round_trip_context(stale))
    assert blocked.snapshot.signal_type is SignalType.BLOCKED_DATA
    assert blocked.signal_intent is None
    assert blocked.transitions == ()
    assert canonical_result_json(blocked) == canonical_result_json(blocked_replay)

    recovered = evaluate(_round_trip_context(base))
    assert recovered.snapshot.signal_type is SignalType.BUY_CORE_READY
    assert recovered.signal_intent is not None
    persisted = _resume_episode(base, recovered)
    after_restart = evaluate(persisted)
    assert after_restart.signal_intent is None
    assert after_restart.transitions == ()


def test_exit_reentry_creates_one_independent_tactical_episode_after_core_entry() -> None:
    initial_context = _context()
    core_entry = evaluate(initial_context)
    assert core_entry.signal_intent is not None
    first_episode = core_entry.snapshot.episode
    assert first_episode is not None
    core_lot = PositionLotSnapshot(
        lot_id="lot-core-replay",
        symbol=SYMBOL,
        bucket="CORE",
        quantity=100,
        remaining_quantity=100,
        acquired_trade_date=TRADE_DATE,
        cost_fen=6400,
    )
    current = _round_trip_context(
        initial_context.model_copy(
            update={
                "low_zone_episode": first_episode,
                "positions": (core_lot,),
            }
        )
    )

    outside_one_context = _append_bar(current, close_fen=6500, low_fen=6500)
    outside_one = evaluate(outside_one_context)
    assert outside_one.signal_intent is None
    outside_two_context = _append_bar(
        _resume_episode(outside_one_context, outside_one),
        close_fen=6500,
        low_fen=6500,
    )
    outside_two = evaluate(outside_two_context)
    assert outside_two.snapshot.episode is not None
    assert outside_two.snapshot.episode.status is EpisodeStatus.CLOSED

    reentry_context = _append_bar(
        _resume_episode(outside_two_context, outside_two),
        close_fen=6400,
        low_fen=6380,
    )
    reentry = evaluate(reentry_context)
    second_episode = reentry.snapshot.episode
    assert second_episode is not None
    assert second_episode.status is EpisodeStatus.ACTIVE
    assert second_episode.episode_id != first_episode.episode_id

    confirm_one_context = _append_bar(
        _resume_episode(reentry_context, reentry),
        close_fen=6400,
        low_fen=6380,
    )
    confirm_one = evaluate(confirm_one_context)
    assert confirm_one.signal_intent is None
    confirm_two_context = _append_bar(
        _resume_episode(confirm_one_context, confirm_one),
        close_fen=6400,
        low_fen=6380,
    )
    tactical_entry = evaluate(confirm_two_context)

    assert tactical_entry.snapshot.signal_type is SignalType.BUY_TACTICAL_READY
    assert tactical_entry.signal_intent is not None
    assert tactical_entry.signal_intent.signal_type is ActionableSignalType.BUY_TACTICAL_READY
    assert tactical_entry.signal_intent.cause_id == second_episode.episode_id
    assert tactical_entry.signal_intent.cause_id != core_entry.signal_intent.cause_id
    exact_replay = evaluate(_round_trip_context(confirm_two_context))
    assert canonical_result_json(exact_replay) == canonical_result_json(tactical_entry)
    persisted = _resume_episode(confirm_two_context, tactical_entry)
    assert evaluate(persisted).signal_intent is None
