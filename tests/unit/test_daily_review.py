"""Source fidelity and current-candidate review, with conspicuous synthetic supplements."""

import pytest
from tests.unit.test_daily_plan import synthetic_plan_payload

from trade_plan_monitor.ai.daily_review import DailyMapping, build_daily_review, semantic_values
from trade_plan_monitor.domain.daily_plan_models import DailyTradePlan
from trade_plan_monitor.domain.daily_plan_validation import (
    DailyPlanDraft,
    daily_draft_content_sha256,
)


def reviewed_mapping(draft, source="Synthetic human-reviewed supplements for this fixture."):
    from trade_plan_monitor.ai.review import server_source_clauses

    digest = daily_draft_content_sha256(draft)
    return DailyMapping.model_validate(
        {
            "mapping_version": "daily-mapping-v1",
            "candidate_content_hash": digest,
            "clauses": [
                {
                    "clause_id": c.clause_id,
                    "start": c.start,
                    "end": c.end,
                    "excerpt": c.excerpt,
                    "disposition": "POLICY",
                    "paths": list(semantic_values(draft)),
                    "reason": (
                        "Synthetic human-reviewed policy supplements, independently reviewed."
                    ),
                }
                for c in server_source_clauses(source)
            ],
            "bindings": [
                {
                    "path": path,
                    "value": value,
                    "origin": "HUMAN_SUPPLEMENT",
                    "unit": "JSON",
                    "clause_ids": [],
                    "supplement_id": "supplement-" + str(i),
                }
                for i, (path, value) in enumerate(semantic_values(draft).items())
            ],
            "supplements": [
                {
                    "supplement_id": "supplement-" + str(i),
                    "path": path,
                    "value": value,
                    "candidate_content_hash": digest,
                    "reason": (
                        "Synthetic human-reviewed supplements; proposed policy, "
                        "not registered inventory."
                    ),
                }
                for i, (path, value) in enumerate(semantic_values(draft).items())
            ],
        }
    )


def test_complete_review_has_no_issues_and_semantic_edit_invalidates_supplements():
    draft = DailyPlanDraft.from_executable(DailyTradePlan.model_validate(synthetic_plan_payload()))
    mapping = reviewed_mapping(draft)
    assert (
        build_daily_review(
            draft, mapping, "Synthetic human-reviewed supplements for this fixture."
        ).issues
        == ()
    )
    raw = draft.model_dump(mode="json")
    raw["levels"]["low_buy"]["include_low"] = False
    with pytest.raises(ValueError, match="candidate"):
        build_daily_review(
            DailyPlanDraft.model_validate(raw),
            mapping,
            "Synthetic human-reviewed supplements for this fixture.",
        )


def test_partial_missing_condition_cannot_be_acknowledged_away():
    draft = DailyPlanDraft.from_executable(DailyTradePlan.model_validate(synthetic_plan_payload()))
    raw = draft.model_dump(mode="json")
    raw["ordinary_rules"][0]["technical"] = None
    partial = DailyPlanDraft.model_validate(raw)
    result = build_daily_review(
        partial, reviewed_mapping(partial), "Synthetic human-reviewed supplements for this fixture."
    )
    assert any("technical" in issue.path for issue in result.issues)


def test_forged_source_span_and_orphan_supplement_are_rejected():
    draft = DailyPlanDraft.from_executable(DailyTradePlan.model_validate(synthetic_plan_payload()))
    raw = reviewed_mapping(draft).model_dump(mode="json")
    raw["clauses"][0]["excerpt"] = "forged"
    with pytest.raises(ValueError, match="source"):
        build_daily_review(
            draft,
            DailyMapping.model_validate(raw),
            "Synthetic human-reviewed supplements for this fixture.",
        )
    raw = reviewed_mapping(draft).model_dump(mode="json")
    raw["bindings"] = raw["bindings"][1:]
    with pytest.raises(ValueError, match="orphan"):
        build_daily_review(
            draft,
            DailyMapping.model_validate(raw),
            "Synthetic human-reviewed supplements for this fixture.",
        )


def test_fixed_simulation_rules_are_bound_by_server_without_human_broker_evidence():
    draft = DailyPlanDraft.from_executable(DailyTradePlan.model_validate(synthetic_plan_payload()))
    mapping = reviewed_mapping(draft)
    mapping = mapping.model_copy(
        update={
            "bindings": tuple(
                b for b in mapping.bindings if not b.path.startswith("trading_rules.")
            ),
            "supplements": tuple(
                s for s in mapping.supplements if not s.path.startswith("trading_rules.")
            ),
        }
    )
    result = build_daily_review(
        draft, mapping, "Synthetic human-reviewed supplements for this fixture."
    )
    assert result.issues == ()
    rules = tuple(b for b in result.mapping.bindings if b.path.startswith("trading_rules."))
    assert len(rules) == 3
    assert all(b.origin == "PRODUCT_CONTRACT" and b.supplement_id is None for b in rules)


@pytest.mark.parametrize(("source", "accepted"), [
    ("risk_branches=[]", True), ("无风险分支。", True),
    ("ordinary_rules=[]", False), ("无普通规则。", False),
    ("风险规则没有写清楚。", False), ("如果放量，无风险分支。", False),
    ("例如 risk_branches=[]", False), ("并非无风险分支。", False),
    ("risk_branches=[]？", False), ("risk_branches=[] 或保留原规则", False),
])
def test_empty_unified_rules_require_exact_matching_source_declaration(source, accepted):
    from tests.unit.test_unified_replay_input import research_plan

    from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft

    draft = UnifiedPlanDraft.from_executable(research_plan())
    raw = reviewed_mapping(draft, source).model_dump(mode="json")
    binding = next(item for item in raw["bindings"] if item["path"] == "risk_branches")
    supplement_id = binding["supplement_id"]
    binding.update(origin="SOURCE", clause_ids=[raw["clauses"][0]["clause_id"]],
                   supplement_id=None)
    raw["supplements"] = [s for s in raw["supplements"]
                          if s["supplement_id"] != supplement_id]
    mapping = DailyMapping.model_validate(raw)
    if accepted:
        assert build_daily_review(draft, mapping, source).issues == ()
    else:
        with pytest.raises(ValueError, match="empty rules"):
            build_daily_review(draft, mapping, source)


@pytest.mark.parametrize(("path", "value", "source", "accepted"), [
    ("levels.low_buy.include_low", True, "levels.low_buy.include_low=true", True),
    ("levels.low_buy.include_high", False, "levels.low_buy.include_high=false。", True),
    ("levels.low_buy.include_low", True, "levels.pressure.include_low=true", False),
    ("levels.low_buy.include_low", True, "levels.low_buy.include_high=true", False),
    ("levels.low_buy.include_low", True, "levels.low_buy.include_low=false", False),
    ("levels.low_buy.include_low", False, "levels.low_buy.include_low=true", False),
    ("levels.low_buy.include_low", True, "若放量 levels.low_buy.include_low=true", False),
    ("levels.low_buy.include_low", True, "例如 levels.low_buy.include_low=true", False),
    ("levels.low_buy.include_low", True, "levels.low_buy.include_low=True", False),
    ("levels.low_buy.include_low", True, "levels.low_buy.INCLUDE_LOW=true", False),
    ("levels.low_buy.include_low", True, "levels.low_buy.include_low=true?", False),
    ("levels.low_buy.include_low", True, "levels.low_buy.include_low=true？", False),
    ("levels.low_buy.include_low", True, "levels.low_buy.include_low=true or false", False),
    ("risk_branches[0].involves_core", True, "risk_branches[0].involves_core=true", False),
])
def test_range_source_boolean_is_exact_and_cannot_authorize_other_policy(
    path, value, source, accepted,
):
    from tests.unit.test_unified_plan_domain import unified_payload

    from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
    from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft

    payload = unified_payload()
    if path.startswith("levels."):
        _, zone, field = path.split(".")
        payload["levels"][zone][field] = value
    draft = UnifiedPlanDraft.from_executable(UnifiedTradePlan.model_validate(payload))
    raw = reviewed_mapping(draft, source).model_dump(mode="json")
    binding = next(item for item in raw["bindings"] if item["path"] == path)
    supplement_id = binding["supplement_id"]
    binding.update(origin="SOURCE", clause_ids=[raw["clauses"][0]["clause_id"]],
                   supplement_id=None)
    raw["supplements"] = [s for s in raw["supplements"]
                          if s["supplement_id"] != supplement_id]
    mapping = DailyMapping.model_validate(raw)
    if accepted:
        assert build_daily_review(draft, mapping, source).issues == ()
    else:
        with pytest.raises(ValueError, match="range boundary"):
            build_daily_review(draft, mapping, source)
def test_buy_suspension_supplement_requires_both_exact_source_and_obligation():
    from pydantic import ValidationError

    from trade_plan_monitor.ai.daily_review import DailySupplement

    payload = dict(supplement_id="start", candidate_content_hash="a" * 64,
                   path="buy_suspension.effective_from", value="2026-09-30T09:30:00+08:00",
                   reason="Explicit checking start")
    old = DailySupplement.model_validate(payload)
    assert old.model_dump(mode="json") == payload
    scoped = DailySupplement.model_validate(payload | {
        "source_hash": "b" * 64, "obligation_id": "c" * 64,
    })
    assert scoped.source_hash == "b" * 64
    for extra in ({"source_hash": "b" * 64}, {"obligation_id": "c" * 64}):
        with pytest.raises(ValidationError):
            DailySupplement.model_validate(payload | extra)


def test_buy_suspension_source_metadata_cannot_expand_historical_non_guard_supplements():
    from pydantic import ValidationError

    from trade_plan_monitor.ai.daily_review import DailySupplement

    payload = dict(supplement_id="old-position", candidate_content_hash="a" * 64,
                   path="position.max_qty", value=300, reason="Explicit legacy position limit")
    assert DailySupplement.model_validate(payload).model_dump(mode="json") == payload
    with pytest.raises(ValidationError):
        DailySupplement.model_validate(payload | dict(source_hash="b" * 64, obligation_id="c" * 64))


def test_buy_suspension_replacement_intent_is_not_a_runtime_receipt():
    from trade_plan_monitor.state.source_coverage_values import BuySuspensionReplacementIntent

    value = BuySuspensionReplacementIntent(
        source_hash="a" * 64, candidate_content_hash="b" * 64,
        source_start=0, source_end=45,
        excerpt="Explicitly replace the predecessor BUY guard.",
        replacement_reason="A new independently reviewed strategy",
        retire_predecessor_guard=True, acknowledge_unverified_predecessor=True,
        strategy_effective_from="2026-11-15T09:30:00+08:00",
    )
    assert value.strategy_effective_from.isoformat() == "2026-11-15T09:30:00+08:00"
    assert "predecessor_plan_version_id" not in value.model_dump(mode="json")
    assert value.authority_granted is False


def test_buy_suspension_review_record_keeps_old_bytes_without_new_evidence():
    from trade_plan_monitor.state.daily_state_models import DailyReviewBinding

    payload = dict(confirmed=False, content_hash="a" * 64, source_hash="b" * 64,
                   evidence_hash="c" * 64, review_id=None, review_revision=0,
                   plan_version_id="version-1")
    assert DailyReviewBinding.model_validate(payload).model_dump(mode="json") == payload
    assert "buy_suspension_replacement" in DailyReviewBinding.model_fields


def _buy_suspension_replacement_receipt(**updates):
    from datetime import datetime

    from tests.unit.test_plan_buy_suspension_contract import suspension_payload

    from trade_plan_monitor.domain.unified_plan_models import BuySuspensionDefinition
    from trade_plan_monitor.state.source_coverage_values import (
        BuySuspensionReplacementBinding,
        BuySuspensionReplacementIntent,
    )

    # Engineering-only value fixture, not a server-resolved runtime snapshot.
    intent = dict(source_hash="d" * 64, candidate_content_hash="e" * 64,
        source_start=0, source_end=45, excerpt="Explicitly replace the predecessor BUY guard.",
        replacement_reason="Explicit new strategy", retire_predecessor_guard=True,
        acknowledge_unverified_predecessor=True,
        strategy_effective_from="2026-11-15T09:30:00+08:00")
    values = dict(symbol="601021.SH", predecessor_plan_version_id="old-version",
        predecessor_plan_id="old-plan", predecessor_plan_version=1,
        predecessor_plan_hash="a" * 64, predecessor_content_hash="b" * 64,
        predecessor_source_hash="c" * 64, predecessor_review_id="old-review",
        predecessor_review_revision=1, predecessor_activation_revision=7,
        predecessor_guard=suspension_payload()["buy_suspension"], predecessor_state_hash="f" * 64,
        predecessor_state_revision=3, predecessor_unresolved_from="2026-10-01T09:30:00+08:00",
        predecessor_unresolved_through="2026-10-02T15:00:00+08:00",
        new_plan_version_id="new-version", new_plan_id="new-plan", new_plan_version=1,
        new_plan_hash="9" * 64, new_content_hash="e" * 64,
        new_source_hash="d" * 64, new_review_id="new-review", new_review_revision=1,
        new_guard=None, intent=intent, confirmed_at="2026-11-15T10:00:00+08:00")
    values.update(updates)
    values["intent"] = BuySuspensionReplacementIntent.model_validate(values["intent"])
    values["predecessor_guard"] = BuySuspensionDefinition.model_validate(
        values["predecessor_guard"])
    for name in ("predecessor_unresolved_from", "predecessor_unresolved_through", "confirmed_at"):
        values[name] = None if values[name] is None else datetime.fromisoformat(values[name])
    return BuySuspensionReplacementBinding.build(**values)


def test_buy_suspension_replacement_receipt_binds_exact_review_and_preserves_unverified_interval():
    from trade_plan_monitor.state.daily_state_models import DailyReviewBinding
    from trade_plan_monitor.state.source_coverage_values import BuySuspensionReplacementBinding

    receipt = _buy_suspension_replacement_receipt()
    assert receipt.version == "buy-suspension-replacement-v1"
    assert BuySuspensionReplacementBinding.model_validate_json(receipt.model_dump_json()) == receipt
    assert receipt.predecessor_state_revision == 3 and receipt.new_guard is None
    assert receipt.intent.acknowledge_unverified_predecessor and receipt.authority_granted is False
    payload = dict(confirmed=True, content_hash=receipt.new_content_hash,
        source_hash=receipt.new_source_hash, evidence_hash="a" * 64,
        review_id=receipt.new_review_id, review_revision=1,
        plan_version_id=receipt.new_plan_version_id,
        buy_suspension_replacement_intent=receipt.intent,
        buy_suspension_replacement=receipt)
    assert DailyReviewBinding.model_validate(payload).buy_suspension_replacement == receipt
    from pydantic import ValidationError

    for update in (dict(plan_version_id="other-version"), dict(review_id="other-review"),
                   dict(source_hash="0" * 64), dict(buy_suspension_replacement_intent=None)):
        with pytest.raises(ValidationError):
            DailyReviewBinding.model_validate(payload | update)


def test_absent_guard_receipt_is_exact_absence_never_a_fabricated_state():
    from trade_plan_monitor.state.source_coverage_values import BuySuspensionReplacementBinding

    receipt = _buy_suspension_replacement_receipt(
        predecessor_state_revision=0, predecessor_state_hash=None,
        predecessor_unresolved_from="2026-09-30T09:30:00+08:00",
        predecessor_unresolved_through=None,
    )
    assert receipt.predecessor_state_revision == 0 and receipt.predecessor_state_hash is None
    values = {name: getattr(receipt, name) for name in type(receipt).model_fields
              if name != "evidence_hash"}
    for change in (dict(predecessor_state_hash="a" * 64),
                   dict(predecessor_state_revision=1),
                   dict(predecessor_unresolved_from=None)):
        with pytest.raises(ValueError):
            BuySuspensionReplacementBinding.build(**(values | change))


@pytest.mark.parametrize("attack", ["retirement", "acknowledgement", "source", "start"])
def test_buy_suspension_replacement_receipt_rejects_missing_exact_decisions(attack):
    from pydantic import ValidationError

    receipt = _buy_suspension_replacement_receipt()
    intent = receipt.intent.model_dump(mode="json")
    if attack == "retirement":
        intent["retire_predecessor_guard"] = False
    elif attack == "acknowledgement":
        intent["acknowledge_unverified_predecessor"] = False
    elif attack == "source":
        intent["source_hash"] = "0" * 64
    else:
        intent["strategy_effective_from"] = "2026-11-15T01:30:00+00:00"
    with pytest.raises(ValidationError):
        _buy_suspension_replacement_receipt(intent=intent)
