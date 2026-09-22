"""Transaction ownership preflight for committed recovery evidence readers."""

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from trade_plan_monitor.state.models import Base


def require_owned_recovery_session(session: Session, models: tuple[type[Base], ...]) -> None:
    """Reject borrowed or split transactions before taking ownership of a session.

    Call before entering the session context or catching content-validation errors.
    The factory must still use state.database's file-backed explicit-BEGIN engine;
    bind validation does not certify custom engine hooks or Session overrides.
    """
    if (session.in_transaction() or session.identity_map or session.new
            or session.dirty or session.deleted):
        raise ValueError("Recovery reader requires a fresh session")
    engine = session.bind
    if not isinstance(engine, Engine) or engine.dialect.name != "sqlite":
        raise ValueError("Recovery reader requires an application SQLite engine")
    for model in models:
        if (session.get_bind(mapper=model) is not engine
                or session.get_bind(clause=model.__table__) is not engine):
            raise ValueError("Recovery reader requires one engine for all evidence")
