"""Durable exception state is additive, validated and append-only."""

from datetime import date, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from tests.integration.test_index_permission_scope_migration import _migrate

from trade_plan_monitor.state.database import create_sqlite_engine
from trade_plan_monitor.state.market_exception_models import ExceptionBinding, new_candidate

NOW = datetime(2026, 9, 18, 16, tzinfo=ZoneInfo("Asia/Shanghai"))


def binding(**changes):
    return ExceptionBinding.model_validate(dict(
        occurrence_id="a" * 64, symbol="601021.SH", lineage="plan-one", rule_id="buy",
        plan_version_id=str(uuid4()), review_id="review-one", activation_revision=1,
        content_hash="b" * 64, route="WEAK_MINIMUM", decision_session=date(2026, 9, 18),
        evidence_cutoff=NOW, execution_date=date(2026, 9, 22),
        expires_at=datetime(2026, 9, 22, 15, tzinfo=NOW.tzinfo),
        evidence_hash="c" * 64, consumed_hash="d" * 64, grid_hash="e" * 64,
        base_quantity=100, minimum=100, increment=100,
    ) | changes)


def test_candidate_is_non_executable_and_digest_checked():
    candidate = new_candidate(binding(), NOW)
    assert candidate.state == "PENDING"
    assert candidate.frozen_quantity is None
    assert candidate.approval_id is None
    raw = candidate.model_dump(mode="json")
    raw["binding"]["base_quantity"] = 200
    with pytest.raises(ValueError, match="hash"):
        type(candidate).model_validate(raw)
    raw = candidate.model_dump(mode="json") | {"version": "future"}
    with pytest.raises(ValueError):
        type(candidate).model_validate(raw)


@pytest.mark.parametrize("state,actor", [
    ("APPROVED", "LOCAL_USER"), ("REJECTED", "LOCAL_USER"),
    ("REVOKED", "LOCAL_USER"), ("EXPIRED", "SYSTEM"),
    ("INVALIDATED", "SYSTEM"), ("CONSUMED", "SYSTEM"),
])
def test_event_actor_is_explicit_hashed_and_transition_bound(state, actor):
    from trade_plan_monitor.domain.daily_hash import daily_hash
    from trade_plan_monitor.state.market_exception_models import transition_candidate

    candidate = new_candidate(binding(), NOW)
    approved, _ = transition_candidate(
        candidate, to_state="APPROVED", command_id="approve", expected_revision=1,
        now=NOW, reason="Explicit local approval", quantity=100, preview_hash="f" * 64)
    before = approved if state in {"REVOKED", "CONSUMED"} else candidate
    _, event = transition_candidate(
        before, to_state=state, command_id="test-actor", expected_revision=1,
        now=NOW, reason="Explicit audit test",
        quantity=100 if state == "APPROVED" else None,
        preview_hash="f" * 64 if state == "APPROVED" else None)
    raw = event.model_dump(mode="json")
    assert raw["actor_kind"] == actor
    for replacement in (None, "AI", "SYSTEM" if actor == "LOCAL_USER" else "LOCAL_USER"):
        changed = dict(raw)
        if replacement is None:
            changed.pop("actor_kind")
        else:
            changed["actor_kind"] = replacement
        changed["event_hash"] = daily_hash(event.version, {
            key: value for key, value in changed.items() if key != "event_hash"})
        with pytest.raises(ValueError):
            type(event).model_validate(changed)


def test_client_commands_cannot_claim_actor_identity():
    from trade_plan_monitor.state.market_exception_service import ExceptionDecisionCommand

    with pytest.raises(ValueError):
        ExceptionDecisionCommand.model_validate(dict(
            command_id="forged", candidate_id="a" * 64, expected_revision=1,
            decision="REJECT", reason="No client actor", actor_kind="LOCAL_USER"))


def test_migration_preserves_bytes_and_refuses_lossy_downgrade(tmp_path):
    engine = create_sqlite_engine(tmp_path / "migration.sqlite")
    _migrate(engine, "0025_index_close_display")
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO daily_plan_record VALUES "
            "('old','REPORT','601021.SH','old',1,'{\"preserved\":  1}',:at,:at)"
        ), {"at": NOW.isoformat()})
    _migrate(engine, "head")
    with engine.begin() as connection:
        assert connection.execute(text(
            "SELECT payload_json FROM daily_plan_record WHERE id='old'"
        )).scalar_one() == '{"preserved":  1}'
        connection.execute(text(
            "INSERT INTO daily_plan_record VALUES "
            "('candidate','EXCEPTION_CANDIDATE','601021.SH','old',1,'{}',:at,:at)"
        ), {"at": NOW.isoformat()})
    with pytest.raises(RuntimeError, match="refuses"):
        _migrate(engine, "0025_index_close_display", downgrade=True)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM daily_plan_record")).scalar_one() == 2
    engine.dispose()


def test_repository_reopen_and_append_only(tmp_path):
    from sqlalchemy.orm import Session

    from trade_plan_monitor.state.daily_repository import DailyRepository
    from trade_plan_monitor.state.market_exception_repository import ExceptionRepository

    engine = create_sqlite_engine(tmp_path / "records.sqlite")
    _migrate(engine, "head")
    candidate = new_candidate(binding(), NOW)
    def repository(session):
        return ExceptionRepository(DailyRepository(
            session, clock=lambda: NOW, id_factory=lambda: str(uuid4())))
    with Session(engine) as session:
        stored = repository(session).create(candidate)
        assert stored["revision"] == 1
        session.commit()
    with Session(engine) as session:
        repo = repository(session)
        assert repo.get(candidate.candidate_id)["payload"] == candidate.model_dump(mode="json")
        assert repo.create(candidate)["revision"] == 1
        with pytest.raises(ValueError, match="binding"):
            repo.create(new_candidate(binding(), NOW))
        session.rollback()
    engine.dispose()


def test_events_atomic_immutable_and_terminal(tmp_path):
    from sqlalchemy.orm import Session

    from trade_plan_monitor.state.daily_repository import DailyRepository
    from trade_plan_monitor.state.market_exception_models import transition_candidate
    from trade_plan_monitor.state.market_exception_repository import ExceptionRepository

    engine = create_sqlite_engine(tmp_path / "events.sqlite")
    _migrate(engine, "head")
    candidate = new_candidate(binding(), NOW)
    with Session(engine) as session:
        daily = DailyRepository(session, clock=lambda: NOW, id_factory=lambda: str(uuid4()))
        repo = ExceptionRepository(daily)
        repo.create(candidate)
        session.commit()
        rejected, event = transition_candidate(
            candidate, to_state="REJECTED", command_id="reject", expected_revision=1,
            now=NOW, reason="Explicit rejection")
        repo.transition(rejected, event, expected_revision=1)
        session.rollback()  # Crash before commit leaves neither event nor transition.
        assert repo.get(candidate.candidate_id)["payload"]["state"] == "PENDING"
        assert daily.get(event.event_id) is None
        repo.transition(rejected, event, expected_revision=1)
        session.commit()
        with pytest.raises(ValueError, match="append-only"):
            daily.save(event.event_id, kind="EXCEPTION_EVENT", symbol=candidate.binding.symbol,
                       lineage=candidate.binding.lineage, payload=event.model_dump(mode="json"),
                       expected_revision=1)
        with pytest.raises(ValueError, match="illegal"):
            transition_candidate(rejected, to_state="APPROVED", command_id="retry",
                                 expected_revision=2, now=NOW, reason="Cannot reopen",
                                 quantity=100, preview_hash="f" * 64)
    with Session(engine) as session:
        repo = ExceptionRepository(DailyRepository(
            session, clock=lambda: NOW, id_factory=lambda: str(uuid4())))
        assert repo.get(candidate.candidate_id)["payload"] == rejected.model_dump(mode="json")
        assert repo.create(candidate)["payload"]["state"] == "REJECTED"
    engine.dispose()


def test_command_identity_unique_across_occurrences(tmp_path):
    from sqlalchemy.exc import IntegrityError

    engine = create_sqlite_engine(tmp_path / "unique.sqlite")
    _migrate(engine, "head")
    statement = text(
        "INSERT INTO daily_plan_record VALUES "
        "(:id,'EXCEPTION_EVENT','601021.SH','old',1,"
        "'{\"command_id\":\"same-command\"}',:at,:at)")
    with engine.begin() as connection:
        connection.execute(statement, {"id": "one", "at": NOW.isoformat()})
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(statement, {"id": "two", "at": NOW.isoformat()})
    engine.dispose()
