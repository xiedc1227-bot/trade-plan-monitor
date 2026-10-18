"""Read-only comparisons of final frozen policies, independent of mutable reviews."""

from typing import Literal

from pydantic import Field

from trade_plan_monitor.backtest.models import Sha256Hex, StableIdentifier
from trade_plan_monitor.backtest.plan_updates import COLLECTIONS, PlanChange
from trade_plan_monitor.backtest.preparation_review import FrozenPreparedCollection
from trade_plan_monitor.domain.risk_scope import risk_identity
from trade_plan_monitor.web.schemas import ApiValue

_IDENTITY_FIELDS = {"schema_version", "plan_id", "version", "symbol", "name", "market"}


class BacktestRuleChangesView(ApiValue):
    run_id: Sha256Hex
    manifest_hash: Sha256Hex
    source_id: StableIdentifier
    version_id: StableIdentifier
    previous_source_id: StableIdentifier | None
    previous_version_id: StableIdentifier | None
    relationship: Literal["INITIAL", "INHERITED", "INDEPENDENT"]
    # Old/new rule identities can be disjoint; include both plus policy sections.
    changes: tuple[PlanChange, ...] = Field(max_length=192)


def compare_plan_values(before: dict | None, after: dict) -> tuple[PlanChange, ...]:
    """Compare every policy field; list order cannot rename stable rule identities."""
    previous = before or {}
    changes = []
    for target in dict.fromkeys((*previous, *after)):
        if target in _IDENTITY_FIELDS:
            continue
        if target in COLLECTIONS:
            identity_of = risk_identity if target == "risk_branches" else lambda r: r["rule_id"]
            old = {identity_of(rule): rule for rule in previous.get(target, [])}
            new = {identity_of(rule): rule for rule in after.get(target, [])}
            pairs = [(identity, old.get(identity), new.get(identity))
                     for identity in dict.fromkeys((*old, *new))]
        else:
            pairs = [(None, previous.get(target), after.get(target))]
        for identity, old, new in pairs:
            if old is None and new is None:
                continue
            action = ("ADD" if old is None else "REVOKE" if new is None
                      else "RETAIN" if old == new else "MODIFY")
            changes.append(PlanChange(target=target, rule_id=identity, action=action,
                                      before=old, after=new, clause_ids=()))
    return tuple(changes)


def project_rule_changes(
    run_id: str, prepared: FrozenPreparedCollection, source_id: str,
) -> BacktestRuleChangesView | None:
    for index, item in enumerate(prepared.items):
        if item.source.source_id != source_id:
            continue
        previous = prepared.items[index - 1] if index else None
        return BacktestRuleChangesView(
            run_id=run_id, manifest_hash=prepared.manifest_hash,
            source_id=source_id, version_id=item.version.version_id,
            previous_source_id=previous.source.source_id if previous else None,
            previous_version_id=previous.version.version_id if previous else None,
            relationship="INITIAL" if previous is None else (
                "INDEPENDENT" if item.independent else "INHERITED"
            ),
            changes=compare_plan_values(
                previous.version.snapshot.model_dump(mode="json") if previous else None,
                item.version.snapshot.model_dump(mode="json"),
            ),
        )
    return None
