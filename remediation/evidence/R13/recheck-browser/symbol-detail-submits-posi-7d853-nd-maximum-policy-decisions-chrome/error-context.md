# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: symbol-detail.spec.ts >> submits position commands for backend-only T+1 and maximum-policy decisions
- Location: tests\e2e\symbol-detail.spec.ts:377:1

# Error details

```
Error: expect(locator).toHaveText(expected) failed

Locator: getByRole('alert')
Expected: "后端拒绝了持仓操作，请核对最新批次和计划规则后重试"
Error: strict mode violation: getByRole('alert') resolved to 2 elements:
    1) <p role="alert" data-v-7c9c68db="">独立库存读取失败；不会从提醒或原文推测持仓。</p> aka getByText('独立库存读取失败；不会从提醒或原文推测持仓。')
    2) <p role="alert" data-v-0794363e="" class="manual-event-risk__error">人工事件风险状态暂不可用；系统会继续按未知风险阻断。</p> aka getByText('人工事件风险状态暂不可用；系统会继续按未知风险阻断。')

Call log:
  - Expect "toHaveText" with timeout 5000ms
  - waiting for getByRole('alert')

```

# Test source

```ts
  308 |       });
  309 |       return;
  310 |     }
  311 |     await fulfillApi(route, ranges, undefined, indexRanges);
  312 |   });
  313 | 
  314 |   await page.goto(`${baseUrl}/stocks/${symbol}`);
  315 | 
  316 |   await expect(page.getByRole("heading", { level: 2, name: "参考指数数据" })).toBeVisible();
  317 |   await expect(page.getByRole("heading", { level: 2, name: "计划指数条件" })).toBeVisible();
  318 |   await expect(page.getByText("计划未使用", { exact: true })).toBeVisible();
  319 |   await expect(page.getByRole("heading", { level: 2, name: "板块指数历史" })).toBeVisible();
  320 |   await expect.poll(() => indexRanges.length).toBe(1);
  321 | });
  322 | 
  323 | test("keeps the separated detail sections responsive and accessible", async ({ page }) => {
  324 |   const ranges: Array<{ endAt: string | null; startAt: string | null }> = [];
  325 |   await page.route("**/api/v1/**", async (route) => fulfillApi(route, ranges));
  326 | 
  327 |   for (const width of [320, 768, 1024, 1440]) {
  328 |     await page.setViewportSize({ height: 900, width });
  329 |     await page.goto(`${baseUrl}/stocks/${symbol}`);
  330 |     await expect(page.getByRole("heading", { level: 2, name: "计划指数条件" })).toBeVisible();
  331 |     await page.evaluate(() => {
  332 |       document.documentElement.style.fontSize = "200%";
  333 |     });
  334 |     const sizes = await page.evaluate(() => ({
  335 |       clientWidth: document.documentElement.clientWidth,
  336 |       scrollWidth: document.documentElement.scrollWidth,
  337 |     }));
  338 |     const overflowSources = await page.evaluate(() => {
  339 |       const viewportWidth = document.documentElement.clientWidth;
  340 |       return [...document.querySelectorAll<HTMLElement>("body *")]
  341 |         .map((element) => ({
  342 |           className: element.className,
  343 |           clientWidth: element.clientWidth,
  344 |           overflowX: getComputedStyle(element).overflowX,
  345 |           scrollWidth: element.scrollWidth,
  346 |           tagName: element.tagName,
  347 |         }))
  348 |         .filter(
  349 |           (element) =>
  350 |             element.clientWidth > viewportWidth ||
  351 |             (element.scrollWidth > element.clientWidth && element.overflowX === "visible"),
  352 |         )
  353 |         .sort((left, right) => right.scrollWidth - left.scrollWidth)
  354 |         .slice(0, 20);
  355 |     });
  356 |     expect(
  357 |       sizes.scrollWidth,
  358 |       `symbol detail overflow at ${width}px: ${JSON.stringify(overflowSources)}`,
  359 |     ).toBeLessThanOrEqual(sizes.clientWidth);
  360 |   }
  361 | 
  362 |   await page.addScriptTag({ path: axePath });
  363 |   const seriousViolations = await page.evaluate(async () => {
  364 |     const axe = (globalThis as typeof globalThis & {
  365 |       axe: { run: (root: Document, options: object) => Promise<{ violations: { impact: string | null }[] }> };
  366 |     }).axe;
  367 |     const result = await axe.run(document, {
  368 |       runOnly: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"],
  369 |     });
  370 |     return result.violations.filter(
  371 |       (violation) => violation.impact === "serious" || violation.impact === "critical",
  372 |     );
  373 |   });
  374 |   expect(seriousViolations).toEqual([]);
  375 | });
  376 | 
  377 | test("submits position commands for backend-only T+1 and maximum-policy decisions", async ({ page }) => {
  378 |   const ranges: Array<{ endAt: string | null; startAt: string | null }> = [];
  379 |   const positionRequests: PositionRequests = { closures: [], creates: [], reads: [] };
  380 |   await page.route("**/api/v1/**", async (route) => fulfillApi(route, ranges, positionRequests));
  381 | 
  382 |   await page.goto(`${baseUrl}/stocks/${symbol}`);
  383 |   await expect(page.getByRole("heading", { level: 2, name: "人工持仓批次" })).toBeVisible();
  384 |   await expect.poll(() => positionRequests.reads.length).toBe(1);
  385 |   expect(positionRequests.reads[0]).toEqual({
  386 |     asOfTradeDate: "2026-08-24",
  387 |     limit: "100",
  388 |     offset: "0",
  389 |     symbol,
  390 |   });
  391 |   await expect(page.getByTestId(`reduce-${sameDayLot.lotId}`)).toBeEnabled();
  392 | 
  393 |   await page.locator('input[name="createCostFen"]').fill("6500");
  394 |   await page.getByRole("button", { name: "复核建仓" }).click();
  395 |   await expect(page.getByTestId("position-confirmation")).toBeVisible();
  396 |   await page.getByTestId("confirm-position").click();
  397 | 
  398 |   await expect.poll(() => positionRequests.creates.length).toBe(1);
  399 |   expect(positionRequests.creates[0]).toEqual({
  400 |     acquiredTradeDate: "2026-08-24",
  401 |     bucket: "CORE",
  402 |     costFen: 6_500,
  403 |     expectedRevision: 0,
  404 |     quantity: 100,
  405 |     relatedAlertId: null,
  406 |     symbol,
  407 |   });
> 408 |   await expect(page.getByRole("alert")).toHaveText(
      |                                         ^ Error: expect(locator).toHaveText(expected) failed
  409 |     "后端拒绝了持仓操作，请核对最新批次和计划规则后重试",
  410 |   );
  411 | 
  412 |   await page.getByTestId(`reduce-${sameDayLot.lotId}`).click();
  413 |   await page.getByRole("button", { name: "复核减仓" }).click();
  414 |   await expect(page.getByTestId("position-confirmation")).toBeVisible();
  415 |   await page.getByTestId("confirm-position").click();
  416 | 
  417 |   await expect.poll(() => positionRequests.closures.length).toBe(1);
  418 |   expect(positionRequests.closures[0]).toEqual({
  419 |     expectedRevision: 0,
  420 |     lotId: sameDayLot.lotId,
  421 |     quantity: 100,
  422 |     tradeDate: "2026-08-24",
  423 |   });
  424 |   await expect.poll(() => positionRequests.reads.length).toBe(3);
  425 |   await expect(page.getByRole("alert")).toHaveText(
  426 |     "后端拒绝了持仓操作，请核对最新批次和计划规则后重试",
  427 |   );
  428 |   await expect(page.locator("body")).not.toContainText("backend policy detail");
  429 |   await expect(page.getByText("T+1 / 当前日期不可卖")).toBeVisible();
  430 | });
  431 | 
  432 | test("confirms plan-scoped manual event risk through the normal symbol page", async ({ page }) => {
  433 |   const manualRiskCommands: unknown[] = [];
  434 |   const planVersionId = "4c623c8c-ca26-4cd8-8cb2-08cd5e61be93";
  435 |   await page.route("**/api/v1/**", async (route) => {
  436 |     const url = new URL(route.request().url());
  437 |     if (url.pathname === "/api/v1/manual-event-risk") {
  438 |       await route.fulfill({
  439 |         body: JSON.stringify({
  440 |           confirmedAt: null,
  441 |           expiresOn: null,
  442 |           planVersionId,
  443 |           reason: "MISSING_CONFIRMATION",
  444 |           revision: 0,
  445 |           status: "UNKNOWN",
  446 |           symbol,
  447 |         }),
  448 |         contentType: "application/json",
  449 |       });
  450 |       return;
  451 |     }
  452 |     if (url.pathname === "/api/v1/manual-event-risk-confirmations") {
  453 |       manualRiskCommands.push({
  454 |         body: readJsonBody(route),
  455 |         idempotencyKey: await route.request().headerValue("Idempotency-Key"),
  456 |       });
  457 |       await route.fulfill({
  458 |         body: JSON.stringify({
  459 |           confirmedAt: observedAt,
  460 |           expiresOn: "2026-08-24",
  461 |           planVersionId,
  462 |           reason: null,
  463 |           revision: 1,
  464 |           status: "RISK_PRESENT",
  465 |           symbol,
  466 |         }),
  467 |         contentType: "application/json",
  468 |       });
  469 |       return;
  470 |     }
  471 |     await fulfillApi(route, []);
  472 |   });
  473 | 
  474 |   await page.goto(`${baseUrl}/stocks/${symbol}`);
  475 |   await expect(page.getByRole("heading", { level: 2, name: "人工事件风险确认" })).toBeVisible();
  476 |   await expect(page.getByRole("alert").filter({ hasText: "缺少人工事件风险确认" })).toBeVisible();
  477 | 
  478 |   await page.locator('select[name="manualRiskStatus"]').selectOption("RISK_PRESENT");
  479 |   await page.locator('input[name="manualRiskExpiresOn"]').fill("2026-08-24");
  480 |   await page.getByRole("button", { name: "复核确认" }).click();
  481 |   await expect(page.getByTestId("manual-risk-confirmation")).toBeVisible();
  482 |   await page.getByTestId("confirm-manual-risk").click();
  483 | 
  484 |   await expect.poll(() => manualRiskCommands.length).toBe(1);
  485 |   expect(manualRiskCommands).toEqual([
  486 |     {
  487 |       body: {
  488 |         expectedRevision: 0,
  489 |         expiresOn: "2026-08-24",
  490 |         status: "RISK_PRESENT",
  491 |         symbol,
  492 |       },
  493 |       idempotencyKey: expect.stringMatching(/^manual-risk-[0-9a-f-]{36}$/),
  494 |     },
  495 |   ]);
  496 |   await expect(page.getByRole("status").filter({ hasText: "已确认存在事件风险" })).toBeVisible();
  497 | });
  498 | 
  499 | async function fulfillApi(
  500 |   route: Route,
  501 |   ranges: Array<{ endAt: string | null; startAt: string | null }>,
  502 |   positionRequests?: PositionRequests,
  503 |   indexRanges?: Array<{
  504 |     endAt: string | null;
  505 |     indexCode: string;
  506 |     interval: string | null;
  507 |     startAt: string | null;
  508 |   }>,
```