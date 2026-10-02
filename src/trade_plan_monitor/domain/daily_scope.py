"""Finite daily scope treatments, not a natural-language semantic classifier.

Only these exact known source fragments may be excluded automatically. Unknown
wording remains visible for technical review; arbitrary BACKGROUND is not authority.
"""

from hashlib import sha256

EXCLUSION_REASON = "FUNDAMENTALS_REVIEWED_AT_PLAN_GENERATION"
FUNDAMENTAL_FRAGMENTS = (
    "必要公告核验完成、未发现使买入逻辑失效的重大利空",
    "公告核验不完整",
    "不把“未查到”当作“没有利空”",
    "无法合理排除重大事件风险时不新增买入",
    "经官方信息核实且明确推翻持有理由时",
    "重大基本面逻辑失效",
    "传闻和普通业绩波动不自动等同于逻辑失效",
    "其他公告及基本面变化",
    "基本面优势及核心风险",
    "基本面仅在生成计划时由用户审核",
    "Fundamentals are reviewed by the user when generating the plan",
    "Announcement verification is outside daily monitoring",
)


def excluded_spans(source, clause):
    """Return nonoverlapping exact registered fragments inside one legacy clause."""
    spans = []
    for fragment in FUNDAMENTAL_FRAGMENTS:
        start = clause.start
        while (start := source.find(fragment, start, clause.end)) != -1:
            end = start + len(fragment)
            if not any(start < old_end and end > old_start for old_start, old_end in spans):
                spans.append((start, end))
            start = end
    return tuple(sorted(spans))


def scope_hash(source):
    return sha256(source.encode()).hexdigest()


def require_nontechnical_exclusion(excerpt):
    """Reject concrete technical contract terms in an explicit human scope selection.

    This guard is deliberately finite. The explicit human content review owns
    semantic classification for other wording, without attesting business truth.
    """
    terms = (
        "收盘",
        "止跌",
        "破位",
        "风险线",
        "低吸区",
        "压力区",
        "缩量",
        "放量",
        "均线",
        "MACD",
        "RSI",
        "ATR",
        "BOLL",
        "CORE",
        "TACTICAL",
        "停牌",
        "可交易",
        "交易日",
        "成交",
        "股价",
        "买入",
        "卖出",
        "加仓",
        "减仓",
        "close",
        "technical",
        "tradability",
        "suspension",
    )
    if any(term.casefold() in excerpt.casefold() for term in terms):
        raise ValueError("technical or operational policy cannot be a scope exclusion")


def require_inventory_assertion(excerpt):
    """Admit explicit holdings context, never common conditional trading instructions."""
    if not any(
        term in excerpt.casefold()
        for term in ("持仓", "成本", "库存", "holdings", "inventory", "cost")
    ) or any(
        term in excerpt.casefold()
        for term in (
            "收盘",
            "低于",
            "高于",
            "跌破",
            "买入",
            "卖出",
            "加仓",
            "减仓",
            "止跌",
            "缩量",
            "均线",
            "macd",
            "rsi",
            "atr",
            "boll",
            "if ",
            "below",
            "above",
            "buy",
            "sell",
        )
    ):
        raise ValueError("inventory assertion cannot hide technical trading policy")


def require_technical_text(value):
    """Reject explicit excluded semantics relabelled as a daily human fact.

    This finite guard covers named scope terms and registered source fragments;
    human review still owns arbitrary natural-language semantic correctness.
    """
    forbidden = (
        "ANNOUNCEMENT_CHECK",
        "FUNDAMENTAL_INVALIDATION",
        "基本面",
        "公告核验",
        "fundamental",
        "announcement verification",
        "holding thesis",
        "earnings",
    )
    if any(term.casefold() in value.casefold() for term in forbidden):
        raise ValueError("fundamental/announcement semantics are excluded from daily monitoring")
    return value
