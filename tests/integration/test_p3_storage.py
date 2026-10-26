"""The capital sidecar is additive, immutable, restartable and transaction-bound."""

import json
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from tests.integration.test_index_permission_scope_migration import _migrate

from trade_plan_monitor.decision.p3_basis import CapitalLot
from trade_plan_monitor.state.database import create_sqlite_engine
from trade_plan_monitor.state.p3_capital_repository import CapitalCommandConflict, CapitalRepository
from trade_plan_monitor.state.p3_models import CapitalBook
from trade_plan_monitor.state.repositories import RevisionConflictError

NOW = datetime(2026, 10, 26, 10, tzinfo=ZoneInfo("Asia/Shanghai"))


def book(revision=1, inventory_revision=1, basis=450001):
    return CapitalBook.build(
        symbol="601021.SH",
        revision=revision,
        inventory_revision=inventory_revision,
        updated_at=NOW,
        lots=(
            CapitalLot(
                lot_id="initial-TACTICAL",
                bucket="TACTICAL",
                quantity=400,
                retained_basis_fen=basis,
                provenance_ref="opening",
            ),
        ),
    )


def save(repo, state=None, expected=0, command="opening", request="a" * 64):
    return repo.write(
        state or book(),
        expected_revision=expected,
        command_id=command,
        request_hash=request,
        kind="OPENING" if not expected else "RECONCILIATION",
        now=NOW,
        details={"source": "explicit temporary fixture"},
    )


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "capital.sqlite"
    engine = create_sqlite_engine(path)
    _migrate(engine, "head")
    yield engine, path
    engine.dispose()


def test_book_reopen_idempotency_and_stale_revision_are_exact(database):
    engine, _ = database
    with Session(engine) as session, session.begin():
        repo = CapitalRepository(session)
        original = save(repo)
        assert original.book.retained_basis_fen == 450001
        assert save(repo) == original
        newer = save(repo, book(2, basis=450002), expected=1, command="correct", request="b" * 64)
        assert newer.book.revision == 2
    with Session(engine) as session:
        repo = CapitalRepository(session)
        assert repo.get("601021.SH") == newer.book
        assert save(repo) == original  # Original receipt, never reset the newer state.
        with pytest.raises(CapitalCommandConflict):
            save(repo, request="c" * 64)
        with pytest.raises(RevisionConflictError):
            save(repo, book(2), expected=1, command="stale", request="d" * 64)


def test_inventory_and_event_scalar_tampering_are_not_silent(database):
    engine, _ = database
    with Session(engine) as session, session.begin():
        save(CapitalRepository(session))
    with engine.begin() as connection:
        raw = connection.execute(
            text("SELECT payload_json FROM simulation_capital_book")
        ).scalar_one()
        changed = json.loads(raw)
        changed["lots"][0]["retained_basis_fen"] = 1
        connection.execute(
            text("UPDATE simulation_capital_book SET payload_json=:payload"),
            {"payload": json.dumps(changed)},
        )
    with Session(engine) as session, pytest.raises(ValueError):
        CapitalRepository(session).get("601021.SH")


def test_exception_after_write_rolls_back_both_new_tables(database):
    engine, _ = database
    with pytest.raises(RuntimeError, match="fault"):
        with Session(engine) as session, session.begin():
            save(CapitalRepository(session))
            raise RuntimeError("fault after budget write")
    with engine.connect() as connection:
        for table in ("simulation_capital_book", "simulation_capital_event"):
            assert connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one() == 0


def test_migration_preserves_old_payload_and_refuses_lossy_downgrade(tmp_path):
    engine = create_sqlite_engine(tmp_path / "migration.sqlite")
    _migrate(engine, "0026_market_exceptions")
    before = '{ "simulation_version": "daily-simulation-v1", "untouched": true }'
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO daily_plan_record VALUES "
                "('old','POSITION','601021.SH','old',1,:payload,:at,:at)"
            ),
            {"payload": before, "at": NOW.isoformat()},
        )
    _migrate(engine, "head")
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT payload_json FROM daily_plan_record WHERE id='old'")
            ).scalar_one()
            == before
        )
    with Session(engine) as session, session.begin():
        save(CapitalRepository(session))
    with pytest.raises(RuntimeError, match="capital"):
        _migrate(engine, "0026_market_exceptions", downgrade=True)
    with Session(engine) as session:
        assert CapitalRepository(session).get("601021.SH").retained_basis_fen == 450001
    engine.dispose()


def test_native_sqlite_backup_preserves_new_records_and_hashes(database, tmp_path):
    engine, path = database
    with Session(engine) as session, session.begin():
        original = save(CapitalRepository(session))
    target = tmp_path / "backup.sqlite"
    with sqlite3.connect(path) as source, sqlite3.connect(target) as backup:
        source.backup(backup)
        assert backup.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    reopened = create_sqlite_engine(target)
    with Session(reopened) as session:
        assert CapitalRepository(session).event("opening") == original
    reopened.dispose()


def test_empty_sidecar_downgrades_and_metadata_matches_head(database):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from trade_plan_monitor.state.models import Base

    engine, _ = database
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
    _migrate(engine, "0026_market_exceptions", downgrade=True)
    _migrate(engine, "head")
    with Session(engine) as session:
        assert CapitalRepository(session).get("601021.SH") is None


def test_event_column_tampering_is_detected_independently(database):
    engine, _ = database
    with Session(engine) as session, session.begin():
        save(CapitalRepository(session))
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE simulation_capital_event SET request_hash=:bad"), {"bad": "f" * 64}
        )
    with Session(engine) as session, pytest.raises(ValueError, match="columns"):
        CapitalRepository(session).event("opening")
