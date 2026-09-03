"""Add durable plan review and activation state for the Web application.

Revision ID: 0007_plan_web_state
Revises: 0006_monitor_event
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_plan_web_state"
down_revision: str | Sequence[str] | None = "0006_monitor_event"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plan_version_review",
        sa.Column(
            "plan_version_id",
            sa.String(36),
            sa.ForeignKey("plan_version.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("review_issues_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "plan_activation_state",
        sa.Column("symbol", sa.String(9), primary_key=True),
        sa.Column(
            "plan_version_id",
            sa.String(36),
            sa.ForeignKey("plan_version.id"),
            nullable=True,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("changed_at", sa.String(40), nullable=False),
        sa.CheckConstraint("revision >= 0", name="ck_plan_activation_state_revision_nonnegative"),
    )

    connection = op.get_bind()
    connection.execute(
        sa.text(
            "INSERT INTO plan_version_review (plan_version_id, review_issues_json) "
            "SELECT id, '[]' FROM plan_version"
        )
    )
    connection.execute(
        sa.text(
            "INSERT INTO plan_activation_state "
            "(symbol, plan_version_id, revision, changed_at) "
            "SELECT symbol, plan_version_id, revision, activated_at FROM active_plan"
        )
    )
    connection.execute(
        sa.text(
            "INSERT INTO plan_activation_state "
            "(symbol, plan_version_id, revision, changed_at) "
            "SELECT plan_version.symbol, NULL, 0, MIN(plan_version.created_at) "
            "FROM plan_version "
            "LEFT JOIN plan_activation_state "
            "ON plan_activation_state.symbol = plan_version.symbol "
            "WHERE plan_activation_state.symbol IS NULL "
            "GROUP BY plan_version.symbol"
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    lossy_review = connection.execute(
        sa.text(
            "SELECT 1 FROM plan_version AS version "
            "LEFT JOIN plan_version_review AS review "
            "ON review.plan_version_id = version.id "
            "WHERE review.plan_version_id IS NULL "
            "OR review.review_issues_json != '[]' "
            "UNION ALL "
            "SELECT 1 FROM plan_version_review AS review "
            "LEFT JOIN plan_version AS version "
            "ON version.id = review.plan_version_id "
            "WHERE version.id IS NULL LIMIT 1"
        )
    ).scalar_one_or_none()
    lossy_activation = connection.execute(
        sa.text(
            "SELECT 1 FROM plan_activation_state AS state "
            "LEFT JOIN active_plan AS active ON active.symbol = state.symbol "
            "LEFT JOIN ("
            "SELECT symbol, MIN(created_at) AS first_created_at "
            "FROM plan_version GROUP BY symbol"
            ") AS first_plan ON first_plan.symbol = state.symbol "
            "WHERE (active.symbol IS NOT NULL AND ("
            "state.plan_version_id IS NOT active.plan_version_id "
            "OR state.revision != active.revision "
            "OR state.changed_at != active.activated_at"
            ")) OR (active.symbol IS NULL AND ("
            "state.plan_version_id IS NOT NULL "
            "OR state.revision != 0 "
            "OR first_plan.symbol IS NULL "
            "OR state.changed_at != first_plan.first_created_at"
            ")) "
            "UNION ALL "
            "SELECT 1 FROM active_plan AS active "
            "LEFT JOIN plan_activation_state AS state ON state.symbol = active.symbol "
            "WHERE state.symbol IS NULL "
            "UNION ALL "
            "SELECT 1 FROM (SELECT DISTINCT symbol FROM plan_version) AS plan_symbol "
            "LEFT JOIN plan_activation_state AS state "
            "ON state.symbol = plan_symbol.symbol "
            "WHERE state.symbol IS NULL LIMIT 1"
        )
    ).scalar_one_or_none()
    if lossy_review is not None or lossy_activation is not None:
        raise RuntimeError("0007_plan_web_state refuses to discard plan Web state")
    op.drop_table("plan_activation_state")
    op.drop_table("plan_version_review")
