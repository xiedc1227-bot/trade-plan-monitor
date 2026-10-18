"""Bounded read-only explanations from verified frozen-loop audit evidence."""

import re
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from trade_plan_monitor.backtest.plan_schedule import LoopTimestamp
from trade_plan_monitor.backtest.research_input import ResearchValue

DiagnosticCategory = Literal[
    "MARKET_UNMET",
    "QUALITATIVE_UNRESOLVED",
    "PROCESSING_ERROR",
    "DATA_UNAVAILABLE",
    "EXECUTION_BLOCKED",
    "NO_BUY_RULE",
    "NO_EVALUATION",
    "CONDITION_MET",
]
_ORDER = {
    name: i
    for i, name in enumerate(
        (
            "MARKET_UNMET",
            "QUALITATIVE_UNRESOLVED",
            "PROCESSING_ERROR",
            "DATA_UNAVAILABLE",
            "EXECUTION_BLOCKED",
            "CONDITION_MET",
            "NO_BUY_RULE",
            "NO_EVALUATION",
        )
    )
}
_COMPARE = {"GT": "高于", "GTE": "不低于", "LT": "低于", "LTE": "不高于", "EQ": "等于"}
_PRICE = {"close": "收盘价", "open": "开盘价", "high": "最高价", "low": "最低价"}
_REASONS = {
    "PRICE_BASIS_UNVERIFIED": "该时点日线价格基准尚未可用，仅影响该时点的判断",
    "DAILY_HISTORY_MISSING": "该时点所需日线历史不足",
    "PRIOR_CLOSE_HISTORY_REQUIRED": "先行收盘所需历史窗口不完整",
    "CASH_UNKNOWN": "旧回测没有确定现金依据",
    "INSUFFICIENT_CASH": "账户余额不足以执行完整数量",
    "POSITION_LIMIT": "达到计划最大持仓限制",
}


class LoopDiagnosticExample(ResearchValue):
    category: DiagnosticCategory
    rule_id: str = Field(max_length=160)
    at: LoopTimestamp
    sequence: int = Field(ge=1)
    root_outcome: Literal["SATISFIED", "UNSATISFIED", "MISSING_INPUT"] | None
    requirement: str = Field(max_length=400)
    actual: str = Field(max_length=400)
    reason: str = Field(max_length=200)


class LoopPlanDiagnostic(ResearchValue):
    source_id: str = Field(max_length=160)
    version_id: str = Field(max_length=160)
    effective_trade_date: date
    buy_rule_count: int = Field(ge=0)
    fill_count: int | None = Field(ge=0)
    evaluation_count: int = Field(ge=0)
    unmet_count: int = Field(ge=0)
    missing_count: int = Field(ge=0)
    satisfied_count: int = Field(ge=0)
    review_status: Literal["PASSED"] = "PASSED"
    categories: tuple[DiagnosticCategory, ...] = Field(max_length=8)
    examples: tuple[LoopDiagnosticExample, ...] = Field(max_length=8)
    sampled: bool


class LoopDiagnostics(ResearchValue):
    availability: Literal["AVAILABLE", "EXPIRED", "UNAVAILABLE"]
    plans: tuple[LoopPlanDiagnostic, ...] = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def bounded_identity(self):
        if len({p.version_id for p in self.plans}) != len(self.plans):
            raise ValueError("diagnostic plan versions must be unique")
        if sum(len(p.examples) for p in self.plans) > 256:
            raise ValueError("diagnostic examples exceed the response budget")
        if self.availability != "AVAILABLE" and any(
            p.examples or p.fill_count is not None for p in self.plans
        ):
            raise ValueError("missing audit cannot claim per-plan fills or examples")
        return self


def _money(value):
    whole, _, fraction = format(Decimal(str(value)) / 100, "f").partition(".")
    return f"{whole}.{fraction.rstrip('0').ljust(2, '0')} 元"


def _leaves(evidence):
    """A satisfied alternative does not make its unused branches blockers."""
    if not evidence.children:
        yield evidence
        return
    for child in evidence.children:
        if evidence.condition.type == "ANY" and evidence.outcome == "SATISFIED":
            if child.outcome != "SATISFIED":
                continue
        yield from _leaves(child)


def _explain(leaf, quote):
    condition, operands = leaf.condition, leaf.operands
    tag = condition.type
    if tag == "REVIEWED_FACT":
        return (
            condition.evidence_requirement.split("\n原文约束：", 1)[0],
            "核验记录确认该条件未满足"
            if leaf.outcome == "UNSATISFIED"
            else "尚无该条件的已核验证据；不假定已满足",
        )
    if tag == "DAILY_PRICE_COMPARE":
        name = _PRICE.get(condition.field, condition.field)
        target = (
            _money(operands[-1])
            if len(operands) >= 2
            else (
                _money(condition.reference.value)
                if condition.reference.mode == "FIXED"
                else "计划约定的动态参照"
            )
        )
        actual = f"{name} {_money(operands[0])}" if len(operands) >= 2 else "价格依据不可用"
        if leaf.session_dates:
            actual = f"{leaf.session_dates[0]} {actual}"
        return f"{name}{_COMPARE.get(condition.comparator, condition.comparator)} {target}", actual
    if tag == "DAILY_PRIOR_CLOSE":
        requirement = (
            f"自 {condition.since_date} 起，先有更早交易日完整收盘"
            f"{_COMPARE[condition.comparator]} {_money(condition.price_fen)}，再判断回踩"
        )
        if len(operands) > 1:
            actual = "先行收盘：" + "、".join(_money(v) for v in operands[:-1][-3:])
        else:
            actual = (
                "尚无窗口内更早交易日的合格收盘"
                if leaf.outcome == "UNSATISFIED"
                else "先行收盘依据不可用"
            )
        if quote is not None and quote.price_fen is not None:
            actual += (
                f"；当时最新行情价 {_money(quote.price_fen)}"
                f"（{quote.price_at:%m-%d %H:%M}，不作先行收盘确认）"
            )
        return requirement, actual
    if tag == "DAILY_CLOSE_SEQUENCE":
        actual = (
            "收盘序列：" + "、".join(_money(v) for v in operands[:5])
            if operands
            else "收盘序列依据不可用"
        )
        requirement = (
            "逐次不下移" if condition.mode == "PAIRWISE_NONDECREASING" else "逐次满足计划参照值比较"
        )
        return f"连续 {condition.sessions} 个收盘{requirement}", actual
    if tag == "DAILY_PRICE_IN_RANGE":
        return (
            f"{_PRICE.get(condition.field, condition.field)}在 "
            f"{'[' if condition.range.include_low else '('}{_money(condition.range.low_fen)} 至 "
            f"{_money(condition.range.high_fen)}{']' if condition.range.include_high else ')'}",
            _money(operands[0]) if operands else "价格依据不可用",
        )
    if tag in {"MINUTE_CLOSE_IN_RANGE", "MINUTE_CLOSE_BELOW"}:
        requirement = (
            f"5 分钟收盘价低于 {_money(condition.price_fen)}"
            if tag == "MINUTE_CLOSE_BELOW"
            else f"5 分钟收盘价在 {'[' if condition.include_low else '('}"
            f"{_money(condition.low_fen)} 至 {_money(condition.high_fen)}"
            f"{']' if condition.include_high else ')'}"
        )
        return requirement, _money(operands[0]) if operands else "完整 5 分钟价格依据不可用"
    if tag in {"DAILY_VOLUME_RATIO", "DAILY_CANDLE_RATIO"}:
        name = (
            "量比"
            if tag == "DAILY_VOLUME_RATIO"
            else {
                "LOWER_WICK": "下影线占振幅比例",
                "UPPER_WICK": "上影线占振幅比例",
                "BODY": "实体占振幅比例",
            }[condition.component]
        )
        return (
            f"{name}{_COMPARE[condition.comparator]} {condition.ratio}",
            f"实际{name} {operands[2]}" if len(operands) >= 3 else "计算依据不可用",
        )
    return "计划约定的指标／量能／分钟条件", (
        "已记录计算值：" + "、".join(operands[:5]) if operands else "没有可展示的计算值"
    )


class PlanDiagnosticCollector:
    """Streaming accumulator; no decisions, provider calls or mutable preparation reads."""

    def __init__(self, versions, *, response_mode):
        self.response_mode = response_mode
        self.states = {}
        self.quote = None
        for source_id, day, version in versions:
            self.states[version.version_id] = {
                "source_id": source_id,
                "version_id": version.version_id,
                "effective_trade_date": day,
                "rules": {r.rule_id for r in version.snapshot.ordinary_rules if r.side == "BUY"},
                "fill_count": 0,
                "evaluation_count": 0,
                "unmet_count": 0,
                "missing_count": 0,
                "satisfied_count": 0,
                "categories": set(),
                "examples": {},
                "overflow": False,
            }

    def _add(
        self, state, category, event, rule="", root=None, requirement="", actual="", reason=""
    ):
        state["categories"].add(category)
        example = LoopDiagnosticExample(
            category=category,
            rule_id=rule[:160],
            at=event.at,
            sequence=event.sequence,
            root_outcome=root,
            requirement=requirement[:400],
            actual=actual[:400],
            reason=reason[:200],
        )
        # One representative per day/rule/criterion; never accumulate minute-sized payloads.
        key = (category, rule, event.at.date(), example.requirement)
        state["examples"][key] = example
        if len(state["examples"]) > 32:
            del state["examples"][next(iter(state["examples"]))]
            state["overflow"] = True

    def observe(self, event):
        payload = event.payload
        if payload.kind == "VALUATION":
            self.quote = payload.valuation
        version_id = getattr(event, "version_id", next(iter(self.states)))
        state = self.states.get(version_id)
        if state is None:
            return
        if payload.kind == "VALUATION" and not state["rules"]:
            quote = payload.valuation
            if quote.price_fen is not None and quote.price_at.date() == event.at.date():
                self._add(
                    state,
                    "NO_BUY_RULE",
                    event,
                    requirement="本版本没有直接买入规则；观察或风险退出不构成买入授权",
                    actual=f"最新行情价 {_money(quote.price_fen)}（{quote.price_at:%m-%d %H:%M}）",
                )
        if payload.kind == "EXECUTED":
            if payload.attempt.status == "FILLED":
                state["fill_count"] += 1
            else:
                self._add(
                    state,
                    "EXECUTION_BLOCKED",
                    event,
                    actual=_REASONS.get(payload.attempt.reason, "执行条件未满足，未产生成交"),
                    reason=payload.attempt.reason or "",
                )
            return
        if payload.kind != "EVALUATED" or payload.duplicate:
            return
        state["evaluation_count"] += 1
        for reason in payload.blockers:
            category = (
                "DATA_UNAVAILABLE"
                if any(
                    v in reason
                    for v in ("BASIS", "HISTORY", "DATA", "CALENDAR", "QUOTE", "BAR", "INPUT")
                )
                else "EXECUTION_BLOCKED"
            )
            if reason.startswith(
                ("DAILY_SOURCE_", "EXTRACTION_", "AI_", "SOURCE_BINDING_", "PLAN_PARAMETER_")
            ):
                category = "PROCESSING_ERROR"
            self._add(
                state,
                category,
                event,
                actual=_REASONS.get(reason, "该时点评估受限，原因保留在核对标识中"),
                reason=reason,
            )
        for row in payload.conditions:
            if row.rule_id not in state["rules"]:
                continue
            root = row.evidence.outcome
            state[
                {
                    "UNSATISFIED": "unmet_count",
                    "MISSING_INPUT": "missing_count",
                    "SATISFIED": "satisfied_count",
                }[root]
            ] += 1
            if root == "SATISFIED" and self.response_mode != "FOLLOW_REMINDERS":
                self._add(
                    state,
                    "EXECUTION_BLOCKED",
                    event,
                    row.rule_id,
                    root,
                    requirement="按本次回测响应方式执行",
                    actual=(
                        "仅观察提醒，不自动模拟成交"
                        if self.response_mode == "OBSERVE_ONLY"
                        else "按记录动作执行，条件满足不自动产生成交"
                    ),
                    reason=self.response_mode,
                )
            for leaf in _leaves(row.evidence):
                # Keep counts for every evaluation, but do not fill the examples
                # with holiday/midnight repetitions of an earlier closing bar.
                is_minute = leaf.condition.type.startswith("MINUTE_")
                is_fact = leaf.condition.type == "REVIEWED_FACT"
                if payload.official_trade_date != event.at.date() and not (
                    (is_minute or is_fact)
                    and payload.minute_target is not None
                    and payload.minute_target.date() == event.at.date()
                ):
                    continue
                if leaf.condition.type == "REVIEWED_FACT":
                    if leaf.outcome == "SATISFIED":
                        continue
                    category = (
                        "QUALITATIVE_UNRESOLVED"
                        if leaf.outcome == "MISSING_INPUT"
                        else "MARKET_UNMET"
                    )
                elif leaf.outcome == "MISSING_INPUT":
                    category = (
                        "PROCESSING_ERROR"
                        if leaf.reason
                        in {
                            "UNSUPPORTED_DAILY_CONDITION",
                            "REFERENCE_UNIT_MISMATCH",
                        }
                        else "DATA_UNAVAILABLE"
                    )
                else:
                    category = "MARKET_UNMET" if leaf.outcome == "UNSATISFIED" else "CONDITION_MET"
                requirement, actual = _explain(leaf, self.quote)
                if is_fact and any(
                    c.condition.type == "DAILY_PRIOR_CLOSE" for c in _leaves(row.evidence)
                ):
                    requirement = re.sub(
                        r"^完整日K(?:首次)?重新(?:收盘站上|收回)\d+(?:\.\d+)?(?:以上)?[；;]",
                        "",
                        requirement,
                    )
                if is_fact:
                    requirement = re.sub(
                        r"须在buy-[A-Za-z0-9.-]+完成后", "须在前一笔买入完成后", requirement
                    )
                self._add(
                    state,
                    category,
                    event,
                    row.rule_id,
                    root,
                    requirement,
                    actual,
                    leaf.reason or "",
                )

    def finish(self, *, availability="AVAILABLE"):
        states = list(self.states.values())
        choices = [
            sorted(s["examples"].values(), key=lambda e: (_ORDER[e.category], -e.at.timestamp()))[
                :8
            ]
            for s in states
        ]
        # Reserve one example for each source before spending the remaining response budget.
        selected = [[] for _ in states]
        budget = 256
        for index in range(8):
            for i, examples in enumerate(choices):
                if budget and index < len(examples):
                    selected[i].append(examples[index])
                    budget -= 1
        plans = []
        for state, examples in zip(states, selected, strict=True):
            categories = set(state["categories"])
            if not state["rules"]:
                categories.add("NO_BUY_RULE")
            elif not state["evaluation_count"]:
                categories.add("NO_EVALUATION")
            if state["satisfied_count"] and not state["fill_count"]:
                categories.add("EXECUTION_BLOCKED")
            plans.append(
                LoopPlanDiagnostic(
                    **{
                        k: state[k]
                        for k in (
                            "source_id",
                            "version_id",
                            "effective_trade_date",
                            "evaluation_count",
                            "unmet_count",
                            "missing_count",
                            "satisfied_count",
                        )
                    },
                    buy_rule_count=len(state["rules"]),
                    fill_count=state["fill_count"] if availability == "AVAILABLE" else None,
                    categories=tuple(sorted(categories, key=_ORDER.get)),
                    examples=tuple(examples) if availability == "AVAILABLE" else (),
                    sampled=state["overflow"] or len(examples) < len(state["examples"]),
                )
            )
        return LoopDiagnostics(availability=availability, plans=tuple(plans))
