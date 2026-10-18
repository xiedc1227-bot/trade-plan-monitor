/** Present durable extraction state, without treating an absent candidate as invalid. */
export function preparationItemStatus(item: { status: string; validation: string | null }): string {
  if (item.status === "DRAFT" || item.status === "WAITING") return "等待提取";
  if (item.status === "FAILED") return "提取失败";
  if (item.status === "EXTRACTING") return "正在提取";
  if (item.status === "CANCEL_REQUESTED") return "等待提取结束";
  if (item.status === "CANCELLED") return "已取消";
  if (item.status === "REVIEWED") return "已审核冻结";
  return item.validation === "VALID" ? "候选完整" : "待补齐 / 修正";
}

export function preparationFailureMessage(code: string | null | undefined): string {
  const messages: Record<string, string> = {
    AI_INPUT_TOO_LARGE: "完整提取请求超过当前 AI 输入长度上限，尚未发送给 AI。请检查原文长度和 AI 最大输入字符数设置，再重试。",
    AI_OUTPUT_TRUNCATED: "AI 返回内容被截断，未生成完整计划。请检查 AI 最大输出长度设置后重新提取。",
    AI_FIELD_EVIDENCE_INVALID: "AI 提取的字段与原文证据未通过校验，未生成可审核候选。这是提取处理问题，不代表原文缺失；可重新提取。",
    AI_CHANGE_IDENTITY_CONFLICT: "AI 混淆了新增规则和已有规则的修改，尚未应用变更。系统会在次数上限内纠正，无需手工填写规则编号。",
    AI_RISK_APPLICABILITY_REQUIRED: "AI 未核对前序风险规则的适用范围，尚未生成可审核候选。系统会在次数上限内纠正，无需手工补填原文已有的信息。",
    AI_FIELD_PATH_INVALID: "AI 引用的规则字段位置不正确，尚未生成完整候选。这属于提取处理问题，无需手工填写内部字段。",
    AI_EMPTY_CHANGE: "AI 声明了修改但未提供变更内容，尚未应用。系统会在次数上限内纠正。",
    AI_AMBIGUITY_REFERENCE_INVALID: "AI 的待确认条款引用格式有误。这属于提取处理问题，不代表原文存在新的歧义。",
    INVALID_UPDATE_EVIDENCE: "AI 提取的变更与前序规则或来源引用不一致，未应用本次变更。可重新提取，无需手工填写内部字段。",
    AI_REPAIR_REQUIRED: "AI 提取结果需要自动纠正，系统会在次数上限内处理。原文不明确的问题会单独列出。",
    AI_OUTPUT_INVALID: "AI 返回内容不符合交易计划格式，未生成可审核候选。请检查模型和提取设置。",
    INVALID_OUTPUT: "未生成符合要求的交易计划；此记录未保存具体原因，不能据此认定原文有误。",
    AUTHENTICATION: "AI 服务认证失败，请检查凭证设置。",
    RATE_LIMITED: "AI 服务限流，请稍后重试。",
    TRANSIENT: "AI 服务暂时不可用，请稍后重试。",
    PREDECESSOR_UNRESOLVED: "前一份计划尚未准备完成，请先处理前一份计划。",
  };
  return messages[code ?? ""] ?? "提取未完成，请检查 AI 服务设置和准备状态。";
}
