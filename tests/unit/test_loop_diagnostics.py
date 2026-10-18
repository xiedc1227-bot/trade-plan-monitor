"""Read-only result explanations must distinguish evidence from missing definitions."""

from datetime import date, datetime
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

from trade_plan_monitor.backtest.loop_diagnostics import PlanDiagnosticCollector
from trade_plan_monitor.decision.unified_conditions import UnifiedConditionEvidence

AT = datetime(2026, 9, 24, 15, 20, tzinfo=ZoneInfo("Asia/Shanghai"))


def collector(count=1, buy=True):
    versions = [
        (
            f"source-{i}",
            date(2026, 9, 24),
            NS(
                version_id=f"v-{i}",
                snapshot=NS(ordinary_rules=[NS(rule_id="buy", side="BUY")] if buy else []),
            ),
        )
        for i in range(count)
    ]
    return PlanDiagnosticCollector(versions, response_mode="FOLLOW_REMINDERS")


def price(outcome="UNSATISFIED", actual="2569"):
    return UnifiedConditionEvidence.model_validate(
        {
            "outcome": outcome,
            "condition": {
                "type": "DAILY_PRICE_COMPARE",
                "field": "close",
                "offset": 0,
                "comparator": "GT",
                "reference": {
                    "mode": "FIXED",
                    "value": "2670",
                    "unit": "FEN",
                    "as_of": None,
                    "source": "收盘站上26.70",
                },
            },
            "operands": [actual, "2670"],
            "session_dates": ["2026-09-24"],
        }
    )


def unknown():
    return UnifiedConditionEvidence.model_validate(
        {
            "outcome": "MISSING_INPUT",
            "condition": {
                "type": "REVIEWED_FACT",
                "fact_kind": "VOLUME_OR_CANDLE",
                "evidence_requirement": "量能不能异常放大\n原文约束：持仓0股",
                "validity_scope": "SIGNAL",
            },
            "reason": "REVIEWED_FACT_REQUIRED",
        }
    )


def event(evidence, version="v-0", blockers=()):
    return NS(
        version_id=version,
        at=AT,
        sequence=2,
        payload=NS(
            kind="EVALUATED",
            conditions=[NS(rule_id="buy", evidence=evidence)],
            blockers=blockers,
            duplicate=False,
            minute_target=None,
            official_trade_date=AT.date(),
        ),
    )


def group(kind, outcome, children):
    return UnifiedConditionEvidence.model_validate(
        {
            "outcome": outcome,
            "condition": {"type": kind, "conditions": [c.condition.model_dump() for c in children]},
            "children": [c.model_dump() for c in children],
        }
    )


def test_false_price_and_unknown_volume_remain_distinct_without_confirmation_request():
    projection = collector()
    projection.observe(event(group("ALL", "UNSATISFIED", [price(), unknown()])))
    result = projection.finish().plans[0]
    assert result.unmet_count == 1 and result.missing_count == 0
    assert set(result.categories) == {"MARKET_UNMET", "QUALITATIVE_UNRESOLVED"}
    market = next(e for e in result.examples if e.category == "MARKET_UNMET")
    assert "25.69" in market.actual and "26.70" in market.requirement
    assert market.root_outcome == "UNSATISFIED"
    assert "原文约束" not in str(result.examples)
    assert result.review_status == "PASSED"


def test_satisfied_any_does_not_present_its_unused_unknown_as_blocker():
    projection = collector()
    projection.observe(event(group("ANY", "SATISFIED", [price("SATISFIED", "2701"), unknown()])))
    result = projection.finish().plans[0]
    assert result.satisfied_count == 1
    assert "QUALITATIVE_UNRESOLVED" not in result.categories
    assert "MARKET_UNMET" not in result.categories
    assert "EXECUTION_BLOCKED" in result.categories


def test_data_absence_is_not_misreported_as_extraction_error():
    projection = collector()
    projection.observe(event(price(), blockers=("PRICE_BASIS_UNVERIFIED",)))
    assert "DATA_UNAVAILABLE" in projection.finish().plans[0].categories
    assert "PROCESSING_ERROR" not in projection.finish().plans[0].categories


def test_fractional_adjusted_prices_are_not_rounded_into_a_different_comparison():
    projection = collector()
    projection.observe(event(price(actual="2569.1234")))
    assert "25.691234 元" in projection.finish().plans[0].examples[0].actual


def test_explicit_processing_blocker_is_not_a_manual_definition_question():
    projection = collector()
    projection.observe(event(price(), blockers=("EXTRACTION_BINDING_CONFLICT",)))
    assert "PROCESSING_ERROR" in projection.finish().plans[0].categories


def test_no_authorized_buy_and_expired_audit_have_distinct_states():
    assert "NO_BUY_RULE" in collector(buy=False).finish().plans[0].categories
    expired = collector().finish(availability="EXPIRED")
    assert expired.availability == "EXPIRED"
    assert not expired.plans[0].examples and expired.plans[0].fill_count is None


def test_fills_are_attributed_to_the_version_that_executed_them():
    projection = collector(2)
    projection.observe(
        NS(
            version_id="v-1",
            at=AT,
            sequence=3,
            payload=NS(kind="EXECUTED", attempt=NS(status="FILLED")),
        )
    )
    assert [p.fill_count for p in projection.finish().plans] == [0, 1]


def test_observe_only_explains_satisfied_condition_without_inventing_a_market_failure():
    projection = collector()
    projection.response_mode = "OBSERVE_ONLY"
    projection.observe(event(price("SATISFIED", "2701")))
    plan = projection.finish().plans[0]
    assert "MARKET_UNMET" not in plan.categories
    assert any("仅观察提醒" in e.actual for e in plan.examples)


def test_unsupported_condition_is_processing_issue_not_missing_price_history():
    projection = collector()
    evidence = price().model_copy(
        update={"outcome": "MISSING_INPUT", "reason": "UNSUPPORTED_DAILY_CONDITION"}
    )
    projection.observe(event(evidence))
    assert projection.finish().plans[0].categories == ("PROCESSING_ERROR",)


def test_many_plans_keep_all_identities_and_bound_evidence():
    projection = collector(256)
    for i in range(256):
        projection.observe(event(group("ALL", "UNSATISFIED", [price(), unknown()]), f"v-{i}"))
    result = projection.finish()
    assert len(result.plans) == 256
    assert sum(len(p.examples) for p in result.plans) <= 256
    assert all(p.examples and p.sampled for p in result.plans)
