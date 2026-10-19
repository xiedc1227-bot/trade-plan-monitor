import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import type { CollectionItemView, CollectionPreparationView, PreparationSource, PreparationView, PreparationFrozenView, SourceBoundField } from "../../src/api/generated-runtime-status";
import { createPreparationApi, type PreparationApi, type PreparationFrozenReceipt } from "../../src/api/preparations";
import { buildPreparationReview, inspectPreparationReview, validReviewCandidate } from "../../src/api/preparationReview";
import { usePlanPreparation } from "../../src/composables/usePlanPreparation";
import PlanPreparationReview from "../../src/components/backtests/PlanPreparationReview.vue";
import PlanPreparationSourceForm from "../../src/components/backtests/PlanPreparationSourceForm.vue";
import PlanPreparationProgress from "../../src/components/backtests/PlanPreparationProgress.vue";
import BacktestNewView from "../../src/views/BacktestNewView.vue";
import { createRouter, createMemoryHistory } from "vue-router";
import { createPlanApi } from "../../src/api/plans";

const fixture = JSON.parse(readFileSync("tests/fixtures/plan-preparation-review.json", "utf8")) as {
  candidate: PreparationView; reviewed: PreparationView; choices: { path: string; reason: string }[];
};
const evidence = "逐项核对原文、完整规则、期初实际账户及可用时间，明确确认当前候选。";
const fresh = () => structuredClone(fixture.candidate);
function frozenView(): PreparationFrozenView {
  if (fixture.reviewed.candidate?.kind !== "FROZEN") throw new Error("fixture variant");
  return { preparationId: fixture.reviewed.preparationId, manifestHash: fixture.reviewed.candidate.candidateHash, frozen: fixture.reviewed.candidate.frozen };
}
const wrappers: VueWrapper[] = [];
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks(); });
function controller() {
  const api: PreparationApi = { ...createPreparationApi(vi.fn<typeof fetch>()),
    get: vi.fn<PreparationApi["get"]>().mockResolvedValue({ body: fresh(), status: 200, retryAfterSeconds: null }),
    review: vi.fn<PreparationApi["review"]>().mockImplementation(async () => {
      vi.mocked(api.get).mockResolvedValue({ body: fixture.reviewed, status: 200, retryAfterSeconds: null });
      return { body: frozenView(), status: 200 };
    }),
  };
  let state!: ReturnType<typeof usePlanPreparation>;
  const wrapper = mount(defineComponent({ setup() {
    state = usePlanPreparation({ api, initialPreparationId: fixture.candidate.preparationId, createId: () => "review-key" });
    return () => h("div");
  } }));
  wrappers.push(wrapper);
  return { state, api, wrapper };
}
function preview(preparation = fresh()) {
  const wrapper = mount(PlanPreparationReview, { props: { preparation, canReview: true, sourceDirty: false, reviewed: false } });
  wrappers.push(wrapper);
  return wrapper;
}
async function confirmPreview(wrapper: Pick<VueWrapper, "get">) {
  await wrapper.get('[data-testid="review-evidence"]').setValue(evidence);
  for (const [index, choice] of fixture.choices.entries()) await wrapper.get(`[data-testid="review-supplement-${index}"]`).setValue(choice.reason);
  await wrapper.get('[data-testid="review-confirmation"]').setValue(true);
}
function receipt(body = frozenView()) {
  return new Response(JSON.stringify(body), { headers: {
    "Cache-Control": "no-store",
  } });
}

describe("exact single preparation review", () => {
  it("keeps required legacy supplement controls visible when a confirmation summary is present", async () => {
    const value = fresh();
    value.candidate!.confirmationSummary = { automaticFacts: ["已确定日期"], questions: [], processingIssues: [] };
    const wrapper = preview(value);
    expect(wrapper.findAll('[data-testid^="review-supplement-"]')).toHaveLength(fixture.choices.length);
    await confirmPreview(wrapper);
    await wrapper.get("form").trigger("submit");
    expect(wrapper.emitted("review")?.[0]?.[0]).toMatchObject({ choices: fixture.choices });
  });
  it("accepts real backend extraction and frozen projections with exact original spans", () => {
    expect(validReviewCandidate(fixture.candidate.candidate, fixture.candidate.source.text)).toBe(true);
    expect(validReviewCandidate(fixture.reviewed.candidate, fixture.reviewed.source.text)).toBe(true);
    expect(inspectPreparationReview(fixture.candidate).blockers).toEqual([]);
    expect(inspectPreparationReview(fixture.candidate).supplements.map(item => item.path)).toEqual(fixture.choices.map(item => item.path));
  });
  it("requires explicit supplements for every displayed unbound value without changing the candidate", () => {
    const original = JSON.stringify(fixture.candidate);
    expect(() => buildPreparationReview(fixture.candidate, evidence, [], true)).toThrow();
    const command = buildPreparationReview(fixture.candidate, evidence, fixture.choices, true);
    expect(command.review).toMatchObject({ confirmed: true, expected_revision: fixture.candidate.revision,
      expected_source_revision: fixture.candidate.sourceRevision, expected_candidate_revision: fixture.candidate.candidateRevision,
      candidate_hash: fixture.candidate.candidate!.candidateHash, evidence_hash: fixture.candidate.candidate!.evidenceHash });
    expect(command.review.mapping!.supplements).toHaveLength(fixture.choices.length);
    expect(command.review.mapping!.supplements[0]).toMatchObject({ path: "activation.mode", value: "MANUAL",
      candidate_content_hash: command.review.mapping!.candidate_content_hash });
    expect(JSON.stringify(fixture.candidate)).toBe(original);
    expect(command.review.account).toBeUndefined();
    expect(command.review.draft).toBeUndefined();
  });
  it.each([[], [{ path: "constructor", reason: evidence }], [...fixture.choices, fixture.choices[0]!],
    fixture.choices.map((item, i) => i === 0 ? { ...item, reason: " " } : item)].map(choices => ({ choices })))("rejects absent, orphan, duplicate or blank choices: %o", ({ choices }) => {
    expect(() => buildPreparationReview(fixture.candidate, evidence, choices, true)).toThrow();
  });
  it.each(["", " ", "x".repeat(2001)])("rejects invalid general review evidence", value => {
    expect(() => buildPreparationReview(fixture.candidate, value, fixture.choices, true)).toThrow();
  });
  it("preserves source cash evidence without making it an execution prerequisite", () => {
    const value = fresh();
    if (value.candidate?.kind !== "EXTRACTION") throw new Error("fixture variant");
    value.candidate.openingAccount.cash_fen = null;
    value.candidate.issues.push("LOOP_ACCOUNT_FACT_REQUIRED: opening_account.cash_fen");
    expect(inspectPreparationReview(value).unknownFacts).not.toContain("opening_account.cash_fen");
    expect(buildPreparationReview(value, evidence, fixture.choices, false).review.account).toBeUndefined();
    expect(buildPreparationReview(value, evidence, fixture.choices, true).review.account).toBeUndefined();
    value.candidate.openingAccount.cash_fen = { value: 0, start: 0, end: 1, excerpt: value.source.text[0]! };
    value.candidate.issues = value.candidate.issues.filter(issue => !issue.includes("cash_fen"));
    expect(inspectPreparationReview(value).unknownFacts).not.toContain("opening_account.cash_fen");
  });
  it("blocks missing chronology, missing technical parameters and unresolved source clauses", () => {
    const time = fresh(); time.source.effective_trade_date = null;
    expect(inspectPreparationReview(time).blockers.length).toBeGreaterThan(0);
    const parameter = fresh();
    if (parameter.candidate?.kind !== "EXTRACTION") throw new Error("fixture variant");
    parameter.candidate.issues.push("DAILY_SOURCE_BINDING_REQUIRED: ordinary_rules[0].quantity");
    parameter.candidate.draft.ordinary_rules[0]!.quantity = null;
    expect(inspectPreparationReview(parameter).blockers.length).toBeGreaterThan(0);
    const clause = fresh();
    if (clause.candidate?.kind !== "EXTRACTION") throw new Error("fixture variant");
    clause.candidate.mapping.clauses[0]!.disposition = "UNRESOLVED";
    expect(inspectPreparationReview(clause).blockers.length).toBeGreaterThan(0);
  });
  it("rejects malformed evidence rather than rendering trusted account facts", () => {
    const value = fresh();
    if (value.candidate?.kind !== "EXTRACTION") throw new Error("fixture variant");
    value.candidate.openingAccount.lots[0]!.unit_cost_yuan!.excerpt = "伪造成本";
    expect(validReviewCandidate(value.candidate, value.source.text)).toBe(false);
  });
  it("sends the generated review contract with its immutable revision and request key", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(receipt());
    const command = buildPreparationReview(fixture.candidate, evidence, fixture.choices, true);
    const result = await createPreparationApi(fetcher).review(fixture.candidate.preparationId, command, "review-one");
    expect(result.body).toEqual(frozenView());
    expect(fetcher.mock.calls[0]![0]).toBe(`/api/v1/backtest-preparations/${fixture.candidate.preparationId}/reviews`);
    const init = fetcher.mock.calls[0]![1]!;
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("Idempotency-Key")).toBe("review-one");
    expect(JSON.parse(String(init.body))).toEqual(command);
  });
  it("rejects forged confirmation and unsafe revisions before network access", async () => {
    const fetcher = vi.fn<typeof fetch>();
    const command = buildPreparationReview(fixture.candidate, evidence, fixture.choices, true);
    const malformed = { review: { ...command.review, expected_revision: Number.MAX_SAFE_INTEGER + 1 } };
    await expect(createPreparationApi(fetcher).review(fixture.candidate.preparationId, malformed, "review-one")).rejects.toMatchObject({ code: "VALIDATION_ERROR" });
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("rejects a frozen receipt for a stale extraction rather than promoting its authority", async () => {
    const stale = structuredClone(frozenView()); stale.frozen.extraction_candidate_hash = "0".repeat(64);
    const api = createPreparationApi(vi.fn<typeof fetch>().mockResolvedValue(receipt(stale)));
    await expect(api.review(fixture.candidate.preparationId, buildPreparationReview(fixture.candidate, evidence, fixture.choices, true), "review-one")).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });
});

describe("preparation creation page composition", () => {
  async function page(initialPreparationId?: string) {
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/backtests/new", component: BacktestNewView }] });
    await router.push("/backtests/new"); await router.isReady();
    const api: PreparationApi = { ...createPreparationApi(vi.fn<typeof fetch>()),
      get: vi.fn<PreparationApi["get"]>().mockResolvedValue({ body: fresh(), status: 200, retryAfterSeconds: null }),
    };
    const planApi = { ...createPlanApi(vi.fn<typeof fetch>()),
      listPlanVersions: vi.fn().mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 }) };
    const wrapper = mount(BacktestNewView, { props: { preparationApi: api, planApi,
      ...(initialPreparationId === undefined ? {} : { initialPreparationId }) },
      global: { plugins: [router], stubs: { BacktestRunForm: true, BacktestReferenceMarketCoveragePanel: true } } });
    wrappers.push(wrapper); await flushPromises(); return { wrapper, api };
  }
  it("keeps default workbench reuse and preparation acquisition inert until an explicit choice", async () => {
    const { wrapper, api } = await page();
    expect(wrapper.findComponent({ name: "WorkbenchPlanReplay" }).exists()).toBe(true);
    expect(api.get).not.toHaveBeenCalled();
    await wrapper.get('[data-testid="choose-prepared-plan"]').trigger("click");
    expect(wrapper.findComponent({ name: "PlanPreparationSourceForm" }).exists()).toBe(true);
    expect(api.get).not.toHaveBeenCalled();
    expect(wrapper.findComponent({ name: "BacktestRunForm" }).exists()).toBe(false);
  });
  it("composes explicit resumed review and blocks mutually exclusive mode switching while the task is unfinished", async () => {
    const { wrapper, api } = await page(fixture.candidate.preparationId);
    expect(wrapper.findComponent(PlanPreparationReview).exists()).toBe(true);
    vi.mocked(api.get).mockResolvedValue({ body: { ...fresh(), workPhase: "UNKNOWN", generation: "g1" }, status: 200, retryAfterSeconds: null });
    await wrapper.get('[data-testid="refresh-preparation"]').trigger("click"); await flushPromises();
    expect(wrapper.get('[data-testid="choose-legacy-plan"]').attributes("disabled")).toBeDefined();
    expect(wrapper.text()).toContain("完成前不能切换");
  });
});

describe("explicit current preparation review controller", () => {
  it("retains the known review revision floor through failed or stale reads until the current state is confirmed", async () => {
    const { state, api } = controller(); await flushPromises();
    vi.mocked(api.review).mockResolvedValue({ body: frozenView(), status: 200 });
    vi.mocked(api.get).mockRejectedValue(new TypeError("read failed"));
    await state.review(evidence, fixture.choices, true);
    expect(state.mutationState.value).toBe("IDLE"); expect(state.isBusy.value).toBe(true);
    expect(state.canUsePrepared.value).toBe(false); expect(state.canSubmitSource.value).toBe(false);
    vi.mocked(api.get).mockResolvedValue({ body: fresh(), status: 200, retryAfterSeconds: null });
    await state.refresh(); expect(state.isBusy.value).toBe(true);
    await state.review(evidence, fixture.choices, true); expect(api.review).toHaveBeenCalledTimes(1);
    vi.mocked(api.get).mockResolvedValue({ body: fixture.reviewed, status: 200, retryAfterSeconds: null });
    await state.refresh(); expect(state.isBusy.value).toBe(false); expect(state.canUsePrepared.value).toBe(true);
  });
  it("never reviews on read and accepts only explicit current review; source edits invalidate approval immediately", async () => {
    const { state, api } = controller(); await flushPromises();
    expect(api.review).not.toHaveBeenCalled(); expect(state.canReview.value).toBe(true);
    await state.review(evidence, fixture.choices, true);
    expect(api.review).toHaveBeenCalledTimes(1); expect(state.canUsePrepared.value).toBe(true);
    state.updateSource({ ...state.draft.value, text: "修正原文" });
    expect(state.sourceDirty.value).toBe(true); expect(state.canUsePrepared.value).toBe(false);
    expect(state.canReview.value).toBe(false);
    await state.review(evidence, fixture.choices, true); expect(api.review).toHaveBeenCalledTimes(1);
  });
  it.each(["CALLING", "UNKNOWN"] as const)("blocks review throughout unended %s work", async workPhase => {
    const { state, api } = controller();
    await flushPromises();
    vi.mocked(api.get).mockResolvedValue({ body: { ...fresh(), workPhase, generation: "unfinished" }, status: 200, retryAfterSeconds: null });
    await state.refresh(); await state.review(evidence, fixture.choices, true);
    expect(state.canReview.value).toBe(false); expect(api.review).not.toHaveBeenCalled();
  });
  it("coalesces explicit review and retries the same immutable payload/key after an unknown outcome", async () => {
    const { state, api } = controller(); await flushPromises();
    let resolve!: (value: PreparationFrozenReceipt) => void;
    const pending = new Promise<PreparationFrozenReceipt>(accept => { resolve = accept; });
    vi.mocked(api.review).mockRejectedValueOnce(new TypeError("network")).mockReturnValueOnce(pending);
    await state.review(evidence, fixture.choices, true);
    const first = vi.mocked(api.review).mock.calls[0]!;
    expect(state.mutationState.value).toBe("UNCERTAIN");
    await state.review("其他说明", [], false); expect(api.review).toHaveBeenCalledTimes(1);
    const retry = state.retryMutation(); const duplicate = state.retryMutation();
    expect(duplicate).toBe(retry); expect(api.review).toHaveBeenCalledTimes(2);
    expect(vi.mocked(api.review).mock.calls[1]!.slice(0, 3)).toEqual(first.slice(0, 3));
    vi.mocked(api.get).mockResolvedValue({ body: fixture.reviewed, status: 200, retryAfterSeconds: null });
    resolve({ body: frozenView(), status: 200 }); await retry;
    expect(state.canUsePrepared.value).toBe(true);
  });
  it("fences late review completion after unmount", async () => {
    const { state, api, wrapper } = controller(); await flushPromises();
    let resolve!: (value: PreparationFrozenReceipt) => void;
    vi.mocked(api.review).mockReturnValue(new Promise(accept => { resolve = accept; }));
    const pending = state.review(evidence, fixture.choices, true);
    wrapper.unmount();
    expect(vi.mocked(api.review).mock.calls[0]![3]!.signal!.aborted).toBe(true);
    resolve({ body: frozenView(), status: 200 }); await pending;
    expect(state.preparation.value!.status).toBe("CANDIDATE");
  });
});

describe("readable complete prepared plan review", () => {
  it("shows complete rules, exact cost, original source evidence and historical chronology", () => {
    const wrapper = preview();
    expect(wrapper.text()).toContain("40.105"); expect(wrapper.text()).toContain("500000");
    expect(wrapper.text()).toContain("2026-08-20T09:00:00+08:00"); expect(wrapper.text()).toContain("4000");
    expect(wrapper.text()).toContain("New structure linked to prior signal");
    expect(wrapper.text()).toContain("每股成本40.105元/股");
    expect(wrapper.find('[data-testid="review-submit"]').attributes("disabled")).toBeDefined();
  });
  it("requires explicit whole review and per-field reasons and resets confirmation after revision or source edits", async () => {
    const wrapper = preview(); await confirmPreview(wrapper);
    expect(wrapper.get('[data-testid="review-submit"]').attributes("disabled")).toBeUndefined();
    await wrapper.get("form").trigger("submit");
    expect(wrapper.emitted("review")![0]![0]).toEqual({ evidence, choices: fixture.choices, unknownConfirmed: false });
    await wrapper.setProps({ preparation: { ...fresh(), revision: fixture.candidate.revision + 1 } });
    expect((wrapper.get('[data-testid="review-confirmation"]').element as HTMLInputElement).checked).toBe(false);
    await confirmPreview(wrapper); await wrapper.setProps({ sourceDirty: true });
    expect(wrapper.text()).toContain("原文已修改");
    expect(wrapper.get('[data-testid="review-submit"]').attributes("disabled")).toBeDefined();
    expect((wrapper.get('[data-testid="review-confirmation"]').element as HTMLInputElement).checked).toBe(false);
  });
  it("preserves unknown facts visibly and requires acknowledging their consequences", async () => {
    const value = fresh(); if (value.candidate?.kind !== "EXTRACTION") throw new Error("fixture variant");
    value.candidate.openingAccount.inventory_quantity = null;
    value.candidate.openingAccount.lots = [];
    const wrapper = preview(value); await confirmPreview(wrapper);
    expect(wrapper.text()).toContain("未知"); expect(wrapper.get('[data-testid="review-submit"]').attributes("disabled")).toBeDefined();
    await wrapper.get('[data-testid="review-unknown-confirmation"]').setValue(true);
    expect(wrapper.get('[data-testid="review-submit"]').attributes("disabled")).toBeUndefined();
  });
  it("renders the exact server-reviewed result and removes further review actions", async () => {
    const wrapper = preview(); await wrapper.setProps({ preparation: fixture.reviewed, canReview: false, reviewed: true });
    expect(wrapper.text()).toContain("401050"); expect(wrapper.text()).toContain("已审核并冻结");
    expect(wrapper.find('[data-testid="review-submit"]').exists()).toBe(false);
  });
});

// Synthetic UI-only collection: preserve real fixture evidence for the opening source.
function collectionReviewFixture() {
  const initial = fresh();
  if (initial.candidate?.kind !== "EXTRACTION" || fixture.reviewed.candidate?.kind !== "FROZEN") throw new Error("fixture variant");
  const initialCandidate = initial.candidate;
  const frozen = fixture.reviewed.candidate.frozen;
  const sources: PreparationSource[] = [initial.source, {
    source_id: "synthetic-later", text: "仅修改最大仓位为1200股，其余规则保留。CORE持仓200股。",
    authored_at: "2026-08-21T08:00:00+08:00", available_at: "2026-08-21T09:00:00+08:00", effective_trade_date: "2026-08-21",
  }];
  const bindings: SourceBoundField[] = frozen.mapping.bindings.map(binding => ({ binding: structuredClone(binding),
    candidate_content_hash: frozen.mapping.candidate_content_hash, original_path: binding.path, path: binding.path,
    source_hash: "a".repeat(64), source_id: sources[0]!.source_id,
    clauses: structuredClone(frozen.mapping.clauses.filter(clause => binding.clause_ids.includes(clause.clause_id))),
    supplement: structuredClone(frozen.mapping.supplements.find(item => item.supplement_id === binding.supplement_id) ?? null),
  }));
  const details: CollectionItemView[] = sources.map((source, index) => {
    const candidateHash = String(index + 1).repeat(64), evidenceHash = String(index + 3).repeat(64);
    const draft = structuredClone(initialCandidate.draft);
    if (index) { draft.position.max_qty = 1200; draft.version = 2; }
    const itemBindings = structuredClone(bindings);
    if (index) {
      const maximum = itemBindings.find(item => item.path === "position.max_qty")!;
      maximum.source_id = source.source_id; maximum.source_hash = "b".repeat(64);
      maximum.binding.value = 1200; maximum.binding.clause_ids = ["synthetic-change"];
      maximum.clauses = [{ clause_id: "synthetic-change", start: 0, end: source.text.indexOf("。") + 1,
        excerpt: source.text.slice(0, source.text.indexOf("。") + 1), disposition: "POLICY", paths: ["position.max_qty"], reason: "原文明示修改仓位上限" }];
      const version = itemBindings.find(item => item.path === "version"); if (version) version.binding.value = 2;
    }
    const start = source.text.indexOf("CORE持仓200股");
    return { sourceId: source.source_id, sourceRevision: 1, candidateRevision: 2, baseHash: index ? "1".repeat(64) : null,
      candidateHash, evidenceHash, validation: "VALID", attemptCount: 1, status: "CANDIDATE",
      effectiveTradeDate: source.effective_trade_date ?? null, source, attempts: [{ attempt_id: `attempt-${index}`,
        base_hash: index ? "1".repeat(64) : null, source_hash: index ? "b".repeat(64) : "a".repeat(64), source_revision: 1,
        started_at: source.available_at!, finished_at: source.available_at!, status: "SUCCEEDED", retryable: false }],
      candidate: { kind: index ? "MATERIALIZED" : "INITIAL", candidateHash, evidenceHash, validation: "VALID", issues: [],
        draft, mapping: index ? null : structuredClone(frozen.mapping),
        openingAccount: index ? null : structuredClone(initialCandidate.openingAccount),
        review: index ? { source_id: source.source_id, source_hash: "b".repeat(64), available_at: source.available_at!, draft,
          bindings: itemBindings, issues: [], changes: [{ target: "position", rule_id: null,
            action: "MODIFY", before: { max_qty: 1000 }, after: { max_qty: 1200 }, clause_ids: ["synthetic-change"] }],
          account_context: { core_qty: { value: 200, start, end: start + 10, excerpt: "CORE持仓200股" },
            tactical_qty: null, dependent_rule_ids: [], dependency_clause_ids: [] },
        } : null },
    };
  });
  const collection: CollectionPreparationView = { schemaVersion: "backtest-preparation-v2", preparationId: "synthetic-collection-review",
    revision: 9, reviewRevision: 0, itemCount: details.length, status: "CANDIDATE", workPhase: null, generation: null,
    currentSourceId: null, frozen: null, items: details.map(({ source, candidate, attempts, ...summary }) => summary) };
  return { collection, details, sources };
}
function collectionPreview(value = collectionReviewFixture()) {
  const wrapper = mount(PlanPreparationReview, { props: { collection: value.collection, items: value.details,
    canReview: true, sourceDirty: false, reviewed: false } });
  wrappers.push(wrapper); return { wrapper, ...value };
}
function batchForm(sources: PreparationSource[]) {
  const wrapper = mount(PlanPreparationSourceForm, { props: { source: sources[0]!, sources, disabled: false } });
  wrappers.push(wrapper); return wrapper;
}
function labelledControl(wrapper: VueWrapper, labelText: string) {
  const label = wrapper.findAll("label").find(item => item.text().includes(labelText));
  if (!label) throw new Error(`Missing visible label: ${labelText}`);
  return label.attributes("for") ? wrapper.get(`[id="${label.attributes("for")}"]`) : label.get("input, select");
}
async function confirmCollection(wrapper: VueWrapper) {
  await wrapper.get('[data-testid="review-evidence"]').setValue(evidence);
  await wrapper.get('[data-testid="review-confirmation"]').setValue(true);
}

describe("ordered collection preparation interface", () => {
  it("renders each complete source independently in collection mode", () => {
    const sources = [
      { ...fresh().source, source_id: "synthetic-first", text: "Synthetic first complete source." },
      { ...fresh().source, source_id: "synthetic-later", text: "Synthetic later complete source." },
    ];
    const wrapper = mount(PlanPreparationSourceForm, { props: { source: sources[0]!, sources, disabled: false } });
    wrappers.push(wrapper);
    expect(wrapper.findAll("textarea").map(item => (item.element as HTMLTextAreaElement).value)).toEqual(sources.map(item => item.text));
    expect(wrapper.findAll('input[type="date"]')).toHaveLength(2);
    expect(wrapper.findAll('input[type="datetime-local"]')).toHaveLength(0);
  });
  it("emits edits, additions, removals and reorderings with stable source identities", async () => {
    const { sources } = collectionReviewFixture(); const original = structuredClone(sources); const wrapper = batchForm(sources);
    await wrapper.findAll("textarea")[1]!.setValue("后续原文更正");
    expect(wrapper.emitted("update:sources")!.at(-1)![0]).toEqual([sources[0], { ...sources[1], text: "后续原文更正", effective_trade_date: null }]);
    await wrapper.get(`[data-testid="source-up-${sources[1]!.source_id}"]`).trigger("click");
    expect(wrapper.emitted("update:sources")!.at(-1)![0]).toEqual([sources[1], sources[0]]);
    await wrapper.get(`[data-testid="source-remove-${sources[0]!.source_id}"]`).trigger("click");
    expect(wrapper.emitted("update:sources")!.at(-1)![0]).toEqual([sources[1]]);
    await wrapper.get('[data-testid="source-add"]').trigger("click");
    const added = wrapper.emitted("update:sources")!.at(-1)![0] as PreparationSource[];
    expect(added.slice(0, 2)).toEqual(sources); expect(added).toHaveLength(3);
    expect(new Set(added.map(source => source.source_id)).size).toBe(3);
    expect(added[2]!.text).toBe(""); expect(sources).toEqual(original);
    for (const button of wrapper.findAll('button[type="button"]')) expect(button.attributes("aria-label") || button.text()).toBeTruthy();
  });
  it("keeps separate uploaded files intact and does not synthesize their chronology", async () => {
    const { sources } = collectionReviewFixture(); const wrapper = batchForm(sources);
    const texts = ["  第一份文件\n完整内容  ", "第二份文件\n不同日期的计划"];
    const files = texts.map((text, index) => {
      const bytes = new TextEncoder().encode(text); const file = new File([bytes], `${index}.md`);
      Object.defineProperty(file, "arrayBuffer", { value: async () => bytes.slice().buffer }); return file;
    });
    const input = wrapper.get('input[type="file"]'); expect(input.attributes("multiple")).toBeDefined();
    Object.defineProperty(input.element, "files", { value: files, configurable: true });
    await input.trigger("change"); await flushPromises();
    const added = wrapper.emitted("update:sources")!.at(-1)![0] as PreparationSource[];
    expect(added.slice(0, sources.length)).toEqual(sources);
    expect(added.slice(sources.length).map(source => source.text)).toEqual(texts);
    expect(new Set(added.map(source => source.source_id)).size).toBe(4);
    for (const source of added.slice(sources.length)) {
      expect(source.available_at ?? null).toBeNull(); expect(source.effective_trade_date ?? null).toBeNull();
    }
  });
  it("discards a late batch file read after work disables editing", async () => {
    const { sources } = collectionReviewFixture(); const wrapper = batchForm(sources);
    let finish!: (bytes: ArrayBuffer) => void;
    const pending = new Promise<ArrayBuffer>(resolve => { finish = resolve; });
    const file = new File(["late"], "late.txt"); Object.defineProperty(file, "arrayBuffer", { value: () => pending });
    const input = wrapper.get('input[type="file"]'); Object.defineProperty(input.element, "files", { value: [file], configurable: true });
    await input.trigger("change"); await wrapper.setProps({ disabled: true });
    finish(new TextEncoder().encode("late complete source").buffer); await flushPromises();
    expect(wrapper.emitted("update:sources")).toBeUndefined();
    await wrapper.get("form").trigger("submit"); expect(wrapper.emitted("submit")).toBeUndefined();
  });
  it("preserves an unfinished source's entered dates and identity when importing another file", async () => {
    const source = { ...fresh().source, text: "" }, wrapper = batchForm([source]);
    const bytes = new TextEncoder().encode("A separate synthetic follow-up source.");
    const file = new File([bytes], "later.txt"); Object.defineProperty(file, "arrayBuffer", { value: async () => bytes.slice().buffer });
    const input = wrapper.get('input[type="file"]'); Object.defineProperty(input.element, "files", { value: [file], configurable: true });
    await input.trigger("change"); await flushPromises();
    const values = wrapper.emitted("update:sources")!.at(-1)![0] as PreparationSource[];
    expect(values).toHaveLength(2); expect(values[0]).toEqual(source);
    expect(values[1]!.text).toBe("A separate synthetic follow-up source.");
  });
  it.each([
    { count: 257, text: "synthetic", message: /256/ },
    { count: 20, text: "原".repeat(150000), message: /8\s*MiB|8388608|8\s*MB/ },
    { count: 10, text: "原".repeat(150000), message: /4\s*MiB|4194304|4\s*MB/ },
  ])("blocks collection count or encoded size overflow: $count sources", async ({ count, text, message }) => {
    const sources = Array.from({ length: count }, (_, index) => ({ ...fresh().source, source_id: `synthetic-${index}`, text }));
    const wrapper = batchForm(sources); await wrapper.get("form").trigger("submit");
    expect(wrapper.emitted("submit")).toBeUndefined(); expect(wrapper.get('[role="alert"]').text()).toMatch(message);
  });
  it("lists every source date and per-item attempt count and emits explicit selection", async () => {
    const { collection } = collectionReviewFixture(); collection.items[1]!.status = "FAILED"; collection.items[1]!.attemptCount = 3;
    const wrapper = mount(PlanPreparationProgress, { props: { preparation: null, collection, requestState: "READY", mutationState: "IDLE",
      canExtract: true, canCancel: false, canRecover: false, canRetryMutation: false } }); wrappers.push(wrapper);
    for (const item of collection.items) {
      const row = wrapper.get(`[data-testid="select-source-${item.sourceId}"]`);
      expect(row.text()).toContain(item.effectiveTradeDate); expect(row.text()).toContain(String(item.attemptCount));
    }
    expect(wrapper.text()).toContain("提取失败");
    await wrapper.get(`[data-testid="select-source-${collection.items[1]!.sourceId}"]`).trigger("click");
    expect(wrapper.emitted("selectSource")).toEqual([[collection.items[1]!.sourceId]]);
  });
  it("shows complete successive plans, inherited evidence, changes and holdings as comparison only", () => {
    const { wrapper, sources } = collectionPreview();
    for (const source of sources) {
      const section = wrapper.get(`[data-testid="collection-item-${source.source_id}"]`);
      expect(section.text()).toContain(source.text); expect(section.text()).toContain(source.available_at);
      expect(section.text()).toContain("New structure linked to prior signal");
    }
    const later = wrapper.get('[data-testid="collection-item-synthetic-later"]').text();
    expect(later).toContain("1000"); expect(later).toContain("1200"); expect(later).toContain("200");
    expect(later).toContain(sources[0]!.source_id); expect(later).toMatch(/对比|比较/); expect(later).toMatch(/不.*重置|不.*覆盖|不改变连续账户/);
    expect(wrapper.findAll('[data-testid="opening-account"]')).toHaveLength(1);
    expect(wrapper.get('[data-testid="opening-account"]').text()).toContain("500000");
    expect(wrapper.find('textarea[aria-label*="JSON"]').exists()).toBe(false);
    expect(wrapper.emitted("reviewCollection")).toBeUndefined();
  });
  it("requires an explicit whole-chain confirmation and resets it on a new revision", async () => {
    const { wrapper, collection } = collectionPreview();
    expect(wrapper.get('[data-testid="review-submit"]').attributes("disabled")).toBeDefined();
    await confirmCollection(wrapper); expect(wrapper.get('[data-testid="review-submit"]').attributes("disabled")).toBeUndefined();
    await wrapper.get("form").trigger("submit");
    expect(wrapper.emitted("reviewCollection")).toEqual([[{ evidence, unknownConfirmed: false }]]);
    await wrapper.setProps({ collection: { ...collection, revision: collection.revision + 1 } });
    expect((wrapper.get('[data-testid="review-confirmation"]').element as HTMLInputElement).checked).toBe(false);
    expect(wrapper.get('[data-testid="review-submit"]').attributes("disabled")).toBeDefined();
  });
  it.each(["missing-page", "unresolved", "dirty"])("blocks whole-chain approval while $0", async reason => {
    const value = collectionReviewFixture();
    if (reason === "missing-page") value.details.pop();
    if (reason === "unresolved") { value.details[1]!.validation = "UNRESOLVED"; value.details[1]!.candidate!.issues = ["UNRESOLVED_SCOPE"]; }
    const { wrapper } = collectionPreview(value); if (reason === "dirty") await wrapper.setProps({ sourceDirty: true });
    await confirmCollection(wrapper); expect(wrapper.get('[data-testid="review-submit"]').attributes("disabled")).toBeDefined();
    await wrapper.get("form").trigger("submit"); expect(wrapper.emitted("reviewCollection")).toBeUndefined();
  });
  it("does not require cash confirmation when reviewing source inventory", async () => {
    const value = collectionReviewFixture(); value.details[0]!.candidate!.openingAccount!.cash_fen = null;
    const { wrapper } = collectionPreview(value); await confirmCollection(wrapper);
    expect(wrapper.find('[data-testid="review-unknown-confirmation"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="opening-cash"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="review-submit"]').attributes("disabled")).toBeUndefined();
    await wrapper.get("form").trigger("submit");
    expect(wrapper.emitted("reviewCollection")![0]![0]).toEqual({ evidence, unknownConfirmed: false });
    expect(value.details[0]!.candidate!.openingAccount!.cash_fen).toBeNull();
  });
  it("accepts a source-bound empty account without inventing cash or a timestamp", async () => {
    const value = collectionReviewFixture(), first = value.details[0]!;
    const opening = first.candidate!.openingAccount!;
    opening.cash_fen = null; opening.snapshot_at = null; opening.lots = [];
    opening.inventory_quantity = { value: 0, start: 0, end: 1, excerpt: "0" };
    first.source.available_at = null;
    const { wrapper } = collectionPreview(value);
    await confirmCollection(wrapper);
    expect(wrapper.find('[data-testid="set-opening-cash"]').exists()).toBe(false);
    expect(wrapper.find('input[type="datetime-local"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="review-unknown-confirmation"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="review-submit"]').attributes("disabled")).toBeUndefined();
    await wrapper.get("form").trigger("submit");
    expect(wrapper.emitted("reviewCollection")![0]![0]).toEqual({ evidence, unknownConfirmed: false });
    expect(opening.cash_fen).toBeNull(); expect(opening.snapshot_at).toBeNull();
  });
  it("emits explicit initial supplements as an item correction without freezing its successors", async () => {
    const value = collectionReviewFixture(), original = fresh();
    if (original.candidate?.kind !== "EXTRACTION") throw new Error("fixture variant");
    const first = value.details[0]!;
    first.validation = "UNRESOLVED"; first.candidate!.validation = "UNRESOLVED";
    first.candidate!.mapping = structuredClone(original.candidate.mapping);
    first.candidate!.issues = [...original.candidate.issues]; value.collection.items[0]!.validation = "UNRESOLVED";
    const { wrapper } = collectionPreview(value); await wrapper.setProps({ canCorrect: true, canReview: false });
    const child = wrapper.getComponent(PlanPreparationReview);
    expect(child.get('[data-testid="review-submit"]').text()).toContain("确认此项修正");
    await confirmPreview(child);
    expect(child.get('[data-testid="review-submit"]').attributes("disabled")).toBeUndefined();
    await child.get("form").trigger("submit");
    const expected = buildPreparationReview(original, evidence, fixture.choices, true).review.mapping;
    expect(wrapper.emitted("correctItem")).toEqual([[{ sourceId: first.sourceId, evidence, changes: { mapping: expected } }]]);
    expect(wrapper.emitted("reviewCollection")).toBeUndefined();
    expect(value.details[1]!.candidateHash).toBe("2".repeat(64));
  });
  it("requires a fresh explicit account after an initial correction and preserves unknown versus zero", async () => {
    const value = collectionReviewFixture(), first = value.details[0]!, laterReview = value.details[1]!.candidate!.review!;
    first.candidate!.kind = "CORRECTED"; first.candidate!.openingAccount = null;
    first.candidate!.review = { ...structuredClone(laterReview), source_id: first.sourceId, source_hash: "a".repeat(64),
      available_at: first.source.available_at!, draft: first.candidate!.draft!, account_context: null, changes: [] };
    const { wrapper } = collectionPreview(value); await confirmCollection(wrapper);
    const button = wrapper.get('[data-testid="review-submit"]');
    expect(button.attributes("disabled")).toBeDefined();
    expect((labelledControl(wrapper, "账户快照时间").element as HTMLInputElement).value).toBe("");
    expect(wrapper.text()).toContain("无需填写现金金额");
    expect((labelledControl(wrapper, "实际持仓总量已知").element as HTMLInputElement).checked).toBe(false);
    await labelledControl(wrapper, "账户快照时间").setValue("2026-08-20T09:00:00");
    expect(button.attributes("disabled")).toBeDefined();
    await wrapper.get('[data-testid="review-unknown-confirmation"]').setValue(true);
    expect(button.attributes("disabled")).toBeUndefined(); await wrapper.get("form").trigger("submit");
    expect(wrapper.emitted("reviewCollection")![0]![0]).toEqual({ evidence, unknownConfirmed: true, account: {
      snapshot_at: "2026-08-20T09:00:00.000000+08:00", cash: { kind: "POSITION_LIMIT_ONLY" }, inventory_known: false,
      lots: [], opening_mark: null, evidence,
    } });
    await labelledControl(wrapper, "实际持仓总量已知").setValue(true);
    expect(button.attributes("disabled")).toBeUndefined(); await wrapper.get("form").trigger("submit");
    expect(wrapper.emitted("reviewCollection")!.at(-1)![0]).toMatchObject({ account: { cash: { kind: "POSITION_LIMIT_ONLY" }, inventory_known: true, lots: [] } });
  });
});
