import ast
import inspect
import json
from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from zoneinfo import ZoneInfo

import pytest
from pydantic import TypeAdapter, ValidationError

import trade_plan_monitor.decision.conditions as condition_module
import trade_plan_monitor.decision.engine as engine_module
import trade_plan_monitor.decision.episodes as episode_module
import trade_plan_monitor.decision.models as decision_models_module
import trade_plan_monitor.decision.risk as risk_module
from trade_plan_monitor.decision.conditions import (
    CONDITION_EVALUATORS,
    evaluate_condition,
)
from trade_plan_monitor.decision.engine import canonical_result_json, evaluate
from trade_plan_monitor.decision.episodes import evaluate_low_zone_episode
from trade_plan_monitor.decision.models import (
    ActionableSignalType,
    ConditionEvidence,
    ConditionOutcome,
    DailyIndicatorProvenance,
    DailyIndicatorSnapshot,
    DataHealthSnapshot,
    DataHealthStatus,
    DecisionZone,
    EpisodeStatus,
    EpisodeTransitionAction,
    EpisodeTransitionIntent,
    EvaluationContext,
    EvaluationResult,
    EvidenceFact,
    EvidenceUnit,
    IndexConditionEvidence,
    IntradayEvaluationIdentity,
    IntradayEvaluationTarget,
    LowZoneEpisodeSnapshot,
    MissingInputCode,
    NextStep,
    NextStepCode,
    OfficialCloseEvaluationIdentity,
    OfficialCloseEvaluationTarget,
    PositionLotSnapshot,
    PositionSummary,
    RiskStateSnapshot,
    RiskStatus,
    RiskTransitionIntent,
    RuleEvidence,
    RuleEvidenceCode,
    SignalIntent,
    SignalType,
    SymbolDecisionSnapshot,
)
from trade_plan_monitor.decision.risk import (
    evaluate_official_close_risk,
    evaluate_pressure_reduction,
)
from trade_plan_monitor.domain.plan_codec import load_plan_yaml
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import (
    AllCondition,
    AnyCondition,
    CloseInBarLowerHalfCondition,
    ConditionNode,
    ConsecutiveClosesBelowLevelCondition,
    DistanceFromLimitDownGteCondition,
    IndexCloseGteMaCondition,
    IndexCloseLteMaCondition,
    IndexMaNonDecreasingCondition,
    IndexMaNonIncreasingCondition,
    IndexReturnGteCondition,
    IndexReturnLteCondition,
    LowerBandHitsLteCondition,
    MacdHistImprovementGteCondition,
    ManualEventRiskClearCondition,
    NextTradingDayRecoveryCondition,
    NonDecreasingCloseCondition,
    NoNewLowForBarsCondition,
    OfficialCloseBelowLevelCondition,
    PositionBucketAvailableCondition,
    PriceInZoneCondition,
    PriceReclaimsIndicatorCondition,
    RetreatFromSessionHighGteCondition,
    SellableQuantityGteCondition,
    UpperWickRatioGteCondition,
    VolumeToMedianGteCondition,
    VolumeToMedianLteCondition,
    VolumeToPreviousLteCondition,
)
from trade_plan_monitor.domain.plan_validation import migrate_trade_plan_to_schema_v2
from trade_plan_monitor.market_data.aggregation import FiveMinuteBar, aggregate_five_minute_bar
from trade_plan_monitor.market_data.indicators import IndicatorPoint, IndicatorSeries
from trade_plan_monitor.market_data.models import DailyBar, DailyLimit, MinuteBar, TradingDay
from trade_plan_monitor.market_data.reconciliation import reconcile_daily_close
from trade_plan_monitor.market_index.canonical import (
    FORMULA_DEFINITION_HASH,
    market_index_bar_set_hash,
    market_index_request_set_hash,
    market_index_snapshot_hash,
)
from trade_plan_monitor.market_index.formulas import calculate_requested_facts
from trade_plan_monitor.market_index.identity import (
    MAPPING_VERSION,
    MarketIndexCode,
    identity_for_index_code,
)
from trade_plan_monitor.market_index.models import (
    MarketIndexBar,
    MarketIndexFactRequest,
    MarketIndexHealth,
    MarketIndexInterval,
    MarketIndexIssueCode,
    MarketIndexSnapshot,
    MarketIndexSourceKind,
    ReturnFactRequest,
    ReturnWindow,
    SmaFactRequest,
    SmaLookbackFactRequest,
)
from trade_plan_monitor.market_index.requirements import union_fact_requests

SHANGHAI = ZoneInfo("Asia/Shanghai")
SYMBOL = "003043.SZ"
TRADE_DATE = date(2026, 8, 7)
PREVIOUS_TRADE_DATE = date(2026, 8, 6)
SAMPLE_PATH = Path(__file__).resolve().parents[2] / "config" / "plans" / "003043.SZ.sample.yaml"
LOW_ZONE_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "decision" / "low_zone.json"
)
RISK_FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "decision" / "risk.json"
ConditionPayload = dict[str, object]
ContextTransform = Callable[[EvaluationContext], EvaluationContext]


def _condition(payload: ConditionPayload) -> ConditionNode:
    return TypeAdapter(ConditionNode).validate_python(payload)


def _bar(
    bar_end: datetime,
    *,
    close_fen: int = 6400,
    volume_shares: int = 100,
    open_fen: int = 6400,
    high_fen: int = 6420,
    low_fen: int = 6380,
) -> FiveMinuteBar:
    return FiveMinuteBar(
        symbol=SYMBOL,
        bar_end=bar_end,
        open_fen=open_fen,
        high_fen=high_fen,
        low_fen=low_fen,
        close_fen=close_fen,
        volume_shares=volume_shares,
        amount_yuan=Decimal(volume_shares),
    )


def _bars(
    volumes: tuple[int, ...] = (100,) * 21,
    *,
    closes: tuple[int, ...] | None = None,
) -> tuple[FiveMinuteBar, ...]:
    start = datetime(2026, 8, 7, 9, 35, tzinfo=SHANGHAI)
    close_values = closes or (6400,) * len(volumes)
    assert len(close_values) == len(volumes)
    return tuple(
        _bar(
            start + timedelta(minutes=5 * index),
            close_fen=close_value,
            volume_shares=volume,
        )
        for index, (volume, close_value) in enumerate(zip(volumes, close_values, strict=True))
    )


def _point(
    bar_at: date,
    *,
    macd_histogram_yuan: float,
    ema10_yuan: float = 64.0,
    boll_lower_yuan: float | None = 63.5,
) -> IndicatorPoint:
    return IndicatorPoint(
        bar_at=bar_at,
        ema10_yuan=ema10_yuan,
        ema12_yuan=64.0,
        ema26_yuan=64.0,
        macd_yuan=0.0,
        macd_signal_yuan=0.0,
        macd_histogram_yuan=macd_histogram_yuan,
        boll_middle_yuan=64.0,
        boll_upper_yuan=64.5,
        boll_lower_yuan=boll_lower_yuan,
        rsi14=50.0,
        atr14_yuan=0.5,
        ma20_yuan=64.0,
        ma50_yuan=64.0,
        ma200_yuan=64.0,
    )


def _daily_indicators(
    *,
    current_histogram: float = -0.08,
    ema10_yuan: float = 64.0,
    boll_lower_yuan: float | None = 63.5,
) -> IndicatorSeries:
    return IndicatorSeries(
        symbol=SYMBOL,
        points=(
            _point(PREVIOUS_TRADE_DATE, macd_histogram_yuan=-0.10),
            _point(
                TRADE_DATE,
                macd_histogram_yuan=current_histogram,
                ema10_yuan=ema10_yuan,
                boll_lower_yuan=boll_lower_yuan,
            ),
        ),
    )


def _five_minute_indicators(bars: tuple[FiveMinuteBar, ...]) -> IndicatorSeries:
    return IndicatorSeries(
        symbol=SYMBOL,
        points=tuple(
            IndicatorPoint(
                bar_at=bar.bar_end,
                ema10_yuan=64.0,
                ema12_yuan=64.0,
                ema26_yuan=64.0,
                macd_yuan=0.0,
                macd_signal_yuan=0.0,
                macd_histogram_yuan=0.0,
                boll_middle_yuan=64.0,
                boll_upper_yuan=64.5,
                boll_lower_yuan=63.5,
                rsi14=50.0,
                atr14_yuan=0.5,
                ma20_yuan=64.0,
                ma50_yuan=None,
                ma200_yuan=None,
            )
            for bar in bars
        ),
    )


def _current_bucket_minutes(bar: FiveMinuteBar) -> tuple[MinuteBar, ...]:
    minute_ends = tuple(bar.bar_end - timedelta(minutes=offset) for offset in range(4, -1, -1))
    previous_close = max(bar.low_fen, min(bar.high_fen, bar.close_fen - 1))
    closes = (bar.open_fen, bar.open_fen, bar.open_fen, previous_close, bar.close_fen)
    return tuple(
        MinuteBar(
            symbol=bar.symbol,
            bar_end=minute_end,
            open_fen=bar.open_fen if index == 0 else closes[index - 1],
            high_fen=bar.high_fen if index == 4 else max(closes[index - 1], close),
            low_fen=bar.low_fen if index == 4 else min(closes[index - 1], close),
            close_fen=close,
            volume_shares=bar.volume_shares if index == 4 else 0,
            amount_yuan=bar.amount_yuan if index == 4 else Decimal("0"),
            received_at=minute_end,
        )
        for index, (minute_end, close) in enumerate(zip(minute_ends, closes, strict=True))
    )


def _current_day_minutes(bars: tuple[FiveMinuteBar, ...]) -> tuple[MinuteBar, ...]:
    return tuple(
        minute
        for bar in bars
        if bar.bar_end.date() == TRADE_DATE
        for minute in _current_bucket_minutes(bar)
    )


def _replace_minute_closes(
    context: EvaluationContext,
    updates: dict[datetime, int],
) -> EvaluationContext:
    minutes = tuple(
        minute.model_copy(
            update={
                "open_fen": updates[minute.bar_end],
                "high_fen": updates[minute.bar_end],
                "low_fen": updates[minute.bar_end],
                "close_fen": updates[minute.bar_end],
            }
        )
        if minute.bar_end in updates
        else minute
        for minute in context.current_day_minutes
    )
    minute_groups: dict[datetime, tuple[MinuteBar, ...]] = {}
    for bar in context.complete_5m_bars:
        if bar.bar_end.date() != context.trade_date:
            continue
        group = tuple(
            minute
            for minute in minutes
            if bar.bar_end - timedelta(minutes=4) <= minute.bar_end <= bar.bar_end
        )
        minute_groups[bar.bar_end] = group
    replacement_bars = {
        bar_end: aggregate_five_minute_bar(
            group,
            bucket_end=bar_end,
            is_open=True,
        )
        for bar_end, group in minute_groups.items()
    }
    bars = tuple(replacement_bars.get(bar.bar_end, bar) for bar in context.complete_5m_bars)
    assert all(bar is not None for bar in bars)
    normalized_bars = tuple(bar for bar in bars if bar is not None)
    return context.model_copy(
        update={
            "current_day_minutes": minutes,
            "complete_5m_bars": normalized_bars,
            "five_minute_indicators": _five_minute_indicators(normalized_bars),
        }
    )


def _replace_minute_values(
    context: EvaluationContext,
    updates: dict[datetime, dict[str, int]],
) -> EvaluationContext:
    minutes = tuple(
        minute.model_copy(update=updates[minute.bar_end]) if minute.bar_end in updates else minute
        for minute in context.current_day_minutes
    )
    minute_groups: dict[datetime, tuple[MinuteBar, ...]] = {}
    for bar in context.complete_5m_bars:
        if bar.bar_end.date() != context.trade_date:
            continue
        group = tuple(
            minute
            for minute in minutes
            if bar.bar_end - timedelta(minutes=4) <= minute.bar_end <= bar.bar_end
        )
        minute_groups[bar.bar_end] = group
    replacement_bars = {
        bar_end: aggregate_five_minute_bar(
            group,
            bucket_end=bar_end,
            is_open=True,
        )
        for bar_end, group in minute_groups.items()
    }
    bars = tuple(replacement_bars.get(bar.bar_end, bar) for bar in context.complete_5m_bars)
    assert all(bar is not None for bar in bars)
    normalized_bars = tuple(bar for bar in bars if bar is not None)
    return context.model_copy(
        update={
            "current_day_minutes": minutes,
            "complete_5m_bars": normalized_bars,
            "five_minute_indicators": _five_minute_indicators(normalized_bars),
        }
    )


def _low_zone_fixture() -> dict[str, object]:
    return json.loads(LOW_ZONE_FIXTURE_PATH.read_text(encoding="utf-8"))


def _risk_fixture() -> dict[str, object]:
    return json.loads(RISK_FIXTURE_PATH.read_text(encoding="utf-8"))


def _pressure_touch_context(
    minute_closes_fen: tuple[int, int, int, int, int],
    *,
    range_override: dict[str, int] | None = None,
) -> EvaluationContext:
    context = _context()
    outside_updates = {
        minute.bar_end: {
            "open_fen": 6800,
            "high_fen": 6800,
            "low_fen": 6800,
            "close_fen": 6800,
        }
        for minute in context.current_day_minutes
    }
    target_updates = {
        minute.bar_end: {
            "open_fen": close,
            "high_fen": close,
            "low_fen": close,
            "close_fen": close,
        }
        for minute, close in zip(
            context.current_bucket_minutes,
            minute_closes_fen,
            strict=True,
        )
    }
    if range_override is not None:
        target = context.current_bucket_minutes[range_override["index"]]
        close = minute_closes_fen[range_override["index"]]
        target_updates[target.bar_end] = {
            "open_fen": close,
            "high_fen": range_override["highFen"],
            "low_fen": range_override["lowFen"],
            "close_fen": close,
        }
    return _replace_minute_values(context, outside_updates | target_updates)


def _pressure_lot(
    lot_id: str,
    *,
    bucket: str = "TACTICAL",
    acquired_trade_date: date = PREVIOUS_TRADE_DATE,
) -> PositionLotSnapshot:
    return PositionLotSnapshot(
        lot_id=lot_id,
        symbol=SYMBOL,
        bucket=bucket,
        quantity=100,
        remaining_quantity=100,
        acquired_trade_date=acquired_trade_date,
        cost_fen=6400,
    )


def _replace_completed_bar(
    context: EvaluationContext,
    replacement: FiveMinuteBar,
) -> EvaluationContext:
    minute_updates = {
        minute.bar_end: {
            "open_fen": minute.open_fen,
            "high_fen": minute.high_fen,
            "low_fen": minute.low_fen,
            "close_fen": minute.close_fen,
            "volume_shares": minute.volume_shares,
            "amount_yuan": minute.amount_yuan,
            "received_at": minute.received_at,
        }
        for minute in _current_bucket_minutes(replacement)
    }
    return _replace_minute_values(context, minute_updates)


def _flat_pressure_bar(
    bar_end: datetime,
    close_fen: int,
    *,
    volume_shares: int = 100,
) -> FiveMinuteBar:
    return _bar(
        bar_end,
        open_fen=close_fen,
        high_fen=close_fen,
        low_fen=close_fen,
        close_fen=close_fen,
        volume_shares=volume_shares,
    )


def _pressure_pattern_context(pattern: str) -> EvaluationContext:
    context = _context().model_copy(update={"positions": (_pressure_lot("lot-tactical-pressure"),)})
    latest_end = context.complete_5m_bars[-1].bar_end
    previous_end = context.complete_5m_bars[-2].bar_end
    if pattern == "upper_wick":
        return _replace_completed_bar(
            context,
            _bar(
                latest_end,
                open_fen=6950,
                high_fen=6970,
                low_fen=6920,
                close_fen=6950,
                volume_shares=100,
            ),
        )
    if pattern == "retreat":
        with_high = _replace_completed_bar(
            context,
            _bar(
                previous_end,
                open_fen=6400,
                high_fen=7000,
                low_fen=6400,
                close_fen=6400,
                volume_shares=100,
            ),
        )
        return _replace_completed_bar(
            with_high,
            _flat_pressure_bar(latest_end, 6930),
        )
    if pattern == "volume_lower_half":
        return _replace_completed_bar(
            context,
            _bar(
                latest_end,
                open_fen=6920,
                high_fen=6940,
                low_fen=6880,
                close_fen=6910,
                volume_shares=150,
            ),
        )
    if pattern == "consecutive":
        first = _replace_completed_bar(
            context,
            _flat_pressure_bar(previous_end, 6905),
        )
        return _replace_completed_bar(
            first,
            _flat_pressure_bar(latest_end, 6905),
        )
    if pattern == "none":
        first = _replace_completed_bar(
            context,
            _flat_pressure_bar(previous_end, 6950),
        )
        return _replace_completed_bar(
            first,
            _flat_pressure_bar(latest_end, 6950),
        )
    raise AssertionError(f"unknown pressure pattern: {pattern}")


def _condition_evidence_of_type(
    evidence: ConditionEvidence,
    condition_type: type[object],
) -> ConditionEvidence:
    if isinstance(evidence.condition, condition_type):
        return evidence
    for child in evidence.children:
        try:
            return _condition_evidence_of_type(child, condition_type)
        except LookupError:
            continue
    raise LookupError(condition_type.__name__)


def _touch_context(
    minute_closes_fen: tuple[int, int, int, int, int],
    *,
    range_override: dict[str, int] | None = None,
) -> EvaluationContext:
    context = _context()
    outside_updates = {
        minute.bar_end: {
            "open_fen": 6500,
            "high_fen": 6500,
            "low_fen": 6500,
            "close_fen": 6500,
        }
        for minute in context.current_day_minutes
    }
    target_updates = {
        minute.bar_end: {
            "open_fen": close,
            "high_fen": close,
            "low_fen": close,
            "close_fen": close,
        }
        for minute, close in zip(
            context.current_bucket_minutes,
            minute_closes_fen,
            strict=True,
        )
    }
    if range_override is not None:
        target = context.current_bucket_minutes[range_override["index"]]
        close = minute_closes_fen[range_override["index"]]
        target_updates[target.bar_end] = {
            "open_fen": close,
            "high_fen": range_override["highFen"],
            "low_fen": range_override["lowFen"],
            "close_fen": close,
        }
    return _replace_minute_values(
        context,
        outside_updates | target_updates,
    ).model_copy(update={"low_zone_episode": None})


def _position_lots(core_quantity: int, tactical_quantity: int) -> tuple[PositionLotSnapshot, ...]:
    lots: list[PositionLotSnapshot] = []
    if core_quantity:
        lots.append(
            PositionLotSnapshot(
                lot_id="lot-core-001",
                symbol=SYMBOL,
                bucket="CORE",
                quantity=core_quantity,
                remaining_quantity=core_quantity,
                acquired_trade_date=PREVIOUS_TRADE_DATE,
                cost_fen=6400,
            )
        )
    if tactical_quantity:
        lots.append(
            PositionLotSnapshot(
                lot_id="lot-tactical-001",
                symbol=SYMBOL,
                bucket="TACTICAL",
                quantity=tactical_quantity,
                remaining_quantity=tactical_quantity,
                acquired_trade_date=PREVIOUS_TRADE_DATE,
                cost_fen=6400,
            )
        )
    return tuple(lots)


def _replace_target_minute_closes(
    context: EvaluationContext,
    closes: tuple[int, int, int, int, int],
) -> EvaluationContext:
    return _replace_minute_closes(
        context,
        {
            minute.bar_end: close
            for minute, close in zip(
                context.current_bucket_minutes,
                closes,
                strict=True,
            )
        },
    )


def _official_history_bar() -> DailyBar:
    return DailyBar(
        symbol=SYMBOL,
        trade_date=PREVIOUS_TRADE_DATE,
        open_fen=6380,
        high_fen=6450,
        low_fen=6350,
        close_fen=6400,
        volume_shares=9_000,
        amount_yuan=Decimal("576000"),
        is_official=True,
        received_at=datetime(2026, 8, 6, 15, 30, tzinfo=SHANGHAI),
    )


def _provisional_bar() -> DailyBar:
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
        received_at=datetime(2026, 8, 7, 11, 15, tzinfo=SHANGHAI),
    )


def _risk_clear(plan_hash: str) -> RiskStateSnapshot:
    return RiskStateSnapshot(
        symbol=SYMBOL,
        plan_hash=plan_hash,
        status=RiskStatus.CLEAR,
        breach_trade_date=None,
        prior_close_fen=6400,
        revision=0,
        updated_at=datetime(2026, 8, 7, 9, 30, tzinfo=SHANGHAI),
    )


def test_daily_indicator_snapshot_requires_explicit_source_provenance() -> None:
    source = _provisional_bar()
    snapshot = DailyIndicatorSnapshot(
        series=_daily_indicators(),
        provenance=DailyIndicatorProvenance.PROVISIONAL,
        source_as_of=source.received_at,
        source_bar=source,
    )

    assert snapshot.provenance is DailyIndicatorProvenance.PROVISIONAL
    assert snapshot.source_as_of == source.received_at
    with pytest.raises(ValidationError, match="provisional"):
        snapshot.model_copy(update={"provenance": DailyIndicatorProvenance.OFFICIAL})


@pytest.mark.parametrize(
    "source_as_of",
    [
        datetime(2026, 8, 7, 11, 16, tzinfo=SHANGHAI),
        datetime(2026, 8, 7, 12, 0, tzinfo=SHANGHAI),
        datetime(2026, 8, 7, 11, 15, 30, tzinfo=SHANGHAI),
    ],
)
def test_provisional_daily_indicator_cutoff_is_a_canonical_five_minute_boundary(
    source_as_of: datetime,
) -> None:
    source = _provisional_bar().model_copy(
        update={"received_at": datetime(2026, 8, 7, 13, 0, tzinfo=SHANGHAI)}
    )

    with pytest.raises(ValidationError, match="session|five-minute|boundary|whole minute"):
        DailyIndicatorSnapshot(
            series=_daily_indicators(),
            provenance=DailyIndicatorProvenance.PROVISIONAL,
            source_as_of=source_as_of,
            source_bar=source,
        )


def _episode(
    plan_hash: str,
    *,
    bars_since_low: int = 2,
    last_processed_bucket_end: datetime | None = None,
) -> LowZoneEpisodeSnapshot:
    return LowZoneEpisodeSnapshot(
        episode_id="episode-001",
        plan_hash=plan_hash,
        symbol=SYMBOL,
        started_at=datetime(2026, 8, 7, 9, 31, tzinfo=SHANGHAI),
        episode_low_fen=6380,
        bars_since_low=bars_since_low,
        last_processed_bucket_end=(
            datetime(2026, 8, 7, 11, 10, tzinfo=SHANGHAI)
            if last_processed_bucket_end is None
            else last_processed_bucket_end
        ),
        status=EpisodeStatus.ACTIVE,
        alerted_signal=None,
    )


def _context() -> EvaluationContext:
    plan = load_plan_yaml(SAMPLE_PATH.read_text(encoding="utf-8"))
    plan_hash = plan_sha256(plan)
    bars = _bars()
    target = IntradayEvaluationTarget(bucket_end=bars[-1].bar_end)
    reconciliation = reconcile_daily_close(
        symbol=SYMBOL,
        current_trade_date=TRADE_DATE,
        daily_bars=(_provisional_bar(),),
    )
    return EvaluationContext(
        evaluated_at=bars[-1].bar_end + timedelta(minutes=1),
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
            source_bar=reconciliation.provisional_bar,
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
            latest_bar_end=bars[-1].bar_end,
            data_age_seconds=60,
            required_data_complete=True,
            fresh=True,
        ),
        positions=(),
        low_zone_episode=_episode(plan_hash),
        risk_state=_risk_clear(plan_hash),
        manual_event_risk=False,
    )


def _index_bar(
    *,
    index_code: MarketIndexCode,
    interval: MarketIndexInterval,
    bar_at: datetime,
    close_points: Decimal,
    observed_at: datetime,
) -> MarketIndexBar:
    return MarketIndexBar(
        index_code=index_code,
        interval=interval,
        bar_at=bar_at,
        open_points=close_points,
        high_points=close_points,
        low_points=close_points,
        close_points=close_points,
        observed_at=observed_at,
        source_kind=(
            MarketIndexSourceKind.PROVISIONAL
            if interval is MarketIndexInterval.FIVE_MINUTE
            else MarketIndexSourceKind.OFFICIAL
        ),
        provider_revision=1,
    )


def _reference_market_snapshot(
    context: EvaluationContext,
    *,
    index_code: MarketIndexCode = MarketIndexCode.SHENZHEN_COMPONENT,
    decision_cutoff: datetime | None = None,
    health: MarketIndexHealth = MarketIndexHealth.LIVE,
    issues: tuple[MarketIndexIssueCode, ...] = (),
    requests: tuple[MarketIndexFactRequest, ...] | None = None,
) -> MarketIndexSnapshot:
    cutoff = context.target_cutoff if decision_cutoff is None else decision_cutoff
    five_minute_bars = tuple(
        _index_bar(
            index_code=index_code,
            interval=MarketIndexInterval.FIVE_MINUTE,
            bar_at=cutoff - timedelta(minutes=offset),
            close_points=close,
            observed_at=context.evaluated_at,
        )
        for offset, close in (
            (10, Decimal("80")),
            (5, Decimal("90")),
            (0, Decimal("100")),
        )
    )
    official_daily_bars = tuple(
        _index_bar(
            index_code=index_code,
            interval=MarketIndexInterval.OFFICIAL_DAILY,
            bar_at=datetime(2026, 8, day, 15, 0, tzinfo=SHANGHAI),
            close_points=Decimal("100"),
            observed_at=datetime(2026, 8, day, 15, 1, tzinfo=SHANGHAI),
        )
        for day in (4, 5, 6)
    )
    selected_requests = (
        union_fact_requests(
            (SmaFactRequest(period=2),),
            (SmaLookbackFactRequest(period=2, lookback=1),),
            (
                ReturnFactRequest(
                    window=ReturnWindow.FIVE_MINUTE_BUCKETS,
                    window_size=2,
                ),
                ReturnFactRequest(
                    window=ReturnWindow.OFFICIAL_OPEN_DAYS,
                    window_size=2,
                ),
            ),
        )
        if requests is None
        else union_fact_requests(requests)
    )
    facts = (
        calculate_requested_facts(
            index_code=index_code,
            five_minute_bars=five_minute_bars,
            official_daily_bars=official_daily_bars,
            requests=selected_requests,
            input_cutoff=cutoff,
        )
        if health is MarketIndexHealth.LIVE
        else ()
    )
    board, display_name = identity_for_index_code(index_code)
    bars = five_minute_bars + official_daily_bars
    payload: dict[str, object] = {
        "index_code": index_code,
        "display_name": display_name,
        "board": board,
        "decision_cutoff": cutoff,
        "latest_completed_five_minute": five_minute_bars[-1],
        "five_minute_bars": five_minute_bars,
        "official_daily_bars": official_daily_bars,
        "prior_official_close_points": official_daily_bars[-1].close_points,
        "fact_requests": selected_requests,
        "indicator_facts": facts,
        "health": health,
        "issues": issues,
        "completed_bucket_at": cutoff,
        "observed_at": context.evaluated_at,
        "mapping_version": MAPPING_VERSION,
        "revision": 1,
        "bar_set_hash": market_index_bar_set_hash(bars),
        "request_set_hash": market_index_request_set_hash(selected_requests),
        "formula_definition_hash": FORMULA_DEFINITION_HASH,
    }
    return MarketIndexSnapshot(
        **payload,
        snapshot_hash=market_index_snapshot_hash(payload),
    )


def _context_with_v2_condition(
    context: EvaluationContext,
    *,
    policy: str,
    condition: dict[str, object],
    snapshot: MarketIndexSnapshot | None,
) -> EvaluationContext:
    migrated = migrate_trade_plan_to_schema_v2(context.plan, new_version=2)
    plan_payload = migrated.model_dump(mode="python", round_trip=True)
    plan_payload[policy] = {"condition": condition}
    plan = type(migrated).model_validate(plan_payload)
    plan_hash = plan_sha256(plan)
    episode = (
        None
        if context.low_zone_episode is None
        else context.low_zone_episode.model_copy(update={"plan_hash": plan_hash})
    )
    risk = context.risk_state.model_copy(update={"plan_hash": plan_hash})
    return context.model_copy(
        update={
            "plan": plan,
            "plan_hash": plan_hash,
            "low_zone_episode": episode,
            "risk_state": risk,
            "reference_market_snapshot": snapshot,
        }
    )


@pytest.mark.parametrize(
    "condition",
    [
        {"type": "INDEX_CLOSE_GTE_MA", "index_role": "BOARD_REFERENCE", "period": 2},
        {"type": "INDEX_CLOSE_LTE_MA", "index_role": "BOARD_REFERENCE", "period": 2},
        {
            "type": "INDEX_MA_NON_DECREASING",
            "index_role": "BOARD_REFERENCE",
            "period": 2,
            "lookback": 1,
        },
        {
            "type": "INDEX_MA_NON_INCREASING",
            "index_role": "BOARD_REFERENCE",
            "period": 2,
            "lookback": 1,
        },
        {
            "type": "INDEX_RETURN_GTE",
            "index_role": "BOARD_REFERENCE",
            "window": "FIVE_MINUTE_BUCKETS",
            "window_size": 2,
            "threshold_ratio": Decimal("0.25"),
        },
        {
            "type": "INDEX_RETURN_LTE",
            "index_role": "BOARD_REFERENCE",
            "window": "OFFICIAL_OPEN_DAYS",
            "window_size": 2,
            "threshold_ratio": Decimal("0"),
        },
    ],
)
def test_all_six_index_conditions_include_equality_and_exact_evidence(
    condition: dict[str, object],
) -> None:
    base = _context()
    snapshot = _reference_market_snapshot(base)
    context = _context_with_v2_condition(
        base,
        policy="entry",
        condition=condition,
        snapshot=snapshot,
    )

    evidence = evaluate_condition(
        context.plan.entry.condition,
        context,
        plan_path="entry.condition",
    )

    assert evidence.outcome is ConditionOutcome.SATISFIED
    assert isinstance(evidence.index_evidence, IndexConditionEvidence)
    assert evidence.index_evidence.plan_path == "entry.condition"
    assert evidence.index_evidence.condition_type == condition["type"]
    assert evidence.index_evidence.snapshot_hash == snapshot.snapshot_hash
    assert evidence.index_evidence.actual_value == evidence.index_evidence.comparison_value
    assert not evidence.index_evidence.missing_inputs


@pytest.mark.parametrize("policy", ["entry", "reduction", "risk", "blockers"])
def test_nested_index_evidence_uses_exact_paths_under_every_policy_root(policy: str) -> None:
    base = _context()
    snapshot = _reference_market_snapshot(base)
    tree = {
        "type": "ALL",
        "conditions": [
            {"type": "NON_DECREASING_CLOSE"},
            {
                "type": "ANY",
                "conditions": [
                    {
                        "type": "INDEX_CLOSE_GTE_MA",
                        "index_role": "BOARD_REFERENCE",
                        "period": 2,
                    }
                ],
            },
        ],
    }
    context = _context_with_v2_condition(
        base,
        policy=policy,
        condition=tree,
        snapshot=snapshot,
    )
    root = getattr(context.plan, policy).condition

    evidence = evaluate_condition(
        root,
        context,
        plan_path=f"{policy}.condition",
    )

    index_evidence = evidence.children[1].children[0].index_evidence
    assert index_evidence is not None
    assert index_evidence.plan_path == f"{policy}.condition.conditions[1].conditions[0]"


@pytest.mark.parametrize(
    ("snapshot_kind", "expected_missing"),
    [
        ("ABSENT", (MissingInputCode.INDEX_SNAPSHOT,)),
        (
            "GAPPED",
            (MissingInputCode.INDEX_HEALTH, MissingInputCode.INDEX_HISTORY),
        ),
        ("IDENTITY", (MissingInputCode.INDEX_IDENTITY,)),
        ("CUTOFF", (MissingInputCode.INDEX_CUTOFF,)),
        ("FACT", (MissingInputCode.INDEX_FACT,)),
        (
            "FORMULA",
            (MissingInputCode.INDEX_HEALTH, MissingInputCode.INDEX_FORMULA),
        ),
    ],
)
def test_index_failures_are_path_local_missing_input(
    snapshot_kind: str,
    expected_missing: tuple[MissingInputCode, ...],
) -> None:
    base = _context()
    if snapshot_kind == "ABSENT":
        snapshot = None
    elif snapshot_kind == "GAPPED":
        snapshot = _reference_market_snapshot(
            base,
            health=MarketIndexHealth.GAPPED,
            issues=(MarketIndexIssueCode.GAPPED_SERIES,),
        )
    elif snapshot_kind == "IDENTITY":
        snapshot = _reference_market_snapshot(base, index_code=MarketIndexCode.STAR_50)
    elif snapshot_kind == "CUTOFF":
        snapshot = _reference_market_snapshot(
            base,
            decision_cutoff=base.target_cutoff - timedelta(minutes=5),
        )
    elif snapshot_kind == "FACT":
        snapshot = _reference_market_snapshot(
            base,
            requests=(
                ReturnFactRequest(
                    window=ReturnWindow.OFFICIAL_OPEN_DAYS,
                    window_size=2,
                ),
            ),
        )
    else:
        snapshot = _reference_market_snapshot(
            base,
            health=MarketIndexHealth.BLOCKED,
            issues=(MarketIndexIssueCode.FORMULA_MISMATCH,),
        )
    condition = {
        "type": "INDEX_CLOSE_GTE_MA",
        "index_role": "BOARD_REFERENCE",
        "period": 2,
    }
    context = _context_with_v2_condition(
        base,
        policy="entry",
        condition=condition,
        snapshot=snapshot,
    )

    evidence = evaluate_condition(
        context.plan.entry.condition,
        context,
        plan_path="entry.condition",
    )

    assert evidence.outcome is ConditionOutcome.MISSING_INPUT
    assert evidence.missing_inputs == expected_missing
    assert evidence.index_evidence is not None
    assert evidence.index_evidence.plan_path == "entry.condition"
    assert evidence.index_evidence.actual_value is None
    assert evidence.index_evidence.comparison_value is None


def test_two_plans_reach_different_final_results_from_the_same_snapshot() -> None:
    base = _context()
    snapshot = _reference_market_snapshot(base)
    satisfied_context = _context_with_v2_condition(
        base,
        policy="entry",
        condition={
            "type": "INDEX_CLOSE_GTE_MA",
            "index_role": "BOARD_REFERENCE",
            "period": 2,
        },
        snapshot=snapshot,
    )
    unsatisfied_context = _context_with_v2_condition(
        base,
        policy="entry",
        condition={
            "type": "INDEX_RETURN_GTE",
            "index_role": "BOARD_REFERENCE",
            "window": "OFFICIAL_OPEN_DAYS",
            "window_size": 2,
            "threshold_ratio": Decimal("0.1"),
        },
        snapshot=snapshot,
    )

    satisfied = evaluate(satisfied_context)
    unsatisfied = evaluate(unsatisfied_context)

    assert satisfied_context.reference_market_snapshot is snapshot
    assert unsatisfied_context.reference_market_snapshot is snapshot
    assert satisfied.snapshot.reference_market is not None
    assert satisfied.snapshot.reference_market.index_code is snapshot.index_code
    assert satisfied.snapshot.reference_market.snapshot_hash == snapshot.snapshot_hash
    assert satisfied.snapshot.reference_market.data_at == snapshot.completed_bucket_at
    assert satisfied.snapshot.reference_market.health is snapshot.health
    assert satisfied.snapshot.signal_type is not unsatisfied.snapshot.signal_type
    assert satisfied.result_hash != unsatisfied.result_hash


def test_plan_without_index_condition_ignores_absent_or_blocked_index_data() -> None:
    base = _context()
    original_condition = base.plan.entry.condition.model_dump(
        mode="python",
        round_trip=True,
    )
    without_snapshot = _context_with_v2_condition(
        base,
        policy="entry",
        condition=original_condition,
        snapshot=None,
    )
    blocked = _reference_market_snapshot(
        base,
        health=MarketIndexHealth.BLOCKED,
        issues=(MarketIndexIssueCode.PROVIDER_UNAVAILABLE,),
    )
    with_blocked_snapshot = without_snapshot.model_copy(
        update={"reference_market_snapshot": blocked}
    )

    absent_result = evaluate(without_snapshot)
    blocked_result = evaluate(with_blocked_snapshot)

    assert absent_result == blocked_result
    assert "index_evidence" not in canonical_result_json(evaluate(base))


def _replace_latest_bar(
    context: EvaluationContext,
    **updates: object,
) -> EvaluationContext:
    bars = (
        *context.complete_5m_bars[:-1],
        context.complete_5m_bars[-1].model_copy(update=updates),
    )
    return context.model_copy(
        update={
            "complete_5m_bars": bars,
            "current_day_minutes": _current_day_minutes(bars),
            "five_minute_indicators": _five_minute_indicators(bars),
        }
    )


def _replace_last_closes(
    context: EvaluationContext,
    closes: tuple[int, ...],
) -> EvaluationContext:
    prefix = context.complete_5m_bars[: -len(closes)]
    suffix = tuple(
        bar.model_copy(
            update={
                "open_fen": close,
                "high_fen": close + 20,
                "low_fen": close - 20,
                "close_fen": close,
            }
        )
        for bar, close in zip(
            context.complete_5m_bars[-len(closes) :],
            closes,
            strict=True,
        )
    )
    bars = prefix + suffix
    return context.model_copy(
        update={
            "complete_5m_bars": bars,
            "current_day_minutes": _current_day_minutes(bars),
            "five_minute_indicators": _five_minute_indicators(bars),
        }
    )


def _with_complete_bars(
    context: EvaluationContext,
    bars: tuple[FiveMinuteBar, ...],
) -> EvaluationContext:
    if not bars:
        return context.model_copy(
            update={
                "current_day_minutes": (),
                "complete_5m_bars": (),
                "five_minute_indicators": None,
                "data_health": DataHealthSnapshot(
                    symbol=SYMBOL,
                    status=DataHealthStatus.BLOCKED,
                    latest_bar_end=None,
                    data_age_seconds=None,
                    required_data_complete=False,
                    fresh=False,
                ),
            }
        )

    latest = bars[-1]
    target_bucket_end = (
        context.target.bucket_end
        if isinstance(context.target, IntradayEvaluationTarget)
        else latest.bar_end
    )
    expected_current_ends = tuple(
        bar_end for bar_end in _session_bar_ends(TRADE_DATE) if bar_end <= target_bucket_end
    )
    current_ends = tuple(bar.bar_end for bar in bars if bar.bar_end.date() == TRADE_DATE)
    is_target_complete = (
        isinstance(context.target, IntradayEvaluationTarget)
        and latest.bar_end == context.target.bucket_end
        and current_ends == expected_current_ends
    )
    return context.model_copy(
        update={
            "current_day_minutes": _current_day_minutes(bars),
            "complete_5m_bars": bars,
            "five_minute_indicators": _five_minute_indicators(bars),
            "data_health": DataHealthSnapshot(
                symbol=SYMBOL,
                status=(DataHealthStatus.LIVE if is_target_complete else DataHealthStatus.GAPPED),
                latest_bar_end=latest.bar_end,
                data_age_seconds=int((context.evaluated_at - latest.bar_end).total_seconds()),
                required_data_complete=is_target_complete,
                fresh=is_target_complete,
            ),
        }
    )


def _append_intraday_bar(
    context: EvaluationContext,
    *,
    close_fen: int = 6400,
    low_fen: int = 6380,
    volume_shares: int = 100,
) -> EvaluationContext:
    assert isinstance(context.target, IntradayEvaluationTarget)
    indicator_snapshot = context.daily_indicator_snapshot
    assert indicator_snapshot is not None
    bar_end = context.target.bucket_end + timedelta(minutes=5)
    bar = _bar(
        bar_end,
        open_fen=close_fen,
        high_fen=max(close_fen, 6420),
        low_fen=low_fen,
        close_fen=close_fen,
        volume_shares=volume_shares,
    )
    bars = (*context.complete_5m_bars, bar)
    source_bar = indicator_snapshot.source_bar.model_copy(
        update={
            "high_fen": max(indicator_snapshot.source_bar.high_fen, close_fen),
            "low_fen": min(indicator_snapshot.source_bar.low_fen, low_fen),
            "close_fen": close_fen,
            "received_at": bar_end,
        }
    )
    reconciliation = reconcile_daily_close(
        symbol=SYMBOL,
        current_trade_date=TRADE_DATE,
        daily_bars=(source_bar,),
    )
    evaluated_at = bar_end + timedelta(minutes=1)
    return context.model_copy(
        update={
            "evaluated_at": evaluated_at,
            "target": IntradayEvaluationTarget(bucket_end=bar_end),
            "current_day_minutes": (*context.current_day_minutes, *_current_bucket_minutes(bar)),
            "complete_5m_bars": bars,
            "five_minute_indicators": _five_minute_indicators(bars),
            "daily_indicator_snapshot": indicator_snapshot.model_copy(
                update={
                    "source_as_of": bar_end,
                    "source_bar": reconciliation.provisional_bar,
                }
            ),
            "close_reconciliation": reconciliation,
            "data_health": DataHealthSnapshot(
                symbol=SYMBOL,
                status=DataHealthStatus.LIVE,
                latest_bar_end=bar_end,
                data_age_seconds=60,
                required_data_complete=True,
                fresh=True,
            ),
        }
    )


def _without_current_minutes(context: EvaluationContext) -> EvaluationContext:
    return context.model_copy(
        update={
            "current_day_minutes": (),
            "data_health": context.data_health.model_copy(
                update={
                    "status": DataHealthStatus.GAPPED,
                    "required_data_complete": False,
                }
            ),
        }
    )


def _with_latest_price(context: EvaluationContext, price_fen: int) -> EvaluationContext:
    return _replace_latest_bar(
        context,
        open_fen=price_fen,
        high_fen=price_fen,
        low_fen=price_fen,
        close_fen=price_fen,
    )


def _session_bar_ends(trade_date: date) -> tuple[datetime, ...]:
    session_minutes = (
        *range(9 * 60 + 35, 11 * 60 + 31, 5),
        *range(13 * 60 + 5, 15 * 60 + 1, 5),
    )
    return tuple(
        datetime(
            trade_date.year,
            trade_date.month,
            trade_date.day,
            minute_of_day // 60,
            minute_of_day % 60,
            tzinfo=SHANGHAI,
        )
        for minute_of_day in session_minutes
    )


def _recent_session_bars(count: int) -> tuple[FiveMinuteBar, ...]:
    trade_dates: list[date] = []
    candidate = TRADE_DATE
    while len(trade_dates) < 12:
        if candidate.weekday() < 5:
            trade_dates.append(candidate)
        candidate -= timedelta(days=1)
    all_ends = tuple(
        bar_end
        for trade_date in reversed(trade_dates)
        for bar_end in _session_bar_ends(trade_date)
        if trade_date < TRADE_DATE or bar_end <= datetime(2026, 8, 7, 11, 15, tzinfo=SHANGHAI)
    )
    return tuple(
        _bar(
            bar_end,
            open_fen=6905,
            high_fen=6920,
            low_fen=6880,
            close_fen=6905,
        )
        for bar_end in all_ends[-count:]
    )


def _previous_weekday(value: date) -> date:
    candidate = value - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def _with_calendar_for_bars(context: EvaluationContext) -> EvaluationContext:
    trade_dates = tuple(sorted({bar.bar_end.date() for bar in context.complete_5m_bars}))
    return context.model_copy(
        update={
            "trading_calendar": tuple(
                TradingDay(
                    exchange="SZSE",
                    cal_date=trade_date,
                    is_open=True,
                    previous_trade_date=_previous_weekday(trade_date),
                )
                for trade_date in trade_dates
            )
        }
    )


def _with_official_close(
    context: EvaluationContext,
    close_fen: int,
) -> EvaluationContext:
    official = DailyBar(
        symbol=SYMBOL,
        trade_date=TRADE_DATE,
        open_fen=6100,
        high_fen=max(6120, close_fen),
        low_fen=min(6050, close_fen),
        close_fen=close_fen,
        volume_shares=10_000,
        amount_yuan=Decimal("610000"),
        is_official=True,
        received_at=datetime(2026, 8, 7, 15, 30, tzinfo=SHANGHAI),
    )
    reconciliation = reconcile_daily_close(
        symbol=SYMBOL,
        current_trade_date=TRADE_DATE,
        daily_bars=(official,),
    )
    evaluated_at = datetime(2026, 8, 7, 15, 31, tzinfo=SHANGHAI)
    return context.model_copy(
        update={
            "evaluated_at": evaluated_at,
            "target": OfficialCloseEvaluationTarget(trade_date=TRADE_DATE),
            "close_reconciliation": reconciliation,
            "daily_indicator_snapshot": DailyIndicatorSnapshot(
                series=context.daily_indicators,
                provenance=DailyIndicatorProvenance.OFFICIAL,
                source_as_of=datetime(2026, 8, 7, 15, 0, tzinfo=SHANGHAI),
                source_bar=official,
            ),
            "data_health": context.data_health.model_copy(
                update={
                    "status": DataHealthStatus.STALE,
                    "data_age_seconds": int(
                        (evaluated_at - context.data_health.latest_bar_end).total_seconds()
                    ),
                    "fresh": False,
                }
            ),
        }
    )


def _with_breached_risk(context: EvaluationContext) -> EvaluationContext:
    return context.model_copy(
        update={
            "risk_state": RiskStateSnapshot(
                symbol=SYMBOL,
                plan_hash=context.plan_hash,
                status=RiskStatus.BREACHED_PENDING_CONFIRMATION,
                breach_trade_date=PREVIOUS_TRADE_DATE,
                prior_close_fen=6070,
                revision=1,
                updated_at=datetime(2026, 8, 6, 15, 31, tzinfo=SHANGHAI),
            )
        }
    )


def _official_risk_context(
    *,
    target_date: date = TRADE_DATE,
    current_close_fen: int = 6070,
    current_volume_shares: int = 10_000,
    current_macd_histogram: float = -0.10,
    risk_status: RiskStatus = RiskStatus.BREACHED_PENDING_CONFIRMATION,
    breach_trade_date: date = PREVIOUS_TRADE_DATE,
    breach_close_fen: int = 6070,
    breach_volume_shares: int = 9_000,
    breach_macd_histogram: float = -0.10,
    previous_trade_date: date = PREVIOUS_TRADE_DATE,
    is_open: bool = True,
    include_breach_bar: bool = True,
    include_daily_indicators: bool = True,
    positions: tuple[PositionLotSnapshot, ...] = (),
) -> EvaluationContext:
    plan = load_plan_yaml(SAMPLE_PATH.read_text(encoding="utf-8"))
    plan_hash = plan_sha256(plan)
    evaluated_at = datetime(
        target_date.year,
        target_date.month,
        target_date.day,
        15,
        31,
        tzinfo=SHANGHAI,
    )
    official = DailyBar(
        symbol=SYMBOL,
        trade_date=target_date,
        open_fen=current_close_fen,
        high_fen=current_close_fen + 20,
        low_fen=max(1, current_close_fen - 20),
        close_fen=current_close_fen,
        volume_shares=current_volume_shares,
        amount_yuan=Decimal(current_volume_shares),
        is_official=True,
        received_at=evaluated_at - timedelta(minutes=1),
    )
    reconciliation = reconcile_daily_close(
        symbol=SYMBOL,
        current_trade_date=target_date,
        daily_bars=(official,),
    )
    breach_bar = DailyBar(
        symbol=SYMBOL,
        trade_date=breach_trade_date,
        open_fen=breach_close_fen,
        high_fen=breach_close_fen + 20,
        low_fen=max(1, breach_close_fen - 20),
        close_fen=breach_close_fen,
        volume_shares=breach_volume_shares,
        amount_yuan=Decimal(breach_volume_shares),
        is_official=True,
        received_at=datetime(
            breach_trade_date.year,
            breach_trade_date.month,
            breach_trade_date.day,
            15,
            30,
            tzinfo=SHANGHAI,
        ),
    )
    history = (breach_bar,) if include_breach_bar else ()
    indicator_snapshot = None
    if include_daily_indicators:
        indicator_points = (
            *(
                (
                    _point(
                        breach_trade_date,
                        macd_histogram_yuan=breach_macd_histogram,
                    ),
                )
                if include_breach_bar
                else ()
            ),
            _point(
                target_date,
                macd_histogram_yuan=current_macd_histogram,
            ),
        )
        indicator_snapshot = DailyIndicatorSnapshot(
            series=IndicatorSeries(symbol=SYMBOL, points=indicator_points),
            provenance=DailyIndicatorProvenance.OFFICIAL,
            source_as_of=datetime(
                target_date.year,
                target_date.month,
                target_date.day,
                15,
                0,
                tzinfo=SHANGHAI,
            ),
            source_bar=official,
        )
    if risk_status is RiskStatus.CLEAR:
        risk = RiskStateSnapshot(
            symbol=SYMBOL,
            plan_hash=plan_hash,
            status=RiskStatus.CLEAR,
            breach_trade_date=None,
            prior_close_fen=6400,
            revision=0,
            updated_at=datetime(
                target_date.year,
                target_date.month,
                target_date.day,
                9,
                30,
                tzinfo=SHANGHAI,
            ),
        )
    else:
        risk = RiskStateSnapshot(
            symbol=SYMBOL,
            plan_hash=plan_hash,
            status=risk_status,
            breach_trade_date=breach_trade_date,
            prior_close_fen=breach_close_fen,
            revision=(1 if risk_status is RiskStatus.BREACHED_PENDING_CONFIRMATION else 2),
            updated_at=datetime(
                breach_trade_date.year,
                breach_trade_date.month,
                breach_trade_date.day,
                15,
                0,
                tzinfo=SHANGHAI,
            ),
        )
    return EvaluationContext(
        evaluated_at=evaluated_at,
        target=OfficialCloseEvaluationTarget(trade_date=target_date),
        plan=plan,
        plan_hash=plan_hash,
        plan_active=True,
        activated_at=datetime(2026, 8, 1, 9, 0, tzinfo=SHANGHAI),
        current_day_minutes=(),
        complete_5m_bars=(),
        official_daily_bars=history,
        five_minute_indicators=None,
        daily_indicator_snapshot=indicator_snapshot,
        close_reconciliation=reconciliation,
        trading_calendar=(
            TradingDay(
                exchange="SZSE",
                cal_date=target_date,
                is_open=is_open,
                previous_trade_date=previous_trade_date,
            ),
        ),
        daily_limit=None,
        data_health=DataHealthSnapshot(
            symbol=SYMBOL,
            status=DataHealthStatus.CLOSE_PENDING,
            latest_bar_end=None,
            data_age_seconds=None,
            required_data_complete=False,
            fresh=False,
        ),
        positions=positions,
        low_zone_episode=None,
        risk_state=risk,
        manual_event_risk=False,
    )


def _provisional_1500_risk_context(close_fen: int) -> EvaluationContext:
    base = _context()
    bar_ends = _session_bar_ends(TRADE_DATE)
    bars = tuple(
        _bar(
            bar_end,
            open_fen=close_fen if index == len(bar_ends) - 1 else 6400,
            high_fen=close_fen if index == len(bar_ends) - 1 else 6400,
            low_fen=close_fen if index == len(bar_ends) - 1 else 6400,
            close_fen=close_fen if index == len(bar_ends) - 1 else 6400,
        )
        for index, bar_end in enumerate(bar_ends)
    )
    target_end = bar_ends[-1]
    provisional = DailyBar(
        symbol=SYMBOL,
        trade_date=TRADE_DATE,
        open_fen=6400,
        high_fen=6400,
        low_fen=min(6400, close_fen),
        close_fen=close_fen,
        volume_shares=10_000,
        amount_yuan=Decimal("640000"),
        is_official=False,
        received_at=target_end,
    )
    reconciliation = reconcile_daily_close(
        symbol=SYMBOL,
        current_trade_date=TRADE_DATE,
        daily_bars=(provisional,),
    )
    evaluated_at = target_end + timedelta(minutes=1)
    return base.model_copy(
        update={
            "evaluated_at": evaluated_at,
            "target": IntradayEvaluationTarget(bucket_end=target_end),
            "current_day_minutes": _current_day_minutes(bars),
            "complete_5m_bars": bars,
            "five_minute_indicators": _five_minute_indicators(bars),
            "daily_indicator_snapshot": DailyIndicatorSnapshot(
                series=_daily_indicators(),
                provenance=DailyIndicatorProvenance.PROVISIONAL,
                source_as_of=target_end,
                source_bar=provisional,
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
            "low_zone_episode": None,
        }
    )


def _with_sellable_tactical(context: EvaluationContext) -> EvaluationContext:
    return context.model_copy(
        update={
            "positions": (
                PositionLotSnapshot(
                    lot_id="lot-tactical-001",
                    symbol=SYMBOL,
                    bucket="TACTICAL",
                    quantity=100,
                    remaining_quantity=100,
                    acquired_trade_date=PREVIOUS_TRADE_DATE,
                    cost_fen=6400,
                ),
            )
        }
    )


def _facts(evidence: ConditionEvidence) -> dict[str, object]:
    return {fact.key: fact.value for fact in evidence.facts}


def _with_entry_condition(
    context: EvaluationContext,
    condition: ConditionNode,
) -> EvaluationContext:
    plan = context.plan.model_copy(
        update={"entry": context.plan.entry.model_copy(update={"condition": condition})}
    )
    plan_hash = plan_sha256(plan)
    episode = context.low_zone_episode
    return context.model_copy(
        update={
            "plan": plan,
            "plan_hash": plan_hash,
            "low_zone_episode": (
                None if episode is None else episode.model_copy(update={"plan_hash": plan_hash})
            ),
            "risk_state": context.risk_state.model_copy(update={"plan_hash": plan_hash}),
        }
    )


def _rule_evidence(
    result: EvaluationResult,
    code: RuleEvidenceCode,
) -> RuleEvidence:
    return next(
        evidence
        for evidence in result.snapshot.condition_evidence
        if isinstance(evidence, RuleEvidence) and evidence.code is code
    )


def _neutral_snapshot(
    context: EvaluationContext,
    *,
    evaluated_at: datetime,
    market_data_at: datetime | None,
    price_fen: int | None,
    risk: RiskStateSnapshot | None = None,
    episode: LowZoneEpisodeSnapshot | None = None,
) -> SymbolDecisionSnapshot:
    data_health = context.data_health
    if evaluated_at != context.evaluated_at and data_health.latest_bar_end is not None:
        data_health = data_health.model_copy(
            update={
                "status": DataHealthStatus.STALE,
                "data_age_seconds": int(
                    (evaluated_at - data_health.latest_bar_end).total_seconds()
                ),
                "fresh": False,
            }
        )
    return SymbolDecisionSnapshot(
        symbol=SYMBOL,
        plan_id=context.plan.plan_id,
        plan_version=context.plan.version,
        plan_hash=context.plan_hash,
        evaluated_at=evaluated_at,
        market_data_at=market_data_at,
        price_fen=price_fen,
        zone=DecisionZone.UNKNOWN,
        signal_type=SignalType.WAIT,
        position=PositionSummary(
            core_quantity=0,
            tactical_quantity=0,
            total_quantity=0,
            sellable_core_quantity=0,
            sellable_tactical_quantity=0,
        ),
        episode=episode,
        risk=risk or context.risk_state,
        data_health=data_health,
        condition_evidence=(),
        next_step=NextStep(code=NextStepCode.WAIT_FOR_COMPLETE_BAR),
    )


def test_evaluation_context_is_immutable_closed_and_revalidates_copy_updates() -> None:
    context = _context()

    with pytest.raises(ValidationError):
        context.evaluated_at = datetime(2026, 8, 7, 12, 0, tzinfo=SHANGHAI)
    with pytest.raises(ValidationError, match="plan_hash"):
        context.model_copy(update={"plan_hash": "0" * 64})
    with pytest.raises(ValidationError):
        context.model_copy(update={"complete_5m_bars": list(context.complete_5m_bars)})
    with pytest.raises(ValidationError):
        EvaluationContext.model_validate(
            {**context.model_dump(mode="python"), "unexpected": "forbidden"}
        )


def test_evaluation_context_exposes_complete_current_day_minutes_and_calendar_history() -> None:
    context = _context()

    assert len(context.current_day_minutes) == 105
    assert len(context.current_bucket_minutes) == 5
    assert context.current_day_minutes[-5:] == context.current_bucket_minutes
    assert context.trading_calendar[-1] == context.trading_day


def test_current_bucket_lookup_does_not_rescan_the_complete_session(monkeypatch) -> None:
    context = _context()
    original = decision_models_module.five_minute_bucket_end
    observed_calls = 0

    def observed_bucket_end(value):
        nonlocal observed_calls
        observed_calls += 1
        return original(value)

    monkeypatch.setattr(
        decision_models_module,
        "five_minute_bucket_end",
        observed_bucket_end,
    )

    assert context.current_bucket_minutes == context.current_day_minutes[-5:]
    assert observed_calls <= 2


def test_evaluation_context_accepts_exactly_240_current_day_minutes_and_rejects_241() -> None:
    bars = tuple(_bar(bar_end) for bar_end in _session_bar_ends(TRADE_DATE))
    target_end = bars[-1].bar_end
    provisional = _provisional_bar().model_copy(update={"received_at": target_end})
    reconciliation = reconcile_daily_close(
        symbol=SYMBOL,
        current_trade_date=TRADE_DATE,
        daily_bars=(provisional,),
    )
    context = _context().model_copy(
        update={
            "evaluated_at": target_end + timedelta(minutes=1),
            "target": IntradayEvaluationTarget(bucket_end=target_end),
            "current_day_minutes": _current_day_minutes(bars),
            "complete_5m_bars": bars,
            "five_minute_indicators": _five_minute_indicators(bars),
            "daily_indicator_snapshot": DailyIndicatorSnapshot(
                series=_daily_indicators(),
                provenance=DailyIndicatorProvenance.PROVISIONAL,
                source_as_of=target_end,
                source_bar=provisional,
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

    assert len(context.current_day_minutes) == 240
    assert context.daily_indicator_snapshot.provenance is DailyIndicatorProvenance.PROVISIONAL
    with pytest.raises(ValidationError, match="240|too_long"):
        context.model_copy(
            update={
                "current_day_minutes": context.current_day_minutes
                + (context.current_day_minutes[-1],)
            }
        )


def test_evaluation_context_rejects_partial_or_gap_claimed_complete_minute_slices() -> None:
    context = _context()
    gapped_health = context.data_health.model_copy(
        update={
            "status": DataHealthStatus.GAPPED,
            "required_data_complete": False,
        }
    )

    with pytest.raises(ValidationError, match="exactly five"):
        context.model_copy(
            update={
                "current_day_minutes": context.current_day_minutes[:-1],
                "data_health": gapped_health,
            }
        )
    with pytest.raises(ValidationError, match="gapless"):
        context.model_copy(update={"current_day_minutes": context.current_day_minutes[5:]})


@pytest.mark.parametrize("calendar_state", ["missing", "closed"])
def test_complete_intraday_context_requires_an_open_target_calendar_day(
    calendar_state: str,
) -> None:
    context = _context()
    target_day = context.trading_day
    assert target_day is not None
    calendar = (
        () if calendar_state == "missing" else (target_day.model_copy(update={"is_open": False}),)
    )

    with pytest.raises(ValidationError, match="open target trading calendar"):
        context.model_copy(update={"trading_calendar": calendar})


def test_evaluation_context_validates_the_supplied_trading_calendar_chain() -> None:
    context = _context()
    august_4 = date(2026, 8, 4)
    august_5 = date(2026, 8, 5)
    calendar_prefix = (
        TradingDay(
            exchange="SZSE",
            cal_date=august_5,
            is_open=True,
            previous_trade_date=august_4,
        ),
    )
    known_intermediate_open = calendar_prefix + (
        TradingDay(
            exchange="SZSE",
            cal_date=PREVIOUS_TRADE_DATE,
            is_open=True,
            previous_trade_date=august_5,
        ),
        TradingDay(
            exchange="SZSE",
            cal_date=TRADE_DATE,
            is_open=True,
            previous_trade_date=august_5,
        ),
    )
    supplied_closed_predecessor = (
        TradingDay(
            exchange="SZSE",
            cal_date=august_5,
            is_open=False,
            previous_trade_date=august_4,
        ),
        TradingDay(
            exchange="SZSE",
            cal_date=TRADE_DATE,
            is_open=True,
            previous_trade_date=august_5,
        ),
    )

    with pytest.raises(ValidationError, match="calendar.*open|open.*calendar"):
        context.model_copy(update={"trading_calendar": known_intermediate_open})
    with pytest.raises(ValidationError, match="previous.*open|open.*previous"):
        context.model_copy(update={"trading_calendar": supplied_closed_predecessor})

    closed_between = calendar_prefix + (
        TradingDay(
            exchange="SZSE",
            cal_date=PREVIOUS_TRADE_DATE,
            is_open=False,
            previous_trade_date=august_5,
        ),
        TradingDay(
            exchange="SZSE",
            cal_date=TRADE_DATE,
            is_open=True,
            previous_trade_date=august_5,
        ),
    )
    assert (
        context.model_copy(update={"trading_calendar": closed_between}).trading_day
        == (closed_between[-1])
    )


def test_evaluation_context_bounds_trading_calendar_history_at_512_rows() -> None:
    context = _context()
    start = TRADE_DATE - timedelta(days=511)
    calendar = tuple(
        TradingDay(
            exchange="SZSE",
            cal_date=start + timedelta(days=index),
            is_open=True,
            previous_trade_date=start + timedelta(days=index - 1),
        )
        for index in range(512)
    )

    assert len(context.model_copy(update={"trading_calendar": calendar}).trading_calendar) == 512
    with pytest.raises(ValidationError, match="512|too_long"):
        context.model_copy(
            update={
                "trading_calendar": (
                    TradingDay(
                        exchange="SZSE",
                        cal_date=start - timedelta(days=1),
                        is_open=True,
                        previous_trade_date=start - timedelta(days=2),
                    ),
                    *calendar,
                )
            }
        )


def test_evaluation_context_rejects_cross_symbol_and_formula_mismatches() -> None:
    context = _context()
    foreign_bar = context.complete_5m_bars[-1].model_copy(update={"symbol": "600000.SH"})
    foreign_indicators = context.daily_indicators.model_copy(update={"symbol": "600000.SH"})

    with pytest.raises(ValidationError, match="bar symbol"):
        context.model_copy(
            update={"complete_5m_bars": (*context.complete_5m_bars[:-1], foreign_bar)}
        )
    with pytest.raises(ValidationError, match="indicator source symbol"):
        context.model_copy(
            update={
                "daily_indicator_snapshot": context.daily_indicator_snapshot.model_copy(
                    update={"series": foreign_indicators}
                )
            }
        )


def test_evaluation_context_carries_activation_and_indicator_source_facts() -> None:
    context = _context()

    assert context.plan_active is True
    assert context.activated_at == datetime(2026, 8, 7, 9, 0, tzinfo=SHANGHAI)
    assert len(context.current_bucket_minutes) == 5
    assert context.official_daily_bars == (_official_history_bar(),)
    assert context.close_reconciliation.provisional_bar == _provisional_bar()
    assert context.close_reconciliation.official_bar is None

    with pytest.raises(ValidationError, match="activation timestamp"):
        context.model_copy(update={"plan_active": False})
    with pytest.raises(ValidationError, match="gapless current-day minutes"):
        context.model_copy(update={"current_day_minutes": ()})
    with pytest.raises(ValidationError, match="reconciliation provenance"):
        context.model_copy(update={"close_reconciliation": None})


def test_evaluation_context_rejects_state_facts_after_the_evaluation_target() -> None:
    context = _context()
    after_target = context.target.bucket_end + timedelta(minutes=1)
    after_episode_target = context.target.bucket_end + timedelta(minutes=5)

    with pytest.raises(ValidationError, match="activate.*target|target.*activat"):
        context.model_copy(update={"activated_at": after_target})
    with pytest.raises(ValidationError, match="episode.*target|target.*episode"):
        context.model_copy(
            update={
                "evaluated_at": after_episode_target + timedelta(minutes=1),
                "data_health": context.data_health.model_copy(update={"data_age_seconds": 360}),
                "low_zone_episode": context.low_zone_episode.model_copy(
                    update={
                        "started_at": after_episode_target,
                        "last_processed_bucket_end": after_episode_target,
                    }
                ),
            }
        )
    with pytest.raises(ValidationError, match="risk.*target|target.*risk"):
        context.model_copy(
            update={
                "risk_state": context.risk_state.model_copy(update={"updated_at": after_target})
            }
        )


def test_low_zone_episode_processing_cursor_is_canonical_and_bounded() -> None:
    context = _context()
    assert context.low_zone_episode is not None
    payload = context.low_zone_episode.model_dump(mode="python", round_trip=True)
    payload["last_processed_bucket_end"] = datetime(
        2026,
        8,
        7,
        11,
        10,
        tzinfo=SHANGHAI,
    )

    episode = LowZoneEpisodeSnapshot.model_validate(payload)

    assert episode.last_processed_bucket_end == datetime(
        2026,
        8,
        7,
        11,
        10,
        tzinfo=SHANGHAI,
    )
    with pytest.raises(ValidationError, match="five-minute|bucket"):
        episode.model_copy(
            update={
                "last_processed_bucket_end": datetime(
                    2026,
                    8,
                    7,
                    11,
                    11,
                    tzinfo=SHANGHAI,
                )
            }
        )
    with pytest.raises(ValidationError, match="touch|start"):
        episode.model_copy(
            update={
                "last_processed_bucket_end": datetime(
                    2026,
                    8,
                    6,
                    15,
                    0,
                    tzinfo=SHANGHAI,
                )
            }
        )
    with pytest.raises(ValidationError, match="cursor.*target|target.*cursor"):
        context.model_copy(
            update={
                "low_zone_episode": episode.model_copy(
                    update={
                        "last_processed_bucket_end": context.target.bucket_end
                        + timedelta(minutes=5)
                    }
                )
            }
        )


def test_evaluation_context_allows_market_receipt_after_target_before_evaluation() -> None:
    context = _context()
    received_at = context.target.bucket_end + timedelta(seconds=30)
    provisional = context.close_reconciliation.provisional_bar.model_copy(
        update={"received_at": received_at}
    )
    reconciliation = reconcile_daily_close(
        symbol=SYMBOL,
        current_trade_date=TRADE_DATE,
        daily_bars=(provisional,),
    )

    updated = context.model_copy(
        update={
            "daily_indicator_snapshot": context.daily_indicator_snapshot.model_copy(
                update={"source_bar": provisional}
            ),
            "close_reconciliation": reconciliation,
        }
    )

    assert updated.daily_indicator_snapshot.source_as_of == context.target.bucket_end
    assert updated.daily_indicator_snapshot.source_bar.received_at == received_at


def test_evaluation_context_rejects_a_rehashed_cross_field_invalid_plan() -> None:
    context = _context()
    invalid_position = context.plan.position.model_copy(
        update={
            "max_qty": 200,
            "core_target_qty": 200,
            "tactical_target_qty": 100,
        }
    )
    invalid_plan = context.plan.model_copy(update={"position": invalid_position})
    invalid_hash = plan_sha256(invalid_plan)

    with pytest.raises(ValidationError, match="cross-field semantic"):
        context.model_copy(
            update={
                "plan": invalid_plan,
                "plan_hash": invalid_hash,
                "low_zone_episode": context.low_zone_episode.model_copy(
                    update={"plan_hash": invalid_hash}
                ),
                "risk_state": context.risk_state.model_copy(update={"plan_hash": invalid_hash}),
            }
        )


def test_condition_registry_is_closed_read_only_and_covers_every_typed_condition() -> None:
    expected = {
        PriceInZoneCondition,
        NoNewLowForBarsCondition,
        NonDecreasingCloseCondition,
        VolumeToPreviousLteCondition,
        VolumeToMedianLteCondition,
        VolumeToMedianGteCondition,
        MacdHistImprovementGteCondition,
        PriceReclaimsIndicatorCondition,
        UpperWickRatioGteCondition,
        RetreatFromSessionHighGteCondition,
        CloseInBarLowerHalfCondition,
        ConsecutiveClosesBelowLevelCondition,
        OfficialCloseBelowLevelCondition,
        NextTradingDayRecoveryCondition,
        PositionBucketAvailableCondition,
        SellableQuantityGteCondition,
        ManualEventRiskClearCondition,
        DistanceFromLimitDownGteCondition,
        LowerBandHitsLteCondition,
        IndexCloseGteMaCondition,
        IndexCloseLteMaCondition,
        IndexMaNonDecreasingCondition,
        IndexMaNonIncreasingCondition,
        IndexReturnGteCondition,
        IndexReturnLteCondition,
        AllCondition,
        AnyCondition,
    }

    assert isinstance(CONDITION_EVALUATORS, MappingProxyType)
    assert set(CONDITION_EVALUATORS) == expected
    with pytest.raises(TypeError):
        CONDITION_EVALUATORS[PriceInZoneCondition] = lambda *_: None  # type: ignore[index]


@pytest.mark.parametrize(
    ("condition_payload", "transform", "expected_fact"),
    [
        ({"type": "PRICE_IN_ZONE", "zone": "LOW_BUY"}, lambda value: value, "price_fen"),
        ({"type": "NO_NEW_LOW_FOR_BARS", "bars": 2}, lambda value: value, "bars_since_low"),
        ({"type": "NON_DECREASING_CLOSE"}, lambda value: value, "close_delta_fen"),
        (
            {"type": "VOLUME_TO_PREVIOUS_LTE", "max_ratio": Decimal("1.00")},
            lambda value: value,
            "latest_volume_shares",
        ),
        (
            {
                "type": "VOLUME_TO_MEDIAN_LTE",
                "max_ratio": Decimal("1.50"),
                "window_bars": 20,
            },
            lambda value: value,
            "median_volume_shares",
        ),
        (
            {
                "type": "VOLUME_TO_MEDIAN_GTE",
                "minimum_ratio": Decimal("1.50"),
                "window_bars": 20,
            },
            lambda value: _replace_latest_bar(value, volume_shares=150),
            "median_volume_shares",
        ),
        (
            {
                "type": "MACD_HIST_IMPROVEMENT_GTE",
                "minimum_improvement": Decimal("0.02"),
            },
            lambda value: value,
            "macd_histogram_improvement_yuan",
        ),
        (
            {"type": "PRICE_RECLAIMS_INDICATOR", "indicator": "EMA10"},
            lambda value: value,
            "indicator_yuan",
        ),
        (
            {"type": "UPPER_WICK_RATIO_GTE", "minimum_ratio": Decimal("0.40")},
            lambda value: value,
            "upper_wick_ratio",
        ),
        (
            {
                "type": "RETREAT_FROM_SESSION_HIGH_GTE",
                "minimum_ratio": Decimal("0.01"),
            },
            lambda value: _replace_latest_bar(
                value,
                open_fen=6450,
                high_fen=6500,
                low_fen=6400,
                close_fen=6435,
            ),
            "retreat_ratio",
        ),
        ({"type": "CLOSE_IN_BAR_LOWER_HALF"}, lambda value: value, "bar_midpoint_twice_fen"),
        (
            {
                "type": "CONSECUTIVE_CLOSES_BELOW_LEVEL",
                "level": "PRESSURE_REFERENCE",
                "bars": 2,
            },
            lambda value: value,
            "consecutive_bars",
        ),
        (
            {"type": "OFFICIAL_CLOSE_BELOW_LEVEL", "level": "RISK_LINE"},
            lambda value: _with_official_close(value, 6079),
            "official_close_fen",
        ),
        (
            {"type": "NEXT_TRADING_DAY_RECOVERY", "level": "RISK_LINE"},
            lambda value: _with_breached_risk(_with_official_close(value, 6080)),
            "official_close_fen",
        ),
        (
            {"type": "POSITION_BUCKET_AVAILABLE", "bucket": "CORE"},
            lambda value: value,
            "available_quantity",
        ),
        (
            {"type": "SELLABLE_QUANTITY_GTE", "bucket": "TACTICAL", "quantity": 100},
            _with_sellable_tactical,
            "sellable_quantity",
        ),
        (
            {"type": "MANUAL_EVENT_RISK_CLEAR"},
            lambda value: value,
            "manual_event_risk",
        ),
        (
            {
                "type": "DISTANCE_FROM_LIMIT_DOWN_GTE",
                "minimum_ratio": Decimal("0.01"),
            },
            lambda value: value,
            "distance_from_limit_down_ratio",
        ),
        (
            {"type": "LOWER_BAND_HITS_LTE", "max_hits": 3, "window_bars": 4},
            lambda value: value,
            "lower_band_hit_count",
        ),
    ],
    ids=lambda value: value.get("type", "context") if isinstance(value, dict) else None,
)
def test_every_leaf_condition_returns_satisfied_numeric_evidence(
    condition_payload: ConditionPayload,
    transform: ContextTransform,
    expected_fact: str,
) -> None:
    context = transform(_context())
    before = context.model_dump(mode="json")

    evidence = evaluate_condition(_condition(condition_payload), context)

    assert evidence.outcome is ConditionOutcome.SATISFIED
    assert expected_fact in _facts(evidence)
    assert evidence.missing_inputs == ()
    assert context.model_dump(mode="json") == before


@pytest.mark.parametrize(
    ("condition_payload", "transform"),
    [
        (
            {"type": "PRICE_IN_ZONE", "zone": "LOW_BUY"},
            lambda value: _replace_latest_bar(
                value,
                open_fen=6451,
                high_fen=6470,
                low_fen=6451,
                close_fen=6451,
            ),
        ),
        (
            {"type": "NO_NEW_LOW_FOR_BARS", "bars": 2},
            lambda value: value.model_copy(
                update={"low_zone_episode": _episode(value.plan_hash, bars_since_low=1)}
            ),
        ),
        (
            {"type": "NON_DECREASING_CLOSE"},
            lambda value: _replace_last_closes(value, (6400, 6399)),
        ),
        (
            {"type": "VOLUME_TO_PREVIOUS_LTE", "max_ratio": Decimal("1.00")},
            lambda value: _replace_latest_bar(value, volume_shares=101),
        ),
        (
            {
                "type": "VOLUME_TO_MEDIAN_LTE",
                "max_ratio": Decimal("1.50"),
                "window_bars": 20,
            },
            lambda value: _replace_latest_bar(value, volume_shares=151),
        ),
        (
            {
                "type": "VOLUME_TO_MEDIAN_GTE",
                "minimum_ratio": Decimal("1.50"),
                "window_bars": 20,
            },
            lambda value: _replace_latest_bar(value, volume_shares=149),
        ),
        (
            {
                "type": "MACD_HIST_IMPROVEMENT_GTE",
                "minimum_improvement": Decimal("0.02"),
            },
            lambda value: value.model_copy(
                update={
                    "daily_indicator_snapshot": value.daily_indicator_snapshot.model_copy(
                        update={"series": _daily_indicators(current_histogram=-0.0801)}
                    )
                }
            ),
        ),
        (
            {"type": "PRICE_RECLAIMS_INDICATOR", "indicator": "EMA10"},
            lambda value: _replace_latest_bar(
                value,
                open_fen=6399,
                high_fen=6410,
                low_fen=6380,
                close_fen=6399,
            ),
        ),
        (
            {"type": "UPPER_WICK_RATIO_GTE", "minimum_ratio": Decimal("0.40")},
            lambda value: _replace_latest_bar(
                value,
                open_fen=6405,
                high_fen=6420,
                low_fen=6380,
                close_fen=6405,
            ),
        ),
        (
            {
                "type": "RETREAT_FROM_SESSION_HIGH_GTE",
                "minimum_ratio": Decimal("0.01"),
            },
            lambda value: _replace_latest_bar(
                value,
                open_fen=6450,
                high_fen=6500,
                low_fen=6400,
                close_fen=6436,
            ),
        ),
        (
            {"type": "CLOSE_IN_BAR_LOWER_HALF"},
            lambda value: _replace_latest_bar(value, close_fen=6401),
        ),
        (
            {
                "type": "CONSECUTIVE_CLOSES_BELOW_LEVEL",
                "level": "PRESSURE_REFERENCE",
                "bars": 2,
            },
            lambda value: _replace_last_closes(value, (6905, 6906)),
        ),
        (
            {"type": "OFFICIAL_CLOSE_BELOW_LEVEL", "level": "RISK_LINE"},
            lambda value: _with_official_close(value, 6080),
        ),
        (
            {"type": "NEXT_TRADING_DAY_RECOVERY", "level": "RISK_LINE"},
            lambda value: _with_breached_risk(_with_official_close(value, 6079)),
        ),
        (
            {"type": "POSITION_BUCKET_AVAILABLE", "bucket": "CORE"},
            lambda value: value.model_copy(
                update={
                    "positions": (
                        PositionLotSnapshot(
                            lot_id="lot-core-001",
                            symbol=SYMBOL,
                            bucket="CORE",
                            quantity=100,
                            remaining_quantity=100,
                            acquired_trade_date=PREVIOUS_TRADE_DATE,
                            cost_fen=6400,
                        ),
                    )
                }
            ),
        ),
        (
            {"type": "SELLABLE_QUANTITY_GTE", "bucket": "TACTICAL", "quantity": 100},
            lambda value: value.model_copy(
                update={
                    "positions": (
                        PositionLotSnapshot(
                            lot_id="lot-tactical-today",
                            symbol=SYMBOL,
                            bucket="TACTICAL",
                            quantity=100,
                            remaining_quantity=100,
                            acquired_trade_date=TRADE_DATE,
                            cost_fen=6400,
                        ),
                    )
                }
            ),
        ),
        (
            {"type": "MANUAL_EVENT_RISK_CLEAR"},
            lambda value: value.model_copy(update={"manual_event_risk": True}),
        ),
        (
            {
                "type": "DISTANCE_FROM_LIMIT_DOWN_GTE",
                "minimum_ratio": Decimal("0.01"),
            },
            lambda value: _replace_latest_bar(
                value,
                open_fen=6059,
                high_fen=6070,
                low_fen=6030,
                close_fen=6059,
            ),
        ),
        (
            {"type": "LOWER_BAND_HITS_LTE", "max_hits": 3, "window_bars": 4},
            lambda value: _replace_last_closes(value, (6300, 6300, 6300, 6300)),
        ),
    ],
    ids=lambda value: value.get("type", "context") if isinstance(value, dict) else None,
)
def test_every_leaf_condition_has_an_exact_unsatisfied_boundary(
    condition_payload: ConditionPayload,
    transform: ContextTransform,
) -> None:
    evidence = evaluate_condition(_condition(condition_payload), transform(_context()))

    assert evidence.outcome is ConditionOutcome.UNSATISFIED
    assert evidence.facts
    assert evidence.missing_inputs == ()


@pytest.mark.parametrize(
    ("condition_payload", "transform", "expected_outcome", "missing_code"),
    [
        (
            {"type": "PRICE_IN_ZONE", "zone": "LOW_BUY"},
            _without_current_minutes,
            ConditionOutcome.MISSING_INPUT,
            MissingInputCode.COMPLETE_MINUTE_BAR,
        ),
        (
            {"type": "NO_NEW_LOW_FOR_BARS", "bars": 2},
            lambda value: value.model_copy(update={"low_zone_episode": None}),
            ConditionOutcome.UNSATISFIED,
            None,
        ),
        (
            {"type": "NON_DECREASING_CLOSE"},
            lambda value: _with_complete_bars(value, value.complete_5m_bars[-1:]),
            ConditionOutcome.MISSING_INPUT,
            MissingInputCode.PREVIOUS_5M_BAR,
        ),
        (
            {"type": "VOLUME_TO_PREVIOUS_LTE", "max_ratio": Decimal("1.00")},
            lambda value: _with_complete_bars(value, value.complete_5m_bars[-1:]),
            ConditionOutcome.MISSING_INPUT,
            MissingInputCode.PREVIOUS_5M_BAR,
        ),
        (
            {
                "type": "VOLUME_TO_MEDIAN_LTE",
                "max_ratio": Decimal("1.50"),
                "window_bars": 20,
            },
            lambda value: _with_complete_bars(value, value.complete_5m_bars[-20:]),
            ConditionOutcome.MISSING_INPUT,
            MissingInputCode.ROLLING_VOLUME_WINDOW,
        ),
        (
            {
                "type": "VOLUME_TO_MEDIAN_GTE",
                "minimum_ratio": Decimal("1.50"),
                "window_bars": 20,
            },
            lambda value: _with_complete_bars(value, value.complete_5m_bars[-20:]),
            ConditionOutcome.MISSING_INPUT,
            MissingInputCode.ROLLING_VOLUME_WINDOW,
        ),
        (
            {
                "type": "MACD_HIST_IMPROVEMENT_GTE",
                "minimum_improvement": Decimal("0.02"),
            },
            lambda value: value.model_copy(update={"daily_indicator_snapshot": None}),
            ConditionOutcome.MISSING_INPUT,
            MissingInputCode.DAILY_INDICATORS,
        ),
        (
            {"type": "PRICE_RECLAIMS_INDICATOR", "indicator": "EMA10"},
            lambda value: value.model_copy(update={"daily_indicator_snapshot": None}),
            ConditionOutcome.MISSING_INPUT,
            MissingInputCode.DAILY_INDICATORS,
        ),
        (
            {"type": "UPPER_WICK_RATIO_GTE", "minimum_ratio": Decimal("0.40")},
            lambda value: _with_complete_bars(value, ()),
            ConditionOutcome.MISSING_INPUT,
            MissingInputCode.COMPLETE_5M_BAR,
        ),
        (
            {"type": "RETREAT_FROM_SESSION_HIGH_GTE", "minimum_ratio": Decimal("0.01")},
            lambda value: _with_complete_bars(value, ()),
            ConditionOutcome.MISSING_INPUT,
            MissingInputCode.SESSION_BARS,
        ),
        (
            {"type": "CLOSE_IN_BAR_LOWER_HALF"},
            lambda value: _with_complete_bars(value, ()),
            ConditionOutcome.MISSING_INPUT,
            MissingInputCode.COMPLETE_5M_BAR,
        ),
        (
            {
                "type": "CONSECUTIVE_CLOSES_BELOW_LEVEL",
                "level": "PRESSURE_REFERENCE",
                "bars": 2,
            },
            lambda value: _with_complete_bars(value, value.complete_5m_bars[-1:]),
            ConditionOutcome.MISSING_INPUT,
            MissingInputCode.COMPLETE_5M_BAR_WINDOW,
        ),
        (
            {"type": "OFFICIAL_CLOSE_BELOW_LEVEL", "level": "RISK_LINE"},
            lambda value: value,
            ConditionOutcome.MISSING_INPUT,
            MissingInputCode.OFFICIAL_DAILY_CLOSE,
        ),
        (
            {"type": "NEXT_TRADING_DAY_RECOVERY", "level": "RISK_LINE"},
            lambda value: _with_breached_risk(_with_official_close(value, 6080)).model_copy(
                update={"trading_calendar": ()}
            ),
            ConditionOutcome.MISSING_INPUT,
            MissingInputCode.TRADING_CALENDAR,
        ),
        (
            {"type": "POSITION_BUCKET_AVAILABLE", "bucket": "CORE"},
            lambda value: value,
            ConditionOutcome.SATISFIED,
            None,
        ),
        (
            {"type": "SELLABLE_QUANTITY_GTE", "bucket": "TACTICAL", "quantity": 100},
            lambda value: value,
            ConditionOutcome.UNSATISFIED,
            None,
        ),
        (
            {"type": "MANUAL_EVENT_RISK_CLEAR"},
            lambda value: value.model_copy(update={"manual_event_risk": None}),
            ConditionOutcome.MISSING_INPUT,
            MissingInputCode.MANUAL_EVENT_RISK,
        ),
        (
            {"type": "DISTANCE_FROM_LIMIT_DOWN_GTE", "minimum_ratio": Decimal("0.01")},
            lambda value: value.model_copy(update={"daily_limit": None}),
            ConditionOutcome.MISSING_INPUT,
            MissingInputCode.DAILY_LIMIT,
        ),
        (
            {"type": "LOWER_BAND_HITS_LTE", "max_hits": 3, "window_bars": 4},
            lambda value: value.model_copy(update={"five_minute_indicators": None}),
            ConditionOutcome.MISSING_INPUT,
            MissingInputCode.FIVE_MINUTE_INDICATORS,
        ),
    ],
    ids=lambda value: value.get("type", "context") if isinstance(value, dict) else None,
)
def test_every_leaf_condition_fails_closed_without_required_input(
    condition_payload: ConditionPayload,
    transform: ContextTransform,
    expected_outcome: ConditionOutcome,
    missing_code: MissingInputCode | None,
) -> None:
    evidence = evaluate_condition(_condition(condition_payload), transform(_context()))

    assert evidence.outcome is expected_outcome
    if missing_code is None:
        assert evidence.missing_inputs == ()
    else:
        assert missing_code in evidence.missing_inputs


def test_volume_median_uses_exact_prior_window_and_even_decimal_median() -> None:
    volumes = tuple(range(91, 111)) + (Decimal("150.75"),)
    context = _context()
    bars = tuple(
        _bar(
            context.complete_5m_bars[index].bar_end,
            volume_shares=int(volume),
        )
        for index, volume in enumerate(volumes)
    )
    context = _with_complete_bars(context, bars)
    condition = _condition(
        {
            "type": "VOLUME_TO_MEDIAN_LTE",
            "max_ratio": Decimal("1.50"),
            "window_bars": 20,
        }
    )

    evidence = evaluate_condition(condition, context)

    assert _facts(evidence)["median_volume_shares"] == Decimal("100.5")
    assert _facts(evidence)["threshold_volume_shares"] == Decimal("150.75")
    assert evidence.outcome is ConditionOutcome.SATISFIED


def test_volume_median_keeps_large_even_window_exact_under_hostile_decimal_context() -> None:
    large_volume = 10**60
    context = _context()
    replacement_volumes = (large_volume, large_volume + 1, large_volume)
    bars = (
        *context.complete_5m_bars[:-3],
        *(
            bar.model_copy(
                update={
                    "volume_shares": volume,
                    "amount_yuan": Decimal(volume),
                }
            )
            for bar, volume in zip(
                context.complete_5m_bars[-3:],
                replacement_volumes,
                strict=True,
            )
        ),
    )
    context = _with_complete_bars(context, bars)
    condition = _condition(
        {
            "type": "VOLUME_TO_MEDIAN_GTE",
            "minimum_ratio": Decimal("1"),
            "window_bars": 2,
        }
    )

    with localcontext() as decimal_context:
        decimal_context.prec = 6
        low_precision = evaluate_condition(condition, context)
    with localcontext() as decimal_context:
        decimal_context.prec = 80
        high_precision = evaluate_condition(condition, context)

    expected_median = Decimal(f"{large_volume}.5")
    assert low_precision == high_precision
    assert low_precision.outcome is ConditionOutcome.UNSATISFIED
    assert _facts(low_precision)["median_volume_shares"] == expected_median
    assert _facts(low_precision)["threshold_volume_shares"] == expected_median


def test_zero_volume_bases_use_cross_multiplication_without_division() -> None:
    context = _context()
    zero_bars = _bars((0,) * 21)
    context = _with_complete_bars(context, zero_bars)

    previous = evaluate_condition(
        _condition({"type": "VOLUME_TO_PREVIOUS_LTE", "max_ratio": Decimal("1")}),
        context,
    )
    median = evaluate_condition(
        _condition(
            {
                "type": "VOLUME_TO_MEDIAN_LTE",
                "max_ratio": Decimal("1"),
                "window_bars": 20,
            }
        ),
        context,
    )

    assert previous.outcome is ConditionOutcome.SATISFIED
    assert median.outcome is ConditionOutcome.SATISFIED
    assert "observed_ratio" not in _facts(previous)
    assert "observed_ratio" not in _facts(median)


def test_indicator_selection_never_falls_back_to_another_field() -> None:
    context = _context().model_copy(
        update={
            "daily_indicator_snapshot": _context().daily_indicator_snapshot.model_copy(
                update={
                    "series": _daily_indicators().model_copy(
                        update={
                            "points": (
                                _point(
                                    PREVIOUS_TRADE_DATE,
                                    macd_histogram_yuan=-0.10,
                                ),
                                _point(
                                    TRADE_DATE,
                                    macd_histogram_yuan=-0.08,
                                    boll_lower_yuan=63.5,
                                ).model_copy(update={"ma200_yuan": None}),
                            )
                        }
                    )
                }
            )
        }
    )

    evidence = evaluate_condition(
        _condition({"type": "PRICE_RECLAIMS_INDICATOR", "indicator": "MA200"}),
        context,
    )

    assert evidence.outcome is ConditionOutcome.MISSING_INPUT
    assert evidence.missing_inputs == (MissingInputCode.INDICATOR_VALUE,)


@pytest.mark.parametrize(
    ("transform", "expected_provenance", "expected_cutoff"),
    [
        (
            lambda value: value,
            DailyIndicatorProvenance.PROVISIONAL,
            datetime(2026, 8, 7, 11, 15, tzinfo=SHANGHAI),
        ),
        (
            lambda value: _with_official_close(value, 6400),
            DailyIndicatorProvenance.OFFICIAL,
            datetime(2026, 8, 7, 15, 0, tzinfo=SHANGHAI),
        ),
    ],
)
def test_daily_indicator_evidence_records_selected_provenance_and_cutoff(
    transform: ContextTransform,
    expected_provenance: DailyIndicatorProvenance,
    expected_cutoff: datetime,
) -> None:
    context = transform(_context())

    evidence = evaluate_condition(
        _condition(
            {
                "type": "MACD_HIST_IMPROVEMENT_GTE",
                "minimum_improvement": Decimal("0.02"),
            }
        ),
        context,
    )

    facts = _facts(evidence)
    assert facts["indicator_provenance"] == expected_provenance.value
    assert facts["indicator_source_as_of"] == expected_cutoff


def test_logical_conditions_preserve_all_ordered_child_evidence_without_short_circuit() -> None:
    context = _context().model_copy(update={"manual_event_risk": True})
    condition = _condition(
        {
            "type": "ALL",
            "conditions": [
                {"type": "MANUAL_EVENT_RISK_CLEAR"},
                {"type": "OFFICIAL_CLOSE_BELOW_LEVEL", "level": "RISK_LINE"},
            ],
        }
    )

    evidence = evaluate_condition(condition, context)

    assert evidence.outcome is ConditionOutcome.UNSATISFIED
    assert tuple(child.condition.type for child in evidence.children) == (
        "MANUAL_EVENT_RISK_CLEAR",
        "OFFICIAL_CLOSE_BELOW_LEVEL",
    )
    assert tuple(child.outcome for child in evidence.children) == (
        ConditionOutcome.UNSATISFIED,
        ConditionOutcome.MISSING_INPUT,
    )


def test_any_condition_prefers_satisfied_then_missing_then_unsatisfied() -> None:
    context = _context()
    satisfied_with_missing = _condition(
        {
            "type": "ANY",
            "conditions": [
                {"type": "PRICE_IN_ZONE", "zone": "LOW_BUY"},
                {"type": "OFFICIAL_CLOSE_BELOW_LEVEL", "level": "RISK_LINE"},
            ],
        }
    )
    missing_with_unsatisfied = _condition(
        {
            "type": "ANY",
            "conditions": [
                {"type": "NO_NEW_LOW_FOR_BARS", "bars": 3},
                {"type": "OFFICIAL_CLOSE_BELOW_LEVEL", "level": "RISK_LINE"},
            ],
        }
    )

    first = evaluate_condition(satisfied_with_missing, context)
    second = evaluate_condition(missing_with_unsatisfied, context)

    assert first.outcome is ConditionOutcome.SATISFIED
    assert len(first.children) == 2
    assert second.outcome is ConditionOutcome.MISSING_INPUT
    assert len(second.children) == 2


def test_evidence_models_snapshot_intents_signal_and_next_step_form_one_closed_result() -> None:
    context = _context()
    evidence = evaluate_condition(
        _condition({"type": "PRICE_IN_ZONE", "zone": "LOW_BUY"}),
        context,
    )
    next_step = NextStep(code=NextStepCode.RECORD_CONFIRMED_FILL)
    position = PositionSummary(
        core_quantity=0,
        tactical_quantity=0,
        total_quantity=0,
        sellable_core_quantity=0,
        sellable_tactical_quantity=0,
    )
    episode = _episode(context.plan_hash)
    snapshot = SymbolDecisionSnapshot(
        symbol=SYMBOL,
        plan_id=context.plan.plan_id,
        plan_version=context.plan.version,
        plan_hash=context.plan_hash,
        evaluated_at=context.evaluated_at,
        market_data_at=context.complete_5m_bars[-1].bar_end,
        price_fen=context.complete_5m_bars[-1].close_fen,
        zone=DecisionZone.LOW_BUY,
        signal_type=SignalType.BUY_CORE_READY,
        position=position,
        episode=episode,
        risk=context.risk_state,
        data_health=context.data_health,
        condition_evidence=(evidence,),
        next_step=next_step,
    )
    transition = EpisodeTransitionIntent(
        action=EpisodeTransitionAction.UPSERT,
        episode=episode,
    )
    signal = SignalIntent(
        signal_type=ActionableSignalType.BUY_CORE_READY,
        plan_hash=context.plan_hash,
        symbol=SYMBOL,
        trading_date=TRADE_DATE,
        cause_id=episode.episode_id,
        quantity=100,
        bucket="CORE",
        target_lot_id=None,
        matched_conditions=(evidence,),
        blockers=(),
        next_step=next_step,
    )
    identity = IntradayEvaluationIdentity(
        plan_hash=context.plan_hash,
        symbol=SYMBOL,
        bucket_end=context.complete_5m_bars[-1].bar_end,
        formula_version="ta-v1",
    )

    result = EvaluationResult.build(
        snapshot=snapshot,
        transitions=(transition,),
        signal_intent=signal,
        satisfied_conditions=(evidence,),
        unmet_conditions=(),
        blockers=(),
        next_step=next_step,
        evaluation_identity=identity,
    )

    assert result.snapshot == snapshot
    assert result.transitions == (transition,)
    assert result.signal_intent == signal
    assert result.next_step.code is NextStepCode.RECORD_CONFIRMED_FILL
    with pytest.raises(ValidationError, match="result_hash"):
        result.model_copy(update={"result_hash": "not-a-hash"})
    with pytest.raises(ValidationError, match="result_hash"):
        result.model_copy(update={"result_hash": "0" * 64})


def test_evaluation_result_build_hashes_the_validated_payload_once(monkeypatch) -> None:
    context = _context()
    original = decision_models_module._evaluation_result_digest
    digest_count = 0

    def observed_digest(payload):
        nonlocal digest_count
        digest_count += 1
        return original(payload)

    monkeypatch.setattr(
        decision_models_module,
        "_evaluation_result_digest",
        observed_digest,
    )

    result = evaluate(context)

    assert digest_count == 1
    restored = EvaluationResult.model_validate_json(result.model_dump_json())
    assert restored == result
    assert digest_count == 2


def test_rule_evidence_is_closed_bounded_and_partitions_with_dsl_evidence() -> None:
    context = _context()
    blocked_context = _with_complete_bars(context, ())
    condition = evaluate_condition(
        _condition({"type": "PRICE_IN_ZONE", "zone": "LOW_BUY"}),
        context,
    )
    pressure_touch = RuleEvidence(
        code=RuleEvidenceCode.PRESSURE_TOUCH,
        outcome=ConditionOutcome.SATISFIED,
        facts=(
            EvidenceFact(
                key="pressure_ratio",
                value=Decimal("1.500"),
                unit=EvidenceUnit.RATIO,
            ),
        ),
    )
    data_blocker = RuleEvidence(
        code=RuleEvidenceCode.DATA_NOT_READY,
        outcome=ConditionOutcome.MISSING_INPUT,
        facts=(),
        missing_inputs=(MissingInputCode.COMPLETE_MINUTE_BAR,),
    )
    next_step = NextStep(
        code=NextStepCode.WAIT_FOR_REQUIRED_DATA,
        required_inputs=(MissingInputCode.COMPLETE_MINUTE_BAR,),
    )
    snapshot = SymbolDecisionSnapshot(
        symbol=SYMBOL,
        plan_id=context.plan.plan_id,
        plan_version=context.plan.version,
        plan_hash=context.plan_hash,
        evaluated_at=context.evaluated_at,
        market_data_at=None,
        price_fen=None,
        zone=DecisionZone.UNKNOWN,
        signal_type=SignalType.BLOCKED_DATA,
        position=PositionSummary(
            core_quantity=0,
            tactical_quantity=0,
            total_quantity=0,
            sellable_core_quantity=0,
            sellable_tactical_quantity=0,
        ),
        episode=context.low_zone_episode,
        risk=context.risk_state,
        data_health=blocked_context.data_health,
        condition_evidence=(pressure_touch, condition, data_blocker),
        next_step=next_step,
    )
    result = EvaluationResult.build(
        snapshot=snapshot,
        transitions=(),
        signal_intent=None,
        satisfied_conditions=(pressure_touch, condition),
        unmet_conditions=(),
        blockers=(data_blocker,),
        next_step=next_step,
        evaluation_identity=IntradayEvaluationIdentity(
            plan_hash=context.plan_hash,
            symbol=SYMBOL,
            bucket_end=context.target.bucket_end,
        ),
    )

    assert result.snapshot.condition_evidence == (
        pressure_touch,
        condition,
        data_blocker,
    )
    assert result.blockers == (data_blocker,)
    with pytest.raises(ValidationError):
        RuleEvidence.model_validate(
            {
                **pressure_touch.model_dump(mode="python"),
                "unexpected": True,
            }
        )
    with pytest.raises(ValidationError, match="missing"):
        data_blocker.model_copy(update={"missing_inputs": ()})
    with pytest.raises(ValidationError, match="structural|blocker|satisfied"):
        data_blocker.model_copy(
            update={
                "outcome": ConditionOutcome.SATISFIED,
                "missing_inputs": (),
            }
        )


def test_intraday_result_identity_is_a_target_not_fabricated_market_evidence() -> None:
    context = _context()
    identity = IntradayEvaluationIdentity(
        plan_hash=context.plan_hash,
        symbol=SYMBOL,
        bucket_end=context.target.bucket_end,
    )

    def build(
        source: EvaluationContext,
        market_data_at: datetime | None,
        price_fen: int | None,
    ) -> EvaluationResult:
        snapshot = _neutral_snapshot(
            source,
            evaluated_at=source.evaluated_at,
            market_data_at=market_data_at,
            price_fen=price_fen,
        )
        return EvaluationResult.build(
            snapshot=snapshot,
            transitions=(),
            signal_intent=None,
            satisfied_conditions=(),
            unmet_conditions=(),
            blockers=(),
            next_step=snapshot.next_step,
            evaluation_identity=identity,
        )

    blocked = _with_complete_bars(context, ())
    assert build(blocked, None, None).snapshot.market_data_at is None
    earlier_context = _with_complete_bars(context, context.complete_5m_bars[:-1])
    earlier = earlier_context.current_day_minutes[-1]
    assert (
        build(earlier_context, earlier.bar_end, earlier.close_fen).snapshot.market_data_at
        == earlier.bar_end
    )
    degraded_but_complete = context.model_copy(
        update={
            "data_health": context.data_health.model_copy(
                update={"status": DataHealthStatus.DEGRADED}
            )
        }
    )
    with pytest.raises(ValidationError, match="complete|fresh|target"):
        build(degraded_but_complete, None, None)
    with pytest.raises(ValidationError, match="intraday.*market|market.*target"):
        build(context, context.target.bucket_end + timedelta(minutes=1), 6400)


def test_result_build_hashes_the_normalized_payload_with_omitted_defaults() -> None:
    context = _context()
    snapshot = _neutral_snapshot(
        context,
        evaluated_at=context.evaluated_at,
        market_data_at=context.target.bucket_end,
        price_fen=context.current_day_minutes[-1].close_fen,
    )

    result = EvaluationResult.build(
        snapshot=snapshot,
        signal_intent=None,
        next_step=snapshot.next_step,
        evaluation_identity=IntradayEvaluationIdentity(
            plan_hash=context.plan_hash,
            symbol=SYMBOL,
            bucket_end=context.target.bucket_end,
        ),
    )

    assert result.transitions == ()
    assert result.satisfied_conditions == ()
    assert result.unmet_conditions == ()
    assert result.blockers == ()


def _result_with_satisfied_rule_evidence(
    evidence: tuple[RuleEvidence, ...],
) -> EvaluationResult:
    context = _context()
    snapshot = _neutral_snapshot(
        context,
        evaluated_at=context.evaluated_at,
        market_data_at=context.target.bucket_end,
        price_fen=context.current_day_minutes[-1].close_fen,
    ).model_copy(update={"condition_evidence": evidence})
    return EvaluationResult.build(
        snapshot=snapshot,
        signal_intent=None,
        satisfied_conditions=evidence,
        next_step=snapshot.next_step,
        evaluation_identity=IntradayEvaluationIdentity(
            plan_hash=context.plan_hash,
            symbol=SYMBOL,
            bucket_end=context.target.bucket_end,
        ),
    )


def _decimal_rule_evidence(value: Decimal) -> RuleEvidence:
    return RuleEvidence(
        code=RuleEvidenceCode.PRESSURE_TOUCH,
        outcome=ConditionOutcome.SATISFIED,
        facts=(
            EvidenceFact(
                key="canonical_decimal",
                value=value,
                unit=EvidenceUnit.RATIO,
            ),
        ),
    )


def test_rule_evidence_enforces_approved_fact_and_missing_input_bounds() -> None:
    facts = tuple(
        EvidenceFact(key=f"fact_{index}", value=index, unit=EvidenceUnit.COUNT)
        for index in range(16)
    )
    bounded_facts = RuleEvidence(
        code=RuleEvidenceCode.PRESSURE_TOUCH,
        outcome=ConditionOutcome.SATISFIED,
        facts=facts,
    )
    assert len(bounded_facts.facts) == 16
    with pytest.raises(ValidationError, match="16|length"):
        bounded_facts.model_copy(
            update={
                "facts": facts
                + (
                    EvidenceFact(
                        key="fact_16",
                        value=16,
                        unit=EvidenceUnit.COUNT,
                    ),
                )
            }
        )

    missing_inputs = tuple(MissingInputCode)[:4]
    bounded_missing = RuleEvidence(
        code=RuleEvidenceCode.DATA_NOT_READY,
        outcome=ConditionOutcome.MISSING_INPUT,
        missing_inputs=missing_inputs,
    )
    assert len(bounded_missing.missing_inputs) == 4
    with pytest.raises(ValidationError, match="4|length"):
        bounded_missing.model_copy(update={"missing_inputs": tuple(MissingInputCode)[:5]})


def test_every_structural_rule_evidence_code_rejects_satisfied_outcome() -> None:
    structural_codes = (
        RuleEvidenceCode.PLAN_INACTIVE,
        RuleEvidenceCode.DATA_NOT_READY,
        RuleEvidenceCode.DAILY_LIMIT_UNKNOWN,
        RuleEvidenceCode.EPISODE_HISTORY_GAP,
        RuleEvidenceCode.BEARISH_VOLUME_EXPANSION,
        RuleEvidenceCode.RISK_PENDING,
    )

    for code in structural_codes:
        with pytest.raises(ValidationError, match="structural|blocker|satisfied"):
            RuleEvidence(code=code, outcome=ConditionOutcome.SATISFIED)


def test_evaluation_evidence_union_survives_strict_json_round_trip() -> None:
    result = _result_with_satisfied_rule_evidence((_decimal_rule_evidence(Decimal("1.5")),))

    restored = EvaluationResult.model_validate_json(result.model_dump_json())

    assert restored == result
    assert isinstance(restored.snapshot.condition_evidence[0], RuleEvidence)
    assert isinstance(restored.satisfied_conditions[0], RuleEvidence)


def test_result_hash_canonicalizes_decimal_scale_sign_and_ambient_context() -> None:
    scaled = _result_with_satisfied_rule_evidence((_decimal_rule_evidence(Decimal("1.500")),))
    unscaled = _result_with_satisfied_rule_evidence((_decimal_rule_evidence(Decimal("1.5")),))
    extreme_scale = _result_with_satisfied_rule_evidence(
        (_decimal_rule_evidence(Decimal("1." + "0" * 10_000)),)
    )
    integer_one = _result_with_satisfied_rule_evidence((_decimal_rule_evidence(Decimal("1")),))
    negative_zero = _result_with_satisfied_rule_evidence(
        (_decimal_rule_evidence(Decimal("-0.000")),)
    )
    positive_zero = _result_with_satisfied_rule_evidence((_decimal_rule_evidence(Decimal("0")),))

    with localcontext() as decimal_context:
        decimal_context.prec = 2
        low_precision = _result_with_satisfied_rule_evidence(
            (_decimal_rule_evidence(Decimal("123456789.0123456789")),)
        )
    with localcontext() as decimal_context:
        decimal_context.prec = 50
        high_precision = _result_with_satisfied_rule_evidence(
            (_decimal_rule_evidence(Decimal("123456789.0123456789")),)
        )
    maximum_coefficient = _result_with_satisfied_rule_evidence(
        (_decimal_rule_evidence(Decimal("1" * 10_000)),)
    )
    maximum_coefficient_replay = _result_with_satisfied_rule_evidence(
        (_decimal_rule_evidence(Decimal("1" * 10_000)),)
    )

    assert scaled.result_hash == unscaled.result_hash
    assert extreme_scale.result_hash == integer_one.result_hash
    assert negative_zero.result_hash == positive_zero.result_hash
    assert low_precision.result_hash == high_precision.result_hash
    assert maximum_coefficient.result_hash == maximum_coefficient_replay.result_hash
    with pytest.raises(ValueError, match="coefficient.*large"):
        _result_with_satisfied_rule_evidence((_decimal_rule_evidence(Decimal("1" * 10_001)),))


def test_result_hash_sorts_object_keys_but_preserves_evidence_array_order() -> None:
    first = _decimal_rule_evidence(Decimal("1.5"))
    second = RuleEvidence(
        code=RuleEvidenceCode.RISK_RECOVERY,
        outcome=ConditionOutcome.SATISFIED,
        facts=(EvidenceFact(key="recovered", value=True, unit=EvidenceUnit.BOOLEAN),),
    )
    ordered = _result_with_satisfied_rule_evidence((first, second))
    reordered = _result_with_satisfied_rule_evidence((second, first))

    payload = ordered.model_dump(
        mode="python",
        round_trip=True,
        exclude={"result_hash"},
    )
    reverse_key_payload = dict(reversed(tuple(payload.items())))
    rebuilt = EvaluationResult.build(**reverse_key_payload)

    assert rebuilt.result_hash == ordered.result_hash
    assert reordered.result_hash != ordered.result_hash


def test_symbol_snapshot_requires_price_and_market_time_to_appear_together() -> None:
    context = _context()
    market_data_at = context.target.bucket_end

    with pytest.raises(ValidationError, match="price.*market|market.*price"):
        _neutral_snapshot(
            context,
            evaluated_at=context.evaluated_at,
            market_data_at=market_data_at,
            price_fen=None,
        )
    with pytest.raises(ValidationError, match="price.*market|market.*price"):
        _neutral_snapshot(
            context,
            evaluated_at=context.evaluated_at,
            market_data_at=None,
            price_fen=6400,
        )

    assert (
        _neutral_snapshot(
            context,
            evaluated_at=context.evaluated_at,
            market_data_at=None,
            price_fen=None,
        ).price_fen
        is None
    )
    assert (
        _neutral_snapshot(
            context,
            evaluated_at=context.evaluated_at,
            market_data_at=market_data_at,
            price_fen=6400,
        ).market_data_at
        == market_data_at
    )


def test_official_result_uses_only_the_canonical_1500_market_cutoff() -> None:
    context = _with_official_close(_context(), 6079)
    identity = OfficialCloseEvaluationIdentity(
        plan_hash=context.plan_hash,
        symbol=SYMBOL,
        official_trade_date=TRADE_DATE,
    )

    def result_for(market_data_at: datetime) -> EvaluationResult:
        snapshot = _neutral_snapshot(
            context,
            evaluated_at=context.evaluated_at,
            market_data_at=market_data_at,
            price_fen=6079,
        )
        return EvaluationResult.build(
            snapshot=snapshot,
            transitions=(),
            signal_intent=None,
            satisfied_conditions=(),
            unmet_conditions=(),
            blockers=(),
            next_step=snapshot.next_step,
            evaluation_identity=identity,
        )

    with pytest.raises(ValidationError, match="15:00|official.*cutoff"):
        result_for(datetime(2026, 8, 7, 14, 55, tzinfo=SHANGHAI))
    with pytest.raises(ValidationError, match="15:00|official.*cutoff"):
        result_for(datetime(2026, 8, 7, 15, 1, tzinfo=SHANGHAI))
    assert result_for(datetime(2026, 8, 7, 15, 0, tzinfo=SHANGHAI)).evaluation_identity == (
        identity
    )


def test_result_state_cannot_postdate_its_evaluation_identity() -> None:
    context = _with_official_close(_context(), 6079)
    delayed_at = datetime(2026, 8, 8, 9, 0, tzinfo=SHANGHAI)
    identity = OfficialCloseEvaluationIdentity(
        plan_hash=context.plan_hash,
        symbol=SYMBOL,
        official_trade_date=TRADE_DATE,
    )

    def build_result(
        snapshot: SymbolDecisionSnapshot,
        transitions: tuple[EpisodeTransitionIntent | RiskTransitionIntent, ...],
    ) -> EvaluationResult:
        return EvaluationResult.build(
            snapshot=snapshot,
            transitions=transitions,
            signal_intent=None,
            satisfied_conditions=(),
            unmet_conditions=(),
            blockers=(),
            next_step=snapshot.next_step,
            evaluation_identity=identity,
        )

    future_risk = RiskStateSnapshot(
        symbol=SYMBOL,
        plan_hash=context.plan_hash,
        status=RiskStatus.BREACHED_PENDING_CONFIRMATION,
        breach_trade_date=delayed_at.date(),
        prior_close_fen=6400,
        revision=1,
        updated_at=delayed_at,
    )
    future_risk_snapshot = _neutral_snapshot(
        context,
        evaluated_at=delayed_at,
        market_data_at=datetime(2026, 8, 7, 15, 0, tzinfo=SHANGHAI),
        price_fen=6079,
        risk=future_risk,
    )
    with pytest.raises(ValidationError, match="risk.*identity|identity.*risk"):
        build_result(
            future_risk_snapshot,
            (RiskTransitionIntent(risk=future_risk, expected_revision=0),),
        )

    future_episode_at = datetime(2026, 8, 8, 9, 31, tzinfo=SHANGHAI)
    future_episode_cursor = datetime(2026, 8, 8, 9, 35, tzinfo=SHANGHAI)
    future_episode = _episode(context.plan_hash).model_copy(
        update={
            "started_at": future_episode_at,
            "last_processed_bucket_end": future_episode_cursor,
        }
    )
    future_episode_snapshot = _neutral_snapshot(
        context,
        evaluated_at=future_episode_cursor + timedelta(minutes=1),
        market_data_at=datetime(2026, 8, 7, 15, 0, tzinfo=SHANGHAI),
        price_fen=6079,
        episode=future_episode,
    )
    with pytest.raises(ValidationError, match="episode.*identity|identity.*episode"):
        build_result(
            future_episode_snapshot,
            (
                EpisodeTransitionIntent(
                    action=EpisodeTransitionAction.UPSERT,
                    episode=future_episode,
                ),
            ),
        )

    valid_episode = _episode(context.plan_hash)
    valid_snapshot = _neutral_snapshot(
        context,
        evaluated_at=delayed_at,
        market_data_at=datetime(2026, 8, 7, 15, 0, tzinfo=SHANGHAI),
        price_fen=6079,
        episode=valid_episode,
    )
    assert (
        build_result(
            valid_snapshot,
            (
                EpisodeTransitionIntent(
                    action=EpisodeTransitionAction.UPSERT,
                    episode=valid_episode,
                ),
            ),
        ).snapshot.evaluated_at
        == delayed_at
    )


def test_signal_intent_rejects_non_actionable_signal_types() -> None:
    context = _context()

    with pytest.raises(ValidationError):
        SignalIntent(
            signal_type=SignalType.WAIT,
            plan_hash=context.plan_hash,
            symbol=SYMBOL,
            trading_date=TRADE_DATE,
            cause_id="wait-is-not-an-alert",
            quantity=None,
            bucket=None,
            target_lot_id=None,
            matched_conditions=(),
            blockers=(),
            next_step=NextStep(code=NextStepCode.WAIT_FOR_COMPLETE_BAR),
        )


def test_decision_modules_have_no_io_database_network_global_clock_or_random_access() -> None:
    forbidden_import_roots = {
        "aiosqlite",
        "httpx",
        "logging",
        "os",
        "pathlib",
        "random",
        "requests",
        "socket",
        "sqlalchemy",
        "subprocess",
        "time",
        "tushare",
    }
    forbidden_calls = {"date.today", "datetime.now", "datetime.utcnow", "open"}

    for module in (
        condition_module,
        decision_models_module,
        engine_module,
        episode_module,
        risk_module,
    ):
        tree = ast.parse(inspect.getsource(module))
        imported_roots = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            (node.module or "").split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        call_names = {
            ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)
        }

        assert imported_roots.isdisjoint(forbidden_import_roots)
        assert call_names.isdisjoint(forbidden_calls)


def test_evidence_fact_units_are_closed_and_numeric_values_remain_decimal() -> None:
    evidence = evaluate_condition(
        _condition(
            {
                "type": "VOLUME_TO_MEDIAN_LTE",
                "max_ratio": Decimal("1.50"),
                "window_bars": 20,
            }
        ),
        _context(),
    )
    facts = {fact.key: fact for fact in evidence.facts}

    assert facts["median_volume_shares"].unit is EvidenceUnit.SHARES
    assert facts["threshold_volume_shares"].value == Decimal("150.0")
    assert isinstance(facts["threshold_volume_shares"].value, Decimal)


def test_decimal_precision_cannot_change_condition_outcome_or_evidence() -> None:
    context = _replace_latest_bar(
        _context(),
        open_fen=6402,
        high_fen=6403,
        low_fen=6400,
        close_fen=6402,
    )
    condition = _condition(
        {
            "type": "UPPER_WICK_RATIO_GTE",
            "minimum_ratio": Decimal("0.33333333333"),
        }
    )

    with localcontext() as decimal_context:
        decimal_context.prec = 10
        low_precision = evaluate_condition(condition, context)
    with localcontext() as decimal_context:
        decimal_context.prec = 50
        high_precision = evaluate_condition(condition, context)

    assert low_precision == high_precision
    assert low_precision.outcome is ConditionOutcome.SATISFIED


def test_large_fen_to_yuan_lower_band_boundary_is_exact_under_hostile_decimal_context() -> None:
    lower_band_yuan = 1e58
    price_fen = 10**60 + 1
    context = _with_latest_price(_context(), price_fen)
    indicator_series = context.five_minute_indicators
    assert indicator_series is not None
    context = context.model_copy(
        update={
            "five_minute_indicators": indicator_series.model_copy(
                update={
                    "points": (
                        *indicator_series.points[:-1],
                        indicator_series.points[-1].model_copy(
                            update={"boll_lower_yuan": lower_band_yuan}
                        ),
                    )
                }
            )
        }
    )
    condition = _condition({"type": "LOWER_BAND_HITS_LTE", "max_hits": 0, "window_bars": 1})

    with localcontext() as decimal_context:
        decimal_context.prec = 6
        low_precision = evaluate_condition(condition, context)
    with localcontext() as decimal_context:
        decimal_context.prec = 80
        high_precision = evaluate_condition(condition, context)

    assert low_precision == high_precision
    assert low_precision.outcome is ConditionOutcome.SATISFIED
    assert _facts(low_precision)["lower_band_hit_count"] == 0
    assert _facts(low_precision)["close_minus_lower_1_yuan"] == Decimal("0.01")


def test_large_fen_to_yuan_reclaim_crossing_is_exact_under_hostile_decimal_context() -> None:
    indicator_yuan = 1e58
    below_fen = 10**60 - 1
    above_fen = 10**60 + 1
    context = _replace_target_minute_closes(
        _context(),
        (below_fen, below_fen, above_fen, above_fen, above_fen),
    )
    indicator_snapshot = context.daily_indicator_snapshot
    assert indicator_snapshot is not None
    points = indicator_snapshot.series.points
    context = context.model_copy(
        update={
            "daily_indicator_snapshot": indicator_snapshot.model_copy(
                update={
                    "series": indicator_snapshot.series.model_copy(
                        update={
                            "points": (
                                *points[:-1],
                                points[-1].model_copy(update={"ema10_yuan": indicator_yuan}),
                            )
                        }
                    )
                }
            )
        }
    )
    condition = _condition({"type": "PRICE_RECLAIMS_INDICATOR", "indicator": "EMA10"})

    with localcontext() as decimal_context:
        decimal_context.prec = 6
        low_precision = evaluate_condition(condition, context)
    with localcontext() as decimal_context:
        decimal_context.prec = 80
        high_precision = evaluate_condition(condition, context)

    assert low_precision == high_precision
    assert low_precision.outcome is ConditionOutcome.SATISFIED
    facts = _facts(low_precision)
    assert facts["previous_price_yuan"] == Decimal("9" * 58 + ".99")
    assert facts["price_yuan"] == Decimal("1" + "0" * 58 + ".01")
    assert facts["bucket_end_price_yuan"] == Decimal("1" + "0" * 58 + ".01")


def test_decimal_precision_cannot_change_repeating_volume_ratio_evidence() -> None:
    context = _with_complete_bars(_context(), _bars((100,) * 19 + (3, 1)))
    condition = _condition(
        {
            "type": "VOLUME_TO_PREVIOUS_LTE",
            "max_ratio": Decimal("0.33333333333333333333333333333333333333333333333333"),
        }
    )

    with localcontext() as decimal_context:
        decimal_context.prec = 6
        low_precision = evaluate_condition(condition, context)
    with localcontext() as decimal_context:
        decimal_context.prec = 50
        high_precision = evaluate_condition(condition, context)

    assert low_precision == high_precision
    facts = _facts(low_precision)
    assert low_precision.outcome is ConditionOutcome.UNSATISFIED
    assert facts["threshold_volume_shares"] == Decimal("0." + "9" * 50)
    assert facts["observed_ratio"] == Decimal("0." + "3" * 50)


def test_condition_ratio_comparison_never_expands_a_decimal_integer_ratio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NoRatioExpansionDecimal(Decimal):
        def as_integer_ratio(self) -> tuple[int, int]:
            raise AssertionError("condition comparison must not expand a Decimal ratio")

    monkeypatch.setattr(condition_module, "Decimal", NoRatioExpansionDecimal)
    tiny_ratio = Decimal("1E-999999999")
    previous_lte = _condition(
        {
            "type": "VOLUME_TO_PREVIOUS_LTE",
            "max_ratio": tiny_ratio,
        }
    )
    median_gte = _condition(
        {
            "type": "VOLUME_TO_MEDIAN_GTE",
            "minimum_ratio": tiny_ratio,
            "window_bars": 20,
        }
    )

    previous_evidence = evaluate_condition(previous_lte, _context())
    median_evidence = evaluate_condition(median_gte, _context())

    assert previous_evidence.outcome is ConditionOutcome.UNSATISFIED
    assert median_evidence.outcome is ConditionOutcome.SATISFIED
    assert _facts(previous_evidence)["threshold_volume_shares"] == Decimal("1.00E-999999997")


def test_decimal_precision_cannot_change_macd_improvement_evidence() -> None:
    context = _context()
    series = IndicatorSeries(
        symbol=SYMBOL,
        points=(
            _point(PREVIOUS_TRADE_DATE, macd_histogram_yuan=-0.123456789),
            _point(TRADE_DATE, macd_histogram_yuan=-0.103456788),
        ),
    )
    context = context.model_copy(
        update={
            "daily_indicator_snapshot": context.daily_indicator_snapshot.model_copy(
                update={"series": series}
            )
        }
    )
    condition = _condition(
        {
            "type": "MACD_HIST_IMPROVEMENT_GTE",
            "minimum_improvement": Decimal("0.0200000005"),
        }
    )

    with localcontext() as decimal_context:
        decimal_context.prec = 6
        low_precision = evaluate_condition(condition, context)
    with localcontext() as decimal_context:
        decimal_context.prec = 50
        high_precision = evaluate_condition(condition, context)

    assert low_precision == high_precision
    assert low_precision.outcome is ConditionOutcome.SATISFIED
    assert _facts(low_precision)["macd_histogram_improvement_yuan"] == Decimal("0.020000001")


def test_context_revalidation_is_independent_of_decimal_precision() -> None:
    context = _context()
    amount = Decimal("0.123456789")
    minutes = tuple(
        minute.model_copy(update={"amount_yuan": amount})
        if minute in context.current_bucket_minutes
        else minute
        for minute in context.current_day_minutes
    )
    latest = context.complete_5m_bars[-1].model_copy(update={"amount_yuan": Decimal("0.617283945")})
    context = context.model_copy(
        update={
            "current_day_minutes": minutes,
            "complete_5m_bars": (*context.complete_5m_bars[:-1], latest),
        }
    )
    condition = _condition({"type": "PRICE_IN_ZONE", "zone": "LOW_BUY"})

    with localcontext() as decimal_context:
        decimal_context.prec = 6
        low_precision = evaluate_condition(condition, context)
    with localcontext() as decimal_context:
        decimal_context.prec = 50
        high_precision = evaluate_condition(condition, context)

    assert low_precision == high_precision


def test_zero_median_cannot_satisfy_volume_expansion() -> None:
    context = _context()
    bars = _bars((0,) * 21)
    context = _with_complete_bars(context, bars)

    evidence = evaluate_condition(
        _condition(
            {
                "type": "VOLUME_TO_MEDIAN_GTE",
                "minimum_ratio": Decimal("1.50"),
                "window_bars": 20,
            }
        ),
        context,
    )

    assert evidence.outcome is ConditionOutcome.MISSING_INPUT
    assert MissingInputCode.ROLLING_VOLUME_WINDOW in evidence.missing_inputs


@pytest.mark.parametrize(
    ("zone", "price_fen", "expected"),
    [
        ("LOW_BUY", 6300, ConditionOutcome.SATISFIED),
        ("LOW_BUY", 6450, ConditionOutcome.SATISFIED),
        ("LOW_BUY", 6299, ConditionOutcome.UNSATISFIED),
        ("LOW_BUY", 6451, ConditionOutcome.UNSATISFIED),
        ("PRESSURE", 6880, ConditionOutcome.SATISFIED),
        ("PRESSURE", 7020, ConditionOutcome.SATISFIED),
        ("PRESSURE", 6879, ConditionOutcome.UNSATISFIED),
        ("PRESSURE", 7021, ConditionOutcome.UNSATISFIED),
    ],
)
def test_price_zone_uses_the_latest_complete_minute_and_exact_owned_endpoints(
    zone: str,
    price_fen: int,
    expected: ConditionOutcome,
) -> None:
    context = _with_latest_price(_context(), price_fen)

    evidence = evaluate_condition(
        _condition({"type": "PRICE_IN_ZONE", "zone": zone}),
        context,
    )

    assert evidence.outcome is expected
    assert _facts(evidence)["price_fen"] == price_fen
    assert _facts(evidence)["price_at"] == context.current_bucket_minutes[-1].bar_end


def test_ratio_and_count_conditions_include_their_exact_satisfied_boundaries() -> None:
    context = _context()
    median_boundary = _replace_latest_bar(context, volume_shares=150)
    upper_wick_boundary = _replace_latest_bar(
        context,
        open_fen=6360,
        high_fen=6400,
        low_fen=6300,
        close_fen=6360,
    )
    distance_boundary = _with_latest_price(context, 6060)
    lower_band_boundary = _replace_last_closes(context, (6300, 6300, 6300, 6400))

    cases = (
        (
            _condition(
                {
                    "type": "VOLUME_TO_MEDIAN_LTE",
                    "max_ratio": Decimal("1.50"),
                    "window_bars": 20,
                }
            ),
            median_boundary,
        ),
        (
            _condition(
                {
                    "type": "VOLUME_TO_MEDIAN_GTE",
                    "minimum_ratio": Decimal("1.50"),
                    "window_bars": 20,
                }
            ),
            median_boundary,
        ),
        (
            _condition({"type": "UPPER_WICK_RATIO_GTE", "minimum_ratio": Decimal("0.40")}),
            upper_wick_boundary,
        ),
        (
            _condition(
                {
                    "type": "DISTANCE_FROM_LIMIT_DOWN_GTE",
                    "minimum_ratio": Decimal("0.01"),
                }
            ),
            distance_boundary,
        ),
        (
            _condition({"type": "LOWER_BAND_HITS_LTE", "max_hits": 3, "window_bars": 4}),
            lower_band_boundary,
        ),
    )

    assert all(
        evaluate_condition(condition, boundary_context).outcome is ConditionOutcome.SATISFIED
        for condition, boundary_context in cases
    )
    assert _facts(evaluate_condition(cases[2][0], cases[2][1]))["upper_wick_ratio"] == Decimal(
        "0.4"
    )
    assert _facts(evaluate_condition(cases[3][0], cases[3][1]))[
        "distance_from_limit_down_ratio"
    ] == Decimal("0.01")
    assert _facts(evaluate_condition(cases[4][0], cases[4][1]))["lower_band_hit_count"] == 3


def test_flat_bar_shapes_and_zero_latest_expansion_fail_closed() -> None:
    flat = _with_latest_price(_context(), 6400)
    zero_latest = _replace_latest_bar(_context(), volume_shares=0)

    assert (
        evaluate_condition(
            _condition({"type": "UPPER_WICK_RATIO_GTE", "minimum_ratio": Decimal("0.40")}),
            flat,
        ).outcome
        is ConditionOutcome.UNSATISFIED
    )
    assert (
        evaluate_condition(
            _condition({"type": "CLOSE_IN_BAR_LOWER_HALF"}),
            flat,
        ).outcome
        is ConditionOutcome.UNSATISFIED
    )
    assert (
        evaluate_condition(
            _condition(
                {
                    "type": "VOLUME_TO_MEDIAN_GTE",
                    "minimum_ratio": Decimal("1.50"),
                    "window_bars": 20,
                }
            ),
            zero_latest,
        ).outcome
        is ConditionOutcome.UNSATISFIED
    )


def test_sellable_quantity_is_isolated_to_the_requested_bucket() -> None:
    context = _context().model_copy(
        update={
            "positions": (
                PositionLotSnapshot(
                    lot_id="lot-core-only",
                    symbol=SYMBOL,
                    bucket="CORE",
                    quantity=100,
                    remaining_quantity=100,
                    acquired_trade_date=PREVIOUS_TRADE_DATE,
                    cost_fen=6400,
                ),
            )
        }
    )

    evidence = evaluate_condition(
        _condition({"type": "SELLABLE_QUANTITY_GTE", "bucket": "TACTICAL", "quantity": 100}),
        context,
    )

    assert evidence.outcome is ConditionOutcome.UNSATISFIED
    assert _facts(evidence)["sellable_quantity"] == 0


def test_maximum_consecutive_window_is_bounded_and_missing_buckets_fail_closed() -> None:
    condition = _condition(
        {
            "type": "CONSECUTIVE_CLOSES_BELOW_LEVEL",
            "level": "PRESSURE_REFERENCE",
            "bars": 500,
        }
    )
    complete_context = _with_calendar_for_bars(
        _with_complete_bars(_context(), _recent_session_bars(500))
    )

    evidence = evaluate_condition(condition, complete_context)

    assert evidence.outcome is ConditionOutcome.SATISFIED
    assert len(evidence.facts) == 503

    context = _context()
    gapped_bars = (*context.complete_5m_bars[:-2], context.complete_5m_bars[-1])
    gapped = _with_complete_bars(context, gapped_bars)
    missing = evaluate_condition(
        _condition(
            {
                "type": "CONSECUTIVE_CLOSES_BELOW_LEVEL",
                "level": "PRESSURE_REFERENCE",
                "bars": 2,
            }
        ),
        gapped,
    )

    assert missing.outcome is ConditionOutcome.MISSING_INPUT
    assert missing.missing_inputs == (MissingInputCode.COMPLETE_5M_BAR_WINDOW,)


@pytest.mark.parametrize(
    ("previous_date", "calendar", "expected_outcome", "expected_missing"),
    [
        (
            PREVIOUS_TRADE_DATE,
            (
                TradingDay(
                    exchange="SZSE",
                    cal_date=TRADE_DATE,
                    is_open=True,
                    previous_trade_date=PREVIOUS_TRADE_DATE,
                ),
            ),
            ConditionOutcome.SATISFIED,
            None,
        ),
        (
            date(2026, 8, 5),
            (
                TradingDay(
                    exchange="SZSE",
                    cal_date=TRADE_DATE,
                    is_open=True,
                    previous_trade_date=PREVIOUS_TRADE_DATE,
                ),
            ),
            ConditionOutcome.MISSING_INPUT,
            MissingInputCode.COMPLETE_5M_BAR_WINDOW,
        ),
        (
            PREVIOUS_TRADE_DATE,
            (),
            ConditionOutcome.MISSING_INPUT,
            MissingInputCode.TRADING_CALENDAR,
        ),
    ],
)
def test_cross_day_five_minute_adjacency_requires_calendar_proof(
    previous_date: date,
    calendar: tuple[TradingDay, ...],
    expected_outcome: ConditionOutcome,
    expected_missing: MissingInputCode | None,
) -> None:
    target_end = datetime(2026, 8, 7, 9, 35, tzinfo=SHANGHAI)
    bars = (
        _bar(datetime.combine(previous_date, datetime.min.time(), SHANGHAI).replace(hour=15)),
        _bar(target_end),
    )
    provisional = _provisional_bar().model_copy(update={"received_at": target_end})
    reconciliation = reconcile_daily_close(
        symbol=SYMBOL,
        current_trade_date=TRADE_DATE,
        daily_bars=(provisional,),
    )
    has_open_target_day = any(day.cal_date == TRADE_DATE and day.is_open for day in calendar)
    context = _context().model_copy(
        update={
            "evaluated_at": target_end + timedelta(minutes=1),
            "target": IntradayEvaluationTarget(bucket_end=target_end),
            "current_day_minutes": _current_day_minutes(bars),
            "complete_5m_bars": bars,
            "five_minute_indicators": _five_minute_indicators(bars),
            "daily_indicator_snapshot": DailyIndicatorSnapshot(
                series=_daily_indicators(),
                provenance=DailyIndicatorProvenance.PROVISIONAL,
                source_as_of=target_end,
                source_bar=provisional,
            ),
            "close_reconciliation": reconciliation,
            "trading_calendar": calendar,
            "data_health": DataHealthSnapshot(
                symbol=SYMBOL,
                status=(DataHealthStatus.LIVE if has_open_target_day else DataHealthStatus.GAPPED),
                latest_bar_end=target_end,
                data_age_seconds=60,
                required_data_complete=has_open_target_day,
                fresh=has_open_target_day,
            ),
            "low_zone_episode": None,
        }
    )

    evidence = evaluate_condition(
        _condition(
            {
                "type": "CONSECUTIVE_CLOSES_BELOW_LEVEL",
                "level": "PRESSURE_REFERENCE",
                "bars": 2,
            }
        ),
        context,
    )

    assert evidence.outcome is expected_outcome
    assert evidence.missing_inputs == (() if expected_missing is None else (expected_missing,))


def test_price_reclaim_requires_a_crossing_from_below_the_selected_indicator() -> None:
    context = _replace_last_closes(_context(), (6500, 6501))

    evidence = evaluate_condition(
        _condition({"type": "PRICE_RECLAIMS_INDICATOR", "indicator": "EMA10"}),
        context,
    )

    assert evidence.outcome is ConditionOutcome.UNSATISFIED
    assert _facts(evidence)["previous_price_fen"] == 6500


@pytest.mark.parametrize(
    ("closes", "expected_outcome", "crossing_index"),
    [
        ((6399, 6399, 6400, 6401, 6401), ConditionOutcome.SATISFIED, 2),
        ((6399, 6400, 6401, 6399, 6399), ConditionOutcome.UNSATISFIED, 1),
        ((6399, 6400, 6401, 6401, 6400), ConditionOutcome.SATISFIED, 1),
        ((6400, 6401, 6401, 6401, 6401), ConditionOutcome.UNSATISFIED, None),
        ((6401, 6401, 6401, 6401, 6401), ConditionOutcome.UNSATISFIED, None),
        ((6399, 6400, 6399, 6400, 6401), ConditionOutcome.SATISFIED, 1),
    ],
)
def test_price_reclaim_scans_the_exact_bucket_and_holds_through_bucket_end(
    closes: tuple[int, int, int, int, int],
    expected_outcome: ConditionOutcome,
    crossing_index: int | None,
) -> None:
    context = _replace_target_minute_closes(_context(), closes)

    evidence = evaluate_condition(
        _condition({"type": "PRICE_RECLAIMS_INDICATOR", "indicator": "EMA10"}),
        context,
    )

    assert evidence.outcome is expected_outcome
    facts = _facts(evidence)
    assert facts["bucket_end_price_fen"] == closes[-1]
    assert facts["indicator_provenance"] == DailyIndicatorProvenance.PROVISIONAL.value
    assert facts["indicator_source_as_of"] == context.target.bucket_end
    if crossing_index is not None:
        assert facts["crossing_from_price_fen"] == closes[crossing_index - 1]
        assert facts["crossing_to_price_fen"] == closes[crossing_index]
        assert facts["crossing_at"] == context.current_bucket_minutes[crossing_index].bar_end


def test_price_reclaim_fails_closed_without_the_exact_current_bucket() -> None:
    evidence = evaluate_condition(
        _condition({"type": "PRICE_RECLAIMS_INDICATOR", "indicator": "EMA10"}),
        _without_current_minutes(_context()),
    )

    assert evidence.outcome is ConditionOutcome.MISSING_INPUT
    assert evidence.missing_inputs == (MissingInputCode.COMPLETE_MINUTE_BAR,)


def test_lower_band_hits_use_each_time_aligned_five_minute_indicator() -> None:
    context = _replace_last_closes(_context(), (6300, 6400, 6500, 6600))
    lower_values = (62.99, 64.00, 65.01, 65.99)
    first_selected = len(context.five_minute_indicators.points) - len(lower_values)
    points = tuple(
        point.model_copy(update={"boll_lower_yuan": lower_values[index - first_selected]})
        if index >= first_selected
        else point
        for index, point in enumerate(context.five_minute_indicators.points)
    )
    context = context.model_copy(
        update={
            "five_minute_indicators": context.five_minute_indicators.model_copy(
                update={"points": points}
            )
        }
    )

    evidence = evaluate_condition(
        _condition({"type": "LOWER_BAND_HITS_LTE", "max_hits": 2, "window_bars": 4}),
        context,
    )

    assert evidence.outcome is ConditionOutcome.SATISFIED
    assert _facts(evidence)["lower_band_hit_count"] == 2
    assert _facts(evidence)["close_minus_lower_2_yuan"] == Decimal("0.0")


def test_lower_band_hits_fail_closed_when_one_aligned_value_is_missing() -> None:
    context = _context()
    points = (
        *context.five_minute_indicators.points[:-2],
        context.five_minute_indicators.points[-2].model_copy(update={"boll_lower_yuan": None}),
        context.five_minute_indicators.points[-1],
    )
    context = context.model_copy(
        update={
            "five_minute_indicators": context.five_minute_indicators.model_copy(
                update={"points": points}
            )
        }
    )

    evidence = evaluate_condition(
        _condition({"type": "LOWER_BAND_HITS_LTE", "max_hits": 3, "window_bars": 4}),
        context,
    )

    assert evidence.outcome is ConditionOutcome.MISSING_INPUT
    assert evidence.missing_inputs == (MissingInputCode.INDICATOR_VALUE,)


def test_session_high_retreat_fails_closed_without_the_exact_current_day_slice() -> None:
    context = _context()
    context = context.model_copy(
        update={
            "current_day_minutes": context.current_day_minutes[5:],
            "data_health": context.data_health.model_copy(
                update={
                    "status": DataHealthStatus.GAPPED,
                    "required_data_complete": False,
                }
            ),
        }
    )

    evidence = evaluate_condition(
        _condition(
            {
                "type": "RETREAT_FROM_SESSION_HIGH_GTE",
                "minimum_ratio": Decimal("0.01"),
            }
        ),
        context,
    )

    assert evidence.outcome is ConditionOutcome.MISSING_INPUT
    assert evidence.missing_inputs == (MissingInputCode.SESSION_BARS,)


def test_session_high_retreat_uses_the_whole_certified_current_day_slice() -> None:
    context = _context()
    bars = (
        context.complete_5m_bars[0].model_copy(update={"high_fen": 6500}),
        *context.complete_5m_bars[1:-1],
        context.complete_5m_bars[-1].model_copy(
            update={
                "open_fen": 6450,
                "high_fen": 6450,
                "low_fen": 6400,
                "close_fen": 6435,
            }
        ),
    )
    context = _with_complete_bars(context, bars)
    condition = _condition(
        {
            "type": "RETREAT_FROM_SESSION_HIGH_GTE",
            "minimum_ratio": Decimal("0.01"),
        }
    )

    evidence = evaluate_condition(condition, context)

    assert evidence.outcome is ConditionOutcome.SATISFIED
    assert _facts(evidence)["session_high_fen"] == 6500
    assert _facts(evidence)["retreat_ratio"] == Decimal("0.01")

    missing = context.model_copy(
        update={
            "current_day_minutes": context.current_day_minutes[5:],
            "data_health": context.data_health.model_copy(
                update={
                    "status": DataHealthStatus.GAPPED,
                    "required_data_complete": False,
                }
            ),
        }
    )
    assert evaluate_condition(condition, missing).missing_inputs == (MissingInputCode.SESSION_BARS,)


def test_context_rejects_non_boundary_target_and_misaligned_indicators() -> None:
    with pytest.raises(ValidationError, match="five-minute boundary"):
        IntradayEvaluationTarget(bucket_end=datetime(2026, 8, 7, 11, 16, tzinfo=SHANGHAI))

    context = _context()
    shifted = context.five_minute_indicators.model_copy(
        update={
            "points": tuple(
                point.model_copy(update={"bar_at": point.bar_at + timedelta(minutes=1)})
                if index == 0
                else point
                for index, point in enumerate(context.five_minute_indicators.points)
            )
        }
    )
    with pytest.raises(ValidationError, match="align"):
        context.model_copy(update={"five_minute_indicators": shifted})


def test_context_rejects_self_contradictory_data_health() -> None:
    context = _context()
    contradictory = context.data_health.model_copy(
        update={
            "latest_bar_end": context.complete_5m_bars[0].bar_end,
            "data_age_seconds": 0,
            "status": DataHealthStatus.LIVE,
            "required_data_complete": True,
            "fresh": True,
        }
    )

    with pytest.raises(ValidationError, match="data age|latest bar"):
        context.model_copy(update={"data_health": contradictory})


def test_sellable_quantity_requires_an_open_trading_calendar_fact() -> None:
    context = _with_sellable_tactical(_context())
    context = context.model_copy(
        update={
            "trading_calendar": (),
            "data_health": context.data_health.model_copy(
                update={
                    "status": DataHealthStatus.GAPPED,
                    "required_data_complete": False,
                    "fresh": False,
                }
            ),
        }
    )

    evidence = evaluate_condition(
        _condition({"type": "SELLABLE_QUANTITY_GTE", "bucket": "TACTICAL", "quantity": 100}),
        context,
    )

    assert evidence.outcome is ConditionOutcome.MISSING_INPUT
    assert evidence.missing_inputs == (MissingInputCode.TRADING_CALENDAR,)


def test_official_ready_reconciliation_cannot_attach_to_an_intraday_identity() -> None:
    official_context = _with_official_close(_context(), 6079)

    with pytest.raises(ValidationError, match="official-close target"):
        official_context.model_copy(
            update={
                "target": IntradayEvaluationTarget(
                    bucket_end=official_context.complete_5m_bars[-1].bar_end
                )
            }
        )


def test_condition_evidence_rejects_reordered_children_and_forged_outcome() -> None:
    context = _context().model_copy(update={"manual_event_risk": True})
    parent = _condition(
        {
            "type": "ALL",
            "conditions": [
                {"type": "MANUAL_EVENT_RISK_CLEAR"},
                {"type": "PRICE_IN_ZONE", "zone": "LOW_BUY"},
            ],
        }
    )
    first = evaluate_condition(parent.conditions[0], context)
    second = evaluate_condition(parent.conditions[1], context)

    with pytest.raises(ValidationError, match="order"):
        ConditionEvidence(
            condition=parent,
            outcome=ConditionOutcome.UNSATISFIED,
            children=(second, first),
        )
    with pytest.raises(ValidationError, match="outcome"):
        ConditionEvidence(
            condition=parent,
            outcome=ConditionOutcome.SATISFIED,
            children=(first, second),
        )


def test_condition_evidence_revalidates_a_copied_nested_condition() -> None:
    invalid = _condition({"type": "NO_NEW_LOW_FOR_BARS", "bars": 2}).model_copy(update={"bars": 0})

    with pytest.raises(ValidationError):
        ConditionEvidence(
            condition=invalid,
            outcome=ConditionOutcome.UNSATISFIED,
        )


def test_signal_intent_locks_target_lot_shape_and_evidence_outcomes() -> None:
    context = _context()
    satisfied = evaluate_condition(
        _condition({"type": "PRICE_IN_ZONE", "zone": "LOW_BUY"}),
        context,
    )
    unmet = evaluate_condition(
        _condition({"type": "NO_NEW_LOW_FOR_BARS", "bars": 3}),
        context,
    )
    values = {
        "plan_hash": context.plan_hash,
        "symbol": SYMBOL,
        "trading_date": TRADE_DATE,
        "cause_id": "episode-001",
        "quantity": 100,
        "bucket": "CORE",
        "matched_conditions": (satisfied,),
        "blockers": (),
        "next_step": NextStep(code=NextStepCode.RECORD_CONFIRMED_FILL),
    }

    with pytest.raises(ValidationError, match="target lot"):
        SignalIntent(
            signal_type=ActionableSignalType.BUY_CORE_READY,
            target_lot_id="lot-core-001",
            **values,
        )
    with pytest.raises(ValidationError, match="target lot"):
        SignalIntent(
            signal_type=ActionableSignalType.PRESSURE_REDUCE_READY,
            target_lot_id=None,
            **(values | {"bucket": "TACTICAL"}),
        )
    with pytest.raises(ValidationError, match="matched"):
        SignalIntent(
            signal_type=ActionableSignalType.BUY_CORE_READY,
            target_lot_id=None,
            **(values | {"matched_conditions": (unmet,)}),
        )


def test_low_zone_fixture_covers_minute_close_boundaries_and_exclusions() -> None:
    fixture = _low_zone_fixture()

    assert fixture["schemaVersion"] == 2
    assert fixture["zone"] == {
        "lowFen": 6300,
        "highFen": 6450,
        "includeLow": True,
        "includeHigh": True,
    }
    cases = fixture["touchCases"]
    assert isinstance(cases, list)

    for case in cases:
        assert isinstance(case, dict)
        minute_closes = tuple(case["minuteClosesFen"])
        assert len(minute_closes) == 5
        range_override = case.get("rangeOverride")
        context = _touch_context(
            minute_closes,
            range_override=range_override,
        )
        before = context.model_dump(mode="python", round_trip=True)

        decision = evaluate_low_zone_episode(context)

        assert context.model_dump(mode="python", round_trip=True) == before, case["id"]
        assert decision == evaluate_low_zone_episode(context), case["id"]
        expected_index = case["expectedTouchIndex"]
        if expected_index is None:
            assert decision.touch_at is None, case["id"]
            assert decision.episode is None, case["id"]
            assert decision.transition is None, case["id"]
            assert decision.signal_intent is None, case["id"]
            continue

        expected_touch = context.current_bucket_minutes[expected_index].bar_end
        assert decision.touch_at == expected_touch, case["id"]
        assert decision.episode is not None, case["id"]
        assert decision.episode.started_at == expected_touch, case["id"]
        assert decision.episode.episode_low_fen == case["expectedEpisodeLowFen"], case["id"]
        assert decision.episode.bars_since_low == 0, case["id"]
        assert decision.episode.last_processed_bucket_end == context.target.bucket_end, case["id"]
        assert decision.episode.status is EpisodeStatus.ACTIVE, case["id"]
        assert decision.transition is not None, case["id"]
        assert decision.transition.action is EpisodeTransitionAction.UPSERT, case["id"]
        assert decision.transition.episode == decision.episode, case["id"]
        assert decision.signal_intent is None, case["id"]

    identity = fixture["episodeIdentity"]
    golden_case = next(case for case in cases if case["id"] == "inclusive-low")
    golden_context = _touch_context(tuple(golden_case["minuteClosesFen"]))
    golden = evaluate_low_zone_episode(golden_context)
    assert golden.touch_at == datetime.fromisoformat(identity["touchAt"])
    assert golden.episode is not None
    assert golden.episode.last_processed_bucket_end == datetime.fromisoformat(
        identity["expectedInitialCursor"]
    )
    assert golden.episode.episode_id == identity["expectedEpisodeId"]


def test_low_zone_touch_before_plan_activation_does_not_start_an_episode() -> None:
    context = _touch_context((6500, 6500, 6400, 6500, 6500)).model_copy(
        update={"activated_at": datetime(2026, 8, 7, 11, 14, tzinfo=SHANGHAI)}
    )

    decision = evaluate_low_zone_episode(context)

    assert decision.touch_at is None
    assert decision.episode is None
    assert decision.transition is None
    assert decision.signal_intent is None
    assert decision.structural_blockers == ()


def test_pre_activation_low_zone_episode_snapshot_cannot_progress_or_buy() -> None:
    context = _context().model_copy(
        update={"activated_at": datetime(2026, 8, 7, 10, 0, tzinfo=SHANGHAI)}
    )
    assert context.low_zone_episode is not None
    assert context.low_zone_episode.started_at < context.activated_at

    decision = evaluate_low_zone_episode(context)

    assert decision.episode == context.low_zone_episode
    assert decision.transition is None
    assert decision.signal_intent is None


def test_incomplete_low_zone_minutes_fail_closed_before_episode_creation() -> None:
    context = _touch_context((6500, 6500, 6400, 6500, 6500))
    incomplete_health = context.data_health.model_copy(
        update={
            "status": DataHealthStatus.GAPPED,
            "required_data_complete": False,
            "fresh": False,
        }
    )

    decision = evaluate_low_zone_episode(
        context.model_copy(update={"data_health": incomplete_health})
    )

    assert decision.episode is None
    assert decision.transition is None
    assert decision.signal_intent is None
    assert len(decision.structural_blockers) == 1
    assert decision.structural_blockers[0].code.value == "DATA_NOT_READY"
    assert decision.structural_blockers[0].outcome is ConditionOutcome.MISSING_INPUT
    assert decision.structural_blockers[0].missing_inputs == (MissingInputCode.COMPLETE_MINUTE_BAR,)


def test_low_zone_touch_bucket_does_not_backfill_pre_touch_low_or_confirm() -> None:
    context = _context()
    target_minutes = context.current_bucket_minutes
    context = _replace_minute_values(
        context,
        {
            minute.bar_end: {
                "open_fen": 6400,
                "high_fen": 6400,
                "low_fen": 6380 if index == 0 else 6400,
                "close_fen": 6400,
            }
            for index, minute in enumerate(target_minutes)
        },
    )
    touch_at = context.current_bucket_minutes[2].bar_end
    episode = LowZoneEpisodeSnapshot(
        episode_id="ep-touch-bucket",
        plan_hash=context.plan_hash,
        symbol=SYMBOL,
        started_at=touch_at,
        episode_low_fen=6400,
        bars_since_low=0,
        last_processed_bucket_end=context.target.bucket_end,
        status=EpisodeStatus.ACTIVE,
        alerted_signal=None,
    )

    decision = evaluate_low_zone_episode(context.model_copy(update={"low_zone_episode": episode}))

    assert context.complete_5m_bars[-1].low_fen == 6380
    assert decision.episode == episode
    assert decision.transition is None
    assert decision.signal_intent is None


@pytest.mark.parametrize(
    ("status", "alerted_signal"),
    [
        (EpisodeStatus.ACTIVE, None),
        (EpisodeStatus.ALERTED, "BUY_CORE_READY"),
        (EpisodeStatus.CLOSED, None),
    ],
)
def test_existing_low_zone_episode_at_the_target_cursor_is_a_complete_no_op(
    status: EpisodeStatus,
    alerted_signal: str | None,
) -> None:
    context = _context()
    assert isinstance(context.target, IntradayEvaluationTarget)
    episode = _episode(
        context.plan_hash,
        bars_since_low=2,
        last_processed_bucket_end=context.target.bucket_end,
    ).model_copy(
        update={
            "status": status,
            "alerted_signal": alerted_signal,
        }
    )

    decision = evaluate_low_zone_episode(context.model_copy(update={"low_zone_episode": episode}))

    assert decision.episode == episode
    assert decision.transition is None
    assert decision.signal_intent is None
    assert decision.entry_evidence is None
    assert decision.blocker_evidence is None
    assert decision.availability_evidence is None
    assert decision.structural_blockers == ()


def test_same_episode_cursor_ignores_late_data_limit_and_risk_fact_changes() -> None:
    context = _context()
    assert isinstance(context.target, IntradayEvaluationTarget)
    episode = _episode(
        context.plan_hash,
        bars_since_low=2,
        last_processed_bucket_end=context.target.bucket_end,
    )
    stale_health = context.data_health.model_copy(
        update={"status": DataHealthStatus.STALE, "fresh": False}
    )
    changed_facts = _with_breached_risk(context).model_copy(
        update={
            "low_zone_episode": episode,
            "data_health": stale_health,
            "daily_limit": None,
            "manual_event_risk": True,
        }
    )

    decision = evaluate_low_zone_episode(changed_facts)

    assert decision.episode == episode
    assert decision.transition is None
    assert decision.signal_intent is None
    assert decision.entry_evidence is None
    assert decision.blocker_evidence is None
    assert decision.availability_evidence is None
    assert decision.structural_blockers == ()


def test_late_discovered_low_zone_touch_consumes_through_the_current_target() -> None:
    context = _context().model_copy(
        update={
            "low_zone_episode": None,
            "manual_event_risk": True,
        }
    )

    decision = evaluate_low_zone_episode(context)

    assert decision.episode is not None
    assert decision.episode.started_at == context.current_day_minutes[0].bar_end
    assert decision.episode.bars_since_low == 2
    assert decision.episode.last_processed_bucket_end == context.target_cutoff
    assert decision.episode.status is EpisodeStatus.ACTIVE
    assert decision.transition is not None
    assert decision.transition.episode == decision.episode
    assert decision.signal_intent is None

    replay = evaluate_low_zone_episode(
        context.model_copy(update={"low_zone_episode": decision.episode})
    )
    assert replay.episode == decision.episode
    assert replay.transition is None
    assert replay.signal_intent is None


def test_late_discovered_low_zone_touch_applies_a_target_bucket_new_low_once() -> None:
    context = _replace_latest_bar(_context(), low_fen=6379).model_copy(
        update={
            "low_zone_episode": None,
            "manual_event_risk": True,
        }
    )

    decision = evaluate_low_zone_episode(context)

    assert decision.episode is not None
    assert decision.episode.episode_low_fen == 6379
    assert decision.episode.bars_since_low == 0
    assert decision.episode.last_processed_bucket_end == context.target_cutoff

    replay = evaluate_low_zone_episode(
        context.model_copy(update={"low_zone_episode": decision.episode})
    )
    assert replay.episode == decision.episode
    assert replay.transition is None


def test_late_discovered_episode_closes_then_reenters_after_its_closure_cursor() -> None:
    closure_context = _replace_last_closes(_context(), (6400, 6451, 6451)).model_copy(
        update={"low_zone_episode": None}
    )

    closed = evaluate_low_zone_episode(closure_context)

    assert closed.episode is not None
    assert closed.episode.status is EpisodeStatus.CLOSED
    assert closed.episode.last_processed_bucket_end == closure_context.target_cutoff
    assert closed.transition is not None
    assert closed.transition.action is EpisodeTransitionAction.CLOSE

    reentry_context = _append_intraday_bar(
        closure_context.model_copy(update={"low_zone_episode": closed.episode}),
        close_fen=6400,
    )
    reentered = evaluate_low_zone_episode(reentry_context)

    assert reentered.episode is not None
    assert reentered.episode.status is EpisodeStatus.ACTIVE
    assert reentered.episode.episode_id != closed.episode.episode_id
    assert reentered.episode.started_at > closed.episode.last_processed_bucket_end
    assert reentered.episode.last_processed_bucket_end == reentry_context.target_cutoff


def test_low_zone_episode_progresses_one_bar_then_one_tick_new_low_resets() -> None:
    touch_context = _touch_context((6500, 6500, 6300, 6400, 6400))
    started = evaluate_low_zone_episode(touch_context)
    assert started.episode is not None
    context = _append_intraday_bar(
        touch_context.model_copy(update={"low_zone_episode": started.episode})
    )

    first = evaluate_low_zone_episode(context)

    assert first.episode is not None
    assert first.episode.episode_low_fen == 6300
    assert first.episode.bars_since_low == 1
    assert first.transition is not None
    assert first.transition.action is EpisodeTransitionAction.UPSERT
    assert first.signal_intent is None

    reset_context = _replace_latest_bar(
        _context(),
        low_fen=6379,
    )
    reset = evaluate_low_zone_episode(reset_context)

    assert reset.episode is not None
    assert reset.episode.episode_low_fen == 6379
    assert reset.episode.bars_since_low == 0
    assert reset.episode.last_processed_bucket_end == reset_context.target.bucket_end
    assert reset.transition is not None
    assert reset.signal_intent is None
    assert reset.entry_evidence is not None
    assert reset.entry_evidence.outcome is ConditionOutcome.UNSATISFIED

    replayed_reset = evaluate_low_zone_episode(
        reset_context.model_copy(update={"low_zone_episode": reset.episode})
    )
    assert replayed_reset.episode == reset.episode
    assert replayed_reset.transition is None


def test_equal_low_does_not_reset_and_second_low_zone_bar_confirms() -> None:
    context = _context().model_copy(
        update={"low_zone_episode": _episode(_context().plan_hash, bars_since_low=1)}
    )

    confirmed = evaluate_low_zone_episode(context)

    assert confirmed.episode is not None
    assert confirmed.episode.bars_since_low == 2
    assert confirmed.episode.status is EpisodeStatus.ALERTED
    assert confirmed.signal_intent is not None
    assert confirmed.signal_intent.signal_type is ActionableSignalType.BUY_CORE_READY

    blocked_at_threshold = context.model_copy(
        update={
            "low_zone_episode": _episode(context.plan_hash, bars_since_low=2),
            "manual_event_risk": True,
        }
    )
    saturated = evaluate_low_zone_episode(blocked_at_threshold)

    assert saturated.episode is not None
    assert (
        saturated.episode.episode_low_fen == blocked_at_threshold.low_zone_episode.episode_low_fen
    )
    assert saturated.episode.bars_since_low == 2
    assert saturated.episode.last_processed_bucket_end == blocked_at_threshold.target.bucket_end
    assert saturated.transition is not None
    assert saturated.transition.action is EpisodeTransitionAction.UPSERT
    assert saturated.signal_intent is None


def test_cross_day_equal_low_advances_once_without_resetting_or_replaying() -> None:
    base = _context()
    fixture = _low_zone_fixture()["crossDayReplay"]
    assert isinstance(fixture, dict)
    target_end = datetime.fromisoformat(fixture["target"])
    initial_cursor = datetime.fromisoformat(fixture["initialCursor"])
    equal_low_fen = fixture["equalLowFen"]
    prior_close = _bar(initial_cursor, low_fen=equal_low_fen)
    current = _bar(target_end, low_fen=equal_low_fen)
    bars = (prior_close, current)
    source_bar = _provisional_bar().model_copy(update={"received_at": target_end})
    reconciliation = reconcile_daily_close(
        symbol=SYMBOL,
        current_trade_date=TRADE_DATE,
        daily_bars=(source_bar,),
    )
    episode = LowZoneEpisodeSnapshot(
        episode_id="episode-cross-day-equal-low",
        plan_hash=base.plan_hash,
        symbol=SYMBOL,
        started_at=prior_close.bar_end,
        episode_low_fen=equal_low_fen,
        bars_since_low=fixture["startingBarsSinceLow"],
        last_processed_bucket_end=prior_close.bar_end,
        status=EpisodeStatus.ACTIVE,
        alerted_signal=None,
    )
    context = base.model_copy(
        update={
            "evaluated_at": target_end + timedelta(minutes=1),
            "target": IntradayEvaluationTarget(bucket_end=target_end),
            "activated_at": datetime(2026, 8, 6, 9, 0, tzinfo=SHANGHAI),
            "current_day_minutes": _current_day_minutes(bars),
            "complete_5m_bars": bars,
            "five_minute_indicators": _five_minute_indicators(bars),
            "daily_indicator_snapshot": DailyIndicatorSnapshot(
                series=_daily_indicators(),
                provenance=DailyIndicatorProvenance.PROVISIONAL,
                source_as_of=target_end,
                source_bar=reconciliation.provisional_bar,
            ),
            "close_reconciliation": reconciliation,
            "trading_calendar": (
                TradingDay(
                    exchange="SZSE",
                    cal_date=PREVIOUS_TRADE_DATE,
                    is_open=True,
                    previous_trade_date=date(2026, 8, 5),
                ),
                TradingDay(
                    exchange="SZSE",
                    cal_date=TRADE_DATE,
                    is_open=True,
                    previous_trade_date=PREVIOUS_TRADE_DATE,
                ),
            ),
            "data_health": DataHealthSnapshot(
                symbol=SYMBOL,
                status=DataHealthStatus.LIVE,
                latest_bar_end=target_end,
                data_age_seconds=60,
                required_data_complete=True,
                fresh=True,
            ),
            "low_zone_episode": episode,
        }
    )

    advanced = evaluate_low_zone_episode(context)

    assert advanced.episode is not None
    assert advanced.episode.episode_low_fen == equal_low_fen
    assert advanced.episode.bars_since_low == fixture["expectedBarsSinceLow"]
    assert advanced.episode.last_processed_bucket_end == target_end
    assert advanced.signal_intent is None

    replayed = evaluate_low_zone_episode(
        context.model_copy(update={"low_zone_episode": advanced.episode})
    )

    assert replayed.episode == advanced.episode
    assert replayed.transition is None
    assert replayed.signal_intent is None


@pytest.mark.parametrize(
    ("include_anchor", "calendar_previous"),
    [
        (False, PREVIOUS_TRADE_DATE),
        (True, date(2026, 8, 5)),
    ],
    ids=("missing-cursor-anchor", "missing-cross-day-calendar-proof"),
)
def test_low_zone_episode_cursor_fails_closed_without_continuity_proof(
    include_anchor: bool,
    calendar_previous: date,
) -> None:
    base = _context()
    cursor = datetime(2026, 8, 6, 15, 0, tzinfo=SHANGHAI)
    anchor = _bar(cursor)
    bars = (anchor, *base.complete_5m_bars) if include_anchor else base.complete_5m_bars
    episode = LowZoneEpisodeSnapshot(
        episode_id="episode-cursor-continuity",
        plan_hash=base.plan_hash,
        symbol=SYMBOL,
        started_at=cursor,
        episode_low_fen=6380,
        bars_since_low=2,
        last_processed_bucket_end=cursor,
        status=EpisodeStatus.ACTIVE,
        alerted_signal=None,
    )
    context = base.model_copy(
        update={
            "activated_at": datetime(2026, 8, 6, 9, 0, tzinfo=SHANGHAI),
            "complete_5m_bars": bars,
            "five_minute_indicators": _five_minute_indicators(bars),
            "trading_calendar": (
                TradingDay(
                    exchange="SZSE",
                    cal_date=TRADE_DATE,
                    is_open=True,
                    previous_trade_date=calendar_previous,
                ),
            ),
            "low_zone_episode": episode,
        }
    )

    decision = evaluate_low_zone_episode(context)

    assert decision.episode == episode
    assert decision.transition is None
    assert decision.signal_intent is None
    assert tuple(item.code.value for item in decision.structural_blockers) == (
        "EPISODE_HISTORY_GAP",
    )
    assert decision.structural_blockers[0].missing_inputs == (
        MissingInputCode.COMPLETE_5M_BAR_WINDOW,
    )
    assert {fact.key: fact.value for fact in decision.structural_blockers[0].facts} == {
        "last_processed_bucket_end": cursor,
        "evaluation_target": context.target_cutoff,
    }


def test_low_zone_confirmation_advances_across_two_sequential_complete_targets() -> None:
    touch_context = _touch_context((6500, 6500, 6300, 6400, 6400))
    started = evaluate_low_zone_episode(touch_context)
    assert started.episode is not None
    assert started.episode.bars_since_low == 0
    assert started.signal_intent is None

    first_context = _append_intraday_bar(
        touch_context.model_copy(update={"low_zone_episode": started.episode})
    )
    first = evaluate_low_zone_episode(first_context)
    assert first.episode is not None
    assert first.episode.status is EpisodeStatus.ACTIVE
    assert first.episode.bars_since_low == 1
    assert first.episode.last_processed_bucket_end == first_context.target.bucket_end
    assert first.signal_intent is None

    same_bucket = evaluate_low_zone_episode(
        first_context.model_copy(update={"low_zone_episode": first.episode})
    )
    assert same_bucket.episode == first.episode
    assert same_bucket.transition is None
    assert same_bucket.signal_intent is None

    second_context = _append_intraday_bar(
        first_context.model_copy(update={"low_zone_episode": first.episode})
    )
    second = evaluate_low_zone_episode(second_context)
    assert second.episode is not None
    assert second.episode.status is EpisodeStatus.ALERTED
    assert second.episode.bars_since_low == 2
    assert second.episode.last_processed_bucket_end == second_context.target.bucket_end
    assert second.signal_intent is not None
    assert second.signal_intent.signal_type is ActionableSignalType.BUY_CORE_READY


@pytest.mark.parametrize(
    ("volumes", "expected_signal"),
    [
        ((100,) * 19 + (150, 150), True),
        ((100,) * 19 + (151, 151), False),
    ],
    ids=("median-threshold-equality", "median-threshold-plus-one"),
)
def test_low_zone_volume_rules_gate_core_signal(
    volumes: tuple[int, ...],
    expected_signal: bool,
) -> None:
    context = _with_complete_bars(_context(), _bars(volumes=volumes))

    decision = evaluate_low_zone_episode(context)

    assert (decision.signal_intent is not None) is expected_signal
    assert decision.entry_evidence is not None
    assert (decision.entry_evidence.outcome is ConditionOutcome.SATISFIED) is expected_signal


@pytest.mark.parametrize(
    ("context_transform", "expected_signal"),
    [
        (lambda value: value, True),
        (lambda value: _replace_last_closes(value, (6401, 6400)), False),
        (
            lambda value: _with_complete_bars(
                value,
                _bars(volumes=(100,) * 20 + (101,)),
            ),
            False,
        ),
    ],
    ids=("equal-close-and-volume", "close-down-one-tick", "volume-up-one-share"),
)
def test_low_zone_non_decreasing_close_and_previous_volume_are_both_required(
    context_transform: ContextTransform,
    expected_signal: bool,
) -> None:
    decision = evaluate_low_zone_episode(context_transform(_context()))

    assert (decision.signal_intent is not None) is expected_signal
    assert decision.entry_evidence is not None
    assert (decision.entry_evidence.outcome is ConditionOutcome.SATISFIED) is expected_signal


@pytest.mark.parametrize(
    ("closes", "current_histogram", "expected_signal"),
    [
        ((6399, 6399), -0.08, True),
        ((6399, 6400), -0.09, True),
        ((6399, 6399), -0.09, False),
    ],
    ids=("macd-equality", "ema-reclaim", "neither-momentum-branch"),
)
def test_low_zone_macd_or_ema_alternative_gates_core_signal(
    closes: tuple[int, int],
    current_histogram: float,
    expected_signal: bool,
) -> None:
    context = _context()
    previous_minutes = context.current_day_minutes[-10:-5]
    target_minutes = context.current_day_minutes[-5:]
    target_closes = (closes[1],) * 5 if closes[1] == 6399 else (6399, 6399, 6399, 6399, closes[1])
    context = _replace_minute_closes(
        context,
        {
            **{minute.bar_end: closes[0] for minute in previous_minutes},
            **{
                minute.bar_end: close
                for minute, close in zip(target_minutes, target_closes, strict=True)
            },
        },
    )
    indicator_snapshot = context.daily_indicator_snapshot
    assert indicator_snapshot is not None
    context = context.model_copy(
        update={
            "daily_indicator_snapshot": indicator_snapshot.model_copy(
                update={"series": _daily_indicators(current_histogram=current_histogram)}
            )
        }
    )

    decision = evaluate_low_zone_episode(context)

    assert (decision.signal_intent is not None) is expected_signal
    assert decision.entry_evidence is not None
    assert (decision.entry_evidence.outcome is ConditionOutcome.SATISFIED) is expected_signal


@pytest.mark.parametrize("manual_event_risk", [True, None])
def test_low_zone_blocker_evidence_suppresses_buy_without_stopping_episode(
    manual_event_risk: bool | None,
) -> None:
    context = _context().model_copy(update={"manual_event_risk": manual_event_risk})

    decision = evaluate_low_zone_episode(context)

    assert decision.episode is not None
    assert decision.episode.episode_id == context.low_zone_episode.episode_id
    assert decision.episode.status is EpisodeStatus.ACTIVE
    assert decision.episode.last_processed_bucket_end == context.target.bucket_end
    assert decision.transition is not None
    assert decision.transition.action is EpisodeTransitionAction.UPSERT
    assert decision.signal_intent is None
    assert decision.blocker_evidence is not None
    expected = (
        ConditionOutcome.UNSATISFIED
        if manual_event_risk is True
        else ConditionOutcome.MISSING_INPUT
    )
    assert decision.blocker_evidence.outcome is expected


def test_low_zone_structural_buy_gates_fail_closed() -> None:
    base = _context()
    stale_health = base.data_health.model_copy(
        update={"status": DataHealthStatus.STALE, "fresh": False}
    )
    cases = (
        (
            base.model_copy(update={"daily_limit": None}),
            "DAILY_LIMIT_UNKNOWN",
            ConditionOutcome.MISSING_INPUT,
            (MissingInputCode.DAILY_LIMIT,),
            {"daily_limit_present": False},
        ),
        (
            base.model_copy(update={"data_health": stale_health}),
            "DATA_NOT_READY",
            ConditionOutcome.UNSATISFIED,
            (),
            {
                "data_health_status": "STALE",
                "required_data_complete": True,
                "fresh": False,
                "trading_day_present": True,
                "trading_day_open": True,
                "minute_history_complete": True,
                "target_bar_present": True,
            },
        ),
        (
            _with_breached_risk(base),
            "RISK_PENDING",
            ConditionOutcome.UNSATISFIED,
            (),
            {
                "risk_status": "BREACHED_PENDING_CONFIRMATION",
                "risk_breach_trade_date": PREVIOUS_TRADE_DATE,
            },
        ),
    )

    for context, expected_code, expected_outcome, expected_missing, expected_facts in cases:
        decision = evaluate_low_zone_episode(context)
        assert decision.signal_intent is None
        assert tuple(item.code.value for item in decision.structural_blockers) == (expected_code,)
        blocker = decision.structural_blockers[0]
        assert blocker.outcome is expected_outcome
        assert blocker.missing_inputs == expected_missing
        assert {fact.key: fact.value for fact in blocker.facts} == expected_facts

    inactive = evaluate_low_zone_episode(
        base.model_copy(update={"plan_active": False, "activated_at": None})
    )
    assert inactive.signal_intent is None
    assert inactive.structural_blockers == ()


@pytest.mark.parametrize(
    ("open_fen", "volume_shares", "expected_blocked"),
    [
        (6401, 150, False),
        (6401, 151, True),
        (6399, 151, False),
    ],
    ids=("bearish-equality", "bearish-plus-one", "bullish-plus-one"),
)
def test_low_zone_bearish_volume_expansion_has_explicit_structural_evidence(
    open_fen: int,
    volume_shares: int,
    expected_blocked: bool,
) -> None:
    context = _replace_latest_bar(
        _context(),
        open_fen=open_fen,
        close_fen=6400,
        volume_shares=volume_shares,
    )

    decision = evaluate_low_zone_episode(context)

    bearish = tuple(
        blocker
        for blocker in decision.structural_blockers
        if blocker.code.value == "BEARISH_VOLUME_EXPANSION"
    )
    assert bool(bearish) is expected_blocked
    if not expected_blocked:
        return
    assert len(bearish) == 1
    assert bearish[0].outcome is ConditionOutcome.UNSATISFIED
    assert bearish[0].missing_inputs == ()
    assert {fact.key: fact.value for fact in bearish[0].facts} == {
        "latest_open_fen": 6401,
        "latest_close_fen": 6400,
        "bearish": True,
        "latest_volume_shares": 151,
        "median_volume_shares": Decimal("100"),
        "threshold_volume_shares": Decimal("150.00"),
        "maximum_ratio": Decimal("1.50"),
        "window_bars": 20,
        "observed_ratio": Decimal("1.51"),
    }


@pytest.mark.parametrize(
    "condition_payload",
    [
        {
            "type": "ANY",
            "conditions": [
                {"type": "PRICE_IN_ZONE", "zone": "LOW_BUY"},
                {
                    "type": "VOLUME_TO_MEDIAN_LTE",
                    "max_ratio": Decimal("1.5"),
                    "window_bars": 20,
                },
            ],
        },
        {
            "type": "ANY",
            "conditions": [
                {
                    "type": "VOLUME_TO_MEDIAN_LTE",
                    "max_ratio": Decimal("1.5"),
                    "window_bars": 20,
                },
                {"type": "PRICE_IN_ZONE", "zone": "LOW_BUY"},
            ],
        },
        {
            "type": "ANY",
            "conditions": [
                {
                    "type": "ANY",
                    "conditions": [
                        {"type": "PRICE_IN_ZONE", "zone": "LOW_BUY"},
                        {
                            "type": "VOLUME_TO_MEDIAN_LTE",
                            "max_ratio": Decimal("1.5"),
                            "window_bars": 20,
                        },
                    ],
                },
                {
                    "type": "VOLUME_TO_MEDIAN_LTE",
                    "max_ratio": Decimal("1.2"),
                    "window_bars": 20,
                },
            ],
        },
    ],
    ids=("price-first", "volume-first", "nested-and-multiple-volume-caps"),
)
def test_low_zone_any_volume_alternatives_do_not_become_structural_blockers(
    condition_payload: ConditionPayload,
) -> None:
    """A satisfied ANY entry branch cannot be vetoed by an optional volume cap."""

    condition = _condition(condition_payload)
    context = _with_entry_condition(
        _replace_latest_bar(
            _context(),
            open_fen=6420,
            high_fen=6420,
            low_fen=6380,
            close_fen=6400,
            volume_shares=100_000,
        ),
        condition,
    )

    source = evaluate_low_zone_episode(context)
    assert source.entry_evidence is not None
    assert source.entry_evidence.outcome is ConditionOutcome.SATISFIED
    assert not any(
        blocker.code.value == "BEARISH_VOLUME_EXPANSION"
        for blocker in source.structural_blockers
    )
    assert source.signal_intent is not None

    result = evaluate(context)

    assert result.snapshot.signal_type is SignalType.BUY_CORE_READY
    assert result.signal_intent == source.signal_intent
    assert not any(
        isinstance(evidence, RuleEvidence)
        and evidence.code is RuleEvidenceCode.BEARISH_VOLUME_EXPANSION
        for evidence in result.blockers
    )


def test_low_zone_near_limit_down_blocker_is_executable_and_visible() -> None:
    context = _context()
    assert context.daily_limit is not None
    context = context.model_copy(
        update={"daily_limit": context.daily_limit.model_copy(update={"down_limit_fen": 6350})}
    )

    decision = evaluate_low_zone_episode(context)

    assert decision.signal_intent is None
    assert decision.blocker_evidence is not None
    distance = next(
        child
        for child in decision.blocker_evidence.children
        if child.condition.type == "DISTANCE_FROM_LIMIT_DOWN_GTE"
    )
    assert distance.outcome is ConditionOutcome.UNSATISFIED
    assert _facts(distance)["minimum_ratio"] == Decimal("0.01")


def test_low_zone_lower_band_walk_blocker_is_executable_and_visible() -> None:
    context = _replace_last_closes(_context(), (6350, 6350, 6350, 6350))

    decision = evaluate_low_zone_episode(context)

    assert decision.signal_intent is None
    assert decision.blocker_evidence is not None
    lower_band = next(
        child
        for child in decision.blocker_evidence.children
        if child.condition.type == "LOWER_BAND_HITS_LTE"
    )
    assert lower_band.outcome is ConditionOutcome.UNSATISFIED
    assert _facts(lower_band)["lower_band_hit_count"] == 4
    assert _facts(lower_band)["maximum_hits"] == 2


def test_low_zone_position_sequence_is_core_first_then_tactical_and_capped() -> None:
    fixture = _low_zone_fixture()
    cases = fixture["positionCases"]
    assert isinstance(cases, list)

    for case in cases:
        assert isinstance(case, dict)
        context = _context().model_copy(
            update={
                "positions": _position_lots(
                    case["coreQuantity"],
                    case["tacticalQuantity"],
                )
            }
        )

        decision = evaluate_low_zone_episode(context)

        expected_signal = case["expectedSignal"]
        if expected_signal is None:
            assert decision.signal_intent is None, case["id"]
            assert decision.episode is not None
            assert decision.episode.status is EpisodeStatus.ACTIVE
            assert decision.availability_evidence is not None
            assert decision.availability_evidence.outcome is ConditionOutcome.UNSATISFIED
            continue

        assert decision.signal_intent is not None, case["id"]
        assert decision.signal_intent.signal_type.value == expected_signal, case["id"]
        assert decision.signal_intent.quantity == fixture["confirmation"]["quantity"]
        assert decision.signal_intent.bucket == (
            "CORE" if expected_signal == "BUY_CORE_READY" else "TACTICAL"
        )
        assert decision.signal_intent.cause_id == decision.episode.episode_id
        assert decision.signal_intent.matched_conditions == (
            decision.entry_evidence,
            decision.blocker_evidence,
            decision.availability_evidence,
        )
        assert decision.episode is not None
        assert decision.episode.status is EpisodeStatus.ALERTED
        assert decision.episode.alerted_signal == expected_signal
        assert decision.transition is not None
        assert decision.transition.action is EpisodeTransitionAction.UPSERT


def test_alerted_low_zone_episode_never_emits_a_second_buy_intent() -> None:
    first = evaluate_low_zone_episode(_context())
    assert first.episode is not None
    assert first.signal_intent is not None
    repeated_context = _context().model_copy(
        update={
            "low_zone_episode": first.episode,
            "positions": _position_lots(100, 0),
        }
    )

    repeated = evaluate_low_zone_episode(repeated_context)

    assert repeated.episode == first.episode
    assert repeated.transition is None
    assert repeated.signal_intent is None


def test_alerted_low_zone_episode_keeps_tracking_new_low_without_realerting() -> None:
    context = _replace_latest_bar(_context(), low_fen=6379)
    alerted = _episode(context.plan_hash).model_copy(
        update={
            "status": EpisodeStatus.ALERTED,
            "alerted_signal": "BUY_CORE_READY",
        }
    )

    decision = evaluate_low_zone_episode(context.model_copy(update={"low_zone_episode": alerted}))

    assert decision.episode is not None
    assert decision.episode.status is EpisodeStatus.ALERTED
    assert decision.episode.episode_low_fen == 6379
    assert decision.episode.bars_since_low == 0
    assert decision.episode.last_processed_bucket_end == context.target.bucket_end
    assert decision.transition is not None
    assert decision.transition.action is EpisodeTransitionAction.UPSERT
    assert decision.signal_intent is None

    replay = evaluate_low_zone_episode(
        context.model_copy(update={"low_zone_episode": decision.episode})
    )
    assert replay.episode == decision.episode
    assert replay.transition is None


@pytest.mark.parametrize("status", [EpisodeStatus.ACTIVE, EpisodeStatus.ALERTED])
def test_low_zone_episode_closes_after_two_adjacent_outside_closes(
    status: EpisodeStatus,
) -> None:
    context = _replace_last_closes(_context(), (6451, 6299))
    episode = _episode(context.plan_hash).model_copy(
        update={
            "status": status,
            "alerted_signal": "BUY_CORE_READY" if status is EpisodeStatus.ALERTED else None,
        }
    )
    context = context.model_copy(update={"low_zone_episode": episode})

    decision = evaluate_low_zone_episode(context)

    assert decision.episode is not None
    assert decision.episode.status is EpisodeStatus.CLOSED
    assert decision.episode.alerted_signal == episode.alerted_signal
    assert decision.episode.episode_low_fen == 6279
    assert decision.episode.bars_since_low == 0
    assert decision.episode.last_processed_bucket_end == context.target.bucket_end
    assert decision.transition is not None
    assert decision.transition.action is EpisodeTransitionAction.CLOSE
    assert decision.signal_intent is None


def test_low_zone_episode_does_not_close_on_one_outside_or_inclusive_boundary() -> None:
    for closes in ((6400, 6451), (6450, 6451), (6299, 6300)):
        context = _replace_last_closes(_context(), closes).model_copy(
            update={"manual_event_risk": True}
        )

        decision = evaluate_low_zone_episode(context)

        assert decision.episode is not None
        assert decision.episode.status is EpisodeStatus.ACTIVE
        assert decision.transition is None or (
            decision.transition.action is EpisodeTransitionAction.UPSERT
        )


def test_closed_low_zone_episode_reentry_creates_a_new_touch_only_episode() -> None:
    context = _replace_last_closes(_context(), (6400, 6451, 6451, 6400))
    closed = _episode(context.plan_hash).model_copy(
        update={
            "status": EpisodeStatus.CLOSED,
            "alerted_signal": "BUY_CORE_READY",
        }
    )
    context = context.model_copy(
        update={
            "low_zone_episode": closed,
            "positions": _position_lots(100, 0),
        }
    )

    decision = evaluate_low_zone_episode(context)

    assert decision.touch_at == datetime(2026, 8, 7, 11, 11, tzinfo=SHANGHAI)
    assert decision.episode is not None
    assert decision.episode.episode_id != closed.episode_id
    assert decision.episode.status is EpisodeStatus.ACTIVE
    assert decision.episode.bars_since_low == 0
    assert decision.episode.last_processed_bucket_end == context.target.bucket_end
    assert decision.transition is not None
    assert decision.transition.action is EpisodeTransitionAction.UPSERT
    assert decision.signal_intent is None


def test_active_episode_recovers_prior_exit_before_accepting_reentry() -> None:
    context = _replace_last_closes(_context(), (6451, 6451, 6400, 6400))
    assert context.low_zone_episode is not None
    context = context.model_copy(
        update={
            "low_zone_episode": context.low_zone_episode.model_copy(
                update={"last_processed_bucket_end": context.complete_5m_bars[-5].bar_end}
            )
        }
    )

    closed = evaluate_low_zone_episode(context)

    assert closed.episode is not None
    assert closed.episode.episode_id == context.low_zone_episode.episode_id
    assert closed.episode.status is EpisodeStatus.CLOSED
    assert closed.episode.last_processed_bucket_end == context.complete_5m_bars[-3].bar_end
    assert closed.transition is not None
    assert closed.transition.action is EpisodeTransitionAction.CLOSE
    assert closed.signal_intent is None

    reentered = evaluate_low_zone_episode(
        context.model_copy(update={"low_zone_episode": closed.episode})
    )
    assert reentered.episode is not None
    assert reentered.episode.episode_id != closed.episode.episode_id
    assert reentered.episode.status is EpisodeStatus.ACTIVE
    assert reentered.transition is not None
    assert reentered.transition.action is EpisodeTransitionAction.UPSERT
    assert reentered.signal_intent is None


def test_reentered_low_zone_episode_emits_one_tactical_buy_with_new_identity() -> None:
    exited_context = _replace_last_closes(_context(), (6400, 6451, 6451, 6400))
    closed = _episode(exited_context.plan_hash).model_copy(
        update={
            "status": EpisodeStatus.CLOSED,
            "alerted_signal": "BUY_CORE_READY",
        }
    )
    exited_context = exited_context.model_copy(
        update={
            "low_zone_episode": closed,
            "positions": _position_lots(100, 0),
        }
    )
    reentered = evaluate_low_zone_episode(exited_context)
    assert reentered.episode is not None
    assert reentered.episode.episode_id != closed.episode_id

    first_context = _append_intraday_bar(
        exited_context.model_copy(update={"low_zone_episode": reentered.episode})
    )
    first = evaluate_low_zone_episode(first_context)
    assert first.episode is not None
    assert first.episode.bars_since_low == 1
    assert first.signal_intent is None

    second_context = _append_intraday_bar(
        first_context.model_copy(update={"low_zone_episode": first.episode})
    )
    second = evaluate_low_zone_episode(second_context)
    assert second.episode is not None
    assert second.episode.status is EpisodeStatus.ALERTED
    assert second.signal_intent is not None
    assert second.signal_intent.signal_type is ActionableSignalType.BUY_TACTICAL_READY
    assert second.signal_intent.cause_id == reentered.episode.episode_id
    assert second.signal_intent.quantity == 100

    replay = evaluate_low_zone_episode(
        second_context.model_copy(update={"low_zone_episode": second.episode})
    )
    assert replay.signal_intent is None


def test_low_zone_episode_evaluation_is_intraday_only() -> None:
    context = _with_official_close(_context(), 6079)

    decision = evaluate_low_zone_episode(context)

    assert decision.episode == context.low_zone_episode
    assert decision.transition is None
    assert decision.signal_intent is None


def test_pressure_fixture_locks_minute_close_touch_boundaries_and_exclusions() -> None:
    fixture = _risk_fixture()["pressure"]

    for case in fixture["touchCases"]:
        context = _pressure_touch_context(
            tuple(case["minuteClosesFen"]),
            range_override=case.get("rangeOverride"),
        )

        decision = evaluate_pressure_reduction(context)

        expected_index = case["expectedTouchIndex"]
        expected_touch = (
            None
            if expected_index is None
            else context.current_bucket_minutes[expected_index].bar_end
        )
        assert decision.touch_evidence.touch_at == expected_touch, case["id"]
        assert decision.touch_evidence.outcome is (
            ConditionOutcome.UNSATISFIED if expected_touch is None else ConditionOutcome.SATISFIED
        ), case["id"]
        assert decision.signal_intent is None


def test_pressure_touch_ignores_pre_activation_minutes_but_includes_activation_boundary() -> None:
    context = _pressure_touch_context((6800, 6900, 6800, 6800, 6800))
    touch_minute = context.current_bucket_minutes[1]

    ignored = evaluate_pressure_reduction(
        context.model_copy(update={"activated_at": context.current_bucket_minutes[2].bar_end})
    )
    included = evaluate_pressure_reduction(
        context.model_copy(update={"activated_at": touch_minute.bar_end})
    )

    assert ignored.touch_evidence.outcome is ConditionOutcome.UNSATISFIED
    assert ignored.touch_evidence.touch_at is None
    assert included.touch_evidence.outcome is ConditionOutcome.SATISFIED
    assert included.touch_evidence.touch_at == touch_minute.bar_end


def test_pressure_touch_distinguishes_missing_history_from_known_no_touch() -> None:
    complete = _pressure_touch_context((6800, 6800, 6800, 6800, 6800))
    missing = _without_current_minutes(complete)

    known = evaluate_pressure_reduction(complete)
    unavailable = evaluate_pressure_reduction(missing)

    assert known.touch_evidence.outcome is ConditionOutcome.UNSATISFIED
    assert known.touch_evidence.missing_inputs == ()
    assert unavailable.touch_evidence.outcome is ConditionOutcome.MISSING_INPUT
    assert unavailable.touch_evidence.missing_inputs == (MissingInputCode.COMPLETE_MINUTE_BAR,)
    assert unavailable.signal_intent is None


def test_pressure_evaluation_is_intraday_only() -> None:
    context = _with_official_close(_context(), 6079)

    decision = evaluate_pressure_reduction(context)

    assert decision.touch_evidence.touch_at is None
    assert decision.reduction_evidence is None
    assert decision.signal_intent is None


@pytest.mark.parametrize(
    "pattern",
    ["upper_wick", "retreat", "volume_lower_half", "consecutive"],
)
def test_each_of_four_pressure_rejection_patterns_independently_creates_reduction(
    pattern: str,
) -> None:
    context = _pressure_pattern_context(pattern)

    decision = evaluate_pressure_reduction(context)

    assert decision.touch_evidence.outcome is ConditionOutcome.SATISFIED
    assert decision.reduction_evidence is not None
    assert decision.reduction_evidence.outcome is ConditionOutcome.SATISFIED
    assert decision.signal_intent is not None
    assert decision.signal_intent.signal_type is ActionableSignalType.PRESSURE_REDUCE_READY
    assert decision.signal_intent.quantity == 100
    assert decision.signal_intent.bucket == "TACTICAL"
    assert decision.signal_intent.target_lot_id == "lot-tactical-pressure"
    assert decision.signal_intent.matched_conditions == (decision.reduction_evidence,)


def test_pressure_evidence_contains_exactly_the_four_ordered_failure_alternatives() -> None:
    decision = evaluate_pressure_reduction(_pressure_pattern_context("upper_wick"))

    assert decision.reduction_evidence is not None
    alternatives = decision.reduction_evidence.children[2]
    assert isinstance(alternatives.condition, AnyCondition)
    assert tuple(type(child.condition) for child in alternatives.children) == (
        UpperWickRatioGteCondition,
        RetreatFromSessionHighGteCondition,
        AllCondition,
        ConsecutiveClosesBelowLevelCondition,
    )
    assert len(alternatives.children) == 4


def test_pressure_upper_wick_does_not_infer_a_fifth_common_reference_close_rule() -> None:
    context = _pressure_pattern_context("upper_wick")
    assert context.current_day_minutes[-1].close_fen > context.plan.levels.pressure_reference_fen

    decision = evaluate_pressure_reduction(context)

    assert decision.signal_intent is not None
    assert decision.signal_intent.signal_type is ActionableSignalType.PRESSURE_REDUCE_READY


def test_pressure_all_four_patterns_false_retains_evidence_without_signal() -> None:
    decision = evaluate_pressure_reduction(_pressure_pattern_context("none"))

    assert decision.reduction_evidence is not None
    alternatives = decision.reduction_evidence.children[2]
    assert alternatives.outcome is ConditionOutcome.UNSATISFIED
    assert all(child.outcome is ConditionOutcome.UNSATISFIED for child in alternatives.children)
    assert decision.signal_intent is None


@pytest.mark.parametrize(
    ("positions", "expected_signal"),
    [
        ((), False),
        ((_pressure_lot("lot-core", bucket="CORE"),), False),
        (
            (
                _pressure_lot(
                    "lot-tactical-today",
                    acquired_trade_date=TRADE_DATE,
                ),
            ),
            False,
        ),
        ((_pressure_lot("lot-tactical-sellable"),), True),
    ],
    ids=("no-position", "core-only", "tactical-t1-locked", "sellable-tactical"),
)
def test_pressure_reduction_never_targets_core_or_unsellable_tactical_inventory(
    positions: tuple[PositionLotSnapshot, ...],
    expected_signal: bool,
) -> None:
    context = _pressure_pattern_context("upper_wick").model_copy(update={"positions": positions})

    decision = evaluate_pressure_reduction(context)

    assert (decision.signal_intent is not None) is expected_signal
    if decision.signal_intent is not None:
        assert decision.signal_intent.target_lot_id == "lot-tactical-sellable"


def test_pressure_reduction_selects_newest_sellable_tactical_lot_deterministically() -> None:
    older = _pressure_lot(
        "lot-z-older",
        acquired_trade_date=date(2026, 8, 5),
    )
    newest_b = _pressure_lot("lot-b-newest")
    newest_a = _pressure_lot("lot-a-newest")
    base = _pressure_pattern_context("upper_wick")

    newest_date = evaluate_pressure_reduction(
        base.model_copy(update={"positions": (older, newest_b)})
    )
    same_date_tie = evaluate_pressure_reduction(
        base.model_copy(update={"positions": (newest_b, newest_a)})
    )

    assert newest_date.signal_intent is not None
    assert newest_date.signal_intent.target_lot_id == newest_b.lot_id
    assert same_date_tie.signal_intent is not None
    assert same_date_tie.signal_intent.target_lot_id == newest_a.lot_id


def test_pressure_replay_and_later_bucket_keep_one_touch_cause_identity() -> None:
    context = _pressure_pattern_context("upper_wick")

    first = evaluate_pressure_reduction(context)
    replay = evaluate_pressure_reduction(context)
    later_context = _replace_latest_bar(
        _append_intraday_bar(context, close_fen=6950, low_fen=6920),
        open_fen=6950,
        high_fen=6970,
        low_fen=6920,
        close_fen=6950,
    )
    later = evaluate_pressure_reduction(later_context)

    assert replay == first
    assert first.signal_intent is not None
    assert later.signal_intent is not None
    assert later.touch_evidence.touch_at == first.touch_evidence.touch_at
    assert later.signal_intent.cause_id == first.signal_intent.cause_id


def test_pressure_consecutive_pattern_counts_the_bar_containing_an_earlier_touch() -> None:
    decision = evaluate_pressure_reduction(_pressure_pattern_context("consecutive"))

    assert decision.reduction_evidence is not None
    evidence = _condition_evidence_of_type(
        decision.reduction_evidence,
        ConsecutiveClosesBelowLevelCondition,
    )
    assert evidence.outcome is ConditionOutcome.SATISFIED
    assert _facts(evidence)["pressure_touch_at"] < _facts(evidence)["bar_1_end"]
    assert _facts(evidence)["close_1_fen"] == 6905
    assert _facts(evidence)["close_2_fen"] == 6905


def test_pressure_consecutive_pattern_excludes_equal_end_and_prior_day_bars() -> None:
    context = _pressure_touch_context((6800, 6800, 6800, 6800, 6800)).model_copy(
        update={"positions": (_pressure_lot("lot-tactical-pressure"),)}
    )
    previous = context.complete_5m_bars[-2]
    previous_minutes = tuple(
        minute
        for minute in context.current_day_minutes
        if previous.bar_end - timedelta(minutes=4) <= minute.bar_end <= previous.bar_end
    )
    equal_end_updates = {
        minute.bar_end: {
            "open_fen": 6905 if minute is previous_minutes[-1] else 6800,
            "high_fen": 6905 if minute is previous_minutes[-1] else 6800,
            "low_fen": 6905 if minute is previous_minutes[-1] else 6800,
            "close_fen": 6905 if minute is previous_minutes[-1] else 6800,
        }
        for minute in previous_minutes
    }
    equal_end = _replace_minute_values(context, equal_end_updates)
    equal_end = _replace_completed_bar(
        equal_end,
        _flat_pressure_bar(equal_end.complete_5m_bars[-1].bar_end, 6905),
    )
    prior_day = _bar(
        datetime(2026, 8, 6, 15, 0, tzinfo=SHANGHAI),
        open_fen=6905,
        high_fen=6905,
        low_fen=6905,
        close_fen=6905,
    )
    with_prior = equal_end.model_copy(
        update={
            "complete_5m_bars": (prior_day, *equal_end.complete_5m_bars),
            "five_minute_indicators": _five_minute_indicators(
                (prior_day, *equal_end.complete_5m_bars)
            ),
            "trading_calendar": (
                TradingDay(
                    exchange="SZSE",
                    cal_date=PREVIOUS_TRADE_DATE,
                    is_open=True,
                    previous_trade_date=date(2026, 8, 5),
                ),
                *equal_end.trading_calendar,
            ),
        }
    )

    decision = evaluate_pressure_reduction(with_prior)

    assert decision.touch_evidence.touch_at == previous.bar_end
    assert decision.reduction_evidence is not None
    evidence = _condition_evidence_of_type(
        decision.reduction_evidence,
        ConsecutiveClosesBelowLevelCondition,
    )
    assert evidence.outcome is ConditionOutcome.MISSING_INPUT
    assert evidence.missing_inputs == (MissingInputCode.COMPLETE_5M_BAR_WINDOW,)
    assert decision.signal_intent is None


def test_pressure_consecutive_pattern_keeps_strict_reference_equality_unsatisfied() -> None:
    context = _pressure_pattern_context("consecutive")
    first = _replace_completed_bar(
        context,
        _flat_pressure_bar(context.complete_5m_bars[-2].bar_end, 6906),
    )
    equal = _replace_completed_bar(
        first,
        _flat_pressure_bar(context.complete_5m_bars[-1].bar_end, 6906),
    )

    decision = evaluate_pressure_reduction(equal)

    assert decision.reduction_evidence is not None
    evidence = _condition_evidence_of_type(
        decision.reduction_evidence,
        ConsecutiveClosesBelowLevelCondition,
    )
    assert evidence.outcome is ConditionOutcome.UNSATISFIED
    assert _facts(evidence)["consecutive_bars"] == 0
    assert decision.signal_intent is None


def test_pressure_consecutive_pattern_needs_the_complete_after_touch_window() -> None:
    context = _pressure_touch_context((6906, 6906, 6906, 6906, 6906)).model_copy(
        update={"positions": (_pressure_lot("lot-tactical-pressure"),)}
    )

    decision = evaluate_pressure_reduction(context)

    assert decision.touch_evidence.touch_at == context.current_bucket_minutes[0].bar_end
    assert decision.reduction_evidence is not None
    evidence = _condition_evidence_of_type(
        decision.reduction_evidence,
        ConsecutiveClosesBelowLevelCondition,
    )
    assert evidence.outcome is ConditionOutcome.MISSING_INPUT
    assert evidence.missing_inputs == (MissingInputCode.COMPLETE_5M_BAR_WINDOW,)
    assert decision.signal_intent is None


def test_pressure_missing_or_nonadjacent_history_fails_closed() -> None:
    context = _without_current_minutes(_pressure_pattern_context("consecutive"))

    decision = evaluate_pressure_reduction(context)

    assert decision.touch_evidence.outcome is ConditionOutcome.MISSING_INPUT
    assert decision.reduction_evidence is not None
    evidence = _condition_evidence_of_type(
        decision.reduction_evidence,
        ConsecutiveClosesBelowLevelCondition,
    )
    assert evidence.outcome is ConditionOutcome.MISSING_INPUT
    assert decision.signal_intent is None


def test_pressure_gapped_current_day_history_fails_closed() -> None:
    context = _pressure_pattern_context("consecutive")
    gapped = context.model_copy(
        update={
            "current_day_minutes": (
                *context.current_day_minutes[:5],
                *context.current_day_minutes[10:],
            ),
            "data_health": context.data_health.model_copy(
                update={
                    "status": DataHealthStatus.GAPPED,
                    "required_data_complete": False,
                    "fresh": False,
                }
            ),
        }
    )

    decision = evaluate_pressure_reduction(gapped)

    assert decision.touch_evidence.outcome is ConditionOutcome.MISSING_INPUT
    assert decision.touch_evidence.missing_inputs == (MissingInputCode.COMPLETE_MINUTE_BAR,)
    assert decision.reduction_evidence is not None
    evidence = _condition_evidence_of_type(
        decision.reduction_evidence,
        ConsecutiveClosesBelowLevelCondition,
    )
    assert evidence.outcome is ConditionOutcome.MISSING_INPUT
    assert decision.signal_intent is None


def test_intraday_and_provisional_1500_closes_never_advance_official_risk() -> None:
    intraday = _with_latest_price(_context(), 6079)
    provisional = _provisional_1500_risk_context(6079)

    intraday_decision = evaluate_official_close_risk(intraday)
    provisional_decision = evaluate_official_close_risk(provisional)

    for decision in (intraday_decision, provisional_decision):
        assert decision.risk.status is RiskStatus.CLEAR
        assert decision.transition is None
        assert decision.signal_type is None
        assert decision.signal_intent is None
        assert decision.risk_evidence.outcome is ConditionOutcome.MISSING_INPUT
        assert decision.risk_evidence.missing_inputs == (MissingInputCode.OFFICIAL_DAILY_CLOSE,)


@pytest.mark.parametrize(
    "context",
    [
        _official_risk_context(
            risk_status=RiskStatus.CLEAR,
            current_close_fen=6079,
        ),
        _official_risk_context(current_close_fen=6080),
    ],
    ids=("does-not-create-breach", "does-not-clear-existing-risk"),
)
def test_inactive_plan_never_advances_official_risk(context: EvaluationContext) -> None:
    inactive = context.model_copy(
        update={
            "plan_active": False,
            "activated_at": None,
        }
    )

    decision = evaluate_official_close_risk(inactive)

    assert decision.risk == inactive.risk_state
    assert decision.transition is None
    assert decision.signal_type is None
    assert decision.signal_intent is None


def test_official_risk_result_rejects_impossible_transition_and_display_shapes() -> None:
    breach = evaluate_official_close_risk(
        _official_risk_context(
            risk_status=RiskStatus.CLEAR,
            current_close_fen=6079,
        )
    )
    unchanged_active = evaluate_official_close_risk(
        _official_risk_context(
            current_close_fen=6070,
            positions=(),
        )
    )

    with pytest.raises(ValidationError, match="transition"):
        breach.model_copy(update={"transition": None})
    with pytest.raises(ValidationError, match="recovered|recovery|CLEAR"):
        unchanged_active.model_copy(update={"signal_type": SignalType.RISK_RECOVERED})


@pytest.mark.parametrize(
    ("close_fen", "expected_breach"),
    [(6080, False), (6079, True)],
    ids=("risk-line-equality", "one-fen-below"),
)
def test_first_official_risk_breach_uses_the_strict_one_fen_boundary(
    close_fen: int,
    expected_breach: bool,
) -> None:
    context = _official_risk_context(
        risk_status=RiskStatus.CLEAR,
        current_close_fen=close_fen,
    )

    decision = evaluate_official_close_risk(context)

    assert decision.risk_evidence.outcome is (
        ConditionOutcome.SATISFIED if expected_breach else ConditionOutcome.UNSATISFIED
    )
    assert (decision.transition is not None) is expected_breach
    assert (decision.signal_intent is not None) is expected_breach
    if not expected_breach:
        assert decision.risk == context.risk_state
        assert decision.signal_type is None
        return

    assert decision.risk.status is RiskStatus.BREACHED_PENDING_CONFIRMATION
    assert decision.risk.breach_trade_date == TRADE_DATE
    assert decision.risk.prior_close_fen == close_fen
    assert decision.risk.revision == 1
    assert decision.risk.updated_at == context.evaluated_at
    assert decision.transition is not None
    assert decision.transition.expected_revision == 0
    assert decision.transition.risk == decision.risk
    assert decision.signal_type is SignalType.RISK_BREACH
    assert decision.signal_intent is not None
    assert decision.signal_intent.signal_type is ActionableSignalType.RISK_BREACH
    assert decision.signal_intent.quantity is None
    assert decision.signal_intent.bucket is None
    assert decision.signal_intent.target_lot_id is None
    assert decision.signal_intent.next_step.code is NextStepCode.WAIT_FOR_NEXT_TRADING_DAY


def test_first_risk_breach_is_deterministic_and_has_one_transition_cause() -> None:
    context = _official_risk_context(
        risk_status=RiskStatus.CLEAR,
        current_close_fen=6079,
    )

    first = evaluate_official_close_risk(context)
    replay = evaluate_official_close_risk(context)

    assert replay == first
    assert first.signal_intent is not None
    assert first.signal_intent.cause_id.startswith("risk-")
    assert len(first.signal_intent.cause_id) == len("risk-") + 32


def test_distinct_risk_breach_dates_have_distinct_transition_causes() -> None:
    first_context = _official_risk_context(
        risk_status=RiskStatus.CLEAR,
        current_close_fen=6079,
    )
    later_context = _official_risk_context(
        target_date=date(2026, 8, 10),
        risk_status=RiskStatus.CLEAR,
        current_close_fen=6079,
        breach_trade_date=TRADE_DATE,
        previous_trade_date=TRADE_DATE,
    )

    first = evaluate_official_close_risk(first_context)
    later = evaluate_official_close_risk(later_context)

    assert first.signal_intent is not None
    assert later.signal_intent is not None
    assert first.signal_intent.cause_id != later.signal_intent.cause_id


def test_same_date_risk_causes_include_the_plan_identity() -> None:
    context = _official_risk_context(
        risk_status=RiskStatus.CLEAR,
        current_close_fen=6079,
    )
    alternate_plan = context.plan.model_copy(update={"version": context.plan.version + 1})
    alternate_hash = plan_sha256(alternate_plan)
    alternate = context.model_copy(
        update={
            "plan": alternate_plan,
            "plan_hash": alternate_hash,
            "risk_state": context.risk_state.model_copy(update={"plan_hash": alternate_hash}),
        }
    )

    first = evaluate_official_close_risk(context)
    second = evaluate_official_close_risk(alternate)

    assert first.signal_intent is not None
    assert second.signal_intent is not None
    assert first.signal_intent.trading_date == second.signal_intent.trading_date
    assert first.signal_intent.cause_id != second.signal_intent.cause_id


def test_missing_or_non_ready_official_reconciliation_fails_closed() -> None:
    official = _official_risk_context(
        risk_status=RiskStatus.CLEAR,
        current_close_fen=6079,
    )
    missing = official.model_copy(
        update={
            "close_reconciliation": None,
            "daily_indicator_snapshot": None,
        }
    )
    official_bar = official.close_reconciliation.official_bar
    assert official_bar is not None
    provisional = official_bar.model_copy(update={"is_official": False})
    pending_reconciliation = reconcile_daily_close(
        symbol=SYMBOL,
        current_trade_date=TRADE_DATE,
        daily_bars=(provisional,),
    )
    pending = official.model_copy(
        update={
            "close_reconciliation": pending_reconciliation,
            "daily_indicator_snapshot": None,
        }
    )

    for context in (missing, pending):
        decision = evaluate_official_close_risk(context)
        assert decision.risk_evidence.outcome is ConditionOutcome.MISSING_INPUT
        assert decision.transition is None
        assert decision.signal_intent is None


def test_official_recovery_at_the_risk_line_clears_without_an_actionable_alert() -> None:
    context = _official_risk_context(current_close_fen=6080)

    decision = evaluate_official_close_risk(context)

    assert decision.recovery_evidence is not None
    assert decision.recovery_evidence.outcome is ConditionOutcome.SATISFIED
    assert decision.risk.status is RiskStatus.CLEAR
    assert decision.risk.breach_trade_date is None
    assert decision.risk.prior_close_fen == 6080
    assert decision.risk.revision == context.risk_state.revision + 1
    assert decision.transition is not None
    assert decision.transition.expected_revision == context.risk_state.revision
    assert decision.signal_type is SignalType.RISK_RECOVERED
    assert decision.signal_intent is None
    assert SignalType.RISK_RECOVERED.value not in {item.value for item in ActionableSignalType}


def test_later_official_recovery_uses_the_original_breach_episode() -> None:
    later_date = date(2026, 8, 10)
    context = _official_risk_context(
        target_date=later_date,
        current_close_fen=6080,
        previous_trade_date=TRADE_DATE,
    )

    decision = evaluate_official_close_risk(context)

    assert context.trading_day.previous_trade_date != context.risk_state.breach_trade_date
    assert decision.risk.status is RiskStatus.CLEAR
    assert decision.signal_type is SignalType.RISK_RECOVERED
    assert decision.transition is not None


@pytest.mark.parametrize(
    "calendar_update",
    [
        (),
        (
            TradingDay(
                exchange="SZSE",
                cal_date=TRADE_DATE,
                is_open=False,
                previous_trade_date=PREVIOUS_TRADE_DATE,
            ),
        ),
    ],
    ids=("missing-calendar", "closed-calendar-row"),
)
def test_risk_recovery_requires_a_certified_open_target_day(
    calendar_update: tuple[TradingDay, ...],
) -> None:
    context = _official_risk_context(current_close_fen=6080).model_copy(
        update={"trading_calendar": calendar_update}
    )

    decision = evaluate_official_close_risk(context)

    assert decision.recovery_evidence is not None
    assert decision.recovery_evidence.outcome is ConditionOutcome.MISSING_INPUT
    assert decision.recovery_evidence.missing_inputs == (MissingInputCode.TRADING_CALENDAR,)
    assert decision.transition is None
    assert decision.signal_type is None
    assert decision.signal_intent is None


@pytest.mark.parametrize(
    (
        "current_close_fen",
        "current_volume_shares",
        "current_macd_histogram",
        "expected_outcome",
    ),
    [
        (6070, 9_000, -0.08, ConditionOutcome.SATISFIED),
        (6069, 8_999, -0.10, ConditionOutcome.SATISFIED),
        (6071, 9_000, -0.10, ConditionOutcome.UNSATISFIED),
        (6070, 8_999, -0.08, ConditionOutcome.UNSATISFIED),
    ],
    ids=(
        "equal-close-equal-volume",
        "lower-close-macd-not-improving",
        "higher-close",
        "lower-volume-improving-macd",
    ),
)
def test_risk_continued_deterioration_uses_exact_close_volume_or_macd_logic(
    current_close_fen: int,
    current_volume_shares: int,
    current_macd_histogram: float,
    expected_outcome: ConditionOutcome,
) -> None:
    context = _official_risk_context(
        current_close_fen=current_close_fen,
        current_volume_shares=current_volume_shares,
        current_macd_histogram=current_macd_histogram,
        positions=(),
    )

    decision = evaluate_official_close_risk(context)

    assert decision.deterioration_evidence is not None
    assert decision.deterioration_evidence.outcome is expected_outcome
    facts = _facts(decision.deterioration_evidence)
    assert facts["breach_close_fen"] == 6070
    assert facts["current_close_fen"] == current_close_fen
    assert facts["breach_volume_shares"] == 9_000
    assert facts["current_volume_shares"] == current_volume_shares
    assert facts["close_not_higher"] is (current_close_fen <= 6070)
    assert facts["volume_not_lower"] is (current_volume_shares >= 9_000)
    assert decision.signal_intent is None


def test_risk_deterioration_fails_closed_without_breach_day_history() -> None:
    context = _official_risk_context(
        current_close_fen=6070,
        current_volume_shares=8_999,
        include_breach_bar=False,
        include_daily_indicators=False,
        positions=(_pressure_lot("lot-core", bucket="CORE"),),
    )

    decision = evaluate_official_close_risk(context)

    assert decision.deterioration_evidence is not None
    assert decision.deterioration_evidence.outcome is ConditionOutcome.MISSING_INPUT
    assert MissingInputCode.OFFICIAL_DAILY_CLOSE in (decision.deterioration_evidence.missing_inputs)
    assert decision.signal_intent is None


def test_risk_deterioration_rejects_a_non_breaching_original_baseline() -> None:
    context = _official_risk_context(
        current_close_fen=6070,
        breach_close_fen=6080,
        positions=(_pressure_lot("lot-core", bucket="CORE"),),
    )

    decision = evaluate_official_close_risk(context)

    assert decision.deterioration_evidence is not None
    assert decision.deterioration_evidence.outcome is ConditionOutcome.MISSING_INPUT
    assert decision.deterioration_evidence.missing_inputs == (
        MissingInputCode.OFFICIAL_DAILY_CLOSE,
    )
    assert decision.transition is None
    assert decision.signal_intent is None


@pytest.mark.parametrize(
    ("current_volume_shares", "expected_outcome"),
    [
        (9_000, ConditionOutcome.SATISFIED),
        (8_999, ConditionOutcome.MISSING_INPUT),
    ],
    ids=("volume-proves-deterioration", "missing-macd-blocks-false-volume"),
)
def test_risk_volume_or_macd_short_circuit_is_fail_closed(
    current_volume_shares: int,
    expected_outcome: ConditionOutcome,
) -> None:
    context = _official_risk_context(
        current_close_fen=6070,
        current_volume_shares=current_volume_shares,
        include_daily_indicators=False,
    )

    decision = evaluate_official_close_risk(context)

    assert decision.deterioration_evidence is not None
    assert decision.deterioration_evidence.outcome is expected_outcome


def test_risk_no_deterioration_retains_breach_for_a_later_official_day() -> None:
    no_deterioration = _official_risk_context(
        current_close_fen=6070,
        current_volume_shares=8_999,
        current_macd_histogram=-0.08,
    )

    held = evaluate_official_close_risk(no_deterioration)

    assert held.risk == no_deterioration.risk_state
    assert held.transition is None
    assert held.signal_intent is None

    later = _official_risk_context(
        target_date=date(2026, 8, 10),
        current_close_fen=6069,
        current_volume_shares=9_000,
        previous_trade_date=TRADE_DATE,
        positions=(_pressure_lot("lot-core", bucket="CORE"),),
    )
    exited = evaluate_official_close_risk(later)

    assert exited.deterioration_evidence is not None
    assert exited.deterioration_evidence.outcome is ConditionOutcome.SATISFIED
    assert exited.signal_intent is not None
    assert exited.signal_intent.signal_type is ActionableSignalType.RISK_EXIT_READY


def test_later_risk_macd_deterioration_uses_the_original_breach_day() -> None:
    intermediate_date = date(2026, 8, 10)
    target_date = date(2026, 8, 11)
    context = _official_risk_context(
        target_date=target_date,
        current_close_fen=6070,
        current_volume_shares=8_999,
        current_macd_histogram=-0.08,
        breach_macd_histogram=-0.10,
        previous_trade_date=intermediate_date,
        positions=(_pressure_lot("lot-core", bucket="CORE"),),
    )
    intermediate_bar = DailyBar(
        symbol=SYMBOL,
        trade_date=intermediate_date,
        open_fen=6070,
        high_fen=6090,
        low_fen=6050,
        close_fen=6070,
        volume_shares=8_999,
        amount_yuan=Decimal(8_999),
        is_official=True,
        received_at=datetime(2026, 8, 10, 15, 30, tzinfo=SHANGHAI),
    )
    snapshot = context.daily_indicator_snapshot
    assert snapshot is not None
    with_intermediate = context.model_copy(
        update={
            "official_daily_bars": (*context.official_daily_bars, intermediate_bar),
            "daily_indicator_snapshot": snapshot.model_copy(
                update={
                    "series": snapshot.series.model_copy(
                        update={
                            "points": (
                                snapshot.series.points[0],
                                _point(
                                    intermediate_date,
                                    macd_histogram_yuan=-0.05,
                                ),
                                snapshot.series.points[-1],
                            )
                        }
                    )
                }
            ),
        }
    )

    decision = evaluate_official_close_risk(with_intermediate)

    assert decision.deterioration_evidence is not None
    assert decision.deterioration_evidence.outcome is ConditionOutcome.UNSATISFIED
    assert _facts(decision.deterioration_evidence)["breach_macd_histogram_yuan"] == Decimal("-0.1")
    assert decision.signal_intent is None


def test_risk_exit_prefers_tactical_before_newer_core_and_then_newest_tactical() -> None:
    tactical_old = _pressure_lot(
        "lot-tactical-old",
        acquired_trade_date=date(2026, 8, 5),
    )
    tactical_new_b = _pressure_lot("lot-tactical-b")
    tactical_new_a = _pressure_lot("lot-tactical-a")
    core = _pressure_lot("lot-core-newer", bucket="CORE")

    tactical_over_core = evaluate_official_close_risk(
        _official_risk_context(
            positions=(core, tactical_old),
        )
    )
    newest_tactical = evaluate_official_close_risk(
        _official_risk_context(
            positions=(tactical_old, tactical_new_b),
        )
    )
    same_date_tie = evaluate_official_close_risk(
        _official_risk_context(
            positions=(tactical_new_b, tactical_new_a),
        )
    )

    assert tactical_over_core.signal_intent is not None
    assert tactical_over_core.signal_intent.target_lot_id == tactical_old.lot_id
    assert newest_tactical.signal_intent is not None
    assert newest_tactical.signal_intent.target_lot_id == tactical_new_b.lot_id
    assert same_date_tie.signal_intent is not None
    assert same_date_tie.signal_intent.target_lot_id == tactical_new_a.lot_id


def test_risk_exit_uses_core_only_when_no_tactical_target_exists() -> None:
    context = _official_risk_context(
        positions=(_pressure_lot("lot-core", bucket="CORE"),),
    )

    decision = evaluate_official_close_risk(context)

    assert decision.signal_intent is not None
    assert decision.signal_intent.signal_type is ActionableSignalType.RISK_EXIT_READY
    assert decision.signal_intent.bucket == "CORE"
    assert decision.signal_intent.target_lot_id == "lot-core"
    assert decision.signal_intent.quantity == 100
    assert decision.signal_intent.next_step.code is NextStepCode.RECORD_CONFIRMED_FILL


def test_risk_fixture_locks_the_breach_baseline_and_exit_quantity() -> None:
    fixture = _risk_fixture()["risk"]
    breach_date = date.fromisoformat(fixture["breachDate"])
    confirmation_date = date.fromisoformat(fixture["confirmationDate"])
    context = _official_risk_context(
        target_date=confirmation_date,
        current_close_fen=fixture["breachCloseFen"],
        breach_trade_date=breach_date,
        breach_close_fen=fixture["breachCloseFen"],
        previous_trade_date=breach_date,
        positions=(_pressure_lot("lot-core-fixture", bucket="CORE"),),
    )

    decision = evaluate_official_close_risk(context)

    assert context.plan.levels.risk_line_fen == fixture["lineFen"]
    assert context.risk_state.breach_trade_date == breach_date
    assert decision.signal_intent is not None
    assert decision.signal_intent.signal_type is ActionableSignalType.RISK_EXIT_READY
    assert decision.signal_intent.quantity == fixture["exitQuantity"]


def test_risk_exit_with_no_position_retains_deterioration_evidence_only() -> None:
    decision = evaluate_official_close_risk(_official_risk_context(positions=()))

    assert decision.deterioration_evidence is not None
    assert decision.deterioration_evidence.outcome is ConditionOutcome.SATISFIED
    assert decision.transition is None
    assert decision.signal_intent is None


def test_risk_t1_locked_tactical_target_waits_without_substituting_sellable_core() -> None:
    locked_tactical = _pressure_lot(
        "lot-tactical-locked",
        acquired_trade_date=TRADE_DATE,
    )
    sellable_core = _pressure_lot("lot-core-sellable", bucket="CORE")
    context = _official_risk_context(
        positions=(sellable_core, locked_tactical),
    )

    decision = evaluate_official_close_risk(context)

    assert decision.risk.status is RiskStatus.EXIT_PENDING_SETTLEMENT
    assert decision.risk.breach_trade_date == PREVIOUS_TRADE_DATE
    assert decision.risk.prior_close_fen == 6070
    assert decision.risk.revision == context.risk_state.revision + 1
    assert decision.transition is not None
    assert decision.transition.expected_revision == context.risk_state.revision
    assert decision.signal_type is SignalType.RISK_EXIT_PENDING_SETTLEMENT
    assert decision.signal_intent is not None
    assert decision.signal_intent.signal_type is ActionableSignalType.RISK_EXIT_PENDING_SETTLEMENT
    assert decision.signal_intent.bucket == "TACTICAL"
    assert decision.signal_intent.target_lot_id == locked_tactical.lot_id
    assert decision.signal_intent.next_step.code is NextStepCode.WAIT_FOR_SETTLEMENT


def test_pending_risk_becomes_ready_on_a_later_open_day_with_the_same_cause() -> None:
    locked = _pressure_lot(
        "lot-tactical-locked",
        acquired_trade_date=TRADE_DATE,
    )
    pending_context = _official_risk_context(positions=(locked,))
    pending = evaluate_official_close_risk(pending_context)
    assert pending.signal_intent is not None

    later_context = _official_risk_context(
        target_date=date(2026, 8, 10),
        previous_trade_date=TRADE_DATE,
        positions=(locked,),
    ).model_copy(update={"risk_state": pending.risk})
    ready = evaluate_official_close_risk(later_context)

    assert later_context.risk_state == pending.risk
    assert ready.risk == pending.risk
    assert ready.transition is None
    assert ready.signal_type is SignalType.RISK_EXIT_READY
    assert ready.signal_intent is not None
    assert ready.signal_intent.signal_type is ActionableSignalType.RISK_EXIT_READY
    assert ready.signal_intent.target_lot_id == locked.lot_id
    assert ready.signal_intent.cause_id == pending.signal_intent.cause_id


@pytest.mark.parametrize(
    "current_close_fen",
    [6070, 6080],
    ids=("does-not-become-ready", "does-not-recover"),
)
def test_pending_risk_does_not_resolve_on_its_own_transition_day(
    current_close_fen: int,
) -> None:
    sellable = _pressure_lot("lot-tactical-sellable")
    context = _official_risk_context(
        current_close_fen=current_close_fen,
        risk_status=RiskStatus.EXIT_PENDING_SETTLEMENT,
        positions=(sellable,),
    )
    same_day_pending = context.risk_state.model_copy(
        update={"updated_at": datetime(2026, 8, 7, 15, 0, tzinfo=SHANGHAI)}
    )

    decision = evaluate_official_close_risk(
        context.model_copy(update={"risk_state": same_day_pending})
    )

    assert decision.risk == same_day_pending
    assert decision.transition is None
    assert decision.signal_type is None
    assert decision.signal_intent is None


def test_pending_risk_can_recover_on_a_later_official_close() -> None:
    context = _official_risk_context(
        target_date=date(2026, 8, 10),
        current_close_fen=6080,
        previous_trade_date=TRADE_DATE,
        risk_status=RiskStatus.EXIT_PENDING_SETTLEMENT,
        positions=(
            _pressure_lot(
                "lot-tactical-prior-pending",
                acquired_trade_date=TRADE_DATE,
            ),
        ),
    )

    decision = evaluate_official_close_risk(context)

    assert decision.risk.status is RiskStatus.CLEAR
    assert decision.transition is not None
    assert decision.signal_type is SignalType.RISK_RECOVERED
    assert decision.signal_intent is None


def test_risk_signal_replay_is_byte_stable_without_repository_or_clock_access() -> None:
    context = _official_risk_context(
        positions=(_pressure_lot("lot-core", bucket="CORE"),),
    )

    first = evaluate_official_close_risk(context)
    replay = evaluate_official_close_risk(context)

    assert replay == first
    assert first.signal_intent is not None
    assert first.signal_intent.cause_id.startswith("risk-")


def test_engine_evaluate_is_pure_closed_and_returns_canonical_self_hashed_json() -> None:
    context = _context()
    before = context.model_dump_json(round_trip=True)

    first = evaluate(context)
    replay = evaluate(context)
    first_json = canonical_result_json(first)
    replay_json = canonical_result_json(replay)

    assert first.snapshot.signal_type is SignalType.BUY_CORE_READY
    assert first == replay
    assert first_json == replay_json
    assert first.result_hash == ("8f41e2c81e99bcb4d6ca1cccfc7f4a2a31f88c7140c9cbbf69c8f31318da200e")
    assert context.model_dump_json(round_trip=True) == before
    document = json.loads(first_json)
    result_hash = document.pop("result_hash")
    payload_json = json.dumps(
        document,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert result_hash == sha256(b"decision-result-v1\0" + payload_json.encode("utf-8")).hexdigest()
    restored = EvaluationResult.model_validate_json(first_json)
    assert canonical_result_json(restored) == first_json
    with pytest.raises(TypeError, match="EvaluationContext"):
        evaluate(context.model_dump(mode="python"))
    with pytest.raises(TypeError, match="EvaluationResult"):
        canonical_result_json(first.model_dump(mode="python"))


def test_engine_inactive_plan_waits_with_explicit_evidence_and_no_intents() -> None:
    context = _context().model_copy(update={"plan_active": False, "activated_at": None})

    result = evaluate(context)

    assert result.snapshot.signal_type is SignalType.WAIT
    assert result.signal_intent is None
    assert result.transitions == ()
    assert result.next_step.code is NextStepCode.REVIEW_BLOCKER
    inactive = _rule_evidence(result, RuleEvidenceCode.PLAN_INACTIVE)
    assert inactive.outcome is ConditionOutcome.UNSATISFIED
    assert result.blockers == (inactive,)


def test_target_global_stale_data_suppresses_pressure_and_episode_progress() -> None:
    context = _pressure_pattern_context("upper_wick")
    pressure = evaluate_pressure_reduction(context)
    assert pressure.signal_intent is not None
    original_episode = context.low_zone_episode
    stale = context.model_copy(
        update={
            "data_health": context.data_health.model_copy(
                update={"status": DataHealthStatus.STALE, "fresh": False}
            )
        }
    )

    result = evaluate(stale)

    assert result.snapshot.signal_type is SignalType.BLOCKED_DATA
    assert result.signal_intent is None
    assert result.transitions == ()
    assert result.snapshot.episode == original_episode
    assert result.next_step.code is NextStepCode.WAIT_FOR_REQUIRED_DATA
    blocker = _rule_evidence(result, RuleEvidenceCode.DATA_NOT_READY)
    assert blocker.outcome is ConditionOutcome.UNSATISFIED
    assert {fact.key: fact.value for fact in blocker.facts} == {
        "data_health_status": "STALE",
        "required_data_complete": True,
        "fresh": False,
        "trading_day_present": True,
        "trading_day_open": True,
        "minute_history_complete": True,
        "target_bar_present": True,
    }
    assert _rule_evidence(result, RuleEvidenceCode.PRESSURE_TOUCH).outcome is (
        ConditionOutcome.SATISFIED
    )
    assert pressure.reduction_evidence in result.satisfied_conditions


def test_target_global_missing_minutes_returns_blocked_data_without_a_price() -> None:
    context = _without_current_minutes(_context())

    result = evaluate(context)

    assert result.snapshot.signal_type is SignalType.BLOCKED_DATA
    assert result.snapshot.market_data_at is None
    assert result.snapshot.price_fen is None
    assert result.transitions == ()
    blocker = _rule_evidence(result, RuleEvidenceCode.DATA_NOT_READY)
    assert blocker.outcome is ConditionOutcome.MISSING_INPUT
    assert MissingInputCode.COMPLETE_MINUTE_BAR in blocker.missing_inputs
    assert MissingInputCode.COMPLETE_MINUTE_BAR in result.next_step.required_inputs


@pytest.mark.parametrize(
    ("transform", "expected_signal", "expected_code"),
    [
        (
            lambda context: context.model_copy(update={"daily_limit": None}),
            SignalType.BLOCKED_DATA,
            RuleEvidenceCode.DAILY_LIMIT_UNKNOWN,
        ),
        (
            _with_breached_risk,
            SignalType.BLOCKED_RISK,
            RuleEvidenceCode.RISK_PENDING,
        ),
    ],
    ids=("missing-daily-limit", "pending-risk"),
)
def test_engine_maps_structural_entry_blockers_without_losing_source_facts(
    transform: ContextTransform,
    expected_signal: SignalType,
    expected_code: RuleEvidenceCode,
) -> None:
    context = transform(_context())
    source = evaluate_low_zone_episode(context)
    assert len(source.structural_blockers) == 1

    result = evaluate(context)

    assert result.snapshot.signal_type is expected_signal
    assert result.signal_intent is None
    assert len(result.transitions) == 1
    mapped = _rule_evidence(result, expected_code)
    structural = source.structural_blockers[0]
    assert mapped.outcome is structural.outcome
    assert mapped.facts == structural.facts
    assert mapped.missing_inputs == structural.missing_inputs
    assert mapped in result.blockers


@pytest.mark.parametrize("manual_event_risk", [True, None])
def test_engine_maps_known_and_missing_dsl_entry_blockers_by_outcome(
    manual_event_risk: bool | None,
) -> None:
    result = evaluate(_context().model_copy(update={"manual_event_risk": manual_event_risk}))

    expected_signal = (
        SignalType.BLOCKED_RISK if manual_event_risk is True else SignalType.BLOCKED_DATA
    )
    assert result.snapshot.signal_type is expected_signal
    assert result.signal_intent is None
    assert any(
        isinstance(evidence, ConditionEvidence)
        and evidence.condition.type == "ALL"
        and evidence.outcome
        is (
            ConditionOutcome.UNSATISFIED
            if manual_event_risk is True
            else ConditionOutcome.MISSING_INPUT
        )
        for evidence in result.blockers
    )


def test_satisfied_any_remains_actionable_when_an_alternative_is_missing() -> None:
    condition = _condition(
        {
            "type": "ANY",
            "conditions": [
                {"type": "PRICE_IN_ZONE", "zone": "LOW_BUY"},
                {"type": "OFFICIAL_CLOSE_BELOW_LEVEL", "level": "RISK_LINE"},
            ],
        }
    )
    context = _with_entry_condition(_context(), condition)
    source = evaluate_low_zone_episode(context)
    entry = source.entry_evidence
    assert entry is not None
    assert entry.outcome is ConditionOutcome.SATISFIED
    assert tuple(child.outcome for child in entry.children) == (
        ConditionOutcome.SATISFIED,
        ConditionOutcome.MISSING_INPUT,
    )
    assert source.signal_intent is not None

    result = evaluate(context)

    assert result.snapshot.signal_type is SignalType.BUY_CORE_READY
    assert result.signal_intent == source.signal_intent
    assert result.next_step.code is NextStepCode.RECORD_CONFIRMED_FILL
    assert result.next_step.required_inputs == ()


def test_nested_missing_entry_input_wins_over_known_risk_failure() -> None:
    context = _context()
    indicators = context.five_minute_indicators
    assert indicators is not None
    points = (
        *indicators.points[:-2],
        indicators.points[-2].model_copy(update={"boll_lower_yuan": None}),
        indicators.points[-1],
    )
    context = context.model_copy(
        update={
            "manual_event_risk": True,
            "five_minute_indicators": indicators.model_copy(update={"points": points}),
        }
    )
    source = evaluate_low_zone_episode(context)
    blocker = source.blocker_evidence
    assert blocker is not None
    assert blocker.outcome is ConditionOutcome.UNSATISFIED
    assert any(
        child.outcome is ConditionOutcome.MISSING_INPUT
        and child.missing_inputs == (MissingInputCode.INDICATOR_VALUE,)
        for child in blocker.children
    )

    result = evaluate(context)

    assert result.snapshot.signal_type is SignalType.BLOCKED_DATA
    assert blocker in result.blockers
    assert result.next_step.code is NextStepCode.WAIT_FOR_REQUIRED_DATA
    assert result.next_step.required_inputs == (MissingInputCode.INDICATOR_VALUE,)


def test_pressure_action_wins_while_retaining_real_episode_progress_and_evidence() -> None:
    context = _pressure_pattern_context("upper_wick")
    episode = evaluate_low_zone_episode(context)
    pressure = evaluate_pressure_reduction(context)
    assert episode.episode is not None
    assert episode.episode.status is EpisodeStatus.ACTIVE
    assert episode.transition is not None
    assert pressure.signal_intent is not None

    result = evaluate(context)

    assert result.snapshot.signal_type is SignalType.PRESSURE_REDUCE_READY
    assert result.signal_intent == pressure.signal_intent
    assert result.next_step.code is NextStepCode.RECORD_CONFIRMED_FILL
    assert result.snapshot.episode == episode.episode
    assert result.transitions == (episode.transition,)
    touch = _rule_evidence(result, RuleEvidenceCode.PRESSURE_TOUCH)
    assert touch.outcome is pressure.touch_evidence.outcome
    assert touch.facts == pressure.touch_evidence.facts
    assert touch.missing_inputs == pressure.touch_evidence.missing_inputs
    assert pressure.reduction_evidence in result.satisfied_conditions
    assert episode.entry_evidence in result.unmet_conditions
    assert episode.blocker_evidence in result.satisfied_conditions
    assert episode.availability_evidence in result.satisfied_conditions


def test_pressure_suppresses_a_ready_buy_without_consuming_its_alerted_state() -> None:
    base = _pressure_pattern_context("upper_wick")
    context = _with_entry_condition(base, base.plan.blockers.condition)
    episode = evaluate_low_zone_episode(context)
    pressure = evaluate_pressure_reduction(context)
    assert episode.signal_intent is not None
    assert episode.episode is not None
    assert episode.episode.status is EpisodeStatus.ALERTED
    assert pressure.signal_intent is not None

    result = evaluate(context)

    assert result.snapshot.signal_type is SignalType.PRESSURE_REDUCE_READY
    assert result.signal_intent == pressure.signal_intent
    assert result.snapshot.episode is not None
    assert result.snapshot.episode.status is EpisodeStatus.ACTIVE
    assert result.snapshot.episode.alerted_signal is None
    assert result.snapshot.episode.episode_low_fen == episode.episode.episode_low_fen
    assert result.snapshot.episode.bars_since_low == episode.episode.bars_since_low
    assert (
        result.snapshot.episode.last_processed_bucket_end
        == episode.episode.last_processed_bucket_end
        == context.target.bucket_end
    )
    assert len(result.transitions) == 1
    transition = result.transitions[0]
    assert isinstance(transition, EpisodeTransitionIntent)
    assert transition.episode == result.snapshot.episode
    assert episode.signal_intent.matched_conditions[0] in result.satisfied_conditions


@pytest.mark.parametrize(
    ("transform", "expected_code"),
    [
        (
            lambda context: context.model_copy(update={"daily_limit": None}),
            RuleEvidenceCode.DAILY_LIMIT_UNKNOWN,
        ),
        (_with_breached_risk, RuleEvidenceCode.RISK_PENDING),
    ],
    ids=("entry-data-blocker", "entry-risk-blocker"),
)
def test_entry_only_blockers_do_not_suppress_pressure_reduction(
    transform: ContextTransform,
    expected_code: RuleEvidenceCode,
) -> None:
    context = transform(_pressure_pattern_context("upper_wick"))

    result = evaluate(context)

    assert result.snapshot.signal_type is SignalType.PRESSURE_REDUCE_READY
    assert result.signal_intent is not None
    assert result.signal_intent.blockers == ()
    assert _rule_evidence(result, expected_code) in result.blockers


def test_engine_returns_low_zone_pressure_and_neutral_observation_states() -> None:
    low_watch = evaluate(_touch_context((6500, 6500, 6300, 6400, 6400)))
    pressure_context = _pressure_pattern_context("upper_wick").model_copy(update={"positions": ()})
    pressure_watch = evaluate(pressure_context)
    neutral = evaluate(_touch_context((6500, 6500, 6500, 6500, 6500)))

    assert low_watch.snapshot.signal_type is SignalType.LOW_ZONE_WATCH
    assert low_watch.signal_intent is None
    assert low_watch.snapshot.episode is not None
    assert low_watch.next_step.code is NextStepCode.WATCH_LOW_ZONE
    assert pressure_watch.snapshot.signal_type is SignalType.WAIT
    assert pressure_watch.snapshot.zone is DecisionZone.PRESSURE
    assert pressure_watch.next_step.code is NextStepCode.WATCH_PRESSURE
    assert (
        _rule_evidence(
            pressure_watch,
            RuleEvidenceCode.PRESSURE_TOUCH,
        ).outcome
        is ConditionOutcome.SATISFIED
    )
    assert neutral.snapshot.signal_type is SignalType.WAIT
    assert neutral.snapshot.zone is DecisionZone.OBSERVATION
    assert neutral.next_step.code is NextStepCode.WAIT_FOR_COMPLETE_BAR


@pytest.mark.parametrize(
    ("price_fen", "expected_zone"),
    [
        (6079, DecisionZone.BELOW_RISK),
        (6450, DecisionZone.LOW_BUY),
        (6451, DecisionZone.OBSERVATION),
        (6879, DecisionZone.OBSERVATION),
        (6880, DecisionZone.PRESSURE),
        (7020, DecisionZone.PRESSURE),
        (7021, DecisionZone.OUTSIDE),
    ],
)
def test_engine_uses_integer_fen_zone_ownership_boundaries(
    price_fen: int,
    expected_zone: DecisionZone,
) -> None:
    context = _touch_context((price_fen,) * 5)

    assert evaluate(context).snapshot.zone is expected_zone


def test_official_risk_is_applicable_despite_intraday_close_pending_health() -> None:
    context = _official_risk_context(
        risk_status=RiskStatus.CLEAR,
        current_close_fen=6079,
    )
    source = evaluate_official_close_risk(context)
    assert context.data_health.status is DataHealthStatus.CLOSE_PENDING
    assert source.signal_intent is not None

    result = evaluate(context)

    assert result.snapshot.signal_type is SignalType.RISK_BREACH
    assert result.signal_intent == source.signal_intent
    assert result.snapshot.market_data_at == datetime(2026, 8, 7, 15, 0, tzinfo=SHANGHAI)
    assert result.snapshot.price_fen == 6079
    assert result.transitions == (source.transition,)
    assert not any(
        isinstance(evidence, RuleEvidence) and evidence.code is RuleEvidenceCode.PRESSURE_TOUCH
        for evidence in result.snapshot.condition_evidence
    )


def test_official_recovery_and_deterioration_rule_evidence_are_preserved() -> None:
    recovery_context = _official_risk_context(current_close_fen=6080)
    recovery_source = evaluate_official_close_risk(recovery_context)
    recovery = evaluate(recovery_context)
    exit_context = _official_risk_context(
        positions=(_pressure_lot("lot-core-exit", bucket="CORE"),)
    )
    exit_source = evaluate_official_close_risk(exit_context)
    exited = evaluate(exit_context)

    assert recovery.snapshot.signal_type is SignalType.RISK_RECOVERED
    assert recovery.signal_intent is None
    assert recovery.transitions == (recovery_source.transition,)
    recovery_rule = _rule_evidence(recovery, RuleEvidenceCode.RISK_RECOVERY)
    assert recovery_source.recovery_evidence is not None
    assert recovery_rule.outcome is recovery_source.recovery_evidence.outcome
    assert recovery_rule.facts == recovery_source.recovery_evidence.facts
    assert recovery_rule.missing_inputs == recovery_source.recovery_evidence.missing_inputs
    assert exited.snapshot.signal_type is SignalType.RISK_EXIT_READY
    deterioration = _rule_evidence(exited, RuleEvidenceCode.RISK_DETERIORATION)
    assert exit_source.deterioration_evidence is not None
    assert deterioration.outcome is exit_source.deterioration_evidence.outcome
    assert deterioration.facts == exit_source.deterioration_evidence.facts
    assert deterioration.missing_inputs == exit_source.deterioration_evidence.missing_inputs


def test_missing_official_close_blocks_only_the_official_target() -> None:
    ready = _official_risk_context(
        risk_status=RiskStatus.CLEAR,
        current_close_fen=6079,
    )
    missing = ready.model_copy(
        update={"close_reconciliation": None, "daily_indicator_snapshot": None}
    )

    result = evaluate(missing)

    assert result.snapshot.signal_type is SignalType.BLOCKED_DATA
    assert result.snapshot.market_data_at is None
    assert result.snapshot.price_fen is None
    assert result.signal_intent is None
    assert result.transitions == ()
    assert result.next_step.code is NextStepCode.WAIT_FOR_OFFICIAL_CLOSE
    assert MissingInputCode.OFFICIAL_DAILY_CLOSE in result.next_step.required_inputs


def test_provisional_1500_close_never_runs_official_risk_or_adds_artificial_blockers() -> None:
    context = _provisional_1500_risk_context(6079)
    risk_before = context.risk_state

    result = evaluate(context)

    assert isinstance(result.evaluation_identity, IntradayEvaluationIdentity)
    assert result.snapshot.risk == risk_before
    assert all(not isinstance(item, RiskTransitionIntent) for item in result.transitions)
    assert result.snapshot.signal_type not in {
        SignalType.RISK_BREACH,
        SignalType.RISK_RECOVERED,
        SignalType.RISK_EXIT_READY,
        SignalType.RISK_EXIT_PENDING_SETTLEMENT,
    }
    assert all(
        MissingInputCode.OFFICIAL_DAILY_CLOSE not in evidence.missing_inputs
        for evidence in result.snapshot.condition_evidence
    )


def test_intraday_1500_and_official_close_keep_distinct_identity_kinds() -> None:
    intraday = evaluate(_provisional_1500_risk_context(6079))
    official = evaluate(
        _official_risk_context(
            risk_status=RiskStatus.CLEAR,
            current_close_fen=6079,
        )
    )

    assert isinstance(intraday.evaluation_identity, IntradayEvaluationIdentity)
    assert isinstance(official.evaluation_identity, OfficialCloseEvaluationIdentity)
    assert intraday.evaluation_identity != official.evaluation_identity
    assert intraday.result_hash != official.result_hash
