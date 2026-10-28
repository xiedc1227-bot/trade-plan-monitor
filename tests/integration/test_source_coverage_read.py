"""Read actual current and legacy coverage without writes, providers or user data."""

import json
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, text, update
from tests.integration.test_source_action_cutover import legacy as legacy
from tests.integration.test_source_coverage_authority import _confirm, _save
from tests.integration.test_source_coverage_authority_save import _NOW, _ai_result
from tests.integration.test_source_coverage_authority_save import _save as save_result
from tests.integration.test_source_coverage_authority_save import state as state
from tests.integration.test_source_coverage_supplement_clock import _save as save_supplemented
from tests.unit.test_source_coverage_baseline import _baseline

from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.models import PlanSource, PlanVersion
from trade_plan_monitor.state.source_coverage_models import (
    COVERAGE_TRIGGER_SQL,
    CoverageAssessmentRow,
)
from trade_plan_monitor.state.source_coverage_store import (
    SourceCoverageIntegrityError,
    SourceCoverageStore,
)
from trade_plan_monitor.web.errors import ApiError, install_error_boundary
from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle
from trade_plan_monitor.web.routers.plans import router
from trade_plan_monitor.web.source_coverage_read import (
    SourceCoverageCursorCodec,
    read_source_coverage,
    source_coverage_page,
)

_AT = _NOW + timedelta(minutes=3)


@contextmanager
def client_for(sessions, engine):
    # Do NOT call service.start(): old-storage cases must remain unupgraded.
    service = PersistentPlanWebLifecycle(database_path=Path(engine.url.database), clock=lambda: _AT)
    service._engine, service._session_factory = engine, sessions
    app = FastAPI()
    install_error_boundary(app)
    app.include_router(router)
    app.state.plan_operation_service = service
    with TestClient(app, base_url="http://127.0.0.1:8765", raise_server_exceptions=False) as client:
        yield client, service


def url(identity):
    return f"/api/v1/plan-versions/{identity}/source-coverage"


def page(client, identity, **params):
    response = client.get(url(identity), params=params)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["authorityGranted"] is False
    assert payload["summary"]["authorityGranted"] is False
    assert len(response.content) <= 1024 * 1024
    return payload


def all_rows(client, identity, *, limit=50):
    values, seen, cursor = [], set(), None
    for _ in range(14289):
        result = page(client, identity, limit=limit, **({"cursor": cursor} if cursor else {}))
        values.extend(result["items"])
        cursor = result["nextCursor"]
        if cursor is None:
            assert [row["rowIndex"] for row in values] == list(range(result["totalRows"]))
            return result, values
        assert cursor not in seen and len(cursor) <= 512
        seen.add(cursor)
    pytest.fail("Coverage pagination did not make bounded forward progress")


def storage_snapshot(engine):
    with engine.connect() as connection:
        names = connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").scalars().all()
        return {name: connection.exec_driver_sql(f'SELECT * FROM "{name}"').all() for name in names}


def test_actual_coverage_get_exposes_complete_inspectable_unreviewed_source(state):
    identity, _ = _save(state)
    with client_for(state.sessions, state.engine) as (client, _):
        value = page(client, identity)
        summary = value["summary"]
        assert summary["status"] == "COMPLETE" and summary["coverageComplete"] is True
        assert summary["currentReviewBound"] is False
        assert summary["canConfirmReview"] is True
        assert value["limit"] == 50
        assert 0 < len(value["items"]) <= 50


def test_complete_get_is_read_only_and_every_original_obligation_is_reachable(state):
    identity, _ = _save(state)
    before = storage_snapshot(state.engine)
    with client_for(state.sessions, state.engine) as (client, _):
        _, rows = all_rows(client, identity, limit=1)
    with state.sessions() as session:
        stored = SourceCoverageStore(session).latest(identity)
    actual = [row["obligation"]["obligationId"] for row in rows if row["kind"] == "OBLIGATION"]
    assert actual == [row.obligation_id for row in stored.assessment.obligations]
    assert storage_snapshot(state.engine) == before


def test_background_misclassification_keeps_blocked_source_visible(state):
    identity, _ = _save(state, blocked=True)
    with client_for(state.sessions, state.engine) as (client, _):
        value, rows = all_rows(client, identity)
    assert value["summary"]["status"] == "BLOCKED"
    assert value["summary"]["canConfirmReview"] is False
    assert any(row["kind"] == "ISSUE" for row in rows)
    assert any(row["kind"] == "OBLIGATION" and row["obligation"]["serverState"]
               in {"UNRESOLVED", "UNSUPPORTED", "CONFLICT"} for row in rows)


def test_normalization_loss_global_issue_has_an_independent_page_row(state):
    draft, source, mapping = _baseline()
    result = _ai_result(draft, source, mapping, with_normalization=False)
    identity = save_result(state, draft, source, mapping, extraction=result)
    with client_for(state.sessions, state.engine) as (client, _):
        final, rows = all_rows(client, identity, limit=1)
    assert final["summary"]["status"] == "BLOCKED"
    issues = [row["issue"] for row in rows if row["kind"] == "ISSUE"]
    assert any(issue["code"] == "SOURCE_NORMALIZATION_LOSS" and issue["start"] is None
               and issue["end"] is None for issue in issues)


def test_existing_legacy_read_is_a_point_diagnostic_without_action_root_scans(legacy):
    case = legacy()
    before = storage_snapshot(case.engine)
    with client_for(case.sessions, case.engine) as (client, _):
        value = page(client, case.id)
    assert value["summary"]["status"] == "LEGACY_UNASSESSED"
    assert value["summary"]["currentReviewBound"] is False
    assert value["summary"]["canConfirmReview"] is False
    assert value["items"] == [] and value["nextCursor"] is None
    assert storage_snapshot(case.engine) == before


def test_missing_sidecar_is_unknown_without_implicit_upgrade(legacy):
    case = legacy(upgraded=False)
    before = storage_snapshot(case.engine)
    with client_for(case.sessions, case.engine) as (client, _):
        value = page(client, case.id)
    assert value["summary"]["status"] == "UNKNOWN"
    assert value["summary"]["reason"] == "SOURCE_COVERAGE_UPGRADE_REQUIRED"
    assert storage_snapshot(case.engine) == before


def test_valid_old_cursor_conflicts_after_identical_assessment_gets_a_new_bundle(state):
    identity, _ = _save(state)
    with client_for(state.sessions, state.engine) as (client, _):
        first = page(client, identity, limit=1)
        assert first["nextCursor"]
        with state.work() as work:
            store = SourceCoverageStore(work.daily.session)
            old = store.latest(identity)
            store.append(identity, old.assessment, inputs=old.inputs,
                expected_revision=old.revision, command_id="api-new-bundle",
                now=_NOW + timedelta(minutes=1))
            work.commit()
        response = client.get(url(identity), params={"limit": 1, "cursor": first["nextCursor"]})
        assert response.status_code == 409
        assert response.json()["error"]["details"][0]["code"] == "SOURCE_COVERAGE_STALE"
        assert page(client, identity, limit=1)["summary"]["coverageRevision"] == 2


def test_cursor_survives_requests_but_not_a_different_lifecycle_owner(state):
    identity, _ = _save(state)
    with client_for(state.sessions, state.engine) as (client, _):
        first = page(client, identity, limit=1)
        second = page(client, identity, limit=1, cursor=first["nextCursor"])
        assert second["items"][0]["rowIndex"] == 1
    with client_for(state.sessions, state.engine) as (client, _):
        response = client.get(url(identity), params={"limit": 1, "cursor": first["nextCursor"]})
        assert response.status_code == 422


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"cursor": "forged"},
                                    {"offset": 0}, {"cursor": "x" * 513}])
def test_closed_coverage_query_contract_rejects_invalid_parameters(state, params):
    identity, _ = _save(state)
    with client_for(state.sessions, state.engine) as (client, _):
        assert client.get(url(identity), params=params).status_code == 422


def test_nonexistent_actual_plan_is_not_a_legacy_or_unknown_success(state):
    with client_for(state.sessions, state.engine) as (client, _):
        assert client.get(url(UUID(int=999999))).status_code == 404


def test_valid_sql_seals_do_not_hide_corrupt_stored_source_evidence(state):
    identity, _ = _save(state)
    with state.work() as work:
        stored = SourceCoverageStore(work.daily.session).latest(identity)
        trigger = "pma_seal_source_coverage_assessment_update"
        work.daily.session.execute(text("DROP TRIGGER " + trigger))
        work.daily.session.execute(update(CoverageAssessmentRow).where(
            CoverageAssessmentRow.plan_version_id == identity).values(
                payload_json=stored.model_dump_json() + " "))
        work.daily.session.execute(text(COVERAGE_TRIGGER_SQL[trigger]))
        work.commit()
    with client_for(state.sessions, state.engine) as (client, _):
        response = client.get(url(identity))
    assert response.status_code == 500 and response.json()["error"]["code"] == "INTERNAL_ERROR"


def test_every_public_obligation_preserves_exact_source_and_saved_mapping_proposal(state):
    identity, _ = _save(state, blocked=True)
    with state.work() as work:
        details = work.plans.get_version_details(identity)
        stored = SourceCoverageStore(work.daily.session).latest(identity)
    with client_for(state.sessions, state.engine) as (client, _):
        _, rows = all_rows(client, identity)
    obligations = [row["obligation"] for row in rows if row["kind"] == "OBLIGATION"]
    for actual, expected in zip(obligations, stored.assessment.obligations, strict=True):
        assert actual["excerpt"] == details.source_text[actual["start"]:actual["end"]]
        assert actual["semanticsJson"] == expected.semantics_json
        assert actual["relationIds"] == list(expected.relation_ids)
        assert actual["paths"] == list(expected.paths)
        clause = next(c for c in details.daily_mapping.clauses
                      if c.clause_id == expected.clause_id)
        assert actual["mappingProposal"] == dict(proposedDisposition=clause.disposition,
            semanticRole=clause.semantic_role, reason=clause.reason,
            proposedPaths=list(clause.paths))
        assert actual["humanSupplements"] == []  # HUMAN origin alone confirms no clause.
    unknown = next(row for row in obligations if row["excerpt"].startswith("Only buy"))
    assert unknown["mappingProposal"]["proposedDisposition"] == "CONTEXT"
    assert unknown["mappingProposal"]["semanticRole"] == "COMMENTARY"
    assert unknown["serverState"] == "UNRESOLVED"


def test_exact_registered_human_supplement_is_linked_only_to_its_own_obligation(state):
    identity = save_supplemented(state)
    with client_for(state.sessions, state.engine) as (client, _):
        result, rows = all_rows(client, identity)
    linked = [row["obligation"] for row in rows if row["kind"] == "OBLIGATION"
              and row["obligation"]["humanSupplements"]]
    assert result["summary"]["coverageComplete"] and len(linked) == 1
    obligation, = linked
    assert obligation["excerpt"] == "position.max_qty = null"
    assert obligation["serverState"] == "MAPPED_WITH_REGISTERED_SUPPLEMENT"
    assert obligation["humanSupplements"] == [dict(supplementId="explicit-missing-0",
        path="position.max_qty", candidateContentHash=result["summary"]["contentHash"])]


@pytest.mark.parametrize("human_edit", [False, True])
def test_normalization_change_stream_distinguishes_current_and_retained_historical_input(
    state, human_edit,
):
    draft, source, mapping = _baseline()
    original = _ai_result(draft, source, mapping, raw_name="  Original raw name  ")
    if human_edit:
        edited = deepcopy(draft.model_dump(mode="json"))
        path = "position.limit.capital_policy.cap_fen"
        edited["position"]["limit"]["capital_policy"]["cap_fen"] += 10000
        draft = type(draft).model_validate(edited)
        mapping = mapping.model_copy(update=dict(candidate_content_hash=
            daily_draft_content_sha256(draft), bindings=tuple(b for b in mapping.bindings
                                                            if b.path != path)))
    identity = save_result(state, draft, source, mapping, extraction=original)
    with client_for(state.sessions, state.engine) as (client, _):
        result, rows = all_rows(client, identity, limit=1)
    changes = [row["change"] for row in rows if row["kind"] == "NORMALIZATION_CHANGE"]
    assert changes and result["summary"]["normalizationChangeCount"] == len(changes)
    assert {c["traceRole"] for c in changes} == {
        "HISTORICAL_INPUT" if human_edit else "CURRENT_ASSESSMENT"}
    assert changes[0]["beforeJson"] == original.normalization_trace.changes[0].before_json
    assert changes[0]["evidenceHash"] == original.normalization_trace.evidence_hash
    assert result["summary"]["automaticFidelityVerified"] is (not human_edit)


def test_review_observation_requires_exact_receipt_and_new_bundle_invalidates_it(state):
    identity, _ = _save(state)
    _confirm(state, identity)
    with client_for(state.sessions, state.engine) as (client, _):
        first = page(client, identity, limit=1)
        assert first["summary"]["currentReviewBound"] is True
        assert first["summary"]["reviewState"] == "CURRENT"
        assert first["summary"]["canConfirmReview"] is False
        with state.work() as work:
            store = SourceCoverageStore(work.daily.session)
            old = store.latest(identity)
            store.append(identity, old.assessment, inputs=old.inputs,
                expected_revision=old.revision, command_id="review-new-bundle", now=_AT)
            work.commit()
        assert client.get(url(identity), params=dict(limit=1, cursor=first["nextCursor"])
                          ).status_code == 409
        summary = page(client, identity)["summary"]
    assert summary["status"] == "COMPLETE" and summary["coverageComplete"]
    assert not summary["currentReviewBound"] and summary["reason"] == "SOURCE_COVERAGE_STALE"
    assert summary["reviewState"] == "NEEDS_REVIEW" and not summary["canConfirmReview"]


@pytest.mark.parametrize("mutation", ["unconfirmed", "mismatch", "malformed", "missing"])
def test_actual_review_shadow_cannot_be_replaced_by_provenance_and_receipt(state, mutation):
    from sqlalchemy import delete

    identity, _ = _save(state)
    _confirm(state, identity)
    with state.work() as work:
        session = work.daily.session
        row = session.get(DailyRecord, "review-" + identity)
        value = json.loads(row.payload_json)
        if mutation == "missing":
            session.execute(delete(DailyRecord).where(DailyRecord.id == row.id))
        else:
            changed = (canonical(value | dict(confirmed=False, review_id=None, review_revision=0))
                if mutation == "unconfirmed" else canonical(value | dict(source_hash="a" * 64))
                if mutation == "mismatch" else "[]")
            session.execute(update(DailyRecord).where(DailyRecord.id == row.id).values(
                payload_json=changed))
        work.commit()
    with client_for(state.sessions, state.engine) as (client, _):
        response = client.get(url(identity))
    if mutation in {"missing", "malformed"}:
        assert response.status_code == 500
    else:
        assert response.status_code == 200
        summary = response.json()["summary"]
        assert not summary["currentReviewBound"] and not summary["canConfirmReview"]
        assert summary["reason"] == "SOURCE_COVERAGE_STALE"
        assert summary["reviewState"] == "NEEDS_REVIEW"


def test_unconfirmed_draft_requires_its_actual_matching_review_shadow(state):
    identity, _ = _save(state)
    with state.work() as work:
        work.daily.session.execute(update(DailyRecord).where(
            DailyRecord.id == "review-" + identity).values(payload_json=canonical(dict(
                confirmed=False, review_id=None, review_revision=0, content_hash="a" * 64,
                source_hash="a" * 64, evidence_hash="a" * 64, plan_version_id=identity))))
        work.commit()
    with client_for(state.sessions, state.engine) as (client, _):
        summary = page(client, identity)["summary"]
    assert summary["coverageComplete"] and not summary["canConfirmReview"]
    assert summary["reason"] == "SOURCE_COVERAGE_STALE"


def test_current_review_shadow_pending_change_is_preserved_and_not_flushed(state):
    identity, _ = _save(state)
    with state.work() as work:
        session = work.daily.session
        row = session.get(DailyRecord, "review-" + identity)
        row.payload_json = "unflushed pending review"
        before = session.connection().exec_driver_sql("SELECT total_changes()").scalar()
        with pytest.raises(SourceCoverageIntegrityError):
            read_source_coverage(work, identity)
        assert row in session.dirty and row.payload_json == "unflushed pending review"
        assert session.connection().exec_driver_sql("SELECT total_changes()").scalar() == before


def test_legacy_display_does_not_scan_other_members_or_historical_risk_owners(legacy):
    case = legacy()
    statements = []
    def record(_conn, _cursor, statement, _params, _ctx, _many):
        statements.append(statement.lower())
    event.listen(case.engine, "before_cursor_execute", record)
    try:
        with client_for(case.sessions, case.engine) as (client, _):
            assert page(client, case.id)["summary"]["status"] == "LEGACY_UNASSESSED"
    finally:
        event.remove(case.engine, "before_cursor_execute", record)
    member_reads = [s for s in statements if "from source_coverage_cutover" in s]
    assert member_reads and all("where source_coverage_cutover.plan_version_id =" in s
                                for s in member_reads)
    assert not any("daily_record.kind" in s or "count(" in s for s in statements)


@pytest.mark.parametrize("pending", ["source", "version", "coverage", "new-related"])
def test_read_preserves_and_rejects_related_dirty_deleted_and_new_owners(state, pending):
    identity, _ = _save(state)
    with state.work() as work:
        session = work.daily.session
        version = session.get(PlanVersion, identity)
        source = session.get(PlanSource, version.source_id)
        if pending == "source":
            source.source_text += "Unflushed new requirement"
        elif pending == "version":
            session.delete(version)
        elif pending == "coverage":
            owner = session.get(CoverageAssessmentRow, (identity, 1))
            owner.command_id = "unflushed-coverage-change"
        else:
            owner = CoverageAssessmentRow(plan_version_id=identity, revision=2)
            session.add(owner)
        before = session.connection().exec_driver_sql("SELECT total_changes()").scalar()
        with pytest.raises(SourceCoverageIntegrityError):
            read_source_coverage(work, identity)
        assert session.connection().exec_driver_sql("SELECT total_changes()").scalar() == before
        assert session.new or session.dirty or session.deleted
        if pending == "source":
            assert source.source_text.endswith("Unflushed new requirement")


def test_read_does_not_flush_or_discard_unrelated_pending_data(state):
    identity, _ = _save(state)
    with state.work() as work:
        session = work.daily.session
        unrelated = DailyRecord(id="unrelated-new-record", kind="NOTE", symbol="000001.SZ")
        session.add(unrelated)
        before = session.connection().exec_driver_sql("SELECT total_changes()").scalar()
        assert read_source_coverage(work, identity).summary.coverage_complete
        assert unrelated in session.new
        assert session.connection().exec_driver_sql("SELECT total_changes()").scalar() == before


def test_read_uses_actual_fresh_record_not_a_held_stale_projection(state):
    identity, _ = _save(state)
    with state.work() as work:
        held = work.daily.session.get(PlanVersion, identity)
        revision = held.revision
        work.daily.session.execute(update(PlanVersion).where(PlanVersion.id == identity).values(
            revision=revision + 1).execution_options(synchronize_session=False))
        assert held.revision == revision
        result = read_source_coverage(work, identity)
        assert result.details.revision == revision + 1 == held.revision


@pytest.mark.parametrize("params", [(("limit", "1"), ("limit", "2")),
                                    (("cursor", "a"), ("cursor", "b")), {"cursor": "汉字"}])
def test_duplicate_and_non_ascii_query_parameters_are_rejected(state, params):
    identity, _ = _save(state)
    with client_for(state.sessions, state.engine) as (client, _):
        assert client.get(url(identity), params=params).status_code == 422


def test_authenticated_cursor_cannot_change_resource_or_limit(state):
    identity, _ = _save(state)
    with client_for(state.sessions, state.engine) as (client, _):
        token = page(client, identity, limit=1)["nextCursor"]
        assert client.get(url(UUID(int=999)), params=dict(cursor=token, limit=1)).status_code == 422
        assert client.get(url(identity), params=dict(cursor=token, limit=2)).status_code == 409


def test_cursor_canonical_encoding_and_bounds_are_enforced_even_with_a_valid_signature(state):
    import base64
    import hmac

    identity, _ = _save(state)
    key = b"x" * 32
    codec = SourceCoverageCursorCodec(key=key)
    def signed(raw):
        def enc(value):
            return base64.urlsafe_b64encode(value).rstrip(b"=").decode()
        return enc(raw) + "." + enc(hmac.digest(key, raw, "sha256"))
    values = dict(v="source-coverage-cursor-v1", planVersionId=identity,
                  binding="a" * 64, nextOffset=1)
    for raw in (json.dumps(values).encode(),  # Noncanonical whitespace/order.
                canonical(values | dict(nextOffset=True)).encode(),
                canonical(values | dict(nextOffset=-1)).encode(),
                canonical(values | dict(extra=1)).encode(),
                (canonical(values)[:-1] + ',"nextOffset":2}').encode()):
        with pytest.raises(ApiError) as error:
            codec.decode(signed(raw), identity)
        assert error.value.code == "VALIDATION_ERROR"
    good = codec.encode(identity, "a" * 64, 1)
    assert codec.decode(good, identity) == ("a" * 64, 1)
    with pytest.raises(ApiError):
        codec.decode(good.split(".")[0] + "=." + good.split(".")[1], identity)


def test_stale_reassessment_is_diagnostic_for_plan_views_but_current_evidence_get_conflicts(
    state, monkeypatch,
):
    from trade_plan_monitor.ai.source_coverage_models import CoverageAssessment, CoverageIssue
    from trade_plan_monitor.state import source_coverage_authority

    identity, _ = _save(state)
    with state.work() as work:
        stored = SourceCoverageStore(work.daily.session).latest(identity)
    # Simulate a later registered ruleset's genuine BLOCKED reassessment, as in
    # the existing authority regression. Never fake a COMPLETE authority reader.
    values = stored.assessment.model_dump(mode="python", exclude={"status", "evidence_hash"})
    values.update(obligations=stored.assessment.obligations, issues=(CoverageIssue(
        code="SOURCE_COVERAGE_REQUIRED", message="The current registered grammar is unresolved."),))
    reassessed = CoverageAssessment.build(**values)
    monkeypatch.setattr(source_coverage_authority, "assess_source_coverage",
                        lambda *args, **kwargs: reassessed)
    before = storage_snapshot(state.engine)
    with state.work() as work:
        result = read_source_coverage(work, identity)
        assert result.details.id == identity and result.stored is None
        assert result.normalization is None and result.summary.total_rows == 0
        assert result.summary.status == "UNKNOWN" and not result.summary.coverage_complete
        assert result.coverage_reason == result.summary.reason == "SOURCE_COVERAGE_STALE"
        assert result.summary.coverage_evidence_hash is None
        assert result.summary.coverage_bundle_hash is None
    with client_for(state.sessions, state.engine) as (client, _):
        response = client.get(url(identity))
    assert response.status_code == 409
    assert response.json()["error"]["details"][0]["code"] == "SOURCE_COVERAGE_STALE"
    assert storage_snapshot(state.engine) == before


def test_actual_http_multibyte_pages_pack_whole_saved_mapping_proposals_under_one_mib(state):
    draft, source, mapping = _baseline()
    longest = max((b.path for b in mapping.bindings), key=len)
    reason = "保留完整的当前映射建议；这不代表已授权任何交易。" * 30
    clauses = tuple(c.model_copy(update=dict(paths=(*c.paths, *(longest for _ in range(
        512 - len(c.paths)))), reason=reason)) if c.disposition == "POLICY" else c
        for c in mapping.clauses)
    mapping = mapping.model_copy(update=dict(clauses=clauses))
    identity = save_result(state, draft, source, mapping)
    with client_for(state.sessions, state.engine) as (client, _):
        first = page(client, identity, limit=100)
        assert 0 < first["returnedCount"] < 100 and first["nextCursor"]
        assert all(len(row["obligation"]["mappingProposal"]["proposedPaths"]) == 512
                   for row in first["items"] if row["kind"] == "OBLIGATION")
        assert first["items"][0]["obligation"]["mappingProposal"]["reason"] == reason
        _, rows = all_rows(client, identity, limit=100)
    assert [r["rowIndex"] for r in rows] == list(range(first["totalRows"]))


def test_projection_byte_admission_allows_exact_one_mib_and_rejects_one_byte_more(state):
    """Exercise legal wide DTO rows, independently of source-language reachability.

    This serializer test uses a genuinely BLOCKED read as its non-authority
    envelope. It does not claim these fabricated destination paths are proved.
    """
    identity, _ = _save(state, blocked=True)
    with state.work() as work:
        actual = read_source_coverage(work, identity)
        unknown = next(actual.row(i)
            for i, obligation in enumerate(actual.stored.assessment.obligations)
            if obligation.state == "UNRESOLVED")
        summary = actual.summary.model_copy(update=dict(obligation_count=1, issue_count=0,
            normalization_change_count=0, total_rows=1))
        selected = unknown.model_copy(update=dict(row_index=0))
        class ProjectionRead(type(actual)):
            def row(self, index):
                assert index == 0
                return selected
        projected = ProjectionRead(actual.details, summary, actual.coverage_reason,
                                   actual.stored, None)
        codec = SourceCoverageCursorCodec(key=b"x" * 32)
        def set_paths(paths):
            nonlocal selected
            selected = selected.model_copy(update=dict(obligation=selected.obligation.model_copy(
                update=dict(paths=paths))))
        set_paths(tuple("a" * 512 for _ in range(512)))
        small = source_coverage_page(projected, codec)
        delta = 1_048_576 - len(small.model_dump_json(by_alias=True).encode("utf-8"))
        emoji_count, remainder = divmod(delta, 3)
        chars = ["😀"] * emoji_count + (["é" if remainder == 1 else "汉"] if remainder else [])
        chars.extend("a" for _ in range(512 * 512 - len(chars)))
        assert len(chars) == 512 * 512
        paths = tuple("".join(chars[i:i + 512]) for i in range(0, len(chars), 512))
        set_paths(paths)
        exact = source_coverage_page(projected, codec)
        assert len(exact.model_dump_json(by_alias=True).encode("utf-8")) == 1_048_576
        assert exact.items[0].obligation.paths == paths
        index = chars.index("a")
        chars[index] = "é"
        set_paths(tuple("".join(chars[i:i + 512]) for i in range(0, len(chars), 512)))
        with pytest.raises(ApiError) as error:
            source_coverage_page(projected, codec)
        assert error.value.code == "VALIDATION_ERROR"
        assert error.value.details[0].code == "SOURCE_COVERAGE_LIMIT_EXCEEDED"


@pytest.mark.parametrize("change", [dict(current_review_bound=True), dict(review_state="CURRENT"),
    dict(automatic_fidelity_verified=True), dict(review_state="NEEDS_REVIEW")])
def test_summary_rejects_self_contradictory_current_or_fidelity_claims(state, change):
    from pydantic import ValidationError

    identity, _ = _save(state)
    with state.work() as work:
        summary = read_source_coverage(work, identity).summary
    with pytest.raises(ValidationError):
        summary.model_copy(update=change)


def test_public_span_models_reject_inconsistent_domain_evidence(state):
    from pydantic import ValidationError

    from trade_plan_monitor.web.source_coverage_schemas import SourceCoverageIssueView

    identity, _ = _save(state)
    with state.work() as work:
        obligation = read_source_coverage(work, identity).row(0).obligation
    with pytest.raises(ValidationError):
        obligation.model_copy(update=dict(excerpt=obligation.excerpt + "x"))
    with pytest.raises(ValidationError):
        obligation.model_copy(update=dict(obligation_id="a" * 64))
    with pytest.raises(ValidationError):
        SourceCoverageIssueView(code="SOURCE_COVERAGE_REQUIRED", path="source",
                                start=1, end=None, message="Missing span endpoint.")


def test_cursor_cannot_continue_after_actual_metadata_disappears(state):
    identity, _ = _save(state)
    with client_for(state.sessions, state.engine) as (client, _):
        first = page(client, identity, limit=1)
        with state.engine.begin() as connection:
            connection.exec_driver_sql("DROP TABLE source_coverage_assessment")
        before = storage_snapshot(state.engine)
        response = client.get(url(identity), params=dict(limit=1, cursor=first["nextCursor"]))
        assert response.status_code == 409
        assert response.json()["error"]["details"][0]["code"] == "SOURCE_COVERAGE_STALE"
        assert page(client, identity)["summary"]["reason"] == "SOURCE_COVERAGE_UPGRADE_REQUIRED"
        assert storage_snapshot(state.engine) == before


def test_absent_proof_is_not_inferred_to_be_legacy_from_version_or_time(state, monkeypatch):
    from tests.integration.test_source_coverage_authority import _without_coverage

    identity, _ = _without_coverage(state, monkeypatch)
    with client_for(state.sessions, state.engine) as (client, _):
        value = page(client, identity)
    assert value["summary"]["status"] == "UNKNOWN"
    assert value["summary"]["reason"] == "SOURCE_COVERAGE_REQUIRED"
    assert value["items"] == []


@pytest.mark.parametrize("value", [0, 14288])
def test_valid_signature_cannot_select_empty_or_out_of_range_current_offsets(state, value):
    identity, _ = _save(state)
    with client_for(state.sessions, state.engine) as (client, service):
        with state.work() as work:
            read = read_source_coverage(work, identity)
            token = service._source_coverage_cursor.encode(identity, read.binding(limit=1), value)
        assert client.get(url(identity), params=dict(limit=1, cursor=token)).status_code == 422


@pytest.mark.parametrize("field", ["coverage_review_receipt_hash", "original_review_evidence_hash",
    "mapping_hash", "content_hash", "coverage_evidence_hash", "coverage_bundle_hash",
    "coverage_revision", "review_id", "rules_version"])
def test_current_summary_requires_all_receipt_and_proof_components(state, field):
    from pydantic import ValidationError

    identity, _ = _save(state)
    _confirm(state, identity)
    with state.work() as work:
        summary = read_source_coverage(work, identity).summary
        assert summary.current_review_bound
    with pytest.raises(ValidationError):
        summary.model_copy(update={field: None})


def test_complete_unpersisted_extraction_summary_does_not_require_a_saved_review_bundle(state):
    identity, _ = _save(state)
    with state.work() as work:
        summary = read_source_coverage(work, identity).summary
    unpersisted = summary.model_copy(update=dict(coverage_revision=None, coverage_bundle_hash=None,
        can_confirm_review=False, review_state="UNCONFIRMED"))
    assert unpersisted.coverage_complete and not unpersisted.current_review_bound


def test_missing_actual_human_registration_is_diagnostic_without_repair_or_old_current_rows(state):
    from sqlalchemy import delete

    from trade_plan_monitor.domain.daily_hash import daily_hash
    from trade_plan_monitor.state.source_coverage_authority import (
        SourceCoverageAuthorityError,
        require_current_coverage,
    )

    identity = save_supplemented(state)
    with client_for(state.sessions, state.engine) as (client, _):
        first = page(client, identity, limit=1)
        assert first["summary"]["coverageComplete"] and first["nextCursor"]
        with state.work() as work:
            details = work.plans.get_version_details(identity)
            registration = daily_hash("daily-human-supplements-v1", dict(
                symbol=details.symbol, content_hash=details.content_hash))
            work.daily.session.execute(delete(DailyRecord).where(DailyRecord.id == registration))
            work.commit()
        before = storage_snapshot(state.engine)
        with state.work() as work:
            details = work.plans.get_version_details(identity)
            with pytest.raises(SourceCoverageAuthorityError, match="^SOURCE_COVERAGE_REQUIRED$"):
                require_current_coverage(work, details)
            diagnostic = read_source_coverage(work, identity)
            assert diagnostic.details == details and diagnostic.stored is None
        current = page(client, identity)
        assert current["summary"]["status"] == "UNKNOWN"
        assert current["summary"]["reason"] == "SOURCE_COVERAGE_REQUIRED"
        assert not current["summary"]["coverageComplete"]
        assert current["summary"]["coverageEvidenceHash"] is None
        assert current["summary"]["coverageBundleHash"] is None
        assert current["items"] == [] and current["totalRows"] == 0
        assert client.get(url(identity), params=dict(limit=1, cursor=first["nextCursor"])
                          ).status_code == 409
        assert storage_snapshot(state.engine) == before
