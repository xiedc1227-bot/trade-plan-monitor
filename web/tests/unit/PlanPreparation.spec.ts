import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h, isReadonly } from "vue";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";

import type { CollectionItemView, CollectionItemsPage, CollectionPreparationView, PreparationView } from "../../src/api/generated-runtime-status";
import { createPreparationApi, type PreparationApi, type PreparationReceipt } from "../../src/api/preparations";
import { ApiClientError } from "../../src/api/transport";
import { usePlanPreparation } from "../../src/composables/usePlanPreparation";
import PlanPreparationSourceForm from "../../src/components/backtests/PlanPreparationSourceForm.vue";
import PlanPreparationProgress from "../../src/components/backtests/PlanPreparationProgress.vue";

const BASE = "/api/v1/backtest-preparations";
const SOURCE = { source_id: "source-1", text: "完整计划原文", effective_trade_date: "2026-09-24" };
const COLLECTION_SOURCES = ["初始计划", "次日跟踪", "第三日跟踪", "第四日跟踪"].map((text, index) => ({
  source_id: `daily-${index + 1}`, text: `  ${text}\n保留原文边界  `,
  available_at: `2026-10-${12 + index}T08:30:00+08:00`, effective_trade_date: `2026-10-${12 + index}`,
}));
const wrappers: VueWrapper[] = [];
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.useRealTimers(); vi.restoreAllMocks(); });

it("opens an exact existing preparation without creating or extracting another source", async () => {
  const api = mockApi(); const { state } = controller(api, null); await flushPromises();
  vi.mocked(api.get).mockResolvedValue(result(preparation({ preparationId: "timeline-head" })));
  await state.open("timeline-head");
  expect(state.preparationId.value).toBe("timeline-head");
  expect(state.preparation.value?.preparationId).toBe("timeline-head");
  expect(api.get).toHaveBeenCalledWith("timeline-head", expect.objectContaining({ signal: expect.any(AbortSignal) }));
  expect(api.create).not.toHaveBeenCalled(); expect(api.extract).not.toHaveBeenCalled();
});

it("does not replace an unsaved source or a pending mutation when opening another timeline", async () => {
  const api = mockApi(); const { state } = controller(api); await flushPromises();
  state.updateSource({ ...SOURCE, text: "未保存的更新" }); await state.open("other-head");
  expect(state.preparationId.value).toBe("prep-1"); expect(state.draft.value.text).toBe("未保存的更新");
  expect(api.get).toHaveBeenCalledTimes(1);
});

it("recovers an initial unavailable progress read without repeating extraction", async () => {
  vi.useFakeTimers(); const api = mockApi();
  vi.mocked(api.get).mockRejectedValueOnce(new ApiClientError({ code: "SERVICE_UNAVAILABLE", status: 503, message: "Starting" }));
  const { state } = controller(api); await flushPromises();
  expect(state.isBusy.value).toBe(true);
  await vi.advanceTimersByTimeAsync(2000); await flushPromises();
  expect(state.requestState.value).toBe("READY"); expect(state.isBusy.value).toBe(false);
  expect(api.get).toHaveBeenCalledTimes(2); expect(api.extract).not.toHaveBeenCalled();
});
it("bounds unavailable initial reads and cancels their timer on unmount", async () => {
  vi.useFakeTimers(); const api = mockApi();
  vi.mocked(api.get).mockRejectedValue(new ApiClientError({ code: "SERVICE_UNAVAILABLE", status: 503, message: "Unavailable" }));
  const { state, wrapper } = controller(api); await flushPromises();
  await vi.advanceTimersByTimeAsync(20_000); await flushPromises();
  expect(api.get).toHaveBeenCalledTimes(4); expect(state.requestState.value).toBe("FAILED");
  wrapper.unmount(); await vi.advanceTimersByTimeAsync(20_000);
  expect(api.get).toHaveBeenCalledTimes(4); expect(api.extract).not.toHaveBeenCalled();
});

function result(body = preparation(), status: 200 | 201 | 202 = 200): PreparationReceipt {
  return { body, status, retryAfterSeconds: status === 202 ? 2 : null };
}
function mockApi(): PreparationApi {
  return {
    review: vi.fn<PreparationApi["review"]>(),
    create: vi.fn<PreparationApi["create"]>().mockResolvedValue(result(preparation(), 201)),
    get: vi.fn<PreparationApi["get"]>().mockResolvedValue(result()),
    edit: vi.fn<PreparationApi["edit"]>().mockResolvedValue(result()),
    extract: vi.fn<PreparationApi["extract"]>().mockResolvedValue(result(preparation({ status: "EXTRACTING", workPhase: "CALLING", generation: "g1", revision: 2 }), 202)),
    cancel: vi.fn<PreparationApi["cancel"]>().mockResolvedValue(result(preparation({ status: "CANCEL_REQUESTED", workPhase: "CALLING", generation: "g1", revision: 3 }), 202)),
    recover: vi.fn<PreparationApi["recover"]>().mockResolvedValue(result(preparation({ status: "CANCELLED", workPhase: "ENDED", generation: "g1", revision: 4 }))),
  };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(accept => { resolve = accept; });
  return { promise, resolve };
}
function controller(api = mockApi(), initialPreparationId: string | null = "prep-1") {
  let state!: ReturnType<typeof usePlanPreparation>;
  let sequence = 0;
  const wrapper = mount(defineComponent({ setup() {
    state = usePlanPreparation({ api, initialPreparationId, createId: () => `local-${++sequence}` });
    return () => h("div");
  } }));
  wrappers.push(wrapper);
  return { state, wrapper, api };
}

function preparation(overrides: Partial<PreparationView> = {}): PreparationView {
  return {
    preparationId: "prep-1", revision: 1, sourceRevision: 1, candidateRevision: 0,
    reviewRevision: 0, source: SOURCE, sourceEditPending: false, status: "DRAFT",
    attempts: [], candidate: null, workPhase: null, generation: null, ...overrides,
  };
}

function receipt(body = preparation(), status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status, headers: { "Cache-Control": "no-store", Location: `${BASE}/${body.preparationId}`,
      ...(status === 202 ? { "Retry-After": "2" } : {}), ...headers },
  });
}

function collectionDetails(): CollectionItemView[] {
  return COLLECTION_SOURCES.map((source, index) => ({
    sourceId: source.source_id, sourceRevision: 1, candidateRevision: 0, baseHash: null,
    candidateHash: null, evidenceHash: null, validation: null, attemptCount: 0,
    status: index === 0 ? "DRAFT" : "WAITING", effectiveTradeDate: source.effective_trade_date,
    source: { ...source }, attempts: [], candidate: null,
  }));
}
function collection(overrides: Partial<CollectionPreparationView> = {}): CollectionPreparationView {
  return {
    schemaVersion: "backtest-preparation-v2", preparationId: "prep-1", revision: 1,
    reviewRevision: 0, itemCount: 4, items: collectionDetails().map(({ source, attempts, candidate, ...summary }) => summary),
    status: "DRAFT", workPhase: null, generation: null, currentSourceId: null, frozen: null, ...overrides,
  };
}
function collectionReceipt(body = collection(), status: 200 | 201 | 202 = 200): PreparationReceipt {
  return { body, status, retryAfterSeconds: status === 202 ? 2 : null };
}
function itemPage(items = collectionDetails(), overrides: Partial<CollectionItemsPage> = {}): CollectionItemsPage {
  return { preparationId: "prep-1", revision: 1, total: 4, offset: 0, limit: 20, nextOffset: null, items, ...overrides };
}
function collectionResponse(body: CollectionPreparationView | CollectionItemsPage = collection(), status = 200) {
  return new Response(JSON.stringify(body), { status, headers: {
    "Cache-Control": "no-store", Location: `${BASE}/${body.preparationId}`,
    ...(status === 202 ? { "Retry-After": "2" } : {}),
  } });
}
function collectionApi() {
  return {
    ...mockApi(),
    create: vi.fn<PreparationApi["create"]>().mockResolvedValue(collectionReceipt(collection(), 201)),
    get: vi.fn<PreparationApi["get"]>().mockResolvedValue(collectionReceipt()),
    items: vi.fn<NonNullable<PreparationApi["items"]>>().mockResolvedValue(itemPage()),
    reviewCollection: vi.fn<NonNullable<PreparationApi["reviewCollection"]>>(),
    correct: vi.fn<NonNullable<PreparationApi["correct"]>>(),
  };
}
function reviewableCollection() {
  const fixture = JSON.parse(readFileSync("tests/fixtures/plan-preparation-review.json", "utf8")) as {
    candidate: PreparationView; reviewed: PreparationView;
  };
  if (fixture.candidate.candidate?.kind !== "EXTRACTION" || fixture.reviewed.candidate?.kind !== "FROZEN") throw new Error("fixture variant");
  const candidate = fixture.candidate.candidate;
  const reviewed = fixture.reviewed.candidate.frozen;
  const details = collectionDetails().map((item, index): CollectionItemView => {
    const candidateHash = String(index + 1).repeat(64); const evidenceHash = String(index + 5).repeat(64);
    const source = { ...fixture.candidate.source, source_id: item.sourceId,
      available_at: item.source.available_at ?? null, effective_trade_date: item.effectiveTradeDate };
    return { ...item, source, candidateRevision: index + 2, candidateHash, evidenceHash,
      baseHash: index === 0 ? null : String(index).repeat(64), validation: "VALID", status: "CANDIDATE",
      candidate: { kind: index === 0 ? "INITIAL" : "MATERIALIZED", candidateHash, evidenceHash, validation: "VALID", issues: [],
        draft: structuredClone(candidate.draft), mapping: structuredClone(reviewed.mapping),
        openingAccount: index === 0 ? structuredClone(candidate.openingAccount) : null,
        review: { source_id: item.sourceId, source_hash: "a".repeat(64), available_at: source.available_at!,
          draft: structuredClone(candidate.draft), bindings: reviewed.mapping.bindings.map(binding => ({
            binding: structuredClone(binding), candidate_content_hash: reviewed.mapping.candidate_content_hash,
            clauses: structuredClone(reviewed.mapping.clauses.filter(clause => binding.clause_ids.includes(clause.clause_id))),
            original_path: binding.path, path: binding.path, source_hash: "a".repeat(64), source_id: item.sourceId,
            supplement: structuredClone(reviewed.mapping.supplements.find(supplement => supplement.supplement_id === binding.supplement_id) ?? null),
          })), changes: [], issues: [], account_context: null },
      },
    };
  });
  const root = collection({ status: "CANDIDATE", revision: 9,
    items: details.map(({ source, attempts, candidate, ...summary }) => summary) });
  return { details, root, account: reviewed.account };
}

describe("ordered collection preparation transport", () => {
  it("creates all four raw sources in one explicitly versioned request", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(collectionResponse(collection(), 201));
    const command = { input: { schema_version: "backtest-preparation-v2" as const, preparation_id: "prep-1", sources: COLLECTION_SOURCES } };
    const response = await createPreparationApi(fetcher).create(command, "batch-1");
    expect(response.body).toEqual(collection());
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(JSON.parse(String(fetcher.mock.calls[0]![1]?.body))).toEqual(command);
  });

  it.each(["duplicate", "empty", "count", "encoded-size"])("rejects invalid collection %s before fetch", async kind => {
    const fetcher = vi.fn<typeof fetch>();
    const sources = kind === "duplicate" ? [COLLECTION_SOURCES[0]!, COLLECTION_SOURCES[0]!] :
      kind === "empty" ? [] : kind === "count" ? Array.from({ length: 257 }, (_, i) => ({ source_id: `s-${i}`, text: "x" })) :
      Array.from({ length: 10 }, (_, i) => ({ source_id: `s-${i}`, text: "汉".repeat(150_000) }));
    await expect(createPreparationApi(fetcher).create({ input: {
      schema_version: "backtest-preparation-v2", preparation_id: "prep-1", sources,
    } }, "batch-1")).rejects.toMatchObject({ code: "VALIDATION_ERROR" });
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("accepts adaptive item pages and binds the read to an exact revision", async () => {
    const page = itemPage(collectionDetails().slice(0, 1), { nextOffset: 1 });
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(collectionResponse(page));
    const api = createPreparationApi(fetcher);
    expect(await api.items!("prep-1", { expectedRevision: 1, offset: 0, limit: 20 })).toEqual(page);
    const [url, init] = fetcher.mock.calls[0]!;
    const parsed = new URL(String(url), "http://localhost");
    expect(parsed.pathname).toBe(`${BASE}/prep-1/items`);
    expect(Object.fromEntries(parsed.searchParams)).toEqual({ expectedRevision: "1", offset: "0", limit: "20" });
    expect(init).toMatchObject({ method: "GET", credentials: "same-origin", redirect: "error" });
  });

  it.each([
    { preparationId: "other" }, { revision: 2 }, { offset: 1 }, { total: 257 },
    { nextOffset: 0 }, { nextOffset: 3 }, { nextOffset: null },
  ])("rejects mismatched or nonadvancing item pages: %o", async overrides => {
    const page = itemPage(collectionDetails().slice(0, 1), { nextOffset: 1, ...overrides });
    const api = createPreparationApi(vi.fn<typeof fetch>().mockResolvedValue(collectionResponse(page)));
    await expect(api.items!("prep-1", { expectedRevision: 1, offset: 0, limit: 20 })).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("rejects malformed detail source binding and duplicate item identifiers", async () => {
    const details = collectionDetails();
    details[0]!.source.source_id = "forged-source";
    const api = createPreparationApi(vi.fn<typeof fetch>().mockResolvedValue(collectionResponse(itemPage(details))));
    await expect(api.items!("prep-1", { expectedRevision: 1 })).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    const duplicate = collection(); duplicate.items[1] = { ...duplicate.items[0]! };
    await expect(createPreparationApi(vi.fn<typeof fetch>().mockResolvedValue(collectionResponse(duplicate))).get("prep-1"))
      .rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("accepts actual INITIAL and MATERIALIZED projection evidence through the transport", async () => {
    const { details } = reviewableCollection();
    const page = itemPage(details, { revision: 9 });
    const api = createPreparationApi(vi.fn<typeof fetch>().mockResolvedValue(collectionResponse(page)));
    expect(await api.items!("prep-1", { expectedRevision: 9 })).toEqual(page);
  });

  it("rejects a materialized candidate whose review belongs to another source", async () => {
    const { details } = reviewableCollection();
    details[1]!.candidate!.review!.source_id = "unrelated-source";
    const api = createPreparationApi(vi.fn<typeof fetch>().mockResolvedValue(collectionResponse(itemPage(details, { revision: 9 }))));
    const rejection = await api.items!("prep-1", { expectedRevision: 9 }).then(() => null, error => error.code);
    expect(rejection).toBe("INVALID_RESPONSE");
  });
});

describe("one ordered collection preparation controller", () => {
  it("creates a collection only on explicit submission and keeps one preparation", async () => {
    const api = collectionApi(); const { state } = controller(api, null);
    api.create.mockImplementation(async command => {
      const created = collection({ preparationId: command.input.preparation_id });
      api.items.mockResolvedValue(itemPage(collectionDetails(), { preparationId: created.preparationId }));
      return collectionReceipt(created, 201);
    });
    await flushPromises(); state.updateSources(COLLECTION_SOURCES);
    expect(api.create).not.toHaveBeenCalled();
    await state.submitSources(); await flushPromises();
    expect(api.create).toHaveBeenCalledTimes(1);
    expect(api.create.mock.calls[0]![0].input).toMatchObject({ schema_version: "backtest-preparation-v2", sources: COLLECTION_SOURCES });
    expect(state.collection.value?.itemCount).toBe(4);
    expect(state.preparation.value).toBeNull();
    expect(state.items.value.map(item => item.sourceId)).toEqual(COLLECTION_SOURCES.map(source => source.source_id));
    await state.submitSources();
    expect(api.create).toHaveBeenCalledTimes(1);
    expect(isReadonly(state.sources)).toBe(true);
  });

  it("loads every adaptive page at one revision before making the chain reviewable", async () => {
    const api = collectionApi(); const last = deferred<CollectionItemsPage>();
    api.items.mockResolvedValueOnce(itemPage(collectionDetails().slice(0, 1), { nextOffset: 1 }))
      .mockImplementationOnce(() => last.promise);
    const { state } = controller(api); await flushPromises();
    expect(api.items.mock.calls.map(([, query]) => [query.expectedRevision, query.offset ?? 0])).toEqual([[1, 0], [1, 1]]);
    expect(state.canReview.value).toBe(false);
    last.resolve(itemPage(collectionDetails().slice(1), { offset: 1 })); await flushPromises();
    expect(state.items.value.map(item => item.sourceId)).toEqual(COLLECTION_SOURCES.map(source => source.source_id));
  });

  it.each(["reorder", "revision", "summary"])("does not mix item details that disagree with root %s", async kind => {
    const api = collectionApi(); const details = collectionDetails();
    if (kind === "reorder") details.reverse();
    if (kind === "summary") details[1]!.sourceRevision = 2;
    api.items.mockResolvedValue(itemPage(details, kind === "revision" ? { revision: 2 } : {}));
    const { state } = controller(api); await flushPromises();
    expect(state.items.value).toHaveLength(0);
    expect(state.canReview.value).toBe(false);
    expect(state.errorMessage.value).toBeTruthy();
  });

  it("retains an unsaved selected source while polling newer server revisions", async () => {
    const api = collectionApi(); const { state } = controller(api); await flushPromises();
    state.selectSource("daily-2");
    state.updateSource({ ...state.draft.value, text: "  尚未提交的次日修订  " });
    api.get.mockResolvedValue(collectionReceipt(collection({ revision: 2 })));
    api.items.mockResolvedValue(itemPage(collectionDetails(), { revision: 2 }));
    await state.refresh(); await flushPromises();
    expect(state.selectedSourceId.value).toBe("daily-2");
    expect(state.draft.value.text).toBe("  尚未提交的次日修订  ");
    expect(state.sourceDirty.value).toBe(true);
    expect(state.canExtract.value).toBe(false);
  });

  it.each([0, 2])("binds invalidated source %i to the current validated predecessor", async index => {
    const api = collectionApi(); const { details } = reviewableCollection();
    const fresh = collectionDetails();
    for (let offset = index; offset < details.length; offset++) details[offset] = {
      ...fresh[offset]!, status: offset === index ? "DRAFT" : "WAITING", sourceRevision: 2,
    };
    const root = collection({ revision: 10, items: details.map(({ source, attempts, candidate, ...summary }) => summary) });
    api.get.mockResolvedValue(collectionReceipt(root));
    api.items.mockResolvedValue(itemPage(details, { revision: 10 }));
    vi.mocked(api.extract).mockRejectedValue(new ApiClientError({ code: "NETWORK_ERROR", status: 0, message: "lost receipt" }));
    const { state } = controller(api); await flushPromises();
    expect(state.canExtract.value).toBe(true);
    await state.extract();
    const original = vi.mocked(api.extract).mock.calls[0]!;
    expect(original[1]).toEqual({ schemaVersion: "backtest-preparation-v2", expectedRevision: 10,
      sourceId: `daily-${index + 1}`, expectedSourceRevision: 2,
      expectedBaseHash: index === 0 ? null : "2".repeat(64) });
    await state.retryMutation();
    expect(vi.mocked(api.extract).mock.calls[1]!.slice(0, 3)).toEqual(original.slice(0, 3));
  });

  it("persists an exact reorder with the current root revision", async () => {
    const api = collectionApi(); const { state } = controller(api); await flushPromises();
    await state.reorderSources(["daily-1", "daily-3", "daily-2", "daily-4"]);
    expect(api.edit).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api.edit).mock.calls[0]![1]).toEqual({ schemaVersion: "backtest-preparation-v2", expectedRevision: 1,
      sourceOrder: ["daily-1", "daily-3", "daily-2", "daily-4"] });
    expect(api.create).not.toHaveBeenCalled();
  });

  it("retries an uncertain batch create with the original key and unchanged source bytes", async () => {
    const api = collectionApi();
    api.create.mockRejectedValueOnce(new ApiClientError({ code: "NETWORK_ERROR", status: 0, message: "disconnected" }))
      .mockResolvedValueOnce(collectionReceipt(collection(), 201));
    const { state } = controller(api, null); await flushPromises();
    state.updateSources(COLLECTION_SOURCES); await state.submitSources();
    expect(state.mutationState.value).toBe("UNCERTAIN");
    state.updateSources([{ source_id: "replacement", text: "不得替换未决请求" }]);
    await state.retryMutation(); await flushPromises();
    expect(api.create).toHaveBeenCalledTimes(2);
    expect(api.create.mock.calls[1]!.slice(0, 2)).toEqual(api.create.mock.calls[0]!.slice(0, 2));
    expect(api.create.mock.calls[1]![0].input.sources).toEqual(COLLECTION_SOURCES);
  });

  it.each(["UNKNOWN", "CALLING"] as const)("locks editing and review while collection work remains %s", async workPhase => {
    const api = collectionApi();
    api.get.mockResolvedValue(collectionReceipt(collection({ status: "CANCEL_REQUESTED", workPhase, generation: "g1", currentSourceId: "daily-2" }), 202));
    const { state } = controller(api); await flushPromises();
    expect(state.isBusy.value).toBe(true);
    expect(state.canSubmitSource.value).toBe(false);
    expect(state.canExtract.value).toBe(false);
    expect(state.canReview.value).toBe(false);
    expect(state.canRecover.value).toBe(workPhase === "UNKNOWN");
    await state.reorderSources(["daily-4", "daily-3", "daily-2", "daily-1"]);
    expect(api.edit).not.toHaveBeenCalled();
  });

  it("aborts and discards an item page arriving after unmount", async () => {
    const api = collectionApi(); const late = deferred<CollectionItemsPage>();
    api.items.mockImplementation(() => late.promise);
    const { state, wrapper } = controller(api); await flushPromises();
    expect(api.items).toHaveBeenCalledTimes(1);
    const signal = api.items.mock.calls[0]![2]?.signal;
    wrapper.unmount();
    expect(signal?.aborted).toBe(true);
    late.resolve(itemPage()); await flushPromises();
    expect(state.items.value).toHaveLength(0);
  });

  it("discards a late old revision after visibility resumes a newer read", async () => {
    const api = collectionApi(); const oldPage = deferred<CollectionItemsPage>();
    api.get.mockResolvedValueOnce(collectionReceipt(collection({ status: "EXTRACTING", workPhase: "CALLING", generation: "g1", currentSourceId: "daily-1" }), 202))
      .mockResolvedValueOnce(collectionReceipt(collection({ revision: 2 })));
    api.items.mockImplementationOnce(() => oldPage.promise).mockResolvedValueOnce(itemPage(collectionDetails(), { revision: 2 }));
    const { state } = controller(api); await flushPromises();
    const visibility = vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    document.dispatchEvent(new Event("visibilitychange"));
    expect(api.items.mock.calls[0]![2]?.signal?.aborted).toBe(true);
    visibility.mockReturnValue(false); document.dispatchEvent(new Event("visibilitychange")); await flushPromises();
    expect(state.collection.value?.revision).toBe(2);
    oldPage.resolve(itemPage()); await flushPromises();
    expect(state.collection.value?.revision).toBe(2);
    expect(state.items.value.map(item => item.sourceId)).toEqual(COLLECTION_SOURCES.map(source => source.source_id));
    expect(state.errorMessage.value).toBeNull();
  });

  it("requires every ordered detail and emits exact source, candidate, evidence and predecessor bindings", async () => {
    const { root, details } = reviewableCollection(); const api = collectionApi();
    api.get.mockResolvedValue(collectionReceipt(root));
    const second = deferred<CollectionItemsPage>();
    api.items.mockResolvedValueOnce(itemPage(details.slice(0, 2), { revision: 9, nextOffset: 2 })).mockImplementationOnce(() => second.promise);
    const { state } = controller(api); await flushPromises();
    await state.reviewCollection("逐份核对全部计划及期初账户", true);
    expect(api.reviewCollection).not.toHaveBeenCalled();
    second.resolve(itemPage(details.slice(2), { revision: 9, offset: 2 })); await flushPromises();
    expect(state.canReview.value).toBe(true);
    api.reviewCollection.mockRejectedValue(new ApiClientError({ code: "NETWORK_ERROR", status: 0, message: "lost receipt" }));
    await state.reviewCollection("逐份核对全部计划及期初账户", true);
    expect(api.reviewCollection).toHaveBeenCalledTimes(1);
    expect(api.reviewCollection.mock.calls[0]![1]).toEqual({ schemaVersion: "backtest-preparation-v2", kind: "CHAIN_REVIEW", review: {
      confirmed: true, evidence: "逐份核对全部计划及期初账户", expected_revision: 9,
      items: details.map(item => ({ source_id: item.sourceId, source_revision: item.sourceRevision,
        candidate_revision: item.candidateRevision, candidate_hash: item.candidateHash, evidence_hash: item.evidenceHash, base_hash: item.baseHash })),
    } });
    await state.retryMutation();
    expect(api.reviewCollection.mock.calls[1]!.slice(0, 3)).toEqual(api.reviewCollection.mock.calls[0]!.slice(0, 3));
  });

  it("never reviews a chain with one unresolved source", async () => {
    const { root, details } = reviewableCollection(); const api = collectionApi();
    root.items[2]!.validation = "UNRESOLVED"; details[2]!.validation = "UNRESOLVED";
    details[2]!.candidate!.validation = "UNRESOLVED"; details[2]!.candidate!.issues = ["Ambiguous daily follow-up"];
    api.get.mockResolvedValue(collectionReceipt(root)); api.items.mockResolvedValue(itemPage(details, { revision: 9 }));
    const { state } = controller(api); await flushPromises();
    expect(state.canReview.value).toBe(false);
    await state.reviewCollection("不能跳过未决来源", true);
    expect(api.reviewCollection).not.toHaveBeenCalled();
  });

  it("freezes an explicit account inside an uncertain chain-review intent", async () => {
    const { root, details, account } = reviewableCollection(); const api = collectionApi();
    api.get.mockResolvedValue(collectionReceipt(root)); api.items.mockResolvedValue(itemPage(details, { revision: 9 }));
    api.reviewCollection.mockRejectedValue(new ApiClientError({ code: "NETWORK_ERROR", status: 0, message: "lost receipt" }));
    const { state } = controller(api); await flushPromises();
    await state.reviewCollection("明确核对人工期初账户", true, account);
    const original = structuredClone(api.reviewCollection.mock.calls[0]![1]);
    account.evidence = "后来修改的账户，不属于原请求";
    if (account.cash.kind === "KNOWN") account.cash.balance_fen += 1;
    await state.retryMutation();
    expect(api.reviewCollection).toHaveBeenCalledTimes(2);
    expect(api.reviewCollection.mock.calls[1]![1]).toEqual(original);
    expect(api.reviewCollection.mock.calls[1]![2]).toBe(api.reviewCollection.mock.calls[0]![2]);
  });

  it("invalidates complete old details while newer revision pages are pending", async () => {
    const { root, details } = reviewableCollection(); const api = collectionApi();
    api.get.mockResolvedValueOnce(collectionReceipt(root)).mockResolvedValueOnce(collectionReceipt({ ...root, revision: 10 }));
    const next = deferred<CollectionItemsPage>();
    api.items.mockResolvedValueOnce(itemPage(details, { revision: 9 })).mockImplementationOnce(() => next.promise);
    const { state } = controller(api); await flushPromises();
    expect(state.canReview.value).toBe(true);
    const refresh = state.refresh(); await flushPromises();
    expect(state.canReview.value).toBe(false);
    await state.reviewCollection("不得审核旧修订", true);
    expect(api.reviewCollection).not.toHaveBeenCalled();
    next.resolve(itemPage(details, { revision: 10 })); await refresh; await flushPromises();
    expect(state.collection.value?.revision).toBe(10);
    expect(state.canReview.value).toBe(true);
  });
});

describe("one-source preparation transport", () => {
  it("accepts the published confirmation summary without rejecting a completed candidate", async () => {
    const fixture = JSON.parse(readFileSync("tests/fixtures/plan-preparation-review.json", "utf8")) as { candidate: PreparationView };
    const body = fixture.candidate;
    body.candidate!.confirmationSummary = { automaticFacts: ["原文明示"], questions: [{ questionId: "q1", category: "SOURCE", message: "待核对", excerpts: ["原文"] }], processingIssues: [] };
    const api = createPreparationApi(vi.fn<typeof fetch>().mockResolvedValue(receipt(body)));
    expect((await api.get(body.preparationId)).body.status).toBe("CANDIDATE");
  });

  it("accepts bounded correction diagnostics on a failed attempt", async () => {
    const body = preparation({ status: "FAILED", attempts: [{
      attempt_id: "a1", source_revision: 1, source_hash: "a".repeat(64), status: "FAILED",
      started_at: "2026-09-24T09:00:00+08:00", finished_at: "2026-09-24T09:00:01+08:00", error_code: "MAPPING_INVALID", retryable: true,
      repair_feedback: ["需纠正映射"], repair_context_json: "{}",
    }] });
    const api = createPreparationApi(vi.fn<typeof fetch>().mockResolvedValue(receipt(body)));
    expect((await api.get(body.preparationId)).body.status).toBe("FAILED");
  });

  it.each([
    { automaticFacts: [1], questions: [], processingIssues: [] },
    { automaticFacts: [], questions: [{ questionId: "q", category: "SOURCE", message: 3 }], processingIssues: [] },
    { automaticFacts: [], questions: [], processingIssues: [], privateOwner: "not-public" },
  ])("rejects malformed confirmation summaries: %j", async summary => {
    const fixture = JSON.parse(readFileSync("tests/fixtures/plan-preparation-review.json", "utf8"));
    fixture.candidate.candidate.confirmationSummary = summary;
    const api = createPreparationApi(vi.fn<typeof fetch>().mockResolvedValue(receipt(fixture.candidate)));
    await expect(api.get(fixture.candidate.preparationId)).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("sends one embedded source, revision and stable mutation key without following redirects", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(receipt(preparation(), 201));
    const api = createPreparationApi(fetcher);
    const signal = new AbortController().signal;
    const command = { input: { preparation_id: "prep-1", sources: [SOURCE] } };
    const result = await api.create(command, "intent-1", { signal });
    expect(result.status).toBe(201);
    const [url, init] = fetcher.mock.calls[0]!;
    expect(url).toBe(BASE);
    expect(init).toMatchObject({ method: "POST", credentials: "same-origin", redirect: "error", signal });
    expect(new Headers(init?.headers).get("Idempotency-Key")).toBe("intent-1");
    expect(JSON.parse(String(init?.body))).toEqual(command);
  });

  it.each([
    { revision: Number.MAX_SAFE_INTEGER + 1 }, { sourceRevision: 0 }, { attempts: [{ source_revision: 1 }] },
    { preparationId: "other" }, { workPhase: "CALLING", generation: null }, { privateOwner: "hidden" },
  ])("rejects malformed progress: %o", async (override) => {
    const api = createPreparationApi(vi.fn<typeof fetch>().mockResolvedValue(receipt(preparation(override as Partial<PreparationView>))));
    await expect(api.get("prep-1")).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it.each([
    { Location: "https://example.com/redirect" }, { "Cache-Control": "public" }, { "Retry-After": "-1" },
  ])("rejects invalid success metadata: %o", async (headers) => {
    const api = createPreparationApi(vi.fn<typeof fetch>().mockResolvedValue(receipt(preparation(), 200, headers)));
    await expect(api.get("prep-1")).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("rejects a second source and an unsafe route before contacting the server", async () => {
    const fetcher = vi.fn<typeof fetch>();
    const api = createPreparationApi(fetcher);
    await expect(api.create({ input: { preparation_id: "p1", sources: [SOURCE, SOURCE] } }, "key-1")).rejects.toMatchObject({ code: "VALIDATION_ERROR" });
    await expect(api.get("../private")).rejects.toMatchObject({ code: "VALIDATION_ERROR" });
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("supports actual extraction, source-edit and cancellation receipts", async () => {
    const fetcher = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(receipt(preparation({ status: "EXTRACTING", workPhase: "CALLING", generation: "g1" }), 202))
      .mockResolvedValueOnce(receipt(preparation({ revision: 2 }), 200))
      .mockResolvedValueOnce(receipt(preparation({ status: "CANCEL_REQUESTED", workPhase: "CALLING", generation: "g1" }), 202))
      .mockResolvedValueOnce(receipt(preparation({ status: "CANCELLED", workPhase: "ENDED", generation: "g1" }), 200));
    const api = createPreparationApi(fetcher);
    expect((await api.extract("prep-1", { expectedRevision: 1 }, "extract-1")).retryAfterSeconds).toBe(2);
    await api.edit("prep-1", { expectedRevision: 1, source: SOURCE }, "edit-1");
    expect((await api.cancel("prep-1", { expectedRevision: 2 }, "cancel-1")).status).toBe(202);
    expect((await api.cancel("prep-1", { expectedRevision: 2 }, "cancel-1")).status).toBe(200);
    expect(fetcher.mock.calls.map(([url, init]) => [url, init?.method])).toEqual([
      [`${BASE}/prep-1/extractions`, "POST"], [`${BASE}/prep-1/source`, "PUT"],
      [`${BASE}/prep-1/cancellations`, "POST"], [`${BASE}/prep-1/cancellations`, "POST"],
    ]);
  });
});

describe("one preparation controller", () => {
  it("retries temporary detail reads after the summary has already reached candidate", async () => {
    vi.useFakeTimers();
    const { root: value, details } = reviewableCollection();
    const api = collectionApi();
    vi.mocked(api.get).mockResolvedValue(collectionReceipt(value));
    vi.mocked(api.items!).mockRejectedValueOnce(new ApiClientError({ code: "SERVICE_UNAVAILABLE", status: 503, message: "busy" }))
      .mockResolvedValue(itemPage(details, { revision: value.revision }));
    const { state } = controller(api); await flushPromises();
    expect(state.canReview.value).toBe(false);
    await vi.advanceTimersByTimeAsync(2000); await flushPromises();
    expect(state.items.value).toHaveLength(4);
    expect(state.errorMessage.value).toBeNull();
    expect(api.extract).not.toHaveBeenCalled();
  });

  it("bounds detail recovery even when every summary read succeeds", async () => {
    vi.useFakeTimers();
    const { root } = reviewableCollection();
    const api = collectionApi();
    vi.mocked(api.get).mockResolvedValue(collectionReceipt(root));
    vi.mocked(api.items!).mockRejectedValue(new ApiClientError({ code: "SERVICE_UNAVAILABLE", status: 503, message: "busy" }));
    const { state, wrapper } = controller(api); await flushPromises();
    await vi.advanceTimersByTimeAsync(20_000); await flushPromises();
    expect(api.get).toHaveBeenCalledTimes(4);
    expect(api.items).toHaveBeenCalledTimes(4);
    expect(state.canReview.value).toBe(false);
    expect(state.errorMessage.value).toContain("未能读取最新进度");
    wrapper.unmount(); await vi.advanceTimersByTimeAsync(20_000);
    expect(api.get).toHaveBeenCalledTimes(4);
    expect(api.extract).not.toHaveBeenCalled();
  });

  it("creates only on explicit intent and keeps one source editable after validation rejection", async () => {
    const { api, state } = controller(mockApi(), null);
    await flushPromises();
    expect(api.get).not.toHaveBeenCalled();
    await state.submitSource();
    expect(api.create).not.toHaveBeenCalled();
    expect(state.errorMessage.value).toBeTruthy();
    state.updateSource({ ...state.draft.value, text: SOURCE.text });
    await state.submitSource();
    expect(api.create).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api.create).mock.calls[0]![0].input.sources).toHaveLength(1);
    expect(isReadonly(state.draft)).toBe(true);
  });

  it.each(["EXTRACTING", "CANCEL_REQUESTED", "FAILED", "CANCELLED"] as const)("keeps actions locked through physical drain for %s", async status => {
    const api = mockApi();
    vi.mocked(api.get).mockResolvedValue(result(preparation({ status, workPhase: "CALLING", generation: "g1" })));
    const { state } = controller(api);
    await flushPromises();
    expect(state.isBusy.value).toBe(true);
    expect(state.canSubmitSource.value).toBe(false);
    expect(state.canExtract.value).toBe(false);
    await state.submitSource(); await state.extract();
    expect(api.edit).not.toHaveBeenCalled(); expect(api.extract).not.toHaveBeenCalled();
  });

  it("does not overlap polls and stops after cancellation drains", async () => {
    vi.useFakeTimers();
    const api = mockApi();
    const pending = deferred<PreparationReceipt>();
    vi.mocked(api.get).mockResolvedValueOnce(result(preparation({ status: "EXTRACTING", workPhase: "CALLING", generation: "g1" }))).mockImplementationOnce(() => pending.promise).mockResolvedValue(result(preparation({ status: "CANCELLED", workPhase: "ENDED", generation: "g1" })));
    const { state } = controller(api);
    await flushPromises();
    await vi.advanceTimersByTimeAsync(2000);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(api.get).toHaveBeenCalledTimes(2);
    pending.resolve(result(preparation({ status: "CANCEL_REQUESTED", workPhase: "CALLING", generation: "g1" })));
    await flushPromises(); await vi.advanceTimersByTimeAsync(2000);
    expect(state.isBusy.value).toBe(false);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(api.get).toHaveBeenCalledTimes(3);
  });

  it.each(["DRAFT", "CANDIDATE", "REVIEWED", "FAILED", "CANCELLED"] as const)("does not poll drained %s state", async status => {
    vi.useFakeTimers(); const api = mockApi();
    vi.mocked(api.get).mockResolvedValue(result(preparation({ status })));
    controller(api); await flushPromises(); await vi.advanceTimersByTimeAsync(20_000);
    expect(api.get).toHaveBeenCalledTimes(1);
  });

  it("aborts a read on unmount and ignores its late result", async () => {
    vi.useFakeTimers(); const api = mockApi(); const pending = deferred<PreparationReceipt>();
    vi.mocked(api.get).mockImplementation(() => pending.promise);
    const { state, wrapper } = controller(api); await flushPromises();
    const signal = vi.mocked(api.get).mock.calls[0]![1]!.signal!;
    wrapper.unmount(); expect(signal.aborted).toBe(true);
    pending.resolve(result()); await flushPromises(); await vi.advanceTimersByTimeAsync(10_000);
    expect(state.preparation.value).toBe(null); expect(api.get).toHaveBeenCalledTimes(1);
  });

  it("retains the exact mutation key and revision after an uncertain cancellation", async () => {
    const api = mockApi();
    vi.mocked(api.get).mockResolvedValue(result(preparation({ revision: 5, status: "EXTRACTING", workPhase: "CALLING", generation: "g1" })));
    vi.mocked(api.cancel).mockRejectedValueOnce(new ApiClientError({ code: "NETWORK_ERROR", status: 0, message: "unsafe provider text" })).mockResolvedValueOnce(result(preparation({ revision: 6, status: "CANCEL_REQUESTED", workPhase: "CALLING", generation: "g1" }), 202));
    const { state } = controller(api); await flushPromises(); await state.cancel();
    expect(state.mutationState.value).toBe("UNCERTAIN"); expect(state.canExtract.value).toBe(false);
    expect(state.errorMessage.value).not.toContain("unsafe provider text");
    await state.retryMutation();
    const calls = vi.mocked(api.cancel).mock.calls;
    expect(calls[0]!.slice(0, 3)).toEqual(calls[1]!.slice(0, 3));
    expect(calls[1]![1]).toEqual({ expectedRevision: 5 });
    expect(state.preparation.value?.status).toBe("CANCEL_REQUESTED");
  });

  it("coalesces duplicate mutation clicks and fences a late read", async () => {
    const api = mockApi(); const poll = deferred<PreparationReceipt>(); const cancellation = deferred<PreparationReceipt>();
    vi.mocked(api.get).mockResolvedValueOnce(result(preparation({ status: "EXTRACTING", workPhase: "CALLING", generation: "g1", revision: 5 }))).mockImplementationOnce(() => poll.promise);
    vi.mocked(api.cancel).mockImplementation(() => cancellation.promise);
    const { state } = controller(api); await flushPromises();
    const read = state.refresh(); const first = state.cancel(); const second = state.cancel();
    expect(api.cancel).toHaveBeenCalledTimes(1);
    cancellation.resolve(result(preparation({ status: "CANCELLED", workPhase: "ENDED", generation: "g1", revision: 6 })));
    await first; await second;
    poll.resolve(result(preparation({ revision: 5 }))); await read;
    expect(state.preparation.value?.status).toBe("CANCELLED");
  });

  it("requires explicit ended confirmation for UNKNOWN and never resubmits implicitly", async () => {
    const api = mockApi();
    vi.mocked(api.get).mockResolvedValue(result(preparation({ status: "CANCEL_REQUESTED", workPhase: "UNKNOWN", generation: "g1" })));
    const { state } = controller(api); await flushPromises();
    expect(state.canRecover.value).toBe(true); await state.recover(false);
    expect(api.recover).not.toHaveBeenCalled(); await state.recover(true);
    expect(api.recover).toHaveBeenCalledWith("prep-1", { expectedRevision: 1, generation: "g1", confirmedEnded: true }, expect.any(String), expect.any(Object));
    expect(api.extract).not.toHaveBeenCalled(); expect(state.isBusy.value).toBe(false);
  });

  it("preserves local text edits on refresh and submits the latest authoritative revision", async () => {
    const { state, api } = controller(); await flushPromises();
    state.updateSource({ ...state.draft.value, text: "修正后的原文" });
    vi.mocked(api.get).mockResolvedValue(result(preparation({ revision: 3 })));
    await state.refresh(); expect(state.draft.value.text).toBe("修正后的原文");
    await state.submitSource();
    expect(api.edit).toHaveBeenCalledWith("prep-1", { expectedRevision: 3, source: { ...SOURCE, text: "修正后的原文" } }, expect.any(String), expect.any(Object));
  });

  it("keeps the original text editable after a definitive create rejection", async () => {
    const api = mockApi();
    vi.mocked(api.create).mockRejectedValue(new ApiClientError({ code: "VALIDATION_ERROR", status: 422, message: "rejected" }));
    const { state } = controller(api, null);
    state.updateSource({ ...state.draft.value, text: "待修正原文" });
    await state.submitSource();
    expect(state.isBusy.value).toBe(false);
    expect(state.canSubmitSource.value).toBe(true);
    state.updateSource({ ...state.draft.value, text: "修正原文" });
    expect(state.draft.value.text).toBe("修正原文");
    expect(state.errorMessage.value).toBeTruthy();
  });

  it("does not downgrade the latest state when an original receipt is replayed", async () => {
    const api = mockApi();
    vi.mocked(api.get).mockResolvedValueOnce(result()).mockResolvedValue(result(preparation({ revision: 5 })));
    vi.mocked(api.edit).mockRejectedValueOnce(new ApiClientError({ code: "NETWORK_ERROR", status: 0, message: "offline" })).mockResolvedValueOnce(result(preparation({ revision: 2 })));
    const { state } = controller(api); await flushPromises();
    state.updateSource({ ...SOURCE, text: "更正" }); await state.submitSource();
    await state.refresh(); await state.retryMutation();
    expect(state.preparation.value?.revision).toBe(5);
    expect(vi.mocked(api.edit).mock.calls[0]!.slice(0, 3)).toEqual(vi.mocked(api.edit).mock.calls[1]!.slice(0, 3));
    expect(state.mutationState.value).toBe("IDLE");
  });

  it("locks an uncertain create and freezes its one-source payload for safe replay", async () => {
    const api = mockApi();
    vi.mocked(api.create).mockRejectedValueOnce(new ApiClientError({ code: "INTERNAL_ERROR", status: 500, message: "private" })).mockResolvedValueOnce(result(preparation(), 201));
    const { state } = controller(api, null);
    state.updateSource({ ...state.draft.value, text: "原始文本" }); await state.submitSource();
    state.updateSource({ ...state.draft.value, text: "不应覆盖" }); await state.submitSource();
    expect(state.draft.value.text).toBe("原始文本"); expect(api.create).toHaveBeenCalledTimes(1);
    await state.retryMutation();
    expect(vi.mocked(api.create).mock.calls[0]!.slice(0, 2)).toEqual(vi.mocked(api.create).mock.calls[1]!.slice(0, 2));
  });

  it("refreshes conflict state without automatically resending the mutation", async () => {
    const api = mockApi();
    vi.mocked(api.get).mockResolvedValueOnce(result()).mockResolvedValue(result(preparation({ revision: 4, status: "CANCELLED" })));
    vi.mocked(api.extract).mockRejectedValue(new ApiClientError({ code: "CONFLICT", status: 409, message: "private conflict" }));
    const { state } = controller(api); await flushPromises(); await state.extract();
    expect(api.extract).toHaveBeenCalledTimes(1); expect(api.get).toHaveBeenCalledTimes(2);
    expect(state.preparation.value?.revision).toBe(4); expect(state.errorMessage.value).toContain("状态已变化");
  });

  it("requires saving edited evidence before extracting and uses the saved revision", async () => {
    const api = mockApi(); const { state } = controller(api); await flushPromises();
    state.updateSource({ ...SOURCE, text: "更正后的原文" });
    expect(state.canExtract.value).toBe(false); await state.extract(); expect(api.extract).not.toHaveBeenCalled();
    vi.mocked(api.edit).mockResolvedValue(result(preparation({ revision: 2, source: { ...SOURCE, text: "更正后的原文" } })));
    await state.submitSource(); expect(state.canExtract.value).toBe(true); await state.extract();
    expect(vi.mocked(api.extract).mock.calls[0]?.[1]).toEqual({ expectedRevision: 2 });
  });

  it("pauses reads while hidden and resumes unfinished work without automatic mutation", async () => {
    vi.useFakeTimers(); const api = mockApi();
    vi.mocked(api.get).mockResolvedValue(result(preparation({ status: "EXTRACTING", workPhase: "CALLING", generation: "g1" })));
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    controller(api); await flushPromises();
    hidden.mockReturnValue(true); document.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(10_000); expect(api.get).toHaveBeenCalledTimes(1);
    hidden.mockReturnValue(false); document.dispatchEvent(new Event("visibilitychange")); await flushPromises();
    expect(api.get).toHaveBeenCalledTimes(2); expect(api.extract).not.toHaveBeenCalled();
  });

  it("preserves current evidence after a failed read and ignores a late unmounted mutation", async () => {
    const api = mockApi(); const { state, wrapper } = controller(api); await flushPromises();
    state.updateSource({ ...SOURCE, text: "本地修正" });
    vi.mocked(api.get).mockRejectedValue(new Error("private detail")); await state.refresh();
    expect(state.preparation.value?.revision).toBe(1); expect(state.draft.value.text).toBe("本地修正");
    expect(state.errorMessage.value).not.toContain("private detail");
    vi.mocked(api.get).mockResolvedValue(result()); await state.refresh();
    const pending = deferred<PreparationReceipt>(); vi.mocked(api.edit).mockReturnValue(pending.promise);
    const operation = state.submitSource(); const signal = vi.mocked(api.edit).mock.calls[0]?.[3]?.signal;
    wrapper.unmount(); expect(signal?.aborted).toBe(true);
    pending.resolve(result(preparation({ revision: 2 }))); await operation;
    expect(state.preparation.value?.revision).toBe(1);
  });

  it("finishes refreshing without downgrading a newer authoritative revision", async () => {
    const api = mockApi();
    vi.mocked(api.get).mockResolvedValueOnce(result(preparation({ revision: 5 }))).mockResolvedValueOnce(result(preparation({ revision: 2 })));
    const { state } = controller(api); await flushPromises(); await state.refresh();
    expect(state.preparation.value?.revision).toBe(5); expect(state.requestState.value).toBe("READY");
  });
});

function sourceForm() {
  const wrapper = mount(PlanPreparationSourceForm, { props: { source: SOURCE, disabled: false, errorMessage: null } });
  wrappers.push(wrapper); return wrapper;
}
function fileWithBytes(bytes: Uint8Array, name = "plan.txt") {
  const file = new File([bytes.slice().buffer], name);
  Object.defineProperty(file, "arrayBuffer", { value: async () => bytes.slice().buffer });
  return file;
}
async function chooseFile(wrapper: VueWrapper, files: File[]) {
  const input = wrapper.get('input[type="file"]');
  Object.defineProperty(input.element, "files", { value: files, configurable: true });
  await input.trigger("change"); await flushPromises();
}
function progressProps(overrides: Record<string, unknown> = {}) {
  return { preparation: preparation(), requestState: "READY" as const, mutationState: "IDLE" as const,
    canExtract: true, canCancel: false, canRecover: false, canRetryMutation: false,
    errorMessage: null, ...overrides };
}

describe("one-source input and progress components", () => {
  it("emits controlled source changes and validates before submitting", async () => {
    const wrapper = sourceForm();
    await wrapper.get("textarea").setValue("新的完整原文");
    expect(wrapper.emitted("update:source")?.[0]?.[0]).toEqual({ ...SOURCE, effective_trade_date: null, text: "新的完整原文" });
    await wrapper.setProps({ source: { ...SOURCE, text: "   " } });
    await wrapper.get("form").trigger("submit");
    expect(wrapper.emitted("submit")).toBeUndefined(); expect(wrapper.get('[role="alert"]').text()).toContain("原文");
    await wrapper.setProps({ source: SOURCE }); await wrapper.get("form").trigger("submit");
    expect(wrapper.emitted("submit")).toHaveLength(1);
    expect(wrapper.find('input[type="file"]').attributes("multiple")).toBeUndefined();
  });

  it("reads exactly one UTF-8 Markdown file without changing its evidence whitespace", async () => {
    const wrapper = sourceForm();
    await chooseFile(wrapper, [fileWithBytes(new TextEncoder().encode("  原文\n完整计划  "), "plan.md")]);
    expect(wrapper.emitted("update:source")?.at(-1)?.[0]).toEqual({ ...SOURCE, effective_trade_date: null, text: "  原文\n完整计划  " });
  });

  it.each(["multiple", "encoding", "extension", "oversize"])("preserves pasted text after invalid file %s", async kind => {
    const wrapper = sourceForm();
    const good = fileWithBytes(new TextEncoder().encode("file"));
    const files = kind === "multiple" ? [good, good] : kind === "encoding" ? [fileWithBytes(new Uint8Array([0xc3, 0x28]))] :
      kind === "extension" ? [fileWithBytes(new TextEncoder().encode("file"), "plan.html")] : [fileWithBytes(new Uint8Array(600_001))];
    await chooseFile(wrapper, files);
    expect(wrapper.emitted("update:source")).toBeUndefined();
    expect((wrapper.get("textarea").element as HTMLTextAreaElement).value).toBe(SOURCE.text);
    expect(wrapper.get('[role="alert"]').text()).toBeTruthy();
  });

  it("ignores a file read that finishes after a manual edit or unmount", async () => {
    const wrapper = sourceForm(); const pending = deferred<ArrayBuffer>();
    const changes = vi.fn(); await wrapper.setProps({ "onUpdate:source": changes });
    const file = new File(["old"], "old.txt"); Object.defineProperty(file, "arrayBuffer", { value: () => pending.promise, configurable: true });
    await chooseFile(wrapper, [file]); await wrapper.get("textarea").setValue("手动更正");
    pending.resolve(new TextEncoder().encode("过时文件").buffer); await flushPromises();
    expect(wrapper.emitted("update:source")).toEqual([[{ ...SOURCE, effective_trade_date: null, text: "手动更正" }]]);
    const another = deferred<ArrayBuffer>(); Object.defineProperty(file, "arrayBuffer", { value: () => another.promise, configurable: true });
    await chooseFile(wrapper, [file]); wrapper.unmount(); another.resolve(new TextEncoder().encode("晚到").buffer); await flushPromises();
    expect(changes).toHaveBeenCalledTimes(1);
  });

  it("keeps server errors as escaped text and disables source changes during pending work", async () => {
    const wrapper = sourceForm(); await wrapper.setProps({ disabled: true, errorMessage: '<img src=x onerror="alert(1)">' });
    expect(wrapper.find("img").exists()).toBe(false); expect(wrapper.get('[role="alert"]').text()).toContain("<img");
    expect(wrapper.get("fieldset").attributes("disabled")).toBeDefined();
    await wrapper.get("form").trigger("submit"); expect(wrapper.emitted("submit")).toBeUndefined();
  });

  it("keeps cancellation waiting visible and emits only permitted progress actions", async () => {
    const wrapper = mount(PlanPreparationProgress, { props: progressProps({ preparation: preparation({ status: "CANCEL_REQUESTED", workPhase: "CALLING", generation: "g1" }), canExtract: false }) });
    wrappers.push(wrapper);
    expect(wrapper.text()).toContain("等待提取结束"); expect(wrapper.text()).toContain("完成前");
    expect(wrapper.find('[data-testid="extract-preparation"]').exists()).toBe(false);
    await wrapper.get('[data-testid="refresh-preparation"]').trigger("click"); expect(wrapper.emitted("refresh")).toHaveLength(1);
  });

  it("requires a checked ended confirmation and shows a safe retry for uncertain results", async () => {
    const wrapper = mount(PlanPreparationProgress, { props: progressProps({ preparation: preparation({ status: "EXTRACTING", workPhase: "UNKNOWN", generation: "g1" }), canExtract: false, canRecover: true }) });
    wrappers.push(wrapper);
    expect(wrapper.get('[data-testid="recover-preparation"]').attributes("disabled")).toBeDefined();
    await wrapper.get('input[type="checkbox"]').setValue(true); await wrapper.get('[data-testid="recover-preparation"]').trigger("click");
    expect(wrapper.emitted("recover")).toEqual([[true]]);
    await wrapper.setProps({ mutationState: "UNCERTAIN", canRecover: false, canRetryMutation: true });
    await wrapper.get('[data-testid="retry-preparation-mutation"]').trigger("click");
    expect(wrapper.emitted("retryMutation")).toHaveLength(1);
  });

  it("records a confirmed effective date and rejects reversed legacy provenance", async () => {
    const wrapper = sourceForm();
    await wrapper.get('input[type="date"]').setValue("2026-10-08");
    expect(wrapper.emitted("update:source")?.at(-1)?.[0]).toEqual({ ...SOURCE, effective_trade_date: "2026-10-08" });
    await wrapper.setProps({ source: { ...SOURCE, authored_at: "2026-10-08T09:30:00+08:00", available_at: "2026-10-08T09:00:00+08:00" } });
    await wrapper.get("form").trigger("submit"); expect(wrapper.emitted("submit")).toBeUndefined();
    expect(wrapper.get('[role="alert"]').text()).toContain("不能晚于");
  });

  it("counts Unicode characters and preserves input when a decoded file exceeds the limit", async () => {
    const wrapper = sourceForm(); await wrapper.setProps({ source: { ...SOURCE, text: "🙂计划" } });
    expect(wrapper.text()).toContain("3 / 150000");
    await chooseFile(wrapper, [fileWithBytes(new TextEncoder().encode("a".repeat(150_001)))]);
    expect(wrapper.emitted("update:source")).toBeUndefined(); expect(wrapper.get('[role="alert"]').text()).toContain("150000");
    expect((wrapper.get("textarea").element as HTMLTextAreaElement).value).toBe("🙂计划");
  });

  it("invalidates a file read when pending work disables the source form", async () => {
    const wrapper = sourceForm(); const pending = deferred<ArrayBuffer>(); const file = new File(["old"], "old.txt");
    Object.defineProperty(file, "arrayBuffer", { value: () => pending.promise }); await chooseFile(wrapper, [file]);
    await wrapper.setProps({ disabled: true }); pending.resolve(new TextEncoder().encode("旧文件").buffer); await flushPromises();
    expect(wrapper.emitted("update:source")).toBeUndefined();
  });

  it("clears an ended confirmation when the observed generation changes", async () => {
    const wrapper = mount(PlanPreparationProgress, { props: progressProps({ preparation: preparation({ status: "EXTRACTING", workPhase: "UNKNOWN", generation: "g1" }), canExtract: false, canRecover: true }) });
    wrappers.push(wrapper); await wrapper.get('input[type="checkbox"]').setValue(true);
    await wrapper.setProps({ preparation: preparation({ status: "EXTRACTING", workPhase: "UNKNOWN", generation: "g2", revision: 2 }) });
    expect(wrapper.get('[data-testid="recover-preparation"]').attributes("disabled")).toBeDefined();
  });
});


it("requires all saved dates before extracting any item", async () => {
  const api = collectionApi();
  const items = collectionDetails();
  items[2]!.effectiveTradeDate = null;
  items[2]!.source.effective_trade_date = null;
  api.items.mockResolvedValue(itemPage(items));
  api.get.mockResolvedValue(collectionReceipt(collection({ items })));
  const { state } = controller(api);
  await flushPromises();
  expect(state.canExtract.value).toBe(false);
  expect(state.extractionBlockers.value.join(" ")).toContain("第 3 份");
  await state.extract();
  expect(api.extract).not.toHaveBeenCalled();
});
