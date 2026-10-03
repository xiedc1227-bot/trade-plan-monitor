"""Reference work must retain the exact persisted plan activation it captured."""

import asyncio
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_live_pipeline_acceptance import NOW
from test_production_semantic_gate import _deadline, _pipeline, _replace_stock_contract
from tests.integration.current_activation_fixture import seed_current as seed_reviewed_current
from tests.integration.current_pipeline_fixture import current_three_rule_plan
from tests.unit.test_unified_plan_domain import unified_payload

from trade_plan_monitor.domain.plan_validation import PlanValidationResult
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.market_data.sessions import SourceTimeLabel
from trade_plan_monitor.runtime.request_control import TushareOperation


def seed_current(tmp_path, *, plan=None, activation_revision=0):
    return seed_reviewed_current(tmp_path, plan=plan or current_three_rule_plan(),
        activation_revision=activation_revision,
        clock=SimpleNamespace(now=lambda: NOW.replace(hour=9)))


def current_pipeline(tmp_path, monkeypatch, *, with_plan=False):
    if with_plan:
        seed_current(tmp_path)
    return _pipeline(tmp_path, monkeypatch)


def replace_or_reactivate(work, pipeline, plan):
    """Use real activation transactions; the replacement remains eligible for this cutoff."""
    previous = pipeline._clock.current
    pipeline._clock.current = NOW.replace(hour=9, minute=1)
    try:
        with work() as transaction:
            active = transaction.plans.get_active(plan.symbol)
            inactive = transaction.plans.deactivate(plan.symbol, expected_revision=active.revision)
            exists = transaction.plans.get_version(plan.plan_id, plan.version) is not None
            directory = Path(transaction.daily.session.bind.url.database).parent
            transaction.commit()
        if not exists:
            seed_current(directory, plan=plan, activation_revision=inactive.revision)
        else:
            with work() as transaction:
                transaction.plans.activate(
                    plan,
                    expected_revision=inactive.revision,
                    validation=PlanValidationResult(issues=()),
                )
                transaction.commit()
        with work() as transaction:
            replacement = transaction.plans.get_active(plan.symbol)
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


def test_same_symbol_minute_to_daily_acquires_required_calendar_warmup(tmp_path, monkeypatch):
    async def scenario():
        with current_pipeline(tmp_path, monkeypatch) as (pipeline, sdk, _, _, work):
            explicit = seed_current(tmp_path)
            sdk.stock_symbols = (explicit.symbol,)
            await pipeline.refresh_references(NOW.date())
            assert all(name == "trade_cal" for name, _ in sdk.calls)
            raw = unified_payload()
            raw.update(
                symbol=explicit.symbol, market=explicit.market, plan_id=explicit.plan_id, version=2
            )
            replace_or_reactivate(work, pipeline, UnifiedTradePlan.model_validate(raw))
            admitted = record_deadline_admission(pipeline)
            await pipeline.run_deadline(_deadline())
            calendar_calls = [arguments for name, arguments in sdk.calls if name == "trade_cal"]
            assert any(
                int(arguments["start_date"])
                <= int((NOW.date() - timedelta(days=750)).strftime("%Y%m%d"))
                for arguments in calendar_calls
            )
            assert all(name == "trade_cal" for name, _ in sdk.calls)
            assert len(admitted) == 1 and isinstance(admitted[0][0], UnifiedTradePlan)
            assert admitted[0][0].version == 2

    asyncio.run(scenario())


def test_same_plan_reactivation_during_refresh_cannot_install_old_activation_key(
    tmp_path,
    monkeypatch,
):
    async def scenario():
        with current_pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            sdk.stock_symbols = (current_three_rule_plan().symbol,)
            original = pipeline._request
            mutated = False

            async def rotate_after_request(operation, call, key):
                nonlocal mutated
                result = await original(operation, call, key)
                if not mutated:
                    mutated = True
                    replace_or_reactivate(work, pipeline, current_three_rule_plan())
                return result

            pipeline._request = rotate_after_request
            with pytest.raises(RuntimeError, match="reference dependencies changed"):
                await pipeline.refresh_references(NOW.date())
            assert pipeline._reference_key is None

    asyncio.run(scenario())


def test_deadline_does_not_admit_captured_plan_reactivated_during_reference_await(
    tmp_path,
    monkeypatch,
):
    async def scenario():
        with current_pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            sdk.stock_symbols = (current_three_rule_plan().symbol,)
            admitted = record_deadline_admission(pipeline)
            original = pipeline.refresh_references

            async def reactivate_before_refresh(day):
                replace_or_reactivate(work, pipeline, current_three_rule_plan())
                await original(day)

            pipeline.refresh_references = reactivate_before_refresh
            with pytest.raises(RuntimeError, match="reference dependencies changed"):
                await pipeline.run_deadline(_deadline())
            assert not admitted
            assert pipeline._deadline_plans is None

    asyncio.run(scenario())


def test_deadline_does_not_admit_captured_plan_reactivated_during_recovery_await(
    tmp_path,
    monkeypatch,
):
    async def scenario():
        with current_pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            sdk.stock_symbols = (current_three_rule_plan().symbol,)
            admitted = record_deadline_admission(pipeline)

            async def reactivate_during_recovery(*, before_date):
                assert before_date == NOW.date()
                replace_or_reactivate(work, pipeline, current_three_rule_plan())

            pipeline._recover_historical_closes = reactivate_during_recovery
            with pytest.raises(RuntimeError, match="reference dependencies changed"):
                await pipeline.run_deadline(_deadline())
            assert not admitted
            assert pipeline._deadline_plans is None

    asyncio.run(scenario())


def test_metadata_only_refresh_during_request_preserves_dependency_identity(tmp_path, monkeypatch):
    async def scenario():
        with current_pipeline(tmp_path, monkeypatch) as (pipeline, _, directory, _, _):
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
        with current_pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            sdk.stock_symbols = (current_three_rule_plan().symbol,)
            original = pipeline._request
            changed = False

            async def deactivate_after_request(operation, call, key):
                nonlocal changed
                result = await original(operation, call, key)
                if not changed:
                    changed = True
                    with work() as transaction:
                        transaction.plans.deactivate(
                            current_three_rule_plan().symbol, expected_revision=1
                        )
                        transaction.commit()
                return result

            pipeline._request = deactivate_after_request
            with pytest.raises(RuntimeError, match="reference dependencies changed"):
                await pipeline.refresh_references(NOW.date())
            assert pipeline._reference_key is None

    asyncio.run(scenario())


def test_semantic_revision_change_after_final_request_cannot_install_reference_key(
    tmp_path,
    monkeypatch,
):
    async def scenario():
        with current_pipeline(tmp_path, monkeypatch) as (pipeline, _, directory, _, _):
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
        with current_pipeline(tmp_path, monkeypatch, with_plan=True) as (
            pipeline,
            sdk,
            directory,
            _,
            _,
        ):
            sdk.stock_symbols = (current_three_rule_plan().symbol,)
            await pipeline.refresh_references(NOW.date())
            calls_before = tuple(sdk.calls)
            _replace_stock_contract(directory)
            admitted = record_deadline_admission(pipeline)
            await pipeline.run_deadline(_deadline())
            assert tuple(sdk.calls) == calls_before
            assert len(admitted) == 1

    asyncio.run(scenario())
