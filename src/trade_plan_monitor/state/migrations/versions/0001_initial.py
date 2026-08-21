"""Create the approved monitor-state baseline.

Revision ID: 0001_initial
Revises: None
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ID_LENGTH = 36
HASH_LENGTH = 64
SYMBOL_LENGTH = 9
TIMESTAMP_LENGTH = 40


def _id_column() -> sa.Column[str]:
    return sa.Column("id", sa.String(ID_LENGTH), primary_key=True)


def _timestamp_column(name: str, *, nullable: bool = False) -> sa.Column[str]:
    return sa.Column(name, sa.String(TIMESTAMP_LENGTH), nullable=nullable)


def _ohlc_columns() -> tuple[sa.Column[int], ...]:
    return (
        sa.Column("open_fen", sa.Integer(), nullable=False),
        sa.Column("high_fen", sa.Integer(), nullable=False),
        sa.Column("low_fen", sa.Integer(), nullable=False),
        sa.Column("close_fen", sa.Integer(), nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "plan_source",
        _id_column(),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("source_hash", sa.String(HASH_LENGTH), nullable=False),
        _timestamp_column("created_at"),
    )
    op.create_table(
        "alert_event",
        _id_column(),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("dedup_key", sa.String(HASH_LENGTH), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("message_text", sa.Text(), nullable=False),
        _timestamp_column("created_at"),
        _timestamp_column("acknowledged_at", nullable=True),
        sa.CheckConstraint("sequence >= 1", name="ck_alert_event_sequence_positive"),
        sa.UniqueConstraint("sequence", name="uq_alert_event_sequence"),
        sa.UniqueConstraint("dedup_key", name="uq_alert_event_dedup_key"),
    )
    op.create_table(
        "plan_version",
        _id_column(),
        sa.Column("plan_id", sa.String(128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(SYMBOL_LENGTH), nullable=False),
        sa.Column("plan_hash", sa.String(HASH_LENGTH), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column(
            "source_id",
            sa.String(ID_LENGTH),
            sa.ForeignKey("plan_source.id"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        _timestamp_column("created_at"),
        sa.CheckConstraint("version >= 1", name="ck_plan_version_version_positive"),
        sa.CheckConstraint("revision >= 0", name="ck_plan_version_revision_nonnegative"),
        sa.UniqueConstraint("plan_id", "version", name="uq_plan_version_identity"),
    )
    op.create_table(
        "active_plan",
        sa.Column("symbol", sa.String(SYMBOL_LENGTH), primary_key=True),
        sa.Column(
            "plan_version_id",
            sa.String(ID_LENGTH),
            sa.ForeignKey("plan_version.id"),
            nullable=False,
            unique=True,
        ),
        _timestamp_column("activated_at"),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint("revision >= 0", name="ck_active_plan_revision_nonnegative"),
    )
    op.create_table(
        "delivery_attempt",
        _id_column(),
        sa.Column(
            "event_id",
            sa.String(ID_LENGTH),
            sa.ForeignKey("alert_event.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("response_code", sa.Integer(), nullable=True),
        _timestamp_column("next_retry_at", nullable=True),
        _timestamp_column("delivered_at", nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.CheckConstraint("attempt >= 1", name="ck_delivery_attempt_attempt_positive"),
        sa.UniqueConstraint("event_id", "channel", "attempt", name="uq_delivery_attempt_identity"),
    )
    op.create_table(
        "position_lot",
        _id_column(),
        sa.Column("symbol", sa.String(SYMBOL_LENGTH), nullable=False),
        sa.Column("bucket", sa.String(16), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("remaining_qty", sa.Integer(), nullable=False),
        sa.Column("acquired_trade_date", sa.Date(), nullable=False),
        sa.Column("cost_fen", sa.Integer(), nullable=False),
        sa.Column(
            "related_alert_id",
            sa.String(ID_LENGTH),
            sa.ForeignKey("alert_event.id"),
            nullable=True,
        ),
        _timestamp_column("closed_at", nullable=True),
        sa.CheckConstraint("bucket IN ('CORE', 'TACTICAL')", name="ck_position_lot_bucket"),
        sa.CheckConstraint("quantity > 0", name="ck_position_lot_quantity_positive"),
        sa.CheckConstraint(
            "remaining_qty >= 0 AND remaining_qty <= quantity",
            name="ck_position_lot_remaining_range",
        ),
        sa.CheckConstraint("cost_fen > 0", name="ck_position_lot_cost_positive"),
    )
    op.create_table(
        "zone_episode",
        _id_column(),
        sa.Column("plan_hash", sa.String(HASH_LENGTH), nullable=False),
        sa.Column("symbol", sa.String(SYMBOL_LENGTH), nullable=False),
        sa.Column("zone", sa.String(64), nullable=False),
        _timestamp_column("started_at"),
        sa.Column("episode_low_fen", sa.Integer(), nullable=False),
        sa.Column("bars_since_low", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("alerted_signal", sa.String(64), nullable=True),
        sa.CheckConstraint("episode_low_fen > 0", name="ck_zone_episode_low_positive"),
        sa.CheckConstraint("bars_since_low >= 0", name="ck_zone_episode_bars_nonnegative"),
    )
    op.create_table(
        "risk_state",
        sa.Column("symbol", sa.String(SYMBOL_LENGTH), primary_key=True),
        sa.Column("plan_hash", sa.String(HASH_LENGTH), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("breach_trade_date", sa.Date(), nullable=True),
        sa.Column("prior_close_fen", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        _timestamp_column("updated_at"),
        sa.CheckConstraint("prior_close_fen > 0", name="ck_risk_state_close_positive"),
        sa.CheckConstraint("revision >= 0", name="ck_risk_state_revision_nonnegative"),
    )
    op.create_table(
        "evaluation_ledger",
        sa.Column("plan_hash", sa.String(HASH_LENGTH), primary_key=True),
        sa.Column("symbol", sa.String(SYMBOL_LENGTH), primary_key=True),
        sa.Column("bucket_end", sa.String(TIMESTAMP_LENGTH), primary_key=True),
        sa.Column("formula_version", sa.String(32), primary_key=True),
        sa.Column("result_hash", sa.String(HASH_LENGTH), nullable=False),
        _timestamp_column("evaluated_at"),
    )
    op.create_table(
        "provider_health",
        sa.Column("capability", sa.String(64), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False),
        _timestamp_column("checked_at"),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        _timestamp_column("next_retry_at", nullable=True),
        sa.CheckConstraint("latency_ms >= 0", name="ck_provider_health_latency_nonnegative"),
    )
    op.create_table(
        "symbol_health",
        sa.Column("symbol", sa.String(SYMBOL_LENGTH), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False),
        _timestamp_column("latest_bar_end", nullable=True),
        sa.Column("data_age_seconds", sa.Integer(), nullable=False),
        sa.Column("gap_json", sa.Text(), nullable=False),
        sa.Column("error_streak", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint("data_age_seconds >= 0", name="ck_symbol_health_age_nonnegative"),
        sa.CheckConstraint("error_streak >= 0", name="ck_symbol_health_streak_nonnegative"),
        sa.CheckConstraint("revision >= 0", name="ck_symbol_health_revision_nonnegative"),
    )
    op.create_table(
        "audit_log",
        _id_column(),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(128), nullable=False),
        sa.Column("before_hash", sa.String(HASH_LENGTH), nullable=True),
        sa.Column("after_hash", sa.String(HASH_LENGTH), nullable=True),
        sa.Column("details_json", sa.Text(), nullable=False),
        _timestamp_column("created_at"),
    )
    op.create_table(
        "minute_bar",
        sa.Column("symbol", sa.String(SYMBOL_LENGTH), primary_key=True),
        sa.Column("bar_end", sa.String(TIMESTAMP_LENGTH), primary_key=True),
        *_ohlc_columns(),
        sa.Column("volume_shares", sa.Integer(), nullable=False),
        sa.Column("amount_yuan", sa.String(128), nullable=False),
        _timestamp_column("received_at"),
        sa.CheckConstraint(
            "low_fen > 0 AND low_fen <= open_fen AND low_fen <= close_fen "
            "AND high_fen >= open_fen AND high_fen >= close_fen",
            name="ck_minute_bar_ohlc",
        ),
        sa.CheckConstraint("volume_shares >= 0", name="ck_minute_bar_volume_nonnegative"),
    )
    op.create_table(
        "five_minute_bar",
        sa.Column("symbol", sa.String(SYMBOL_LENGTH), primary_key=True),
        sa.Column("bar_end", sa.String(TIMESTAMP_LENGTH), primary_key=True),
        sa.Column("formula_version", sa.String(32), primary_key=True),
        *_ohlc_columns(),
        sa.Column("volume_shares", sa.Integer(), nullable=False),
        sa.Column("amount_yuan", sa.String(128), nullable=False),
        sa.CheckConstraint(
            "low_fen > 0 AND low_fen <= open_fen AND low_fen <= close_fen "
            "AND high_fen >= open_fen AND high_fen >= close_fen",
            name="ck_five_minute_bar_ohlc",
        ),
        sa.CheckConstraint("volume_shares >= 0", name="ck_five_minute_bar_volume_nonnegative"),
    )
    op.create_table(
        "daily_bar",
        sa.Column("symbol", sa.String(SYMBOL_LENGTH), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column(
            "is_official",
            sa.Boolean(),
            primary_key=True,
        ),
        *_ohlc_columns(),
        sa.Column("volume_shares", sa.Integer(), nullable=False),
        sa.Column("amount_yuan", sa.String(128), nullable=False),
        _timestamp_column("received_at"),
        sa.CheckConstraint("is_official IN (0, 1)", name="ck_daily_bar_is_official"),
        sa.CheckConstraint(
            "low_fen > 0 AND low_fen <= open_fen AND low_fen <= close_fen "
            "AND high_fen >= open_fen AND high_fen >= close_fen",
            name="ck_daily_bar_ohlc",
        ),
        sa.CheckConstraint("volume_shares >= 0", name="ck_daily_bar_volume_nonnegative"),
    )
    op.create_table(
        "trading_calendar",
        sa.Column("exchange", sa.String(8), primary_key=True),
        sa.Column("cal_date", sa.Date(), primary_key=True),
        sa.Column(
            "is_open",
            sa.Boolean(),
            nullable=False,
        ),
        sa.Column("previous_trade_date", sa.Date(), nullable=True),
        sa.CheckConstraint("is_open IN (0, 1)", name="ck_trading_calendar_is_open"),
    )
    op.create_table(
        "daily_price_limit",
        sa.Column("symbol", sa.String(SYMBOL_LENGTH), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("up_limit_fen", sa.Integer(), nullable=False),
        sa.Column("down_limit_fen", sa.Integer(), nullable=False),
        _timestamp_column("received_at"),
        sa.CheckConstraint(
            "down_limit_fen > 0 AND up_limit_fen > down_limit_fen",
            name="ck_daily_price_limit_range",
        ),
    )
    op.create_table(
        "latest_quote",
        sa.Column("symbol", sa.String(SYMBOL_LENGTH), primary_key=True),
        sa.Column("price_fen", sa.Integer(), nullable=False),
        sa.Column("bar_end", sa.String(TIMESTAMP_LENGTH), nullable=False),
        _timestamp_column("received_at"),
        sa.CheckConstraint("price_fen > 0", name="ck_latest_quote_price_positive"),
    )
    op.create_table(
        "request_idempotency",
        sa.Column("idempotency_key", sa.String(128), primary_key=True),
        sa.Column("request_hash", sa.String(HASH_LENGTH), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("response_code", sa.Integer(), nullable=True),
        sa.Column("response_json", sa.Text(), nullable=True),
        _timestamp_column("created_at"),
        _timestamp_column("updated_at"),
    )


def downgrade() -> None:
    for table_name in (
        "request_idempotency",
        "latest_quote",
        "daily_price_limit",
        "trading_calendar",
        "daily_bar",
        "five_minute_bar",
        "minute_bar",
        "audit_log",
        "symbol_health",
        "provider_health",
        "evaluation_ledger",
        "risk_state",
        "zone_episode",
        "position_lot",
        "delivery_attempt",
        "active_plan",
        "plan_version",
        "alert_event",
        "plan_source",
    ):
        op.drop_table(table_name)
