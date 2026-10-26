"""Persisted P2 signal evidence survives reopen and rejects tampering."""

from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session
from tests.integration.test_p2_runtime import signal_fixture

from trade_plan_monitor.state.daily_repository import DailyRepository
from trade_plan_monitor.state.daily_state_models import DailySignalState
from trade_plan_monitor.state.database import create_sqlite_engine
from trade_plan_monitor.state.models import Base


def test_owned_signal_evidence_roundtrip_and_revision_fence(tmp_path):
    plan, signal = signal_fixture()
    engine = create_sqlite_engine(tmp_path / "p2.sqlite")
    Base.metadata.create_all(engine)
    now = datetime.fromisoformat(signal["pretrade"]["cutoff"])
    try:
        with Session(engine) as session:
            repo = DailyRepository(session, clock=lambda: now, id_factory=lambda: str(uuid4()))
            repo.save(signal["signal_id"], kind="SIGNAL", symbol=plan.symbol,
                lineage=plan.plan_id, payload=signal, expected_revision=0)
            session.commit()
            from trade_plan_monitor.state.repositories import RevisionConflictError
            with pytest.raises(RevisionConflictError):
                repo.save(signal["signal_id"], kind="SIGNAL", symbol=plan.symbol,
                    lineage=plan.plan_id, payload=signal, expected_revision=0)
        with Session(engine) as session:
            repo = DailyRepository(session, clock=lambda: now, id_factory=lambda: str(uuid4()))
            assert repo.get(signal["signal_id"])["payload"] == signal
    finally:
        engine.dispose()


def test_stored_signal_rejects_modified_frozen_q0():
    _, signal = signal_fixture()
    signal["pretrade"]["sizing"]["q0"] = 600
    with pytest.raises(ValueError):
        DailySignalState.model_validate(signal)
