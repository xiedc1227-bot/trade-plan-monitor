import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { mount } from "@vue/test-utils";
import { afterEach, describe, expect, it } from "vitest";

import type { RuntimeHealthResponse } from "../../src/api/generated";
import HealthMatrix from "../../src/components/health/HealthMatrix.vue";
import MarketStatusStrip from "../../src/components/health/MarketStatusStrip.vue";
import SystemView from "../../src/views/SystemView.vue";

const health: RuntimeHealthResponse = {
  cooldownUntil: "2026-08-24T10:05:00+08:00",
  database: {
    errorCode: null,
    lastBackupAt: "2026-08-24T08:00:00+08:00",
    lastCheckpointAt: "2026-08-24T09:50:00+08:00",
    status: "READY",
    walStatus: "READY",
  },
  delivery: {
    errorCode: "WEBHOOK_TRANSIENT",
    failedCount: 1,
    lastDeliveredAt: "2026-08-24T09:54:00+08:00",
    nextRetryAt: "2026-08-24T10:01:00+08:00",
    pendingCount: 2,
    status: "DEGRADED",
  },
  executor: {
    activeCount: 1,
    maxWorkers: 2,
    waitingCount: 3,
  },
  gaps: [
    { barEnd: "2026-08-24T09:58:00+08:00", symbol: "600000.SH" },
    { barEnd: "2026-08-24T09:59:00+08:00", symbol: "600519.SH" },
  ],
  lastCompletedMinute: "2026-08-24T09:59:00+08:00",
  lastCompletedMinuteAgeSeconds: 60,
  latestEvaluationAgeSeconds: 300,
  latestEvaluationAt: "2026-08-24T09:55:00+08:00",
  nextPollAt: "2026-08-24T10:00:12+08:00",
  nextRetryAt: "2026-08-24T10:01:00+08:00",
  observedAt: "2026-08-24T10:00:00+08:00",
  providers: [
    {
      capability: "realtime_minutes",
      checkedAt: "2026-08-24T09:59:00+08:00",
      errorCode: "RATE_LIMITED",
      latencyMs: 125,
      nextRetryAt: "2026-08-24T10:01:00+08:00",
      status: "RATE_LIMITED",
    },
    {
      capability: "daily_bars",
      checkedAt: "2026-08-24T09:58:00+08:00",
      errorCode: null,
      latencyMs: 42,
      nextRetryAt: null,
      status: "READY",
    },
  ],
  readOnly: true,
  startedAt: "2026-08-24T09:00:00+08:00",
  status: "DEGRADED",
  stoppedAt: null,
};

function mountSystem(
  props: Partial<InstanceType<typeof SystemView>["$props"]> = {},
) {
  return mount(SystemView, {
    attachTo: document.body,
    props: {
      health,
      ...props,
    },
  });
}

afterEach(() => {
  document.body.replaceChildren();
});

describe("SystemView", () => {
  it("renders backend-authored lifecycle, polling, cooldown, and age facts", () => {
    const wrapper = mountSystem();
    const strip = wrapper.get('[data-testid="market-status-strip"]');

    expect(strip.text()).toContain("降级");
    expect(strip.text()).toContain("只读");
    expect(strip.text()).toContain("2026-08-24 10:00:00");
    expect(strip.text()).toContain("启动时间 2026-08-24 09:00:00");
    expect(strip.text()).toContain("停止时间 —");
    expect(strip.text()).toContain("最后分钟时点 2026-08-24 09:59:00");
    expect(strip.text()).toContain("最后分钟 60 秒前");
    expect(strip.text()).toContain("最近判断时点 2026-08-24 09:55:00");
    expect(strip.text()).toContain("最近判断 300 秒前");
    expect(strip.text()).toContain("下次轮询 2026-08-24 10:00:12");
    expect(strip.text()).toContain("下次重试 2026-08-24 10:01:00");
    expect(strip.text()).toContain("冷却至 2026-08-24 10:05:00");
  });

  it("renders capability status, latency, observation, retry, and safe error codes", () => {
    const wrapper = mountSystem();
    const rows = wrapper.findAll('[data-testid="provider-health-row"]');

    expect(rows).toHaveLength(2);
    expect(rows[0]?.text()).toContain("realtime_minutes");
    expect(rows[0]?.text()).toContain("限流");
    expect(rows[0]?.text()).toContain("◆");
    expect(rows[0]?.text()).toContain("125 毫秒");
    expect(rows[0]?.text()).toContain("RATE_LIMITED");
    expect(rows[0]?.text()).toContain("2026-08-24 10:01:00");
    expect(rows[1]?.text()).toContain("就绪");
    expect(rows[1]?.text()).toContain("●");
  });

  it("renders executor, database, WAL, checkpoint, backup, and delivery diagnostics", () => {
    const wrapper = mountSystem();

    expect(wrapper.get('[data-testid="executor-health"]').text()).toContain("活动 1 / 2");
    expect(wrapper.get('[data-testid="executor-health"]').text()).toContain("等待 3");
    expect(wrapper.get('[data-testid="database-health"]').text()).toContain("数据库 就绪");
    expect(wrapper.get('[data-testid="database-health"]').text()).toContain("WAL 就绪");
    expect(wrapper.get('[data-testid="database-health"]').text()).toContain(
      "2026-08-24 09:50:00",
    );
    expect(wrapper.get('[data-testid="database-health"]').text()).toContain(
      "2026-08-24 08:00:00",
    );
    expect(wrapper.get('[data-testid="delivery-health"]').text()).toContain("待投递 2");
    expect(wrapper.get('[data-testid="delivery-health"]').text()).toContain("失败 1");
    expect(wrapper.get('[data-testid="delivery-health"]').text()).toContain(
      "WEBHOOK_TRANSIENT",
    );
  });

  it("owns database and WAL visual status independently", () => {
    const wrapper = mountSystem({
      health: {
        ...health,
        database: {
          ...health.database,
          errorCode: "WAL_WRITE_FAILED",
          status: "READY",
          walStatus: "ERROR",
        },
      },
    });

    expect(wrapper.get('[data-testid="database-status-marker"]').attributes("data-status")).toBe(
      "READY",
    );
    expect(wrapper.get('[data-testid="wal-status-marker"]').attributes("data-status")).toBe(
      "ERROR",
    );
    expect(wrapper.get('[data-testid="database-health"]').text()).toContain("数据库 就绪");
    expect(wrapper.get('[data-testid="database-health"]').text()).toContain("WAL 错误");
  });

  it("renders gap identities as native links and emits symbol selection", async () => {
    const wrapper = mountSystem();
    const links = wrapper.findAll<HTMLAnchorElement>('[data-testid="health-gap-link"]');

    expect(links).toHaveLength(2);
    expect(links[0]?.attributes("href")).toBe("/stocks/600000.SH");
    expect(links[0]?.text()).toContain("600000.SH");
    expect(links[0]?.element.closest("tr")?.textContent).toContain(
      "2026-08-24 09:58:00",
    );
    links[0]?.element.focus();
    expect(document.activeElement).toBe(links[0]?.element);
    await links[0]?.trigger("click");

    expect(wrapper.emitted("selectSymbol")).toEqual([["600000.SH"]]);
  });

  it("keeps loading, unavailable, error, and cached-health states distinct", async () => {
    const loading = mountSystem({ health: null, loading: true });
    expect(loading.get('[role="status"]').text()).toContain("正在读取系统健康状态");
    expect(loading.find('[data-testid="system-empty"]').exists()).toBe(false);
    loading.unmount();

    const empty = mountSystem({ health: null });
    expect(empty.get('[data-testid="system-empty"]').text()).toContain("尚无系统健康快照");
    empty.unmount();

    const failed = mountSystem({ error: "raw provider authorization failure", health: null });
    expect(failed.get('[role="alert"]').text()).toContain("系统健康状态暂不可用");
    expect(failed.text()).not.toContain("raw provider authorization failure");
    failed.unmount();

    const cached = mountSystem({ error: "another raw failure" });
    expect(cached.get('[role="alert"]').text()).toContain("显示上一次安全快照");
    expect(cached.find('[data-testid="health-matrix"]').exists()).toBe(true);
    expect(cached.text()).not.toContain("another raw failure");
    await cached.get('[data-testid="refresh-system-health"]').trigger("click");
    expect(cached.emitted("refresh")).toHaveLength(1);
  });

  it("renders explicit provider and gap empty states inside an available snapshot", () => {
    const wrapper = mountSystem({
      health: { ...health, gaps: [], providers: [] },
    });

    expect(wrapper.get('[data-testid="providers-empty"]').text()).toContain("尚无能力探测结果");
    expect(wrapper.get('[data-testid="gaps-empty"]').text()).toContain("未报告分钟缺口");
    expect(wrapper.find('[data-testid="system-empty"]').exists()).toBe(false);
  });

  it("does not expose unexpected secrets, raw errors, unsafe codes, or HTML", () => {
    const secret = "sk-never-render-this-value";
    const hostile = '<img src=x onerror="globalThis.compromised=true">';
    const unsafeHealth = {
      ...health,
      database: {
        ...health.database,
        errorCode: `Authorization Bearer ${secret}`,
        rawError: hostile,
      },
      delivery: {
        ...health.delivery,
        errorCode: hostile,
      },
      providers: [
        {
          ...health.providers?.[0],
          errorCode: `token=${secret}`,
          rawProviderBody: secret,
        },
      ],
      token: secret,
    } as unknown as RuntimeHealthResponse;
    const wrapper = mountSystem({ health: unsafeHealth });

    expect(wrapper.text()).not.toContain(secret);
    expect(wrapper.text()).not.toContain(hostile);
    expect(wrapper.text()).toContain("已脱敏");
    expect(wrapper.find("img").exists()).toBe(false);
    expect(wrapper.html()).not.toContain("rawProviderBody");
  });

  it("uses polite live regions and semantic markers instead of color alone", () => {
    const wrapper = mountSystem();
    const strip = wrapper.get('[data-testid="market-status-strip"]');

    expect(strip.attributes("role")).toBe("status");
    expect(strip.attributes("aria-live")).toBe("polite");
    expect(strip.attributes("aria-atomic")).toBe("true");
    expect(strip.attributes("data-status")).toBe("DEGRADED");
    expect(strip.text()).toContain("▲");
    expect(wrapper.findAll("table")).toHaveLength(2);
    expect(wrapper.findAll("caption").map((caption) => caption.text())).toEqual([
      "Tushare 能力健康",
      "分钟数据缺口",
    ]);
  });

  it("keeps input records immutable", async () => {
    const originalProviders = health.providers;
    const originalGaps = health.gaps;
    const wrapper = mountSystem();

    await wrapper.get('[data-testid="refresh-system-health"]').trigger("click");

    expect(health.providers).toBe(originalProviders);
    expect(health.gaps).toBe(originalGaps);
    expect(health.providers?.[0]?.status).toBe("RATE_LIMITED");
  });

  it("defines responsive, reduced-motion, focus, and contrast-state hooks", () => {
    const sources = [
      "src/views/SystemView.vue",
      "src/components/health/MarketStatusStrip.vue",
      "src/components/health/HealthMatrix.vue",
    ]
      .map((file) => readFileSync(resolve(process.cwd(), file), "utf8"))
      .join("\n");

    expect(sources).toMatch(/@media\s*\(min-width:\s*20rem\)/);
    expect(sources).toMatch(/@media\s*\(min-width:\s*48rem\)/);
    expect(sources).toMatch(/@media\s*\(min-width:\s*64rem\)/);
    expect(sources).toMatch(/@media\s*\(min-width:\s*90rem\)/);
    expect(sources).toMatch(/@media\s*\(prefers-reduced-motion:\s*reduce\)/);
    expect(sources).toMatch(/:focus-visible/);
    expect(sources).toMatch(/data-status/);
    expect(sources).toMatch(/var\(--color-text-mineral\)/);
  });
});

describe("health presentation components", () => {
  it("emits only explicit strip and matrix intents", async () => {
    const strip = mount(MarketStatusStrip, {
      props: { health, showDetailsAction: true },
    });
    await strip.get('[data-testid="open-system-health"]').trigger("click");
    expect(strip.emitted("openSystem")).toHaveLength(1);

    const matrix = mount(HealthMatrix, { props: { health } });
    await matrix.get('[data-testid="health-gap-link"]').trigger("click");
    expect(matrix.emitted("selectSymbol")).toEqual([["600000.SH"]]);
  });
});
