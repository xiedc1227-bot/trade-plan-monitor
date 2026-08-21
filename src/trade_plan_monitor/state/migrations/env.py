"""Programmatic Alembic environment for the packaged SQLite database."""

from alembic import context
from sqlalchemy.engine import Connection

from trade_plan_monitor.state.models import Base

target_metadata = Base.metadata


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
