"""Programmatic Alembic environment for the packaged SQLite database."""

from alembic import context
from sqlalchemy.engine import Connection

from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.p3_models import CapitalBookRow
from trade_plan_monitor.state.source_coverage_models import CoverageInstallationRow

target_metadata = DailyRecord.metadata
assert CapitalBookRow.metadata is target_metadata
assert CoverageInstallationRow.metadata is target_metadata


def run_migrations_online() -> None:
    """Run migrations through the connection supplied by ``upgrade_database``."""

    connection = context.config.attributes.get("connection")
    if not isinstance(connection, Connection):
        raise RuntimeError("Alembic requires an existing SQLAlchemy connection")

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("Offline migrations are not supported")
run_migrations_online()
