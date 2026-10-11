"""Existing HTTP result routes expose an owned, bounded, causal loop report."""

import asyncio
from datetime import datetime, timedelta
from threading import Event, get_ident

import pytest
from fastapi.testclient import TestClient
from tests.integration.test_monitor_loop_publication import publication_case
from tests.integration.test_monitor_loop_submission import Coordinator

import trade_plan_monitor.backtest.composition as composition
from trade_plan_monitor.backtest.dataset_service import BacktestDatasetService
from trade_plan_monitor.backtest.jobs.models import BacktestRunJobResult, MonitorLoopJobRequest
from trade_plan_monitor.backtest.jobs.repository import BacktestJobRepository
from trade_plan_monitor.backtest.loop_publication import stage_loop_report
from trade_plan_monitor.backtest.market_store import BacktestMarketStore
from trade_plan_monitor.backtest.pagination import HmacCursorSigner
from trade_plan_monitor.backtest.result_service import BacktestResultService
from trade_plan_monitor.backtest.time import SHANGHAI
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.backtest_pagination import BacktestApiCursorSigner
from trade_plan_monitor.web.routers import backtest_exports, backtest_results, backtest_runs


def test_scheduled_prepared_command_requires_explicit_schema_discriminator():
    from pydantic import ValidationError
    from tests.integration.test_monitor_loop_submission import payload

    from trade_plan_monitor.web.backtest_schemas import ScheduledPreparedBacktestRunCommand

    class Prepared:
        preparation_id = "synthetic-collection"
        manifest_hash = "a" * 64

    with pytest.raises(ValidationError):
        ScheduledPreparedBacktestRunCommand.model_validate(payload(Prepared()))
    command = ScheduledPreparedBacktestRunCommand.model_validate(
        payload(Prepared(), schemaVersion="prepared-loop-plan-v2"),
    )
    assert command.schema_version == "prepared-loop-plan-v2"


@pytest.fixture(scope="module")
def scheduled_published(tmp_path_factory):
    from tests.integration.test_monitor_loop_input_store import scheduled_frozen_case
    from tests.unit.test_monitor_loop_schedule import at

    from trade_plan_monitor.backtest.control import CancellationToken
    from trade_plan_monitor.backtest.loop_replay import run_frozen_loop
    from trade_plan_monitor.backtest.results import BacktestResultStore

    root = tmp_path_factory.mktemp("scheduled-result-api")
    _, market, prepared, run_input, dataset = scheduled_frozen_case(root)
    repository = BacktestJobRepository(root / "results.sqlite3", clock=lambda: at(26, 16))
    store = BacktestResultStore(repository.database_path)
    reference = store.record_loop_input(
        prepared=prepared,
        run_input=run_input,
        dataset=dataset,
        market_source=market,
    )
    repository.submit(MonitorLoopJobRequest(input_reference=reference), "scheduled")
    claim = repository.claim_next()
    report = run_frozen_loop(
        store, reference, cancellation_token=CancellationToken(), progress_callback=lambda _: None
    )
    assert repository.complete(
        claim.job_id,
        claim.claim_token.get_secret_value(),
        BacktestRunJobResult(run_id=reference.run_id, report_hash=report.report_hash, reused=False),
    )
    signer = HmacCursorSigner(b"x" * 32)
    service = composition._ProductionBacktestService(
        plan_snapshot_reader=None,
        market_store=market,
        repository=repository,
        result_store=store,
        dataset_service=BacktestDatasetService(store=market, cursor_signer=signer),
        result_service=BacktestResultService(store=store, cursor_signer=signer),
        coordinator=Coordinator(),
        result_cursor_signer=signer,
        job_cursor_signer=BacktestApiCursorSigner(b"x" * 32),
    )
    app = create_app()
    app.state.backtest_read_service = service
    app.state.backtest_operation_service = service
    for router in (backtest_runs.router, backtest_results.router, backtest_exports.router):
        app.include_router(router)
    client = TestClient(app)
    try:
        yield client, service, store, reference, report
    finally:
        client.close()
        asyncio.run(service.stop_metadata())


def test_scheduled_result_has_exact_bounded_provenance_and_native_report_header(
    scheduled_published,
):
    client, _, store, reference, report = scheduled_published
    stored = store.get_loop_input(reference)
    response = client.get(f"/api/v1/backtest-runs/{reference.run_id}")
    assert response.status_code == 200 and len(response.content) <= 4 * 1024 * 1024
    value = response.json()
    assert value["schemaVersion"] == "monitor-loop-result-v2"
    assert "frozenPlan" not in value and value["planVersionId"] is None
    expected = report.model_dump(mode="json", exclude={"schedule", "schema_version"})
    expected["report_schema_version"] = "backtest-report-v5"
    assert value["report"] == expected
    assert value["openingAccount"] == stored.run_input.initial_account.model_dump(mode="json")
    provenance = value["provenance"]
    assert (
        provenance["preparationId"],
        provenance["manifestHash"],
        provenance["inputHash"],
        provenance["revision"],
    ) == (
        stored.prepared.preparation_id,
        stored.prepared.manifest_hash,
        reference.input_hash,
        stored.prepared.revision,
    )
    assert len(provenance["sources"]) == len(value["versions"]) == 2
    for item, source, version in zip(
        stored.prepared.items, provenance["sources"], value["versions"], strict=True
    ):
        assert source["sourceId"] == item.source.source_id
        assert source["sourceHash"] == item.source.binding_hash
        assert source["sourceRevision"] == item.source_revision
        assert source["candidateRevision"] == item.extraction_candidate_revision
        assert source["candidateHash"] == item.extraction_candidate_hash
        assert source["evidenceHash"] == item.extraction_evidence_hash
        assert source["baseHash"] == item.base_hash
        assert version["versionId"] == item.version.version_id
        assert "snapshot" not in version and item.source.text not in response.text
    summary = client.get("/api/v1/backtest-runs").json()["items"][0]
    assert summary["schemaVersion"] == "monitor-loop-result-v2"
    assert summary["runId"] == reference.run_id
    assert "report" not in summary and "versions" not in summary


def test_scheduled_event_pages_bind_each_event_to_its_historical_authority(scheduled_published):
    client, _, _, reference, report = scheduled_published
    actual, cursor = [], None
    while True:
        params = {"kind": "DECISION", "limit": 100}
        if cursor:
            params["cursor"] = cursor
        response = client.get(f"/api/v1/backtest-runs/{reference.run_id}/details", params=params)
        assert response.status_code == 200 and len(response.content) <= 4 * 1024 * 1024
        page = response.json()
        for item in page["items"]:
            assert item["schemaVersion"] == "monitor-loop-event-v2"
            event = item["event"]
            selected = report.schedule.select(datetime.fromisoformat(event["at"]))
            assert event["authority_id"] == (None if selected is None else selected.authority_id)
            assert event["version_id"] == (
                None if selected is None else selected.version.version_id
            )
            actual.append(event)
        if not page["hasMore"]:
            break
        cursor = page["nextCursor"]
    assert [event["sequence"] for event in actual] == list(range(1, report.event_count + 1))
    assert any(event["payload"]["kind"] == "REPLACED" for event in actual)


def test_scheduled_event_projection_rejects_foreign_identity_and_changed_hash(scheduled_published):
    from pydantic import ValidationError

    from trade_plan_monitor.web.backtest_schemas import BacktestScheduledEventView

    client, _, _, reference, _ = scheduled_published
    response = client.get(
        f"/api/v1/backtest-runs/{reference.run_id}/details", params={"kind": "DECISION", "limit": 1}
    )
    assert response.status_code == 200
    original = response.json()["items"][0]
    for changed in (
        original | {"detailId": "foreign"},
        original | {"event": original["event"] | {"event_id": "f" * 64}},
        original | {"event": original["event"] | {"authority_id": "f" * 64}},
    ):
        with pytest.raises(ValidationError):
            BacktestScheduledEventView.model_validate(changed)


def test_scheduled_pin_replays_and_exports_reject_before_stream_headers(scheduled_published):
    client, _, _, reference, _ = scheduled_published
    route = f"/api/v1/backtest-runs/{reference.run_id}"
    before = client.get(route).json()
    kwargs = {
        "json": {"pinned": True, "expectedRevision": before["revision"]},
        "headers": {"Idempotency-Key": "scheduled-pin"},
    }
    first = client.patch(route, **kwargs)
    assert first.status_code == 200
    assert client.patch(route, **kwargs).json() == first.json()
    assert first.json()["pinned"] is True
    assert first.json()["report"] == before["report"]
    for kind in ("SUMMARY_JSON", "FILLS_CSV"):
        rejected = client.get(route + "/exports/" + kind)
        assert rejected.status_code == 409
        assert "content-disposition" not in rejected.headers
        assert "x-export-schema-version" not in rejected.headers


@pytest.fixture
def published(tmp_path):
    store, reference, report, events = publication_case(tmp_path)
    repository = BacktestJobRepository(store.database_path)
    repository.submit(MonitorLoopJobRequest(input_reference=reference), "one")
    claim = repository.claim_next()
    stage_loop_report(store, reference=reference, report=report, events=events)
    assert repository.complete(
        claim.job_id,
        claim.claim_token.get_secret_value(),
        BacktestRunJobResult(run_id=reference.run_id, report_hash=report.report_hash, reused=False),
    )
    signer = HmacCursorSigner(b"x" * 32)
    market = BacktestMarketStore(tmp_path / "unrelated-market.sqlite3")
    service = composition._ProductionBacktestService(
        plan_snapshot_reader=None,
        market_store=market,
        repository=repository,
        result_store=store,
        dataset_service=BacktestDatasetService(store=market, cursor_signer=signer),
        result_service=BacktestResultService(store=store, cursor_signer=signer),
        coordinator=Coordinator(),
        result_cursor_signer=signer,
        job_cursor_signer=BacktestApiCursorSigner(b"x" * 32),
    )
    app = create_app()
    app.state.backtest_read_service = service
    app.state.backtest_operation_service = service
    for router in (backtest_runs.router, backtest_results.router, backtest_exports.router):
        app.include_router(router)
    client = TestClient(app)
    try:
        yield client, service, store, reference, report, events
    finally:
        client.close()
        asyncio.run(service.stop_metadata())


def test_existing_run_routes_identify_loop_metrics_cutoff_and_frozen_provenance(published):
    client, _, store, reference, report, _ = published
    stored = store.get_loop_input(reference)
    response = client.get(f"/api/v1/backtest-runs/{reference.run_id}")
    assert response.status_code == 200
    value = response.json()
    assert value["schemaVersion"] == "monitor-loop-result-v1"
    assert value["planVersionId"] is None
    assert value["frozenPlan"] == stored.prepared.version.model_dump(mode="json")
    assert value["openingAccount"] == stored.run_input.initial_account.model_dump(mode="json")
    assert value["report"] == report.model_dump(mode="json")
    assert value["metrics"] == report.metrics.model_dump(mode="json")
    assert value["report"]["boundary"]["evidence_cutoff"] == "2026-08-24T09:43:12+08:00"
    assert value["provenance"]["preparationId"] == stored.prepared.preparation_id
    assert value["provenance"]["inputHash"] == reference.input_hash
    assert value["fillCount"] == 1
    assert "initialCashFen" not in value
    page = client.get("/api/v1/backtest-runs", params={"limit": 1}).json()
    assert len(page["items"]) == 1
    assert page["items"][0]["schemaVersion"] == "monitor-loop-result-v1"
    assert page["items"][0]["runId"] == reference.run_id
    assert "frozenPlan" not in page["items"][0]


def test_causal_event_pages_preserve_exact_hashes_sequence_and_cursor(published):
    client, _, _, reference, _, events = published
    actual, cursor, anchors = [], None, set()
    while True:
        params = {"kind": "DECISION", "limit": 3}
        if cursor:
            params["cursor"] = cursor
        response = client.get(f"/api/v1/backtest-runs/{reference.run_id}/details", params=params)
        assert response.status_code == 200
        page = response.json()
        assert page["availability"] == "AVAILABLE"
        assert len(page["items"]) <= 3
        anchors.add(page["highWatermark"])
        for item in page["items"]:
            assert item["schemaVersion"] == "monitor-loop-event-v1"
            actual.append(item["event"])
        if not page["hasMore"]:
            assert page["nextCursor"] is None
            break
        cursor = page["nextCursor"]
    assert len(anchors) == 1
    assert actual == [event.model_dump(mode="json") for event in events]
    assert {item["payload"]["kind"] for item in actual} >= {
        "EVALUATED",
        "REMINDED",
        "REQUESTED",
        "EXECUTED",
        "STATE",
        "VALUATION",
    }


def test_fill_receipts_and_absent_legacy_equity_are_honest(published):
    client, _, _, reference, _, events = published
    response = client.get(f"/api/v1/backtest-runs/{reference.run_id}/fills")
    assert response.status_code == 200
    item = response.json()["items"][0]
    executed = next(event for event in events if event.payload.kind == "EXECUTED")
    assert item["schemaVersion"] == "monitor-loop-fill-v1"
    assert item["eventId"] == executed.event_id
    assert item["receipt"] == executed.payload.attempt.receipt.model_dump(mode="json")
    equity = client.get(f"/api/v1/backtest-runs/{reference.run_id}/equity-series")
    assert equity.status_code == 200
    assert equity.json() == {"availability": "NOT_RECORDED", "items": []}


@pytest.mark.parametrize("kind", ["SUMMARY_JSON", "FILLS_CSV"])
def test_unsupported_loop_exports_reject_before_stream_headers(published, kind):
    client, _, _, reference, _, _ = published
    response = client.get(f"/api/v1/backtest-runs/{reference.run_id}/exports/{kind}")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"
    assert "content-disposition" not in response.headers
    assert "x-export-schema-version" not in response.headers


def test_typed_projection_runs_on_existing_owned_thread(published, monkeypatch):
    _, service, _, reference, _, _ = published
    seen = []
    for name in ("_fill_view", "_detail_view"):
        original = getattr(composition, name)

        def project(value, original=original):
            seen.append(get_ident())
            return original(value)

        monkeypatch.setattr(composition, name, project)

    async def query():
        from trade_plan_monitor.web.backtest_schemas import BacktestDetailFiltersView

        owner = get_ident()
        await service.list_fills(run_id=reference.run_id, limit=1, cursor=None)
        await service.list_details(
            run_id=reference.run_id,
            filters=BacktestDetailFiltersView.model_validate({"kind": "DECISION"}),
            limit=3,
            cursor=None,
        )
        assert seen and owner not in seen
        assert len(set(seen)) == 1

    asyncio.run(query())


def test_expired_events_keep_typed_header_and_provenance(published):
    client, _, store, reference, report, _ = published
    result = store.prune_result_rows(
        as_of=datetime.now(SHANGHAI) + timedelta(days=91), remaining_budget=1000
    )
    assert result.deleted_count > 0
    response = client.get(
        f"/api/v1/backtest-runs/{reference.run_id}/details", params={"kind": "DECISION"}
    )
    assert response.status_code == 200
    assert response.json()["availability"] == "EXPIRED"
    assert response.json()["items"] == []
    header = client.get(f"/api/v1/backtest-runs/{reference.run_id}")
    assert header.status_code == 200
    assert header.json()["report"] == report.model_dump(mode="json")
    assert header.json()["availability"]["decisionDetails"] == "EXPIRED"


def test_native_event_identity_and_hash_are_revalidated(published):
    _, service, _, reference, _, _ = published
    from pydantic import ValidationError

    from trade_plan_monitor.web.backtest_schemas import (
        BacktestDetailFiltersView,
        BacktestLoopEventView,
    )

    async def read():
        return await service.list_details(
            run_id=reference.run_id,
            filters=BacktestDetailFiltersView.model_validate({"kind": "DECISION"}),
            limit=1,
            cursor=None,
        )

    value = asyncio.run(read()).items[0].canonical_payload()
    with pytest.raises(ValidationError):
        BacktestLoopEventView.model_validate(value | {"detailId": "foreign"})
    changed = value | {"event": value["event"] | {"event_id": "f" * 64}}
    with pytest.raises(ValidationError):
        BacktestLoopEventView.model_validate(changed)


def test_loop_pin_replay_preserves_native_header(published):
    client, _, _, reference, report, _ = published
    before = client.get(f"/api/v1/backtest-runs/{reference.run_id}").json()
    kwargs = {
        "json": {"pinned": True, "expectedRevision": before["revision"]},
        "headers": {"Idempotency-Key": "loop-pin-one"},
    }
    first = client.patch(f"/api/v1/backtest-runs/{reference.run_id}", **kwargs)
    replay = client.patch(f"/api/v1/backtest-runs/{reference.run_id}", **kwargs)
    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    assert first.json()["pinned"] is True
    assert first.json()["report"] == report.model_dump(mode="json")


@pytest.mark.parametrize("fact", ["zero", "unknown"])
def test_loop_summary_preserves_zero_and_unknown_cash(published, tmp_path, fact):
    from tests.integration.test_monitor_loop_cycle import cycle_input
    from tests.integration.test_monitor_loop_valuation import report_case
    from tests.unit.test_monitor_loop_input import account

    from trade_plan_monitor.backtest.loop_input import (
        LoopResponsePolicy,
        UnknownLoopCash,
    )
    from trade_plan_monitor.web.backtest_schemas import BacktestLoopRunSummaryView

    client, _, _, reference, _, _ = published
    opening = account(lots=())
    if fact == "unknown":
        opening = opening.model_copy(update={"cash": UnknownLoopCash()})
    value = cycle_input(initial_account=opening, response=LoopResponsePolicy(mode="OBSERVE_ONLY"))
    report, _ = report_case(tmp_path / "unknown-private", value)
    summary = client.get("/api/v1/backtest-runs").json()["items"][0]
    result = BacktestLoopRunSummaryView.model_validate(
        summary | {"metrics": report.metrics.model_dump(mode="json"), "fillCount": 0}
    )
    expected = 0 if fact == "zero" else None
    assert result.metrics.initial_equity_fen == expected
    assert result.metrics.final_equity_fen == expected
    assert result.metrics.interval_return is None


def test_projection_backpressure_keeps_event_loop_responsive(published, monkeypatch):
    from trade_plan_monitor.web.backtest_schemas import BacktestDetailFiltersView
    from trade_plan_monitor.web.errors import ApiError
    from trade_plan_monitor.web.schemas import ApiErrorCode

    _, service, _, reference, _, _ = published
    entered, release = Event(), Event()
    original = composition._detail_view

    def held(value):
        entered.set()
        assert release.wait(5)
        return original(value)

    monkeypatch.setattr(composition, "_detail_view", held)

    async def query():
        task = asyncio.create_task(
            service.list_details(
                run_id=reference.run_id,
                filters=BacktestDetailFiltersView.model_validate({"kind": "DECISION"}),
                limit=1,
                cursor=None,
            )
        )
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            assert service.outstanding_work == 1
            for _ in range(10):
                await asyncio.sleep(0)
            with pytest.raises(ApiError) as failure:
                await service.get_job(job_id="missing")
            assert failure.value.code is ApiErrorCode.SERVICE_UNAVAILABLE
            assert failure.value.retry_after_seconds == 1
        finally:
            release.set()
            await task
        assert service.outstanding_work == 0

    asyncio.run(query())
