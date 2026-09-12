"""Record edited AI content as an unapproved review provenance.

Revision ID: 0011_plan_review_content_invalidation
Revises: 0010_plan_review_binding
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_plan_review_content_invalidation"
down_revision: str | Sequence[str] | None = "0010_plan_review_binding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_provenance_table(name: str, *, include_ai_edited: bool) -> None:
    origins = "'LEGACY_PENDING', 'MANUAL', 'AI_EXTRACTION', 'AI_REIMPORT'"
    extracted = "'AI_EXTRACTION', 'AI_REIMPORT'"
    if include_ai_edited:
        origins = "'LEGACY_PENDING', 'MANUAL', 'AI_EXTRACTION', 'AI_EDITED', 'AI_REIMPORT'"
        extracted = "'AI_EXTRACTION', 'AI_EDITED', 'AI_REIMPORT'"
    op.create_table(
        name,
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
            f"origin IN ({origins})",
            name="ck_plan_review_provenance_origin",
        ),
        sa.CheckConstraint(
            "(origin IN ('LEGACY_PENDING', 'MANUAL') AND extraction_id IS NULL) OR "
            f"(origin IN ({extracted}) AND extraction_id IS NOT NULL)",
            name="ck_plan_review_provenance_extraction_identity",
        ),
    )


def _replace_provenance_table(*, include_ai_edited: bool) -> None:
    temporary = "plan_review_provenance_replacement"
    _create_provenance_table(temporary, include_ai_edited=include_ai_edited)
    op.get_bind().execute(
        sa.text(
            "INSERT INTO plan_review_provenance_replacement "
            "(plan_version_id, origin, extraction_id, source_hash, draft_hash, confirmed_at) "
            "SELECT plan_version_id, origin, extraction_id, source_hash, draft_hash, confirmed_at "
            "FROM plan_review_provenance"
        )
    )
    op.drop_table("plan_review_provenance")
    op.rename_table(temporary, "plan_review_provenance")


def upgrade() -> None:
    _replace_provenance_table(include_ai_edited=True)


def downgrade() -> None:
    has_edited_content = op.get_bind().execute(
        sa.text("SELECT 1 FROM plan_review_provenance WHERE origin = 'AI_EDITED' LIMIT 1")
    ).scalar_one_or_none()
    if has_edited_content is not None:
        raise RuntimeError("0011_plan_review_content_invalidation refuses to discard edit evidence")
    _replace_provenance_table(include_ai_edited=False)
