"""Jinja-free deterministic Chinese alert rendering."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import date, datetime
from decimal import Decimal
from html import escape

from trade_plan_monitor.decision.models import (
    ActionableSignalType,
    ConditionEvidence,
    EvaluationEvidence,
    EvidenceFact,
    EvidenceUnit,
    RuleEvidence,
)
from trade_plan_monitor.notifications.models import (
    AlertPayload,
    AlertPriceZone,
    ExplicitAlertPayload,
)

MAX_ALERT_TEXT_CHARS = 16_384
DISCLAIMER = "仅提醒，不会自动下单。"

_SIGNAL_LABELS = {
    ActionableSignalType.BUY_CORE_READY: "低吸底仓买点成立",
    ActionableSignalType.BUY_TACTICAL_READY: "低吸机动仓买点成立",
    ActionableSignalType.PRESSURE_REDUCE_READY: "压力位机动仓减仓条件成立",
    ActionableSignalType.RISK_BREACH: "官方收盘跌破风险线",
    ActionableSignalType.RISK_EXIT_READY: "风险退出条件成立",
    ActionableSignalType.RISK_EXIT_PENDING_SETTLEMENT: "风险退出待T+1结算",
}
_NEXT_STEPS = {
    ActionableSignalType.BUY_CORE_READY: "人工确认后自行决定是否下单",
    ActionableSignalType.BUY_TACTICAL_READY: "人工确认后自行决定是否下单",
    ActionableSignalType.PRESSURE_REDUCE_READY: "人工确认后自行决定是否减仓",
    ActionableSignalType.RISK_BREACH: "暂停加仓，等待下一交易日官方收盘",
    ActionableSignalType.RISK_EXIT_READY: "人工确认后自行决定是否减仓",
    ActionableSignalType.RISK_EXIT_PENDING_SETTLEMENT: "等待下一交易日解禁后重新评估",
}
_ZONE_LABELS = {
    "LOW_BUY": "低吸区",
    "PRESSURE": "压力区",
}
_RULE_LABELS = {
    "PLAN_INACTIVE": "计划未激活",
    "DATA_NOT_READY": "所需行情未就绪",
    "DAILY_LIMIT_UNKNOWN": "当日涨跌停价未知",
    "EPISODE_HISTORY_GAP": "事件历史存在缺口",
    "BEARISH_VOLUME_EXPANSION": "阴线成交量异常放大",
    "RISK_PENDING": "风险状态待确认",
    "PRESSURE_TOUCH": "价格已触及压力区",
    "RISK_RECOVERY": "官方收盘已收回风险线",
    "RISK_DETERIORATION": "风险相对原始跌破继续恶化",
}


def render_explicit_alert(payload: ExplicitAlertPayload) -> str:
    """Render a bounded explicit reminder without implying order execution."""

    if type(payload) is not ExplicitAlertPayload:
        raise TypeError("payload must be an ExplicitAlertPayload")
    title = {"BUY": "买入提醒", "SELL": "卖出提醒", "RISK_ALERT": "风险提醒"}[payload.signal_type]
    quantity_line = () if payload.quantity is None else (f"提醒数量: {payload.quantity}股",)
    next_step = {
        "BUY": "人工复核后自行决定是否下单",
        "SELL": "人工复核后另行登记实际减仓",
        "RISK_ALERT": "人工复核风险，不会自动卖出或改变风险状态",
    }[payload.signal_type]
    lines = (
        f"[{title}] {payload.name} {payload.symbol}",
        f"规则: {payload.rule_id}",
        f"完成K线: {payload.target_bucket_end.isoformat()}",
        *quantity_line,
        "条件证据: 已满足",
        f"下一步: {next_step}",
        DISCLAIMER,
    )
    value = "\n".join(lines)
    if len(value) > MAX_ALERT_TEXT_CHARS:
        raise ValueError("rendered alert exceeds the text limit")
    return value


_FACT_LABELS = {
    "current_price_fen": "当前价",
    "risk_status": "风险状态",
    "price_fen": "价格",
    "quantity": "数量",
    "target_quantity": "目标数量",
    "volume_shares": "成交量",
    "bar_count": "K线数",
    "touch_at": "触价时间",
}
_OUTCOME_LABELS = {
    "SATISFIED": "成立",
    "UNSATISFIED": "未成立",
    "MISSING_INPUT": "缺少输入",
}


class AlertRenderError(ValueError):
    """Stable fail-closed rendering failure."""


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():  # protected by evidence/domain validation
        raise AlertRenderError("alert contains an invalid number")
    sign, digits, exponent = value.as_tuple()
    if not any(digits):
        return "0"
    if not isinstance(exponent, int):  # pragma: no cover - finite guard above
        raise AlertRenderError("alert contains an invalid number")

    end = len(digits)
    normalized_exponent = exponent
    while digits[end - 1] == 0:
        end -= 1
        normalized_exponent += 1
    coefficient = "".join(str(digit) for digit in digits[:end])
    prefix = "-" if sign else ""
    decimal_point = len(coefficient) + normalized_exponent
    if normalized_exponent >= 0 and decimal_point <= 256:
        return f"{prefix}{coefficient}{'0' * normalized_exponent}"
    if 0 < decimal_point <= 256:
        return f"{prefix}{coefficient[:decimal_point]}.{coefficient[decimal_point:]}"
    if -16 < decimal_point <= 0:
        return f"{prefix}0.{'0' * -decimal_point}{coefficient}"
    mantissa = coefficient[0]
    if len(coefficient) > 1:
        mantissa += f".{coefficient[1:]}"
    scientific_exponent = normalized_exponent + len(coefficient) - 1
    return f"{prefix}{mantissa}e{scientific_exponent}"


def _fen_text(value: int) -> str:
    sign = "-" if value < 0 else ""
    absolute = abs(value)
    return f"{sign}{absolute // 100}.{absolute % 100:02d}元"


def _fact_value(fact: EvidenceFact) -> str:
    value = fact.value
    if fact.unit is EvidenceUnit.FEN:
        return _fen_text(value)
    if fact.unit is EvidenceUnit.SHARES:
        return f"{_decimal_text(value) if isinstance(value, Decimal) else value}股"
    if fact.unit is EvidenceUnit.RATIO:
        return _decimal_text(value) if isinstance(value, Decimal) else str(value)
    if fact.unit is EvidenceUnit.BARS:
        return f"{value}根"
    if fact.unit is EvidenceUnit.YUAN:
        return f"{_decimal_text(value)}元"
    if fact.unit is EvidenceUnit.COUNT:
        return f"{value}个"
    if fact.unit is EvidenceUnit.BOOLEAN:
        return "是" if value else "否"
    if fact.unit is EvidenceUnit.DATE:
        return value.isoformat() if isinstance(value, date) else str(value)
    if fact.unit is EvidenceUnit.DATETIME:
        return value.strftime("%Y-%m-%d %H:%M") if isinstance(value, datetime) else str(value)
    return escape(str(value), quote=True)


def _fact_text(fact: EvidenceFact) -> str:
    label = _FACT_LABELS.get(fact.key, fact.key)
    return f"{label}={_fact_value(fact)}"


def _ratio(value: object) -> str:
    return _decimal_text(value) if isinstance(value, Decimal) else str(value)


def _condition_label(evidence: ConditionEvidence) -> str:
    condition = evidence.condition
    kind = condition.type
    if kind == "PRICE_IN_ZONE":
        return f"价格位于{_ZONE_LABELS[condition.zone]}"
    if kind == "NO_NEW_LOW_FOR_BARS":
        return f"连续{condition.bars}根5分钟K线未创新低"
    if kind == "NON_DECREASING_CLOSE":
        return "最新5分钟收盘不低于前一根"
    if kind == "VOLUME_TO_PREVIOUS_LTE":
        return f"成交量不高于前一根的{_ratio(condition.max_ratio)}倍"
    if kind == "VOLUME_TO_MEDIAN_LTE":
        return f"成交量不高于前{condition.window_bars}根中位数的{_ratio(condition.max_ratio)}倍"
    if kind == "VOLUME_TO_MEDIAN_GTE":
        return f"成交量达到前{condition.window_bars}根中位数的{_ratio(condition.minimum_ratio)}倍"
    if kind == "MACD_HIST_IMPROVEMENT_GTE":
        return f"MACD柱改善至少{_ratio(condition.minimum_improvement)}"
    if kind == "PRICE_RECLAIMS_INDICATOR":
        return f"价格重新站上{condition.indicator}"
    if kind == "UPPER_WICK_RATIO_GTE":
        return f"上影线占振幅至少{_ratio(condition.minimum_ratio)}"
    if kind == "RETREAT_FROM_SESSION_HIGH_GTE":
        return f"较当日高点回落至少{_ratio(condition.minimum_ratio)}"
    if kind == "CLOSE_IN_BAR_LOWER_HALF":
        return "收盘位于K线下半部"
    if kind == "CONSECUTIVE_CLOSES_BELOW_LEVEL":
        return f"连续{condition.bars}根收盘低于压力参考位"
    if kind == "OFFICIAL_CLOSE_BELOW_LEVEL":
        return "官方收盘低于风险线"
    if kind == "NEXT_TRADING_DAY_RECOVERY":
        return "后续交易日收回风险线"
    if kind == "POSITION_BUCKET_AVAILABLE":
        return f"{condition.bucket}仓位可用"
    if kind == "SELLABLE_QUANTITY_GTE":
        return f"{condition.bucket}可卖数量不少于{condition.quantity}股"
    if kind == "MANUAL_EVENT_RISK_CLEAR":
        return "人工事件风险标记已清除"
    if kind == "DISTANCE_FROM_LIMIT_DOWN_GTE":
        return f"距跌停价至少{_ratio(condition.minimum_ratio)}"
    if kind == "LOWER_BAND_HITS_LTE":
        return f"前{condition.window_bars}根下轨命中不超过{condition.max_hits}次"
    return "全部条件" if kind == "ALL" else "任一条件"


def _evidence_chunks(evidence: EvaluationEvidence) -> Iterator[str]:
    if isinstance(evidence, RuleEvidence):
        label = _RULE_LABELS[evidence.code.value]
        facts = evidence.facts
        missing_inputs = evidence.missing_inputs
    else:
        label = _condition_label(evidence)
        facts = evidence.facts
        missing_inputs = evidence.missing_inputs
    yield label
    yield f"【{_OUTCOME_LABELS[evidence.outcome.value]}】"
    if facts:
        yield "（"
        for index, fact in enumerate(facts):
            if index:
                yield "；"
            yield _fact_text(fact)
        yield "）"
    if missing_inputs:
        yield "（缺少："
        for index, value in enumerate(missing_inputs):
            if index:
                yield "、"
            yield value.value
        yield "）"
    if isinstance(evidence, ConditionEvidence) and evidence.children:
        yield "{"
        for index, child in enumerate(evidence.children):
            if index:
                yield "；"
            yield from _evidence_chunks(child)
        yield "}"


def _evidence_line_chunks(
    label: str,
    evidence: tuple[EvaluationEvidence, ...],
) -> Iterator[str]:
    yield f"{label}："
    if not evidence:
        yield "无"
        return
    for index, value in enumerate(evidence):
        if index:
            yield "；"
        yield from _evidence_chunks(value)


class _BoundedAlertText:
    """Accumulate alert fragments without ever retaining an oversized result."""

    def __init__(self) -> None:
        self._parts: list[str] = []
        self._length = 0
        self._has_line = False

    def add_line(self, chunks: Iterable[str]) -> None:
        if self._has_line:
            self._add("\n")
        for chunk in chunks:
            self._add(chunk)
        self._has_line = True

    def _add(self, chunk: str) -> None:
        if len(chunk) > MAX_ALERT_TEXT_CHARS - self._length:
            raise AlertRenderError("alert text is too large")
        self._parts.append(chunk)
        self._length += len(chunk)

    def build(self) -> str:
        return "".join(self._parts)


def _suggestion(payload: AlertPayload) -> str:
    signal_type = payload.signal_type
    if signal_type is ActionableSignalType.RISK_BREACH:
        return "暂停加仓"
    quantity = payload.quantity
    if quantity is None:  # protected by AlertPayload validation
        raise AlertRenderError("alert action is incomplete")
    if signal_type is ActionableSignalType.BUY_CORE_READY:
        return f"低吸底仓{quantity}股"
    if signal_type is ActionableSignalType.BUY_TACTICAL_READY:
        return f"低吸机动仓{quantity}股"
    if signal_type is ActionableSignalType.PRESSURE_REDUCE_READY:
        return f"减仓机动仓{quantity}股"
    if payload.bucket is None:
        if signal_type is ActionableSignalType.RISK_EXIT_PENDING_SETTLEMENT:
            return f"目标持仓{quantity}股尚不可卖"
        return f"提示卖出已确认持仓{quantity}股（未指定批次）"
    bucket = "机动仓" if payload.bucket == "TACTICAL" else "底仓"
    if signal_type is ActionableSignalType.RISK_EXIT_PENDING_SETTLEMENT:
        return f"目标{bucket}{quantity}股尚不可卖"
    return f"卖出{bucket}{quantity}股"


def _zone_line(zone: AlertPriceZone) -> str:
    lower = "含下界" if zone.include_low else "不含下界"
    upper = "含上界" if zone.include_high else "不含上界"
    return (
        f"区间：{_ZONE_LABELS[zone.zone.value]}{_fen_text(zone.low_fen)[:-1]}～"
        f"{_fen_text(zone.high_fen)}（{lower}、{upper}）"
    )


def render_alert(payload: AlertPayload) -> str:
    """Render one validated alert as bounded escaped plain text."""

    if not isinstance(payload, AlertPayload):
        raise TypeError("payload must be an AlertPayload")
    market_text = "不可用（延迟未知）"
    if payload.market_data_at is not None:
        market_text = f"{payload.market_data_at:%Y-%m-%d %H:%M}（延迟{payload.data_age_seconds}秒）"
    price_text = "不可用" if payload.price_fen is None else _fen_text(payload.price_fen)
    rendered = _BoundedAlertText()
    rendered.add_line(
        (
            f"【{_SIGNAL_LABELS[payload.signal_type]}｜{payload.severity.value}】"
            f"{escape(payload.name, quote=True)}（{payload.symbol}）",
        ),
    )
    rendered.add_line((f"时间：{payload.evaluated_at:%Y-%m-%d %H:%M}  行情：{market_text}",))
    rendered.add_line((f"价格：{price_text}  建议：{_suggestion(payload)}",))
    if payload.relevant_zone is not None:
        rendered.add_line((_zone_line(payload.relevant_zone),))
    rendered.add_line(_evidence_line_chunks("信号成立", payload.matched_conditions))
    rendered.add_line(_evidence_line_chunks("结果成立", payload.satisfied_conditions))
    rendered.add_line(_evidence_line_chunks("结果未成立", payload.unmet_conditions))
    rendered.add_line(_evidence_line_chunks("阻断", payload.blockers))
    rendered.add_line(
        (
            f"风险线："
            f"{_fen_text(payload.risk_line_fen) if payload.risk_line_fen else '未提供'}"
            f"  计划：{escape(payload.plan_id, quote=True)}-v{payload.plan_version}",
        )
    )
    rendered.add_line((f"下一步：{_NEXT_STEPS[payload.signal_type]}",))
    rendered.add_line((f"原因：{escape(payload.cause_id, quote=True)}",))
    rendered.add_line((f"事件：{payload.event_id}",))
    rendered.add_line((DISCLAIMER,))
    return rendered.build()


__all__ = [
    "AlertRenderError",
    "DISCLAIMER",
    "MAX_ALERT_TEXT_CHARS",
    "render_alert",
    "render_explicit_alert",
]
