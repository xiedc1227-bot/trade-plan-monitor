import { createHash, webcrypto } from "node:crypto";
import { flushPromises } from "@vue/test-utils";
import { effectScope, isReadonly, shallowRef, type MaybeRefOrGetter } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createSourceCoverageApi, type SourceCoverageApi, type SourceCoveragePage,
  type SourceCoverageSummaryView } from "../../src/api/sourceCoverage";
import { ApiClientError } from "../../src/api/transport";
import { useSourceCoverage, type SourceCoverageContext,
  type UseSourceCoverageOptions } from "../../src/composables/useSourceCoverage";

const source = "最大持仓300股。\r\n😀";
const hash = (value: string) => createHash("sha256").update(value, "utf8").digest("hex");
const digest = (character: string) => character.repeat(64);
const context: SourceCoverageContext = { planVersionId: "00000000-0000-4000-8000-000000000001",
  sourceHash: hash(source), candidatePlanHash: digest("b"), contentHash: digest("c"),
  originalReviewEvidenceHash: digest("d"), reviewId: null, reviewRevision: 0,
  sourceText: source, ownerGeneration: 1 };
function summary(overrides: Partial<SourceCoverageSummaryView> = {}): SourceCoverageSummaryView {
  return { authorityGranted: false, status: "COMPLETE", coverageComplete: true, currentReviewBound: false,
    canConfirmReview: true, reviewState: "UNCONFIRMED", reason: null,
    sourceHash: context.sourceHash, candidatePlanHash: context.candidatePlanHash,
    contentHash: context.contentHash, mappingHash: digest("e"), rulesVersion: "source-coverage-rules-v1",
    coverageEvidenceHash: digest("f"), coverageRevision: 1, coverageBundleHash: digest("a"),
    normalizationHash: null, originalReviewEvidenceHash: context.originalReviewEvidenceHash,
    reviewId: null, reviewRevision: 0, coverageReviewReceiptHash: null, origin: "HUMAN",
    automaticFidelityVerified: false, obligationCount: 1, issueCount: 0,
    normalizationChangeCount: 0, totalRows: 1, ...overrides };
}
function page(value = summary()): SourceCoveragePage {
  return { authorityGranted: false, planVersionId: context.planVersionId, summary: value, limit: 50,
    returnedCount: 1, totalRows: value.totalRows, nextCursor: null, items: [{ kind: "OBLIGATION", rowIndex: 0,
      obligation: { version: "source-obligation-v1", rulesVersion: "source-coverage-rules-v1",
        sourceHash: value.sourceHash, clauseId: "clause-1", start: 0, end: 9, excerpt: "最大持仓300股。",
        kind: "DECLARATION", scope: "PLAN", serverState: "MAPPED", semanticsJson: null,
        groupId: null, relationIds: [], paths: ["position.max_qty"], obligationId: digest("1"),
        mappingProposal: null, humanSupplements: [] } }] };
}
const scopes: ReturnType<typeof effectScope>[] = [];
afterEach(() => { for (const scope of scopes.splice(0)) scope.stop(); vi.unstubAllGlobals(); });
function setup(input: Parameters<typeof useSourceCoverage>[0] = context,
  getSourceCoverage: SourceCoverageApi["getSourceCoverage"] = vi.fn(async () => page()),
  options: MaybeRefOrGetter<UseSourceCoverageOptions> = {}) {
  vi.stubGlobal("crypto", webcrypto);
  const scope = effectScope(); scopes.push(scope);
  const api = { getSourceCoverage };
  const state = scope.run(() => useSourceCoverage(input, () => ({ api,
    ...(typeof options === "function" ? options() : "value" in options ? options.value : options) })))!;
  return { state, getSourceCoverage, scope };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((accept, deny) => { resolve = accept; reject = deny; });
  return { promise, resolve, reject };
}

function streams() {
  const value = summary({ status: "BLOCKED", coverageComplete: false, canConfirmReview: false,
    reviewState: "NEEDS_REVIEW", reason: "SOURCE_COVERAGE_REQUIRED", issueCount: 1,
    normalizationChangeCount: 1, totalRows: 3 });
  const all = page(value);
  all.items.push({ kind: "ISSUE", rowIndex: 1, issue: { code: "SOURCE_CONTEXT_UNVERIFIED",
    path: "source.global", start: null, end: null, message: "全局问题不因当前页不可见而消失" } },
  { kind: "NORMALIZATION_CHANGE", rowIndex: 2, change: { path: "position.max_qty",
    beforeJson: "null", afterJson: "300", reason: "NORMALIZATION", traceRole: "HISTORICAL_INPUT",
    sourceHash: digest("9"), beforeHash: digest("2"), afterHash: digest("3"), evidenceHash: digest("4") } });
  all.returnedCount = 3;
  return all;
}

function piece(all: SourceCoveragePage, start: number, end: number, nextCursor: string | null): SourceCoveragePage {
  return { ...all, items: all.items.slice(start, end), returnedCount: end - start, nextCursor };
}

async function finished(state: ReturnType<typeof useSourceCoverage>) {
  await vi.waitFor(() => expect(state.phase.value).not.toBe("LOADING"));
  await flushPromises();
}

describe("source coverage current view", () => {
  it("reads the exact source and exposes only the server's two confirmation fields", async () => {
    const { state } = setup();
    await vi.waitFor(() => expect(state.phase.value).toBe("CURRENT"));
    await flushPromises();
    expect(state.currentConfirmation.value).toEqual({ coverageEvidenceHash: digest("f"),
      coverageRulesVersion: "source-coverage-rules-v1" });
    expect(state.verifiedSourceHash.value).toBe(context.sourceHash);
  });

  it.each(["plain", "ref", "getter"] as const)("accepts a %s readonly context", async (kind) => {
    const value = shallowRef<SourceCoverageContext | null>(context);
    const { state } = setup(kind === "plain" ? context : kind === "ref" ? value : () => value.value);
    await finished(state);
    expect(state.phase.value).toBe("CURRENT");
    expect(isReadonly(state.page)).toBe(true);
    expect(isReadonly(state.page.value?.summary)).toBe(true);
    expect(Object.isFrozen(state.currentConfirmation.value)).toBe(true);
  });

  it("does not fetch while an edited/historical/unloaded owner supplies null", async () => {
    const call = vi.fn<SourceCoverageApi["getSourceCoverage"]>();
    const value = shallowRef<SourceCoverageContext | null>(null);
    const { state } = setup(value, call);
    await flushPromises();
    expect(call).not.toHaveBeenCalled();
    expect(state.phase.value).toBe("IDLE");
    value.value = context;
    call.mockResolvedValue(page());
    await finished(state);
    value.value = null;
    expect(state.phase.value).toBe("IDLE");
    expect(state.currentConfirmation.value).toBeNull();
    expect(state.page.value).toBeNull();
  });

  it("supports reactive options and fixed chain limits", async () => {
    const selected = shallowRef(2);
    const call = vi.fn<SourceCoverageApi["getSourceCoverage"]>(async (_id, request) => ({ ...page(), limit: request!.limit! }));
    const { state } = setup(context, call, () => ({ limit: selected.value }));
    await finished(state);
    expect(state.page.value?.limit).toBe(2);
    selected.value = 1;
    expect(state.currentConfirmation.value).toBeNull();
    await finished(state);
    expect(state.page.value?.limit).toBe(1);
  });

  it("immediately removes confirmation on refresh/invalidate and only refetches explicitly", async () => {
    const { state, getSourceCoverage } = setup();
    await finished(state);
    state.invalidate();
    expect(state.phase.value).toBe("STALE");
    expect(state.currentConfirmation.value).toBeNull();
    await flushPromises();
    expect(getSourceCoverage).toHaveBeenCalledTimes(1);
    const refreshing = state.refresh();
    expect(state.currentConfirmation.value).toBeNull();
    await refreshing;
    expect(state.phase.value).toBe("CURRENT");
  });

  it("uses the real typed GET API with an exact abort signal and no mutation request", async () => {
    const fetcher = vi.fn<typeof fetch>(async () => new Response(JSON.stringify(page())));
    const api = createSourceCoverageApi(fetcher);
    const { state } = setup(context, api.getSourceCoverage);
    await finished(state);
    expect(state.phase.value).toBe("CURRENT");
    expect(fetcher.mock.calls[0]?.[1]).toMatchObject({ method: "GET", headers: { Accept: "application/json" } });
    expect(fetcher.mock.calls[0]?.[1]?.signal).toBeInstanceOf(AbortSignal);
  });

  it("rejects a raw source hash mismatch instead of normalizing CRLF or trimming", async () => {
    const call = vi.fn(async () => page());
    const { state } = setup({ ...context, sourceText: source.replace("\r\n", "\n") }, call);
    await finished(state);
    expect(state.phase.value).toBe("STALE");
    expect(state.safeError.value?.code).toBe("SOURCE_HASH_MISMATCH");
    expect(state.verifiedSourceHash.value).toBeNull();
    expect(call).not.toHaveBeenCalled();
  });

  it("refuses lone surrogates before TextEncoder can replace them", async () => {
    const call = vi.fn(async () => page());
    const { state } = setup({ ...context, sourceText: "\ud800" }, call);
    await finished(state);
    expect(state.phase.value).toBe("ERROR");
    expect(call).not.toHaveBeenCalled();
  });

  it.each(["sourceHash", "candidatePlanHash", "contentHash", "originalReviewEvidenceHash"] as const)(
    "rejects a changed native %s peer", async (field) => {
      const { state } = setup(context, vi.fn(async () => page(summary({ [field]: digest("9") }))));
      await finished(state);
      expect(state.phase.value).toBe("STALE");
      expect(state.currentConfirmation.value).toBeNull();
    });

  it("requires an exact optional saved-summary seed, including proof revision", async () => {
    const { state } = setup({ ...context, expectedSummary: summary({ coverageRevision: 2 }) });
    await finished(state);
    expect(state.safeError.value?.code).toBe("PAGE_CHANGED");
    expect(state.currentConfirmation.value).toBeNull();
  });

  it("keeps server denial despite a complete HUMAN-origin result", async () => {
    const { state } = setup(context, vi.fn(async () => page(summary({ canConfirmReview: false }))));
    await finished(state);
    expect(state.summary.value?.coverageComplete).toBe(true);
    expect(state.currentConfirmation.value).toBeNull();
  });

  it.each(["unresolved-obligation", "foreign-human-link"] as const)(
    "rejects an incoherent injected page with %s using the same wire contract", async (fault) => {
      const response = page();
      const row = response.items[0]!;
      if (row.kind !== "OBLIGATION") throw new Error("fixture requires an obligation");
      if (fault === "unresolved-obligation") {
        row.obligation.serverState = "UNRESOLVED";
        row.obligation.scope = "UNKNOWN";
      } else {
        row.obligation.serverState = "MAPPED_WITH_REGISTERED_SUPPLEMENT";
        row.obligation.humanSupplements = [{ supplementId: "human-1", path: "position.max_qty",
          candidateContentHash: digest("9") }];
      }
      const { state } = setup(context, vi.fn(async () => response));
      await finished(state);
      expect(state.phase.value).toBe("STALE");
      expect(state.safeError.value?.code).toBe("PAGE_CHANGED");
      expect(state.currentConfirmation.value).toBeNull();
    });

  it("owns the accepted page rather than a mutable injected API object", async () => {
    const response = page();
    const { state } = setup(context, vi.fn(async () => response));
    await finished(state);
    response.summary.coverageEvidenceHash = digest("9");
    response.items.length = 0;
    expect(state.currentConfirmation.value?.coverageEvidenceHash).toBe(digest("f"));
    expect(state.page.value?.items).toHaveLength(1);
  });

  it("matches exact native review identity and revision", async () => {
    const id = "00000000-0000-4000-8000-000000000002";
    const reviewed = summary({ reviewId: id, reviewRevision: 1, canConfirmReview: false,
      currentReviewBound: true, reviewState: "CURRENT", coverageReviewReceiptHash: digest("9") });
    const { state } = setup({ ...context, reviewId: id, reviewRevision: 1 }, vi.fn(async () => page(reviewed)));
    await finished(state);
    expect(state.phase.value).toBe("CURRENT");
    expect(state.currentConfirmation.value).toBeNull();
    const mismatch = setup(context, vi.fn(async () => page(reviewed)));
    await finished(mismatch.state);
    expect(mismatch.state.phase.value).toBe("STALE");
  });
});

describe("bounded single-page source streams", () => {
  it("advances by actual short-page rows across all three streams while preserving global blockers", async () => {
    const all = streams();
    const call = vi.fn<SourceCoverageApi["getSourceCoverage"]>()
      .mockResolvedValueOnce(piece(all, 0, 1, "opaque+/=?"))
      .mockResolvedValueOnce(piece(all, 1, 2, "opaque-2"))
      .mockResolvedValueOnce(piece(all, 2, 3, null));
    const { state } = setup(context, call);
    await finished(state);
    expect(state.page.value?.items.map((row) => row.kind)).toEqual(["OBLIGATION"]);
    expect(state.summary.value?.issueCount).toBe(1);
    expect(state.currentConfirmation.value).toBeNull();
    await state.nextPage();
    expect(state.page.value?.items.map((row) => row.kind)).toEqual(["ISSUE"]);
    expect(call.mock.calls[1]?.[1]).toEqual({ limit: 50, cursor: "opaque+/=?" });
    await state.nextPage();
    expect(state.page.value?.items.map((row) => row.kind)).toEqual(["NORMALIZATION_CHANGE"]);
    expect(state.page.value?.items).toHaveLength(1);
    await state.nextPage();
    expect(call).toHaveBeenCalledTimes(3);
  });

  it.each(["coverageEvidenceHash", "mappingHash", "normalizationHash", "origin", "coverageRevision"] as const)(
    "refuses cross-page change to the full summary field %s", async (field) => {
      const all = streams();
      const later = structuredClone(all);
      if (field === "origin") later.summary.origin = "AI_NEW";
      else if (field === "coverageRevision") later.summary.coverageRevision = 2;
      else later.summary[field] = digest("7");
      const call = vi.fn<SourceCoverageApi["getSourceCoverage"]>()
        .mockResolvedValueOnce(piece(all, 0, 1, "cursor1")).mockResolvedValueOnce(piece(later, 1, 2, "cursor2"));
      const { state } = setup(context, call); await finished(state);
      await state.nextPage();
      expect(state.phase.value).toBe("STALE");
      expect(state.page.value).toBeNull();
      expect(state.currentConfirmation.value).toBeNull();
    });

  it.each(["gap", "wrong-kind", "loop", "empty", "count", "limit", "native-version"])(
    "rejects continuation %s without skipping or reloading automatically", async (fault) => {
      const all = streams(); const later = piece(all, 1, 2, "cursor2");
      if (fault === "gap") later.items[0]!.rowIndex = 2;
      if (fault === "wrong-kind") later.items = [structuredClone(all.items[0]!)], later.items[0]!.rowIndex = 1;
      if (fault === "loop") later.nextCursor = "cursor1";
      if (fault === "empty") later.items = [], later.returnedCount = 0;
      if (fault === "count") later.totalRows = 4;
      if (fault === "limit") later.limit = 100;
      if (fault === "native-version") later.planVersionId = "00000000-0000-4000-8000-000000000002";
      const call = vi.fn<SourceCoverageApi["getSourceCoverage"]>()
        .mockResolvedValueOnce(piece(streams(), 0, 1, "cursor1")).mockResolvedValueOnce(later);
      const { state } = setup(context, call); await finished(state);
      await state.nextPage(); await state.nextPage();
      expect(state.phase.value).toBe("STALE");
      expect(call).toHaveBeenCalledTimes(2);
    });

  it.each([409, 422])("requires an explicit first page after cursor HTTP%s", async (status) => {
    const all = streams();
    const call = vi.fn<SourceCoverageApi["getSourceCoverage"]>()
      .mockResolvedValueOnce(piece(all, 0, 1, "cursor1"))
      .mockRejectedValueOnce(new ApiClientError({ code: status === 409 ? "CONFLICT" : "VALIDATION_ERROR",
        status, message: "private path must not be shown" }))
      .mockResolvedValueOnce(piece(all, 0, 1, "new-chain"));
    const { state } = setup(context, call); await finished(state);
    await state.nextPage();
    expect(state.safeError.value?.requiresFirstPage).toBe(true);
    expect(state.safeError.value?.message).not.toContain("private path");
    await state.nextPage(); expect(call).toHaveBeenCalledTimes(2);
    await state.firstPage();
    expect(call.mock.calls[2]?.[1]).toEqual({ limit: 50 });
    expect(state.phase.value).toBe("CURRENT");
  });

  it("allows confirmation from the exact first short page without requiring every page to be viewed", async () => {
    const all = page(summary({ obligationCount: 2, totalRows: 2 }));
    const call = vi.fn<SourceCoverageApi["getSourceCoverage"]>().mockResolvedValue({ ...all, nextCursor: "next" });
    const { state } = setup(context, call); await finished(state);
    expect(state.currentConfirmation.value?.coverageEvidenceHash).toBe(digest("f"));
    expect(call).toHaveBeenCalledTimes(1);
  });

  it("does not reuse an old chain after nonreactive owner mutation at the next-page boundary", async () => {
    const mutable = { ...context };
    const call = vi.fn<SourceCoverageApi["getSourceCoverage"]>().mockResolvedValue(piece(streams(), 0, 1, "cursor1"));
    const { state } = setup(mutable, call); await finished(state);
    mutable.ownerGeneration = 2;
    await state.nextPage();
    expect(state.phase.value).toBe("STALE");
    expect(call).toHaveBeenCalledTimes(1);
  });
});

describe("source owner and async fencing", () => {
  it("ignores success from an aborted A request after A-B-A and preserves the newest A proof", async () => {
    const a = deferred<SourceCoveragePage>();
    const b = deferred<SourceCoveragePage>();
    const latest = deferred<SourceCoveragePage>();
    const call = vi.fn<SourceCoverageApi["getSourceCoverage"]>()
      .mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise).mockReturnValueOnce(latest.promise);
    const value = shallowRef<SourceCoverageContext | null>(context);
    const { state } = setup(value, call);
    await vi.waitFor(() => expect(call).toHaveBeenCalledTimes(1));
    value.value = { ...context, ownerGeneration: 2 };
    await vi.waitFor(() => expect(call).toHaveBeenCalledTimes(2));
    expect(call.mock.calls[0]?.[2]?.signal?.aborted).toBe(true);
    value.value = context;
    await vi.waitFor(() => expect(call).toHaveBeenCalledTimes(3));
    latest.resolve(page(summary({ coverageEvidenceHash: digest("8") })));
    await finished(state);
    a.resolve(page()); b.reject(new Error("late private error")); await flushPromises();
    expect(state.currentConfirmation.value?.coverageEvidenceHash).toBe(digest("8"));
    expect(state.safeError.value).toBeNull();
    expect(state.phase.value).toBe("CURRENT");
  });

  it("invalidates same-version proof replacement and preserves a newer loading phase from old error/finally", async () => {
    const first = deferred<SourceCoveragePage>(); const second = deferred<SourceCoveragePage>();
    const call = vi.fn<SourceCoverageApi["getSourceCoverage"]>().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const value = shallowRef<SourceCoverageContext | null>({ ...context, expectedSummary: summary() });
    const { state } = setup(value, call);
    await vi.waitFor(() => expect(call).toHaveBeenCalledTimes(1));
    const newer = summary({ coverageEvidenceHash: digest("8") });
    value.value = { ...context, expectedSummary: newer };
    expect(state.currentConfirmation.value).toBeNull();
    await vi.waitFor(() => expect(call).toHaveBeenCalledTimes(2));
    first.reject(new Error("old private error")); await flushPromises();
    expect(state.phase.value).toBe("LOADING"); expect(state.safeError.value).toBeNull();
    second.resolve(page(newer)); await finished(state);
    expect(state.currentConfirmation.value?.coverageEvidenceHash).toBe(digest("8"));
  });

  it("captures plain context scalars before await and rejects mutation without reactive notifications", async () => {
    const response = deferred<SourceCoveragePage>(); const call = vi.fn(() => response.promise);
    const mutable = { ...context };
    const { state } = setup(mutable, call);
    await vi.waitFor(() => expect(call).toHaveBeenCalledTimes(1));
    mutable.ownerGeneration = 2;
    response.resolve(page()); await flushPromises();
    expect(state.phase.value).toBe("STALE"); expect(state.currentConfirmation.value).toBeNull();
  });

  it("drops late hash success after an edited context and does not even dispatch its request", async () => {
    const { state, getSourceCoverage, scope } = setup(null);
    scope.stop();
    expect(state.phase.value).toBe("IDLE");
    const hashResult = deferred<ArrayBuffer>();
    vi.stubGlobal("crypto", { subtle: { digest: vi.fn(() => hashResult.promise) } });
    const value = shallowRef<SourceCoverageContext | null>(context);
    const owned = effectScope(); scopes.push(owned);
    const current = owned.run(() => useSourceCoverage(value, { api: { getSourceCoverage } }))!;
    value.value = null;
    hashResult.resolve(Uint8Array.from(Buffer.from(context.sourceHash, "hex")).buffer);
    await flushPromises();
    expect(current.phase.value).toBe("IDLE"); expect(getSourceCoverage).not.toHaveBeenCalled();
    expect(current.verifiedSourceHash.value).toBeNull();
  });

  it("ignores a late hash failure while the new owner is still loading", async () => {
    const owner = effectScope(); scopes.push(owner);
    const firstHash = deferred<ArrayBuffer>(); const secondHash = deferred<ArrayBuffer>();
    vi.stubGlobal("crypto", { subtle: { digest: vi.fn().mockReturnValueOnce(firstHash.promise).mockReturnValueOnce(secondHash.promise) } });
    const value = shallowRef<SourceCoverageContext | null>(context);
    const call = vi.fn<SourceCoverageApi["getSourceCoverage"]>(async () => page());
    const state = owner.run(() => useSourceCoverage(value, { api: { getSourceCoverage: call } }))!;
    value.value = { ...context, ownerGeneration: 2 };
    firstHash.reject(new Error("old digest failed")); await flushPromises();
    expect(state.phase.value).toBe("LOADING"); expect(state.safeError.value).toBeNull();
    secondHash.resolve(Uint8Array.from(Buffer.from(context.sourceHash, "hex")).buffer);
    await finished(state);
    expect(state.phase.value).toBe("CURRENT");
    expect(call).toHaveBeenCalledTimes(1);
  });

  it("aborts on scope disposal and never applies late success or failure", async () => {
    const result = deferred<SourceCoveragePage>();
    const call = vi.fn<SourceCoverageApi["getSourceCoverage"]>(() => result.promise);
    const { state, scope } = setup(context, call);
    await vi.waitFor(() => expect(call).toHaveBeenCalledTimes(1));
    scope.stop(); result.resolve(page()); await flushPromises();
    expect(state.phase.value).toBe("IDLE"); expect(state.page.value).toBeNull();
    expect(call.mock.calls[0]?.[2]?.signal?.aborted).toBe(true);
  });

  it("retries manually with a safe error and never displays attacker-shaped error properties", async () => {
    const call = vi.fn<SourceCoverageApi["getSourceCoverage"]>()
      .mockRejectedValueOnce({ requiresFirstPage: false, code: "LEAK", message: "secret URL/path" })
      .mockResolvedValueOnce(page());
    const { state } = setup(context, call); await finished(state);
    expect(state.safeError.value?.message).toBe("暂时无法读取原文核对结果，请重试");
    expect(state.safeError.value?.code).toBe("READ_FAILED");
    expect(call).toHaveBeenCalledTimes(1);
    await state.refresh(); expect(state.phase.value).toBe("CURRENT");
  });
});
