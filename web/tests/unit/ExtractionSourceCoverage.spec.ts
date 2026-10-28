import { createHash, webcrypto } from "node:crypto";
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PlanExtractionView, SourceCoverageSummaryView } from "../../src/api/generated";
import ExtractionSourceCoverage from "../../src/components/plans/ExtractionSourceCoverage.vue";
import ExtractionEvidence from "../../src/components/plans/ExtractionEvidence.vue";
import PlanSourceExtraction from "../../src/components/plans/PlanSourceExtraction.vue";

const rawSource = "最大持仓300股。\r\n😀e\u0301";
const digest = (value: string) => createHash("sha256").update(value, "utf8").digest("hex");
const hash = (character: string) => character.repeat(64);
const sourceHash = digest(rawSource);
const extractionId = "00000000-0000-4000-8000-000000000001";
function summary(status: "COMPLETE" | "BLOCKED" | "UNKNOWN" = "COMPLETE"): SourceCoverageSummaryView {
  const complete = status === "COMPLETE", unknown = status === "UNKNOWN";
  return { authorityGranted: false, status, coverageComplete: complete, currentReviewBound: false,
    canConfirmReview: false, reviewState: complete ? "UNCONFIRMED" : "UNKNOWN",
    reason: unknown ? "SOURCE_COVERAGE_STALE" : complete ? null : "SOURCE_COVERAGE_REQUIRED",
    sourceHash, candidatePlanHash: hash("a"), contentHash: hash("b"), mappingHash: hash("c"),
    rulesVersion: "source-coverage-rules-v1", coverageEvidenceHash: unknown ? null : hash("d"),
    coverageRevision: null, coverageBundleHash: null, normalizationHash: null,
    originalReviewEvidenceHash: hash("e"), reviewId: null, reviewRevision: 0,
    coverageReviewReceiptHash: null, origin: "AI_NEW", automaticFidelityVerified: false,
    obligationCount: unknown ? 0 : 1, issueCount: status === "BLOCKED" ? 1 : 0,
    normalizationChangeCount: 0, totalRows: unknown ? 0 : complete ? 1 : 2 };
}
const wrappers: ReturnType<typeof mount>[] = [];
afterEach(() => { for (const wrapper of wrappers.splice(0)) wrapper.unmount(); vi.unstubAllGlobals(); });
function child(overrides: Partial<InstanceType<typeof ExtractionSourceCoverage>["$props"]> = {}, cryptoValue: unknown = webcrypto) {
  vi.stubGlobal("crypto", cryptoValue);
  const wrapper = mount(ExtractionSourceCoverage, { props: { extractionId, sourceText: rawSource,
    sourceTextSha256: sourceHash, summary: summary(), ...overrides } });
  wrappers.push(wrapper);
  return wrapper;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((accept, deny) => { resolve = accept; reject = deny; });
  return { promise, resolve, reject };
}
function hashBytes(text: string): ArrayBuffer { return Uint8Array.from(Buffer.from(digest(text), "hex")).buffer; }
function extraction(overrides: Partial<PlanExtractionView> = {}): PlanExtractionView {
  // Synthetic presentation fixture; it is not a real extraction accuracy claim.
  return { id: extractionId, providerId: "00000000-0000-4000-8000-000000000002", status: "SUCCEEDED",
    submittedAt: "2026-10-28T10:00:00+08:00", promptVersion: "plan-extract-v12",
    sourceTextSha256: sourceHash, sourceCoverage: summary(), evidence: [],
    dailyMapping: { mapping_version: "daily-mapping-v1", candidate_content_hash: hash("b"),
      bindings: [], clauses: [{ clause_id: "clause-1", disposition: "POLICY", start: 0,
        end: Array.from(rawSource).length, excerpt: rawSource, paths: [], reason: "供展示测试的完整原文" }], supplements: [] },
    ...overrides };
}
function evidence(value = extraction(), resolvedIssueKeys: readonly string[] = []) {
  vi.stubGlobal("crypto", webcrypto);
  const wrapper = mount(ExtractionEvidence, { props: { extraction: value, sourceText: rawSource, resolvedIssueKeys } });
  wrappers.push(wrapper); return wrapper;
}
function workbench(value = extraction(), sourceText = rawSource) {
  vi.stubGlobal("crypto", webcrypto);
  const wrapper = mount(PlanSourceExtraction, { props: { extraction: value, initialSourceText: sourceText,
    providers: [{ baseUrl: "https://provider.example.test", configured: true, enabled: true,
      displayName: "展示测试供应商", model: "test", providerId: value.providerId, maxInputChars: 200000,
      maxOutputTokens: 4096, revision: 0 }] } });
  wrappers.push(wrapper); return wrapper;
}

describe("unsaved extraction source summary", () => {
  it("shows a matching complete summary only after the raw UTF8 source hash is verified", async () => {
    const wrapper = child();
    expect(wrapper.text()).not.toContain("原文条件已完整核对");
    await vi.waitFor(() => expect(wrapper.text()).toContain("原文条件已完整核对"));
    expect(wrapper.text()).toContain("原文义务：1");
    expect(wrapper.findAll("button")).toHaveLength(0);
  });

  it.each(["COMPLETE", "BLOCKED", "UNKNOWN"] as const)("shows the bound %s extraction outcome without granting review", async (status) => {
    const wrapper = child({ summary: summary(status) });
    const text = { COMPLETE: "原文条件已完整核对", BLOCKED: "原文条件仍有待解决项", UNKNOWN: "原文核对结果暂不可用" };
    await vi.waitFor(() => expect(wrapper.text()).toContain(text[status]));
    expect(wrapper.text()).toContain("保存版本后还需逐项审核");
    expect(wrapper.text()).toContain("检查行情、运行进程和通知交付");
    expect(wrapper.text()).not.toContain("本次证明已完成审核");
    expect(wrapper.findAll("button, a, input, textarea")).toHaveLength(0);
    if (status === "BLOCKED") expect(wrapper.get('[role="alert"]').text()).toContain("仍有 1 项来源问题");
    if (status === "UNKNOWN") expect(wrapper.text()).not.toContain("已完整核对");
  });

  it("does not treat HUMAN origin as automatic review or confirmation", async () => {
    const wrapper = child({ summary: { ...summary(), origin: "HUMAN" } });
    await vi.waitFor(() => expect(wrapper.text()).toContain("人工整理，审核状态另列"));
    expect(wrapper.text()).not.toContain("自动保真已验证");
    expect(wrapper.text()).not.toContain("本次证明已完成审核");
    expect(wrapper.emitted()).toEqual({});
  });

  it.each(["CRLF", "trim", "combining"])("does not normalize raw %s source text", async (change) => {
    const sourceText = change === "CRLF" ? rawSource.replace("\r\n", "\n") :
      change === "trim" ? ` ${rawSource} ` : rawSource.replace("e\u0301", "é");
    const wrapper = child({ sourceText });
    await vi.waitFor(() => expect(wrapper.text()).toContain("尚未准确对应"));
    expect(wrapper.text()).not.toContain("已完整核对");
    expect(wrapper.text()).not.toContain("原文义务：");
  });

  it.each(["summary", "receipt", "missing-receipt"])("requires exact %s source hash as well as actual raw hash", async (change) => {
    const wrapper = child({ summary: change === "summary" ? { ...summary(), sourceHash: hash("9") } : summary(),
      sourceTextSha256: change === "receipt" ? hash("9") : change === "missing-receipt" ? null : sourceHash });
    await vi.waitFor(() => expect(wrapper.text()).toContain("尚未准确对应"));
    expect(wrapper.text()).not.toContain("已完整核对");
    expect(wrapper.text()).not.toContain("原文义务：");
  });

  it.each(["", "\ud800", "\udfff"])("rejects empty text or lone surrogates before TextEncoder replacement", (sourceText) => {
    const call = vi.fn(); const value = digest(sourceText);
    const wrapper = child({ sourceText, sourceTextSha256: value, summary: { ...summary(), sourceHash: value } },
      { subtle: { digest: call } });
    expect(wrapper.text()).toContain("尚未准确对应");
    expect(wrapper.text()).not.toContain("原文义务：");
    expect(call).not.toHaveBeenCalled();
  });

  it("does not bypass the shared summary guard for an internally incoherent summary", () => {
    const call = vi.fn();
    const wrapper = child({ summary: { ...summary(), origin: "HUMAN", automaticFidelityVerified: true } },
      { subtle: { digest: call } });
    expect(wrapper.text()).toContain("尚未准确对应"); expect(call).not.toHaveBeenCalled();
  });

  it("handles a current digest failure without displaying raw implementation details", async () => {
    const wrapper = child({}, { subtle: { digest: vi.fn(async () => { throw new Error("secret URL/config path"); }) } });
    await vi.waitFor(() => expect(wrapper.text()).toContain("尚未准确对应"));
    expect(wrapper.text()).not.toContain("secret"); expect(wrapper.text()).not.toContain("原文义务：");
  });

  it("hides old COMPLETE and counts immediately during same-ID source replacement", async () => {
    const first = deferred<ArrayBuffer>(); const second = deferred<ArrayBuffer>();
    const digestCall = vi.fn().mockReturnValueOnce(first.promise).mockReturnValue(second.promise);
    const wrapper = child({}, { subtle: { digest: digestCall } });
    first.resolve(hashBytes(rawSource));
    await vi.waitFor(() => expect(wrapper.text()).toContain("已完整核对"));
    const changed = rawSource + "新条款"; const changedHash = digest(changed);
    await wrapper.setProps({ sourceText: changed, sourceTextSha256: changedHash,
      summary: { ...summary("BLOCKED"), sourceHash: changedHash } });
    expect(wrapper.text()).not.toContain("已完整核对"); expect(wrapper.text()).not.toContain("原文义务：");
    expect(wrapper.get("section").attributes("aria-busy")).toBe("true");
    second.resolve(hashBytes(changed));
    await vi.waitFor(() => expect(wrapper.text()).toContain("仍有 1 项来源问题"));
  });

  it("ignores stale A-B-A digest success and failure without replacing the latest source summary", async () => {
    const first = deferred<ArrayBuffer>(), second = deferred<ArrayBuffer>(), latest = deferred<ArrayBuffer>();
    const otherSource = "另一份原文"; const otherHash = digest(otherSource);
    let firstSourceCall = true;
    // A sync prop watcher may observe intermediate prop frames. The fake digest,
    // like SHA itself, returns the same result for every identical raw byte input.
    const digestCall = vi.fn((_algorithm: string, bytes: Uint8Array) => {
      if (new TextDecoder().decode(bytes) === otherSource) return second.promise;
      if (firstSourceCall) { firstSourceCall = false; return first.promise; }
      return latest.promise;
    });
    const wrapper = child({}, { subtle: { digest: digestCall } });
    await wrapper.setProps({ extractionId: "other-id", sourceText: otherSource, sourceTextSha256: otherHash,
      summary: { ...summary("BLOCKED"), sourceHash: otherHash } });
    await wrapper.setProps({ extractionId, sourceText: rawSource, sourceTextSha256: sourceHash,
      summary: { ...summary(), obligationCount: 2, totalRows: 2 } });
    latest.resolve(hashBytes(rawSource));
    await vi.waitFor(() => expect(wrapper.text()).toContain("原文义务：2"));
    first.resolve(hashBytes(rawSource)); second.reject(new Error("late secret failure")); await flushPromises();
    expect(wrapper.text()).toContain("原文义务：2");
    expect(wrapper.text()).not.toContain("原文义务：1"); expect(wrapper.text()).not.toContain("late secret");
    expect(wrapper.get("section").attributes("aria-busy")).toBe("false");
  });

  it("does not let a late old failure change the new pending hash state", async () => {
    const first = deferred<ArrayBuffer>(), second = deferred<ArrayBuffer>();
    const wrapper = child({}, { subtle: { digest: vi.fn().mockReturnValueOnce(first.promise).mockReturnValue(second.promise) } });
    await wrapper.setProps({ extractionId: "new-id", summary: summary("BLOCKED") });
    first.reject(new Error("old failure")); await flushPromises();
    expect(wrapper.text()).toContain("正在核对当前原文");
    expect(wrapper.text()).not.toContain("尚未准确对应");
    second.resolve(hashBytes(rawSource));
    await vi.waitFor(() => expect(wrapper.text()).toContain("仍有 1 项来源问题"));
  });

  it("compares the immutable summary snapshot again after the digest await", async () => {
    const pending = deferred<ArrayBuffer>(); const value = summary();
    const wrapper = child({ summary: value }, { subtle: { digest: vi.fn(() => pending.promise) } });
    value.coverageEvidenceHash = hash("9");
    pending.resolve(hashBytes(rawSource)); await flushPromises();
    expect(wrapper.text()).toContain("尚未准确对应");
    expect(wrapper.text()).not.toContain("已完整核对");
  });

  it.each(["success", "failure"])("ignores digest %s after unmount without recreating a view", async (outcome) => {
    const pending = deferred<ArrayBuffer>();
    const wrapper = child({}, { subtle: { digest: vi.fn(() => pending.promise) } });
    const element = wrapper.element;
    wrapper.unmount(); wrappers.splice(wrappers.indexOf(wrapper), 1);
    if (outcome === "success") pending.resolve(hashBytes(rawSource)); else pending.reject(new Error("late failure"));
    await flushPromises();
    expect(document.body.contains(element)).toBe(false);
    expect(wrapper.text()).not.toContain("已完整核对");
    expect(wrapper.emitted()).toEqual({});
  });

  it("renders no coverage view at all for a null summary", () => {
    const wrapper = child({ summary: null });
    expect(wrapper.find("section").exists()).toBe(false);
    expect(wrapper.text()).toBe("");
  });

  it("performs no network call or business emit while validating a hostile raw source", async () => {
    const sourceText = '<img src=x onerror="alert(1)"><script>bad()</script>\r\n😀';
    const value = digest(sourceText); const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    const wrapper = child({ sourceText, sourceTextSha256: value, summary: { ...summary("BLOCKED"), sourceHash: value } });
    await vi.waitFor(() => expect(wrapper.text()).toContain("仍有 1 项来源问题"));
    expect(wrapper.find("img, script").exists()).toBe(false);
    expect(wrapper.findAll("button, a, input, textarea")).toHaveLength(0);
    expect(wrapper.emitted()).toEqual({}); expect(fetcher).not.toHaveBeenCalled();
  });
});

describe("extraction evidence compatibility and source forwarding", () => {
  it("describes the current daily mapping instead of rejecting empty legacy field evidence", async () => {
    const wrapper = evidence();
    expect(wrapper.text()).toContain("当前提取使用逐句原文与字段映射");
    expect(wrapper.text()).not.toContain("没有可展示证据；该结果不能进入启用流程");
    await vi.waitFor(() => expect(wrapper.findComponent(ExtractionSourceCoverage).text()).toContain("已完整核对"));
  });

  it.each(["absent", "null"])("preserves the legacy %s summary and missing-field-evidence path", (kind) => {
    const value = extraction({ promptVersion: "plan-extract-v1", dailyMapping: null });
    if (kind === "absent") Reflect.deleteProperty(value, "sourceCoverage"); else value.sourceCoverage = null;
    const wrapper = evidence(value);
    expect(wrapper.text()).toContain("没有可展示证据；该结果不能进入启用流程");
    expect(wrapper.findComponent(ExtractionSourceCoverage).exists()).toBe(false);
    expect(wrapper.text()).not.toContain("原文核对摘要（提取阶段）");
  });

  it("keeps source blockers after legacy warning and unmapped hints are locally resolved", async () => {
    const value = extraction({ sourceCoverage: summary("BLOCKED"), warnings: [{ path: "source.warning",
      message: "仍需人工核对", material: true }], unmappedText: [{ path: "source.unmapped", excerpt: "放量",
      reason: "尚未对应规则", material: true, start: 0, end: 2 }] });
    const wrapper = evidence(value);
    await vi.waitFor(() => expect(wrapper.text()).toContain("仍有 1 项来源问题"));
    await wrapper.get('[data-issue-key="WARNING:source.warning"] button').trigger("click");
    expect(wrapper.emitted("resolveIssue")).toHaveLength(1);
    await wrapper.setProps({ resolvedIssueKeys: ["WARNING:source.warning", "UNMAPPED_TEXT:source.unmapped"] });
    expect(wrapper.get('[data-testid="unresolved-material-count"]').text()).toContain("0");
    expect(wrapper.findComponent(ExtractionSourceCoverage).text()).toContain("仍有 1 项来源问题");
    expect(wrapper.findComponent(ExtractionSourceCoverage).text()).toContain("本地标记已处理不会清除");
    expect(wrapper.findComponent(ExtractionSourceCoverage).emitted()).toEqual({});
  });

  it("does not use an empty default sourceText to verify an externally supplied summary", async () => {
    vi.stubGlobal("crypto", webcrypto);
    const wrapper = mount(ExtractionEvidence, { props: { extraction: extraction() } }); wrappers.push(wrapper);
    await flushPromises();
    expect(wrapper.findComponent(ExtractionSourceCoverage).text()).toContain("尚未准确对应");
    expect(wrapper.text()).not.toContain("已完整核对");
  });

  it("forwards the exact current raw source through the existing parent without rewriting it", async () => {
    const wrapper = workbench();
    expect(wrapper.getComponent(ExtractionEvidence).props("sourceText")).toBe(rawSource);
    await vi.waitFor(() => expect(wrapper.getComponent(ExtractionSourceCoverage).text()).toContain("已完整核对"));
    expect(wrapper.getComponent(ExtractionSourceCoverage).props("sourceText")).toBe(rawSource);
    expect(wrapper.emitted("submitExtraction")).toBeUndefined();
  });

  it("rejects a late external new-ID result for an old source even when the old parent text guard resets", async () => {
    const wrapper = workbench();
    await vi.waitFor(() => expect(wrapper.getComponent(ExtractionSourceCoverage).text()).toContain("已完整核对"));
    const changed = "用户当前的另一份原文\r\n😀";
    await wrapper.setProps({ initialSourceText: changed });
    expect(wrapper.findComponent(ExtractionSourceCoverage).exists()).toBe(false);
    await wrapper.setProps({ extraction: extraction({ id: "00000000-0000-4000-8000-000000000009" }) });
    await vi.waitFor(() => expect(wrapper.getComponent(ExtractionSourceCoverage).text()).toContain("尚未准确对应"));
    expect(wrapper.text()).not.toContain("已完整核对");
    expect(wrapper.getComponent(ExtractionSourceCoverage).text()).not.toContain("原文义务：");
  });

  it("retains the parent's existing same-ID source-edit stale-review guard", async () => {
    const wrapper = workbench();
    await vi.waitFor(() => expect(wrapper.getComponent(ExtractionSourceCoverage).text()).toContain("已完整核对"));
    await wrapper.setProps({ initialSourceText: "同一提取任务后的新原文" });
    expect(wrapper.get('[data-testid="stale-extraction-review"]').text()).toContain("原文已在提取后修改");
    expect(wrapper.findComponent(ExtractionSourceCoverage).exists()).toBe(false);
  });
});
