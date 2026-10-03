import { describe, expect, it, vi } from "vitest";

import { createAIPlanApi } from "../../src/api/ai";
import partialExtraction from "../fixtures/ai-partial-extraction.json";

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
  it("reads frozen v8 current-family responses without changing their draft or mapping", async () => {
    const result = { ...partialExtraction, promptVersion: "plan-extract-v8" };
    const api = createAIPlanApi(vi.fn(async () => jsonResponse(result)) as typeof fetch);
    await expect(api.getExtraction(result.id)).resolves.toMatchObject({
      promptVersion: "plan-extract-v8", draftPlanJson: result.draftPlanJson,
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
