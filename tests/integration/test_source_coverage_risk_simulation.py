"""Actual runtime offers and simulations use the sealed historical risk grant."""

import json
from copy import deepcopy
from datetime import date, timedelta
from uuid import UUID

import pytest
from sqlalchemy import insert, text, update
from tests.integration.test_live_monitor_projection_migration import _upgrade
from tests.integration.test_market_linkage_review import source_mapping
from tests.integration.test_source_action_cutover import (
    _REVIEW,
    _daily,
    _risk_payload,
    _signal,
)
from tests.integration.test_source_action_cutover import (
    legacy as legacy,
)
from tests.integration.test_source_coverage_authority_save import _NOW

from trade_plan_monitor.ai.daily_review import build_daily_review
from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_json, daily_draft_sha256
from trade_plan_monitor.market_data.daily_data import DailyExecutionQuote
from trade_plan_monitor.runtime.daily_service import (
    DailyRuntimeEvaluationService,
    DailyRuntimeInputs,
)
from trade_plan_monitor.state.daily_accounting import DailyAccounting
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.daily_state_models import DailyRiskState
from trade_plan_monitor.state.models import (
    ActivePlan,
    PlanActivationState,
    PlanReviewProvenance,
    PlanSource,
    PlanVersion,
    TradingCalendar,
)
from trade_plan_monitor.state.simulation import (
    SimulationAuthorityError,
    SimulationCommand,
    simulate_inventory,
)
from trade_plan_monitor.state.source_coverage_store import SourceCoverageStore

_AT = _NOW + timedelta(minutes=3)
_SESSIONS = (date(2026, 10, 23), date(2026, 10, 26), _AT.date())


def _retained_core_case(legacy):
    """Establish a coherent old policy while still at 0027, then seal the real cutover."""
    case = legacy(upgraded=False)
    branch, severe = case.draft.risk_branches
    case.draft = case.draft.model_copy(update={"risk_branches": (
        branch.model_copy(update={"target_core_qty": 100}), severe)})
    source, mapping = source_mapping(case.draft)
    review = build_daily_review(case.draft, mapping, source)
    assert not review.issues
    case.cause_id, case.risk = _risk_payload(case.draft)
    with case.engine.begin() as connection:
        connection.execute(update(PlanSource).values(source_text=source,
            source_hash=review.source_hash))
        connection.execute(update(PlanVersion).values(payload_json=daily_draft_json(case.draft),
            plan_hash=daily_draft_sha256(case.draft)))
        connection.execute(update(PlanReviewProvenance).values(source_hash=review.source_hash,
            draft_hash=daily_draft_sha256(case.draft), content_hash=review.content_hash,
            review_evidence_hash=review.evidence_hash,
            mapping_json=canonical(mapping.model_dump(mode="json"))))
        old = connection.execute(text("SELECT payload_json FROM daily_plan_record "
            "WHERE id=:id"), {"id": "review-" + case.id}).scalar_one()
        payload = json.loads(old) | dict(source_hash=review.source_hash,
            content_hash=review.content_hash, evidence_hash=review.evidence_hash)
        connection.execute(update(DailyRecord).where(DailyRecord.id == "review-" + case.id)
            .values(payload_json=canonical(payload)))
        connection.execute(update(DailyRecord).where(DailyRecord.id == case.cause_id)
            .values(payload_json=canonical(case.risk)))
    case.content_hash = review.content_hash
    _upgrade(case.engine, "0028_source_coverage")
    return case


def _ready(case):
    """Initialize real sellable baseline lots and obtain the real persisted offer."""
    with case.work() as work:
        for previous, day in zip((date(2026, 10, 22), *_SESSIONS[:-1]), _SESSIONS, strict=True):
            work.daily.session.add(TradingCalendar(exchange=case.draft.market, cal_date=day,
                is_open=True, previous_trade_date=previous))
        work.daily.session.flush()
        DailyAccounting(work.daily).initialize(symbol=case.draft.symbol, core_qty=100,
            tactical_qty=200, expected_revision=0, now=_AT)
        work.commit()
    quote = DailyExecutionQuote(symbol=case.draft.symbol, price_fen=2600, quote_at=_AT,
        available_at=_AT, evaluated_at=_AT, tradable=True, special_state_verified=True,
        liquidity_available=True)
    result = DailyRuntimeEvaluationService(case.work).run_inputs(
        plan=case.draft.to_executable(), expected_activation_revision=1,
        inputs=DailyRuntimeInputs(evaluated_at=_AT, official_trade_date=None, series=None,
            session_dates=_SESSIONS, suspended_dates=(), quote=quote, data_blockers=()))
    assert result.snapshot["risk_action"]["status"] == "RISK_EXIT"
    with case.work() as work:
        assert work.daily.get("evaluation-head-" + case.draft.symbol)["payload"] == (
            result.snapshot)
    return result.snapshot["risk_action"]


def _command(case, *, cause=None, quantity=None):
    with case.work() as work:
        cause = work.daily.get(cause or case.cause_id)
        head = work.daily.get("evaluation-head-" + case.draft.symbol)["payload"]
        action = head["risk_action"]
        return SimulationCommand(plan_version_id=UUID(case.id), cause_id=cause["id"],
            expected_cause_revision=cause["revision"],
            expected_inventory_revision=head["inventory"]["revision"],
            quantity=quantity if quantity is not None else (
                action["core_qty"] + action["tactical_qty"]))


def _business(case):
    with case.engine.connect() as connection:
        return {table: tuple(connection.execute(text(
            f"SELECT * FROM {table} ORDER BY id")).all())
            for table in ("daily_plan_record", "audit_log")}


@pytest.mark.parametrize("options", [{}, {"buy_only_failure": True}, {"expired": True}])
def test_real_cutover_latched_risk_sells_the_actual_offer_despite_ordinary_limits(legacy, options):
    case = legacy(**options)
    action = _ready(case)
    assert action["cause_id"] == case.cause_id
    with case.work() as work:
        store = SourceCoverageStore(work.daily.session)
        assert store.cutover(case.id) is not None and store.latest(case.id) is None
        receipt = simulate_inventory(work, _command(case), _AT)
        assert receipt.side == "SELL"
        # The original branch retains zero of baseline CORE100 + TACTICAL200.
        assert receipt.quantity == action["core_qty"] + action["tactical_qty"] == 300
        assert receipt.inventory.core_qty == 0 and receipt.inventory.tactical_qty == 0
        assert work.daily.get(case.cause_id)["payload"]["status"] == "FULFILLED"
        work.commit()
    with case.work() as work:
        assert work.daily.get(receipt.simulation_id)["payload"]["cause_id"] == case.cause_id
        assert DailyAccounting(work.daily).snapshot(case.draft.symbol, _AT.date())["total_qty"] == 0


@pytest.mark.parametrize("quantity", [100, 400])
def test_cutover_source_authority_cannot_resize_the_frozen_risk_offer(legacy, quantity):
    case = legacy()
    action = _ready(case)
    assert action["core_qty"] + action["tactical_qty"] == 300
    before = _business(case)
    with pytest.raises(ValueError, match="complete offered quantity"), case.work() as work:
        simulate_inventory(work, _command(case, quantity=quantity), _AT)
    assert _business(case) == before


@pytest.mark.parametrize("missing_grant", ["unmigrated", "no-original-activation"])
def test_zero_issue_ordinary_sell_without_cutover_grant_cannot_borrow_risk(legacy, missing_grant):
    case = legacy(upgraded=False) if missing_grant == "unmigrated" else legacy(active=False)
    if missing_grant == "no-original-activation":
        # Activation after migration is not the ACTIVE grant captured by the cutover.
        with case.engine.begin() as connection:
            connection.execute(update(PlanVersion).values(status="ACTIVE", revision=1))
            connection.execute(insert(ActivePlan), dict(symbol=case.draft.symbol,
                plan_version_id=case.id, revision=1, activated_at=_AT.isoformat()))
            connection.execute(insert(PlanActivationState), dict(symbol=case.draft.symbol,
                plan_version_id=case.id, revision=1, changed_at=_AT.isoformat()))
        with case.work() as work:
            member = SourceCoverageStore(work.daily.session).cutover(case.id)
            assert member.legacy_identity["status"] == "DRAFT"
            assert member.legacy_identity["active_revision"] is None
    _ready(case)
    with case.engine.begin() as connection:
        connection.execute(insert(DailyRecord), _daily("ordinary-sell", "SIGNAL", case.draft,
            _signal(case.draft, case.id, _REVIEW, identity="ordinary-sell", side="SELL")))
    before = _business(case)
    expected = ("SOURCE_COVERAGE_UPGRADE_REQUIRED" if missing_grant == "unmigrated"
                else "SOURCE_COVERAGE_REQUIRED")
    with pytest.raises(SimulationAuthorityError, match=expected):
        with case.work() as work:
            assert not work.plans.get_version_details(case.id).daily_issues
            simulate_inventory(work, _command(case, cause="ordinary-sell", quantity=100), _AT)
    assert _business(case) == before


def test_removed_risk_sibling_cannot_donate_core_quantity_or_block_the_real_offer(legacy):
    case = _retained_core_case(legacy)
    action = _ready(case)
    assert (action["core_qty"], action["tactical_qty"]) == (0, 200)
    ghost = deepcopy(case.risk) | dict(rule_id="removed-risk", risk_id="unowned-sibling",
        target_core_qty=0)
    DailyRiskState.model_validate(ghost)
    with case.engine.begin() as connection:
        connection.execute(insert(DailyRecord), _daily("unowned-sibling", "RISK", case.draft,
            ghost))
    # The immutable head was produced by the runtime, before the unrelated row existed.
    with case.work() as work:
        receipt = simulate_inventory(work, _command(case), _AT)
        assert receipt.quantity == 200 and receipt.inventory.core_qty == 100
        assert work.daily.get("unowned-sibling")["payload"] == ghost
        work.commit()


@pytest.mark.parametrize("which", ["ordinary", "unproved-severe"])
def test_unproved_sibling_head_cannot_be_silently_resized_or_used_as_a_cause(legacy, which):
    case = _retained_core_case(legacy)
    severe_id, severe = _risk_payload(case.draft, index=1)
    severe["technical_evidence"], severe["evidence_ids"] = [], []
    with case.engine.begin() as connection:
        connection.execute(insert(DailyRecord), _daily(severe_id, "RISK", case.draft, severe))
    action = _ready(case)
    assert action["cause_id"] == severe_id
    assert (action["core_qty"], action["tactical_qty"]) == (100, 200)
    before = _business(case)
    cause = case.cause_id if which == "ordinary" else severe_id
    expected = ("DAILY_SIMULATION_RISK_NOT_EXECUTABLE" if which == "ordinary"
                else "SOURCE_COVERAGE_REQUIRED")
    with pytest.raises(SimulationAuthorityError, match=expected), case.work() as work:
        simulate_inventory(work, _command(case, cause=cause, quantity=200), _AT)
    assert _business(case) == before


def test_late_risk_accounting_failure_rolls_back_the_real_source_authorized_sale(legacy,
                                                                             monkeypatch):
    case = legacy()
    _ready(case)
    command = _command(case)
    before = _business(case)
    original = DailyAccounting.simulate

    def fail_after_write(self, **kwargs):
        original(self, **kwargs)
        raise RuntimeError("synthetic late risk accounting failure")

    monkeypatch.setattr(DailyAccounting, "simulate", fail_after_write)
    with pytest.raises(RuntimeError, match="late risk accounting"), case.work() as work:
        simulate_inventory(work, command, _AT)
    assert _business(case) == before
