import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";
import { routes } from "../router";

export const runtimeRoutes: RouteRecordRaw[] = routes.map((route) => {
  if (route.path === "/") return { path: route.path, name: "dashboard", meta: { title: "监控总览 · Trade Plan Monitor" }, component: () => import("./DashboardView.vue") };
  if (route.path === "/system") return { path: route.path, name: "system", meta: { title: "系统健康 · Trade Plan Monitor" }, component: () => import("./SystemView.vue") };
  if (route.path === "/stocks/:symbol") return { path: route.path, name: "stock-detail", props: true, meta: { title: "个股详情 · Trade Plan Monitor" }, component: () => import("./SymbolView.vue") };
  return route;
});
export const runtimeRouter = createRouter({ history: createWebHistory(), routes: runtimeRoutes });
