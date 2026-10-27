"""Finite positive meanings for policy prose; text equality is not an evaluator."""

from trade_plan_monitor.ai.source_obligations import MISSING, value_at
from trade_plan_monitor.market_data.daily_indicators import PARAMETERS

# These are complete atomic requirements, never satisfied runtime facts. The
# synthetic forms support deterministic contract fixtures, not real-AI accuracy.
_MANUAL_REQUIREMENTS = {
    "Synthetic reviewer checks complete official evidence",
    "Review technical evidence for SEVERE_STRUCTURE",
    "Review technical evidence for SEVERE_DETERIORATION",
    "量能不能异常放大",
    "成交不异常放大",
    "明显下影",
    "相对深证成指不再转弱",
}
_INDEPENDENT_REQUIREMENTS = {
    "New structure linked to prior signal",
    "Human confirms a new independent technical event",
    "Explicit reviewed independent event linked to the prior signal; "
    "unchanged true evidence never resets it.",
}
_SCOPE_REQUIREMENTS = {"Synthetic reviewed holding structure invalidation"}
_ANNOTATIONS = {
    ".source": {
        "fixture", "Exact synthetic threshold", "Exact synthetic fixed threshold",
        "Synthetic threshold",
    },
    ".excerpt": {"synthetic, not market rates"},
    ".schedule_id": {"synthetic"},
    ".version": {"test-v1"},
    ".indicator": frozenset(PARAMETERS),
    ".reason": frozenset(),
    ".allocation_evidence": {"Synthetic human proposal"},
}
_ATOM_KINDS = {
    "Review technical evidence for SEVERE_STRUCTURE": {"SEVERE_STRUCTURE"},
    "Review technical evidence for SEVERE_DETERIORATION": {"SEVERE_DETERIORATION"},
    "量能不能异常放大": {"VOLUME_OR_CANDLE"},
    "成交不异常放大": {"VOLUME_OR_CANDLE"},
    "明显下影": {"VOLUME_OR_CANDLE"},
    "相对深证成指不再转弱": {"TECHNICAL", "TRADE_VIABILITY"},
}


def supported_policy_text(path, value, values):
    """Every free prose carrier needs a whole positive production of its own."""
    if not isinstance(value, str):
        return True
    if path.endswith(".scope_evidence"):
        return value in _SCOPE_REQUIREMENTS
    if path.endswith(".independent_signal.evidence_requirement"):
        return value in _INDEPENDENT_REQUIREMENTS
    if path.endswith(".evidence_requirement"):
        required = _ATOM_KINDS.get(value)
        kind = values.get(path.removesuffix("evidence_requirement") + "fact_kind")
        return value in _MANUAL_REQUIREMENTS and (required is None or kind in required)
    for suffix, meanings in _ANNOTATIONS.items():
        if path.endswith(suffix):
            return value in meanings
    return True  # Other string leaves are typed identifiers/enums/decimals.


def declaration_text_supported(declaration, values):
    """A complete JSON container cannot hide prose in a nested annotation."""
    from trade_plan_monitor.ai.source_semantics import declared_paths

    for path in declared_paths(declaration, values):
        value = (declaration.value if path == declaration.path else value_at(
            {"root": declaration.value}, "root" + path[len(declaration.path):]))
        if value is MISSING or not supported_policy_text(path, value, values):
            return False
    return supported_policy_text(declaration.path, declaration.value, values)
