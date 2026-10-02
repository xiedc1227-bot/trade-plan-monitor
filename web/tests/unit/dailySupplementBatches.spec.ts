import { mount } from "@vue/test-utils";
import { defineComponent, h } from "vue";
import { describe, expect, it, vi } from "vitest";
import type { DailyMapping, DailySupplement, PlanVersionView } from "../../src/api/generated";
import { apiFetchKey } from "../../src/api/context";
import { useDailyWorkbench } from "../../src/composables/useDailyWorkbench";

const candidate = { plan_id: "synthetic", version: 1, symbol: "601021.SH", levels: { risk_line_fen: 3818, other: 3970 } };
const originalMapping: DailyMapping = {
  mapping_version: "daily-mapping-v1", candidate_content_hash: "a".repeat(64),
  clauses: [], bindings: [], supplements: [],
};

function harness() {
  let registered: DailySupplement[] = [];
  let revision = 0;
  const commands: { expectedRevision: number; supplements: DailySupplement[] }[] = [];
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const body = JSON.parse(String(init?.body ?? "{}"));
    let result: object = {};
    if (url.endsWith("daily-plan-review-previews")) {
      const raw = JSON.parse(body.candidateJson);
      const hash = (raw.levels.risk_line_fen === 3818 ? "a" : "b").repeat(64);
      const exact = hash === "a".repeat(64) ? registered : [];
      const mapping = { ...(body.mapping ?? originalMapping), candidate_content_hash: hash,
        supplements: exact, bindings: exact.map(s => ({ path: s.path, value: s.value,
          origin: "HUMAN_SUPPLEMENT", unit: "JSON", clause_ids: [], supplement_id: s.supplement_id })) };
      result = { candidateJson: body.candidateJson, supplementRevision: exact === registered ? revision : 0,
        review: { content_hash: hash, source_hash: "c".repeat(64), evidence_hash: "d".repeat(64), mapping, issues: [] } };
    } else if (url.endsWith("daily-plan-review-supplements")) {
      commands.push(body);
      if (body.expectedRevision !== revision) throw new Error("conflict");
      registered = body.supplements;
      revision++;
      result = { id: "registry", revision, recordedAt: "2026-09-18T16:00:00+08:00" };
    } else if (url.includes("plan-versions/")) {
      result = { id: "version", planId: candidate.plan_id, version: 1, planJson: JSON.stringify(candidate), sourceText: "Synthetic source",
        dailyMapping: originalMapping, canActivate: false } as PlanVersionView;
    } else if (url.endsWith("/plan-drafts")) {
      const raw = JSON.parse(body.planJson);
      result = { id: "next-version", planId: raw.plan_id, version: raw.version,
        planJson: body.planJson, dailyMapping: body.dailyMapping };
    } else if (url.endsWith("daily-plan-editor-schema")) result = { candidateSchema: {} };
    return new Response(JSON.stringify(result), { headers: { "Content-Type": "application/json" } });
  });
  let work!: ReturnType<typeof useDailyWorkbench>;
  const wrapper = mount(defineComponent({ setup() { work = useDailyWorkbench(); return () => h("div"); } }),
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
    await work.load("version");
    expect(work.preview.value?.review.mapping.supplements).toHaveLength(1);
    expect(work.mapping.value?.supplements).toHaveLength(1);
    expect(work.saved.value?.id).toBe("version");
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
    await work.load("version");
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
