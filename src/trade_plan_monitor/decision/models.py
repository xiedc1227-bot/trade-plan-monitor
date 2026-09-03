"""Immutable inputs, evidence, snapshots, and intents for pure decisions."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum, StrEnum
from hashlib import sha256
from itertools import pairwise
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import (
    AllCondition,
    AnyCondition,
    ConditionNode,
    PositionBucket,
    TradePlan,
)
from trade_plan_monitor.domain.plan_validation import (
    ALL_MARKET_EVIDENCE,
    validate_trade_plan,
)
from trade_plan_monitor.market_data.aggregation import (
    FiveMinuteBar,
    aggregate_five_minute_bar,
    expected_five_minute_ends,
    five_minute_bucket_end,
)
from trade_plan_monitor.market_data.indicators import IndicatorSeries
from trade_plan_monitor.market_data.models import (
    AShareSymbol,
    DailyBar,
    DailyLimit,
    MinuteBar,
    ShanghaiDatetime,
    TradingDay,
)
from trade_plan_monitor.market_data.reconciliation import CloseReconciliationIntent
from trade_plan_monitor.market_index.canonical import validate_market_index_snapshot_integrity
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.models import (
    MarketIndexFactUnit,
    MarketIndexHealth,
    MarketIndexSnapshot,
)

Sha256Hex = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$"),
]
StableIdentifier = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
PersistedIdentifier = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=36,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
EvidenceKey = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    ),
]
EvidenceCode = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Z][A-Z0-9_]*$",
    ),
]
PositiveFen = Annotated[int, Field(strict=True, gt=0)]
NonNegativeInteger = Annotated[int, Field(strict=True, ge=0)]
NonNegativeBoardLot = Annotated[int, Field(strict=True, ge=0, multiple_of=100)]
PositiveBoardLot = Annotated[int, Field(strict=True, gt=0, multiple_of=100)]
PositiveVersion = Annotated[int, Field(strict=True, gt=0)]
StrictBoolean = Annotated[bool, Field(strict=True)]
FiniteDecimal = Annotated[Decimal, Field(strict=True, allow_inf_nan=False)]
EvidenceScalar = bool | int | Decimal | datetime | date | EvidenceCode
IndexPlanPath = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=15,
        max_length=256,
        pattern=(
            r"^(?:entry|reduction|risk|blockers)\.condition"
            r"(?:\.conditions\[[0-9]+\])*$"
        ),
    ),
]
IndexConditionType = Literal[
    "INDEX_CLOSE_GTE_MA",
    "INDEX_CLOSE_LTE_MA",
    "INDEX_MA_NON_DECREASING",
    "INDEX_MA_NON_INCREASING",
    "INDEX_RETURN_GTE",
    "INDEX_RETURN_LTE",
]
_MAX_MARKET_BARS = 10_000
_MAX_DAILY_BARS = 500
_MAX_CURRENT_DAY_MINUTES = 240
_MAX_TRADING_DAYS = 512
_MAX_POSITION_LOTS = 200
_MAX_EVIDENCE_FACTS = 512
_MAX_CONDITION_VALUES = 50
_MAX_MISSING_INPUTS = 16
_MAX_CANONICAL_DECIMAL_DIGITS = 10_000
_RESULT_HASH_DOMAIN = b"decision-result-v1\0"
_STRUCTURAL_RULE_EVIDENCE_CODES = frozenset(
    {
        "PLAN_INACTIVE",
        "DATA_NOT_READY",
        "DAILY_LIMIT_UNKNOWN",
        "EPISODE_HISTORY_GAP",
        "BEARISH_VOLUME_EXPANSION",
        "RISK_PENDING",
    }
)


def _expected_current_day_minute_ends_through(target: datetime) -> tuple[datetime, ...]:
    minute_numbers = (
        *range(9 * 60 + 31, 11 * 60 + 31),
        *range(13 * 60 + 1, 15 * 60 + 1),
    )
    return tuple(
        datetime(
            target.year,
            target.month,
            target.day,
            minute_number // 60,
            minute_number % 60,
            tzinfo=target.tzinfo,
        )
        for minute_number in minute_numbers
        if datetime(
            target.year,
            target.month,
            target.day,
            minute_number // 60,
            minute_number % 60,
            tzinfo=target.tzinfo,
        )
        <= target
    )


class _DecisionValue(BaseModel):
    """Close, freeze, and revalidate every public decision value."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    def model_copy(
        self,
        *,
        update: Mapping[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        """Copy one value while validating all public updates."""

        if not update:
            return super().model_copy(deep=deep)
        values = self.model_dump(mode="python", round_trip=True)
        values.update(update)
        return type(self).model_validate(values)


def _canonical_decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("canonical decimals must be finite")
    sign, digits, exponent = value.as_tuple()
    if not isinstance(exponent, int):  # pragma: no cover - finite guard above
        raise ValueError("canonical decimal exponent must be finite")
    if not any(digits):
        return "0"
    normalized_digits = list(digits)
    normalized_exponent = exponent
    while normalized_digits[-1] == 0:
        normalized_digits.pop()
        normalized_exponent += 1
    if len(normalized_digits) > _MAX_CANONICAL_DECIMAL_DIGITS:
        raise ValueError("canonical decimal coefficient is too large")
    coefficient = "".join(str(digit) for digit in normalized_digits)
    prefix = "-" if sign else ""
    return f"{prefix}{coefficient}e{normalized_exponent}"


def _canonical_json_text(value: object) -> str:
    return json.dumps(
        value,
        default=_canonical_json_default,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _canonical_json_default(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="python", round_trip=True)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return _canonical_decimal(value)
    if type(value) in {date, datetime}:
        return value.isoformat()
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def _evaluation_result_digest(payload: Mapping[str, object]) -> str:
    canonical_payload = _canonical_json_text(payload).encode("utf-8")
    return sha256(_RESULT_HASH_DOMAIN + canonical_payload).hexdigest()


class ConditionOutcome(StrEnum):
    """Three-valued outcome that distinguishes false from unavailable facts."""

    SATISFIED = "SATISFIED"
    UNSATISFIED = "UNSATISFIED"
    MISSING_INPUT = "MISSING_INPUT"


class EvidenceUnit(StrEnum):
    """Stable units used in deterministic condition evidence."""

    FEN = "FEN"
    SHARES = "SHARES"
    RATIO = "RATIO"
    BARS = "BARS"
    YUAN = "YUAN"
    COUNT = "COUNT"
    BOOLEAN = "BOOLEAN"
    DATE = "DATE"
    DATETIME = "DATETIME"
    CODE = "CODE"
    POINTS = "POINTS"


class MissingInputCode(StrEnum):
    """Closed reasons why a condition cannot be evaluated safely."""

    COMPLETE_MINUTE_BAR = "COMPLETE_MINUTE_BAR"
    PREVIOUS_MINUTE_BAR = "PREVIOUS_MINUTE_BAR"
    COMPLETE_5M_BAR = "COMPLETE_5M_BAR"
    PREVIOUS_5M_BAR = "PREVIOUS_5M_BAR"
    COMPLETE_5M_BAR_WINDOW = "COMPLETE_5M_BAR_WINDOW"
    ROLLING_VOLUME_WINDOW = "ROLLING_VOLUME_WINDOW"
    SESSION_BARS = "SESSION_BARS"
    DAILY_INDICATORS = "DAILY_INDICATORS"
    PROVISIONAL_DAILY_BAR = "PROVISIONAL_DAILY_BAR"
    FIVE_MINUTE_INDICATORS = "FIVE_MINUTE_INDICATORS"
    INDICATOR_VALUE = "INDICATOR_VALUE"
    OFFICIAL_DAILY_CLOSE = "OFFICIAL_DAILY_CLOSE"
    TRADING_CALENDAR = "TRADING_CALENDAR"
    DAILY_LIMIT = "DAILY_LIMIT"
    MANUAL_EVENT_RISK = "MANUAL_EVENT_RISK"
    INDEX_SNAPSHOT = "INDEX_SNAPSHOT"
    INDEX_IDENTITY = "INDEX_IDENTITY"
    INDEX_CUTOFF = "INDEX_CUTOFF"
    INDEX_HEALTH = "INDEX_HEALTH"
    INDEX_FACT = "INDEX_FACT"
    INDEX_HISTORY = "INDEX_HISTORY"
    INDEX_FORMULA = "INDEX_FORMULA"


class EvidenceFact(_DecisionValue):
    """One named, typed value used to explain a condition outcome."""

    key: EvidenceKey
    value: EvidenceScalar
    unit: EvidenceUnit

    @model_validator(mode="after")
    def validate_unit_and_value(self) -> Self:
        value_type = type(self.value)
        if isinstance(self.value, Decimal) and not self.value.is_finite():
            raise ValueError("decimal evidence must be finite")

        if self.unit is EvidenceUnit.CODE and value_type is not str:
            raise ValueError("CODE evidence requires a bounded code string")
        if self.unit is EvidenceUnit.BOOLEAN and value_type is not bool:
            raise ValueError("BOOLEAN evidence requires a strict boolean")
        if self.unit is EvidenceUnit.DATE and value_type is not date:
            raise ValueError("DATE evidence requires a strict date")
        if self.unit is EvidenceUnit.DATETIME:
            if value_type is not datetime or self.value.utcoffset() != timedelta(hours=8):
                raise ValueError("DATETIME evidence requires an Asia/Shanghai timestamp")
        if (
            self.unit in {EvidenceUnit.RATIO, EvidenceUnit.YUAN, EvidenceUnit.POINTS}
            and value_type is not Decimal
        ):
            raise ValueError("decimal evidence unit requires a Decimal value")
        if self.unit in {EvidenceUnit.FEN, EvidenceUnit.BARS, EvidenceUnit.COUNT}:
            if value_type is not int:
                raise ValueError("integer evidence unit requires a strict integer")
        if self.unit is EvidenceUnit.SHARES and value_type not in {int, Decimal}:
            raise ValueError("SHARES evidence requires an integer or Decimal value")
        return self


class IndexConditionEvidence(_DecisionValue):
    """Path-addressed plan-specific interpretation of one shared index fact."""

    plan_path: IndexPlanPath
    condition_type: IndexConditionType
    index_code: MarketIndexCode
    mapping_version: Literal["board-index-map-v1"] = "board-index-map-v1"
    snapshot_hash: Sha256Hex | None = None
    decision_cutoff: ShanghaiDatetime
    data_cutoff: ShanghaiDatetime | None = None
    formula_id: Literal["SMA", "SMA_LOOKBACK", "RETURN"]
    formula_definition_hash: Sha256Hex | None = None
    parameters: tuple[EvidenceFact, ...] = Field(default=(), max_length=8)
    actual_value: FiniteDecimal | None = None
    comparison_value: FiniteDecimal | None = None
    unit: MarketIndexFactUnit
    outcome: ConditionOutcome
    missing_inputs: tuple[MissingInputCode, ...] = Field(
        default=(),
        max_length=7,
    )

    @model_validator(mode="after")
    def validate_index_evidence_shape(self) -> Self:
        if len({item.key for item in self.parameters}) != len(self.parameters):
            raise ValueError("index evidence parameter keys must be unique")
        if len(set(self.missing_inputs)) != len(self.missing_inputs):
            raise ValueError("index evidence missing inputs must be unique")
        allowed_missing = {
            MissingInputCode.INDEX_SNAPSHOT,
            MissingInputCode.INDEX_IDENTITY,
            MissingInputCode.INDEX_CUTOFF,
            MissingInputCode.INDEX_HEALTH,
            MissingInputCode.INDEX_FACT,
            MissingInputCode.INDEX_HISTORY,
            MissingInputCode.INDEX_FORMULA,
        }
        if any(item not in allowed_missing for item in self.missing_inputs):
            raise ValueError("index evidence contains a non-index missing-input code")
        if self.outcome is ConditionOutcome.MISSING_INPUT:
            if not self.missing_inputs:
                raise ValueError("missing index evidence requires an exact missing code")
            if self.actual_value is not None or self.comparison_value is not None:
                raise ValueError("missing index evidence cannot guess comparison values")
            return self
        if self.missing_inputs:
            raise ValueError("known index evidence cannot contain missing-input codes")
        if self.actual_value is None or self.comparison_value is None:
            raise ValueError("known index evidence requires both compared values")
        if any(
            value is None
            for value in (
                self.snapshot_hash,
                self.data_cutoff,
                self.formula_definition_hash,
            )
        ):
            raise ValueError("known index evidence requires complete snapshot identity")
        return self


class ConditionEvidence(_DecisionValue):
    """Complete evidence for one leaf or logical condition."""

    condition: ConditionNode
    outcome: ConditionOutcome
    facts: tuple[EvidenceFact, ...] = Field(
        default=(),
        max_length=_MAX_EVIDENCE_FACTS,
    )
    missing_inputs: tuple[MissingInputCode, ...] = Field(
        default=(),
        max_length=_MAX_MISSING_INPUTS,
    )
    children: tuple[ConditionEvidence, ...] = Field(
        default=(),
        max_length=_MAX_CONDITION_VALUES,
    )
    index_evidence: IndexConditionEvidence | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )

    @model_validator(mode="after")
    def validate_evidence_shape(self) -> Self:
        validated_condition = type(self.condition).model_validate(
            self.condition.model_dump(mode="python", round_trip=True)
        )
        if validated_condition != self.condition:
            raise ValueError("condition evidence must retain a validated condition")
        if len({fact.key for fact in self.facts}) != len(self.facts):
            raise ValueError("evidence fact keys must be unique")
        if len(set(self.missing_inputs)) != len(self.missing_inputs):
            raise ValueError("missing input codes must be unique")

        is_all = isinstance(self.condition, AllCondition)
        is_any = isinstance(self.condition, AnyCondition)
        is_composite = is_all or is_any
        is_index = self.condition.type.startswith("INDEX_")
        if is_index != (self.index_evidence is not None):
            raise ValueError("only an index leaf requires index condition evidence")
        if self.index_evidence is not None:
            if self.index_evidence.condition_type != self.condition.type:
                raise ValueError("index evidence condition type must match its leaf")
            if self.index_evidence.outcome is not self.outcome:
                raise ValueError("index evidence outcome must match its leaf")
            if self.index_evidence.missing_inputs != self.missing_inputs:
                raise ValueError("index evidence missing codes must match its leaf")
        if is_composite:
            expected_conditions = self.condition.conditions
            if len(self.children) != len(expected_conditions):
                raise ValueError("logical evidence must preserve every condition child")
            if tuple(child.condition for child in self.children) != expected_conditions:
                raise ValueError("logical evidence must preserve condition child order")
        if not is_composite and self.children:
            raise ValueError("leaf evidence cannot contain child evidence")

        if is_all:
            if any(child.outcome is ConditionOutcome.UNSATISFIED for child in self.children):
                expected_outcome = ConditionOutcome.UNSATISFIED
            elif any(child.outcome is ConditionOutcome.MISSING_INPUT for child in self.children):
                expected_outcome = ConditionOutcome.MISSING_INPUT
            else:
                expected_outcome = ConditionOutcome.SATISFIED
            if self.outcome is not expected_outcome:
                raise ValueError("ALL evidence outcome must match its child outcomes")
        if is_any:
            if any(child.outcome is ConditionOutcome.SATISFIED for child in self.children):
                expected_outcome = ConditionOutcome.SATISFIED
            elif any(child.outcome is ConditionOutcome.MISSING_INPUT for child in self.children):
                expected_outcome = ConditionOutcome.MISSING_INPUT
            else:
                expected_outcome = ConditionOutcome.UNSATISFIED
            if self.outcome is not expected_outcome:
                raise ValueError("ANY evidence outcome must match its child outcomes")

        child_is_missing = any(
            child.outcome is ConditionOutcome.MISSING_INPUT for child in self.children
        )
        if self.outcome is ConditionOutcome.MISSING_INPUT:
            if not self.missing_inputs and not child_is_missing:
                raise ValueError("missing-input evidence must identify an unavailable fact")
        elif self.missing_inputs:
            raise ValueError("non-missing evidence cannot contain missing input codes")
        return self


class RuleEvidenceCode(StrEnum):
    """Stable non-DSL evidence codes assembled by the decision engine."""

    PLAN_INACTIVE = "PLAN_INACTIVE"
    DATA_NOT_READY = "DATA_NOT_READY"
    DAILY_LIMIT_UNKNOWN = "DAILY_LIMIT_UNKNOWN"
    EPISODE_HISTORY_GAP = "EPISODE_HISTORY_GAP"
    BEARISH_VOLUME_EXPANSION = "BEARISH_VOLUME_EXPANSION"
    RISK_PENDING = "RISK_PENDING"
    PRESSURE_TOUCH = "PRESSURE_TOUCH"
    RISK_RECOVERY = "RISK_RECOVERY"
    RISK_DETERIORATION = "RISK_DETERIORATION"


class RuleEvidence(_DecisionValue):
    """Bounded non-DSL facts preserved without inventing a condition tag."""

    code: RuleEvidenceCode
    outcome: ConditionOutcome
    facts: tuple[EvidenceFact, ...] = Field(
        default=(),
        max_length=16,
    )
    missing_inputs: tuple[MissingInputCode, ...] = Field(
        default=(),
        max_length=4,
    )

    @model_validator(mode="after")
    def validate_evidence_shape(self) -> Self:
        if len({fact.key for fact in self.facts}) != len(self.facts):
            raise ValueError("rule evidence fact keys must be unique")
        if len(set(self.missing_inputs)) != len(self.missing_inputs):
            raise ValueError("rule evidence missing inputs must be unique")
        if (
            self.code.value in _STRUCTURAL_RULE_EVIDENCE_CODES
            and self.outcome is ConditionOutcome.SATISFIED
        ):
            raise ValueError("structural blocker rule evidence cannot be satisfied")
        if self.outcome is ConditionOutcome.MISSING_INPUT:
            if not self.missing_inputs:
                raise ValueError("missing rule evidence must identify an unavailable fact")
        elif self.missing_inputs:
            raise ValueError("non-missing rule evidence cannot contain missing inputs")
        return self


EvaluationEvidence = ConditionEvidence | RuleEvidence


class EpisodeStatus(StrEnum):
    """Pure low-zone episode lifecycle used by the decision boundary."""

    ACTIVE = "ACTIVE"
    ALERTED = "ALERTED"
    CLOSED = "CLOSED"


class RiskStatus(StrEnum):
    """Pure official-close risk lifecycle used by the decision boundary."""

    CLEAR = "CLEAR"
    BREACHED_PENDING_CONFIRMATION = "BREACHED_PENDING_CONFIRMATION"
    EXIT_PENDING_SETTLEMENT = "EXIT_PENDING_SETTLEMENT"


class DataHealthStatus(StrEnum):
    """Closed per-symbol data-health vocabulary without persistence imports."""

    STARTING = "STARTING"
    LIVE = "LIVE"
    STALE = "STALE"
    GAPPED = "GAPPED"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"
    CLOSE_PENDING = "CLOSE_PENDING"


class DailyIndicatorProvenance(StrEnum):
    """Closed provenance for the current-date point of a daily series."""

    PROVISIONAL = "PROVISIONAL"
    OFFICIAL = "OFFICIAL"


class SignalType(StrEnum):
    """Every display decision defined by the approved engine contract."""

    WAIT = "WAIT"
    LOW_ZONE_WATCH = "LOW_ZONE_WATCH"
    BLOCKED_DATA = "BLOCKED_DATA"
    BLOCKED_RISK = "BLOCKED_RISK"
    BUY_CORE_READY = "BUY_CORE_READY"
    BUY_TACTICAL_READY = "BUY_TACTICAL_READY"
    PRESSURE_REDUCE_READY = "PRESSURE_REDUCE_READY"
    RISK_BREACH = "RISK_BREACH"
    RISK_RECOVERED = "RISK_RECOVERED"
    RISK_EXIT_READY = "RISK_EXIT_READY"
    RISK_EXIT_PENDING_SETTLEMENT = "RISK_EXIT_PENDING_SETTLEMENT"


class ActionableSignalType(StrEnum):
    """Signal values that may create a durable textual alert intent."""

    BUY_CORE_READY = "BUY_CORE_READY"
    BUY_TACTICAL_READY = "BUY_TACTICAL_READY"
    PRESSURE_REDUCE_READY = "PRESSURE_REDUCE_READY"
    RISK_BREACH = "RISK_BREACH"
    RISK_EXIT_READY = "RISK_EXIT_READY"
    RISK_EXIT_PENDING_SETTLEMENT = "RISK_EXIT_PENDING_SETTLEMENT"


class DecisionZone(StrEnum):
    """One unambiguous zone classification for a symbol snapshot."""

    LOW_BUY = "LOW_BUY"
    OBSERVATION = "OBSERVATION"
    PRESSURE = "PRESSURE"
    BELOW_RISK = "BELOW_RISK"
    OUTSIDE = "OUTSIDE"
    UNKNOWN = "UNKNOWN"


class NextStepCode(StrEnum):
    """Stable action/observation codes rendered only outside the engine."""

    WAIT_FOR_COMPLETE_BAR = "WAIT_FOR_COMPLETE_BAR"
    WAIT_FOR_REQUIRED_DATA = "WAIT_FOR_REQUIRED_DATA"
    WATCH_LOW_ZONE = "WATCH_LOW_ZONE"
    WATCH_PRESSURE = "WATCH_PRESSURE"
    REVIEW_BLOCKER = "REVIEW_BLOCKER"
    WAIT_FOR_OFFICIAL_CLOSE = "WAIT_FOR_OFFICIAL_CLOSE"
    WAIT_FOR_NEXT_TRADING_DAY = "WAIT_FOR_NEXT_TRADING_DAY"
    WAIT_FOR_SETTLEMENT = "WAIT_FOR_SETTLEMENT"
    RECORD_CONFIRMED_FILL = "RECORD_CONFIRMED_FILL"


class PositionLotSnapshot(_DecisionValue):
    """One known manual lot without importing persistence DTOs."""

    lot_id: PersistedIdentifier
    symbol: AShareSymbol
    bucket: PositionBucket
    quantity: PositiveBoardLot
    remaining_quantity: NonNegativeBoardLot
    acquired_trade_date: Annotated[date, Field(strict=True)]
    cost_fen: PositiveFen

    @model_validator(mode="after")
    def validate_remaining_quantity(self) -> Self:
        if self.remaining_quantity > self.quantity:
            raise ValueError("remaining_quantity cannot exceed quantity")
        return self


class LowZoneEpisodeSnapshot(_DecisionValue):
    """Known low-zone episode state supplied explicitly to pure evaluation."""

    episode_id: PersistedIdentifier
    plan_hash: Sha256Hex
    symbol: AShareSymbol
    started_at: ShanghaiDatetime
    episode_low_fen: PositiveFen
    bars_since_low: NonNegativeInteger
    last_processed_bucket_end: ShanghaiDatetime
    status: EpisodeStatus
    alerted_signal: Literal["BUY_CORE_READY", "BUY_TACTICAL_READY"] | None

    @model_validator(mode="after")
    def validate_alert_state(self) -> Self:
        expected_five_minute_ends(self.last_processed_bucket_end)
        if self.last_processed_bucket_end < five_minute_bucket_end(self.started_at):
            raise ValueError("episode processing cursor cannot precede its touch bucket")
        if self.status is EpisodeStatus.ALERTED and self.alerted_signal is None:
            raise ValueError("alerted episode must identify its signal")
        if self.status is EpisodeStatus.ACTIVE and self.alerted_signal is not None:
            raise ValueError("active episode cannot already identify an alert")
        return self


class RiskStateSnapshot(_DecisionValue):
    """Known official-close risk state supplied explicitly to evaluation."""

    symbol: AShareSymbol
    plan_hash: Sha256Hex
    status: RiskStatus
    breach_trade_date: Annotated[date, Field(strict=True)] | None
    prior_close_fen: PositiveFen
    revision: NonNegativeInteger
    updated_at: ShanghaiDatetime

    @model_validator(mode="after")
    def validate_risk_state(self) -> Self:
        if self.status is RiskStatus.CLEAR:
            if self.breach_trade_date is not None:
                raise ValueError("clear risk state cannot retain a breach date")
        elif self.breach_trade_date is None:
            raise ValueError("active risk state requires a breach date")
        if self.breach_trade_date is not None and self.breach_trade_date > self.updated_at.date():
            raise ValueError("risk breach date cannot follow its update timestamp")
        return self


class DataHealthSnapshot(_DecisionValue):
    """Explicit per-symbol completeness and freshness facts."""

    symbol: AShareSymbol
    status: DataHealthStatus
    latest_bar_end: ShanghaiDatetime | None
    data_age_seconds: NonNegativeInteger | None
    required_data_complete: StrictBoolean
    fresh: StrictBoolean

    @model_validator(mode="after")
    def validate_data_age(self) -> Self:
        if (self.latest_bar_end is None) != (self.data_age_seconds is None):
            raise ValueError("latest bar timestamp and data age must appear together")
        if self.fresh and self.latest_bar_end is None:
            raise ValueError("fresh data health requires a latest bar timestamp")
        if self.status is DataHealthStatus.LIVE and (
            not self.fresh or not self.required_data_complete or self.latest_bar_end is None
        ):
            raise ValueError("LIVE data health requires fresh complete market data")
        if self.status is DataHealthStatus.STALE and self.fresh:
            raise ValueError("STALE data health cannot be fresh")
        if self.status in {DataHealthStatus.GAPPED, DataHealthStatus.BLOCKED} and (
            self.required_data_complete
        ):
            raise ValueError("gapped or blocked data health cannot be complete")
        return self


class DailyIndicatorSnapshot(_DecisionValue):
    """One daily series tied to its exact current-date source and cutoff."""

    series: IndicatorSeries
    provenance: DailyIndicatorProvenance
    source_as_of: ShanghaiDatetime
    source_bar: DailyBar

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        if self.provenance is DailyIndicatorProvenance.PROVISIONAL:
            if self.source_bar.is_official:
                raise ValueError("provisional provenance requires a provisional source bar")
            expected_five_minute_ends(self.source_as_of)
        elif not self.source_bar.is_official:
            raise ValueError("official provenance cannot use a provisional source bar")
        if self.source_as_of.date() != self.source_bar.trade_date:
            raise ValueError("daily indicator cutoff must match its source date")
        if self.source_as_of > self.source_bar.received_at:
            raise ValueError("daily indicator cutoff cannot follow its source receipt")
        if self.provenance is DailyIndicatorProvenance.OFFICIAL:
            official_cutoff = self.source_as_of.replace(
                hour=15,
                minute=0,
                second=0,
                microsecond=0,
            )
            if self.source_as_of != official_cutoff:
                raise ValueError("official daily indicator cutoff must be 15:00")
        if self.series.symbol != self.source_bar.symbol:
            raise ValueError("daily indicator source symbol must match its series")
        latest = self.series.points[-1]
        if type(latest.bar_at) is not date or latest.bar_at != self.source_bar.trade_date:
            raise ValueError("daily indicator source date must match its latest point")
        return self


class IntradayEvaluationTarget(_DecisionValue):
    """One complete five-minute bucket selected for evaluation."""

    kind: Literal["INTRADAY"] = "INTRADAY"
    bucket_end: ShanghaiDatetime

    @model_validator(mode="after")
    def validate_bucket_boundary(self) -> Self:
        expected_five_minute_ends(self.bucket_end)
        return self


class OfficialCloseEvaluationTarget(_DecisionValue):
    """One official trade date selected for close-risk evaluation."""

    kind: Literal["OFFICIAL_CLOSE"] = "OFFICIAL_CLOSE"
    trade_date: Annotated[date, Field(strict=True)]


EvaluationTarget = Annotated[
    IntradayEvaluationTarget | OfficialCloseEvaluationTarget,
    Field(discriminator="kind"),
]


class EvaluationContext(_DecisionValue):
    """All explicit facts available to one deterministic symbol evaluation."""

    evaluated_at: ShanghaiDatetime
    target: EvaluationTarget
    plan: TradePlan
    plan_hash: Sha256Hex
    plan_active: StrictBoolean
    activated_at: ShanghaiDatetime | None
    current_day_minutes: tuple[MinuteBar, ...] = Field(
        default=(),
        max_length=_MAX_CURRENT_DAY_MINUTES,
    )
    complete_5m_bars: tuple[FiveMinuteBar, ...] = Field(
        default=(),
        max_length=_MAX_MARKET_BARS,
    )
    official_daily_bars: tuple[DailyBar, ...] = Field(
        default=(),
        max_length=_MAX_DAILY_BARS,
    )
    five_minute_indicators: IndicatorSeries | None
    daily_indicator_snapshot: DailyIndicatorSnapshot | None
    close_reconciliation: CloseReconciliationIntent | None
    trading_calendar: tuple[TradingDay, ...] = Field(
        default=(),
        max_length=_MAX_TRADING_DAYS,
    )
    daily_limit: DailyLimit | None
    data_health: DataHealthSnapshot
    positions: tuple[PositionLotSnapshot, ...] = Field(
        default=(),
        max_length=_MAX_POSITION_LOTS,
    )
    low_zone_episode: LowZoneEpisodeSnapshot | None
    risk_state: RiskStateSnapshot
    manual_event_risk: StrictBoolean | None
    reference_market_snapshot: MarketIndexSnapshot | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )

    @property
    def trade_date(self) -> date:
        """Return the explicit trading date selected by the target."""

        if isinstance(self.target, IntradayEvaluationTarget):
            return self.target.bucket_end.date()
        return self.target.trade_date

    @property
    def target_cutoff(self) -> datetime:
        """Return the effective market-time cutoff for supplied strategy state."""

        if isinstance(self.target, IntradayEvaluationTarget):
            return self.target.bucket_end
        return datetime(
            self.target.trade_date.year,
            self.target.trade_date.month,
            self.target.trade_date.day,
            15,
            0,
            tzinfo=self.evaluated_at.tzinfo,
        )

    @property
    def trading_day(self) -> TradingDay | None:
        """Return the explicit calendar row for the selected target date."""

        return next(
            (item for item in reversed(self.trading_calendar) if item.cal_date == self.trade_date),
            None,
        )

    @property
    def current_bucket_minutes(self) -> tuple[MinuteBar, ...]:
        """Derive the latest target bucket without storing a conflicting copy."""

        if not self.current_day_minutes:
            return ()
        bucket_end = (
            self.target.bucket_end
            if isinstance(self.target, IntradayEvaluationTarget)
            else five_minute_bucket_end(self.current_day_minutes[-1].bar_end)
        )
        return tuple(
            minute
            for minute in self.current_day_minutes
            if five_minute_bucket_end(minute.bar_end) == bucket_end
        )

    @property
    def daily_indicators(self) -> IndicatorSeries | None:
        """Expose the sourced daily series without accepting a second input."""

        if self.daily_indicator_snapshot is None:
            return None
        return self.daily_indicator_snapshot.series

    @model_validator(mode="after")
    def validate_context_identity(self) -> Self:
        validated_plan = TradePlan.model_validate(
            self.plan.model_dump(mode="python", round_trip=True)
        )
        if validated_plan != self.plan:
            raise ValueError("plan must remain a validated immutable value")
        if plan_sha256(validated_plan) != self.plan_hash:
            raise ValueError("plan_hash must match the complete plan content")
        semantic_validation = validate_trade_plan(
            validated_plan,
            available_market_evidence=ALL_MARKET_EVIDENCE,
        )
        if not semantic_validation.can_save:
            raise ValueError("plan must pass cross-field semantic validation")
        if self.reference_market_snapshot is not None:
            validate_market_index_snapshot_integrity(self.reference_market_snapshot)
        if self.plan_active != (self.activated_at is not None):
            raise ValueError("active plan fact requires exactly one activation timestamp")
        if self.activated_at is not None and self.activated_at > self.evaluated_at:
            raise ValueError("plan cannot activate after evaluation time")
        if self.activated_at is not None and self.activated_at > self.target_cutoff:
            raise ValueError("plan cannot activate after the evaluation target")

        if isinstance(self.target, IntradayEvaluationTarget):
            if self.target.bucket_end > self.evaluated_at:
                raise ValueError("intraday target cannot be after evaluation time")
        elif self.evaluated_at.date() < self.target.trade_date:
            raise ValueError("official-close target cannot be after evaluation date")

        bar_ends = tuple(bar.bar_end for bar in self.complete_5m_bars)
        if any(current <= previous for previous, current in pairwise(bar_ends)):
            raise ValueError("complete 5-minute bars must be strictly increasing")
        for bar in self.complete_5m_bars:
            if bar.symbol != self.plan.symbol:
                raise ValueError("complete 5-minute bar symbol must match plan symbol")
            if bar.formula_version != self.plan.monitoring.indicator_formula_version:
                raise ValueError("bar formula version must match plan formula version")
            if bar.bar_end > self.evaluated_at:
                raise ValueError("complete 5-minute bar cannot be from the future")
            if isinstance(self.target, IntradayEvaluationTarget):
                if bar.bar_end > self.target.bucket_end:
                    raise ValueError("complete bar cannot be after intraday target")
            elif bar.bar_end.date() > self.target.trade_date:
                raise ValueError("complete bar cannot be after official-close target")

        minute_ends = tuple(bar.bar_end for bar in self.current_day_minutes)
        if any(current <= previous for previous, current in pairwise(minute_ends)):
            raise ValueError("current-day minutes must be strictly increasing")
        minute_groups: dict[datetime, list[MinuteBar]] = {}
        for minute in self.current_day_minutes:
            if minute.symbol != self.plan.symbol:
                raise ValueError("minute bar symbol must match plan symbol")
            if minute.bar_end.date() != self.trade_date:
                raise ValueError("current-day minute must match target trade date")
            if minute.received_at > self.evaluated_at:
                raise ValueError("minute bar cannot be received after evaluation time")
            if isinstance(self.target, IntradayEvaluationTarget):
                if minute.bar_end > self.target.bucket_end:
                    raise ValueError("current-day minute cannot be after intraday target")
            bucket_end = five_minute_bucket_end(minute.bar_end)
            minute_groups.setdefault(bucket_end, []).append(minute)

        bars_by_end = {bar.bar_end: bar for bar in self.complete_5m_bars}
        for bucket_end, group_values in minute_groups.items():
            group = tuple(group_values)
            if len(group) != 5:
                raise ValueError("represented minute buckets must contain exactly five minutes")
            aggregate = aggregate_five_minute_bar(
                group,
                bucket_end=bucket_end,
                is_open=True,
            )
            if aggregate is None or bars_by_end.get(bucket_end) != aggregate:
                raise ValueError("current-day minutes must aggregate to their complete bar")

        daily_dates = tuple(bar.trade_date for bar in self.official_daily_bars)
        if any(current <= previous for previous, current in pairwise(daily_dates)):
            raise ValueError("official daily bars must be strictly increasing")
        for daily_bar in self.official_daily_bars:
            if daily_bar.symbol != self.plan.symbol:
                raise ValueError("official daily bar symbol must match plan symbol")
            if not daily_bar.is_official:
                raise ValueError("official daily history cannot contain provisional bars")
            if daily_bar.trade_date >= self.trade_date:
                raise ValueError("official daily history must precede target trade date")
            if daily_bar.received_at > self.evaluated_at:
                raise ValueError("official daily history cannot contain future data")

        self._validate_indicator_series(self.five_minute_indicators, intraday=True)
        self._validate_indicator_series(self.daily_indicators, intraday=False)

        if self.close_reconciliation is not None:
            if self.close_reconciliation.symbol != self.plan.symbol:
                raise ValueError("close reconciliation symbol must match plan symbol")
            if self.close_reconciliation.trade_date != self.trade_date:
                raise ValueError("close reconciliation date must match target trade date")
            if self.close_reconciliation.advance_close_risk and not isinstance(
                self.target,
                OfficialCloseEvaluationTarget,
            ):
                raise ValueError("official-ready reconciliation requires an official-close target")
            for daily_bar in (
                self.close_reconciliation.provisional_bar,
                self.close_reconciliation.official_bar,
            ):
                if daily_bar is not None and daily_bar.received_at > self.evaluated_at:
                    raise ValueError("close reconciliation cannot contain future data")

        indicator_snapshot = self.daily_indicator_snapshot
        if indicator_snapshot is not None:
            if self.close_reconciliation is None:
                raise ValueError("daily indicators require close reconciliation provenance")
            if indicator_snapshot.source_bar.symbol != self.plan.symbol:
                raise ValueError("daily indicator source symbol must match plan")
            if indicator_snapshot.source_bar.trade_date != self.trade_date:
                raise ValueError("daily indicator source date must match target")
            if indicator_snapshot.source_as_of > self.evaluated_at:
                raise ValueError("daily indicator source cannot be after evaluation time")
            if isinstance(self.target, IntradayEvaluationTarget):
                if indicator_snapshot.provenance is not DailyIndicatorProvenance.PROVISIONAL:
                    raise ValueError("intraday daily indicators require provisional provenance")
                if indicator_snapshot.source_as_of != self.target.bucket_end:
                    raise ValueError("provisional indicator cutoff must match intraday target")
                if self.close_reconciliation.provisional_bar != indicator_snapshot.source_bar:
                    raise ValueError("provisional indicator source must match reconciliation")
            else:
                if indicator_snapshot.provenance is not DailyIndicatorProvenance.OFFICIAL:
                    raise ValueError("official-close indicators require official provenance")
                if (
                    not self.close_reconciliation.advance_close_risk
                    or self.close_reconciliation.official_bar != indicator_snapshot.source_bar
                ):
                    raise ValueError("official indicator source must match reconciliation")

        calendar_dates = tuple(item.cal_date for item in self.trading_calendar)
        if any(current <= previous for previous, current in pairwise(calendar_dates)):
            raise ValueError("trading calendar dates must be strictly increasing")
        for calendar_day in self.trading_calendar:
            if calendar_day.exchange != self.plan.market:
                raise ValueError("trading calendar exchange must match plan market")
            if calendar_day.cal_date > self.trade_date:
                raise ValueError("trading calendar cannot contain a future target date")
        calendar_by_date = {
            calendar_day.cal_date: calendar_day for calendar_day in self.trading_calendar
        }
        if (
            isinstance(self.target, IntradayEvaluationTarget)
            and self.data_health.required_data_complete
        ):
            target_day = calendar_by_date.get(self.trade_date)
            if target_day is None or not target_day.is_open:
                raise ValueError(
                    "complete intraday health requires an open target trading calendar row"
                )
        supplied_open_dates = tuple(
            calendar_day.cal_date for calendar_day in self.trading_calendar if calendar_day.is_open
        )
        for calendar_day in self.trading_calendar:
            supplied_previous = calendar_by_date.get(calendar_day.previous_trade_date)
            if supplied_previous is not None and not supplied_previous.is_open:
                raise ValueError("calendar previous_trade_date must identify a supplied open date")
            if any(
                calendar_day.previous_trade_date < open_date < calendar_day.cal_date
                for open_date in supplied_open_dates
            ):
                raise ValueError(
                    "trading calendar previous_trade_date cannot skip a supplied open date"
                )

        if self.daily_limit is not None:
            if self.daily_limit.symbol != self.plan.symbol:
                raise ValueError("daily-limit symbol must match plan symbol")
            if self.daily_limit.trade_date != self.trade_date:
                raise ValueError("daily-limit date must match target trade date")
            if self.daily_limit.received_at > self.evaluated_at:
                raise ValueError("daily limit cannot be received after evaluation time")

        if self.data_health.symbol != self.plan.symbol:
            raise ValueError("data-health symbol must match plan symbol")
        if (
            self.data_health.latest_bar_end is not None
            and self.data_health.latest_bar_end > self.evaluated_at
        ):
            raise ValueError("data-health latest bar cannot be from the future")
        if self.data_health.latest_bar_end is None:
            if self.complete_5m_bars:
                raise ValueError("data-health latest bar must identify available history")
        else:
            if (
                not self.complete_5m_bars
                or self.data_health.latest_bar_end != self.complete_5m_bars[-1].bar_end
            ):
                raise ValueError("data-health latest bar must match complete bar history")
            expected_age = timedelta(seconds=self.data_health.data_age_seconds)
            if self.evaluated_at - self.data_health.latest_bar_end != expected_age:
                raise ValueError("data age must match evaluation and latest bar times")
        if (
            isinstance(self.target, IntradayEvaluationTarget)
            and self.data_health.required_data_complete
            and self.data_health.latest_bar_end != self.target.bucket_end
        ):
            raise ValueError("complete intraday health latest bar must match target")
        if (
            isinstance(self.target, IntradayEvaluationTarget)
            and self.data_health.required_data_complete
            and minute_ends != _expected_current_day_minute_ends_through(self.target.bucket_end)
        ):
            raise ValueError("complete intraday health requires gapless current-day minutes")

        lot_ids: set[str] = set()
        total_remaining = 0
        for lot in self.positions:
            if lot.lot_id in lot_ids:
                raise ValueError("position lot IDs must be unique")
            lot_ids.add(lot.lot_id)
            if lot.symbol != self.plan.symbol:
                raise ValueError("position symbol must match plan symbol")
            if lot.acquired_trade_date > self.trade_date:
                raise ValueError("position lot cannot be acquired after target trade date")
            total_remaining += lot.remaining_quantity
        if total_remaining > self.plan.position.max_qty:
            raise ValueError("remaining position cannot exceed plan maximum")

        if self.low_zone_episode is not None:
            if self.low_zone_episode.symbol != self.plan.symbol:
                raise ValueError("episode symbol must match plan symbol")
            if self.low_zone_episode.plan_hash != self.plan_hash:
                raise ValueError("episode plan hash must match evaluation plan")
            if self.low_zone_episode.started_at > self.evaluated_at:
                raise ValueError("episode cannot start after evaluation time")
            if self.low_zone_episode.started_at > self.target_cutoff:
                raise ValueError("episode cannot start after the evaluation target")
            if self.low_zone_episode.last_processed_bucket_end > self.target_cutoff:
                raise ValueError("episode processing cursor cannot exceed the evaluation target")

        if self.risk_state.symbol != self.plan.symbol:
            raise ValueError("risk-state symbol must match plan symbol")
        if self.risk_state.plan_hash != self.plan_hash:
            raise ValueError("risk-state plan hash must match evaluation plan")
        if self.risk_state.updated_at > self.evaluated_at:
            raise ValueError("risk state cannot be updated after evaluation time")
        if self.risk_state.updated_at > self.target_cutoff:
            raise ValueError("risk state cannot be updated after the evaluation target")
        if (
            self.risk_state.breach_trade_date is not None
            and self.risk_state.breach_trade_date > self.trade_date
        ):
            raise ValueError("risk breach date cannot be after target trade date")
        return self

    def _validate_indicator_series(
        self,
        series: IndicatorSeries | None,
        *,
        intraday: bool,
    ) -> None:
        if series is None:
            return
        if series.symbol != self.plan.symbol:
            raise ValueError("indicator symbol must match plan symbol")
        if series.formula_version != self.plan.monitoring.indicator_formula_version:
            raise ValueError("indicator formula version must match plan formula version")

        identities = tuple(point.bar_at for point in series.points)
        if intraday:
            if any(type(identity) is not datetime for identity in identities):
                raise ValueError("five-minute indicators must use datetime identities")
            datetimes = tuple(identity for identity in identities if isinstance(identity, datetime))
            if any(current <= previous for previous, current in pairwise(datetimes)):
                raise ValueError("indicator identities must be strictly increasing")
            if any(value > self.evaluated_at for value in datetimes):
                raise ValueError("indicator point cannot be from the future")
            bar_ends = tuple(bar.bar_end for bar in self.complete_5m_bars)
            if datetimes != bar_ends:
                raise ValueError("five-minute indicator identities must align with bars")
        else:
            if any(type(identity) is not date for identity in identities):
                raise ValueError("daily indicators must use date identities")
            dates = tuple(identity for identity in identities if type(identity) is date)
            if any(current <= previous for previous, current in pairwise(dates)):
                raise ValueError("indicator identities must be strictly increasing")
            if any(value > self.trade_date for value in dates):
                raise ValueError("daily indicator point cannot be after target date")
            expected_dates = tuple(bar.trade_date for bar in self.official_daily_bars) + (
                self.trade_date,
            )
            if dates != expected_dates:
                raise ValueError("daily indicator identities must align with source bars")


class PositionSummary(_DecisionValue):
    """Aggregated position facts shown in one decision snapshot."""

    core_quantity: NonNegativeBoardLot
    tactical_quantity: NonNegativeBoardLot
    total_quantity: NonNegativeBoardLot
    sellable_core_quantity: NonNegativeBoardLot
    sellable_tactical_quantity: NonNegativeBoardLot

    @model_validator(mode="after")
    def validate_summary(self) -> Self:
        if self.total_quantity != self.core_quantity + self.tactical_quantity:
            raise ValueError("total quantity must equal core plus tactical quantity")
        if self.sellable_core_quantity > self.core_quantity:
            raise ValueError("sellable core quantity cannot exceed core quantity")
        if self.sellable_tactical_quantity > self.tactical_quantity:
            raise ValueError("sellable tactical quantity cannot exceed tactical quantity")
        return self


class NextStep(_DecisionValue):
    """One stable non-rendered instruction for the runtime or user interface."""

    code: NextStepCode
    not_before: ShanghaiDatetime | Annotated[date, Field(strict=True)] | None = None
    required_inputs: tuple[MissingInputCode, ...] = Field(
        default=(),
        max_length=_MAX_MISSING_INPUTS,
    )

    @model_validator(mode="after")
    def validate_required_inputs(self) -> Self:
        if len(set(self.required_inputs)) != len(self.required_inputs):
            raise ValueError("next-step required inputs must be unique")
        return self


class DecisionReferenceMarketSnapshot(_DecisionValue):
    """Compact index context persisted exactly with one authoritative decision."""

    index_code: MarketIndexCode
    snapshot_hash: Sha256Hex
    data_at: ShanghaiDatetime | None
    health: MarketIndexHealth

    @classmethod
    def from_snapshot(cls, snapshot: MarketIndexSnapshot) -> Self:
        if type(snapshot) is not MarketIndexSnapshot:
            raise TypeError("snapshot must be an exact MarketIndexSnapshot")
        return cls(
            index_code=snapshot.index_code,
            snapshot_hash=snapshot.snapshot_hash,
            data_at=snapshot.completed_bucket_at,
            health=snapshot.health,
        )


class SymbolDecisionSnapshot(_DecisionValue):
    """The single authoritative display snapshot returned for one symbol."""

    symbol: AShareSymbol
    plan_id: StableIdentifier
    plan_version: PositiveVersion
    plan_hash: Sha256Hex
    evaluated_at: ShanghaiDatetime
    market_data_at: ShanghaiDatetime | None
    price_fen: PositiveFen | None
    zone: DecisionZone
    signal_type: SignalType
    position: PositionSummary
    episode: LowZoneEpisodeSnapshot | None
    risk: RiskStateSnapshot
    data_health: DataHealthSnapshot
    condition_evidence: tuple[EvaluationEvidence, ...] = Field(
        default=(),
        max_length=_MAX_CONDITION_VALUES,
    )
    reference_market: DecisionReferenceMarketSnapshot | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    next_step: NextStep

    @model_validator(mode="after")
    def validate_snapshot_identity(self) -> Self:
        if (self.market_data_at is None) != (self.price_fen is None):
            raise ValueError("price and market_data_at must appear together")
        if self.risk.symbol != self.symbol or self.risk.plan_hash != self.plan_hash:
            raise ValueError("snapshot risk identity must match snapshot")
        if self.data_health.symbol != self.symbol:
            raise ValueError("snapshot data-health symbol must match snapshot")
        if self.episode is not None and (
            self.episode.symbol != self.symbol or self.episode.plan_hash != self.plan_hash
        ):
            raise ValueError("snapshot episode identity must match snapshot")
        if self.episode is not None and self.episode.started_at > self.evaluated_at:
            raise ValueError("snapshot episode cannot start after evaluation")
        if self.episode is not None and self.episode.last_processed_bucket_end > self.evaluated_at:
            raise ValueError("snapshot episode cursor cannot exceed evaluation")
        if self.risk.updated_at > self.evaluated_at:
            raise ValueError("snapshot risk cannot update after evaluation")
        if (
            self.risk.breach_trade_date is not None
            and self.risk.breach_trade_date > self.evaluated_at.date()
        ):
            raise ValueError("snapshot risk breach cannot be after evaluation date")
        if (
            self.data_health.latest_bar_end is not None
            and self.data_health.latest_bar_end > self.evaluated_at
        ):
            raise ValueError("snapshot data health cannot be from the future")
        if self.data_health.latest_bar_end is not None:
            expected_age = timedelta(seconds=self.data_health.data_age_seconds)
            if self.evaluated_at - self.data_health.latest_bar_end != expected_age:
                raise ValueError("snapshot data age must match evaluation time")
        if self.market_data_at is not None and self.market_data_at > self.evaluated_at:
            raise ValueError("snapshot market data cannot be from the future")
        if (
            self.reference_market is not None
            and self.reference_market.data_at is not None
            and self.reference_market.data_at > self.evaluated_at
        ):
            raise ValueError("snapshot reference-market data cannot be from the future")
        return self


class EpisodeTransitionAction(StrEnum):
    """Supported low-zone episode persistence operations."""

    UPSERT = "UPSERT"
    CLOSE = "CLOSE"


class EpisodeTransitionIntent(_DecisionValue):
    """Pure requested episode transition; applying it belongs to the runtime."""

    intent_type: Literal["EPISODE"] = "EPISODE"
    action: EpisodeTransitionAction
    episode: LowZoneEpisodeSnapshot

    @model_validator(mode="after")
    def validate_action_status(self) -> Self:
        if self.action is EpisodeTransitionAction.CLOSE:
            if self.episode.status is not EpisodeStatus.CLOSED:
                raise ValueError("CLOSE episode intent requires CLOSED status")
        elif self.episode.status is EpisodeStatus.CLOSED:
            raise ValueError("UPSERT episode intent cannot carry CLOSED status")
        return self


class RiskTransitionIntent(_DecisionValue):
    """Pure requested risk-state transition with optimistic revision."""

    intent_type: Literal["RISK"] = "RISK"
    risk: RiskStateSnapshot
    expected_revision: NonNegativeInteger

    @model_validator(mode="after")
    def validate_revision(self) -> Self:
        if self.risk.revision != self.expected_revision + 1:
            raise ValueError("risk intent revision must advance expected revision once")
        return self


StateTransitionIntent = Annotated[
    EpisodeTransitionIntent | RiskTransitionIntent,
    Field(discriminator="intent_type"),
]


class SignalIntent(_DecisionValue):
    """At most one actionable alert request returned by a decision."""

    signal_type: ActionableSignalType
    plan_hash: Sha256Hex
    symbol: AShareSymbol
    trading_date: Annotated[date, Field(strict=True)]
    cause_id: StableIdentifier
    quantity: PositiveBoardLot | None
    bucket: PositionBucket | None
    target_lot_id: PersistedIdentifier | None
    matched_conditions: tuple[ConditionEvidence, ...] = Field(
        min_length=1,
        max_length=_MAX_CONDITION_VALUES,
    )
    blockers: tuple[ConditionEvidence, ...] = Field(
        default=(),
        max_length=_MAX_CONDITION_VALUES,
    )
    next_step: NextStep

    @model_validator(mode="after")
    def validate_action_shape(self) -> Self:
        if any(
            evidence.outcome is not ConditionOutcome.SATISFIED
            for evidence in self.matched_conditions
        ):
            raise ValueError("matched conditions must all be satisfied")
        if self.blockers:
            raise ValueError("actionable signal cannot retain active blockers")
        if self.signal_type is ActionableSignalType.RISK_BREACH:
            if any(value is not None for value in (self.quantity, self.bucket, self.target_lot_id)):
                raise ValueError("risk-breach signal cannot imply a trade or fill")
            return self

        if self.quantity is None or self.bucket is None:
            raise ValueError("trade-ready signal requires quantity and position bucket")
        if (
            self.signal_type
            in {
                ActionableSignalType.BUY_CORE_READY,
                ActionableSignalType.BUY_TACTICAL_READY,
            }
            and self.target_lot_id is not None
        ):
            raise ValueError("buy signal cannot identify a target lot")
        if (
            self.signal_type
            in {
                ActionableSignalType.PRESSURE_REDUCE_READY,
                ActionableSignalType.RISK_EXIT_READY,
                ActionableSignalType.RISK_EXIT_PENDING_SETTLEMENT,
            }
            and self.target_lot_id is None
        ):
            raise ValueError("reduction or exit signal requires a target lot")
        if self.signal_type is ActionableSignalType.BUY_CORE_READY and self.bucket != "CORE":
            raise ValueError("core-buy signal must target the core bucket")
        if (
            self.signal_type
            in {
                ActionableSignalType.BUY_TACTICAL_READY,
                ActionableSignalType.PRESSURE_REDUCE_READY,
            }
            and self.bucket != "TACTICAL"
        ):
            raise ValueError("tactical signal must target the tactical bucket")
        return self


class IntradayEvaluationIdentity(_DecisionValue):
    """Replay identity for one completed five-minute evaluation."""

    kind: Literal["INTRADAY"] = "INTRADAY"
    plan_hash: Sha256Hex
    symbol: AShareSymbol
    bucket_end: ShanghaiDatetime
    formula_version: Literal["ta-v1"] = "ta-v1"

    @model_validator(mode="after")
    def validate_bucket_boundary(self) -> Self:
        expected_five_minute_ends(self.bucket_end)
        return self


class OfficialCloseEvaluationIdentity(_DecisionValue):
    """Replay identity for one official-close date evaluation."""

    kind: Literal["OFFICIAL_CLOSE"] = "OFFICIAL_CLOSE"
    plan_hash: Sha256Hex
    symbol: AShareSymbol
    official_trade_date: Annotated[date, Field(strict=True)]
    formula_version: Literal["ta-v1"] = "ta-v1"


EvaluationIdentity = Annotated[
    IntradayEvaluationIdentity | OfficialCloseEvaluationIdentity,
    Field(discriminator="kind"),
]


class _EvaluationResultPayload(_DecisionValue):
    """Normalized result fields before the canonical digest is attached."""

    snapshot: SymbolDecisionSnapshot
    transitions: tuple[StateTransitionIntent, ...] = Field(
        default=(),
        max_length=_MAX_CONDITION_VALUES,
    )
    signal_intent: SignalIntent | None
    satisfied_conditions: tuple[EvaluationEvidence, ...] = Field(
        default=(),
        max_length=_MAX_CONDITION_VALUES,
    )
    unmet_conditions: tuple[EvaluationEvidence, ...] = Field(
        default=(),
        max_length=_MAX_CONDITION_VALUES,
    )
    blockers: tuple[EvaluationEvidence, ...] = Field(
        default=(),
        max_length=_MAX_CONDITION_VALUES,
    )
    next_step: NextStep
    evaluation_identity: EvaluationIdentity

    @model_validator(mode="after")
    def validate_result_identity(self) -> Self:
        identity = self.evaluation_identity
        if identity.symbol != self.snapshot.symbol:
            raise ValueError("evaluation identity symbol must match snapshot")
        if identity.plan_hash != self.snapshot.plan_hash:
            raise ValueError("evaluation identity plan hash must match snapshot")
        if self.snapshot.next_step != self.next_step:
            raise ValueError("result next step must match snapshot next step")

        if isinstance(identity, IntradayEvaluationIdentity):
            if identity.bucket_end > self.snapshot.evaluated_at:
                raise ValueError("intraday identity cannot be after snapshot")
            identity_date = identity.bucket_end.date()
            identity_cutoff = identity.bucket_end
            market_data_at = self.snapshot.market_data_at
            if market_data_at is not None and (
                market_data_at.date() != identity_date or market_data_at > identity.bucket_end
            ):
                raise ValueError("intraday market data cannot follow its target")
            if (
                self.snapshot.data_health.fresh
                and self.snapshot.data_health.required_data_complete
                and market_data_at != identity.bucket_end
            ):
                raise ValueError("fresh complete intraday market data must match its target")
        else:
            if identity.official_trade_date > self.snapshot.evaluated_at.date():
                raise ValueError("official identity cannot be after snapshot")
            identity_date = identity.official_trade_date
            identity_cutoff = datetime(
                identity.official_trade_date.year,
                identity.official_trade_date.month,
                identity.official_trade_date.day,
                15,
                0,
                tzinfo=self.snapshot.evaluated_at.tzinfo,
            )
            if self.snapshot.market_data_at is not None and (
                self.snapshot.market_data_at != identity_cutoff
            ):
                raise ValueError("official market-data cutoff must be exactly 15:00")

        if (
            self.snapshot.risk.breach_trade_date is not None
            and self.snapshot.risk.breach_trade_date > identity_date
        ):
            raise ValueError("snapshot risk breach cannot postdate evaluation identity")
        if self.snapshot.episode is not None and self.snapshot.episode.started_at > identity_cutoff:
            raise ValueError("snapshot episode cannot postdate evaluation identity")
        if (
            self.snapshot.episode is not None
            and self.snapshot.episode.last_processed_bucket_end > identity_cutoff
        ):
            raise ValueError("snapshot episode cursor cannot postdate evaluation identity")

        actionable_values = {item.value for item in ActionableSignalType}
        snapshot_is_actionable = self.snapshot.signal_type.value in actionable_values
        if snapshot_is_actionable != (self.signal_intent is not None):
            raise ValueError("actionable snapshot requires exactly one signal intent")

        if self.signal_intent is not None:
            if self.signal_intent.symbol != self.snapshot.symbol:
                raise ValueError("signal symbol must match snapshot")
            if self.signal_intent.plan_hash != self.snapshot.plan_hash:
                raise ValueError("signal plan hash must match snapshot")
            if self.signal_intent.next_step != self.next_step:
                raise ValueError("signal next step must match result next step")
            if self.signal_intent.trading_date != identity_date:
                raise ValueError("signal trading date must match evaluation identity")
            expected_signal = SignalType(self.signal_intent.signal_type.value)
            if self.snapshot.signal_type is not expected_signal:
                raise ValueError("snapshot signal type must match actionable signal")

        seen_transition_types: set[str] = set()
        for transition in self.transitions:
            if transition.intent_type in seen_transition_types:
                raise ValueError("result cannot contain duplicate transition types")
            seen_transition_types.add(transition.intent_type)
            state = (
                transition.episode
                if isinstance(transition, EpisodeTransitionIntent)
                else transition.risk
            )
            if state.symbol != self.snapshot.symbol or state.plan_hash != self.snapshot.plan_hash:
                raise ValueError("transition identity must match snapshot")
            if isinstance(transition, EpisodeTransitionIntent):
                if self.snapshot.episode != transition.episode:
                    raise ValueError("episode transition must match snapshot episode")
            elif self.snapshot.risk != transition.risk:
                raise ValueError("risk transition must match snapshot risk")

        if any(
            evidence.outcome is not ConditionOutcome.SATISFIED
            for evidence in self.satisfied_conditions
        ):
            raise ValueError("satisfied_conditions can contain only satisfied evidence")
        if any(
            evidence.outcome is ConditionOutcome.SATISFIED for evidence in self.unmet_conditions
        ):
            raise ValueError("unmet_conditions cannot contain satisfied evidence")
        if any(evidence.outcome is ConditionOutcome.SATISFIED for evidence in self.blockers):
            raise ValueError("blockers cannot contain satisfied evidence")
        partitioned_evidence = self.satisfied_conditions + self.unmet_conditions + self.blockers
        if self.snapshot.condition_evidence != partitioned_evidence:
            raise ValueError("result evidence partitions must match snapshot evidence")
        if self.signal_intent is not None:
            if any(
                evidence not in self.satisfied_conditions
                for evidence in self.signal_intent.matched_conditions
            ):
                raise ValueError("signal evidence must be part of satisfied result evidence")
        return self


class EvaluationResult(_EvaluationResultPayload):
    """Closed deterministic result with a self-validating canonical digest."""

    result_hash: Sha256Hex

    @classmethod
    def build(cls, **payload: object) -> Self:
        """Normalize one payload before attaching its deterministic digest."""

        if "result_hash" in payload:
            raise TypeError("build computes result_hash")
        normalized = _EvaluationResultPayload.model_validate(payload)
        normalized_payload = normalized.model_dump(mode="python", round_trip=True)
        digest = _evaluation_result_digest(normalized_payload)
        return cls.model_construct(
            **{name: getattr(normalized, name) for name in _EvaluationResultPayload.model_fields},
            result_hash=digest,
        )

    @model_validator(mode="after")
    def validate_result_hash(self) -> Self:
        expected_hash = _evaluation_result_digest(
            self.model_dump(
                mode="python",
                round_trip=True,
                exclude={"result_hash"},
            )
        )
        if self.result_hash != expected_hash:
            raise ValueError("result_hash must match the canonical result payload")
        return self


ConditionEvidence.model_rebuild()

__all__ = [
    "ActionableSignalType",
    "ConditionEvidence",
    "ConditionOutcome",
    "DailyIndicatorProvenance",
    "DailyIndicatorSnapshot",
    "DataHealthSnapshot",
    "DataHealthStatus",
    "DecisionZone",
    "EpisodeStatus",
    "EpisodeTransitionAction",
    "EpisodeTransitionIntent",
    "EvaluationContext",
    "EvaluationEvidence",
    "EvaluationIdentity",
    "EvaluationResult",
    "EvaluationTarget",
    "EvidenceFact",
    "EvidenceUnit",
    "IntradayEvaluationIdentity",
    "IntradayEvaluationTarget",
    "IndexConditionEvidence",
    "LowZoneEpisodeSnapshot",
    "MissingInputCode",
    "NextStep",
    "NextStepCode",
    "OfficialCloseEvaluationIdentity",
    "OfficialCloseEvaluationTarget",
    "PositionLotSnapshot",
    "PositionSummary",
    "RiskStateSnapshot",
    "RiskStatus",
    "RiskTransitionIntent",
    "RuleEvidence",
    "RuleEvidenceCode",
    "Sha256Hex",
    "SignalIntent",
    "SignalType",
    "StateTransitionIntent",
    "SymbolDecisionSnapshot",
]
