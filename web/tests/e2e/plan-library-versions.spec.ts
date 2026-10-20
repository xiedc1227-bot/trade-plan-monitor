import { expect, test } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { createServer, type ViteDevServer } from "vite";
import vue from "@vitejs/plugin-vue";

let server: ViteDevServer;
let url: string;
const items = ["a", "b"].flatMap(chain => [0, 1, 2, 3].map(index => ({
  preparationId: `${chain}-${index}`, manifestHash: (chain + index).repeat(32),
  sourceId: `source-${index}`, name: "相同名称的已审核计划", symbol: "002240.SZ",
  effectiveTradeDate: ["2026-09-24", "2026-09-28", "2026-09-30", "2026-10-09"][index],
  reviewedAt: `2026-10-17T${chain === "a" ? "02" : "11"}:48:03+08:00`,
  reviewedBase: index ? { preparation_id: `${chain}-${index - 1}`, manifest_hash: (chain + (index - 1)).repeat(32) } : null,
  identity: { sourceHash: String(index + 1).repeat(64), planHash: chain.repeat(64),
    planVersionId: `prepared-${chain}-${index}`, reviewedVersionHash: (chain + index).repeat(32) },
})));
const manyItems = Array.from({ length: 30 }, (_, chain) => items.slice(0, 4).map((item, index) => ({
  ...item, preparationId: `page-${chain}-${index}`, name: `测试时间线${chain + 1}`,
  manifestHash: (chain * 4 + index + 1).toString(16).padStart(64, "0"),
  reviewedBase: index ? { preparation_id: `page-${chain}-${index - 1}`,
    manifest_hash: (chain * 4 + index).toString(16).padStart(64, "0") } : null,
}))).flat();

test.beforeAll(async () => {
  const cache = join(process.cwd(), ".pytest_cache");
  await mkdir(cache, { recursive: true });
  await writeFile(join(cache, "library-display.html"), `<!doctype html><html lang="zh-CN"><head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,"></head>
  <body><main style="padding:1rem"><h1>已审核计划库核对</h1><div id="app"></div></main><script type="module">
  import {createApp,h,reactive} from 'vue';
  import Library from '/src/components/backtests/ReviewedPlanLibrary.vue';
  import '/src/assets/tokens.css';
  const response=await fetch('/library-fixture.json'+location.search); const items=await response.json();
  const state=reactive({endpointId:location.search?'page-25-3':'',updates:[],submissions:0});
  const detailsApi={get:async id=>{const item=items.find(item=>item.preparationId===id);return {body:{preparationId:id,
    workflow:'SINGLE',status:'REVIEWED',revision:1,items:[{sourceId:item.sourceId,sourceRevision:1,candidateRevision:1,
    candidateHash:'9'.repeat(64),evidenceHash:item.reviewedBase?'e'.repeat(64):'f'.repeat(64),baseHash:item.reviewedBase?.manifest_hash??null}],frozen:{manifestHash:item.manifestHash,
    versions:[{sourceId:item.sourceId,effectiveTradeDate:item.effectiveTradeDate,planHash:item.identity.planHash,sourceRevision:1,candidateRevision:1,evidenceHash:'e'.repeat(64)}]}}};},
    items:async id=>{const item=items.find(item=>item.preparationId===id);return {preparationId:id,revision:1,items:[{sourceId:item.sourceId,
    effectiveTradeDate:item.effectiveTradeDate,sourceRevision:1,candidateRevision:1,candidateHash:'9'.repeat(64),
    evidenceHash:item.reviewedBase?'e'.repeat(64):'f'.repeat(64),baseHash:item.reviewedBase?.manifest_hash??null,
    candidate:{kind:item.reviewedBase?'MATERIALIZED':'INITIAL',candidateHash:'9'.repeat(64),validation:'VALID',
    evidenceHash:item.reviewedBase?'e'.repeat(64):'f'.repeat(64),draft:{position:{max_qty:1000},levels:{risk_line_fen:2599}},
    review:{changes:[{target:'levels',rule_id:'private-risk',action:'MODIFY',before:{risk_line_fen:2500},after:{risk_line_fen:2599},clause_ids:[]}]}}}]};}};
  createApp({setup(){return()=>h('div',[h(Library,{items,endpointId:state.endpointId,
    disabled:false,loading:false,pending:false,uncertain:false,error:null,canStart:true,detailsApi,
    onOpen:value=>state.endpointId=value,onUpdate:value=>state.updates.push(value),onNew:()=>state.endpointId=''}),h('output',{'data-testid':'composition-count'},String(state.submissions)),h('output',{'data-testid':'update-endpoint'},state.updates.join(','))]);}}).mount('#app');
  </script></body></html>`);
  server = await createServer({ configFile: false, logLevel: "silent",
    plugins: [vue(), { name: "library-display-fixture", configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const requestUrl = new URL(request.url ?? "/", "http://fixture");
        if (requestUrl.pathname !== "/library-fixture.json") { next(); return; }
        response.setHeader("Content-Type", "application/json");
        response.end(JSON.stringify(requestUrl.searchParams.has("many") ? manyItems : items));
      });
    } }], server: { host: "127.0.0.1", port: 0, hmr: false } });
  await server.listen();
  const address = server.httpServer!.address();
  if (!address || typeof address === "string") throw new Error("Missing fixture listener");
  url = `http://127.0.0.1:${address.port}/.pytest_cache/library-display.html`;
});
test.afterAll(async () => { await server.close(); });

test("eight records form two timelines with exact endpoint updates at 200 percent text", async ({ page }, testInfo) => {
  const failures: string[] = [], errors: string[] = [], writes: string[] = [];
  page.on("requestfailed", request => failures.push(`${request.url()} ${request.failure()?.errorText}`));
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", message => { if (["error", "warning"].includes(message.type())) errors.push(message.text()); });
  page.on("request", request => { if (!["GET", "HEAD"].includes(request.method())) writes.push(request.url()); });
  await page.goto(url);
  await page.waitForLoadState("networkidle");
  expect(errors).toEqual([]); expect(failures).toEqual([]);
  await expect(page.getByTestId("plan-library-chain")).toHaveCount(2);
  await expect(page.locator('input[type="checkbox"]')).toHaveCount(0);
  await expect(page.locator(".plan-library__record")).toHaveCount(8);
  await expect(page.locator(".plan-library__record:visible")).toHaveCount(0);
  for (const updates of await page.getByTestId("timeline-updates").all()) await updates.locator("summary").first().click();
  await expect(page.locator(".plan-library__record:visible")).toHaveCount(8);
  await expect(page.getByTestId("open-plan-timeline")).toHaveCount(2);
  await expect(page.locator("select")).toHaveCount(0);
  await expect(page.getByText("同原文，计划内容不同", { exact: true })).toHaveCount(8);
  const library = page.getByRole("region", { name: "已审核计划库", exact: true });
  for (const item of items) for (const id of [item.preparationId, item.manifestHash, item.sourceId,
    item.identity.planVersionId, item.identity.reviewedVersionHash, item.identity.sourceHash, item.identity.planHash])
    await expect(library).not.toContainText(id);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({ path: testInfo.outputPath("timeline-desktop.png"), fullPage: true });
  for (const width of [320, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.evaluate(() => { document.documentElement.style.fontSize = "200%"; });
    await page.getByText("查看计划及本次调整", { exact: true }).nth(1).click();
    const change = page.getByText("25.00 元 → 25.99 元", { exact: true });
    await expect(change).toHaveCount(1);
    await expect(change).toBeVisible();
    await expect(library).not.toContainText("private-risk");
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.getByText("查看计划及本次调整", { exact: true }).nth(1).click();
  }
  await page.locator('[data-endpoint-id="b-3"]').focus(); await page.keyboard.press("Enter");
  await expect(page.locator('[data-endpoint-id="b-3"]')).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator('[data-endpoint-id="a-3"]')).toHaveAttribute("aria-pressed", "false");
  await page.getByTestId("prepare-next-source").click();
  await expect(page.getByTestId("update-endpoint")).toHaveText("b-3");
  await expect(page.getByTestId("composition-count")).toHaveText("0");
  await expect(page.locator('a[href="/backtests/new?preparationId=b-2&inspect=1"]')).toHaveAttribute("target", "_blank");
  await page.screenshot({ path: testInfo.outputPath("chain-versions.png"), fullPage: true });
  await page.waitForLoadState("networkidle");
  expect(failures).toEqual([]); expect(errors).toEqual([]); expect(writes).toEqual([]);
});

test("thirty timelines stay paged and collapsed while retaining the selected full path", async ({ page }, testInfo) => {
  const failures: string[] = [], errors: string[] = [], writes: string[] = [];
  page.on("requestfailed", request => failures.push(`${request.url()} ${request.failure()?.errorText}`));
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", message => { if (["error", "warning"].includes(message.type())) errors.push(message.text()); });
  page.on("request", request => { if (!["GET", "HEAD"].includes(request.method())) writes.push(request.url()); });
  await page.goto(url + "?many=1"); await page.waitForLoadState("networkidle");
  const library = page.getByRole("region", { name: "已审核计划库", exact: true });
  const paging = page.getByRole("navigation", { name: "计划时间线分页" });
  await expect(library.getByTestId("plan-library-chain")).toHaveCount(10);
  await expect(library.locator(".plan-library__record")).toHaveCount(40);
  await expect(library.locator(".plan-library__record:visible")).toHaveCount(0);
  await expect(paging).toContainText("第 1 / 3 页");
  await expect(library).toContainText("当前已选：测试时间线26");
  await paging.getByRole("button", { name: "下一页", exact: true }).focus(); await page.keyboard.press("Enter");
  await expect(paging).toContainText("第 2 / 3 页");
  await library.getByRole("button", { name: "定位已选时间线", exact: true }).click();
  await expect(paging).toContainText("第 3 / 3 页");
  const selected = library.locator('[data-chain-id="page-25-0"]');
  await expect(selected.locator('[data-endpoint-id="page-25-3"]')).toHaveAttribute("aria-pressed", "true");
  await selected.getByText("查看更新记录（4）", { exact: true }).focus(); await page.keyboard.press("Enter");
  await expect(selected.locator(".plan-library__record:visible")).toHaveCount(4);
  await selected.getByText("查看计划及本次调整", { exact: true }).nth(1).click();
  for (const width of [320, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.evaluate(() => { document.documentElement.style.fontSize = "200%"; });
    await expect(selected.getByText("25.00 元 → 25.99 元", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  }
  await selected.getByTestId("prepare-next-source").click();
  await expect(page.getByTestId("update-endpoint")).toHaveText("page-25-3");
  await selected.getByText("查看更新记录（4）", { exact: true }).click();
  await paging.getByRole("button", { name: "上一页", exact: true }).click();
  await expect(library).toContainText("当前已选：测试时间线26");
  await expect(library.locator(".plan-library__record:visible")).toHaveCount(0);
  await expect(page.getByTestId("composition-count")).toHaveText("0");
  await page.screenshot({ path: testInfo.outputPath("thirty-timelines.png"), fullPage: true });
  await page.waitForLoadState("networkidle");
  expect(failures).toEqual([]); expect(errors).toEqual([]); expect(writes).toEqual([]);
});
