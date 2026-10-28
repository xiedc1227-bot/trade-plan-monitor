import type { DeepReadonly } from "vue";
import type { SourceCoverageSummaryView, SourceObligationView } from "../../api/generated";

export interface SourceSpan { readonly start: number; readonly end: number; readonly excerpt: string }
export interface SourceSpanParts { readonly before: string; readonly mark: string; readonly after: string }

/** Python offsets count Unicode code points, including each raw CR and LF. */
export function sourceSpanParts(text: string, sourceHash: string,
  verifiedSourceHash: string | null, span: SourceSpan): Readonly<SourceSpanParts> | null {
  if (!/^[0-9a-f]{64}$/.test(sourceHash) || verifiedSourceHash !== sourceHash ||
    !Number.isSafeInteger(span.start) || !Number.isSafeInteger(span.end) ||
    span.start < 0 || span.end <= span.start) return null;
  const points = Array.from(text);
  if (points.some(unpaired) || Array.from(span.excerpt).some(unpaired) ||
    span.end > points.length || points.slice(span.start, span.end).join("") !== span.excerpt) return null;
  return Object.freeze({ before: points.slice(0, span.start).join(""), mark: span.excerpt,
    after: points.slice(span.end).join("") });
}

function unpaired(character: string): boolean {
  const point = character.codePointAt(0)!;
  return point >= 0xd800 && point <= 0xdfff;
}

/** A stable equality tuple, not a proof hash or permission calculation. */
export function summaryBinding(summary: DeepReadonly<SourceCoverageSummaryView>): string {
  return JSON.stringify(Object.keys(summary).sort().map((key) =>
    [key, summary[key as keyof SourceCoverageSummaryView]]));
}

export function sourceCoverageStatusLabel(summary: DeepReadonly<SourceCoverageSummaryView> | null): string {
  if (!summary) return "尚未读取原文核对结果";
  return { COMPLETE: "原文条件已完整核对", BLOCKED: "原文条件仍有待解决项",
    LEGACY_UNASSESSED: "历史计划尚未完成原文核对", UNKNOWN: "原文核对结果暂不可用" }[summary.status];
}

export function sourceCoverageReviewLabel(summary: DeepReadonly<SourceCoverageSummaryView> | null): string {
  if (!summary) return "尚未读取审核状态";
  return { CURRENT: "本次证明已完成审核", UNCONFIRMED: "本次证明待审核",
    NEEDS_REVIEW: "需要重新核对并审核", UNKNOWN: "审核状态暂不可确认" }[summary.reviewState];
}

export function sourceCoverageOriginLabel(summary: DeepReadonly<SourceCoverageSummaryView>): string {
  if (summary.origin === "HUMAN") return "人工整理，审核状态另列";
  if (summary.origin === "AI_HISTORICAL") return "历史提取，未声明当前自动保真";
  if (summary.origin === "AI_NEW") return summary.automaticFidelityVerified
    ? "AI 提取，原文保真已验证" : "AI 提取，原文保真尚未验证";
  return "来源方式暂不可确认";
}

export function sourceObligationStateLabel(state: SourceObligationView["serverState"]): string {
  return { MAPPED: "已对应规则", MAPPED_WITH_REGISTERED_SUPPLEMENT: "已对应规则及登记的人工补充",
    CONTEXT_VERIFIED: "背景信息已核对", SCOPE_EXCLUDED: "已明确排除适用范围",
    UNRESOLVED: "尚未明确对应规则", UNSUPPORTED: "当前尚不支持", CONFLICT: "原文与规则存在冲突" }[state];
}
