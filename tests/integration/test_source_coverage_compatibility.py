"""Actual cutover facts stay descriptive while new source authority stays closed.

Disposable 0027/0028 SQLite stores and production readers only; no provider or
caller-supplied COMPLETE status. FIELD sources are engineering fixtures.
"""

from functools import partial

import pytest
from sqlalchemy import event, insert, update
from tests.integration.test_current_plan_api import (
    SOURCE,
    make_app,
    review_payload,
    reviewed_save,
    simple_plan,
)
from tests.integration.test_live_monitor_projection_migration import _upgrade
from tests.integration.test_source_action_cutover import (
    _ACTIVATED,
    _resolve,
)
from tests.integration.test_source_action_cutover import (
    legacy as legacy,
)
from tests.integration.test_source_coverage_migration import _seed_legacy
from tests.integration.test_source_coverage_read import client_for, page

from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft
from trade_plan_monitor.state.models import ActivePlan, PlanActivationState, PlanVersion
from trade_plan_monitor.state.repositories import PlanSaveBlockedError
from trade_plan_monitor.state.source_coverage_authority import SourceCoverageAuthorityError
from trade_plan_monitor.state.source_coverage_models import COVERAGE_TRIGGER_SQL, CoverageCutoverRow
from trade_plan_monitor.state.source_coverage_store import SourceCoverageStore
from trade_plan_monitor.state.source_coverage_values import CoverageCutover

_NATIVE = ("plan_source", "plan_version", "plan_version_review", "plan_review_provenance",
           "daily_plan_record", "active_plan", "plan_activation_state")


def native_rows(engine):
    with engine.connect() as connection:
        return {table: tuple(connection.exec_driver_sql(f'SELECT * FROM "{table}"').all())
                for table in _NATIVE}


def test_real_upgrade_preserves_native_bytes_and_get_never_upgrades_legacy_authority(legacy):
    case = legacy(upgraded=False)
    before = native_rows(case.engine)
    with client_for(case.sessions, case.engine) as (client, _):
        missing = page(client, case.id)["summary"]
        assert missing["status"] == "UNKNOWN"
        assert missing["reason"] == "SOURCE_COVERAGE_UPGRADE_REQUIRED"
    assert native_rows(case.engine) == before
    with case.engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == (
            "0027_simulation_capital")
        assert not connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE name LIKE 'source_coverage_%'").all()

    _upgrade(case.engine, "0028_source_coverage")
    with client_for(case.sessions, case.engine) as (client, _):
        source = page(client, case.id)
        detail = client.get("/api/v1/plan-versions/" + case.id).json()
        listing = client.get("/api/v1/plan-versions", params={"offset": 0, "limit": 50})
        assert listing.status_code == 200
        summary = source["summary"]
        assert summary["status"] == "LEGACY_UNASSESSED"
        assert not summary["coverageComplete"] and not summary["currentReviewBound"]
        assert not summary["canConfirmReview"] and source["items"] == []
        assert detail["status"] == "ACTIVE" and detail["canActivate"] is False
        assert detail.get("obsoleteReason") is None
        assert detail["sourceCoverage"] == summary
        assert listing.json()["items"][0]["sourceCoverage"] == summary
    with case.work() as work:
        assert SourceCoverageStore(work.daily.session).latest(case.id) is None
        basis = _resolve(work, case.id, case.cause_id)
        assert basis.basis == "HISTORICAL_TECHNICAL_RISK"
        assert basis.coverage_evidence_hash is None and basis.cutover_evidence_hash
        with pytest.raises(SourceCoverageAuthorityError, match="SOURCE_COVERAGE_REQUIRED"):
            _resolve(work, case.id)
    assert native_rows(case.engine) == before


def test_backdated_post_cutover_version_is_not_a_captured_legacy_member(legacy):
    case = legacy()
    newer = _seed_legacy(case.engine, number=2, created_at="1990-01-01T00:00:00+00:00")
    before = native_rows(case.engine)
    with client_for(case.sessions, case.engine) as (client, service):
        observed = page(client, newer.id)
        assert observed["summary"]["status"] == "UNKNOWN"
        assert observed["summary"]["reason"] == "SOURCE_COVERAGE_REQUIRED"
        assert not observed["summary"]["canConfirmReview"] and observed["items"] == []
        with pytest.raises(PlanSaveBlockedError):
            client.portal.call(partial(service.get_reviewed_backtest_plan, version_id=newer.id))
    with case.work() as work:
        assert SourceCoverageStore(work.daily.session).cutover(newer.id) is None
    assert native_rows(case.engine) == before


def test_legacy_diagnostic_is_point_only_and_does_not_veto_independent_buy_gap_risk(legacy):
    case = legacy(buy_only_failure=True, extra_members=2)
    before = native_rows(case.engine)
    statements = []
    def listener(_c, _u, sql, _p, _x, _m):
        statements.append(sql.lower())
    event.listen(case.engine, "before_cursor_execute", listener)
    try:
        with client_for(case.sessions, case.engine) as (client, _):
            assert page(client, case.id)["summary"]["status"] == "LEGACY_UNASSESSED"
    finally:
        event.remove(case.engine, "before_cursor_execute", listener)
    members = [sql for sql in statements if "from source_coverage_cutover" in sql]
    assert members and all("where source_coverage_cutover.plan_version_id =" in sql
                           for sql in members)
    assert not any("daily_plan_record" in sql or "count(" in sql for sql in statements)
    with case.work() as work:
        basis = _resolve(work, case.id, case.cause_id)
        assert basis.basis == "HISTORICAL_TECHNICAL_RISK"
        assert [row["id"] for row in basis.risk_rows] == [case.cause_id]
    assert native_rows(case.engine) == before


def test_point_display_cannot_authenticate_an_individually_resigned_cutover_grant(legacy):
    case = legacy(active=False)
    with case.work() as work:
        member = SourceCoverageStore(work.daily.session).cutover(case.id)
    forged = CoverageCutover.build(**member.model_dump(mode="python", exclude={
        "evidence_hash", "legacy_identity"}), legacy_identity=member.legacy_identity | dict(
            status="ACTIVE", revision=1, active_revision=1, activated_at=_ACTIVATED.isoformat()))
    with case.engine.begin() as connection:
        connection.execute(update(PlanVersion).values(status="ACTIVE", revision=1))
        connection.execute(insert(ActivePlan), dict(symbol=case.draft.symbol,
            plan_version_id=case.id, revision=1, activated_at=_ACTIVATED.isoformat()))
        connection.execute(insert(PlanActivationState), dict(symbol=case.draft.symbol,
            plan_version_id=case.id, revision=1, changed_at=_ACTIVATED.isoformat()))
        trigger = "pma_seal_source_coverage_cutover_update"
        connection.exec_driver_sql("DROP TRIGGER " + trigger)
        connection.execute(update(CoverageCutoverRow).values(
            payload_json=canonical(forged.model_dump(mode="json")),
            evidence_hash=forged.evidence_hash))
        connection.exec_driver_sql(COVERAGE_TRIGGER_SQL[trigger])
    before = native_rows(case.engine)
    with client_for(case.sessions, case.engine) as (client, _):
        # Display validates the point member; only action authority verifies its root.
        assert page(client, case.id)["summary"]["status"] == "LEGACY_UNASSESSED"
    with case.work() as work, pytest.raises(SourceCoverageAuthorityError,
                                           match="SOURCE_COVERAGE_INTEGRITY"):
        _resolve(work, case.id, case.cause_id)
    assert native_rows(case.engine) == before


@pytest.mark.parametrize("extra", ["所有风险退出必须先等待蓝灯。",
                                  "Only buy when turnover exceeds 3 percent."])
def test_legacy_display_does_not_treat_unknown_scope_as_buy_only(legacy, extra):
    case = legacy(extra=extra)
    with client_for(case.sessions, case.engine) as (client, _):
        assert page(client, case.id)["summary"]["status"] == "LEGACY_UNASSESSED"
    with case.work() as work, pytest.raises(SourceCoverageAuthorityError,
                                           match="SOURCE_COVERAGE_REQUIRED"):
        _resolve(work, case.id, case.cause_id)


def test_original_generic_supplemented_source_remains_a_blocked_current_negative(tmp_path):
    from fastapi.testclient import TestClient

    app = make_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        saved = reviewed_save(client, UnifiedPlanDraft.from_executable(simple_plan()))
        assert saved["sourceText"] == SOURCE
        observed = page(client, saved["id"])
        assert observed["summary"]["status"] == "BLOCKED"
        assert not observed["summary"]["canConfirmReview"]
        rejected = client.post("/api/v1/plan-review-confirmations", json=review_payload(saved),
                               headers={"Idempotency-Key": "generic-is-not-current"})
        assert rejected.status_code == 409
        assert {i["code"] for i in rejected.json()["error"]["details"]} == {
            "SOURCE_COVERAGE_REQUIRED"}
        with pytest.raises(PlanSaveBlockedError):
            client.portal.call(partial(app.state.plan_operation_service.get_reviewed_backtest_plan,
                                       version_id=saved["id"]))
        detail = client.get("/api/v1/plan-versions/" + saved["id"]).json()
        assert detail["reviewId"] is None and detail["reviewRevision"] == 0
