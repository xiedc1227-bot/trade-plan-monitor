"""Bind server-owned extraction review facts to immutable plan versions.

Revision ID: 0010_plan_review_binding
Revises: 0009_live_monitor_projection
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_plan_review_binding"
down_revision: str | Sequence[str] | None = "0009_live_monitor_projection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plan_extraction_review",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider_id", sa.String(36), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("draft_hash", sa.String(64), nullable=False),
        sa.Column("review_issues_json", sa.Text(), nullable=False),
        sa.Column("completed_at", sa.String(40), nullable=False),
    )
    op.create_index(
        "ix_plan_extraction_review_draft_hash",
        "plan_extraction_review",
        ["draft_hash"],
    )
    op.create_table(
        "plan_review_provenance",
        sa.Column(
            "plan_version_id",
            sa.String(36),
            sa.ForeignKey("plan_version.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("origin", sa.String(32), nullable=False),
        sa.Column(
            "extraction_id",
            sa.String(36),
            sa.ForeignKey("plan_extraction_review.id"),
            nullable=True,
        ),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("draft_hash", sa.String(64), nullable=False),
        sa.Column("confirmed_at", sa.String(40), nullable=True),
        sa.CheckConstraint(
            "origin IN ('LEGACY_PENDING', 'MANUAL', 'AI_EXTRACTION', 'AI_REIMPORT')",
            name="ck_plan_review_provenance_origin",
        ),
        sa.CheckConstraint(
            "(origin IN ('LEGACY_PENDING', 'MANUAL') AND extraction_id IS NULL) OR "
            "(origin IN ('AI_EXTRACTION', 'AI_REIMPORT') AND extraction_id IS NOT NULL)",
            name="ck_plan_review_provenance_extraction_identity",
        ),
    )

    op.get_bind().execute(
        sa.text(
            "INSERT INTO plan_review_provenance "
            "(plan_version_id, origin, extraction_id, source_hash, draft_hash, confirmed_at) "
            "SELECT version.id, 'LEGACY_PENDING', NULL, source.source_hash, "
            "version.plan_hash, NULL "
            "FROM plan_version AS version "
            "JOIN plan_source AS source ON source.id = version.source_id"
        )
    )


def downgrade() -> None:
    lossy = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 WHERE "
                "EXISTS (SELECT 1 FROM plan_extraction_review) OR EXISTS ("
                "SELECT 1 FROM plan_review_provenance AS provenance "
                "JOIN plan_version AS version ON version.id = provenance.plan_version_id "
                "JOIN plan_source AS source ON source.id = version.source_id "
                "WHERE provenance.origin NOT IN ('LEGACY_PENDING', 'MANUAL') "
                "OR provenance.extraction_id IS NOT NULL "
                "OR provenance.confirmed_at IS NOT NULL "
                "OR provenance.source_hash != source.source_hash "
                "OR provenance.draft_hash != version.plan_hash)"
            )
        )
        .scalar_one_or_none()
    )
    if lossy is not None:
        raise RuntimeError("0010_plan_review_binding refuses to discard plan review evidence")
    op.drop_table("plan_review_provenance")
    op.drop_index(
        "ix_plan_extraction_review_draft_hash",
        table_name="plan_extraction_review",
    )
    op.drop_table("plan_extraction_review")
