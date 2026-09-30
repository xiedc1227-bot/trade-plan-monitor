"""Recovered source minutes supply future explicit rolling windows without replay."""

import asyncio
from datetime import timedelta
from threading import Event

import pytest
import test_explicit_runtime_production as fixture
from sqlalchemy import func, select

from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.market_data.models import MinuteBar
from trade_plan_monitor.runtime.production import ProductionMonitorPipeline
from trade_plan_monitor.runtime.recovery import RecoveryAdmissionChangedError
from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline
from trade_plan_monitor.state.models import AlertDeliveryEligibility, AlertEvent, DeliveryAttempt


@pytest.mark.parametrize("precovered", [False, True])
def test_recovery_materializes_complete_history_without_replaying_decisions(
    tmp_path, monkeypatch, precovered,
):
    def build(**kwargs):
        kwargs.update(
            enable_runtime_status=True,
            recovery_session_factory=kwargs["unit_of_work_factory"]()._session_factory,
        )
        return ProductionMonitorPipeline(**kwargs)

    monkeypatch.setattr(fixture, "ProductionMonitorPipeline", build)

    async def scenario():
        engine, work, plan, sdk, _, controller, pipeline, _ = fixture._pipeline_fixture(
            tmp_path, monkeypatch, current_volume=300,
        )

        async def deadline(target):
            pipeline._clock.current = target + timedelta(seconds=15)
            return await pipeline.run_deadline(MarketDeadline(
                kind=DeadlineKind.REALTIME_MINUTE, trade_date=target.date(),
                due_at=pipeline._clock.now(), bar_end=target,
            ))

        try:
            await pipeline.refresh_references(fixture.TARGET.date())
            await deadline(fixture.TARGET)
            assert pipeline.runtime_status_snapshot()[2][0].completion is not None
            missed = fixture.TARGET + timedelta(minutes=5)
            # Provider is still held at the earlier target; the new bucket cannot commit.
            await deadline(missed)
            with work() as transaction:
                assert transaction.explicit_rules.get(
                    plan_hash=plan_sha256(plan), symbol=plan.symbol,
                    target_bucket_end=missed, activation_revision=1,
                ) is None
            pipeline._clock.current = missed + timedelta(minutes=1, seconds=15)
            sdk.source_time = missed
            if precovered:
                rows = pipeline.provider.current_day_minutes(plan.symbol)
                with work() as transaction:
                    have = {bar.bar_end for bar in transaction.history.list_minutes(
                        plan.symbol, start=rows[0].bar_end, end=rows[-1].bar_end,
                    )}
                    transaction.history.upsert_minutes(tuple(
                        row for row in rows if row.bar_end not in have
                    ))
                    transaction.commit()
            calls_before = len(sdk.calls)
            with work() as transaction:
                counts_before = tuple(transaction._session.scalar(
                    select(func.count()).select_from(model)
                ) for model in (AlertEvent, AlertDeliveryEligibility, DeliveryAttempt))
            recovered = (await pipeline._run_stock_recovery_unit(maintenance=False)).result
            assert recovered.ready
            if precovered:
                assert len(sdk.calls) == calls_before
            with work() as transaction:
                bars = transaction.history.list_five_minute(
                    plan.symbol, start=missed, end=missed + timedelta(minutes=5),
                    formula_version=plan.monitoring.indicator_formula_version,
                )
                assert tuple(bar.bar_end for bar in bars) == (missed,)
                assert transaction.explicit_rules.get(
                    plan_hash=plan_sha256(plan), symbol=plan.symbol,
                    target_bucket_end=missed, activation_revision=1,
                ) is None
                counts_after = tuple(transaction._session.scalar(
                    select(func.count()).select_from(model)
                ) for model in (AlertEvent, AlertDeliveryEligibility, DeliveryAttempt))
                assert counts_after == counts_before
            # The next real market duty consumes complete history; no old duty is replayed.
            future = missed + timedelta(minutes=5)
            for offset in range(2, 6):
                minute = missed + timedelta(minutes=offset)
                sdk.source_time = minute - timedelta(minutes=1)
                await deadline(minute)
            authority = pipeline.runtime_status_snapshot()[2][0]
            assert authority.completion is not None
            assert authority.completion.target.bucket_end == future
            from test_persistent_monitor_read_service import _setup

            from trade_plan_monitor.runtime.progress import ProgressSnapshot
            from trade_plan_monitor.runtime.status_authority import RuntimeReadAuthority
            from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService

            template = tmp_path / "read-template"
            template.mkdir()
            other, _, _, health = _setup(template)
            other.dispose()

            def read_authority():
                token, config, plans = pipeline.runtime_status_snapshot()
                observed = pipeline._clock.now()
                return RuntimeReadAuthority(
                    token=token, lifecycle="RUNNING", health=health,
                    configuration_revision=config, plans=plans,
                    progress=ProgressSnapshot(
                        pipeline._runtime_generation, observed, "SCHEDULED", observed,
                        observed + timedelta(seconds=10), observed + timedelta(seconds=30),
                    ),
                )

            reader = RuntimeStatusReadService(
                work()._session_factory, read_authority, clock=pipeline._clock.now,
            )
            assert (await reader.get_symbol(symbol=plan.symbol)).summary.availability == "CURRENT"
            with work() as transaction:
                result = transaction.explicit_rules.get(
                    plan_hash=plan_sha256(plan), symbol=plan.symbol,
                    target_bucket_end=future, activation_revision=1,
                )
                evidence = result.rule_results[0].condition_evidence
                assert not evidence.missing_inputs
                assert all(not child.missing_inputs for child in evidence.children)
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("fence", [None, "generation", "configuration", "activation", "cancelled"])
def test_recovered_aggregation_is_session_contained_and_capture_fenced(
    tmp_path, monkeypatch, fence,
):
    async def scenario():
        engine, work, plan, _, _, controller, pipeline, _ = fixture._pipeline_fixture(
            tmp_path, monkeypatch, current_volume=300,
        )
        try:
            await pipeline.refresh_references(fixture.TARGET.date())
            cutoff = fixture.TARGET.replace(hour=13, minute=3)
            pipeline._clock.current = cutoff + timedelta(seconds=15)
            capture = pipeline._capture_recovery_scope(plan.symbol)
            morning = cutoff.replace(hour=11, minute=30)
            ends = tuple(morning - timedelta(minutes=i) for i in range(4, -1, -1))
            ends += tuple(cutoff.replace(minute=i) for i in (1, 2, 3))
            rows = tuple(MinuteBar(
                symbol=plan.symbol, bar_end=end, open_fen=990, high_fen=990,
                low_fen=990, close_fen=990, volume_shares=60,
                amount_yuan=fixture.Decimal("0"), received_at=pipeline._clock.now(),
            ) for end in ends)
            cancelled = Event()
            if fence == "generation":
                pipeline._generation_current = lambda: False
            elif fence == "configuration":
                pipeline._recovery_configuration_revision = "changed"
            elif fence == "activation":
                with work() as transaction:
                    transaction.plans.deactivate(plan.symbol, expected_revision=1)
                    transaction.commit()
            elif fence == "cancelled":
                cancelled.set()
            if fence:
                with pytest.raises(RecoveryAdmissionChangedError):
                    pipeline._persist_recovery_capture(capture, rows, cancelled=cancelled)
            else:
                pipeline._persist_recovery_capture(capture, rows, cancelled=cancelled)
            with work() as transaction:
                bars = transaction.history.list_five_minute(
                    plan.symbol, start=morning, end=cutoff + timedelta(minutes=2),
                    formula_version=plan.monitoring.indicator_formula_version,
                )
                assert tuple(bar.bar_end for bar in bars) == (() if fence else (morning,))
                persisted = transaction.history.list_minutes(
                    plan.symbol, start=ends[0], end=cutoff,
                )
                assert len(persisted) == (0 if fence else len(rows))
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())
