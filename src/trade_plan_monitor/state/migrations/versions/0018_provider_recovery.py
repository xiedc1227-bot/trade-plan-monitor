"""Persist bounded provider retry admission facts.

Revision ID: 0018_provider_recovery
Revises: 0017_market_index_recovery
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_provider_recovery"
down_revision: str | Sequence[str] | None = "0017_market_index_recovery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_recovery_checkpoint",
        sa.Column("provider_identity", sa.String(64), primary_key=True),
        sa.Column("kind", sa.String(16), primary_key=True),
        sa.Column("scope_key", sa.String(64), primary_key=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("retry_at", sa.String(40), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("reason_code", sa.String(32), nullable=False),
        sa.CheckConstraint("schema_version = 1", name="ck_provider_recovery_version"),
        sa.CheckConstraint("failures BETWEEN 0 AND 16", name="ck_provider_recovery_failures"),
        sa.CheckConstraint(
            "kind IN ('cooldown', 'permission', 'backoff')", name="ck_provider_recovery_kind"
        ),
    )


def downgrade() -> None:
    pending = (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM provider_recovery_checkpoint LIMIT 1"))
        .scalar_one_or_none()
    )
    if pending is not None:
        raise RuntimeError("0018_provider_recovery refuses to discard provider retry checkpoints")
    op.drop_table("provider_recovery_checkpoint")
