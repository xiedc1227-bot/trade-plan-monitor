"""Reference work must retain the exact persisted plan activation it captured."""

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import update
from test_explicit_runtime_production import _plan as explicit_plan
from test_explicit_runtime_production import _seed_active
from test_live_pipeline_acceptance import NOW, _sample_plan
from test_production_semantic_gate import _deadline, _pipeline, _replace_stock_contract

from trade_plan_monitor.domain.plan_models import TradePlan
from trade_plan_monitor.domain.plan_validation import ALL_MARKET_EVIDENCE, validate_trade_plan
from trade_plan_monitor.market_data.sessions import SourceTimeLabel
from trade_plan_monitor.runtime.request_control import TushareOperation
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import ActivePlan, PlanActivationState


def seed_explicit(tmp_path):
    engine = create_sqlite_engine(tmp_path / "monitor.sqlite3")
    plan = explicit_plan(active_date=NOW.date())
    try:
        _seed_active(engine, plan)
        with create_session_factory(engine).begin() as session:
            session.execute(update(ActivePlan).values(activated_at=NOW.replace(hour=9).isoformat()))
            session.execute(
                update(PlanActivationState).values(changed_at=NOW.replace(hour=9).isoformat())
            )
    finally:
        engine.dispose()
    return plan


def replace_or_reactivate(work, pipeline, plan):
    """Use real activation transactions; the replacement remains eligible for this cutoff."""
    previous = pipeline._clock.current
    pipeline._clock.current = NOW.replace(hour=9, minute=1)
    try:
        with work() as transaction:
            active = transaction.plans.get_active(plan.symbol)
            inactive = transaction.plans.deactivate(plan.symbol, expected_revision=active.revision)
            if transaction.plans.get_version(plan.plan_id, plan.version) is None:
                transaction.plans.save_draft(
                    plan, source_text="offline recovery activation fixture",
                )
            replacement = transaction.plans.activate(
                plan, expected_revision=inactive.revision,
                validation=validate_trade_plan(plan, available_market_evidence=ALL_MARKET_EVIDENCE),
            )
            transaction.commit()
        return replacement
    finally:
        pipeline._clock.current = previous


def record_deadline_admission(pipeline):
    admitted = []

    async def run(_deadline):
        admitted.append(pipeline.deadline_plans())
        return ()

    async def noop(*args, **kwargs):
        return None

    pipeline.coordinator = SimpleNamespace(run_deadline=run)
    pipeline._repair_detected_gaps = noop
    pipeline._refresh_dashboard_indexes = noop
    return admitted


def test_same_symbol_explicit_to_legacy_acquires_new_history_and_limits(tmp_path, monkeypatch):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch) as (pipeline, sdk, _, _, work):
            explicit = seed_explicit(tmp_path)
            sdk.stock_symbols = (explicit.symbol,)
            await pipeline.refresh_references(NOW.date())
            assert all(name == "trade_cal" for name, _ in sdk.calls)
            replace_or_reactivate(work, pipeline, _sample_plan())
            admitted = record_deadline_admission(pipeline)
            await pipeline.run_deadline(_deadline())
            names = [name for name, _ in sdk.calls]
            assert "stk_limit" in names
            assert "daily" in names
            assert len(admitted) == 1 and isinstance(admitted[0][0], TradePlan)

    asyncio.run(scenario())


def test_same_plan_reactivation_during_refresh_cannot_install_old_activation_key(
    tmp_path, monkeypatch,
):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            sdk.stock_symbols = (_sample_plan().symbol,)
            original = pipeline._request
            mutated = False

            async def rotate_after_request(operation, call, key):
                nonlocal mutated
                result = await original(operation, call, key)
                if not mutated:
                    mutated = True
                    replace_or_reactivate(work, pipeline, _sample_plan())
                return result

            pipeline._request = rotate_after_request
            with pytest.raises(RuntimeError, match="reference dependencies changed"):
                await pipeline.refresh_references(NOW.date())
            assert pipeline._reference_key is None

    asyncio.run(scenario())


def test_deadline_does_not_admit_captured_plan_reactivated_during_reference_await(
    tmp_path, monkeypatch,
):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            sdk.stock_symbols = (_sample_plan().symbol,)
            admitted = record_deadline_admission(pipeline)
            original = pipeline.refresh_references

            async def reactivate_before_refresh(day):
                replace_or_reactivate(work, pipeline, _sample_plan())
                await original(day)

            pipeline.refresh_references = reactivate_before_refresh
            with pytest.raises(RuntimeError, match="reference dependencies changed"):
                await pipeline.run_deadline(_deadline())
            assert not admitted
            assert pipeline._deadline_plans is None

    asyncio.run(scenario())


def test_deadline_does_not_admit_captured_plan_reactivated_during_recovery_await(
    tmp_path, monkeypatch,
):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            sdk.stock_symbols = (_sample_plan().symbol,)
            admitted = record_deadline_admission(pipeline)

            async def reactivate_during_recovery(*, before_date):
                assert before_date == NOW.date()
                replace_or_reactivate(work, pipeline, _sample_plan())

            pipeline._recover_historical_closes = reactivate_during_recovery
            with pytest.raises(RuntimeError, match="reference dependencies changed"):
                await pipeline.run_deadline(_deadline())
            assert not admitted
            assert pipeline._deadline_plans is None

    asyncio.run(scenario())


def test_metadata_only_refresh_during_request_preserves_dependency_identity(tmp_path, monkeypatch):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch) as (pipeline, _, directory, _, _):
            await pipeline.refresh_references(NOW.date())
            original_key = pipeline._reference_key
            original = pipeline._request

            async def refresh_metadata(operation, call, key):
                result = await original(operation, call, key)
                if operation is TushareOperation.TRADING_CALENDAR:
                    _replace_stock_contract(directory)
                return result

            pipeline._request = refresh_metadata
            await pipeline.refresh_references(NOW.date())
            assert pipeline._reference_key == original_key

    asyncio.run(scenario())


def test_deactivation_during_refresh_cannot_install_removed_plan_key(tmp_path, monkeypatch):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            sdk.stock_symbols = (_sample_plan().symbol,)
            original = pipeline._request
            changed = False

            async def deactivate_after_request(operation, call, key):
                nonlocal changed
                result = await original(operation, call, key)
                if not changed:
                    changed = True
                    with work() as transaction:
                        transaction.plans.deactivate(_sample_plan().symbol, expected_revision=1)
                        transaction.commit()
                return result

            pipeline._request = deactivate_after_request
            with pytest.raises(RuntimeError, match="reference dependencies changed"):
                await pipeline.refresh_references(NOW.date())
            assert pipeline._reference_key is None

    asyncio.run(scenario())


def test_semantic_revision_change_after_final_request_cannot_install_reference_key(
    tmp_path, monkeypatch,
):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch) as (pipeline, _, directory, _, _):
            original = pipeline._request

            async def change_semantics(operation, call, key):
                result = await original(operation, call, key)
                _replace_stock_contract(directory, label=SourceTimeLabel.END)
                return result

            pipeline._request = change_semantics
            with pytest.raises(RuntimeError, match="reference dependencies changed"):
                await pipeline.refresh_references(NOW.date())
            assert pipeline._reference_key is None

    asyncio.run(scenario())


def test_metadata_refresh_does_not_refetch_ready_plan_references(tmp_path, monkeypatch):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, directory, _, _):
            sdk.stock_symbols = (_sample_plan().symbol,)
            await pipeline.refresh_references(NOW.date())
            calls_before = tuple(sdk.calls)
            _replace_stock_contract(directory)
            admitted = record_deadline_admission(pipeline)
            await pipeline.run_deadline(_deadline())
            assert tuple(sdk.calls) == calls_before
            assert len(admitted) == 1

    asyncio.run(scenario())
