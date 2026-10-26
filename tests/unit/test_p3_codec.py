"""Schema9 current admission is distinct from the historical frozen readers."""

import json
from hashlib import sha256

import pytest
from tests.unit.test_p3_policy_contract import p3_payload

from trade_plan_monitor.domain.daily_plan_validation import (
    daily_draft_content_sha256,
    daily_draft_issues,
)
from trade_plan_monitor.domain.p3_policy_models import P3TradePlan
from trade_plan_monitor.domain.p3_validation import P3PlanDraft
from trade_plan_monitor.domain.plan_codec import dump_plan_json, load_plan_json
from trade_plan_monitor.domain.plan_hash import daily_plan_content_sha256


def test_private_plan_and_draft_have_exact_new_review_domain():
    plan = P3TradePlan.model_validate(p3_payload())
    draft = P3PlanDraft.from_executable(plan)
    assert draft.to_executable() == plan
    content = plan.model_dump(mode="json", exclude={"plan_id", "version", "name", "metadata"})
    canonical = json.dumps(content, ensure_ascii=False, allow_nan=False,
                           sort_keys=True, separators=(",", ":")).encode()
    expected = sha256(b"plan-review-content-v6\x00" + canonical).hexdigest()
    assert daily_plan_content_sha256(plan) == daily_draft_content_sha256(draft) == expected
    assert daily_draft_issues(draft) == ()


def test_missing_monetary_amount_stays_reviewable_and_cannot_execute():
    raw = p3_payload()
    raw["position"]["limit"]["capital_policy"]["cap_fen"] = None
    draft = P3PlanDraft.model_validate(raw)
    assert draft.to_executable() is None
    assert any("cap_fen" in issue["path"] for issue in daily_draft_issues(draft))


def test_current_codec_admits_exact_schema9_after_execution_guards():
    plan = P3TradePlan.model_validate(p3_payload())
    assert load_plan_json(dump_plan_json(plan)) == plan
    from trade_plan_monitor.backtest.run_input import BacktestRunInput
    with pytest.raises(TypeError, match="manifest must be a DatasetManifest"):
        BacktestRunInput.create(plan=plan, manifest=None, initial_cash_fen=1, initial_lots=(),
                               execution_config=None, manual_event_risk=False)
