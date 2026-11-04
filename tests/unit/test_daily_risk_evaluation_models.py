"""Closed private native risk facts retain owner, target and legacy API bytes."""

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError
from tests.unit.test_daily_conditions import synthetic_series
from tests.unit.test_daily_plan import synthetic_plan_payload
from tests.unit.test_unified_plan_domain import unified_payload

from trade_plan_monitor.decision import daily_risk
from trade_plan_monitor.decision.unified_conditions import evaluate_unified_condition
from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.daily_plan_models import DailyTradePlan
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.state import daily_state_models as state
from trade_plan_monitor.web.routers.daily_plans import DailyEvaluationApiView, DailyRiskApiView

FIXTURE = Path(__file__).parents[1] / "fixtures" / "pma_legacy_risk_head.json"


def legacy_payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["payload"]


def missing_severe():
    plan = UnifiedTradePlan.model_validate(unified_payload())
    branch = next(item for item in plan.risk_branches if item.kind == "SEVERE_TECHNICAL")
    return evaluate_unified_condition(branch.condition, None)


def owner(payload):
    return {
        key: payload[key]
        for key in (
            "plan_version_id",
            "content_hash",
            "review_id",
            "activation_revision",
            "evaluated_at",
        )
    }


@pytest.fixture
def native_payload():
    payload = legacy_payload()
    series, _ = synthetic_series(2)
    last = series.bars[-1].model_copy(
        update={"open": 3800, "high": 3820, "low": 3780, "close": 3800}
    )
    series = series.model_copy(update={"bars": (*series.bars[:-1], last)})
    observations, births = [], []
    risks = daily_risk.advance_daily_risks(
        DailyTradePlan.model_validate(synthetic_plan_payload()),
        previous=(),
        close_date=last.trade_date,
        close_fen=last.close,
        basis_id=series.basis_id,
        session_dates=series.session_dates,
        suspended_dates=(),
        facts=(),
        _evaluation_observer=observations.append,
        _birth_observer=births.append,
    )
    payload.update(
        evaluated_at=series.cutoff.isoformat(),
        official_trade_date=str(last.trade_date),
        daily_evidence=series.model_dump(mode="json"),
        quote=None,
        risks=list(risks),
    )
    payload = state.DailyEvaluationState.model_validate_json(canonical(payload)).model_dump(
        mode="json"
    )
    payload["risk_evaluations"] = [
        {
            **owner(payload),
            "risk_identity": "ORDINARY_TECHNICAL",
            "kind": "ORDINARY_TECHNICAL",
            "target": {"kind": "OFFICIAL_CLOSE", "trade_date": str(last.trade_date)},
            "evidence": None,
            "ordinary_close": observations[0].model_dump(mode="json"),
        }
    ]
    payload["risk_births"] = [birth.model_dump(mode="json") for birth in births]
    return payload


def test_severe_without_an_actual_target_can_only_retain_native_missing_input():
    payload = legacy_payload()
    evidence = missing_severe()
    assert evidence.outcome == "MISSING_INPUT" and evidence.children
    row = state.DailyRiskEvaluation.model_validate_json(
        canonical(
            {
                **owner(payload),
                "risk_identity": "SEVERE_TECHNICAL",
                "kind": "SEVERE_TECHNICAL",
                "target": None,
                "ordinary_close": None,
                "evidence": evidence.model_dump(mode="json"),
            }
        )
    )
    assert row.target is None and row.evidence == evidence
    payload["risk_evaluations"] = [row.model_dump(mode="json")]
    parsed = state.DailyEvaluationState.model_validate_json(canonical(payload))
    assert parsed.risk_evaluations == (row,)
    for outcome in ("SATISFIED", "UNSATISFIED"):
        invalid = row.model_dump(mode="json")
        invalid["evidence"]["outcome"] = outcome
        with pytest.raises(ValidationError):
            state.DailyRiskEvaluation.model_validate_json(canonical(invalid))


def test_actual_ordinary_close_and_birth_roundtrip_without_fake_condition_leaves(native_payload):
    parsed = state.DailyEvaluationState.model_validate_json(canonical(native_payload))
    row = parsed.risk_evaluations[0]
    assert row.evidence is None and row.ordinary_close.below is True
    assert row.target.trade_date == row.ordinary_close.close_date
    assert row.ordinary_close.confirmation_close_used is False
    assert parsed.risk_births[0].status_before == "CLEAR"
    assert state.DailyEvaluationState.model_validate_json(parsed.model_dump_json()) == parsed
    with pytest.raises(ValidationError):
        row.risk_identity = "another-risk"


@pytest.mark.parametrize(
    "field,value",
    [
        ("plan_version_id", "another-version"),
        ("content_hash", "b" * 64),
        ("review_id", "another-review"),
        ("activation_revision", 2),
        ("evaluated_at", "2026-06-02T16:01:00+08:00"),
        ("risk_identity", "another-owner"),
        ("kind", "SEVERE_TECHNICAL"),
    ],
)
def test_risk_observation_cannot_cross_its_native_owner(native_payload, field, value):
    native_payload["risk_evaluations"][0][field] = value
    with pytest.raises(ValidationError):
        state.DailyEvaluationState.model_validate_json(canonical(native_payload))


@pytest.mark.parametrize(
    "change",
    [
        "none",
        "intraday",
        "wrong-day",
        "wrong-close",
        "wrong-basis",
        "missing-observation",
        "severe-evidence",
        "comparison-owner",
    ],
)
def test_ordinary_comparison_requires_its_actual_official_close(native_payload, change):
    row = native_payload["risk_evaluations"][0]
    if change == "none":
        row["target"] = None
    elif change == "intraday":
        row["target"] = {"kind": "INTRADAY", "bucket_end": "2026-06-02T10:05:00+08:00"}
    elif change == "wrong-day":
        row["target"]["trade_date"] = "2026-06-01"
    elif change == "wrong-close":
        row["ordinary_close"]["close_fen"] = "3799"
    elif change == "wrong-basis":
        row["ordinary_close"]["current_basis_id"] = "different-current-basis"
    elif change == "missing-observation":
        row["ordinary_close"] = None
    elif change == "severe-evidence":
        row["evidence"] = missing_severe().model_dump(mode="json")
    else:
        row["ordinary_close"]["risk_identity"] = "another-owner"
    with pytest.raises(ValidationError):
        state.DailyEvaluationState.model_validate_json(canonical(native_payload))


def test_known_target_time_must_match_parent_and_not_precede_official_close(native_payload):
    row = native_payload["risk_evaluations"][0]
    for stamp in ("2026-06-02T14:59:00+08:00", "2026-06-01T16:00:00+08:00"):
        invalid = deepcopy(row)
        invalid["evaluated_at"] = stamp
        with pytest.raises(ValidationError):
            state.DailyRiskEvaluation.model_validate_json(canonical(invalid))
    severe = {
        **owner(native_payload),
        "risk_identity": "SEVERE_TECHNICAL",
        "kind": "SEVERE_TECHNICAL",
        "ordinary_close": None,
        "evidence": missing_severe().model_dump(mode="json"),
        "target": {"kind": "INTRADAY", "bucket_end": "2026-06-02T10:05:00+08:00"},
    }
    native_payload["minute_target"] = "2026-06-02T10:00:00+08:00"
    native_payload["risk_evaluations"] = [severe]
    with pytest.raises(ValidationError):
        state.DailyEvaluationState.model_validate_json(canonical(native_payload))


@pytest.mark.parametrize(
    "field,value",
    [
        ("status_before", "OBSERVATION"),
        ("status_after", "CLEAR"),
        ("kind", "SEVERE_TECHNICAL"),
        ("close_date", "2026-06-03"),
        ("risk_identity", "another-owner"),
    ],
)
def test_birth_records_only_actual_creation_shape_and_matching_native_owner(
    native_payload, field, value
):
    native_payload["risk_births"][0][field] = value
    with pytest.raises(ValidationError):
        state.DailyEvaluationState.model_validate_json(canonical(native_payload))


@pytest.mark.parametrize("field", ["risk_evaluations", "risk_births"])
def test_private_native_sets_are_optional_nonempty_unique_and_bounded(native_payload, field):
    for rows in ([], native_payload[field] * 2, native_payload[field] * 65):
        invalid = deepcopy(native_payload)
        invalid[field] = rows
        with pytest.raises(ValidationError):
            state.DailyEvaluationState.model_validate_json(canonical(invalid))
    schema = state.DailyEvaluationState.model_json_schema()["properties"][field]
    array = next(item for item in schema["anyOf"] if item.get("type") == "array")
    assert array["minItems"] == 1 and array["maxItems"] == 64


def test_risk_condition_leaves_share_the_native_fifty_leaf_boundary(native_payload):
    condition = missing_severe().condition.model_dump(mode="json")
    leaf = condition["conditions"][0]
    raw = unified_payload()
    severe = next(branch for branch in raw["risk_branches"] if branch["kind"] == "SEVERE_TECHNICAL")
    severe["condition"] = {"type": "ALL", "conditions": [leaf] * 26}
    plan = UnifiedTradePlan.model_validate(raw)
    branch = next(item for item in plan.risk_branches if item.kind == "SEVERE_TECHNICAL")
    evidence = evaluate_unified_condition(branch.condition, None).model_dump(mode="json")
    risk = next(item for item in native_payload["risks"] if item["kind"] == "SEVERE_TECHNICAL")
    native_payload["risks"] = [{**risk, "rule_id": identity} for identity in ("risk-a", "risk-b")]
    native_payload["risk_births"] = None
    native_payload["risk_evaluations"] = [
        {
            **owner(native_payload),
            "risk_identity": identity,
            "kind": "SEVERE_TECHNICAL",
            "target": None,
            "ordinary_close": None,
            "evidence": evidence,
        }
        for identity in ("risk-a", "risk-b")
    ]
    with pytest.raises(ValidationError, match="leaf bound"):
        state.DailyEvaluationState.model_validate_json(canonical(native_payload))


def test_birth_is_retained_independently_of_later_current_comparison(native_payload):
    native_payload["risk_births"][0]["close_date"] = "2026-06-01"
    parsed = state.DailyEvaluationState.model_validate_json(canonical(native_payload))
    assert parsed.risk_births[0].close_date < parsed.risk_evaluations[0].target.trade_date
    risk = parsed.risks[1]
    assert risk.origin_evaluation_id is None
    bound = risk.model_copy(update={"origin_evaluation_id": "immutable-original-evaluation"})
    assert bound.origin_evaluation_id == "immutable-original-evaluation"
    assert "origin_evaluation_id" not in risk.model_dump(mode="json")


@pytest.mark.parametrize("missing", ["series", "visited-date"])
def test_birth_requires_a_close_actually_present_in_the_parent_daily_input(native_payload, missing):
    native_payload["risk_evaluations"] = None
    if missing == "series":
        native_payload["daily_evidence"] = None
    else:
        native_payload["risk_births"][0]["close_date"] = "2026-05-31"
    with pytest.raises(ValidationError, match="actual consumed daily close"):
        state.DailyEvaluationState.model_validate_json(canonical(native_payload))


def test_new_private_fields_validate_internally_but_never_leak_to_old_api(native_payload):
    native_payload["risks"][1]["origin_evaluation_id"] = "immutable-original-evaluation"
    parsed = state.DailyEvaluationState.model_validate_json(canonical(native_payload))
    view = DailyEvaluationApiView.model_validate_json(canonical(native_payload))
    assert (
        view.risk_evaluations == parsed.risk_evaluations and view.risk_births == parsed.risk_births
    )
    assert view.risks[1].origin_evaluation_id == parsed.risks[1].origin_evaluation_id
    output = view.model_dump_json(by_alias=True)
    assert all(
        name not in output for name in ("riskEvaluations", "riskBirths", "originEvaluationId")
    )
    validation = DailyEvaluationApiView.model_json_schema(mode="validation", by_alias=True)
    assert {"riskEvaluations", "riskBirths"} <= validation["properties"].keys()
    serialized = DailyEvaluationApiView.model_json_schema(mode="serialization", by_alias=True)
    assert {"riskEvaluations", "riskBirths"}.isdisjoint(serialized["properties"])
    assert (
        "originEvaluationId"
        not in DailyRiskApiView.model_json_schema(mode="serialization", by_alias=True)["properties"]
    )
    invalid = deepcopy(native_payload)
    invalid["risk_evaluations"][0]["review_id"] = "different-review"
    with pytest.raises(ValidationError):
        DailyEvaluationApiView.model_validate_json(canonical(invalid))


def test_old_missing_private_fields_keep_exact_frozen_native_and_public_bytes():
    payload = legacy_payload()
    native = state.DailyEvaluationState.model_validate_json(canonical(payload))
    public = DailyEvaluationApiView.model_validate_json(canonical(payload))
    for value, expected_size, digest in (
        (
            native.model_dump_json(),
            2796,
            "ec8fc2f35c34db4efe2d9b2b4cc85c317e2d7bd2292dc65d3315ff41c6e5acc8",
        ),
        (
            public.model_dump_json(by_alias=True),
            2694,
            "fe4342695c4eb7d09ef02953604ae8ca7dcf390629a581303f1e8f3889bd6344",
        ),
        (
            native.risks[1].model_dump_json(),
            739,
            "a358bbdcb9df151abc9d0be1a12ba3a4ee6c19076a154f48830c26f1737aba45",
        ),
    ):
        assert len(value.encode()) == expected_size and sha256(value.encode()).hexdigest() == digest
    assert native.risk_evaluations is None and native.risk_births is None
    assert all(risk.origin_evaluation_id is None for risk in native.risks)
