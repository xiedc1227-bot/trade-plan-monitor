"""Independent scope/identity oracles for reviewed plan update materialization."""

import json

import pytest
from tests.unit.test_monitor_loop_extraction import update_output
from tests.unit.test_unified_replay_input import research_plan

from trade_plan_monitor.ai.plan_update_extraction import PlanUpdateExtractionOutput


def proposed(base=None, *, scope="FULL_REPLACEMENT", operations=(), retain=False, **changes):
    base = base or research_plan()
    raw = update_output()
    raw.update(
        draft=base.model_dump(mode="json") | changes,
        scope=scope,
        retain_unmentioned=retain,
        operations=list(operations),
    )
    return PlanUpdateExtractionOutput.model_validate_json(json.dumps(raw))


def operation(action, rule_id=None, target="ordinary_rules"):
    return {
        "target": target,
        "action": action,
        "rule_id": rule_id,
        "clause_ids": update_output()["scope_clause_ids"],
    }


def test_full_replacement_drops_old_rule_and_uses_only_the_new_complete_draft():
    from trade_plan_monitor.backtest.plan_updates import materialize_plan_update

    base = research_plan()
    old = base.ordinary_rules[0]
    new = old.model_copy(update={"rule_id": "replacement-rule", "quantity": 200})
    output = proposed(base, ordinary_rules=[new.model_dump(mode="json")])
    result = materialize_plan_update(base, output)
    assert [rule.rule_id for rule in result.draft.ordinary_rules] == ["replacement-rule"]
    assert result.draft.ordinary_rules[0].quantity == 200
    assert result.draft.to_executable() is not None
    changes = {(item.target, item.rule_id, item.action) for item in result.changes}
    assert ("ordinary_rules", old.rule_id, "REVOKE") in changes
    assert ("ordinary_rules", "replacement-rule", "ADD") in changes
    assert all(item.origin == "CURRENT" for item in result.origins)
    assert base.ordinary_rules == (old,)


def test_partial_add_and_modify_use_named_rules_and_ignore_unmentioned_draft_values():
    from trade_plan_monitor.backtest.plan_updates import materialize_plan_update

    base = research_plan()
    old = base.ordinary_rules[0]
    modified = old.model_copy(update={"quantity": 200})
    added = old.model_copy(update={"rule_id": "new-sell", "side": "SELL", "quantity": 300})
    output = proposed(
        base,
        scope="EXPLICIT_CHANGES",
        retain=True,
        operations=(
            operation("MODIFY", old.rule_id),
            operation("ADD", "new-sell"),
        ),
        ordinary_rules=[added.model_dump(mode="json"), modified.model_dump(mode="json")],
        position={"max_qty": 500},
        name="AI changed unmentioned name",
        plan_id="foreign",
        version=99,
    )
    result = materialize_plan_update(base, output)
    assert {rule.rule_id: rule.quantity for rule in result.draft.ordinary_rules} == {
        old.rule_id: 200,
        "new-sell": 300,
    }
    assert result.draft.position.max_qty == base.position.max_qty == 1000
    assert (result.draft.plan_id, result.draft.version, result.draft.name) == (
        base.plan_id,
        base.version + 1,
        base.name,
    )
    assert base.ordinary_rules[0].quantity == 100


def test_explicit_retain_ignores_changed_proposed_values_and_keeps_base_origins():
    from trade_plan_monitor.backtest.plan_updates import materialize_plan_update

    base = research_plan()
    rule = base.ordinary_rules[0]
    output = proposed(
        base,
        scope="EXPLICIT_CHANGES",
        retain=True,
        operations=(operation("RETAIN", rule.rule_id),),
        ordinary_rules=[
            rule.model_copy(update={"quantity": 900}).model_dump(mode="json"),
        ],
    )
    result = materialize_plan_update(base, output)
    assert result.draft.ordinary_rules[0].quantity == 100
    origin = next(item for item in result.origins if item.path == "ordinary_rules[0].quantity")
    assert (origin.origin, origin.original_path) == ("BASE", "ordinary_rules[0].quantity")
    retained = next(item for item in result.changes if item.rule_id == rule.rule_id)
    assert retained.action == "RETAIN" and retained.before == retained.after


def test_revoke_remaps_retained_rule_evidence_to_its_original_index():
    from trade_plan_monitor.ai.daily_review import semantic_values
    from trade_plan_monitor.backtest.plan_updates import materialize_plan_update

    base = research_plan()
    first = base.ordinary_rules[0]
    second = first.model_copy(update={"rule_id": "keep-sell", "side": "SELL", "quantity": 200})
    base = base.model_copy(update={"ordinary_rules": (first, second)})
    result = materialize_plan_update(
        base,
        proposed(
            base,
            scope="EXPLICIT_CHANGES",
            retain=True,
            operations=(operation("REVOKE", first.rule_id),),
            ordinary_rules=[],
        ),
    )
    assert [rule.rule_id for rule in result.draft.ordinary_rules] == ["keep-sell"]
    origins = {item.path: item for item in result.origins}
    assert len(origins) == len(result.origins)
    assert set(origins) == set(semantic_values(result.draft))
    assert origins["ordinary_rules[0].quantity"].origin == "BASE"
    assert origins["ordinary_rules[0].quantity"].original_path == "ordinary_rules[1].quantity"


def test_revoke_last_rule_marks_empty_collection_current_without_inventing_authority():
    from trade_plan_monitor.backtest.plan_updates import materialize_plan_update

    base = research_plan()
    result = materialize_plan_update(
        base,
        proposed(
            base,
            scope="EXPLICIT_CHANGES",
            retain=True,
            operations=(operation("REVOKE", base.ordinary_rules[0].rule_id),),
        ),
    )
    assert result.draft.ordinary_rules == () and result.draft.to_executable() is None
    empty = next(item for item in result.origins if item.path == "ordinary_rules")
    assert empty.origin == "CURRENT"
    untouched = next(item for item in result.origins if item.path == "risk_branches")
    assert untouched.origin == "BASE"


def test_scalar_modification_replaces_the_whole_section_and_ignores_unmentioned_rules():
    from trade_plan_monitor.backtest.plan_updates import materialize_plan_update

    base = research_plan()
    forged = base.ordinary_rules[0].model_copy(update={"quantity": 900})
    result = materialize_plan_update(
        base,
        proposed(
            base,
            scope="EXPLICIT_CHANGES",
            retain=True,
            operations=(operation("MODIFY", target="position"),),
            position={"max_qty": 500},
            ordinary_rules=[forged.model_dump(mode="json")],
        ),
    )
    assert result.draft.position.max_qty == 500
    assert result.draft.ordinary_rules[0].quantity == 100
    assert (
        result.draft.position.core_target_qty is result.draft.position.tactical_target_qty is None
    )
    origin = next(item for item in result.origins if item.path == "position.max_qty")
    assert (origin.origin, origin.original_path) == ("CURRENT", "position.max_qty")


@pytest.mark.parametrize(
    "action,identity,target",
    [
        ("ADD", "existing", "ordinary_rules"),
        ("MODIFY", "absent", "ordinary_rules"),
        ("REVOKE", "absent", "ordinary_rules"),
        ("RETAIN", "absent", "ordinary_rules"),
        ("REVOKE", "unknown-risk", "risk_branches"),
    ],
)
def test_unknown_or_conflicting_target_identity_rejects(action, identity, target):
    from trade_plan_monitor.backtest.plan_updates import materialize_plan_update

    base = research_plan()
    identity = base.ordinary_rules[0].rule_id if identity == "existing" else identity
    output = proposed(
        base,
        scope="EXPLICIT_CHANGES",
        retain=True,
        operations=(operation(action, identity, target),),
    )
    with pytest.raises(ValueError):
        materialize_plan_update(base, output)


def test_unresolved_scope_and_unmentioned_sections_without_retention_reject():
    from trade_plan_monitor.backtest.plan_updates import materialize_plan_update

    base = research_plan()
    for output in (
        proposed(base, scope="UNRESOLVED", retain=None),
        proposed(
            base,
            scope="EXPLICIT_CHANGES",
            retain=False,
            operations=(operation("RETAIN", base.ordinary_rules[0].rule_id),),
        ),
    ):
        with pytest.raises(ValueError):
            materialize_plan_update(base, output)
    explicit = tuple(
        operation("RETAIN", target=target)
        for target in (
            "activation",
            "levels",
            "position",
            "monitoring",
            "execution_policy",
            "trading_rules",
            "metadata",
        )
    ) + (operation("RETAIN", base.ordinary_rules[0].rule_id),)
    result = materialize_plan_update(
        base,
        proposed(
            base,
            scope="EXPLICIT_CHANGES",
            retain=False,
            operations=explicit,
        ),
    )
    assert result.draft.to_executable() is not None
    assert result.draft.ordinary_rules[0].quantity == 100


def test_missing_modified_value_stays_incomplete_instead_of_inheriting_old_authority():
    from trade_plan_monitor.backtest.plan_updates import materialize_plan_update

    base = research_plan()
    raw_rule = base.ordinary_rules[0].model_dump(mode="json") | {
        "condition": None,
        "quantity": None,
    }
    result = materialize_plan_update(
        base,
        proposed(
            base,
            scope="EXPLICIT_CHANGES",
            retain=True,
            operations=(operation("MODIFY", raw_rule["rule_id"]),),
            ordinary_rules=[raw_rule],
        ),
    )
    assert result.draft.ordinary_rules[0].condition is None
    assert result.draft.ordinary_rules[0].quantity is None
    assert result.draft.to_executable() is None
    assert base.ordinary_rules[0].condition is not None


def test_changed_symbol_and_forged_incomplete_base_cannot_be_materialized():
    from trade_plan_monitor.backtest.plan_updates import materialize_plan_update
    from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan

    base = research_plan()
    with pytest.raises(ValueError):
        materialize_plan_update(base, proposed(base, symbol="002240.SZ", market="SZSE"))
    raw = {name: getattr(base, name) for name in type(base).model_fields}
    raw["position"] = type(base.position).model_construct(max_qty=None)
    forged = UnifiedTradePlan.model_construct(**raw)
    with pytest.raises((TypeError, ValueError)):
        materialize_plan_update(forged, proposed(base))
