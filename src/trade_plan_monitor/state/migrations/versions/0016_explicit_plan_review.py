"""Persist v4 mappings and current-content explicit-plan confirmations.

Revision ID: 0016_explicit_plan_review
Revises: 0015_optional_inventory_rev
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_explicit_plan_review"
down_revision: str | Sequence[str] | None = "0015_optional_inventory_rev"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("plan_extraction_review", "plan_review_provenance"):
        op.add_column(table, sa.Column("mapping_json", sa.Text(), nullable=True))
        op.add_column(table, sa.Column("content_hash", sa.String(64), nullable=True))
        op.add_column(table, sa.Column("review_evidence_hash", sa.String(64), nullable=True))
        op.add_column(table, sa.Column("required_issues_json", sa.Text(), nullable=True))
    op.add_column(
        "plan_review_provenance",
        sa.Column("resolutions_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "plan_review_provenance",
        sa.Column("review_id", sa.String(36), nullable=True),
    )
    op.add_column(
        "plan_review_provenance",
        sa.Column("review_revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "uq_plan_review_provenance_review_id",
        "plan_review_provenance",
        ["review_id"],
        unique=True,
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(
        sa.text(
            "SELECT 1 FROM plan_review_provenance "
            "WHERE content_hash IS NOT NULL OR review_id IS NOT NULL LIMIT 1"
        )
    ).scalar_one_or_none() is not None:
        raise RuntimeError("0016_explicit_plan_review refuses to discard explicit review evidence")
    op.drop_index(
        "uq_plan_review_provenance_review_id",
        table_name="plan_review_provenance",
    )
    for column in (
        "review_revision",
        "review_id",
        "resolutions_json",
        "required_issues_json",
        "review_evidence_hash",
        "content_hash",
        "mapping_json",
    ):
        op.drop_column("plan_review_provenance", column)
    for column in (
        "required_issues_json",
        "review_evidence_hash",
        "content_hash",
        "mapping_json",
    ):
        op.drop_column("plan_extraction_review", column)
