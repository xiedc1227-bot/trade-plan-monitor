"""Offline coordinator checks for ordered restart recovery and activation fencing."""

import asyncio
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from trade_plan_monitor.domain.plan_codec import load_plan_yaml
from trade_plan_monitor.runtime.historical_close_evidence import (
    HistoricalCloseUnknownReason,
    UnknownHistoricalClose,
)
from trade_plan_monitor.runtime.production import ProductionMonitorPipeline
from trade_plan_monitor.runtime.service import OfficialCloseCycleStatus


def test_recovery_retries_changed_activation_and_processes_missing_days_in_order():
    plan = load_plan_yaml((Path(__file__).parents[2] /
        "config/plans/003043.SZ.sample.yaml").read_text(encoding="utf-8"))
    observed = datetime(2026, 8, 25, 17, tzinfo=ZoneInfo("Asia/Shanghai"))
    first = date(2026, 8, 24)
    second = date(2026, 8, 25)
    active = SimpleNamespace(revision=1, activated_at=datetime(
        2026, 8, 24, 9, tzinfo=observed.tzinfo,
    ))
    responses = [UnknownHistoricalClose(HistoricalCloseUnknownReason.MISSING_EVIDENCE),
                 (first, second)]
    calls = []

    class Evaluator:
        async def run_official_close(self, **kwargs):
            calls.append(kwargs["trade_date"])
            return SimpleNamespace(status=OfficialCloseCycleStatus.COMMITTED)

    @contextmanager
    def work():
        yield SimpleNamespace(plans=SimpleNamespace(get_active=lambda _symbol: active))

    pipeline = object.__new__(ProductionMonitorPipeline)
    pipeline._clock = SimpleNamespace(now=lambda: observed)
    pipeline._historical_reader = SimpleNamespace(
        missing_targets=lambda _symbol, _observed: responses.pop(0),
    )
    pipeline.historical_evaluations = Evaluator()
    pipeline._persisted_active_plans = lambda: (plan,)
    pipeline._work = work
    pipeline._historical_blocked = {}
    pipeline._historical_retry_at = {}
    pipeline._historical_identity = {}

    asyncio.run(pipeline._recover_historical_closes(before_date=None))
    assert pipeline._historical_blocked[plan.symbol] == "MISSING_EVIDENCE"
    issue, = pipeline.recovery_issues()
    assert issue.symbol == plan.symbol
    assert issue.reason == "MISSING_EVIDENCE"
    assert issue.next_retry_at > observed
    assert calls == []

    # A new activation must not inherit the old task's retry delay or block.
    active.revision = 2
    asyncio.run(pipeline._recover_historical_closes(before_date=None))
    assert calls == [first, second]
    assert plan.symbol not in pipeline._historical_blocked
    assert pipeline.recovery_issues() == ()
