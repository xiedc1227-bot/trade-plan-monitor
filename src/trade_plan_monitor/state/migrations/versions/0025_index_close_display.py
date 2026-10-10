"""Separate latest index acquisition from effective display data."""

import sqlalchemy as sa
from alembic import op

revision = "0025_index_close_display"
down_revision = "0024_daily_plan"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_index_acquisition_state",
        sa.Column("mapping_version", sa.String(32), primary_key=True),
        sa.Column("index_code", sa.String(16), primary_key=True),
        sa.Column("attempt_id", sa.String(64), nullable=False),
        sa.Column("decision_cutoff", sa.String(40), nullable=False),
        sa.Column("request_set_hash", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.String(40), nullable=False),
        sa.Column(
            "snapshot_hash",
            sa.String(64),
            sa.ForeignKey("market_index_snapshot.snapshot_hash", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("health", sa.String(16), nullable=False),
        sa.Column("issues_json", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("source_identity", sa.String(64), nullable=True),
        sa.Column("effective_source_identity", sa.String(64), nullable=True),
        sa.Column("effective_snapshot_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "market_index_recovery_state",
        sa.Column("kind", sa.String(32), nullable=False, server_default="TRANSIENT"),
    )
    op.add_column(
        "market_index_recovery_state", sa.Column("source_identity", sa.String(64), nullable=True)
    )
    with op.batch_alter_table("market_index_recovery_state") as batch:
        batch.drop_constraint("ck_index_recovery_attempts", type_="check")
        batch.create_check_constraint("ck_index_recovery_attempts", "attempts BETWEEN 0 AND 3")


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM market_index_recovery_state "
                "WHERE kind != 'TRANSIENT' OR attempts > 2 LIMIT 1"
            )
        )
        .scalar_one_or_none()
        is not None
    ):
        raise RuntimeError("Cannot discard final-bucket retries")
    op.drop_column("market_index_recovery_state", "kind")
    op.drop_column("market_index_recovery_state", "source_identity")
    with op.batch_alter_table("market_index_recovery_state") as batch:
        batch.drop_constraint("ck_index_recovery_attempts", type_="check")
        batch.create_check_constraint("ck_index_recovery_attempts", "attempts BETWEEN 0 AND 2")
    op.drop_table("market_index_acquisition_state")
