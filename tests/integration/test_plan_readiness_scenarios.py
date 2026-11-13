"""Missing cross-capability scenarios on real temporary owners and public reads."""

import asyncio
import json
import socket
from contextlib import contextmanager
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
import requests
from sqlalchemy import event
from tests.integration import current_pipeline_fixture as pipeline_fixture
from tests.integration import test_plan_readiness_money_reads as money_fixture
from tests.integration.test_daily_plan_chain import Chain
from tests.integration.test_plan_readiness_api import get
from tests.integration.test_plan_readiness_execution_reads import execution_case as execution_case
from tests.integration.test_plan_readiness_fact_current import reevaluate
from tests.integration.test_plan_readiness_money_reads import capital_case as capital_case
from tests.integration.test_plan_readiness_notification_fulfillment import (
    alert_profile as alert_profile,
)
from tests.integration.test_plan_readiness_notification_fulfillment import (
    check,
    in_app,
)
from tests.integration.test_plan_readiness_notification_fulfillment import (
    fulfillment_case as fulfillment_case,
)
from tests.integration.test_plan_readiness_notification_fulfillment import (
    service_case as service_case,
)
from tests.unit.test_unified_plan_domain import unified_payload

from trade_plan_monitor.decision import p2_economics, p3_capital, unified_lifecycle
from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.runtime import daily_service
from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.p3_capital_repository import CapitalRepository
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.plan_readiness_models import ReadinessAssessment


@pytest.fixture(autouse=True)
def offline_connections(monkeypatch):
    """Allow Windows' local event-loop socket pair, never provider connections."""
    connect, connect_ex = socket.socket.connect, socket.socket.connect_ex

    def local_only(native):
        def guarded(instance, address):
            assert isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}, (
                "scenario attempted an external socket connection"
            )
            return native(instance, address)

        return guarded

    monkeypatch.setattr(socket.socket, "connect", local_only(connect))
    monkeypatch.setattr(socket.socket, "connect_ex", local_only(connect_ex))


def owner_rule(assessment, identity):
    return next(rule for rule in assessment.rules if rule.facts.owner_id == identity)


@contextmanager
def observation_only(case, monkeypatch):
    """Only the GET interval is read-only; native setup/cycles happen outside it."""
    statements = []

    def forbidden(*_args, **_kwargs):
        pytest.fail("readiness GET attempted acquisition, evaluation, delivery or external IO")

    def readonly(_connection, _cursor, sql, _parameters, _context, _many):
        verb = sql.lstrip().split()[0].upper()
        statements.append(verb)
        assert verb not in {"INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "ALTER", "DROP"}

    with monkeypatch.context() as patch:
        patch.setattr(requests.Session, "request", forbidden)
        patch.setattr(httpx.Client, "send", forbidden)
        patch.setattr(httpx.AsyncClient, "send", forbidden)
        for name in (
            "run_deadline",
            "prepare_daily_inputs",
            "refresh_references",
            "recover_startup",
        ):
            patch.setattr(case.pipeline, name, forbidden)
        for module, name in (
            (daily_service, "evaluate_unified_condition"),
            (daily_service, "advance_daily_risks"),
            (daily_service, "check_execution"),
            (daily_service, "risk_execution"),
            (unified_lifecycle, "check_execution"),
            (p3_capital, "assess_capital"),
            (p2_economics, "calculate_economics"),
            (money_fixture.IndexInputs, "acquire_index_data"),
        ):
            patch.setattr(module, name, forbidden)
        for name in ("rt_min", "daily", "adj_factor", "stock_basic", "trade_cal"):
            if hasattr(case.sdk, name):
                patch.setattr(case.sdk, name, forbidden)
        if hasattr(case, "dispatcher"):
            patch.setattr(case.dispatcher, "dispatch_pending", forbidden)
            patch.setattr(case.dispatcher, "dispatch_event", forbidden)
        event.listen(case.engine, "before_cursor_execute", readonly)
        try:
            yield
            assert "SELECT" in statements
        finally:
            event.remove(case.engine, "before_cursor_execute", readonly)


def public_read(case, monkeypatch):
    app = create_app(read_service=case.reader, monitor_contract_version=2)
    version = case.result.snapshot["plan_version_id"]
    with observation_only(case, monkeypatch):
        response = asyncio.run(get(app, version))
    assert response.status_code == 200, response.text
    assert len(response.content) <= 1024 * 1024
    assessment = ReadinessAssessment.model_validate_json(response.content)
    assert assessment.authority_granted is False
    assert str(assessment.snapshot.context.plan_version_id) == version
    assert assessment.snapshot.context.content_hash == case.result.snapshot["content_hash"]
    return assessment


@pytest.fixture
def capital_risk_configuration(monkeypatch):
    native_payload = money_fixture.p3_payload
    native_fixture = pipeline_fixture.current_pipeline_fixture

    def payload(*args, **kwargs):
        raw = native_payload(*args, **kwargs)
        risk = next(
            row for row in unified_payload()["risk_branches"] if row["kind"] == "SEVERE_TECHNICAL"
        )
        risk.update(
            rule_id="independent-risk",
            condition={
                "type": "DAILY_PRICE_COMPARE",
                "field": "close",
                "offset": 0,
                "comparator": "GT",
                "reference": {
                    "mode": "FIXED",
                    "value": "7000",
                    "unit": "FEN",
                    "as_of": "2026-09-11",
                    "source": "fixture",
                },
            },
        )
        raw.update(risk_branches=[risk], monitoring=unified_payload()["monitoring"])
        return raw

    def early_activation(*args, **kwargs):
        kwargs["activation_at"] = pipeline_fixture.PREPARED_AT.replace(
            day=11, hour=9, minute=0, second=0
        )
        return native_fixture(*args, **kwargs)

    monkeypatch.setattr(money_fixture, "p3_payload", payload)
    monkeypatch.setattr(pipeline_fixture, "current_pipeline_fixture", early_activation)


@pytest.fixture
def capital_risk_case(capital_risk_configuration, capital_case, tmp_path):
    capital_case.tmp_path = tmp_path
    return capital_case


def official_cycle(case, *, price, days=0):
    now = case.now.replace(hour=15, minute=21, second=0) + timedelta(days=days)
    case.pipeline._clock.current = now
    case.daily_source.official_closes[now.date()] = price
    case.sdk.source_time = now.replace(hour=15, minute=0) - timedelta(minutes=1)
    deadline = MarketDeadline(
        kind=DeadlineKind.OFFICIAL_CLOSE,
        trade_date=now.date(),
        due_at=now,
        bar_end=None,
        close_attempt=1,
    )

    async def run():
        await case.pipeline.refresh_references(now.date())
        return await case.pipeline.run_deadline(deadline)

    (case.result,) = asyncio.run(run())
    assert not case.result.duplicate and case.owner().plans[0].completion is not None


@pytest.mark.parametrize("capital_case", [{"mode": "OPEN_COST_CAP"}], indirect=True)
def test_missing_p3_cost_does_not_disable_independent_native_risk(
    capital_risk_case,
    monkeypatch,
):
    case = capital_risk_case
    initial = public_read(case, monkeypatch)
    buy = next(rule.facts for rule in initial.rules if rule.facts.side == "BUY")
    assert buy.requirements.cost_basis is True
    assert buy.money.inputs.state == "UNKNOWN" and buy.money.capital.outcome == "UNKNOWN"
    assert initial.snapshot.context.book_revision is None
    risk = owner_rule(initial, "independent-risk")
    assert risk.facts.risk.current.evidence.outcome == "UNSATISFIED"

    # Legal producer work: admitted official data changes, then the owned cycle runs.
    official_cycle(case, price="75.00")
    confirmed = public_read(case, monkeypatch)
    risk = owner_rule(confirmed, "independent-risk")
    native = next(
        row
        for row in case.result.snapshot["risk_evaluations"]
        if row["risk_identity"] == "independent-risk"
    )
    assert native["evidence"]["outcome"] == "SATISFIED"
    assert risk.facts.risk.current.model_dump(mode="json") == native
    assert risk.state == "CONDITION_TRUE"
    assert risk.facts.risk.obligation.status == "CONFIRMED"
    origin = risk.facts.risk.origin
    assert origin is not None
    assert origin.plan_version_id == str(confirmed.snapshot.context.plan_version_id)
    assert origin.content_hash == confirmed.snapshot.context.content_hash
    native_cause = next(
        row for row in case.result.snapshot["risks"] if row["rule_id"] == "independent-risk"
    )
    assert origin.evaluation_id == native_cause["origin_evaluation_id"]
    assert origin.evaluated_at == risk.facts.risk.current.evaluated_at
    assert risk.facts.risk.maintenance.state == "PASS"

    official_cycle(case, price="64.05", days=1)
    compared = public_read(case, monkeypatch)
    risk = owner_rule(compared, "independent-risk")
    assert risk.facts.risk.current.evidence.outcome == "UNSATISFIED"
    assert risk.facts.risk.obligation.status == "CONFIRMED"
    assert risk.facts.risk.origin == origin
    assert risk.facts.risk.maintenance.state == "PASS"
    assert case.result.snapshot["risk_action"]["status"] == "RISK_EXIT"
    # Cost absence does not erase the exit obligation or waive its native execution gate.
    assert case.result.snapshot["risk_action"]["blockers"] == ["WAIT_FOR_CERTIFIED_TRADABILITY"]
    assert case.result.snapshot["risk_action"]["tactical_qty"] == 0
    assert case.result.snapshot["risk_action"]["unavailable_tactical_qty"] == 100
    assert case.result.snapshot["risk_action"]["cause_id"] == risk.facts.risk.obligation.risk_id
    assert (
        next(axis for axis in compared.axes if axis.axis == "INVENTORY_CAPITAL").state == "UNKNOWN"
    )
    assert compared.summary != "READY_FOR_MONITORING"
    with case.sessions() as session:
        assert CapitalRepository(session).get(case.plan.symbol) is None

    # A cause revision revokes maintenance, not an independently proven market comparison.
    with case.sessions.begin() as session:
        session.get(DailyRecord, risk.facts.risk.obligation.risk_id).revision += 1
    changed = owner_rule(public_read(case, monkeypatch), "independent-risk")
    assert changed.facts.risk.current == risk.facts.risk.current
    assert changed.facts.risk.maintenance.state == "UNKNOWN"
    assert changed.facts.risk.origin == origin

    # Restore the cause revision, then invalidate the original EVALUATION's exact revision.
    with case.sessions.begin() as session:
        session.get(DailyRecord, risk.facts.risk.obligation.risk_id).revision -= 1
        session.get(DailyRecord, origin.evaluation_id).revision += 1
    unverified = owner_rule(public_read(case, monkeypatch), "independent-risk")
    assert unverified.facts.risk.origin is None
    assert unverified.facts.risk.current == risk.facts.risk.current
    assert unverified.facts.risk.obligation.status == "CONFIRMED"
    assert unverified.facts.risk.maintenance.state == "UNKNOWN"


@pytest.fixture
def two_leaf_configuration(monkeypatch):
    native = pipeline_fixture.current_three_rule_plan

    def plan(**kwargs):
        raw = native(**kwargs).model_dump(mode="json")
        raw["ordinary_rules"][0]["condition"] = {
            "type": "ALL",
            "conditions": [
                {
                    "type": "REVIEWED_FACT",
                    "fact_kind": "VOLUME_OR_CANDLE",
                    "validity_scope": "TRADE_DATE",
                    "evidence_requirement": requirement,
                }
                for requirement in (
                    "成交不异常放大",
                    "明显下影",
                )
            ],
        }
        return UnifiedTradePlan.model_validate(raw)

    monkeypatch.setattr(pipeline_fixture, "current_three_rule_plan", plan)


@pytest.fixture
def two_leaf_case(two_leaf_configuration, execution_case):
    return execution_case


class DeferredOwnedCycle:
    """No background monitor here; tests explicitly drive the existing owned pipeline."""

    async def reevaluate_version(self, _version):
        return None


def post_fact(case, body, *, key):
    chain = Chain(case.tmp_path)
    chain.plan, chain.now = case.plan, case.pipeline._clock.now()
    chain.runtime = DeferredOwnedCycle()
    with chain.client:
        return chain.client.post("/api/v1/plan-facts", json=body, headers={"Idempotency-Key": key})


def post_leaf(case, index, *, identity, satisfied=True, **changes):
    body = dict(
        planVersionId=case.result.snapshot["plan_version_id"],
        contentHash=case.result.snapshot["content_hash"],
        factId=identity,
        kind="VOLUME_OR_CANDLE",
        tradeDate=str(case.pipeline._clock.now().date()),
        satisfied=satisfied,
        evidence="Synthetic actual human observation for this exact reviewed condition.",
        expectedRevision=0,
        conditionSelection={
            "ownerKind": "ORDINARY_RULE",
            "ownerId": case.plan.ordinary_rules[0].rule_id,
            "conditionPath": f"condition.conditions[{index}]",
        },
    )
    body.update(changes)
    return post_fact(case, body, key=identity)


@pytest.mark.parametrize("change", ["delete", "revision", "content"])
def test_public_same_kind_leaves_remain_distinct_through_owned_readiness(
    two_leaf_case,
    monkeypatch,
    change,
):
    case = two_leaf_case
    owner = case.plan.ordinary_rules[0].rule_id
    a = post_leaf(case, 0, identity="leaf-a", satisfied=True)
    assert a.status_code == 200, a.text
    reevaluate(case)
    partial = owner_rule(public_read(case, monkeypatch), owner)
    assert partial.state == "MISSING_INPUT"
    assert [(leaf.condition_path, leaf.state) for leaf in partial.facts.leaves] == [
        ("condition.conditions[0]", "CONDITION_TRUE"),
        ("condition.conditions[1]", "MISSING_INPUT"),
    ]

    b = post_leaf(case, 1, identity="leaf-b", satisfied=False)
    assert b.status_code == 200, b.text
    reevaluate(case)
    actual = owner_rule(public_read(case, monkeypatch), owner)
    assert actual.state == "CONDITION_FALSE" and actual.facts.root_outcome == "UNSATISFIED"
    native = next(
        row["evidence"]
        for row in case.result.snapshot["ordinary_evaluations"]
        if row["rule_id"] == owner
    )
    assert [leaf["fact_ids"] for leaf in native["children"]] == [[a.json()["id"]], [b.json()["id"]]]
    assert [leaf.state for leaf in actual.facts.leaves] == ["CONDITION_TRUE", "CONDITION_FALSE"]
    assert case.result.evaluation_id is not None
    assert all(leaf.evidence_refs == (case.result.evaluation_id,) for leaf in actual.facts.leaves)
    assert not case.result.snapshot["signals"]

    # Negative source mutation occurs outside the GET observation interval.
    with case.sessions.begin() as session:
        row = session.get(DailyRecord, b.json()["id"])
        if change == "delete":
            session.delete(row)
        elif change == "revision":
            row.revision += 1
        else:
            payload = json.loads(row.payload_json)
            payload["satisfied"] = True
            row.payload_json = canonical(payload)
    revoked = owner_rule(public_read(case, monkeypatch), owner)
    assert revoked.state == "UNKNOWN" and revoked.facts.root_outcome is None
    assert revoked.facts.leaves[1].state == "UNKNOWN"


@pytest.mark.parametrize("binding", ["owner", "path", "version"])
def test_invalid_public_leaf_binding_cannot_supply_the_missing_sibling(
    two_leaf_case,
    monkeypatch,
    binding,
):
    case = two_leaf_case
    a = post_leaf(case, 0, identity="leaf-a")
    assert a.status_code == 200, a.text
    changes = (
        {"planVersionId": str(uuid4())}
        if binding == "version"
        else {
            "conditionSelection": {
                "ownerKind": "ORDINARY_RULE",
                "ownerId": "missing-owner"
                if binding == "owner"
                else case.plan.ordinary_rules[0].rule_id,
                "conditionPath": "condition.conditions[99]"
                if binding == "path"
                else "condition.conditions[1]",
            },
        }
    )
    rejected = post_leaf(case, 1, identity="invalid-b", **changes)
    assert rejected.status_code in {404, 409, 422}, rejected.text
    reevaluate(case)
    actual = owner_rule(public_read(case, monkeypatch), case.plan.ordinary_rules[0].rule_id)
    assert actual.state == "MISSING_INPUT"
    assert [leaf.state for leaf in actual.facts.leaves] == ["CONDITION_TRUE", "MISSING_INPUT"]
    with case.work() as work:
        assert len(work.daily.list(symbol=case.plan.symbol, kind="FACT")) == 2  # A + tradability.


@pytest.mark.parametrize("service_case", [{"true": True, "two_alerts": True}], indirect=True)
@pytest.mark.parametrize("change", ["expired", "closed"])
def test_public_notification_receipts_remain_history_when_current_service_is_lost(
    fulfillment_case,
    monkeypatch,
    change,
):
    case = fulfillment_case
    native = case.dispatcher.dispatch_pending

    async def one():
        return await native(limit=1)

    with monkeypatch.context() as patch:
        patch.setattr(case.dispatcher, "dispatch_pending", one)
        check(case)
    partial = public_read(case, monkeypatch)
    assert all(rule.state == "CONDITION_TRUE" for rule in partial.rules)
    assert sum(in_app(rule).latest_attempt is not None for rule in partial.rules) == 1
    assert (
        next(axis for axis in partial.axes if axis.axis == "NOTIFICATION_DELIVERY").state
        == "UNKNOWN"
    )

    check(case)
    complete = public_read(case, monkeypatch)
    assert all(in_app(rule).latest_attempt.status == "DELIVERED" for rule in complete.rules)
    assert (
        next(axis for axis in complete.axes if axis.axis == "NOTIFICATION_DELIVERY").state == "PASS"
    )
    original = {rule.facts.owner_id: rule.facts.notification for rule in complete.rules}
    guards = tuple(case.send_guards)
    if change == "closed":
        case.dispatcher.begin_shutdown()
    else:
        current = case.owner().notification_service
        case.pipeline._clock.current = current.valid_until + timedelta(seconds=1)
        token = case.progress.begin_step(timeout_seconds=30)
        case.progress.complete_step(
            token, next_wake_at=case.pipeline._clock.now() + timedelta(seconds=30)
        )
    lost = public_read(case, monkeypatch)
    assert lost.summary == "UNKNOWN" and lost.fresh_until is None
    assert (
        next(axis for axis in lost.axes if axis.axis == "NOTIFICATION_DELIVERY").state == "UNKNOWN"
    )
    for rule in lost.rules:
        channel = in_app(rule)
        assert (
            channel.latest_attempt
            == in_app(owner_rule(complete, rule.facts.owner_id)).latest_attempt
        )
        assert rule.facts.notification.created_at == original[rule.facts.owner_id].created_at
        assert rule.facts.notification.target == original[rule.facts.owner_id].target
        assert channel.eligible is None
    assert tuple(case.send_guards) == guards
