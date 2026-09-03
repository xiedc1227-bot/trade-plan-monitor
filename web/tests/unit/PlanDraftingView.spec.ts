import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  ActivePlanView,
  ConfiguredAIRuntimeView,
  OperationReceipt,
  PlanExtractionView,
  PlanVersionPage,
  PlanVersionSummary,
  PlanVersionView,
} from "../../src/api/generated";
import type { AIPlanApi } from "../../src/api/ai";
import { ApiClientError, type PlanApi } from "../../src/api/plans";
import PlanDraftingView from "../../src/views/PlanDraftingView.vue";

const PROVIDER_ID = "00000000-0000-4000-8000-0000000000d5";
const OPERATION_ID = "00000000-0000-4000-8000-000000000201";
const PLAN_VERSION_ID = "00000000-0000-4000-8000-000000000402";

const runtime: ConfiguredAIRuntimeView = {
  baseUrl: "https://api.deepseek.com/",
  configured: true,
  displayName: "DeepSeek",
  enabled: true,
  maxInputChars: 50_000,
  maxOutputTokens: 4_096,
  model: "deepseek-v4-flash",
  providerId: PROVIDER_ID,
  revision: 0,
};

const receipt: OperationReceipt = {
  kind: "PLAN_EXTRACTION",
  operationId: OPERATION_ID,
  status: "QUEUED",
  submittedAt: "2026-09-02T09:00:00+08:00",
};

const invalidExtraction: PlanExtractionView = {
  assumptions: [],
  completedAt: "2026-09-02T09:00:02+08:00",
  draftPlanJson: null,
  evidence: [],
  id: OPERATION_ID,
  model: null,
  promptVersion: null,
  providerId: PROVIDER_ID,
  sourceTextSha256: null,
  startedAt: "2026-09-02T09:00:01+08:00",
  status: "INVALID_OUTPUT",
  submittedAt: receipt.submittedAt,
  unmappedText: [],
  usage: null,
  validationIssues: [],
  warnings: [],
};

const planVersion: PlanVersionView = {
  canActivate: true,
  createdAt: "2026-09-03T10:00:00.000000+08:00",
  id: PLAN_VERSION_ID,
  planHash: "a".repeat(64),
  planId: "huaya-smart",
  planJson: JSON.stringify({
    activation: { mode: "MANUAL" },
    blockers: { condition: { conditions: [], type: "ALL" } },
    entry: { condition: { conditions: [], type: "ALL" } },
    levels: {
      low_buy: { high_fen: 6450, include_high: true, include_low: true, low_fen: 6300 },
      pressure: { high_fen: 7020, include_high: true, include_low: true, low_fen: 6880 },
      pressure_reference_fen: 6906,
      risk_line_fen: 6080,
    },
    market: "SZSE",
    metadata: { reference_price_fen: 6660, report_at: "2026-08-06T01:16:00+08:00" },
    monitoring: { indicator_formula_version: "ta-v1", timeframe_minutes: 5 },
    name: "华亚智能审核方案",
    plan_id: "huaya-smart",
    position: { core_target_qty: 100, lot_size: 100, max_qty: 200, tactical_target_qty: 100 },
    reduction: { condition: { conditions: [], type: "ALL" } },
    risk: { condition: { level: "RISK_LINE", type: "OFFICIAL_CLOSE_BELOW_LEVEL" } },
    schema_version: 1,
    symbol: "003043.SZ",
    version: 1,
  }),
  reviewIssues: [],
  revision: 0,
  sourceText: "华亚智能交易计划",
  status: "DRAFT",
  symbol: "003043.SZ",
  validationIssues: [],
  version: 1,
};

const successfulExtraction: PlanExtractionView = {
  assumptions: [],
  completedAt: "2026-09-02T09:00:02+08:00",
  draftPlanJson: planVersion.planJson,
  evidence: [
    {
      end: 8,
      excerpt: "华亚智能交易计划",
      path: "draft",
      start: 0,
    },
  ],
  id: OPERATION_ID,
  model: "deepseek-v4-flash",
  promptVersion: "plan-extract-v1",
  providerId: PROVIDER_ID,
  sourceTextSha256: "b".repeat(64),
  startedAt: "2026-09-02T09:00:01+08:00",
  status: "SUCCEEDED",
  submittedAt: receipt.submittedAt,
  unmappedText: [],
  usage: null,
  validationIssues: [
    {
      activationBlocking: true,
      code: "AI_EVIDENCE_REVIEW_REQUIRED",
      message: "必须由用户审核 AI 字段证据。",
      path: "draft",
      severity: "WARNING",
    },
  ],
  warnings: [],
};

const planPage: PlanVersionPage = {
  items: [planSummary(planVersion)],
  limit: 100,
  offset: 0,
  total: 1,
};

function planSummary(plan: PlanVersionView): PlanVersionSummary {
  return {
    canActivate: plan.canActivate,
    createdAt: plan.createdAt,
    id: plan.id,
    planHash: plan.planHash,
    planId: plan.planId,
    revision: plan.revision,
    status: plan.status,
    symbol: plan.symbol,
    version: plan.version,
  };
}

const inactiveState: ActivePlanView = {
  active: false,
  changedAt: "2026-09-03T10:00:00.000000+08:00",
  planVersionId: null,
  revision: 0,
  symbol: planVersion.symbol,
};

function apiWith(overrides: Partial<AIPlanApi> = {}): AIPlanApi {
  const unused = vi.fn(() => Promise.reject(new Error("unexpected API call")));
  return {
    getExtraction: unused,
    getRuntime: unused,
    submitExtraction: unused,
    ...overrides,
  } as AIPlanApi;
}

function planApiWith(overrides: Partial<PlanApi> = {}): PlanApi {
  const unused = vi.fn(() => Promise.reject(new Error("unexpected plan API call")));
  return {
    activatePlan: unused,
    deactivatePlan: unused,
    getPlanActivationState: unused,
    getPlanVersion: vi.fn().mockResolvedValue(planVersion),
    importPlan: unused,
    listPlanVersions: vi.fn().mockResolvedValue({ ...planPage, items: [], total: 0 }),
    savePlanDraft: unused,
    ...overrides,
  } as PlanApi;
}

describe("PlanDraftingView", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("loads the file-configured AI runtime and completes the Web extraction flow", async () => {
    const getRuntime = vi.fn().mockResolvedValue(runtime);
    const submitExtraction = vi.fn().mockResolvedValue(receipt);
    const getExtraction = vi.fn().mockResolvedValue(invalidExtraction);
    const api = apiWith({ getExtraction, getRuntime, submitExtraction });
    const wrapper = mount(PlanDraftingView, {
      props: {
        api,
        createIdempotencyKey: () => "web-plan-intent-001",
        planApi: planApiWith(),
        pollIntervalMs: 0,
      },
    });
    await flushPromises();

    expect(wrapper.text()).toContain("DeepSeek");
    expect(wrapper.text()).toContain("deepseek-v4-flash");
    expect(wrapper.text()).toContain("配置文件只读");
    expect(wrapper.find("#provider-secret").exists()).toBe(false);

    const sourceText = "华亚智能：回踩 20.10 至 20.50 分批关注。";
    await wrapper.get<HTMLTextAreaElement>("#plan-source-text").setValue(sourceText);
    await wrapper.get('[data-testid="source-editor"]').trigger("submit");
    await flushPromises();

    expect(submitExtraction).toHaveBeenCalledWith(
      { expectedRevision: 0, providerId: PROVIDER_ID, sourceText },
      "web-plan-intent-001",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(getExtraction).toHaveBeenCalledWith(
      OPERATION_ID,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(wrapper.get('[role="alert"]').text()).toContain("AI 输出未通过封闭契约校验");
    wrapper.unmount();
  });

  it("requires an explicit handoff before an AI result can be reviewed and saved", async () => {
    const sourceText = "华亚智能交易计划";
    const listPlanVersions = vi
      .fn()
      .mockResolvedValueOnce({ ...planPage, items: [], total: 0 })
      .mockResolvedValueOnce(planPage);
    const getPlanActivationState = vi
      .fn()
      .mockRejectedValueOnce(
        new ApiClientError({
          code: "NOT_FOUND",
          message: "请求的资源不存在",
          status: 404,
        }),
      )
      .mockResolvedValueOnce(inactiveState);
    const savePlanDraft = vi.fn().mockResolvedValue(planVersion);
    const activatePlan = vi.fn();
    const wrapper = mount(PlanDraftingView, {
      props: {
        api: apiWith({
          getExtraction: vi.fn().mockResolvedValue(successfulExtraction),
          getRuntime: vi.fn().mockResolvedValue(runtime),
          submitExtraction: vi.fn().mockResolvedValue(receipt),
        }),
        createIdempotencyKey: () => "ai-extraction-key",
        createPlanIdempotencyKey: () => "ai-reviewed-draft-key",
        planApi: planApiWith({
          activatePlan,
          getPlanActivationState,
          listPlanVersions,
          savePlanDraft,
        }),
        pollIntervalMs: 0,
      },
    });
    await flushPromises();

    await wrapper.get<HTMLTextAreaElement>("#plan-source-text").setValue(sourceText);
    await wrapper.get('[data-testid="source-editor"]').trigger("submit");
    await flushPromises();

    expect(wrapper.get('[data-testid="enter-structured-review"]').text()).toContain(
      "进入结构化审核",
    );
    expect(wrapper.find("#ai-review-plan-name").exists()).toBe(false);
    expect(savePlanDraft).not.toHaveBeenCalled();
    expect(activatePlan).not.toHaveBeenCalled();

    await wrapper.get('[data-testid="enter-structured-review"]').trigger("click");
    expect(wrapper.get<HTMLInputElement>("#ai-review-plan-name").element.value).toBe(
      "华亚智能审核方案",
    );
    expect(wrapper.get('[data-testid="ai-review-save-draft"]').text()).toContain(
      "保存为待审核版本",
    );
    expect(savePlanDraft).not.toHaveBeenCalled();
    expect(activatePlan).not.toHaveBeenCalled();

    await wrapper.get('[data-issue-key="MISSING_EVIDENCE:draft"] button').trigger("click");
    await wrapper.get('[data-testid="ai-review-save-draft"]').trigger("click");
    await flushPromises();

    expect(savePlanDraft).toHaveBeenCalledWith(
      {
        expectedRevision: 0,
        planJson: planVersion.planJson,
        reviewIssues: [
          { kind: "MISSING_EVIDENCE", material: true, path: "draft", resolved: true },
        ],
        sourceText,
      },
      "ai-reviewed-draft-key",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(savePlanDraft.mock.calls[0]?.[0]).not.toHaveProperty("basePlanVersionId");
    expect(activatePlan).not.toHaveBeenCalled();
    expect(wrapper.get('[data-testid="request-activation"]').text()).toContain("激活");
    wrapper.unmount();
  });

  it("shows a fixed safe message when startup configuration cannot be loaded", async () => {
    const api = apiWith({ getRuntime: vi.fn().mockRejectedValue(new Error("TOKEN=secret")) });
    const wrapper = mount(PlanDraftingView, { props: { api, planApi: planApiWith() } });
    await flushPromises();

    expect(wrapper.get('[role="alert"]').text()).toContain("AI 配置加载失败");
    expect(wrapper.text()).not.toContain("TOKEN=secret");
    expect(wrapper.find("#plan-source-text").exists()).toBe(false);
    wrapper.unmount();
  });

  it("releases the editor when status polling becomes uncertain without claiming cancellation", async () => {
    const api = apiWith({
      getExtraction: vi.fn().mockRejectedValue(new Error("Authorization: Bearer secret")),
      getRuntime: vi.fn().mockResolvedValue(runtime),
      submitExtraction: vi.fn().mockResolvedValue(receipt),
    });
    const wrapper = mount(PlanDraftingView, {
      props: {
        api,
        createIdempotencyKey: () => "uncertain-plan-intent",
        planApi: planApiWith(),
        pollIntervalMs: 0,
      },
    });
    await flushPromises();
    await wrapper.get<HTMLTextAreaElement>("#plan-source-text").setValue("华亚智能交易计划");
    await wrapper.get('[data-testid="source-editor"]').trigger("submit");
    await flushPromises();

    expect(wrapper.get('[role="alert"]').text()).toContain("无法确认 AI 提取状态");
    expect(wrapper.text()).toContain("服务端任务可能仍会继续");
    expect(wrapper.text()).not.toContain("Authorization");
    expect(wrapper.text()).not.toContain("提取已取消");
    expect(wrapper.get<HTMLTextAreaElement>("#plan-source-text").element.disabled).toBe(false);
    wrapper.unmount();
  });

  it("imports JSON or YAML with an explicit target symbol without parsing it in the browser", async () => {
    const listPlanVersions = vi
      .fn()
      .mockResolvedValueOnce({ ...planPage, items: [], total: 0 })
      .mockResolvedValueOnce(planPage);
    const importPlan = vi.fn().mockResolvedValue(planVersion);
    const planApi = planApiWith({
      getPlanActivationState: vi.fn().mockResolvedValue(inactiveState),
      importPlan,
      listPlanVersions,
    });
    const wrapper = mount(PlanDraftingView, {
      props: {
        api: apiWith({ getRuntime: vi.fn().mockResolvedValue(runtime) }),
        createPlanIdempotencyKey: () => "portable-import-key",
        planApi,
      },
    });
    await flushPromises();
    const document = "schema_version: 1\nplan_id: huaya-smart\nsymbol: 003043.SZ\n";

    await wrapper.get<HTMLSelectElement>("#portable-plan-import-format").setValue("YAML");
    await wrapper
      .get<HTMLTextAreaElement>("#portable-plan-import-document")
      .setValue(document);
    expect(
      wrapper.get<HTMLButtonElement>('[data-testid="plan-import-form"] button[type="submit"]')
        .element.disabled,
    ).toBe(true);
    await wrapper
      .get<HTMLInputElement>("#portable-plan-import-symbol")
      .setValue(planVersion.symbol);
    await wrapper.get('[data-testid="plan-import-form"]').trigger("submit");
    await flushPromises();

    expect(importPlan).toHaveBeenCalledWith(
      { document, expectedRevision: 0, format: "YAML", symbol: planVersion.symbol },
      "portable-import-key",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(wrapper.text()).toContain("v1 · 003043.SZ");
    wrapper.unmount();
  });

  it("downloads the canonical server document using the selected portable format", async () => {
    const createObjectURL = vi.fn((_blob: Blob) => "blob:plan-export");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
    const downloads: { download: string; href: string }[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function click(
      this: HTMLAnchorElement,
    ) {
      downloads.push({ download: this.download, href: this.href });
    });
    const wrapper = mount(PlanDraftingView, {
      props: {
        api: apiWith({ getRuntime: vi.fn().mockResolvedValue(runtime) }),
        planApi: planApiWith({
          getPlanActivationState: vi.fn().mockResolvedValue(inactiveState),
          listPlanVersions: vi.fn().mockResolvedValue(planPage),
        }),
      },
    });
    await flushPromises();

    await wrapper.get<HTMLSelectElement>("#plan-export-format").setValue("YAML");
    await wrapper.get('[data-testid="export-plan"]').trigger("click");

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    const call = createObjectURL.mock.calls[0];
    if (call === undefined) throw new Error("plan export did not create a download blob");
    const [blob] = call;
    expect(blob.type).toBe("application/yaml;charset=utf-8");
    expect(await blob.text()).toBe(planVersion.planJson);
    expect(downloads).toEqual([
      { download: `trade-plan-${PLAN_VERSION_ID}.yaml`, href: "blob:plan-export" },
    ]);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:plan-export");
    wrapper.unmount();
  });

  it("keeps cross-symbol import reachable with existing versions and preflights a missing target state", async () => {
    const targetSymbol = "600000.SH";
    const importedVersion: PlanVersionView = {
      ...planVersion,
      id: "00000000-0000-4000-8000-000000000404",
      planHash: "b".repeat(64),
      planId: "pudong-bank",
      planJson: JSON.stringify({
        ...JSON.parse(planVersion.planJson),
        market: "SSE",
        name: "浦发银行审核方案",
        plan_id: "pudong-bank",
        symbol: targetSymbol,
      }),
      sourceText: "浦发银行交易计划",
      symbol: targetSymbol,
    };
    const importedPage: PlanVersionPage = {
      ...planPage,
      items: [planSummary(importedVersion), planSummary(planVersion)],
      total: 2,
    };
    let targetStateReads = 0;
    const getPlanActivationState = vi.fn(async (symbol: string) => {
      if (symbol === planVersion.symbol) return inactiveState;
      if (symbol !== targetSymbol) throw new Error("unexpected symbol");
      targetStateReads += 1;
      if (targetStateReads === 1) {
        throw new ApiClientError({
          code: "NOT_FOUND",
          message: "请求的资源不存在",
          status: 404,
        });
      }
      return { ...inactiveState, symbol: targetSymbol };
    });
    const importPlan = vi.fn().mockResolvedValue(importedVersion);
    const planApi = planApiWith({
      getPlanActivationState,
      getPlanVersion: vi.fn(async (id: string) =>
        id === importedVersion.id ? importedVersion : planVersion,
      ),
      importPlan,
      listPlanVersions: vi
        .fn()
        .mockResolvedValueOnce(planPage)
        .mockResolvedValueOnce(importedPage),
    });
    const wrapper = mount(PlanDraftingView, {
      props: {
        api: apiWith({ getRuntime: vi.fn().mockResolvedValue(runtime) }),
        createPlanIdempotencyKey: () => "cross-symbol-import-key",
        planApi,
      },
    });
    await flushPromises();

    expect(wrapper.text()).toContain("v1 · 003043.SZ");
    expect(wrapper.get("#portable-plan-import-title").text()).toBe("导入计划版本");
    await wrapper
      .get<HTMLInputElement>("#portable-plan-import-symbol")
      .setValue(targetSymbol);
    await wrapper
      .get<HTMLTextAreaElement>("#portable-plan-import-document")
      .setValue(importedVersion.sourceText);
    await wrapper.get('[data-testid="plan-import-form"]').trigger("submit");
    await flushPromises();

    expect(getPlanActivationState).toHaveBeenCalledWith(
      targetSymbol,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(importPlan).toHaveBeenCalledWith(
      {
        document: importedVersion.sourceText,
        expectedRevision: 0,
        format: "JSON",
        symbol: targetSymbol,
      },
      "cross-symbol-import-key",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(
      getPlanActivationState.mock.invocationCallOrder.find(
        (_, index) => getPlanActivationState.mock.calls[index]?.[0] === targetSymbol,
      ),
    ).toBeLessThan(importPlan.mock.invocationCallOrder[0] ?? Number.POSITIVE_INFINITY);
    expect(wrapper.text()).toContain("v1 · 600000.SH");
    wrapper.unmount();
  });

  it("does not guess revision zero when the authoritative version query fails", async () => {
    const wrapper = mount(PlanDraftingView, {
      props: {
        api: apiWith({ getRuntime: vi.fn().mockResolvedValue(runtime) }),
        planApi: planApiWith({
          listPlanVersions: vi
            .fn()
            .mockRejectedValue(new Error("Authorization: Bearer secret")),
        }),
      },
    });
    await flushPromises();

    expect(wrapper.text()).toContain("计划版本加载失败");
    expect(wrapper.text()).not.toContain("Authorization");
    expect(wrapper.find('[data-testid="plan-import-form"]').exists()).toBe(false);
    expect(wrapper.get(".plan-drafting-view__retry").text()).toContain("重新读取计划");
    wrapper.unmount();
  });

  it("wires authoritative activation and deactivation through the persisted plan view", async () => {
    const activeVersion = { ...planVersion, status: "ACTIVE" as const, revision: 1 };
    const supersededVersion = {
      ...activeVersion,
      status: "SUPERSEDED" as const,
      revision: 2,
    };
    const activeState: ActivePlanView = {
      ...inactiveState,
      active: true,
      planVersionId: PLAN_VERSION_ID,
      revision: 1,
    };
    const deactivatedState = { ...inactiveState, revision: 2 };
    const activatePlan = vi.fn().mockResolvedValue(activeState);
    const deactivatePlan = vi.fn().mockResolvedValue(deactivatedState);
    const planApi = planApiWith({
      activatePlan,
      deactivatePlan,
      getPlanActivationState: vi
        .fn()
        .mockResolvedValueOnce(inactiveState)
        .mockResolvedValueOnce(activeState)
        .mockResolvedValueOnce(deactivatedState),
      getPlanVersion: vi
        .fn()
        .mockResolvedValueOnce(planVersion)
        .mockResolvedValueOnce(activeVersion)
        .mockResolvedValueOnce(supersededVersion),
      listPlanVersions: vi
        .fn()
        .mockResolvedValueOnce(planPage)
        .mockResolvedValueOnce({ ...planPage, items: [planSummary(activeVersion)] })
        .mockResolvedValueOnce({ ...planPage, items: [planSummary(supersededVersion)] }),
    });
    const keys = ["activate-key", "deactivate-key"];
    const wrapper = mount(PlanDraftingView, {
      props: {
        api: apiWith({ getRuntime: vi.fn().mockResolvedValue(runtime) }),
        createPlanIdempotencyKey: () => keys.shift() ?? "unexpected-key",
        planApi,
      },
    });
    await flushPromises();

    await wrapper.get('[data-testid="request-activation"]').trigger("click");
    await wrapper.get<HTMLInputElement>("#confirm-plan-action").setValue(true);
    await wrapper.get('[data-testid="confirm-plan-action"]').trigger("click");
    await flushPromises();
    expect(activatePlan).toHaveBeenCalledWith(
      { expectedRevision: 0, planVersionId: PLAN_VERSION_ID },
      "activate-key",
      expect.any(Object),
    );

    await wrapper.get('[data-testid="request-deactivation"]').trigger("click");
    await wrapper.get<HTMLInputElement>("#confirm-plan-action").setValue(true);
    await wrapper.get('[data-testid="confirm-plan-action"]').trigger("click");
    await flushPromises();
    expect(deactivatePlan).toHaveBeenCalledWith(
      { expectedRevision: 1, symbol: planVersion.symbol },
      "deactivate-key",
      expect.any(Object),
    );
    wrapper.unmount();
  });
});
