"""Add the monotonic alert sequence high-water mark.

Revision ID: 0004_alert_sequence
Revises: 0003_episode_cursor
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_alert_sequence"
down_revision: str | Sequence[str] | None = "0003_episode_cursor"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alert_sequence",
        sa.Column("singleton_id", sa.Integer(), primary_key=True),
        sa.Column("last_sequence", sa.Integer(), nullable=False),
        sa.CheckConstraint("singleton_id = 1", name="ck_alert_sequence_singleton"),
        sa.CheckConstraint("last_sequence >= 0", name="ck_alert_sequence_nonnegative"),
    )
    op.get_bind().execute(
        sa.text(
            "INSERT INTO alert_sequence (singleton_id, last_sequence) "
            "SELECT 1, COALESCE(MAX(sequence), 0) FROM alert_event"
        )
    )


def downgrade() -> None:
    op.drop_table("alert_sequence")
