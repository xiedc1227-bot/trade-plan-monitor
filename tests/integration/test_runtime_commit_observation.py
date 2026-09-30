"""Owner completion observers see only actual commits and their consumed context."""

import asyncio
from datetime import timedelta

from test_ten_symbol_runtime import (
    _at,
    _bar,
    _runtime_context,
    _runtime_plan,
    _runtime_uow_factory,
)

from trade_plan_monitor.market_data.aggregation import expected_five_minute_ends
from trade_plan_monitor.runtime.service import IntradayCycleStatus, RuntimeEvaluationService
from trade_plan_monitor.state.database import create_sqlite_engine, upgrade_database


def test_observer_sees_committed_head_outside_transaction_and_not_duplicate(tmp_path):
    engine = create_sqlite_engine(tmp_path / "owner-commit.sqlite")
    upgrade_database(engine)
    plan, target = _runtime_plan(), _at(9, 35)
    now = target + timedelta(seconds=20)
    tracker, calls = {"active": 0}, []
    factory = _runtime_uow_factory(engine, tracker, now=now)

    async def fetch(symbol, bucket):
        return [_bar(symbol, minute) for minute in expected_five_minute_ends(bucket)]

    def observe(actual_plan, result, context):
        assert tracker["active"] == 0
        assert actual_plan == plan
        assert context.target.bucket_end == target
        with factory() as work:
            assert work.projections.get_decision_head(plan.symbol).result == result
        calls.append(result.result_hash)

    try:
        service = RuntimeEvaluationService(
            fetch_minutes=fetch, unit_of_work_factory=factory, context_builder=_runtime_context,
            committed_event_publisher=lambda _: None, committed_result_observer=observe,
        )
        first = asyncio.run(service.run_intraday(plan=plan, bucket_end=target, evaluated_at=now))
        second = asyncio.run(service.run_intraday(plan=plan, bucket_end=target, evaluated_at=now))
        assert first.status is IntradayCycleStatus.COMMITTED
        assert second.status is IntradayCycleStatus.DUPLICATE
        assert calls == [first.evaluation_result.result_hash]
    finally:
        engine.dispose()
