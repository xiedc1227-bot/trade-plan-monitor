import { afterEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h, isReadonly } from "vue";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";

import type { PreparationView } from "../../src/api/generated-runtime-status";
import { createPreparationApi, type PreparationApi, type PreparationReceipt } from "../../src/api/preparations";
import { ApiClientError } from "../../src/api/transport";
import { usePlanPreparation } from "../../src/composables/usePlanPreparation";

const BASE = "/api/v1/backtest-preparations";
const SOURCE = { source_id: "source-1", text: "完整计划原文" };
const wrappers: VueWrapper[] = [];
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.useRealTimers(); vi.restoreAllMocks(); });

function result(body = preparation(), status: 200 | 201 | 202 = 200): PreparationReceipt {
  return { body, status, retryAfterSeconds: status === 202 ? 2 : null };
}
function mockApi(): PreparationApi {
  return {
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

describe("one-source preparation transport", () => {
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
});
