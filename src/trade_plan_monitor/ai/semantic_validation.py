"""Representation checks shared by initial plans and predecessor patches."""

import re
from decimal import Decimal

from trade_plan_monitor.ai.daily_review import semantic_values


def semantic_interpretation_matches(path, value, excerpt, draft):
    """Check quantities and units literally; semantic enums are reviewable translations.

    A proposed meaning is never a human supplement or a satisfied market fact.
    Unlike legacy decoding, enum attribution does not depend on a verb dictionary.
    """
    from trade_plan_monitor.ai.source_resolution import interpretation_matches, plain

    text = plain(excerpt)
    if not text.strip():
        return False
    if path in {"symbol", "market"}:
        return interpretation_matches(path, value, excerpt, draft)
    if path.endswith((".ratio", ".minimum_ratio")):
        if any(
            Decimal(n) == Decimal(str(value))
            for n in re.findall(r"(\d+(?:\.\d+)?)\s*(?:倍|times|x\b)", text, re.I)
        ):
            return True
        return any(
            Decimal(n) / 100 == Decimal(str(value))
            for n in re.findall(r"(\d+(?:\.\d+)?)\s*[%％]", text)
        )
    if path.endswith(".sessions") and type(value) is int:
        words = {
            "一": 1,
            "二": 2,
            "两": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
            "十": 10,
        }
        if any(
            words[word] == value
            for word in re.findall(r"([一二两三四五六七八九十])(?:个)?(?:交易日|收盘|日|天)", text)
        ):
            return True
    if type(value) is int or (
        path.endswith(".reference.value") and re.fullmatch(r"\d+(?:\.\d+)?", str(value))
    ):
        return interpretation_matches(path, value, excerpt, draft)
    # Source clauses, paths, values and units are checked by build_daily_review.
    # Semantic role/enum translations remain visible for whole-plan review.
    return True


def semantic_representation_issues(draft):
    """Executable node names inside prose are not executable conditions.

    This checks the condition language, not natural-language sentence patterns.
    It cannot establish semantic completeness; source review remains necessary.
    """
    return tuple(
        ("AI_COMPUTABLE_CONDITION_UNEXPANDED", path)
        for path, value in semantic_values(draft).items()
        if path.endswith(".evidence_requirement")
        and isinstance(value, str)
        and re.search(r"\b(?:DAILY|MINUTE)_[A-Z_]+\b", value)
    )
