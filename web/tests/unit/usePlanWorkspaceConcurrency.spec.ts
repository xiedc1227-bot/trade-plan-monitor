import { createHash, webcrypto } from "node:crypto";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { defineComponent, h } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DailyMapping, PlanVersionView } from "../../src/api/generated";
import { apiFetchKey } from "../../src/api/context";
import { usePlanWorkspace } from "../../src/composables/usePlanWorkspace";
import type { Json } from "../../src/components/plans/planSchema";

// UI wire fixtures test actual clients/ownership, not production source proof.
const id = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const hash = (text: string) => createHash("sha256").update(text).digest("hex");
const runtime = { providerId: id(9), configured: true, enabled: true, displayName: "UI wire",
  baseUrl: "https://example.test/v1", model: "wire", revision: 0,
  maxInputChars: 50000, maxOutputTokens: 4096 };
function document(n: number): Record<string, Json> {
  return { schema_version: 5, execution_mode: "CONDITION_PLAN", execution_version: "condition-plan-v1",
    plan_id: `wire-${n}`, version: 1, symbol: "600000.SH", name: `Wire ${n}` };
}
function mapping(raw: string): DailyMapping {
  return { mapping_version: "daily-mapping-v1", candidate_content_hash: hash(raw),
    clauses: [], bindings: [], supplements: [] };
}
function version(n: number): PlanVersionView {
  const planJson = JSON.stringify(document(n)), sourceText = `Wire source ${n}`;
  return { id: id(n), planId: `wire-${n}`, version: 1, symbol: "600000.SH",
    planJson, sourceText, planHash: hash(planJson), contentHash: hash(planJson), sourceHash: hash(sourceText),
    reviewEvidenceHash: hash(`review${n}`), reviewId: null, reviewRevision: 0,
    dailyMapping: mapping(planJson), dailyIssues: [], status: "DRAFT", canActivate: false,
    revision: 0, createdAt: "2026-10-28T10:00:00+08:00" };
}
function extractionResult(n = 1, operationId = id(8)) {
  return { id: operationId, providerId: id(9), status: "SUCCEEDED",
    submittedAt: "2026-10-28T10:00:00+08:00", startedAt: "2026-10-28T10:00:01+08:00",
    completedAt: "2026-10-28T10:00:02+08:00", model: "wire", promptVersion: "plan-extract-v12",
    draftPlanJson: JSON.stringify(document(n)), dailyMapping: mapping(JSON.stringify(document(n))),
    sourceTextSha256: hash(`Wire source ${n}`), evidence: [] };
}
function extractionReceipt(operationId = id(8)) {
  return new Response(JSON.stringify({ kind: "PLAN_EXTRACTION", operationId, status: "QUEUED",
    submittedAt: "2026-10-28T10:00:00+08:00" }), { status: 202 });
}
const active = { active: false, changedAt: "2026-10-28T10:00:00+08:00",
  planVersionId: null, revision: 0, symbol: "600000.SH" };
function json(value: unknown) { return new Response(JSON.stringify(value), { headers: { "Content-Type": "application/json" } }); }
function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
interface Call { url: string; method: string; body: Record<string, any>; signal: AbortSignal | null; key: string | null }
const wrappers: VueWrapper[] = [];
afterEach(() => { wrappers.splice(0).forEach(w => w.unmount()); vi.unstubAllGlobals(); });
function harness(intercept: (call: Call) => Response | Promise<Response> | undefined = () => undefined) {
  vi.stubGlobal("crypto", webcrypto);
  const calls: Call[] = [];
  const fetcher = vi.fn<typeof fetch>(async (input, init) => {
    const call: Call = { url: String(input), method: init?.method ?? "GET",
      body: JSON.parse(String(init?.body ?? "{}")), signal: init?.signal ?? null,
      key: new Headers(init?.headers).get("Idempotency-Key") };
    calls.push(call);
    const selected = intercept(call);
    if (selected !== undefined) return selected;
    if (call.url.endsWith("/plan-editor-schema")) return json({ candidateSchema: {}, operationSchemas: {} });
    if (call.url.endsWith("/ai-runtime")) return json(runtime);
    if (call.url.includes("/plan-versions?")) return json({ items: [], total: 0, offset: 0, limit: 100 });
    if (call.url.includes("/plan-versions/")) return json(version(call.url.endsWith(id(2)) ? 2 : 1));
    if (call.url.includes("/plan-activation-states/")) return json(active);
    if (call.url.endsWith("/plan-review-previews")) return json({ candidateJson: call.body.candidateJson,
      supplementRevision: 0, review: { content_hash: hash(call.body.candidateJson),
        source_hash: hash(call.body.sourceText), evidence_hash: hash("wire-preview"),
        mapping: call.body.mapping ?? mapping(call.body.candidateJson), issues: [] } });
    if (call.url.endsWith("/plan-drafts")) {
      const raw = JSON.parse(call.body.planJson);
      return json({ ...version(3), planId: raw.plan_id, version: raw.version,
        planJson: call.body.planJson, sourceText: call.body.sourceText,
        contentHash: call.body.dailyMapping.candidate_content_hash, sourceHash: hash(call.body.sourceText),
        dailyMapping: call.body.dailyMapping });
    }
    throw new Error(`Unexpected UI request ${call.method} ${call.url}`);
  });
  let work!: ReturnType<typeof usePlanWorkspace>;
  const wrapper = mount(defineComponent({ setup() { work = usePlanWorkspace(); return () => h("div"); } }),
    { global: { provide: { [apiFetchKey as symbol]: fetcher } } });
  wrappers.push(wrapper);
  return { work, calls, wrapper, fetcher };
}
function seed(work: ReturnType<typeof usePlanWorkspace>, n = 1) {
  work.candidate.value = document(n); work.source.value = `Wire source ${n}`;
  work.mapping.value = mapping(JSON.stringify(document(n)));
}

describe("workspace current owner concurrency", () => {
  it("admits load B while A is waiting, displays B and ignores A's late response", async () => {
    const first = deferred<Response>();
    const { work, calls } = harness(c => c.url.endsWith(id(1)) ? first.promise : undefined);
    const a = work.load(id(1));
    await vi.waitFor(() => expect(calls.some(c => c.url.endsWith(id(1)))).toBe(true));
    const b = work.load(id(2));
    await b;
    expect(calls.some(c => c.url.endsWith(id(2)))).toBe(true);
    expect(work.saved.value?.id).toBe(id(2));
    first.resolve(json(version(1))); await a;
    expect(work.saved.value?.id).toBe(id(2)); expect(work.source.value).toBe("Wire source 2");
  });

  it("aborts the superseded load's read-only preview while retaining its exact body", async () => {
    const pending = deferred<Response>(); let previews = 0;
    const { work, calls } = harness(c => c.url.endsWith("/plan-review-previews") && ++previews === 1 ? pending.promise : undefined);
    const a = work.load(id(1));
    await vi.waitFor(() => expect(calls.some(c => c.url.endsWith("/plan-review-previews"))).toBe(true));
    const oldPreview = calls.find(c => c.url.endsWith("/plan-review-previews"))!;
    await work.load(id(2));
    const aborted = oldPreview.signal?.aborted;
    const old = version(1);
    pending.resolve(json({ candidateJson: old.planJson, supplementRevision: 0,
      review: { content_hash: old.contentHash, source_hash: old.sourceHash,
        evidence_hash: old.reviewEvidenceHash, mapping: old.dailyMapping, issues: [] } })); await a;
    expect(oldPreview.body).toEqual({ candidateJson: old.planJson,
      sourceText: old.sourceText, mapping: old.dailyMapping });
    expect(work.saved.value?.id).toBe(id(2)); expect(work.source.value).toBe("Wire source 2");
    expect(aborted).toBe(true);
  });

  it("clears a selected plan synchronously for an empty/new-plan route", async () => {
    const { work } = harness(); await work.load(id(1));
    expect(work.saved.value?.id).toBe(id(1));
    const clearing = work.load();
    expect(work.saved.value).toBeNull(); expect(work.candidate.value).toBeNull();
    await clearing;
    expect(work.source.value).toBe(""); expect(work.saved.value).toBeNull();
  });

  it("does not overwrite an edit with a preview response from the previous source owner", async () => {
    const reply = deferred<Response>();
    const { work, calls } = harness(c => c.url.endsWith("/plan-review-previews") ? reply.promise : undefined);
    seed(work);
    const checking = work.refreshPreview();
    await vi.waitFor(() => expect(calls.some(c => c.url.endsWith("/plan-review-previews"))).toBe(true));
    work.edit(document(2)); work.editSource("Edited source B");
    reply.resolve(json({ candidateJson: JSON.stringify(document(1)), supplementRevision: 0,
      review: { content_hash: hash("old"), source_hash: hash("old-source"), evidence_hash: hash("old-review"),
        mapping: mapping(JSON.stringify(document(1))), issues: [] } }));
    await checking;
    expect(work.candidate.value).toEqual(document(2)); expect(work.source.value).toBe("Edited source B");
    expect(work.preview.value).toBeNull(); expect(work.dirty.value).toBe(true);
  });

  it("does not send a mixed save after editing while the activation GET is pending", async () => {
    const state = deferred<Response>();
    const { work, calls } = harness(c => c.url.includes("/plan-activation-states/") ? state.promise : undefined);
    seed(work); const saving = work.save();
    await vi.waitFor(() => expect(calls.some(c => c.url.includes("/plan-activation-states/"))).toBe(true));
    work.edit(document(2)); work.editSource("Edited B while save awaited");
    state.resolve(json(active)); await saving;
    expect(calls.filter(c => c.url.endsWith("/plan-drafts"))).toHaveLength(0);
    expect(work.dirty.value).toBe(true); expect(work.saved.value).toBeNull();
  });

  it("keeps B loading when A's rejected read runs its error and finally", async () => {
    const first = deferred<Response>(), second = deferred<Response>(); let editors = 0;
    const { work } = harness(c => c.url.endsWith("/plan-editor-schema") ? (++editors === 1 ? first.promise : second.promise) : undefined);
    const a = work.load(id(1)); const b = work.load(id(2));
    first.reject(new Error("Old A failure")); await a;
    expect(work.busy.value).toBe(true); expect(work.error.value).toBe("");
    second.resolve(json({ candidateSchema: { title: "B schema" }, operationSchemas: {} })); await b;
    expect(work.saved.value?.id).toBe(id(2)); expect(work.schema.value.title).toBe("B schema");
  });

  it("never applies A's metadata after B has become the current owner", async () => {
    const first = deferred<Response>(); let editors = 0;
    const { work } = harness(c => c.url.endsWith("/plan-editor-schema") && ++editors === 1 ? first.promise : undefined);
    const a = work.load(id(1)); await work.load(id(2));
    first.resolve(json({ candidateSchema: { title: "Old A schema" }, operationSchemas: {} })); await a;
    expect(work.saved.value?.id).toBe(id(2)); expect(work.schema.value.title).not.toBe("Old A schema");
  });

  it("distinguishes a new A intent from an earlier A across A-B-A", async () => {
    const first = deferred<Response>(); let aReads = 0;
    const latest = version(1);
    latest.planJson = JSON.stringify({ ...document(1), name: "Latest A" });
    latest.contentHash = hash(latest.planJson); latest.planHash = hash(latest.planJson);
    latest.dailyMapping = mapping(latest.planJson);
    const { work, calls } = harness(c => c.url.endsWith(id(1)) ? (++aReads === 1 ? first.promise : json(latest)) : undefined);
    const oldA = work.load(id(1));
    await vi.waitFor(() => expect(calls.some(c => c.url.endsWith(id(1)))).toBe(true));
    await work.load(id(2)); await work.load(id(1));
    first.resolve(json(version(1))); await oldA;
    expect(work.candidate.value).toEqual({ ...document(1), name: "Latest A" });
    expect(calls.find(c => c.url.endsWith(id(1)))!.signal?.aborted).toBe(true);
  });

  it.each(["runtime", "list"])("does not apply a stale %s after a newer load", async stage => {
    const pending = deferred<Response>(); let seen = 0;
    const target = (c: Call) => stage === "runtime" ? c.url.endsWith("/ai-runtime") : c.url.includes("/plan-versions?");
    const { work, calls } = harness(c => {
      if (!target(c)) return undefined;
      seen++;
      // usePlanDrafting's mounted runtime read is separate from workspace.load.
      return seen === (stage === "runtime" ? 2 : 1) ? pending.promise : undefined;
    });
    const old = work.load(id(1));
    await vi.waitFor(() => expect(calls.filter(target)).toHaveLength(stage === "runtime" ? 2 : 1));
    await work.load(id(2));
    pending.resolve(json(stage === "runtime" ? { ...runtime, model: "Old A runtime" } :
      { items: [], total: 0, offset: 0, limit: 100 })); await old;
    expect(work.saved.value?.id).toBe(id(2)); expect(work.providers.value[0]?.model).toBe("wire");
  });

  it.each(["detail", "preview", "activation"])("invalidates load at its pending %s read when source is edited", async stage => {
    const pending = deferred<Response>();
    const matches = (c: Call) => stage === "detail" ? c.url.endsWith(id(1)) :
      stage === "preview" ? c.url.endsWith("/plan-review-previews") : c.url.includes("/plan-activation-states/");
    const { work, calls } = harness(c => matches(c) ? pending.promise : undefined);
    const loading = work.load(id(1));
    await vi.waitFor(() => expect(calls.some(matches)).toBe(true));
    work.editSource("Edited B while loading"); work.edit(document(2));
    const old = version(1);
    pending.resolve(json(stage === "detail" ? old : stage === "activation" ? active : {
      candidateJson: old.planJson, supplementRevision: 0, review: { content_hash: old.contentHash,
        source_hash: old.sourceHash, evidence_hash: old.reviewEvidenceHash, mapping: old.dailyMapping, issues: [] } }));
    await loading;
    expect(work.source.value).toBe("Edited B while loading"); expect(work.candidate.value).toEqual(document(2));
    expect(work.saved.value).toBeNull(); expect(work.dirty.value).toBe(true);
  });

  it.each([false, true])("ignores an already-sent old save's late response (rejected=%s)", async rejected => {
    const pending = deferred<Response>();
    const { work, calls } = harness(c => c.url.endsWith("/plan-drafts") ? pending.promise : undefined);
    seed(work); const saving = work.save();
    await vi.waitFor(() => expect(calls.some(c => c.url.endsWith("/plan-drafts"))).toBe(true));
    const posted = calls.find(c => c.url.endsWith("/plan-drafts"))!;
    expect(posted.body.sourceText).toBe("Wire source 1"); expect(JSON.parse(posted.body.planJson)).toEqual(document(1));
    await work.load(id(2));
    if (rejected) pending.reject(new Error("Old mutation may have completed"));
    else pending.resolve(json(version(1)));
    await saving;
    expect(work.saved.value?.id).toBe(id(2)); expect(work.source.value).toBe("Wire source 2");
    expect(work.error.value).toBe(""); expect(work.notice.value).toBe("");
  });

  it("captures nested candidate and mapping values before awaiting an activation read", async () => {
    const pending = deferred<Response>();
    const { work, calls } = harness(c => c.url.includes("/plan-activation-states/") ? pending.promise : undefined);
    seed(work);
    const raw = { ...document(1), position: { max_qty: 300 } };
    work.candidate.value = raw;
    const original = work.mapping.value!;
    original.bindings.push({ path: "position.max_qty", value: 300, origin: "SOURCE", unit: "JSON", clause_ids: [], supplement_id: null });
    const saving = work.save();
    raw.position.max_qty = 900; original.bindings[0]!.value = 900;
    pending.resolve(json(active)); await saving;
    const posted = calls.find(c => c.url.endsWith("/plan-drafts"))!;
    expect(JSON.parse(posted.body.planJson).position.max_qty).toBe(300);
    expect(posted.body.dailyMapping.bindings[0].value).toBe(300);
  });

  it("does not post an exclusion after source changes while SHA is pending", async () => {
    const digest = deferred<ArrayBuffer>();
    const { work, calls } = harness(); seed(work);
    work.source.value = "公告说明。😀";
    work.mapping.value = { ...mapping(JSON.stringify(document(1))), clauses: [{ clause_id: "c1", start: 0,
      end: Array.from(work.source.value).length, excerpt: work.source.value, disposition: "POLICY", paths: [], reason: "UI wire" }] };
    vi.stubGlobal("crypto", { randomUUID: () => webcrypto.randomUUID(), subtle: { digest: () => digest.promise } });
    const excluding = work.exclude("c1", "公告说明");
    work.editSource("Owner B source");
    digest.resolve(new ArrayBuffer(32)); await excluding;
    expect(calls.filter(c => c.url.endsWith("/plan-review-previews"))).toHaveLength(0);
    expect(work.source.value).toBe("Owner B source"); expect(work.notice.value).toContain("原文已修改");
  });

  it("does not register supplements after editing during the first preview", async () => {
    const pending = deferred<Response>();
    const { work, calls } = harness(c => c.url.endsWith("/plan-review-previews") ? pending.promise : undefined);
    seed(work); const applying = work.supplement([{ path: "position.max_qty", reason: "A complete UI-wire human reason" }], []);
    work.editSource("Owner B source");
    pending.resolve(json({ candidateJson: JSON.stringify(document(1)), supplementRevision: 0,
      review: { content_hash: hash("old"), source_hash: hash("oldsource"), evidence_hash: hash("oldreview"),
        mapping: mapping(JSON.stringify(document(1))), issues: [] } }));
    await applying;
    expect(calls.some(c => c.url.endsWith("/plan-review-supplements"))).toBe(false);
    expect(work.source.value).toBe("Owner B source"); expect(work.preview.value).toBeNull();
  });

  it("snapshots human supplement arguments while their initial preview is pending", async () => {
    const pending = deferred<Response>(); let previews = 0;
    const { work, calls } = harness(c => {
      if (c.url.endsWith("/plan-review-previews") && ++previews === 1) return pending.promise;
      if (c.url.endsWith("/plan-review-supplements")) return json({ revision: 1 });
      return undefined;
    });
    seed(work);
    const raw = { ...document(1), position: { max_qty: 300 } }; work.candidate.value = raw;
    const requested = [{ path: "position.max_qty", reason: "Captured source-bound human definition" }];
    const applying = work.supplement(requested, []);
    requested[0]!.path = "position.other"; requested[0]!.reason = "Changed after dispatch";
    raw.position.max_qty = 900;
    pending.resolve(json({ candidateJson: JSON.stringify({ ...document(1), position: { max_qty: 300 } }), supplementRevision: 0,
      review: { content_hash: hash("wire-supplement"), source_hash: hash("Wire source 1"), evidence_hash: hash("review"),
        mapping: mapping(JSON.stringify(document(1))), issues: [] } })); await applying;
    const posted = calls.find(c => c.url.endsWith("/plan-review-supplements"))!;
    expect(posted.body.supplements[0]).toMatchObject({ path: "position.max_qty", value: 300,
      reason: "Captured source-bound human definition" });
  });

  it.each([false, true])("binds extraction results to the submitting owner (navigate=%s)", async navigate => {
    const pending = deferred<Response>();
    const { work, calls } = harness(c => {
      if (c.url.endsWith("/plan-extractions")) return pending.promise;
      if (c.url.endsWith(`/plan-extractions/${id(8)}`)) return json({ id: id(8), providerId: id(9), status: "SUCCEEDED",
        submittedAt: "2026-10-28T10:00:00+08:00", startedAt: "2026-10-28T10:00:01+08:00",
        completedAt: "2026-10-28T10:00:02+08:00", model: "wire", promptVersion: "plan-extract-v12",
        draftPlanJson: JSON.stringify(document(1)), dailyMapping: mapping(JSON.stringify(document(1))),
        sourceTextSha256: hash("Wire source 1"), evidence: [] });
      return undefined;
    });
    const extracting = work.extract({ providerId: id(9), expectedRevision: 0, sourceText: "Wire source 1" });
    await vi.waitFor(() => expect(calls.some(c => c.url.endsWith("/plan-extractions"))).toBe(true));
    if (navigate) await work.load(id(2));
    pending.resolve(new Response(JSON.stringify({ kind: "PLAN_EXTRACTION", operationId: id(8), status: "QUEUED",
      submittedAt: "2026-10-28T10:00:00+08:00" }), { status: 202 })); await extracting;
    if (navigate) {
      expect(work.saved.value?.id).toBe(id(2)); expect(work.source.value).toBe("Wire source 2");
      expect(work.extraction.value).toBeNull(); expect(work.notice.value).toBe("");
    } else {
      expect(work.candidate.value).toEqual(document(1)); expect(work.dirty.value).toBe(true);
      expect(work.extraction.value?.status).toBe("SUCCEEDED"); expect(work.notice.value).toContain("已提取候选");
    }
  });

  it("invalidates the old saved owner even when a direct new-source extraction fails", async () => {
    const { work } = harness(c => c.url.endsWith("/plan-extractions") ? Promise.reject(new Error("UI wire submit failed")) : undefined);
    await work.load(id(1)); expect(work.saved.value?.id).toBe(id(1));
    await work.extract({ providerId: id(9), expectedRevision: 0, sourceText: "Direct new source B" });
    expect(work.source.value).toBe("Direct new source B"); expect(work.saved.value).toBeNull();
    expect(work.mapping.value).toBeNull(); expect(work.preview.value).toBeNull();
    expect(work.activated.value).toBeNull(); expect(work.dirty.value).toBe(true);
  });

  it("does not expose the previous receipt while a new source submission is pending", async () => {
    const pending = deferred<Response>(); let submissions = 0;
    const { work, calls } = harness(c => {
      if (c.url.endsWith("/plan-extractions")) return ++submissions === 2 ? pending.promise :
        new Response(JSON.stringify({ kind: "PLAN_EXTRACTION", operationId: id(8), status: "QUEUED",
          submittedAt: "2026-10-28T10:00:00+08:00" }), { status: 202 });
      if (c.url.endsWith(`/plan-extractions/${id(8)}`)) return json({ id: id(8), providerId: id(9), status: "SUCCEEDED",
        submittedAt: "2026-10-28T10:00:00+08:00", startedAt: "2026-10-28T10:00:01+08:00",
        completedAt: "2026-10-28T10:00:02+08:00", model: "wire", promptVersion: "plan-extract-v12",
        draftPlanJson: JSON.stringify(document(1)), dailyMapping: mapping(JSON.stringify(document(1))),
        sourceTextSha256: hash("Wire source A"), evidence: [] });
      return undefined;
    });
    await work.extract({ providerId: id(9), expectedRevision: 0, sourceText: "Wire source A" });
    expect(work.extraction.value?.id).toBe(id(8));
    work.editSource("Wire source B"); expect(work.extraction.value).toBeNull();
    const next = work.extract({ providerId: id(9), expectedRevision: 0, sourceText: "Wire source B" });
    await vi.waitFor(() => expect(calls.filter(c => c.url.endsWith("/plan-extractions"))).toHaveLength(2));
    const oldReceipt = work.extraction.value;
    pending.reject(new Error("New submit result unknown")); await next;
    expect(oldReceipt).toBeNull(); expect(work.extraction.value).toBeNull();
  });

  it("exposes the actual newly accepted receipt and completes its current source", async () => {
    const submitted = deferred<Response>(), polled = deferred<Response>(); let submissions = 0;
    const { work, calls } = harness(c => {
      if (c.url.endsWith("/plan-extractions")) return ++submissions === 1 ? extractionReceipt() : submitted.promise;
      if (c.url.endsWith(`/plan-extractions/${id(8)}`)) return json(extractionResult());
      if (c.url.endsWith(`/plan-extractions/${id(7)}`)) return polled.promise;
      return undefined;
    });
    await work.extract({ providerId: id(9), expectedRevision: 0, sourceText: "Wire source 1" });
    work.editSource("Wire source 2");
    const next = work.extract({ providerId: id(9), expectedRevision: 0, sourceText: "Wire source 2" });
    await vi.waitFor(() => expect(calls.filter(c => c.url.endsWith("/plan-extractions"))).toHaveLength(2));
    expect(work.extraction.value).toBeNull(); submitted.resolve(extractionReceipt(id(7)));
    await vi.waitFor(() => expect(calls.some(c => c.url.endsWith(`/plan-extractions/${id(7)}`))).toBe(true));
    expect(work.extraction.value).toMatchObject({ id: id(7), status: "QUEUED" });
    polled.resolve(json(extractionResult(2, id(7)))); await next;
    expect(work.candidate.value).toEqual(document(2)); expect(work.source.value).toBe("Wire source 2");
    expect(work.extraction.value?.id).toBe(id(7)); expect(work.dirty.value).toBe(true);
  });

  it("rechecks the same current operation after a query failure without submitting another job", async () => {
    let queries = 0;
    const { work, calls } = harness(c => {
      if (c.url.endsWith("/plan-extractions")) return extractionReceipt();
      if (c.url.endsWith(`/plan-extractions/${id(8)}`)) return ++queries === 1 ?
        Promise.reject(new Error("UI wire query unavailable")) : json(extractionResult());
      return undefined;
    });
    await work.extract({ providerId: id(9), expectedRevision: 0, sourceText: "Wire source 1" });
    expect(work.extraction.value).toMatchObject({ id: id(8), status: "QUEUED" });
    expect(work.error.value).not.toBe(""); await work.retryExtraction();
    expect(calls.filter(c => c.url.endsWith("/plan-extractions"))).toHaveLength(1);
    expect(calls.filter(c => c.url.endsWith(`/plan-extractions/${id(8)}`))).toHaveLength(2);
    expect(work.extraction.value?.status).toBe("SUCCEEDED"); expect(work.candidate.value).toEqual(document(1));
    expect(work.error.value).toBe("");
  });

  it("stops waiting for its current receipt without adopting a later result or claiming server cancellation", async () => {
    const polled = deferred<Response>();
    const { work, calls } = harness(c => {
      if (c.url.endsWith("/plan-extractions")) return extractionReceipt();
      if (c.url.endsWith(`/plan-extractions/${id(8)}`)) return polled.promise;
      return undefined;
    });
    const pending = work.extract({ providerId: id(9), expectedRevision: 0, sourceText: "Wire source 1" });
    await vi.waitFor(() => expect(work.extraction.value?.id).toBe(id(8)));
    work.stopWaiting(id(8)); polled.resolve(json(extractionResult())); await pending;
    expect(work.extraction.value).toBeNull(); expect(work.candidate.value).toBeNull();
    expect(work.notice.value).toContain("服务端已接收的任务可能仍会继续执行");
    expect(calls.some(c => c.url.endsWith("/plan-review-previews"))).toBe(false);
    expect(calls.some(c => c.url.includes("cancel"))).toBe(false);
  });

  it("retains the same mutation idempotency key for an identical failed save retry", async () => {
    let failed = false;
    const { work, calls } = harness(c => {
      if (c.url.endsWith("/plan-drafts") && !failed) { failed = true; return Promise.reject(new Error("Unknown response")); }
      return undefined;
    });
    seed(work); await work.save(); await work.save();
    const posts = calls.filter(c => c.url.endsWith("/plan-drafts"));
    expect(posts).toHaveLength(2); expect(posts[0]!.key).toBe(posts[1]!.key);
    expect(posts[0]!.body).toEqual(posts[1]!.body);
    expect(work.saved.value).not.toBeNull();
  });

  it("does not revive an unmounted workspace or start a new load after disposal", async () => {
    const pending = deferred<Response>();
    const { work, calls, wrapper } = harness(c => c.url.endsWith(id(1)) ? pending.promise : undefined);
    const loading = work.load(id(1));
    await vi.waitFor(() => expect(calls.some(c => c.url.endsWith(id(1)))).toBe(true));
    wrapper.unmount(); const before = calls.length;
    pending.resolve(json(version(1))); await loading; await work.load(id(2)); await flushPromises();
    expect(calls).toHaveLength(before); expect(work.saved.value).toBeNull();
  });
});
