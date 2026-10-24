import pytest


@pytest.mark.parametrize(
    "regime,available,strength,group,reason",
    [
        ("NORMAL_TRANSITION", True, "UNKNOWN", "S0", None),
        ("WEAK", True, "UNKNOWN", "S1", None),
        ("WEAK", False, "STRONG", "S1", "P1_EXCEPTION_REQUIRED"),
        ("BROKEN", False, "NOT_STRONG", None, "MARKET_BROKEN"),
        ("BROKEN", False, "STRONG", "S2", "P1_EXCEPTION_REQUIRED"),
        ("BROKEN", False, "UNKNOWN", None, "MARKET_INPUT_UNKNOWN"),
        ("UNKNOWN", True, "STRONG", None, "MARKET_INPUT_UNKNOWN"),
        ("WEAK", None, "STRONG", None, "MARKET_INPUT_UNKNOWN"),
        ("WEAK", False, "UNKNOWN", None, "MARKET_INPUT_UNKNOWN"),
    ],
)
def test_all_routes(regime, available, strength, group, reason):
    from trade_plan_monitor.decision.confirmation_selection import select_confirmation

    result = select_confirmation(
        regime=regime, ordinary_quantity_available=available, strength=strength
    )
    assert result.group == group
    assert result.blocker == reason


def test_s1_s2_components_and_own_day_ma_are_preserved():
    from tests.unit.test_market_linkage_contract import linked_payload

    from trade_plan_monitor.decision.confirmation_selection import confirmation_components
    from trade_plan_monitor.domain.market_linkage_models import MarketLinkedTradePlan

    plan = MarketLinkedTradePlan.model_validate(linked_payload())
    rule = plan.ordinary_rules[0]
    s1 = confirmation_components(plan, rule, "S1")
    s2 = confirmation_components(plan, rule, "S2")
    assert s1[0] == rule.condition
    assert len(s1) == 6  # risk is evaluated independently, never fabricated as a fact
    assert s2[:6] == s1
    assert [(c.offset, c.reference.offset) for c in s2[-2:]] == [(1, 0), (0, 0)]


def test_each_required_predicate_can_fail_or_be_unknown():
    from trade_plan_monitor.decision.market_regime import all_truth

    for index in range(9):
        for outcome in ("UNSATISFIED", "MISSING_INPUT"):
            values = ["SATISFIED"] * 9
            values[index] = outcome
            assert all_truth(*values) == outcome


def confirmation_fixture():
    from decimal import Decimal

    from tests.unit.test_market_linkage_contract import linked_payload
    from tests.unit.test_market_regime import index_fixture
    from tests.unit.test_relative_strength import stock_fixture

    from trade_plan_monitor.domain.market_linkage_models import MarketLinkedTradePlan

    _, days, _, cutoff = index_fixture(40)
    series = stock_fixture(days, cutoff)
    bars = []
    for i, bar in enumerate(series.bars):
        close = Decimal(100 + i + 2 * (i % 2))
        bars.append(
            bar.model_copy(
                update={"open": close, "close": close, "low": close - 1, "high": close + 1}
            )
        )
    series = series.model_copy(update={"bars": tuple(bars)})
    raw = linked_payload()
    zone = dict(low_fen=100, high_fen=200, include_low=True, include_high=True)
    raw["levels"]["low_buy"] = zone
    raw["ordinary_rules"][0]["condition"] = dict(
        type="DAILY_PRICE_IN_RANGE", field="close", offset=0, range=zone
    )
    return MarketLinkedTradePlan.model_validate(raw), series, days[-1]


def test_s2_evaluates_each_own_day_ma_not_double_offset():
    from decimal import Decimal

    from trade_plan_monitor.decision.confirmation_selection import evaluate_confirmation

    plan, series, day = confirmation_fixture()
    outcome, proofs = evaluate_confirmation(
        plan,
        plan.ordinary_rules[0],
        "S2",
        series=series,
        facts=(),
        decision_session=day,
        risk="UNSATISFIED",
    )
    assert outcome == "SATISFIED"
    assert Decimal(proofs[-2].operands[1]) == sum(b.close for b in series.bars[-21:-1]) / 20
    assert Decimal(proofs[-1].operands[1]) == sum(b.close for b in series.bars[-20:]) / 20


@pytest.mark.parametrize(
    "component",
    [
        "s0",
        "previous_zone",
        "current_zone",
        "sequence",
        "volume",
        "rsi",
        "risk",
        "unknown_s0",
        "gap",
    ],
)
def test_s1_data_failures_cannot_confirm(component):
    from decimal import Decimal

    from trade_plan_monitor.decision.confirmation_selection import evaluate_confirmation
    from trade_plan_monitor.domain.market_linkage_models import MarketLinkedTradePlan

    plan, series, day = confirmation_fixture()
    raw = plan.model_dump(mode="json")
    bars = list(series.bars)
    risk = "SATISFIED" if component == "risk" else "UNSATISFIED"
    if component == "s0":
        raw["ordinary_rules"][0]["condition"]["range"]["low_fen"] = 190
    elif component == "unknown_s0":
        raw["ordinary_rules"][0]["condition"]["offset"] = 100
    elif component in {"previous_zone", "current_zone", "sequence"}:
        i = -2 if component == "previous_zone" else -1
        close = Decimal(90 if i == -2 else 201 if component == "current_zone" else 137)
        bars[i] = bars[i].model_copy(
            update={"close": close, "open": close, "low": close - 1, "high": close + 1}
        )
    elif component == "volume":
        bars[-1] = bars[-1].model_copy(update={"volume_shares": 1001})
    elif component == "rsi":
        # An unchanged close leaves Wilder RSI unchanged; strict increase fails.
        close = bars[-2].close
        bars[-1] = bars[-1].model_copy(
            update={"close": close, "open": close, "low": close - 1, "high": close + 1}
        )
    elif component == "gap":
        missing = bars.pop(-3).trade_date
        series = series.model_copy(update={"bars": tuple(bars), "suspended_dates": (missing,)})
    series = series.model_copy(update={"bars": tuple(bars)})
    plan = MarketLinkedTradePlan.model_validate(raw)
    outcome, _ = evaluate_confirmation(
        plan, plan.ordinary_rules[0], "S1", series=series, facts=(), decision_session=day, risk=risk
    )
    assert outcome != "SATISFIED"
