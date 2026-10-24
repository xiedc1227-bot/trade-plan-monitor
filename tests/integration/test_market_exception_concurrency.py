"""Independent connections cannot reopen or multiply occurrence authority."""

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session
from tests.integration import test_market_exception_authorization as authorization_fixture
from tests.integration.test_market_exception_authorization import approve, preview, setup
from tests.integration.test_market_exception_storage import NOW

from trade_plan_monitor.state.daily_repository import DailyRepository
from trade_plan_monitor.state.market_exception_models import ExceptionCandidate
from trade_plan_monitor.state.market_exception_repository import ExceptionRepository
from trade_plan_monitor.state.market_exception_service import (
    ExceptionAuthorityError,
    ExceptionDecisionCommand,
    ExceptionRevocationCommand,
    decide_exception,
    revoke_exception,
    terminate_exception,
)

ledger = authorization_fixture.ledger


def test_revoke_is_terminal_and_replayed_approval_cannot_reopen(ledger):
    candidate, context = setup(ledger)
    shown = preview(ledger, candidate, context)
    approved = approve(ledger, candidate, context, shown)
    command = ExceptionRevocationCommand(
        command_id="revoke", approval_id=approved.event.event_id, expected_revision=2,
        reason="Withdraw exact occurrence")
    revoked = revoke_exception(ledger, command, now=NOW)
    assert revoked.candidate.state == "REVOKED"
    assert revoke_exception(ledger, command, now=NOW) == revoked
    assert approve(ledger, candidate, context, shown) == approved
    assert ExceptionRepository(ledger).get(candidate.candidate_id)["payload"]["state"] == "REVOKED"
    with pytest.raises(ExceptionAuthorityError):
        approve(ledger, candidate, context, shown, command_id="another", expected_revision=3)


@pytest.mark.parametrize("approved", [False, True])
@pytest.mark.parametrize("state", ["EXPIRED", "INVALIDATED"])
def test_terminal_states_preserve_history_and_never_reopen(ledger, approved, state):
    candidate, context = setup(ledger)
    shown = preview(ledger, candidate, context)
    if approved:
        approve(ledger, candidate, context, shown)
    later = candidate.binding.expires_at if state == "EXPIRED" else NOW
    ledger.clock = lambda: later
    row = terminate_exception(ledger, candidate.candidate_id, state=state,
                              reason="Current authority ceased", now=later)
    assert row["payload"]["state"] == state
    assert terminate_exception(ledger, candidate.candidate_id, state=state,
                               reason="Repeated evaluation", now=later) == row
    assert ExceptionRepository(ledger).create(candidate)["payload"]["state"] == state
    ledger.session.commit()
    with Session(ledger.session.bind) as session:
        reopened = DailyRepository(session, clock=lambda: later, id_factory=lambda: str(uuid4()))
        assert ExceptionRepository(reopened).get(candidate.candidate_id) == row


def test_no_backdating_or_early_expiry(ledger):
    candidate, context = setup(ledger)
    with pytest.raises(ValueError):
        terminate_exception(ledger, candidate.candidate_id, state="EXPIRED", reason="Too early",
                            now=NOW)
    command = ExceptionDecisionCommand(
        command_id="backdated", candidate_id=candidate.candidate_id, expected_revision=1,
        decision="REJECT", reason="Cannot backdate")
    with pytest.raises(ExceptionAuthorityError):
        decide_exception(ledger, command, current=lambda _: context, now=NOW-timedelta(seconds=1))


@pytest.mark.parametrize("second", ["APPROVE", "REJECT"])
def test_two_connections_only_one_decision_wins(ledger, second):
    candidate, context = setup(ledger)
    shown = preview(ledger, candidate, context)
    ledger.session.commit()
    barrier = Barrier(2)

    def attempt(identity):
        with Session(ledger.session.bind) as session:
            daily = DailyRepository(session, clock=lambda: NOW, id_factory=lambda: str(uuid4()))
            barrier.wait(timeout=5)
            try:
                if identity == "two" and second == "REJECT":
                    result = decide_exception(daily, ExceptionDecisionCommand(
                        command_id=identity, candidate_id=candidate.candidate_id,
                        expected_revision=1, decision="REJECT", reason="Reject in competing tab"),
                        current=lambda _: context, now=NOW)
                else:
                    result = approve(daily, candidate, context, shown, command_id=identity)
                session.commit()
                return result.candidate.state
            except ExceptionAuthorityError:
                session.rollback()
                return "CONFLICT"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ["one", "two"]))
    assert results.count("CONFLICT") == 1
    assert sum(result in {"APPROVED", "REJECTED"} for result in results) == 1
    ledger.session.expire_all()
    row = ExceptionRepository(ledger).get(candidate.candidate_id)
    assert row["revision"] == 2
    restored = ExceptionCandidate.model_validate(row["payload"])
    assert restored.frozen_quantity == (100 if restored.state == "APPROVED" else None)


def test_command_reuse_with_changed_reason_conflicts(ledger):
    candidate, context = setup(ledger)
    shown = preview(ledger, candidate, context)
    approve(ledger, candidate, context, shown)
    with pytest.raises(ExceptionAuthorityError, match="REUSE"):
        approve(ledger, candidate, context, shown, reason="Changed intent")


def _reopen_process(args):
    from trade_plan_monitor.state.database import create_sqlite_engine

    path, identity = args
    engine = create_sqlite_engine(path)
    with Session(engine) as session:
        daily = DailyRepository(session, clock=lambda: NOW, id_factory=lambda: str(uuid4()))
        result = ExceptionRepository(daily).get(identity)
    engine.dispose()
    return result


def test_fresh_process_preserves_approved_evidence(ledger):
    candidate, context = setup(ledger)
    shown = preview(ledger, candidate, context)
    approved = approve(ledger, candidate, context, shown)
    ledger.session.commit()
    with ProcessPoolExecutor(max_workers=1) as pool:
        row = pool.submit(_reopen_process, (
            ledger.session.bind.url.database, candidate.candidate_id)).result(timeout=30)
    assert row["payload"] == approved.candidate.model_dump(mode="json")
    assert row["revision"] == approved.revision
