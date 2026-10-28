"""The browser fixture must establish real source state, never synthetic grants."""

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from tests.browser.source_coverage_server import (
    MARKUP,
    PREFIX,
    TURNOVER,
    _request_server_shutdown,
    create_fixture_app,
)
from tests.integration.test_market_linkage_review import source_mapping
from tests.integration.test_source_treatment_review_api import literal_draft

from trade_plan_monitor.domain.daily_plan_validation import daily_draft_json
from trade_plan_monitor.state.source_coverage_store import SourceCoverageStore


@pytest.fixture
def workspace(tmp_path):
    app = create_fixture_app(tmp_path)
    with TestClient(
        app,
        base_url="http://127.0.0.1:8765",
        client=("127.0.0.1", 50000),
        headers={"X-Monitor-Contract-Version": "2"},
    ) as client:
        yield client, app.state.source_fixture


def post(client, path, payload, *, expected=200, key=None):
    result = client.post(path, json=payload, headers={"Idempotency-Key": key or uuid4().hex})
    assert result.status_code == expected, result.text
    return result.json()


def seed(client, scenario="complete", generation=1):
    setup = post(client, PREFIX + "/setup", {"scenario": scenario, "generation": generation})
    result = client.get("/api/v1/plan-versions/" + setup["planVersionId"])
    assert result.status_code == 200, result.text
    return result.json()


def coverage(client, identity, **params):
    result = client.get(f"/api/v1/plan-versions/{identity}/source-coverage", params=params)
    assert result.status_code == 200, result.text
    assert len(result.content) <= 1_048_576
    return result.json()


def review_command(saved):
    source = saved["sourceCoverage"]
    return dict(
        planVersionId=saved["id"],
        contentHash=saved["contentHash"],
        sourceHash=saved["sourceHash"],
        reviewEvidenceHash=saved["reviewEvidenceHash"],
        expectedRevision=saved["reviewRevision"],
        coverageEvidenceHash=source["coverageEvidenceHash"],
        coverageRulesVersion=source["rulesVersion"],
    )


def activation_command(saved, reviewed):
    return dict(
        planVersionId=saved["id"],
        contentHash=saved["contentHash"],
        sourceHash=saved["sourceHash"],
        reviewEvidenceHash=saved["reviewEvidenceHash"],
        reviewId=reviewed["reviewId"],
        reviewRevision=reviewed["revision"],
        expectedRevision=0,
    )


def assert_conflict(value, reason):
    assert value["error"]["code"] == "CONFLICT"
    assert reason in {item["code"] for item in value["error"]["details"]}


def test_setup_saves_a_complete_but_unreviewed_human_draft(tmp_path):
    app = create_fixture_app(tmp_path)
    assert list(tmp_path.iterdir()) == []
    with TestClient(app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50000)) as client:
        setup = client.post(
            "/_test/source-coverage/setup",
            json={"scenario": "complete"},
            headers={"Idempotency-Key": "fixture-complete"},
        )
        assert setup.status_code == 200, setup.text
        identity = setup.json()["planVersionId"]
        detail = client.get("/api/v1/plan-versions/" + identity).json()
        assert detail["status"] == "DRAFT"
        assert detail["canActivate"] is False
        assert detail["reviewId"] is None
        assert detail["reviewRevision"] == 0
        assert detail["sourceCoverage"]["coverageComplete"] is True
        assert detail["sourceCoverage"]["origin"] == "HUMAN"
        assert detail["sourceCoverage"]["automaticFidelityVerified"] is False
        assert detail["sourceCoverage"]["currentReviewBound"] is False
        assert detail["sourceCoverage"]["canConfirmReview"] is True


def test_real_read_confirm_activate_and_missing_binding_preserve_separate_authorities(workspace):
    client, state = workspace
    saved = seed(client)
    before = state.snapshot()
    for _ in range(2):
        page = coverage(client, saved["id"])
        assert page["authorityGranted"] is False
        assert page["summary"]["authorityGranted"] is False
        assert page["returnedCount"] <= 50
        assert page["nextCursor"] is not None
        assert client.get("/api/v1/plan-versions/" + saved["id"]).status_code == 200
        # The whole workspace also restores supplements via this existing
        # read-only POST; only the coverage pane itself is GET-only.
        preview = post(
            client,
            "/api/v1/plan-review-previews",
            dict(
                candidateJson=saved["planJson"],
                sourceText=saved["sourceText"],
                mapping=saved["dailyMapping"],
            ),
        )
        assert preview["review"]["content_hash"] == saved["contentHash"]
        assert preview["review"]["issues"] == []
    assert state.snapshot() == before
    assert before["source_coverage_review"]["count"] == before["active_plan"]["count"] == 0
    assert all(
        before[table]["count"] == 0
        for table in ("position_lot", "evaluation_ledger", "alert_event", "delivery_attempt")
    )
    assert set(before["dailyKinds"]) <= {"REVIEW"}

    missing = review_command(saved)
    missing.pop("coverageEvidenceHash")
    missing.pop("coverageRulesVersion")
    assert_conflict(
        post(client, "/api/v1/plan-review-confirmations", missing, expected=409),
        "SOURCE_COVERAGE_REQUIRED",
    )
    assert state.snapshot() == before
    reviewed = post(client, "/api/v1/plan-review-confirmations", review_command(saved))
    assert reviewed["canActivate"] is True
    assert state.snapshot()["active_plan"]["count"] == 0
    current = coverage(client, saved["id"])["summary"]
    assert current["currentReviewBound"] and current["reviewState"] == "CURRENT"
    with state.lifecycle._session_factory() as session:
        receipt = SourceCoverageStore(session).receipt(reviewed["reviewId"])
        assert receipt.evidence_hash == current["coverageReviewReceiptHash"]
        assert receipt.coverage_evidence_hash == saved["sourceCoverage"]["coverageEvidenceHash"]
    active = post(client, "/api/v1/plan-activations", activation_command(saved, reviewed))
    assert active["active"] is True and active["planVersionId"] == saved["id"]
    assert state.snapshot()["position_lot"]["count"] == 0
    assert state.no_io.attempts == []


@pytest.mark.parametrize("scenario,marker", [("mislabelled", TURNOVER), ("xss-emoji", MARKUP)])
def test_mislabelled_mandatory_and_markup_remain_blocked_even_before_their_page(
    workspace, scenario, marker
):
    client, state = workspace
    saved = seed(client, scenario)
    assert marker in saved["sourceText"]
    assert saved["dailyIssues"] == []  # Historical zero issues is not current completeness.
    first = coverage(client, saved["id"])
    assert first["summary"]["status"] == "BLOCKED"
    assert first["summary"]["issueCount"] > 0
    assert first["summary"]["currentReviewBound"] is False
    assert all(
        row["kind"] == "OBLIGATION" and row["obligation"]["serverState"] == "MAPPED"
        for row in first["items"]
    )
    rows, page = list(first["items"]), first
    while page["nextCursor"] is not None:
        page = coverage(client, saved["id"], cursor=page["nextCursor"])
        rows.extend(page["items"])
    assert [row["rowIndex"] for row in rows] == list(range(first["totalRows"]))
    (obligation,) = [
        row["obligation"]
        for row in rows
        if row["kind"] == "OBLIGATION" and row["obligation"]["excerpt"] == marker
    ]
    assert obligation["mappingProposal"]["proposedDisposition"] == "CONTEXT"
    assert obligation["mappingProposal"]["semanticRole"] == "COMMENTARY"
    assert obligation["serverState"] == "UNRESOLVED"
    assert saved["sourceText"][obligation["start"] : obligation["end"]] == marker
    assert obligation["end"] - obligation["start"] == len(marker)
    before = state.snapshot()
    assert_conflict(
        post(client, "/api/v1/plan-review-confirmations", review_command(saved), expected=409),
        "SOURCE_COVERAGE_REQUIRED",
    )
    assert state.snapshot() == before
    assert before["source_coverage_review"]["count"] == before["active_plan"]["count"] == 0


def supplement_and_preview(client, candidate, source, mapping):
    preview = post(
        client,
        "/api/v1/plan-review-previews",
        dict(candidateJson=json.dumps(candidate), sourceText=source, mapping=mapping),
    )
    digest = preview["review"]["content_hash"]
    post(
        client,
        "/api/v1/plan-review-supplements",
        dict(
            candidateJson=preview["candidateJson"],
            contentHash=digest,
            expectedRevision=preview["supplementRevision"],
            supplements=[
                dict(
                    supplement_id="browser-explicit-maximum",
                    candidate_content_hash=digest,
                    path="position.max_qty",
                    value=candidate["position"]["max_qty"],
                    reason=(
                        "Human supplies the explicitly missing maximum; "
                        "no source condition is waived."
                    ),
                )
            ],
        ),
    )
    return post(
        client,
        "/api/v1/plan-review-previews",
        dict(
            candidateJson=preview["candidateJson"],
            sourceText=source,
            mapping=preview["review"]["mapping"],
        ),
    )


def test_explicit_null_is_repaired_only_by_actual_registered_supplement_and_new_version(workspace):
    client, state = workspace
    original = seed(client, "missing-cap")
    assert "position.max_qty = null" in original["sourceText"]
    assert original["sourceCoverage"]["coverageComplete"] is False
    candidate = json.loads(original["planJson"])
    assert candidate["position"]["max_qty"] is None
    candidate["position"]["max_qty"] = 300
    candidate["version"] += 1
    preview = supplement_and_preview(
        client, candidate, original["sourceText"], original["dailyMapping"]
    )
    saved = post(
        client,
        "/api/v1/plan-drafts",
        dict(
            planJson=preview["candidateJson"],
            sourceText=original["sourceText"],
            dailyMapping=preview["review"]["mapping"],
            expectedRevision=0,
            basePlanVersionId=original["id"],
        ),
    )
    assert saved["id"] != original["id"]
    assert saved["sourceHash"] == original["sourceHash"]
    assert saved["contentHash"] != original["contentHash"]
    assert saved["sourceCoverage"]["coverageComplete"] is True
    assert saved["sourceCoverage"]["origin"] == "HUMAN"
    assert saved["sourceCoverage"]["automaticFidelityVerified"] is False
    assert saved["sourceCoverage"]["currentReviewBound"] is False
    assert saved["sourceCoverage"]["canConfirmReview"] is True
    assert saved["reviewId"] is None and not saved["canActivate"]
    reloaded = client.get("/api/v1/plan-versions/" + original["id"]).json()
    assert reloaded["planJson"] == original["planJson"]
    assert state.snapshot()["source_coverage_review"]["count"] == 0


def test_supplement_does_not_override_a_known_nonnull_source_value(workspace):
    client, state = workspace
    draft = literal_draft(complete=True)
    source, mapping = source_mapping(draft)
    original = post(
        client,
        "/api/v1/plan-drafts",
        dict(
            planJson=daily_draft_json(draft),
            sourceText=source,
            dailyMapping=mapping.model_dump(mode="json"),
            expectedRevision=0,
        ),
    )
    assert "position.max_qty = 300" in source
    candidate = json.loads(original["planJson"])
    candidate["position"]["max_qty"] = 500
    candidate["version"] += 1
    preview = supplement_and_preview(client, candidate, source, original["dailyMapping"])
    saved = post(
        client,
        "/api/v1/plan-drafts",
        dict(
            planJson=preview["candidateJson"],
            sourceText=source,
            dailyMapping=preview["review"]["mapping"],
            expectedRevision=0,
            basePlanVersionId=original["id"],
        ),
    )
    assert saved["sourceCoverage"]["coverageComplete"] is False
    before = state.snapshot()
    assert_conflict(
        post(client, "/api/v1/plan-review-confirmations", review_command(saved), expected=409),
        "SOURCE_COVERAGE_REQUIRED",
    )
    assert state.snapshot() == before


def test_other_tab_and_bundle_advance_reject_stale_commands_without_rewriting_receipt(
    workspace,
):
    client, state = workspace
    saved = seed(client)
    first_page = coverage(client, saved["id"])
    old = review_command(saved)
    reviewed = post(client, "/api/v1/plan-review-confirmations", old, key="actual-first-review")
    before = state.snapshot()
    # A stale numeric CAS uses the existing CONFLICT envelope. A source bundle
    # mismatch below has its separate exact SOURCE_COVERAGE_STALE diagnostic.
    conflict = post(
        client, "/api/v1/plan-review-confirmations", old, key="other-tab-old-revision", expected=409
    )
    assert conflict["error"]["code"] == "CONFLICT"
    assert state.snapshot() == before
    changed = post(
        client,
        PREFIX + "/reassess/" + saved["id"],
        {"expectedRevision": first_page["summary"]["coverageRevision"]},
    )
    assert changed["coverageRevision"] == first_page["summary"]["coverageRevision"] + 1
    assert changed["coverageBundleHash"] != first_page["summary"]["coverageBundleHash"]
    before = state.snapshot()
    stale = client.get(
        f"/api/v1/plan-versions/{saved['id']}/source-coverage",
        params={"cursor": first_page["nextCursor"]},
    )
    assert stale.status_code == 409, stale.text
    assert_conflict(stale.json(), "SOURCE_COVERAGE_STALE")
    assert_conflict(
        post(client, "/api/v1/plan-activations", activation_command(saved, reviewed), expected=409),
        "SOURCE_COVERAGE_STALE",
    )
    current = coverage(client, saved["id"])["summary"]
    assert not current["currentReviewBound"] and current["reason"] == "SOURCE_COVERAGE_STALE"
    assert state.snapshot() == before
    assert before["source_coverage_review"]["count"] == 1


def test_two_source_versions_have_distinct_actual_owners_and_neither_is_auto_reviewed(workspace):
    client, state = workspace
    first, second = seed(client, "source-version", 1), seed(client, "source-version", 2)
    assert first["planId"] == second["planId"] and first["version"] + 1 == second["version"]
    assert first["id"] != second["id"] and first["sourceHash"] != second["sourceHash"]
    assert first["contentHash"] != second["contentHash"]
    assert (
        first["sourceCoverage"]["canConfirmReview"] and second["sourceCoverage"]["canConfirmReview"]
    )
    assert state.snapshot()["source_coverage_review"]["count"] == 0
    assert state.snapshot()["active_plan"]["count"] == 0

    before = state.snapshot()
    old_exact_binding = review_command(first)
    old_exact_binding["planVersionId"] = second["id"]
    assert_conflict(
        post(client, "/api/v1/plan-review-confirmations", old_exact_binding, expected=409),
        "SOURCE_COVERAGE_STALE",
    )
    assert state.snapshot() == before
    for saved in (first, second):
        revised = post(
            client,
            PREFIX + "/reassess/" + saved["id"],
            {"expectedRevision": saved["sourceCoverage"]["coverageRevision"]},
        )
        assert revised["coverageRevision"] == saved["sourceCoverage"]["coverageRevision"] + 1


def test_disabled_configuration_and_every_external_capability_fail_without_external_io(workspace):
    client, state = workspace
    before = state.snapshot()
    health = client.get("/api/v1/health")
    assert health.status_code == 200, health.text
    assert health.json()["monitorContractVersion"] == 2
    assert health.json()["providers"] == []
    assert health.json()["lastCompletedMinute"] is None
    assert health.json()["latestEvaluationAt"] is None
    configured = client.get("/api/v1/ai-runtime").json()
    assert configured["configured"] is False and configured["enabled"] is False
    assert configured["maxInputChars"] == 50000 and configured["maxOutputTokens"] == 4096
    post(
        client,
        "/api/v1/plan-extractions",
        dict(
            providerId=configured["providerId"],
            sourceText="Synthetic offline source",
            expectedRevision=0,
        ),
        expected=503,
    )
    assert state.no_io.attempts == []
    assert state.snapshot() == before
    for acquire in (
        state.no_io.acquire_provider,
        state.no_io.acquire_market_data,
        state.no_io.send_notification,
    ):
        with pytest.raises(AssertionError, match="External I/O is prohibited"):
            acquire()
    assert state.no_io.attempts == ["provider", "market", "notification"]


def test_loopback_origin_closed_setup_and_safe_shutdown_are_confined_to_owned_temp_files(tmp_path):
    with TemporaryDirectory(dir=tmp_path, prefix="owned-fixture-") as directory:
        root = Path(directory)
        app = create_fixture_app(root)
        assert list(root.iterdir()) == []
        with TestClient(
            app, base_url="http://127.0.0.1:8765", client=("198.51.100.2", 50000)
        ) as remote:
            result = remote.post(
                PREFIX + "/setup",
                json={"scenario": "complete"},
                headers={"Idempotency-Key": "remote"},
            )
            assert result.status_code == 403
            assert app.state.source_fixture.snapshot()["plan_version"]["count"] == 0
        with pytest.raises(ValueError, match="fresh temporary"):
            create_fixture_app(root)
        # Reuse only the owned app/lifecycle. A new fixture cannot reopen
        # this existing database path.
        with TestClient(
            app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50000)
        ) as client:
            result = client.post(
                PREFIX + "/setup",
                json={"scenario": "complete"},
                headers={"Origin": "https://outside.invalid", "Idempotency-Key": "outside"},
            )
            assert result.status_code == 403
            result = client.post(
                PREFIX + "/setup",
                json={"scenario": "complete", "userDatabase": "elsewhere"},
                headers={"Idempotency-Key": "extra-field"},
            )
            assert result.status_code == 422
            result = client.get(PREFIX + "/isolation")
            assert result.json()["temporary"] is True
            assert Path(result.json()["database"]).parent == root
            before = app.state.source_fixture.snapshot()
            called = []
            app.state.source_fixture.shutdown = lambda: called.append(True)
            assert client.post(PREFIX + "/shutdown").json() == {"shutdownRequested": True}
            assert called == [True]
            assert app.state.source_fixture.snapshot() == before
        assert app.state.source_fixture_lifecycle._engine is None
    assert not root.exists()


def test_static_spa_keeps_fixture_json_routes_reachable(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    index = "<!doctype html><html><body>Isolated source fixture</body></html>"
    (assets / "index.html").write_text(index, encoding="utf-8")
    (assets / "monitor-contract.json").write_text(
        '{"monitorContractVersion":2}\n', encoding="utf-8"
    )
    database_root = tmp_path / "database"
    database_root.mkdir()
    app = create_fixture_app(database_root, static_directory=assets)
    with TestClient(
        app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50000)
    ) as client:
        for endpoint in ("isolation", "inspect"):
            result = client.get(PREFIX + "/" + endpoint)
            assert result.status_code == 200
            assert result.headers["content-type"].startswith("application/json"), result.text
            assert isinstance(result.json(), dict)
        assert client.get("/plans/isolated-spa-route").text == index
        saved = seed(client)
        assert coverage(client, saved["id"])["summary"]["canConfirmReview"] is True


def test_shutdown_awaits_the_owned_async_transport_cleanup(workspace):
    client, state = workspace
    completed = []

    async def cleanup():
        await asyncio.sleep(0)
        completed.append(True)

    state.shutdown = cleanup
    assert client.post(PREFIX + "/shutdown").json() == {"shutdownRequested": True}
    assert completed == [True]


def test_shutdown_waits_for_websocket_transport_exit_without_waiting_on_its_http_request():
    closing = []

    class Connection:
        def __init__(self, kind):
            self.scope = {"type": kind}
            self.transport = SimpleNamespace(close=lambda: closing.append(kind))

    async def scenario():
        websocket, http, unstarted_http = (
            Connection("websocket"), Connection("http"), Connection("http")
        )
        unstarted_http.scope = None
        connections = {websocket, http, unstarted_http}
        server = SimpleNamespace(
            should_exit=False, server_state=SimpleNamespace(connections=connections)
        )
        cleanup = asyncio.create_task(_request_server_shutdown(server))
        await asyncio.sleep(0)
        assert not cleanup.done() and server.should_exit is False
        assert closing == ["websocket"]
        connections.remove(websocket)
        await cleanup
        assert server.should_exit is True and connections == {http, unstarted_http}

    asyncio.run(scenario())


def test_shutdown_reports_an_unclosed_websocket_instead_of_acknowledging_success():
    async def scenario():
        server = SimpleNamespace(should_exit=False, server_state=SimpleNamespace(
            connections=[SimpleNamespace(scope={"type": "websocket"},
                transport=SimpleNamespace(close=lambda: None))]
        ))
        with pytest.raises(TimeoutError):
            await _request_server_shutdown(server, timeout_seconds=0.02)
        assert server.should_exit is False

    asyncio.run(scenario())


def test_actual_source_reads_and_restoring_preview_issue_no_sql_writes(workspace):
    client, state = workspace
    saved = seed(client)
    before = state.snapshot()
    engine = state.lifecycle._engine
    assert engine is not None
    writes = []

    def capture(_connection, _cursor, statement, _parameters, context, _many):
        normalized = " ".join(statement.upper().split())
        first = normalized.partition(" ")[0]
        if (
            context.isinsert or context.isupdate or context.isdelete
            or first in {"INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "ALTER", "DROP"}
            or normalized.startswith("BEGIN IMMEDIATE")
        ):
            writes.append(first)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        coverage(client, saved["id"])
        detail = client.get("/api/v1/plan-versions/" + saved["id"])
        assert detail.status_code == 200
        post(client, "/api/v1/plan-review-previews", dict(
            candidateJson=saved["planJson"], sourceText=saved["sourceText"],
            mapping=saved["dailyMapping"],
        ))
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert writes == []
    assert state.snapshot() == before
