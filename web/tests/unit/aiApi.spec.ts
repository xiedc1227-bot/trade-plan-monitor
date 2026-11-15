import { describe, expect, it, vi } from "vitest";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

import { createAIPlanApi } from "../../src/api/ai";
import type { SourceCoverageSummaryView } from "../../src/api/generated";
import partialExtraction from "../fixtures/ai-partial-extraction.json";
import buySuspensionExtraction from "../fixtures/ai-buy-suspension-extraction.json";

const runtime = {
  baseUrl: "https://api.deepseek.com/",
  configured: true,
  displayName: "DeepSeek",
  enabled: true,
  maxInputChars: 50_000,
  maxOutputTokens: 4_096,
  model: "deepseek-v4-flash",
  providerId: "00000000-0000-4000-8000-0000000000d5",
  revision: 0,
};

describe("AI plan API", () => {
  it.each(["plan-extract-v8", "plan-extract-v9", "plan-extract-v10", "plan-extract-v11", "plan-extract-v12"])("reads %s current-family responses without changing their draft or mapping", async (promptVersion) => {
    const result = { ...partialExtraction, promptVersion };
    const api = createAIPlanApi(vi.fn(async () => jsonResponse(result)) as typeof fetch);
    await expect(api.getExtraction(result.id)).resolves.toMatchObject({
      promptVersion, draftPlanJson: result.draftPlanJson,
      dailyMapping: result.dailyMapping,
    });
  });
  it.each(["plan-extract-v4", "plan-extract-v5", "plan-extract-v6"])(
    "accepts %s mapping while rejecting a result with neither mapping nor evidence",
    async (promptVersion) => {
      const result = {
        id: "00000000-0000-4000-8000-000000000111", providerId: runtime.providerId,
        status: "SUCCEEDED", submittedAt: "2026-09-14T10:00:00+08:00",
        startedAt: "2026-09-14T10:00:00+08:00", completedAt: "2026-09-14T10:00:01+08:00",
        sourceTextSha256: "a".repeat(64), model: "isolated-v3", promptVersion,
        draftPlanJson: '{"schema_version":3}', evidence: [],
        mapping: { mappingVersion: "plan-mapping-v1", sourceClauses: [{ clauseId: "clause-1", excerpt: "买入100股", start: 0, end: 6 }],
          fieldBindings: [{ path: "rules[0].action.quantity", value: 100, unit: "SHARES", origin: "SOURCE" }] },
      };
      const api = createAIPlanApi(vi.fn(async () => jsonResponse(result)) as typeof fetch);
      await expect(api.getExtraction(result.id)).resolves.toMatchObject({ mapping: result.mapping });
      const malformed = createAIPlanApi(vi.fn(async () => jsonResponse({ ...result, mapping: null })) as typeof fetch);
      await expect(malformed.getExtraction(result.id)).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    },
  );

  it("loads read-only file configuration and submits one idempotent extraction", async () => {
    const requests: Array<{ init: RequestInit | undefined; url: string }> = [];
    const fetchImplementation = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({ init, url });
      if (url === "/api/v1/ai-runtime") {
        return jsonResponse(runtime);
      }
      if (url === "/api/v1/plan-extractions" && init?.method === "POST") {
        return jsonResponse(
          {
            kind: "PLAN_EXTRACTION",
            operationId: "00000000-0000-4000-8000-000000000111",
            status: "QUEUED",
            submittedAt: "2026-09-02T10:00:00+08:00",
          },
          202,
        );
      }
      return jsonResponse({
        assumptions: [],
        completedAt: "2026-09-02T10:00:02+08:00",
        draftPlanJson: null,
        evidence: [],
        id: "00000000-0000-4000-8000-000000000111",
        model: null,
        promptVersion: null,
        providerId: runtime.providerId,
        sourceTextSha256: null,
        startedAt: "2026-09-02T10:00:01+08:00",
        status: "INVALID_OUTPUT",
        submittedAt: "2026-09-02T10:00:00+08:00",
        unmappedText: [],
        usage: null,
        validationIssues: [
          {
            activationBlocking: true,
            code: "AI_OUTPUT_INVALID",
            message: "AI output did not satisfy the extraction contract.",
            path: "draft",
            severity: "ERROR",
          },
        ],
        warnings: [],
      });
    }) as typeof fetch;
    const api = createAIPlanApi(fetchImplementation);

    const configured = await api.getRuntime();
    const receipt = await api.submitExtraction(
      {
        expectedRevision: 0,
        providerId: runtime.providerId,
        sourceText: "华亚智能交易计划",
      },
      "plan-draft-intent-1",
    );
    const extraction = await api.getExtraction(receipt.operationId);

    expect(configured).toEqual(runtime);
    expect(receipt.status).toBe("QUEUED");
    expect(extraction.status).toBe("INVALID_OUTPUT");
    expect(requests[1]?.init?.headers).toEqual({
      Accept: "application/json",
      "Content-Type": "application/json",
      "Idempotency-Key": "plan-draft-intent-1",
    });
    expect(JSON.parse(String(requests[1]?.init?.body))).toEqual({
      expectedRevision: 0,
      providerId: runtime.providerId,
      sourceText: "华亚智能交易计划",
    });
  });

  it("accepts configured alternative model summaries", async () => {
    const proRuntime = {
      ...runtime,
      displayName: "DeepSeek Pro",
      model: "deepseek-v4-pro",
      providerId: "b5399495-ef52-58ba-b975-df01c6d65b8c",
    };
    const fetchImplementation = vi.fn(async () =>
      jsonResponse({ ...runtime, alternativeProviders: [proRuntime] }),
    ) as typeof fetch;

    const configured = await createAIPlanApi(fetchImplementation).getRuntime();

    expect(configured.alternativeProviders).toEqual([proRuntime]);
  });

  it("rejects extra fields in an alternative model summary", async () => {
    const fetchImplementation = vi.fn(async () =>
      jsonResponse({
        ...runtime,
        alternativeProviders: [{ ...runtime, apiKey: "must-not-cross-boundary" }],
      }),
    ) as typeof fetch;

    await expect(createAIPlanApi(fetchImplementation).getRuntime()).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
    });
  });

  it("rejects duplicate provider identities across runtime summaries", async () => {
    const fetchImplementation = vi.fn(async () =>
      jsonResponse({ alternativeProviders: [runtime], ...runtime }),
    ) as typeof fetch;

    await expect(createAIPlanApi(fetchImplementation).getRuntime()).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
    });
  });
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
    status,
  });
}

function sourceSummary(status: "COMPLETE" | "BLOCKED" | "UNKNOWN" = "BLOCKED"): SourceCoverageSummaryView {
  const complete = status === "COMPLETE";
  return {
    authorityGranted: false, status, coverageComplete: complete, currentReviewBound: false,
    canConfirmReview: false, reviewState: complete ? "UNCONFIRMED" : "UNKNOWN",
    reason: status === "UNKNOWN" ? "SOURCE_COVERAGE_STALE" : complete ? null : "SOURCE_COVERAGE_REQUIRED",
    sourceHash: partialExtraction.sourceTextSha256, candidatePlanHash: "a".repeat(64),
    contentHash: partialExtraction.dailyMapping.candidate_content_hash, mappingHash: "b".repeat(64),
    rulesVersion: "source-coverage-rules-v1", coverageEvidenceHash: status === "UNKNOWN" ? null : "c".repeat(64),
    coverageRevision: null, coverageBundleHash: null, normalizationHash: null,
    originalReviewEvidenceHash: "d".repeat(64), reviewId: null, reviewRevision: 0,
    coverageReviewReceiptHash: null, origin: "AI_NEW", automaticFidelityVerified: false,
    obligationCount: status === "UNKNOWN" ? 0 : 1, issueCount: status === "BLOCKED" ? 1 : 0,
    normalizationChangeCount: 0, totalRows: status === "UNKNOWN" ? 0 : complete ? 1 : 2,
  };
}

function readExtraction<T extends { id: string }>(body: T) {
  return createAIPlanApi(vi.fn(async () => jsonResponse(body))).getExtraction(body.id);
}

function noResult(status: string) {
  return { id: partialExtraction.id, providerId: runtime.providerId, status,
    submittedAt: partialExtraction.submittedAt,
    startedAt: status === "QUEUED" ? null : partialExtraction.startedAt,
    completedAt: ["QUEUED", "RUNNING"].includes(status) ? null : partialExtraction.completedAt };
}

describe("current-only buy suspension extraction", () => {
  it.each(["captured", "absent", "null"])("preserves the actual v13 server response with %s source proof", async (proof) => {
    const value: Record<string, unknown> = structuredClone(buySuspensionExtraction);
    if (proof === "absent") delete value.sourceCoverage;
    if (proof === "null") value.sourceCoverage = null;
    const result = await readExtraction(value as typeof buySuspensionExtraction);
    expect(result).toEqual(value);
    expect(createHash("sha256").update(result.draftPlanJson!).digest("hex")).toBe(
      createHash("sha256").update(buySuspensionExtraction.draftPlanJson).digest("hex"));
    const draft = JSON.parse(result.draftPlanJson!);
    expect(draft.buy_suspension).toEqual({ condition: {
      type: "MINUTE_CLOSE_BELOW", timeframe_minutes: 5, price_fen: 2420,
    }, effective_from: "2026-09-30T09:30:00+08:00" });
    expect(result.dailyMapping).toEqual(buySuspensionExtraction.dailyMapping);
    expect(result.validationIssues).toEqual(buySuspensionExtraction.validationIssues);
  });

  it.each([null, { condition: null, effective_from: null }])("retains unresolved/absent guard %j without inventing clarification", async (guard) => {
    const value = { ...buySuspensionExtraction, sourceCoverage: null, draftPlanJson: JSON.stringify({
      ...JSON.parse(buySuspensionExtraction.draftPlanJson), buy_suspension: guard,
    }) };
    await expect(readExtraction(value)).resolves.toEqual(value);
  });

  it.each(["plan-extract-v8", "plan-extract-v9", "plan-extract-v10", "plan-extract-v11", "plan-extract-v12"])(
    "rejects Schema10 under %s even without captured source evidence", async (promptVersion) => {
      for (const sourceCoverage of [undefined, buySuspensionExtraction.sourceCoverage]) {
        await expect(readExtraction({ ...buySuspensionExtraction, promptVersion, sourceCoverage }))
          .rejects.toMatchObject({ code: "INVALID_RESPONSE" });
      }
    });

  it.each([5, 6, 7, 8, 9])("rejects v13 paired with legacy Schema%i", async (schema_version) => {
    const value = { ...buySuspensionExtraction, sourceCoverage: null, draftPlanJson: JSON.stringify({
      ...JSON.parse(partialExtraction.draftPlanJson), schema_version,
      execution_version: `condition-plan-v${schema_version - 4}`,
    }) };
    await expect(readExtraction(value)).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it.each([
    { execution_mode: "DAILY_CLOSE_PLAN" }, { execution_version: "condition-plan-v1" },
    { schema_version: "10" }, { reference_market: null },
    { contract_version: "plan-buy-suspension-extraction-v1" },
    { buy_suspension: { condition: null } },
    { buy_suspension: { condition: { type: "MINUTE_CLOSE_ABOVE", timeframe_minutes: 5, price_fen: 2420 }, effective_from: null } },
    { buy_suspension: { condition: { type: "MINUTE_CLOSE_BELOW", timeframe_minutes: 1, price_fen: 2420 }, effective_from: null } },
    { buy_suspension: { condition: null, effective_from: "2026-09-30T09:31:00+08:00" } },
    { buy_suspension: { condition: null, effective_from: "2026-09-30T01:30:00Z" } },
    { buy_suspension: { condition: null, effective_from: "2026-09-30T09:30:00.000001+08:00" } },
  ])("rejects an incompatible v13 document without dropping fields %j", async (patch) => {
    const value = { ...buySuspensionExtraction, sourceCoverage: null, draftPlanJson: JSON.stringify({
      ...JSON.parse(buySuspensionExtraction.draftPlanJson), ...patch,
    }) };
    await expect(readExtraction(value)).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("rejects invented envelope, human supplement and saved replacement authority", async () => {
    for (const patch of [
      { contractVersion: "plan-buy-suspension-extraction-v1" },
      { buySuspensionReplacementBinding: { authority_granted: true } },
      { dailyMapping: { ...buySuspensionExtraction.dailyMapping, supplements: [{ supplement_id: "invented" }] } },
    ]) {
      await expect(readExtraction({ ...buySuspensionExtraction, sourceCoverage: null, ...patch }))
        .rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    }
  });
});

describe("captured extraction source evidence", () => {
  it.each(["COMPLETE", "BLOCKED", "UNKNOWN"] as const)("retains the SUCCEEDED candidate with %s source evidence", async (status) => {
    const value = { ...partialExtraction, sourceCoverage: sourceSummary(status) };
    await expect(readExtraction(value)).resolves.toEqual(value);
  });

  it.each(["QUEUED", "RUNNING", "INVALID_OUTPUT", "PROVIDER_ERROR", "CANCELLED"])(
    "does not expose a valid current daily mapping on %s", async (status) => {
      const value = { ...noResult(status), dailyMapping: partialExtraction.dailyMapping };
      await expect(readExtraction(value)).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    },
  );

  it.each([5, 6, 7, 8, 9])("accepts source-bearing current schema%i with its exact execution version", async (schema) => {
    const value = { ...partialExtraction, sourceCoverage: sourceSummary(), draftPlanJson: JSON.stringify({
      ...JSON.parse(partialExtraction.draftPlanJson), schema_version: schema, execution_version: `condition-plan-v${schema - 4}`,
    }) };
    await expect(readExtraction(value)).resolves.toEqual(value);
  });

  it.each(["plan-extract-v8", "plan-extract-v9", "plan-extract-v10", "plan-extract-v11", "plan-extract-v12"])(
    "accepts the current %s family without equating transport success with source completeness", async (promptVersion) => {
      const value = { ...partialExtraction, promptVersion, sourceCoverage: sourceSummary() };
      const result = await readExtraction(value);
      expect(result.status).toBe("SUCCEEDED");
      expect(result.draftPlanJson).toBe(partialExtraction.draftPlanJson);
      expect(result.dailyMapping).toEqual(partialExtraction.dailyMapping);
      expect(result.validationIssues).toEqual(partialExtraction.validationIssues);
      expect(result.sourceCoverage?.coverageComplete).toBe(false);
    },
  );

  it.each([
    { sourceHash: "f".repeat(64) }, { contentHash: "f".repeat(64) },
    { coverageBundleHash: "f".repeat(64) }, { coverageRevision: 1 },
    { reviewId: "00000000-0000-4000-8000-000000000001" }, { reviewRevision: 1 },
    { coverageReviewReceiptHash: "f".repeat(64) },
    { authorityGranted: true }, { extra: false },
  ])("rejects unrelated source evidence or a saved-state field %j", async (patch) => {
    const value = { ...partialExtraction, sourceCoverage: { ...sourceSummary("COMPLETE"), ...patch } };
    await expect(readExtraction(value)).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("rejects otherwise coherent CURRENT and confirmation observations on unsaved extraction", async () => {
    for (const sourceCoverage of [
      { ...sourceSummary("COMPLETE"), currentReviewBound: true, reviewState: "CURRENT",
        reviewId: "00000000-0000-4000-8000-000000000001", reviewRevision: 1,
        coverageRevision: 1, coverageBundleHash: "e".repeat(64), coverageReviewReceiptHash: "f".repeat(64) },
      { ...sourceSummary("COMPLETE"), canConfirmReview: true, coverageRevision: 1, coverageBundleHash: "e".repeat(64) },
      { ...sourceSummary("UNKNOWN"), status: "LEGACY_UNASSESSED" },
    ]) {
      await expect(readExtraction({ ...partialExtraction, sourceCoverage })).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    }
  });

  it.each(["HUMAN", "AI_HISTORICAL"] as const)("does not promote %s provenance to automatic fidelity", async (origin) => {
    const value = { ...partialExtraction, sourceCoverage: { ...sourceSummary("COMPLETE"), origin } };
    await expect(readExtraction(value)).resolves.toEqual(value);
    await expect(readExtraction({ ...value, sourceCoverage: { ...value.sourceCoverage,
      normalizationHash: "f".repeat(64), automaticFidelityVerified: true } }))
      .rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("retains verified automatic fidelity and also unaccepted captured normalization changes", async () => {
    const complete = { ...partialExtraction, sourceCoverage: { ...sourceSummary("COMPLETE"),
      normalizationHash: "f".repeat(64), automaticFidelityVerified: true } };
    await expect(readExtraction(complete)).resolves.toEqual(complete);
    const blocked = { ...partialExtraction, sourceCoverage: { ...sourceSummary(), normalizationChangeCount: 1, totalRows: 3 } };
    await expect(readExtraction(blocked)).resolves.toEqual(blocked);
    expect(blocked.sourceCoverage.normalizationHash).toBeNull();
  });

  it.each([
    { schema_version: 4 }, { schema_version: 10 }, { schema_version: 5.5 }, { schema_version: "5" },
    { execution_mode: "DAILY_CLOSE_PLAN" }, { execution_version: "condition-plan-v2" },
  ])("rejects source evidence attached to an incompatible current document %j", async (patch) => {
    const value = { ...partialExtraction, sourceCoverage: sourceSummary(), draftPlanJson: JSON.stringify({
      ...JSON.parse(partialExtraction.draftPlanJson), ...patch,
    }) };
    await expect(readExtraction(value)).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("rejects malformed JSON, wrong mapping content and invented provider supplements", async () => {
    for (const patch of [
      { draftPlanJson: "{" },
      { dailyMapping: { ...partialExtraction.dailyMapping, candidate_content_hash: "f".repeat(64) } },
      { dailyMapping: { ...partialExtraction.dailyMapping, candidate_content_hash: null } },
      { dailyMapping: { ...partialExtraction.dailyMapping, supplements: [{ supplement_id: "invented-human" }] } },
    ]) {
      await expect(readExtraction({ ...partialExtraction, sourceCoverage: sourceSummary(), ...patch }))
        .rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    }
  });

  it.each([undefined, null, "daily-mapping-v2"])("rejects a source-bearing mapping with header %s", async (mappingVersion) => {
    const dailyMapping = { ...partialExtraction.dailyMapping, mapping_version: mappingVersion };
    await expect(readExtraction({ ...partialExtraction, sourceCoverage: sourceSummary(), dailyMapping }))
      .rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it.each(["QUEUED", "RUNNING", "INVALID_OUTPUT", "PROVIDER_ERROR", "CANCELLED"])(
    "keeps result-free %s compatible with absent/null fields and rejects any captured proof", async (status) => {
      for (const fields of [{}, { dailyMapping: null, sourceCoverage: null }]) {
        const value = { ...noResult(status), ...fields };
        await expect(readExtraction(value)).resolves.toEqual(value);
      }
      await expect(readExtraction({ ...noResult(status), sourceCoverage: sourceSummary() }))
        .rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    },
  );

  it.each(["plan-extract-v4", "plan-extract-v5", "plan-extract-v6"])(
    "preserves old %s no-summary/null wire but cannot attach current source evidence", async (promptVersion) => {
      const legacy = { ...partialExtraction, promptVersion, draftPlanJson: '{"schema_version":3}', dailyMapping: null,
        mapping: { mappingVersion: "plan-mapping-v1", sourceClauses: [{ clauseId: "clause-1", excerpt: "买入100股", start: 0, end: 6 }],
          fieldBindings: [{ path: "rules[0].action.quantity", value: 100, unit: "SHARES", origin: "SOURCE" }] } };
      for (const fields of [{}, { sourceCoverage: null }]) {
        const value = { ...legacy, ...fields };
        await expect(readExtraction(value)).resolves.toEqual(value);
      }
      await expect(readExtraction({ ...legacy, sourceCoverage: sourceSummary() })).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    },
  );

  it("preserves source field omission, rejects unrelated fields and pins the original golden bytes", async () => {
    for (const value of [partialExtraction, { ...partialExtraction, sourceCoverage: null }]) {
      const result = await readExtraction(value);
      expect(result).toEqual(value);
      expect(Object.hasOwn(result, "sourceCoverage")).toBe(Object.hasOwn(value, "sourceCoverage"));
    }
    await expect(readExtraction({ ...partialExtraction, sourceCoverage: sourceSummary(), extra: false }))
      .rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    expect(createHash("sha256").update(readFileSync("tests/fixtures/ai-partial-extraction.json")).digest("hex"))
      .toBe("2e9d713b607048f01690db94be61db08553454f1b56b218f4c0bff22da621209");
  });
});
