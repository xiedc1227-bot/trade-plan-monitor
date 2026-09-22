"""Index symbol-scoped inventory recovery without rewriting ledger data."""

from alembic import op

revision = "0021_inventory_history_index"
down_revision = "0020_lot_history_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_position_lot_symbol", "position_lot", ["symbol"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_position_lot_symbol", table_name="position_lot")
