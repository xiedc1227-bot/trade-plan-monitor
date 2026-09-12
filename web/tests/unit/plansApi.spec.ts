import { describe, expect, it, vi } from "vitest";

import type {
  ActivePlanView,
  ExplicitPlanRuntimeView,
  PlanDraftCommand,
  PlanImportCommand,
  PlanVersionSummary,
  PlanVersionView,
} from "../../src/api/generated";
import { createPlanApi } from "../../src/api/plans";

const VERSION_ID = "00000000-0000-4000-8000-000000000402";
const TIME = "2026-09-03T10:00:00.000000+08:00";

const version: PlanVersionView = {
  canActivate: true,
  createdAt: TIME,
  id: VERSION_ID,
  planHash: "a".repeat(64),
  planId: "huaya-smart",
  planJson: '{"schema_version":1}',
  reviewIssues: [],
  revision: 0,
  sourceText: "华亚智能交易计划",
  status: "DRAFT",
  symbol: "003043.SZ",
  validationIssues: [],
  version: 1,
};

const inactiveState: ActivePlanView = {
  active: false,
  changedAt: TIME,
  planVersionId: null,
  revision: 0,
  symbol: version.symbol,
};

const explicitRuntime: ExplicitPlanRuntimeView = {
  activationRevision: 1,
  evaluatedAt: "2026-09-03T10:05:00.000000+08:00",
  planHash: "c".repeat(64),
  planVersionId: VERSION_ID,
  ruleOutcomes: [{
    action: "BUY",
    blockers: [],
    conditionCode: "ALL",
    missingInputs: [],
    outcome: "SATISFIED",
    ruleId: "buy-range",
    suppressionReason: null,
  }],
  status: "CURRENT",
  symbol: version.symbol,
  targetBucketEnd: "2026-09-03T10:05:00.000000+08:00",
};

const summary: PlanVersionSummary = {
  canActivate: version.canActivate,
  createdAt: version.createdAt,
  id: version.id,
  planHash: version.planHash,
  planId: version.planId,
  revision: version.revision,
  status: version.status,
  symbol: version.symbol,
  version: version.version,
};

describe("plan API", () => {
  it("queries versions, details, and the durable activation state", async () => {
    const requests: Array<{ init: RequestInit | undefined; url: string }> = [];
    const fetchImplementation = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        requests.push({ init, url });
        if (url.startsWith("/api/v1/plan-versions?")) {
          return jsonResponse({ items: [summary], limit: 20, offset: 0, total: 1 });
        }
        if (url === `/api/v1/plan-versions/${VERSION_ID}`) {
          return jsonResponse(version);
        }
        return jsonResponse(inactiveState);
      },
    ) as typeof fetch;
    const api = createPlanApi(fetchImplementation);

    const page = await api.listPlanVersions({
      canActivate: true,
      limit: 20,
      offset: 0,
      status: "DRAFT",
      symbol: version.symbol,
    });
    const detail = await api.getPlanVersion(VERSION_ID);
    const activeState = await api.getPlanActivationState(version.symbol);

    expect(page.items).toEqual([summary]);
    expect(detail).toEqual(version);
    expect(activeState).toEqual(inactiveState);
    expect(requests.map(({ url }) => url)).toEqual([
      "/api/v1/plan-versions?offset=0&limit=20&symbol=003043.SZ&status=DRAFT&canActivate=true",
      `/api/v1/plan-versions/${VERSION_ID}`,
      "/api/v1/plan-activation-states/003043.SZ",
    ]);
    expect(requests.every(({ init }) => init?.method === "GET")).toBe(true);
  });

  it("sends every mutation with its caller-owned idempotency key", async () => {
    const requests: Array<{ init: RequestInit | undefined; url: string }> = [];
    let activationState: ActivePlanView = inactiveState;
    const savedVersion = {
      ...version,
      id: "00000000-0000-4000-8000-000000000403",
      version: 2,
    };
    const fetchImplementation = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        requests.push({ init, url });
        if (url.endsWith("plan-drafts")) {
          return jsonResponse(savedVersion);
        }
        if (url.endsWith("plan-imports")) {
          return jsonResponse({ ...version, sourceText: version.planJson });
        }
        if (url.endsWith("plan-activations")) {
          activationState = {
            ...inactiveState,
            active: true,
            planVersionId: VERSION_ID,
            revision: 1,
          };
          return jsonResponse(activationState);
        }
        activationState = {
          ...inactiveState,
          changedAt: "2026-09-03T10:01:00.000000+08:00",
          revision: 2,
        };
        return jsonResponse(activationState);
      },
    ) as typeof fetch;
    const api = createPlanApi(fetchImplementation);
    const draft: PlanDraftCommand = {
      basePlanVersionId: VERSION_ID,
      expectedRevision: 0,
      planJson: version.planJson,
      reviewIssues: [],
      sourceText: version.sourceText,
    };
    const imported: PlanImportCommand = {
      document: version.planJson,
      expectedRevision: 0,
      format: "JSON",
      symbol: version.symbol,
    };

    await api.savePlanDraft(draft, "plan-save-1");
    await api.importPlan(imported, "plan-import-1");
    await api.activatePlan(
      { expectedRevision: 0, planVersionId: VERSION_ID },
      "plan-activate-1",
    );
    await api.deactivatePlan(
      { expectedRevision: 1, symbol: version.symbol },
      "plan-deactivate-1",
    );

    expect(requests.map(({ url }) => url)).toEqual([
      "/api/v1/plan-drafts",
      "/api/v1/plan-imports",
      "/api/v1/plan-activations",
      "/api/v1/plan-deactivations",
    ]);
    expect(
      requests.map(({ init }) => (init?.headers as Record<string, string>)["Idempotency-Key"]),
    ).toEqual([
      "plan-save-1",
      "plan-import-1",
      "plan-activate-1",
      "plan-deactivate-1",
    ]);
    expect(requests.map(({ init }) => JSON.parse(String(init?.body)))).toEqual([
      draft,
      imported,
      { expectedRevision: 0, planVersionId: VERSION_ID },
      { expectedRevision: 1, symbol: version.symbol },
    ]);
  });

  it("reads persisted v3 rule outcomes without accepting a legacy-shaped fallback", async () => {
    const api = createPlanApi(vi.fn(async () => jsonResponse(explicitRuntime)) as typeof fetch);
    await expect(api.getExplicitPlanRuntime(version.symbol)).resolves.toEqual(explicitRuntime);
    const malformed = createPlanApi(vi.fn(async () => jsonResponse({
      ...explicitRuntime,
      ruleOutcomes: [{ ...explicitRuntime.ruleOutcomes[0], outcome: "UNKNOWN" }],
    })) as typeof fetch);
    await expect(malformed.getExplicitPlanRuntime(version.symbol)).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
    });
  });

  it("rejects a save response that reuses the immutable base version identity", async () => {
    const api = createPlanApi(
      vi.fn(async () => jsonResponse(version)) as typeof fetch,
    );
    const command: PlanDraftCommand = {
      basePlanVersionId: version.id,
      expectedRevision: 0,
      planJson: version.planJson,
      reviewIssues: [],
      sourceText: version.sourceText,
    };

    await expect(api.savePlanDraft(command, "immutable-base-conflict")).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
      message: "本地监控服务返回了无效响应",
    });
  });

  it("accepts omitted OpenAPI default arrays and their nested default fields", async () => {
    const reviewIssueWithoutResolved = {
      kind: "WARNING" as const,
      material: false,
      path: "entry.condition",
    };
    const detailWithoutDefaultArrays = {
      ...version,
      canActivate: false,
      reviewIssues: [reviewIssueWithoutResolved],
    };
    delete (detailWithoutDefaultArrays as Partial<PlanVersionView>).validationIssues;
    const fetchImplementation = vi.fn(
      async (input: RequestInfo | URL) => {
        if (String(input).startsWith("/api/v1/plan-versions?")) {
          return jsonResponse({ limit: 20, offset: 0, total: 0 });
        }
        return jsonResponse(detailWithoutDefaultArrays);
      },
    ) as typeof fetch;
    const api = createPlanApi(fetchImplementation);

    await expect(api.listPlanVersions({ limit: 20, offset: 0 })).resolves.toEqual({
      limit: 20,
      offset: 0,
      total: 0,
    });
    await expect(api.getPlanVersion(VERSION_ID)).resolves.toEqual(
      detailWithoutDefaultArrays,
    );
  });

  it("compares review issues using the OpenAPI default for resolved", async () => {
    const unresolvedReview = {
      kind: "WARNING" as const,
      material: true,
      path: "entry.condition",
    };
    const response: PlanVersionView = {
      ...version,
      canActivate: false,
      id: "00000000-0000-4000-8000-000000000403",
      reviewIssues: [{ ...unresolvedReview, resolved: false }],
      version: 2,
    };
    const api = createPlanApi(
      vi.fn(async () => jsonResponse(response)) as typeof fetch,
    );
    const command: PlanDraftCommand = {
      basePlanVersionId: version.id,
      expectedRevision: 0,
      planJson: version.planJson,
      reviewIssues: [unresolvedReview],
      sourceText: version.sourceText,
    };

    await expect(api.savePlanDraft(command, "review-default")).resolves.toEqual(response);
  });

  it("enforces current OpenAPI bounds and allowlists on plan responses", async () => {
    const invalidResponses: unknown[] = [
      { ...version, planJson: "{" },
      { ...version, planJson: "x".repeat(262_145) },
      { ...version, sourceText: "x".repeat(262_145) },
      {
        ...version,
        reviewIssues: [
          { kind: "WARNING", material: false, path: "entry secret", resolved: true },
        ],
      },
      {
        ...version,
        validationIssues: [
          {
            activationBlocking: false,
            code: "VALID_CODE",
            message: "invalid path",
            path: "entry/condition",
            severity: "WARNING",
          },
        ],
      },
    ];

    for (const body of invalidResponses) {
      const api = createPlanApi(vi.fn(async () => jsonResponse(body)) as typeof fetch);
      await expect(api.getPlanVersion(VERSION_ID)).rejects.toMatchObject({
        code: "INVALID_RESPONSE",
      });
    }

    const oversizedTotalApi = createPlanApi(
      vi.fn(async () =>
        jsonResponse({ items: [], limit: 20, offset: 0, total: 10_001 }),
      ) as typeof fetch,
    );
    await expect(
      oversizedTotalApi.listPlanVersions({ limit: 20, offset: 0 }),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });

    const impossibleActiveSummaryApi = createPlanApi(
      vi.fn(async () =>
        jsonResponse({
          items: [{ ...summary, canActivate: false, status: "ACTIVE" }],
          limit: 20,
          offset: 0,
          total: 1,
        }),
      ) as typeof fetch,
    );
    await expect(
      impossibleActiveSummaryApi.listPlanVersions({ limit: 20, offset: 0 }),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("accepts the OpenAPI maximum-length validation code", async () => {
    const validationIssue = {
      activationBlocking: false,
      code: `A${"B".repeat(99)}`,
      message: "bounded validation",
      path: "entry.condition.conditions[0]",
      severity: "WARNING" as const,
    };
    const response = { ...version, validationIssues: [validationIssue] };
    const api = createPlanApi(
      vi.fn(async () => jsonResponse(response)) as typeof fetch,
    );

    await expect(api.getPlanVersion(VERSION_ID)).resolves.toEqual(response);
  });

  it("rejects malformed or identity-mismatched responses without exposing them", async () => {
    const api = createPlanApi(
      vi.fn(async () =>
        jsonResponse({
          ...version,
          authorizationToken: "must-not-be-returned",
        }),
      ) as typeof fetch,
    );

    await expect(api.getPlanVersion(VERSION_ID)).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
      message: "本地监控服务返回了无效响应",
    });
  });
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
    status,
  });
}
