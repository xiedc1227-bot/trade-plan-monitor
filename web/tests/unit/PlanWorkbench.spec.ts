import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import type {
  ConfiguredAIRuntimeView,
  PlanExtractionCommand,
  PlanExtractionView,
} from "../../src/api/generated";
import PlanWorkbench from "../../src/components/plans/PlanWorkbench.vue";

const firstProvider: ConfiguredAIRuntimeView = {
  baseUrl: "https://ai.example.test/v1",
  configured: true,
  displayName: "审阅模型",
  enabled: true,
  maxInputChars: 200_000,
  maxOutputTokens: 4_096,
  model: "review-model-v1",
  providerId: "00000000-0000-0000-0000-000000000001",
  revision: 0,
};

const secondProvider: ConfiguredAIRuntimeView = {
  baseUrl: "http://127.0.0.1:11434/v1",
  configured: false,
  displayName: "本地模型",
  enabled: true,
  maxInputChars: 200_000,
  maxOutputTokens: 4_096,
  model: "local-review-model",
  providerId: "00000000-0000-0000-0000-000000000002",
  revision: 0,
};

const disabledProvider: ConfiguredAIRuntimeView = {
  ...firstProvider,
  displayName: "已停用模型",
  enabled: false,
  providerId: "00000000-0000-0000-0000-000000000003",
};

function extraction(
  status: PlanExtractionView["status"],
  overrides: Partial<PlanExtractionView> = {},
): PlanExtractionView {
  return {
    id: "00000000-0000-0000-0000-000000000201",
    providerId: firstProvider.providerId,
    status,
    submittedAt: "2026-08-24T10:30:00+08:00",
    ...overrides,
  };
}

function successfulExtraction(
  overrides: Partial<PlanExtractionView> = {},
): PlanExtractionView {
  return extraction("SUCCEEDED", {
    assumptions: [
      {
        material: true,
        message: "报告日期未明确，需要人工确认。",
        path: "metadata.reportDate",
      },
    ],
    completedAt: "2026-08-24T10:31:00+08:00",
    draftPlanJson: '{"schemaVersion":1,"symbol":"003043.SZ"}',
    evidence: [
      {
        end: 18,
        excerpt: "回踩 20.10 至 20.50 分批关注",
        path: "entry.coreCondition",
        start: 2,
      },
    ],
    model: "review-model-v1",
    promptVersion: "plan-extract-v1",
    sourceTextSha256: "a".repeat(64),
    startedAt: "2026-08-24T10:30:05+08:00",
    unmappedText: [
      {
        end: 40,
        excerpt: "结合盘感灵活处理",
        material: true,
        path: "sourceText[24:40]",
        reason: "无法映射为白名单条件",
        start: 24,
      },
    ],
    usage: { completionTokens: 320, promptTokens: 850, totalTokens: 1170 },
    validationIssues: [
      {
        activationBlocking: true,
        code: "MISSING_REPORT_DATE",
        message: "报告日期需要确认。",
        path: "metadata.reportDate",
        severity: "WARNING",
      },
    ],
    warnings: [
      {
        material: true,
        message: "AI 证据必须由用户审核。",
        path: "AI_EVIDENCE_REVIEW_REQUIRED",
      },
    ],
    ...overrides,
  });
}

function mountWorkbench(
  props: Partial<InstanceType<typeof PlanWorkbench>["$props"]> = {},
) {
  return mount(PlanWorkbench, {
    props: {
      initialProviderId: firstProvider.providerId,
      initialSourceText: "华亚智能交易计划",
      providers: [firstProvider, secondProvider],
      ...props,
    },
  });
}

describe("PlanWorkbench", () => {
  it("shows file-configured provider metadata without any Web configuration control", async () => {
    const wrapper = mountWorkbench();
    const providerSelect = wrapper.get<HTMLSelectElement>("#ai-provider");

    expect(providerSelect.element.value).toBe(firstProvider.providerId);
    expect(wrapper.text()).toContain("已配置");
    expect(wrapper.text()).not.toContain("ai/provider/review");
    expect(wrapper.text()).toContain("配置文件只读");
    expect(wrapper.find("#provider-secret").exists()).toBe(false);
    expect(wrapper.find('[data-testid="replace-secret"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="test-provider"]').exists()).toBe(false);

    await providerSelect.setValue(secondProvider.providerId);
    expect(wrapper.text()).toContain("local-review-model");
  });

  it("never defaults to or submits work for a disabled provider", async () => {
    const wrapper = mountWorkbench({
      initialProviderId: disabledProvider.providerId,
      providers: [disabledProvider, firstProvider],
    });
    const providerSelect = wrapper.get<HTMLSelectElement>("#ai-provider");

    expect(providerSelect.element.value).toBe(firstProvider.providerId);
    await providerSelect.setValue(disabledProvider.providerId);

    expect(wrapper.text()).toContain("已禁用");
    expect(wrapper.get<HTMLTextAreaElement>("#plan-source-text").element.disabled).toBe(true);
    await wrapper.get('[data-testid="source-editor"]').trigger("submit");
    expect(wrapper.emitted("submitExtraction")).toBeUndefined();
  });

  it("submits pasted Chinese source for extraction without exposing an activation action", async () => {
    const wrapper = mountWorkbench();
    const source = "华亚智能：回踩 20.10 至 20.50 分批关注，跌破风险线离场。";

    await wrapper.get<HTMLTextAreaElement>("#plan-source-text").setValue(source);
    await wrapper.get('[data-testid="source-editor"]').trigger("submit");

    expect(wrapper.emitted("submitExtraction")).toEqual([
      [
        {
          expectedRevision: 0,
          providerId: firstProvider.providerId,
          sourceText: source,
        },
      ],
    ]);
    expect(wrapper.emitted("activate")).toBeUndefined();
    expect(wrapper.find('[data-testid="activate-plan"]').exists()).toBe(false);
  });

  it("announces queued and running 202 progress and emits only a stop-waiting intent", async () => {
    const wrapper = mountWorkbench({ extraction: extraction("QUEUED") });

    expect(wrapper.get('[role="status"]').text()).toContain("提取任务已排队");
    expect(wrapper.get<HTMLTextAreaElement>("#plan-source-text").element.disabled).toBe(true);
    await wrapper.get('[data-testid="stop-waiting"]').trigger("click");
    expect(wrapper.emitted("stopWaiting")).toEqual([
      ["00000000-0000-0000-0000-000000000201"],
    ]);

    await wrapper.setProps({
      extraction: extraction("RUNNING", {
        startedAt: "2026-08-24T10:30:05+08:00",
      }),
    });
    expect(wrapper.get('[role="status"]').text()).toContain("正在提取并校验计划草稿");
  });

  it("does not render a no-op cancel control before an operation identity exists", () => {
    const wrapper = mountWorkbench({ extraction: null, submitting: true });

    expect(wrapper.get<HTMLTextAreaElement>("#plan-source-text").element.disabled).toBe(true);
    expect(wrapper.find('[data-testid="stop-waiting"]').exists()).toBe(false);
  });

  it("releases local pending state when submission ends without a new operation receipt", async () => {
    const wrapper = mountWorkbench();

    await wrapper.get('[data-testid="source-editor"]').trigger("submit");
    await wrapper.setProps({ submitting: true });
    await wrapper.setProps({ submitting: false });

    expect(wrapper.get<HTMLTextAreaElement>("#plan-source-text").element.disabled).toBe(false);
    expect(wrapper.find('[data-testid="stale-extraction-review"]').exists()).toBe(false);
    await wrapper.get('[data-testid="source-editor"]').trigger("submit");
    expect(wrapper.emitted("submitExtraction")).toHaveLength(2);
  });

  it("invalidates review evidence when locally submitted source text later changes", async () => {
    const wrapper = mountWorkbench();
    const textarea = wrapper.get<HTMLTextAreaElement>("#plan-source-text");

    await wrapper.get('[data-testid="source-editor"]').trigger("submit");
    expect(textarea.element.disabled).toBe(true);
    await wrapper.setProps({ extraction: successfulExtraction() });
    expect(wrapper.text()).toContain("entry.coreCondition");

    await textarea.setValue("已经修改、尚未重新提取的计划原文");

    expect(wrapper.get('[data-testid="stale-extraction-review"]').text()).toContain(
      "原文已在提取后修改",
    );
    expect(wrapper.text()).not.toContain("entry.coreCondition");
  });

  it("keeps the submitted source locked while an old extraction is cleared before the new receipt", async () => {
    const wrapper = mountWorkbench({ extraction: successfulExtraction() });

    await wrapper.get('[data-testid="source-editor"]').trigger("submit");
    await wrapper.setProps({ extraction: null });

    expect(wrapper.get<HTMLTextAreaElement>("#plan-source-text").element.disabled).toBe(true);
  });

  it("releases pending when an old extraction is cleared and submission then fails", async () => {
    const wrapper = mountWorkbench({ extraction: successfulExtraction() });

    await wrapper.get('[data-testid="source-editor"]').trigger("submit");
    await wrapper.setProps({ submitting: true, extraction: null });
    await wrapper.setProps({ submitting: false });

    expect(wrapper.get<HTMLTextAreaElement>("#plan-source-text").element.disabled).toBe(false);
    expect(wrapper.find('[data-testid="stale-extraction-review"]').exists()).toBe(false);
  });

  it("renders all review channels and tracks unresolved material issues explicitly", async () => {
    const wrapper = mountWorkbench({ extraction: successfulExtraction() });

    expect(wrapper.text()).toContain("entry.coreCondition");
    expect(wrapper.text()).toContain("回踩 20.10 至 20.50 分批关注");
    expect(wrapper.text()).toContain("报告日期未明确，需要人工确认。");
    expect(wrapper.text()).toContain("AI 证据必须由用户审核。");
    expect(wrapper.text()).toContain("结合盘感灵活处理");
    expect(wrapper.text()).toContain("无法映射为白名单条件");
    expect(wrapper.text()).toContain("MISSING_REPORT_DATE");
    expect(wrapper.get('[data-testid="unresolved-material-count"]').text()).toContain("3");

    await wrapper
      .get('[data-issue-key="ASSUMPTION:metadata.reportDate"] button')
      .trigger("click");

    expect(wrapper.emitted("resolveIssue")).toEqual([
      [
        {
          kind: "ASSUMPTION",
          material: true,
          path: "metadata.reportDate",
          resolved: true,
        },
      ],
    ]);
    expect(wrapper.get('[data-testid="unresolved-material-count"]').text()).toContain("2");
    expect(
      wrapper
        .get('[data-issue-key="WARNING:AI_EVIDENCE_REVIEW_REQUIRED"] button')
        .attributes("aria-label"),
    ).toContain("WARNING AI_EVIDENCE_REVIEW_REQUIRED");
  });

  it("treats the canonical evidence-review validation blocker as unresolved evidence", async () => {
    const wrapper = mountWorkbench({
      extraction: successfulExtraction({
        assumptions: [],
        unmappedText: [],
        validationIssues: [
          {
            activationBlocking: true,
            code: "AI_EVIDENCE_REVIEW_REQUIRED",
            message: "Review AI field evidence before activation.",
            path: "draft",
            severity: "WARNING",
          },
        ],
        warnings: [],
      }),
    });

    expect(wrapper.get('[data-testid="unresolved-material-count"]').text()).toContain("1");
    await wrapper.get('[data-issue-key="MISSING_EVIDENCE:draft"] button').trigger("click");
    expect(wrapper.emitted("resolveIssue")).toEqual([
      [
        {
          kind: "MISSING_EVIDENCE",
          material: true,
          path: "draft",
          resolved: true,
        },
      ],
    ]);
  });

  it("fails closed when multiple review items share the same backend identity", async () => {
    const duplicateIdentity = "metadata.reportDate";
    const warningSpy = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const wrapper = mountWorkbench({
      extraction: successfulExtraction({
        assumptions: [
          { material: true, message: "第一条不确定说明", path: duplicateIdentity },
          { material: true, message: "第二条不确定说明", path: duplicateIdentity },
        ],
        unmappedText: [],
        validationIssues: [],
        warnings: [],
      }),
    });

    const duplicateItems = wrapper.findAll(
      `[data-issue-key="ASSUMPTION:${duplicateIdentity}"]`,
    );
    expect(duplicateItems).toHaveLength(2);
    expect(wrapper.get('[data-testid="unresolved-material-count"]').text()).toContain("2");
    expect(duplicateItems.every((item) => item.get("button").attributes("disabled") !== undefined)).toBe(
      true,
    );
    expect(wrapper.text()).toContain("重复问题 identity，必须重新提取");
    expect(wrapper.emitted("resolveIssue")).toBeUndefined();
    expect(
      warningSpy.mock.calls.some((call) => String(call[0]).includes("Duplicate keys")),
    ).toBe(false);
    warningSpy.mockRestore();
  });

  it("escapes hostile user and AI text instead of creating executable markup", () => {
    const hostile = '<img src=x onerror="globalThis.compromised=true"><script>alert(1)</script>';
    const wrapper = mountWorkbench({
      extraction: successfulExtraction({
        evidence: [{ excerpt: hostile, path: "entry.coreCondition" }],
      }),
      initialSourceText: hostile,
    });

    expect(wrapper.get<HTMLTextAreaElement>("#plan-source-text").element.value).toBe(hostile);
    expect(wrapper.text()).toContain(hostile);
    expect(wrapper.find("script").exists()).toBe(false);
    expect(wrapper.find("img").exists()).toBe(false);
    expect(wrapper.html()).not.toContain("<script>alert(1)</script>");
  });

  it("marks long unbroken review copy for mobile-safe wrapping", () => {
    const unbrokenMessage = "A".repeat(512);
    const wrapper = mountWorkbench({
      extraction: successfulExtraction({
        warnings: [
          {
            material: true,
            message: unbrokenMessage,
            path: "risk.longUnbrokenMessage",
          },
        ],
      }),
    });

    expect(
      wrapper
        .get(
          '[data-issue-key="WARNING:risk.longUnbrokenMessage"] .extraction-evidence__copy',
        )
        .text(),
    ).toBe(unbrokenMessage);
  });

  it("supports error, retry, and cancelled states without displaying raw provider details", async () => {
    const wrapper = mountWorkbench({ extraction: extraction("PROVIDER_ERROR") });

    expect(wrapper.get('[role="alert"]').text()).toContain("AI 供应商暂时不可用");
    expect(wrapper.text()).not.toContain("Authorization");
    expect(wrapper.text()).not.toContain("尚未提交提取任务");
    await wrapper.get('[data-testid="retry-extraction"]').trigger("click");
    expect(wrapper.emitted("submitExtraction")).toEqual([
      [
        {
          expectedRevision: 0,
          providerId: firstProvider.providerId,
          sourceText: "华亚智能交易计划",
        },
      ],
    ]);

    await wrapper.setProps({
      extraction: extraction("CANCELLED", {
        completedAt: "2026-08-24T10:30:30+08:00",
      }),
    });
    expect(wrapper.get('[role="status"]').text()).toContain("提取已取消");
  });

  it("allows only one error-state retry while waiting for a new operation receipt", async () => {
    const wrapper = mountWorkbench({ extraction: extraction("PROVIDER_ERROR") });
    const retry = wrapper.get('[data-testid="retry-extraction"]');

    await retry.trigger("click");
    expect(retry.attributes("disabled")).toBeDefined();
    await retry.trigger("click");

    expect(wrapper.emitted("submitExtraction")).toHaveLength(1);
  });

  it("rejects an oversized extraction retry at the final emit boundary", async () => {
    const wrapper = mountWorkbench({
      extraction: extraction("PROVIDER_ERROR"),
      initialSourceText: "计".repeat(200_001),
    });

    await wrapper.get('[data-testid="retry-extraction"]').trigger("click");

    expect(wrapper.emitted("submitExtraction")).toBeUndefined();
  });

  it("counts astral source characters with the backend Unicode code-point semantics", async () => {
    const validAstralSource = "😀".repeat(100_001);
    const wrapper = mountWorkbench({ initialSourceText: validAstralSource });

    expect(wrapper.get(".source-editor__count").text()).toContain("100001 / 200000");
    await wrapper.get('[data-testid="source-editor"]').trigger("submit");

    const command = wrapper.emitted("submitExtraction")?.[0]?.[0] as
      | PlanExtractionCommand
      | undefined;
    expect(command?.sourceText).toBe(validAstralSource);
  });

  it("rejects an oversized BMP paste atomically without rewriting source text", async () => {
    const wrapper = mountWorkbench();
    const textarea = wrapper.get<HTMLTextAreaElement>("#plan-source-text");

    await textarea.setValue("计".repeat(200_001));

    expect(textarea.element.value).toBe("华亚智能交易计划");
    expect(wrapper.get('[role="alert"]').text()).toContain("原文不能超过 200000 个字符");
    await wrapper.get('[data-testid="source-editor"]').trigger("submit");
    expect(wrapper.emitted("submitExtraction")).toBeUndefined();
  });

  it("atomically rejects astral source above the backend code-point limit", async () => {
    const wrapper = mountWorkbench();
    const textarea = wrapper.get<HTMLTextAreaElement>("#plan-source-text");

    expect(textarea.attributes("maxlength")).toBeUndefined();
    await textarea.setValue("😀".repeat(200_001));

    expect(textarea.element.value).toBe("华亚智能交易计划");
    expect(wrapper.get('[role="alert"]').text()).toContain("原文不能超过 200000 个字符");
    await wrapper.get('[data-testid="source-editor"]').trigger("submit");
    expect(wrapper.emitted("submitExtraction")).toBeUndefined();
  });

  it("caps over-limit source counting at the first rejected code point", async () => {
    const wrapper = mountWorkbench({ initialSourceText: "计".repeat(400_000) });

    expect(wrapper.get(".source-editor__count").text()).toContain("200001 / 200000");
    await wrapper.get('[data-testid="source-editor"]').trigger("submit");
    expect(wrapper.emitted("submitExtraction")).toBeUndefined();
  });

  it("rejects over-limit whitespace before evaluating source emptiness", async () => {
    const wrapper = mountWorkbench({ initialSourceText: " ".repeat(400_000) });

    await wrapper.get('[data-testid="source-editor"]').trigger("submit");

    expect(wrapper.emitted("submitExtraction")).toBeUndefined();
  });

  it("uses labelled native controls for the complete keyboard interaction surface", () => {
    const wrapper = mountWorkbench();

    expect(wrapper.get('label[for="ai-provider"]')).toBeTruthy();
    expect(wrapper.get('label[for="plan-source-text"]')).toBeTruthy();
    expect(wrapper.get("#ai-provider").element.tagName).toBe("SELECT");
    expect(wrapper.get("#plan-source-text").element.tagName).toBe("TEXTAREA");
    expect(wrapper.findAll("button").every((button) => button.element.tagName === "BUTTON")).toBe(
      true,
    );
  });
});
