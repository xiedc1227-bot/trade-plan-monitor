import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import type { PreparationView, PreparationFrozenView } from "../../src/api/generated-runtime-status";
import { createPreparationApi, type PreparationApi, type PreparationFrozenReceipt } from "../../src/api/preparations";
import { buildPreparationReview, inspectPreparationReview, validReviewCandidate } from "../../src/api/preparationReview";
import { usePlanPreparation } from "../../src/composables/usePlanPreparation";
import PlanPreparationReview from "../../src/components/backtests/PlanPreparationReview.vue";
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
async function confirmPreview(wrapper: VueWrapper) {
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
  it("preserves unknown cash separately from zero and requires an explicit unknown acknowledgement", () => {
    const value = fresh();
    if (value.candidate?.kind !== "EXTRACTION") throw new Error("fixture variant");
    value.candidate.openingAccount.cash_fen = null;
    value.candidate.issues.push("LOOP_ACCOUNT_FACT_REQUIRED: opening_account.cash_fen");
    expect(inspectPreparationReview(value).unknownFacts).toContain("opening_account.cash_fen");
    expect(() => buildPreparationReview(value, evidence, fixture.choices, false)).toThrow();
    expect(buildPreparationReview(value, evidence, fixture.choices, true).review.account).toBeUndefined();
    value.candidate.openingAccount.cash_fen = { value: 0, start: 0, end: 1, excerpt: value.source.text[0]! };
    value.candidate.issues = value.candidate.issues.filter(issue => !issue.includes("cash_fen"));
    expect(inspectPreparationReview(value).unknownFacts).not.toContain("opening_account.cash_fen");
  });
  it("blocks missing chronology, missing technical parameters and unresolved source clauses", () => {
    const time = fresh(); time.source.available_at = null;
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
  it("keeps default legacy creation and preparation acquisition inert until an explicit choice", async () => {
    const { wrapper, api } = await page();
    expect(wrapper.findComponent({ name: "BacktestRunForm" }).exists()).toBe(true);
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
    value.candidate.openingAccount.cash_fen = null;
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
