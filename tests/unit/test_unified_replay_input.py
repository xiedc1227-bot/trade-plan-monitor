"""Frozen current research authority is explicit and legacy bytes stay unchanged."""

import json
from datetime import datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError
from tests.unit.test_backtest_run_input import _config, _goldens, _lot, _manifest, _plan
from tests.unit.test_unified_plan_domain import unified_payload

from trade_plan_monitor.backtest.research_input import (
    ResearchDeactivate,
    ResearchFactor,
    ResearchReview,
    ResearchSimulation,
    UnifiedResearchInput,
)
from trade_plan_monitor.backtest.run_input import BacktestRunInput
from trade_plan_monitor.domain.plan_hash import daily_plan_content_sha256
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan

SH = ZoneInfo("Asia/Shanghai")


def research_plan():
    raw = unified_payload()
    raw.update(levels=None, monitoring=None, risk_branches=[])
    raw["position"] = {"max_qty": 1000}
    raw["ordinary_rules"][0].update(
        zone=None,
        validity={"mode": "PLAN_ACTIVE"},
        condition={"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5, "price_fen": 4000},
        confirmation={"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
        execution_window="CURRENT_SESSION",
    )
    return UnifiedTradePlan.model_validate(raw)


def research_input(plan, *, known=True):
    return UnifiedResearchInput(
        started_at=datetime(2026, 8, 20, 9, 0, tzinfo=SH),
        inventory_known=known,
        review=ResearchReview(
            content_hash=daily_plan_content_sha256(plan),
            reviewed_at=datetime(2026, 8, 19, 18, 0, tzinfo=SH),
            confirmed=True,
            evidence="Synthetic explicit reviewed research fixture",
        ),
    )


def create(plan, research=None, *, lots=(), manual=False):
    case = _goldens()["cases"][0]
    return BacktestRunInput.create(
        plan=plan,
        manifest=_manifest(case),
        initial_cash_fen=1_000_000,
        initial_lots=lots,
        execution_config=_config(case),
        manual_event_risk=manual,
        research_input=research,
    )


def test_current_v4_optional_allocations_roundtrip_and_explicit_authority():
    plan = research_plan()
    frozen = research_input(plan)
    result = create(plan, frozen, lots=(_lot("start-holding", quantity=200),))
    assert result.run_formula_version == "backtest-run-v4"
    assert BacktestRunInput.model_validate_json(result.model_dump_json()) == result
    assert result.research_input == frozen
    changed = create(plan, frozen.model_copy(update={"inventory_known": False}))
    assert changed.run_id != create(plan, frozen).run_id
    assert changed.authority_id == create(plan, frozen).authority_id


def test_current_missing_review_input_manual_risk_and_legacy_research_are_rejected():
    plan = research_plan()
    with pytest.raises(ValueError, match="RESEARCH_INPUT_REQUIRED"):
        create(plan)
    with pytest.raises(ValueError, match="MANUAL_EVENT_RISK_UNSUPPORTED"):
        create(plan, research_input(plan), manual=True)
    with pytest.raises(ValueError, match="RESEARCH_INPUT_FORBIDDEN"):
        create(_plan(), research_input(plan))
    with pytest.raises(ValidationError):
        ResearchReview(
            content_hash="0" * 64,
            reviewed_at=datetime.now(SH),
            confirmed=False,
            evidence="Unreviewed",
        )
    bad = research_input(plan).model_copy(
        update={
            "review": ResearchReview(
                content_hash="0" * 64,
                reviewed_at=datetime(2026, 8, 19, tzinfo=SH),
                confirmed=True,
                evidence="Wrong frozen binding",
            )
        }
    )
    with pytest.raises(ValueError, match="RESEARCH_REVIEW_BINDING_MISMATCH"):
        create(plan, bad)


def test_research_start_offset_and_unknown_inventory_are_explicit():
    plan = research_plan()
    payload = research_input(plan).model_dump(mode="json")
    payload["started_at"] = "2026-08-20T01:00:00Z"
    with pytest.raises(ValidationError):
        UnifiedResearchInput.model_validate_json(json.dumps(payload))
    payload["started_at"] = "2026-08-20T09:00:00.1234567+08:00"
    with pytest.raises(ValidationError):
        UnifiedResearchInput.model_validate_json(json.dumps(payload))
    with pytest.raises(ValueError, match="UNKNOWN_INVENTORY_FORBIDS_LOTS"):
        create(plan, research_input(plan, known=False), lots=(_lot("ambiguous"),))


def test_absent_research_field_is_omitted_from_legacy_serialization():
    result = create(_plan())
    assert "research_input" not in result.model_dump(mode="json")
    assert "research_input" not in result.model_dump_json()


def test_operation_identity_order_bounds_and_future_independent_authority():
    plan = research_plan()
    frozen = research_input(plan)
    operation = ResearchDeactivate(
        kind="DEACTIVATE", operation_id="stop", order=0, at=datetime(2026, 8, 20, 14, tzinfo=SH)
    )
    changed = frozen.model_copy(update={"operations": (operation,)})
    assert create(plan, changed).run_id != create(plan, frozen).run_id
    assert create(plan, changed).authority_id == create(plan, frozen).authority_id
    with pytest.raises(ValidationError, match="unique increasing"):
        frozen.model_copy(update={"operations": (operation, operation)})
    with pytest.raises(ValidationError, match="exactly one"):
        ResearchSimulation(
            kind="SIMULATE", operation_id="trade", order=1, at=operation.at, quantity=100
        )
    with pytest.raises(ValidationError):
        ResearchSimulation(
            kind="SIMULATE",
            operation_id="trade",
            order=1,
            at=operation.at,
            rule_id="buy",
            occurrence=1,
            quantity=50,
        )


def test_review_today_is_submission_metadata_and_not_historical_fact_availability():
    plan = research_plan()
    frozen = research_input(plan)
    reviewed = frozen.review.model_copy(
        update={"reviewed_at": datetime(2026, 10, 3, 14, tzinfo=SH)}
    )
    assert create(plan, frozen.model_copy(update={"review": reviewed})).run_id


def test_current_version_locator_does_not_change_semantic_identity():
    original = create(research_plan(), research_input(research_plan()))
    first = original.model_copy(update={"plan_version_id": UUID(int=1)})
    second = original.model_copy(update={"plan_version_id": UUID(int=2)})
    assert first.run_id == second.run_id == original.run_id


def test_constructed_incomplete_plan_cannot_cross_research_boundary():
    plan = research_plan()
    broken = UnifiedTradePlan.model_construct(
        **{
            **plan.__dict__,
            "ordinary_rules": (),
            "risk_branches": (),
            "alert_rules": (),
        }
    )
    with pytest.raises(ValidationError):
        create(broken, research_input(plan))


@pytest.mark.parametrize("bad", [1, "true", False])
def test_review_true_is_never_coerced(bad):
    payload = research_input(research_plan()).review.model_dump(mode="json")
    payload["confirmed"] = bad
    with pytest.raises(ValidationError):
        ResearchReview.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize("bad", [1.1, "bad", "1e999999", "Infinity", "1" * 10001])
def test_adjustment_factor_has_exact_bounded_decimal_boundary(bad):
    with pytest.raises(ValidationError):
        ResearchFactor.model_validate_json(json.dumps({"trade_date": "2026-08-20", "factor": bad}))
    assert ResearchFactor.model_validate_json(
        '{"trade_date":"2026-08-20","factor":"1.1"}').factor == Decimal("1.1")
