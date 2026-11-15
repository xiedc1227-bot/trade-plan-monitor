import { spawn, type ChildProcess } from "node:child_process";
import { createHash } from "node:crypto";
import type { DailySupplementCommand, SourceCoveragePage } from "../../src/api/generated";
import { createServer } from "node:net";
import { join, resolve } from "node:path";
import { expect, test } from "./fixtures";

const repo = resolve(process.cwd(), "..");
const cases = [
  {mode: "MARKET_VALUE_CAP", limit: "CAPITAL_ONLY", route: "ORDINARY", quantity: 200, humanCount: 75,
    frozenSourceHash: "5d063ac6e5e4c72f2be92e2d85c64a61aee40cb5e8d6ff02bd304f162bb35fd0",
    frozenPlanHash: "39830a366038ec72a828b4dd51b0030c5ca667cc1a029c8cfba4de1af7767d38"},
  {mode: "OPEN_COST_CAP", limit: "CAPITAL_ONLY", route: "ORDINARY", quantity: 200, humanCount: 88,
    frozenSourceHash: "5dfd835b93c52aaff9f1a1babc9731635e903108a171a5507dd4981a5823ca7d",
    frozenPlanHash: "e186d25f35481026cd5c3bc91cc71ed2298f0f9a9e45c11c38779920e4c47e24"},
  {mode: "MARKET_VALUE_CAP", limit: "QUANTITY_AND_CAPITAL", route: "WEAK_MINIMUM", quantity: 100, humanCount: 76,
    frozenSourceHash: "84bd67c450f4e741ee31732db8a883d099b6cd0542ccb61109890b8675658038",
    frozenPlanHash: "97b649d8fa49395c5adc6201410efd0a48319d2eb1b418a322a90e653ab785fa"},
  {mode: "OPEN_COST_CAP", limit: "QUANTITY_AND_CAPITAL", route: "BROKEN_STRONG", quantity: 300, humanCount: 89,
    frozenSourceHash: "ed4b0a4a6471562cca6045a85e5fa605987c128975bdbc2dfe2eb6c1cdc5b2fe",
    frozenPlanHash: "24ea35fda3883417388eb639aa21456588efd47ed826ea73fad524b72b5b81ab"},
] as const;

for (const scenario of cases) for (const completeSource of [false, true]) test.describe(
  `${completeSource ? "complete FIELD source" : "original abbreviated source"} ${scenario.mode} ${scenario.limit} ${scenario.route}`, () => {
  let base: string, server: ChildProcess | undefined;
  let log = "";
  test.beforeAll(async ({request}) => {
    const listener = createServer();
    await new Promise<void>(done => listener.listen(0, "127.0.0.1", done));
    const address = listener.address();
    if (!address || typeof address === "string") throw new Error("Missing isolated browser port");
    await new Promise<void>(done => listener.close(() => done()));
    base = `http://127.0.0.1:${address.port}`;
    server = spawn(join(repo, ".venv/Scripts/python.exe"), ["-m", "tests.browser.condition_server",
      "--port", String(address.port), "--exception", scenario.route === "BROKEN_STRONG" ? "BROKEN_STRONG" : "WEAK_MINIMUM",
      "--p3", scenario.mode, "--p3-limit", scenario.limit, "--p3-route", scenario.route], {cwd: repo, windowsHide: true});
    server.stdout?.on("data", value => {log += String(value);});
    server.stderr?.on("data", value => {log += String(value);});
    await expect.poll(async () => {try {return (await request.get(`${base}/_test/isolation`)).status();} catch {return 0;}},
      {timeout: 30_000, message: "Offline P3 fixture readiness"}).toBe(200);
  });
  test.afterAll(async ({request}) => {
    if (server?.exitCode === null) {
      await request.post(`${base}/_test/shutdown`).catch(() => null);
      await Promise.race([new Promise<void>(done => server?.once("exit", () => done())), new Promise<void>(done => setTimeout(done, 5000))]);
      if (server.exitCode === null) server.kill();
    }
    if (log.includes("Traceback")) console.log(log);
  });
  test("review, reconcile, preview, approve separately, whole quote fail/recovery and reload", async ({page, request}, testInfo) => {
    test.setTimeout(150_000);
    await page.clock.install({time: new Date("2026-09-22T10:00:00+08:00")});
    const setup: {source: string; originalSource: string; sourceContract: string; bindingInputBudgetChars: number; expectedPlan: unknown;
      humanDefinitions: {path: string; value: unknown}[]} = await (await request.post(
        `${base}/_test/setup?source_contract=${completeSource ? "COMPLETE_FIELDS" : "ABBREVIATED"}`)).json();
    expect(setup.sourceContract).toBe(completeSource ? "COMPLETE_FIELDS" : "ABBREVIATED");
    const configured = await request.get(`${base}/api/v1/ai-runtime`);
    expect(configured.status()).toBe(200);
    expect((await configured.json()).maxInputChars).toBe(setup.bindingInputBudgetChars);
    expect(setup.bindingInputBudgetChars).toBe(200000);
    expect(createHash("sha256").update(setup.originalSource).digest("hex")).toBe(scenario.frozenSourceHash);
    expect(setup.humanDefinitions).toHaveLength(scenario.humanCount);
    const external: string[] = [];
    const mutations: string[] = [];
    page.on("request", req => {
      if (new URL(req.url()).origin !== base) external.push(req.url());
      if (req.method() === "POST") mutations.push(new URL(req.url()).pathname);
    });
    await page.goto(`${base}/plans`);
    await page.getByLabel("粘贴中文计划原文", {exact: true}).fill(setup.source);
    await page.getByRole("button", {name: "生成计划草稿", exact: true}).click();
    await expect(page.getByRole("heading", {name: "编辑规则、周期与执行窗口"})).toBeVisible();
    await expect(page.getByRole("region", {name: "金额上限政策审核"})).toContainText("超限不会自动缩量");
    if (completeSource) {
      await expect(page.locator('.daily-review textarea[id^="reason-"]')).toHaveCount(scenario.humanCount);
      for (const field of setup.humanDefinitions)
        await page.locator(`[id="reason-${field.path}"]`).fill(
          `Synthetic independent human definition: ${field.path} = ${JSON.stringify(field.value)}; verified against this exact complete FIELD source, with no holdings, cost basis or trades inferred.`);
    } else {
      for (const input of await page.getByLabel("本句实际对应的技术参数路径（逗号分隔）", {exact: true}).all())
        await input.fill("ordinary_rules[0].pretrade_policy.sizing.base_qty");
      for (const textarea of await page.locator(".daily-review textarea").all())
        await textarea.fill(`Synthetic independent human verification: ${setup.source}`);
    }
    const registering = page.waitForResponse(r => r.url().endsWith("/plan-review-supplements") && r.request().method() === "POST");
    await page.getByRole("button", {name: "单独登记上述人工补充", exact: true}).click();
    await expect(page.getByRole("status").filter({hasText: "人工补充已独立登记"})).toBeVisible();
    const registered = await registering;
    expect(registered.status(), await registered.text()).toBe(200);
    const humanCommand: DailySupplementCommand = registered.request().postDataJSON();
    expect(humanCommand.supplements).toHaveLength(scenario.humanCount);
    expect(Object.fromEntries(humanCommand.supplements.map(item => [item.path, item.value]))).toEqual(
      Object.fromEntries(setup.humanDefinitions.map(item => [item.path, item.value])));
    const saving = page.waitForResponse(r => r.url().endsWith("/plan-drafts") && r.request().method() === "POST");
    await page.getByRole("button", {name: "保存待审核版本", exact: true}).click();
    const savedResponse = await saving;
    expect(savedResponse.status(), await savedResponse.text()).toBe(200);
    const saved = await savedResponse.json();
    expect(JSON.parse(saved.planJson).schema_version).toBe(9);
    expect(JSON.parse(saved.planJson)).toEqual(setup.expectedPlan);
    expect(createHash("sha256").update(saved.planJson).digest("hex")).toBe(scenario.frozenPlanHash);
    expect(saved.sourceText).toBe(setup.source);
    expect(saved.dailyMapping.supplements).toHaveLength(scenario.humanCount);
    expect(saved.dailyIssues).toEqual([]);
    const pages: SourceCoveragePage[] = [];
    let cursor: string | null = null;
    do {
      const coverage = await request.get(`${base}/api/v1/plan-versions/${saved.id}/source-coverage`,
        {params: {limit: 50, ...(cursor ? {cursor} : {})}});
      expect(coverage.status(), await coverage.text()).toBe(200);
      const page: SourceCoveragePage = await coverage.json(); pages.push(page); cursor = page.nextCursor;
    } while (cursor);
    const summary = pages[0]!.summary;
    expect(summary).toEqual(saved.sourceCoverage);
    expect(summary.authorityGranted).toBe(false); expect(summary.currentReviewBound).toBe(false);
    await testInfo.attach("actual-source-contract-chain", {contentType: "application/json",
      body: Buffer.from(JSON.stringify({setup, humanCommand, saved, pages}, null, 2))});
    if (!completeSource) {
      expect(saved.sourceText).toBe(setup.originalSource);
      expect(summary.coverageComplete).toBe(false); expect(summary.status).toBe("BLOCKED");
      expect(summary.obligationCount).toBe(46); expect(summary.issueCount).toBe(46);
      expect(pages.flatMap(page => page.items).filter(item => item.kind === "OBLIGATION")
        .every(item => item.kind === "OBLIGATION" && item.obligation.serverState === "UNRESOLVED")).toBe(true);
      expect(summary.canConfirmReview).toBe(false); expect(saved.canActivate).toBe(false);
      await expect(page.getByRole("button", {name: "确认当前完整审核", exact: true})).toBeDisabled();
      expect(mutations.filter(path => /plan-review-confirmations|plan-activations|simulated-trades/.test(path))).toEqual([]);
      expect(external).toEqual([]);
      return;
    }
    expect(summary.coverageComplete).toBe(true); expect(summary.issueCount).toBe(0);
    expect(summary.canConfirmReview).toBe(true);
    await expect(page.getByRole("button", {name: "确认当前完整审核", exact: true})).toBeEnabled();
    await page.getByRole("button", {name: "确认当前完整审核"}).click();
    await expect(page.getByRole("button", {name: "启用当前审核绑定"})).toBeEnabled();
    await page.getByRole("button", {name: "启用当前审核绑定"}).click();
    await expect(page.getByRole("status").filter({hasText: "计划已启用"})).toBeVisible();
    const operations = page.locator(".daily-operations");
    await operations.getByLabel("选择独立操作").selectOption("POSITION");
    await operations.getByLabel("期初模拟CORE（股）", {exact: true}).fill("100");
    await operations.getByLabel("期初模拟TACTICAL（股）", {exact: true}).fill("0");
    await operations.getByRole("button", {name: "确认登记期初模拟仓位"}).click();
    await expect(operations.getByRole("status").filter({hasText: "已记录并更新当前状态"})).toBeVisible();
    const closeResponse = await request.post(`${base}/_test/confirm-close`);
    expect(closeResponse.status(), await closeResponse.text()).toBe(200);
    await operations.getByRole("button", {name: "刷新当前状态", exact: true}).click();
    const opening = page.getByRole("region", {name: "模拟预算与开仓成本"});
    if (scenario.mode === "OPEN_COST_CAP") {
      await expect(opening).toContainText("未知，尚无完整成本依据");
      await expect(opening.getByLabel("此批次当前保留成本（分，0须明确填写）")).toHaveValue("");
      await opening.getByLabel("此批次当前保留成本（分，0须明确填写）").fill("20000");
      await opening.getByLabel("成本依据观察时间（上海时间）").fill("2026-09-18T16:00");
      await opening.getByLabel("成本来源", {exact: true}).fill("Explicit synthetic simulation cost statement");
      await opening.getByLabel("对应原句或凭据").fill("Current CORE100shares retained basis20000fen");
      await opening.getByLabel("本次确认或校正理由").fill("Reviewed the complete current simulation lot");
      await opening.getByRole("checkbox").check();
      const confirming = page.waitForResponse(r => r.url().endsWith("/simulation-capital-openings"));
      await opening.getByRole("button", {name: "单独确认模拟开仓成本", exact: true}).click();
      const confirmed = await confirming;
      expect(confirmed.status(), await confirmed.text()).toBe(200);
      expect(confirmed.request().postDataJSON().lots).toEqual([{lot_id: "initial-CORE", bucket: "CORE", quantity: 100, retained_basis_fen: 20000}]);
      const receipt = await confirmed.json();
      expect(receipt.authorityGranted).toBe(false); expect(receipt.inventoryChanged).toBe(false);
      await expect(opening).toContainText("200.00 元");
      const recheck = await request.post(`${base}/_test/confirm-close`);
      expect(recheck.status(), await recheck.text()).toBe(200);
      await operations.getByRole("button", {name: "刷新当前状态", exact: true}).click();
    } else {
      await expect(opening).toContainText("不需要开仓成本");
      await expect(opening.locator("form")).toHaveCount(0);
    }
    if (scenario.route !== "ORDINARY") {
      const candidate = page.locator(".exception-approval");
      await expect(candidate).toContainText("等待逐次审核");
      if (scenario.route === "BROKEN_STRONG") {
        await expect(candidate.getByLabel("本次申请数量 Qe（股，不设默认值）")).toHaveValue("");
        await candidate.getByLabel("本次申请数量 Qe（股，不设默认值）").fill("300");
      }
      await candidate.getByRole("button", {name: "生成本次精确预览"}).click();
      await expect(candidate).toContainText(`本次精确批准量：${scenario.quantity} 股`);
      await candidate.getByLabel("本次决定的具体理由（必填）").fill("Reviewed exact market route, strength, conditions and whole budget");
      await candidate.getByRole("button", {name: `批准本次${scenario.quantity}股`}).click();
      await expect(candidate).toContainText("已批准，数量已冻结");
    }
    expect(mutations.filter(path => path.endsWith("simulated-trades"))).toEqual([]);
    const live = await request.post(`${base}/_test/live`);
    expect(live.status(), await live.text()).toBe(200);
    await operations.getByRole("button", {name: "刷新当前状态", exact: true}).click();
    const preview = page.getByRole("region", {name: "当前金额预览", exact: true});
    if (scenario.route === "BROKEN_STRONG") {
      await expect(preview.getByLabel("本次金额预览数量（不代表批准量）")).toHaveValue("");
      await preview.getByLabel("本次金额预览数量（不代表批准量）").fill("300");
    }
    const estimating = page.waitForResponse(r => r.url().endsWith("/plan-capital-previews"));
    await preview.getByRole("button", {name: "按当前预算只读预览"}).click();
    const estimate = await estimating;
    expect(estimate.status(), await estimate.text()).toBe(200);
    const estimateBody = await estimate.json();
    expect(estimateBody.quantity).toBe(scenario.quantity); expect(estimateBody.authorityGranted).toBe(false);
    await expect(preview).toContainText("本次整笔金额通过");
    const buy = operations.getByRole("button", {name: `确认一次模拟买入${scenario.quantity}股`, exact: true});
    await expect(buy).toBeEnabled();
    const failed = await request.post(`${base}/_test/p2-quote/162`);
    expect(failed.status(), await failed.text()).toBe(200);
    await operations.getByRole("button", {name: "刷新当前状态", exact: true}).click();
    await expect(buy).toBeDisabled();
    await expect(operations).toContainText("买入后超过金额上限，整笔暂停");
    await request.post(`${base}/_test/p2-quote/161`);
    await operations.getByRole("button", {name: "刷新当前状态", exact: true}).click();
    await expect(buy).toBeEnabled();
    for (const width of [320, 768, 1024, 1440]) {
      await page.setViewportSize({width, height: 1000});
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `P3 overflow at${width}`).toBe(true);
    }
    const screenshot = testInfo.outputPath("p3-capital.png");
    await operations.screenshot({path: screenshot});
    await testInfo.attach("p3-capital", {path: screenshot, contentType: "image/png"});
    await buy.click();
    await expect(operations.getByRole("status").filter({hasText: `已一次完成模拟买入${scenario.quantity}股`})).toBeVisible();
    const inventory = await (await request.get(`${base}/api/v1/simulation-position-inventory?symbol=601021.SH&asOfTradeDate=2026-09-22`)).json();
    expect(inventory.snapshot.totalQty).toBe(100+scenario.quantity);
    await page.goto(`${base}/plans/${saved.id}`);
    await expect(page.locator(".daily-operations")).toContainText("本笔模拟已完成");
    expect(external).toEqual([]);
  });
});
