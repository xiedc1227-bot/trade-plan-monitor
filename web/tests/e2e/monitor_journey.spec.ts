import type { Page } from "@playwright/test";

import type {
  AIProviderPage,
  AIProviderSecretCommand,
  AIProviderTestCommand,
  AIProviderView,
  ActivePlanView,
  AlertPage,
  OperationReceipt,
  PlanActivationCommand,
  PlanDraftCommand,
  PlanExtractionCommand,
  PlanExtractionView,
  PlanVersionView,
  PositionLotPage,
  components,
} from "../../src/api/generated";
import type { PositionOperations } from "../../src/composables/usePositions";
import type { AlertOperations, AlertQuery } from "../../src/views/AlertsView.vue";
import { expect, reviewedPlanJson, test } from "./fixtures";

type PositionLot =
  components["schemas"]["trade_plan_monitor__web__routers__positions__PositionLotView"];

const sourceText = "华亚智能交易计划：6300 至 6450 分批关注，报告时间请人工核对。";

test("completes the reviewed plan-to-alert-to-manual-fill journey", async ({
  journey,
  page,
}) => {
  await mountJourney(page, journey.baseUrl);

  await expect(page.getByRole("heading", { level: 1, name: "AI 计划提取审核" })).toBeVisible();
  const providerRegion = page.getByRole("region", { name: "供应商与密钥状态" });
  await expect(page.getByLabel("已配置供应商")).toContainText("确定性假 AI");
  await expect(providerRegion).toContainText("未配置");

  await page.getByLabel("替换 API 密钥").fill("sk-fake-e2e");
  await page.getByRole("button", { name: "写入替换" }).click();
  await expect(providerRegion).toContainText("********");
  await page.getByRole("button", { name: "测试连接" }).click();
  await expect(providerRegion.getByRole("status")).toContainText("连接测试已排队");

  await page.getByLabel("粘贴中文计划原文").fill(sourceText);
  await page.getByRole("button", { name: "提交提取审核" }).click();
  await expect(page.getByText("结构化草稿已生成；仍需完成证据与重大问题审核。")).toBeVisible();
  await expect(page.getByTestId("unresolved-material-count")).toHaveText("未解决重大问题：1");
  await expect(page.getByRole("button", { name: "保存审核后的草稿" })).toBeDisabled();

  await page
    .getByRole("button", { name: "标记 WARNING metadata.report_at 为已处理" })
    .click();
  await expect(page.getByTestId("unresolved-material-count")).toHaveText("未解决重大问题：0");
  await page.getByRole("button", { name: "保存审核后的草稿" }).click();

  await expect(page.getByRole("heading", { level: 1, name: "计划版本与激活" })).toBeVisible();
  await page.getByTestId("request-activation").click();
  const activationDialog = page.getByRole("dialog", { name: "确认激活计划" });
  await expect(activationDialog).toBeVisible();
  await activationDialog
    .getByLabel("我已核对前后差异，并明确确认本次激活。")
    .check();
  await activationDialog.getByRole("button", { name: "确认激活" }).click();

  await expect(page.getByRole("heading", { level: 1, name: "确定性行情回放" })).toBeVisible();
  await page.getByRole("button", { name: "运行确定性行情回放" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "文字提醒中心" })).toBeVisible();
  await expect(page.getByRole("button", { name: "确认已查看（不代表成交）" })).toHaveCount(1);

  await page.getByRole("button", { name: "确认已查看（不代表成交）" }).click();
  await expect(
    page.getByRole("button", { name: "已确认；确认提醒不代表成交，也不会修改持仓" }),
  ).toBeDisabled();
  await expect(page.getByTestId("position-count-after-acknowledgement")).toHaveText(
    "确认提醒后的持仓批次：0",
  );
  expect(journey.snapshot()).toMatchObject({
    acknowledged: true,
    alertCount: 1,
    positionCount: 0,
  });

  await page.getByRole("button", { name: "登记真实成交" }).click();
  await expect(page.getByRole("heading", { level: 2, name: "人工持仓批次" })).toBeVisible();
  await expect(page.getByRole("status")).toContainText("确认提醒不等于成交");
  await page.getByLabel("成本（分）").fill("6420");
  await page.getByRole("button", { name: "复核建仓" }).click();
  const positionDialog = page.getByRole("dialog", { name: "确认手工持仓变更" });
  await expect(positionDialog).toContainText("确认提醒不等于成交");
  await positionDialog.getByRole("button", { name: "确认登记" }).click();
  await expect(page.getByRole("row", { name: /底仓 2026-08-24 6420 100 100/ })).toBeVisible();

  const snapshot = journey.snapshot();
  expect(snapshot).toMatchObject({ acknowledged: true, alertCount: 1, positionCount: 1 });
  expect(snapshot.mutations.map(({ path }) => path)).toEqual([
    "/api/v1/ai-provider-secrets",
    "/api/v1/ai-provider-tests",
    "/api/v1/plan-extractions",
    "/api/v1/plan-drafts",
    "/api/v1/plan-activations",
    "/api/v1/alert-acknowledgements",
    "/api/v1/position-lots",
  ]);
  expect(snapshot.mutations.every(({ idempotencyKeyPresent }) => idempotencyKeyPresent)).toBe(true);
  expect(snapshot.mutations.every(({ jsonContentTypePresent }) => jsonContentTypePresent)).toBe(
    true,
  );
});

async function mountJourney(page: Page, baseUrl: string): Promise<void> {
  await page.route(`${baseUrl}/t055-monitor-journey`, async (route) => {
    await route.fulfill({
      body: '<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>完整监控旅程</title></head><body><div id="app"></div></body></html>',
      contentType: "text/html",
    });
  });
  await page.goto(`${baseUrl}/t055-monitor-journey`);
  await page.evaluate(
    async ({ expectedPlanJson }) => {
      const vuePath = "/@id/vue";
      const workbenchPath = "/src/components/plans/PlanWorkbench.vue";
      const plansPath = "/src/views/PlansView.vue";
      const alertsPath = "/src/views/AlertsView.vue";
      const positionsPath = "/src/components/symbol/PositionLots.vue";
      const tokensPath = "/src/assets/tokens.css";
      const vue = (await import(vuePath)) as typeof import("vue");
      const PlanWorkbench = (await import(workbenchPath)).default;
      const PlansView = (await import(plansPath)).default;
      const AlertsView = (await import(alertsPath)).default;
      const PositionLots = (await import(positionsPath)).default;
      await import(tokensPath);

      type Stage = "ALERTS" | "PLANS" | "POSITIONS" | "REPLAY" | "WORKBENCH";
      const apiRoot = "/api/v1";
      const symbol = "003043.SZ";
      const activeState = vue.shallowRef<ActivePlanView>({
        active: false,
        changedAt: "2026-08-24T09:00:00+08:00",
        planVersionId: null,
        revision: 0,
        symbol,
      });
      const alertsPage = vue.shallowRef<AlertPage | null>(null);
      const extraction = vue.shallowRef<PlanExtractionView | null>(null);
      const positionPage = vue.shallowRef<PositionLotPage | null>(null);
      const providerTestProviderId = vue.shallowRef<string | null>(null);
      const providerTestReceipt = vue.shallowRef<OperationReceipt | null>(null);
      const providers = vue.shallowRef<readonly AIProviderView[]>([]);
      const replayBusy = vue.shallowRef(false);
      const stage = vue.shallowRef<Stage>("WORKBENCH");
      const versions = vue.shallowRef<readonly PlanVersionView[]>([]);

      async function request<Value>(path: string, init?: RequestInit): Promise<Value> {
        const response = await fetch(`${apiRoot}${path}`, init);
        if (!response.ok) {
          throw new Error(`API ${response.status}: ${await response.text()}`);
        }
        return (await response.json()) as Value;
      }

      function mutationInit(
        command: unknown,
        idempotencyKey: string = crypto.randomUUID(),
      ): RequestInit {
        return {
          body: JSON.stringify(command),
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": idempotencyKey,
          },
          method: "POST",
        };
      }

      function alertQueryPath(query: AlertQuery): string {
        const parameters = new URLSearchParams({
          limit: String(query.limit),
          offset: String(query.offset),
        });
        if (query.acknowledged !== null) parameters.set("acknowledged", String(query.acknowledged));
        if (query.endAt !== null) parameters.set("endAt", query.endAt);
        if (query.signalType !== null) parameters.set("signalType", query.signalType);
        if (query.startAt !== null) parameters.set("startAt", query.startAt);
        if (query.symbol !== null) parameters.set("symbol", query.symbol);
        return `/alerts?${parameters.toString()}`;
      }

      const alertOperations: AlertOperations = {
        acknowledgeAlert: ({ command, idempotencyKey }) =>
          request("/alert-acknowledgements", mutationInit(command, idempotencyKey)),
        listAlerts: (query) => request(alertQueryPath(query)),
      };

      const positionOperations: PositionOperations = {
        closePosition: () => Promise.reject(new Error("closure is outside the T055 journey")),
        createPosition: ({ command, idempotencyKey }) =>
          request<PositionLot>("/position-lots", mutationInit(command, idempotencyKey)),
        listPositions: ({ asOfTradeDate, limit, offset, symbol: requestedSymbol }) => {
          const parameters = new URLSearchParams({
            asOfTradeDate,
            limit: String(limit),
            offset: String(offset),
            symbol: requestedSymbol,
          });
          return request(`/position-lots?${parameters.toString()}`);
        },
      };

      async function replaceSecret(command: AIProviderSecretCommand): Promise<void> {
        const provider = await request<AIProviderView>(
          "/ai-provider-secrets",
          mutationInit(command),
        );
        providers.value = Object.freeze([provider]);
      }

      async function testProvider(command: AIProviderTestCommand): Promise<void> {
        providerTestProviderId.value = command.providerId;
        providerTestReceipt.value = await request(
          "/ai-provider-tests",
          mutationInit(command),
        );
      }

      async function submitExtraction(command: PlanExtractionCommand): Promise<void> {
        const receipt = await request<OperationReceipt>(
          "/plan-extractions",
          mutationInit(command),
        );
        extraction.value = await request(`/plan-extractions/${receipt.operationId}`);
      }

      async function saveDraft(
        extractionValue: PlanExtractionView,
        resolvedIssueKeys: readonly string[],
        reviewedSourceText: string,
      ): Promise<void> {
        if (extractionValue.draftPlanJson !== expectedPlanJson) {
          throw new Error("fixture extraction returned an unexpected plan document");
        }
        const command: PlanDraftCommand = {
          expectedRevision: 0,
          planJson: extractionValue.draftPlanJson,
          reviewIssues: [
            {
              kind: "WARNING",
              material: true,
              path: "metadata.report_at",
              resolved: resolvedIssueKeys.includes("WARNING:metadata.report_at"),
            },
          ],
          sourceText: reviewedSourceText,
        };
        const version = await request<PlanVersionView>("/plan-drafts", mutationInit(command));
        versions.value = Object.freeze([version]);
        stage.value = "PLANS";
      }

      async function activatePlan(command: PlanActivationCommand): Promise<void> {
        activeState.value = await request("/plan-activations", mutationInit(command));
        stage.value = "REPLAY";
      }

      async function runReplay(): Promise<void> {
        replayBusy.value = true;
        try {
          await request(`/symbols/${symbol}`);
          const range = new URLSearchParams({
            endAt: "2026-08-24T10:05:00+08:00",
            interval: "FIVE_MINUTES",
            limit: "100",
            offset: "0",
            startAt: "2026-08-24T09:30:00+08:00",
          });
          await request(`/symbols/${symbol}/bars?${range.toString()}`);
          range.delete("interval");
          await request(`/symbols/${symbol}/events?${range.toString()}`);
          alertsPage.value = await request("/alerts?limit=20&offset=0");
          positionPage.value = await request(
            `/position-lots?asOfTradeDate=2026-08-24&limit=100&offset=0&symbol=${symbol}`,
          );
          stage.value = "ALERTS";
        } finally {
          replayBusy.value = false;
        }
      }

      const App = vue.defineComponent({
        name: "MonitorJourneyHarness",
        setup() {
          vue.onMounted(async () => {
            const page = await request<AIProviderPage>("/ai-providers?limit=20&offset=0");
            providers.value = Object.freeze(page.items ?? []);
          });
          return () => {
            if (stage.value === "WORKBENCH") {
              return vue.h(
                "main",
                vue.h(
                  PlanWorkbench,
                  {
                    expectedRevision: 0,
                    extraction: extraction.value,
                    initialProviderId: providers.value[0]?.config.providerId ?? null,
                    providers: providers.value,
                    onReplaceSecret: replaceSecret,
                    onSubmitExtraction: submitExtraction,
                    onTestProvider: testProvider,
                    providerTestProviderId: providerTestProviderId.value,
                    providerTestReceipt: providerTestReceipt.value,
                  },
                  {
                    extractedDraft: ({
                      extraction: extractionValue,
                      resolvedIssueKeys,
                      sourceText: reviewedSourceText,
                    }: {
                      extraction: PlanExtractionView;
                      resolvedIssueKeys: readonly string[];
                      sourceText: string;
                    }) =>
                      vue.h("section", { "aria-label": "审核后的结构化草稿" }, [
                        vue.h(
                          "button",
                          {
                            disabled: !resolvedIssueKeys.includes("WARNING:metadata.report_at"),
                            onClick: () =>
                              saveDraft(extractionValue, resolvedIssueKeys, reviewedSourceText),
                            type: "button",
                          },
                          "保存审核后的草稿",
                        ),
                      ]),
                  },
                ),
              );
            }
            if (stage.value === "PLANS") {
              return vue.h("main", [
                vue.h(PlansView, {
                  activeState: activeState.value,
                  onActivatePlan: activatePlan,
                  selectedPlanId: versions.value[0]?.id ?? null,
                  versions: versions.value,
                }),
              ]);
            }
            if (stage.value === "REPLAY") {
              return vue.h("main", [
                vue.h("h1", "确定性行情回放"),
                vue.h(
                  "button",
                  { disabled: replayBusy.value, onClick: runReplay, type: "button" },
                  replayBusy.value ? "回放中" : "运行确定性行情回放",
                ),
              ]);
            }
            if (stage.value === "ALERTS") {
              return vue.h("main", [
                vue.h(AlertsView, {
                  initialPage: alertsPage.value,
                  operations: alertOperations,
                }),
                vue.h(
                  "p",
                  { "data-testid": "position-count-after-acknowledgement" },
                  `确认提醒后的持仓批次：${positionPage.value?.total ?? 0}`,
                ),
                vue.h(
                  "button",
                  { onClick: () => (stage.value = "POSITIONS"), type: "button" },
                  "登记真实成交",
                ),
              ]);
            }
            return vue.h("main", [
              vue.h(PositionLots, {
                asOfTradeDate: "2026-08-24",
                initialPage: positionPage.value,
                maximumQuantity: 200,
                operations: positionOperations,
                prefill: alertsPage.value?.items?.[0]?.positionPrefill ?? null,
                summaryLots: [],
                symbol,
              }),
            ]);
          };
        },
      });
      vue.createApp(App).mount("#app");
    },
    { expectedPlanJson: reviewedPlanJson },
  );
}
