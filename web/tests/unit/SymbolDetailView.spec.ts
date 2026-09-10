import { isShallow, nextTick, shallowRef } from "vue";
import { enableAutoUnmount, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AuthoritativeDecisionView,
  BarView,
  SymbolDetailResponse,
  SymbolEventView,
} from "../../src/api/generated";
import EpisodeTimeline from "../../src/components/symbol/EpisodeTimeline.vue";
import PriceChart from "../../src/components/symbol/PriceChart.vue";
import type { ChartSeries } from "../../src/composables/useChartSeries";
import { useChartSeries } from "../../src/composables/useChartSeries";
import SymbolDetailView from "../../src/views/SymbolDetailView.vue";

const echartsMock = vi.hoisted(() => {
  const handlers = new Map<string, (payload: unknown) => void>();
  const chart = {
    dispose: vi.fn(),
    off: vi.fn((event: string) => handlers.delete(event)),
    on: vi.fn((event: string, handler: (payload: unknown) => void) => {
      handlers.set(event, handler);
    }),
    resize: vi.fn(),
    setOption: vi.fn(),
  };
  return {
    chart,
    handlers,
    init: vi.fn(() => chart),
  };
});

vi.mock("echarts/core", () => ({ init: echartsMock.init, use: vi.fn() }));
vi.mock("echarts/charts", () => ({ CandlestickChart: {}, ScatterChart: {} }));
vi.mock("echarts/components", () => ({
  AriaComponent: {},
  DataZoomComponent: {},
  GridComponent: {},
  LegendComponent: {},
  MarkLineComponent: {},
  TooltipComponent: {},
}));
vi.mock("echarts/renderers", () => ({ CanvasRenderer: {} }));

const symbol = "003043.SZ";
const firstTime = "2026-08-24T10:00:00+08:00";
const secondTime = "2026-08-24T10:05:00+08:00";
const alertTime = "2026-08-24T10:05:05+08:00";

const bars: readonly BarView[] = Object.freeze([
  Object.freeze({
    amountYuan: "18200.00",
    barEnd: secondTime,
    closeFen: 1_230,
    formulaVersion: "five-minute-v1",
    highFen: 1_250,
    interval: "FIVE_MINUTES",
    lowFen: 1_210,
    openFen: 1_220,
    receivedAt: "2026-08-24T10:05:12+08:00",
    symbol,
    volumeShares: 1_800,
  }),
  Object.freeze({
    amountYuan: "12000.00",
    barEnd: firstTime,
    closeFen: 1_220,
    formulaVersion: "five-minute-v1",
    highFen: 1_230,
    interval: "FIVE_MINUTES",
    lowFen: 1_190,
    openFen: 1_200,
    receivedAt: "2026-08-24T10:00:12+08:00",
    symbol,
    volumeShares: 1_000,
  }),
]);

const evidence: NonNullable<AuthoritativeDecisionView["evidence"]> = [
  {
    children: [
      {
        children: [],
        code: "MANUAL_EVENT_RISK_CLEAR",
        facts: [],
        kind: "CONDITION",
        missingInputs: ["MANUAL_EVENT_RISK"],
        outcome: "MISSING_INPUT",
      },
    ],
    code: "PRICE_IN_ZONE",
    facts: [
      { key: "zone_low_fen", unit: "FEN", value: 1_200 },
      { key: "zone_high_fen", unit: "FEN", value: 1_260 },
      { key: "risk_line_fen", unit: "FEN", value: 1_100 },
      { key: "indicator_yuan", unit: "YUAN", value: "-0.103456788" },
      { key: "indicator_source_as_of", unit: "DATETIME", value: firstTime },
    ],
    kind: "CONDITION",
    missingInputs: [],
    outcome: "SATISFIED",
  },
];

const decision: AuthoritativeDecisionView = Object.freeze({
  dataAgeSeconds: 5,
  dataHealth: Object.freeze({
    dataAgeSeconds: 5,
    fresh: true,
    latestBarEnd: secondTime,
    requiredDataComplete: true,
    status: "LIVE",
  }),
  episodeLowFen: 1_190,
  episodeStatus: "ACTIVE",
  evaluatedAt: "2026-08-24T10:05:05+08:00",
  evidence,
  marketDataAt: secondTime,
  nextStep: Object.freeze({ code: "WATCH_LOW_ZONE" }),
  planHash: "b".repeat(64),
  planId: "plan-1",
  planVersion: 3,
  position: Object.freeze({
    coreQuantity: 0,
    sellableCoreQuantity: 0,
    sellableTacticalQuantity: 0,
    tacticalQuantity: 0,
    totalQuantity: 0,
  }),
  priceFen: 1_230,
  resultHash: "a".repeat(64),
  riskBreachTradeDate: null,
  riskStatus: "CLEAR",
  signalType: "LOW_ZONE_WATCH",
  symbol,
  zone: "LOW_BUY",
});

const events: readonly SymbolEventView[] = Object.freeze([
  Object.freeze({
    eventId: "00000000-0000-4000-8000-000000000001",
    eventType: "EPISODE",
    messageText: "低吸阶段开始",
    occurredAt: firstTime,
    resultHash: decision.resultHash,
    sequence: 10,
    signalType: null,
    symbol,
  }),
  Object.freeze({
    eventId: "00000000-0000-4000-8000-000000000002",
    eventType: "ALERT",
    messageText: '<img src=x onerror="globalThis.compromised=true">',
    occurredAt: alertTime,
    resultHash: decision.resultHash,
    sequence: 11,
    signalType: "BUY_CORE_READY",
    symbol,
  }),
  Object.freeze({
    eventId: "00000000-0000-4000-8000-000000000003",
    eventType: "RISK",
    messageText: "风险状态保持清晰",
    occurredAt: secondTime,
    resultHash: decision.resultHash,
    sequence: 12,
    signalType: null,
    symbol,
  }),
]);

const detail: SymbolDetailResponse = Object.freeze({
  positionLots: [],
  summary: Object.freeze({
    connected: true,
    decision,
    name: "华亚智能",
    observedAt: "2026-08-24T10:05:05+08:00",
    riskDistanceFen: 130,
    satisfiedConditionCount: 1,
    symbol,
    totalConditionCount: 2,
  }),
});

const emptySeries: ChartSeries = Object.freeze({
  alertMarkers: Object.freeze([]),
  candles: Object.freeze([]),
  episodeLow: null,
  evidenceRows: Object.freeze([]),
  indicators: Object.freeze([]),
  priceLevels: Object.freeze([]),
});

beforeEach(() => {
  echartsMock.handlers.clear();
  vi.clearAllMocks();
});
enableAutoUnmount(afterEach);

describe("useChartSeries", () => {
  it("maps immutable OHLC, levels, indicators, episode low, alerts, and evidence without calculation", () => {
    const originalOrder = bars.map((bar) => bar.barEnd);
    const { series } = useChartSeries({ bars, decision, events });

    expect(isShallow(series)).toBe(true);
    expect(series.value.candles).toEqual([
      {
        closeYuan: 12.2,
        highYuan: 12.3,
        lowYuan: 11.9,
        openYuan: 12,
        time: firstTime,
        volumeShares: 1_000,
      },
      {
        closeYuan: 12.3,
        highYuan: 12.5,
        lowYuan: 12.1,
        openYuan: 12.2,
        time: secondTime,
        volumeShares: 1_800,
      },
    ]);
    expect(series.value.priceLevels.map((level) => [level.factKey, level.valueYuan])).toEqual([
      ["zone_low_fen", 12],
      ["zone_high_fen", 12.6],
      ["risk_line_fen", 11],
    ]);
    expect(series.value.indicators).toEqual([
      expect.objectContaining({
        factKey: "indicator_yuan",
        plotTime: firstTime,
        time: firstTime,
        value: -0.103456788,
        valueText: "-0.103456788",
      }),
    ]);
    expect(series.value.episodeLow).toEqual({
      label: "阶段低点",
      time: null,
      valueYuan: 11.9,
    });
    expect(series.value.alertMarkers).toEqual([
      expect.objectContaining({
        eventId: events[1]?.eventId,
        label: "BUY_CORE_READY",
        messageText: events[1]?.messageText,
        plotTime: secondTime,
        time: alertTime,
        valueYuan: 12.3,
      }),
    ]);
    expect(series.value.evidenceRows).toHaveLength(2);
    expect(series.value.evidenceRows[1]).toEqual(
      expect.objectContaining({ code: "MANUAL_EVENT_RISK_CLEAR", depth: 1 }),
    );
    expect(Object.isFrozen(series.value)).toBe(true);
    expect(Object.isFrozen(series.value.candles)).toBe(true);
    expect(Object.isFrozen(series.value.evidenceRows[0]?.facts[0])).toBe(true);
    expect(bars.map((bar) => bar.barEnd)).toEqual(originalOrder);
  });

  it("accepts refs and getters and replaces one shallow immutable series", async () => {
    const barSource = shallowRef(bars);
    const eventSource = shallowRef(events);
    const decisionSource = shallowRef<AuthoritativeDecisionView | null>(decision);
    const { series } = useChartSeries({
      bars: barSource,
      decision: () => decisionSource.value,
      events: eventSource,
    });
    const firstSeries = series.value;

    barSource.value = Object.freeze([bars[0] as BarView]);
    eventSource.value = Object.freeze([]);
    decisionSource.value = null;
    await vi.dynamicImportSettled();

    expect(series.value).not.toBe(firstSeries);
    expect(series.value.candles).toHaveLength(1);
    expect(series.value.priceLevels).toEqual([]);
    expect(series.value.alertMarkers).toEqual([]);
  });

  it("retains an authoritative alert when no chart price anchor is available", () => {
    const priceUnavailable: AuthoritativeDecisionView = {
      ...decision,
      priceFen: null,
    };
    const { series } = useChartSeries({
      bars: [],
      decision: priceUnavailable,
      events: [events[1] as SymbolEventView],
    });

    expect(series.value.alertMarkers).toEqual([
      expect.objectContaining({
        eventId: events[1]?.eventId,
        plotTime: null,
        valueYuan: null,
      }),
    ]);

  });

  it("binds indicator siblings to their authoritative times and preserves decimal text", () => {
    const previousBar: BarView = {
      ...(bars[0] as BarView),
      barEnd: "2026-08-22T15:00:00+08:00",
    };
    const currentBar: BarView = {
      ...(bars[1] as BarView),
      barEnd: "2026-08-23T15:00:00+08:00",
    };
    const timedDecision: AuthoritativeDecisionView = {
      ...decision,
      evidence: [
        {
          children: [],
          code: "MACD_HIST_IMPROVEMENT_GTE",
          facts: [
            {
              key: "previous_macd_histogram_yuan",
              unit: "YUAN",
              value: "-0.103456788",
            },
            {
              key: "current_macd_histogram_yuan",
              unit: "YUAN",
              value: "1E-400",
            },
            { key: "previous_indicator_date", unit: "DATE", value: "2026-08-22" },
            { key: "current_indicator_date", unit: "DATE", value: "2026-08-23" },
            {
              key: "indicator_source_as_of",
              unit: "DATETIME",
              value: "2026-08-24T15:00:00+08:00",
            },
          ],
          kind: "CONDITION",
          missingInputs: [],
          outcome: "SATISFIED",
        },
      ],
      marketDataAt: "2026-08-24T15:00:00+08:00",
    };
    const { series } = useChartSeries({
      bars: [previousBar, currentBar],
      decision: timedDecision,
      events: [],
    });

    expect(series.value.indicators).toEqual([
      expect.objectContaining({
        factKey: "previous_macd_histogram_yuan",
        plotTime: previousBar.barEnd,
        time: "2026-08-22",
        valueText: "-0.103456788",
      }),
      expect.objectContaining({
        factKey: "current_macd_histogram_yuan",
        plotTime: currentBar.barEnd,
        time: "2026-08-23",
        value: null,
        valueText: "1E-400",
      }),
    ]);

    const followingBar: BarView = {
      ...currentBar,
      barEnd: "2026-08-24T10:00:00+08:00",
    };
    const withoutCurrentDateBar = useChartSeries({
      bars: [previousBar, followingBar],
      decision: timedDecision,
      events: [],
    });
    expect(
      withoutCurrentDateBar.series.value.indicators.find(
        (indicator) => indicator.factKey === "current_macd_histogram_yuan",
      )?.plotTime,
    ).toBeNull();
  });

  it("keeps an untimed indicator for the table without inventing a chart coordinate", () => {
    const untimedDecision: AuthoritativeDecisionView = {
      ...decision,
      evidence: [
        {
          children: [],
          code: "BOLL_LOWER_HIT_LIMIT",
          facts: [{ key: "latest_boll_lower_yuan", unit: "YUAN", value: "12.123456" }],
          kind: "CONDITION",
          missingInputs: [],
          outcome: "SATISFIED",
        },
      ],
    };
    const { series } = useChartSeries({ bars, decision: untimedDecision, events: [] });

    expect(series.value.indicators).toEqual([
      expect.objectContaining({
        factKey: "latest_boll_lower_yuan",
        plotTime: null,
        time: null,
        valueText: "12.123456",
      }),
    ]);
  });
});

describe("PriceChart", () => {
  it("loads ECharts on demand, updates it, emits zoom, and cleans resize/unmount", async () => {
    const wrapper = mount(PriceChart, { props: { series: emptySeries, stale: false } });
    await vi.dynamicImportSettled();

    expect(echartsMock.init).toHaveBeenCalledTimes(1);
    expect(echartsMock.chart.setOption).toHaveBeenCalledTimes(1);
    window.dispatchEvent(new Event("resize"));
    expect(echartsMock.chart.resize).toHaveBeenCalledTimes(1);

    echartsMock.handlers.get("datazoom")?.({ batch: [{ end: 80, start: 20 }] });
    expect(wrapper.emitted("rangeChange")).toEqual([[{ endPercent: 80, startPercent: 20 }]]);

    await wrapper.setProps({ series: useChartSeries({ bars, decision, events }).series.value });
    expect(echartsMock.init).toHaveBeenCalledTimes(1);
    expect(echartsMock.chart.setOption).toHaveBeenCalledTimes(2);

    wrapper.unmount();
    expect(echartsMock.chart.off).toHaveBeenCalledWith("datazoom", expect.any(Function));
    expect(echartsMock.chart.dispose).toHaveBeenCalledTimes(1);
    window.dispatchEvent(new Event("resize"));
    expect(echartsMock.chart.resize).toHaveBeenCalledTimes(1);
  });
});

describe("EpisodeTimeline", () => {
  it("renders only episode/risk events as native selectable controls", async () => {
    const wrapper = mount(EpisodeTimeline, { props: { events, selectedAt: firstTime } });
    const buttons = wrapper.findAll("button");

    expect(buttons).toHaveLength(2);
    expect(wrapper.text()).toContain("低吸阶段开始");
    expect(wrapper.text()).toContain("风险状态保持清晰");
    expect(wrapper.text()).not.toContain("onerror");
    expect(buttons[0]?.attributes("aria-current")).toBe("true");

    await buttons[1]?.trigger("click");
    expect(wrapper.emitted("selectTime")).toEqual([[secondTime]]);
  });
});

describe("SymbolDetailView", () => {
  it("renders chart facts and the accessible tabular alternative from one mapped series", async () => {
    const wrapper = mount(SymbolDetailView, {
      props: { bars, detail, events },
    });
    await vi.dynamicImportSettled();
    await nextTick();

    expect(wrapper.text()).toContain("华亚智能");
    expect(wrapper.text()).toContain("已连接");
    expect(wrapper.text()).toContain("数据年龄 5 秒");
    expect(wrapper.text()).toContain("2026-08-24 10:05:00");
    expect(wrapper.get('[data-testid="bar-table"]').text()).toContain("12.00");
    expect(wrapper.get('[data-testid="bar-table"]').text()).toContain("12.20");
    expect(wrapper.get('[data-testid="overlay-table"]').text()).toContain("风险线");
    expect(wrapper.get('[data-testid="overlay-table"]').text()).toContain("11.00");
    expect(wrapper.get('[data-testid="overlay-table"]').text()).toContain("指标值");
    expect(wrapper.get('[data-testid="overlay-table"]').text()).toContain("-0.103456788 元");
    expect(wrapper.get('[data-testid="overlay-table"]').text()).not.toContain("-0.10 元");
    expect(wrapper.find('[data-testid="price-chart"]').exists()).toBe(true);
    expect(wrapper.get('[data-testid="bar-table"]').text()).toContain("2026-08-24 10:00:00");
  });

  it("shows hierarchical evidence, blockers, and missing inputs as escaped text", () => {
    const wrapper = mount(SymbolDetailView, { props: { bars, detail, events } });
    const evidence = wrapper.get('[data-testid="evidence-table"]');

    expect(evidence.text()).toContain("PRICE_IN_ZONE");
    expect(evidence.text()).toContain("MANUAL_EVENT_RISK_CLEAR");
    expect(evidence.text()).toContain("MISSING_INPUT");
    expect(evidence.text()).toContain("MANUAL_EVENT_RISK");
    expect(wrapper.text()).toContain('<img src=x onerror="globalThis.compromised=true">');
    expect(wrapper.find("img").exists()).toBe(false);
  });

  it("keeps authoritative facts visible while explicitly labelling stale state", async () => {
    const staleDetail: SymbolDetailResponse = {
      ...detail,
      summary: {
        ...detail.summary,
        connected: false,
        decision: {
          ...decision,
          dataHealth: {
            ...decision.dataHealth,
            fresh: false,
            status: "DEGRADED",
          },
        },
      },
    };
    const wrapper = mount(SymbolDetailView, {
      props: { bars, detail: staleDetail, events, stale: true },
    });
    await vi.dynamicImportSettled();
    await nextTick();

    expect(wrapper.get('[role="status"]').text()).toContain("陈旧 / 降级");
    expect(wrapper.get('[role="status"]').text()).toContain("不得视为实时");
    expect(wrapper.findAll('[data-testid="bar-row"]')).toHaveLength(2);
    expect(wrapper.get('[data-testid="price-chart"]').attributes("aria-label")).toContain("陈旧");
  });

  it("separates loading, error, and empty states without inventing data", () => {
    const loading = mount(SymbolDetailView, {
      props: { bars: [], detail: null, events: [], loading: true },
    });
    const failed = mount(SymbolDetailView, {
      props: { bars: [], detail: null, error: "详情不可用", events: [] },
    });
    const empty = mount(SymbolDetailView, {
      props: { bars: [], detail: null, events: [] },
    });

    expect(loading.get('[role="status"]').text()).toContain("加载");
    expect(loading.find('[data-testid="detail-empty"]').exists()).toBe(false);
    expect(failed.get('[role="alert"]').text()).toContain("详情不可用");
    expect(failed.find('[data-testid="detail-empty"]').exists()).toBe(false);
    expect(empty.get('[data-testid="detail-empty"]').text()).toContain("暂无个股详情");
  });

  it("labels an authoritative detail with no chart history", () => {
    const wrapper = mount(SymbolDetailView, {
      props: { bars: [], detail, events: [] },
    });

    expect(wrapper.get('[data-testid="bars-empty"]').text()).toContain("暂无 K 线数据");
    expect(wrapper.findAll('[data-testid="bar-row"]')).toHaveLength(0);
  });

  it("forwards chart ranges and timeline time selection without changing inputs", async () => {
    const originalBars = [...bars];
    const wrapper = mount(SymbolDetailView, { props: { bars, detail, events } });
    await vi.dynamicImportSettled();
    await nextTick();

    const chart = wrapper.findComponent({ name: "PriceChart" });
    expect(chart.exists()).toBe(true);
    chart.vm.$emit("rangeChange", {
      endPercent: 90,
      startPercent: 10,
    });
    await wrapper.getComponent(EpisodeTimeline).findAll("button")[0]?.trigger("click");

    expect(wrapper.emitted("rangeChange")).toEqual([[{ endPercent: 90, startPercent: 10 }]]);
    expect(wrapper.emitted("selectTime")).toEqual([[firstTime]]);
    expect(bars).toEqual(originalBars);
  });
});
