"""SQLAlchemy metadata for the monitor's approved SQLite baseline."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

ID_LENGTH = 36
HASH_LENGTH = 64
SYMBOL_LENGTH = 9
TIMESTAMP_LENGTH = 40


class PlanVersionStatus(StrEnum):
    """Lifecycle metadata for immutable plan-version payloads."""

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class IdempotencyStatus(StrEnum):
    """Durable request-claim lifecycle."""

    PENDING = "PENDING"
    COMPLETED = "COMPLETED"


class PositionBucket(StrEnum):
    """User-maintained lot bucket used by deterministic position policies."""

    CORE = "CORE"
    TACTICAL = "TACTICAL"


class SymbolHealthStatus(StrEnum):
    """Runtime-owned per-symbol health vocabulary persisted by strategy state."""

    STARTING = "STARTING"
    LIVE = "LIVE"
    STALE = "STALE"
    GAPPED = "GAPPED"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"
    CLOSE_PENDING = "CLOSE_PENDING"


class Base(DeclarativeBase):
    """Declarative base shared by all persistence models."""


class PlanSource(Base):
    __tablename__ = "plan_source"

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    source_text: Mapped[str] = mapped_column(Text)
    source_hash: Mapped[str] = mapped_column(String(HASH_LENGTH))
    created_at: Mapped[str] = mapped_column(String(TIMESTAMP_LENGTH))


class PlanVersion(Base):
    __tablename__ = "plan_version"
    __table_args__ = (
        UniqueConstraint("plan_id", "version", name="uq_plan_version_identity"),
        CheckConstraint("version >= 1", name="ck_plan_version_version_positive"),
        CheckConstraint("revision >= 0", name="ck_plan_version_revision_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(128))
    version: Mapped[int] = mapped_column(Integer)
    symbol: Mapped[str] = mapped_column(String(SYMBOL_LENGTH))
    plan_hash: Mapped[str] = mapped_column(String(HASH_LENGTH))
    status: Mapped[str] = mapped_column(String(32))
    payload_json: Mapped[str] = mapped_column(Text)
    source_id: Mapped[str] = mapped_column(ForeignKey("plan_source.id"))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(TIMESTAMP_LENGTH))


class ActivePlan(Base):
    __tablename__ = "active_plan"
    __table_args__ = (CheckConstraint("revision >= 0", name="ck_active_plan_revision_nonnegative"),)

    symbol: Mapped[str] = mapped_column(String(SYMBOL_LENGTH), primary_key=True)
    plan_version_id: Mapped[str] = mapped_column(ForeignKey("plan_version.id"), unique=True)
    activated_at: Mapped[str] = mapped_column(String(TIMESTAMP_LENGTH))
    revision: Mapped[int] = mapped_column(Integer, default=0)


class AlertEvent(Base):
    __tablename__ = "alert_event"
    __table_args__ = (
        UniqueConstraint("sequence", name="uq_alert_event_sequence"),
        UniqueConstraint("dedup_key", name="uq_alert_event_dedup_key"),
        CheckConstraint("sequence >= 1", name="ck_alert_event_sequence_positive"),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    sequence: Mapped[int] = mapped_column(Integer)
    dedup_key: Mapped[str] = mapped_column(String(HASH_LENGTH))
    payload_json: Mapped[str] = mapped_column(Text)
    message_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(TIMESTAMP_LENGTH))
    acknowledged_at: Mapped[str | None] = mapped_column(String(TIMESTAMP_LENGTH))


class DeliveryAttempt(Base):
    __tablename__ = "delivery_attempt"
    __table_args__ = (
        UniqueConstraint(
            "event_id",
            "channel",
            "attempt",
            name="uq_delivery_attempt_identity",
        ),
        CheckConstraint("attempt >= 1", name="ck_delivery_attempt_attempt_positive"),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("alert_event.id", ondelete="CASCADE"))
    channel: Mapped[str] = mapped_column(String(16))
    attempt: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32))
    response_code: Mapped[int | None] = mapped_column(Integer)
    next_retry_at: Mapped[str | None] = mapped_column(String(TIMESTAMP_LENGTH))
    delivered_at: Mapped[str | None] = mapped_column(String(TIMESTAMP_LENGTH))
    error_code: Mapped[str | None] = mapped_column(String(64))


class PositionLot(Base):
    __tablename__ = "position_lot"
    __table_args__ = (
        CheckConstraint("bucket IN ('CORE', 'TACTICAL')", name="ck_position_lot_bucket"),
        CheckConstraint("quantity > 0", name="ck_position_lot_quantity_positive"),
        CheckConstraint(
            "remaining_qty >= 0 AND remaining_qty <= quantity",
            name="ck_position_lot_remaining_range",
        ),
        CheckConstraint("cost_fen > 0", name="ck_position_lot_cost_positive"),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(SYMBOL_LENGTH))
    bucket: Mapped[str] = mapped_column(String(16))
    quantity: Mapped[int] = mapped_column(Integer)
    remaining_qty: Mapped[int] = mapped_column(Integer)
    acquired_trade_date: Mapped[date] = mapped_column(Date)
    cost_fen: Mapped[int] = mapped_column(Integer)
    related_alert_id: Mapped[str | None] = mapped_column(ForeignKey("alert_event.id"))
    closed_at: Mapped[str | None] = mapped_column(String(TIMESTAMP_LENGTH))


class ZoneEpisode(Base):
    __tablename__ = "zone_episode"
    __table_args__ = (
        CheckConstraint("episode_low_fen > 0", name="ck_zone_episode_low_positive"),
        CheckConstraint("bars_since_low >= 0", name="ck_zone_episode_bars_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    plan_hash: Mapped[str] = mapped_column(String(HASH_LENGTH))
    symbol: Mapped[str] = mapped_column(String(SYMBOL_LENGTH))
    zone: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[str] = mapped_column(String(TIMESTAMP_LENGTH))
    episode_low_fen: Mapped[int] = mapped_column(Integer)
    bars_since_low: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32))
    alerted_signal: Mapped[str | None] = mapped_column(String(64))


class RiskState(Base):
    __tablename__ = "risk_state"
    __table_args__ = (
        CheckConstraint("prior_close_fen > 0", name="ck_risk_state_close_positive"),
        CheckConstraint("revision >= 0", name="ck_risk_state_revision_nonnegative"),
    )

    symbol: Mapped[str] = mapped_column(String(SYMBOL_LENGTH), primary_key=True)
    plan_hash: Mapped[str] = mapped_column(String(HASH_LENGTH))
    status: Mapped[str] = mapped_column(String(32))
    breach_trade_date: Mapped[date | None] = mapped_column(Date)
    prior_close_fen: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[str] = mapped_column(String(TIMESTAMP_LENGTH))


class EvaluationLedger(Base):
    __tablename__ = "evaluation_ledger"

    plan_hash: Mapped[str] = mapped_column(String(HASH_LENGTH), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(SYMBOL_LENGTH), primary_key=True)
    bucket_end: Mapped[str] = mapped_column(String(TIMESTAMP_LENGTH), primary_key=True)
    formula_version: Mapped[str] = mapped_column(String(32), primary_key=True)
    result_hash: Mapped[str] = mapped_column(String(HASH_LENGTH))
    evaluated_at: Mapped[str] = mapped_column(String(TIMESTAMP_LENGTH))


class AIProviderConfiguration(Base):
    """Persist only non-secret AI settings and secret lookup references."""

    __tablename__ = "ai_provider_configuration"
    __table_args__ = (
        CheckConstraint(
            "provider_type = 'OPENAI_COMPATIBLE'",
            name="ck_ai_provider_configuration_type",
        ),
        CheckConstraint(
            "key_ref GLOB 'ai/provider/*' AND length(key_ref) BETWEEN 13 AND 140",
            name="ck_ai_provider_configuration_key_ref",
        ),
        CheckConstraint(
            "environment_variable IS NULL OR ("
            "length(environment_variable) BETWEEN 1 AND 128 "
            "AND environment_variable NOT GLOB '*[^A-Za-z0-9_]*' "
            "AND substr(environment_variable, 1, 1) GLOB '[A-Za-z_]')",
            name="ck_ai_provider_configuration_environment_ref",
        ),
        CheckConstraint(
            "timeout_seconds BETWEEN 1 AND 120",
            name="ck_ai_provider_configuration_timeout",
        ),
        CheckConstraint(
            "max_retries BETWEEN 0 AND 2",
            name="ck_ai_provider_configuration_retries",
        ),
        CheckConstraint(
            "max_input_chars BETWEEN 1 AND 200000",
            name="ck_ai_provider_configuration_input_chars",
        ),
        CheckConstraint(
            "max_output_tokens BETWEEN 1 AND 16384",
            name="ck_ai_provider_configuration_output_tokens",
        ),
        CheckConstraint(
            "temperature_milli BETWEEN 0 AND 300",
            name="ck_ai_provider_configuration_temperature",
        ),
        CheckConstraint("enabled IN (0, 1)", name="ck_ai_provider_configuration_enabled"),
        CheckConstraint("revision >= 0", name="ck_ai_provider_configuration_revision"),
    )

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100))
    provider_type: Mapped[str] = mapped_column(String(32))
    base_url: Mapped[str] = mapped_column(String(2048))
    model_name: Mapped[str] = mapped_column(String(200))
    key_ref: Mapped[str] = mapped_column(String(140))
    environment_variable: Mapped[str | None] = mapped_column(String(128))
    timeout_seconds: Mapped[int] = mapped_column(Integer)
    max_retries: Mapped[int] = mapped_column(Integer)
    max_input_chars: Mapped[int] = mapped_column(Integer)
    max_output_tokens: Mapped[int] = mapped_column(Integer)
    temperature_milli: Mapped[int] = mapped_column(Integer)
    prompt_version: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(TIMESTAMP_LENGTH))
    updated_at: Mapped[str] = mapped_column(String(TIMESTAMP_LENGTH))


class ProviderHealth(Base):
    __tablename__ = "provider_health"
    __table_args__ = (
        CheckConstraint("latency_ms >= 0", name="ck_provider_health_latency_nonnegative"),
    )

    capability: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32))
    checked_at: Mapped[str] = mapped_column(String(TIMESTAMP_LENGTH))
    latency_ms: Mapped[int] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(64))
    next_retry_at: Mapped[str | None] = mapped_column(String(TIMESTAMP_LENGTH))


class SymbolHealth(Base):
    __tablename__ = "symbol_health"
    __table_args__ = (
        CheckConstraint("data_age_seconds >= 0", name="ck_symbol_health_age_nonnegative"),
        CheckConstraint("error_streak >= 0", name="ck_symbol_health_streak_nonnegative"),
        CheckConstraint("revision >= 0", name="ck_symbol_health_revision_nonnegative"),
    )

    symbol: Mapped[str] = mapped_column(String(SYMBOL_LENGTH), primary_key=True)
    status: Mapped[str] = mapped_column(String(32))
    latest_bar_end: Mapped[str | None] = mapped_column(String(TIMESTAMP_LENGTH))
    data_age_seconds: Mapped[int] = mapped_column(Integer)
    gap_json: Mapped[str] = mapped_column(Text)
    error_streak: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer, default=0)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(128))
    before_hash: Mapped[str | None] = mapped_column(String(HASH_LENGTH))
    after_hash: Mapped[str | None] = mapped_column(String(HASH_LENGTH))
    details_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(TIMESTAMP_LENGTH))


class MinuteBar(Base):
    __tablename__ = "minute_bar"
    __table_args__ = (
        CheckConstraint(
            "low_fen > 0 AND low_fen <= open_fen AND low_fen <= close_fen "
            "AND high_fen >= open_fen AND high_fen >= close_fen",
            name="ck_minute_bar_ohlc",
        ),
        CheckConstraint("volume_shares >= 0", name="ck_minute_bar_volume_nonnegative"),
    )

    symbol: Mapped[str] = mapped_column(String(SYMBOL_LENGTH), primary_key=True)
    bar_end: Mapped[str] = mapped_column(String(TIMESTAMP_LENGTH), primary_key=True)
    open_fen: Mapped[int] = mapped_column(Integer)
    high_fen: Mapped[int] = mapped_column(Integer)
    low_fen: Mapped[int] = mapped_column(Integer)
    close_fen: Mapped[int] = mapped_column(Integer)
    volume_shares: Mapped[int] = mapped_column(Integer)
    amount_yuan: Mapped[str] = mapped_column(String(128))
    received_at: Mapped[str] = mapped_column(String(TIMESTAMP_LENGTH))


class FiveMinuteBar(Base):
    __tablename__ = "five_minute_bar"
    __table_args__ = (
        CheckConstraint(
            "low_fen > 0 AND low_fen <= open_fen AND low_fen <= close_fen "
            "AND high_fen >= open_fen AND high_fen >= close_fen",
            name="ck_five_minute_bar_ohlc",
        ),
        CheckConstraint("volume_shares >= 0", name="ck_five_minute_bar_volume_nonnegative"),
    )

    symbol: Mapped[str] = mapped_column(String(SYMBOL_LENGTH), primary_key=True)
    bar_end: Mapped[str] = mapped_column(String(TIMESTAMP_LENGTH), primary_key=True)
    formula_version: Mapped[str] = mapped_column(String(32), primary_key=True)
    open_fen: Mapped[int] = mapped_column(Integer)
    high_fen: Mapped[int] = mapped_column(Integer)
    low_fen: Mapped[int] = mapped_column(Integer)
    close_fen: Mapped[int] = mapped_column(Integer)
    volume_shares: Mapped[int] = mapped_column(Integer)
    amount_yuan: Mapped[str] = mapped_column(String(128))


class DailyBar(Base):
    __tablename__ = "daily_bar"
    __table_args__ = (
        CheckConstraint("is_official IN (0, 1)", name="ck_daily_bar_is_official"),
        CheckConstraint(
            "low_fen > 0 AND low_fen <= open_fen AND low_fen <= close_fen "
            "AND high_fen >= open_fen AND high_fen >= close_fen",
            name="ck_daily_bar_ohlc",
        ),
        CheckConstraint("volume_shares >= 0", name="ck_daily_bar_volume_nonnegative"),
    )

    symbol: Mapped[str] = mapped_column(String(SYMBOL_LENGTH), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    is_official: Mapped[bool] = mapped_column(Boolean, primary_key=True)
    open_fen: Mapped[int] = mapped_column(Integer)
    high_fen: Mapped[int] = mapped_column(Integer)
    low_fen: Mapped[int] = mapped_column(Integer)
    close_fen: Mapped[int] = mapped_column(Integer)
    volume_shares: Mapped[int] = mapped_column(Integer)
    amount_yuan: Mapped[str] = mapped_column(String(128))
    received_at: Mapped[str] = mapped_column(String(TIMESTAMP_LENGTH))


class TradingCalendar(Base):
    __tablename__ = "trading_calendar"
    __table_args__ = (CheckConstraint("is_open IN (0, 1)", name="ck_trading_calendar_is_open"),)

    exchange: Mapped[str] = mapped_column(String(8), primary_key=True)
    cal_date: Mapped[date] = mapped_column(Date, primary_key=True)
    is_open: Mapped[bool] = mapped_column(Boolean)
    previous_trade_date: Mapped[date | None] = mapped_column(Date)


class DailyPriceLimit(Base):
    __tablename__ = "daily_price_limit"
    __table_args__ = (
        CheckConstraint(
            "down_limit_fen > 0 AND up_limit_fen > down_limit_fen",
            name="ck_daily_price_limit_range",
        ),
    )

    symbol: Mapped[str] = mapped_column(String(SYMBOL_LENGTH), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    up_limit_fen: Mapped[int] = mapped_column(Integer)
    down_limit_fen: Mapped[int] = mapped_column(Integer)
    received_at: Mapped[str] = mapped_column(String(TIMESTAMP_LENGTH))


class LatestQuote(Base):
    __tablename__ = "latest_quote"
    __table_args__ = (CheckConstraint("price_fen > 0", name="ck_latest_quote_price_positive"),)

    symbol: Mapped[str] = mapped_column(String(SYMBOL_LENGTH), primary_key=True)
    price_fen: Mapped[int] = mapped_column(Integer)
    bar_end: Mapped[str] = mapped_column(String(TIMESTAMP_LENGTH))
    received_at: Mapped[str] = mapped_column(String(TIMESTAMP_LENGTH))


class RequestIdempotency(Base):
    __tablename__ = "request_idempotency"

    idempotency_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(HASH_LENGTH))
    status: Mapped[str] = mapped_column(String(32))
    response_code: Mapped[int | None] = mapped_column(Integer)
    response_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(TIMESTAMP_LENGTH))
    updated_at: Mapped[str] = mapped_column(String(TIMESTAMP_LENGTH))


__all__ = [
    "ActivePlan",
    "AIProviderConfiguration",
    "AlertEvent",
    "AuditLog",
    "Base",
    "DailyBar",
    "DailyPriceLimit",
    "DeliveryAttempt",
    "EvaluationLedger",
    "FiveMinuteBar",
    "LatestQuote",
    "MinuteBar",
    "PlanSource",
    "PlanVersion",
    "PlanVersionStatus",
    "PositionBucket",
    "PositionLot",
    "ProviderHealth",
    "RequestIdempotency",
    "IdempotencyStatus",
    "RiskState",
    "SymbolHealth",
    "SymbolHealthStatus",
    "TradingCalendar",
    "ZoneEpisode",
]
