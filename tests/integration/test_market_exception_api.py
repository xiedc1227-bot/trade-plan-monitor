"""Public exception commands retain same-origin, revision and explicit-human fences."""

from datetime import datetime, time

from tests.integration import test_market_exception_runtime as runtime_fixture
from tests.integration.test_daily_plan_chain import SH, TUESDAY
from tests.integration.test_market_exception_runtime import exception_inputs

exception_chain = runtime_fixture.exception_chain


def pending(chain):
    result = chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
    return result.snapshot["exception_candidates"][0]


def test_public_preview_approve_and_separate_simulation(exception_chain):
    chain = exception_chain
    row = pending(chain)
    shown = chain.post("plan-exception-previews", dict(
        candidateId=row["candidate"]["candidate_id"], expectedRevision=1,
        proposedQuantity=None if chain.route == "WEAK_MINIMUM" else 300))
    assert shown["quantity"] == (100 if chain.route == "WEAK_MINIMUM" else 300)
    command = dict(commandId="approve", candidateId=shown["candidateId"], expectedRevision=1,
        decision="APPROVE", reason="Reviewed exact quantity", previewId=shown["previewId"],
        previewHash=shown["previewHash"])
    result = chain.post("plan-exception-decisions", command, key="approve-http")
    assert result["candidate"]["state"] == "APPROVED"
    assert chain.post("plan-exception-decisions", command, key="approve-http") == result
    with chain.plans._unit_of_work() as work:
        assert work.daily.list(symbol=chain.plan.symbol, kind="SIMULATION") == ()
        assert work.daily.get(result["candidate"]["candidate_id"])["payload"]["state"] == "APPROVED"
    chain.now = datetime.combine(TUESDAY, time(9, 35), SH)
    ready = chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
    assert chain.simulate(ready.snapshot["signals"][0])["quantity"] == shown["quantity"]


def test_public_commands_reject_missing_forged_and_cross_origin(exception_chain):
    chain = exception_chain
    row = pending(chain)
    candidate_id = row["candidate"]["candidate_id"]
    data = dict(candidateId=candidate_id, expectedRevision=1, proposedQuantity=300)
    if chain.route == "WEAK_MINIMUM":
        data["proposedQuantity"] = None
    response = chain.client.post("/api/v1/plan-exception-previews", json=data,
        headers={"Origin": "https://foreign.example", "Idempotency-Key": "foreign"})
    assert response.status_code == 403
    chain.post("plan-exception-previews", data | {"authorizedQuantity": 100}, status=422)
    chain.post("plan-exception-previews", data | {"candidateId": "f"*64}, status=404)
    chain.post("plan-exception-previews", data | {"expectedRevision": 99}, status=409)
    chain.post("plan-exception-decisions", dict(commandId="forged", candidateId=candidate_id,
        expectedRevision=1, decision="APPROVE", reason="Missing preview"), status=422)
    if chain.route == "BROKEN_STRONG":
        chain.post("plan-exception-previews", data | {"proposedQuantity": None}, status=422)


def test_public_rejection_does_not_require_preview(exception_chain):
    chain = exception_chain
    row = pending(chain)
    result = chain.post("plan-exception-decisions", dict(commandId="reject",
        candidateId=row["candidate"]["candidate_id"], expectedRevision=1,
        decision="REJECT", reason="Decline occurrence"))
    assert result["candidate"]["state"] == "REJECTED"
    chain.post("plan-exception-previews", dict(candidateId=row["candidate"]["candidate_id"],
        expectedRevision=2, proposedQuantity=None), status=409)


def test_public_revocation_and_unavailable_storage(exception_chain, monkeypatch):
    chain = exception_chain
    row = pending(chain)
    shown = chain.post("plan-exception-previews", dict(
        candidateId=row["candidate"]["candidate_id"], expectedRevision=1,
        proposedQuantity=None if chain.route == "WEAK_MINIMUM" else 300))
    approved = chain.post("plan-exception-decisions", dict(
        commandId="approve", candidateId=shown["candidateId"], expectedRevision=1,
        decision="APPROVE", reason="Reviewed", previewId=shown["previewId"],
        previewHash=shown["previewHash"]))
    revoked = chain.post("plan-exception-revocations", dict(commandId="revoke",
        approvalId=approved["event"]["event_id"], expectedRevision=2, reason="Withdraw"))
    assert revoked["candidate"]["state"] == "REVOKED"
    with chain.plans._unit_of_work() as work:
        assert work.daily.list(symbol=chain.plan.symbol, kind="SIMULATION") == ()
    monkeypatch.setattr(chain.plans, "_session_factory", None)
    chain.post("plan-exception-previews", dict(candidateId=shown["candidateId"],
        expectedRevision=3, proposedQuantity=None), status=503)


def test_public_schema_advertises_complete_exception_policy(exception_chain):
    response = exception_chain.client.get("/api/v1/plan-editor-schema")
    assert response.status_code == 200
    data = response.json()
    assert data["supportedSchemaVersions"] == [5, 6, 7]
    assert len(data["exceptionPolicyDefinitions"]) == 11
    assert data["exceptionCandidateSchema"]["properties"]["schema_version"]["const"] == 7
