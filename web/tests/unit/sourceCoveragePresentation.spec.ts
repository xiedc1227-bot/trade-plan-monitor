import { describe, expect, it } from "vitest";
import type { SourceCoverageSummaryView, SourceObligationView } from "../../src/api/generated";
import { sourceCoverageOriginLabel, sourceCoverageReviewLabel, sourceCoverageStatusLabel,
  sourceObligationStateLabel, sourceSpanParts, summaryBinding } from "../../src/components/plans/sourceCoveragePresentation";

const digest = "a".repeat(64);
function summary(overrides: Partial<SourceCoverageSummaryView> = {}): SourceCoverageSummaryView {
  return { authorityGranted: false, status: "COMPLETE", coverageComplete: true,
    currentReviewBound: false, canConfirmReview: true, reviewState: "UNCONFIRMED", reason: null,
    sourceHash: digest, candidatePlanHash: digest, contentHash: digest, mappingHash: digest,
    rulesVersion: "source-coverage-rules-v1", coverageEvidenceHash: digest, coverageRevision: 1,
    coverageBundleHash: digest, normalizationHash: null, originalReviewEvidenceHash: digest,
    reviewId: null, reviewRevision: 0, coverageReviewReceiptHash: null, origin: "HUMAN",
    automaticFidelityVerified: false, obligationCount: 1, issueCount: 0,
    normalizationChangeCount: 0, totalRows: 1, ...overrides };
}

describe("source codepoint location", () => {
  it("preserves emoji, combining characters and CRLF as raw source text", () => {
    expect(sourceSpanParts("甲😀e\u0301\r\n乙", "a".repeat(64), "a".repeat(64),
      { start: 1, end: 4, excerpt: "😀e\u0301" })).toEqual({ before: "甲", mark: "😀e\u0301", after: "\r\n乙" });
  });

  it("uses an exact later occurrence instead of finding the first repeated excerpt", () => {
    expect(sourceSpanParts("条件😀条件", digest, digest, { start: 3, end: 5, excerpt: "条件" }))
      .toEqual({ before: "条件😀", mark: "条件", after: "" });
    expect(sourceSpanParts("条件😀条件", digest, digest, { start: 2, end: 4, excerpt: "条件" })).toBeNull();
  });

  it("returns plain escaped-renderable text without HTML interpretation", () => {
    const value = sourceSpanParts("前<script>x</script>后", digest, digest,
      { start: 1, end: 19, excerpt: "<script>x</script>" });
    expect(value).toEqual({ before: "前", mark: "<script>x</script>", after: "后" });
    expect(Object.isFrozen(value)).toBe(true);
  });

  it.each([null, "b".repeat(64), "A".repeat(64), "", "bad"])("refuses unverified/mismatched digest %s", (verified) => {
    expect(sourceSpanParts("原文", digest, verified, { start: 0, end: 2, excerpt: "原文" })).toBeNull();
  });

  it.each([
    { start: -1, end: 1, excerpt: "原" }, { start: 0, end: 3, excerpt: "原文" },
    { start: 1, end: 1, excerpt: "" }, { start: 2, end: 1, excerpt: "" },
    { start: 0.5, end: 2, excerpt: "原文" }, { start: Number.NaN, end: 2, excerpt: "原文" },
    { start: 0, end: Number.POSITIVE_INFINITY, excerpt: "原文" },
    { start: 0, end: Number.MAX_SAFE_INTEGER + 1, excerpt: "原文" },
    { start: 0, end: 2, excerpt: "另一" },
  ])("refuses an invalid or mismatched source span %j", (span) => {
    expect(sourceSpanParts("原文", digest, digest, span)).toBeNull();
  });

  it.each(["\ud800原文", "原文\udfff", "\udc00\ud800"])("rejects an unpaired surrogate anywhere in source", (text) => {
    expect(sourceSpanParts(text, digest, digest, { start: 0, end: 1, excerpt: text[0]! })).toBeNull();
  });

  it("preserves each CR and LF instead of using textarea-normalized offsets", () => {
    expect(sourceSpanParts("甲\r\n乙", digest, digest, { start: 1, end: 3, excerpt: "\r\n" }))
      .toEqual({ before: "甲", mark: "\r\n", after: "乙" });
    expect(sourceSpanParts("甲\r\n乙", digest, digest, { start: 1, end: 2, excerpt: "\n" })).toBeNull();
    expect(sourceSpanParts("e\u0301", digest, digest, { start: 0, end: 2, excerpt: "é" })).toBeNull();
  });
});

describe("source presentation without permission inference", () => {
  it("compares every summary field independently of object key order", () => {
    const value = summary();
    const reordered = Object.fromEntries(Object.entries(value).reverse()) as SourceCoverageSummaryView;
    expect(summaryBinding(reordered)).toBe(summaryBinding(value));
    for (const key of Object.keys(value) as (keyof SourceCoverageSummaryView)[]) {
      const changed = { ...value, [key]: "different" } as SourceCoverageSummaryView;
      expect(summaryBinding(changed)).not.toBe(summaryBinding(value));
    }
  });

  it("does not label HUMAN as reviewed or COMPLETE as monitoring ready", () => {
    const value = summary();
    expect(sourceCoverageOriginLabel(value)).toBe("人工整理，审核状态另列");
    expect(sourceCoverageReviewLabel(value)).toBe("本次证明待审核");
    expect(sourceCoverageStatusLabel(value)).toBe("原文条件已完整核对");
    expect(sourceCoverageStatusLabel(value)).not.toContain("就绪");
  });

  it.each(["COMPLETE", "BLOCKED", "LEGACY_UNASSESSED", "UNKNOWN"] as const)("labels whole-summary status %s", (status) => {
    expect(sourceCoverageStatusLabel(summary({ status }))).toMatch(/[\u4e00-\u9fff]/);
  });
  it.each(["CURRENT", "UNCONFIRMED", "NEEDS_REVIEW", "UNKNOWN"] as const)("labels exact review status %s", (reviewState) => {
    expect(sourceCoverageReviewLabel(summary({ reviewState }))).toMatch(/[\u4e00-\u9fff]/);
  });
  it.each(["MAPPED", "MAPPED_WITH_REGISTERED_SUPPLEMENT", "CONTEXT_VERIFIED", "SCOPE_EXCLUDED",
    "UNRESOLVED", "UNSUPPORTED", "CONFLICT"] satisfies SourceObligationView["serverState"][])(
    "labels the independent server treatment %s", (state) => {
      expect(sourceObligationStateLabel(state)).toMatch(/[\u4e00-\u9fff]/);
    });
  it("labels unknown and historical origin without claiming automatic fidelity", () => {
    expect(sourceCoverageOriginLabel(summary({ origin: null }))).toContain("暂不可确认");
    expect(sourceCoverageOriginLabel(summary({ origin: "AI_HISTORICAL" }))).toContain("未声明");
    expect(sourceCoverageOriginLabel(summary({ origin: "AI_NEW" }))).toContain("尚未验证");
    expect(sourceCoverageOriginLabel(summary({ origin: "AI_NEW", automaticFidelityVerified: true }))).toContain("已验证");
    expect(sourceCoverageStatusLabel(null)).toContain("尚未读取");
    expect(sourceCoverageReviewLabel(null)).toContain("尚未读取");
  });
});
