import { createHash, webcrypto } from "node:crypto";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import PlanWorkbench from "../../src/components/plans/PlanWorkbench.vue";
import SourceCoverageReview from "../../src/components/plans/SourceCoverageReview.vue";
import PlanSourceReview from "../../src/components/plans/PlanSourceReview.vue";
import { apiFetchKey } from "../../src/api/context";
import type { DailyMapping, PlanVersionView, SourceCoveragePage, SourceCoverageSummaryView } from "../../src/api/generated";
import type { usePlanWorkspace } from "../../src/composables/usePlanWorkspace";
import type { Json } from "../../src/components/plans/planSchema";

// Synthetic UI wire projections exercise the real parent/clients; no policy proof.
const id = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const hash = (s: string) => createHash("sha256").update(s).digest("hex");
const CONTENT = hash("wire semantic content"), REVIEW = hash("wire original review");
const runtime = { providerId: id(9), configured: true, enabled: true, displayName: "UI wire",
  baseUrl: "https://example.test/v1", model: "wire", revision: 0, maxInputChars: 50000, maxOutputTokens: 4096 };
const source = "最大计划持仓300股。\r\n😀";
function mapping(text = source): DailyMapping {
  return { mapping_version: "daily-mapping-v1", candidate_content_hash: CONTENT,
    clauses: [{ clause_id: "c1", start: 0, end: Array.from(text).length, excerpt: text,
      disposition: "POLICY", paths: ["position.max_qty"], reason: "Synthetic UI source projection" }],
    bindings: [{ path: "position.max_qty", value: 300, origin: "SOURCE", unit: "JSON", clause_ids: ["c1"], supplement_id: null }], supplements: [] };
}
function native(n = 1): PlanVersionView {
  const planJson = JSON.stringify({ schema_version: 5, execution_mode: "CONDITION_PLAN", execution_version: "condition-plan-v1",
    plan_id: "wire-plan", version: n, symbol: "600000.SH", name: "Wire plan", position: { max_qty: 300 } });
  return { id: id(n), planId: "wire-plan", version: n, symbol: "600000.SH", planJson, sourceText: source,
    planHash: hash(planJson), contentHash: CONTENT, sourceHash: hash(source), reviewEvidenceHash: REVIEW,
    reviewId: null, reviewRevision: 0, dailyMapping: mapping(), dailyIssues: [], status: "DRAFT", canActivate: false,
    revision: 0, createdAt: "2026-10-28T10:00:00+08:00" };
}
function summary(value: PlanVersionView, state: "COMPLETE" | "BLOCKED" | "UNKNOWN" = "COMPLETE", revision = 1): SourceCoverageSummaryView {
  const complete = state === "COMPLETE", bound = complete && value.reviewId != null;
  return { authorityGranted: false, status: state, coverageComplete: complete, currentReviewBound: bound,
    canConfirmReview: complete && !bound, reviewState: bound ? "CURRENT" : complete ? "UNCONFIRMED" : "NEEDS_REVIEW",
    reason: complete ? null : "SOURCE_COVERAGE_REQUIRED", sourceHash: value.sourceHash!, candidatePlanHash: value.planHash,
    contentHash: value.contentHash!, mappingHash: hash("wire-mapping"), rulesVersion: "source-coverage-rules-v1",
    coverageEvidenceHash: hash(`wire-coverage-${revision}`), coverageRevision: revision, coverageBundleHash: hash(`wire-bundle-${revision}`),
    normalizationHash: null, originalReviewEvidenceHash: value.reviewEvidenceHash!, reviewId: value.reviewId!,
    reviewRevision: value.reviewRevision!, coverageReviewReceiptHash: bound ? hash("wire-receipt") : null,
    origin: "HUMAN", automaticFidelityVerified: false, obligationCount: 2, issueCount: complete ? 0 : 1,
    normalizationChangeCount: 0, totalRows: complete ? 2 : 3 };
}
function page(value: PlanVersionView): SourceCoveragePage {
  const s = value.sourceCoverage!;
  return { authorityGranted: false, planVersionId: value.id, summary: s, limit: 50,
    returnedCount: 1, totalRows: s.totalRows, nextCursor: "wire-next-page",
    items: [{ kind: "OBLIGATION", rowIndex: 0, obligation: { version: "source-obligation-v1",
      rulesVersion: "source-coverage-rules-v1", sourceHash: value.sourceHash!, clauseId: "c1", start: 0,
      end: Array.from(source).length, excerpt: source, kind: "PREDICATE", scope: s.coverageComplete ? "PLAN" : "UNKNOWN",
      serverState: s.coverageComplete ? "MAPPED" : "UNRESOLVED", semanticsJson: null,
      groupId: null, relationIds: [], paths: ["position.max_qty"], obligationId: hash("wire-obligation"),
      mappingProposal: null, humanSupplements: [] } }] };
}
function response(value: unknown, status = 200) { return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } }); }
function deferred<T>() {
  let resolve!: (v: T) => void, reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
interface Call { url: string; method: string; body: Record<string, any>; signal: AbortSignal | null }
const wrappers: VueWrapper[] = [];
afterEach(() => { wrappers.splice(0).forEach(w => w.unmount()); vi.unstubAllGlobals(); });
function harness(options: { state?: "COMPLETE" | "BLOCKED" | "UNKNOWN";
  configure?: (records: Map<string, PlanVersionView>) => void;
  intercept?: (call: Call) => Response | Promise<Response> | undefined } = {}) {
  vi.stubGlobal("crypto", webcrypto);
  const records = new Map([1, 2].map(n => { const v = native(n); v.sourceCoverage = summary(v, options.state); return [v.id, v]; }));
  options.configure?.(records);
  const calls: Call[] = [];
  const fetcher = vi.fn<typeof fetch>(async (input, init) => {
    const c: Call = { url: String(input), method: init?.method ?? "GET", body: JSON.parse(String(init?.body ?? "{}")), signal: init?.signal ?? null };
    calls.push(c); const picked = options.intercept?.(c); if (picked !== undefined) return picked;
    if (c.url.endsWith("/plan-editor-schema")) return response({ candidateSchema: { type: "object", properties: {
      position: { type: "object", properties: { max_qty: { type: "integer" } } } } }, operationSchemas: {} });
    if (c.url.endsWith("/ai-runtime")) return response(runtime);
    if (c.url.includes("/plan-versions?")) return response({ items: [], total: 0, offset: 0, limit: 100 });
    if (c.url.includes("/source-coverage?")) return response(page(records.get(c.url.split("/")[4]!)!));
    if (c.url.includes("/plan-versions/")) return response(records.get(c.url.split("/").at(-1)!)!);
    if (c.url.includes("/plan-activation-states/")) return response({ active: false, planVersionId: null, revision: 0,
      symbol: "600000.SH", changedAt: "2026-10-28T10:00:00+08:00" });
    if (c.url.endsWith("/plan-review-previews")) return response({ candidateJson: c.body.candidateJson, supplementRevision: 0,
      review: { content_hash: CONTENT, source_hash: hash(c.body.sourceText), evidence_hash: REVIEW,
        mapping: c.body.mapping, issues: [] } });
    if (c.url.endsWith("/plan-review-confirmations")) {
      const v = records.get(c.body.planVersionId)!;
      v.reviewId = id(90); v.reviewRevision = 1; v.canActivate = true;
      v.sourceCoverage = summary(v);
      return response({ canActivate: true, revision: 1 });
    }
    if (c.url.endsWith("/plan-drafts")) {
      const v = native(3), raw = JSON.parse(c.body.planJson);
      v.planJson = c.body.planJson; v.planHash = hash(v.planJson); v.version = raw.version;
      v.sourceText = c.body.sourceText; v.sourceHash = hash(v.sourceText); v.dailyMapping = c.body.dailyMapping;
      v.sourceCoverage = summary(v, options.state); records.set(v.id, v); return response(v);
    }
    throw new Error(`Unexpected UI request ${c.method} ${c.url}`);
  });
  const wrapper = mount(PlanWorkbench, { props: { planVersionId: id(1) }, attachTo: document.body,
    global: { provide: { [apiFetchKey as symbol]: fetcher }, stubs: {
      PlanSourceExtraction: true, PlanSimulationPanel: true, P2PolicyReview: true, P3PolicyReview: true, PlanExceptionPermissions: true,
    } } });
  wrappers.push(wrapper);
  const work = (wrapper.vm as unknown as { work: ReturnType<typeof usePlanWorkspace> }).work;
  return { wrapper, work, records, calls };
}
function button(wrapper: VueWrapper, label: string) { return wrapper.findAll("button").find(b => b.text() === label)!; }
async function loaded(wrapper: VueWrapper) { await vi.waitFor(() => expect(wrapper.findComponent(PlanSourceReview).exists()).toBe(true)); await flushPromises(); }
async function current(wrapper: VueWrapper) { await vi.waitFor(() => expect(wrapper.findComponent(SourceCoverageReview).props("phase")).toBe("CURRENT")); }
function conflict() { return response({ error: { code: "CONFLICT", message: "Synthetic current conflict", details: [] } }, 409); }

describe("actual plan workbench source coverage owner", () => {
  it("keeps native zero-issue BLOCKED drafts saveable while disabling review confirmation", async () => {
    const { wrapper, calls } = harness({ state: "BLOCKED" }); await loaded(wrapper);
    expect(button(wrapper, "确认当前完整审核").attributes("disabled")).toBeDefined();
    expect(button(wrapper, "保存待审核版本").attributes("disabled")).toBeUndefined();
    await button(wrapper, "保存待审核版本").trigger("click"); await flushPromises();
    expect(calls.filter(c => c.url.endsWith("/plan-drafts"))).toHaveLength(1);
    expect(calls.some(c => c.url.endsWith("/plan-review-confirmations"))).toBe(false);
  });

  it("confirms the exact first short page with both coverage fields and no automatic activation", async () => {
    const { wrapper, calls, records } = harness(); await loaded(wrapper);
    await vi.waitFor(() => expect(button(wrapper, "确认当前完整审核").attributes("disabled")).toBeUndefined());
    await button(wrapper, "确认当前完整审核").trigger("click"); await flushPromises();
    const posted = calls.find(c => c.url.endsWith("/plan-review-confirmations"))!;
    expect(posted.body).toEqual({ planVersionId: id(1), contentHash: CONTENT, sourceHash: hash(source), reviewEvidenceHash: REVIEW,
      expectedRevision: 0, resolutions: [], coverageEvidenceHash: hash("wire-coverage-1"), coverageRulesVersion: "source-coverage-rules-v1" });
    expect(records.get(id(1))!.reviewRevision).toBe(1);
    expect(calls.some(c => c.url.endsWith("/plan-activations"))).toBe(false);
    expect(calls.some(c => c.url.includes("cursor="))).toBe(false);
    expect(wrapper.findComponent(SourceCoverageReview).exists()).toBe(true);
  });

  it("does not enable confirmation while the actual coverage GET is pending", async () => {
    const pending = deferred<Response>();
    const { wrapper } = harness({ intercept: c => c.url.includes("/source-coverage?") ? pending.promise : undefined });
    await loaded(wrapper);
    expect(button(wrapper, "确认当前完整审核").attributes("disabled")).toBeDefined();
    expect(wrapper.findComponent(SourceCoverageReview).props("phase")).toBe("LOADING");
  });

  it.each(["UNKNOWN", "LEGACY_UNASSESSED", "UPGRADE"] as const)("keeps %s diagnostics readable without confirming", async state => {
    const { wrapper, calls } = harness({ configure: records => {
      const v = records.get(id(1))!, s = summary(v, "UNKNOWN");
      v.sourceCoverage = { ...s, status: state === "LEGACY_UNASSESSED" ? state : "UNKNOWN",
        reason: state === "UPGRADE" ? "SOURCE_COVERAGE_UPGRADE_REQUIRED" : "SOURCE_COVERAGE_REQUIRED",
        mappingHash: null, coverageEvidenceHash: null, coverageRevision: null, coverageBundleHash: null,
        rulesVersion: null, origin: null, obligationCount: 0, issueCount: 0, totalRows: 0 };
    }, intercept: c => {
      if (!c.url.includes("/source-coverage?")) return;
      const v = native(); v.sourceCoverage = { ...summary(v, "UNKNOWN"),
        status: state === "LEGACY_UNASSESSED" ? state : "UNKNOWN",
        reason: state === "UPGRADE" ? "SOURCE_COVERAGE_UPGRADE_REQUIRED" : "SOURCE_COVERAGE_REQUIRED",
        mappingHash: null, coverageEvidenceHash: null, coverageRevision: null, coverageBundleHash: null,
        rulesVersion: null, origin: null, obligationCount: 0, issueCount: 0, totalRows: 0 };
      return response({ ...page(v), items: [], returnedCount: 0, totalRows: 0, nextCursor: null });
    } });
    await loaded(wrapper); await current(wrapper);
    expect(button(wrapper, "确认当前完整审核").attributes("disabled")).toBeDefined();
    expect(calls.some(c => c.url.endsWith("/plan-review-confirmations"))).toBe(false);
  });

  it.each([409, 500])("keeps a coverage GET %s from becoming confirmation permission", async status => {
    const { wrapper, calls } = harness({ intercept: c => c.url.includes("/source-coverage?") ?
      status === 409 ? conflict() : response({ error: { code: "INTERNAL_ERROR", message: "Synthetic failure", details: [] } }, 500) : undefined });
    await loaded(wrapper);
    await vi.waitFor(() => expect(wrapper.findComponent(SourceCoverageReview).props("phase")).toBe(status === 409 ? "STALE" : "ERROR"));
    expect(button(wrapper, "确认当前完整审核").attributes("disabled")).toBeDefined();
    expect(calls.filter(c => c.url.includes("/source-coverage?"))).toHaveLength(1);
  });

  it("does not bind a preview with different complete JSON to the native saved plan", async () => {
    const { wrapper, work, calls } = harness({ intercept: c => {
      if (!c.url.endsWith("/plan-review-previews")) return;
      const changed = JSON.parse(c.body.candidateJson); changed.position.max_qty = 200;
      return response({ candidateJson: JSON.stringify(changed), supplementRevision: 0,
        review: { content_hash: CONTENT, source_hash: hash(source), evidence_hash: REVIEW, mapping: c.body.mapping, issues: [] } });
    } });
    await loaded(wrapper);
    expect(work.dirty.value).toBe(false);
    expect(button(wrapper, "确认当前完整审核").attributes("disabled")).toBeDefined();
    await work.confirm();
    expect(calls.some(c => c.url.endsWith("/plan-review-confirmations"))).toBe(false);
    expect(calls.some(c => c.url.includes("/source-coverage?"))).toBe(false);
  });

  it.each(["source", "candidate", "mapping"] as const)("invalidates the displayed proof on a %s edit", async kind => {
    const { wrapper, work, calls } = harness(); await loaded(wrapper); await current(wrapper);
    if (kind === "source") work.editSource(`${source} 改动`);
    else if (kind === "candidate") work.edit({ ...(work.candidate.value as Record<string, Json>), name: "Changed" });
    else work.mapping.value = { ...mapping(), bindings: [] };
    await flushPromises();
    expect(button(wrapper, "确认当前完整审核").attributes("disabled")).toBeDefined();
    expect(wrapper.findComponent(SourceCoverageReview).props("page")).toBeNull();
    await work.confirm();
    expect(calls.some(c => c.url.endsWith("/plan-review-confirmations"))).toBe(false);
  });

  it.each(["number", "numeric-string", "missing", "null", "array-order"])("rechecks a direct nested %s change immediately before confirm", async mutation => {
    const { wrapper, work, calls } = harness({ configure: records => {
      if (mutation !== "array-order") return;
      const v = records.get(id(1))!, raw = JSON.parse(v.planJson); raw.extra = [1, 2];
      v.planJson = JSON.stringify(raw); v.planHash = hash(v.planJson); v.sourceCoverage = summary(v);
    } }); await loaded(wrapper); await current(wrapper);
    const candidate = work.candidate.value as Record<string, Json>;
    if (mutation === "number") (candidate.position as Record<string, Json>).max_qty = 200;
    if (mutation === "numeric-string") (candidate.position as Record<string, Json>).max_qty = "300";
    if (mutation === "missing") delete (candidate.position as Record<string, Json>).max_qty;
    if (mutation === "null") candidate.position = null;
    if (mutation === "array-order") candidate.extra = [2, 1];
    // shallowRef does not observe this edit; the dispatch guard must do so itself.
    await work.confirm(); await flushPromises();
    expect(calls.some(c => c.url.endsWith("/plan-review-confirmations"))).toBe(false);
    expect(wrapper.findComponent(SourceCoverageReview).props("page")).toBeNull();
  });

  it("accepts complete JSON object key reordering without changing array or value semantics", async () => {
    const { wrapper, work, calls } = harness(); await loaded(wrapper); await current(wrapper);
    const entries = Object.entries(work.candidate.value as Record<string, Json>).reverse();
    work.candidate.value = Object.fromEntries(entries); await flushPromises(); await current(wrapper);
    await work.confirm(); await flushPromises();
    expect(calls.filter(c => c.url.endsWith("/plan-review-confirmations"))).toHaveLength(1);
  });

  it("keeps the captured binding while busy and ignores a sent confirmation after a route change", async () => {
    const pending = deferred<Response>();
    const { wrapper, work, calls } = harness({ intercept: c => c.url.endsWith("/plan-review-confirmations") ? pending.promise : undefined });
    await loaded(wrapper); await current(wrapper);
    const confirmed = work.confirm(); await flushPromises();
    expect(work.busy.value).toBe(true);
    expect(calls.filter(c => c.url.endsWith("/plan-review-confirmations"))).toHaveLength(1);
    await wrapper.setProps({ planVersionId: id(2) }); await loaded(wrapper); await current(wrapper);
    pending.resolve(response({ canActivate: true, revision: 1 })); await confirmed; await flushPromises();
    expect(work.saved.value?.id).toBe(id(2));
    expect(work.notice.value).not.toContain("当前版本已审核");
  });

  it("rejects late coverage for A across A-B-A navigation even when hashes match", async () => {
    const pending = deferred<Response>(); let first = true;
    const { wrapper, calls, records } = harness({ intercept: c => {
      if (c.url.includes(`/plan-versions/${id(1)}/source-coverage?`) && first) { first = false; return pending.promise; }
    } });
    await loaded(wrapper); await vi.waitFor(() => expect(calls.some(c => c.url.includes("/source-coverage?"))).toBe(true));
    const old = calls.find(c => c.url.includes("/source-coverage?"))!;
    await wrapper.setProps({ planVersionId: id(2) }); await loaded(wrapper); await current(wrapper);
    records.get(id(1))!.sourceCoverage = summary(records.get(id(1))!, "BLOCKED", 2);
    await wrapper.setProps({ planVersionId: id(1) }); await loaded(wrapper); await current(wrapper);
    const stale = native(); stale.sourceCoverage = summary(stale);
    pending.resolve(response(page(stale))); await flushPromises();
    expect(old.signal?.aborted).toBe(true);
    expect(wrapper.findComponent(SourceCoverageReview).props("page")!.summary.status).toBe("BLOCKED");
    expect(button(wrapper, "确认当前完整审核").attributes("disabled")).toBeDefined();
  });

  it("clears same-hash local reasons, paths and exclusions when the source owner changes", async () => {
    const { wrapper, work } = harness(); await loaded(wrapper); await current(wrapper);
    await wrapper.get("#clause-c1").setValue("这是旧版本填写的人工对应说明，不能被新的来源所有者复用。");
    await wrapper.get("#paths-c1").setValue("position.max_qty");
    await wrapper.get("#exclude-c1").setValue("旧版本范围");
    work.edit(JSON.parse(JSON.stringify(work.candidate.value)) as Json); await work.refreshPreview(); await flushPromises();
    expect((wrapper.get("#clause-c1").element as HTMLTextAreaElement).value).toBe("");
    expect((wrapper.get("#paths-c1").element as HTMLInputElement).value).toBe("");
    expect((wrapper.get("#exclude-c1").element as HTMLInputElement).value).toBe("");
  });

  it("retains unfinished form values during a same-owner same-hash parameter recheck", async () => {
    const { wrapper, work } = harness(); await loaded(wrapper); await current(wrapper);
    const reason = "本来源的其它理由尚未提交，普通参数重检后仍须保留供继续填写。";
    await wrapper.get("#clause-c1").setValue(reason);
    await wrapper.get("#paths-c1").setValue("position.max_qty");
    await wrapper.get("#exclude-c1").setValue("尚未提交的排除片段");
    const generation = work.ownerGeneration.value;
    await button(wrapper, "检查当前参数与来源").trigger("click"); await flushPromises();
    expect(work.ownerGeneration.value).toBe(generation);
    expect(work.preview.value?.review.mapping.candidate_content_hash).toBe(CONTENT);
    expect((wrapper.get("#clause-c1").element as HTMLTextAreaElement).value).toBe(reason);
    expect((wrapper.get("#paths-c1").element as HTMLInputElement).value).toBe("position.max_qty");
    expect((wrapper.get("#exclude-c1").element as HTMLInputElement).value).toBe("尚未提交的排除片段");
  });

  it("requires an explicit native re-read and reconfirmation after one 409 without automatic retry", async () => {
    let reject = true;
    const { wrapper, work, calls, records } = harness({ intercept: c => {
      if (c.url.endsWith("/plan-review-confirmations") && reject) { reject = false; return conflict(); }
    } });
    await loaded(wrapper); await current(wrapper);
    await button(wrapper, "确认当前完整审核").trigger("click"); await flushPromises();
    expect(calls.filter(c => c.url.endsWith("/plan-review-confirmations"))).toHaveLength(1);
    expect(button(wrapper, "确认当前完整审核").attributes("disabled")).toBeDefined();
    expect(work.error.value).toContain("重新读取");
    const v = records.get(id(1))!; v.sourceCoverage = summary(v, "COMPLETE", 2);
    const before = calls.length;
    await button(wrapper, "从第一页重新读取").trigger("click"); await current(wrapper);
    const after = calls.slice(before);
    expect(after[0]!.url).toBe(`/api/v1/plan-versions/${id(1)}`);
    expect(after.filter(c => c.url.includes("/source-coverage?"))).toHaveLength(1);
    expect(calls.filter(c => c.url.endsWith("/plan-review-confirmations"))).toHaveLength(1);
    await button(wrapper, "确认当前完整审核").trigger("click"); await flushPromises();
    const posts = calls.filter(c => c.url.endsWith("/plan-review-confirmations"));
    expect(posts).toHaveLength(2);
    expect(posts[1]!.body.coverageEvidenceHash).toBe(hash("wire-coverage-2"));
  });

  it("reads only the typed next page and locates exact DOM IDs without editing any field", async () => {
    const { wrapper, calls, records } = harness({ intercept: c => {
      if (!c.url.includes("cursor=")) return;
      const next = page(records.get(id(1))!); next.items[0]!.rowIndex = 1; next.nextCursor = null; return response(next);
    } });
    await loaded(wrapper); await current(wrapper);
    const input = wrapper.get('[id="daily-.position.max_qty"]');
    wrapper.findComponent(SourceCoverageReview).vm.$emit("revealField", "position.max_qty"); await flushPromises();
    expect(document.activeElement).toBe(input.element);
    const before = calls.length;
    await button(wrapper, "读取下一页").trigger("click"); await current(wrapper);
    expect(calls.slice(before)).toHaveLength(1);
    expect(calls.at(-1)!.method).toBe("GET"); expect(calls.at(-1)!.url).toContain("cursor=");
    expect((input.element as HTMLInputElement).value).toBe("300");
    wrapper.findComponent(SourceCoverageReview).vm.$emit("revealField", "missing[0].field"); await flushPromises();
    expect(wrapper.text()).toContain("没有可定位的编辑字段");
  });

  it.each([5, 6, 7, 8, 9])("binds the actual schema %i current pair without inventing a coverage default", async schema => {
    const { wrapper } = harness({ configure: records => {
      const v = records.get(id(1))!, raw = JSON.parse(v.planJson);
      raw.schema_version = schema; raw.execution_version = `condition-plan-v${schema - 4}`;
      v.planJson = JSON.stringify(raw); v.planHash = hash(v.planJson); v.sourceCoverage = summary(v);
    } });
    await loaded(wrapper); await current(wrapper);
    expect(button(wrapper, "确认当前完整审核").attributes("disabled")).toBeUndefined();
  });

  it("uses the server canConfirm flag rather than COMPLETE or empty native issues", async () => {
    const { wrapper, work, calls } = harness({ configure: records => {
      records.get(id(1))!.sourceCoverage!.canConfirmReview = false;
    } }); await loaded(wrapper); await current(wrapper);
    expect(button(wrapper, "确认当前完整审核").attributes("disabled")).toBeDefined();
    await work.confirm();
    expect(calls.some(c => c.url.endsWith("/plan-review-confirmations"))).toBe(false);
  });

  it("describes a retained review record without claiming blocked source proof is currently reviewed", async () => {
    const { wrapper } = harness({ state: "BLOCKED", configure: records => {
      const v = records.get(id(1))!; v.reviewId = id(90); v.reviewRevision = 1; v.sourceCoverage = summary(v, "BLOCKED");
    } }); await loaded(wrapper); await current(wrapper);
    expect(wrapper.findComponent(PlanSourceReview).text()).toContain("已有审核记录，请查看原文核对状态");
    expect(wrapper.findComponent(PlanSourceReview).text()).not.toContain("当前内容已审核");
    expect(wrapper.findComponent(SourceCoverageReview).text()).toContain("需要重新核对并审核");
    expect(button(wrapper, "确认当前完整审核").attributes("disabled")).toBeDefined();
  });

  it("distinguishes product constants from source and registered human mapping origins", async () => {
    const { wrapper } = harness({ configure: records => {
      const m = records.get(id(1))!.dailyMapping!;
      m.bindings.push({ path: "schema_version", value: 5, origin: "PRODUCT_CONTRACT", unit: "JSON", clause_ids: [], supplement_id: null });
      m.supplements.push({ supplement_id: "wire-human-1", candidate_content_hash: CONTENT, path: "name", value: "Wire plan",
        reason: "明确以当前人工注册定义此候选的计划名称，供界面标签测试。" });
      m.bindings.push({ path: "name", value: "Wire plan", origin: "HUMAN_SUPPLEMENT", unit: "JSON", clause_ids: [], supplement_id: "wire-human-1" });
    } }); await loaded(wrapper); await current(wrapper);
    const rows = wrapper.findComponent(PlanSourceReview).findAll("li");
    const product = rows.find(row => row.text().startsWith("schema_version ="))!;
    expect(product.text()).toContain("产品固定规则"); expect(product.text()).not.toContain("原文来源");
    expect(rows.find(row => row.text().startsWith("position.max_qty ="))!.text()).toContain("原文来源");
    expect(rows.find(row => row.text().startsWith("name ="))!.text()).toContain("已独立登记人工补充");
  });

  it("does not use the old URL prop to disable a newly opened internal version", async () => {
    const { wrapper, work, calls } = harness(); await loaded(wrapper); await current(wrapper);
    await work.openVersion(id(2)); await loaded(wrapper); await current(wrapper);
    expect(wrapper.props("planVersionId")).toBe(id(1)); expect(work.saved.value?.id).toBe(id(2));
    await button(wrapper, "确认当前完整审核").trigger("click"); await flushPromises();
    expect(calls.find(c => c.url.endsWith("/plan-review-confirmations"))!.body.planVersionId).toBe(id(2));
  });

  it("preserves the displayed blocked draft on an explicit native re-read failure", async () => {
    let reject = false;
    const { wrapper, work } = harness({ state: "BLOCKED", intercept: c => {
      if (reject && c.url.endsWith(`/plan-versions/${id(1)}`)) return conflict();
    } }); await loaded(wrapper); await current(wrapper);
    const before = JSON.stringify(work.candidate.value), beforeSource = work.source.value;
    reject = true; await button(wrapper, "重新读取核对结果").trigger("click"); await flushPromises();
    expect(JSON.stringify(work.candidate.value)).toBe(before); expect(work.source.value).toBe(beforeSource);
    expect(work.saved.value?.id).toBe(id(1));
    expect(button(wrapper, "保存待审核版本").attributes("disabled")).toBeUndefined();
    expect(button(wrapper, "确认当前完整审核").attributes("disabled")).toBeDefined();
  });

  it("does not overwrite edited source with a late explicit native re-read", async () => {
    let hold = false; const pending = deferred<Response>();
    const { wrapper, work } = harness({ intercept: c => hold && c.url.endsWith(`/plan-versions/${id(1)}`) ? pending.promise : undefined });
    await loaded(wrapper); await current(wrapper); hold = true;
    const read = work.refreshSourceCoverage(); await flushPromises();
    work.editSource("新的原文需保存审核。"); pending.resolve(response(native())); await read; await flushPromises();
    expect(work.source.value).toBe("新的原文需保存审核。"); expect(work.saved.value).toBeNull();
    expect(work.sourceCoverage.page.value).toBeNull();
  });
});


describe("PBS source-bound workflow", () => {
  function pbsRecords(records: Map<string, PlanVersionView>) {
    const v = records.get(id(1))!, raw = JSON.parse(v.planJson);
    Object.assign(raw, { schema_version: 10, execution_version: "condition-plan-v6", buy_suspension: {
      condition: { type: "MINUTE_CLOSE_BELOW", timeframe_minutes: 5, price_fen: 2420 }, effective_from: "2026-09-30T09:30:00+08:00" } });
    v.planJson = JSON.stringify(raw); v.planHash = hash(v.planJson); v.sourceCoverage = summary(v);
  }
  it("loads all coverage pages and registers only the exact server obligation", async () => {
    let records!: Map<string, PlanVersionView>;
    const { wrapper, work, calls } = harness({ configure: r => { pbsRecords(r); records = r; }, intercept: c => {
      if (c.url.includes("source-coverage?") && c.url.includes("limit=100")) {
        const body = page(records.get(id(1))!); body.limit = 100;
        const next = c.url.includes("cursor="); body.items[0]!.rowIndex = next ? 1 : 0;
        if (next && body.items[0]!.kind === "OBLIGATION") Object.assign(body.items[0]!.obligation, {
          obligationId: hash("guard"), semanticsJson: JSON.stringify({ treatment: "PERSISTENT_BUY_SUSPENSION" }), scope: "BUY" });
        body.nextCursor = next ? null : "wire-next-page"; return response(body);
      }
      if (c.url.endsWith("plan-review-supplements")) return response({ revision: 1 });
    } });
    await loaded(wrapper); await work.loadBuySuspensionObligations();
    expect(work.buySuspensionObligations.value.map(o => o.obligationId)).toEqual([hash("guard")]);
    await work.registerBuySuspensionClarification(hash("guard"), "Explicitly register this exact source guard and approved checking start");
    expect(work.error.value).toBe("");
    const command = calls.find(c => c.url.endsWith("plan-review-supplements"))!;
    expect(command.body.sourceText).toBe(source);
    expect(command.body.supplements).toHaveLength(4);
    expect(command.body.supplements.every((s: Record<string, unknown>) => s.source_hash === hash(source) && s.obligation_id === hash("guard") && s.buy_suspension_clarification === "ALL_PLAN_BUY_REVIEWED_REPLACEMENT_ONLY")).toBe(true);
    expect(calls.some(c => c.url.endsWith("plan-review-confirmations"))).toBe(false);
    expect(calls.some(c => c.url.endsWith("plan-activations"))).toBe(false);
  });
  it("clears guard selections on source changes and ignores a late full-page response", async () => {
    const delayed = deferred<Response>();
    const { wrapper, work } = harness({ configure: pbsRecords, intercept: c => c.url.includes("source-coverage?") && c.url.includes("limit=100") ? delayed.promise : undefined });
    await loaded(wrapper);
    const reading = work.loadBuySuspensionObligations(); await flushPromises();
    work.editSource("Different exact source"); delayed.resolve(response({})); await reading;
    expect(work.buySuspensionObligations.value).toEqual([]);
    expect(work.error.value).toBe(""); expect(work.source.value).toBe("Different exact source");
  });
  it("keeps source-only guard meaning from becoming a review checkbox grant", async () => {
    const { wrapper, work } = harness({ configure: r => { pbsRecords(r); const v = r.get(id(1))!; v.sourceCoverage = summary(v, "BLOCKED"); }, state: "BLOCKED" }); await loaded(wrapper);
    const review = wrapper.findComponent(PlanSourceReview);
    expect(review.text()).toContain("禁买澄清与接替登记");
    expect(review.text()).toContain("其他原文义务仍须解决");
    expect(button(wrapper, "确认当前完整审核").attributes("disabled")).toBeDefined();
    await review.get('[data-pbs="reason"]').setValue("Unsubmitted explanation must disappear on source owner change");
    work.editSource("Different current source"); await flushPromises();
    expect(review.get<HTMLTextAreaElement>('[data-pbs="reason"]').element.value).toBe("");
  });
  it("registers the exact Unicode replacement span but never reviews or activates implicitly", async () => {
    const statement = "本新计划明确接替前序计划的持续禁买义务，并采用新保护条件。";
    const text = `😀新策略\n${statement}\nstrategy_effective_from=2026-11-15T09:30:00+08:00`;
    let intent: unknown; let expectedVersion!: PlanVersionView;
    const { wrapper, work, calls } = harness({ configure: r => {
      pbsRecords(r); const v = r.get(id(1))!;
      v.sourceText = text; v.sourceHash = hash(text); v.dailyMapping = mapping(text); v.sourceCoverage = summary(v); expectedVersion = v;
    }, intercept: c => {
      if (c.url.includes("source-coverage?") && c.url.includes("limit=100")) {
        const v = expectedVersion;
        const result = page(v); result.limit = 100; result.items = [result.items[0]!, { ...result.items[0]!, rowIndex: 1 }];
        result.returnedCount = 2; result.nextCursor = null;
        return response(result);
      }
      if (c.url.endsWith("plan-review-supplements")) { intent = c.body.buySuspensionReplacementIntent; return response({ revision: 1 }); }
      if (c.url.endsWith("plan-review-previews")) return response({ candidateJson: c.body.candidateJson, supplementRevision: intent ? 1 : 0,
        buySuspensionReplacementIntent: intent, review: { content_hash: CONTENT, source_hash: hash(text), evidence_hash: REVIEW, mapping: c.body.mapping, issues: [] } });
    } });
    await loaded(wrapper); await work.loadBuySuspensionObligations();
    // This fixture's source summary must bind the actual Schema10 plan hash.
    expect(work.error.value).toBe("");
    const form = wrapper.findComponent(PlanSourceReview);
    await form.get('[data-pbs="reason"]').setValue("Explicit source proposal for this exact new strategy and reviewed activation");
    await form.get('[data-pbs="excerpt"]').setValue(statement);
    await form.get('[data-pbs="start"]').setValue("2026-11-15T09:30:00+08:00");
    await button(wrapper, "独立登记新原文接替意图").trigger("click");
    await form.findAll("form").at(-1)!.trigger("submit"); await flushPromises();
    expect(work.error.value).toBe("");
    expect(intent).toMatchObject({ source_hash: hash(text), candidate_content_hash: CONTENT, source_start: 5,
      source_end: 5 + Array.from(statement).length, excerpt: statement, authority_granted: false,
      strategy_effective_from: "2026-11-15T09:30:00+08:00" });
    expect(calls.some(c => c.url.endsWith("plan-review-confirmations") || c.url.endsWith("plan-activations"))).toBe(false);
    expect(work.preview.value?.buySuspensionReplacementIntent).toEqual(intent);
  });

});

it("shows the server-read predecessor definition and unresolved interval in replacement review", () => {
  const wrapper = mount(PlanSourceReview, { props: { preview: null, saved: native(), mapping: mapping(), values: { schema_version: 10 }, busy: false,
    predecessorGuard: { ownerPlanVersionId: id(7), ownerHash: CONTENT, birthActivationRevision: 1, state: null, stateRevision: null,
      definition: { condition: { type: "MINUTE_CLOSE_BELOW", timeframe_minutes: 5, price_fen: 2420 }, effective_from: "2026-09-30T09:30:00+08:00" },
      target: "2026-11-15T10:00:00+08:00", outcome: "UNVERIFIED", maintenance: { axis: "DATA_EVALUATION", state: "UNKNOWN" }, blocker: "HISTORY_PENDING" } } });
  wrappers.push(wrapper);
  expect(wrapper.text()).toContain("前序保护：完整5分钟收盘严格低于 24.20 元");
  expect(wrapper.text()).toContain("实际未核实区间：2026-09-30 09:30:00+08:00 至 2026-11-15 10:00:00+08:00");
  expect(wrapper.get('[data-pbs="acknowledge"]').attributes("disabled")).toBeUndefined();
});
