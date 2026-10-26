"""Add an isolated monetary-budget sidecar without rewriting quantity records."""

import sqlalchemy as sa
from alembic import op

revision = "0027_simulation_capital"
down_revision = "0026_market_exceptions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("simulation_capital_book",
        sa.Column("symbol", sa.String(9), primary_key=True),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("inventory_revision", sa.Integer, nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.CheckConstraint("revision > 0", name="ck_capital_book_revision"),
        sa.CheckConstraint("inventory_revision > 0", name="ck_capital_book_inventory"))
    op.create_table("simulation_capital_event",
        sa.Column("command_id", sa.String(128), primary_key=True),
        sa.Column("symbol", sa.String(9), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.CheckConstraint("revision > 0", name="ck_capital_event_revision"))
    op.create_index("ix_capital_event_symbol_time", "simulation_capital_event",
                    ["symbol", "created_at", "command_id"])


def downgrade():
    for table in ("simulation_capital_book", "simulation_capital_event"):
        if op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first() is not None:
            raise RuntimeError("0027 refuses to discard capital evidence")
    op.drop_index("ix_capital_event_symbol_time", table_name="simulation_capital_event")
    op.drop_table("simulation_capital_event")
    op.drop_table("simulation_capital_book")
