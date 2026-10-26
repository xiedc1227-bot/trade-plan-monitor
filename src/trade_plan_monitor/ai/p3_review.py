"""Narrow monetary-source checks supplement, never replace exact human review."""

import re
from decimal import Decimal


def capital_source_matches(path, value, excerpt):
    if not excerpt.strip():
        return False
    if isinstance(value, str) and re.fullmatch(r"[+-]?\d+(?:\.\d+)?", value):
        matches = re.findall(r"(?<![A-Za-z0-9_.])([+-]?\d+(?:\.\d+)?)([%％]?)"
                             r"(?![A-Za-z0-9_.])", excerpt)
        return any(Decimal(number) / (100 if percent else 1) == Decimal(value)
                   for number, percent in matches)
    if type(value) is int:
        numbers = re.findall(r"(?<![A-Za-z0-9_.])([+-]?\d+(?:\.\d+)?)\s*(元|yuan)?"
                             r"(?![A-Za-z0-9_.])",
                             excerpt, re.I)
        return any(Decimal(n)*(100 if unit and path.endswith("_fen") else 1) == value
                   for n, unit in numbers)
    if not isinstance(value, str):
        return False
    if path.endswith(".mode"):
        negatives = r"(?:不采用|不使用|不启用|禁止|do\s+not\s+(?:use|enable|apply)|not)\s*"
        if re.search(negatives+re.escape(value), excerpt, re.I):
            return False
        aliases = {"OPEN_COST_CAP": ("持仓成本占用上限", "持仓保留成本上限"),
            "MARKET_VALUE_CAP": ("持仓市值上限",),
            "CAPITAL_ONLY": ("仅金额上限", "只设金额上限"),
            "QUANTITY_AND_CAPITAL": ("股数和金额同时限制", "股数与金额组合上限")}
        if value == "OPEN_COST_CAP" and re.search(
            r"(?:means|is|指|按).{0,12}(?:cumulative lifetime purchases|累计买入支出|净投入)",
            excerpt, re.I,
        ):
            return False
        for alias in aliases.get(value, ()):
            if alias in excerpt:
                return not re.search(negatives+re.escape(alias), excerpt, re.I)
    aliases = {"CNY": ("人民币",), "SIMULATION": ("模拟账户", "工具模拟"),
        "SYMBOL_CORE_AND_TACTICAL": ("全部模拟持仓", "底仓和机动仓合计"),
        "CURRENT_ADMITTED_QUOTE": ("当前准入报价", "当前有效报价")}
    return (bool(re.search(r"(?<![\w])"+re.escape(value)+r"(?![\w])", excerpt))
            or any(a in excerpt for a in aliases.get(value, ())))
