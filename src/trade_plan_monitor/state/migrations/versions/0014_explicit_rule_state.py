"""Persist activation-aware explicit results and repeat occurrence state.

Revision ID: 0014_explicit_rule_state
Revises: 0013_position_inventory
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_explicit_rule_state"
down_revision: str | Sequence[str] | None = "0013_position_inventory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "explicit_evaluation_ledger",
        sa.Column("plan_hash", sa.String(64), primary_key=True),
        sa.Column("symbol", sa.String(9), primary_key=True),
        sa.Column("target_value", sa.String(40), primary_key=True),
        sa.Column("execution_version", sa.String(32), primary_key=True),
        sa.Column("activation_revision", sa.Integer(), primary_key=True),
        sa.Column("result_hash", sa.String(64), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("inventory_revision", sa.Integer(), nullable=False),
        sa.Column("manual_event_risk_revision", sa.Integer(), nullable=True),
        sa.Column("evaluated_at", sa.String(40), nullable=False),
        sa.CheckConstraint(
            "execution_version = 'explicit-rules-v1'",
            name="ck_explicit_evaluation_execution_version",
        ),
        sa.CheckConstraint(
            "activation_revision >= 0 AND inventory_revision >= 0",
            name="ck_explicit_evaluation_revisions",
        ),
        sa.CheckConstraint(
            "manual_event_risk_revision IS NULL OR manual_event_risk_revision >= 0",
            name="ck_explicit_evaluation_manual_risk_revision",
        ),
        sa.CheckConstraint(
            "length(plan_hash) = 64 AND length(result_hash) = 64",
            name="ck_explicit_evaluation_hashes",
        ),
    )
    op.create_table(
        "explicit_rule_occurrence_state",
        sa.Column("plan_hash", sa.String(64), primary_key=True),
        sa.Column("symbol", sa.String(9), primary_key=True),
        sa.Column("activation_revision", sa.Integer(), primary_key=True),
        sa.Column("rule_id", sa.String(128), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("has_emitted", sa.Boolean(), nullable=False),
        sa.Column("last_emitted_bucket_end", sa.String(40), nullable=False),
        sa.CheckConstraint(
            "activation_revision >= 0 AND revision >= 1",
            name="ck_explicit_rule_occurrence_revisions",
        ),
        sa.CheckConstraint(
            "has_emitted = 1 AND last_emitted_bucket_end IS NOT NULL",
            name="ck_explicit_rule_occurrence_emitted",
        ),
    )


def downgrade() -> None:
    connection = op.get_bind()
    for table in ("explicit_rule_occurrence_state", "explicit_evaluation_ledger"):
        if connection.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).scalar_one_or_none():
            raise RuntimeError("0014_explicit_rule_state refuses to discard decision evidence")
    op.drop_table("explicit_rule_occurrence_state")
    op.drop_table("explicit_evaluation_ledger")
