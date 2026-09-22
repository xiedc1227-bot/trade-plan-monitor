"""Single-lot history scopes use indexes without rewriting durable evidence."""

from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, inspect

from trade_plan_monitor.state import database
from trade_plan_monitor.state.database import create_sqlite_engine, upgrade_database
from trade_plan_monitor.state.models import AuditLog, Base, MonitorEvent

PREVIOUS_REVISION = "0019_alert_delivery_eligibility"
HISTORY_REVISION = "0020_lot_history_indexes"
EXPECTED_INDEXES = {
    "audit_log": ("ix_audit_log_entity", ["entity_type", "entity_id"]),
    "monitor_event": ("ix_monitor_event_aggregate_sequence", ["aggregate_id", "sequence"]),
}


def _migrate(engine: Engine, target: str, *, downgrade: bool = False) -> None:
    config = Config()
    config.set_main_option("script_location", str(Path(database.__file__).with_name("migrations")))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        (command.downgrade if downgrade else command.upgrade)(config, target)


@pytest.fixture
def populated_database(tmp_path: Path):
    engine = create_sqlite_engine(tmp_path / "lot-history.db")
    try:
        _migrate(engine, PREVIOUS_REVISION)
        with engine.begin() as connection:
            connection.execute(
                AuditLog.__table__.insert(),
                [
                    {
                        "id": f"audit-{index}",
                        "action": "position.reduced",
                        "entity_type": "position_lot" if index != 3 else "other",
                        "entity_id": "target" if index != 4 else "unrelated",
                        "before_hash": "a" * 64,
                        "after_hash": "b" * 64,
                        "details_json": '{"retained":"审计原文"}',
                        "created_at": "2026-09-22T10:00:00+08:00",
                    }
                    for index in range(1, 5)
                ],
            )
            connection.execute(
                MonitorEvent.__table__.insert(),
                [
                    {
                        "id": f"event-{index}",
                        "sequence": index,
                        "event_type": "position.updated",
                        "schema_version": 1,
                        "aggregate_id": "target" if index != 3 else "unrelated",
                        "payload_json": '{"retained":"事件原文"}',
                        "occurred_at": "2026-09-22T10:00:00+08:00",
                    }
                    for index in range(1, 5)
                ],
            )
            connection.exec_driver_sql(
                "UPDATE monitor_sequence SET last_sequence = 4 WHERE singleton_id = 1"
            )
        yield engine
    finally:
        engine.dispose()


def _stored_rows(engine: Engine) -> dict[str, list[tuple]]:
    with engine.connect() as connection:
        return {
            table: [tuple(row) for row in connection.exec_driver_sql(f'SELECT * FROM "{table}"')]
            for table in inspect(connection).get_table_names()
            if table != "alembic_version"
        }


def _assert_history_indexes(engine: Engine) -> None:
    inspector = inspect(engine)
    for table, (name, columns) in EXPECTED_INDEXES.items():
        matching = [index for index in inspector.get_indexes(table) if index["name"] == name]
        assert len(matching) == 1
        assert matching[0]["column_names"] == columns
        assert matching[0]["unique"] == 0


def test_upgrade_repeat_downgrade_and_reupgrade_preserve_every_stored_row(populated_database):
    engine = populated_database
    before = _stored_rows(engine)
    indexes_before = {table: inspect(engine).get_indexes(table) for table in EXPECTED_INDEXES}

    for _ in range(2):
        upgrade_database(engine)
        _assert_history_indexes(engine)
        assert _stored_rows(engine) == before
        with engine.connect() as connection:
            assert (
                connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
                == HISTORY_REVISION
            )

    _migrate(engine, PREVIOUS_REVISION, downgrade=True)
    assert _stored_rows(engine) == before
    for table in EXPECTED_INDEXES:
        assert inspect(engine).get_indexes(table) == indexes_before[table]
    with engine.connect() as connection:
        assert (
            connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
            == PREVIOUS_REVISION
        )

    upgrade_database(engine)
    _assert_history_indexes(engine)
    assert _stored_rows(engine) == before


@pytest.mark.parametrize(
    "query, parameters, index_name, expected_ids",
    [
        (
            "SELECT id FROM audit_log WHERE entity_type = ? AND entity_id = ? LIMIT ?",
            ("position_lot", "target", 3),
            "ix_audit_log_entity",
            {"audit-1", "audit-2"},
        ),
        (
            "SELECT id FROM monitor_event WHERE aggregate_id = ? ORDER BY sequence LIMIT ?",
            ("target", 3),
            "ix_monitor_event_aggregate_sequence",
            {"event-1", "event-2", "event-4"},
        ),
    ],
)
def test_scoped_bounded_history_queries_use_indexes_without_scan_or_sort(
    populated_database, query, parameters, index_name, expected_ids
):
    engine = populated_database
    with engine.connect() as connection:
        plan_before = " ".join(
            row[3] for row in connection.exec_driver_sql("EXPLAIN QUERY PLAN " + query, parameters)
        )
        rows_before = connection.exec_driver_sql(query, parameters).scalars().all()
    assert "SCAN " in plan_before
    assert index_name not in plan_before

    upgrade_database(engine)
    with engine.connect() as connection:
        plan = " ".join(
            row[3] for row in connection.exec_driver_sql("EXPLAIN QUERY PLAN " + query, parameters)
        )
        assert f"USING INDEX {index_name}" in plan
        assert "SEARCH " in plan
        assert "SCAN " not in plan
        assert "TEMP B-TREE" not in plan
        rows = connection.exec_driver_sql(query, parameters).scalars().all()
        assert rows == rows_before
        assert set(rows) == expected_ids
        if index_name == "ix_monitor_event_aggregate_sequence":
            assert rows == ["event-1", "event-2", "event-4"]


def test_history_migration_matches_orm_metadata(populated_database):
    engine = populated_database
    upgrade_database(engine)
    _assert_history_indexes(engine)
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
