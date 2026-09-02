import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import type {
  ConfiguredAIRuntimeView,
  OperationReceipt,
  PlanExtractionView,
} from "../../src/api/generated";
import type { AIPlanApi } from "../../src/api/ai";
import PlanDraftingView from "../../src/views/PlanDraftingView.vue";

const PROVIDER_ID = "00000000-0000-4000-8000-0000000000d5";
const OPERATION_ID = "00000000-0000-4000-8000-000000000201";

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

function apiWith(overrides: Partial<AIPlanApi> = {}): AIPlanApi {
  const unused = vi.fn(() => Promise.reject(new Error("unexpected API call")));
  return {
    getExtraction: unused,
    getRuntime: unused,
    submitExtraction: unused,
    ...overrides,
  } as AIPlanApi;
}

describe("PlanDraftingView", () => {
  it("loads the file-configured AI runtime and completes the Web extraction flow", async () => {
    const getRuntime = vi.fn().mockResolvedValue(runtime);
    const submitExtraction = vi.fn().mockResolvedValue(receipt);
    const getExtraction = vi.fn().mockResolvedValue(invalidExtraction);
    const api = apiWith({ getExtraction, getRuntime, submitExtraction });
    const wrapper = mount(PlanDraftingView, {
      props: {
        api,
        createIdempotencyKey: () => "web-plan-intent-001",
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

  it("shows a fixed safe message when startup configuration cannot be loaded", async () => {
    const api = apiWith({ getRuntime: vi.fn().mockRejectedValue(new Error("TOKEN=secret")) });
    const wrapper = mount(PlanDraftingView, { props: { api } });
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
      props: { api, createIdempotencyKey: () => "uncertain-plan-intent", pollIntervalMs: 0 },
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
});
