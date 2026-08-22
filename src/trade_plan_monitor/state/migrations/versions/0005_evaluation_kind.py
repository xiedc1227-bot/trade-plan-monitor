"""Add a lossless discriminator to persisted evaluation identities.

Revision ID: 0005_evaluation_kind
Revises: 0004_alert_sequence
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_evaluation_kind"
down_revision: str | Sequence[str] | None = "0004_alert_sequence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KIND_CHECK = "evaluation_kind IN ('INTRADAY', 'OFFICIAL_CLOSE')"
_TARGET_SHAPE_CHECK = (
    "(evaluation_kind = 'INTRADAY' "
    "AND length(target_value) = 25 "
    "AND substr(target_value, 11, 1) = 'T' "
    "AND substr(target_value, 20, 6) = '+08:00') "
    "OR (evaluation_kind = 'OFFICIAL_CLOSE' "
    "AND length(target_value) = 10 "
    "AND substr(target_value, 5, 1) = '-' "
    "AND substr(target_value, 8, 1) = '-')"
)


def upgrade() -> None:
    op.create_table(
        "evaluation_ledger_0005",
        sa.Column("plan_hash", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(9), nullable=False),
        sa.Column("evaluation_kind", sa.String(16), nullable=False),
        sa.Column("target_value", sa.String(40), nullable=False),
        sa.Column("formula_version", sa.String(32), nullable=False),
        sa.Column("result_hash", sa.String(64), nullable=False),
        sa.Column("evaluated_at", sa.String(40), nullable=False),
        sa.CheckConstraint(_KIND_CHECK, name="ck_evaluation_ledger_kind"),
        sa.CheckConstraint(
            _TARGET_SHAPE_CHECK,
            name="ck_evaluation_ledger_target_shape",
        ),
        sa.PrimaryKeyConstraint(
            "plan_hash",
            "symbol",
            "evaluation_kind",
            "target_value",
            "formula_version",
        ),
    )
    op.get_bind().execute(
        sa.text(
            "INSERT INTO evaluation_ledger_0005 "
            "(plan_hash, symbol, evaluation_kind, target_value, formula_version, "
            "result_hash, evaluated_at) "
            "SELECT plan_hash, symbol, 'INTRADAY', bucket_end, formula_version, "
            "result_hash, evaluated_at FROM evaluation_ledger"
        )
    )
    op.drop_table("evaluation_ledger")
    op.rename_table("evaluation_ledger_0005", "evaluation_ledger")


def downgrade() -> None:
    connection = op.get_bind()
    official_row = connection.execute(
        sa.text("SELECT 1 FROM evaluation_ledger WHERE evaluation_kind = 'OFFICIAL_CLOSE' LIMIT 1")
    ).scalar_one_or_none()
    if official_row is not None:
        raise RuntimeError("0005_evaluation_kind refuses to discard official-close identities")

    op.create_table(
        "evaluation_ledger_0004",
        sa.Column("plan_hash", sa.String(64), primary_key=True),
        sa.Column("symbol", sa.String(9), primary_key=True),
        sa.Column("bucket_end", sa.String(40), primary_key=True),
        sa.Column("formula_version", sa.String(32), primary_key=True),
        sa.Column("result_hash", sa.String(64), nullable=False),
        sa.Column("evaluated_at", sa.String(40), nullable=False),
    )
    connection.execute(
        sa.text(
            "INSERT INTO evaluation_ledger_0004 "
            "(plan_hash, symbol, bucket_end, formula_version, result_hash, evaluated_at) "
            "SELECT plan_hash, symbol, target_value, formula_version, result_hash, "
            "evaluated_at FROM evaluation_ledger WHERE evaluation_kind = 'INTRADAY'"
        )
    )
    op.drop_table("evaluation_ledger")
    op.rename_table("evaluation_ledger_0004", "evaluation_ledger")
