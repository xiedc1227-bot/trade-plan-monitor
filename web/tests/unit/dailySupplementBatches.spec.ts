import { mount } from "@vue/test-utils";
import { defineComponent, h } from "vue";
import { describe, expect, it, vi } from "vitest";
import type { DailyMapping, DailySupplement, PlanVersionView } from "../../src/api/generated";
import { apiFetchKey } from "../../src/api/context";
import { usePlanWorkspace } from "../../src/composables/usePlanWorkspace";

const candidate = { schema_version: 5, execution_mode: "CONDITION_PLAN", execution_version: "condition-plan-v1", plan_id: "synthetic", version: 1, symbol: "601021.SH", levels: { risk_line_fen: 3818, other: 3970 } };
const originalMapping: DailyMapping = {
  mapping_version: "daily-mapping-v1", candidate_content_hash: "a".repeat(64),
  clauses: [], bindings: [], supplements: [],
};
const savedVersionId = "00000000-0000-4000-8000-000000000001";
const nextVersionId = "00000000-0000-4000-8000-000000000002";
const changedAt = "2026-09-18T16:00:00+08:00";

// Synthetic UI wire data, not a source-complete plan or current review grant.
function versionView(raw = candidate, mapping = originalMapping, id = savedVersionId,
  sourceText = "Synthetic source"): PlanVersionView {
  return { id, planId: raw.plan_id, version: raw.version, symbol: raw.symbol,
    planHash: "e".repeat(64), revision: 0, createdAt: changedAt, status: "DRAFT",
    planJson: JSON.stringify(raw), sourceText, dailyMapping: mapping, dailyIssues: [],
    contentHash: mapping.candidate_content_hash, sourceHash: "c".repeat(64),
    reviewEvidenceHash: "d".repeat(64), reviewRevision: 0, reviewId: null,
    reviewIssues: [], validationIssues: [], canActivate: false };
}

function harness(registeredIntent?: object) {
  let registered: DailySupplement[] = [];
  let revision = 0;
  const commands: { expectedRevision: number; supplements: DailySupplement[] }[] = [];
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const body = JSON.parse(String(init?.body ?? "{}"));
    let result: object = {};
    if (url.endsWith("plan-review-previews")) {
      const raw = JSON.parse(body.candidateJson);
      const hash = (raw.levels.risk_line_fen === 3818 ? "a" : "b").repeat(64);
      const exact = hash === "a".repeat(64) ? registered : [];
      const mapping = { ...(body.mapping ?? originalMapping), candidate_content_hash: hash,
        supplements: exact, bindings: exact.map(s => ({ path: s.path, value: s.value,
          origin: "HUMAN_SUPPLEMENT", unit: "JSON", clause_ids: [], supplement_id: s.supplement_id })) };
      result = { candidateJson: body.candidateJson, buySuspensionReplacementIntent: registeredIntent, supplementRevision: exact === registered ? revision : 0,
        review: { content_hash: hash, source_hash: "c".repeat(64), evidence_hash: "d".repeat(64), mapping, issues: [] } };
    } else if (url.endsWith("plan-review-supplements")) {
      commands.push(body);
      if (body.expectedRevision !== revision) throw new Error("conflict");
      registered = body.supplements;
      revision++;
      result = { id: "registry", revision, recordedAt: "2026-09-18T16:00:00+08:00" };
    } else if (url.includes("plan-versions/")) {
      result = versionView();
    } else if (url.endsWith("/plan-drafts")) {
      const raw = JSON.parse(body.planJson);
      result = versionView(raw, body.dailyMapping, nextVersionId, body.sourceText);
    } else if (url.endsWith("plan-editor-schema")) result = { candidateSchema: {}, operationSchemas: {} };
    else if (url.endsWith("/ai-runtime")) result = { providerId: "synthetic", configured: true, enabled: true };
    else if (url.includes("/plan-versions?")) result = { items: [], total: 0, offset: 0, limit: 100 };
    else if (url.includes("/plan-activation-states/")) result = {
      active: false, revision: 0, symbol: candidate.symbol, planVersionId: null, changedAt };
    return new Response(JSON.stringify(result), { headers: { "Content-Type": "application/json" } });
  });
  let work!: ReturnType<typeof usePlanWorkspace>;
  const wrapper = mount(defineComponent({ setup() { work = usePlanWorkspace(); return () => h("div"); } }),
    { global: { provide: { [apiFetchKey as symbol]: fetcher } } });
  work.candidate.value = candidate;
  work.source.value = "Synthetic source";
  work.mapping.value = originalMapping;
  return { work, wrapper, commands, fetcher };
}

describe("daily human supplement batches", () => {
  it("registers cumulative evidence at the latest server revision and keeps it across previews", async () => {
    const { work, wrapper, commands } = harness();
    await work.supplement([{ path: "levels.risk_line_fen", reason: "First explicitly reviewed human policy" }], []);
    expect(work.error.value).toBe("");
    await work.supplement([{ path: "levels.other", reason: "Second explicitly reviewed human policy" }], []);
    expect(work.error.value).toBe("");
    expect(commands.map(c => c.expectedRevision)).toEqual([0, 1]);
    expect(commands.map(c => c.supplements.length)).toEqual([1, 2]);
    await work.refreshPreview();
    expect(work.preview.value?.review.mapping.supplements).toHaveLength(2);
    wrapper.unmount();
  });

  it("restores registered evidence when loading a saved version and preserves review actions", async () => {
    const { work, wrapper } = harness();
    await work.supplement([{ path: "levels.risk_line_fen", reason: "First explicitly reviewed human policy" }], []);
    await work.load(savedVersionId);
    expect(work.preview.value?.review.mapping.supplements).toHaveLength(1);
    expect(work.mapping.value?.supplements).toHaveLength(1);
    expect(work.saved.value?.id).toBe(savedVersionId);
    wrapper.unmount();
  });

  it("discards prior content evidence when the candidate changes", async () => {
    const { work, wrapper } = harness();
    await work.supplement([{ path: "levels.risk_line_fen", reason: "First explicitly reviewed human policy" }], []);
    work.edit({ ...candidate, levels: { ...candidate.levels, risk_line_fen: 3817 } });
    await work.refreshPreview();
    expect(work.mapping.value?.supplements).toEqual([]);
    expect(work.saved.value).toBeNull();
    wrapper.unmount();
  });

  it("saves continued review as a new immutable version while preserving the content binding", async () => {
    const { work, wrapper, fetcher } = harness();
    await work.load(savedVersionId);
    await work.supplement([{ path: "levels.risk_line_fen", reason: "First explicitly reviewed human policy" }], []);
    await work.save();
    expect(work.error.value).toBe("");
    const savedBody = fetcher.mock.calls.find(([url]) => String(url).endsWith("/plan-drafts"))?.[1]?.body;
    expect(JSON.parse(JSON.parse(String(savedBody)).planJson).version).toBe(2);
    expect(work.saved.value?.version).toBe(2);
    expect(work.mapping.value?.supplements[0]?.candidate_content_hash).toBe("a".repeat(64));
    wrapper.unmount();
  });
});


it("does not register a replacement from an absent source statement or auto-review it", async () => {
  const { work, wrapper, commands } = harness();
  await work.load(savedVersionId);
  await work.registerBuySuspensionReplacement({ excerpt: "Not present in the source", reason: "Explicit intended new strategy replacement for this source", strategyStart: "2026-11-15T09:30:00+08:00", retire: true, acknowledge: false });
  expect(commands).toEqual([]); expect(work.error.value).not.toBe("");
  wrapper.unmount();
});

it("preserves a server-registered replacement intent when adding other policy supplements", async () => {
  const intent = { source_hash: "c".repeat(64), candidate_content_hash: "a".repeat(64), source_start: 0, source_end: 1,
    excerpt: "S", replacement_reason: "Synthetic explicit source replacement reason", retire_predecessor_guard: true,
    acknowledge_unverified_predecessor: false, strategy_effective_from: "2026-11-15T09:30:00+08:00", authority_granted: false };
  const { work, wrapper, fetcher } = harness(intent);
  await work.supplement([{ path: "levels.risk_line_fen", reason: "Other explicitly registered human policy evidence" }], []);
  const sent = fetcher.mock.calls.find(([url]) => String(url).endsWith("plan-review-supplements"));
  expect(JSON.parse(String(sent?.[1]?.body))).toMatchObject({ sourceText: "Synthetic source", buySuspensionReplacementIntent: intent });
  wrapper.unmount();
});
