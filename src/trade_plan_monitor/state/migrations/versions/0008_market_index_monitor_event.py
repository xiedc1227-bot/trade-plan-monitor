"""Allow the committed market-index invalidation event.

Revision ID: 0008_market_index_monitor_event
Revises: 0007_plan_web_state
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_market_index_monitor_event"
down_revision: str | Sequence[str] | None = "0007_plan_web_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_EVENT_TYPES = (
    "'symbol.snapshot.updated', "
    "'symbol.health.updated', "
    "'alert.created', "
    "'alert.acknowledged', "
    "'plan.extraction.updated', "
    "'plan.activated', "
    "'plan.deactivated', "
    "'position.updated', "
    "'ai.provider.updated', "
    "'system.health.updated'"
)
_EVENT_TYPES = f"{_OLD_EVENT_TYPES}, 'market.index.updated'"
_COPY_TABLE = "monitor_event_0008"


def upgrade() -> None:
    connection = op.get_bind()
    invalid_row = connection.execute(
        sa.text(f"SELECT 1 FROM monitor_event WHERE event_type NOT IN ({_EVENT_TYPES}) LIMIT 1")
    ).scalar_one_or_none()
    if invalid_row is not None:
        raise RuntimeError("0008_market_index_monitor_event found an invalid event type")
    _rebuild_monitor_event(_EVENT_TYPES)


def downgrade() -> None:
    connection = op.get_bind()
    market_index_row = connection.execute(
        sa.text("SELECT 1 FROM monitor_event WHERE event_type = 'market.index.updated' LIMIT 1")
    ).scalar_one_or_none()
    if market_index_row is not None:
        raise RuntimeError("0008_market_index_monitor_event refuses to discard market-index events")
    _rebuild_monitor_event(_OLD_EVENT_TYPES)


def _rebuild_monitor_event(event_types: str) -> None:
    connection = op.get_bind()
    expected_count = connection.execute(sa.text("SELECT COUNT(*) FROM monitor_event")).scalar_one()
    op.create_table(
        _COPY_TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("aggregate_id", sa.String(128), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("sequence", name="uq_monitor_event_sequence"),
        sa.CheckConstraint("sequence >= 1", name="ck_monitor_event_sequence_positive"),
        sa.CheckConstraint(
            f"event_type IN ({event_types})",
            name="ck_monitor_event_type",
        ),
        sa.CheckConstraint("schema_version = 1", name="ck_monitor_event_schema_version"),
    )
    connection.execute(
        sa.text(
            f"INSERT INTO {_COPY_TABLE} "
            "(id, sequence, event_type, schema_version, aggregate_id, payload_json, occurred_at) "
            "SELECT id, sequence, event_type, schema_version, aggregate_id, payload_json, "
            "occurred_at FROM monitor_event"
        )
    )
    copied_count = connection.execute(sa.text(f"SELECT COUNT(*) FROM {_COPY_TABLE}")).scalar_one()
    if copied_count != expected_count:
        raise RuntimeError("0008_market_index_monitor_event could not preserve the event ledger")
    op.drop_table("monitor_event")
    op.rename_table(_COPY_TABLE, "monitor_event")
