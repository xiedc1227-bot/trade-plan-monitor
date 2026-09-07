import { createRequire } from "node:module";
import { join } from "node:path";
import { tmpdir } from "node:os";

import { expect, test } from "./fixtures";
import { createServer } from "vite";
import type { ViteDevServer } from "vite";

import type {
  ActivePlanView,
  ConfiguredAIRuntimeView,
  DashboardResponse,
  DraftReviewIssue,
  OperationReceipt,
  PlanExtractionView,
  PlanVersionSummary,
  PlanVersionView,
} from "../../src/api/generated";

const require = createRequire(import.meta.url);
const axePath = require.resolve("axe-core/axe.min.js");
const PROVIDER_ID = "00000000-0000-4000-8000-0000000000d5";
const OPERATION_ID = "00000000-0000-4000-8000-000000000201";
const TIME = "2026-09-02T09:00:00.000000+08:00";
const PLAN_VERSION_ID = "00000000-0000-4000-8000-000000000402";
const CROSS_SYMBOL_PLAN_VERSION_ID = "00000000-0000-4000-8000-000000000403";
const SAVED_PLAN_VERSION_ID = "00000000-0000-4000-8000-000000000404";
const CROSS_SYMBOL = "600000.SH";

const planDocument = JSON.stringify({
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
});

const persistedPlan: PlanVersionView = {
  canActivate: true,
  createdAt: TIME,
  id: PLAN_VERSION_ID,
  planHash: "a".repeat(64),
  planId: "huaya-smart",
  planJson: planDocument,
  reviewIssues: [],
  revision: 0,
  sourceText: planDocument,
  status: "DRAFT",
  symbol: "003043.SZ",
  validationIssues: [],
  version: 1,
};

const crossSymbolPlan: PlanVersionView = {
  ...persistedPlan,
  id: CROSS_SYMBOL_PLAN_VERSION_ID,
  planHash: "b".repeat(64),
  planId: "pudong-bank",
  planJson: JSON.stringify({
    ...JSON.parse(planDocument),
    market: "SSE",
    name: "浦发银行审核方案",
    plan_id: "pudong-bank",
    symbol: CROSS_SYMBOL,
  }),
  symbol: CROSS_SYMBOL,
};

const inactiveState: ActivePlanView = {
  active: false,
  changedAt: TIME,
  planVersionId: null,
  revision: 0,
  symbol: persistedPlan.symbol,
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

const dashboard: DashboardResponse = {
  connectionStatus: "CONNECTED",
  counts: { actionable: 0, blocked: 0, lowZoneWatch: 0, normal: 0, risk: 0, stale: 0 },
  dataAgeSeconds: 0,
  marketIndexes: [],
  observedAt: TIME,
  runtimeGeneration: "00000000-0000-4000-8000-000000000001",
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

const successfulExtraction: PlanExtractionView = {
  assumptions: [],
  completedAt: "2026-09-02T09:00:02.000000+08:00",
  draftPlanJson: planDocument,
  evidence: [{ end: 8, excerpt: "华亚智能交易计划", path: "draft", start: 0 }],
  id: OPERATION_ID,
  model: "deepseek-v4-flash",
  promptVersion: "plan-extract-v1",
  providerId: PROVIDER_ID,
  sourceTextSha256: "d".repeat(64),
  startedAt: "2026-09-02T09:00:01.000000+08:00",
  status: "SUCCEEDED",
  submittedAt: TIME,
  unmappedText: [],
  usage: null,
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
};

let server: ViteDevServer;
let baseUrl: string;

test.beforeAll(async () => {
  server = await createServer({
    clearScreen: false,
    logLevel: "silent",
    root: process.cwd(),
    server: { hmr: false, host: "127.0.0.1", port: 0 },
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

test("requires explicit review, save, and backend-approved activation for an AI result", async ({
  page,
}) => {
  const consoleFailures: string[] = [];
  const externalRequests: string[] = [];
  const savedDraftCommands: Record<string, unknown>[] = [];
  const activationCommands: Record<string, unknown>[] = [];
  let storedPlan: PlanVersionView | null = null;
  let activationState: ActivePlanView | null = null;

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
    let body: unknown;
    let status = 200;
    if (key === "GET /api/v1/dashboard") body = dashboard;
    else if (key === "GET /api/v1/ai-runtime") body = runtime;
    else if (key === "GET /api/v1/plan-versions") {
      body = {
        items: storedPlan === null ? [] : [planSummary(storedPlan)],
        limit: 100,
        offset: 0,
        total: storedPlan === null ? 0 : 1,
      };
    } else if (key.startsWith("GET /api/v1/plan-versions/")) {
      body = storedPlan ?? {};
    } else if (key.startsWith("GET /api/v1/plan-activation-states/")) {
      if (activationState === null) {
        const symbol = decodeURIComponent(
          key.slice("GET /api/v1/plan-activation-states/".length),
        );
        body = { ...inactiveState, symbol };
      } else {
        body = activationState;
      }
    } else if (key === "POST /api/v1/plan-extractions") {
      body = receipt;
      status = 202;
    } else if (key === `GET /api/v1/plan-extractions/${OPERATION_ID}`) {
      body = successfulExtraction;
    } else if (key === "POST /api/v1/plan-drafts") {
      const command = request.postDataJSON() as Record<string, unknown>;
      savedDraftCommands.push(command);
      storedPlan = {
        ...persistedPlan,
        id: SAVED_PLAN_VERSION_ID,
        planJson: String(command.planJson ?? ""),
        reviewIssues: (command.reviewIssues ?? []) as DraftReviewIssue[],
        sourceText: String(command.sourceText ?? ""),
      };
      activationState = { ...inactiveState, planVersionId: null };
      body = storedPlan;
    } else if (key === "POST /api/v1/plan-activations") {
      const command = request.postDataJSON() as Record<string, unknown>;
      activationCommands.push(command);
      storedPlan = storedPlan === null ? null : { ...storedPlan, revision: 1, status: "ACTIVE" };
      activationState = {
        ...inactiveState,
        active: true,
        planVersionId: SAVED_PLAN_VERSION_ID,
        revision: 1,
      };
      body = activationState;
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
  await expect(page.getByRole("tab", { name: /从原文 AI 提取/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await page.getByLabel("粘贴中文计划原文").fill("华亚智能交易计划");
  await page.getByRole("button", { name: "提交提取审核" }).click();
  await expect(page.getByText("结构化草稿已生成；仍需完成证据与重大问题审核。")).toBeVisible();
  await expect(page.getByTestId("enter-structured-review")).toBeVisible();
  await expect(page.locator("#ai-review-plan-name")).toHaveCount(0);
  expect(savedDraftCommands).toEqual([]);
  expect(activationCommands).toEqual([]);

  await page.getByTestId("enter-structured-review").click();
  await expect(page.locator("#ai-review-plan-name")).toHaveValue("华亚智能审核方案");
  expect(savedDraftCommands).toEqual([]);
  expect(activationCommands).toEqual([]);

  await page.getByRole("button", { name: "标记 MISSING_EVIDENCE draft 为已处理" }).click();
  await page.getByTestId("ai-review-save-draft").click();
  await expect(page.getByText("AI 审核结果已保存为持久草稿")).toBeVisible();
  expect(savedDraftCommands).toEqual([
    {
      expectedRevision: 0,
      planJson: planDocument,
      reviewIssues: [
        { kind: "MISSING_EVIDENCE", material: true, path: "draft", resolved: true },
      ],
      sourceText: "华亚智能交易计划",
    },
  ]);
  expect(activationCommands).toEqual([]);

  await page.getByTestId("request-activation").click();
  expect(activationCommands).toEqual([]);
  await page.locator("#confirm-plan-action").check();
  expect(activationCommands).toEqual([]);
  await page.getByTestId("confirm-plan-action").click();
  await expect(page.getByTestId("request-deactivation")).toBeVisible();
  expect(activationCommands).toEqual([
    { expectedRevision: 0, planVersionId: SAVED_PLAN_VERSION_ID },
  ]);
  expect(consoleFailures).toEqual([]);
  expect(externalRequests).toEqual([]);
});

test("runs the configured AI and persisted plan workbench flow in isolated Chromium", async ({ page }) => {
  const chartRequests: string[] = [];
  page.on("request", (request) => {
    if (/PriceChart|BacktestEquityChart|installCanvasRenderer|echarts/i.test(request.url())) {
      chartRequests.push(request.url());
    }
  });
  const consoleFailures: string[] = [];
  const externalRequests: string[] = [];
  const failedResponses: string[] = [];
  const apiRequests: string[] = [];
  let submittedBody: unknown;
  let idempotencyKey: string | null = null;
  const importCommands: unknown[] = [];
  const importIdempotencyKeys: string[] = [];
  const savedDraftCommands: unknown[] = [];
  let persistedVersions: PlanVersionView[] = [];

  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      consoleFailures.push(`${message.type()}:${message.text()}`);
    }
  });
  page.on("response", (response) => {
    if (response.status() >= 400) {
      failedResponses.push(`${response.status()} ${new URL(response.url()).pathname}`);
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
    else if (key === "GET /api/v1/plan-versions") {
      body = {
        items: persistedVersions.map(planSummary),
        limit: 100,
        offset: 0,
        total: persistedVersions.length,
      };
    } else if (key.startsWith("GET /api/v1/plan-versions/")) {
      const versionId = key.slice("GET /api/v1/plan-versions/".length);
      body = persistedVersions.find((plan) => plan.id === versionId) ?? {};
    } else if (key.startsWith("GET /api/v1/plan-activation-states/")) {
      const symbol = decodeURIComponent(
        key.slice("GET /api/v1/plan-activation-states/".length),
      );
      body = { ...inactiveState, symbol };
    } else if (key === "POST /api/v1/plan-imports") {
      const command = request.postDataJSON() as {
        document?: unknown;
        symbol?: unknown;
      };
      importCommands.push(command);
      importIdempotencyKeys.push(request.headers()["idempotency-key"] ?? "");
      const imported = command.symbol === CROSS_SYMBOL ? crossSymbolPlan : persistedPlan;
      const persisted = { ...imported, sourceText: String(command.document ?? "") };
      persistedVersions = [
        persisted,
        ...persistedVersions.filter((plan) => plan.id !== persisted.id),
      ];
      body = persisted;
    } else if (key === "POST /api/v1/plan-drafts") {
      const command = request.postDataJSON() as {
        planJson?: unknown;
        reviewIssues?: unknown;
        sourceText?: unknown;
      };
      savedDraftCommands.push(command);
      const saved = {
        ...persistedPlan,
        id: SAVED_PLAN_VERSION_ID,
        planHash: "c".repeat(64),
        planJson: String(command.planJson ?? ""),
        reviewIssues: command.reviewIssues as [],
        sourceText: String(command.sourceText ?? ""),
        version: 2,
      };
      persistedVersions = [
        saved,
        ...persistedVersions.filter((plan) => plan.id !== saved.id),
      ];
      body = saved;
    } else if (key === "POST /api/v1/plan-extractions") {
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
  const creationTabs = page.getByRole("tab");
  await expect(creationTabs.first()).toContainText("从原文 AI 提取");
  await expect(page.getByRole("tab", { name: /从原文 AI 提取/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(chartRequests).toEqual([]);
  await expect(page.getByRole("heading", { name: "AI 计划提取审核" })).toBeVisible();
  await page.getByRole("tab", { name: /导入 JSON \/ YAML/ }).click();
  const planViewWidth = await page.locator(".plan-drafting-view").evaluate(
    (element) => element.getBoundingClientRect().width,
  );
  const importPanelWidth = await page.locator(".plan-import").evaluate(
    (element) => element.getBoundingClientRect().width,
  );
  const importPanelHeight = await page.locator(".plan-import").evaluate(
    (element) => element.getBoundingClientRect().height,
  );
  expect(importPanelWidth).toBeGreaterThan(planViewWidth * 0.9);
  expect(importPanelHeight).toBeLessThan(400);
  await expect(page.getByRole("tab", { name: /导入 JSON \/ YAML/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(page.getByRole("heading", { name: "AI 计划提取审核" })).toBeHidden();
  await page.getByRole("tab", { name: /从原文 AI 提取/ }).click();
  await expect(page.getByText("配置文件只读")).toBeVisible();
  await expect(page.getByText("deepseek-v4-flash", { exact: true })).toBeVisible();
  await expect(page.locator("#provider-secret")).toHaveCount(0);

  const source = "华亚智能：回踩 20.10 至 20.50 分批关注。";
  await page.getByLabel("粘贴中文计划原文").fill(source);
  await page.getByRole("button", { name: "提交提取审核" }).click();
  await expect(
    page.getByText("AI 输出未通过封闭契约校验，未保存为可执行规则。"),
  ).toBeVisible();

  expect(submittedBody).toEqual({
    expectedRevision: 0,
    providerId: PROVIDER_ID,
    sourceText: source,
  });
  expect(idempotencyKey).toMatch(/^[0-9a-f-]{36}$/);
  await page.getByRole("tab", { name: /导入 JSON \/ YAML/ }).click();
  const importForm = page.getByTestId("plan-import-form");
  await importForm.getByLabel("计划文档").fill(planDocument);
  await importForm.getByLabel("导入目标股票").fill(persistedPlan.symbol);
  await page.getByRole("button", { name: "提交后端安全导入" }).click();
  await expect(page.getByText("v1 · 003043.SZ")).toBeVisible();
  const versionWorkspaceWidth = await page.locator(".plans-view").evaluate(
    (element) => element.getBoundingClientRect().width,
  );
  expect(versionWorkspaceWidth).toBeGreaterThan(planViewWidth * 0.9);
  expect(importIdempotencyKeys[0]).toMatch(/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/);
  expect(importCommands[0]).toEqual({
    document: planDocument,
    expectedRevision: 0,
    format: "JSON",
    symbol: persistedPlan.symbol,
  });

  await page.goto(`${baseUrl}/plans/${PLAN_VERSION_ID}`);
  await expect(page.getByRole("heading", { level: 1, name: "计划工作台" })).toBeVisible();
  await expect(page.locator("#plan-name")).toHaveValue("华亚智能审核方案");
  await page.locator("#plan-name").fill("华亚智能浏览器保存方案");
  await page.getByTestId("save-draft").click();
  await expect(page.locator("#plan-name")).toHaveValue("华亚智能浏览器保存方案");
  expect(savedDraftCommands).toHaveLength(1);
  expect(savedDraftCommands[0]).toMatchObject({
    basePlanVersionId: PLAN_VERSION_ID,
    expectedRevision: 0,
    sourceText: planDocument,
  });
  expect(JSON.parse((savedDraftCommands[0] as { planJson: string }).planJson)).toMatchObject({
    name: "华亚智能浏览器保存方案",
  });

  await page.goto(`${baseUrl}/plans/${SAVED_PLAN_VERSION_ID}`);
  await expect(page.locator("#plan-name")).toHaveValue("华亚智能浏览器保存方案");
  await page.locator("#plan-export-format").selectOption("YAML");
  const downloadPromise = page.waitForEvent("download");
  await page.getByTestId("export-plan").click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe(`trade-plan-${SAVED_PLAN_VERSION_ID}.yaml`);

  await page.goto(`${baseUrl}/plans`);
  await expect(page.getByText("v1 · 003043.SZ")).toBeVisible();
  await page.getByRole("tab", { name: /导入 JSON \/ YAML/ }).click();
  const crossSymbolImportForm = page.getByTestId("plan-import-form");
  await crossSymbolImportForm.getByLabel("计划文档").fill(crossSymbolPlan.planJson);
  await crossSymbolImportForm.getByLabel("导入目标股票").fill(CROSS_SYMBOL);
  await crossSymbolImportForm.getByRole("button", { name: "提交后端安全导入" }).click();
  await expect(page.getByText(`v1 · ${CROSS_SYMBOL}`)).toBeVisible();
  expect(importCommands[1]).toEqual({
    document: crossSymbolPlan.planJson,
    expectedRevision: 0,
    format: "JSON",
    symbol: CROSS_SYMBOL,
  });
  expect(importIdempotencyKeys[1]).toMatch(/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/);
  const secondImportIndex = apiRequests.lastIndexOf("POST /api/v1/plan-imports");
  const targetStateIndex = apiRequests.indexOf(
    `GET /api/v1/plan-activation-states/${CROSS_SYMBOL}`,
  );
  expect(targetStateIndex).toBeGreaterThan(-1);
  expect(targetStateIndex).toBeLessThan(secondImportIndex);

  await page.reload();
  await expect(page.getByText(`v1 · ${CROSS_SYMBOL}`)).toBeVisible();
  await expect(page.getByText("v1 · 003043.SZ")).toBeVisible();
  expect(apiRequests).toEqual(
    expect.arrayContaining([
      "GET /api/v1/dashboard",
      "GET /api/v1/ai-runtime",
      "GET /api/v1/plan-versions",
      "POST /api/v1/plan-extractions",
      `GET /api/v1/plan-extractions/${OPERATION_ID}`,
      "POST /api/v1/plan-imports",
      "POST /api/v1/plan-drafts",
      `GET /api/v1/plan-activation-states/${persistedPlan.symbol}`,
      `GET /api/v1/plan-activation-states/${CROSS_SYMBOL}`,
    ]),
  );

  for (const width of [320, 768, 1024, 1440]) {
    await page.setViewportSize({ height: 900, width });
    const layout = await page.evaluate(() => ({
      horizontalOverflow:
        document.documentElement.scrollWidth - document.documentElement.clientWidth,
      overflowingElements: [...document.querySelectorAll<HTMLElement>("body *")]
        .filter(
          (element) =>
            element.children.length === 0 &&
            element.getBoundingClientRect().right > window.innerWidth + 1,
        )
        .slice(-20)
        .map((element) => ({
          className: element.className,
          left: Math.round(element.getBoundingClientRect().left),
          right: Math.round(element.getBoundingClientRect().right),
          tagName: element.tagName,
          text: element.textContent?.slice(0, 40),
        })),
    }));
    expect(
      layout.horizontalOverflow,
      `viewport ${width}px: ${JSON.stringify(layout.overflowingElements)}`,
    ).toBeLessThanOrEqual(1);
  }

  await page.setViewportSize({ height: 900, width: 320 });
  const mobileImportTab = await page.getByRole("tab", { name: /导入 JSON \/ YAML/ }).boundingBox();
  const mobileAiTab = await page.getByRole("tab", { name: /从原文 AI 提取/ }).boundingBox();
  expect(mobileImportTab).not.toBeNull();
  expect(mobileAiTab).not.toBeNull();
  expect(mobileImportTab?.y).toBeGreaterThan(mobileAiTab?.y ?? Number.POSITIVE_INFINITY);

  await page.setViewportSize({ height: 900, width: 1440 });

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
  expect(failedResponses).toEqual([]);
  expect(consoleFailures).toEqual([]);
  expect(externalRequests).toEqual([]);
  expect(chartRequests).toEqual([]);
});
