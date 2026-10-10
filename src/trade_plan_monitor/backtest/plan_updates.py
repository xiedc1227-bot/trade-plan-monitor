"""Deterministically materialize declared changes without account or review side effects."""

import json
from typing import Literal

from pydantic import Field, JsonValue

from trade_plan_monitor.ai.daily_review import semantic_values
from trade_plan_monitor.ai.plan_update_extraction import PlanUpdateExtractionOutput
from trade_plan_monitor.backtest.models import StableIdentifier
from trade_plan_monitor.backtest.research_input import ResearchValue
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft

COLLECTIONS = ("ordinary_rules", "risk_branches", "alert_rules")
SECTIONS = (
    "activation",
    "levels",
    "position",
    "monitoring",
    "execution_policy",
    "trading_rules",
    "metadata",
)


class PlanChange(ResearchValue):
    target: str = Field(min_length=1, max_length=64)
    rule_id: StableIdentifier | None
    action: Literal["ADD", "MODIFY", "REVOKE", "RETAIN"]
    before: JsonValue
    after: JsonValue
    clause_ids: tuple[StableIdentifier, ...] = Field(max_length=50)


class PlanFieldOrigin(ResearchValue):
    path: str = Field(min_length=1, max_length=512)
    origin: Literal["BASE", "CURRENT"]
    original_path: str = Field(min_length=1, max_length=512)


class MaterializedPlanUpdate(ResearchValue):
    draft: UnifiedPlanDraft
    changes: tuple[PlanChange, ...] = Field(max_length=64)
    origins: tuple[PlanFieldOrigin, ...] = Field(max_length=2000)


def _identity(target, rule):
    value = rule.get("kind" if target == "risk_branches" else "rule_id")
    if not value:
        raise ValueError("update rules need an explicit stable identity")
    return value


def _rules(target, values):
    mapped = {_identity(target, value): value for value in values}
    if len(mapped) != len(values):
        raise ValueError("update cannot repeat a rule identity")
    return mapped


def _change(target, key, before, after, clauses, action=None):
    return PlanChange(
        target=target,
        rule_id=key,
        before=before,
        after=after,
        clause_ids=clauses,
        action=action
        or (
            "ADD"
            if before is None
            else "REVOKE"
            if after is None
            else "RETAIN"
            if before == after
            else "MODIFY"
        ),
    )


def materialize_plan_update(
    base: UnifiedTradePlan,
    output: PlanUpdateExtractionOutput,
) -> MaterializedPlanUpdate:
    """Resolve whole sections or stable rules; undeclared draft fields have no effect."""
    if not isinstance(base, UnifiedTradePlan) or not isinstance(output, PlanUpdateExtractionOutput):
        raise TypeError("materialization requires a complete base and typed update")
    base = UnifiedTradePlan.model_validate(base.model_dump(mode="python"))
    output = PlanUpdateExtractionOutput.model_validate(output.model_dump(mode="python"))
    if output.scope == "UNRESOLVED":
        raise ValueError("ambiguous scope blocks dependent materialization")
    if (output.draft.symbol, output.draft.market) != (base.symbol, base.market):
        raise ValueError("update cannot change the symbol or market")
    prior = UnifiedPlanDraft.from_executable(base).model_dump(mode="json")
    proposed = output.draft.model_dump(mode="json")
    changes = []
    # Origins are chosen at the complete section/rule level, then expanded into field paths.
    sections = {key: ("BASE", key) for key in prior}
    rule_origins = {}
    for target in COLLECTIONS:
        _rules(target, proposed[target])
        rule_origins[target] = {
            _identity(target, rule): ("BASE", f"{target}[{index}]")
            for index, rule in enumerate(prior[target])
        }
    if output.scope == "FULL_REPLACEMENT":
        draft = output.draft
        for target in (*SECTIONS, *COLLECTIONS):
            if target in COLLECTIONS:
                before, after = _rules(target, prior[target]), _rules(target, proposed[target])
                for key in dict.fromkeys((*before, *after)):
                    changes.append(
                        _change(
                            target, key, before.get(key), after.get(key), output.scope_clause_ids
                        )
                    )
            else:
                changes.append(
                    _change(target, None, prior[target], proposed[target], output.scope_clause_ids)
                )
        origins = tuple(
            PlanFieldOrigin(path=path, origin="CURRENT", original_path=path)
            for path in sorted(semantic_values(draft))
        )
    else:
        explicit = {(op.target, op.rule_id) for op in output.operations}
        required = {(key, None) for key in SECTIONS}
        required.update((target, key) for target in COLLECTIONS for key in rule_origins[target])
        if not output.retain_unmentioned and not required <= explicit:
            raise ValueError("unmentioned scope cannot silently retain or remove prior content")
        merged = dict(prior)
        for target in COLLECTIONS:
            merged[target] = list(prior[target])
        merged["version"] = base.version + 1
        for op in output.operations:
            if op.target not in COLLECTIONS:
                before = prior[op.target]
                after = before if op.action == "RETAIN" else proposed[op.target]
                merged[op.target] = after
                sections[op.target] = (
                    "BASE" if op.action == "RETAIN" else "CURRENT",
                    op.target,
                )
            else:
                target = op.target
                old = _rules(target, prior[target])
                new = _rules(target, proposed[target])
                exists = op.rule_id in old
                if (op.action == "ADD") == exists:
                    raise ValueError("rule action conflicts with predecessor identity")
                if op.action in {"ADD", "MODIFY"} and op.rule_id not in new:
                    raise ValueError("changed rule is absent from current draft")
                before = old.get(op.rule_id)
                after = (
                    None
                    if op.action == "REVOKE"
                    else before
                    if op.action == "RETAIN"
                    else new[op.rule_id]
                )
                if op.action == "ADD":
                    merged[target].append(after)
                elif op.action != "RETAIN":
                    index = next(
                        i
                        for i, value in enumerate(merged[target])
                        if _identity(target, value) == op.rule_id
                    )
                    if op.action == "REVOKE":
                        merged[target].pop(index)
                        rule_origins[target].pop(op.rule_id)
                    else:
                        merged[target][index] = after
                if op.action in {"ADD", "MODIFY"}:
                    index = next(
                        i
                        for i, value in enumerate(proposed[target])
                        if _identity(target, value) == op.rule_id
                    )
                    rule_origins[target][op.rule_id] = ("CURRENT", f"{target}[{index}]")
                if not merged[target]:
                    sections[target] = ("CURRENT", target)
            changes.append(_change(op.target, op.rule_id, before, after, op.clause_ids, op.action))
        # Include implicit retention in the reviewable diff without claiming current evidence.
        for target, key in sorted(required - explicit, key=lambda pair: (pair[0], pair[1] or "")):
            value = _rules(target, prior[target])[key] if key is not None else prior[target]
            changes.append(_change(target, key, value, value, (), "RETAIN"))
        draft = UnifiedPlanDraft.model_validate_json(json.dumps(merged))
        origins = []
        for path in sorted(semantic_values(draft)):
            target = path.split(".", 1)[0].split("[", 1)[0]
            origin, original = sections[target]
            prefix = target
            if target in COLLECTIONS and path.startswith(target + "["):
                prefix = path.split("]", 1)[0] + "]"
                index = int(prefix.split("[")[1][:-1])
                key = _identity(target, merged[target][index])
                origin, original = rule_origins[target][key]
            origins.append(
                PlanFieldOrigin(
                    path=path,
                    origin=origin,
                    original_path=original + path[len(prefix) :],
                )
            )
        origins = tuple(origins)
    return MaterializedPlanUpdate(draft=draft, changes=tuple(changes), origins=origins)
