"""Migration contract for the durable live-monitor projection store."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect

from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import SymbolHealthStatus
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

_REVISION = "0009_live_monitor_projection"
_PREVIOUS_REVISION = "0008_market_index_monitor_event"
_SUPPORTED_PRIOR_REVISIONS = (
    "0001_initial",
    "0002_ai_provider_configuration",
    "0003_episode_cursor",
    "0004_alert_sequence",
    "0005_evaluation_kind",
    "0006_monitor_event",
    "0007_plan_web_state",
    _PREVIOUS_REVISION,
)
_NEW_TABLES = frozenset(
    {
        "evaluation_result",
        "market_index_snapshot",
        "market_index_snapshot_head",
        "pending_official_close",
        "symbol_decision_head",
        "symbol_health_projection",
    }
)


def _alembic_config(engine: Engine) -> Config:
    migrations_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "trade_plan_monitor"
        / "state"
        / "migrations"
    )
    config = Config()
    config.set_main_option("script_location", str(migrations_path))
    config.attributes["connection"] = engine.connect()
    return config


def _upgrade(engine: Engine, revision: str) -> None:
    config = _alembic_config(engine)
    connection = config.attributes["connection"]
    try:
        with connection.begin():
            command.upgrade(config, revision)
    finally:
        connection.close()


def _downgrade(engine: Engine, revision: str) -> None:
    config = _alembic_config(engine)
    connection = config.attributes["connection"]
    try:
        with connection.begin():
            command.downgrade(config, revision)
    finally:
        connection.close()


def _revision(engine: Engine) -> str:
    with engine.connect() as connection:
        return connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()


def _revision_number(revision: str) -> int:
    return int(revision[:4])


def _seed_identity_bearing_history(engine: Engine, revision: str) -> dict[str, object]:
    revision_number = _revision_number(revision)
    observed_at = "2026-09-05T10:00:18+08:00"
    bucket_end = "2026-09-05T10:00:00+08:00"
    source_text = "plan: 华亚智能\nbytes: exact\r\n"
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO plan_source (id, source_text, source_hash, created_at) "
            "VALUES (:id, :source_text, :source_hash, :created_at)",
            {
                "id": "00000000-0000-4000-8000-000000000001",
                "source_text": source_text,
                "source_hash": "1" * 64,
                "created_at": observed_at,
            },
        )
        connection.exec_driver_sql(
            "INSERT INTO plan_version "
            "(id, plan_id, version, symbol, plan_hash, status, payload_json, "
            "source_id, revision, created_at) VALUES "
            "(:id, 'migration-plan', 1, '003043.SZ', :plan_hash, 'ACTIVE', "
            ":payload_json, :source_id, 3, :created_at)",
            {
                "id": "00000000-0000-4000-8000-000000000002",
                "plan_hash": "2" * 64,
                "payload_json": '{"exact":"历史值","version":1}',
                "source_id": "00000000-0000-4000-8000-000000000001",
                "created_at": observed_at,
            },
        )
        connection.exec_driver_sql(
            "INSERT INTO active_plan (symbol, plan_version_id, activated_at, revision) "
            "VALUES ('003043.SZ', :plan_version_id, :activated_at, 3)",
            {
                "plan_version_id": "00000000-0000-4000-8000-000000000002",
                "activated_at": observed_at,
            },
        )
        connection.exec_driver_sql(
            "INSERT INTO symbol_health "
            "(symbol, status, latest_bar_end, data_age_seconds, gap_json, "
            "error_streak, revision) VALUES "
            "('003043.SZ', 'LIVE', :latest, 18, '[]', 0, 7)",
            {"latest": bucket_end},
        )
        if revision_number < 5:
            connection.exec_driver_sql(
                "INSERT INTO evaluation_ledger "
                "(plan_hash, symbol, bucket_end, formula_version, result_hash, evaluated_at) "
                "VALUES (:plan_hash, '003043.SZ', :target, 'ta-v1', :result_hash, "
                ":evaluated_at)",
                {
                    "plan_hash": "2" * 64,
                    "target": bucket_end,
                    "result_hash": "3" * 64,
                    "evaluated_at": observed_at,
                },
            )
        else:
            connection.exec_driver_sql(
                "INSERT INTO evaluation_ledger "
                "(plan_hash, symbol, evaluation_kind, target_value, formula_version, "
                "result_hash, evaluated_at) VALUES "
                "(:plan_hash, '003043.SZ', 'INTRADAY', :target, 'ta-v1', "
                ":result_hash, :evaluated_at)",
                {
                    "plan_hash": "2" * 64,
                    "target": bucket_end,
                    "result_hash": "3" * 64,
                    "evaluated_at": observed_at,
                },
            )
        if revision_number >= 2:
            connection.exec_driver_sql(
                "INSERT INTO ai_provider_configuration "
                "(id, display_name, provider_type, base_url, model_name, key_ref, "
                "environment_variable, timeout_seconds, max_retries, max_input_chars, "
                "max_output_tokens, temperature_milli, prompt_version, enabled, revision, "
                "created_at, updated_at) VALUES "
                "('00000000-0000-4000-8000-000000000003', '历史配置', "
                "'OPENAI_COMPATIBLE', 'https://example.invalid/v1', 'exact-model', "
                "'ai/provider/exact', NULL, 15, 0, 4096, 512, 0, 'prompt-v1', 0, 4, "
                ":created_at, :updated_at)",
                {"created_at": observed_at, "updated_at": observed_at},
            )
        if revision_number in {4, 5}:
            connection.exec_driver_sql(
                "UPDATE alert_sequence SET last_sequence = 41 WHERE singleton_id = 1"
            )
        if revision_number >= 6:
            connection.exec_driver_sql(
                "UPDATE monitor_sequence SET last_sequence = 41 WHERE singleton_id = 1"
            )
            connection.exec_driver_sql(
                "INSERT INTO monitor_event "
                "(id, sequence, event_type, schema_version, aggregate_id, payload_json, "
                "occurred_at) VALUES "
                "('00000000-0000-4000-8000-000000000041', 41, "
                "'symbol.health.updated', 1, '003043.SZ', :payload, :occurred_at)",
                {
                    "payload": (
                        '{"entityId":"003043.SZ","revision":7,'
                        '"status":"LIVE","symbol":"003043.SZ"}'
                    ),
                    "occurred_at": observed_at,
                },
            )
        if revision_number >= 7:
            connection.exec_driver_sql(
                "INSERT INTO plan_version_review (plan_version_id, review_issues_json) "
                "VALUES ('00000000-0000-4000-8000-000000000002', '[]')"
            )
            connection.exec_driver_sql(
                "INSERT INTO plan_activation_state "
                "(symbol, plan_version_id, revision, changed_at) VALUES "
                "('003043.SZ', '00000000-0000-4000-8000-000000000002', 3, :changed_at)",
                {"changed_at": observed_at},
            )
        return {
            "active_plan": connection.exec_driver_sql("SELECT * FROM active_plan").all(),
            "ai_provider_configuration": (
                connection.exec_driver_sql(
                    "SELECT * FROM ai_provider_configuration"
                ).all()
                if revision_number >= 2
                else None
            ),
            "evaluation": (
                "2" * 64,
                "003043.SZ",
                "INTRADAY",
                bucket_end,
                "ta-v1",
                "3" * 64,
                observed_at,
            ),
            "monitor_event": (
                connection.exec_driver_sql("SELECT * FROM monitor_event").all()
                if revision_number >= 6
                else None
            ),
            "plan_activation_state": (
                connection.exec_driver_sql("SELECT * FROM plan_activation_state").all()
                if revision_number >= 7
                else None
            ),
            "plan_source": connection.exec_driver_sql("SELECT * FROM plan_source").all(),
            "plan_version": connection.exec_driver_sql("SELECT * FROM plan_version").all(),
            "plan_version_review": (
                connection.exec_driver_sql("SELECT * FROM plan_version_review").all()
                if revision_number >= 7
                else None
            ),
            "sequence": (
                connection.exec_driver_sql("SELECT * FROM alert_sequence").all()
                if revision_number in {4, 5}
                else connection.exec_driver_sql("SELECT * FROM monitor_sequence").all()
                if revision_number >= 6
                else None
            ),
            "source_text": source_text,
            "symbol_health": connection.exec_driver_sql(
                "SELECT * FROM symbol_health"
            ).all(),
        }


def test_0009_adds_only_the_six_projection_tables_and_preserves_legacy_identities(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    evaluated_at = "2026-09-05T10:00:00+08:00"
    target_value = "2026-09-05T10:00:00+08:00"

    try:
        _upgrade(engine, _PREVIOUS_REVISION)
        tables_before = frozenset(inspect(engine).get_table_names())
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO evaluation_ledger "
                "(plan_hash, symbol, evaluation_kind, target_value, formula_version, "
                "result_hash, evaluated_at) VALUES "
                "(:plan_hash, '003043.SZ', 'INTRADAY', :target_value, 'ta-v1', "
                ":result_hash, :evaluated_at)",
                {
                    "plan_hash": "a" * 64,
                    "target_value": target_value,
                    "result_hash": "b" * 64,
                    "evaluated_at": evaluated_at,
                },
            )
            connection.exec_driver_sql(
                "UPDATE monitor_sequence SET last_sequence = 41 WHERE singleton_id = 1"
            )
            connection.exec_driver_sql(
                "INSERT INTO monitor_event "
                "(id, sequence, event_type, schema_version, aggregate_id, payload_json, "
                "occurred_at) VALUES "
                "('00000000-0000-4000-8000-000000000041', 41, "
                "'symbol.snapshot.updated', 1, '003043.SZ', '{}', :occurred_at)",
                {"occurred_at": evaluated_at},
            )
            legacy_rows = {
                "evaluation": connection.exec_driver_sql(
                    "SELECT * FROM evaluation_ledger"
                ).all(),
                "events": connection.exec_driver_sql("SELECT * FROM monitor_event").all(),
                "sequence": connection.exec_driver_sql("SELECT * FROM monitor_sequence").all(),
            }

        _upgrade(engine, _REVISION)

        assert _revision(engine) == _REVISION
        assert frozenset(inspect(engine).get_table_names()) == tables_before | _NEW_TABLES
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT * FROM evaluation_ledger").all() == (
                legacy_rows["evaluation"]
            )
            assert connection.exec_driver_sql("SELECT * FROM monitor_event").all() == (
                legacy_rows["events"]
            )
            assert connection.exec_driver_sql("SELECT * FROM monitor_sequence").all() == (
                legacy_rows["sequence"]
            )
            assert connection.exec_driver_sql("SELECT * FROM evaluation_result").all() == []
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    finally:
        engine.dispose()


@pytest.mark.parametrize("start_revision", _SUPPORTED_PRIOR_REVISIONS)
def test_0009_upgrades_from_every_supported_prior_revision(
    tmp_path: Path,
    start_revision: str,
) -> None:
    engine = create_sqlite_engine(tmp_path / f"monitor-{start_revision}.db")
    try:
        _upgrade(engine, start_revision)
        _upgrade(engine, _REVISION)

        assert _revision(engine) == _REVISION
        assert _NEW_TABLES.issubset(inspect(engine).get_table_names())
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    finally:
        engine.dispose()


@pytest.mark.parametrize("start_revision", _SUPPORTED_PRIOR_REVISIONS)
def test_0009_preserves_populated_identity_rows_from_every_supported_revision(
    tmp_path: Path,
    start_revision: str,
) -> None:
    engine = create_sqlite_engine(tmp_path / f"populated-{start_revision}.db")
    try:
        _upgrade(engine, start_revision)
        before = _seed_identity_bearing_history(engine, start_revision)

        _upgrade(engine, _REVISION)

        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT * FROM plan_source").all() == before[
                "plan_source"
            ]
            assert connection.exec_driver_sql("SELECT * FROM plan_version").all() == before[
                "plan_version"
            ]
            assert connection.exec_driver_sql("SELECT * FROM active_plan").all() == before[
                "active_plan"
            ]
            assert connection.exec_driver_sql("SELECT * FROM symbol_health").all() == before[
                "symbol_health"
            ]
            assert connection.exec_driver_sql(
                "SELECT plan_hash, symbol, evaluation_kind, target_value, formula_version, "
                "result_hash, evaluated_at FROM evaluation_ledger"
            ).one() == before["evaluation"]
            assert connection.exec_driver_sql(
                "SELECT source_text FROM plan_source"
            ).scalar_one() == before["source_text"]
            if before["ai_provider_configuration"] is not None:
                assert connection.exec_driver_sql(
                    "SELECT * FROM ai_provider_configuration"
                ).all() == before["ai_provider_configuration"]
            if before["monitor_event"] is not None:
                assert connection.exec_driver_sql("SELECT * FROM monitor_event").all() == before[
                    "monitor_event"
                ]
            if before["sequence"] is not None:
                assert connection.exec_driver_sql(
                    "SELECT * FROM monitor_sequence"
                ).all() == before["sequence"]
            if before["plan_version_review"] is not None:
                assert connection.exec_driver_sql(
                    "SELECT * FROM plan_version_review"
                ).all() == before["plan_version_review"]
                assert connection.exec_driver_sql(
                    "SELECT * FROM plan_activation_state"
                ).all() == before["plan_activation_state"]
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    finally:
        engine.dispose()


def test_0009_empty_projection_store_downgrades_cleanly(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")

    try:
        _upgrade(engine, _REVISION)
        _downgrade(engine, _PREVIOUS_REVISION)

        assert _revision(engine) == _PREVIOUS_REVISION
        assert _NEW_TABLES.isdisjoint(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_0009_first_public_health_projection_inherits_legacy_revision(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    zone = ZoneInfo("Asia/Shanghai")
    target = datetime(2026, 9, 4, 10, 0, tzinfo=zone)
    observed = datetime(2026, 9, 4, 10, 0, 18, tzinfo=zone)
    try:
        _upgrade(engine, _PREVIOUS_REVISION)
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO symbol_health "
                "(symbol, status, latest_bar_end, data_age_seconds, gap_json, "
                "error_streak, revision) VALUES "
                "('003043.SZ', 'LIVE', :latest, 18, '[]', 0, 7)",
                {"latest": target.isoformat()},
            )
        _upgrade(engine, _REVISION)
        session_factory = create_session_factory(engine)

        with SqlAlchemyUnitOfWork(session_factory, clock=lambda: observed) as work:
            after = work.health.upsert_symbol(
                symbol="003043.SZ",
                status=SymbolHealthStatus.LIVE,
                latest_bar_end=target,
                data_age_seconds=18,
                gaps=(),
                error_streak=0,
                expected_revision=7,
            )
            projection = work.projections.put_symbol_health(
                symbol="003043.SZ",
                revision=after.revision,
                projection={
                    "symbol": "003043.SZ",
                    "observedAt": observed,
                    "targetEnd": target,
                    "status": "LIVE",
                    "latestBarEnd": target,
                    "dataAgeSeconds": 18,
                    "requiredDataComplete": True,
                    "fresh": True,
                    "gaps": (),
                    "consecutiveIncompleteBuckets": 0,
                    "lastRequiredBucketEnd": target,
                    "errorCode": None,
                    "actionable": True,
                },
                observed_at=observed,
            )
            work.commit()

        assert after.revision == projection.revision == 8
    finally:
        engine.dispose()


def test_0009_refuses_unrecoverable_legacy_close_pending_before_ddl(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    try:
        _upgrade(engine, _PREVIOUS_REVISION)
        tables_before = frozenset(inspect(engine).get_table_names())
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO symbol_health "
                "(symbol, status, latest_bar_end, data_age_seconds, gap_json, "
                "error_streak, revision) VALUES "
                "('003043.SZ', 'CLOSE_PENDING', NULL, 0, "
                "'{\"closePendingTradeDate\":\"2026-09-04\",\"resume\":{}}', 1, 7)"
            )

        with pytest.raises(RuntimeError, match="resolve.*CLOSE_PENDING|CLOSE_PENDING.*resolved"):
            _upgrade(engine, _REVISION)

        assert _revision(engine) == _PREVIOUS_REVISION
        assert frozenset(inspect(engine).get_table_names()) == tables_before
        with engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT symbol, status, revision FROM symbol_health"
            ).one() == ("003043.SZ", "CLOSE_PENDING", 7)
    finally:
        engine.dispose()


def test_0009_refuses_populated_downgrade_before_any_destructive_ddl(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")

    try:
        _upgrade(engine, _REVISION)
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO symbol_health_projection "
                "(symbol, revision, activation_revision, runtime_generation, projection_json, "
                "observed_at, schema_version) "
                "VALUES ('003043.SZ', 1, 1, "
                "'00000000-0000-4000-8000-000000000001', '{}', "
                "'2026-09-05T10:00:00+08:00', 1)"
            )

        with pytest.raises(RuntimeError, match="refuses populated live monitor projection"):
            _downgrade(engine, _PREVIOUS_REVISION)

        assert _revision(engine) == _REVISION
        assert _NEW_TABLES.issubset(inspect(engine).get_table_names())
        with engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT symbol, revision FROM symbol_health_projection"
            ).one() == ("003043.SZ", 1)
    finally:
        engine.dispose()
