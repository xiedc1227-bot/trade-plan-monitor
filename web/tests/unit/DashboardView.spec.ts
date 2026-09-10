import { h } from "vue";
import type { VNode } from "vue";
import { mount } from "@vue/test-utils";
import { createMemoryHistory, createRouter } from "vue-router";
import { describe, expect, it } from "vitest";

import type {
  AuthoritativeDecisionView,
  DashboardCounts,
  DataHealthStatus,
  SignalType,
  SymbolSummaryView,
} from "../../src/api/generated";
import DashboardView from "../../src/views/DashboardView.vue";

const counts: DashboardCounts = {
  actionable: 5,
  blocked: 1,
  lowZoneWatch: 1,
  normal: 2,
  risk: 2,
  stale: 1,
};

function decision(
  index: number,
  overrides: Partial<AuthoritativeDecisionView> = {},
): AuthoritativeDecisionView {
  const symbol = `${String(index + 1).padStart(6, "0")}.SZ`;
  return {
    dataAgeSeconds: index + 1,
    dataHealth: {
      dataAgeSeconds: index + 1,
      fresh: true,
      latestBarEnd: `2026-08-24T10:${String(20 + index).padStart(2, "0")}:00+08:00`,
      requiredDataComplete: true,
      status: "LIVE",
    },
    episodeLowFen: 950 + index,
    episodeStatus: "ACTIVE",
    evaluatedAt: `2026-08-24T10:${String(20 + index).padStart(2, "0")}:05+08:00`,
    evidence: [],
    marketDataAt: `2026-08-24T10:${String(20 + index).padStart(2, "0")}:00+08:00`,
    nextStep: { code: "WATCH_LOW_ZONE" },
    planHash: String(index).repeat(64),
    planId: `plan-${index + 1}`,
    planVersion: index + 1,
    position: {
      coreQuantity: index * 100,
      sellableCoreQuantity: index * 100,
      sellableTacticalQuantity: index % 2 === 0 ? 0 : 100,
      tacticalQuantity: index % 2 === 0 ? 0 : 100,
      totalQuantity: index * 100 + (index % 2 === 0 ? 0 : 100),
    },
    priceFen: 1_000 + index * 25,
    resultHash: String(index + 1).repeat(64),
    riskBreachTradeDate: null,
    riskStatus: "CLEAR",
    signalType: "WAIT",
    symbol,
    zone: "OUTSIDE",
    ...overrides,
  };
}

function symbolSummary(
  index: number,
  options: {
    connected?: boolean;
    fresh?: boolean;
    health?: DataHealthStatus;
    name?: string;
    riskDistanceFen?: number | null;
    signal?: SignalType;
  } = {},
): SymbolSummaryView {
  const baseDecision = decision(index);
  const status = options.health ?? "LIVE";
  const fresh = options.fresh ?? status === "LIVE";
  const selectedDecision: AuthoritativeDecisionView = {
    ...baseDecision,
    dataHealth: {
      ...baseDecision.dataHealth,
      fresh,
      requiredDataComplete: fresh,
      status,
    },
    signalType: options.signal ?? baseDecision.signalType,
    zone:
      options.signal === "LOW_ZONE_WATCH"
        ? "LOW_BUY"
        : options.signal === "RISK_BREACH"
          ? "BELOW_RISK"
          : baseDecision.zone,
  };
  return {
    connected: options.connected ?? true,
    decision: selectedDecision,
    name: options.name ?? `监控股票${index + 1}`,
    observedAt: selectedDecision.evaluatedAt,
    riskDistanceFen: options.riskDistanceFen ?? 100 - index * 10,
    satisfiedConditionCount: index % 4,
    symbol: selectedDecision.symbol,
    totalConditionCount: 3,
  };
}

const symbols: readonly SymbolSummaryView[] = [
  symbolSummary(0, { name: "平安银行", signal: "BUY_CORE_READY" }),
  symbolSummary(1, { name: "万科A", signal: "LOW_ZONE_WATCH" }),
  symbolSummary(2, { connected: false, health: "GAPPED", signal: "BLOCKED_DATA" }),
  symbolSummary(3, { riskDistanceFen: -20, signal: "RISK_BREACH" }),
  symbolSummary(4),
  symbolSummary(5, { signal: "PRESSURE_REDUCE_READY" }),
  symbolSummary(6, { signal: "RISK_EXIT_PENDING_SETTLEMENT" }),
  symbolSummary(7, { signal: "BUY_TACTICAL_READY" }),
  symbolSummary(8, { signal: "RISK_RECOVERED" }),
  symbolSummary(9, { health: "DEGRADED" }),
];

async function mountDashboard(
  props: Partial<InstanceType<typeof DashboardView>["$props"]> = {},
  slots: {
    actionableRail?: (props: { symbols: readonly SymbolSummaryView[] }) => VNode;
  } = {},
) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", component: { template: "<div />" } },
      { path: "/stocks/:symbol", component: { template: "<div />" } },
    ],
  });
  await router.push("/");
  await router.isReady();

  return mount(DashboardView, {
    global: { plugins: [router] },
    props: {
      connectionStatus: "CONNECTED",
      counts,
      dataAgeSeconds: 2,
      observedAt: "2026-08-24T10:30:00+08:00",
      symbols,
      ...props,
    },
    slots,
  });
}

describe("DashboardView", () => {
  it("renders ten isolated rows with every authoritative summary field", async () => {
    const wrapper = await mountDashboard();
    const rows = wrapper.findAll('[data-testid="watchlist-row"]');

    expect(rows).toHaveLength(10);
    expect(rows[0]?.text()).toContain("平安银行");
    expect(rows[0]?.text()).toContain("10.00 元");
    expect(rows[0]?.text()).toContain("核心买入就绪");
    expect(rows[0]?.text()).toContain("总计 0");
    expect(rows[0]?.text()).toContain("+1.00 元");
    expect(rows[0]?.text()).toContain("2026-08-24T10:20:00+08:00");
    expect(rows[9]?.text()).toContain("降级");
    expect(rows[4]?.text()).toContain("监控股票5");
    expect(rows[4]?.text()).toContain("实时");
  });

  it("shows server counts and explicit non-color connection/freshness labels", async () => {
    const wrapper = await mountDashboard();

    expect(wrapper.get('[data-testid="dashboard-count-actionable"]').text()).toContain("5");
    expect(wrapper.get('[data-testid="dashboard-count-stale"]').text()).toContain("1");
    expect(wrapper.get('[data-testid="market-status-strip"]').text()).toContain("已连接");
    expect(wrapper.get('[data-testid="market-status-strip"]').text()).toContain("数据年龄 2 秒");
    expect(wrapper.get('[data-testid="market-status-strip"]').text()).toContain(
      "2026-08-24T10:30:00+08:00",
    );
  });

  it("searches by symbol or name without mutating the readonly rows", async () => {
    const wrapper = await mountDashboard();
    const originalFirst = symbols[0];

    await wrapper.get<HTMLInputElement>("#watchlist-search").setValue("万科");
    expect(wrapper.findAll('[data-testid="watchlist-row"]')).toHaveLength(1);
    expect(wrapper.text()).toContain("万科A");

    await wrapper.get<HTMLInputElement>("#watchlist-search").setValue("000001");
    expect(wrapper.findAll('[data-testid="watchlist-row"]')).toHaveLength(1);
    expect(wrapper.text()).toContain("平安银行");
    expect(symbols[0]).toBe(originalFirst);
    expect(symbols[0]?.name).toBe("平安银行");
  });

  it("filters authoritative actionable, blocked, risk, stale, and normal categories", async () => {
    const degradedButFresh = symbols.map((item, index) =>
      index === 9 ? symbolSummary(index, { fresh: true, health: "DEGRADED" }) : item,
    );
    const wrapper = await mountDashboard({ symbols: degradedButFresh });
    const filter = wrapper.get<HTMLSelectElement>("#watchlist-filter");

    await filter.setValue("BLOCKED");
    expect(wrapper.findAll('[data-testid="watchlist-row"]')).toHaveLength(1);
    expect(wrapper.text()).toContain("数据阻断");

    await filter.setValue("STALE");
    expect(wrapper.findAll('[data-testid="watchlist-row"]')).toHaveLength(2);
    expect(wrapper.text()).toContain("缺口");
    expect(wrapper.text()).toContain("降级");

    await filter.setValue("ACTIONABLE");
    expect(wrapper.findAll('[data-testid="watchlist-row"]')).toHaveLength(5);

    await filter.setValue("NORMAL");
    expect(wrapper.findAll('[data-testid="watchlist-row"]')).toHaveLength(2);
    expect(wrapper.text()).not.toContain("监控股票10");
  });

  it("sorts copied display rows while keeping null values last", async () => {
    const withNull = symbols.map((item, index) =>
      index === 4 ? { ...item, riskDistanceFen: null } : item,
    );
    const wrapper = await mountDashboard({ symbols: withNull });

    await wrapper.get<HTMLSelectElement>("#watchlist-sort").setValue("RISK_DISTANCE");
    const ascending = wrapper.findAll('[data-testid="watchlist-row"]');
    expect(ascending[0]?.text()).toContain("000004.SZ");
    expect(ascending.at(-1)?.text()).toContain("风险距离 —");

    await wrapper.get('[data-testid="toggle-sort-direction"]').trigger("click");
    const descending = wrapper.findAll('[data-testid="watchlist-row"]');
    expect(descending[0]?.text()).toContain("000001.SZ");
    expect(descending.at(-1)?.text()).toContain("风险距离 —");
  });

  it("provides keyboard-native row navigation and emits the selected symbol", async () => {
    const wrapper = await mountDashboard();
    const link = wrapper.get<HTMLAnchorElement>('a[href="/stocks/000001.SZ"]');

    expect(link.element.tagName).toBe("A");
    expect(link.attributes("tabindex")).toBeUndefined();
    await link.trigger("click");

    expect(wrapper.emitted("selectSymbol")).toEqual([["000001.SZ"]]);
  });

  it("exposes only authoritative actionable rows to the typed rail slot", async () => {
    const wrapper = await mountDashboard({}, {
      actionableRail: ({ symbols: actionable }: { symbols: readonly SymbolSummaryView[] }) =>
        h(
          "ol",
          { "data-testid": "actionable-rail" },
          actionable.map((item) => h("li", { key: item.symbol }, item.symbol)),
        ),
    });

    const rail = wrapper.get('[data-testid="actionable-rail"]');
    expect(rail.findAll("li")).toHaveLength(5);
    expect(rail.text()).toContain("000001.SZ");
    expect(rail.text()).not.toContain("000005.SZ");
  });

  it("hides the actionable rail when no stocks are being monitored", async () => {
    const wrapper = await mountDashboard({ symbols: [] });

    expect(wrapper.find("#actionable-rail-title").exists()).toBe(false);
    expect(wrapper.text()).not.toContain("具备后端权威可执行信号");
  });

  it("keeps stale cached rows visible beside loading and escaped error states", async () => {
    const hostile = '<img src=x onerror="globalThis.compromised=true">';
    const wrapper = await mountDashboard({
      connectionStatus: "DISCONNECTED",
      error: hostile,
      loading: true,
    });

    expect(wrapper.get('[role="alert"]').text()).toContain(hostile);
    expect(wrapper.find("img").exists()).toBe(false);
    expect(wrapper.get('[role="status"]').text()).toContain("正在刷新");
    expect(wrapper.findAll('[data-testid="watchlist-row"]')).toHaveLength(10);
    expect(wrapper.text()).toContain("连接中断");
  });

  it("does not misreport unavailable data as an empty watchlist", async () => {
    const loading = await mountDashboard({ loading: true, symbols: [] });
    const failed = await mountDashboard({ error: "快照不可用", symbols: [] });

    expect(loading.find('[data-testid="watchlist-empty"]').exists()).toBe(false);
    expect(failed.find('[data-testid="watchlist-empty"]').exists()).toBe(false);
    expect(failed.get('[role="alert"]').text()).toContain("快照不可用");
  });

  it("keeps four empty index charts visible while the monitor projection is unavailable", async () => {
    const wrapper = await mountDashboard({
      symbols: [],
      unavailable: {
        availability: "UNAVAILABLE",
        observedAt: "2026-09-10T10:48:49+08:00",
        reason: "EMPTY_DATABASE",
        sequence: 0,
      },
    });

    expect(wrapper.findAll('[data-testid="market-index-trend-card"]')).toHaveLength(4);
    expect(wrapper.findAll('[data-testid="market-index-sparkline"]')).toHaveLength(4);
    expect(wrapper.text()).toContain("当前暂无当日五分钟数据");
  });

  it("renders distinct empty and no-match states", async () => {
    const empty = await mountDashboard({ symbols: [] });
    expect(empty.get('[data-testid="watchlist-empty"]').text()).toContain("尚无监控股票");

    const noMatch = await mountDashboard();
    await noMatch.get<HTMLInputElement>("#watchlist-search").setValue("不存在的股票");
    expect(noMatch.get('[data-testid="watchlist-empty"]').text()).toContain("没有匹配当前条件");
  });

  it("renders condition progress as count plus text rather than color alone", async () => {
    const wrapper = await mountDashboard();
    const blockedRow = wrapper.findAll('[data-testid="watchlist-row"]')[2];
    const progress = blockedRow?.get('[data-testid="condition-progress"]');

    expect(progress?.text()).toContain("2 / 3");
    expect(progress?.text()).toContain("阻断");
    expect(progress?.get("progress").attributes("max")).toBe("3");
    expect(progress?.get("progress").attributes("value")).toBe("2");
  });

  it("supports labelled keyboard controls and compact/comfortable display modes", async () => {
    const wrapper = await mountDashboard();

    expect(wrapper.get('label[for="watchlist-search"]').text()).toContain("搜索");
    expect(wrapper.get('label[for="watchlist-filter"]').text()).toContain("筛选");
    expect(wrapper.get('label[for="watchlist-sort"]').text()).toContain("排序");
    await wrapper.get('[data-testid="toggle-view-mode"]').trigger("click");
    expect(wrapper.get("table").attributes("data-density")).toBe("COMFORTABLE");
  });

  it("bounds search input before display filtering", async () => {
    const wrapper = await mountDashboard();
    const search = wrapper.get<HTMLInputElement>("#watchlist-search");

    await search.setValue("万".repeat(1_000));

    expect(search.element.value).toHaveLength(128);
    expect(search.attributes("maxlength")).toBe("128");
  });
});
