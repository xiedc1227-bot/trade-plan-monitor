"""Private attribution diagnostics for unbound facts, never action authority.

Callers must resolve the fact's actual SQL owner before passing its native plan.
The content digest alone cannot identify a PlanVersion: it omits display identity.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.domain.daily_plan_models import (
    DailyAll,
    DailyAny,
    DailyResetPolicy,
    DailyTradePlan,
    Identifier,
    ReviewedDailyFact,
)
from trade_plan_monitor.domain.plan_hash import daily_plan_content_sha256, plan_sha256
from trade_plan_monitor.domain.risk_scope import risk_identity
from trade_plan_monitor.domain.unified_plan_models import (
    UnifiedAll,
    UnifiedAny,
    UnifiedResetPolicy,
    UnifiedTradePlan,
)

CONTROL_FACT_KINDS = frozenset({
    "TRADABILITY", "FULL_SESSION_SUSPENSION", "INDEPENDENT_EVENT", "SIGNAL_INVALIDATION",
})
PREDICATE_FACT_KINDS = frozenset({
    "PRICE_STRUCTURE", "VOLUME_OR_CANDLE", "TECHNICAL", "TRADE_VIABILITY",
    "SEVERE_STRUCTURE", "SEVERE_DETERIORATION",
})
FactReason = Literal[
    "CONTROL_FACT", "UNIQUE_DEFINITION", "NO_DEFINITION", "AMBIGUOUS_DEFINITION",
    "CONTENT_MISMATCH", "INVALID_FACT",
]


@dataclass(frozen=True, slots=True)
class FactDefinition:
    owner_kind: Literal["ORDINARY_RULE", "ALERT_RULE", "RISK_BRANCH"]
    owner_id: str
    condition_path: str
    definition_json: str
    observation_context: str
    fact_kind: str
    validity_scope: Literal["TRADE_DATE", "SIGNAL"]


@dataclass(frozen=True, slots=True)
class UnboundFactDecision:
    reason: FactReason
    definition_json: str | None = None
    definition_count: int = 0
    definitions: tuple[FactDefinition, ...] = ()

    @property
    def usable(self) -> bool:
        return self.reason == "UNIQUE_DEFINITION"


def _definitions(plan):
    refs = []
    leaves = 0

    def walk(node, owner_kind, owner_id, path, context, depth=1):
        nonlocal leaves
        if depth > 4:
            raise ValueError("native condition depth exceeds four")
        if isinstance(node, (DailyAll, DailyAny, UnifiedAll, UnifiedAny)):
            for index, child in enumerate(node.conditions):
                walk(child, owner_kind, owner_id, f"{path}.conditions[{index}]",
                     context, depth + 1)
            return
        leaves += 1
        if leaves > 50:
            raise ValueError("native condition leaves exceed fifty")
        if isinstance(node, ReviewedDailyFact):
            refs.append(FactDefinition(owner_kind, owner_id, path,
                canonical(node.model_dump(mode="json")), context,
                node.fact_kind, node.validity_scope))

    for rule in plan.ordinary_rules:
        if rule.status != "ENABLED":
            continue
        unified = isinstance(plan, UnifiedTradePlan)
        confirmation = (rule.confirmation.model_dump(mode="json") if unified else
                        {"kind": plan.execution_policy.confirmation})
        validity = rule.validity.model_dump(mode="json")
        context = canonical(dict(purpose="ORDINARY_CONFIRMATION",
                                 confirmation=confirmation, validity=validity))
        roots = (("condition", rule.condition),) if unified else tuple(
            (name, getattr(rule, name)) for name in
            ("price_structure", "volume_or_candle", "technical")) + tuple(
                (f"prerequisites[{i}]", node) for i, node in enumerate(rule.prerequisites))
        for path, node in roots:
            walk(node, "ORDINARY_RULE", rule.rule_id, path, context)
        if isinstance(rule.independent_signal, (DailyResetPolicy, UnifiedResetPolicy)):
            reset_context = canonical(dict(purpose="RESET", validity=validity))
            walk(rule.independent_signal.reset_condition, "ORDINARY_RULE", rule.rule_id,
                 "independent_signal.reset_condition", reset_context)
    if isinstance(plan, UnifiedTradePlan):
        for rule in plan.alert_rules:
            context = canonical(dict(purpose="ALERT_CONFIRMATION",
                                     confirmation=rule.confirmation.model_dump(mode="json")))
            walk(rule.condition, "ALERT_RULE", rule.rule_id, "condition", context)
        for branch in plan.risk_branches:
            if branch.kind == "SEVERE_TECHNICAL" and branch.condition is not None:
                context = canonical(dict(purpose="RISK_CONFIRMATION",
                                         evidence_mode=branch.evidence_mode))
                walk(branch.condition, "RISK_BRANCH", risk_identity(branch),
                     "condition", context)
    return tuple(refs)


def _payload(fact):
    if isinstance(fact, BaseModel):
        fact = fact.model_dump(mode="json")
    return fact if isinstance(fact, Mapping) else None


def _valid_date(value):
    if type(value) is date:
        return True
    if type(value) is not str:
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _assess(content_hash, definitions, fact):
    value = _payload(fact)
    if value is None:
        return UnboundFactDecision("INVALID_FACT")
    kind = value.get("kind")
    if type(kind) is not str:
        return UnboundFactDecision("INVALID_FACT")
    if content_hash is None:
        return UnboundFactDecision("INVALID_FACT")
    declared = tuple(ref for ref in definitions if ref.fact_kind == kind)
    if kind in CONTROL_FACT_KINDS and not declared:
        return UnboundFactDecision("CONTROL_FACT")
    if (kind not in PREDICATE_FACT_KINDS | CONTROL_FACT_KINDS
            or value.get("verified") is not True
            or not _valid_date(value.get("trade_date"))
            or type(value.get("satisfied", True)) is not bool
            or value.get("signal_id") is not None and type(value.get("signal_id")) is not str):
        return UnboundFactDecision("INVALID_FACT")
    if value.get("content_hash") != content_hash:
        return UnboundFactDecision("CONTENT_MISMATCH")
    refs = tuple(ref for ref in declared
                 if ref.validity_scope == "TRADE_DATE" or bool(value.get("signal_id")))
    keys = {(ref.definition_json, ref.observation_context) for ref in refs}
    if not keys:
        return UnboundFactDecision("NO_DEFINITION")
    if len(keys) != 1:
        return UnboundFactDecision("AMBIGUOUS_DEFINITION", definition_count=len(keys),
                                   definitions=refs)
    return UnboundFactDecision("UNIQUE_DEFINITION", refs[0].definition_json, 1, refs)


def _catalog(owner_plan):
    if not isinstance(owner_plan, DailyTradePlan):
        return None, ()
    try:
        return daily_plan_content_sha256(owner_plan), _definitions(owner_plan)
    except (TypeError, ValueError, AttributeError, RecursionError):
        return None, ()


def assess_unbound_fact(
    owner_plan: DailyTradePlan, fact: Mapping[str, object] | BaseModel,
) -> UnboundFactDecision:
    """Classify one actual owner's fact without granting truth, review or execution."""
    return _assess(*_catalog(owner_plan), fact)


def filter_unbound_facts(
    owner_plan: DailyTradePlan, facts: tuple[dict, ...],
) -> tuple[dict, ...]:
    """Project predicate inputs only; callers retain all rows for freshness/audit."""
    catalog = _catalog(owner_plan)
    return tuple(fact for fact in facts if (result := _assess(*catalog, fact)).usable
                 or result.reason == "CONTROL_FACT")


class ReviewedFactTarget(BaseModel):
    """Private exact selector, never a verified fact, review or authority token."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    version: Literal["reviewed-fact-target-v1"]
    plan_version_id: Identifier
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    owner_kind: Literal["ORDINARY_RULE", "ALERT_RULE", "RISK_BRANCH"]
    owner_id: Identifier
    condition_path: str = Field(min_length=1, max_length=512)
    target_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


def _bound_definitions(owner_plan, plan_version_id, content_hash):
    TypeAdapter(Identifier).validate_python(plan_version_id, strict=True)
    native_content, definitions = _catalog(owner_plan)
    if (native_content is None or type(content_hash) is not str
            or content_hash != native_content):
        raise ValueError("explicit fact target requires the supplied native content")
    return definitions


def _explicit_target(plan_version_id, content_hash, native_plan_hash, definition):
    selector = dict(version="reviewed-fact-target-v1", plan_version_id=plan_version_id,
                    content_hash=content_hash, owner_kind=definition.owner_kind,
                    owner_id=definition.owner_id, condition_path=definition.condition_path)
    target_hash = daily_hash("reviewed-fact-target-v1", {
        **selector, "native_plan_hash": native_plan_hash,
        "definition_json": definition.definition_json,
        "observation_context": definition.observation_context,
    })
    return ReviewedFactTarget(**selector, target_hash=target_hash)


def list_reviewed_fact_targets(
    owner_plan: DailyTradePlan, *, plan_version_id: str, content_hash: str,
) -> tuple[ReviewedFactTarget, ...]:
    """Reuse the native catalog without folding repeated explicit positions.

    The caller must reread the actual SQL owner and supply its plan and identity.
    This pure function cannot authenticate that correspondence or current review.
    """
    definitions = _bound_definitions(owner_plan, plan_version_id, content_hash)
    native_hash = plan_sha256(owner_plan)
    return tuple(_explicit_target(plan_version_id, content_hash, native_hash, ref)
                 for ref in definitions)


def resolve_reviewed_fact_target(
    owner_plan: DailyTradePlan, target: Mapping[str, object] | BaseModel,
    *, plan_version_id: str,
) -> FactDefinition:
    """Resolve exactly one native leaf; never infer a target from kind or text.

    Revalidate even a supplied model. Date, signal, completed observation, review
    and original SQL ownership remain the authoritative caller's responsibility.
    """
    selected = ReviewedFactTarget.model_validate(_payload(target))
    definitions = _bound_definitions(owner_plan, plan_version_id, selected.content_hash)
    matches = tuple(ref for ref in definitions if (
        ref.owner_kind, ref.owner_id, ref.condition_path) == (
            selected.owner_kind, selected.owner_id, selected.condition_path))
    if len(matches) != 1 or selected != _explicit_target(
        plan_version_id, selected.content_hash, plan_sha256(owner_plan), matches[0],
    ):
        raise ValueError("explicit fact target does not match the supplied native owner")
    return matches[0]
