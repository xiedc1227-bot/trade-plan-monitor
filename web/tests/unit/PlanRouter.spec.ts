import { describe, expect, it } from "vitest";
import type { RouteComponent, RouteRecordRaw } from "vue-router";

import { routes } from "../../src/router";

type LazyRouteComponent = () => Promise<{ default: RouteComponent }>;

function routeAt(path: string): RouteRecordRaw {
  const route = routes.find((candidate) => candidate.path === path);
  if (route === undefined) throw new Error(`Missing route ${path}`);
  return route;
}

describe("plan production routes", () => {
  it.each([
    ["/plans", "计划工作台 · Trade Plan Monitor"],
    ["/plans/:id", "计划详情 · Trade Plan Monitor"],
  ])("loads %s from the real plan workbench", async (path, title) => {
    const route = routeAt(path);

    expect(route.meta?.title).toBe(title);
    expect(typeof route.component).toBe("function");

    const loaded = await (route.component as LazyRouteComponent)();
    expect(loaded.default).toBeDefined();
  });

  it("passes the exact plan version ID to the detail workbench", () => {
    const route = routeAt("/plans/:id");

    expect(typeof route.props).toBe("function");
    const props = (route.props as (route: { params: Record<string, string> }) => unknown)({
      params: { id: "00000000-0000-4000-8000-000000000402" },
    });

    expect(props).toEqual({ planVersionId: "00000000-0000-4000-8000-000000000402" });
  });
});
