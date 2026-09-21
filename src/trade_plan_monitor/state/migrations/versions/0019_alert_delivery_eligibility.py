"""Add isolated recovery delivery metadata without rewriting canonical events.

Revision ID: 0019_alert_delivery_eligibility
Revises: 0018_provider_recovery
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_alert_delivery_eligibility"
down_revision: str | Sequence[str] | None = "0018_provider_recovery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alert_delivery_eligibility",
        sa.Column("event_id", sa.String(36), sa.ForeignKey("alert_event.id"), primary_key=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("delivery_class", sa.String(32), nullable=False),
        sa.Column("source_cutoff", sa.String(40)),
        sa.Column("expires_at", sa.String(40)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("barrier_json", sa.Text()),
        sa.Column("result_hash", sa.String(64)),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.CheckConstraint("schema_version = 1", name="ck_delivery_eligibility_schema"),
        sa.CheckConstraint("revision >= 0", name="ck_delivery_eligibility_revision"),
        sa.CheckConstraint(
            "status IN ('HOLD', 'ELIGIBLE', 'SUPPRESS')",
            name="ck_delivery_eligibility_status",
        ),
        sa.CheckConstraint(
            "delivery_class IN ('INTRADAY_ACTIONABLE', 'STATE_RISK')",
            name="ck_delivery_eligibility_class",
        ),
        sa.CheckConstraint(
            "status != 'ELIGIBLE' OR (barrier_json IS NOT NULL AND result_hash IS NOT NULL)",
            name="ck_delivery_eligibility_evidence",
        ),
        sa.CheckConstraint(
            "delivery_class != 'STATE_RISK' OR expires_at IS NULL",
            name="ck_delivery_eligibility_risk_expiry",
        ),
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM alert_delivery_eligibility LIMIT 1"))
        .scalar_one_or_none()
        is not None
    ):
        raise RuntimeError("0019_alert_delivery_eligibility refuses to discard delivery metadata")
    op.drop_table("alert_delivery_eligibility")
