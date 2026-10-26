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
    if ".market_policy.exception_routes." in path:
        if value == "PER_OCCURRENCE" and re.search(
            r"(?:不|未|暂不)(?:允许|启用|采用|授权)|禁止|取消|"
            r"\b(?:do\s+not|don't|never)\s+(?:allow|enable|authorize)\b",
            text, re.I,
        ):
            return False
        if re.search(r"(?<!\w)" + re.escape(str(value)) + r"(?!\w)", excerpt):
            return True
        name = "最低量例外" if path.endswith("weak_minimum") else "明显破坏强势例外"
        return (value == "PER_OCCURRENCE" and f"允许逐次人工复评{name}" in text
                or value == "DISABLED" and f"关闭{name}" in text)
    if ".market_policy.expanded." in path:
        # Unlike general enum translations, a version label cannot stand in
        # for all the conditions hidden behind a built-in strategy expansion.
        from trade_plan_monitor.domain.market_linkage_definitions import (
            EXPANDED_EXCEPTION_POLICY_ZH,
            EXPANDED_LINKAGE_POLICY_ZH,
        )
        # The approved definition itself says approval does not execute a trade;
        # that is a required restriction, not a negation of the policy definition.
        negative_text = (text.replace("批准不执行交易", "")
                         if draft.schema_version in {7, 8} else text)
        if re.search(
            r"(?:不|未|暂不)(?:采用|使用|执行|启用)|取消(?:以下|该|此)?(?:定义|规则|政策)|"
            r"\b(?:do\s+not|don't|never)\s+(?:apply|use|adopt|enable)\b",
            negative_text, re.I,
        ):
            return False
        def normalized(text):
            return re.sub(r"[\s;；\"'。，,：:]", "", text).casefold()
        translations = (
            str(value),
            (EXPANDED_EXCEPTION_POLICY_ZH if draft.schema_version in {7, 8}
             else EXPANDED_LINKAGE_POLICY_ZH).get(path.rsplit(".", 1)[-1], str(value)),
        )
        return any(normalized(text) in normalized(excerpt) for text in translations)
    if ".pretrade_policy." in path and isinstance(value, str) and re.fullmatch(
            r"[+-]?\d+(?:\.\d+)?", value):
        return any(Decimal(n) == Decimal(value) for n in re.findall(
            r"(?<![\w.])[+-]?\d+(?:\.\d+)?(?![\w.])", text))
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
