"""Injected durable semantics gate real adapters before each offline SDK request."""

import asyncio
from contextlib import contextmanager
from datetime import timedelta
from uuid import uuid4

import pytest
from test_live_pipeline_acceptance import (
    ENDPOINT,
    NOW,
    ControlledClock,
    OfflineSDK,
    VirtualPace,
    _activate_plans,
    _sample_plan,
    _write_configuration_and_evidence,
)

from trade_plan_monitor.config import load_application_config
from trade_plan_monitor.live_profiles import read_stock_certification_history
from trade_plan_monitor.market_data.sessions import SourceTimeLabel
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.runtime.production import (
    ProductionMonitorPipeline,
    ProductionSemanticBindings,
    SemanticContractBinding,
)
from trade_plan_monitor.runtime.provider_contract import (
    import_index_semantic_contract,
    import_stock_semantic_contract,
)
from trade_plan_monitor.runtime.request_control import (
    RequestControlError,
    create_live_tushare_request_controller,
)
from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork


@contextmanager
def _pipeline(tmp_path, monkeypatch, *, stock=True, index=True, swapped=False, with_plan=False):
    clock = ControlledClock(NOW)
    sdk_version = ["1.4.29"]
    config_path = _write_configuration_and_evidence(
        tmp_path, observed_at=NOW - timedelta(days=30), include_index=True
    )
    directory = tmp_path / "data/live-certification"
    stock_path = directory / "stock-semantic.json"
    index_path = directory / "index-semantic.json"
    stock_record = import_stock_semantic_contract(
        directory / "tushare-stock-live.json",
        stock_path,
        now=NOW,
        endpoint_url=ENDPOINT,
        installed_sdk_version=lambda: "1.4.29",
    )
    index_record = import_index_semantic_contract(
        directory / "tushare-board-index-live.json",
        index_path,
        now=NOW,
        endpoint_url=ENDPOINT,
        installed_sdk_version=lambda: "1.4.29",
    )
    assert stock_record is not None and index_record is not None
    stock_binding = SemanticContractBinding(stock_path, stock_record.semantic_revision)
    index_binding = SemanticContractBinding(index_path, index_record.semantic_revision)
    if swapped:
        stock_binding, index_binding = index_binding, stock_binding
    if with_plan:
        _activate_plans(
            tmp_path / "monitor.sqlite3", ControlledClock(NOW.replace(hour=9)), (_sample_plan(),)
        )
    engine = create_sqlite_engine(tmp_path / "monitor.sqlite3")
    upgrade_database(engine)
    sessions = create_session_factory(engine)

    def work():
        return SqlAlchemyUnitOfWork(sessions, clock=clock.now)

    pace = VirtualPace()
    controller = create_live_tushare_request_controller(
        clock=clock, monotonic=pace.monotonic, pace_sleep=pace.sleep
    )
    sdk = OfflineSDK(clock, ())
    monkeypatch.setattr(
        "trade_plan_monitor.runtime.production.create_tushare_client", lambda config: sdk
    )
    try:
        pipeline = ProductionMonitorPipeline(
            configuration=load_application_config(config_path).tushare,
            certification_directory=directory,
            stock_certification=None,
            clock=clock,
            request_controller=controller,
            unit_of_work_factory=work,
            runtime_generation=uuid4(),
            publisher=lambda event: None,
            semantic_bindings=ProductionSemanticBindings(
                stock=stock_binding if stock else None,
                index=index_binding if index else None,
                installed_sdk_version=lambda: sdk_version[0],
            ),
        )
        yield pipeline, sdk, directory, sdk_version, work
    finally:
        controller.close()
        engine.dispose()


def _deadline():
    return MarketDeadline(
        kind=DeadlineKind.REALTIME_MINUTE,
        trade_date=NOW.date(),
        due_at=NOW,
        bar_end=NOW.replace(second=0),
    )


def test_old_evidence_allows_current_request_only_with_valid_injected_semantics(
    tmp_path, monkeypatch
):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch) as (pipeline, sdk, directory, _, work):
            assert not sdk.calls
            assert pipeline.provider._source_time_label is SourceTimeLabel.START
            original = read_stock_certification_history(
                directory / "tushare-stock-live.json", now=NOW, endpoint_url=ENDPOINT
            )
            assert original is not None and original.valid_until < NOW
            await pipeline.refresh_references(NOW.date())
            assert [name for name, _ in sdk.calls] == ["trade_cal"]
            with work() as transaction:
                days = transaction.references.list_trading_days("SSE", NOW.date(), NOW.date())
            assert len(days) == 1 and days[0].is_open

    asyncio.run(scenario())


@pytest.mark.parametrize("mutation", ["sdk", "revision", "endpoint", "corrupt"])
def test_each_physical_stock_request_rechecks_binding(tmp_path, monkeypatch, mutation):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch) as (pipeline, sdk, directory, sdk_version, _):
            await pipeline.refresh_references(NOW.date())
            if mutation == "sdk":
                sdk_version[0] = "1.4.30"
            elif mutation == "corrupt":
                (directory / "stock-semantic.json").write_text("{}")
            else:
                _replace_stock_contract(
                    directory,
                    label=SourceTimeLabel.END,
                    endpoint="https://other.example" if mutation == "endpoint" else ENDPOINT,
                )
            with pytest.raises(RequestControlError, match="trading_calendar"):
                await pipeline.refresh_references(NOW.date())
            assert [name for name, _ in sdk.calls] == ["trade_cal"]

    asyncio.run(scenario())


def _replace_stock_contract(directory, *, label=SourceTimeLabel.START, endpoint=ENDPOINT):
    from trade_plan_monitor.live_profiles import (
        create_stock_certification,
        write_live_certification,
    )
    from trade_plan_monitor.market_data.models import ProviderCapabilities, ProviderCapabilityStatus

    source = directory / "updated-source.json"
    replacement = directory / "updated-semantic.json"
    write_live_certification(
        source,
        create_stock_certification(
            observed_at=NOW - timedelta(days=1),
            endpoint_url=endpoint,
            source_time_label=label,
            capabilities=ProviderCapabilities(
                **{key: ProviderCapabilityStatus.READY for key in ProviderCapabilities.model_fields}
            ),
        ),
    )
    record = import_stock_semantic_contract(
        source, replacement, now=NOW, endpoint_url=endpoint, installed_sdk_version=lambda: "1.4.29"
    )
    assert record is not None
    replacement.replace(directory / "stock-semantic.json")


def test_metadata_refresh_does_not_invalidate_running_pipeline(tmp_path, monkeypatch):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch) as (pipeline, sdk, directory, _, _):
            await pipeline.refresh_references(NOW.date())
            _replace_stock_contract(directory)
            await pipeline.refresh_references(NOW.date())
            assert [name for name, _ in sdk.calls] == ["trade_cal", "trade_cal"]

    asyncio.run(scenario())


def test_missing_stock_binding_does_not_block_index_only_display(tmp_path, monkeypatch):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, stock=False) as (pipeline, sdk, _, _, work):
            assert await pipeline.run_deadline(_deadline()) == ()
            assert sdk.calls and all(
                name in {"idx_mins", "rt_idx_min_daily", "index_daily"} for name, _ in sdk.calls
            )
            assert any(args["ts_code"] == "399107.SZ" for _, args in sdk.calls)
            with work() as transaction:
                records = transaction.projections.list_latest_market_index_snapshots(
                    mapping_version="board-index-map-v1",
                    index_codes=(MarketIndexCode.SSE_COMPOSITE,),
                )
            assert len(records) == 1

    asyncio.run(scenario())


def test_wrong_surface_bindings_cannot_issue_requests(tmp_path, monkeypatch):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, swapped=True) as (pipeline, sdk, _, _, _):
            with pytest.raises(RequestControlError, match="trading_calendar"):
                await pipeline.refresh_references(NOW.date())
            assert await pipeline.run_deadline(_deadline()) == ()
            assert not sdk.calls

    asyncio.run(scenario())


def test_invalid_index_binding_does_not_prevent_stock_requests(tmp_path, monkeypatch):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, index=False) as (pipeline, sdk, _, _, _):
            await pipeline.refresh_references(NOW.date())
            assert [name for name, _ in sdk.calls] == ["trade_cal"]
            assert await pipeline.run_deadline(_deadline()) == ()
            assert [name for name, _ in sdk.calls] == ["trade_cal"]

    asyncio.run(scenario())


def test_index_contract_is_rechecked_between_physical_calls(tmp_path, monkeypatch):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, stock=False) as (pipeline, sdk, directory, _, _):
            original = OfflineSDK.__getattr__

            def invalidating_getattr(self, name):
                request = original(self, name)

                def call(**kwargs):
                    result = request(**kwargs)
                    (directory / "index-semantic.json").write_text("{}")
                    return result

                return call

            monkeypatch.setattr(OfflineSDK, "__getattr__", invalidating_getattr)
            assert await pipeline.run_deadline(_deadline()) == ()
            assert len(sdk.calls) == 1

    asyncio.run(scenario())


def test_index_display_remains_independently_callable_after_selected_stock_is_blocked(
    tmp_path, monkeypatch
):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, stock=False, with_plan=True) as (
            pipeline,
            sdk,
            _,
            _,
            _,
        ):
            with pytest.raises(RuntimeError, match="stock certification"):
                await pipeline.run_deadline(_deadline())
            assert not sdk.calls
            # Orchestration remains responsible for scheduling this independent work
            # after a selected stock deadline fails; this slice exposes no scheduler.
            await pipeline._refresh_dashboard_indexes(_deadline())
            assert sdk.calls and all(
                name in {"idx_mins", "rt_idx_min_daily", "index_daily"} for name, _ in sdk.calls
            )

    asyncio.run(scenario())
