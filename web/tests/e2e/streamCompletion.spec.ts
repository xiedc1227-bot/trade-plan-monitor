import { expect, test } from "@playwright/test";
import { createServer, type ViteDevServer } from "vite";
import type { ServerResponse } from "node:http";
import browserPin from "../../test-browser.json" with { type: "json" };

let server: ViteDevServer;
let baseUrl: string;
const unfinished = new Map<string, ServerResponse>();

test.beforeAll(async ({ browser }) => {
  expect(browser.version()).toBe(browserPin.version);
  server = await createServer({
    configFile: "vite.legacy-test.config.ts", logLevel: "silent",
    plugins: [{ name: "stream-completion-controls", configureServer(server) {
      server.middlewares.use((request, response, next) => {
        if (!["/api/delayed-end", "/api/cancelled-stream"].includes(request.url!)) { next(); return; }
        const path = request.url!;
        unfinished.set(path, response);
        response.once("close", () => unfinished.delete(path));
        response.writeHead(200, { "Content-Type": "application/json", "Cache-Control": "no-store" });
        response.write(path === "/api/delayed-end" ? '{"complete":true}' : '{"pending":');
      });
    } }],
    server: { host: "127.0.0.1", port: 0, hmr: false },
  });
  await server.listen();
  const address = server.httpServer?.address();
  if (!address || typeof address === "string") throw new Error("Missing local fixture server");
  baseUrl = `http://127.0.0.1:${address.port}`;
});

test.afterAll(async () => {
  for (const response of unfinished.values()) response.destroy();
  await server.close();
});

test("complete bounded JSON stream reads finish every request without cancellation", async ({ page }) => {
  const failures: string[] = [], finished: string[] = [];
  page.on("requestfailed", request => failures.push(`${request.url()} ${request.failure()?.errorText}`));
  page.on("requestfinished", request => {
    if (new URL(request.url()).pathname === "/api/stream-fixture") finished.push(request.url());
  });
  const payload = { text: "完整离线响应", items: [1, 2, 3] };
  await page.route(`${baseUrl}/api/stream-fixture?*`, route => route.fulfill({
    status: 200, contentType: "application/json; charset=utf-8",
    headers: { "Cache-Control": "no-store" }, body: JSON.stringify(payload),
  }));
  await page.goto(`${baseUrl}/src/api/transport.ts`);
  const count = 1000;
  const values = await page.evaluate(async ({ count }) => {
    const modulePath = "/src/api/transport.ts";
    const { requestJson } = await import(modulePath);
    const values = [];
    for (let index = 0; index < count; index++) {
      values.push((await requestJson(fetch, `/api/stream-fixture?${index}`, {
        cache: "no-store", credentials: "same-origin", redirect: "error",
      })).body);
    }
    return values;
  }, { count });
  expect(values).toEqual(Array.from({ length: count }, () => payload));
  await expect.poll(() => ({ finished: finished.length, failures })).toEqual({ finished: count, failures: [] });
});

test("a no-store body ending after its last data chunk finishes successfully", async ({ page }) => {
  const failures: string[] = [];
  page.on("requestfailed", request => failures.push(request.failure()?.errorText ?? "unknown"));
  await page.goto(`${baseUrl}/src/api/transport.ts`);
  const finished = page.waitForEvent("requestfinished", request => new URL(request.url()).pathname === "/api/delayed-end");
  const body = page.evaluate(async () => {
    const response = await fetch("/api/delayed-end", { cache: "no-store" });
    const reader = response.body!.getReader(), decoder = new TextDecoder();
    let text = "";
    while (true) {
      const value = await reader.read();
      if (value.done) return JSON.parse(text) as unknown;
      text += decoder.decode(value.value, { stream: true });
      Reflect.set(globalThis, "lastFixtureChunkRead", true);
    }
  });
  await page.waitForFunction(() => Reflect.get(globalThis, "lastFixtureChunkRead") === true);
  unfinished.get("/api/delayed-end")!.end();
  expect(await body).toEqual({ complete: true });
  await finished;
  expect(failures).toEqual([]);
});

test("a real caller cancellation is still reported as a failed request", async ({ page }) => {
  const failures: string[] = [], finished: string[] = [];
  page.on("requestfailed", request => failures.push(request.failure()?.errorText ?? "unknown"));
  page.on("requestfinished", request => {
    if (new URL(request.url()).pathname === "/api/cancelled-stream") finished.push(request.url());
  });
  await page.goto(`${baseUrl}/src/api/transport.ts`);
  const failed = page.waitForEvent("requestfailed", request => new URL(request.url()).pathname === "/api/cancelled-stream");
  await page.evaluate(async () => {
    const controller = new AbortController();
    const response = await fetch("/api/cancelled-stream", { signal: controller.signal });
    const reader = response.body!.getReader();
    await reader.read(); controller.abort();
    await reader.cancel().catch(() => undefined);
  });
  expect((await failed).failure()?.errorText).toBe("net::ERR_ABORTED");
  expect(failures).toEqual(["net::ERR_ABORTED"]);
  expect(finished).toEqual([]);
  await expect.poll(() => unfinished.size).toBe(0);
});
