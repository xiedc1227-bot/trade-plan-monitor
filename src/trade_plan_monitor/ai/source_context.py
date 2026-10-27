"""Finite complete-span non-policy syntax, never a market or inventory attestation."""

import re
from collections.abc import Mapping
from datetime import date

from trade_plan_monitor.domain.daily_hash import canonical

_MAX_SAFE_QUANTITY = 9_007_199_254_740_991
_HISTORY_ZH = re.compile(
    r"历史记录：(?P<day>[0-9]{4}-[0-9]{2}-[0-9]{2})(?:买入|卖出)"
    r"(?P<quantity>0|[1-9][0-9]{0,15})股。"
)
_HISTORY_EN = re.compile(
    r"Historical record: (?:bought|sold) (?P<quantity>0|[1-9][0-9]{0,15}) shares on "
    r"(?P<day>[0-9]{4}-[0-9]{2}-[0-9]{2})\."
)
_METADATA_LINE = re.compile(
    r"(?P<path>plan_id|version|name|metadata\.[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*)"
    r"[ \t]*=[ \t]*(?P<value>.+)"
)
_EXACT_CONTEXT = {
    "# Trade plan": "TITLE_EN",
    "# 交易计划": "TITLE_ZH",
    "账户记录：当前持仓0股。": "ACCOUNT_ZERO_ZH",
    "当前账户持仓0股。": "ACCOUNT_ZERO_ZH",
    "账户持仓：0股。": "ACCOUNT_ZERO_ZH",
    "你没有持仓。": "ACCOUNT_ZERO_ZH",
    "你目前0股。": "ACCOUNT_ZERO_ZH",
    "你当前0股。": "ACCOUNT_ZERO_ZH",
    "Account record: current holdings are 0 shares.": "ACCOUNT_ZERO_EN",
    "Current account holdings: 0 shares.": "ACCOUNT_ZERO_EN",
    "Account holdings: 0 shares.": "ACCOUNT_ZERO_EN",
    "You currently hold 0 shares.": "ACCOUNT_ZERO_EN",
}


def _historical_record(text: str) -> str | None:
    for pattern, identity in (
        (_HISTORY_ZH, "HISTORICAL_TRADE_ZH"),
        (_HISTORY_EN, "HISTORICAL_TRADE_EN"),
    ):
        match = pattern.fullmatch(text)
        if match is None:
            continue
        try:
            date.fromisoformat(match["day"])
        except ValueError:
            return None
        if int(match["quantity"]) <= _MAX_SAFE_QUANTITY:
            return identity
    return None


def _matching_metadata(text: str, metadata: Mapping[str, object] | None) -> bool:
    if not isinstance(metadata, Mapping) or (match := _METADATA_LINE.fullmatch(text)) is None:
        return False
    value = metadata
    for part in match["path"].split("."):
        if not isinstance(value, Mapping) or part not in value:
            return False
        value = value[part]
    try:
        return match["value"] == canonical(value)
    except (TypeError, ValueError, RecursionError):
        return False


def positive_context(text: str, *, metadata: Mapping[str, object] | None = None) -> str | None:
    """Return a registry ID only for a fully consumed positive non-policy form.

    ``metadata`` is the validated candidate's JSON-mode full dump. Historical
    quantities need no simulation buy-grid alignment: recognizing a statement
    never confirms holdings, a trade, a cost, an approval or the statement's truth.
    Outer whitespace is immaterial; additional statements remain unrecognized.
    """
    if not isinstance(text, str):
        return None
    text = text.strip()
    if identity := _EXACT_CONTEXT.get(text):
        return identity
    if identity := _historical_record(text):
        return identity
    if _matching_metadata(text, metadata):
        return "METADATA_EXACT_JSON"
    return None
