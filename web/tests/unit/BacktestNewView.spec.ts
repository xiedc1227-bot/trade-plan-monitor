import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { createMemoryHistory, createRouter } from "vue-router";
import { describe, expect, it, vi } from "vitest";

import type {
  BacktestJobReceipt,
  BacktestReferenceMarketCoverageView,
  BacktestRunCommand,
} from "../../src/api/generated";
import type { BacktestApi, BacktestMutationResponse } from "../../src/api/backtests";
import { ApiClientError } from "../../src/api/transport";
import BacktestNewView from "../../src/views/BacktestNewView.vue";

const PLAN_VERSION_ID = "123e4567-e89b-42d3-a456-426614174000";
const DATASET_HASH = "a".repeat(64);
const RUN_ID = "b".repeat(64);
const JOB_ID = "backtest-job-001";

function receipt(
  overrides: Partial<BacktestJobReceipt> = {},
): BacktestJobReceipt {
  return {
    attempt: 0,
    datasetHash: DATASET_HASH,
    jobId: JOB_ID,
    kind: "BACKTEST_RUN",
    reused: false,
    revision: 0,
    runId: RUN_ID,
    status: "QUEUED",
    submittedAt: "2026-08-29T12:00:00.000000+08:00",
    ...overrides,
  };
}

function mutation(body: BacktestJobReceipt): BacktestMutationResponse<BacktestJobReceipt> {
  return {
    body,
    location: `/api/v1/backtest-jobs/${body.jobId}`,
    retryAfterSeconds: body.status === "COMPLETED" ? null : 2,
    status: 202,
  };
}

function apiWith(overrides: Partial<BacktestApi> = {}): BacktestApi {
  const unused = vi.fn(() => Promise.reject(new Error("unexpected API call")));
  return {
    cancelJob: unused,
    getDataset: unused,
    getEquitySeries: unused,
    getMarketIndexSeries: unused,
    getReferenceMarketCoverage: unused,
    getJob: unused,
    getRun: unused,
    listDatasets: unused,
    listDetails: unused,
    listFills: unused,
    listJobs: unused,
    listRuns: unused,
    pinRun: unused,
    submitRun: unused,
    syncData: unused,
    verifyDataset: unused,
    ...overrides,
  } as BacktestApi;
}

function referenceMarketCoverage(
  overrides: Partial<BacktestReferenceMarketCoverageView> = {},
): BacktestReferenceMarketCoverageView {
  return {
    availableFiveMinuteCount: 0,
    availableOfficialDayCount: 22,
    binding: {
      board: "SZSE_MAIN",
      displayName: "深证成指",
      indexCode: "399001.SZ",
      mappingVersion: "board-index-map-v1",
      selection: "AUTO_BOARD",
    },
    blockers: [],
    conditionPaths: ["entry.conditions.all[0]"],
    coverageStatus: "AVAILABLE",
    datasetHash: DATASET_HASH,
    formulaDefinitionHash: "c".repeat(64),
    indexRequirementHash: "d".repeat(64),
    marketIndexDataHash: "e".repeat(64),
    planVersionId: PLAN_VERSION_ID,
    required: true,
    requiredFiveMinuteCount: 0,
    requiredOfficialDayCount: 21,
    warmupEnd: "2026-08-28",
    warmupStart: "2026-07-01",
    ...overrides,
  };
}

function deferred<Value>() {
  let resolve!: (value: Value) => void;
  const promise = new Promise<Value>((resolver) => {
    resolve = resolver;
  });
  return { promise, resolve };
}

async function mountNewView(options: {
  api?: BacktestApi;
  beforeRunNavigation?: () => false | Promise<false | void> | void;
  createIdempotencyKey?: () => string;
} = {}) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/backtests/new", component: { template: "<div />" } },
      { path: "/backtests/:runId", component: { template: "<div />" } },
    ],
  });
  if (options.beforeRunNavigation !== undefined) {
    router.beforeEach((to) => {
      if (to.path === `/backtests/${RUN_ID}`) return options.beforeRunNavigation?.();
    });
  }
  await router.push("/backtests/new");
  await router.isReady();
  const wrapper = mount(BacktestNewView, {
    attachTo: document.body,
    global: { plugins: [router] },
    props: {
      api: options.api ?? apiWith(),
      ...(options.createIdempotencyKey === undefined
        ? {}
        : { createIdempotencyKey: options.createIdempotencyKey }),
    },
  });
  await flushPromises();
  return { router, wrapper };
}

async function fillValidBase(wrapper: VueWrapper): Promise<void> {
  await wrapper.get<HTMLInputElement>("#plan-version-id").setValue(PLAN_VERSION_ID);
  await wrapper.get<HTMLInputElement>("#dataset-hash").setValue(DATASET_HASH);
  await wrapper.get<HTMLInputElement>("#initial-cash-fen").setValue("10000000");
  await wrapper.get<HTMLInputElement>("#commission-rate").setValue("0.0003");
  await wrapper.get<HTMLInputElement>("#minimum-commission-fen").setValue("500");
  await wrapper.get<HTMLInputElement>("#stamp-duty-rate").setValue("0.001");
  await wrapper.get<HTMLInputElement>("#transfer-fee-rate").setValue("0.00001");
  await wrapper.get<HTMLInputElement>("#buy-slippage-bps").setValue("2.5");
  await wrapper.get<HTMLInputElement>("#sell-slippage-bps").setValue("3.75");
}

async function submit(wrapper: VueWrapper): Promise<void> {
  await wrapper.get('[data-testid="submit-backtest-run"]').trigger("click");
  await flushPromises();
}

describe("BacktestNewView", () => {
  it("previews only backend-resolved index binding, paths, warm-up, and coverage", async () => {
    const getReferenceMarketCoverage = vi
      .fn<BacktestApi["getReferenceMarketCoverage"]>()
      .mockResolvedValue(referenceMarketCoverage());
    const { wrapper } = await mountNewView({
      api: apiWith({ getReferenceMarketCoverage }),
    });

    await wrapper.get<HTMLInputElement>("#plan-version-id").setValue(PLAN_VERSION_ID);
    expect(getReferenceMarketCoverage).not.toHaveBeenCalled();
    await wrapper.get<HTMLInputElement>("#dataset-hash").setValue(DATASET_HASH);
    await flushPromises();

    expect(getReferenceMarketCoverage).toHaveBeenCalledWith(
      DATASET_HASH,
      PLAN_VERSION_ID,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    const panel = wrapper.get('[data-testid="reference-market-coverage"]');
    expect(panel.text()).toContain("深证成指");
    expect(panel.text()).toContain("board-index-map-v1");
    expect(panel.text()).toContain("entry.conditions.all[0]");
    expect(panel.text()).toContain("2026-07-01");
    expect(panel.text()).toContain("21 / 22");
    expect(panel.text()).not.toMatch(/强势|弱势|允许买入|禁止买入/);
    wrapper.unmount();
  });

  it("aborts a stale coverage preview and shows the newest no-index result without blocking submit", async () => {
    const first = deferred<BacktestReferenceMarketCoverageView>();
    const secondHash = "f".repeat(64);
    const getReferenceMarketCoverage = vi
      .fn<BacktestApi["getReferenceMarketCoverage"]>()
      .mockReturnValueOnce(first.promise)
      .mockResolvedValueOnce(
        referenceMarketCoverage({
          availableOfficialDayCount: 0,
          blockers: [],
          conditionPaths: [],
          coverageStatus: "NOT_REQUIRED",
          datasetHash: secondHash,
          marketIndexDataHash: null,
          required: false,
          requiredOfficialDayCount: 0,
        }),
      );
    const submitRun = vi.fn<BacktestApi["submitRun"]>().mockResolvedValue(mutation(receipt({ datasetHash: secondHash })));
    const { wrapper } = await mountNewView({
      api: apiWith({ getReferenceMarketCoverage, submitRun }),
    });
    await wrapper.get<HTMLInputElement>("#plan-version-id").setValue(PLAN_VERSION_ID);
    await wrapper.get<HTMLInputElement>("#dataset-hash").setValue(DATASET_HASH);
    await flushPromises();
    const firstSignal = getReferenceMarketCoverage.mock.calls[0]?.[2]?.signal;
    await wrapper.get<HTMLInputElement>("#dataset-hash").setValue(secondHash);
    await flushPromises();

    expect(firstSignal?.aborted).toBe(true);
    expect(wrapper.get('[data-testid="reference-market-coverage"]').text()).toContain(
      "计划未使用指数条件",
    );
    first.resolve(referenceMarketCoverage());
    await flushPromises();
    expect(wrapper.text()).not.toContain("entry.conditions.all[0]");

    await wrapper.get<HTMLInputElement>("#initial-cash-fen").setValue("10000000");
    await wrapper.get<HTMLInputElement>("#commission-rate").setValue("0.0003");
    await wrapper.get<HTMLInputElement>("#minimum-commission-fen").setValue("500");
    await wrapper.get<HTMLInputElement>("#stamp-duty-rate").setValue("0.001");
    await wrapper.get<HTMLInputElement>("#transfer-fee-rate").setValue("0.00001");
    await wrapper.get<HTMLInputElement>("#buy-slippage-bps").setValue("2.5");
    await wrapper.get<HTMLInputElement>("#sell-slippage-bps").setValue("3.75");
    await submit(wrapper);
    expect(submitRun).toHaveBeenCalledOnce();
    wrapper.unmount();
  });

  it("submits one exact generated command without decimal float conversion", async () => {
    const submitRun = vi.fn().mockResolvedValue(mutation(receipt()));
    const { wrapper } = await mountNewView({
      api: apiWith({ submitRun }),
      createIdempotencyKey: () => "run-intent-001",
    });
    await fillValidBase(wrapper);
    await submit(wrapper);

    expect(submitRun).toHaveBeenCalledWith(
      {
        datasetHash: DATASET_HASH,
        eventRiskAssumption: "NO_EVENT_RISK",
        executionConfig: {
          buySlippageBps: "2.5",
          commissionRate: "0.0003",
          minimumCommissionFen: 500,
          sellSlippageBps: "3.75",
          stampDutyRate: "0.001",
          transferFeeRate: "0.00001",
        },
        initialCashFen: 10_000_000,
        initialLots: [],
        planVersionId: PLAN_VERSION_ID,
      } satisfies BacktestRunCommand,
      "run-intent-001",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    const submitted = submitRun.mock.calls[0]?.[0];
    expect(Object.isFrozen(submitted)).toBe(true);
    expect(Object.isFrozen(submitted?.executionConfig)).toBe(true);
    expect(Object.isFrozen(submitted?.initialLots)).toBe(true);
    wrapper.unmount();
  });

  it("focuses a linked error summary and rejects unsafe or noncanonical drafts", async () => {
    const submitRun = vi.fn();
    const { wrapper } = await mountNewView({ api: apiWith({ submitRun }) });
    await fillValidBase(wrapper);
    const oversizedInteger = "9".repeat(10_000);
    const bigInt = vi.spyOn(globalThis, "BigInt");
    await wrapper
      .get<HTMLInputElement>("#initial-cash-fen")
      .setValue(oversizedInteger);
    await wrapper.get<HTMLInputElement>("#commission-rate").setValue("0.00030");
    await submit(wrapper);

    const summary = wrapper.get('[data-testid="run-form-error-summary"]');
    expect(document.activeElement).toBe(summary.element);
    expect(summary.text()).toContain("初始现金");
    expect(summary.text()).toContain("佣金率");
    expect(wrapper.get("#initial-cash-fen").attributes("aria-invalid")).toBe("true");
    expect(bigInt).not.toHaveBeenCalledWith(oversizedInteger);
    expect(submitRun).not.toHaveBeenCalled();
    bigInt.mockRestore();
    wrapper.unmount();
  });

  it("uses field-appropriate mobile input modes", async () => {
    const { wrapper } = await mountNewView();

    expect(wrapper.get("#plan-version-id").attributes("inputmode")).toBe("text");
    expect(wrapper.get("#dataset-hash").attributes("inputmode")).toBe("text");
    expect(wrapper.get("#initial-cash-fen").attributes("inputmode")).toBe("numeric");
    expect(wrapper.get("#commission-rate").attributes("inputmode")).toBe("decimal");
    wrapper.unmount();
  });

  it("preserves exact lot drafts and submits a stable generated lot shape", async () => {
    const submitRun = vi.fn().mockResolvedValue(mutation(receipt()));
    const { wrapper } = await mountNewView({ api: apiWith({ submitRun }) });
    await fillValidBase(wrapper);
    await wrapper.get('[data-testid="add-initial-lot"]').trigger("click");
    const row = wrapper.get('[data-testid="initial-lot-row"]');
    await row.get<HTMLInputElement>('[data-field="lotKey"]').setValue("core-lot-001");
    await row.get<HTMLSelectElement>('[data-field="bucket"]').setValue("CORE");
    await row
      .get<HTMLInputElement>('[data-field="acquiredTradeDate"]')
      .setValue("2026-07-31");
    await row.get<HTMLInputElement>('[data-field="quantity"]').setValue("9007199254740900");
    await row.get<HTMLInputElement>('[data-field="costBasisFen"]').setValue("91");
    await submit(wrapper);

    expect(submitRun.mock.calls[0]?.[0].initialLots).toEqual([
      {
        acquiredTradeDate: "2026-07-31",
        bucket: "CORE",
        costBasisFen: 91,
        lotKey: "core-lot-001",
        quantity: 9_007_199_254_740_900,
      },
    ]);
    wrapper.unmount();
  });

  it("caps initial-lot drafts at 200 rows", async () => {
    const { wrapper } = await mountNewView();
    const add = wrapper.get('[data-testid="add-initial-lot"]');
    for (let index = 0; index < 200; index += 1) await add.trigger("click");

    expect(wrapper.findAll('[data-testid="initial-lot-row"]')).toHaveLength(200);
    expect(add.attributes("disabled")).toBeDefined();
    await add.trigger("click");
    expect(wrapper.findAll('[data-testid="initial-lot-row"]')).toHaveLength(200);
    wrapper.unmount();
  });

  it("rejects duplicate lot keys and invalid lot shapes without copying plan rules", async () => {
    const submitRun = vi.fn();
    const { wrapper } = await mountNewView({ api: apiWith({ submitRun }) });
    await fillValidBase(wrapper);
    for (let index = 0; index < 2; index += 1) {
      await wrapper.get('[data-testid="add-initial-lot"]').trigger("click");
    }
    const rows = wrapper.findAll('[data-testid="initial-lot-row"]');
    for (const row of rows) {
      await row.get<HTMLInputElement>('[data-field="lotKey"]').setValue("duplicate-lot");
      await row
        .get<HTMLInputElement>('[data-field="acquiredTradeDate"]')
        .setValue("2026-07-31");
      await row.get<HTMLInputElement>('[data-field="quantity"]').setValue("101");
      await row.get<HTMLInputElement>('[data-field="costBasisFen"]').setValue("1000");
    }
    await submit(wrapper);

    expect(wrapper.get('[data-testid="run-form-error-summary"]').text()).toContain(
      "lotKey 不得重复",
    );
    expect(wrapper.text()).toContain("100 股整数倍");
    expect(wrapper.text()).not.toContain("T+1 校验");
    expect(submitRun).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it.each(["NETWORK_ERROR", "INVALID_RESPONSE"] as const)(
    "retries an uncertain %s outcome with the same body and key",
    async (code) => {
      const submitRun = vi
        .fn<BacktestApi["submitRun"]>()
        .mockRejectedValueOnce(new ApiClientError({ code, message: "private", status: 0 }))
        .mockResolvedValueOnce(mutation(receipt()));
      const createIdempotencyKey = vi.fn(() => "stable-run-intent");
      const { wrapper } = await mountNewView({
        api: apiWith({ submitRun }),
        createIdempotencyKey,
      });
      await fillValidBase(wrapper);
      await submit(wrapper);
      expect(wrapper.get('[role="alert"]').text()).toContain("结果尚未确认");
      expect(wrapper.text()).not.toContain("private");

      await wrapper.get('[data-testid="retry-run-submission"]').trigger("click");
      await flushPromises();
      expect(submitRun.mock.calls[1]?.[0]).toEqual(submitRun.mock.calls[0]?.[0]);
      expect(submitRun.mock.calls[1]?.[1]).toBe("stable-run-intent");
      expect(createIdempotencyKey).toHaveBeenCalledTimes(1);
      wrapper.unmount();
    },
  );

  it("creates a new semantic intent after an uncertain draft changes", async () => {
    const submitRun = vi
      .fn<BacktestApi["submitRun"]>()
      .mockRejectedValueOnce(
        new ApiClientError({ code: "NETWORK_ERROR", message: "private", status: 0 }),
      )
      .mockResolvedValueOnce(mutation(receipt()));
    const keys = ["old-run-intent", "new-run-intent"];
    const createIdempotencyKey = vi.fn(() => keys.shift() ?? "unexpected-key");
    const { wrapper } = await mountNewView({
      api: apiWith({ submitRun }),
      createIdempotencyKey,
    });
    await fillValidBase(wrapper);
    await submit(wrapper);

    await wrapper.get<HTMLInputElement>("#initial-cash-fen").setValue("10000100");
    await submit(wrapper);
    expect(submitRun.mock.calls[0]?.[1]).toBe("old-run-intent");
    expect(submitRun.mock.calls[1]?.[1]).toBe("new-run-intent");
    expect(submitRun.mock.calls[1]?.[0].initialCashFen).toBe(10_000_100);
    expect(createIdempotencyKey).toHaveBeenCalledTimes(2);
    wrapper.unmount();
  });

  it("navigates ordinary acceptance to the exact run and job URL", async () => {
    const { router, wrapper } = await mountNewView({
      api: apiWith({ submitRun: vi.fn().mockResolvedValue(mutation(receipt())) }),
    });
    await fillValidBase(wrapper);
    await submit(wrapper);

    expect(router.currentRoute.value.path).toBe(`/backtests/${RUN_ID}`);
    expect(router.currentRoute.value.query).toEqual({ jobId: JOB_ID });
    wrapper.unmount();
  });

  it("locks an accepted semantic intent until delayed navigation completes", async () => {
    const navigation = deferred<void>();
    const submitRun = vi.fn().mockResolvedValue(mutation(receipt()));
    const createIdempotencyKey = vi.fn(() => "accepted-run-intent");
    const { wrapper } = await mountNewView({
      api: apiWith({ submitRun }),
      beforeRunNavigation: () => navigation.promise,
      createIdempotencyKey,
    });
    await fillValidBase(wrapper);
    await submit(wrapper);

    const button = wrapper.get('[data-testid="submit-backtest-run"]');
    expect(button.attributes("disabled")).toBeDefined();
    await button.trigger("click");
    expect(submitRun).toHaveBeenCalledTimes(1);
    expect(createIdempotencyKey).toHaveBeenCalledTimes(1);

    navigation.resolve();
    await flushPromises();
    wrapper.unmount();
  });

  it("surfaces a resolved router navigation failure without unlocking the accepted intent", async () => {
    const submitRun = vi.fn().mockResolvedValue(mutation(receipt()));
    const { router, wrapper } = await mountNewView({
      api: apiWith({ submitRun }),
      beforeRunNavigation: () => false,
    });
    await fillValidBase(wrapper);
    await submit(wrapper);

    expect(router.currentRoute.value.path).toBe("/backtests/new");
    expect(wrapper.get('[role="alert"]').text()).toContain("无法打开结果页");
    expect(wrapper.get('[data-testid="submit-backtest-run"]').attributes("disabled")).toBeDefined();
    await wrapper.get('[data-testid="submit-backtest-run"]').trigger("click");
    expect(submitRun).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });

  it("skips job polling for immediately completed reuse", async () => {
    const getJob = vi.fn();
    const { router, wrapper } = await mountNewView({
      api: apiWith({
        getJob,
        submitRun: vi.fn().mockResolvedValue(
          mutation(
            receipt({
              attempt: 1,
              reused: true,
              revision: 1,
              status: "COMPLETED",
            }),
          ),
        ),
      }),
    });
    await fillValidBase(wrapper);
    await submit(wrapper);

    expect(router.currentRoute.value.path).toBe(`/backtests/${RUN_ID}`);
    expect(router.currentRoute.value.query).toEqual({});
    expect(getJob).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("coalesces duplicate clicks and aborts one pending submission on unmount", async () => {
    const pending = deferred<BacktestMutationResponse<BacktestJobReceipt>>();
    const submitRun = vi.fn<BacktestApi["submitRun"]>().mockReturnValue(pending.promise);
    const { wrapper } = await mountNewView({ api: apiWith({ submitRun }) });
    await fillValidBase(wrapper);
    const button = wrapper.get('[data-testid="submit-backtest-run"]');
    await button.trigger("click");
    await button.trigger("click");
    expect(submitRun).toHaveBeenCalledTimes(1);
    const signal = submitRun.mock.calls[0]?.[2]?.signal;

    wrapper.unmount();
    expect(signal?.aborted).toBe(true);
    pending.resolve(mutation(receipt()));
  });
});
