"""PBS complete controls isolate the durable obligation from unrelated source gaps."""

from copy import deepcopy

import pytest
from tests.integration.test_market_linkage_review import source_mapping
from tests.unit.test_plan_buy_suspension_contract import suspension_payload

from trade_plan_monitor.ai.daily_review import (
    DailyClause,
    DailyFieldBinding,
    DailyMapping,
    DailySupplement,
    build_daily_review,
    daily_source_clauses,
    semantic_values,
)
from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.ai.source_coverage import assess_source_coverage
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256
from trade_plan_monitor.domain.daily_scope import scope_hash
from trade_plan_monitor.domain.unified_plan_validation import BuySuspensionPlanDraft

DIRECTIVE = "再次跌破24.20后继续空仓，等待新底部结构。"


def complete_suspension_case(*, substitute=None, clarified=False, guard=True, tail="",
                             directive=DIRECTIVE):
    payload = suspension_payload()
    if substitute in {"transient", "sell"}:
        payload["ordinary_rules"][0].update(
            condition={"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5, "price_fen": 2420},
            confirmation={"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
            execution_window="CURRENT_SESSION",
        )
        if substitute == "sell":
            payload["ordinary_rules"][0]["side"] = "SELL"
            payload["ordinary_rules"][0]["zone"] = "PRESSURE"
    if substitute == "fact":
        payload["ordinary_rules"][0]["condition"] = dict(
            type="REVIEWED_FACT", fact_kind="TECHNICAL",
            evidence_requirement="Human verifies the completed five-minute pattern",
            validity_scope="TRADE_DATE",
        )
    # The preserved source declares every other value, but never invents guard period/start.
    absent = deepcopy(payload)
    absent["buy_suspension"] = None
    bare = BuySuspensionPlanDraft.model_validate(absent)
    source, mapping = source_mapping(bare)
    source += "\n" + directive + tail
    added = tuple(DailyClause.model_validate(c.model_dump() | dict(
        disposition="CONTEXT", semantic_role="COMMENTARY", paths=(), reason="Untrusted label",
    )) for c in server_source_clauses(source)[len(mapping.clauses):])
    draft = BuySuspensionPlanDraft.model_validate(payload if guard else absent)
    digest = daily_draft_content_sha256(draft)
    mapping = mapping.model_copy(update={
        "candidate_content_hash": digest, "clauses": (*mapping.clauses, *added),
    })
    raw = assess_source_coverage(bare, mapping.model_copy(update={
        "candidate_content_hash": daily_draft_content_sha256(bare),
    }), source, origin="HUMAN")
    obligation = next(o for o in raw.obligations if o.semantics_json is not None
                      and '"treatment":"PERSISTENT_BUY_SUSPENSION"' in o.semantics_json)
    if guard:
        items = []
        for index, (path, value) in enumerate(semantic_values(draft).items()):
            if path.startswith("buy_suspension."):
                extra = (dict(source_hash=scope_hash(source),
                              obligation_id=obligation.obligation_id,
                              buy_suspension_clarification="ALL_PLAN_BUY_REVIEWED_REPLACEMENT_ONLY")
                         if clarified else {})
                items.append(DailySupplement(supplement_id=f"guard-{index}",
                    candidate_content_hash=digest, path=path, value=value,
                    reason="Explicit user clarification of this exact persistent obligation",
                    **extra))
        mapping = mapping.model_copy(update={
            "supplements": tuple(items), "bindings": (*mapping.bindings, *(
                DailyFieldBinding(path=s.path, value=s.value, origin="HUMAN_SUPPLEMENT",
                    unit="JSON", clause_ids=(), supplement_id=s.supplement_id) for s in items)),
        })
    return draft, source, mapping, obligation


@pytest.mark.parametrize("substitute", ["background", "transient", "sell", "fact"])
def test_buy_suspension_complete_positive_then_only_guard_omission_blocks(substitute):
    draft, source, mapping, raw = complete_suspension_case(substitute=substitute, clarified=True)
    assert build_daily_review(draft, mapping, source).issues == ()
    positive = assess_source_coverage(draft, mapping, source, origin="HUMAN")
    assert positive.coverage_complete, positive.issues
    assert positive.automatic_fidelity_verified is False
    resolved = next(o for o in positive.obligations if o.obligation_id == raw.obligation_id)
    assert resolved.state == "MAPPED_WITH_REGISTERED_SUPPLEMENT"
    absent, same_source, absent_mapping, same_obligation = complete_suspension_case(
        substitute=substitute, guard=False)
    assert same_source == source
    assert same_obligation.obligation_id == raw.obligation_id
    assert build_daily_review(absent, absent_mapping, source).issues == ()
    blocked = assess_source_coverage(absent, absent_mapping, source, origin="HUMAN")
    assert {i.code for i in blocked.issues} == {"SOURCE_BUY_SUSPENSION_REQUIRED"}
    assert all(o.state in {"MAPPED", "CONTEXT_VERIFIED"} for o in blocked.obligations
               if o.obligation_id != raw.obligation_id)


@pytest.mark.parametrize("mutation", ["unscoped", "source", "obligation", "value"])
def test_buy_suspension_clarification_must_match_the_exact_source_obligation(mutation):
    draft, source, mapping, _ = complete_suspension_case(clarified=True)
    assert assess_source_coverage(draft, mapping, source, origin="HUMAN").coverage_complete
    items = []
    for s in mapping.supplements:
        update = ({"source_hash": None, "obligation_id": None,
                   "buy_suspension_clarification": None} if mutation == "unscoped"
                  else {"source_hash": "0" * 64} if mutation == "source"
                  else {"obligation_id": "0" * 64} if mutation == "obligation"
                  else {"value": "wrong"})
        items.append(s.model_copy(update=update))
    changed = mapping.model_copy(update={"supplements": tuple(items)})
    blocked = assess_source_coverage(draft, changed, source, origin="HUMAN")
    assert not blocked.coverage_complete
    assert any(i.code == "SOURCE_BUY_SUSPENSION_CLARIFICATION_REQUIRED" for i in blocked.issues)


def test_buy_suspension_clarification_does_not_discharge_an_unknown_tail():
    draft, source, mapping, raw = complete_suspension_case(
        clarified=True, tail="\n仅当换手率超过3%时才允许买入。")
    result = assess_source_coverage(draft, mapping, source, origin="HUMAN")
    assert not result.coverage_complete
    assert next(o for o in result.obligations if o.obligation_id == raw.obligation_id).state == (
        "MAPPED_WITH_REGISTERED_SUPPLEMENT")
    assert all(i.start != raw.start for i in result.issues)


def test_buy_suspension_raw_and_approved_clarified_keep_the_same_source_obligation():
    draft, source, mapping, obligation = complete_suspension_case(clarified=True)
    clarified = assess_source_coverage(draft, mapping, source, origin="HUMAN")
    raw = assess_source_coverage(draft, mapping, source, origin="HUMAN",
                                allow_buy_suspension_clarifications=False)
    assert clarified.coverage_complete
    assert not raw.coverage_complete
    assert [(o.source_hash, o.obligation_id) for o in clarified.obligations] == [
        (o.source_hash, o.obligation_id) for o in raw.obligations]
    raw_guard = next(o for o in raw.obligations if o.obligation_id == obligation.obligation_id)
    assert raw_guard.state == "UNRESOLVED"


def test_buy_suspension_literal_background_label_cannot_erase_the_dedicated_obligation():
    control, source, registered, _ = complete_suspension_case(clarified=True)
    assert assess_source_coverage(control, registered, source, origin="HUMAN").coverage_complete
    absent, same_source, mapping, guard = complete_suspension_case(guard=False)
    assert source == same_source
    assert {i.code for i in assess_source_coverage(absent, mapping, source).issues} == {
        "SOURCE_BUY_SUSPENSION_REQUIRED"}
    clauses = tuple(c.model_copy(update={"disposition": "BACKGROUND"})
                    if c.start == guard.start else c for c in mapping.clauses)
    result = assess_source_coverage(absent, mapping.model_copy(update={"clauses": clauses}), source)
    assert any(i.code == "SOURCE_BUY_SUSPENSION_REQUIRED" and i.start == guard.start
               and i.end == guard.end for i in result.issues)
    assert all(o.state in {"MAPPED", "CONTEXT_VERIFIED"} for o in result.obligations
               if o.obligation_id != guard.obligation_id)
    # The legacy verifier additionally rejects this very BACKGROUND label. No
    # unrelated omitted parameter supplies the test's blocking evidence.
    assert {i.code for i in result.issues} == {
        "SOURCE_BUY_SUSPENSION_REQUIRED", "SOURCE_COVERAGE_REQUIRED"}


@pytest.mark.parametrize("missing", ["buy_suspension.condition.timeframe_minutes",
                                   "buy_suspension.effective_from"])
def test_buy_suspension_model_defaults_are_not_an_explicit_human_clarification(missing):
    draft, source, mapping, _ = complete_suspension_case(clarified=True)
    # Candidate stays structurally complete. Remove only the relevant source binding.
    items = tuple(s.model_copy(update=dict(source_hash=None, obligation_id=None,
        buy_suspension_clarification=None)) if s.path == missing else s
        for s in mapping.supplements)
    blocked = assess_source_coverage(draft, mapping.model_copy(update={"supplements": items}),
                                     source, origin="HUMAN")
    assert {i.code for i in blocked.issues} == {"SOURCE_BUY_SUSPENSION_CLARIFICATION_REQUIRED"}


@pytest.mark.parametrize("tail", ["不向下移动原25.99风险线。", "不向下移动原28.37风险线。",
                                "只有紫灯亮起才允许买入。"])
def test_buy_suspension_full_sentence_does_not_depend_on_the_following_risk_value(tail):
    directive = "如果再次跌破24.20创新低，则继续空仓，等待新的底部结构，" + tail
    draft, source, mapping, obligation = complete_suspension_case(
        clarified=True, directive=directive)
    result = assess_source_coverage(draft, mapping, source, origin="HUMAN")
    guard = next(o for o in result.obligations if o.obligation_id == obligation.obligation_id)
    assert guard.excerpt == directive[:-len(tail)]
    assert guard.state == "MAPPED_WITH_REGISTERED_SUPPLEMENT"
    remaining = [o for o in result.obligations if o.start >= guard.end]
    assert len(remaining) == 1 and remaining[0].excerpt == tail
    assert remaining[0].state == "UNRESOLVED"
    assert {i.start for i in result.issues} == {remaining[0].start}


@pytest.mark.parametrize("filename,digest", [
    ("03-20260930-095728.txt", "ed0addcd166735798111a6a22e9951270a2e4a8b1fc4448d0f49443baf8eb6bc"),
    ("04-20261009-091956.txt", "e71ab6dbfda744c92358b14ffd1ef8c09b2af13d6a12f6bc2d0e3255ea4f7d2b"),
])
def test_buy_suspension_originals_keep_other_blockers_after_exact_guard_clarification(
    filename, digest,
):
    from hashlib import sha256
    from pathlib import Path

    source_bytes = (Path(__file__).parents[1] / "fixtures/shengxin_sources" / filename).read_bytes()
    assert sha256(source_bytes).hexdigest() == digest
    source = source_bytes.decode("utf-8")
    draft = BuySuspensionPlanDraft.model_validate(suspension_payload())
    content = daily_draft_content_sha256(draft)
    mapping = DailyMapping(mapping_version="daily-mapping-v1", candidate_content_hash=content,
        clauses=daily_source_clauses(source), bindings=(), supplements=())
    raw = assess_source_coverage(draft, mapping, source, origin="HUMAN")
    obligations = [o for o in raw.obligations if o.semantics_json is not None
                   and '"treatment":"PERSISTENT_BUY_SUSPENSION"' in o.semantics_json]
    assert len(obligations) == 1
    obligation = obligations[0]
    assert obligation.state == "UNRESOLVED"
    items = tuple(DailySupplement(supplement_id=f"original-guard-{i}",
        candidate_content_hash=content, path=path, value=value,
        reason="Explicit approved clarification; all other source obligations remain blocking",
        source_hash=digest, obligation_id=obligation.obligation_id,
        buy_suspension_clarification="ALL_PLAN_BUY_REVIEWED_REPLACEMENT_ONLY")
        for i, (path, value) in enumerate(semantic_values(draft).items())
        if path.startswith("buy_suspension."))
    clarified_mapping = mapping.model_copy(update={"supplements": items, "bindings": tuple(
        DailyFieldBinding(path=s.path, value=s.value, origin="HUMAN_SUPPLEMENT", unit="JSON",
                          clause_ids=(), supplement_id=s.supplement_id) for s in items)})
    clarified = assess_source_coverage(draft, clarified_mapping, source, origin="HUMAN")
    assert clarified.source_hash == raw.source_hash == digest
    assert [(o.obligation_id, o.semantics_json) for o in clarified.obligations] == [
        (o.obligation_id, o.semantics_json) for o in raw.obligations]
    resolved = next(o for o in clarified.obligations if o.obligation_id == obligation.obligation_id)
    assert resolved.state == "MAPPED_WITH_REGISTERED_SUPPLEMENT"
    assert clarified.coverage_complete is False and clarified.issues
    assert not any(i.code.startswith("SOURCE_BUY_SUSPENSION") for i in clarified.issues)
