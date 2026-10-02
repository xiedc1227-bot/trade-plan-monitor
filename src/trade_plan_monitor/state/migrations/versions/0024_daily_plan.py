"""Add durable daily evidence and isolated simulation records."""

import sqlalchemy as sa
from alembic import op

revision = "0024_daily_plan"
down_revision = "0023_index_permission_scopes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_plan_record",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("symbol", sa.String(9), nullable=False),
        sa.Column("lineage", sa.String(128), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.CheckConstraint("revision >= 0", name="ck_daily_record_revision"),
        sa.CheckConstraint(
            "kind IN "
            "('SIGNAL','RISK','FACT','SIMULATION','REPORT','POSITION','EVALUATION','REVIEW','DRAFT','EXT"
            "RACTION','REASSESSMENT')",
            name="ck_daily_record_kind",
        ),
    )
    op.create_index("ix_daily_record_symbol_kind", "daily_plan_record", ["symbol", "kind"])
    op.create_index("ix_daily_record_lineage_kind", "daily_plan_record", ["lineage", "kind"])


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM daily_plan_record LIMIT 1"))
        .scalar_one_or_none()
        is not None
    ):
        raise RuntimeError("0024_daily_plan refuses to discard daily evidence or consumption")
    op.drop_table("daily_plan_record")
