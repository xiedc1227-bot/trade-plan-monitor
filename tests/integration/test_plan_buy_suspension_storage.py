"""Real isolated SQL, revision fences and immutable original suspension owner."""

import json
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from tests.integration.test_lot_history_indexes import _migrate
from tests.unit.test_daily_state_models import signal_payload
from tests.unit.test_plan_buy_suspension_state import (
    at,
    state_payload,
    trigger_payload,
)

from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.daily_repository import DailyRepository, buy_suspension_record_id
from trade_plan_monitor.state.daily_state_models import DailyBuySuspensionState
from trade_plan_monitor.state.database import create_sqlite_engine, upgrade_database
from trade_plan_monitor.state.models import AuditLog, Base
from trade_plan_monitor.state.repositories import RevisionConflictError

NOW = at("2026-10-09T16:00:00")


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "suspension.sqlite3"
    engine = create_sqlite_engine(path)
    # Fresh private test tables only: no application DB or Alembic upgrade.
    Base.metadata.create_all(engine, tables=[DailyRecord.__table__, AuditLog.__table__])
    yield engine, path
    engine.dispose()


def repo(session):
    return DailyRepository(session, clock=lambda: NOW, id_factory=lambda: str(uuid4()))


def save(session, state, revision=0, **changes):
    values = dict(kind="BUY_SUSPENSION", symbol=state.symbol,
                  lineage=state.owner_plan_version_id, payload=state.model_dump(mode="json"),
                  expected_revision=revision)
    values.update(changes)
    repository = repo(session)
    repository.lock_symbol(state.symbol)
    return repository.save(buy_suspension_record_id(state.symbol, state.owner_plan_version_id),
                           **values)


def test_roundtrip_restart_typed_read_revision_and_audit(database):
    engine, path = database
    state = DailyBuySuspensionState.model_validate(state_payload())
    with Session(engine) as session:
        first = save(session, state)
        session.commit()
    engine.dispose()
    restarted = create_sqlite_engine(path)
    writes = []
    event.listen(restarted, "before_cursor_execute", lambda c, u, sql, p, x, m:
                 writes.append(sql) if sql.lstrip().upper().startswith(
                     ("INSERT", "UPDATE", "DELETE", "ALTER", "CREATE")) else None)
    try:
        with Session(restarted) as session:
            row = repo(session).get_buy_suspension(
                symbol=state.symbol, owner_plan_version_id=state.owner_plan_version_id)
            assert row["state"] == state and row["revision"] == first["revision"] == 1
            assert row["state_hash"] == state.state_hash
            assert len(session.scalars(select(AuditLog)).all()) == 1
        assert writes == []
        with Session(restarted) as session:
            assert save(session, state, revision=1)["revision"] == 2
            session.commit()
        with Session(restarted) as session, pytest.raises(RevisionConflictError):
            save(session, state, revision=1)
    finally:
        restarted.dispose()


@pytest.mark.parametrize("change", [
    {"symbol": "601021.SH"}, {"lineage": "copied-owner"},
    {"expected_revision": True},
])
def test_new_kind_rejects_wrong_outer_owner_and_invalid_revision(database, change):
    engine, _ = database
    state = DailyBuySuspensionState.model_validate(state_payload())
    with Session(engine) as session, pytest.raises(ValueError):
        save(session, state, **change)


def test_stored_latch_and_definition_cannot_be_rewritten_and_rollback_is_real(database):
    engine, _ = database
    state = DailyBuySuspensionState.model_validate(
        {**state_payload(), "trigger": trigger_payload(), "blocker": None})
    with Session(engine) as session:
        save(session, state)
        session.commit()
    for changed in (
        state.model_copy(update={"trigger": None, "blocker": "HISTORY_PENDING"}),
        state.model_copy(update={"review_id": "other-review"}),
        state.model_copy(update={"definition": {**state.definition.model_dump(),
            "condition": {"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5,
                          "price_fen": 2500}}}),
    ):
        with Session(engine) as session, pytest.raises(ValueError):
            save(session, changed, revision=1)
    with Session(engine) as session:
        later = state.model_copy(update={"evaluated_at": NOW, "target": NOW})
        save(session, later, revision=1)
        session.rollback()
    with Session(engine) as session:
        row = repo(session).get_buy_suspension(
            symbol=state.symbol, owner_plan_version_id=state.owner_plan_version_id)
        assert row["state"] == state and row["revision"] == 1
        assert len(session.scalars(select(AuditLog)).all()) == 1


def test_other_contexts_stay_separate_and_legacy_signal_bytes_do_not_change(database):
    engine, _ = database
    state = DailyBuySuspensionState.model_validate(state_payload())
    legacy = json.dumps(signal_payload(), sort_keys=True, separators=(",", ":"))
    with Session(engine) as session:
        save(session, state)
        save(session, state.model_copy(update={"owner_plan_version_id": "unrelated"}))
        repo(session).save("legacy", kind="SIGNAL", symbol=state.symbol, lineage="legacy",
                           payload=signal_payload(), expected_revision=0)
        session.commit()
    with Session(engine) as session:
        assert repo(session).get_buy_suspension(symbol="601021.SH",
            owner_plan_version_id=state.owner_plan_version_id) is None
        assert session.get(DailyRecord, "legacy").payload_json == legacy
        with pytest.raises(IntegrityError):
            session.execute(text("INSERT INTO daily_plan_record VALUES "
                "('bad','UNLOCK','002240.SZ','x',1,'{}',:now,:now)"), {"now": NOW.isoformat()})


def test_read_rejects_corrupt_future_and_wrong_owner_payload(database):
    engine, _ = database
    state = DailyBuySuspensionState.model_validate(state_payload())
    with Session(engine) as session:
        row = save(session, state)
        session.commit()
    for change in ({"symbol": "601021.SH"},
                   {"evaluated_at": (NOW + timedelta(days=1)).isoformat()}):
        payload = state.model_dump(mode="json") | change
        with engine.begin() as connection:
            connection.execute(text(
                "UPDATE daily_plan_record SET payload_json=:payload WHERE id=:id"),
                {"payload": json.dumps(payload), "id": row["id"]})
        with Session(engine) as session, pytest.raises(ValueError):
            repo(session).get_buy_suspension(symbol=state.symbol,
                owner_plan_version_id=state.owner_plan_version_id)


@pytest.mark.parametrize("existing_0029", [False, True])
def test_packaged_upgrade_accepts_suspension_from_fresh_and_old_schema(tmp_path, existing_0029):
    engine = create_sqlite_engine(tmp_path / "packaged-upgrade.sqlite3")
    state = DailyBuySuspensionState.model_validate(state_payload())
    try:
        if existing_0029:
            _migrate(engine, "0029_native_fact_lookup")
            # The historical constraint really rejects the new kind before upgrade.
            with Session(engine) as session, pytest.raises(IntegrityError):
                save(session, state)
        upgrade_database(engine)
        upgrade_database(engine)
        with Session(engine) as session:
            assert save(session, state)["revision"] == 1
            session.commit()
        with Session(engine) as session:
            actual = repo(session).get_buy_suspension(symbol=state.symbol,
                owner_plan_version_id=state.owner_plan_version_id)
            assert actual["state"] == state
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0030_buy_suspension")
    finally:
        engine.dispose()


def migration_snapshot(engine):
    with engine.connect() as connection:
        return dict(
            rows=tuple(connection.exec_driver_sql("SELECT * FROM daily_plan_record ORDER BY id")),
            indexes=tuple(connection.exec_driver_sql(
                "SELECT name,sql FROM sqlite_master WHERE type='index' "
                "AND tbl_name='daily_plan_record' ORDER BY name")),
        )


@pytest.mark.parametrize("populated", [False, True])
def test_upgrade_and_safe_downgrade_keep_old_bytes_and_all_expression_indexes(tmp_path, populated):
    engine = create_sqlite_engine(tmp_path / "retained-evidence.sqlite3")
    try:
        _migrate(engine, "0029_native_fact_lookup")
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE INDEX ix_pbs_test_partial "
                "ON daily_plan_record(revision) WHERE kind='REPORT'")
            if populated:
                old_kinds = ("SIGNAL", "RISK", "FACT", "SIMULATION", "REPORT", "POSITION",
                    "EVALUATION", "REVIEW", "DRAFT", "EXTRACTION", "REASSESSMENT",
                    "EXCEPTION_CANDIDATE", "EXCEPTION_EVENT", "EXCEPTION_PREVIEW")
                for kind in old_kinds:
                    connection.execute(text("INSERT INTO daily_plan_record VALUES "
                        "(:id,:kind,'002240.SZ','legacy',7,:payload,:at,:at)"),
                        {"id": kind, "kind": kind, "payload": '{"原文":  "kept", "n": 1}',
                         "at": NOW.isoformat()})
        before = migration_snapshot(engine)
        assert {name for name, _ in before["indexes"]} >= {
            "ix_daily_fact_trade_date_lookup", "ux_exception_command", "ix_pbs_test_partial"}
        upgrade_database(engine)
        assert migration_snapshot(engine) == before
        _migrate(engine, "0029_native_fact_lookup", downgrade=True)
        assert migration_snapshot(engine) == before
        state = DailyBuySuspensionState.model_validate(state_payload())
        with Session(engine) as session, pytest.raises(IntegrityError):
            save(session, state)
        upgrade_database(engine)
        assert migration_snapshot(engine) == before
    finally:
        engine.dispose()


def test_downgrade_with_suspension_refuses_before_ddl_and_keeps_all_state(tmp_path):
    engine = create_sqlite_engine(tmp_path / "refuse-loss.sqlite3")
    statements = []
    try:
        upgrade_database(engine)
        state = DailyBuySuspensionState.model_validate(state_payload())
        with Session(engine) as session:
            save(session, state)
            session.commit()
        before = migration_snapshot(engine)

        def observe(_connection, _cursor, sql, _parameters, _context, _many):
            if sql.lstrip().upper().startswith(("CREATE", "ALTER", "DROP", "DELETE")):
                statements.append(sql)

        event.listen(engine, "before_cursor_execute", observe)
        with pytest.raises(RuntimeError, match="refuses to discard buy suspension"):
            _migrate(engine, "0029_native_fact_lookup", downgrade=True)
        event.remove(engine, "before_cursor_execute", observe)
        assert statements == [] and migration_snapshot(engine) == before
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0030_buy_suspension")
        with Session(engine) as session:
            assert repo(session).get_buy_suspension(symbol=state.symbol,
                owner_plan_version_id=state.owner_plan_version_id)["state"] == state
    finally:
        engine.dispose()
