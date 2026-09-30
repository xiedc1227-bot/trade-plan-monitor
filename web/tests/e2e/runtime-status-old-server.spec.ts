import { spawn, type ChildProcess } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import { createServer as createHttpServer, request as proxyRequest, type Server } from "node:http";
import { createServer } from "node:net";
import { join, resolve, extname, sep } from "node:path";
import { expect, test } from "@playwright/test";

const repo = resolve(process.cwd(), ".."); const assets = resolve("dist-runtime-status");
let backend: ChildProcess | undefined; let proxy: Server | undefined; let origin = ""; let upstream = ""; let log = "";
const forwarded: { method: string; path: string }[] = [];
async function port(): Promise<number> {
  const listener = createServer(); await new Promise<void>(done => listener.listen(0, "127.0.0.1", done));
  const address = listener.address(); if (!address || typeof address === "string") throw new Error("No isolated port");
  await new Promise<void>(done => listener.close(() => done())); return address.port;
}

test.beforeAll(async ({ request }) => {
  const upstreamPort = await port(); upstream = `http://127.0.0.1:${upstreamPort}`;
  backend = spawn(join(repo, ".venv/Scripts/python.exe"), ["-m", "tests.browser.explicit_server", "--port", String(upstreamPort)], { cwd: repo, windowsHide: true });
  backend.stdout?.on("data", value => { log += String(value); }); backend.stderr?.on("data", value => { log += String(value); });
  await expect.poll(async () => { try { return (await request.get(`${upstream}/_test/isolation`)).status(); } catch { return 0; } }, { timeout: 30_000 }).toBe(200);
  proxy = createHttpServer(async (incoming, outgoing) => {
    const url = new URL(incoming.url ?? "/", "http://127.0.0.1");
    if (url.pathname.startsWith("/api/v1/")) {
      forwarded.push({ method: incoming.method ?? "GET", path: url.pathname });
      const relay = proxyRequest(new URL(`${url.pathname}${url.search}`, upstream), { method: incoming.method, headers: { ...incoming.headers, host: new URL(upstream).host } }, response => {
        outgoing.writeHead(response.statusCode ?? 500, response.headers); response.pipe(outgoing);
      });
      relay.on("error", () => { outgoing.writeHead(502); outgoing.end(); }); incoming.pipe(relay); return;
    }
    const file = resolve(assets, `.${decodeURIComponent(url.pathname)}`);
    if (!file.startsWith(`${assets}${sep}`) && file !== assets) { outgoing.writeHead(404); outgoing.end(); return; }
    try {
      let content: Buffer; let suffix = extname(file);
      try { content = await readFile(file); }
      catch { if (suffix) throw new Error("Missing asset"); content = await readFile(join(assets, "index.html")); suffix = ".html"; }
      outgoing.setHeader("Content-Type", ({ ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json" } as Record<string, string>)[suffix] ?? "application/octet-stream");
      outgoing.end(content);
    } catch { outgoing.writeHead(404); outgoing.end(); }
  });
  const browserPort = await port(); origin = `http://127.0.0.1:${browserPort}`;
  await new Promise<void>(done => proxy!.listen(browserPort, "127.0.0.1", done));
});

test.afterAll(async ({ request }) => {
  await new Promise<void>(done => proxy ? proxy.close(() => done()) : done());
  if (backend?.exitCode === null) {
    await request.post(`${upstream}/_test/shutdown`).catch(() => null);
    await Promise.race([new Promise<void>(done => backend?.once("exit", () => done())), new Promise<void>(done => setTimeout(done, 10_000))]);
    if (backend.exitCode === null) backend.kill();
  }
  if (log) console.log(log);
});

test("direct inventory command page sends zero protected POSTs to a real old backend", async ({ page, request }, testInfo) => {
  const isolation = await (await request.get(`${upstream}/_test/isolation`)).json();
  const literal = JSON.parse(await readFile(join(repo, "tests/fixtures/ai/explicit-plan-literal-source-v3.json"), "utf8"));
  const runtime = await (await request.get(`${upstream}/api/v1/ai-runtime`)).json();
  const submission = await request.post(`${upstream}/api/v1/plan-extractions`, { headers: { "Idempotency-Key": "s4-browser-old-server-extraction" },
    data: { providerId: runtime.providerId, sourceText: literal.sourceText, expectedRevision: 0 } });
  expect(submission.status()).toBe(202); const receipt = await submission.json();
  const extraction = async () => (await request.get(`${upstream}/api/v1/plan-extractions/${receipt.operationId}`)).json();
  await expect.poll(async () => (await extraction()).status, { timeout: 15_000 }).toBe("SUCCEEDED");
  const extracted = await extraction();
  const draft = await request.post(`${upstream}/api/v1/plan-drafts`, { headers: { "Idempotency-Key": "s4-browser-old-server-draft" },
    data: { extractionId: extracted.id, planJson: extracted.draftPlanJson, sourceText: literal.sourceText, expectedRevision: 0 } });
  expect(draft.status()).toBe(200); const saved = await draft.json();
  const oldHealth = await request.get(`${upstream}/api/v1/health`, { headers: { "X-Monitor-Contract-Version": "2" } });
  expect(oldHealth.headers()["x-monitor-contract-version"]).toBeUndefined();
  const errors: string[] = []; const external: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", msg => { if (["error", "warning"].includes(msg.type())) errors.push(msg.text()); });
  page.on("request", req => { if (new URL(req.url()).origin !== origin) external.push(req.url()); });
  await page.goto(`${origin}/plans/${saved.id}`);
  await expect(page.getByRole("button", { name: "重新加载页面" })).toBeVisible();
  await page.getByLabel("库存登记交易日", { exact: true }).fill("2026-09-14");
  await page.getByLabel("总股数", { exact: true }).fill("100"); await page.getByLabel("可卖股数", { exact: true }).fill("100");
  await page.getByLabel("我确认已完整登记该股票的当前库存").check();
  await page.getByRole("button", { name: "保存独立库存登记" }).click();
  await expect(page.getByText("库存登记未确认；请刷新后以当前库存修订重试。", { exact: true })).toBeVisible();
  expect(forwarded.filter(req => req.method === "POST")).toEqual([]);
  expect(errors).toEqual([]); expect(external).toEqual([]);
  const proof = JSON.stringify({ isolation, origin, upstream, forwarded, oldHealth: await oldHealth.json(), oldHealthHeaders: oldHealth.headers(), errors, external, serverLog: log }, null, 2);
  await page.screenshot({ path: join(isolation.root, "s4-v2-old-server-command.png"), fullPage: true });
  await writeFile(join(isolation.root, "s4-v2-old-server-evidence.json"), proof);
  await testInfo.attach("old-backend-command-proof", { body: proof, contentType: "application/json" });
  console.log(`S4 old backend evidence: ${isolation.root}`);
});
