"""Persist inventory revisions only when an explicit trade candidate consumes them.

Revision ID: 0015_optional_inventory_rev
Revises: 0014_explicit_rule_state
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_optional_inventory_rev"
down_revision: str | Sequence[str] | None = "0014_explicit_rule_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("explicit_evaluation_ledger", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_explicit_evaluation_revisions", type_="check")
        batch_op.alter_column(
            "inventory_revision",
            existing_type=sa.Integer(),
            nullable=True,
        )
        batch_op.create_check_constraint(
            "ck_explicit_evaluation_revisions",
            "activation_revision >= 0 AND (inventory_revision IS NULL OR inventory_revision >= 0)",
        )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(
        sa.text("SELECT 1 FROM explicit_evaluation_ledger WHERE inventory_revision IS NULL LIMIT 1")
    ).scalar_one_or_none():
        raise RuntimeError(
            "Cannot downgrade while explicit results omit an unconsumed inventory revision"
        )
    with op.batch_alter_table("explicit_evaluation_ledger", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_explicit_evaluation_revisions", type_="check")
        batch_op.alter_column(
            "inventory_revision",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.create_check_constraint(
            "ck_explicit_evaluation_revisions",
            "activation_revision >= 0 AND inventory_revision >= 0",
        )
