"""Explicit human intent freezes exact quantity without touching inventory."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session
from tests.integration.test_index_permission_scope_migration import _migrate
from tests.integration.test_market_exception_storage import NOW, binding

from trade_plan_monitor.state.daily_repository import DailyRepository
from trade_plan_monitor.state.database import create_sqlite_engine
from trade_plan_monitor.state.market_exception_models import new_candidate
from trade_plan_monitor.state.market_exception_repository import ExceptionRepository
from trade_plan_monitor.state.market_exception_service import (
    ExceptionAuthorityContext,
    ExceptionDecisionCommand,
    ExceptionPreviewCommand,
    decide_exception,
    preview_exception,
)


@pytest.fixture
def ledger(tmp_path):
    engine = create_sqlite_engine(tmp_path / "authorization.sqlite")
    _migrate(engine, "head")
    with Session(engine) as session:
        daily = DailyRepository(session, clock=lambda: NOW, id_factory=lambda: str(uuid4()))
        yield daily
    engine.dispose()


def setup(daily, *, route="WEAK_MINIMUM", base=100, capacity=500):
    candidate = new_candidate(binding(route=route, base_quantity=base), NOW)
    ExceptionRepository(daily).create(candidate)
    context = ExceptionAuthorityContext(
        binding_hash=candidate.binding_hash, inventory_revision=1, evaluation_revision=1,
        authority_hash="f" * 64, capacity=capacity, blockers=())
    return candidate, context


def preview(daily, candidate, context, quantity=None):
    return preview_exception(daily, ExceptionPreviewCommand(
        candidate_id=candidate.candidate_id, expected_revision=1, proposed_quantity=quantity),
        current=lambda _: context, now=NOW)


def approve(daily, candidate, context, shown, **changes):
    command = ExceptionDecisionCommand.model_validate(dict(
        command_id="approve-once", candidate_id=candidate.candidate_id, expected_revision=1,
        decision="APPROVE", reason="Explicit independent review", preview_id=shown.preview_id,
        preview_hash=shown.preview_hash,
    ) | changes)
    return decide_exception(daily, command, current=lambda _: context, now=NOW)


def test_preview_has_no_authority_and_exact_weak_approval(ledger):
    candidate, context = setup(ledger)
    shown = preview(ledger, candidate, context)
    assert shown.quantity == 100
    assert ExceptionRepository(ledger).get(candidate.candidate_id)["revision"] == 1
    result = approve(ledger, candidate, context, shown)
    assert result.candidate.state == "APPROVED"
    assert result.candidate.frozen_quantity == 100
    assert ledger.list(symbol=candidate.binding.symbol, kind="SIMULATION") == ()
    assert approve(ledger, candidate, context, shown) == result


@pytest.mark.parametrize("quantity", [None, 0, 150, 600])
def test_broken_invalid_or_missing_quantity_never_defaults(ledger, quantity):
    candidate, context = setup(ledger, route="BROKEN_STRONG", base=500)
    with pytest.raises(ValueError):
        preview(ledger, candidate, context, quantity)
    assert ExceptionRepository(ledger).get(candidate.candidate_id)["payload"]["state"] == "PENDING"


@pytest.mark.parametrize("quantity", [100, 300, 500])
def test_broken_approves_exact_explicit_quantity(ledger, quantity):
    candidate, context = setup(ledger, route="BROKEN_STRONG", base=500)
    shown = preview(ledger, candidate, context, quantity)
    assert approve(ledger, candidate, context, shown).candidate.frozen_quantity == quantity


@pytest.mark.parametrize("change", [
    {"inventory_revision": 2}, {"evaluation_revision": 2}, {"authority_hash": "a" * 64},
    {"binding_hash": "a" * 64}, {"capacity": None}, {"capacity": 0},
    {"blockers": ("HIGHER_PRIORITY_RISK",)},
])
def test_changed_or_unknown_current_authority_cannot_approve_old_preview(ledger, change):
    candidate, context = setup(ledger)
    shown = preview(ledger, candidate, context)
    current = ExceptionAuthorityContext.model_validate(context.model_dump() | change)
    with pytest.raises(ValueError):
        approve(ledger, candidate, current, shown)
    assert ExceptionRepository(ledger).get(candidate.candidate_id)["payload"]["state"] == "PENDING"


def test_reject_requires_reason_and_no_preview(ledger):
    candidate, context = setup(ledger)
    command = ExceptionDecisionCommand(
        command_id="reject-once", candidate_id=candidate.candidate_id, expected_revision=1,
        decision="REJECT", reason="Decline this occurrence")
    result = decide_exception(ledger, command, current=lambda _: context, now=NOW)
    assert result.candidate.state == "REJECTED"
    with pytest.raises(ValueError):
        ExceptionDecisionCommand.model_validate(command.model_dump() | {"reason": " "})
