"""Real HTTP capital resources using the strict pre-admission private plan harness."""

import pytest
from tests.integration.p3_private_chain import PrivateChain
from tests.integration.test_daily_plan_chain import Chain
from tests.integration.test_p3_storage import database
from tests.integration.test_unified_simulation_transactions import ledger_dump

__all__ = ["database"]


@pytest.fixture
def capital_api(database, tmp_path, monkeypatch):
    engine, path = database
    private = PrivateChain(engine, monkeypatch, mode="OPEN_COST_CAP", quantity=400)
    shell = Chain(tmp_path)
    from trade_plan_monitor.web import p3_service
    monkeypatch.setattr(p3_service, "load_plan_json", type(private.plan).model_validate_json)
    with shell.client:
        monkeypatch.setattr(shell.plans, "_unit_of_work", private.work)
        monkeypatch.setattr(shell.plans, "_clock", lambda: private.now)
        yield private, shell, path


def test_preview_and_book_http_are_read_only_and_never_grant_authority(capital_api):
    private, shell, path = capital_api
    private.evaluate()
    before = ledger_dump(path)
    result = shell.post("plan-capital-previews", {"planVersionId": private.version_id,
        "ruleId": private.plan.ordinary_rules[0].rule_id})
    assert result["quantity"] == 200
    assert result["assessment"]["outcome"] == "UNKNOWN"
    assert result["assessment"]["blockers"] == ["CAPITAL_BASE_UNKNOWN"]
    assert result["authorityGranted"] is False
    book = shell.client.get("/api/v1/simulation-capital-books/"+private.plan.symbol)
    assert book.status_code == 200
    assert book.json()["book"] is None and book.json()["retainedBasisFen"] is None
    assert book.json()["authorityGranted"] is False
    assert ledger_dump(path) == before


def test_opening_receipt_retry_and_preview_use_complete_reviewed_lots(capital_api):
    private, shell, path = capital_api
    with private.work() as work:
        batches = work.daily.get("simulation-position-"+private.plan.symbol)["payload"]["batches"]
    body = dict(planVersionId=private.version_id, expectedInventoryRevision=1,
        expectedBookRevision=0, observedAt=private.now.isoformat(),
        source="Synthetic reviewed simulation opening",
        excerpt="Retained basis of the current complete lot is450000fen",
        reason="Explicit budget opening confirmation", confirmed=True,
        lots=[dict(lot_id=b["id"], bucket=b["bucket"], quantity=b["quantity"],
                   retained_basis_fen=450000) for b in batches])
    first = shell.post("simulation-capital-openings", body, key="opening-once")
    assert first["inventoryChanged"] is first["authorityGranted"] is False
    assert first["event"]["book"]["revision"] == 1
    assert shell.post("simulation-capital-openings", body, key="opening-once") == first
    changed = body | {"reason": "Changed request"}
    shell.post("simulation-capital-openings", changed, key="opening-once", status=409)
    private.evaluate()
    before = ledger_dump(path)
    preview = shell.post("plan-capital-previews", {"planVersionId": private.version_id,
        "ruleId": private.plan.ordinary_rules[0].rule_id})
    assert preview["assessment"]["after_fen"] == 482700
    assert preview["assessment"]["outcome"] == "PASS"
    assert ledger_dump(path) == before


@pytest.mark.parametrize("field", ["priceFen", "retainedBasisFen", "capacity", "approval"])
def test_preview_rejects_caller_financial_authority(capital_api, field):
    private, shell, _ = capital_api
    shell.post("plan-capital-previews", {"planVersionId": private.version_id,
        "ruleId": private.plan.ordinary_rules[0].rule_id, field: 1}, status=422)


def test_capital_http_requires_same_origin_and_idempotency_header(capital_api):
    private, shell, _ = capital_api
    body = {"planVersionId": private.version_id, "ruleId": private.plan.ordinary_rules[0].rule_id}
    response = shell.client.post("/api/v1/plan-capital-previews", json=body)
    assert response.status_code == 422
    response = shell.client.post("/api/v1/plan-capital-previews", json=body,
        headers={"Idempotency-Key": "cross-site", "Origin": "https://untrusted.example"})
    assert response.status_code == 403
