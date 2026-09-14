import { createServer, type ViteDevServer } from "vite";
import { expect, test } from "./fixtures";

let server: ViteDevServer;
let baseUrl: string;
const providerId = "00000000-0000-4000-8000-0000000000d5";
const operationId = "00000000-0000-4000-8000-000000000201";
const submittedAt = "2026-09-14T14:38:12+08:00";

test.beforeAll(async () => {
  server = await createServer({ clearScreen: false, logLevel: "silent", root: process.cwd(),
    server: { hmr: false, host: "127.0.0.1", port: 0 } });
  await server.listen();
  const address = server.httpServer?.address();
  if (!address || typeof address === "string") throw new Error("No isolated local port");
  baseUrl = `http://127.0.0.1:${address.port}`;
});
test.afterAll(async () => { await server?.close(); });

for (const { status, diagnosticStatus, queryFailure } of [
  { status: "PROVIDER_ERROR", diagnosticStatus: "RECORDED", queryFailure: false },
  { status: "INVALID_OUTPUT", diagnosticStatus: "WRITE_FAILED", queryFailure: false },
  { status: "PROVIDER_ERROR", diagnosticStatus: "RECORDED", queryFailure: true },
]) {
  test(`preserves ${status} after queued/running production DTOs (${diagnosticStatus}, query recovery ${queryFailure})`, async ({ page }) => {
    let polls = 0;
    let submissions = 0;
    let failedQuery = false;
    const unexpected: string[] = [];
    await page.route("**/*", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.origin !== baseUrl) {
        unexpected.push(request.url());
        return route.abort();
      }
      if (!url.pathname.startsWith("/api/")) return route.continue();
      let body: unknown;
      let httpStatus = 200;
      if (url.pathname === "/api/v1/ai-runtime") {
        body = { baseUrl: "https://api.deepseek.com/", configured: true, enabled: true,
          displayName: "DeepSeek", maxInputChars: 50_000, maxOutputTokens: 4096,
          model: "deepseek-v4-pro", providerId, revision: 0 };
      } else if (url.pathname === "/api/v1/plan-versions") {
        body = { items: [], limit: 100, offset: 0, total: 0 };
      } else if (url.pathname === "/api/v1/dashboard") {
        body = { observedAt: submittedAt, runtimeGeneration: "00000000-0000-4000-8000-000000000001", sequence: 1, symbols: [] };
      } else if (url.pathname === "/api/v1/plan-extractions" && request.method() === "POST") {
        submissions += 1;
        httpStatus = 202;
        body = { kind: "PLAN_EXTRACTION", operationId, status: "QUEUED", submittedAt };
      } else if (url.pathname === `/api/v1/plan-extractions/${operationId}`) {
        if (queryFailure && !failedQuery) {
          failedQuery = true;
          return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ malformed: true }) });
        }
        const state = ["QUEUED", "RUNNING", status][Math.min(polls++, 2)];
        const terminal = state === status;
        body = { id: operationId, providerId, status: state, submittedAt,
          startedAt: state === "QUEUED" ? null : "2026-09-14T14:38:13+08:00",
          completedAt: terminal ? "2026-09-14T14:38:42+08:00" : null,
          sourceTextSha256: null, model: null, promptVersion: null, draftPlanJson: null,
          mapping: null, evidence: [], assumptions: [], warnings: [], unmappedText: [],
          validationIssues: [], usage: null, diagnosticStatus: terminal ? diagnosticStatus : null };
      } else {
        unexpected.push(`${request.method()} ${url.pathname}`);
        return route.abort();
      }
      await route.fulfill({ status: httpStatus, contentType: "application/json", body: JSON.stringify(body) });
    });
    await page.goto(`${baseUrl}/plans`);
    await page.getByLabel("粘贴中文计划原文").fill("离线诊断契约测试：价格低于 60 元买入 100 股。");
    await page.getByRole("button", { name: "提交提取审核" }).click();
    if (queryFailure) {
      await expect(page.getByText(/无法确认 AI 提取状态/)).toBeVisible();
      await page.getByRole("button", { name: "重新查询提取状态", exact: true }).click();
    }
    await expect(page.getByText("提取任务已排队，尚未执行模型调用。", { exact: true })).toBeVisible();
    await expect(page.getByText("正在提取并校验计划草稿。", { exact: true })).toBeVisible();
    await expect(page.locator(".extraction-evidence")).toContainText(status === "PROVIDER_ERROR" ? "供应商" : "未通过");
    await expect(page.getByText(/无法确认 AI 提取状态/)).toHaveCount(0);
    await expect(page.getByRole("button", { name: "保存并进入逐项复核" })).toHaveCount(0);
    expect(submissions).toBe(1);
    expect(polls).toBe(3);
    expect(unexpected).toEqual([]);
  });
}
