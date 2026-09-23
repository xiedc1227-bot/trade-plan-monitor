"""Record local monitor liveness without rewriting historical business data."""

import sqlalchemy as sa
from alembic import op

revision = "0022_runtime_liveness"
down_revision = "0021_inventory_history_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_liveness",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("last_alive_at", sa.String(40), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_runtime_liveness_singleton"),
        sa.CheckConstraint("schema_version = 1", name="ck_runtime_liveness_schema"),
        sa.CheckConstraint("revision >= 0", name="ck_runtime_liveness_revision"),
    )


def downgrade() -> None:
    present = (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM runtime_liveness LIMIT 1"))
        .scalar_one_or_none()
    )
    if present is not None:
        raise RuntimeError("0022_runtime_liveness refuses to discard liveness evidence")
    op.drop_table("runtime_liveness")
