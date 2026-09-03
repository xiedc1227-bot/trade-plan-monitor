import { describe, expect, it } from "vitest";
import type { RouteComponent, RouteRecordRaw } from "vue-router";

import { routes } from "../../src/router";

const historicalPaths = [
  "/",
  "/stocks/:symbol",
  "/plans",
  "/plans/:id",
  "/alerts",
  "/system",
] as const;

const remainingPlaceholderPaths = ["/alerts"] as const;

const backtestPaths = [
  "/backtests",
  "/backtests/new",
  "/backtests/data",
  "/backtests/:runId",
] as const;

type LazyRouteComponent = () => Promise<{ default: RouteComponent }>;

function routeAt(path: string): RouteRecordRaw {
  const route = routes.find((candidate) => candidate.path === path);
  if (route === undefined) throw new Error(`Missing route ${path}`);
  return route;
}

describe("backtest production routes", () => {
  it("keeps the exact ten-route surface with stock detail wired and alerts still placeholder", () => {
    expect(routes).toHaveLength(10);
    expect(routes.map((route) => route.path)).toEqual([
      ...historicalPaths,
      ...backtestPaths,
    ]);

    for (const path of remainingPlaceholderPaths) {
      expect(typeof routeAt(path).component).not.toBe("function");
    }
    for (const path of ["/", "/stocks/:symbol", "/plans", "/plans/:id", "/system"]) {
      expect(typeof routeAt(path).component).toBe("function");
    }
  });

  it("keeps the three static backtest routes before the dynamic run route", () => {
    const paths = routes.map((route) => route.path);
    const dynamicIndex = paths.indexOf("/backtests/:runId");

    expect(paths.indexOf("/backtests")).toBeLessThan(dynamicIndex);
    expect(paths.indexOf("/backtests/new")).toBeLessThan(dynamicIndex);
    expect(paths.indexOf("/backtests/data")).toBeLessThan(dynamicIndex);
  });

  it.each([
    ["/backtests", "回测运行记录 · Trade Plan Monitor"],
    ["/backtests/new", "创建回测 · Trade Plan Monitor"],
    ["/backtests/data", "历史数据管理 · Trade Plan Monitor"],
    ["/backtests/:runId", "回测结果 · Trade Plan Monitor"],
  ])("loads %s from a real lazy SFC with route title metadata", async (path, title) => {
    const route = routeAt(path);

    expect(route.meta?.title).toBe(title);
    expect(typeof route.component).toBe("function");

    const loaded = await (route.component as LazyRouteComponent)();
    expect(loaded.default).toBeDefined();
  });
});
