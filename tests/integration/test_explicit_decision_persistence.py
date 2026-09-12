from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from trade_plan_monitor.decision.explicit_rules import (
    ExplicitInventorySnapshot,
    evaluate_explicit_rules,
)
from trade_plan_monitor.domain.plan_models import ExplicitTradePlan
from trade_plan_monitor.market_data.aggregation import FiveMinuteBar
from trade_plan_monitor.notifications.identity import explicit_alert_event_id
from trade_plan_monitor.notifications.models import (
    ExplicitAlertEvent,
    build_explicit_alert_payload,
)
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

SHANGHAI = ZoneInfo("Asia/Shanghai")
TARGET = datetime(2026, 9, 14, 10, 5, tzinfo=SHANGHAI)
NOW = TARGET + timedelta(seconds=2)


def _plan() -> ExplicitTradePlan:
    return ExplicitTradePlan.model_validate(
        {
            "schema_version": 3,
            "execution_mode": "EXPLICIT_RULES",
            "execution_version": "explicit-rules-v1",
            "plan_id": "synthetic-buy-persistence",
            "version": 1,
            "symbol": "003043.SZ",
            "name": "SYNTHETIC BUY PERSISTENCE",
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
                        "type": "COMPLETED_CLOSE_IN_RANGE",
                        "low_fen": 980,
                        "high_fen": 1000,
                        "include_low": True,
                        "include_high": True,
                    },
                    "action": {"type": "BUY", "quantity": 100},
                    "confirmation": {
                        "kind": "COMPLETED_BAR_CLOSE",
                        "timeframe_minutes": 5,
                    },
                    "repeat_policy": {"mode": "ONCE_PER_ACTIVATION"},
                    "safety_conditions": None,
                }
            ],
            "conflict_policy": {
                "trade_conflict": "BLOCK_BOTH",
                "risk_conflict": "RISK_ONLY",
            },
        }
    )


def _result():
    plan = _plan()
    bar = FiveMinuteBar(
        symbol=plan.symbol,
        bar_end=TARGET,
        open_fen=990,
        high_fen=990,
        low_fen=990,
        close_fen=990,
        volume_shares=100,
        amount_yuan=Decimal("0"),
    )
    result = evaluate_explicit_rules(
        plan=plan,
        bars=(bar,),
        trading_calendar=(),
        target_bucket_end=TARGET,
        evaluated_at=NOW,
        activation_revision=4,
        inventory=ExplicitInventorySnapshot(status="KNOWN", total_qty=100, inventory_revision=7),
        rule_states=(),
    )
    return plan, result


def _multi_result():
    payload = _plan().model_dump(mode="python", round_trip=True)
    payload["rules"] = [
        {
            "rule_id": "sell-100",
            "condition": {
                "type": "COMPLETED_CLOSE_IN_RANGE",
                "low_fen": 1080,
                "high_fen": 1100,
                "include_low": True,
                "include_high": True,
            },
            "action": {
                "type": "SELL",
                "quantity": 100,
                "inventory_scope": "ALL_REGISTERED",
            },
            "confirmation": {"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
            "repeat_policy": {"mode": "ONCE_PER_ACTIVATION"},
            "safety_conditions": None,
        },
        {
            "rule_id": "risk-under-1200",
            "condition": {"type": "COMPLETED_CLOSE_BELOW", "price_fen": 1200},
            "action": {"type": "RISK_ALERT"},
            "confirmation": {"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
            "repeat_policy": {"mode": "ONCE_PER_ACTIVATION"},
            "safety_conditions": None,
        },
    ]
    payload["conflict_policy"]["risk_conflict"] = "RISK_WITH_SELL_BLOCK_BUY"
    plan = ExplicitTradePlan.model_validate(payload)
    bar = FiveMinuteBar(
        symbol=plan.symbol,
        bar_end=TARGET,
        open_fen=1080,
        high_fen=1080,
        low_fen=1080,
        close_fen=1080,
        volume_shares=100,
        amount_yuan=Decimal("0"),
    )
    result = evaluate_explicit_rules(
        plan=plan,
        bars=(bar,),
        trading_calendar=(),
        target_bucket_end=TARGET,
        evaluated_at=NOW,
        activation_revision=4,
        inventory=ExplicitInventorySnapshot(
            status="KNOWN",
            total_qty=100,
            sellable_qty=100,
            inventory_revision=7,
        ),
        rule_states=(),
    )
    return plan, result


def _work(engine):
    return SqlAlchemyUnitOfWork(create_session_factory(engine), clock=lambda: NOW)


def _persist_with_alert(work, plan, result):
    record = work.explicit_rules.persist(result)
    signal = result.signal_intents[0]
    payload = build_explicit_alert_payload(
        event_id=explicit_alert_event_id(signal),
        plan=plan,
        result=result,
        signal=signal,
    )
    return record, work.alerts.enqueue_explicit(payload)


def test_result_state_and_explicit_alert_commit_atomically_and_replay_after_restart(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "explicit-atomic.sqlite3")
    try:
        upgrade_database(engine)
        plan, result = _result()
        with _work(engine) as work:
            record, event = _persist_with_alert(work, plan, result)
            work.commit()
        assert record.created is True
        assert isinstance(event, ExplicitAlertEvent)
        assert event.signal_type == "BUY"
        assert "仅提醒，不会自动下单" in event.message_text

        with _work(engine) as restarted:
            restored = restarted.explicit_rules.get(
                plan_hash=result.plan_hash,
                symbol=result.symbol,
                target_bucket_end=result.target_bucket_end,
                activation_revision=result.activation_revision,
            )
            states = restarted.explicit_rules.states(
                plan_hash=result.plan_hash,
                symbol=result.symbol,
                activation_revision=result.activation_revision,
            )
            replay, replayed_event = _persist_with_alert(restarted, plan, result)
            listed, total = restarted.alerts.list_events(
                symbol=result.symbol,
                signal_type="BUY",
                acknowledged=None,
                start_at=None,
                end_at=None,
                offset=0,
                limit=10,
            )
            restarted.commit()
        assert restored == result
        assert states[0].revision == 1
        assert replay.created is False
        assert replayed_event == event
        assert total == 1 and listed == (event,)
    finally:
        engine.dispose()


def test_rollback_after_enqueue_releases_result_state_event_and_dedup_claim(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "explicit-rollback.sqlite3")
    try:
        upgrade_database(engine)
        plan, result = _result()
        with _work(engine) as work:
            _, event = _persist_with_alert(work, plan, result)
            assert work.alerts.has_dedup_key(event.dedup_key)
            work.rollback()

        with _work(engine) as restarted:
            assert (
                restarted.explicit_rules.get(
                    plan_hash=result.plan_hash,
                    symbol=result.symbol,
                    target_bucket_end=result.target_bucket_end,
                    activation_revision=result.activation_revision,
                )
                is None
            )
            assert (
                restarted.explicit_rules.states(
                    plan_hash=result.plan_hash,
                    symbol=result.symbol,
                    activation_revision=result.activation_revision,
                )
                == ()
            )
            assert not restarted.alerts.has_dedup_key(event.dedup_key)
    finally:
        engine.dispose()


def test_risk_and_sell_enqueue_failure_rolls_back_both_and_retry_keeps_identities(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "explicit-multi-rollback.sqlite3")
    try:
        upgrade_database(engine)
        plan, result = _multi_result()
        assert tuple(signal.action.type for signal in result.signal_intents) == (
            "SELL",
            "RISK_ALERT",
        )
        first_event_id = None
        with _work(engine) as work:
            work.explicit_rules.persist(result)
            first_signal = result.signal_intents[0]
            first_event = work.alerts.enqueue_explicit(
                build_explicit_alert_payload(
                    event_id=explicit_alert_event_id(first_signal),
                    plan=plan,
                    result=result,
                    signal=first_signal,
                )
            )
            first_event_id = first_event.event_id
            work.rollback()

        committed_ids = []
        with _work(engine) as retry:
            record = retry.explicit_rules.persist(result)
            for signal in result.signal_intents:
                event = retry.alerts.enqueue_explicit(
                    build_explicit_alert_payload(
                        event_id=explicit_alert_event_id(signal),
                        plan=plan,
                        result=result,
                        signal=signal,
                    )
                )
                committed_ids.append(event.event_id)
            retry.commit()

        assert record.created is True
        assert committed_ids[0] == first_event_id
        assert len(set(committed_ids)) == 2
        with _work(engine) as restarted:
            events, total = restarted.alerts.list_events(
                symbol=plan.symbol,
                signal_type=None,
                acknowledged=None,
                start_at=None,
                end_at=None,
                offset=0,
                limit=10,
            )
            states = restarted.explicit_rules.states(
                plan_hash=result.plan_hash,
                symbol=result.symbol,
                activation_revision=result.activation_revision,
            )
        assert total == 2
        assert {event.signal_type for event in events} == {"SELL", "RISK_ALERT"}
        assert len(states) == 2
    finally:
        engine.dispose()
