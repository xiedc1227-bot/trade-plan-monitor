"""Single-lot history scopes use indexes without rewriting durable evidence."""

import json
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from uuid import UUID

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
LATEST_REVISION = "0030_buy_suspension"
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
            if table not in {"alembic_version", "runtime_liveness"}
        }


def _assert_history_indexes(engine: Engine) -> None:
    inspector = inspect(engine)
    for table, (name, columns) in EXPECTED_INDEXES.items():
        matching = [index for index in inspector.get_indexes(table) if index["name"] == name]
        assert len(matching) == 1
        assert matching[0]["column_names"] == columns
        assert matching[0]["unique"] == 0


def _installation_marker(engine: Engine) -> list[tuple]:
    with engine.connect() as connection:
        rows = connection.exec_driver_sql(
            "SELECT id, installation_id, payload_json, evidence_hash "
            "FROM source_coverage_installation"
        ).all()
    assert len(rows) == 1
    identity, installation_id, raw, evidence_hash = rows[0]
    payload = json.loads(raw)
    assert identity == 1
    assert str(UUID(installation_id)) == installation_id
    assert set(payload) == {
        "version", "installation_id", "installed_at", "member_count", "membership_hash",
        "evidence_hash",
    }
    assert payload["version"] == "source-coverage-installation-v1"
    assert payload["installation_id"] == installation_id
    assert datetime.fromisoformat(payload["installed_at"]).utcoffset() is not None
    assert payload["member_count"] == 0
    assert payload["membership_hash"] == sha256(
        b"source-coverage-membership-v1\0[]"
    ).hexdigest()
    unsigned = {key: value for key, value in payload.items() if key != "evidence_hash"}
    canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False)
    assert payload["evidence_hash"] == evidence_hash == sha256(
        b"source-coverage-installation-v1\0" + canonical.encode("utf-8")
    ).hexdigest()
    return [tuple(rows[0])]


def test_upgrade_repeat_downgrade_and_reupgrade_preserve_every_stored_row(populated_database):
    engine = populated_database
    before = _stored_rows(engine)
    assert "daily_plan_record" not in before
    after_upgrade = before | {
        "daily_plan_record": [],
        "market_index_acquisition_state": [],
        "simulation_capital_book": [],
        "simulation_capital_event": [],
        "source_coverage_cutover": [],
        "source_coverage_input": [],
        "source_coverage_assessment": [],
        "source_coverage_review": [],
    }
    indexes_before = {table: inspect(engine).get_indexes(table) for table in EXPECTED_INDEXES}

    marker = None
    for _ in range(2):
        upgrade_database(engine)
        _assert_history_indexes(engine)
        observed_marker = _installation_marker(engine)
        if marker is None:
            marker = observed_marker
            after_upgrade["source_coverage_installation"] = marker
        assert observed_marker == marker
        assert _stored_rows(engine) == after_upgrade
        with engine.connect() as connection:
            assert (
                connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
                == LATEST_REVISION
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
    reinstalled_marker = _installation_marker(engine)
    assert reinstalled_marker[0][1] != marker[0][1]
    assert _stored_rows(engine) == after_upgrade | {
        "source_coverage_installation": reinstalled_marker,
    }
    with engine.connect() as connection:
        assert (
            connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
            == LATEST_REVISION
        )


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
