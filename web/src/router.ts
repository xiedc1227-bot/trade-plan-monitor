import { defineComponent, h } from "vue";
import { createRouter, createWebHistory } from "vue-router";
import type { RouteRecordRaw } from "vue-router";

function createRoutePlaceholder(name: string, title: string, description: string) {
  return defineComponent({
    name,
    setup() {
      return () =>
        h("section", { "aria-labelledby": `${name}-title` }, [
          h("h1", { id: `${name}-title` }, title),
          h("p", description),
        ]);
    },
  });
}

const DashboardRoute = () => import("./views/DashboardRouteView.vue");
const StockDetailRoute = createRoutePlaceholder(
  "StockDetailRoute",
  "个股详情",
  "个股视图将在后续任务中提供。",
);
const PlanWorkbenchRoute = () => import("./views/PlanDraftingView.vue");
const AlertsRoute = createRoutePlaceholder(
  "AlertsRoute",
  "提醒中心",
  "提醒视图将在后续任务中提供。",
);
const SystemRoute = () => import("./views/SystemRouteView.vue");

export const routes: RouteRecordRaw[] = [
  {
    path: "/",
    name: "dashboard",
    component: DashboardRoute,
    meta: { title: "监控总览 · Trade Plan Monitor" },
  },
  {
    path: "/stocks/:symbol",
    name: "stock-detail",
    component: StockDetailRoute,
    meta: { title: "个股详情 · Trade Plan Monitor" },
  },
  {
    path: "/plans",
    name: "plans",
    component: PlanWorkbenchRoute,
    meta: { title: "计划工作台 · Trade Plan Monitor" },
  },
  {
    path: "/plans/:id",
    name: "plan-detail",
    component: PlanWorkbenchRoute,
    props: (route) => ({
      planVersionId: typeof route.params.id === "string" ? route.params.id : undefined,
    }),
    meta: { title: "计划详情 · Trade Plan Monitor" },
  },
  {
    path: "/alerts",
    name: "alerts",
    component: AlertsRoute,
    meta: { title: "提醒中心 · Trade Plan Monitor" },
  },
  {
    path: "/system",
    name: "system",
    component: SystemRoute,
    meta: { title: "系统健康 · Trade Plan Monitor" },
  },
  {
    path: "/backtests",
    name: "backtest-runs",
    component: () => import("./views/BacktestRunsView.vue"),
    meta: { section: "backtests", title: "回测运行记录 · Trade Plan Monitor" },
  },
  {
    path: "/backtests/new",
    name: "backtest-new",
    component: () => import("./views/BacktestNewView.vue"),
    meta: { section: "backtests", title: "创建回测 · Trade Plan Monitor" },
  },
  {
    path: "/backtests/data",
    name: "backtest-data",
    component: () => import("./views/BacktestDataView.vue"),
    meta: { section: "backtests", title: "历史数据管理 · Trade Plan Monitor" },
  },
  {
    path: "/backtests/:runId",
    name: "backtest-run-detail",
    component: () => import("./views/BacktestRunDetailView.vue"),
    meta: { section: "backtests", title: "回测结果 · Trade Plan Monitor" },
  },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
});
