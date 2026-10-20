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

test.beforeAll(async () => {
  const cache = join(process.cwd(), ".pytest_cache");
  await mkdir(cache, { recursive: true });
  await writeFile(join(cache, "library-display.html"), `<!doctype html><html lang="zh-CN"><head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,"></head>
  <body><main style="padding:1rem"><h1>已审核计划库核对</h1><div id="app"></div></main><script type="module">
  import {createApp,h,reactive} from 'vue';
  import Library from '/src/components/backtests/ReviewedPlanLibrary.vue';
  import '/src/assets/tokens.css';
  const response=await fetch('/library-fixture.json'); const items=await response.json();
  const state=reactive({endpointId:'',updates:[],submissions:0});
  createApp({setup(){return()=>h('div',[h(Library,{items,endpointId:state.endpointId,
    disabled:false,loading:false,pending:false,uncertain:false,error:null,canStart:true,
    onOpen:value=>state.endpointId=value,onUpdate:value=>state.updates.push(value),onNew:()=>state.endpointId=''}),h('output',{'data-testid':'composition-count'},String(state.submissions)),h('output',{'data-testid':'update-endpoint'},state.updates.join(','))]);}}).mount('#app');
  </script></body></html>`);
  server = await createServer({ configFile: false, logLevel: "silent",
    plugins: [vue(), { name: "library-display-fixture", configureServer(server) {
      server.middlewares.use((request, response, next) => {
        if (request.url !== "/library-fixture.json") { next(); return; }
        response.setHeader("Content-Type", "application/json"); response.end(JSON.stringify(items));
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
  await expect(page.getByTestId("open-plan-timeline")).toHaveCount(2);
  await expect(page.locator("select")).toHaveCount(0);
  await expect(page.getByText("同原文，计划内容不同", { exact: true })).toHaveCount(8);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({ path: testInfo.outputPath("timeline-desktop.png"), fullPage: true });
  for (const width of [320, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.evaluate(() => { document.documentElement.style.fontSize = "200%"; });
    await page.getByText("查看版本与来源", { exact: true }).first().click();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.getByText("查看版本与来源", { exact: true }).first().click();
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
