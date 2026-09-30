"""Offline regression coverage for the diagnostic gaps observed in R17."""

import asyncio
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
import requests
from sqlalchemy.exc import SQLAlchemyError
from tests.integration.test_ai_provider_contract import _config, _secret_store
from tests.integration.test_certified_production_runtime import NOW, Clock
from tests.unit.test_ai_plan_extraction_v4 import _extract, _valid_output

from trade_plan_monitor.ai.extraction import extract_plan
from trade_plan_monitor.ai.openai_compatible import OpenAICompatibleProvider
from trade_plan_monitor.market_data.models import ProviderCapabilities, ProviderCapabilityStatus
from trade_plan_monitor.market_data.tushare import TushareMarketDataProvider
from trade_plan_monitor.runtime.production import (
    ProductionMonitorPipeline,
    ReferenceDataUnavailableError,
)
from trade_plan_monitor.runtime.request_control import (
    RequestControlError,
    RequestControlErrorCode,
    TushareOperation,
    create_live_tushare_request_controller,
)
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.web.monitor_composition import _ProductionRuntimeState


@pytest.mark.parametrize("field", ["clause_id", "start", "end", "excerpt"])
def test_mapping_diagnostic_identifies_mismatched_source_field_without_content(field):
    payload = _valid_output()
    clause = payload["source_clauses"][0]
    clause[field] = (
        clause[field] + 1
        if field in {"start", "end"}
        else ("clause-0000000000000000" if field == "clause_id" else "SECRET-untrusted-excerpt")
    )
    result = _extract(payload)
    assert result.draft is None
    assert result.mapping is None
    assert result.diagnostic.stage == "mapping"
    assert result.diagnostic.path == f"source_clauses[0].{field}"
    assert "SECRET" not in result.model_dump_json()


@pytest.mark.parametrize(
    "field,value", [("unit", "NONE"), ("value", 200), ("path", "SECRET-unknown-path")]
)
def test_mapping_diagnostic_identifies_invalid_binding_without_echoing_path(field, value):
    payload = _valid_output()
    clause = payload["source_clauses"][0]
    clause.update(disposition="MAPPED", paths=["rules[0].action.quantity"])
    binding = dict(
        path="rules[0].action.quantity",
        value=100,
        unit="SHARES",
        origin="SOURCE",
        clause_ids=[clause["clause_id"]],
        binding_kind="VALUE",
    )
    binding[field] = value
    payload["field_bindings"] = [binding]
    result = _extract(payload)
    assert result.draft is None
    assert result.diagnostic.stage == "mapping"
    assert result.diagnostic.path == f"field_bindings[0].{field}"
    assert "SECRET" not in result.model_dump_json()


def test_structure_binding_to_scalar_is_a_mapping_failure():
    payload = _valid_output()
    clause = payload["source_clauses"][0]
    clause.update(disposition="MAPPED", paths=["rules[0].action.quantity"])
    payload["field_bindings"] = [
        dict(
            path="rules[0].action.quantity",
            value="ALL",
            unit="NONE",
            origin="SOURCE",
            clause_ids=[clause["clause_id"]],
            binding_kind="STRUCTURE",
        )
    ]
    result = _extract(payload)
    assert result.status.value == "INVALID_OUTPUT"
    assert result.diagnostic.path == "field_bindings[0].path"


def test_missing_current_calendar_has_a_distinct_local_category():
    class Pipeline(ProductionMonitorPipeline):
        def __init__(self):
            self.reference_stage = TushareOperation.TRADING_CALENDAR
            self._status_progress_owner = None

        def active_plans(self, trade_date):
            return ()

        async def _request(self, operation, call, key):
            return []

    with pytest.raises(RuntimeError) as captured:
        asyncio.run(Pipeline().refresh_references(NOW.date()))
    assert isinstance(captured.value, ReferenceDataUnavailableError)


@pytest.mark.parametrize("code", list(RequestControlErrorCode))
def test_reference_failure_retains_closed_category_and_recovery_clears_it(tmp_path, code, caplog):
    retry_at = NOW + timedelta(seconds=30)

    class Pipeline:
        reference_stage = TushareOperation.TRADING_CALENDAR
        _stock_semantics = object()
        failing = True

        def recovery_issues(self):
            return ()

        async def refresh_references(self, trade_date):
            if self.failing:
                raise RequestControlError(
                    code, self.reference_stage, attempts=1, next_retry_at=retry_at
                )

    engine = create_sqlite_engine(tmp_path / "monitor.sqlite3")
    controller = create_live_tushare_request_controller(clock=Clock())
    state = _ProductionRuntimeState(
        config_path=tmp_path / "unused.yaml",
        database_path=tmp_path / "monitor.sqlite3",
        engine=engine,
        session_factory=create_session_factory(engine),
        clock=Clock(),
        request_controller=controller,
    )
    pipeline = Pipeline()
    state._pipeline = pipeline
    state._capabilities = ProviderCapabilities(trading_calendar=ProviderCapabilityStatus.READY)

    async def scenario():
        with pytest.raises(RequestControlError):
            await state.refresh_references(NOW.date())
        health = next(
            p for p in state.health_details().providers if p.capability == "trading_calendar"
        )
        assert health.error_code == f"REFERENCE_{code.value}"
        assert health.status == ProviderCapabilityStatus.ERROR
        assert health.next_retry_at == retry_at
        assert f"REFERENCE_{code.value}" in caplog.text
        pipeline.failing = False
        await state.refresh_references(NOW.date())
        health = next(
            p for p in state.health_details().providers if p.capability == "trading_calendar"
        )
        assert health.error_code is None
        assert health.next_retry_at is None
        assert health.status == ProviderCapabilityStatus.READY

    try:
        asyncio.run(scenario())
    finally:
        controller.close()
        engine.dispose()


def test_missing_stock_binding_skips_reference_refresh_without_stage_errors(tmp_path):
    refreshed_dates = []
    observed_failures = []

    class Pipeline:
        reference_stage = TushareOperation.TRADING_CALENDAR
        _stock_semantics = None

        def recovery_issues(self):
            return ()

        async def refresh_references(self, trade_date):
            refreshed_dates.append(trade_date)
            raise AssertionError("unbound stock references must not refresh")

    engine = create_sqlite_engine(tmp_path / "monitor.sqlite3")
    controller = create_live_tushare_request_controller(clock=Clock())
    state = _ProductionRuntimeState(
        config_path=tmp_path / "unused.yaml",
        database_path=tmp_path / "monitor.sqlite3",
        engine=engine,
        session_factory=create_session_factory(engine),
        clock=Clock(),
        request_controller=controller,
        on_reference_failure=observed_failures.append,
    )
    state._pipeline = Pipeline()
    try:
        asyncio.run(state.refresh_references(NOW.date()))
        assert refreshed_dates == []
        assert state._stage_errors == {}
        assert state._stage_retry_at == {}
        assert observed_failures == []
    finally:
        controller.close()
        engine.dispose()


def test_literal_timeout_stays_one_attempt_without_exposing_provider_details():
    config = _config(
        max_retries=0,
        timeout_seconds=30,
        prompt_version="plan-extract-v4",
        max_input_chars=19_000,
        max_output_tokens=4096,
    )
    calls = []

    def handler(request):
        calls.append(request.method)
        raise httpx.ReadTimeout("SECRET-provider-detail", request=request)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(client=client, secret_store=_secret_store(config))
            return await extract_plan(
                request_id=uuid4(), source_text="离线原文超时测试", config=config, provider=provider
            )

    result = asyncio.run(scenario())
    assert result.status.value == "PROVIDER_ERROR"
    assert result.diagnostic.stage == "provider"
    assert result.diagnostic.provider_error_code == "TIMEOUT"
    assert result.diagnostic.attempts == 1
    assert result.draft is None and result.usage is None
    assert calls == ["POST"]
    assert "SECRET" not in result.model_dump_json()


@pytest.mark.parametrize(
    "failure,expected",
    [
        (ReferenceDataUnavailableError("SECRET-reference-detail"), "REFERENCE_DATA_UNAVAILABLE"),
        (SQLAlchemyError("SECRET-database-detail"), "REFERENCE_STORAGE_ERROR"),
        (RuntimeError("SECRET-unexpected-detail"), "REFERENCE_REFRESH_FAILED"),
    ],
)
def test_reference_diagnostic_never_logs_untrusted_exception(tmp_path, caplog, failure, expected):
    observed_failures: list[str] = []
    class Pipeline:
        reference_stage = TushareOperation.TRADING_CALENDAR
        _stock_semantics = object()

        def recovery_issues(self):
            return ()

        async def refresh_references(self, trade_date):
            raise failure

    engine = create_sqlite_engine(tmp_path / "monitor.sqlite3")
    controller = create_live_tushare_request_controller(clock=Clock())
    state = _ProductionRuntimeState(
        config_path=tmp_path / "unused.yaml",
        database_path=tmp_path / "monitor.sqlite3",
        engine=engine,
        session_factory=create_session_factory(engine),
        clock=Clock(),
        request_controller=controller,
        on_reference_failure=observed_failures.append,
    )
    state._pipeline = Pipeline()
    try:
        with pytest.raises(type(failure)):
            asyncio.run(state.refresh_references(NOW.date()))
        health = next(
            p for p in state.health_details().providers if p.capability == "trading_calendar"
        )
        assert health.error_code == expected
        assert expected in caplog.text
        assert "SECRET" not in caplog.text
        assert observed_failures == [expected]
    finally:
        controller.close()
        engine.dispose()


def test_calendar_transport_timeout_reaches_reference_timeout_category() -> None:
    class Client:
        def trade_cal(self, **_kwargs):
            raise requests.Timeout("SECRET transport detail")

    provider = TushareMarketDataProvider(
        Client(),
        now=Clock().now,
        is_open_on=lambda _date: True,
    )
    controller = create_live_tushare_request_controller(clock=Clock())

    async def scenario() -> RequestControlError:
        with pytest.raises(RequestControlError) as caught:
            await controller.execute(
                TushareOperation.TRADING_CALENDAR,
                lambda: provider.trading_calendar(NOW.date(), NOW.date()),
                work_key="calendar:SSE:r21-offline",
            )
        return caught.value

    try:
        result = asyncio.run(scenario())
    finally:
        controller.close()

    assert result.code is RequestControlErrorCode.TIMEOUT
    assert result.attempts == 1
    assert "SECRET" not in str(result)
