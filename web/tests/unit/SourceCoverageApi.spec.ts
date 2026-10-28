import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";

import type { PlanVersionSummary, PlanVersionView, SourceCoveragePage, SourceCoverageSummaryView,
  SourceObligationView } from "../../src/api/generated";
import { createPlanApi } from "../../src/api/plans";
import { createSourceCoverageApi, isSourceCoverageSummary, type SourceCoverageRequest } from "../../src/api/sourceCoverage";

// Synthetic wire projections exercise client structure, never authenticate policy.
// The original native fixture remains unchanged; full semantic/proof verification
// belongs to the server and is covered by its actual HTTP/storage tests.
const native: PlanVersionView = JSON.parse(readFileSync("tests/unit/fixtures/daily-reviewed-version.json", "utf8"));
const hash = (character = "a") => character.repeat(64);

function completeSummary(): SourceCoverageSummaryView {
  return {
    authorityGranted: false, status: "COMPLETE", coverageComplete: true,
    currentReviewBound: true, canConfirmReview: false, reviewState: "CURRENT", reason: null,
    sourceHash: native.sourceHash!, candidatePlanHash: native.planHash,
    contentHash: native.contentHash!, mappingHash: hash("b"), rulesVersion: "source-coverage-rules-v1",
    coverageEvidenceHash: hash("c"), coverageRevision: 1, coverageBundleHash: hash("d"),
    normalizationHash: null, originalReviewEvidenceHash: native.reviewEvidenceHash!,
    reviewId: native.reviewId!, reviewRevision: native.reviewRevision!,
    coverageReviewReceiptHash: hash("e"), origin: "HUMAN", automaticFidelityVerified: false,
    obligationCount: 1, issueCount: 0, normalizationChangeCount: 0, totalRows: 1,
  };
}

function planSummary(sourceCoverage: SourceCoverageSummaryView): PlanVersionSummary {
  return { id: native.id, planId: native.planId, planHash: native.planHash, version: native.version,
    revision: native.revision, createdAt: native.createdAt, symbol: native.symbol,
    status: "ACTIVE", canActivate: sourceCoverage.currentReviewBound, obsoleteReason: null, sourceCoverage };
}

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

function threeStreams(): SourceCoveragePage {
  const summary: SourceCoverageSummaryView = { ...completeSummary(), status: "BLOCKED", coverageComplete: false,
    currentReviewBound: false, reviewState: "NEEDS_REVIEW", reason: "SOURCE_COVERAGE_REQUIRED",
    coverageReviewReceiptHash: null, issueCount: 1, normalizationChangeCount: 1, totalRows: 3 };
  return { authorityGranted: false, planVersionId: native.id, summary, limit: 50, returnedCount: 3,
    totalRows: 3, nextCursor: null, items: [
      { kind: "OBLIGATION", rowIndex: 0, obligation: {
        version: "source-obligation-v1", rulesVersion: "source-coverage-rules-v1", sourceHash: summary.sourceHash,
        clauseId: "clause-1", start: 0, end: 6, excerpt: "policy", kind: "PREDICATE", scope: "BUY",
        serverState: "UNRESOLVED", semanticsJson: null, groupId: null, relationIds: [hash("1")],
        paths: ["position.max_qty"], obligationId: hash("2"), humanSupplements: [],
        mappingProposal: { proposedDisposition: "CONTEXT", semanticRole: "COMMENTARY",
          reason: "Proposed only; not server treatment", proposedPaths: [] },
      } },
      { kind: "ISSUE", rowIndex: 1, issue: { code: "SOURCE_CONDITION_UNRESOLVED", path: "source.clause-1",
        start: 0, end: 6, message: "The hidden or visible issue still blocks the whole summary." } },
      { kind: "NORMALIZATION_CHANGE", rowIndex: 2, change: { path: "position.max_qty", beforeJson: "null",
        afterJson: "300", reason: "SOURCE_NORMALIZATION", traceRole: "HISTORICAL_INPUT",
        sourceHash: hash("f"), beforeHash: hash("3"), afterHash: hash("4"), evidenceHash: hash("5") } },
    ] };
}

function firstObligation(page: SourceCoveragePage): SourceObligationView {
  const row = page.items.find((item) => item.kind === "OBLIGATION");
  if (!row) throw new Error("test requires an obligation row");
  return row.obligation;
}

function readPage(body: unknown, request?: SourceCoverageRequest) {
  return createPlanApi(vi.fn(async () => response(body))).getSourceCoverage(native.id, request);
}

function nativeDetail(schemaVersion = 5): PlanVersionView {
  const document = JSON.parse(native.planJson);
  return { ...native, planJson: JSON.stringify({ ...document, schema_version: schemaVersion,
    execution_mode: "CONDITION_PLAN", execution_version: `condition-plan-v${schemaVersion - 4}` }),
    sourceCoverage: completeSummary() };
}

describe("shared source summary decoder", () => {
  it.each(Object.keys(completeSummary()))("requires the published %s field, including literal false", (field) => {
    const value = { ...completeSummary() };
    Reflect.deleteProperty(value, field);
    expect(isSourceCoverageSummary(value)).toBe(false);
  });

  it.each([
    { authorityGranted: true }, { authorityGranted: null }, { extra: false },
    { sourceHash: hash("A") }, { candidatePlanHash: "abc" }, { mappingHash: undefined },
    { coverageRevision: 0 }, { coverageRevision: Number.MAX_SAFE_INTEGER + 1 },
    { reviewRevision: -1 }, { rulesVersion: "source-coverage-rules-v2" },
    { reviewId: "not-a-uuid" }, { origin: "HUMAN", automaticFidelityVerified: true },
    { origin: "AI_HISTORICAL", automaticFidelityVerified: true },
    { origin: "AI_NEW", automaticFidelityVerified: true, normalizationHash: null },
    { status: "BLOCKED" }, { coverageComplete: false }, { issueCount: 1, totalRows: 2 },
    { obligationCount: 0, totalRows: 0 }, { obligationCount: 4097, totalRows: 4097 },
    { normalizationChangeCount: 2001, totalRows: 2002 },
    { issueCount: 8193, totalRows: 8194, status: "BLOCKED", coverageComplete: false, currentReviewBound: false, reviewState: "UNKNOWN" },
    { totalRows: 2 }, { reviewState: "NEEDS_REVIEW" }, { coverageReviewReceiptHash: null },
    { contentHash: null }, { coverageBundleHash: null }, { reason: "SOURCE_COVERAGE_STALE" },
    { canConfirmReview: true },
  ])("rejects incoherent source summary %j", (patch) => {
    expect(isSourceCoverageSummary({ ...completeSummary(), ...patch })).toBe(false);
  });

  it("distinguishes unconfirmed and unsaved COMPLETE observations from current review", () => {
    const unconfirmed: SourceCoverageSummaryView = { ...completeSummary(), currentReviewBound: false,
      reviewState: "UNCONFIRMED", reviewId: null, reviewRevision: 0, coverageReviewReceiptHash: null, canConfirmReview: true };
    expect(isSourceCoverageSummary(unconfirmed)).toBe(true);
    expect(isSourceCoverageSummary({ ...unconfirmed, canConfirmReview: false,
      coverageBundleHash: null, coverageRevision: null })).toBe(true);
    expect(isSourceCoverageSummary({ ...completeSummary(), origin: "AI_NEW",
      normalizationHash: hash("f"), automaticFidelityVerified: true })).toBe(true);
  });

  it.each(["LEGACY_UNASSESSED", "UNKNOWN"] as const)("accepts %s as a non-authoritative diagnostic", (status) => {
    const summary = { ...completeSummary(), status, coverageComplete: false, currentReviewBound: false,
      reviewState: "UNKNOWN", origin: null, reason: "SOURCE_COVERAGE_UPGRADE_REQUIRED",
      coverageEvidenceHash: null, coverageRevision: null, coverageBundleHash: null, coverageReviewReceiptHash: null,
      normalizationHash: null, mappingHash: null, rulesVersion: null, obligationCount: 0, totalRows: 0 };
    expect(isSourceCoverageSummary(summary)).toBe(true);
  });
});

describe("read-only source evidence API", () => {
  it("delegates GET with default50 and the exact abort signal, without mutation headers", async () => {
    const body = threeStreams();
    const controller = new AbortController();
    const fetcher = vi.fn<typeof fetch>(async () => response(body));
    const result = await createPlanApi(fetcher).getSourceCoverage(native.id, undefined, { signal: controller.signal });
    expect(fetcher).toHaveBeenCalledExactlyOnceWith(`/api/v1/plan-versions/${native.id}/source-coverage?limit=50`,
      { method: "GET", signal: controller.signal, headers: { Accept: "application/json" } });
    expect(result).toEqual(body);
    expect(Object.isFrozen(result.items)).toBe(true);
    expect(result.summary.coverageComplete).toBe(false);
  });

  it("supports the standalone read-only client and URL-encodes an opaque continuation", async () => {
    const body = threeStreams();
    body.limit = 100; body.items = body.items.slice(1); body.returnedCount = 2;
    const fetcher = vi.fn<typeof fetch>(async () => response(body));
    await expect(createSourceCoverageApi(fetcher).getSourceCoverage(native.id, { limit: 100, cursor: "opaque+/=?" }))
      .resolves.toEqual(body);
    expect(fetcher.mock.calls[0]?.[0]).toBe(`/api/v1/plan-versions/${native.id}/source-coverage?limit=100&cursor=opaque%2B%2F%3D%3F`);
  });

  it("captures first-page identity before a caller can mutate the dispatched request", async () => {
    const page = threeStreams(); page.items = page.items.slice(1); page.returnedCount = 2;
    const request: { cursor?: string } = {};
    const fetcher = vi.fn<typeof fetch>(async () => {
      request.cursor = "changed-after-dispatch";
      return response(page);
    });
    await expect(createSourceCoverageApi(fetcher).getSourceCoverage(native.id, request))
      .rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 200 });
  });

  it.each([{}, { limit: 0 }, { limit: 101 }, { limit: 1.5 }, { limit: Number.NaN },
    { cursor: "" }, { cursor: "😀" }, { cursor: "a".repeat(513) }, { offset: 0 }])(
    "rejects an invalid UUID or request before fetching %j", async (request) => {
      const fetcher = vi.fn<typeof fetch>();
      const api = createSourceCoverageApi(fetcher);
      const id = Object.keys(request).length ? native.id : "invalid";
      await expect(api.getSourceCoverage(id, request)).rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 0 });
      expect(fetcher).not.toHaveBeenCalled();
    },
  );

  it("accepts cursor512 and a byte-packed short page without hiding the whole-summary issue", async () => {
    const page = threeStreams();
    page.items = page.items.slice(0, 1); page.returnedCount = 1; page.nextCursor = "a".repeat(512);
    await expect(readPage(page)).resolves.toEqual(page);
    const continuation = threeStreams();
    continuation.items = continuation.items.slice(1); continuation.returnedCount = 2;
    await expect(readPage(continuation, { cursor: page.nextCursor })).resolves.toEqual(continuation);
  });

  it.each(["authorityGranted", "planVersionId", "summary", "items", "limit", "returnedCount", "totalRows", "nextCursor"])(
    "rejects a missing page field %s", async (field) => {
      const page = threeStreams(); Reflect.deleteProperty(page, field);
      await expect(readPage(page)).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    },
  );

  it.each([
    { authorityGranted: true }, { extra: false }, { planVersionId: "00000000-0000-4000-8000-000000000001" },
    { limit: 100 }, { returnedCount: 2 }, { totalRows: 2 }, { nextCursor: "nonterminal-on-final-page" },
    { nextCursor: "" }, { nextCursor: "a".repeat(513) }, { items: [], returnedCount: 0 },
  ])("rejects incoherent page metadata %j", async (patch) => {
    await expect(readPage({ ...threeStreams(), ...patch })).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("rejects gaps, reordered streams, missing discriminators and unknown nested fields", async () => {
    for (const mutate of [
      (p: SourceCoveragePage) => { p.items[1]!.rowIndex = 0; },
      (p: SourceCoveragePage) => { p.items.reverse(); },
      (p: SourceCoveragePage) => { Reflect.deleteProperty(p.items[0]!, "kind"); },
      (p: SourceCoveragePage) => { Object.assign(p.items[0]!, { extra: false }); },
      (p: SourceCoveragePage) => { Object.assign(firstObligation(p).mappingProposal!, { extra: false }); },
      (p: SourceCoveragePage) => { p.items = [p.items[1]!, p.items[2]!]; p.returnedCount = 2; },
    ]) {
      const page = threeStreams(); mutate(page);
      await expect(readPage(page)).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    }
  });

  it.each([
    { sourceHash: hash("f") }, { rulesVersion: "source-coverage-rules-v2" }, { extra: false },
    { start: -1 }, { end: 0 }, { start: 1, end: 1 }, { end: 150001 }, { end: 7 },
    { excerpt: "😀".repeat(513), end: 513 }, { excerpt: "\ud800", end: 1 },
    { paths: ["a".repeat(513)] }, { paths: Array(513).fill("x") },
    { relationIds: Array(65).fill(hash()) }, { semanticsJson: "x".repeat(8193) },
    { kind: "EXECUTABLE" }, { serverState: "COMPLETE" }, { scope: "CURRENT" },
    { mappingProposal: { proposedDisposition: "CONTEXT", semanticRole: null, reason: "", proposedPaths: [] } },
  ])("rejects invalid obligation data %j", async (patch) => {
    const page = threeStreams(); Object.assign(firstObligation(page), patch);
    await expect(readPage(page)).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("uses code points for excerpt/span bounds and permits relation targets on another page", async () => {
    const page = threeStreams();
    Object.assign(firstObligation(page), { excerpt: "😀".repeat(512), end: 512 });
    await expect(readPage(page)).resolves.toEqual(page);
  });

  it("rejects COMPLETE when a mapped obligation still has UNKNOWN scope", async () => {
    const page = threeStreams();
    page.items = page.items.slice(0, 1); page.returnedCount = 1; page.totalRows = 1;
    page.summary = completeSummary();
    Object.assign(firstObligation(page), { serverState: "MAPPED", scope: "UNKNOWN" });
    await expect(readPage(page)).rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 200 });
  });

  it("binds registered supplement links to the visible exact path and content", async () => {
    const page = threeStreams(); const obligation = firstObligation(page);
    obligation.serverState = "MAPPED_WITH_REGISTERED_SUPPLEMENT";
    const link = { supplementId: "registered-human-1", path: "position.max_qty", candidateContentHash: page.summary.contentHash! };
    obligation.humanSupplements = [link];
    await expect(readPage(page)).resolves.toEqual(page);
    for (const patch of [{ candidateContentHash: hash("f") }, { path: "position.core_target_qty" }, { extra: false }]) {
      obligation.humanSupplements = [{ ...link, ...patch }];
      await expect(readPage(page)).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    }
  });

  it("checks issue paired spans and visible current trace binding without conflating historical input", async () => {
    const page = threeStreams();
    await expect(readPage(page)).resolves.toEqual(page);
    const issue = page.items.find((item) => item.kind === "ISSUE")!.issue;
    for (const patch of [{ start: null }, { end: 0 }, { code: "lowercase" }, { extra: false }]) {
      const before = { ...issue }; Object.assign(issue, patch);
      await expect(readPage(page)).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
      Object.keys(issue).forEach((key) => Reflect.deleteProperty(issue, key)); Object.assign(issue, before);
    }
    const change = page.items.find((item) => item.kind === "NORMALIZATION_CHANGE")!.change;
    change.traceRole = "CURRENT_ASSESSMENT";
    await expect(readPage(page)).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    change.sourceHash = page.summary.sourceHash; page.summary.normalizationHash = change.evidenceHash;
    await expect(readPage(page)).resolves.toEqual(page);
  });

  it("accepts an empty unassessed diagnostic, never an empty page of nonempty evidence", async () => {
    const page = threeStreams();
    page.items = []; page.returnedCount = 0; page.totalRows = 0;
    Object.assign(page.summary, { status: "LEGACY_UNASSESSED", obligationCount: 0, issueCount: 0,
      normalizationChangeCount: 0, totalRows: 0 });
    await expect(readPage(page)).resolves.toEqual(page);
    await expect(readPage(page, { cursor: "old" })).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("applies the independent 1MiB raw budget even when the JSON projection is tiny", async () => {
    const raw = `${JSON.stringify(threeStreams())}${" ".repeat(1_048_576)}`;
    const api = createSourceCoverageApi(vi.fn(async () => new Response(raw)));
    await expect(api.getSourceCoverage(native.id)).rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 200 });
  });

  it.each([[409, "CONFLICT"], [422, "VALIDATION_ERROR"], [500, "INTERNAL_ERROR"]] as const)(
    "preserves structured error %s without turning it into an UNKNOWN grant", async (status, code) => {
      const api = createSourceCoverageApi(vi.fn(async () => response({ error: {
        code, details: [], message: "raw-proof-secret", requestId: "1".repeat(32),
      } }, status)));
      const promise = api.getSourceCoverage(native.id);
      await expect(promise).rejects.toMatchObject({ code, status });
      await expect(promise).rejects.not.toThrow("raw-proof-secret");
    },
  );
});

describe("source-aware plan wire projections", () => {
  it("accepts a current bound ACTIVE summary", async () => {
    const item = planSummary(completeSummary());
    const api = createPlanApi(vi.fn(async () => response({ items: [item], limit: 50, offset: 0, total: 1 })));
    await expect(api.listPlanVersions({ limit: 50, offset: 0 })).resolves.toHaveProperty("items", [item]);
  });

  it("keeps ACTIVE without an obsolete reason when source review is no longer current", async () => {
    const source: SourceCoverageSummaryView = { ...completeSummary(), currentReviewBound: false,
      coverageReviewReceiptHash: null, reviewState: "NEEDS_REVIEW", reason: "SOURCE_COVERAGE_STALE" };
    const item = planSummary(source);
    const api = createPlanApi(vi.fn(async () => response({ items: [item], limit: 50, offset: 0, total: 1 })));
    await expect(api.listPlanVersions({ limit: 50, offset: 0 })).resolves.toHaveProperty("items", [item]);
  });

  it.each([5, 6, 7, 8, 9])("links schema%i native details to source and review identities", async (schema) => {
    const detail = nativeDetail(schema);
    await expect(createPlanApi(vi.fn(async () => response(detail))).getPlanVersion(detail.id)).resolves.toEqual(detail);
    const stale = { ...detail, status: "ACTIVE", canActivate: false,
      sourceCoverage: { ...completeSummary(), currentReviewBound: false, coverageReviewReceiptHash: null,
        reviewState: "NEEDS_REVIEW", reason: "SOURCE_COVERAGE_STALE" } };
    await expect(createPlanApi(vi.fn(async () => response(stale))).getPlanVersion(detail.id)).resolves.toEqual(stale);
  });

  it.each([6, 7, 8, 9])("retains the old schema%i dispatch when the entire source field is absent or null", async (schema) => {
    for (const source of [{}, { sourceCoverage: null }]) {
      const old = { ...native, planJson: JSON.stringify({ schema_version: schema }), ...source };
      await expect(createPlanApi(vi.fn(async () => response(old))).getPlanVersion(old.id)).resolves.toEqual(old);
    }
  });

  it.each(["execution_version", "plan_id", "mapping"])("requires exact source-bearing current %s ownership", async (field) => {
    const detail = nativeDetail(9);
    if (field === "mapping") detail.dailyMapping = { ...detail.dailyMapping!, candidate_content_hash: hash("f") };
    else detail.planJson = JSON.stringify({ ...JSON.parse(detail.planJson), [field]: "different" });
    await expect(createPlanApi(vi.fn(async () => response(detail))).getPlanVersion(detail.id))
      .rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it.each(["sourceHash", "contentHash", "originalReviewEvidenceHash", "reviewId", "reviewRevision", "candidatePlanHash"])(
    "rejects a source summary attached to a different native %s", async (field) => {
      const detail = nativeDetail();
      Object.assign(detail.sourceCoverage!, { [field]: field === "reviewRevision" ? 2 : field === "reviewId"
        ? "00000000-0000-4000-8000-000000000001" : hash("f") });
      await expect(createPlanApi(vi.fn(async () => response(detail))).getPlanVersion(detail.id))
        .rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    },
  );

  it("permits COMPLETE unconfirmed DRAFT while keeping canActivate false", async () => {
    const detail = nativeDetail(); detail.canActivate = false; detail.reviewId = null; detail.reviewRevision = 0;
    detail.sourceCoverage = { ...completeSummary(), reviewId: null, reviewRevision: 0,
      currentReviewBound: false, canConfirmReview: true, reviewState: "UNCONFIRMED", coverageReviewReceiptHash: null };
    await expect(createPlanApi(vi.fn(async () => response(detail))).getPlanVersion(detail.id)).resolves.toEqual(detail);
    detail.dailyIssues = [{ code: "SOURCE_REQUIRED", issue_id: "one", path: "position", reason: "Needs review" }];
    await expect(createPlanApi(vi.fn(async () => response(detail))).getPlanVersion(detail.id))
      .rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("retains all512 native blockers and does not manufacture optional source fields on old reads", async () => {
    const detail = nativeDetail(); detail.canActivate = false;
    detail.validationIssues = Array.from({ length: 512 }, () => ({ activationBlocking: true,
      code: "SOURCE_COVERAGE_REQUIRED", path: "source", message: "Review required", severity: "WARNING" }));
    await expect(createPlanApi(vi.fn(async () => response(detail))).getPlanVersion(detail.id)).resolves.toEqual(detail);
    for (const old of [native, { ...native, sourceCoverage: null }]) {
      const result = await createPlanApi(vi.fn(async () => response(old))).getPlanVersion(old.id);
      expect(result).toEqual(old);
      expect(Object.hasOwn(result, "sourceCoverage")).toBe(Object.hasOwn(old, "sourceCoverage"));
    }
  });

  it("preserves an unchanged old save receipt projection and validates a source-bearing first save", async () => {
    for (const detail of [native, nativeDetail()]) {
      const api = createPlanApi(vi.fn(async () => response(detail)));
      await expect(api.savePlanDraft({ planJson: detail.planJson, sourceText: detail.sourceText, expectedRevision: 0 }, "same-key"))
        .resolves.toEqual(detail);
    }
  });

  it("does not lend current source authority to a historical schema document", async () => {
    const detail = { ...native, sourceCoverage: completeSummary() };
    await expect(createPlanApi(vi.fn(async () => response(detail))).getPlanVersion(detail.id))
      .rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });
});
