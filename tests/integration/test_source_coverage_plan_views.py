"""Plan views use actual current source owners, without changing old save receipts.

All source plans are explicit synthetic engineering fixtures. Temporary native
SQLite state, real HTTP mutations and the real0027->0028 cutover establish the
owners; no provider, user database, mocked coverage grant or legacy flag is used.
"""

import json
from contextlib import contextmanager, nullcontext
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select, update
from tests.integration.test_current_plan_api import post, review_payload
from tests.integration.test_market_linkage_review import source_mapping
from tests.integration.test_source_action_cutover import legacy as legacy
from tests.integration.test_source_coverage_projection import _advance_coverage, _snapshot
from tests.integration.test_source_coverage_review_api import _command, _proof
from tests.integration.test_source_coverage_review_api import workspace as workspace
from tests.unit.test_source_coverage_baseline import _append_as_context, _baseline

from trade_plan_monitor.ai.daily_review import DailyClause, build_daily_review
from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_json, daily_draft_sha256
from trade_plan_monitor.state.models import PlanSource, PlanVersion, RequestIdempotency
from trade_plan_monitor.state.source_coverage_store import (
    SourceCoverageIntegrityError,
    SourceCoverageStore,
)
from trade_plan_monitor.web.errors import install_error_boundary
from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle
from trade_plan_monitor.web.routers.plans import PlanVersionView, router


def _payload(*, number=1, role=None):
    draft, source, mapping = _baseline()
    if number != 1:
        draft = draft.model_copy(update={"version": number})
        source, mapping = source_mapping(draft)
    if role is not None:
        source, mapping = _append_as_context(
            source,
            mapping,
            "Only buy when turnover exceeds 3 percent.",
            semantic_role=role,
            misclassification=dict(disposition="CONTEXT", paths=[], reason="Proposed background"),
        )
    assert build_daily_review(draft, mapping, source).issues == ()
    return dict(
        planJson=daily_draft_json(draft),
        sourceText=source,
        dailyMapping=mapping.model_dump(mode="json"),
        expectedRevision=0,
    )


def _save(client, **options):
    return post(client, "plan-drafts", _payload(**options))


def _detail(client, identity):
    response = client.get("/api/v1/plan-versions/" + identity)
    assert response.status_code == 200, response.text
    return response.json()


def _coverage(client, identity):
    response = client.get(f"/api/v1/plan-versions/{identity}/source-coverage")
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["authorityGranted"] is False
    return value["summary"]


def _page(client, **params):
    response = client.get("/api/v1/plan-versions", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _confirm(client, lifecycle, saved):
    return post(
        client, "plan-review-confirmations", _command(saved, _proof(lifecycle, saved["id"]))
    )


def _activate(client, saved, reviewed):
    return post(
        client,
        "plan-activations",
        review_payload(
            saved,
            reviewId=reviewed["reviewId"],
            reviewRevision=reviewed["revision"],
        ),
    )


@contextmanager
def _legacy_client(case):
    # The fixture already performed its explicit temporary migration. Do not start
    # an application lifecycle, which would silently upgrade the old-storage case.
    service = PersistentPlanWebLifecycle(
        database_path=Path(case.engine.url.database), clock=case.work()._clock
    )
    service._engine, service._session_factory = case.engine, case.sessions
    app = FastAPI()
    install_error_boundary(app)
    app.include_router(router)
    app.state.plan_operation_service = service
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        yield client, service


def test_first_native_save_and_detail_expose_the_same_complete_unconfirmed_source(workspace):
    client, lifecycle = workspace
    saved = _save(client)
    summary = saved["sourceCoverage"]
    assert summary["status"] == "COMPLETE" and summary["coverageComplete"] is True
    assert summary["currentReviewBound"] is False and summary["canConfirmReview"] is True
    assert summary["reviewState"] == "UNCONFIRMED" and summary["reason"] is None
    assert summary["authorityGranted"] is False
    assert saved["reviewId"] is None and saved["canActivate"] is False
    assert saved["dailyIssues"] == saved["validationIssues"] == []
    assert summary["sourceHash"] == saved["sourceHash"]
    assert summary["candidatePlanHash"] == saved["planHash"]
    assert summary["contentHash"] == saved["contentHash"]
    assert summary["originalReviewEvidenceHash"] == saved["reviewEvidenceHash"]
    before = _snapshot(lifecycle)
    assert _detail(client, saved["id"])["sourceCoverage"] == summary
    assert _coverage(client, saved["id"]) == summary
    listed = _page(client)["items"][0]
    assert listed["sourceCoverage"] == summary and listed["canActivate"] is False
    assert _snapshot(lifecycle) == before


@pytest.mark.parametrize("role", ["COMMENTARY", "ACCOUNT", "HISTORICAL"])
def test_mandatory_background_condition_stays_inspectable_and_blocks_native_views(workspace, role):
    client, lifecycle = workspace
    saved = _save(client, role=role)
    summary = saved["sourceCoverage"]
    assert summary["status"] == "BLOCKED" and summary["issueCount"] > 0
    assert not summary["currentReviewBound"] and not summary["canConfirmReview"]
    assert summary["reason"] == "SOURCE_COVERAGE_REQUIRED"
    assert saved["status"] == "DRAFT" and saved["canActivate"] is False
    assert saved["dailyIssues"] == []  # Historical verifier is not current completeness.
    before = _snapshot(lifecycle)
    detail = _detail(client, saved["id"])
    assert detail["sourceCoverage"] == _coverage(client, saved["id"]) == summary
    assert detail["sourceText"] == saved["sourceText"]
    assert detail["planJson"] == saved["planJson"]
    assert _page(client, canActivate="true")["items"] == []
    negative = _page(client, canActivate="false")
    assert negative["total"] == 1 and negative["items"][0]["id"] == saved["id"]
    assert _snapshot(lifecycle) == before


def test_confirmed_active_native_view_has_the_exact_current_bound_receipt(workspace):
    client, lifecycle = workspace
    saved = _save(client)
    reviewed = _confirm(client, lifecycle, saved)
    active = _activate(client, saved, reviewed)
    assert active["active"] is True
    before = _snapshot(lifecycle)
    detail = _detail(client, saved["id"])
    summary = detail["sourceCoverage"]
    assert detail["status"] == "ACTIVE" and detail["obsoleteReason"] is None
    assert detail["canActivate"] is True
    assert summary["status"] == "COMPLETE" and summary["currentReviewBound"] is True
    assert summary["reviewState"] == "CURRENT" and summary["canConfirmReview"] is False
    assert summary["reviewId"] == reviewed["reviewId"]
    assert summary["coverageReviewReceiptHash"] is not None
    assert summary == _coverage(client, saved["id"])
    assert _page(client, canActivate="true")["items"][0]["sourceCoverage"] == summary
    assert _snapshot(lifecycle) == before


def test_new_bundle_revokes_current_review_without_falsifying_active_or_old_review(workspace):
    client, lifecycle = workspace
    saved = _save(client)
    original = _proof(lifecycle, saved["id"])
    reviewed = _confirm(client, lifecycle, saved)
    _activate(client, saved, reviewed)
    newer = _advance_coverage(lifecycle, saved["id"], original)
    assert newer.assessment == original.assessment
    before = _snapshot(lifecycle)
    detail = _detail(client, saved["id"])
    summary = detail["sourceCoverage"]
    assert detail["status"] == "ACTIVE" and detail["obsoleteReason"] is None
    assert detail["canActivate"] is False and detail["dailyIssues"] == []
    assert summary["coverageComplete"] is True and summary["currentReviewBound"] is False
    assert summary["reason"] == "SOURCE_COVERAGE_STALE" and not summary["canConfirmReview"]
    assert summary["coverageRevision"] == newer.revision
    assert detail["reviewId"] == reviewed["reviewId"]
    assert detail["reviewEvidenceHash"] == saved["reviewEvidenceHash"]
    assert detail["planJson"] == saved["planJson"]
    assert _page(client, canActivate="true")["items"] == []
    assert _page(client, canActivate="false")["items"][0]["sourceCoverage"] == summary
    assert _snapshot(lifecycle) == before


@pytest.mark.parametrize("upgraded", [True, False], ids=["real-cutover", "missing-storage"])
def test_old_active_owner_is_descriptive_legacy_or_upgrade_without_fake_obsolete(legacy, upgraded):
    case = legacy(upgraded=upgraded)
    if upgraded:
        with case.work() as work:
            store = SourceCoverageStore(work.daily.session)
            member = store.cutover(case.id)
            assert member.legacy_identity["status"] == "ACTIVE"
            assert member.plan_hash == daily_draft_sha256(case.draft)
            assert store.latest(case.id) is None
    with _legacy_client(case) as (client, service):
        before = _snapshot(service) if upgraded else None
        detail = _detail(client, case.id)
        summary = detail["sourceCoverage"]
        assert detail["status"] == "ACTIVE" and detail["obsoleteReason"] is None
        assert detail["canActivate"] is False and detail["dailyIssues"] == []
        assert summary["status"] == ("LEGACY_UNASSESSED" if upgraded else "UNKNOWN")
        assert summary["reason"] == (
            "SOURCE_COVERAGE_REQUIRED" if upgraded else "SOURCE_COVERAGE_UPGRADE_REQUIRED"
        )
        assert not summary["currentReviewBound"] and not summary["canConfirmReview"]
        assert summary["coverageEvidenceHash"] is None and summary["authorityGranted"] is False
        assert detail["planJson"] == daily_draft_json(case.draft)
        assert _page(client, canActivate="true")["items"] == []
        assert _page(client, canActivate="false")["items"][0]["sourceCoverage"] == summary
        if upgraded:
            assert _snapshot(service) == before


def test_list_filter_uses_current_summary_for_both_branches_and_requested_window(workspace):
    client, lifecycle = workspace
    complete = _save(client)
    blocked = _save(client, number=2, role="COMMENTARY")
    unconfirmed = _save(client, number=3)
    _confirm(client, lifecycle, complete)
    before = _snapshot(lifecycle)
    full = _page(client)
    assert full["total"] == 3
    for item in full["items"]:
        assert item["sourceCoverage"] == _detail(client, item["id"])["sourceCoverage"]
        assert not {"planJson", "sourceText", "dailyMapping", "validationIssues"} & item.keys()
        assert not {"items", "rawJson", "inputs"} & item["sourceCoverage"].keys()
    positive = _page(client, canActivate="true")
    assert positive["total"] == 1 and positive["items"][0]["id"] == complete["id"]
    negative = _page(client, canActivate="false")
    assert negative["total"] == 2
    assert {row["id"] for row in negative["items"]} == {blocked["id"], unconfirmed["id"]}
    window = _page(client, canActivate="false", offset=1, limit=1)
    assert window["total"] == 2 and window["items"] == negative["items"][1:2]
    assert _snapshot(lifecycle) == before


@pytest.mark.parametrize("projection", ["detail", "list", "filtered"])
def test_projection_uses_the_same_fresh_sql_record_as_source_summary(
    workspace, monkeypatch, projection
):
    client, lifecycle = workspace
    saved = _save(client)
    before = _snapshot(lifecycle)
    with lifecycle._unit_of_work() as work:
        held = work.daily.session.get(PlanVersion, saved["id"])
        assert held.revision == 0
        work.daily.session.execute(
            update(PlanVersion)
            .where(PlanVersion.id == held.id)
            .values(revision=9)
            .execution_options(synchronize_session=False)
        )
        assert held.revision == 0  # A held stale ORM identity is the actual adversarial seam.
        monkeypatch.setattr(lifecycle, "_unit_of_work", lambda: nullcontext(work))
        if projection == "detail":
            value = lifecycle._get_plan_version_sync(version_id=saved["id"])
        else:
            value = lifecycle._list_plan_versions_sync(
                offset=0,
                limit=50,
                symbol=None,
                status=None,
                can_activate=False if projection == "filtered" else None,
            ).items[0]
        assert value.revision == 9
        assert value.model_dump(mode="json", by_alias=True)["sourceCoverage"]["coverageComplete"]
    assert _snapshot(lifecycle) == before  # Uncommitted fault transaction was rolled back.


@pytest.mark.parametrize("owner", ["source", "version"])
def test_projection_does_not_flush_or_discard_related_pending_changes(
    workspace, monkeypatch, owner
):
    client, lifecycle = workspace
    saved = _save(client)
    before = _snapshot(lifecycle)
    with lifecycle._unit_of_work() as work:
        session = work.daily.session
        version = session.get(PlanVersion, saved["id"])
        row = session.get(PlanSource, version.source_id) if owner == "source" else version
        field = "source_text" if owner == "source" else "payload_json"
        actual = getattr(row, field)
        changed = actual + " Pending private source condition."
        setattr(row, field, changed)
        monkeypatch.setattr(lifecycle, "_unit_of_work", lambda: nullcontext(work))
        with pytest.raises(SourceCoverageIntegrityError):
            lifecycle._get_plan_version_sync(version_id=saved["id"])
        assert row in session.dirty and getattr(row, field) == changed
        table = PlanSource if owner == "source" else PlanVersion
        with session.no_autoflush:
            assert (
                session.execute(
                    select(getattr(table, field)).where(table.id == row.id)
                ).scalar_one()
                == actual
            )
    assert _snapshot(lifecycle) == before


def test_full_512_native_issues_are_saved_without_truncation_or_513th_source_copy(workspace):
    client, lifecycle = workspace
    draft, source, mapping = _baseline()
    missing = 512 - len(mapping.clauses)
    source += "\n" + "\n".join(f"Unresolved source span {index}." for index in range(missing))
    canonical_clauses = server_source_clauses(source)
    assert len(canonical_clauses) == 512
    clauses = tuple(
        row.model_copy(update={"semantic_role": "AMBIGUOUS"}) for row in mapping.clauses
    ) + tuple(
        DailyClause.model_validate(
            row.model_dump()
            | dict(
                disposition="UNRESOLVED",
                paths=(),
                reason="Unresolved synthetic source span.",
            )
        )
        for row in canonical_clauses[len(mapping.clauses) :]
    )
    mapping = mapping.model_copy(update={"clauses": clauses})
    review = build_daily_review(draft, mapping, source)
    assert len(review.issues) == 512
    saved = post(
        client,
        "plan-drafts",
        dict(
            planJson=daily_draft_json(draft),
            sourceText=source,
            dailyMapping=mapping.model_dump(mode="json"),
            expectedRevision=0,
        ),
    )
    assert len(saved["dailyIssues"]) == len(saved["validationIssues"]) == 512
    assert saved["dailyIssues"] == [row.model_dump(mode="json") for row in review.issues]
    assert [(row["code"], row["path"]) for row in saved["validationIssues"]] == [
        (row.code, row.path) for row in review.issues
    ]
    assert saved["sourceCoverage"]["reason"] == "SOURCE_COVERAGE_REQUIRED"
    assert not saved["sourceCoverage"]["canConfirmReview"] and not saved["canActivate"]
    before = _snapshot(lifecycle)
    assert _detail(client, saved["id"])["validationIssues"] == saved["validationIssues"]
    assert _snapshot(lifecycle) == before


def test_completed_old_save_response_preserves_its_projection_and_exact_stored_bytes(workspace):
    client, lifecycle = workspace
    command, key = _payload(), "old-save-response-projection"
    saved = post(client, "plan-drafts", command, key=key)
    historical = {name: value for name, value in saved.items() if name != "sourceCoverage"}
    # The real completed intent/hash is unchanged; only its old-version response
    # shape is represented. This does not create a source proof or review grant.
    old_bytes = canonical(historical)
    with lifecycle._session_factory() as session, session.begin():
        row = session.get(RequestIdempotency, key)
        assert row.status == "COMPLETED"
        row.response_json = old_bytes
    original = _proof(lifecycle, saved["id"])
    newer = _advance_coverage(lifecycle, saved["id"], original)
    before = _snapshot(lifecycle)
    replay = post(client, "plan-drafts", command, key=key)
    assert replay == historical and "sourceCoverage" not in replay
    assert _detail(client, saved["id"])["sourceCoverage"]["coverageRevision"] == newer.revision
    with lifecycle._session_factory() as session:
        assert session.get(RequestIdempotency, key).response_json == old_bytes
    assert _snapshot(lifecycle) == before


@pytest.mark.parametrize("mutation", ["activate-unconfirmed", "confirm-superseded"])
def test_native_dto_rejects_eligibility_inconsistent_with_its_actual_source_summary(
    workspace, mutation
):
    client, _ = workspace
    saved = _save(client)
    assert saved["sourceCoverage"]["canConfirmReview"] is True
    changed = (
        {**saved, "canActivate": True}
        if mutation == "activate-unconfirmed"
        else {
            **saved,
            "status": "SUPERSEDED",
        }
    )
    with pytest.raises(ValidationError):
        PlanVersionView.model_validate_json(json.dumps(changed))


def test_old_receipt_dto_without_source_projection_preserves_omission(workspace):
    client, _ = workspace
    saved = _save(client)
    historical = {name: value for name, value in saved.items() if name != "sourceCoverage"}
    decoded = PlanVersionView.model_validate_json(json.dumps(historical))
    assert decoded.model_dump(mode="json", by_alias=True) == historical
    assert "sourceCoverage" not in decoded.model_dump(mode="json", by_alias=True)
