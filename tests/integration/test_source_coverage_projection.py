"""Read projections and current workbench reuse require exact coverage receipts.

All application lifecycles use disposable test databases and a fake runtime.
Historical daily review remains readable; no provider or user state is accessed.
"""

from datetime import datetime, timedelta
from functools import partial
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from tests.integration.test_current_plan_api import post
from tests.integration.test_live_monitor_projection_migration import _upgrade
from tests.integration.test_source_coverage_migration import _seed_legacy
from tests.integration.test_source_coverage_review_api import _command, _proof, _save
from tests.integration.test_source_coverage_review_api import workspace as workspace
from tests.integration.test_web_api import _FakeLifecycle

from trade_plan_monitor.ai.source_coverage import assess_source_coverage
from trade_plan_monitor.backtest.workbench_selection import WorkbenchReviewedPlan
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_json
from trade_plan_monitor.state.database import create_sqlite_engine
from trade_plan_monitor.state.repositories import PlanSaveBlockedError
from trade_plan_monitor.state.source_coverage_store import SourceCoverageStore
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle, _validated_plan_state

_NOW = datetime(2026, 10, 27, 10, tzinfo=ZoneInfo("Asia/Shanghai"))


@pytest.fixture
def upgraded_legacy(tmp_path):
    path = tmp_path / "projection-old-upgraded.sqlite3"
    engine = create_sqlite_engine(path)
    try:
        _upgrade(engine, "0027_simulation_capital")
        legacy = _seed_legacy(engine, confirmed=True)
        _upgrade(engine, "0028_source_coverage")
    finally:
        engine.dispose()
    lifecycle = PersistentPlanWebLifecycle(database_path=path, clock=lambda: _NOW)
    app = create_app(runtime_factory=lambda: _FakeLifecycle(events=[]),
                     plan_lifecycle_factory=lambda: lifecycle)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        yield client, lifecycle, legacy


def _advance_coverage(lifecycle, version_id, stored):
    with lifecycle._session_factory() as session, session.begin():
        return SourceCoverageStore(session).append(version_id, stored.assessment,
            inputs=stored.inputs, expected_revision=stored.revision,
            command_id="projection-new-coverage-revision",
            now=stored.created_at + timedelta(seconds=1))


def _snapshot(lifecycle):
    tables = ("plan_source", "plan_version", "plan_review_provenance", "daily_plan_record",
              "audit_log",
              "active_plan", "source_coverage_installation", "source_coverage_cutover",
              "source_coverage_assessment", "source_coverage_input", "source_coverage_review")
    with lifecycle._session_factory() as session:
        connection = session.connection()
        return {table: tuple(sorted(tuple(row) for row in connection.exec_driver_sql(
            f"SELECT * FROM {table}"))) for table in tables}


def _assert_list_blocked(client, version_id):
    unfiltered = client.get("/api/v1/plan-versions")
    assert unfiltered.status_code == 200, unfiltered.text
    listed = next(item for item in unfiltered.json()["items"] if item["id"] == version_id)
    assert listed["canActivate"] is False
    positive = client.get("/api/v1/plan-versions", params={"canActivate": "true"})
    assert positive.status_code == 200, positive.text
    assert version_id not in {item["id"] for item in positive.json()["items"]}
    negative = client.get("/api/v1/plan-versions", params={"canActivate": "false"})
    assert negative.status_code == 200, negative.text
    assert version_id in {item["id"] for item in negative.json()["items"]}


def _read_backtest(client, version_id):
    return client.portal.call(partial(
        client.app.state.plan_operation_service.get_reviewed_backtest_plan, version_id=version_id,
    ))


def test_stale_receipt_cannot_still_project_an_activatable_detail(workspace):
    client, lifecycle = workspace
    saved = _save(client)
    stored = _proof(lifecycle, saved["id"])
    reviewed = post(client, "plan-review-confirmations", _command(saved, stored))
    assert reviewed["canActivate"] is True
    newer = _advance_coverage(lifecycle, saved["id"], stored)
    assert newer.assessment == stored.assessment and newer.revision == stored.revision + 1
    before = _snapshot(lifecycle)

    response = client.get("/api/v1/plan-versions/" + saved["id"])

    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["canActivate"] is False
    assert "SOURCE_COVERAGE_STALE" in {issue["code"] for issue in detail["validationIssues"]}
    assert detail["dailyIssues"] == []
    assert detail["reviewId"] == reviewed["reviewId"]
    assert detail["reviewEvidenceHash"] == saved["reviewEvidenceHash"]
    assert detail["planJson"] == saved["planJson"]
    _assert_list_blocked(client, saved["id"])
    assert _snapshot(lifecycle) == before


def test_upgraded_confirmed_history_stays_readable_but_is_not_currently_activatable(
    upgraded_legacy,
):
    client, lifecycle, legacy = upgraded_legacy
    with lifecycle._unit_of_work() as work:
        historical = work.plans.get_version_details(legacy.id)
        assert historical.daily_issues == ()
        assert historical.review_id == legacy.review_id
        assert historical.review_evidence_hash == legacy.snapshot.evidence_hash
        assert historical.payload_json == daily_draft_json(legacy.draft)
        assert SourceCoverageStore(work.daily.session).latest(legacy.id) is None
    before = _snapshot(lifecycle)

    response = client.get("/api/v1/plan-versions/" + legacy.id)

    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["canActivate"] is False
    assert "SOURCE_COVERAGE_REQUIRED" in {issue["code"] for issue in detail["validationIssues"]}
    assert detail["dailyIssues"] == [] and detail["obsoleteReason"] is None
    assert detail["reviewId"] == legacy.review_id
    assert detail["reviewEvidenceHash"] == legacy.snapshot.evidence_hash
    assert detail["planJson"] == daily_draft_json(legacy.draft)
    _assert_list_blocked(client, legacy.id)
    assert _snapshot(lifecycle) == before
    with lifecycle._session_factory() as session:
        assert SourceCoverageStore(session).latest(legacy.id) is None


def test_missing_current_proof_cannot_be_wrapped_as_a_reviewed_workbench_plan(upgraded_legacy):
    client, lifecycle, legacy = upgraded_legacy
    before = _snapshot(lifecycle)

    with pytest.raises(PlanSaveBlockedError):
        _read_backtest(client, legacy.id)

    assert _snapshot(lifecycle) == before


def test_complete_current_proof_without_its_receipt_cannot_be_reused_as_reviewed(upgraded_legacy):
    client, lifecycle, legacy = upgraded_legacy
    assessment = assess_source_coverage(legacy.draft, legacy.mapping, legacy.source,
                                       origin="AI_HISTORICAL")
    assert assessment.coverage_complete is True
    with lifecycle._session_factory() as session, session.begin():
        store = SourceCoverageStore(session)
        store.append(legacy.id, assessment, expected_revision=0,
                     command_id="current-assessment-without-receipt", now=_NOW)
        assert store.receipt(legacy.review_id) is None
    before = _snapshot(lifecycle)

    with pytest.raises(PlanSaveBlockedError):
        _read_backtest(client, legacy.id)

    assert _snapshot(lifecycle) == before


def test_stale_current_receipt_cannot_be_reused_as_reviewed_workbench_plan(workspace):
    client, lifecycle = workspace
    saved = _save(client)
    stored = _proof(lifecycle, saved["id"])
    reviewed = post(client, "plan-review-confirmations", _command(saved, stored))
    _advance_coverage(lifecycle, saved["id"], stored)
    before = _snapshot(lifecycle)

    with pytest.raises(PlanSaveBlockedError):
        _read_backtest(client, saved["id"])

    assert _snapshot(lifecycle) == before
    with lifecycle._session_factory() as session:
        assert SourceCoverageStore(session).receipt(reviewed["reviewId"]).coverage_revision == 1


def test_exact_current_receipt_still_allows_read_only_reviewed_workbench_reuse(workspace):
    client, lifecycle = workspace
    saved = _save(client)
    stored = _proof(lifecycle, saved["id"])
    reviewed = post(client, "plan-review-confirmations", _command(saved, stored))
    before = _snapshot(lifecycle)

    selected = _read_backtest(client, saved["id"])

    assert isinstance(selected, WorkbenchReviewedPlan)
    assert str(selected.reference.review_id) == reviewed["reviewId"]
    assert str(selected.reference.plan_version_id) == saved["id"]
    assert selected.reference.review_evidence_hash == saved["reviewEvidenceHash"]
    assert selected.draft_json == saved["planJson"]
    assert selected.source_text == saved["sourceText"]
    assert _snapshot(lifecycle) == before


def test_unqualified_pure_projection_defaults_to_missing_coverage_instead_of_legacy_approval(
    workspace,
):
    client, lifecycle = workspace
    saved = _save(client)
    reviewed = post(client, "plan-review-confirmations",
                    _command(saved, _proof(lifecycle, saved["id"])))
    assert reviewed["canActivate"] is True
    with lifecycle._unit_of_work() as work:
        details = work.plans.get_version_details(saved["id"])

        _, validation, can_activate = _validated_plan_state(details)

        assert can_activate is False
        assert "SOURCE_COVERAGE_REQUIRED" in {issue.code for issue in validation.issues}
        assert details.daily_issues == ()
