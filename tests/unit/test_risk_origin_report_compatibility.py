"""Old report risk positions omit private provenance and retain native validation."""

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from trade_plan_monitor.backtest.loop_report import LoopEvaluation
from trade_plan_monitor.backtest.research_report import ResearchDecisionEvent
from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.state.daily_state_models import DailyRiskState as StoredRisk

ROOT = Path(__file__).parents[2]
PARENTS = {"loop": LoopEvaluation, "research": ResearchDecisionEvent}
POSITIONS = [("loop", "risks"), ("research", "risks"), ("research", "resulting_risks")]


def snapshot():
    return json.loads(
        (ROOT / "tests/fixtures/pma_legacy_risk_head.json").read_text(encoding="utf-8")
    )["payload"]


def report_data(kind):
    source = snapshot()
    shared = dict(
        evaluation_id="a" * 64,
        official_trade_date=None,
        minute_target=None,
        signals=[],
        risks=[source["risks"][1]],
        alerts=[],
        risk_action=source["risk_action"],
        conditions=[],
        blockers=[],
    )
    if kind == "loop":
        return {**shared, "duplicate": False, "inventory": source["inventory"]}
    return {
        **shared,
        "event_id": "b" * 64,
        "at": source["evaluated_at"],
        "resulting_signals": [],
        "resulting_risks": [deepcopy(source["risks"][1])],
        "inventory_before": source["inventory"],
        "inventory_after": source["inventory"],
    }


def stored():
    return StoredRisk.model_validate_json(canonical(snapshot()["risks"][1]))


@pytest.mark.parametrize("kind,field", POSITIONS)
def test_nonempty_origin_is_not_serialized_at_any_existing_report_risk_position(kind, field):
    data = report_data(kind)
    data[field][0]["origin_evaluation_id"] = "immutable-original-evaluation"
    parsed = PARENTS[kind].model_validate_json(canonical(data))
    output = parsed.model_dump_json()
    body = json.loads(output)
    expected = json.loads(stored().model_dump_json())
    assert body[field][0] == expected
    assert list(body[field][0]) == list(expected)
    assert getattr(parsed, field)[0].model_dump_json() == stored().model_dump_json()
    assert "origin_evaluation_id" not in output and "immutable-original-evaluation" not in output
    assert PARENTS[kind].model_validate_json(output).model_dump_json() == output


@pytest.mark.parametrize("kind", PARENTS)
def test_existing_native_instances_remain_supported_in_the_report_parent(kind):
    native = stored().model_copy(update={"origin_evaluation_id": "immutable-native-origin"})
    internal = native.model_dump_json()
    assert json.loads(internal)["origin_evaluation_id"] == "immutable-native-origin"
    assert StoredRisk.model_validate_json(internal) == native
    values = (
        PARENTS[kind].model_validate_json(canonical(report_data(kind))).model_dump(mode="python")
    )
    values["risks"] = (native,)
    if kind == "research":
        values["resulting_risks"] = (native,)
    parsed = PARENTS[kind].model_validate(values)
    assert parsed.risks[0].model_dump_json() == stored().model_dump_json()
    assert json.loads(parsed.model_dump_json())["risks"][0] == json.loads(
        stored().model_dump_json()
    )
    assert "immutable-native-origin" not in parsed.model_dump_json()
    assert native.model_dump_json() == internal


@pytest.mark.parametrize("kind", PARENTS)
@pytest.mark.parametrize("form", ["dict", "native-instance"])
@pytest.mark.parametrize(
    "change", [{"priority": 2}, {"target_core_qty": 101}, {"status": "PENDING"}]
)
def test_report_projection_preserves_original_invalid_risk_rejection(kind, form, change):
    values = (
        PARENTS[kind].model_validate_json(canonical(report_data(kind))).model_dump(mode="python")
    )
    invalid = {**stored().model_dump(mode="python"), **change}
    values["risks"] = (invalid if form == "dict" else StoredRisk.model_construct(**invalid),)
    with pytest.raises(ValidationError):
        PARENTS[kind].model_validate(values)


@pytest.mark.parametrize("kind,field", POSITIONS)
def test_excluded_origin_still_validates_its_existing_identifier_type(kind, field):
    data = report_data(kind)
    data[field][0]["origin_evaluation_id"] = "not a valid identifier"
    with pytest.raises(ValidationError):
        PARENTS[kind].model_validate_json(canonical(data))


@pytest.mark.parametrize("kind", PARENTS)
def test_report_risk_serialization_schema_is_the_exact_committed_wire_component(kind):
    expected = json.loads((ROOT / "openapi.json").read_text(encoding="utf-8"))["components"][
        "schemas"
    ]["DailyRiskState"]
    schema = PARENTS[kind].model_json_schema(mode="serialization")
    actual = schema["$defs"]["DailyRiskState"]
    # FastAPI omits None defaults when encoding the actual OpenAPI document.
    encoded = jsonable_encoder(actual, exclude_none=True)
    normalized = json.loads(json.dumps(encoded).replace("#/$defs/", "#/components/schemas/"))
    assert normalized == expected
    assert "origin_evaluation_id" not in actual["properties"]
    assert actual["title"] == "DailyRiskState"


def test_original_risk_bytes_remain_unchanged_without_private_origin():
    original = stored().model_dump_json().encode()
    assert len(original) == 739
    assert sha256(original).hexdigest() == (
        "a358bbdcb9df151abc9d0be1a12ba3a4ee6c19076a154f48830c26f1737aba45"
    )
