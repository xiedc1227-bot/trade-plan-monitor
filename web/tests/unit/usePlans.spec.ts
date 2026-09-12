import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent, h } from "vue";
import { describe, expect, it, vi } from "vitest";

import type {
  ActivePlanView,
  PlanDraftCommand,
  PlanImportCommand,
  PlanVersionPage,
  PlanVersionSummary,
  PlanVersionView,
} from "../../src/api/generated";
import { ApiClientError, type PlanApi } from "../../src/api/plans";
import { usePlans } from "../../src/composables/usePlans";

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

const page: PlanVersionPage = {
  items: [summary(version)],
  limit: 100,
  offset: 0,
  total: 1,
};

function summary(candidate: PlanVersionView): PlanVersionSummary {
  return {
    canActivate: candidate.canActivate,
    createdAt: candidate.createdAt,
    id: candidate.id,
    planHash: candidate.planHash,
    planId: candidate.planId,
    revision: candidate.revision,
    status: candidate.status,
    symbol: candidate.symbol,
    version: candidate.version,
  };
}

const inactiveState: ActivePlanView = {
  active: false,
  changedAt: TIME,
  planVersionId: null,
  revision: 0,
  symbol: version.symbol,
};

describe("usePlans", () => {
  it("loads versions and the selected symbol's durable activation state", async () => {
    const api = apiWith({
      getPlanActivationState: vi.fn().mockResolvedValue(inactiveState),
      listPlanVersions: vi.fn().mockResolvedValue(page),
    });
    const { plans, wrapper } = mountPlans(api);
    await flushPromises();

    expect(plans.versions.value).toEqual([summary(version)]);
    expect(plans.selectedPlan.value).toEqual(version);
    expect(plans.selectedPlanId.value).toBe(VERSION_ID);
    expect(plans.activeState.value).toEqual(inactiveState);
    expect(plans.loading.value).toBe(false);
    expect(plans.errorMessage.value).toBeNull();
    wrapper.unmount();
  });

  it("loads only the selected and active details from a summary page", async () => {
    const activeVersion: PlanVersionView = {
      ...version,
      id: "00000000-0000-4000-8000-000000000403",
      planHash: "b".repeat(64),
      status: "ACTIVE",
      version: 2,
    };
    const historicalVersion: PlanVersionView = {
      ...version,
      id: "00000000-0000-4000-8000-000000000404",
      planHash: "c".repeat(64),
      status: "SUPERSEDED",
      version: 3,
    };
    const activeState: ActivePlanView = {
      ...inactiveState,
      active: true,
      planVersionId: activeVersion.id,
      revision: 4,
    };
    const getPlanVersion = vi.fn(async (id: string) => {
      if (id === version.id) return version;
      if (id === activeVersion.id) return activeVersion;
      return historicalVersion;
    });
    const api = apiWith({
      getPlanActivationState: vi.fn().mockResolvedValue(activeState),
      getPlanVersion,
      listPlanVersions: vi.fn().mockResolvedValue({
        ...page,
        items: [summary(version), summary(activeVersion), summary(historicalVersion)],
        total: 3,
      }),
    });
    const { plans, wrapper } = mountPlans(api);
    await flushPromises();

    expect(getPlanVersion.mock.calls.map(([id]) => id)).toEqual([
      version.id,
      activeVersion.id,
    ]);
    expect(plans.selectedPlan.value).toEqual(version);
    expect(plans.activePlan.value).toEqual(activeVersion);
    wrapper.unmount();
  });

  it("loads a direct plan-version route even when the version is outside the current list page", async () => {
    const directVersion: PlanVersionView = {
      ...version,
      id: "00000000-0000-4000-8000-000000000499",
      planHash: "c".repeat(64),
      planId: "direct-route-plan",
      symbol: "600000.SH",
      version: 9,
    };
    const directState: ActivePlanView = {
      ...inactiveState,
      changedAt: "2026-09-03T10:10:00.000000+08:00",
      symbol: directVersion.symbol,
    };
    const getPlanVersion = vi.fn(async (id: string) =>
      id === directVersion.id ? directVersion : version,
    );
    const api = apiWith({
      getPlanActivationState: vi.fn(async (symbol: string) =>
        symbol === directVersion.symbol ? directState : inactiveState,
      ),
      getPlanVersion,
      listPlanVersions: vi.fn().mockResolvedValue(page),
    });
    const { plans, wrapper } = mountPlans(api, [], directVersion.id);
    await flushPromises();

    expect(getPlanVersion).toHaveBeenCalledWith(
      directVersion.id,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(plans.selectedPlanId.value).toBe(directVersion.id);
    expect(plans.selectedPlan.value).toEqual(directVersion);
    expect(plans.activeState.value).toEqual(directState);
    wrapper.unmount();
  });

  it("imports into an empty repository only after a missing target state proves revision zero", async () => {
    const listPlanVersions = vi
      .fn()
      .mockResolvedValueOnce({ ...page, items: [], total: 0 })
      .mockResolvedValueOnce(page);
    const importPlan = vi.fn().mockResolvedValue({
      ...version,
      sourceText: version.planJson,
    });
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
    const api = apiWith({
      getPlanActivationState,
      importPlan,
      listPlanVersions,
    });
    const { plans, wrapper } = mountPlans(api, ["plan-import-from-browser"]);
    await flushPromises();
    const command: PlanImportCommand = {
      document: version.planJson,
      expectedRevision: 0,
      format: "JSON",
      symbol: version.symbol,
    };

    await plans.importPlan(command);

    expect(importPlan).toHaveBeenCalledWith(
      command,
      "plan-import-from-browser",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(getPlanActivationState).toHaveBeenNthCalledWith(
      1,
      version.symbol,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(getPlanActivationState.mock.invocationCallOrder[0]).toBeLessThan(
      importPlan.mock.invocationCallOrder[0] ?? Number.POSITIVE_INFINITY,
    );
    expect(listPlanVersions).toHaveBeenCalledTimes(2);
    expect(plans.versions.value).toEqual([summary(version)]);
    expect(plans.selectedPlan.value).toEqual(version);
    expect(plans.selectedPlanId.value).toBe(VERSION_ID);
    wrapper.unmount();
  });

  it("saves an AI-reviewed root draft only after resolving target authority", async () => {
    const reviewedVersion: PlanVersionView = {
      ...version,
      reviewIssues: [
        { kind: "MISSING_EVIDENCE", material: true, path: "draft", resolved: true },
      ],
    };
    const listPlanVersions = vi
      .fn()
      .mockResolvedValueOnce({ ...page, items: [], total: 0 })
      .mockResolvedValueOnce({ ...page, items: [summary(reviewedVersion)] });
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
    const savePlanDraft = vi.fn().mockResolvedValue(reviewedVersion);
    const api = apiWith({
      getPlanActivationState,
      getPlanVersion: vi.fn().mockResolvedValue(reviewedVersion),
      listPlanVersions,
      savePlanDraft,
    });
    const { plans, wrapper } = mountPlans(api, ["ai-reviewed-root-draft"]);
    await flushPromises();

    const saved = await plans.saveExtractedDraft({
      extractionId: "00000000-0000-4000-8000-000000000201",
      planJson: version.planJson,
      reviewIssues: reviewedVersion.reviewIssues ?? [],
      sourceText: version.sourceText,
      symbol: version.symbol,
    });

    expect(saved).toBe(true);
    expect(savePlanDraft).toHaveBeenCalledWith(
      {
        expectedRevision: 0,
        extractionId: "00000000-0000-4000-8000-000000000201",
        planJson: version.planJson,
        reviewIssues: reviewedVersion.reviewIssues,
        sourceText: version.sourceText,
      },
      "ai-reviewed-root-draft",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(savePlanDraft.mock.calls[0]?.[0]).not.toHaveProperty("basePlanVersionId");
    expect(getPlanActivationState.mock.invocationCallOrder[0]).toBeLessThan(
      savePlanDraft.mock.invocationCallOrder[0] ?? Number.POSITIVE_INFINITY,
    );
    expect(plans.selectedPlan.value).toEqual(reviewedVersion);
    wrapper.unmount();
  });

  it("does not save an AI-reviewed draft when target authority is unavailable", async () => {
    const savePlanDraft = vi.fn();
    const api = apiWith({
      getPlanActivationState: vi.fn().mockRejectedValue(
        new ApiClientError({
          code: "SERVICE_UNAVAILABLE",
          message: "sensitive upstream detail",
          status: 503,
        }),
      ),
      listPlanVersions: vi.fn().mockResolvedValue({ ...page, items: [], total: 0 }),
      savePlanDraft,
    });
    const { plans, wrapper } = mountPlans(api, ["must-not-be-used"]);
    await flushPromises();

    const saved = await plans.saveExtractedDraft({
      extractionId: "00000000-0000-4000-8000-000000000201",
      planJson: version.planJson,
      reviewIssues: [],
      sourceText: version.sourceText,
      symbol: version.symbol,
    });

    expect(saved).toBe(false);
    expect(savePlanDraft).not.toHaveBeenCalled();
    expect(plans.errorMessage.value).toBe(
      "目标股票启停状态无法确认，未保存 AI 审核草稿。",
    );
    expect(plans.errorMessage.value).not.toContain("sensitive upstream detail");
    wrapper.unmount();
  });

  it("uses one caller key per save, activation, and deactivation then requeries", async () => {
    const listPlanVersions = vi.fn().mockResolvedValue(page);
    const savedVersion = {
      ...version,
      id: "00000000-0000-4000-8000-000000000403",
      version: 2,
    };
    const savePlanDraft = vi.fn().mockImplementation(async (command: PlanDraftCommand) => {
      if (command.basePlanVersionId !== VERSION_ID) {
        throw new Error("immutable version base was not supplied");
      }
      return savedVersion;
    });
    const activatePlan = vi.fn().mockResolvedValue({
      ...inactiveState,
      active: true,
      planVersionId: VERSION_ID,
      revision: 1,
    });
    const deactivatePlan = vi.fn().mockResolvedValue({
      ...inactiveState,
      changedAt: "2026-09-03T10:02:00.000000+08:00",
      revision: 2,
    });
    const api = apiWith({
      activatePlan,
      deactivatePlan,
      getPlanActivationState: vi
        .fn()
        .mockResolvedValueOnce(inactiveState)
        .mockResolvedValueOnce(inactiveState)
        .mockResolvedValueOnce({
          ...inactiveState,
          active: true,
          planVersionId: VERSION_ID,
          revision: 1,
        })
        .mockResolvedValueOnce({ ...inactiveState, revision: 2 }),
      listPlanVersions,
      savePlanDraft,
    });
    const { plans, wrapper } = mountPlans(api, ["save-key", "activate-key", "deactivate-key"]);
    await flushPromises();
    const draft: PlanDraftCommand = {
      expectedRevision: 0,
      planJson: version.planJson,
      reviewIssues: [],
      sourceText: version.sourceText,
    };

    await plans.saveDraft(draft);
    await plans.activatePlan({ expectedRevision: 0, planVersionId: VERSION_ID });
    await plans.deactivatePlan({ expectedRevision: 1, symbol: version.symbol });

    expect(savePlanDraft).toHaveBeenCalledWith(
      { ...draft, basePlanVersionId: VERSION_ID },
      "save-key",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(activatePlan).toHaveBeenCalledWith(
      { expectedRevision: 0, planVersionId: VERSION_ID },
      "activate-key",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(deactivatePlan).toHaveBeenCalledWith(
      { expectedRevision: 1, symbol: version.symbol },
      "deactivate-key",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(listPlanVersions).toHaveBeenCalledTimes(4);
    wrapper.unmount();
  });

  it("binds save and import to the last authoritative activation revision", async () => {
    const durableState = { ...inactiveState, revision: 7 };
    const savePlanDraft = vi.fn().mockResolvedValue(version);
    const importPlan = vi.fn().mockResolvedValue({
      ...version,
      id: "00000000-0000-4000-8000-000000000403",
      version: 2,
    });
    const api = apiWith({
      getPlanActivationState: vi.fn().mockResolvedValue(durableState),
      importPlan,
      listPlanVersions: vi.fn().mockResolvedValue(page),
      savePlanDraft,
    });
    const { plans, wrapper } = mountPlans(api, ["save-revision", "import-revision"]);
    await flushPromises();

    const staleDraft: PlanDraftCommand = {
      expectedRevision: version.revision,
      planJson: version.planJson,
      reviewIssues: [],
      sourceText: version.sourceText,
    };
    const staleImport: PlanImportCommand = {
      document: version.planJson,
      expectedRevision: version.revision,
      format: "JSON",
      symbol: version.symbol,
    };
    await plans.saveDraft(staleDraft);
    await plans.importPlan(staleImport);

    expect(savePlanDraft).toHaveBeenCalledWith(
      { ...staleDraft, basePlanVersionId: VERSION_ID, expectedRevision: 7 },
      "save-revision",
      expect.any(Object),
    );
    expect(importPlan).toHaveBeenCalledWith(
      { ...staleImport, expectedRevision: 7 },
      "import-revision",
      expect.any(Object),
    );
    wrapper.unmount();
  });

  it("resolves a different import symbol's missing activation state to authoritative revision zero", async () => {
    const targetSymbol = "600000.SH";
    const importedVersion: PlanVersionView = {
      ...version,
      id: "00000000-0000-4000-8000-000000000404",
      planHash: "b".repeat(64),
      planId: "pudong-bank",
      symbol: targetSymbol,
    };
    const importedPage: PlanVersionPage = {
      ...page,
      items: [summary(importedVersion), summary(version)],
      total: 2,
    };
    const importPlan = vi.fn().mockResolvedValue(importedVersion);
    const getPlanActivationState = vi.fn(async (symbol: string) => {
      if (symbol === version.symbol) return inactiveState;
      if (getPlanActivationState.mock.calls.length === 2) {
        throw new ApiClientError({
          code: "NOT_FOUND",
          message: "请求的资源不存在",
          status: 404,
        });
      }
      return { ...inactiveState, symbol: targetSymbol };
    });
    const api = apiWith({
      getPlanActivationState,
      getPlanVersion: vi.fn(async (id: string) =>
        id === importedVersion.id ? importedVersion : version,
      ),
      importPlan,
      listPlanVersions: vi
        .fn()
        .mockResolvedValueOnce(page)
        .mockResolvedValueOnce(importedPage),
    });
    const { plans, wrapper } = mountPlans(api, ["cross-symbol-import"]);
    await flushPromises();

    await plans.importPlan({
      document: importedVersion.planJson,
      expectedRevision: 99,
      format: "JSON",
      symbol: targetSymbol,
    });

    expect(importPlan).toHaveBeenCalledWith(
      {
        document: importedVersion.planJson,
        expectedRevision: 0,
        format: "JSON",
        symbol: targetSymbol,
      },
      "cross-symbol-import",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(plans.selectedPlan.value).toEqual(importedVersion);
    wrapper.unmount();
  });

  it("does not import when a different symbol's activation revision is unavailable", async () => {
    const importPlan = vi.fn();
    const getPlanActivationState = vi.fn(async (symbol: string) => {
      if (symbol === version.symbol) return inactiveState;
      throw new ApiClientError({
        code: "SERVICE_UNAVAILABLE",
        message: "本地监控服务暂不可用",
        status: 503,
      });
    });
    const api = apiWith({
      getPlanActivationState,
      importPlan,
      listPlanVersions: vi.fn().mockResolvedValue(page),
    });
    const { plans, wrapper } = mountPlans(api, ["must-not-be-used"]);
    await flushPromises();

    const imported = await plans.importPlan({
      document: version.planJson,
      expectedRevision: 0,
      format: "JSON",
      symbol: "600000.SH",
    });

    expect(imported).toBe(false);
    expect(importPlan).not.toHaveBeenCalled();
    expect(plans.errorMessage.value).toBe("目标股票启停状态无法确认，未提交导入。");
    wrapper.unmount();
  });

  it("reuses the same idempotency key when an unchanged save intent is uncertain", async () => {
    const savedVersion: PlanVersionView = {
      ...version,
      id: "00000000-0000-4000-8000-000000000405",
      version: 2,
    };
    const savedPage: PlanVersionPage = {
      ...page,
      items: [summary(savedVersion), summary(version)],
      total: 2,
    };
    const savePlanDraft = vi
      .fn()
      .mockRejectedValueOnce(
        new ApiClientError({
          code: "NETWORK_ERROR",
          message: "无法连接本地监控服务",
          status: 0,
        }),
      )
      .mockResolvedValueOnce(savedVersion);
    const api = apiWith({
      getPlanActivationState: vi.fn().mockResolvedValue(inactiveState),
      getPlanVersion: vi.fn(async (id: string) =>
        id === savedVersion.id ? savedVersion : version,
      ),
      listPlanVersions: vi
        .fn()
        .mockResolvedValueOnce(page)
        .mockResolvedValueOnce(page)
        .mockResolvedValueOnce(savedPage),
      savePlanDraft,
    });
    const { plans, wrapper } = mountPlans(api, ["stable-save-key", "new-key-not-used"]);
    await flushPromises();
    const command: PlanDraftCommand = {
      expectedRevision: 0,
      planJson: version.planJson,
      reviewIssues: [],
      sourceText: version.sourceText,
    };

    expect(await plans.saveDraft(command)).toBe(false);
    expect(plans.errorMessage.value).toBe(
      "计划草稿可能已保存，但无法确认结果；请刷新后核对。",
    );
    expect(await plans.saveDraft(command)).toBe(true);

    expect(savePlanDraft.mock.calls.map((call) => call[1])).toEqual([
      "stable-save-key",
      "stable-save-key",
    ]);
    expect(plans.selectedPlan.value).toEqual(savedVersion);
    wrapper.unmount();
  });

  it("reuses one semantic intent key after a submitted request returns 500 and refresh also fails", async () => {
    const activeVersion: PlanVersionView = {
      ...version,
      revision: 1,
      status: "ACTIVE",
    };
    const activeState: ActivePlanView = {
      ...inactiveState,
      active: true,
      planVersionId: version.id,
      revision: 1,
    };
    const activatePlan = vi
      .fn()
      .mockRejectedValueOnce(
        new ApiClientError({
          code: "INTERNAL_ERROR",
          message: "database committed; Authorization: Bearer secret",
          status: 500,
        }),
      )
      .mockResolvedValueOnce(activeState);
    const api = apiWith({
      activatePlan,
      getPlanActivationState: vi
        .fn()
        .mockResolvedValueOnce(inactiveState)
        .mockResolvedValueOnce(activeState),
      getPlanVersion: vi.fn().mockResolvedValueOnce(version).mockResolvedValueOnce(activeVersion),
      listPlanVersions: vi
        .fn()
        .mockResolvedValueOnce(page)
        .mockRejectedValueOnce(new Error("refresh transport secret"))
        .mockResolvedValueOnce({ ...page, items: [summary(activeVersion)] }),
    });
    const { plans, wrapper } = mountPlans(api, ["server-500-intent", "must-not-be-used"]);
    await flushPromises();
    const command = { expectedRevision: 0, planVersionId: version.id };

    expect(await plans.activatePlan(command)).toBe(false);
    expect(plans.errorMessage.value).toBe(
      "计划可能已启用，但无法确认结果；请刷新后核对。",
    );
    expect(plans.errorMessage.value).not.toContain("Authorization");
    expect(await plans.activatePlan(command)).toBe(true);

    expect(activatePlan.mock.calls.map((call) => call[1])).toEqual([
      "server-500-intent",
      "server-500-intent",
    ]);
    wrapper.unmount();
  });

  it("allocates a new idempotency key after an uncertain save intent changes", async () => {
    const savedVersion: PlanVersionView = {
      ...version,
      id: "00000000-0000-4000-8000-000000000406",
      planHash: "d".repeat(64),
      planJson: '{"schema_version":1,"name":"changed"}',
      version: 2,
    };
    const savePlanDraft = vi
      .fn()
      .mockRejectedValueOnce(
        new ApiClientError({
          code: "INVALID_RESPONSE",
          message: "本地监控服务返回了无效响应",
          status: 200,
        }),
      )
      .mockResolvedValueOnce(savedVersion);
    const api = apiWith({
      getPlanActivationState: vi.fn().mockResolvedValue(inactiveState),
      getPlanVersion: vi.fn(async (id: string) =>
        id === savedVersion.id ? savedVersion : version,
      ),
      listPlanVersions: vi
        .fn()
        .mockResolvedValueOnce(page)
        .mockResolvedValueOnce(page)
        .mockResolvedValueOnce({
          ...page,
          items: [summary(savedVersion), summary(version)],
          total: 2,
        }),
      savePlanDraft,
    });
    const { plans, wrapper } = mountPlans(api, ["original-intent", "changed-intent"]);
    await flushPromises();
    const original: PlanDraftCommand = {
      expectedRevision: 0,
      planJson: version.planJson,
      sourceText: version.sourceText,
    };

    expect(await plans.saveDraft(original)).toBe(false);
    expect(
      await plans.saveDraft({ ...original, planJson: savedVersion.planJson }),
    ).toBe(true);

    expect(savePlanDraft.mock.calls.map((call) => call[1])).toEqual([
      "original-intent",
      "changed-intent",
    ]);
    wrapper.unmount();
  });

  it("retains the mutation key when the response succeeds but authority refresh is uncertain", async () => {
    const activeVersion: PlanVersionView = {
      ...version,
      revision: 1,
      status: "ACTIVE",
    };
    const activeState: ActivePlanView = {
      ...inactiveState,
      active: true,
      planVersionId: version.id,
      revision: 1,
    };
    const activatePlan = vi.fn().mockResolvedValue(activeState);
    const api = apiWith({
      activatePlan,
      getPlanActivationState: vi
        .fn()
        .mockResolvedValueOnce(inactiveState)
        .mockResolvedValueOnce(activeState),
      getPlanVersion: vi.fn().mockResolvedValueOnce(version).mockResolvedValueOnce(activeVersion),
      listPlanVersions: vi
        .fn()
        .mockResolvedValueOnce(page)
        .mockRejectedValueOnce(new Error("Authorization: Bearer secret"))
        .mockResolvedValueOnce({ ...page, items: [summary(activeVersion)] }),
    });
    const { plans, wrapper } = mountPlans(api, ["refresh-uncertain", "must-not-be-used"]);
    await flushPromises();
    const command = { expectedRevision: 0, planVersionId: version.id };

    expect(await plans.activatePlan(command)).toBe(false);
    expect(await plans.activatePlan(command)).toBe(true);

    expect(activatePlan.mock.calls.map((call) => call[1])).toEqual([
      "refresh-uncertain",
      "refresh-uncertain",
    ]);
    expect(plans.activeState.value).toEqual(activeState);
    wrapper.unmount();
  });

  it("shows a fixed definitive message and clears the key for a backend conflict", async () => {
    const savePlanDraft = vi.fn().mockRejectedValue(
      new ApiClientError({
        code: "CONFLICT",
        message: "请求与当前状态冲突",
        status: 409,
      }),
    );
    const api = apiWith({
      getPlanActivationState: vi.fn().mockResolvedValue(inactiveState),
      listPlanVersions: vi.fn().mockResolvedValue(page),
      savePlanDraft,
    });
    const { plans, wrapper } = mountPlans(api, ["conflict-key", "conflict-retry-key"]);
    await flushPromises();
    const command: PlanDraftCommand = {
      expectedRevision: 0,
      planJson: version.planJson,
      sourceText: version.sourceText,
    };

    expect(await plans.saveDraft(command)).toBe(false);
    expect(plans.errorMessage.value).toBe(
      "计划状态已变化，本次变更未应用；请核对刷新后的版本。",
    );
    expect(await plans.saveDraft(command)).toBe(false);
    expect(savePlanDraft.mock.calls.map((call) => call[1])).toEqual([
      "conflict-key",
      "conflict-retry-key",
    ]);
    wrapper.unmount();
  });

  it("keeps raw transport failures out of visible state", async () => {
    const api = apiWith({
      listPlanVersions: vi.fn().mockRejectedValue(new Error("Authorization: Bearer secret")),
    });
    const { plans, wrapper } = mountPlans(api);
    await flushPromises();

    expect(plans.errorMessage.value).toBe("计划版本加载失败，请稍后重试。");
    expect(plans.errorMessage.value).not.toContain("Authorization");
    expect(plans.errorMessage.value).not.toContain("secret");
    wrapper.unmount();
  });

  it("requeries authority after an uncertain mutation without claiming failure or success", async () => {
    const activeVersion = { ...version, status: "ACTIVE" as const, revision: 1 };
    const activeState: ActivePlanView = {
      ...inactiveState,
      active: true,
      planVersionId: VERSION_ID,
      revision: 1,
    };
    const listPlanVersions = vi
      .fn()
      .mockResolvedValueOnce(page)
      .mockResolvedValueOnce({ ...page, items: [summary(activeVersion)] });
    const api = apiWith({
      activatePlan: vi.fn().mockRejectedValue(new Error("Authorization: Bearer secret")),
      getPlanActivationState: vi
        .fn()
        .mockResolvedValueOnce(inactiveState)
        .mockResolvedValueOnce(activeState),
      listPlanVersions,
    });
    const { plans, wrapper } = mountPlans(api, ["uncertain-activation"]);
    await flushPromises();

    const confirmed = await plans.activatePlan({
      expectedRevision: 0,
      planVersionId: VERSION_ID,
    });

    expect(confirmed).toBe(false);
    expect(listPlanVersions).toHaveBeenCalledTimes(2);
    expect(plans.activeState.value).toEqual(activeState);
    expect(plans.errorMessage.value).toBe(
      "计划可能已启用，但无法确认结果；请刷新后核对。",
    );
    expect(plans.errorMessage.value).not.toContain("Authorization");
    wrapper.unmount();
  });
});

function mountPlans(
  api: PlanApi,
  keys: string[] = [],
  initialPlanVersionId?: string,
) {
  let plans: ReturnType<typeof usePlans> | undefined;
  const nextKey = vi.fn(() => keys.shift() ?? "fallback-plan-key");
  const Harness = defineComponent({
    setup() {
      plans = usePlans({
        api,
        createIdempotencyKey: nextKey,
        ...(initialPlanVersionId === undefined ? {} : { initialPlanVersionId }),
      });
      return () => h("div");
    },
  });
  const wrapper = mount(Harness);
  if (plans === undefined) throw new Error("plan harness did not initialize");
  return { plans, wrapper };
}

function apiWith(overrides: Partial<PlanApi>): PlanApi {
  const unused = vi.fn(() => Promise.reject(new Error("unexpected plan API call")));
  return {
    activatePlan: unused,
    deactivatePlan: unused,
    getPlanActivationState: unused,
    getPlanVersion: vi.fn().mockResolvedValue(version),
    importPlan: unused,
    listPlanVersions: unused,
    savePlanDraft: unused,
    ...overrides,
  } as PlanApi;
}
