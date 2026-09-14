import { flushPromises, mount } from "@vue/test-utils";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { defineComponent, h } from "vue";
import { describe, expect, it, vi } from "vitest";

import { createAIPlanApi } from "../../src/api/ai";
import { usePlanDrafting } from "../../src/composables/usePlanDrafting";

const providerId = "00000000-0000-4000-8000-0000000000d5";
const operationId = "00000000-0000-4000-8000-000000000201";
const submittedAt = "2026-09-14T14:38:12+08:00";
const runtime = {
  baseUrl: "https://api.deepseek.com/", configured: true, displayName: "DeepSeek",
  enabled: true, maxInputChars: 50_000, maxOutputTokens: 4096,
  model: "deepseek-v4-pro", providerId, revision: 0,
};

// Keep all nullable/defaulted public DTO fields: production serializes these too.
function extraction(status: string, diagnosticStatus: unknown) {
  return {
    id: operationId, providerId, status, submittedAt,
    startedAt: status === "QUEUED" ? null : "2026-09-14T14:38:13+08:00",
    completedAt: ["QUEUED", "RUNNING"].includes(status) ? null : "2026-09-14T14:38:42+08:00",
    sourceTextSha256: null, model: null, promptVersion: null,
    draftPlanJson: null, mapping: null, evidence: [], assumptions: [], warnings: [],
    unmappedText: [], validationIssues: [], usage: null, diagnosticStatus,
  };
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("production extraction diagnostic contract", () => {
  it("accepts the three preserved R17 failure responses unchanged", async () => {
    const captured = JSON.parse(readFileSync(resolve(
      "../remediation/evidence/R17-execution-20260914/observed-extractions.json",
    ), "utf8")) as Array<{ id: string }>;
    for (const body of captured) {
      const api = createAIPlanApi(vi.fn(async () => json(body)) as typeof fetch);
      await expect(api.getExtraction(body.id)).resolves.toEqual(body);
    }
  });

  it("accepts the backend's partial review draft with no field bindings", async () => {
    const body = JSON.parse(readFileSync(resolve(
      "tests/fixtures/ai-partial-extraction.json",
    ), "utf8"));
    const api = createAIPlanApi(vi.fn(async () => json(body)) as typeof fetch);
    await expect(api.getExtraction(body.id)).resolves.toEqual(body);
    expect(body.validationIssues.some((issue: { activationBlocking: boolean }) => issue.activationBlocking)).toBe(true);
  });

  it.each([
    ["QUEUED", null], ["RUNNING", null], ["INVALID_OUTPUT", null],
    ["INVALID_OUTPUT", "RECORDED"], ["PROVIDER_ERROR", "RECORDED"],
    ["PROVIDER_ERROR", "WRITE_FAILED"], ["CANCELLED", null],
  ])("accepts %s with diagnosticStatus %s", async (status, diagnosticStatus) => {
    const body = extraction(String(status), diagnosticStatus);
    const api = createAIPlanApi(vi.fn(async () => json(body)) as typeof fetch);
    await expect(api.getExtraction(operationId)).resolves.toEqual(body);
  });

  it.each(["RECORD_FAILED", "recorded", "", 1, false, {}, []])(
    "rejects invalid diagnostic status %j", async (diagnosticStatus) => {
      const api = createAIPlanApi(vi.fn(async () => json(extraction("INVALID_OUTPUT", diagnosticStatus))) as typeof fetch);
      await expect(api.getExtraction(operationId)).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    },
  );

  it("accepts an omitted diagnostic status but rejects an unknown extraction status", async () => {
    const { diagnosticStatus: _omitted, ...compatible } = extraction("INVALID_OUTPUT", null);
    const api = createAIPlanApi(vi.fn(async () => json(compatible)) as typeof fetch);
    await expect(api.getExtraction(operationId)).resolves.toEqual(compatible);
    const invalid = createAIPlanApi(vi.fn(async () => json({
      ...compatible, status: "READY_TO_ACTIVATE",
    })) as typeof fetch);
    await expect(invalid.getExtraction(operationId)).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("still rejects unrelated response fields", async () => {
    const api = createAIPlanApi(vi.fn(async () => json({
      ...extraction("INVALID_OUTPUT", "RECORDED"), rawProviderResponse: "private",
    })) as typeof fetch);
    await expect(api.getExtraction(operationId)).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("retains an accepted operation after a query failure and recovers with GET only", async () => {
    let submissions = 0;
    let unavailable = true;
    const queried: string[] = [];
    const terminal = extraction("INVALID_OUTPUT", "RECORDED");
    const api = createAIPlanApi(vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/v1/ai-runtime") return json(runtime);
      if (init?.method === "POST") {
        submissions += 1;
        return json({ kind: "PLAN_EXTRACTION", operationId, status: "QUEUED", submittedAt }, 202);
      }
      queried.push(url);
      if (unavailable) throw new TypeError("Local query unavailable");
      return json(terminal);
    }) as typeof fetch);
    let drafting!: ReturnType<typeof usePlanDrafting>;
    const wrapper = mount(defineComponent({ setup() {
      drafting = usePlanDrafting({ api, pollIntervalMs: 0, createIdempotencyKey: () => "query-recovery" });
      return () => h("div");
    } }));
    try {
      await flushPromises();
      await drafting.submitExtraction({ providerId, expectedRevision: 0, sourceText: "离线查询恢复测试" });
      expect(drafting.extraction.value).toMatchObject({ id: operationId, status: "QUEUED" });
      expect(drafting.errorMessage.value).toBeTruthy();
      expect(drafting.errorMessage.value).not.toMatch(/重新提交|重新提取/);
      unavailable = false;
      await drafting.retryExtraction();
      expect(drafting.extraction.value).toEqual(terminal);
      expect(drafting.errorMessage.value).toBeNull();
      expect(submissions).toBe(1);
      expect(queried).toEqual([
        `/api/v1/plan-extractions/${operationId}`, `/api/v1/plan-extractions/${operationId}`,
      ]);
    } finally {
      wrapper.unmount();
    }
  });

  it.each(["RECORDED", "WRITE_FAILED", null])(
    "polls queued and running DTOs through the real client and preserves terminal diagnostics %s", async (diagnosticStatus) => {
      const results = [extraction("QUEUED", null), extraction("RUNNING", null), extraction("PROVIDER_ERROR", diagnosticStatus)];
      let submissions = 0;
      let polls = 0;
      const api = createAIPlanApi(vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (String(input) === "/api/v1/ai-runtime") return json(runtime);
        if (init?.method === "POST") {
          submissions += 1;
          return json({ kind: "PLAN_EXTRACTION", operationId, status: "QUEUED", submittedAt }, 202);
        }
        return json(results[polls++]);
      }) as typeof fetch);
      let drafting!: ReturnType<typeof usePlanDrafting>;
      const wrapper = mount(defineComponent({ setup() {
        drafting = usePlanDrafting({ api, pollIntervalMs: 0, createIdempotencyKey: () => "diagnostic-contract" });
        return () => h("div");
      } }));
      try {
        await flushPromises();
        await drafting.submitExtraction({ providerId, expectedRevision: 0, sourceText: "离线诊断契约测试" });
        expect(drafting.errorMessage.value).toBeNull();
        expect(drafting.extraction.value).toEqual(results[2]);
        expect(submissions).toBe(1);
        expect(polls).toBe(3);
      } finally {
        wrapper.unmount();
      }
    },
  );
});
