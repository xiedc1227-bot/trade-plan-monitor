"""Precisely stated alternatives are executable; optional preferences are not gates."""

from copy import deepcopy

from tests.unit.test_preparation_source_resolution import recorded_candidate

from trade_plan_monitor.domain.unified_plan_models import condition_leaves


def test_explicit_two_close_alternative_is_not_a_manual_fact():
    source, candidate = recorded_candidate(1)
    leaves = list(condition_leaves(candidate.draft.ordinary_rules[0].condition))
    sequence = next((c for c in leaves if c.type == "DAILY_CLOSE_SEQUENCE"), None)
    assert sequence is not None
    assert sequence.sessions == 2 and sequence.mode == "PAIRWISE_NONDECREASING"
    assert any(c.type == "REVIEWED_FACT" and "量能" in c.evidence_requirement for c in leaves)
    assert not any(i.code.startswith("DAILY_SOURCE") for i in candidate.review(source.text).issues)


def test_explicit_best_preference_does_not_become_hard_buy_prerequisite():
    from trade_plan_monitor.ai.source_resolution import normalize_source_conditions, plain

    source, candidate = recorded_candidate(4)
    data = candidate.draft.model_dump(mode="json")
    required = deepcopy(data["ordinary_rules"][0]["condition"])
    optional = {
        "type": "REVIEWED_FACT",
        "fact_kind": "VOLUME_OR_CANDLE",
        "evidence_requirement": "成交不明显萎缩；收盘不重新落回25.99以下（最好条件，非硬性前提）",
        "validity_scope": "SIGNAL",
    }
    data["ordinary_rules"][0]["condition"] = {"type": "ALL", "conditions": [required, optional]}
    normalize_source_conditions(data, plain(source.text))
    assert data["ordinary_rules"][0]["condition"]["conditions"] == [required]
