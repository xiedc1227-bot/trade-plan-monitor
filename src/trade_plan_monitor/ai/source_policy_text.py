"""Finite positive meanings for policy prose; text equality is not an evaluator."""

import re

from trade_plan_monitor.ai.source_obligations import MISSING, value_at

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
}
_SCOPE_REQUIREMENTS = {"Synthetic reviewed holding structure invalidation"}
_ANNOTATION_PHRASES = {"synthetic, not market rates", "Synthetic human proposal"}
_ATOM_KINDS = {
    "Review technical evidence for SEVERE_STRUCTURE": {"SEVERE_STRUCTURE"},
    "Review technical evidence for SEVERE_DETERIORATION": {"SEVERE_DETERIORATION"},
    "量能不能异常放大": {"VOLUME_OR_CANDLE"},
    "成交不异常放大": {"VOLUME_OR_CANDLE"},
    "明显下影": {"VOLUME_OR_CANDLE"},
    "相对深证成指不再转弱": {"TECHNICAL", "TRADE_VIABILITY"},
}
_ANNOTATION = re.compile(
    r"[A-Za-z0-9_./:#-]{1,256}|Exact synthetic (?:fixed )?threshold"
)


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
    if path.endswith((".source", ".excerpt", ".schedule_id", ".version", ".indicator",
                      ".reason", ".allocation_evidence")):
        return value in _ANNOTATION_PHRASES or _ANNOTATION.fullmatch(value) is not None
    return True  # Other string leaves are typed identifiers/enums/decimals.


def declaration_text_supported(declaration, values):
    """A complete JSON container cannot hide prose in a nested annotation."""
    from trade_plan_monitor.ai.source_semantics import declared_paths

    for path in declared_paths(declaration, values):
        value = (declaration.value if path == declaration.path else value_at(
            declaration.value, path[len(declaration.path):].lstrip(".")))
        if value is MISSING or not supported_policy_text(path, value, values):
            return False
    return supported_policy_text(declaration.path, declaration.value, values)
