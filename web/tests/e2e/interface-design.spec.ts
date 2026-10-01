import { createRequire } from "node:module";
import { createServer, type ViteDevServer } from "vite";
import type { Page } from "@playwright/test";
import { test, expect } from "./fixtures";
import { emptyDashboard, explicitDashboard, runtimeHealth } from "../fixtures/runtimeStatus";

const axePath = createRequire(import.meta.url).resolve("axe-core/axe.min.js");
let server: ViteDevServer;
let origin: string;

test.beforeAll(async () => {
  server = await createServer({
    configFile: "vite.config.ts", logLevel: "silent",
    server: { host: "127.0.0.1", port: 0, hmr: false },
  });
  await server.listen();
  const address = server.httpServer?.address();
  if (!address || typeof address === "string") throw new Error("Missing isolated UI port");
  origin = `http://127.0.0.1:${address.port}`;
});

test.afterAll(async () => { await server.close(); });

async function prepare(page: Page, active: boolean): Promise<void> {
  await page.route(`${origin}/api/v1/**`, async route => {
    const path = new URL(route.request().url()).pathname;
    expect(route.request().method()).toBe("GET");
    expect(["/api/v1/dashboard", "/api/v1/health"]).toContain(path);
    await route.fulfill({
      json: path.endsWith("/health") ? runtimeHealth() : active ? explicitDashboard() : emptyDashboard(),
      headers: { "X-Monitor-Contract-Version": "2" },
    });
  });
  // An isolated transport keeps the presentation check independent of providers.
  await page.routeWebSocket(`${origin.replace("http:", "ws:")}/ws/v1/monitor**`, () => {});
}

test("installed v2 overview keeps empty and active plans accessible at every design breakpoint", async ({ page }) => {
  for (const active of [false, true]) {
    await page.unroute(`${origin}/api/v1/**`);
    await prepare(page, active);
    for (const width of [320, 768, 1024, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(origin);
      await expect(page.getByRole("heading", { name: "活动计划", exact: false })).toBeVisible();
      await expect(page).toHaveTitle("监控总览 · Trade Plan Monitor");
      await expect(page.locator("article[data-symbol]")).toHaveCount(active ? 1 : 0);
      if (!active) await expect(page.getByRole("link", { name: "前往计划工作台" })).toBeVisible();
      for (const zoom of ["100%", "200%"]) {
        await page.evaluate(value => { document.documentElement.style.fontSize = value; }, zoom);
        const layout = await page.evaluate(() => ({
          width: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth,
        }));
        expect(layout.scroll, `${width}px at ${zoom}, active=${active}`).toBeLessThanOrEqual(layout.width);
        const panels = await page.evaluate(() => {
          const status = document.querySelector(".overview-status")!.getBoundingClientRect();
          const index = document.querySelector(".index-strip")!.getBoundingClientRect();
          const surface = document.querySelector(".index-strip__surface")!.getBoundingClientRect();
          return { wide: matchMedia("(min-width: 75rem)").matches,
            statusTop: status.top, statusBottom: status.bottom, indexTop: index.top, surfaceTop: surface.top };
        });
        if (panels.wide) {
          expect(Math.abs(panels.statusTop - panels.surfaceTop), "panel top alignment").toBeLessThan(1);
        } else {
          expect(panels.statusBottom, "narrow monitoring priority").toBeLessThanOrEqual(panels.indexTop);
        }
      }
      await page.addScriptTag({ path: axePath });
      const violations = await page.evaluate(async () => {
        const axe = (globalThis as typeof globalThis & {
          axe: { run: (root: Document, options: object) => Promise<{ violations: unknown[] }> };
        }).axe;
        return (await axe.run(document, { runOnly: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] })).violations;
      });
      expect(violations, `${width}px, active=${active}`).toEqual([]);
    }
  }
});

test("installed v2 mobile navigation, action focus, and reduced motion work together", async ({ page }) => {
  await prepare(page, false);
  await page.setViewportSize({ width: 320, height: 900 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto(origin);
  await expect(page.getByRole("heading", { name: "活动计划", exact: false })).toBeVisible();
  const navigation = page.getByRole("button", { name: "导航", exact: true });
  await navigation.click();
  await expect(navigation).toHaveAttribute("aria-expanded", "true");
  await page.keyboard.press("Escape");
  await expect(navigation).toHaveAttribute("aria-expanded", "false");
  await expect(navigation).toBeFocused();
  await navigation.press("Tab");
  const action = page.getByRole("link", { name: "管理交易计划" });
  await expect(action).toBeFocused();
  const feedback = await action.evaluate(element => ({
    outline: getComputedStyle(element).outlineStyle,
    transition: Number.parseFloat(getComputedStyle(element).transitionDuration),
  }));
  expect(feedback.outline).toBe("solid");
  expect(feedback.transition).toBeLessThanOrEqual(.00001);
});

test("index selectors have no internal scrollbar while focused or pressed", async ({ page }) => {
  await prepare(page, false);
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const width of [320, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(origin);
    await expect(page.getByRole("heading", { name: "活动计划", exact: false })).toBeVisible();
    const selector = page.getByTestId("market-index-selector").filter({ hasText: "深证成指" });
    await selector.focus();
    const box = await selector.boundingBox();
    if (!box) throw new Error("Missing visible index selector");
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    try {
      const verticalScroll = await page.locator(".index-strip__selectors").evaluate(element => {
        element.scrollTop = 100;
        return { offset: element.scrollTop, overflow: getComputedStyle(element).overflowY };
      });
      expect(verticalScroll.offset, `index selector vertical scroll at ${width}px`).toBe(0);
      expect(["auto", "scroll"], "index selector must not create a vertical scroll container")
        .not.toContain(verticalScroll.overflow);
    } finally {
      await page.mouse.up();
    }
    await expect(selector).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("market-index-trend-card")).toContainText("深证成指");
  }
});
