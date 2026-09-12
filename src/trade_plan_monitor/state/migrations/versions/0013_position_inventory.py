"""Persist complete inventory confirmations and ordinary opening balances.

Revision ID: 0013_position_inventory
Revises: 0012_manual_event_risk
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_position_inventory"
down_revision: str | Sequence[str] | None = "0012_manual_event_risk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "position_inventory_state",
        sa.Column("symbol", sa.String(9), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "revision >= 0",
            name="ck_position_inventory_state_revision",
        ),
    )
    op.create_table(
        "position_opening_balance",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("symbol", sa.String(9), nullable=False),
        sa.Column("original_qty", sa.Integer(), nullable=False),
        sa.Column("remaining_qty", sa.Integer(), nullable=False),
        sa.Column("sellable_from", sa.Date(), nullable=False),
        sa.Column("confirmation_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("closed_at", sa.String(40), nullable=True),
        sa.CheckConstraint(
            "original_qty > 0",
            name="ck_position_opening_balance_positive",
        ),
        sa.CheckConstraint(
            "remaining_qty >= 0 AND remaining_qty <= original_qty",
            name="ck_position_opening_balance_remaining",
        ),
        sa.CheckConstraint(
            "revision >= 0",
            name="ck_position_opening_balance_revision",
        ),
    )
    op.create_index(
        "ix_position_opening_balance_symbol",
        "position_opening_balance",
        ["symbol"],
    )
    op.create_table(
        "position_inventory_confirmation",
        sa.Column("symbol", sa.String(9), primary_key=True),
        sa.Column("confirmation_id", sa.String(36), nullable=False, unique=True),
        sa.Column("as_of_trade_date", sa.Date(), nullable=False),
        sa.Column("confirmed_at", sa.String(40), nullable=False),
        sa.Column("inventory_revision", sa.Integer(), nullable=False),
        sa.Column("total_qty", sa.Integer(), nullable=False),
        sa.Column("sellable_qty", sa.Integer(), nullable=False),
        sa.Column("included_lot_ids_json", sa.Text(), nullable=False),
        sa.Column("opening_balance_ids_json", sa.Text(), nullable=False),
        sa.Column("complete_registration", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "total_qty >= 0",
            name="ck_inventory_confirmation_total",
        ),
        sa.CheckConstraint(
            "sellable_qty >= 0 AND sellable_qty <= total_qty",
            name="ck_inventory_confirmation_sellable",
        ),
        sa.CheckConstraint(
            "inventory_revision >= 0",
            name="ck_inventory_confirmation_revision",
        ),
        sa.CheckConstraint(
            "complete_registration = 1",
            name="ck_inventory_confirmation_complete",
        ),
    )


def downgrade() -> None:
    connection = op.get_bind()
    for table in (
        "position_inventory_confirmation",
        "position_opening_balance",
        "position_inventory_state",
    ):
        if connection.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).scalar_one_or_none():
            raise RuntimeError("0013_position_inventory refuses to discard inventory evidence")
    op.drop_table("position_inventory_confirmation")
    op.drop_index("ix_position_opening_balance_symbol", table_name="position_opening_balance")
    op.drop_table("position_opening_balance")
    op.drop_table("position_inventory_state")
