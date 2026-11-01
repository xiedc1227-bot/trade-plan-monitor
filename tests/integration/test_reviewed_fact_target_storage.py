"""Private FACT codec and real temporary SQL; never a registration permission."""

import json
from datetime import datetime
from hashlib import sha256
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import URL, create_engine, event, select, text
from sqlalchemy.orm import Session
from tests.integration.test_daily_plan_chain import Chain
from tests.unit.test_daily_conditions import synthetic_series
from tests.unit.test_reviewed_fact_target_fences import _evaluate
from tests.unit.test_reviewed_fact_targets import _plan

from trade_plan_monitor.domain.reviewed_fact_targets import (
    ReviewedFactTarget,
    assess_unbound_fact,
    filter_unbound_facts,
    list_reviewed_fact_targets,
)
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.daily_repository import DailyRepository
from trade_plan_monitor.state.daily_state_models import DailyFactState
from trade_plan_monitor.state.models import AuditLog, Base
from trade_plan_monitor.state.repositories import RevisionConflictError
from trade_plan_monitor.web.routers.daily_plans import DailyFactCommand

OWNER = "11111111-1111-4111-8111-111111111111"
NOW = datetime(2026, 9, 22, 16, 5, tzinfo=ZoneInfo("Asia/Shanghai"))
LEGACY = dict(
    plan_version_id=OWNER,
    content_hash="115602b028d5716a224f7583d49e5e38c017e25e5c6eb52440ec47fd5e114837",
    kind="VOLUME_OR_CANDLE", trade_date="2026-09-22", signal_id=None, prior_signal_id=None,
    evidence="Human reviewed only the synthetic volume condition.", verified=True, satisfied=True,
    verified_at="2026-09-22T16:01:00+08:00", available_at="2026-09-22T16:02:00+08:00",
    official_evidence=None,
)
LEGACY_MODEL_BYTES = json.dumps(LEGACY, ensure_ascii=False, separators=(",", ":")).encode()
LEGACY_SQL_BYTES = json.dumps(LEGACY, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode()


@pytest.fixture
def database(tmp_path):
    engine = create_engine(URL.create("sqlite+pysqlite", database=str(tmp_path / "facts.sqlite3")))
    Base.metadata.create_all(engine, tables=[DailyRecord.__table__, AuditLog.__table__])
    try:
        yield engine
    finally:
        engine.dispose()


def _schema(engine):
    with engine.connect() as connection:
        return tuple(connection.execute(text(
            "SELECT type,name,tbl_name,sql FROM sqlite_schema "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")).all())


def _save(engine, payload, revision=0):
    with Session(engine) as session:
        repo = DailyRepository(session, clock=lambda: NOW, id_factory=lambda: str(uuid4()))
        result = repo.save("synthetic-fact", kind="FACT", symbol="601021.SH",
                           lineage="synthetic-daily", payload=payload, expected_revision=revision)
        session.commit()
        return result


def _read(engine):
    writes = []

    def observe(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER")):
            writes.append(statement)

    event.listen(engine, "before_cursor_execute", observe)
    try:
        # A new Session reads the actual committed SQL, never a writer's cached object.
        with Session(engine) as session:
            repo = DailyRepository(session, clock=lambda: NOW, id_factory=lambda: str(uuid4()))
            result = repo.get("synthetic-fact")
            raw = session.get(DailyRecord, "synthetic-fact").payload_json.encode()
            hashes = tuple(session.execute(select(AuditLog.before_hash, AuditLog.after_hash)
                           .order_by(AuditLog.id)).all())
        assert writes == []
        return result, raw, hashes
    finally:
        event.remove(engine, "before_cursor_execute", observe)


def _targeted(**changes):
    target = list_reviewed_fact_targets(_plan(), plan_version_id=OWNER,
                                        content_hash=LEGACY["content_hash"])[0]
    return {**LEGACY, "reviewed_fact_target": target.model_dump(), **changes}


def test_legacy_fact_model_and_actual_sql_keep_original_bytes_hash_and_revision(database):
    schema = _schema(database)
    assert {row[1] for row in schema if row[0] == "table"} == {"daily_plan_record", "audit_log"}
    model = DailyFactState.model_validate(LEGACY)
    assert model.model_dump_json().encode() == LEGACY_MODEL_BYTES
    assert "reviewed_fact_target" not in model.model_dump(mode="json")
    assert _save(database, LEGACY)["revision"] == 1
    read, raw, hashes = _read(database)
    digest = sha256(LEGACY_SQL_BYTES).hexdigest()
    assert raw == LEGACY_SQL_BYTES and hashes == ((None, digest),)
    assert read["payload"] == LEGACY
    assert DailyFactState.model_validate(read["payload"]).model_dump_json().encode() == (
        LEGACY_MODEL_BYTES)
    assert _save(database, LEGACY, revision=1)["revision"] == 2
    with pytest.raises(RevisionConflictError):
        _save(database, LEGACY, revision=1)
    assert _read(database)[1] == LEGACY_SQL_BYTES
    assert _schema(database) == schema


def test_actual_repo_accepts_private_target_without_model_preflight(database):
    payload = _targeted()
    assert _save(database, payload)["revision"] == 1
    read, _, _ = _read(database)
    assert read["payload"] == payload


@pytest.mark.parametrize("satisfied", [True, False])
def test_private_target_roundtrips_actual_sql_without_schema_change_or_old_authority(
    database, satisfied,
):
    payload = _targeted(satisfied=satisfied)
    schema = _schema(database)
    model = DailyFactState.model_validate(payload)
    assert isinstance(model.reviewed_fact_target, ReviewedFactTarget)
    assert model.model_dump(mode="json") == payload
    _save(database, payload)
    read, raw, hashes = _read(database)
    expected = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")).encode()
    assert raw == expected and hashes == ((None, sha256(expected).hexdigest()),)
    restored = DailyFactState.model_validate(read["payload"])
    assert restored == model and _schema(database) == schema
    assert assess_unbound_fact(_plan(), restored).reason == "INVALID_FACT"
    fact = {**read["payload"], "id": read["id"]}
    assert filter_unbound_facts(_plan(), (fact,)) == ()
    series = synthetic_series(count=114)[0]
    leaf = _plan().ordinary_rules[0].condition.conditions[0].model_dump(mode="json")
    for engine in ("daily", "unified"):
        result = _evaluate(engine, leaf, series, (fact,))
        assert result.outcome == "MISSING_INPUT" and result.fact_ids == ()


@pytest.mark.parametrize("target", [None, {}, {"version": "other"}])
def test_explicit_null_and_damaged_targets_are_rejected_before_sql_write(database, target):
    payload = {**LEGACY, "reviewed_fact_target": target}
    with pytest.raises(ValueError):
        DailyFactState.model_validate(payload)
    with pytest.raises(ValueError):
        _save(database, payload)
    with Session(database) as session:
        assert session.scalars(select(DailyRecord)).all() == []
        assert session.scalars(select(AuditLog)).all() == []


@pytest.mark.parametrize("field,value", [
    ("plan_version_id", "another-owner"), ("content_hash", "0" * 64),
])
def test_target_metadata_must_match_the_fact_itself(database, field, value):
    payload = _targeted()
    payload["reviewed_fact_target"][field] = value
    with pytest.raises(ValueError, match="target metadata"):
        DailyFactState.model_validate(payload)
    with pytest.raises(ValueError, match="target metadata"):
        _save(database, payload)


def test_nested_model_instance_is_revalidated_and_explicit_null_cannot_erase_target():
    payload = _targeted()
    payload["reviewed_fact_target"] = ReviewedFactTarget.model_construct(
        **{**payload["reviewed_fact_target"], "target_hash": "damaged"})
    with pytest.raises(ValueError):
        DailyFactState.model_validate(payload)
    valid = DailyFactState.model_validate(_targeted())
    with pytest.raises(ValueError):
        valid.model_copy(update={"reviewed_fact_target": None})


def test_codec_does_not_authenticate_native_paths_kinds_scope_or_sql_plan_owner(database):
    payload = _targeted(kind="TECHNICAL")
    payload["reviewed_fact_target"].update(owner_id="not-in-native-plan",
                                         condition_path="condition.conditions[49]",
                                         target_hash="0" * 64)
    # This store has no plan/version/source/review tables. Shape is not owner authority.
    model = DailyFactState.model_validate(payload)
    assert _save(database, model.model_dump(mode="json"))["revision"] == 1
    read, _, _ = _read(database)
    assert read["payload"] == payload
    assert assess_unbound_fact(_plan(), DailyFactState.model_validate(payload)).reason == (
        "INVALID_FACT")


@pytest.mark.parametrize("changes,message", [
    ({"available_at": "2026-09-22T16:00:00+08:00"}, "available before"),
    ({"trade_date": "2026-09-23"}, "available before"),
    ({"kind": "TRADABILITY"}, "official proof is required"),
    ({"kind": "FULL_SESSION_SUSPENSION"}, "official proof is required"),
    ({"kind": "INDEPENDENT_EVENT"}, "previous signal"),
    ({"kind": "SIGNAL_INVALIDATION", "satisfied": False}, "negative assertions"),
])
def test_target_cannot_bypass_existing_fact_proof_and_time_rules(changes, message):
    for payload in ({**LEGACY, **changes}, _targeted(**changes)):
        with pytest.raises(ValueError, match=message):
            DailyFactState.model_validate(payload)


def test_repo_clock_still_rejects_future_targeted_evidence(database):
    with pytest.raises(ValueError, match="not yet available"):
        _save(database, _targeted(verified_at="2026-09-22T16:06:00+08:00",
                                  available_at="2026-09-22T16:06:00+08:00"))
    with Session(database) as session:
        assert session.scalars(select(DailyRecord)).all() == []


def test_public_fact_command_and_actual_http_still_reject_both_target_spellings(tmp_path):
    command = dict(planVersionId=OWNER, contentHash=LEGACY["content_hash"],
                   factId="unsupported-public-target", kind=LEGACY["kind"],
                   tradeDate=LEGACY["trade_date"], evidence=LEGACY["evidence"], expectedRevision=0)
    assert DailyFactCommand.model_validate(command).kind == LEGACY["kind"]
    chain = Chain(tmp_path)
    with chain.client:
        for field in ("reviewedFactTarget", "reviewed_fact_target"):
            payload = {**command, field: _targeted()["reviewed_fact_target"]}
            with pytest.raises(ValueError):
                DailyFactCommand.model_validate(payload)
            result = chain.post("plan-facts", payload, status=422)
            assert result["error"]["code"] == "VALIDATION_ERROR"
        with chain.plans._unit_of_work() as work:
            assert work.daily.list(symbol="601021.SH", kind="FACT") == ()
