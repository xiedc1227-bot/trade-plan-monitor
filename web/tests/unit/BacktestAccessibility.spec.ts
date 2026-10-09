import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { mount } from "@vue/test-utils";
import { nextTick } from "vue";
import { afterEach, describe, expect, it } from "vitest";

import type {
  BacktestJobView,
  BacktestRunSummaryView,
  PlanVersionPage,
} from "../../src/api/generated";
import BacktestJobStatus from "../../src/components/backtests/BacktestJobStatus.vue";
import BacktestRunForm from "../../src/components/backtests/BacktestRunForm.vue";
import BacktestRunTable from "../../src/components/backtests/BacktestRunTable.vue";
import type { BacktestRunDraft } from "../../src/composables/useBacktestRunForm";

const TIME = "2026-08-30T10:00:00.000000+08:00";
const RUN_ID = "a".repeat(64);
const EMPTY_PLAN_PAGE: PlanVersionPage = {
  items: [],
  limit: 20,
  offset: 0,
  total: 0,
};

function draft(): BacktestRunDraft {
  return Object.freeze({
    endDate: "",
    responseMode: "FOLLOW_REMINDERS",
    responseDelaySeconds: "0",
    buySlippageFen: "0",
    sellSlippageFen: "0",
    researchInputJson: "",
    buySlippageBps: "1",
    commissionRate: "0.0003",
    datasetHash: "d".repeat(64),
    eventRiskAssumption: "NO_EVENT_RISK",
    initialCashFen: "10000000",
    initialLots: Object.freeze([
      Object.freeze({
        acquiredTradeDate: "2026-08-01",
        bucket: "CORE" as const,
        costBasisFen: "100000",
        draftId: "lot-draft-1",
        lotKey: "core-1",
        quantity: "100",
      }),
    ]),
    minimumCommissionFen: "500",
    planVersionId: "123e4567-e89b-42d3-a456-426614174000",
    sellSlippageBps: "1",
    stampDutyRate: "0.001",
    transferFeeRate: "0.00001",
  });
}

function job(status: BacktestJobView["status"] = "RUNNING"): BacktestJobView {
  return Object.freeze({
    attempt: 1,
    cancelRequestedAt: null,
    createdAt: TIME,
    datasetHash: null,
    errorCode: null,
    errorMessage: null,
    finishedAt: null,
    jobId: "accessibility-job-001",
    kind: "DATA_SYNC",
    progress: Object.freeze({
      completedUnits: 2,
      phase: "SYNCING_DATA",
      totalUnits: 4,
      unit: "ITEMS",
      updatedAt: TIME,
    }),
    requestHash: "b".repeat(64),
    result: null,
    reused: false,
    revision: 1,
    runId: null,
    startedAt: TIME,
    status,
    updatedAt: TIME,
  });
}

function summary(): BacktestRunSummaryView {
  return Object.freeze({
    availability: Object.freeze({
      decisionDetails: "AVAILABLE",
      equitySeries: "AVAILABLE",
      executionOutcomeDetails: "AVAILABLE",
      signalDetails: "AVAILABLE",
    }),
    completedAt: TIME,
    datasetHash: "d".repeat(64),
    eventEnd: "2026-08-29",
    eventStart: "2026-08-01",
    fillCount: 1,
    metrics: Object.freeze({
      blockedCount: 0,
      finalCashFen: "900000",
      finalEquityFen: "1100000",
      initialCashFen: "1000000",
      initialEquityFen: "1000000",
      maximumDrawdown: "0.1",
      realizedPnlFen: "100000",
      skippedCount: 0,
      totalCostFen: "100",
      totalReturn: "0.1",
      tradeCount: 1,
      turnoverFen: "100000",
      unrealizedPnlFen: "0",
      winRate: "1",
      winningSellCount: 1,
    }),
    pinned: false,
    planHash: "e".repeat(64),
    planVersionId: "123e4567-e89b-42d3-a456-426614174000",
    reportHash: "f".repeat(64),
    revision: 0,
    runId: RUN_ID,
    status: "COMPLETED",
    symbol: "000001.SZ",
  });
}

afterEach(() => {
  document.body.replaceChildren();
});

describe("BT048 cross-slice accessibility", () => {
  it("keeps an unavailable required plan selector focusable from the error summary", async () => {
    const wrapper = mount(BacktestRunForm, {
      attachTo: document.body,
      props: {
        draft: draft(),
        errorRevision: 0,
        errors: Object.freeze({ planVersionId: "请选择计划版本" }),
        planVersionError: null,
        planVersionPage: EMPTY_PLAN_PAGE,
        planVersionState: "EMPTY",
        selectedPlanVersion: null,
        submissionState: "IDLE",
      },
    });
    await wrapper.setProps({ errorRevision: 1 });
    await nextTick();

    const selector = wrapper.get<HTMLSelectElement>("#plan-version-id");
    expect(selector.attributes("disabled")).toBeUndefined();
    await wrapper.get('[data-testid="run-form-error-summary"] a').trigger("click");
    expect(document.activeElement).toBe(selector.element);
    wrapper.unmount();
  });

  it("links every form error to its field and moves focus only on explicit activation", async () => {
    const wrapper = mount(BacktestRunForm, {
      attachTo: document.body,
      props: {
        draft: draft(),
        errorRevision: 0,
        errors: Object.freeze({
          initialCashFen: "初始现金无效",
          "initialLots.lot-draft-1.quantity": "数量无效",
        }),
        planVersionError: null,
        planVersionPage: EMPTY_PLAN_PAGE,
        planVersionState: "EMPTY",
        selectedPlanVersion: null,
        submissionState: "IDLE",
      },
    });
    await wrapper.setProps({ errorRevision: 1 });
    await nextTick();

    const summaryElement = wrapper.get('[data-testid="run-form-error-summary"]');
    expect(document.activeElement).toBe(summaryElement.element);
    const links = summaryElement.findAll("a");
    expect(links.map((link) => link.attributes("href"))).toEqual([
      "#initial-cash-fen",
      "#lot-draft-1-quantity",
    ]);

    await links[1]?.trigger("click");
    expect(document.activeElement).toBe(wrapper.get("#lot-draft-1-quantity").element);
    expect(wrapper.get("#initial-cash-fen").attributes("aria-describedby")).toContain(
      "initial-cash-fen-error",
    );
    wrapper.unmount();
  });

  it("uses a native cancel dialog, contains focus, and restores a safe focus target", async () => {
    const wrapper = mount(BacktestJobStatus, {
      attachTo: document.body,
      props: {
        cancellationState: "IDLE",
        job: job(),
        requestState: "READY",
      },
    });
    const root = wrapper.get<HTMLElement>('[data-testid="backtest-job-status"]');
    const trigger = wrapper.get<HTMLButtonElement>('[data-testid="request-job-cancel"]');
    trigger.element.focus();
    await trigger.trigger("click");

    const dialog = wrapper.get("dialog");
    expect(dialog.attributes("aria-modal")).toBe("true");
    expect(document.activeElement).toBe(
      wrapper.get<HTMLButtonElement>('[data-testid="confirm-job-cancel"]').element,
    );
    await dialog.trigger("keydown", { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(
      wrapper.get<HTMLButtonElement>('[data-testid="dismiss-job-cancel"]').element,
    );

    await wrapper.setProps({ cancellationState: "SUBMITTING" });
    await nextTick();
    expect(wrapper.find("dialog").exists()).toBe(false);
    expect(document.activeElement).toBe(root.element);
    wrapper.unmount();
  });

  it("does not steal focus or change the live text for unchanged polling", async () => {
    const wrapper = mount(BacktestJobStatus, {
      attachTo: document.body,
      props: {
        cancellationState: "IDLE",
        job: job(),
        requestState: "READY",
      },
    });
    const refreshTarget = wrapper.get<HTMLButtonElement>('[data-testid="request-job-cancel"]');
    refreshTarget.element.focus();
    const live = wrapper.get('[data-testid="job-status-announcement"]');
    const initialAnnouncement = live.text();

    await wrapper.setProps({
      job: Object.freeze({
        ...job(),
        progress: Object.freeze({ ...job().progress, completedUnits: 3 }),
        revision: 2,
      }),
      requestState: "REFRESHING",
    });

    expect(document.activeElement).toBe(refreshTarget.element);
    expect(live.text()).toBe(initialAnnouncement);
    wrapper.unmount();
  });

  it("keeps fixed sort, paging, and horizontally scrollable table semantics native", async () => {
    const wrapper = mount(BacktestRunTable, {
      attachTo: document.body,
      props: {
        errorMessage: null,
        hasMore: true,
        items: [summary()],
        pageNumber: 2,
        queryState: "READY",
      },
    });

    expect(wrapper.get("caption").text()).toContain("按完成时间倒序排列");
    expect(wrapper.get("th[aria-sort]").attributes("aria-sort")).toBe("descending");
    expect(wrapper.get('[role="region"]').attributes()).toMatchObject({
      "aria-label": "回测运行记录，可横向滚动",
      tabindex: "0",
    });
    expect(wrapper.get('[data-testid="run-page-number"]').attributes("aria-current")).toBe(
      "page",
    );
    const next = wrapper.get<HTMLButtonElement>('[data-testid="next-run-page"]');
    next.element.focus();
    await next.trigger("click");
    expect(wrapper.emitted("nextPage")).toHaveLength(1);
    expect(document.activeElement).toBe(next.element);
    expect(wrapper.get('[data-testid="run-detail-link"]').attributes("href")).toBe(
      `/backtests/${RUN_ID}`,
    );
    wrapper.unmount();
  });

  it("keeps all four slices responsive, rem-sized, visibly focusable, and reduced-motion aware", () => {
    const sourcePaths = [
      resolve(process.cwd(), "src", "components", "backtests", "BacktestRunForm.vue"),
      resolve(process.cwd(), "src", "components", "backtests", "BacktestJobStatus.vue"),
      resolve(process.cwd(), "src", "components", "backtests", "BacktestRunTable.vue"),
      resolve(process.cwd(), "src", "views", "BacktestRunDetailView.vue"),
    ];
    const sources = sourcePaths.map((file) => readFileSync(file, "utf8"));

    for (const source of sources) {
      expect(source).toMatch(/@media \(max-width: 47\.9375rem\)/);
      expect(source).toMatch(/@media \(prefers-reduced-motion: reduce\)/);
      expect(source).toContain("min-height: 2.75rem");
      expect(source).toMatch(/:focus-visible/);
      expect(source).not.toMatch(/font-size:\s*\d+px/);
    }

    expect(sources[1]).toContain("dialog.showModal()");
    expect(sources[2]).toMatch(
      /\.run-table__pagination\s*\{[^}]*flex-wrap:\s*wrap;[^}]*justify-content:\s*flex-start;/s,
    );
  });
});
