"""Persistent current rules preserve dated codecs and exact reviewed authority."""

from hashlib import sha256

import pytest
from pydantic import ValidationError
from tests.unit.test_daily_review import reviewed_mapping
from tests.unit.test_unified_plan_domain import unified_payload

from trade_plan_monitor.ai.daily_review import build_daily_review, daily_contract_bindings
from trade_plan_monitor.domain.plan_codec import dump_plan_json, load_plan_json
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft


def persistent_draft():
    raw = unified_payload()
    raw["activation"] = {"mode": "MANUAL"}
    for rule in raw["ordinary_rules"]:
        rule["validity"] = {"mode": "PLAN_ACTIVE"}
    return UnifiedPlanDraft.from_executable(UnifiedTradePlan.model_validate(raw))


def test_historical_v8_extraction_response_keeps_draft_and_mapping_bytes():
    import json
    from pathlib import Path

    from trade_plan_monitor.web.routers.plans import PlanExtractionView

    fixture = Path(__file__).parents[2] / "web/tests/fixtures/ai-partial-extraction.json"
    raw = json.loads(fixture.read_text(encoding="utf-8"))
    raw["promptVersion"] = "plan-extract-v8"
    restored = PlanExtractionView.model_validate_json(json.dumps(raw))
    assert restored.prompt_version == "plan-extract-v8"
    assert restored.draft_plan_json == raw["draftPlanJson"]
    assert restored.daily_mapping.model_dump(mode="json") == raw["dailyMapping"]


def test_persistent_mode_is_explicit_and_has_no_dates_or_load_fallback():
    draft = persistent_draft()
    plan = draft.to_executable()
    assert plan is not None
    assert plan.ordinary_rules[0].validity.model_dump() == {"mode": "PLAN_ACTIVE"}
    assert load_plan_json(dump_plan_json(plan)) == plan
    raw = draft.model_dump(mode="json")
    raw["ordinary_rules"][0]["validity"] = None
    assert UnifiedPlanDraft.model_validate(raw).to_executable() is None
    raw["ordinary_rules"][0]["validity"] = {"mode": "PLAN_ACTIVE", "end_date": "2026-09-30"}
    with pytest.raises(ValidationError):
        UnifiedPlanDraft.model_validate(raw)


def test_exact_persistent_defaults_are_product_bindable():
    draft = persistent_draft()
    defaults = {b.path: b.value for b in daily_contract_bindings(draft)}
    assert defaults["activation.mode"] == "MANUAL"
    assert defaults["ordinary_rules[0].validity.mode"] == "PLAN_ACTIVE"
    assert "ordinary_rules[0].quantity" not in defaults
    mapping = reviewed_mapping(draft)
    selected = {b.path: b for b in daily_contract_bindings(draft)}
    removed = {b.supplement_id for b in mapping.bindings if b.path in selected}
    mapping = mapping.model_copy(update={
        "bindings": tuple(selected.get(b.path, b) for b in mapping.bindings),
        "supplements": tuple(s for s in mapping.supplements if s.supplement_id not in removed),
    })
    assert build_daily_review(draft, mapping,
                             "Synthetic human-reviewed supplements for this fixture.").issues == ()


@pytest.mark.parametrize("source", [
    "规则有效至2026-09-30，收盘低于40元买入100股。",
    "本规则仅限未来三个交易日，收盘低于40元买入100股。",
    "This rule expires on 2026-09-30; buy 100 shares below 40 yuan.",
    "This plan is valid until manually deactivated or 2026-09-30, whichever comes first.",
    "计划有效期限：持续有效直到人工停用或2026-09-30，以先发生者为准。",
    "计划有效期限：持续有效，直到人工停用或2026-09-30，以先发生者为准。",
])
def test_source_deadline_cannot_be_resolved_by_persistent_default(source):
    draft = persistent_draft()
    result = build_daily_review(draft, reviewed_mapping(draft, source), source)
    assert any(i.code == "PLAN_SOURCE_TIME_LIMIT_REQUIRED" for i in result.issues)


@pytest.mark.parametrize("source", [
    "报告日期2026-09-18，收盘低于40元买入100股。",
    "报告数据截止日期2026-09-18，收盘低于40元买入100股。",
    "单次日线信号仅下一交易日可执行；规则持续有效直到人工停用。",
    "单次买入信号仅限下一交易日执行。",
    "Single buy signal only for next session.",
])
def test_report_date_and_single_signal_window_are_not_rule_deadlines(source):
    draft = persistent_draft()
    assert build_daily_review(draft, reviewed_mapping(draft, source), source).issues == ()


def test_dated_review_and_omitted_legacy_mode_keep_exact_codec():
    raw = unified_payload()
    old = UnifiedTradePlan.model_validate(raw)
    document = dump_plan_json(old)
    draft = UnifiedPlanDraft.from_executable(old)
    source = "规则有效至2026-09-30，以下为人工审核的原始日期规则。"
    review = build_daily_review(draft, reviewed_mapping(draft, source), source)
    assert review.issues == ()
    assert dump_plan_json(load_plan_json(document)) == document
    raw["ordinary_rules"][0]["validity"].pop("mode", None)
    assert UnifiedTradePlan.model_validate(raw) == old


def test_fixed_prechange_json_and_review_hashes_are_unchanged():
    # Captured independently from Git HEAD 86bb448 before this implementation.
    plan = UnifiedTradePlan.model_validate(unified_payload())
    draft = UnifiedPlanDraft.from_executable(plan)
    review = build_daily_review(draft, reviewed_mapping(draft),
                                "Synthetic human-reviewed supplements for this fixture.")
    assert sha256(dump_plan_json(plan).encode()).hexdigest() == (
        "937c7b062a93abb3567f04e074f8eb4d82efc467ea60e04d1e89cd12502bf741")
    assert review.content_hash == (
        "832a1d87b3c3bea92b12ef94c621a42790e82aaef030d4cc8d8fa2b2a23f80ee")
    assert review.evidence_hash == (
        "5feb96a2bfba4c1bd84bffa2ce85a906c29e3f7a05a47b606fac1f87ac203dcd")
    assert review.source_hash == (
        "5ebe3212d9cfcafce2a9b5da7e293d3678bbf92145703fce6e840b95ee86ccff")
    assert review.issues == ()


@pytest.mark.parametrize("source", [
    "计划有效期限：持续有效直到人工停用或审核启用新版本替换。",
    "计划有效期：持续有效，直到人工停用或新版本正式替换。",
    "This plan remains valid until manually deactivated or replaced by a reviewed new version.",
])
def test_template_persistent_validity_is_not_a_source_deadline(source):
    draft = persistent_draft()
    assert build_daily_review(draft, reviewed_mapping(draft, source), source).issues == ()


def test_scoped_human_conversion_of_deadline_requires_exact_clause():
    draft = persistent_draft()
    source = "本规则有效至2026-09-30。"
    mapping = reviewed_mapping(draft, source)
    mode = next(b for b in mapping.bindings if b.path == "ordinary_rules[0].validity.mode")
    mapping = mapping.model_copy(update={"supplements": tuple(
        s.model_copy(update={"reason": f"引用原句：{source} 改为持续有效；重新审核并明确启用。"})
        if s.supplement_id == mode.supplement_id else s for s in mapping.supplements)})
    assert build_daily_review(draft, mapping, source).issues == ()


@pytest.mark.parametrize("source", [
    "规则有效至2026-09-30且单次信号仅下一交易日可执行。",
    "单次信号仅下一交易日可执行且买入有效至2026-09-30。",
    "单次买入信号仅限下一交易日执行且买入有效至2026-09-30。",
    "单次信号仅下一交易日可执行同时买入有效至2026-09-30。",
    "A single signal executes only next trading day and buy expires on 2026-09-30.",
    "Single signal only for next session and buy valid until 2026-09-30.",
])
def test_single_signal_window_does_not_hide_deadline_in_same_clause(source):
    draft = persistent_draft()
    assert any(i.code == "PLAN_SOURCE_TIME_LIMIT_REQUIRED" for i in
               build_daily_review(draft, reviewed_mapping(draft, source), source).issues)


def test_manual_lifetime_does_not_hide_another_rule_deadline():
    source = "计划有效期：持续有效，直到人工停用；买入规则有效至2026-09-30。"
    draft = persistent_draft()
    assert any(i.code == "PLAN_SOURCE_TIME_LIMIT_REQUIRED" for i in
               build_daily_review(draft, reviewed_mapping(draft, source), source).issues)


@pytest.mark.parametrize("path", ["activation", "ordinary_rules[1].validity"])
def test_source_bound_date_exception_does_not_require_persistent_rule_conversion(path):
    raw = persistent_draft().to_executable().model_dump(mode="json")
    dated = {"mode": "DATE_RANGE", "start_date": "2026-09-01", "end_date": "2026-12-31"}
    if path == "activation":
        raw["activation"] = dated
    else:
        raw["ordinary_rules"].append({**raw["ordinary_rules"][0], "side": "SELL",
                                    "rule_id": "source-dated-sell", "zone": None,
                                    "validity": dated})
    draft = UnifiedPlanDraft.from_executable(UnifiedTradePlan.model_validate(raw))
    source = ("计划" if path == "activation" else "卖出规则") + "有效期2026-12-31。"
    mapping = reviewed_mapping(draft, source)
    date_path = path + ".end_date"
    old = next(b for b in mapping.bindings if b.path == date_path)
    mapping = mapping.model_copy(update={
        "bindings": tuple(b.model_copy(update={"origin": "SOURCE", "supplement_id": None,
                          "clause_ids": (mapping.clauses[0].clause_id,)})
                          if b == old else b for b in mapping.bindings),
        "supplements": tuple(s for s in mapping.supplements
                             if s.supplement_id != old.supplement_id),
    })
    assert build_daily_review(draft, mapping, source).issues == ()
    if path != "activation":
        combined_source = "买入规则和卖出规则有效至2026-12-31。"
        combined = reviewed_mapping(draft, combined_source)
        old = next(b for b in combined.bindings if b.path == date_path)
        combined = combined.model_copy(update={
            "bindings": tuple(b.model_copy(update={"origin": "SOURCE", "supplement_id": None,
                              "clause_ids": (combined.clauses[0].clause_id,)})
                              if b == old else b for b in combined.bindings),
            "supplements": tuple(s for s in combined.supplements
                                 if s.supplement_id != old.supplement_id),
        })
        assert any(i.code == "PLAN_SOURCE_TIME_LIMIT_REQUIRED" for i in
                   build_daily_review(draft, combined, combined_source).issues)


def test_source_start_date_does_not_hide_rule_deadline():
    raw = persistent_draft().to_executable().model_dump(mode="json")
    raw["activation"] = {"mode": "DATE_RANGE", "start_date": "2026-09-01",
                         "end_date": "2026-12-31"}
    draft = UnifiedPlanDraft.from_executable(UnifiedTradePlan.model_validate(raw))
    source = "计划2026-09-01开始，买入规则有效至2026-09-30。"
    mapping = reviewed_mapping(draft, source)
    old = next(b for b in mapping.bindings if b.path == "activation.start_date")
    mapping = mapping.model_copy(update={
        "bindings": tuple(b.model_copy(update={"origin": "SOURCE", "supplement_id": None,
                          "clause_ids": (mapping.clauses[0].clause_id,)})
                          if b == old else b for b in mapping.bindings),
        "supplements": tuple(s for s in mapping.supplements
                             if s.supplement_id != old.supplement_id),
    })
    assert any(i.code == "PLAN_SOURCE_TIME_LIMIT_REQUIRED" for i in
               build_daily_review(draft, mapping, source).issues)


def test_two_affected_persistent_rules_have_one_visible_issue_per_source_clause():
    raw = persistent_draft().to_executable().model_dump(mode="json")
    raw["ordinary_rules"].append({**raw["ordinary_rules"][0], "side": "SELL",
                                "rule_id": "persistent-sell", "zone": None})
    draft = UnifiedPlanDraft.from_executable(UnifiedTradePlan.model_validate(raw))
    source = "买入规则和卖出规则有效至2026-09-30。"
    issues = build_daily_review(draft, reviewed_mapping(draft, source), source).issues
    assert len(issues) == 1 and issues[0].code == "PLAN_SOURCE_TIME_LIMIT_REQUIRED"
    assert "ordinary_rules[0].validity.mode" in issues[0].reason
    assert "ordinary_rules[1].validity.mode" in issues[0].reason


def test_later_day_after_old_deadline_needs_independent_signal_and_keeps_expiry(tmp_path):
    from datetime import date, datetime

    from tests.integration.test_daily_plan_chain import SH, Chain

    from trade_plan_monitor.decision.daily_lifecycle import expire_daily_signal
    from trade_plan_monitor.decision.unified_lifecycle import confirm_signal

    chain = Chain(tmp_path)
    raw = persistent_draft().to_executable().model_dump(mode="json")
    raw["ordinary_rules"][0].update(zone=None, condition={
        "type": "DAILY_PRICE_COMPARE", "field": "close", "offset": 0, "comparator": "LT",
        "reference": {"mode": "FIXED", "value": "4000", "unit": "FEN",
                      "as_of": "2026-09-18", "source": "Synthetic reviewed threshold"}})
    plan = UnifiedTradePlan.model_validate(raw)
    days = (date(2027, 1, 4), date(2027, 1, 5), date(2027, 1, 6))

    def confirm(day, *, previous=(), facts=(), rule=None):
        return confirm_signal(plan, rule or plan.ordinary_rules[0], series=chain.series(day),
            facts=facts, previous=previous, session_dates=days,
            plan_version_id="current", review_id="reviewed")

    first = confirm(days[0])
    assert first is not None and first["execution_date"] == str(days[1])
    dated = UnifiedTradePlan.model_validate(unified_payload()).ordinary_rules[0]
    assert confirm(days[0], rule=dated) is None
    assert confirm(days[1], previous=(first,)) is None
    expired = expire_daily_signal(first, datetime(2027, 1, 5, 15, tzinfo=SH))
    assert expired["state"] == "EXPIRED" and expired["executable_qty"] == 0
    assert confirm(days[2], previous=(expired,)) is None
    second = confirm(days[2], previous=(expired,), facts=({"id": "new-structure",
        "kind": "INDEPENDENT_EVENT", "prior_signal_id": first["signal_id"],
        "trade_date": str(days[2]), "verified": True},))
    assert second is not None and second["signal_id"] != first["signal_id"]
    assert confirm(days[2], previous=(expired, second)) is None
