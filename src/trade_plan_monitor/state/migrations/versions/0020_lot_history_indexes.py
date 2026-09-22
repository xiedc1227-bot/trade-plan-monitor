"""Index bounded single-lot history reads without rewriting durable records.

Revision ID: 0020_lot_history_indexes
Revises: 0019_alert_delivery_eligibility
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0020_lot_history_indexes"
down_revision: str | Sequence[str] | None = "0019_alert_delivery_eligibility"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_audit_log_entity", "audit_log", ["entity_type", "entity_id"], unique=False)
    op.create_index(
        "ix_monitor_event_aggregate_sequence",
        "monitor_event",
        ["aggregate_id", "sequence"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_monitor_event_aggregate_sequence", table_name="monitor_event")
    op.drop_index("ix_audit_log_entity", table_name="audit_log")
