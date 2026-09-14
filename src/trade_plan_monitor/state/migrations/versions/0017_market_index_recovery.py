"""Persist bounded market-index recovery state.

Revision ID: 0017_market_index_recovery
Revises: 0016_explicit_plan_review
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_market_index_recovery"
down_revision: str | Sequence[str] | None = "0016_explicit_plan_review"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_index_recovery_state",
        sa.Column("index_code", sa.String(16), primary_key=True),
        sa.Column("decision_cutoff", sa.String(40), nullable=False),
        sa.Column("first_failed_at", sa.String(40), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("due_at", sa.String(40), nullable=False),
        sa.CheckConstraint("attempts BETWEEN 0 AND 2", name="ck_index_recovery_attempts"),
    )


def downgrade() -> None:
    active = op.get_bind().execute(
        sa.text("SELECT 1 FROM market_index_recovery_state LIMIT 1")
    ).scalar_one_or_none()
    if active is not None:
        raise RuntimeError("0017_market_index_recovery refuses to discard pending retries")
    op.drop_table("market_index_recovery_state")
