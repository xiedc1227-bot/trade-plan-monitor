from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from trade_plan_monitor.decision.models import ConditionOutcome
from trade_plan_monitor.domain.plan_models import ExplicitTradePlan
from trade_plan_monitor.market_data.aggregation import FiveMinuteBar

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _plan(*, repeat: str = "ONCE_PER_ACTIVATION") -> ExplicitTradePlan:
    return ExplicitTradePlan.model_validate(
        {
            "schema_version": 3,
            "execution_mode": "EXPLICIT_RULES",
            "execution_version": "explicit-rules-v1",
            "plan_id": "synthetic-f06-buy",
            "version": 1,
            "symbol": "003043.SZ",
            "name": "SYNTHETIC F06 BUY SUBSET",
            "market": "SZSE",
            "metadata": {},
            "activation": {"mode": "TRADING_DAY", "trading_day": "2026-09-14"},
            "position": {
                "inventory_scope": "ALL_REGISTERED",
                "lot_size": 100,
                "max_qty": 300,
            },
            "monitoring": {
                "timeframe_minutes": 5,
                "indicator_formula_version": "ta-v1",
            },
            "rules": [
                {
                    "rule_id": "buy-100",
                    "condition": {
                        "type": "ALL",
                        "conditions": [
                            {
                                "type": "COMPLETED_CLOSE_IN_RANGE",
                                "low_fen": 980,
                                "high_fen": 1000,
                                "include_low": True,
                                "include_high": True,
                            },
                            {
                                "type": "VOLUME_TO_MEAN_GTE",
                                "window_bars": 5,
                                "minimum_ratio": "1.5",
                                "history_scope": "CONTIGUOUS_TRADING_BARS",
                            },
                        ],
                    },
                    "action": {"type": "BUY", "quantity": 100},
                    "confirmation": {
                        "kind": "COMPLETED_BAR_CLOSE",
                        "timeframe_minutes": 5,
                    },
                    "repeat_policy": {"mode": repeat},
                    "safety_conditions": None,
                }
            ],
            "conflict_policy": {
                "trade_conflict": "BLOCK_BOTH",
                "risk_conflict": "RISK_ONLY",
            },
        }
    )


def _bars(*, current_volume: int = 300, current_close: int = 990) -> tuple[FiveMinuteBar, ...]:
    first = datetime(2026, 9, 14, 9, 40, tzinfo=SHANGHAI)
    volumes = (100, 100, 100, 100, 600, current_volume)
    return tuple(
        FiveMinuteBar(
            symbol="003043.SZ",
            bar_end=first + timedelta(minutes=index * 5),
            open_fen=current_close,
            high_fen=current_close,
            low_fen=current_close,
            close_fen=current_close,
            volume_shares=volume,
            amount_yuan=Decimal("0"),
        )
        for index, volume in enumerate(volumes)
    )


def _inventory(
    total: int | None,
    *,
    sellable: int | None = None,
    revision: int = 7,
    missing_reasons: tuple[str, ...] = (),
):
    from trade_plan_monitor.decision.explicit_rules import ExplicitInventorySnapshot

    if total is None and not missing_reasons:
        missing_reasons = ("POSITION_UNKNOWN",)
    if total is not None and sellable is None and not missing_reasons:
        sellable = total
    return ExplicitInventorySnapshot(
        status="KNOWN" if total is not None else "UNKNOWN",
        total_qty=total,
        sellable_qty=sellable,
        inventory_revision=revision,
        missing_reasons=missing_reasons,
    )


def _rule(
    rule_id: str,
    *,
    condition: dict[str, object],
    action: dict[str, object],
    repeat: str = "ONCE_PER_ACTIVATION",
) -> dict[str, object]:
    return {
        "rule_id": rule_id,
        "condition": condition,
        "action": action,
        "confirmation": {"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
        "repeat_policy": {"mode": repeat},
        "safety_conditions": None,
    }


def _plan_with_rules(
    *rules: dict[str, object],
    risk_conflict: str = "RISK_ONLY",
) -> ExplicitTradePlan:
    payload = _plan().model_dump(mode="python", round_trip=True)
    payload["rules"] = list(rules)
    payload["conflict_policy"]["risk_conflict"] = risk_conflict
    return ExplicitTradePlan.model_validate(payload)


def _range(low_fen: int, high_fen: int) -> dict[str, object]:
    return {
        "type": "COMPLETED_CLOSE_IN_RANGE",
        "low_fen": low_fen,
        "high_fen": high_fen,
        "include_low": True,
        "include_high": True,
    }


def _evaluate(*, plan=None, bars=None, inventory=None, state=None, activation_revision=4):
    from trade_plan_monitor.decision.explicit_rules import evaluate_explicit_rules

    values = bars or _bars()
    return evaluate_explicit_rules(
        plan=plan or _plan(),
        bars=values,
        trading_calendar=(),
        target_bucket_end=values[-1].bar_end,
        evaluated_at=values[-1].bar_end + timedelta(seconds=2),
        activation_revision=activation_revision,
        inventory=inventory or _inventory(100),
        rule_states=() if state is None else (state,),
    )


def test_first_qualifying_bar_emits_direct_buy_100_with_state_proposal() -> None:
    result = _evaluate()

    assert result.result_schema_version == "decision-result-v2"
    assert len(result.signal_intents) == 1
    assert result.signal_intents[0].action.type == "BUY"
    assert result.signal_intents[0].action.quantity == 100
    assert result.signal_intents[0].rule_id == "buy-100"
    assert result.rule_results[0].condition_evidence.outcome is ConditionOutcome.SATISFIED
    assert result.rule_results[0].state_transition is not None
    assert result.rule_results[0].state_transition.next_revision == 1
    assert result.inventory_revision == 7


@pytest.mark.parametrize(
    ("total", "emits", "blocker"),
    [(None, False, "POSITION_UNKNOWN"), (200, True, None), (300, False, "MAX_POSITION_EXCEEDED")],
)
def test_buy_uses_known_current_inventory_without_reserving_or_filling(
    total: int | None,
    emits: bool,
    blocker: str | None,
) -> None:
    result = _evaluate(inventory=_inventory(total))

    assert bool(result.signal_intents) is emits
    if emits:
        assert result.rule_results[0].state_transition is not None
    else:
        assert result.rule_results[0].state_transition is None
    if blocker is not None:
        assert blocker in result.rule_results[0].blockers


def test_once_per_activation_suppresses_after_emit_but_new_activation_can_emit() -> None:
    from trade_plan_monitor.decision.explicit_rules import ExplicitRuleStateSnapshot

    target = _bars()[-1].bar_end
    state = ExplicitRuleStateSnapshot(
        rule_id="buy-100",
        activation_revision=4,
        revision=1,
        has_emitted=True,
        last_emitted_bucket_end=target - timedelta(minutes=5),
    )

    repeated = _evaluate(state=state)
    rotated = _evaluate(activation_revision=5, state=state)

    assert repeated.signal_intents == ()
    assert repeated.rule_results[0].suppression_reason == "ONCE_ALREADY_EMITTED"
    assert len(rotated.signal_intents) == 1


def test_each_qualifying_bar_suppresses_replay_only_and_does_not_consume_blocked_bar() -> None:
    from trade_plan_monitor.decision.explicit_rules import ExplicitRuleStateSnapshot

    values = _bars()
    target = values[-1].bar_end
    state = ExplicitRuleStateSnapshot(
        rule_id="buy-100",
        activation_revision=4,
        revision=1,
        has_emitted=True,
        last_emitted_bucket_end=target,
    )
    replay = _evaluate(plan=_plan(repeat="EACH_QUALIFYING_BAR"), state=state)
    next_values = values[1:] + (
        values[-1].model_copy(
            update={"bar_end": target + timedelta(minutes=5), "volume_shares": 600}
        ),
    )
    later = _evaluate(plan=_plan(repeat="EACH_QUALIFYING_BAR"), bars=next_values, state=state)
    blocked = _evaluate(
        plan=_plan(repeat="EACH_QUALIFYING_BAR"),
        bars=next_values,
        inventory=_inventory(300),
        state=state,
    )

    assert replay.signal_intents == ()
    assert replay.rule_results[0].suppression_reason == "TARGET_ALREADY_EMITTED"
    assert len(later.signal_intents) == 1
    assert later.rule_results[0].state_transition.next_revision == 2
    assert blocked.rule_results[0].state_transition is None


def test_result_hash_is_deterministic_and_tamper_evident() -> None:
    from pydantic import ValidationError

    first = _evaluate()
    second = _evaluate()
    assert first.result_hash == second.result_hash

    payload = first.model_dump(mode="python", round_trip=True)
    payload["inventory_revision"] = 8
    with pytest.raises(ValidationError, match="result_hash"):
        type(first).model_validate(payload)


def test_price_or_volume_false_emits_nothing_without_legacy_episode_state() -> None:
    price_only = _evaluate(bars=_bars(current_volume=299))
    volume_only = _evaluate(bars=_bars(current_close=1001))

    assert price_only.signal_intents == ()
    assert volume_only.signal_intents == ()
    assert price_only.rule_results[0].state_transition is None
    assert volume_only.rule_results[0].state_transition is None


@pytest.mark.parametrize(
    ("close_fen", "emits"),
    [(1079, False), (1080, True), (1100, True), (1101, False)],
)
def test_sell_range_emits_exact_requested_quantity_only_when_sellable(
    close_fen: int,
    emits: bool,
) -> None:
    plan = _plan_with_rules(
        _rule(
            "sell-100",
            condition=_range(1080, 1100),
            action={"type": "SELL", "quantity": 100, "inventory_scope": "ALL_REGISTERED"},
        )
    )

    result = _evaluate(
        plan=plan,
        bars=_bars(current_close=close_fen),
        inventory=_inventory(100, sellable=100),
    )

    assert bool(result.signal_intents) is emits
    if emits:
        assert result.signal_intents[0].action.type == "SELL"
        assert result.signal_intents[0].action.quantity == 100
        assert result.signal_intents[0].next_step == "REVIEW_SELL_REMINDER"


@pytest.mark.parametrize(
    ("inventory", "blocker"),
    [
        (_inventory(None, missing_reasons=("POSITION_UNKNOWN",)), "POSITION_UNKNOWN"),
        (
            _inventory(100, sellable=None, missing_reasons=("SELLABLE_QUANTITY_UNKNOWN",)),
            "SELLABLE_QUANTITY_UNKNOWN",
        ),
        (_inventory(100, sellable=0), "INSUFFICIENT_SELLABLE_QUANTITY"),
    ],
)
def test_sell_preserves_requested_quantity_and_reports_authoritative_inventory_blocker(
    inventory,
    blocker: str,
) -> None:
    plan = _plan_with_rules(
        _rule(
            "sell-100",
            condition=_range(1080, 1100),
            action={"type": "SELL", "quantity": 100, "inventory_scope": "ALL_REGISTERED"},
        )
    )

    result = _evaluate(
        plan=plan,
        bars=_bars(current_close=1080),
        inventory=inventory,
    )

    assert result.signal_intents == ()
    assert result.rule_results[0].action.quantity == 100
    assert blocker in result.rule_results[0].blockers


@pytest.mark.parametrize(
    ("close_fen", "emits"),
    [(949, True), (950, False), (951, False)],
)
def test_pure_five_minute_risk_has_no_quantity_or_inventory_dependency(
    close_fen: int,
    emits: bool,
) -> None:
    plan = _plan_with_rules(
        _rule(
            "risk-below-950",
            condition={"type": "COMPLETED_CLOSE_BELOW", "price_fen": 950},
            action={"type": "RISK_ALERT"},
        )
    )

    result = _evaluate(
        plan=plan,
        bars=_bars(current_close=close_fen),
        inventory=_inventory(None, missing_reasons=("POSITION_UNKNOWN",)),
    )

    assert bool(result.signal_intents) is emits
    assert result.inventory_revision is None
    if emits:
        signal = result.signal_intents[0]
        assert signal.action.type == "RISK_ALERT"
        assert getattr(signal.action, "quantity", None) is None
        assert signal.next_step == "REVIEW_RISK_REMINDER"


def test_trade_conflict_blocks_buy_and_sell_before_repeat_or_inventory_checks() -> None:
    plan = _plan_with_rules(
        _rule("buy-100", condition=_range(990, 990), action={"type": "BUY", "quantity": 100}),
        _rule(
            "sell-100",
            condition=_range(990, 990),
            action={"type": "SELL", "quantity": 100, "inventory_scope": "ALL_REGISTERED"},
        ),
    )

    result = _evaluate(
        plan=plan,
        inventory=_inventory(None, missing_reasons=("POSITION_UNKNOWN",)),
    )

    assert result.signal_intents == ()
    assert result.inventory_revision is None
    assert all("TRADE_RULE_CONFLICT" in item.blockers for item in result.rule_results)


@pytest.mark.parametrize(
    ("risk_conflict", "expected_actions"),
    [("RISK_ONLY", ("RISK_ALERT",)), ("RISK_WITH_SELL_BLOCK_BUY", ("SELL", "RISK_ALERT"))],
)
def test_risk_sell_conflict_policy_preserves_independent_multi_intents(
    risk_conflict: str,
    expected_actions: tuple[str, ...],
) -> None:
    plan = _plan_with_rules(
        _rule(
            "sell-100",
            condition=_range(1080, 1100),
            action={"type": "SELL", "quantity": 100, "inventory_scope": "ALL_REGISTERED"},
        ),
        _rule(
            "risk-under-1200",
            condition={"type": "COMPLETED_CLOSE_BELOW", "price_fen": 1200},
            action={"type": "RISK_ALERT"},
        ),
        risk_conflict=risk_conflict,
    )

    result = _evaluate(
        plan=plan,
        bars=_bars(current_close=1080),
        inventory=_inventory(100, sellable=100),
    )

    assert tuple(intent.action.type for intent in result.signal_intents) == expected_actions
    sell_result = result.rule_results[0]
    if risk_conflict == "RISK_ONLY":
        assert "RISK_RULE_CONFLICT" in sell_result.blockers
    else:
        assert result.inventory_revision == 7


def test_repeat_suppressed_true_risk_still_blocks_buy() -> None:
    from trade_plan_monitor.decision.explicit_rules import ExplicitRuleStateSnapshot

    plan = _plan_with_rules(
        _rule("buy-100", condition=_range(990, 990), action={"type": "BUY", "quantity": 100}),
        _rule(
            "risk-under-1200",
            condition={"type": "COMPLETED_CLOSE_BELOW", "price_fen": 1200},
            action={"type": "RISK_ALERT"},
        ),
    )
    state = ExplicitRuleStateSnapshot(
        rule_id="risk-under-1200",
        activation_revision=4,
        revision=1,
        has_emitted=True,
        last_emitted_bucket_end=_bars()[-1].bar_end - timedelta(minutes=5),
    )

    result = _evaluate(plan=plan, inventory=_inventory(100, sellable=100), state=state)

    assert result.signal_intents == ()
    assert "RISK_RULE_CONFLICT" in result.rule_results[0].blockers
    assert result.rule_results[1].suppression_reason == "ONCE_ALREADY_EMITTED"


def test_unknown_potential_risk_blocks_trade_but_not_known_risk() -> None:
    risk_missing = {
        "type": "ALL",
        "conditions": [
            {"type": "COMPLETED_CLOSE_BELOW", "price_fen": 1200},
            {
                "type": "VOLUME_TO_MEAN_GTE",
                "window_bars": 5,
                "minimum_ratio": "1.5",
                "history_scope": "CONTIGUOUS_TRADING_BARS",
            },
        ],
    }
    plan = _plan_with_rules(
        _rule("buy-100", condition=_range(990, 990), action={"type": "BUY", "quantity": 100}),
        _rule("risk-unknown", condition=risk_missing, action={"type": "RISK_ALERT"}),
    )
    short_bars = (_bars()[-1],)

    result = _evaluate(
        plan=plan,
        bars=short_bars,
        inventory=_inventory(100, sellable=100),
    )

    assert result.signal_intents == ()
    assert "CONFLICT_INPUT_UNKNOWN" in result.rule_results[0].blockers
    assert "CONDITION_INPUT_MISSING" in result.rule_results[1].blockers


def test_known_risk_is_not_swallowed_by_unrelated_buy_input_missing() -> None:
    buy_missing = {
        "type": "ALL",
        "conditions": [
            _range(990, 990),
            {
                "type": "VOLUME_TO_MEAN_GTE",
                "window_bars": 5,
                "minimum_ratio": "1.5",
                "history_scope": "CONTIGUOUS_TRADING_BARS",
            },
        ],
    }
    plan = _plan_with_rules(
        _rule("buy-missing", condition=buy_missing, action={"type": "BUY", "quantity": 100}),
        _rule(
            "risk-known",
            condition={"type": "COMPLETED_CLOSE_BELOW", "price_fen": 1200},
            action={"type": "RISK_ALERT"},
        ),
    )

    result = _evaluate(
        plan=plan,
        bars=(_bars()[-1],),
        inventory=_inventory(None, missing_reasons=("POSITION_UNKNOWN",)),
    )

    assert tuple(intent.action.type for intent in result.signal_intents) == ("RISK_ALERT",)
    assert result.inventory_revision is None
    assert "CONDITION_INPUT_MISSING" in result.rule_results[0].blockers
    assert result.rule_results[1].blockers == ()
