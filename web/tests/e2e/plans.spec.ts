import { createRequire } from "node:module";
import { join } from "node:path";
import { tmpdir } from "node:os";

import { expect, test } from "@playwright/test";
import { createServer } from "vite";
import type { ViteDevServer } from "vite";

import type {
  ConfiguredAIRuntimeView,
  DashboardResponse,
  OperationReceipt,
  PlanExtractionView,
} from "../../src/api/generated";

const require = createRequire(import.meta.url);
const axePath = require.resolve("axe-core/axe.min.js");
const PROVIDER_ID = "00000000-0000-4000-8000-0000000000d5";
const OPERATION_ID = "00000000-0000-4000-8000-000000000201";
const TIME = "2026-09-02T09:00:00.000000+08:00";

const dashboard: DashboardResponse = {
  connectionStatus: "CONNECTED",
  counts: { actionable: 0, blocked: 0, lowZoneWatch: 0, normal: 0, risk: 0, stale: 0 },
  dataAgeSeconds: 0,
  marketIndexes: [],
  observedAt: TIME,
  sequence: 1,
  symbols: [],
};

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
  submittedAt: TIME,
};

const invalidExtraction: PlanExtractionView = {
  assumptions: [],
  completedAt: "2026-09-02T09:00:02.000000+08:00",
  draftPlanJson: null,
  evidence: [],
  id: OPERATION_ID,
  model: null,
  promptVersion: null,
  providerId: PROVIDER_ID,
  sourceTextSha256: null,
  startedAt: "2026-09-02T09:00:01.000000+08:00",
  status: "INVALID_OUTPUT",
  submittedAt: TIME,
  unmappedText: [],
  usage: null,
  validationIssues: [],
  warnings: [],
};

let server: ViteDevServer;
let baseUrl: string;

test.beforeAll(async () => {
  server = await createServer({
    clearScreen: false,
    logLevel: "silent",
    root: process.cwd(),
    server: { host: "127.0.0.1", port: 0 },
  });
  await server.listen();
  const address = server.httpServer?.address();
  if (address === null || address === undefined || typeof address === "string") {
    throw new Error("Vite plan harness did not expose a local port");
  }
  baseUrl = `http://127.0.0.1:${address.port}`;
});

test.afterAll(async () => {
  await server.close();
});

test("runs the read-only file-configured AI plan flow in isolated Chromium", async ({ page }) => {
  const consoleFailures: string[] = [];
  const externalRequests: string[] = [];
  const apiRequests: string[] = [];
  let submittedBody: unknown;
  let idempotencyKey: string | null = null;

  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      consoleFailures.push(`${message.type()}:${message.text()}`);
    }
  });
  page.on("request", (request) => {
    const requestUrl = new URL(request.url());
    if (requestUrl.host !== new URL(baseUrl).host) externalRequests.push(request.url());
  });
  await page.route(`${baseUrl}/api/v1/**`, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const key = `${request.method()} ${path}`;
    apiRequests.push(key);
    let body: unknown;
    let status = 200;
    if (key === "GET /api/v1/dashboard") body = dashboard;
    else if (key === "GET /api/v1/ai-runtime") body = runtime;
    else if (key === "POST /api/v1/plan-extractions") {
      submittedBody = request.postDataJSON();
      idempotencyKey = request.headers()["idempotency-key"] ?? null;
      body = receipt;
      status = 202;
    } else if (key === `GET /api/v1/plan-extractions/${OPERATION_ID}`) {
      body = invalidExtraction;
    } else {
      await route.fulfill({ body: "unexpected request", status: 500 });
      return;
    }
    await route.fulfill({
      body: JSON.stringify(body),
      contentType: "application/json; charset=utf-8",
      status,
    });
  });

  await page.goto(`${baseUrl}/plans`);
  await expect(page.getByRole("heading", { level: 1, name: "计划工作台" })).toBeVisible();
  await expect(page.getByText("配置文件只读")).toBeVisible();
  await expect(page.getByText("deepseek-v4-flash", { exact: true })).toBeVisible();
  await expect(page.locator("#provider-secret")).toHaveCount(0);

  const source = "华亚智能：回踩 20.10 至 20.50 分批关注。";
  await page.getByLabel("粘贴中文计划原文").fill(source);
  await page.getByRole("button", { name: "提交提取审核" }).click();
  await expect(page.getByRole("alert")).toContainText("AI 输出未通过封闭契约校验");

  expect(submittedBody).toEqual({
    expectedRevision: 0,
    providerId: PROVIDER_ID,
    sourceText: source,
  });
  expect(idempotencyKey).toMatch(/^[0-9a-f-]{36}$/);
  expect(apiRequests).toEqual([
    "GET /api/v1/dashboard",
    "GET /api/v1/ai-runtime",
    "POST /api/v1/plan-extractions",
    `GET /api/v1/plan-extractions/${OPERATION_ID}`,
  ]);

  await page.addScriptTag({ path: axePath });
  const seriousViolations = await page.evaluate(async () => {
    const axe = (globalThis as typeof globalThis & {
      axe: { run: (root: Document, options: object) => Promise<{ violations: { impact: string | null }[] }> };
    }).axe;
    const result = await axe.run(document, {
      runOnly: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"],
    });
    return result.violations.filter(
      (violation) => violation.impact === "serious" || violation.impact === "critical",
    );
  });
  await page.screenshot({
    fullPage: true,
    path: join(tmpdir(), "trade-plan-monitor-plans.png"),
  });

  expect(seriousViolations).toEqual([]);
  expect(consoleFailures).toEqual([]);
  expect(externalRequests).toEqual([]);
});
