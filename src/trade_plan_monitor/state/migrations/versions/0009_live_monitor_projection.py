"""Add the durable live-monitor result and projection store.

Revision ID: 0009_live_monitor_projection
Revises: 0008_market_index_monitor_event
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_live_monitor_projection"
down_revision: str | Sequence[str] | None = "0008_market_index_monitor_event"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IDENTITY_COLUMNS = (
    "plan_hash",
    "symbol",
    "evaluation_kind",
    "target_value",
    "formula_version",
)
_NEW_TABLES = (
    "evaluation_result",
    "symbol_decision_head",
    "symbol_health_projection",
    "pending_official_close",
    "market_index_snapshot",
    "market_index_snapshot_head",
)
_EVALUATION_TARGET_CHECK = (
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
    legacy_pending_symbol = op.get_bind().execute(
        sa.text(
            "SELECT symbol FROM symbol_health "
            "WHERE status = 'CLOSE_PENDING' LIMIT 1"
        )
    ).scalar_one_or_none()
    if legacy_pending_symbol is not None:
        raise RuntimeError(
            "0009_live_monitor_projection requires legacy CLOSE_PENDING "
            "to be resolved before upgrade"
        )
    op.create_index(
        "uq_evaluation_ledger_identity_hash",
        "evaluation_ledger",
        (*_IDENTITY_COLUMNS, "result_hash"),
        unique=True,
    )
    op.create_table(
        "evaluation_result",
        sa.Column("plan_hash", sa.String(64), primary_key=True),
        sa.Column("symbol", sa.String(9), primary_key=True),
        sa.Column("evaluation_kind", sa.String(16), primary_key=True),
        sa.Column("target_value", sa.String(40), primary_key=True),
        sa.Column("formula_version", sa.String(32), primary_key=True),
        sa.Column("result_hash", sa.String(64), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("position_lots_json", sa.Text(), nullable=False),
        sa.Column("evaluated_at", sa.String(40), nullable=False),
        sa.Column("source_at", sa.String(40), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            (*_IDENTITY_COLUMNS, "result_hash"),
            tuple(
                f"evaluation_ledger.{name}"
                for name in (*_IDENTITY_COLUMNS, "result_hash")
            ),
            name="fk_evaluation_result_ledger",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            *_IDENTITY_COLUMNS,
            "result_hash",
            name="uq_evaluation_result_identity_hash",
        ),
        sa.CheckConstraint(
            "evaluation_kind IN ('INTRADAY', 'OFFICIAL_CLOSE')",
            name="ck_evaluation_result_kind",
        ),
        sa.CheckConstraint(
            _EVALUATION_TARGET_CHECK,
            name="ck_evaluation_result_target_shape",
        ),
        sa.CheckConstraint("length(result_hash) = 64", name="ck_evaluation_result_hash"),
        sa.CheckConstraint("schema_version = 1", name="ck_evaluation_result_schema_version"),
    )
    op.create_table(
        "symbol_health_projection",
        sa.Column("symbol", sa.String(9), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("activation_revision", sa.Integer(), nullable=False),
        sa.Column("runtime_generation", sa.String(36), nullable=False),
        sa.Column("projection_json", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.String(40), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_symbol_health_projection_revision_positive",
        ),
        sa.CheckConstraint(
            "schema_version = 1",
            name="ck_symbol_health_projection_schema_version",
        ),
        sa.CheckConstraint(
            "activation_revision >= 1",
            name="ck_symbol_health_projection_activation_revision_positive",
        ),
        sa.CheckConstraint(
            "length(runtime_generation) = 36",
            name="ck_symbol_health_projection_runtime_generation_uuid",
        ),
    )
    op.create_table(
        "pending_official_close",
        sa.Column("plan_hash", sa.String(64), primary_key=True),
        sa.Column("symbol", sa.String(9), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("formula_version", sa.String(32), primary_key=True),
        sa.Column("pending_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("symbol", name="uq_pending_official_close_symbol"),
        sa.CheckConstraint(
            "length(plan_hash) = 64",
            name="ck_pending_official_close_plan_hash",
        ),
    )
    op.create_table(
        "market_index_snapshot",
        sa.Column("snapshot_hash", sa.String(64), primary_key=True),
        sa.Column("mapping_version", sa.String(32), nullable=False),
        sa.Column("index_code", sa.String(16), nullable=False),
        sa.Column("decision_cutoff", sa.String(40), nullable=False),
        sa.Column("request_set_hash", sa.String(64), nullable=False),
        sa.Column("provider_content_revision", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("bar_set_hash", sa.String(64), nullable=False),
        sa.Column("formula_definition_hash", sa.String(64), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.String(40), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "mapping_version",
            "index_code",
            "decision_cutoff",
            "request_set_hash",
            "provider_content_revision",
            name="uq_market_index_snapshot_cache_identity",
        ),
        sa.UniqueConstraint(
            "mapping_version",
            "index_code",
            "decision_cutoff",
            "request_set_hash",
            "provider_content_revision",
            "snapshot_hash",
            name="uq_market_index_snapshot_head_target",
        ),
        sa.CheckConstraint(
            "provider_content_revision >= 1",
            name="ck_market_index_snapshot_provider_revision_positive",
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_market_index_snapshot_revision_positive",
        ),
        sa.CheckConstraint(
            "length(snapshot_hash) = 64 "
            "AND length(request_set_hash) = 64 "
            "AND length(bar_set_hash) = 64 "
            "AND length(formula_definition_hash) = 64",
            name="ck_market_index_snapshot_hashes",
        ),
        sa.CheckConstraint(
            "schema_version = 1",
            name="ck_market_index_snapshot_schema_version",
        ),
    )
    op.create_table(
        "market_index_snapshot_head",
        sa.Column("mapping_version", sa.String(32), primary_key=True),
        sa.Column("index_code", sa.String(16), primary_key=True),
        sa.Column("decision_cutoff", sa.String(40), primary_key=True),
        sa.Column("request_set_hash", sa.String(64), primary_key=True),
        sa.Column("provider_content_revision", sa.Integer(), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.ForeignKeyConstraint(
            (
                "mapping_version",
                "index_code",
                "decision_cutoff",
                "request_set_hash",
                "provider_content_revision",
                "snapshot_hash",
            ),
            (
                "market_index_snapshot.mapping_version",
                "market_index_snapshot.index_code",
                "market_index_snapshot.decision_cutoff",
                "market_index_snapshot.request_set_hash",
                "market_index_snapshot.provider_content_revision",
                "market_index_snapshot.snapshot_hash",
            ),
            name="fk_market_index_snapshot_head_payload",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "provider_content_revision >= 1",
            name="ck_market_index_snapshot_head_provider_revision_positive",
        ),
        sa.CheckConstraint(
            "length(snapshot_hash) = 64 AND length(request_set_hash) = 64",
            name="ck_market_index_snapshot_head_hashes",
        ),
    )
    op.create_table(
        "symbol_decision_head",
        sa.Column("symbol", sa.String(9), primary_key=True),
        sa.Column("plan_hash", sa.String(64), nullable=False),
        sa.Column("evaluation_kind", sa.String(16), nullable=False),
        sa.Column("target_value", sa.String(40), nullable=False),
        sa.Column("formula_version", sa.String(32), nullable=False),
        sa.Column("result_hash", sa.String(64), nullable=False),
        sa.Column("activation_revision", sa.Integer(), nullable=False),
        sa.Column(
            "event_sequence",
            sa.Integer(),
            sa.ForeignKey("monitor_event.sequence", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.ForeignKeyConstraint(
            (
                "plan_hash",
                "symbol",
                "evaluation_kind",
                "target_value",
                "formula_version",
                "result_hash",
            ),
            (
                "evaluation_result.plan_hash",
                "evaluation_result.symbol",
                "evaluation_result.evaluation_kind",
                "evaluation_result.target_value",
                "evaluation_result.formula_version",
                "evaluation_result.result_hash",
            ),
            name="fk_symbol_decision_head_result",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("event_sequence", name="uq_symbol_decision_head_event_sequence"),
        sa.CheckConstraint(
            "evaluation_kind IN ('INTRADAY', 'OFFICIAL_CLOSE')",
            name="ck_symbol_decision_head_kind",
        ),
        sa.CheckConstraint(
            _EVALUATION_TARGET_CHECK,
            name="ck_symbol_decision_head_target_shape",
        ),
        sa.CheckConstraint(
            "event_sequence >= 1",
            name="ck_symbol_decision_head_event_sequence_positive",
        ),
        sa.CheckConstraint(
            "activation_revision >= 1",
            name="ck_symbol_decision_head_activation_revision_positive",
        ),
        sa.CheckConstraint(
            "length(result_hash) = 64",
            name="ck_symbol_decision_head_result_hash",
        ),
    )


def downgrade() -> None:
    connection = op.get_bind()
    for table_name in _NEW_TABLES:
        populated = connection.execute(
            sa.text(f'SELECT 1 FROM "{table_name}" LIMIT 1')
        ).scalar_one_or_none()
        if populated is not None:
            raise RuntimeError(
                "0009_live_monitor_projection refuses populated live monitor projection tables"
            )

    op.drop_table("symbol_decision_head")
    op.drop_table("market_index_snapshot_head")
    op.drop_table("market_index_snapshot")
    op.drop_table("pending_official_close")
    op.drop_table("symbol_health_projection")
    op.drop_table("evaluation_result")
    op.drop_index(
        "uq_evaluation_ledger_identity_hash",
        table_name="evaluation_ledger",
    )
