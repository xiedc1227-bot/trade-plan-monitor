import { createHash } from "node:crypto";
import { flushPromises, mount } from "@vue/test-utils";
import { nextTick } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SourceCoveragePage, SourceCoverageSummaryView } from "../../src/api/sourceCoverage";
import SourceCoverageReview from "../../src/components/plans/SourceCoverageReview.vue";
import SourceCoverageRows from "../../src/components/plans/SourceCoverageRows.vue";
import SourceCoverageSpan from "../../src/components/plans/SourceCoverageSpan.vue";
import type { SourceCoveragePhase } from "../../src/composables/useSourceCoverage";

const hash = (character: string) => character.repeat(64);
const prefix = "甲😀e\u0301\r\n";
const excerpt = "放量才买入。";
const rawSource = prefix + excerpt + excerpt + "<img src=x onerror=alert(1)>";
const sourceHash = createHash("sha256").update(rawSource, "utf8").digest("hex");
const start = Array.from(prefix).length;
const end = start + Array.from(excerpt).length;
function summary(overrides: Partial<SourceCoverageSummaryView> = {}): SourceCoverageSummaryView {
  return { authorityGranted: false, status: "BLOCKED", coverageComplete: false, currentReviewBound: false,
    canConfirmReview: false, reviewState: "NEEDS_REVIEW", reason: "SOURCE_COVERAGE_REQUIRED",
    sourceHash, candidatePlanHash: hash("b"), contentHash: hash("c"), mappingHash: hash("d"),
    rulesVersion: "source-coverage-rules-v1", coverageEvidenceHash: hash("e"), coverageRevision: 1,
    coverageBundleHash: hash("f"), normalizationHash: hash("1"), originalReviewEvidenceHash: hash("2"),
    reviewId: null, reviewRevision: 0, coverageReviewReceiptHash: null, origin: "HUMAN",
    automaticFidelityVerified: false, obligationCount: 1, issueCount: 1, normalizationChangeCount: 1,
    totalRows: 3, ...overrides };
}
function page(): SourceCoveragePage {
  const value = summary();
  return { authorityGranted: false, planVersionId: "00000000-0000-4000-8000-000000000001",
    summary: value, limit: 50, returnedCount: 3, totalRows: 3, nextCursor: null, items: [
      { kind: "OBLIGATION", rowIndex: 0, obligation: { version: "source-obligation-v1",
        rulesVersion: "source-coverage-rules-v1", sourceHash, clauseId: "clause-1", start, end, excerpt,
        kind: "PREDICATE", scope: "BUY", serverState: "UNRESOLVED", semanticsJson: "{\"threshold\":null}",
        groupId: null, relationIds: [], paths: ["ordinary_rules[0].condition"], obligationId: hash("3"),
        mappingProposal: { proposedDisposition: "BACKGROUND", semanticRole: "COMMENTARY",
          reason: "保存时提议为背景", proposedPaths: [] }, humanSupplements: [] } },
      { kind: "ISSUE", rowIndex: 1, issue: { code: "SOURCE_CONDITION_UNRESOLVED", path: "source.global",
        start: null, end: null, message: "全局尚有强制条件未对应规则" } },
      { kind: "NORMALIZATION_CHANGE", rowIndex: 2, change: { path: "position.max_qty", beforeJson: "null",
        afterJson: "\"<script>300</script>\"", reason: "SOURCE_NORMALIZATION", traceRole: "HISTORICAL_INPUT",
        sourceHash: hash("4"), beforeHash: hash("5"), afterHash: hash("6"), evidenceHash: hash("7") } },
    ] };
}

function completePage(): SourceCoveragePage {
  const value = page(); value.items = value.items.slice(0, 1);
  const row = value.items[0]!;
  if (row.kind !== "OBLIGATION") throw new Error("fixture requires obligation");
  row.obligation.serverState = "MAPPED";
  value.summary = summary({ status: "COMPLETE", coverageComplete: true, canConfirmReview: true,
    reviewState: "UNCONFIRMED", reason: null, issueCount: 0, normalizationChangeCount: 0, totalRows: 1 });
  value.returnedCount = value.totalRows = 1;
  return value;
}

const wrappers: ReturnType<typeof mount>[] = [];
afterEach(() => { for (const wrapper of wrappers.splice(0)) wrapper.unmount(); vi.unstubAllGlobals(); });
function review(overrides: Partial<InstanceType<typeof SourceCoverageReview>["$props"]> = {}, attached = false) {
  const wrapper = mount(SourceCoverageReview, { props: { phase: "CURRENT", page: page(),
    sourceText: rawSource, sourceHash, verifiedSourceHash: sourceHash, safeError: null, ...overrides },
    ...(attached ? { attachTo: document.body } : {}) });
  wrappers.push(wrapper);
  return wrapper;
}
function button(wrapper: ReturnType<typeof review>, text: string) {
  const result = wrapper.findAll("button").find((item) => item.text() === text);
  if (!result) throw new Error(`Missing button ${text}`);
  return result;
}

describe("source coverage review presentation", () => {
  it("keeps the whole-summary blocker visible on a short first page", () => {
    const value = page(); value.items = value.items.slice(0, 1); value.returnedCount = 1; value.nextCursor = "next";
    const wrapper = review({ page: value });
    expect(wrapper.text()).toContain("整份计划仍有 1 项待解决");
    expect(wrapper.text()).toContain("保存的映射建议");
    expect(wrapper.text()).toContain("服务端核对结果");
    expect(wrapper.text()).toContain("尚未明确对应规则");
    expect(wrapper.text()).toContain("第 1–1 项，本页 1 项，共 3 项");
    expect(wrapper.text()).not.toContain("全局尚有强制条件");
    expect(button(wrapper, "读取下一页").element.tagName).toBe("BUTTON");
  });

  it.each(["IDLE", "LOADING", "STALE", "ERROR", "CURRENT"] satisfies SourceCoveragePhase[])(
    "shows an old complete page only in the CURRENT phase, not %s", (phase) => {
      const wrapper = review({ phase, page: completePage() });
      expect(wrapper.text().includes("原文条件已完整核对")).toBe(phase === "CURRENT");
      expect(wrapper.findComponent(SourceCoverageRows).exists()).toBe(phase === "CURRENT");
      expect(wrapper.findComponent(SourceCoverageSpan).exists()).toBe(phase === "CURRENT");
      expect(wrapper.get("section").attributes("aria-busy")).toBe(String(phase === "LOADING"));
      expect(wrapper.text()).not.toContain("READY");
    });

  it.each(["COMPLETE", "BLOCKED", "LEGACY_UNASSESSED", "UNKNOWN"] as const)(
    "shows exact whole-summary source status %s", (status) => {
      const value = status === "COMPLETE" ? completePage() : page();
      value.summary.status = status;
      if (status === "LEGACY_UNASSESSED" || status === "UNKNOWN") {
        value.items = []; value.returnedCount = value.totalRows = 0;
        value.summary = summary({ status, origin: null, reviewState: "UNKNOWN",
          reason: "SOURCE_COVERAGE_UPGRADE_REQUIRED", obligationCount: 0, issueCount: 0,
          normalizationChangeCount: 0, totalRows: 0, mappingHash: null, rulesVersion: null,
          coverageEvidenceHash: null, coverageRevision: null, coverageBundleHash: null, normalizationHash: null });
      }
      const wrapper = review({ page: value });
      const labels = { COMPLETE: "原文条件已完整核对", BLOCKED: "原文条件仍有待解决项",
        LEGACY_UNASSESSED: "历史计划尚未完成原文核对", UNKNOWN: "原文核对结果暂不可用" };
      expect(wrapper.text()).toContain(labels[status]);
      expect(wrapper.text()).toContain("还需检查行情、运行进程和通知交付");
      if (status === "UNKNOWN") expect(wrapper.text()).toContain("本页 0 项，共 0 项");
    });

  it("shows exact current review receipt separately from HUMAN origin", () => {
    const value = completePage();
    value.summary = { ...value.summary, currentReviewBound: true, canConfirmReview: false,
      reviewState: "CURRENT", reviewId: "00000000-0000-4000-8000-000000000002",
      reviewRevision: 1, coverageReviewReceiptHash: hash("9") };
    const wrapper = review({ page: value });
    expect(wrapper.text()).toContain("本次证明已完成审核");
    expect(wrapper.text()).toContain("人工整理，审核状态另列");
    expect(wrapper.text()).toContain(hash("9"));
    expect(wrapper.text()).not.toContain("全部已确认");
  });

  it("renders all three independent streams with explicit proposed-background versus blocked treatment", () => {
    const wrapper = review();
    expect(wrapper.findAll("ol[aria-label='本页原文核对明细'] > li")).toHaveLength(3);
    const first = wrapper.get("ol[aria-label='本页原文核对明细'] > li");
    expect(first.get('[aria-label="保存的映射建议"]').text()).toContain("背景（建议）");
    expect(first.get('[aria-label="服务端核对结果"]').text()).toContain("阻断：尚未明确对应规则");
    expect(wrapper.text()).toContain("全局问题，没有单独的原文片段");
    expect(wrapper.findAll('button[aria-label^="定位原文第"]')).toHaveLength(1);
    expect(wrapper.text()).toContain("本条没有已登记的人工补充链接");
  });

  it("shows only real human supplement IDs, paths and content hashes", async () => {
    const value = page(); const row = value.items[0]!;
    if (row.kind !== "OBLIGATION") throw new Error("fixture requires obligation");
    row.obligation.serverState = "MAPPED_WITH_REGISTERED_SUPPLEMENT";
    row.obligation.humanSupplements = [{ supplementId: "human-operation-17",
      path: "ordinary_rules[0].condition", candidateContentHash: value.summary.contentHash! }];
    const wrapper = review({ page: value });
    const links = wrapper.get('[aria-label="已登记的人工补充链接"]');
    expect(links.text()).toContain("human-operation-17");
    expect(links.text()).toContain("ordinary_rules[0].condition");
    expect(links.text()).toContain(hash("c"));
    await links.get("button").trigger("click");
    expect(wrapper.emitted("revealField")).toEqual([["ordinary_rules[0].condition"]]);
    expect(wrapper.text()).not.toContain("全部已确认");
  });

  it.each(["proposedPaths", "paths"] as const)(
    "preserves legal duplicate %s across a middle update without duplicate-key warnings", async (group) => {
      const value = page(); const row = value.items[0]!;
      if (row.kind !== "OBLIGATION" || !row.obligation.mappingProposal)
        throw new Error("fixture requires a proposed obligation");
      const oldPaths = ["symbol", "position.max_qty", "position.core_target_qty",
        "position.tactical_target_qty", "activation.mode"];
      if (group === "proposedPaths") row.obligation.mappingProposal.proposedPaths = oldPaths;
      else row.obligation.paths = oldPaths;
      const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
      const wrapper = review({ page: value });
      const next = structuredClone(value); const updated = next.items[0]!;
      if (updated.kind !== "OBLIGATION" || !updated.obligation.mappingProposal)
        throw new Error("fixture requires a proposed obligation");
      const repeated = "ordinary_rules[0].condition";
      const paths = [oldPaths[0]!, repeated, repeated, oldPaths[3]!, oldPaths[4]!];
      if (group === "proposedPaths") updated.obligation.mappingProposal.proposedPaths = paths;
      else updated.obligation.paths = paths;
      await wrapper.setProps({ page: next });
      const section = wrapper.get(group === "proposedPaths"
        ? '[aria-label="保存的映射建议"]' : '[aria-label="服务端核对结果"]');
      const controls = section.findAll("button");
      expect(controls.map((control) => control.get("code").text())).toEqual(paths);
      await controls[1]!.trigger("click"); await controls[2]!.trigger("click");
      expect(wrapper.emitted("revealField")).toEqual([[repeated], [repeated]]);
      expect(warn.mock.calls.filter((args) => String(args[0]).includes("Duplicate keys"))).toHaveLength(0);
    });

  it.each(["CURRENT_ASSESSMENT", "HISTORICAL_INPUT"] as const)("labels %s normalization without interpreting HTML", (traceRole) => {
    const value = page(); const row = value.items[2]!;
    if (row.kind !== "NORMALIZATION_CHANGE") throw new Error("fixture requires normalization");
    row.change.traceRole = traceRole;
    if (traceRole === "CURRENT_ASSESSMENT") {
      row.change.sourceHash = value.summary.sourceHash;
      row.change.evidenceHash = value.summary.normalizationHash!;
    }
    const wrapper = review({ page: value });
    expect(wrapper.text()).toContain(traceRole === "CURRENT_ASSESSMENT"
      ? "当前来源的规范化差异" : "历史输入的规范化差异，不代表当前来源证明");
    expect(wrapper.get('pre[aria-label="规范化前"]').text()).toBe("null");
    expect(wrapper.get('pre[aria-label="规范化后"]').text()).toBe('"<script>300</script>"');
    expect(wrapper.find("script").exists()).toBe(false);
    expect(wrapper.get('pre[aria-label="规范化后"]').attributes("tabindex")).toBe("0");
  });

  it("moves keyboard focus from an explicit native button action to the exact codepoint mark", async () => {
    const wrapper = review({}, true);
    const locator = wrapper.get('button[aria-label="定位原文第 1 项"]');
    (locator.element as HTMLButtonElement).focus();
    expect((locator.element as HTMLButtonElement).tabIndex).toBe(0);
    await locator.trigger("click"); await nextTick();
    const mark = wrapper.get('mark[aria-label="已定位的原文片段"]');
    expect(document.activeElement).toBe(mark.element);
    expect(mark.text()).toBe(excerpt);
    expect(wrapper.get('pre[aria-label="原文及定位片段"]').element.textContent).toBe(rawSource);
    expect(wrapper.find("img").exists()).toBe(false);
    expect(wrapper.emitted("revealSource")).toEqual([[{ start, end, excerpt }]]);
  });

  it("makes the scrollable original source reachable through the native keyboard tab order", async () => {
    const wrapper = review({}, true);
    await wrapper.get('button[aria-label="定位原文第 1 项"]').trigger("click");
    const original = wrapper.get('pre[aria-label="原文及定位片段"]');
    expect((original.element as HTMLElement).tabIndex).toBe(0);
    (original.element as HTMLElement).focus();
    expect(document.activeElement).toBe(original.element);
    expect(original.element.textContent).toBe(rawSource);
  });

  it("locates the second repeated excerpt by its exact offset and preserves raw emoji/combining/CRLF", async () => {
    const value = page(); const row = value.items[0]!;
    if (row.kind !== "OBLIGATION") throw new Error("fixture requires obligation");
    row.obligation.start = end; row.obligation.end = end + Array.from(excerpt).length;
    const wrapper = review({ page: value });
    await wrapper.get('button[aria-label="定位原文第 1 项"]').trigger("click");
    expect(wrapper.get('pre[aria-label="原文及定位片段"] > span').text()).toBe((prefix + excerpt).trim());
    expect(wrapper.get('pre[aria-label="原文及定位片段"]').element.textContent).toBe(rawSource);
  });

  it.each(["wrong-hash", "unverified", "wrong-excerpt", "wrong-range"])("refuses %s source location without finding a similar phrase", async (fault) => {
    const value = page(); const row = value.items[0]!;
    if (row.kind !== "OBLIGATION") throw new Error("fixture requires obligation");
    if (fault === "wrong-excerpt") row.obligation.excerpt = "另一个要求";
    if (fault === "wrong-range") row.obligation.start = 1;
    const wrapper = review({ page: value, verifiedSourceHash: fault === "unverified" ? null : sourceHash,
      sourceHash: fault === "wrong-hash" ? hash("9") : sourceHash }, true);
    await wrapper.get('button[aria-label="定位原文第 1 项"]').trigger("click"); await nextTick();
    expect(wrapper.find("mark").exists()).toBe(false);
    expect(wrapper.text()).toContain("无法准确定位原文");
    expect(document.activeElement).toBe(wrapper.get('[aria-label="原文准确定位"]').element);
  });

  it.each(["phase", "page", "sourceText", "sourceHash", "verifiedSourceHash"] as const)(
    "clears old source highlight on %s context change", async (field) => {
      const wrapper = review();
      await wrapper.get('button[aria-label="定位原文第 1 项"]').trigger("click");
      expect(wrapper.find("mark").exists()).toBe(true);
      if (field === "phase") await wrapper.setProps({ phase: "LOADING" });
      if (field === "page") await wrapper.setProps({ page: structuredClone(page()) });
      if (field === "sourceText") await wrapper.setProps({ sourceText: "另一版本原文" });
      if (field === "sourceHash") await wrapper.setProps({ sourceHash: hash("9") });
      if (field === "verifiedSourceHash") await wrapper.setProps({ verifiedSourceHash: null });
      expect(wrapper.find("mark").exists()).toBe(false);
      expect(wrapper.emitted("revealSource")).toHaveLength(1);
    });

  it("emits navigation/paging intent only and never fetches or creates business commands", async () => {
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    const value = page(); value.items = value.items.slice(1, 2); value.returnedCount = 1; value.nextCursor = "next";
    const wrapper = review({ page: value });
    await button(wrapper, "读取下一页").trigger("click");
    await button(wrapper, "返回第一页").trigger("click");
    await button(wrapper, "重新读取核对结果").trigger("click");
    await wrapper.get("ol button").trigger("click");
    expect(wrapper.emitted("nextPage")).toEqual([[]]);
    expect(wrapper.emitted("firstPage")).toEqual([[]]);
    expect(wrapper.emitted("refresh")).toEqual([[]]);
    expect(wrapper.emitted("revealField")).toEqual([["source.global"]]);
    for (const name of ["confirm", "save", "exclude", "supplement", "activate", "deactivate"])
      expect(wrapper.emitted(name)).toBeUndefined();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it.each(["STALE", "ERROR"] as const)("offers explicit safe recovery for %s without automatic requests", async (phase) => {
    const wrapper = review({ phase, safeError: { code: "CURSOR_RESTART_REQUIRED",
      message: "证明已变化，请从第一页重新读取", requiresFirstPage: phase === "STALE" } });
    expect(wrapper.text()).toContain("证明已变化，请从第一页重新读取");
    await button(wrapper, phase === "STALE" ? "从第一页重新读取" : "重试读取").trigger("click");
    expect(wrapper.emitted(phase === "STALE" ? "firstPage" : "refresh")).toEqual([[]]);
    expect(wrapper.findComponent(SourceCoverageRows).exists()).toBe(false);
  });

  it("uses first-page recovery for an ERROR explicitly requiring it", async () => {
    const wrapper = review({ phase: "ERROR", safeError: { code: "CURSOR_RESTART_REQUIRED",
      message: "请从第一页重新读取", requiresFirstPage: true } });
    await button(wrapper, "从第一页重新读取").trigger("click");
    expect(wrapper.emitted("firstPage")).toEqual([[]]);
  });

  it("disables every navigation button when its owner is busy", async () => {
    const wrapper = review({ busy: true });
    for (const control of wrapper.findAll("button")) {
      expect((control.element as HTMLButtonElement).disabled).toBe(true);
      await control.trigger("click");
    }
    expect(wrapper.emitted("revealSource")).toBeUndefined();
    expect(wrapper.emitted("revealField")).toBeUndefined();
    expect(wrapper.emitted("refresh")).toBeUndefined();
  });

  it("shows a bounded readable error when CURRENT has no page instead of old success", () => {
    const wrapper = review({ page: null });
    expect(wrapper.get('[role="alert"]').text()).toContain("核对结果暂不可用");
    expect(wrapper.text()).not.toContain("已完整核对");
  });

  it("keeps loading skeletons and status accessible while hiding previous proof rows", () => {
    const wrapper = review({ phase: "LOADING" });
    expect(wrapper.get('[aria-label="正在读取原文核对结果"]').attributes("role")).toBe("status");
    expect(wrapper.findAll('[aria-hidden="true"]')).toHaveLength(2);
    expect(wrapper.text()).not.toContain(excerpt);
    expect(wrapper.findAll("button")).toHaveLength(0);
  });

  it("keeps selected source safe on rapid context clearing before focus settles", async () => {
    const wrapper = review({}, true);
    const click = wrapper.get('button[aria-label="定位原文第 1 项"]').trigger("click");
    await wrapper.setProps({ phase: "STALE" }); await click; await flushPromises();
    expect(wrapper.find("mark").exists()).toBe(false);
    expect(wrapper.findComponent(SourceCoverageSpan).exists()).toBe(false);
  });
});
