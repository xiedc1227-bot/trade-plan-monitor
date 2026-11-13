"""Keep actual complete ordinary outputs private across both installed API profiles."""

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from tests.integration.test_daily_plan_chain import OfflineRuntime
from tests.integration.test_runtime_status_projection import _current_status

from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.runtime.status_authority import condition_completion_matches
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.daily_state_models import DailyEvaluationState
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.persistent_monitor_read_service import PersistentMonitorReadService
from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle
from trade_plan_monitor.web.routers.daily_plans import DailyEvaluationApiView


@pytest.fixture(params=[1, 2], ids=["compatibility-v1", "canonical-v2"])
def installed_api(tmp_path, monkeypatch, request):
    case = _current_status(tmp_path, monkeypatch)
    plans = PersistentPlanWebLifecycle(
        database_path=tmp_path / "daily.sqlite", clock=lambda: case.now)
    reader = (case.reader if request.param == 2 else PersistentMonitorReadService(
        case.work, lambda: case.current[0].health, clock=lambda: case.now))
    app = create_app(runtime_factory=lambda: OfflineRuntime(None),
                     monitor_contract_version=request.param, read_service=reader,
                     plan_lifecycle_factory=lambda: plans)
    headers = {"X-Monitor-Contract-Version": str(request.param)}
    try:
        with TestClient(app, base_url="http://127.0.0.1:8765", headers=headers) as client:
            yield SimpleNamespace(case=case, plans=plans, reader=reader, app=app,
                                  client=client, version=request.param)
    finally:
        case.close()


def assert_private_output_absent(value):
    if isinstance(value, dict):
        assert "ordinaryEvaluations" not in value
        assert "ordinary_evaluations" not in value
        for child in value.values():
            assert_private_output_absent(child)
    elif isinstance(value, list):
        for child in value:
            assert_private_output_absent(child)


def test_actual_saved_outputs_stay_internal_in_daily_and_nested_monitor_responses(installed_api):
    env, case = installed_api, installed_api.case
    original = canonical(case.result.snapshot)
    expected = case.result.snapshot["ordinary_evaluations"]
    assert len(expected) == 2
    assert expected[0]["evidence"]["children"]
    native = DailyEvaluationState.model_validate_json(original)
    api = DailyEvaluationApiView.model_validate_json(original)
    assert api.ordinary_evaluations == native.ordinary_evaluations
    # The public child keeps the same parent validation, even for excluded values.
    invalid = deepcopy(case.result.snapshot)
    invalid["ordinary_evaluations"][0]["review_id"] = "different-review"
    with pytest.raises(ValidationError, match="crosses its actual evaluation owner"):
        DailyEvaluationApiView.model_validate_json(canonical(invalid))
    for rows in ([], [expected[0], expected[0]], [expected[0]] * 3):
        invalid["ordinary_evaluations"] = rows
        with pytest.raises(ValidationError):
            DailyEvaluationApiView.model_validate_json(canonical(invalid))
    daily = env.client.get("/api/v1/plan-runtime/" + case.plan.symbol)
    assert daily.status_code == 200, daily.text
    body = daily.json()
    assert body["status"] == "CURRENT"
    assert body["snapshot"]["reviewId"] == case.result.snapshot["review_id"]
    assert body["snapshot"]["signals"]
    assert_private_output_absent(body)
    assert_private_output_absent(json.loads(api.model_dump_json(by_alias=True)))
    if env.version == 2:
        # These are real parent response models containing the same API child.
        for path, key in (("/dashboard", "symbols"), ("/symbols", "items"),
                          ("/symbols/" + case.plan.symbol, "summary")):
            response = env.client.get("/api/v1" + path)
            assert response.status_code == 200, response.text
            parent = response.json()
            entry = parent[key] if key == "summary" else parent[key][0]
            assert entry["planFamily"] == "CONDITION_PLAN"
            assert entry["planRuntime"]["reviewId"] == case.result.snapshot["review_id"]
            assert_private_output_absent(parent)
    internal = asyncio.run(env.plans.read_daily(symbol=case.plan.symbol, trade_date=None))
    assert internal.snapshot.ordinary_evaluations == native.ordinary_evaluations
    assessed = asyncio.run(case.reader.get_plan_readiness(
        version_id=case.result.snapshot["plan_version_id"]))
    sell = next(rule for rule in assessed.rules if rule.facts.owner_id == "sell-100")
    assert sell.state == "CONDITION_FALSE"
    assert sell.facts.root_outcome == "UNSATISFIED"
    assert sell.facts.leaves[0].evidence_refs
    proof = case.current[0].plans[0].completion
    with case.sessions() as session, session.begin():
        assert session.get(DailyRecord, "evaluation-head-" + case.plan.symbol).payload_json == (
            original)
        assert session.get(DailyRecord, proof.input_stamp.immutable_record_id).payload_json == (
            original)
        assert condition_completion_matches(session, proof=proof,
                                            snapshot=case.result.snapshot, now=case.now)


def test_configured_serialization_schema_keeps_the_old_public_surface(installed_api):
    schemas = installed_api.app.openapi()["components"]["schemas"]
    properties = schemas["DailyEvaluationApiView"]["properties"]
    assert "ordinaryEvaluations" not in properties
    assert "ordinary_evaluations" not in properties
    assert "DailyOrdinaryEvaluation" not in schemas
    readiness = installed_api.app.openapi()["paths"][
        "/api/v1/plan-versions/{version_id}/monitor-readiness"]["get"]
    assert readiness["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ReadinessAssessment"}
    assert schemas["ReadinessAssessment"]["properties"]["snapshot"] == {
        "$ref": "#/components/schemas/ReadinessSnapshot"}
    assert schemas["ReadinessSnapshot"]["properties"]["rules"]["items"] == {
        "$ref": "#/components/schemas/RuleReadinessFacts"}

    def references(value):
        if isinstance(value, dict):
            return {value["$ref"]} if "$ref" in value else set().union(
                *(references(child) for child in value.values()))
        if isinstance(value, list):
            return set().union(*(references(child) for child in value))
        return set()

    for name in ("expectedTarget", "evaluatedTarget"):
        assert references(schemas["RuleReadinessFacts"]["properties"][name]) == {
            "#/components/schemas/IntradayEvaluationTarget",
            "#/components/schemas/OfficialCloseEvaluationTarget"}
    # Exclusion belongs only to the public serialization boundary.
    validation = DailyEvaluationApiView.model_json_schema(mode="validation", by_alias=True)
    assert "ordinaryEvaluations" in validation["properties"]
    assert "ordinary_evaluations" in DailyEvaluationState.model_json_schema()["properties"]
