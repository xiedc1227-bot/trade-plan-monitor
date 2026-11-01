"""Recorded evidence recheck on actual temporary SQL owners.

FACT admission uses the released private registration path. Recorded SIGNALs
are explicitly arranged typed engineering artifacts, using the pure scoped
evaluator's evidence; this does not claim a new runtime producer/action route.
"""

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select, update
from tests.integration.test_daily_plan_chain import SH, Chain
from tests.integration.test_reviewed_fact_target_registration import (
    SELECTION,
    _command,
    _current,
    _plan,
    _signal,
    _write,
)
from tests.integration.test_source_action_cutover import _install_severe
from tests.integration.test_source_action_cutover import legacy as legacy
from tests.integration.test_unified_runtime import minute_inputs
from tests.unit.test_daily_state_models import signal_payload
from tests.unit.test_plan_domain import _valid_plan_payload

from trade_plan_monitor.decision.unified_conditions import evaluate_unified_condition
from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.domain.plan_codec import load_plan_json
from trade_plan_monitor.domain.plan_models import TradePlan
from trade_plan_monitor.domain.reviewed_fact_targets import list_reviewed_fact_targets
from trade_plan_monitor.domain.risk_scope import risk_identity
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.models import AuditLog, PlanVersion
from trade_plan_monitor.state.reviewed_fact_authority import (
    _target_leaf,
    fact_evidence_satisfied,
    signal_fact_evidence_satisfied,
)
from trade_plan_monitor.state.source_action_authority import require_source_action_authority
from trade_plan_monitor.state.source_coverage_authority import SourceCoverageAuthorityError


def _register(chain, index, *, path=None, **changes):
    return _write(chain, _command(chain, factId=f"leaf-{index}", **changes),
                  fact_selection=(*SELECTION[:2], path or f"condition.conditions[{index}]"))


def _proof(chain, facts, *, signal_id=None):
    inputs = minute_inputs(chain)
    return evaluate_unified_condition(chain.plan.ordinary_rules[0].condition, None,
        facts=tuple({"id": row["id"], **row["payload"]} for row in facts),
        target=inputs.minute_target, bars=inputs.five_minute_bars,
        trading_calendar=inputs.trading_calendar, signal_id=signal_id,
        _fact_owner=(chain.plan, chain.version["id"], *SELECTION[:2]),
        _condition_path="condition").model_dump(mode="json")


def _save_signal(chain, roots, **changes):
    with chain.plans._unit_of_work() as work:
        details = work.plans.get_version_details(chain.version["id"])
        payload = {**signal_payload(), "signal_id": "arranged-exact-evidence",
            "lineage": chain.plan.plan_id, "plan_version_id": details.id,
            "review_id": details.review_id, "state": "CONFIRMED", "executable_qty": 0,
            "confirmed_trade_date": str(chain.now.date()), "execution_date": None,
            "confirmation_kind": "COMPLETED_BAR_CLOSE", "execution_window": "CURRENT_SESSION",
            "confirmed_at": chain.now.isoformat(), "evidence": roots,
            "evidence_fingerprint": daily_hash("condition-signal-evidence-v1", roots), **changes}
        work.daily.save(payload["signal_id"], kind="SIGNAL", symbol=details.symbol,
            lineage=details.plan_id, expected_revision=0, payload=payload)
        work.commit()
    return payload["signal_id"]


def _check(chain, identity):
    with chain.plans._unit_of_work() as work, work.daily.session.no_autoflush:
        work.daily.lock_symbol(chain.plan.symbol)
        row = work.daily.get(identity)
        before = canonical(row)
        result = signal_fact_evidence_satisfied(work, chain.plan, row["payload"])
        assert canonical(work.daily.get(identity)) == before
        return result


def test_registered_exact_leaves_in_recorded_evidence_pass_original_sql_recheck(tmp_path):
    with _current(tmp_path) as chain:
        facts = [_register(chain, i) for i in range(2)]
        proof = _proof(chain, facts)
        assert proof["outcome"] == "SATISFIED"
        assert [child["fact_ids"] for child in proof["children"]] == [
            [row["id"]] for row in facts]
        identity = _save_signal(chain, [deepcopy(proof)])
        assert _check(chain, identity)


@contextmanager
def _variant(tmp_path, *, operator="ALL", duplicate=False, numeric=False, unique=False,
             folded=False, nested=False):
    raw = _plan().model_dump(mode="json")
    condition = raw["ordinary_rules"][0]["condition"]
    condition["type"] = operator
    if duplicate:
        condition["conditions"][1] = deepcopy(condition["conditions"][0])
    if numeric:
        condition["conditions"].append(dict(type="MINUTE_CLOSE_BELOW", timeframe_minutes=5,
                                            price_fen=4000))
    if unique or folded:
        if unique:
            condition["conditions"] = condition["conditions"][:1]
        raw["ordinary_rules"] = raw["ordinary_rules"][:1]
        raw["ordinary_rules"][0]["independent_signal"] = {"mode": "ONCE_PER_RULE"}
    if nested:
        raw["ordinary_rules"][0]["condition"] = dict(type="ALL", conditions=[condition])
    chain = Chain(tmp_path)
    chain.plan = UnifiedTradePlan.model_validate(raw)
    with chain.client:
        chain.activate()
        chain.now = datetime(2026, 9, 22, 9, 35, 12, tzinfo=SH)
        chain.runtime.run_inputs(plan=chain.plan, inputs=minute_inputs(chain))
        yield chain


@pytest.mark.parametrize("duplicate", [False, True])
@pytest.mark.parametrize("wrong", ["reuse-a", "swap", "other-owner"])
def test_same_kind_or_identical_leaves_cannot_borrow_another_position_or_owner(
        tmp_path, duplicate, wrong):
    with _variant(tmp_path, duplicate=duplicate) as chain:
        facts = [_register(chain, i) for i in range(2)]
        proof = _proof(chain, facts)
        assert proof["outcome"] == "SATISFIED"
        if wrong == "reuse-a":
            proof["children"][1]["fact_ids"] = [facts[0]["id"]]
        elif wrong == "swap":
            for child, row in zip(proof["children"], reversed(facts), strict=True):
                child["fact_ids"] = [row["id"]]
        else:
            other = _write(chain, _command(chain, factId="other-owner"), fact_selection=(
                "ORDINARY_RULE", "sell-other", "condition.conditions[0]"))
            proof["children"][0]["fact_ids"] = [other["id"]]
        assert not _check(chain, _save_signal(chain, [proof]))


@pytest.mark.parametrize("damage", ["root-subtree", "operator", "derived-roots", "missing-child",
                                    "reordered-children", "wrong-child-condition", "missing-id"])
def test_root_and_recursive_evidence_must_correspond_without_leaf_search(tmp_path, damage):
    with _current(tmp_path) as chain:
        facts = [_register(chain, i) for i in range(2)]
        proof = _proof(chain, facts)
        roots = [proof]
        if damage == "root-subtree":
            roots = [proof["children"][0]]
        elif damage == "operator":
            proof["condition"]["type"] = "ANY"
        elif damage == "derived-roots":
            roots.append(deepcopy(proof))
        elif damage == "missing-child":
            proof["children"].pop()
        elif damage == "reordered-children":
            proof["children"].reverse()
        elif damage == "wrong-child-condition":
            proof["children"][1]["condition"] = deepcopy(proof["children"][0]["condition"])
        else:
            proof["children"][0]["fact_ids"] = ["nonexistent-fact"]
        assert not _check(chain, _save_signal(chain, roots))


def test_true_a_does_not_supply_missing_b_and_negative_b_is_local(tmp_path):
    with _current(tmp_path) as chain:
        a = _register(chain, 0)
        proof = _proof(chain, [a])
        assert [child["outcome"] for child in proof["children"]] == [
            "SATISFIED", "MISSING_INPUT"]
        assert not _check(chain, _save_signal(chain, [proof]))


def test_nested_native_paths_are_carried_through_actual_child_positions(tmp_path):
    with _variant(tmp_path, nested=True) as chain:
        facts = [_register(chain, i, path=f"condition.conditions[0].conditions[{i}]")
                 for i in range(2)]
        proof = _proof(chain, facts)
        assert proof["outcome"] == "SATISFIED"
        assert _check(chain, _save_signal(chain, [proof]))


@pytest.mark.parametrize("numeric", [False, True])
def test_any_keeps_independent_true_leaf_despite_another_negative_or_missing_fact(
        tmp_path, numeric):
    with _variant(tmp_path, operator="ANY", numeric=numeric) as chain:
        facts = [_register(chain, 1, satisfied=False)]
        if not numeric:
            facts.append(_register(chain, 0))
        proof = _proof(chain, facts)
        assert proof["outcome"] == "SATISFIED"
        assert proof["children"][1]["outcome"] == "UNSATISFIED"
        assert _check(chain, _save_signal(chain, [proof]))


def test_wrong_path_negative_cannot_be_a_decisive_unsatisfied_any_operand(tmp_path):
    with _variant(tmp_path, operator="ANY") as chain:
        negative = _register(chain, 1, satisfied=False)
        proof = _proof(chain, [negative])
        proof["children"][0].update(outcome="UNSATISFIED", fact_ids=[negative["id"]])
        # It cannot supply the other position's missing negative assertion.
        assert not _check(chain, _save_signal(chain, [proof]))


@pytest.mark.parametrize("mode", ["ambiguous", "unique", "folded"])
def test_old_target_free_complete_definition_diagnostic_is_preserved(tmp_path, mode):
    with _variant(tmp_path, unique=mode == "unique", duplicate=mode == "folded",
                  folded=mode == "folded") as chain:
        old = _write(chain, _command(chain, factId="old-unbound"))
        inputs = minute_inputs(chain)
        proof = evaluate_unified_condition(chain.plan.ordinary_rules[0].condition, None,
            facts=({"id": old["id"], **old["payload"]},), target=inputs.minute_target
        ).model_dump(mode="json")
        assert proof["outcome"] == "SATISFIED"  # Frozen kind-only arrangement.
        assert _check(chain, _save_signal(chain, [proof])) is (mode != "ambiguous")


@pytest.mark.parametrize("damage", ["trade-date", "content", "same-time-conflict", "future"])
def test_bound_evidence_retains_day_content_conflict_and_availability_guards(tmp_path, damage):
    with _current(tmp_path) as chain:
        facts = [_register(chain, i) for i in range(2)]
        proof = _proof(chain, facts)
        if damage == "same-time-conflict":
            conflict = _write(chain, _command(chain, factId="conflicting-a", satisfied=False),
                              fact_selection=SELECTION)
            proof["children"][0]["fact_ids"].append(conflict["id"])
        else:
            payload = deepcopy(facts[0]["payload"])
            if damage == "trade-date":
                payload["trade_date"] = "2026-09-18"
                if "reviewed_fact_observation" in payload:
                    # Engineering counterexample: align shape only. source_hash
                    # still claims the newer source, not a verified old-day observation.
                    observation = payload["reviewed_fact_observation"]
                    old_day = datetime.fromisoformat(payload["trade_date"])
                    bar_end = datetime.fromisoformat(observation["bar_end"])
                    observation["bar_end"] = bar_end.replace(
                        year=old_day.year, month=old_day.month, day=old_day.day).isoformat()
            elif damage == "content":
                payload["content_hash"] = "0" * 64
                payload["reviewed_fact_target"]["content_hash"] = "0" * 64
            else:
                # Write while available, then turn back the test clock.
                chain.now += timedelta(minutes=1)
                payload["verified_at"] = payload["available_at"] = chain.now.isoformat()
            with chain.plans._unit_of_work() as work:
                work.daily.save(facts[0]["id"], kind="FACT", symbol=chain.plan.symbol,
                    lineage=chain.plan.plan_id, expected_revision=1, payload=payload)
                work.commit()
        identity = _save_signal(chain, [proof])
        if damage == "future":
            chain.now -= timedelta(minutes=1)
            # The signal's own row must stay available; only its cited fact is future.
            with chain.plans._unit_of_work() as work:
                work.daily.session.execute(update(DailyRecord).where(
                    DailyRecord.id == identity).values(created_at=chain.now.isoformat(),
                                                       updated_at=chain.now.isoformat()))
                work.commit()
        if damage == "future":
            # Keep the repository's pre-existing future-row rejection intact;
            # it is not a new leaf outcome or a registration failure.
            with pytest.raises(ValueError, match="invalid or future"):
                _check(chain, identity)
        else:
            assert not _check(chain, identity)


def test_signal_scope_must_keep_the_actual_signal_identity(tmp_path):
    with _current(tmp_path, scope="SIGNAL") as chain:
        signal_id = _signal(chain)
        facts = [_register(chain, i, signalId=signal_id) for i in range(2)]
        proof = _proof(chain, facts, signal_id=signal_id)
        with chain.plans._unit_of_work() as work, work.daily.session.no_autoflush:
            arguments = dict(confirmed_trade_date=chain.now.date(), owner_kind="ORDINARY_RULE",
                owner_id="low-buy", plan_version_id=chain.version["id"])
            assert fact_evidence_satisfied(
                work, chain.plan, [proof], signal_id=signal_id, **arguments)
            assert not fact_evidence_satisfied(
                work, chain.plan, [proof], signal_id="other", **arguments)
            assert not fact_evidence_satisfied(work, chain.plan, [proof], **arguments)


@pytest.mark.parametrize("borrow_sibling", [False, True])
def test_targeted_historical_risk_uses_actual_superseded_owner_not_equal_content_active(
        legacy, borrow_sibling):
    case = legacy(historical_fact_owner=True, buy_only_failure=True)
    identity, risk = _install_severe(case)
    with case.work() as work:
        original = work.plans.get_version_details(case.fact_owner_id)
        active = work.plans.get_version_details(case.id)
        assert original.status == "SUPERSEDED" and active.status == "ACTIVE"
        assert original.content_hash == active.content_hash
        native = load_plan_json(original.payload_json)
        selected_owner = load_plan_json(active.payload_json) if borrow_sibling else native
        selected_id = active.id if borrow_sibling else original.id
        targets = list_reviewed_fact_targets(selected_owner, plan_version_id=selected_id,
                                             content_hash=original.content_hash)
        for index, child in enumerate(risk["technical_evidence"][0]["children"]):
            row = work.daily.get(child["fact_ids"][0])
            target = next(t for t in targets if t.owner_kind == "RISK_BRANCH"
                and t.owner_id == risk_identity(native.risk_branches[1])
                and t.condition_path == f"condition.conditions[{index}]")
            # Deliberate stored engineering target arrangement: b3 does not
            # register risk targets. A sibling's digest cannot authenticate
            # the actual original owner merely by replacing its ID field.
            target = target.model_copy(update={"plan_version_id": original.id})
            work.daily.save(row["id"], kind="FACT", symbol=native.symbol,
                lineage=row["lineage"], expected_revision=row["revision"],
                payload={**row["payload"], "reviewed_fact_target": target.model_dump(mode="json")})
        work.commit()
    with case.work() as work:
        before = tuple(tuple(row) for row in work.daily.session.execute(
            select(DailyRecord.id, DailyRecord.payload_json).order_by(DailyRecord.id)))
        if borrow_sibling:
            with pytest.raises(SourceCoverageAuthorityError):
                require_source_action_authority(work, case.id, cause_id=identity)
        else:
            basis = require_source_action_authority(work, case.id, cause_id=identity)
            assert basis.basis == "HISTORICAL_TECHNICAL_RISK"
            assert identity in {row["id"] for row in basis.risk_rows}
        assert tuple(tuple(row) for row in work.daily.session.execute(
            select(DailyRecord.id, DailyRecord.payload_json).order_by(DailyRecord.id))) == before


def test_recheck_preserves_fact_signal_and_audit_bytes_and_rejects_pending_owner(tmp_path):
    with _current(tmp_path) as chain:
        facts = [_register(chain, i) for i in range(2)]
        identity = _save_signal(chain, [_proof(chain, facts)])

        def stored():
            with chain.plans._unit_of_work() as work:
                return tuple((model.__tablename__, tuple(tuple(row)
                    for row in work.daily.session.execute(select(model.__table__).order_by(
                        *model.__table__.primary_key.columns))))
                    for model in (DailyRecord, AuditLog))

        before = stored()
        assert _check(chain, identity)
        assert stored() == before
        with chain.plans._unit_of_work() as work, work.daily.session.no_autoflush:
            signal = work.daily.get(identity)["payload"]
            owner = work.daily.session.get(PlanVersion, chain.version["id"])
            owner.plan_hash = "0" * 64
            with pytest.raises(SourceCoverageAuthorityError, match="SOURCE_COVERAGE_INTEGRITY"):
                signal_fact_evidence_satisfied(work, chain.plan, signal)
            assert owner in work.daily.session.dirty and owner.plan_hash == "0" * 64
        assert stored() == before


@pytest.mark.parametrize("damage", ["hash", "owner", "path"])
def test_shaped_but_incorrect_stored_target_never_falls_back_to_legacy(tmp_path, damage):
    with _variant(tmp_path, unique=True) as chain:
        fact = _register(chain, 0)
        proof = _proof(chain, [fact])
        payload = deepcopy(fact["payload"])
        target = payload["reviewed_fact_target"]
        if damage == "hash":
            target["target_hash"] = "0" * 64
        elif damage == "owner":
            target["owner_id"] = "another-rule"
        else:
            target["condition_path"] = "independent_signal.reset_condition"
        with chain.plans._unit_of_work() as work:
            work.daily.save(fact["id"], kind="FACT", symbol=chain.plan.symbol,
                lineage=chain.plan.plan_id, expected_revision=1, payload=payload)
            work.commit()
        assert not _check(chain, _save_signal(chain, [proof]))


@pytest.mark.parametrize("owner_kind", ["ORDINARY_RULE", "ALERT_RULE", "RISK_BRANCH"])
def test_unsupported_native_type_has_no_inferred_condition_root(owner_kind):
    # Pure parsed-type guard; unlike the preceding tests, this does not arrange
    # a SQL owner or claim that legacy content can pass current FACT metadata.
    original = load_plan_json(TradePlan.model_validate(_valid_plan_payload()).model_dump_json())
    assert _target_leaf(original, [{"condition": {}}], 0, (), owner_kind, "old-rule") is None
