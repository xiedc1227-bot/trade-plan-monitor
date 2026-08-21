"""Add the durable low-zone episode evaluation cursor.

Revision ID: 0003_episode_cursor
Revises: 0002_ai_provider_configuration
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_episode_cursor"
down_revision: str | Sequence[str] | None = "0002_ai_provider_configuration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    existing_episode = connection.execute(
        sa.text("SELECT 1 FROM zone_episode LIMIT 1")
    ).scalar_one_or_none()
    if existing_episode is not None:
        raise RuntimeError(
            "0003_episode_cursor refuses populated zone_episode; table must be empty"
        )

    with op.batch_alter_table("zone_episode") as batch_op:
        batch_op.add_column(sa.Column("last_processed_bucket_end", sa.String(40), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("zone_episode") as batch_op:
        batch_op.drop_column("last_processed_bucket_end")
