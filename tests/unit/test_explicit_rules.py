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


def _inventory(total: int | None, *, revision: int = 7):
    from trade_plan_monitor.decision.explicit_rules import ExplicitInventorySnapshot

    return ExplicitInventorySnapshot(
        status="KNOWN" if total is not None else "UNKNOWN",
        total_qty=total,
        inventory_revision=revision,
    )


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


def test_r09_buy_consumer_rejects_unimplemented_actions_explicitly() -> None:
    from trade_plan_monitor.decision.explicit_rules import (
        ExplicitExecutionCapabilityError,
        evaluate_explicit_rules,
    )

    payload = _plan().model_dump(mode="python", round_trip=True)
    payload["rules"][0]["action"] = {
        "type": "SELL",
        "quantity": 100,
        "inventory_scope": "ALL_REGISTERED",
    }
    plan = ExplicitTradePlan.model_validate(payload)
    values = _bars()

    with pytest.raises(ExplicitExecutionCapabilityError) as error:
        evaluate_explicit_rules(
            plan=plan,
            bars=values,
            trading_calendar=(),
            target_bucket_end=values[-1].bar_end,
            evaluated_at=values[-1].bar_end,
            activation_revision=4,
            inventory=_inventory(100),
            rule_states=(),
        )
    assert error.value.code == "EXECUTION_CAPABILITY_UNAVAILABLE"
