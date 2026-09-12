"""Persist scoped manual event-risk confirmations.

Revision ID: 0012_manual_event_risk
Revises: 0011_plan_review_content_invalidation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_manual_event_risk"
down_revision: str | Sequence[str] | None = "0011_plan_review_content_invalidation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "manual_event_risk",
        sa.Column("symbol", sa.String(9), primary_key=True),
        sa.Column("plan_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("expires_on", sa.Date(), nullable=False),
        sa.Column("confirmed_at", sa.String(40), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "status IN ('CLEAR', 'RISK_PRESENT')",
            name="ck_manual_event_risk_status",
        ),
        sa.CheckConstraint(
            "revision >= 0",
            name="ck_manual_event_risk_revision_nonnegative",
        ),
    )


def downgrade() -> None:
    has_confirmation = op.get_bind().execute(
        sa.text("SELECT 1 FROM manual_event_risk LIMIT 1")
    ).scalar_one_or_none()
    if has_confirmation is not None:
        raise RuntimeError("0012_manual_event_risk refuses to discard confirmation audit evidence")
    op.drop_table("manual_event_risk")
