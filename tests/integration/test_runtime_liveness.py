"""Durable last-alive evidence must not silently admit expired or legacy plans."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from trade_plan_monitor.runtime.clock import SHANGHAI
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.models import ActivePlan, PlanSource, PlanVersion
from trade_plan_monitor.state.runtime_liveness import (
    InterruptionDecision,
    RuntimeLivenessError,
    RuntimeLivenessRepository,
    classify_interruption,
)

NOW = datetime(2026, 9, 23, 10, tzinfo=SHANGHAI)


def test_interruption_boundary_and_unknown_evidence():
    assert classify_interruption(NOW - timedelta(hours=120), NOW) is InterruptionDecision.ELIGIBLE
    assert (
        classify_interruption(NOW - timedelta(hours=120, microseconds=1), NOW)
        is InterruptionDecision.EXPIRED
    )
    assert classify_interruption(None, NOW) is InterruptionDecision.UNKNOWN
    assert (
        classify_interruption(NOW + timedelta(microseconds=1), NOW) is InterruptionDecision.UNKNOWN
    )


def test_first_run_and_reopen_preserve_last_alive_without_resetting_it(tmp_path):
    engine = create_sqlite_engine(tmp_path / "state.db")
    upgrade_database(engine)
    repository = RuntimeLivenessRepository(create_session_factory(engine))
    assert repository.load() is None
    first = repository.initialize_empty(NOW - timedelta(days=3))
    assert first.revision == 0
    assert classify_interruption(first.last_alive_at, NOW) is InterruptionDecision.ELIGIBLE
    engine.dispose()

    reopened = create_sqlite_engine(tmp_path / "state.db")
    restored = RuntimeLivenessRepository(create_session_factory(reopened))
    assert restored.load() == first
    with pytest.raises(RuntimeLivenessError, match="already initialized"):
        restored.initialize_empty(NOW)
    assert restored.load() == first
    reopened.dispose()


def test_heartbeat_advances_monotonically_and_rejects_stale_writer(tmp_path):
    engine = create_sqlite_engine(tmp_path / "state.db")
    upgrade_database(engine)
    repository = RuntimeLivenessRepository(create_session_factory(engine))
    first = repository.initialize_empty(NOW)
    second = repository.touch(NOW + timedelta(seconds=30), expected_revision=first.revision)
    assert second.revision == 1

    with pytest.raises(RuntimeLivenessError, match="interruption exceeds 120 hours"):
        repository.touch(NOW + timedelta(hours=121), expected_revision=second.revision)
    assert repository.load() == second
    with pytest.raises(RuntimeLivenessError):
        repository.touch(NOW + timedelta(seconds=31), expected_revision=first.revision)
    with pytest.raises(RuntimeLivenessError):
        repository.touch(NOW - timedelta(seconds=1), expected_revision=second.revision)
    assert repository.load() == second
    engine.dispose()


def test_corrupt_heartbeat_fails_closed(tmp_path):
    engine = create_sqlite_engine(tmp_path / "state.db")
    upgrade_database(engine)
    repository = RuntimeLivenessRepository(create_session_factory(engine))
    repository.initialize_empty(NOW)
    with engine.begin() as connection:
        connection.execute(text("UPDATE runtime_liveness SET last_alive_at = 'invalid'"))
    with pytest.raises(RuntimeLivenessError, match="invalid runtime liveness"):
        repository.load()
    engine.dispose()


def test_noncanonical_parseable_heartbeat_fails_closed(tmp_path):
    engine = create_sqlite_engine(tmp_path / "state.db")
    upgrade_database(engine)
    repository = RuntimeLivenessRepository(create_session_factory(engine))
    repository.initialize_empty(NOW)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE runtime_liveness SET last_alive_at = '2026-09-23 10:00:00+08:00'")
        )
    with pytest.raises(RuntimeLivenessError, match="invalid runtime liveness"):
        repository.load()
    engine.dispose()


def test_legacy_active_plan_cannot_silently_start_a_new_heartbeat(tmp_path):
    engine = create_sqlite_engine(tmp_path / "state.db")
    upgrade_database(engine)
    factory = create_session_factory(engine)
    with factory.begin() as session:
        session.add(
            PlanSource(
                id="source",
                source_text="test",
                source_hash="a" * 64,
                created_at=NOW.isoformat(),
            )
        )
        session.flush()
        session.add(
            PlanVersion(
                id="version",
                plan_id="plan",
                version=1,
                symbol="000001.SZ",
                plan_hash="b" * 64,
                status="ACTIVE",
                payload_json="{}",
                source_id="source",
                revision=0,
                created_at=NOW.isoformat(),
            )
        )
        session.flush()
        session.add(
            ActivePlan(
                symbol="000001.SZ",
                plan_version_id="version",
                activated_at=NOW.isoformat(),
                revision=1,
            )
        )
    repository = RuntimeLivenessRepository(factory)
    with pytest.raises(RuntimeLivenessError, match="active plans lack"):
        repository.initialize_empty(NOW)
    assert repository.load() is None
    engine.dispose()


def test_migration_downgrade_refuses_to_discard_liveness_evidence(tmp_path):
    engine = create_sqlite_engine(tmp_path / "state.db")
    upgrade_database(engine)
    repository = RuntimeLivenessRepository(create_session_factory(engine))
    repository.initialize_empty(NOW)
    config = Config()
    import trade_plan_monitor.state.database as database

    config.set_main_option("script_location", str(Path(database.__file__).with_name("migrations")))
    with pytest.raises(RuntimeError, match="refuses to discard"):
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "0021_inventory_history_index")
    assert repository.load() is not None
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM runtime_liveness"))
        config.attributes["connection"] = connection
        command.downgrade(config, "0021_inventory_history_index")
    upgrade_database(engine)
    assert repository.load() is None
    engine.dispose()
