"""Permit private BUY suspension records without changing existing evidence."""

import sqlalchemy as sa
from alembic import op

revision = "0030_buy_suspension"
down_revision = "0029_native_fact_lookup"
branch_labels = None
depends_on = None

OLD = (
    "'SIGNAL','RISK','FACT','SIMULATION','REPORT','POSITION','EVALUATION','REVIEW','DRAFT',"
    "'EXTRACTION','REASSESSMENT','EXCEPTION_CANDIDATE','EXCEPTION_EVENT','EXCEPTION_PREVIEW'"
)


def _replace(kinds):
    connection = op.get_bind()
    indexes = connection.execute(sa.text(
        "SELECT name,sql FROM sqlite_master WHERE type='index' "
        "AND tbl_name='daily_plan_record' AND sql IS NOT NULL ORDER BY name"
    )).all()
    # SQLite reflection omits expression indexes. Preserve every exact existing
    # definition, including native FACT and exception-command partial indexes,
    # while Alembic copies the table. The caller owns the atomic DDL transaction.
    for name, _sql in indexes:
        op.drop_index(name, table_name="daily_plan_record")
    with op.batch_alter_table("daily_plan_record") as batch:
        batch.drop_constraint("ck_daily_record_kind", type_="check")
        batch.create_check_constraint("ck_daily_record_kind", "kind IN (" + kinds + ")")
    for _name, sql in indexes:
        connection.exec_driver_sql(sql)


def upgrade():
    _replace(OLD + ",'BUY_SUSPENSION'")


def downgrade():
    if op.get_bind().execute(sa.text(
        "SELECT 1 FROM daily_plan_record WHERE kind='BUY_SUSPENSION' LIMIT 1"
    )).scalar_one_or_none() is not None:
        raise RuntimeError("0030_buy_suspension refuses to discard buy suspension evidence")
    _replace(OLD)
