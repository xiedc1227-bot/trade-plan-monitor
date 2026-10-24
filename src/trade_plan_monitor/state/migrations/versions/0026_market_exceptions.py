"""Permit additive exception evidence kinds without rewriting payload bytes."""

import sqlalchemy as sa
from alembic import op

revision = "0026_market_exceptions"
down_revision = "0025_index_close_display"
branch_labels = None
depends_on = None

OLD = (
    "'SIGNAL','RISK','FACT','SIMULATION','REPORT','POSITION','EVALUATION','REVIEW','DRAFT',"
    "'EXTRACTION','REASSESSMENT'"
)
NEW = "'EXCEPTION_CANDIDATE','EXCEPTION_EVENT','EXCEPTION_PREVIEW'"


def _replace(kinds):
    with op.batch_alter_table("daily_plan_record") as batch:
        batch.drop_constraint("ck_daily_record_kind", type_="check")
        batch.create_check_constraint("ck_daily_record_kind", "kind IN (" + kinds + ")")


def upgrade():
    _replace(OLD + "," + NEW)
    op.execute("CREATE UNIQUE INDEX ux_exception_command ON daily_plan_record "
               "(json_extract(payload_json, '$.command_id')) WHERE kind = 'EXCEPTION_EVENT'")


def downgrade():
    if op.get_bind().execute(sa.text(
            "SELECT 1 FROM daily_plan_record WHERE kind IN (" + NEW + ") LIMIT 1"
    )).scalar_one_or_none() is not None:
        raise RuntimeError("0026_market_exceptions refuses to discard exception evidence")
    op.drop_index("ux_exception_command", table_name="daily_plan_record")
    _replace(OLD)
