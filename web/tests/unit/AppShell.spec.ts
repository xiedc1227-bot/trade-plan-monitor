import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { flushPromises, mount } from "@vue/test-utils";
import { createPinia } from "pinia";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../src/composables/useMonitorStream", async () => {
  const { computed } = await import("vue");
  return {
    useMonitorStream: () => ({
      connectionState: computed(() => ({
        code: "DISCONNECTED",
        label: "连接中断，正在重试",
        marker: "×",
      })),
      recoverSnapshot: vi.fn(),
      start: vi.fn(),
      stop: vi.fn(),
    }),
  };
});

import AppShell from "../../src/layouts/AppShell.vue";
import { routes } from "../../src/router";

const expectedPaths = [
  "/daily-plans/:versionId?",
  "/",
  "/stocks/:symbol",
  "/plans",
  "/plans/:id",
  "/alerts",
  "/system",
  "/backtests",
  "/backtests/new",
  "/backtests/data",
  "/backtests/:runId",
];

function createTestRouter(stubBacktestViews = false) {
  return createRouter({
    history: createMemoryHistory(),
    routes: stubBacktestViews
      ? routes.map((route) =>
          route.path.startsWith("/backtests")
            ? {
                path: route.path,
                meta: route.meta ?? {},
                component: {
                  template: `<section><h1>${String(route.meta?.title ?? "回测")}</h1><button type="button">保留焦点</button></section>`,
                },
              }
            : route,
        )
      : routes,
  });
}

async function mountShell(
  path = "/",
  withConnectionSlot = true,
  stubBacktestViews = false,
) {
  const router = createTestRouter(stubBacktestViews);
  await router.push(path);
  await router.isReady();

  const wrapper = mount(AppShell, {
    attachTo: document.body,
    global: { plugins: [createPinia(), router] },
    slots: withConnectionSlot
      ? { connectionBanner: '<p data-testid="connection-message">连接已恢复</p>' }
      : {},
  });

  return { router, wrapper };
}

afterEach(() => {
  document.body.replaceChildren();
  document.title = "";
});

describe("AppShell", () => {
  it("declares the complete approved route surface", () => {
    expect(routes.map((route) => route.path)).toEqual(expectedPaths);
  });

  it("renders navigation, the connection banner slot, and the route outlet", async () => {
    const { router, wrapper } = await mountShell();

    expect(wrapper.get('nav[aria-label="主要导航"]')).toBeTruthy();
    expect(wrapper.get('nav[aria-label="移动端主要导航"]')).toBeTruthy();
    expect(wrapper.get('nav[aria-label="主要导航"] a[href="/backtests"]')).toBeTruthy();
    expect(
      wrapper.get('nav[aria-label="移动端主要导航"] a[href="/backtests"]'),
    ).toBeTruthy();
    expect(wrapper.get('[role="status"][aria-live="polite"]').text()).toContain("连接已恢复");
    expect(wrapper.get("#main-content").text()).toContain("监控总览");

    await wrapper.get('nav[aria-label="主要导航"] a[href="/plans"]').trigger("click");
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe("/plans"));
    await flushPromises();

    expect(wrapper.get("#main-content").text()).toContain("计划工作台");
  });

  it("renders native backtest sub-navigation and applies route title and heading focus", async () => {
    const { router, wrapper } = await mountShell("/backtests", true, true);
    await flushPromises();

    const subNavigation = wrapper.get('nav[aria-label="回测导航"]');
    const heading = wrapper.get("#main-content h1");

    expect(subNavigation.get('a[href="/backtests"]').text()).toBe("运行记录");
    expect(subNavigation.get('a[href="/backtests/new"]').text()).toBe("新建回测");
    expect(subNavigation.get('a[href="/backtests/data"]').text()).toBe("历史数据");
    expect(document.title).toBe("回测运行记录 · Trade Plan Monitor");
    expect(heading.attributes("tabindex")).toBe("-1");
    expect(document.activeElement).toBe(heading.element);

    await subNavigation.get('a[href="/backtests/data"]').trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.path).toBe("/backtests/data");
    expect(document.title).toBe("历史数据管理 · Trade Plan Monitor");
    expect(document.activeElement).toBe(wrapper.get("#main-content h1").element);
  });

  it("does not steal focus when only the current route query changes", async () => {
    const runId = "a".repeat(64);
    const { router, wrapper } = await mountShell(
      `/backtests/${runId}?jobId=run-job-001`,
      true,
      true,
    );
    await flushPromises();

    const retainedFocus = wrapper.get<HTMLButtonElement>("#main-content button");
    retainedFocus.element.focus();
    expect(document.activeElement).toBe(retainedFocus.element);

    await router.replace({ path: `/backtests/${runId}`, query: {} });
    await flushPromises();

    expect(document.activeElement).toBe(retainedFocus.element);
  });

  it.each([
    ["/backtests", "运行记录"],
    ["/backtests/new", "新建回测"],
    ["/backtests/data", "历史数据"],
    [`/backtests/${"a".repeat(64)}`, "运行记录"],
  ])("marks the backtest section and exact sub-navigation target at %s", async (path, label) => {
    const { wrapper } = await mountShell(path, true, true);
    await flushPromises();

    expect(
      wrapper
        .get('nav[aria-label="主要导航"] a[href="/backtests"]')
        .attributes("aria-current"),
    ).toBe("location");
    expect(
      wrapper
        .get('nav[aria-label="移动端主要导航"] a[href="/backtests"]')
        .attributes("aria-current"),
    ).toBe("location");

    const currentLinks = wrapper.findAll(
      'nav[aria-label="回测导航"] a[aria-current]',
    );
    expect(currentLinks).toHaveLength(1);
    expect(currentLinks[0]?.text()).toBe(label);
    expect(currentLinks[0]?.attributes("aria-current")).toBe("page");
  });

  it("preserves exact current-page semantics for non-backtest desktop and mobile links", async () => {
    const { wrapper } = await mountShell("/plans");
    await flushPromises();

    for (const label of ["主要导航", "移动端主要导航"]) {
      const currentLinks = wrapper.findAll(
        `nav[aria-label="${label}"] a[aria-current]`,
      );
      expect(currentLinks).toHaveLength(1);
      expect(currentLinks[0]?.attributes("href")).toBe("/plans");
      expect(currentLinks[0]?.attributes("aria-current")).toBe("page");
    }
  });

  it("applies title and heading focus only for the latest rapid path navigation", async () => {
    const { router, wrapper } = await mountShell("/backtests", true, true);
    await flushPromises();

    const firstNavigation = router.push("/backtests/new");
    const secondNavigation = router.push("/backtests/data");
    await Promise.all([firstNavigation, secondNavigation]);
    await flushPromises();

    expect(router.currentRoute.value.path).toBe("/backtests/data");
    expect(document.title).toBe("历史数据管理 · Trade Plan Monitor");
    expect(document.activeElement).toBe(wrapper.get("#main-content h1").element);
  });

  it("renders a semantic non-color-only stream status when no banner slot is supplied", async () => {
    const { wrapper } = await mountShell("/", false);
    const banner = wrapper.get('[role="status"][aria-live="polite"]');

    expect(banner.attributes("data-connection-state")).toBe("DISCONNECTED");
    expect(banner.text()).toContain("×");
    expect(banner.text()).toContain("连接中断，正在重试");
  });

  it("moves keyboard focus to the main landmark through the skip link", async () => {
    const { wrapper } = await mountShell();
    const skipLink = wrapper.get('a[href="#main-content"]');
    const main = wrapper.get("#main-content");
    const skipLinkElement = skipLink.element as HTMLAnchorElement;
    const mainElement = main.element as HTMLElement;

    skipLinkElement.focus();
    expect(document.activeElement).toBe(skipLinkElement);

    await skipLink.trigger("click");

    expect(document.activeElement).toBe(mainElement);
  });

  it("exposes a keyboard-operable mobile menu without replacing desktop navigation", async () => {
    const { router, wrapper } = await mountShell();
    const menuButton = wrapper.get("#mobile-navigation-toggle");
    const mobileNavigation = wrapper.get("#mobile-navigation");
    const menuButtonElement = menuButton.element as HTMLButtonElement;

    expect(menuButton.attributes("aria-expanded")).toBe("false");
    expect(mobileNavigation.attributes("hidden")).toBeDefined();

    menuButtonElement.focus();
    expect(menuButtonElement.tagName).toBe("BUTTON");
    await menuButton.trigger("click");

    expect(menuButton.attributes("aria-expanded")).toBe("true");
    expect(mobileNavigation.attributes("hidden")).toBeUndefined();

    await menuButton.trigger("keydown.escape");

    expect(menuButton.attributes("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(menuButtonElement);
    expect(wrapper.get('nav[aria-label="主要导航"]')).toBeTruthy();

    await menuButton.trigger("click");
    const alertsLink = wrapper.get<HTMLAnchorElement>(
      'nav[aria-label="移动端主要导航"] a[href="/alerts"]',
    );
    alertsLink.element.focus();
    await alertsLink.trigger("click");
    await flushPromises();

    await vi.waitFor(() => {
      expect(router.currentRoute.value.path).toBe("/alerts");
    });
    expect(menuButton.attributes("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(wrapper.get("#main-content h1").element);
  });

  it("uses responsive navigation rules and disables motion for reduced-motion users", () => {
    const source = readFileSync(resolve(process.cwd(), "src/layouts/AppShell.vue"), "utf8");

    expect(source).toMatch(/@media\s*\(min-width:\s*48rem\)/);
    expect(source).toMatch(/@media\s*\(prefers-reduced-motion:\s*reduce\)/);
    expect(source).toMatch(/transition-duration:\s*0\.01ms/);
  });

  it("suppresses the full-page focus ring on the programmatically focused main region", () => {
    const source = readFileSync(resolve(process.cwd(), "src/layouts/AppShell.vue"), "utf8");

    expect(source).toMatch(
      /\.app-shell__main:focus-visible\s*\{[^}]*outline:\s*none;/s,
    );
  });

  it("suppresses the focus ring on the programmatically focused route heading", () => {
    const source = readFileSync(resolve(process.cwd(), "src/layouts/AppShell.vue"), "utf8");

    expect(source).toMatch(
      /\.app-shell__main\s+:deep\(h1\[tabindex="-1"\]:focus-visible\)\s*\{[^}]*outline:\s*none;/s,
    );
  });

  it("styles a reachable service with unavailable monitoring as a warning", () => {
    const source = readFileSync(resolve(process.cwd(), "src/layouts/AppShell.vue"), "utf8");

    expect(source).toMatch(
      /\[data-connection-state="UNAVAILABLE"\]\s*\{[^}]*var\(--color-signal-watch-amber\)/s,
    );
  });
});
