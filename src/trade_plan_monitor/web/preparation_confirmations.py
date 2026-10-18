"""Business questions, literal source facts and software diagnostics stay separate."""

import re
from decimal import Decimal

from pydantic import Field

from trade_plan_monitor.ai.source_resolution import plain
from trade_plan_monitor.domain.unified_plan_models import condition_leaves
from trade_plan_monitor.web.schemas import ApiValue


class PreparationQuestion(ApiValue):
    question_id: str
    category: str
    message: str
    excerpts: tuple[str, ...] = Field(default=(), max_length=20)


class PreparationConfirmationSummary(ApiValue):
    automatic_facts: tuple[str, ...]
    questions: tuple[PreparationQuestion, ...]
    processing_issues: tuple[str, ...]


def confirmation_summary(source, draft, mapping, issues, opening=None):
    """Presentation only; cannot change stored validation or authorize execution."""
    facts, questions, processing = [], [], []
    text = plain(source.text)
    if source.effective_trade_date:
        facts.append(f"生效交易日：{source.effective_trade_date}（已确定，无需再次填写）")
    if opening and opening.inventory_quantity:
        facts.append(
            f"原文明示期初持仓 {opening.inventory_quantity.value} 股；后续计划不重置回测账户。"
        )
    if re.search(r"低吸观察区\s*\|\s*暂不(?:设置|启用)", text):
        facts.append("低吸观察区暂不启用，无需填写区间上下限。")
    if re.search(r"(?:不是|并非).{0,12}(?:新仓|新仓位).{0,12}止损", text):
        facts.append("原文明示结构修复门槛不是新仓止损，不自动生成清仓规则。")
    if re.search(r"再重新设置低吸区并评估第一笔", text):
        facts.append("本份要求重新评估买入，未授权直接下单；不会拆成两笔买入。")
    for match in re.finditer(r"(?:第一笔|第二笔|最大计划)\s*\d+股", text):
        fact = "原文明示：" + match.group()
        if fact not in facts:
            facts.append(fact)
    if re.search(r"最后100股继续保留", text):
        facts.append("最后 100 股保留，不生成买满 300 股的指令。")

    def ask(identity, category, message, excerpts=()):
        questions.append(
            PreparationQuestion(
                question_id=identity,
                category=category,
                message=message,
                excerpts=tuple(dict.fromkeys(excerpts))[:20],
            )
        )

    facts.append('回测按计划最大持仓限制买入，不要求现金金额；成交盈亏正常记录，不计算本金收益率。')
    if draft.position.max_qty is None:
        ask(
            "position-limit",
            "SOURCE_MISSING",
            "本份没有明确最大持仓。首次买入数量不等于总仓位上限，不能用后续计划倒填；请确认本份适用的上限。",
        )
    technical = []
    for rule in (*draft.ordinary_rules, *draft.alert_rules):
        if rule.condition:
            leaves = condition_leaves(rule.condition)
            prior = [leaf for leaf in leaves if leaf.type == "DAILY_PRIOR_CLOSE"]
            for gate in prior:
                comparator = "高于" if gate.comparator == "GT" else "达到或高于"
                facts.append(
                    f"规则 {rule.rule_id}：先行收盘条件已自动提取，从已确认生效日 "
                    f"{gate.since_date} 起，须有更早交易日的完整收盘{comparator}"
                    f" {Decimal(gate.price_fen) / 100:.2f} 元；当天站上不等于之后回踩已完成。"
                )
            for leaf in leaves:
                if leaf.type != "REVIEWED_FACT":
                    continue
                # Exact original restrictions remain in the draft/mapping. The
                # business question shows the unresolved criterion, not repeated
                # inventory/context fragments or the already executable stage.
                criterion = leaf.evidence_requirement.split('\n原文约束：', 1)[0]
                if prior:
                    criterion = re.sub(
                        r'^完整日K(?:首次)?重新(?:收盘站上|收回)\d+(?:\.\d+)?(?:以上)?[；;]',
                        '', criterion).strip()
                technical.append(criterion)
    if technical:
        ask(
            "technical-criteria",
            "SOURCE_AMBIGUOUS",
            "以下条件有文字描述，但未形成完整的自动判定标准。请统一选择明确判定口径，或保留人工复核；系统不会编造阈值，也不会当作条件已满足。",
            technical,
        )
    if draft.ordinary_rules and not draft.risk_branches:
        ask(
            "exit-policy",
            "SOURCE_MISSING",
            "新仓的完整退出规则未明确：请确认仅执行原文明示动作并保留剩余持仓，还是另行补充退出规则。不会把修复门槛当止损。",
        )
    if any(
        branch.target_core_qty is None or branch.target_tactical_qty is None
        for branch in draft.risk_branches
    ):
        ask(
            "exit-scope",
            "SOURCE_AMBIGUOUS",
            "原文提到了风险退出，但退出范围或数量未完整确定。请明确适用持仓及退出数量，不需要填写内部风险枚举。",
        )
    if any(branch.kind == "ORDINARY_TECHNICAL"
           and branch.suspension_confirmation_policy is None for branch in draft.risk_branches):
        ask(
            "risk-suspension", "SOURCE_AMBIGUOUS",
            "普通破位确认期间若发生个股停牌，原文未说明复牌后是继续用首个收盘确认，"
            "还是重新等待连续两个收盘。请确认一次；周末和节假日不属于停牌。",
        )
    known_paths = ("position.max_qty", "opening_account.cash_fen", "opening_account.snapshot_at")
    actionable = []
    scope_issues = []
    ambiguous_excerpts = []
    issue_texts = [issue if isinstance(issue, str) else f"{issue.code}: {issue.path}"
                   for issue in issues]
    ambiguous_paths = {value.partition(": ")[2] for value in issue_texts
                       if value.startswith("SOURCE_CONTENT_AMBIGUOUS:")}
    for issue in issues:
        value = issue if isinstance(issue, str) else f"{issue.code}: {issue.path}"
        if value.startswith("UPDATE_PARTIAL_SCOPE_UNSUPPORTED:"):
            processing.append(
                "这是旧候选保存的范围处理状态。当前系统已支持按新旧持仓批次执行；"
                "请重新提取以生成有原文依据的适用范围。无需手工补填已明确的原文事实，"
                "也不会将旧止损套给被排除的新仓。"
            )
            continue
        if value.startswith("UPDATE_WITHDRAWAL_SCOPE_REQUIRED:"):
            processing.append(
                "AI 尚未核对风险撤销适用范围，系统需要重新提取确认是整条撤销还是部分范围调整；"
                "已保留前序规则，不要求用户补填原文已有的信息。"
            )
            continue
        if value.startswith("UPDATE_SCOPE_DIRECTION_REQUIRED:"):
            processing.append(
                "AI 已识别风险范围变化，但尚未完整提取适用于旧仓还是新仓。"
                "系统会重新核对原文与前序规则，并使用已确认生效交易日划分批次；"
                "这是提取处理问题，无需手工补填原文已有的信息。"
            )
            continue
        if value.startswith("SOURCE_CONTENT_AMBIGUOUS:"):
            clause_id = value.partition("source.")[2]
            clauses = getattr(mapping, "clauses", ())
            excerpts = tuple(c.excerpt for c in clauses if c.clause_id == clause_id)
            ambiguous_excerpts.extend(excerpts)
            continue
        if value.partition(": ")[2] in ambiguous_paths:
            continue
        if value.split(":", 1)[0] in {
            "UPDATE_SOURCE_AMBIGUITY", "UPDATE_SCOPE_UNRESOLVED",
        }:
            scope_issues.append(value)
            continue
        if any(value.endswith(": " + path) for path in known_paths):
            continue
        if "risk_branches" in value and "PLAN_PARAMETER_REQUIRED" in value:
            continue
        actionable.append(value)
    if scope_issues:
        ask(
            "rule-inheritance", "SOURCE_AMBIGUOUS",
            "原文的变更含义或对应目标尚不明确，请确认要修改或取消哪条规则。"
            "未提及的规则默认保留，无需重复确认；明确变更已列在审核对比中。",
        )
    if ambiguous_paths:
        ask("source-content", "SOURCE_AMBIGUOUS",
            "以下原文含义尚不明确，请集中确认适用条件或动作；明确内容已自动处理。",
            ambiguous_excerpts)
    if actionable:
        processing.append(
            f"仍有 {len(actionable)} 项来源映射或模型表达需要处理；"
            "这些不等于原文缺失，不要求手工填写内部字段。详情保留在技术诊断中。"
        )
    if not source.effective_trade_date:
        ask("effective-date", "SOURCE_AMBIGUOUS", "请确认本份计划的生效交易日。")
    return PreparationConfirmationSummary(
        automatic_facts=tuple(facts),
        questions=tuple(questions),
        processing_issues=tuple(processing),
    )
