"""Current public diagnostics never rewrite original selection/input codecs.

Real production lifecycle/composition and result-owned copies use temporary
stores. No source authority, current receipt or provider response is mocked.
"""

import json
import sqlite3
from contextlib import closing
from datetime import date, datetime
from functools import partial
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from tests.integration.test_current_plan_api import (
    coverage_review_payload,
    post,
    simple_plan,
)
from tests.integration.test_market_linkage_review import source_mapping
from tests.integration.test_monitor_loop_input_store import frozen_case
from tests.integration.test_web_api import _FakeLifecycle
from tests.unit.test_workbench_selection_context import context

from trade_plan_monitor.backtest.composition import create_backtest_composition_factory
from trade_plan_monitor.backtest.jobs.repository import BacktestJobRepository
from trade_plan_monitor.backtest.loop_input import decode_monitor_loop_input_json
from trade_plan_monitor.backtest.loop_input_store import StoredLoopInput
from trade_plan_monitor.backtest.preparation_store import PreparationStore
from trade_plan_monitor.backtest.results import BacktestResultStore
from trade_plan_monitor.backtest.workbench_selection import (
    WorkbenchPlanSelection,
    WorkbenchSelectionCommand,
    WorkbenchSelectionStore,
)
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_json
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft
from trade_plan_monitor.state.source_coverage_store import SourceCoverageStore
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle

SH = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 9, 22, 10, tzinfo=SH)


def _selection_rows(path):
    with closing(sqlite3.connect(path)) as connection:
        return {table: connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                for table in ("backtest_plan_selection", "backtest_preparation_idempotency")}


def _no_job(path, key):
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("SELECT count(*) FROM backtest_job").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM backtest_job_idempotency "
                                  "WHERE idempotency_key=?", (key,)).fetchone() == (0,)


def test_actual_selection_receipt_survives_current_source_drift_but_new_intents_do_not(tmp_path):
    lifecycle = PersistentPlanWebLifecycle(database_path=tmp_path / "workbench.sqlite3",
                                           clock=lambda: NOW)
    preparation_path, result_path = tmp_path / "preparation.sqlite3", tmp_path / "result.sqlite3"
    factory = create_backtest_composition_factory(
        config_path=tmp_path / "absent.yaml", plan_snapshot_reader=lifecycle,
        market_database=tmp_path / "market.sqlite3", results_database=result_path,
        preparation_database=preparation_path, cursor_key_path=tmp_path / "cursor.key")
    app = create_app(runtime_factory=lambda: _FakeLifecycle(events=[]),
                     plan_lifecycle_factory=lambda: lifecycle, backtest_lifecycle_factory=factory)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        draft = UnifiedPlanDraft.from_executable(simple_plan())
        source, mapping = source_mapping(draft)
        saved = post(client, "plan-drafts", {"planJson": daily_draft_json(draft),
            "sourceText": source, "dailyMapping": mapping.model_dump(mode="json"),
            "expectedRevision": 0})
        reviewed = post(client, "plan-review-confirmations", coverage_review_payload(client, saved))
        original = client.portal.call(partial(lifecycle.get_reviewed_backtest_plan,
                                              version_id=saved["id"]))
        assert str(original.reference.review_id) == reviewed["reviewId"]
        research = context().model_copy(update={"effective_trade_date": date(2026, 9, 23),
            "available_at": datetime(2026, 9, 23, 9, 30, tzinfo=SH), "information_cutoff": NOW})
        command = WorkbenchSelectionCommand(schema_version="workbench-loop-selection-v1",
                                             plan=original.reference, context=research)
        body = command.model_dump(mode="json", by_alias=True)
        headers = {"Origin": "http://127.0.0.1:8765", "Idempotency-Key": "original-selection"}
        created = client.post("/api/v1/backtest-plan-selections", json=body, headers=headers)
        assert created.status_code == 201, created.text
        frozen = created.json()
        before = _selection_rows(preparation_path)
        encoded = before["backtest_plan_selection"][0][1]
        stored = WorkbenchSelectionStore(PreparationStore(preparation_path))
        selected = stored.get(frozen["selectionId"])
        assert selected.model_dump_json() == encoded
        assert selected.reviewed == original and selected.manifest_hash == frozen["selectionHash"]
        assert '"sourceCoverage"' not in encoded and '"coverage_complete"' not in encoded

        with lifecycle._unit_of_work() as work:
            store = SourceCoverageStore(work.daily.session)
            old = store.latest(saved["id"])
            store.append(saved["id"], old.assessment, inputs=old.inputs,
                expected_revision=old.revision, command_id="selection-new-source-bundle", now=NOW)
            work.commit()
        diagnostic = client.get(f"/api/v1/plan-versions/{saved['id']}/source-coverage")
        assert diagnostic.status_code == 200
        assert diagnostic.json()["summary"]["coverageComplete"]
        assert not diagnostic.json()["summary"]["currentReviewBound"]
        assert client.get("/api/v1/plan-versions/" + saved["id"]).status_code == 200
        assert client.get("/api/v1/plan-versions").status_code == 200

        fetched = client.get("/api/v1/backtest-plan-selections/" + frozen["selectionId"])
        assert fetched.status_code == 200 and fetched.json() == frozen
        repeated = client.post("/api/v1/backtest-plan-selections", json=body, headers=headers)
        assert repeated.status_code == 201 and repeated.json() == frozen
        fresh = client.post("/api/v1/backtest-plan-selections", json=body,
                            headers=headers | {"Idempotency-Key": "fresh-selection"})
        assert fresh.status_code == 409, fresh.text
        assert _selection_rows(preparation_path) == before

        run = {"schemaVersion": "workbench-loop-selection-v1", "selectionId": frozen["selectionId"],
            "selectionHash": frozen["selectionHash"], "response": {"mode": "OBSERVE_ONLY"},
            "costs": {"commissionRate": "0", "minimumCommissionFen": 0, "stampDutyRate": "0",
                "transferFeeRate": "0", "buySlippageFen": 0, "sellSlippageFen": 0}}
        denied = client.post("/api/v1/backtest-runs", json=run,
                             headers=headers | {"Idempotency-Key": "fresh-run"})
        assert denied.status_code == 409, denied.text
        _no_job(result_path, "fresh-run")
        assert _selection_rows(preparation_path) == before
        assert client.get("/api/v1/plan-activation-states/" + saved["symbol"]).json()[
            "active"] is False

    restarted = WorkbenchSelectionStore(PreparationStore(preparation_path))
    assert restarted.get(frozen["selectionId"]).model_dump_json() == encoded
    assert restarted.replay(command, "original-selection").model_dump_json() == encoded
    assert _selection_rows(preparation_path) == before
    for field in ("sourceCoverage", "covered", "current", "authority_granted"):
        with pytest.raises(ValidationError):
            WorkbenchPlanSelection.model_validate_json(json.dumps(
                json.loads(encoded) | {field: True}))
    assert _selection_rows(preparation_path) == before


def test_old_result_owned_input_rejects_added_authority_flags_without_codec_fallback(tmp_path):
    preparation, market, prepared, run_input, dataset = frozen_case(tmp_path)
    BacktestJobRepository(tmp_path / "results.sqlite3")
    results = BacktestResultStore(tmp_path / "results.sqlite3")
    reference = results.record_loop_input(prepared=prepared, run_input=run_input,
                                          dataset=dataset, market_source=market)
    before = {path.name: path.read_bytes() for path in results.loop_input_store.root.iterdir()}
    input_bytes, prepared_bytes = run_input.model_dump_json(), prepared.model_dump_json()
    stored = results.get_loop_input(reference)
    stored_bytes = stored.model_dump_json()
    assert decode_monitor_loop_input_json(input_bytes) == run_input
    assert '"sourceCoverage"' not in stored_bytes
    for field in ("sourceCoverage", "covered", "current", "authority_granted"):
        for model, raw in ((type(prepared), prepared_bytes), (StoredLoopInput, stored_bytes)):
            with pytest.raises(ValidationError):
                model.model_validate_json(json.dumps(json.loads(raw) | {field: True}))
        with pytest.raises(ValidationError):
            decode_monitor_loop_input_json(json.dumps(json.loads(input_bytes) | {field: True}))
    with pytest.raises(ValidationError):
        decode_monitor_loop_input_json(json.dumps(json.loads(input_bytes) | {
            "schema_version": "workbench-loop-input-v1"}))
    assert results.get_loop_input(reference).model_dump_json() == stored_bytes
    assert prepared.model_dump_json() == prepared_bytes
    assert run_input.model_dump_json() == input_bytes
    assert {p.name: p.read_bytes() for p in results.loop_input_store.root.iterdir()} == before
    # Original prepared document and actual copied-day objects remain decodable.
    assert preparation.get(prepared.preparation_id).preparation_id == prepared.preparation_id
    with results.loop_input_store.open_dataset(reference) as reader:
        assert tuple(reader)
