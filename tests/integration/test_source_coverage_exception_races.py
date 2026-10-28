"""Current source reads belong inside the real exception writer transaction."""

import pytest
from sqlalchemy import delete, text
from sqlalchemy.exc import OperationalError
from tests.integration.test_source_coverage_exception_actions import (
    _append_bundle,
    _approval_command,
    _approved,
    _candidate,
    _expected,
    _ledger,
    _preview,
    _stale_source,
)
from tests.integration.test_source_coverage_exception_actions import (
    exception_chain as exception_chain,
)

from trade_plan_monitor.runtime.market_exceptions import apply_exception_decision
from trade_plan_monitor.state import source_action_authority
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.daily_repository import DailyRepository
from trade_plan_monitor.state.market_exception_service import ExceptionAuthorityError
from trade_plan_monitor.state.source_coverage_store import SourceCoverageStore


@pytest.mark.parametrize("stage", ["preview", "approve"])
def test_current_source_is_rechecked_inside_the_real_exception_writer(
    exception_chain, monkeypatch, stage,
):
    chain = exception_chain
    candidate = _candidate(chain)
    shown = _preview(chain, candidate) if stage == "approve" else None
    original = source_action_authority.require_source_action_authority
    observed = []

    def guarded(work, version_id, **kwargs):
        # Observe the actual proof reader; never replace its result with a fake COMPLETE.
        basis = original(work, version_id, **kwargs)
        assert basis.basis == "CURRENT" and version_id == candidate.binding.plan_version_id
        with chain.plans._session_factory() as other:
            other.execute(text("PRAGMA busy_timeout=0"))
            store = SourceCoverageStore(other)
            old = store.latest(version_id)
            with pytest.raises(OperationalError, match="locked"):
                store.append(version_id, old.assessment, inputs=old.inputs,
                    expected_revision=old.revision, command_id="competing-source-check",
                    now=chain.now)
            other.rollback()
        observed.append(basis.coverage_evidence_hash)
        return basis

    monkeypatch.setattr(source_action_authority, "require_source_action_authority", guarded)
    if shown is None:
        assert _preview(chain, candidate).quantity == _expected(chain)
    else:
        with chain.plans._unit_of_work() as work:
            receipt = apply_exception_decision(work, _approval_command(shown), now=chain.now)
            work.commit()
        assert receipt.candidate.frozen_quantity == _expected(chain)
    assert observed, "The real current source reader must run under the already-held writer."
    with chain.plans._unit_of_work() as work:
        assert SourceCoverageStore(work.daily.session).latest(chain.version["id"]).revision == 1


def test_source_writer_winning_before_approval_forces_a_fresh_check_after_retry(exception_chain):
    chain = exception_chain
    shown = _preview(chain, _candidate(chain))
    command = _approval_command(shown)
    with chain.plans._unit_of_work() as writer:
        _append_bundle(writer, chain, command_id="source-wins-the-exception-race")
        with chain.plans._unit_of_work() as other:
            other.daily.session.execute(text("PRAGMA busy_timeout=0"))
            with pytest.raises(ExceptionAuthorityError, match="EXCEPTION_CONCURRENT_COMMAND"):
                apply_exception_decision(other, command, now=chain.now)
        writer.commit()
    before = _ledger(chain)
    with pytest.raises(ExceptionAuthorityError, match="SOURCE_COVERAGE_STALE"):
        with chain.plans._unit_of_work() as work:
            apply_exception_decision(work, command, now=chain.now)
            work.commit()
    assert shown.quantity == _expected(chain)
    assert _ledger(chain) == before


def test_signal_write_failure_rolls_back_the_approval_and_preserves_its_whole_quantity(
    exception_chain, monkeypatch,
):
    chain = exception_chain
    shown = _preview(chain, _candidate(chain))
    command = _approval_command(shown)
    before = _ledger(chain)
    original = DailyRepository.save

    def fail_after_signal(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        if kwargs.get("kind") == "SIGNAL":
            raise RuntimeError("synthetic failure after staged exception signal")
        return result

    monkeypatch.setattr(DailyRepository, "save", fail_after_signal)
    with pytest.raises(RuntimeError, match="after staged exception signal"):
        with chain.plans._unit_of_work() as work:
            apply_exception_decision(work, command, now=chain.now)
            work.commit()
    assert _ledger(chain) == before
    monkeypatch.setattr(DailyRepository, "save", original)
    with chain.plans._unit_of_work() as work:
        approved = apply_exception_decision(work, command, now=chain.now)
        work.commit()
    assert shown.quantity == approved.candidate.frozen_quantity == _expected(chain)


def test_completed_receipt_replay_cannot_recreate_a_missing_signal_after_source_changes(
    exception_chain,
):
    chain = exception_chain
    _, command, approved = _approved(chain)
    with chain.plans._unit_of_work() as work:
        work.daily.session.execute(delete(DailyRecord).where(
            DailyRecord.id == approved.candidate.binding.occurrence_id))
        work.commit()
    _stale_source(chain)
    before = _ledger(chain)
    with chain.plans._unit_of_work() as work:
        replay = apply_exception_decision(work, command, now=chain.now)
        work.commit()
    assert replay == approved
    assert _ledger(chain) == before, "Historical command replay must not manufacture a new signal."
