"""Closed v2 status models reject contradictory authority, not just bad types."""

import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from trade_plan_monitor.web.runtime_status_models import RuntimeStatusEnvelope

OBSERVED = "2026-09-27T12:00:00.000000+08:00"
FUTURE = "2026-09-27T12:00:30.000000+08:00"
GENERATION = "b2f55d82-8d98-4c5e-a3bc-18529f84e982"


def status_envelope():
    return {
        "monitorContractVersion": 2,
        "runtimeGeneration": GENERATION,
        "observedAt": OBSERVED,
        "runtimeStatus": {
            "lifecycle": "RUNNING",
            "mode": "STANDBY",
            "reasonCode": "SESSION_BREAK",
            "nextWakeAt": FUTURE,
            "nextRetryAt": None,
            "lastProgressAt": OBSERVED,
            "coordinator": {"state": "SCHEDULED", "progressDueAt": FUTURE},
            "scopes": [],
        },
    }


def plan_scope():
    return {
        "scopeKey": "plan:003043.SZ:7",
        "kind": "PLAN",
        "status": "WAITING",
        "reasonCode": "AWAITING_FIRST_EVALUATION",
        "requiredTarget": None,
        "dataCutoff": None,
        "nextRetryAt": None,
        "progress": {"requiredCount": None, "completedCount": None},
        "symbol": "003043.SZ",
        "planFamily": "EXPLICIT_RULES",
        "planVersionId": "41699c9c-8c65-4ab8-9740-20efdd45e3d9",
        "planHash": "a" * 64,
        "activationRevision": 7,
        "readOnly": True,
    }


def parse(value):
    return RuntimeStatusEnvelope.model_validate_json(json.dumps(value))


def test_plan_scopes_cannot_duplicate_a_symbol_under_different_keys():
    wire = status_envelope()
    first = plan_scope()
    second = {**first, "scopeKey": "plan:003043.SZ:8", "activationRevision": 8}
    wire["runtimeStatus"]["scopes"] = [first, second]
    with pytest.raises(ValidationError):
        parse(wire)


@pytest.mark.parametrize("state", ["SCHEDULED", "WORKING"])
def test_overdue_owned_deadline_requires_stalled(state):
    wire = status_envelope()
    wire["runtimeStatus"]["coordinator"] = {
        "state": state,
        "progressDueAt": "2026-09-27T11:59:59.000000+08:00",
    }
    with pytest.raises(ValidationError):
        parse(wire)


@pytest.mark.parametrize("mutation", ["empty_rules", "official_target"])
def test_explicit_current_requires_nonempty_rules_and_exact_intraday_target(mutation):
    from trade_plan_monitor.web.runtime_status_models import RuntimeDashboardResponse

    wire = explicit_dashboard()
    entry = wire["symbols"][0]
    if mutation == "empty_rules":
        entry["explicitRuntime"]["ruleOutcomes"] = []
        entry["ruleEligibility"] = []
        entry["actionableRuleIds"] = []
        entry["currentActionable"] = False
        wire["counts"] = {
            "actionable": 0,
            "lowZoneWatch": 0,
            "blocked": 0,
            "risk": 0,
            "stale": 0,
            "normal": 1,
        }
    else:
        target = {"kind": "OFFICIAL_CLOSE", "tradeDate": "2026-09-26"}
        entry["scope"]["requiredTarget"] = target
        wire["runtimeStatus"]["scopes"][0]["requiredTarget"] = target
    with pytest.raises(ValidationError):
        RuntimeDashboardResponse.model_validate_json(json.dumps(wire))


def test_standby_retains_generation_and_closed_status_without_global_read_only():
    wire = status_envelope()
    wire["runtimeStatus"]["scopes"] = [plan_scope()]
    assert parse(wire).model_dump(mode="json", by_alias=True) == wire


@pytest.mark.parametrize(
    "field,value",
    [
        ("monitorContractVersion", "2"),
        ("monitorContractVersion", True),
        ("runtimeGeneration", None),
        ("readOnly", False),
        ("connectionStatus", "CONNECTED"),
    ],
)
def test_invalid_or_legacy_envelope_fields_fail_closed(field, value):
    wire = status_envelope()
    wire[field] = value
    with pytest.raises(ValidationError):
        parse(wire)


@pytest.mark.parametrize(
    "mutation",
    [
        {"mode": "MONITORING"},
        {"lastProgressAt": FUTURE},
        {"reasonCode": "RAW_SECRET"},
        {"coordinator": {"state": "STALLED", "progressDueAt": OBSERVED}},
        {"nextWakeAt": None},
        {"readOnly": False},
    ],
)
def test_contradictory_status_is_not_accepted_as_transport_health(mutation):
    wire = status_envelope()
    wire["runtimeStatus"].update(mutation)
    with pytest.raises(ValidationError):
        parse(wire)


@pytest.mark.parametrize(
    "mutation",
    [
        {"readOnly": False},
        {"status": "READY"},
        {"progress": {"requiredCount": 5, "completedCount": 6}},
        {"progress": {"requiredCount": 5, "completedCount": None}},
        {"progress": {"requiredCount": 2**53, "completedCount": 0}},
        {"dataCutoff": FUTURE},
        {"activationRevision": 2**53},
        {"requiredTarget": {"kind": "INTRADAY", "targetEnd": FUTURE}},
        {"scopeKey": "https://private.example/key"},
        {"extra": "unknown"},
    ],
)
def test_invalid_plan_scope_never_grants_evaluation(mutation):
    wire = status_envelope()
    scope = plan_scope()
    scope.update(mutation)
    wire["runtimeStatus"]["scopes"] = [scope]
    with pytest.raises(ValidationError):
        parse(wire)


def test_ready_standby_may_remain_read_only():
    wire = status_envelope()
    scope = plan_scope()
    scope.update(
        status="READY",
        reasonCode=None,
        requiredTarget={"kind": "INTRADAY", "targetEnd": "2026-09-27T11:30:00.000000+08:00"},
        progress={"requiredCount": 0, "completedCount": 0},
    )
    wire["runtimeStatus"]["scopes"] = [scope]
    assert parse(wire).runtime_status.scopes[0].read_only


def test_scope_identity_must_be_unique():
    wire = status_envelope()
    wire["runtimeStatus"]["scopes"] = [plan_scope(), deepcopy(plan_scope())]
    with pytest.raises(ValidationError):
        parse(wire)


def test_authoritatively_absent_owner_has_stopped_state_and_no_schedule():
    wire = status_envelope()
    wire["runtimeGeneration"] = None
    wire["runtimeStatus"].update(
        lifecycle="STOPPED",
        mode="BLOCKED",
        reasonCode="RUNTIME_STOPPED",
        nextWakeAt=None,
        lastProgressAt=None,
        coordinator={"state": "STOPPED", "progressDueAt": None},
    )
    assert parse(wire).runtime_generation is None


def explicit_dashboard():
    wire = status_envelope()
    scope = plan_scope()
    scope.update(
        status="READY",
        reasonCode=None,
        requiredTarget={"kind": "INTRADAY", "targetEnd": "2026-09-27T11:30:00.000000+08:00"},
        progress={"requiredCount": 0, "completedCount": 0},
    )
    wire["runtimeStatus"]["scopes"] = [scope]
    source = {
        "eventId": "41699c9c-8c65-5ab8-9740-20efdd45e3d9",
        "resultHash": "b" * 64,
        "evaluatedAt": "2026-09-26T10:05:01.000000+08:00",
        "dataCutoff": "2026-09-26T10:05:00.000000+08:00",
    }
    runtime = {
        "symbol": scope["symbol"],
        "planVersionId": scope["planVersionId"],
        "planHash": scope["planHash"],
        "activationRevision": scope["activationRevision"],
        "status": "CURRENT",
        "evaluatedAt": OBSERVED,
        "targetBucketEnd": "2026-09-27T11:30:00.000000+08:00",
        "ruleOutcomes": [
            {
                "ruleId": rule,
                "action": action,
                "conditionCode": "PRICE_ABOVE",
                "conditionEvidence": None,
                "outcome": "SATISFIED",
                "missingInputs": [],
                "blockers": [],
                "suppressionReason": "ONCE_ALREADY_EMITTED",
            }
            for rule, action in (("entry", "BUY"), ("risk", "RISK_ALERT"))
        ],
    }
    row = {
        **{
            key: scope[key]
            for key in (
                "symbol",
                "planFamily",
                "planVersionId",
                "planHash",
                "activationRevision",
            )
        },
        "name": "测试股票",
        "observedAt": OBSERVED,
        "availability": "CURRENT",
        "scope": scope,
        "currentActionable": True,
        "explicitRuntime": runtime,
        "resultHash": "c" * 64,
        "ruleEligibility": [
            {
                "ruleId": "entry",
                "action": "BUY",
                "currentActionable": False,
                "reasonCode": "INTRADAY_EXPIRED",
                "actionableUntil": None,
                "sourceAlert": None,
            },
            {
                "ruleId": "risk",
                "action": "RISK_ALERT",
                "currentActionable": True,
                "reasonCode": None,
                "actionableUntil": None,
                "sourceAlert": source,
            },
        ],
        "actionableRuleIds": ["risk"],
    }
    wire.update(
        sequence=42,
        symbols=[row],
        marketIndexes=[],
        marketTurnover=None,
        counts={
            "actionable": 1,
            "lowZoneWatch": 0,
            "blocked": 0,
            "risk": 1,
            "stale": 1,
            "normal": 0,
        },
    )
    return wire


def parse_dashboard(value):
    from trade_plan_monitor.web.runtime_status_models import RuntimeDashboardResponse

    return RuntimeDashboardResponse.model_validate_json(json.dumps(value))


def test_expired_buy_and_current_risk_keep_original_source_without_promoting_buy():
    wire = explicit_dashboard()
    assert parse_dashboard(wire).model_dump(mode="json", by_alias=True) == wire


@pytest.mark.parametrize(
    "mutation",
    [
        {"actionableRuleIds": ["entry", "risk"]},
        {"decision": {}},
        {"currentActionable": False},
        {"availability": "CACHED"},
        {"planHash": "d" * 64},
        {"activationRevision": 8},
        {"observedAt": FUTURE},
    ],
)
def test_inconsistent_family_or_identity_rejects_whole_snapshot(mutation):
    wire = explicit_dashboard()
    wire["symbols"][0].update(mutation)
    with pytest.raises(ValidationError):
        parse_dashboard(wire)


@pytest.mark.parametrize(
    "mutation",
    [
        {"sourceAlert": None},
        {"action": "SELL"},
        {"reasonCode": "CACHED_RESULT"},
        {"actionableUntil": OBSERVED},
        {"ruleId": "unknown-rule"},
    ],
)
def test_explicit_rule_eligibility_requires_exact_persisted_source_and_outcome(mutation):
    wire = explicit_dashboard()
    wire["symbols"][0]["ruleEligibility"][1].update(mutation)
    with pytest.raises(ValidationError):
        parse_dashboard(wire)


def test_explicit_detail_shares_dashboard_authority_and_has_no_legacy_details():
    from trade_plan_monitor.web.runtime_status_models import RuntimeSymbolDetailResponse

    dashboard = explicit_dashboard()
    wire = {
        key: dashboard[key]
        for key in (
            "monitorContractVersion",
            "runtimeGeneration",
            "observedAt",
            "runtimeStatus",
            "sequence",
        )
    }
    wire.update(summary=dashboard["symbols"][0], legacyDetails=None)
    assert RuntimeSymbolDetailResponse.model_validate_json(
        json.dumps(wire)
    ).summary.plan_family == ("EXPLICIT_RULES")
    wire["legacyDetails"] = {
        "positionLots": [],
        "referenceMarket": None,
        "indexConditionEvidence": [],
    }
    with pytest.raises(ValidationError):
        RuntimeSymbolDetailResponse.model_validate_json(json.dumps(wire))


def test_symbol_health_requires_exact_scope_in_status():
    from trade_plan_monitor.web.runtime_status_models import RuntimeSymbolHealthResponse

    wire = status_envelope()
    scope = plan_scope()
    wire["scope"] = scope
    with pytest.raises(ValidationError):
        RuntimeSymbolHealthResponse.model_validate_json(json.dumps(wire))
    wire["runtimeStatus"]["scopes"] = [scope]
    assert RuntimeSymbolHealthResponse.model_validate_json(json.dumps(wire)).scope.read_only


def test_heartbeat_cannot_add_legacy_runtime_live_or_advance_a_negative_cursor():
    from trade_plan_monitor.web.runtime_status_models import RuntimeHeartbeatFrame

    wire = {"type": "heartbeat", "sequence": 42, **status_envelope()}
    assert RuntimeHeartbeatFrame.model_validate_json(json.dumps(wire)).sequence == 42
    wire["runtimeLive"] = True
    with pytest.raises(ValidationError):
        RuntimeHeartbeatFrame.model_validate_json(json.dumps(wire))
