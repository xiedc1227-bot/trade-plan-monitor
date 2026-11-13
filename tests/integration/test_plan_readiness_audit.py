"""T20 audits disposable files only; no application lifespan or external I/O."""

import json
import socket
import sqlite3
from pathlib import Path

import pytest
from scripts.audit_plan_readiness import audit_database, main
from sqlalchemy import text

from trade_plan_monitor.state.database import create_sqlite_engine, upgrade_database


@pytest.fixture
def migrated(tmp_path):
    path = tmp_path / "temporary.sqlite3"
    engine = create_sqlite_engine(path)
    upgrade_database(engine)
    try:
        yield path, engine
    finally:
        engine.dispose()


def test_missing_path_is_reported_without_creating_anything(tmp_path):
    path = tmp_path / "missing" / "never-created.sqlite3"
    report = audit_database(path)
    assert report["database"] == "MISSING"
    assert report["installationStatus"] == "NOT_READY"
    assert not path.parent.exists()


def test_old_and_empty_schema_are_safe_and_unchanged(tmp_path):
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE alembic_version(version_num TEXT)")
        connection.execute("INSERT INTO alembic_version VALUES ('0001_initial')")
    before = path.read_bytes()
    report = audit_database(path)
    assert report["migration"] == ["0001_initial"]
    assert report["schema"]["plan_version"] == "MISSING"
    assert report["plans"] == []
    assert report["coverageInstallation"]["state"] == "MISSING"
    assert path.read_bytes() == before
    with sqlite3.connect(tmp_path / "empty.sqlite3"):
        pass
    assert audit_database(tmp_path / "empty.sqlite3")["database"] == "READABLE"


def test_migrated_marker_reuses_existing_signed_type_without_claiming_ready(migrated):
    path, _ = migrated
    report = audit_database(path)
    assert report["coverageInstallation"]["state"] == "VALID_PERSISTED_MARKER"
    assert report["coverageInstallation"]["installedAt"]
    assert report["provenance"] == "PERSISTED_ONLY"
    assert report["runtimeOwnership"] == "UNKNOWN"
    assert report["notificationConfiguration"] == "UNKNOWN"
    assert report["installationStatus"] == "NOT_READY"
    assert report["authorityGranted"] is False


def test_wal_commits_are_visible_and_audit_has_no_sql_writes(migrated, monkeypatch):
    path, engine = migrated
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO daily_plan_record VALUES "
            "('eval-1','EVALUATION','600000.SH','private',0,'{}',"
            "'2026-11-14T10:00:00+08:00','2026-11-14T10:00:00+08:00')"))
    assert Path(str(path) + "-wal").stat().st_size > 0
    real_connect = sqlite3.connect
    observed = []

    def connect(database, *args, **kwargs):
        assert "mode=ro" in database and "immutable" not in database
        assert kwargs["uri"] is True
        connection = real_connect(database, *args, **kwargs)
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("CREATE TABLE must_not_exist(value TEXT)")
        connection.set_trace_callback(observed.append)
        return connection

    def denied(*args, **kwargs):
        pytest.fail("audit attempted network or application database initialization")

    monkeypatch.setattr(sqlite3, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr("trade_plan_monitor.state.database.create_sqlite_engine", denied)
    monkeypatch.setattr("trade_plan_monitor.state.database.upgrade_database", denied)
    monkeypatch.setattr("requests.Session.request", denied)
    monkeypatch.setattr("httpx.Client.send", denied)
    monkeypatch.setattr("httpx.AsyncClient.send", denied)
    monkeypatch.setattr(
        "trade_plan_monitor.runtime.daily_service.DailyRuntimeEvaluationService.run_inputs", denied)
    before = {p: p.read_bytes() for p in (path, Path(str(path) + "-wal"))}
    report = audit_database(path)
    assert len(report["evaluations"]) == 1
    assert report["evaluations"][0]["createdAt"] == "2026-11-14T10:00:00+08:00"
    assert {p: p.read_bytes() for p in before} == before
    assert any("query_only" in statement.lower() for statement in observed)
    assert not any(statement.split()[0].upper() in {
        "INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP", "REPLACE"
    } for statement in observed)


def test_corrupt_marker_and_hostile_metadata_never_escape(migrated):
    path, engine = migrated
    secret = "https://private.example/token=DO_NOT_PRINT"
    with engine.begin() as connection:
        connection.execute(text("DROP TRIGGER pma_seal_source_coverage_installation_update"))
        connection.execute(text("UPDATE source_coverage_installation SET payload_json=:value"),
                           {"value": secret})
        connection.execute(text("INSERT INTO alert_event "
            "(id,sequence,dedup_key,payload_json,message_text,created_at) "
            "VALUES ('y',1,'unused','{}',:value,'2026-11-14T10:00:00+08:00')"),
            {"value": secret})
        connection.execute(text("INSERT INTO delivery_attempt "
            "(id,event_id,channel,attempt,status,delivered_at,error_code) "
            "VALUES ('x','y',:value,1,:value,:value,:value)"), {"value": secret})
    report = audit_database(path)
    assert report["coverageInstallation"]["state"] == "INVALID_PERSISTED_MARKER"
    assert secret not in json.dumps(report)
    assert report["deliveryAttempts"][0]["channel"] == "INVALID"
    assert report["deliveryAttempts"][0]["status"] == "INVALID"


def test_actual_saved_plan_scope_and_review_are_metadata_not_authority(migrated):
    from tests.integration.test_source_coverage_migration import _seed_legacy

    path, engine = migrated
    saved = _seed_legacy(engine)
    report = audit_database(path)
    plan = report["plans"][0]
    assert plan["versionId"] == saved.id
    assert plan["scope"] in {"TRADE_RULES", "MIXED"}
    assert plan["ordinaryRules"] == len(saved.draft.ordinary_rules)
    assert plan["riskBranches"] == len(saved.draft.risk_branches)
    assert plan["alertRules"] == len(saved.draft.alert_rules)
    assert report["reviews"][0]["confirmedAt"]
    assert report["reviews"][0]["binding"] == "NOT_REVALIDATED"
    assert saved.source not in json.dumps(report)
    assert report["installationStatus"] == "NOT_READY"


def test_oversized_raw_plan_is_not_loaded_or_printed(migrated):
    from tests.integration.test_source_coverage_migration import _seed_legacy

    path, engine = migrated
    _seed_legacy(engine)
    with engine.begin() as connection:
        connection.execute(text("UPDATE plan_version SET payload_json=:value"),
                           {"value": "PRIVATE" * 100_000})
    report = audit_database(path)
    assert report["plans"][0]["scope"] == "UNKNOWN"
    assert report["plans"][0]["payloadState"] == "INVALID_OR_UNSUPPORTED_OR_OVER_LIMIT"
    assert "PRIVATE" not in json.dumps(report)


def test_checkpointed_wal_without_sidecars_is_not_opened_or_repaired(migrated):
    path, engine = migrated
    engine.dispose()
    sidecars = [Path(str(path) + suffix) for suffix in ("-wal", "-shm")]
    assert not any(p.exists() for p in sidecars)
    before = path.read_bytes()
    report = audit_database(path)
    assert report["database"] == "WAL_SIDECARS_UNAVAILABLE"
    assert path.read_bytes() == before
    assert not any(p.exists() for p in sidecars)


def test_row_bounds_are_explicit_and_cannot_create_a_ready_claim(migrated):
    path, engine = migrated
    with engine.begin() as connection:
        for number in range(105):
            connection.execute(text("INSERT INTO daily_plan_record VALUES "
                "(:id,'EVALUATION','600000.SH','private',0,'{}',"
                "'2026-11-14T10:00:00+08:00','2026-11-14T10:00:00+08:00')"),
                {"id": str(number)})
    report = audit_database(path)
    assert len(report["evaluations"]) == 100
    assert "evaluations" in report["limitedSections"]
    assert len(json.dumps(report).encode()) <= 1024 * 1024
    assert report["installationStatus"] == "NOT_READY"


def test_cli_requires_read_only_and_writes_only_a_report(tmp_path, capsys):
    output = tmp_path / "reports"
    with pytest.raises(SystemExit):
        main(["--database", str(tmp_path / "missing.db"), "--output-dir", str(output)])
    assert not output.exists()
    assert main(["--database", str(tmp_path / "missing.db"), "--read-only",
                 "--output-dir", str(output)]) == 2
    report = json.loads((output / "audit.json").read_text(encoding="utf-8"))
    assert report["database"] == "MISSING"
    assert "missing.db" not in capsys.readouterr().out


def test_incompatible_schema_and_unrecognized_migration_are_not_echoed(tmp_path):
    path = tmp_path / "incompatible.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript("CREATE TABLE plan_version(id TEXT);"
                                 "CREATE TABLE alembic_version(version_num TEXT);")
        connection.execute("INSERT INTO alembic_version VALUES (?)", ("0001_private_key",))
    report = audit_database(path)
    assert report["schema"]["plan_version"] == "INCOMPATIBLE"
    assert report["migration"] == ["INVALID"]
    assert "private_key" not in json.dumps(report)


def test_corrupt_file_errors_do_not_reveal_path_or_contents(tmp_path):
    path = tmp_path / "private-path.sqlite3"
    path.write_bytes(b"RAW_PRIVATE_DATABASE_CONTENT")
    report = audit_database(path)
    assert report["database"] == "UNAVAILABLE_OR_BUDGET_EXCEEDED"
    assert "PRIVATE" not in json.dumps(report)
    assert "private-path" not in json.dumps(report)


def test_historical_delivered_attempt_is_not_current_channel_verification(migrated):
    path, engine = migrated
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO alert_event "
            "(id,sequence,dedup_key,payload_json,message_text,created_at) "
            "VALUES ('event',1,'unused','{}','private','2026-11-14T10:00:00+08:00')"))
        connection.execute(text("INSERT INTO delivery_attempt "
            "(id,event_id,channel,attempt,status,delivered_at) VALUES "
            "('attempt','event','IN_APP',1,'DELIVERED','2026-11-14T10:00:01+08:00')"))
    report = audit_database(path)
    assert report["deliveryAttempts"] == [{"channel": "IN_APP", "status": "DELIVERED",
        "deliveredAt": "2026-11-14T10:00:01+08:00", "nextRetryAt": None,
        "binding": "NOT_REVALIDATED"}]
    assert report["notificationConfiguration"] == "UNKNOWN"
    assert report["installationStatus"] == "NOT_READY"


def test_existing_output_is_preserved(tmp_path):
    output = tmp_path / "report"
    output.mkdir()
    result = output / "audit.json"
    result.write_text("previous evidence", encoding="utf-8")
    with pytest.raises(FileExistsError):
        main(["--database", str(tmp_path / "missing.db"), "--read-only",
              "--output-dir", str(output)])
    assert result.read_text(encoding="utf-8") == "previous evidence"


def test_persisted_heartbeat_and_legacy_evaluation_do_not_supply_current_owner(tmp_path):
    path = tmp_path / "partial.sqlite3"
    at = "2026-11-14T10:00:00+08:00"
    with sqlite3.connect(path) as connection:
        connection.executescript("CREATE TABLE runtime_liveness(last_alive_at TEXT);"
            "CREATE TABLE evaluation_result("
            "evaluation_kind TEXT,evaluated_at TEXT,source_at TEXT);")
        connection.execute("INSERT INTO runtime_liveness VALUES (?)", (at,))
        connection.execute("INSERT INTO evaluation_result VALUES ('INTRADAY',?,?)", (at, at))
    report = audit_database(path)
    assert report["persistedLiveness"] == [{"lastAliveAt": at, "authority": "UNKNOWN"}]
    assert report["legacyEvaluations"][0]["evaluatedAt"] == at
    assert report["runtimeOwnership"] == "UNKNOWN"
    assert report["installationStatus"] == "NOT_READY"


def test_current_version_and_review_are_not_lost_after_more_than_100_versions(migrated):
    from tests.integration.test_source_coverage_migration import _seed_legacy

    path, engine = migrated
    saved = _seed_legacy(engine)
    current = "ffffffff-ffff-4fff-bfff-ffffffffffff"
    with engine.begin() as connection:
        for number in range(105):
            identity = f"00000000-0000-4000-8000-{number + 100:012d}"
            connection.execute(text("INSERT INTO plan_version SELECT "
                ":id,:id,version,symbol,plan_hash,status,payload_json,"
                "source_id,revision,created_at "
                "FROM plan_version WHERE id=:seed"), {"id": identity, "seed": saved.id})
            connection.execute(text("INSERT INTO plan_review_provenance "
                "(plan_version_id,origin,source_hash,draft_hash,review_revision) "
                "SELECT :id,origin,source_hash,draft_hash,review_revision "
                "FROM plan_review_provenance WHERE plan_version_id=:seed"),
                {"id": identity, "seed": saved.id})
        connection.execute(text("INSERT INTO plan_version SELECT "
            ":id,:id,version,symbol,plan_hash,'ACTIVE',payload_json,source_id,revision,created_at "
            "FROM plan_version WHERE id=:seed"), {"id": current, "seed": saved.id})
        connection.execute(text("INSERT INTO active_plan VALUES "
            "('600000.SH',:id,'2026-11-14T10:00:00+08:00',1)"), {"id": current})
        connection.execute(text("INSERT INTO plan_review_provenance "
            "(plan_version_id,origin,source_hash,draft_hash,review_revision,confirmed_at) "
            "SELECT :id,origin,source_hash,draft_hash,1,'2026-11-14T09:00:00+08:00' "
            "FROM plan_review_provenance WHERE plan_version_id=:seed"),
            {"id": current, "seed": saved.id})
    first, second = audit_database(path), audit_database(path)
    assert first["plans"][0]["versionId"] == current
    assert first["reviews"][0]["versionId"] == current
    assert first["reviews"][0]["confirmedAt"] == "2026-11-14T09:00:00+08:00"
    assert first["activePlans"][0]["versionId"] == current
    assert first["activeReferenceGaps"] == []
    assert len(first["plans"]) == len(first["reviews"]) == 100
    assert {"plans", "plan_review_provenance"} <= set(first["limitedSections"])
    assert first["plans"] == second["plans"]
    assert first["reviews"] == second["reviews"]
    assert first["installationStatus"] == "NOT_READY"
