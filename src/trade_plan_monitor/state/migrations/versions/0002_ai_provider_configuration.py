"""Add non-secret AI provider configuration metadata.

Revision ID: 0002_ai_provider_configuration
Revises: 0001_initial
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_ai_provider_configuration"
down_revision: str | Sequence[str] | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_provider_configuration",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("provider_type", sa.String(32), nullable=False),
        sa.Column("base_url", sa.String(2048), nullable=False),
        sa.Column("model_name", sa.String(200), nullable=False),
        sa.Column("key_ref", sa.String(140), nullable=False),
        sa.Column("environment_variable", sa.String(128), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("max_input_chars", sa.Integer(), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False),
        sa.Column("temperature_milli", sa.Integer(), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.CheckConstraint(
            "provider_type = 'OPENAI_COMPATIBLE'",
            name="ck_ai_provider_configuration_type",
        ),
        sa.CheckConstraint(
            "key_ref GLOB 'ai/provider/*' AND length(key_ref) BETWEEN 13 AND 140",
            name="ck_ai_provider_configuration_key_ref",
        ),
        sa.CheckConstraint(
            "environment_variable IS NULL OR ("
            "length(environment_variable) BETWEEN 1 AND 128 "
            "AND environment_variable NOT GLOB '*[^A-Za-z0-9_]*' "
            "AND substr(environment_variable, 1, 1) GLOB '[A-Za-z_]')",
            name="ck_ai_provider_configuration_environment_ref",
        ),
        sa.CheckConstraint(
            "timeout_seconds BETWEEN 1 AND 120",
            name="ck_ai_provider_configuration_timeout",
        ),
        sa.CheckConstraint(
            "max_retries BETWEEN 0 AND 2",
            name="ck_ai_provider_configuration_retries",
        ),
        sa.CheckConstraint(
            "max_input_chars BETWEEN 1 AND 200000",
            name="ck_ai_provider_configuration_input_chars",
        ),
        sa.CheckConstraint(
            "max_output_tokens BETWEEN 1 AND 16384",
            name="ck_ai_provider_configuration_output_tokens",
        ),
        sa.CheckConstraint(
            "temperature_milli BETWEEN 0 AND 300",
            name="ck_ai_provider_configuration_temperature",
        ),
        sa.CheckConstraint("enabled IN (0, 1)", name="ck_ai_provider_configuration_enabled"),
        sa.CheckConstraint("revision >= 0", name="ck_ai_provider_configuration_revision"),
    )


def downgrade() -> None:
    op.drop_table("ai_provider_configuration")
