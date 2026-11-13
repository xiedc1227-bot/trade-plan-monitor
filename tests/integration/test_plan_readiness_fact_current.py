"""Readiness validates original native FACT inputs without evaluating predicates."""

import asyncio
from copy import deepcopy
from datetime import timedelta

import pytest
from tests.integration.test_daily_plan_chain import Chain
from tests.integration.test_plan_readiness_execution_reads import execution_case as execution_case
from tests.integration.test_plan_readiness_money_reads import capital_case as capital_case

from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.state.daily_models import DailyRecord


def assess(case):
    return asyncio.run(
        case.reader.get_plan_readiness(version_id=case.result.snapshot["plan_version_id"])
    )


def owner_rule(result, identity):
    return next(rule for rule in result.rules if rule.facts.owner_id == identity)


@pytest.fixture
def fact_configuration(monkeypatch):
    from tests.integration import current_pipeline_fixture as fixture

    original = fixture.current_three_rule_plan

    def plan(**kwargs):
        raw = original(**kwargs).model_dump(mode="json")
        rule = raw["ordinary_rules"][0]
        rule["condition"] = {
            "type": "ALL",
            "conditions": [
                rule["condition"],
                {
                    "type": "REVIEWED_FACT",
                    "fact_kind": "TECHNICAL",
                    "validity_scope": "TRADE_DATE",
                    "evidence_requirement": "Human verifies the completed five-minute pattern",
                },
            ],
        }
        return UnifiedTradePlan.model_validate(raw)

    monkeypatch.setattr(fixture, "current_three_rule_plan", plan)


@pytest.fixture
def fact_case(fact_configuration, execution_case):
    return execution_case


@pytest.fixture
def staged_configuration(monkeypatch):
    from tests.integration import current_pipeline_fixture as fixture

    original = fixture.current_three_rule_plan

    def plan(**kwargs):
        raw = original(**kwargs).model_dump(mode="json")
        raw["ordinary_rules"][0]["independent_signal"] = {"mode": "ONCE_PER_RULE"}
        return UnifiedTradePlan.model_validate(raw)

    monkeypatch.setattr(fixture, "current_three_rule_plan", plan)


@pytest.fixture
def staged_case(staged_configuration, execution_case):
    return execution_case


@pytest.fixture
def risk_configuration(monkeypatch):
    from tests.integration import current_pipeline_fixture as fixture
    from tests.integration.test_s3_missed_close_kill_restart import CurrentCloseSDK
    from tests.unit.test_unified_plan_domain import unified_payload

    original, activate = fixture.current_three_rule_plan, Chain.activate

    def plan(**kwargs):
        raw = original(**kwargs).model_dump(mode="json")
        severe = unified_payload()["risk_branches"][1]
        severe.update(
            rule_id="severe-manual",
            condition={
                "type": "REVIEWED_FACT",
                "fact_kind": "SEVERE_STRUCTURE",
                "validity_scope": "TRADE_DATE",
                "evidence_requirement": "Review technical evidence for SEVERE_STRUCTURE",
            },
        )
        raw["risk_branches"] = [severe]
        return UnifiedTradePlan.model_validate(raw)

    def activated(chain, **kwargs):
        value = activate(chain, **kwargs)
        # Native offline input fixture. No head/proof or condition result is
        # installed; the owned production cycle must produce every observation.
        with chain.plans._unit_of_work() as work:
            work.daily.save(
                "severe-negative",
                kind="FACT",
                symbol=chain.plan.symbol,
                lineage=chain.plan.plan_id,
                expected_revision=0,
                payload=dict(
                    plan_version_id=chain.version["id"],
                    content_hash=chain.version["contentHash"],
                    kind="SEVERE_STRUCTURE",
                    trade_date=str(chain.now.date() - timedelta(days=3)),
                    signal_id=None,
                    evidence="Synthetic complete technical failure independently verified",
                    satisfied=False,
                    verified=True,
                    verified_at=chain.now.isoformat(),
                    available_at=chain.now.isoformat(),
                    official_evidence=None,
                ),
            )
            work.commit()
        return value

    monkeypatch.setattr(fixture, "current_three_rule_plan", plan)
    monkeypatch.setattr(Chain, "activate", activated)
    native_fixture = fixture.current_pipeline_fixture

    def configured(*args, **kwargs):
        result = native_fixture(*args, **kwargs)
        source = CurrentCloseSDK(result[6]._clock, (result[2].symbol,))
        result[3].daily, result[3].adj_factor = source.daily, source.adj_factor
        return result

    monkeypatch.setattr(fixture, "current_pipeline_fixture", configured)


@pytest.fixture
def risk_fact_case(risk_configuration, execution_case):
    return execution_case


def register_fact(case, *, identity="minute-pattern", satisfied=True, revision=0):
    class PausedWorker:
        async def reevaluate_version(self, _version):
            return None

    chain = Chain(case.tmp_path)
    chain.plan, chain.now = case.plan, case.pipeline._clock.now()
    chain.runtime = PausedWorker()
    with chain.client:
        return chain.post(
            "plan-facts",
            {
                "planVersionId": case.result.snapshot["plan_version_id"],
                "contentHash": case.result.snapshot["content_hash"],
                "factId": identity,
                "kind": "TECHNICAL",
                "tradeDate": str(case.now.date()),
                "evidence": "Human verifies the completed five-minute pattern",
                "satisfied": satisfied,
                "expectedRevision": revision,
                "conditionSelection": {
                    "ownerKind": "ORDINARY_RULE",
                    "ownerId": case.plan.ordinary_rules[0].rule_id,
                    "conditionPath": "condition.conditions[1]",
                },
            },
        )


def reevaluate(case):
    case.pipeline._clock.current += timedelta(seconds=1)
    case.result = asyncio.run(case.pipeline.run_deadline(case.deadline))[0]
    assert case.result is not None and not case.result.duplicate
    assert case.owner().plans[0].completion is not None
    return case.result


def test_registered_but_unconsumed_fact_revokes_old_missing_prompt(fact_case):
    case = fact_case
    identity = case.plan.ordinary_rules[0].rule_id
    before = owner_rule(assess(case), identity)
    assert before.facts.root_outcome == "MISSING_INPUT"
    register_fact(case)
    after = owner_rule(assess(case), identity)
    assert after.state == "UNKNOWN" and after.facts.root_outcome is None
    assert all(
        leaf.state == "UNKNOWN" and leaf.reason != "HUMAN_EVIDENCE_REQUIRED"
        for leaf in after.facts.leaves
    )
    assert owner_rule(assess(case), "sell-100").state == "CONDITION_FALSE"


@pytest.mark.parametrize("satisfied", [True, False])
def test_actual_minute_fact_evaluation_keeps_original_truth_without_a_required_signal(
    fact_case,
    satisfied,
):
    case = fact_case
    receipt = register_fact(case, satisfied=satisfied)
    reevaluate(case)
    rule = owner_rule(assess(case), case.plan.ordinary_rules[0].rule_id)
    assert rule.state == ("CONDITION_TRUE" if satisfied else "CONDITION_FALSE")
    assert rule.facts.observation.availability == "CURRENT"
    native = case.result.snapshot["ordinary_evaluations"][0]["evidence"]
    assert rule.facts.root_outcome == native["outcome"]
    assert native["children"][1]["fact_ids"] == [receipt["id"]]
    if not satisfied:
        assert not case.result.snapshot["signals"]
    else:
        assert rule.facts.execution.eligible is True


def test_actual_conflicting_ties_are_complete_missing_input(fact_case):
    case = fact_case
    first = register_fact(case, identity="positive", satisfied=True)
    second = register_fact(case, identity="negative", satisfied=False)
    reevaluate(case)
    rule = owner_rule(assess(case), case.plan.ordinary_rules[0].rule_id)
    assert rule.state == "MISSING_INPUT" and rule.facts.observation.availability == "CURRENT"
    proof = case.result.snapshot["ordinary_evaluations"][0]["evidence"]["children"][1]
    assert proof["reason"] == "CONFLICTING_REVIEWED_FACT"
    assert set(proof["fact_ids"]) == {first["id"], second["id"]}


def test_next_actual_cycle_keeps_pure_market_ready_signal_execution(staged_case):
    case = staged_case
    old = case.result.snapshot["signals"][0]
    with case.work() as work:
        work.daily.save(
            "next-cycle-input",
            kind="FACT",
            symbol=case.plan.symbol,
            lineage=case.plan.plan_id,
            expected_revision=0,
            payload=dict(
                plan_version_id=case.result.snapshot["plan_version_id"],
                content_hash=case.result.snapshot["content_hash"],
                kind="TECHNICAL",
                trade_date=str(case.now.date()),
                signal_id=None,
                evidence="Synthetic independent technical review",
                verified=True,
                satisfied=True,
                verified_at=case.now.isoformat(),
                available_at=case.now.isoformat(),
                official_evidence=None,
            ),
        )
        work.commit()
    reevaluate(case)
    assert all(
        row["rule_id"] != old["rule_id"]
        for row in case.result.snapshot.get("ordinary_evaluations", [])
    )
    observed = owner_rule(assess(case), old["rule_id"])
    assert observed.facts.root_outcome is None
    assert observed.facts.execution.signal_id == old["signal_id"]
    assert observed.facts.execution.approved_quantity == old["planned_qty"]
    assert observed.facts.execution.eligible is True


@pytest.mark.parametrize("change", ["delete", "revision", "opposite", "late", "new-tie"])
def test_changed_native_fact_cannot_keep_recorded_truth_or_execution(fact_case, change):
    case = fact_case
    receipt = register_fact(case)
    reevaluate(case)
    identity = case.plan.ordinary_rules[0].rule_id
    before = owner_rule(assess(case), identity)
    assert before.facts.execution.eligible is True
    original = deepcopy(case.result.snapshot)
    if change == "new-tie":
        register_fact(case, identity="contradictory-tie", satisfied=False)
    else:
        with case.sessions.begin() as session:
            row = session.get(DailyRecord, receipt["id"])
            if change == "delete":
                session.delete(row)
            elif change == "revision":
                row.revision += 1
            else:
                import json

                payload = json.loads(row.payload_json)
                if change == "opposite":
                    payload["satisfied"] = False  # Negative fixture: unchanged revision.
                else:
                    case.pipeline._clock.current += timedelta(seconds=1)
                    payload["verified_at"] = payload["available_at"] = (
                        case.pipeline._clock.now().isoformat()
                    )
                row.payload_json = canonical(payload)
    after = owner_rule(assess(case), identity)
    assert after.state == "UNKNOWN" and after.facts.root_outcome is None
    assert after.facts.execution.eligible is None
    assert after.facts.execution.approved_quantity == before.facts.execution.approved_quantity
    assert case.result.snapshot == original
    assert owner_rule(assess(case), "sell-100").state == "CONDITION_FALSE"


def test_signal_original_fact_is_checked_when_the_latest_root_uses_another_fact(fact_case):
    case = fact_case
    first = register_fact(case, identity="original-A")
    reevaluate(case)
    old_signal = case.result.snapshot["signals"][0]
    case.pipeline._clock.current += timedelta(seconds=1)
    second = register_fact(case, identity="current-B")
    reevaluate(case)
    proof = case.result.snapshot["ordinary_evaluations"][0]["evidence"]["children"][1]
    assert proof["fact_ids"] == [second["id"]]
    assert case.result.snapshot["signals"][0]["evidence"] == old_signal["evidence"]
    assert owner_rule(assess(case), old_signal["rule_id"]).facts.execution.eligible is True
    with case.sessions.begin() as session:
        session.delete(session.get(DailyRecord, first["id"]))
    after = owner_rule(assess(case), old_signal["rule_id"])
    assert after.facts.root_outcome == "SATISFIED"
    assert after.facts.execution.eligible is None


def test_recorded_candidate_payload_participates_in_existing_double_read(fact_case, monkeypatch):
    from trade_plan_monitor.web import plan_readiness_service as projection

    case = fact_case
    receipt = register_fact(case)
    reevaluate(case)
    original, calls = projection.read_readiness_binding, []

    def changed(*args):
        if not calls:
            import json

            with case.sessions.begin() as session:
                row = session.get(DailyRecord, receipt["id"])
                payload = json.loads(row.payload_json)
                payload["evidence"] += " Additional exact recorded evidence."
                row.payload_json = canonical(payload)
        calls.append(True)
        return original(*args)

    monkeypatch.setattr(projection, "read_readiness_binding", changed)
    after = owner_rule(assess(case), case.plan.ordinary_rules[0].rule_id)
    assert len(calls) == 2  # The original bounded retry observes raw payload changes.
    assert after.facts.root_outcome == "SATISFIED"


@pytest.mark.parametrize(
    "change",
    ["inventory", "tradability-delete", "tradability-revision", "suspension", "invalidation"],
)
def test_related_control_inputs_revoke_execution_independently_of_market_false(
    execution_case, change
):
    case = execution_case
    before = owner_rule(assess(case), case.plan.ordinary_rules[0].rule_id)
    assert before.facts.execution.eligible is True
    with case.work() as work:
        if change == "inventory":
            # Negative ledger fixture: an actual POSITION revision changes
            # without a new evaluation; initialization itself is immutable.
            row = work.daily.session.get(DailyRecord, "simulation-position-" + case.plan.symbol)
            row.revision += 1
        else:
            tradability = next(
                row
                for row in work.daily.list(symbol=case.plan.symbol, kind="FACT")
                if row["payload"]["kind"] == "TRADABILITY"
            )
            if change.startswith("tradability"):
                row = work.daily.session.get(DailyRecord, tradability["id"])
                if change.endswith("delete"):
                    work.daily.session.delete(row)
                else:
                    row.revision += 1
            else:
                payload = {
                    **tradability["payload"],
                    "kind": "FULL_SESSION_SUSPENSION"
                    if change == "suspension"
                    else "SIGNAL_INVALIDATION",
                }
                if change == "invalidation":
                    payload["signal_id"] = case.result.snapshot["signals"][0]["signal_id"]
                work.daily.save(
                    "new-control",
                    kind="FACT",
                    symbol=case.plan.symbol,
                    lineage=case.plan.plan_id,
                    expected_revision=0,
                    payload=payload,
                )
        work.commit()
    after = owner_rule(assess(case), case.plan.ordinary_rules[0].rule_id)
    assert after.facts.execution.eligible is None
    assert after.facts.execution.approved_quantity == before.facts.execution.approved_quantity
    assert owner_rule(assess(case), "sell-100").state == "CONDITION_FALSE"


def test_new_severe_fact_revokes_buy_even_when_risk_post_state_did_not_change(risk_fact_case):
    case = risk_fact_case
    identity = case.plan.ordinary_rules[0].rule_id
    before = owner_rule(assess(case), identity)
    assert before.facts.execution.eligible is True
    witness = case.result.snapshot["risk_evaluations"][0]
    assert witness["evidence"]["outcome"] == "UNSATISFIED"
    with case.work() as work:
        old_risks = work.daily.list(symbol=case.plan.symbol, kind="RISK")
        work.daily.save(
            "new-severe-positive",
            kind="FACT",
            symbol=case.plan.symbol,
            lineage=case.plan.plan_id,
            expected_revision=0,
            payload=dict(
                plan_version_id=case.result.snapshot["plan_version_id"],
                content_hash=case.result.snapshot["content_hash"],
                kind="SEVERE_STRUCTURE",
                trade_date=witness["target"]["trade_date"],
                signal_id=None,
                evidence="Synthetic complete technical failure independently verified",
                verified=True,
                satisfied=True,
                verified_at=case.now.isoformat(),
                available_at=case.now.isoformat(),
                official_evidence=None,
            ),
        )
        work.commit()
    after = owner_rule(assess(case), identity)
    assert after.facts.root_outcome == "SATISFIED"  # Ordinary market evidence is independent.
    assert after.facts.execution.eligible is None
    with case.work() as work:
        assert work.daily.list(symbol=case.plan.symbol, kind="RISK") == old_risks


def test_recorded_tie_ids_are_sets_but_duplicate_ids_and_revisions_are_not_valid(fact_case):
    from trade_plan_monitor.state.daily_state_models import DailyEvaluationState
    from trade_plan_monitor.state.readiness_fact_inputs import recorded_fact_inputs_current

    case = fact_case
    register_fact(case, identity="tie-a")
    register_fact(case, identity="tie-b")
    reevaluate(case)
    native = DailyEvaluationState.model_validate_json(canonical(case.result.snapshot))
    ordinary = native.ordinary_evaluations[0]
    proof = ordinary.evidence
    leaf = proof.children[1]
    assert len(leaf.fact_ids) == 2

    def check(*, evidence=proof, snapshot=native):
        with case.work() as work:
            return recorded_fact_inputs_current(
                work,
                details=work.plans.get_version_details(native.plan_version_id),
                owner_kind="ORDINARY_RULE",
                owner_id=ordinary.rule_id,
                condition=case.plan.ordinary_rules[0].condition,
                evidence=evidence,
                snapshot=snapshot,
                target=ordinary.target,
                now=case.pipeline._clock.now(),
            )[0]

    reversed_leaf = leaf.model_copy(update={"fact_ids": tuple(reversed(leaf.fact_ids))})
    assert check(evidence=proof.model_copy(update={"children": (proof.children[0], reversed_leaf)}))
    duplicate_leaf = leaf.model_copy(update={"fact_ids": (leaf.fact_ids[0], leaf.fact_ids[0])})
    assert not check(
        evidence=proof.model_copy(update={"children": (proof.children[0], duplicate_leaf)})
    )
    duplicate_revisions = native.model_dump(mode="json")
    duplicate_revisions["fact_revisions"].append(duplicate_revisions["fact_revisions"][0])
    assert not check(snapshot=duplicate_revisions)


def test_minute_candidate_must_match_the_original_bucket_and_source(fact_case):
    import json

    case = fact_case
    receipt = register_fact(case, satisfied=False)
    reevaluate(case)
    assert owner_rule(assess(case), case.plan.ordinary_rules[0].rule_id).state == "CONDITION_FALSE"
    with case.sessions.begin() as session:
        row = session.get(DailyRecord, receipt["id"])
        original = json.loads(row.payload_json)
    for field, value in (
        ("bar_end", (case.now - timedelta(minutes=5)).replace(second=0).isoformat()),
        ("source_hash", "f" * 64),
    ):
        with case.sessions.begin() as session:
            payload = deepcopy(original)
            payload["reviewed_fact_observation"][field] = value
            session.get(DailyRecord, receipt["id"]).payload_json = canonical(payload)
        rule = owner_rule(assess(case), case.plan.ordinary_rules[0].rule_id)
        assert rule.facts.root_outcome is None and rule.state == "UNKNOWN"


def test_native_s1_confirmation_tuple_keeps_its_first_exact_s0_input(capital_case):
    from trade_plan_monitor.decision.confirmation_selection import evaluate_confirmation
    from trade_plan_monitor.decision.p3_composition import seal_capital_decision
    from trade_plan_monitor.market_data.daily_data import DailySeries
    from trade_plan_monitor.state.daily_state_models import DailyEvaluationState
    from trade_plan_monitor.web.plan_readiness_service import _recorded_fact_sources

    case = capital_case
    native = DailyEvaluationState.model_validate_json(canonical(case.result.snapshot))
    decision = native.market_linkage[0]
    series = DailySeries.model_validate_json(native.daily_evidence.model_dump_json())
    _, proofs = evaluate_confirmation(case.plan, case.plan.ordinary_rules[0], "S1",
        series=series, facts=(), decision_session=decision.decision_session, risk="UNSATISFIED")
    assert len(proofs) > 1 and proofs[0] == decision.confirmation[0]
    owners = [("ORDINARY_RULE", decision.rule_id, "BUY", case.plan.ordinary_rules[0])]

    def checked(change=None):
        # Exercise only the input selector with actual native evaluator proofs.
        # These copies never enter SQL, a completion proof, or a CURRENT projection.
        raw = decision.model_dump(mode="json", exclude={"evidence_hash"})
        raw.update(confirmation=[proof.model_dump(mode="json") for proof in proofs],
                   **(change or {}))
        selected = seal_capital_decision(raw)
        raw_snapshot = native.model_dump(mode="json")
        raw_snapshot["market_linkage"] = [selected.model_dump(mode="json")]
        proposed = DailyEvaluationState.model_validate_json(canonical(raw_snapshot))
        with case.work() as work:
            current, _ = _recorded_fact_sources(work,
                work.plans.get_version_details(native.plan_version_id), case.plan,
                owners, proposed, case.pipeline._clock.now())
            return current[("ORDINARY_RULE", decision.rule_id)]

    assert checked()
    assert not checked({"content_hash": "f" * 64})
    assert not checked({"decision_session": str(decision.decision_session - timedelta(days=1))})
    assert not checked({"evidence_cutoff": (
        native.evaluated_at - timedelta(seconds=1)).isoformat()})


def test_pure_market_false_survives_an_unrelated_native_fact(execution_case):
    case = execution_case
    assert owner_rule(assess(case), "sell-100").state == "CONDITION_FALSE"
    with case.work() as work:
        work.daily.save(
            "unrelated-native-fact",
            kind="FACT",
            symbol=case.plan.symbol,
            lineage=case.plan.plan_id,
            expected_revision=0,
            payload=dict(
                plan_version_id=case.result.snapshot["plan_version_id"],
                content_hash=case.result.snapshot["content_hash"],
                kind="TECHNICAL",
                trade_date=str(case.now.date()),
                signal_id=None,
                evidence="Synthetic complete technical failure independently verified",
                verified=True,
                satisfied=False,
                verified_at=case.now.isoformat(),
                available_at=case.now.isoformat(),
                official_evidence=None,
            ),
        )
        work.commit()
    assert owner_rule(assess(case), "sell-100").state == "CONDITION_FALSE"
