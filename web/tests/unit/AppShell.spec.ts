import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, describe, expect, it } from "vitest";

import AppShell from "../../src/layouts/AppShell.vue";
import { routes } from "../../src/router";

const expectedPaths = [
  "/",
  "/stocks/:symbol",
  "/plans",
  "/plans/:id",
  "/alerts",
  "/system",
];

function createTestRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes,
  });
}

async function mountShell(path = "/") {
  const router = createTestRouter();
  await router.push(path);
  await router.isReady();

  const wrapper = mount(AppShell, {
    attachTo: document.body,
    global: { plugins: [router] },
    slots: {
      connectionBanner: '<p data-testid="connection-message">连接已恢复</p>',
    },
  });

  return { router, wrapper };
}

afterEach(() => {
  document.body.replaceChildren();
});

describe("AppShell", () => {
  it("declares the complete approved route surface", () => {
    expect(routes.map((route) => route.path)).toEqual(expectedPaths);
  });

  it("renders navigation, the connection banner slot, and the route outlet", async () => {
    const { wrapper } = await mountShell();

    expect(wrapper.get('nav[aria-label="主要导航"]')).toBeTruthy();
    expect(wrapper.get('nav[aria-label="移动端主要导航"]')).toBeTruthy();
    expect(wrapper.get('[role="status"][aria-live="polite"]').text()).toContain("连接已恢复");
    expect(wrapper.get("#main-content").text()).toContain("监控总览");

    await wrapper.get('nav[aria-label="主要导航"] a[href="/plans"]').trigger("click");
    await flushPromises();

    expect(wrapper.get("#main-content").text()).toContain("计划工作台");
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

    expect(router.currentRoute.value.path).toBe("/alerts");
    expect(menuButton.attributes("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(wrapper.get("#main-content").element);
  });

  it("uses responsive navigation rules and disables motion for reduced-motion users", () => {
    const source = readFileSync(resolve(process.cwd(), "src/layouts/AppShell.vue"), "utf8");

    expect(source).toMatch(/@media\s*\(min-width:\s*48rem\)/);
    expect(source).toMatch(/@media\s*\(prefers-reduced-motion:\s*reduce\)/);
    expect(source).toMatch(/transition-duration:\s*0\.01ms/);
  });
});
