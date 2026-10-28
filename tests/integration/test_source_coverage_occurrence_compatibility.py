"""Source diagnostics and harmless drafts cannot rearm an actual consumed occurrence."""

from sqlalchemy import text
from tests.integration.test_daily_simulation import command, inventory
from tests.integration.test_market_linkage_review import source_mapping
from tests.integration.test_source_coverage_simulation_actions import (
    _stale,
)
from tests.integration.test_source_coverage_simulation_actions import (
    current as current,
)
from tests.unit.test_source_coverage_baseline import _append_as_context

from trade_plan_monitor.domain.daily_plan_validation import daily_draft_json
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft


def _effects(chain, key):
    # New DRAFT/REVIEW/audit and legitimate EVALUATION rows are allowed writes.
    # POSITION carries the complete simulated lots; original real holdings stay inert.
    with chain.plans._unit_of_work() as work:
        session = work.daily.session
        return {
            "actions": tuple(session.execute(text("SELECT * FROM daily_plan_record "
                "WHERE kind IN ('POSITION','SIMULATION') ORDER BY id")).all()),
            "original_receipt": tuple(session.execute(text("SELECT * FROM request_idempotency "
                "WHERE idempotency_key=:key"), {"key": key}).all()),
            "alerts": tuple(session.execute(text("SELECT * FROM alert_event ORDER BY id")).all()),
            "deliveries": tuple(session.execute(text("SELECT * FROM delivery_attempt ORDER BY id"))
                                .all()),
            "active": tuple(session.execute(text("SELECT * FROM active_plan ORDER BY symbol"))
                            .all()),
            "real_lots": tuple(session.execute(text("SELECT * FROM position_lot ORDER BY id"))
                               .all()),
        }


def _signal(chain, identity):
    with chain.plans._unit_of_work() as work:
        return work.daily.get(identity)


def _assert_consumed(chain, original):
    row = _signal(chain, original["signal_id"])
    payload = row["payload"]
    assert row["id"] == original["signal_id"]
    assert payload["side"] == original["side"]
    assert payload["state"] == "SIMULATED"
    assert payload["planned_qty"] == payload["simulated_qty"] == 100
    assert payload["executable_qty"] == 0
    return row


def test_consumed_buy_sell_survive_reassessment_draft_get_replay_and_fresh_key(current):
    chain, signal = current
    key = "consumed-before-source-diagnostics"
    body = command(chain, signal)
    receipt = chain.post("simulated-trades", body, key=key)
    expected = _effects(chain, key)
    assert expected["original_receipt"]
    before_inventory = inventory(chain)
    _assert_consumed(chain, signal)

    _stale(chain)
    resource = chain.client.get(f"/api/v1/plan-versions/{chain.version['id']}/source-coverage")
    assert resource.status_code == 200, resource.text
    proof = resource.json()["summary"]
    assert proof["coverageComplete"] and not proof["currentReviewBound"]
    assert proof["reviewState"] == "NEEDS_REVIEW"

    draft = UnifiedPlanDraft.from_executable(chain.plan).model_copy(
        update={"version": chain.plan.version + 1})
    source, mapping = source_mapping(draft)
    source, mapping = _append_as_context(source, mapping, "# Trade plan",
        semantic_role="COMMENTARY", misclassification={"disposition": "CONTEXT", "paths": [],
            "reason": "Explicit non-execution heading for this engineering draft"})
    active = chain.client.get("/api/v1/plan-activation-states/" + chain.plan.symbol).json()
    newer = chain.post("plan-drafts", {
        "basePlanVersionId": chain.version["id"], "planJson": daily_draft_json(draft),
        "sourceText": source, "dailyMapping": mapping.model_dump(mode="json"),
        "expectedRevision": active["revision"],
    }, key="harmless-unreviewed-draft")
    assert newer["status"] == "DRAFT" and newer["reviewId"] is None
    assert newer["sourceCoverage"]["coverageComplete"]
    assert not newer["sourceCoverage"]["currentReviewBound"]
    for identity in (chain.version["id"], newer["id"]):
        assert chain.client.get("/api/v1/plan-versions/" + identity).status_code == 200
        read = chain.client.get(f"/api/v1/plan-versions/{identity}/source-coverage")
        assert read.status_code == 200 and read.json()["authorityGranted"] is False
    assert _effects(chain, key) == expected
    assert inventory(chain) == before_inventory
    _assert_consumed(chain, signal)

    assert chain.post("simulated-trades", body, key=key) == receipt
    assert _effects(chain, key) == expected
    latest = _assert_consumed(chain, signal)
    # The fresh attempt uses actual revisions, not a deliberately stale cause/account.
    fresh = body | {"expectedCauseRevision": latest["revision"],
                    "expectedInventoryRevision": inventory(chain)["revision"]}
    rejected = chain.post("simulated-trades", fresh, key="fresh-consumed-intent", status=409)
    assert rejected["error"]["code"] == "CONFLICT"
    assert _effects(chain, key) == expected
    assert inventory(chain) == before_inventory
    _assert_consumed(chain, signal)
