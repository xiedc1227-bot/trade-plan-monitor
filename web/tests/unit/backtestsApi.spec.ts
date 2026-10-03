import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it, vi } from "vitest";

import { buildBacktestExportHref, createBacktestApi } from "../../src/api/backtests";
import { ApiClientError } from "../../src/api/transport";

const HASH = "a".repeat(64);
const DATASET_HASH = "b".repeat(64);
const JOB_ID = "job-data-001";
const TIME = "2026-08-28T10:00:00.000000+08:00";
const LATER_TIME = "2026-08-28T10:01:00.000000+08:00";
const CURSOR = "anchor.signature";
const REPORT_HASH = "c".repeat(64);
const PLAN_HASH = "d".repeat(64);
const RESULT_HASH = "e".repeat(64);
const CONFIG_HASH = "f".repeat(64);
const PLAN_VERSION_ID = "123e4567-e89b-42d3-a456-426614174000";

function scope() {
  return {
    adjustmentPolicy: "NONE" as const,
    end: "2026-08-02",
    historicalProfile: "TUSHARE_STK_MINS_241_END_V1" as const,
    start: "2026-08-01",
    symbols: ["000001.SZ", "600000.SH"],
    warmupStart: "2026-07-01",
  };
}

function coverage() {
  return {
    blockers: [] as string[],
    calendarRowCount: 4,
    dailyBarRowCount: 4,
    dailyLimitRowCount: 4,
    minuteBarCount: 968,
    minuteDayCount: 4,
    symbolCount: 2,
    tradingDayCount: 2,
  };
}

function dataset(datasetHash = DATASET_HASH) {
  return {
    coverage: coverage(),
    createdAt: TIME,
    datasetHash,
    schemaVersion: "backtest-dataset-v1" as const,
    scope: scope(),
    verifiedAt: LATER_TIME,
  };
}

function datasetPage() {
  return {
    filters: {
      adjustmentPolicy: "NONE" as const,
      endOnOrBefore: "2026-08-02",
      historicalProfile: "TUSHARE_STK_MINS_241_END_V1" as const,
      startOnOrAfter: "2026-08-01",
      symbol: "000001.SZ",
    },
    hasMore: false,
    highWatermark: CURSOR,
    items: [dataset()],
    limit: 20,
    nextCursor: null,
  };
}

function queuedJob(attempt = 0) {
  return {
    attempt,
    cancelRequestedAt: null,
    createdAt: TIME,
    datasetHash: null,
    errorCode: null,
    errorMessage: null,
    finishedAt: null,
    jobId: JOB_ID,
    kind: "DATA_SYNC" as const,
    progress: {
      completedUnits: 0,
      phase: "QUEUED" as const,
      totalUnits: 1,
      unit: "ITEMS" as const,
      updatedAt: TIME,
    },
    requestHash: HASH,
    result: null,
    reused: false,
    revision: 0,
    runId: null,
    startedAt: null,
    status: "QUEUED" as const,
    updatedAt: TIME,
  };
}

function cancelledJob() {
  return {
    ...queuedJob(),
    cancelRequestedAt: TIME,
    errorCode: "BACKTEST_OPERATION_CANCELLED",
    errorMessage: "The job was cancelled.",
    finishedAt: TIME,
    progress: { ...queuedJob().progress, phase: "TERMINAL" as const },
    status: "CANCELLED" as const,
  };
}

function runningJob(attempt = 2) {
  return {
    ...queuedJob(),
    attempt,
    progress: { ...queuedJob().progress, phase: "SYNCING_DATA" as const },
    revision: attempt,
    startedAt: TIME,
    status: "RUNNING" as const,
  };
}

function completedJob(kind: "DATA_SYNC" | "DATASET_VERIFY" | "BACKTEST_RUN") {
  const result =
    kind === "DATA_SYNC"
      ? {
          calendarRows: 4,
          dailyBarRows: 4,
          dailyLimitRows: 4,
          kind,
          minuteDays: 4,
          networkCalls: 0,
        }
      : kind === "DATASET_VERIFY"
        ? {
            blockers: [] as string[],
            coverage: coverage(),
            datasetHash: DATASET_HASH,
            kind,
            ready: true,
          }
        : {
            kind,
            reportHash: "c".repeat(64),
            reused: false,
            runId: HASH,
          };
  return {
    ...runningJob(1),
    datasetHash: kind === "DATA_SYNC" ? null : DATASET_HASH,
    finishedAt: LATER_TIME,
    kind,
    progress: {
      ...runningJob(1).progress,
      completedUnits: 1,
      phase: "TERMINAL" as const,
      updatedAt: LATER_TIME,
    },
    result,
    runId: kind === "BACKTEST_RUN" ? HASH : null,
    status: "COMPLETED" as const,
    updatedAt: LATER_TIME,
  };
}

function receipt(kind: "DATA_SYNC" | "DATASET_VERIFY" = "DATA_SYNC") {
  return {
    attempt: 0,
    datasetHash: null,
    jobId: JOB_ID,
    kind,
    reused: false,
    revision: 0,
    runId: null,
    status: "QUEUED" as const,
    submittedAt: TIME,
  };
}

function jobPage() {
  return {
    filters: {
      createdFrom: TIME,
      createdTo: LATER_TIME,
      datasetHash: null,
      kind: ["DATA_SYNC" as const],
      runId: null,
      status: ["QUEUED" as const],
    },
    hasMore: false,
    highWatermark: CURSOR,
    items: [queuedJob()],
    limit: 20,
    nextCursor: null,
  };
}

function jsonResponse(
  body: unknown,
  status = 200,
  headers: HeadersInit = {},
): Response {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json", ...headers },
    status,
  });
}

describe("backtest API jobs and datasets", () => {
  it("uses generated list/get contracts, canonical queries, abort signals, and deep freezing", async () => {
    const controller = new AbortController();
    const fetchImplementation = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(jobPage()))
      .mockResolvedValueOnce(jsonResponse(runningJob()))
      .mockResolvedValueOnce(jsonResponse(datasetPage()))
      .mockResolvedValueOnce(jsonResponse(dataset()));
    const api = createBacktestApi(fetchImplementation);

    const jobs = await api.listJobs(
      {
        createdFrom: "2026-08-28T10:00:00+08:00",
        createdTo: LATER_TIME,
        kind: ["DATA_SYNC", "DATA_SYNC"],
        limit: 20,
        status: ["QUEUED"],
      },
      { signal: controller.signal },
    );
    const job = await api.getJob(JOB_ID);
    const datasets = await api.listDatasets({
      adjustmentPolicy: "NONE",
      endOnOrBefore: "2026-08-02",
      historicalProfile: "TUSHARE_STK_MINS_241_END_V1",
      limit: 20,
      startOnOrAfter: "2026-08-01",
      symbol: "000001.SZ",
    });
    const item = await api.getDataset(DATASET_HASH);

    expect(fetchImplementation.mock.calls[0]?.[0]).toBe(
      "/api/v1/backtest-jobs?kind=DATA_SYNC&status=QUEUED&createdFrom=2026-08-28T10%3A00%3A00.000000%2B08%3A00&createdTo=2026-08-28T10%3A01%3A00.000000%2B08%3A00&limit=20",
    );
    expect(fetchImplementation.mock.calls[0]?.[1]).toMatchObject({
      method: "GET",
      signal: controller.signal,
    });
    expect(fetchImplementation.mock.calls[1]?.[0]).toBe(`/api/v1/backtest-jobs/${JOB_ID}`);
    expect(fetchImplementation.mock.calls[2]?.[0]).toBe(
      "/api/v1/backtest-datasets?symbol=000001.SZ&startOnOrAfter=2026-08-01&endOnOrBefore=2026-08-02&historicalProfile=TUSHARE_STK_MINS_241_END_V1&adjustmentPolicy=NONE&limit=20",
    );
    expect(fetchImplementation.mock.calls[3]?.[0]).toBe(
      `/api/v1/backtest-datasets/${DATASET_HASH}`,
    );
    expect(job.attempt).toBe(2);
    expect(Object.isFrozen(jobs)).toBe(true);
    expect(Object.isFrozen(jobs.items)).toBe(true);
    expect(Object.isFrozen(job.progress)).toBe(true);
    expect(Object.isFrozen(datasets.items[0]?.scope.symbols)).toBe(true);
    expect(Object.isFrozen(item.coverage)).toBe(true);
  });

  it.each(["DATA_SYNC", "DATASET_VERIFY", "BACKTEST_RUN"] as const)(
    "accepts and freezes the closed %s completed-result discriminator",
    async (kind) => {
      const api = createBacktestApi(async () => jsonResponse(completedJob(kind)));

      const job = await api.getJob(JOB_ID);

      expect(job.result?.kind).toBe(kind);
      expect(Object.isFrozen(job.result)).toBe(true);
    },
  );

  it("submits only closed commands and preserves exact active response metadata", async () => {
    const fetchImplementation = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse(receipt(), 202, {
          Location: `/api/v1/backtest-jobs/${JOB_ID}`,
          "Retry-After": "2",
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse(receipt("DATASET_VERIFY"), 202, {
          Location: `/api/v1/backtest-jobs/${JOB_ID}`,
          "Retry-After": "2",
        }),
      );
    const api = createBacktestApi(fetchImplementation);

    const sync = await api.syncData(
      {
        allowNetwork: true,
        refresh: false,
        scope: { ...scope(), symbols: ["600000.SH", "000001.SZ"] },
      },
      "sync-intent-001",
    );
    const verify = await api.verifyDataset({ scope: scope() }, "verify-intent-001");

    expect(fetchImplementation.mock.calls[0]?.[0]).toBe("/api/v1/backtest-data-syncs");
    expect(fetchImplementation.mock.calls[0]?.[1]).toMatchObject({
      body: JSON.stringify({ allowNetwork: true, refresh: false, scope: scope() }),
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "Idempotency-Key": "sync-intent-001",
      },
      method: "POST",
    });
    expect(fetchImplementation.mock.calls[1]?.[0]).toBe(
      "/api/v1/backtest-dataset-verifications",
    );
    expect(sync).toEqual({
      body: receipt(),
      location: `/api/v1/backtest-jobs/${JOB_ID}`,
      retryAfterSeconds: 2,
      status: 202,
    });
    expect(verify.body.kind).toBe("DATASET_VERIFY");
    expect(Object.isFrozen(sync)).toBe(true);
  });

  it("preserves terminal submission and cancellation status/header matrices", async () => {
    const completedReceipt = {
      ...receipt(),
      attempt: 1,
      revision: 1,
      status: "COMPLETED" as const,
    };
    const fetchImplementation = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse(completedReceipt, 202, {
          Location: `/api/v1/backtest-jobs/${JOB_ID}`,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(cancelledJob(), 200));
    const api = createBacktestApi(fetchImplementation);

    const terminal = await api.syncData(
      { allowNetwork: true, refresh: false, scope: scope() },
      "sync-intent-002",
    );
    const cancelled = await api.cancelJob({ jobId: JOB_ID }, "cancel-intent-001");

    expect(terminal.retryAfterSeconds).toBeNull();
    expect(cancelled).toEqual({
      body: cancelledJob(),
      location: null,
      retryAfterSeconds: null,
      status: 200,
    });
  });

  it.each([
    ["job kind", { ...queuedJob(), kind: "UNKNOWN" }],
    ["job status", { ...queuedJob(), status: "UNKNOWN" }],
    [
      "job kind/phase",
      {
        ...queuedJob(),
        kind: "DATASET_VERIFY",
        progress: { ...queuedJob().progress, phase: "SYNCING_DATA" },
      },
    ],
    ["job attempt generation", queuedJob(1)],
    ["job response time", { ...queuedJob(), createdAt: "2026-08-28T02:00:00Z" }],
    [
      "job progress count",
      { ...queuedJob(), progress: { ...queuedJob().progress, completedUnits: 2 } },
    ],
    [
      "job progress phase",
      { ...queuedJob(), progress: { ...queuedJob().progress, phase: "UNKNOWN" } },
    ],
    [
      "job progress unit",
      { ...queuedJob(), progress: { ...queuedJob().progress, unit: "BYTES" } },
    ],
    [
      "job result discriminator",
      { ...completedJob("DATA_SYNC"), result: { kind: "UNKNOWN" } },
    ],
    ["job private field", { ...queuedJob(), providerPayload: { code: 0 } }],
  ])("rejects contradictory %s records before exposure", async (_name, body) => {
    const api = createBacktestApi(async () => jsonResponse(body));

    await expect(api.getJob(JOB_ID)).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
      status: 200,
    });
  });

  it.each([
    [
      "scope count",
      { ...dataset(), coverage: { ...coverage(), symbolCount: 1 } },
    ],
    ["dataset chronology", { ...dataset(), createdAt: "2026-08-28T10:02:00.000000+08:00" }],
    ["dataset response time", { ...dataset(), verifiedAt: "2026-08-28T10:01:00+08:00" }],
    ["dataset schema", { ...dataset(), schemaVersion: "backtest-dataset-v3" }],
    [
      "dataset profile",
      { ...dataset(), scope: { ...scope(), historicalProfile: "OTHER" } },
    ],
    [
      "dataset adjustment",
      { ...dataset(), scope: { ...scope(), adjustmentPolicy: "FORWARD" } },
    ],
    ["dataset private field", { ...dataset(), artifactPath: "C:/private/data" }],
  ])("rejects contradictory %s datasets before exposure", async (_name, body) => {
    const api = createBacktestApi(async () => jsonResponse(body));

    await expect(api.getDataset(DATASET_HASH)).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
      status: 200,
    });
  });

  it.each([
    ["filter echo", { ...jobPage(), filters: { ...jobPage().filters, status: ["RUNNING"] } }],
    ["duplicate position", { ...jobPage(), items: [queuedJob(), queuedJob()] }],
    ["cursor state", { ...jobPage(), hasMore: true, nextCursor: null }],
    ["limit", { ...jobPage(), limit: 0 }],
    ["item count", { ...jobPage(), items: Array.from({ length: 101 }, queuedJob) }],
  ])("rejects contradictory job-page %s boundaries", async (_name, body) => {
    const api = createBacktestApi(async () => jsonResponse(body));

    await expect(
      api.listJobs({
        createdFrom: TIME,
        createdTo: LATER_TIME,
        kind: ["DATA_SYNC"],
        limit: 20,
        status: ["QUEUED"],
      }),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 200 });
  });

  it.each([
    [
      "filter echo",
      { ...datasetPage(), filters: { ...datasetPage().filters, symbol: "600001.SH" } },
    ],
    ["duplicate position", { ...datasetPage(), items: [dataset(), dataset()] }],
    ["cursor state", { ...datasetPage(), hasMore: true, nextCursor: null }],
    ["limit", { ...datasetPage(), limit: 101 }],
    ["item count", { ...datasetPage(), items: Array.from({ length: 101 }, dataset) }],
  ])("rejects contradictory dataset-page %s boundaries", async (_name, body) => {
    const api = createBacktestApi(async () => jsonResponse(body));

    await expect(
      api.listDatasets({
        adjustmentPolicy: "NONE",
        endOnOrBefore: "2026-08-02",
        historicalProfile: "TUSHARE_STK_MINS_241_END_V1",
        limit: 20,
        startOnOrAfter: "2026-08-01",
        symbol: "000001.SZ",
      }),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 200 });
  });

  it("rejects mismatched mutation headers and discriminators", async () => {
    const api = createBacktestApi(async () =>
      jsonResponse(receipt("DATASET_VERIFY"), 202, {
        Location: "/api/v1/backtest-jobs/wrong-job",
        "Retry-After": "1",
      }),
    );

    await expect(
      api.syncData(
        { allowNetwork: true, refresh: false, scope: scope() },
        "sync-intent-003",
      ),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 202 });
  });

  it("rejects an otherwise valid body returned under the wrong success status", async () => {
    const api = createBacktestApi(async () => jsonResponse(queuedJob(), 201));

    await expect(api.getJob(JOB_ID)).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
      status: 201,
    });
  });

  it("preserves the active cancellation status and polling headers", async () => {
    const cancelRequested = {
      ...runningJob(),
      cancelRequestedAt: TIME,
      status: "CANCEL_REQUESTED" as const,
    };
    const api = createBacktestApi(async () =>
      jsonResponse(cancelRequested, 202, {
        Location: `/api/v1/backtest-jobs/${JOB_ID}`,
        "Retry-After": "2",
      }),
    );

    await expect(
      api.cancelJob({ jobId: JOB_ID }, "cancel-intent-002"),
    ).resolves.toEqual({
      body: cancelRequested,
      location: `/api/v1/backtest-jobs/${JOB_ID}`,
      retryAfterSeconds: 2,
      status: 202,
    });
  });

  it("serializes cancellation from a fresh closed command instead of inherited toJSON", async () => {
    const inherited = {
      toJSON: () => ({ jobId: "different-job", providerToken: "private-value" }),
    };
    const command = Object.assign(Object.create(inherited) as object, { jobId: JOB_ID });
    const fetchImplementation = vi.fn<typeof fetch>(async (_input, init) => {
      expect(init?.body).toBe(JSON.stringify({ jobId: JOB_ID }));
      return jsonResponse(cancelledJob(), 200);
    });
    const api = createBacktestApi(fetchImplementation);

    await expect(api.cancelJob(command, "cancel-intent-003")).resolves.toMatchObject({
      status: 200,
    });
  });

  it("rejects malformed request identities and query values before transport", async () => {
    const fetchImplementation = vi.fn<typeof fetch>();
    const api = createBacktestApi(fetchImplementation);

    await expect(api.getJob("../private")).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
      status: 0,
    });
    await expect(api.getDataset("A".repeat(64))).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
      status: 0,
    });
    await expect(
      api.cancelJob({ jobId: JOB_ID }, "bad key"),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 0 });
    await expect(
      api.listJobs({ createdFrom: "2026-08-28T02:00:00Z" }),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 0 });
    expect(fetchImplementation).not.toHaveBeenCalled();
  });

  it("preserves typed shared-transport errors and abort forwarding", async () => {
    const controller = new AbortController();
    const fetchImplementation = vi.fn<typeof fetch>(async (_input, init) => {
      expect(init?.signal).toBe(controller.signal);
      throw Object.assign(new Error("private abort context"), { name: "AbortError" });
    });
    const api = createBacktestApi(fetchImplementation);

    try {
      await api.getJob(JOB_ID, { signal: controller.signal });
      throw new Error("expected request to fail");
    } catch (error) {
      expect(error).toBeInstanceOf(ApiClientError);
      expect(error).toMatchObject({ code: "NETWORK_ERROR", status: 0 });
      expect(String(error)).not.toContain("private abort context");
    }
  });

  it("preserves the shared fixed-copy API error contract", async () => {
    const rawMessage = "private provider context";
    const api = createBacktestApi(async () =>
      jsonResponse(
        {
          error: {
            code: "CONFLICT",
            details: [],
            message: rawMessage,
            requestId: "1".repeat(32),
          },
        },
        409,
      ),
    );

    try {
      await api.getJob(JOB_ID);
      throw new Error("expected request to fail");
    } catch (error) {
      expect(error).toMatchObject({
        code: "CONFLICT",
        details: [],
        message: "请求与当前状态冲突",
        requestId: "1".repeat(32),
        status: 409,
      });
      expect(String(error)).not.toContain(rawMessage);
    }
  });

  it("keeps generated fields and the shared transport as the sole adapter boundaries", () => {
    const source = readFileSync(resolve(process.cwd(), "src/api/backtests.ts"), "utf8");

    expect(source).toContain('from "./generated"');
    expect(source).toContain('from "./transport"');
    expect(source).not.toMatch(/\binterface\s+Backtest(?:Job|Dataset|DataSync)/);
    expect(source).not.toMatch(/JSON\.parse|TextDecoder|getReader|safeErrorMessages/);
    expect(source).not.toMatch(/\bfetch\s*\(/);
  });
});

function resultAvailability(
  availability: "AVAILABLE" | "EXPIRED" | "NOT_RECORDED" = "AVAILABLE",
) {
  return {
    decisionDetails: availability,
    equitySeries: availability,
    executionOutcomeDetails: availability,
    signalDetails: availability,
  };
}

function runMetrics() {
  return {
    blockedCount: 0,
    finalCashFen: "95000",
    finalEquityFen: "110000",
    initialCashFen: "100000",
    initialEquityFen: "100000",
    maximumDrawdown: "0.05",
    realizedPnlFen: "5000",
    skippedCount: 0,
    totalCostFen: "100",
    totalReturn: "0.1",
    tradeCount: 1,
    turnoverFen: "1000",
    unrealizedPnlFen: "5000",
    winRate: "1",
    winningSellCount: 1,
  };
}

function runSummary(runId = HASH) {
  return {
    availability: resultAvailability(),
    completedAt: LATER_TIME,
    datasetHash: DATASET_HASH,
    eventEnd: "2026-08-02",
    eventStart: "2026-08-01",
    fillCount: 1,
    metrics: runMetrics(),
    pinned: false,
    planHash: PLAN_HASH,
    planVersionId: PLAN_VERSION_ID,
    reportHash: REPORT_HASH,
    revision: 2,
    runId,
    status: "COMPLETED" as const,
    symbol: "000001.SZ",
  };
}

function runView(runId = HASH) {
  return {
    ...runSummary(runId),
    assumptions: {
      eventRiskAssumption: "NO_EVENT_RISK" as const,
      executionConfig: {
        buySlippageBps: "1",
        commissionRate: "0.0003",
        minimumCommissionFen: "500",
        sellSlippageBps: "1",
        stampDutyRate: "0.001",
        transferFeeRate: "0.00001",
      },
      executionConfigHash: CONFIG_HASH,
      historicalProfile: "TUSHARE_STK_MINS_241_END_V1" as const,
      priceAdjustmentPolicy: "NONE" as const,
    },
    coverage: {
      decisionCount: 1,
      equityPointCount: 1,
      eventEnd: "2026-08-02",
      eventStart: "2026-08-01",
      fillCount: 1,
      orderCount: 1,
      outcomeCount: 1,
      signalCount: 1,
      tradingDayCount: 2,
    },
    formulaVersions: {
      executionFormulaVersion: "execution-v1",
      metricFormulaVersion: "metrics-v1",
      reportSchemaVersion: "report-v2",
      runFormulaVersion: "run-v2",
    },
    initialCashFen: "100000",
    limitations: ["HISTORICAL_SIMULATION", "NO_MARKET_IMPACT"],
    referenceMarket: null,
  };
}

function referenceMarketCoverage() {
  return {
    availableFiveMinuteCount: 0,
    availableOfficialDayCount: 22,
    binding: {
      board: "SZSE_MAIN" as const,
      displayName: "深证成指",
      indexCode: "399001.SZ" as const,
      mappingVersion: "board-index-map-v1" as const,
      selection: "AUTO_BOARD" as const,
    },
    blockers: [] as string[],
    conditionPaths: ["entry.conditions.all[0]"],
    coverageStatus: "AVAILABLE" as const,
    datasetHash: DATASET_HASH,
    formulaDefinitionHash: CONFIG_HASH,
    indexRequirementHash: PLAN_HASH,
    marketIndexDataHash: REPORT_HASH,
    planVersionId: PLAN_VERSION_ID,
    required: true,
    requiredFiveMinuteCount: 0,
    requiredOfficialDayCount: 21,
    warmupEnd: "2026-08-02",
    warmupStart: "2026-07-01",
  };
}

function indexConditionSummary() {
  return {
    applicableBranchCount: 2,
    conditionType: "INDEX_CLOSE_GTE_MA" as const,
    formulaId: "SMA" as const,
    missingCount: 0,
    parameters: { period: 20 },
    planPath: "entry.conditions.all[0]",
    satisfiedCount: 1,
    unsatisfiedCount: 1,
  };
}

function referenceMarket() {
  const coverageView = referenceMarketCoverage();
  return {
    binding: coverageView.binding,
    blockers: coverageView.blockers,
    conditionPaths: coverageView.conditionPaths,
    conditionSummaries: [indexConditionSummary()],
    coverageStatus: "AVAILABLE" as const,
    datasetHash: DATASET_HASH,
    formulaDefinitionHash: CONFIG_HASH,
    indexRequirementHash: PLAN_HASH,
    marketIndexDataHash: REPORT_HASH,
    required: true as const,
    warmupStart: "2026-07-01",
  };
}

function marketIndexSeries() {
  return {
    conditionSummaries: [indexConditionSummary()],
    healthTimeline: [{ dataAt: TIME, health: "LIVE" as const, issues: [] }],
    items: [
      {
        closePoints: "10000.5",
        dataAt: TIME,
        health: "LIVE" as const,
        indicatorFacts: [
          {
            formulaDefinitionHash: CONFIG_HASH,
            formulaId: "SMA" as const,
            period: 20,
            sourceBarHash: RESULT_HASH,
            unit: "POINTS" as const,
            value: "9999.5",
          },
        ],
        issues: [],
        snapshotHash: HASH,
        tradeDate: "2026-08-28",
      },
    ],
    referenceMarket: referenceMarket(),
    runId: HASH,
  };
}

function runPage() {
  return {
    filters: {
      completedFrom: TIME,
      completedTo: LATER_TIME,
      datasetHash: DATASET_HASH,
      pinned: false,
      planVersionId: PLAN_VERSION_ID,
      symbol: "000001.SZ",
    },
    hasMore: false,
    highWatermark: CURSOR,
    items: [runSummary()],
    limit: 20,
    nextCursor: null,
  };
}

function fill() {
  return {
    bucket: "CORE" as const,
    cashDeltaFen: "-1010",
    configHash: CONFIG_HASH,
    costBasisReleasedFen: "0",
    datasetHash: DATASET_HASH,
    fees: {
      commissionFen: "5",
      stampDutyFen: "0",
      totalFen: "10",
      transferFeeFen: "5",
    },
    fillId: "fill-001",
    filledAt: TIME,
    notionalFen: "1000",
    orderId: "order-001",
    planHash: PLAN_HASH,
    priceFen: "10",
    quantity: 100,
    realizedPnlFen: null,
    requestedQuantity: 100,
    resultHash: RESULT_HASH,
    runId: HASH,
    side: "BUY" as const,
    signalId: "signal-001",
    sourceBarId: "bar-001",
    symbol: "000001.SZ",
    targetLotId: null,
  };
}

function fillPage() {
  return {
    filters: {},
    hasMore: false,
    highWatermark: CURSOR,
    items: [fill()],
    limit: 20,
    nextCursor: null,
  };
}

function signalDetail() {
  return {
    bucket: "CORE" as const,
    causeId: "decision-001",
    detailId: "detail-signal-001",
    eventAt: TIME,
    kind: "SIGNAL" as const,
    quantity: 100,
    resultHash: RESULT_HASH,
    runId: HASH,
    signalId: "signal-001",
    signalType: "BUY_CORE_READY" as const,
    symbol: "000001.SZ",
    targetLotId: null,
  };
}

function detailPage() {
  return {
    availability: "AVAILABLE" as const,
    filters: { kind: "SIGNAL" as const },
    hasMore: false,
    highWatermark: CURSOR,
    items: [signalDetail()],
    kind: "SIGNAL" as const,
    limit: 20,
    nextCursor: null,
  };
}

function decisionDetail() {
  return {
    decision: {
      dataAgeSeconds: 0,
      dataHealth: {
        dataAgeSeconds: 0,
        fresh: true,
        latestBarEnd: TIME,
        requiredDataComplete: true,
        status: "LIVE" as const,
      },
      episodeLowFen: null,
      episodeStatus: null,
      evaluatedAt: TIME,
      evidence: [],
      marketDataAt: TIME,
      nextStep: {
        code: "WAIT_FOR_COMPLETE_BAR" as const,
        notBefore: null,
        requiredInputs: [],
      },
      planHash: PLAN_HASH,
      planId: "plan-001",
      planVersion: 1,
      position: {
        coreQuantity: 0,
        sellableCoreQuantity: 0,
        sellableTacticalQuantity: 0,
        tacticalQuantity: 0,
        totalQuantity: 0,
      },
      priceFen: "10",
      resultHash: RESULT_HASH,
      riskBreachTradeDate: null,
      riskStatus: "CLEAR" as const,
      signalType: "WAIT" as const,
      symbol: "000001.SZ",
      zone: "OBSERVATION" as const,
    },
    detailId: "detail-decision-001",
    eventAt: TIME,
    kind: "DECISION" as const,
    resultHash: RESULT_HASH,
    runId: HASH,
  };
}

function executionOutcomeDetail() {
  return {
    detailId: "detail-outcome-001",
    eventAt: TIME,
    fillId: "fill-001",
    kind: "EXECUTION_OUTCOME" as const,
    orderId: "order-001",
    outcomeId: "outcome-001",
    reason: null,
    runId: HASH,
    signalId: "signal-001",
    sourceBarId: "bar-001",
    status: "FILLED" as const,
  };
}

function equityPoint() {
  return {
    cashFen: "90000",
    costBasisFen: "500",
    equityFen: "91000",
    markPriceFen: "10",
    markedAt: TIME,
    marketValueFen: "1000",
    positionQuantity: 100,
    realizedPnlFen: "0",
    runId: HASH,
    snapshotId: "snapshot-001",
    symbol: "000001.SZ",
    totalCostFen: "10",
    unrealizedPnlFen: "500",
  };
}

function equitySeries() {
  return { availability: "AVAILABLE" as const, items: [equityPoint()] };
}

function runReceipt() {
  return {
    attempt: 0,
    datasetHash: DATASET_HASH,
    jobId: "job-run-001",
    kind: "BACKTEST_RUN" as const,
    reused: false,
    revision: 0,
    runId: HASH,
    status: "QUEUED" as const,
    submittedAt: TIME,
  };
}

describe("backtest API runs results and export", () => {
  it("loads server-authored reference-market coverage and frozen run series", async () => {
    const fetchImplementation = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(referenceMarketCoverage()))
      .mockResolvedValueOnce(jsonResponse(marketIndexSeries()));
    const api = createBacktestApi(fetchImplementation);

    const preview = await api.getReferenceMarketCoverage(DATASET_HASH, PLAN_VERSION_ID);
    const series = await api.getMarketIndexSeries(HASH, {
      endOn: "2026-08-31",
      limit: 120,
      startOn: "2026-08-01",
    });

    expect(fetchImplementation.mock.calls.map((call) => call[0])).toEqual([
      `/api/v1/backtest-datasets/${DATASET_HASH}/reference-market-coverage?planVersionId=${PLAN_VERSION_ID}`,
      `/api/v1/backtest-runs/${HASH}/market-index-series?startOn=2026-08-01&endOn=2026-08-31&limit=120`,
    ]);
    expect(preview.conditionPaths).toEqual(["entry.conditions.all[0]"]);
    expect(series.conditionSummaries[0]?.satisfiedCount).toBe(1);
    expect(Object.isFrozen(preview.binding)).toBe(true);
    expect(Object.isFrozen(series.items[0]?.indicatorFacts)).toBe(true);
  });

  it("uses generated run/result routes, canonical Shanghai queries, and deep freezing", async () => {
    const pinnedRun = { ...runView(), pinned: true, revision: 3 };
    const fetchImplementation = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(runPage()))
      .mockResolvedValueOnce(jsonResponse(runView()))
      .mockResolvedValueOnce(
        jsonResponse(runReceipt(), 202, {
          Location: "/api/v1/backtest-jobs/job-run-001",
          "Retry-After": "2",
        }),
      )
      .mockResolvedValueOnce(jsonResponse(pinnedRun))
      .mockResolvedValueOnce(jsonResponse(fillPage()))
      .mockResolvedValueOnce(jsonResponse(detailPage()))
      .mockResolvedValueOnce(jsonResponse(equitySeries()));
    const api = createBacktestApi(fetchImplementation);

    const runs = await api.listRuns({
      completedFrom: "2026-08-28T10:00:00+08:00",
      completedTo: LATER_TIME,
      datasetHash: DATASET_HASH,
      limit: 20,
      pinned: "false",
      planVersionId: PLAN_VERSION_ID,
      symbol: "000001.SZ",
    });
    const oneRun = await api.getRun(HASH);
    const submitted = await api.submitRun(
      {
        datasetHash: DATASET_HASH,
        eventRiskAssumption: "NO_EVENT_RISK",
        executionConfig: {
          buySlippageBps: "1",
          commissionRate: "0.0003",
          minimumCommissionFen: 500,
          sellSlippageBps: "1",
          stampDutyRate: "0.001",
          transferFeeRate: "0.00001",
        },
        initialCashFen: 100000,
        initialLots: [
          {
            acquiredTradeDate: "2026-07-31",
            bucket: "TACTICAL",
            costBasisFen: 1000,
            lotKey: "lot-b",
            quantity: 100,
          },
          {
            acquiredTradeDate: "2026-07-30",
            bucket: "CORE",
            costBasisFen: 2000,
            lotKey: "lot-a",
            quantity: 100,
          },
        ],
        planVersionId: PLAN_VERSION_ID,
      },
      "run-intent-001",
    );
    const pinned = await api.pinRun(
      HASH,
      { expectedRevision: 2, pinned: true },
      "pin-intent-001",
    );
    const fills = await api.listFills(HASH, { limit: 20 });
    const details = await api.listDetails(HASH, { kind: "SIGNAL", limit: 20 });
    const equity = await api.getEquitySeries(HASH);

    expect(fetchImplementation.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/backtest-runs?symbol=000001.SZ&planVersionId=123e4567-e89b-42d3-a456-426614174000&datasetHash=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb&completedFrom=2026-08-28T10%3A00%3A00.000000%2B08%3A00&completedTo=2026-08-28T10%3A01%3A00.000000%2B08%3A00&pinned=false&limit=20",
      `/api/v1/backtest-runs/${HASH}`,
      "/api/v1/backtest-runs",
      `/api/v1/backtest-runs/${HASH}`,
      `/api/v1/backtest-runs/${HASH}/fills?limit=20`,
      `/api/v1/backtest-runs/${HASH}/details?kind=SIGNAL&limit=20`,
      `/api/v1/backtest-runs/${HASH}/equity-series`,
    ]);
    expect(fetchImplementation.mock.calls[2]?.[1]).toMatchObject({
      body: expect.stringContaining('"lotKey":"lot-a"'),
      headers: expect.objectContaining({ "Idempotency-Key": "run-intent-001" }),
      method: "POST",
    });
    expect(fetchImplementation.mock.calls[3]?.[1]).toMatchObject({
      body: JSON.stringify({ expectedRevision: 2, pinned: true }),
      headers: expect.objectContaining({ "Idempotency-Key": "pin-intent-001" }),
      method: "PATCH",
    });
    expect(submitted.body.kind).toBe("BACKTEST_RUN");
    expect(pinned.body.pinned).toBe(true);
    expect(Object.isFrozen(runs.items[0]?.metrics)).toBe(true);
    expect(Object.isFrozen(oneRun.assumptions.executionConfig)).toBe(true);
    expect(Object.isFrozen(fills.items[0]?.fees)).toBe(true);
    expect(Object.isFrozen(details.items[0])).toBe(true);
    expect(Object.isFrozen(equity.items)).toBe(true);
  });

  it.each([
    ["metric return", { ...runView(), metrics: { ...runMetrics(), totalReturn: "0.2" } }],
    ["fill count", { ...runView(), fillCount: 2 }],
    [
      "coverage availability",
      {
        ...runView(),
        availability: { ...resultAvailability(), equitySeries: "NOT_RECORDED" },
      },
    ],
    ["coverage range", { ...runView(), coverage: { ...runView().coverage, eventEnd: "2026-08-03" } }],
    ["limitations order", { ...runView(), limitations: ["NO_MARKET_IMPACT", "HISTORICAL_SIMULATION"] }],
    ["private path", { ...runView(), reportPath: "C:/private/report.json" }],
  ])("rejects contradictory run %s before exposure", async (_name, body) => {
    const api = createBacktestApi(async () => jsonResponse(body));

    await expect(api.getRun(HASH)).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
      status: 200,
    });
  });

  it("accepts the backend 28-digit half-even metric ratio", async () => {
    const body = {
      ...runView(),
      fillCount: 0,
      coverage: { ...runView().coverage, fillCount: 0 },
      metrics: {
        ...runMetrics(),
        finalEquityFen: "4",
        initialEquityFen: "3",
        totalReturn: "0.3333333333333333333333333333",
        tradeCount: 0,
        winningSellCount: 0,
      },
    };
    const api = createBacktestApi(async () => jsonResponse(body));

    await expect(api.getRun(HASH)).resolves.toMatchObject({ runId: HASH });
  });

  it("rejects private fields from run-list items", async () => {
    const body = {
      ...runPage(),
      items: [{ ...runSummary(), reportPath: "C:/private/report.json" }],
    };
    const api = createBacktestApi(async () => jsonResponse(body));

    await expect(
      api.listRuns({
        completedFrom: TIME,
        completedTo: LATER_TIME,
        datasetHash: DATASET_HASH,
        limit: 20,
        pinned: "false",
        planVersionId: PLAN_VERSION_ID,
        symbol: "000001.SZ",
      }),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 200 });
  });

  it.each([
    ["filter echo", { ...runPage(), filters: { ...runPage().filters, pinned: true } }],
    ["duplicate position", { ...runPage(), items: [runSummary(), runSummary()] }],
    ["cursor state", { ...runPage(), hasMore: true, nextCursor: null }],
    ["limit", { ...runPage(), limit: 101 }],
    [
      "item count",
      {
        ...runPage(),
        items: Array.from({ length: 101 }, (_item, index) =>
          runSummary((1000 - index).toString(16).padStart(64, "0")),
        ),
      },
    ],
    [
      "items beyond limit",
      {
        ...runPage(),
        items: Array.from({ length: 21 }, (_item, index) =>
          runSummary((1000 - index).toString(16).padStart(64, "0")),
        ),
      },
    ],
  ])("rejects contradictory run-page %s boundaries", async (_name, body) => {
    const api = createBacktestApi(async () => jsonResponse(body));

    await expect(
      api.listRuns({
        completedFrom: TIME,
        completedTo: LATER_TIME,
        datasetHash: DATASET_HASH,
        limit: 20,
        pinned: "false",
        planVersionId: PLAN_VERSION_ID,
        symbol: "000001.SZ",
      }),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 200 });
  });

  it.each([
    ["fill duplicate", "fills", { ...fillPage(), items: [fill(), fill()] }],
    ["fill cursor", "fills", { ...fillPage(), hasMore: true, nextCursor: null }],
    ["fill limit", "fills", { ...fillPage(), limit: 0 }],
    [
      "fill count",
      "fills",
      {
        ...fillPage(),
        items: Array.from({ length: 101 }, (_item, index) => ({
          ...fill(),
          fillId: `fill-${index.toString().padStart(3, "0")}`,
        })),
      },
    ],
    [
      "fill items beyond limit",
      "fills",
      {
        ...fillPage(),
        items: Array.from({ length: 21 }, (_item, index) => ({
          ...fill(),
          fillId: `fill-${index.toString().padStart(3, "0")}`,
        })),
      },
    ],
    [
      "detail filter echo",
      "details",
      { ...detailPage(), filters: { kind: "DECISION" } },
    ],
    [
      "detail duplicate",
      "details",
      { ...detailPage(), items: [signalDetail(), signalDetail()] },
    ],
    ["detail cursor", "details", { ...detailPage(), hasMore: true, nextCursor: null }],
    ["detail limit", "details", { ...detailPage(), limit: 101 }],
    [
      "detail count",
      "details",
      {
        ...detailPage(),
        items: Array.from({ length: 101 }, (_item, index) => ({
          ...signalDetail(),
          detailId: `detail-signal-${index.toString().padStart(3, "0")}`,
        })),
      },
    ],
    [
      "detail items beyond limit",
      "details",
      {
        ...detailPage(),
        items: Array.from({ length: 21 }, (_item, index) => ({
          ...signalDetail(),
          detailId: `detail-signal-${index.toString().padStart(3, "0")}`,
        })),
      },
    ],
  ])("rejects contradictory %s page-frame boundaries", async (_name, resource, body) => {
    const api = createBacktestApi(async () => jsonResponse(body));
    const request =
      resource === "fills"
        ? api.listFills(HASH, { limit: 20 })
        : api.listDetails(HASH, { kind: "SIGNAL", limit: 20 });

    await expect(request).rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 200 });
  });

  it("sorts initial lots by backend code-point tuple order without locale dependence", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(async (_input, init) => {
      expect(init?.body).toBe(
        JSON.stringify({
          datasetHash: DATASET_HASH,
          eventRiskAssumption: "NO_EVENT_RISK",
          executionConfig: {
            buySlippageBps: "1",
            commissionRate: "0.0003",
            minimumCommissionFen: 500,
            sellSlippageBps: "1",
            stampDutyRate: "0.001",
            transferFeeRate: "0.00001",
          },
          initialCashFen: 100000,
          initialLots: ["lot-1", "lot.1", "lot_1"].map((lotKey) => ({
            acquiredTradeDate: "2026-07-31",
            bucket: "CORE",
            costBasisFen: 100,
            lotKey,
            quantity: 100,
          })),
          planVersionId: PLAN_VERSION_ID,
        }),
      );
      return jsonResponse(runReceipt(), 202, {
        Location: "/api/v1/backtest-jobs/job-run-001",
        "Retry-After": "2",
      });
    });
    const api = createBacktestApi(fetchImplementation);

    await api.submitRun(
      {
        datasetHash: DATASET_HASH,
        eventRiskAssumption: "NO_EVENT_RISK",
        executionConfig: {
          buySlippageBps: "1",
          commissionRate: "0.0003",
          minimumCommissionFen: 500,
          sellSlippageBps: "1",
          stampDutyRate: "0.001",
          transferFeeRate: "0.00001",
        },
        initialCashFen: 100000,
        initialLots: ["lot_1", "lot.1", "lot-1"].map((lotKey) => ({
          acquiredTradeDate: "2026-07-31",
          bucket: "CORE" as const,
          costBasisFen: 100,
          lotKey,
          quantity: 100,
        })),
        planVersionId: PLAN_VERSION_ID,
      },
      "run-sort-001",
    );
  });

  it("serializes run and pin mutations from fresh closed shapes instead of inherited toJSON", async () => {
    const inherited = { toJSON: () => ({ reportPath: "C:/private/report.json" }) };
    const executionConfig = Object.assign(Object.create(inherited) as object, {
      buySlippageBps: "1",
      commissionRate: "0.0003",
      minimumCommissionFen: 500,
      sellSlippageBps: "1",
      stampDutyRate: "0.001",
      transferFeeRate: "0.00001",
    });
    const initialLot = Object.assign(Object.create(inherited) as object, {
      acquiredTradeDate: "2026-07-31",
      bucket: "CORE",
      costBasisFen: 100,
      lotKey: "lot-1",
      quantity: 100,
    });
    const command = Object.assign(Object.create(inherited) as object, {
      datasetHash: DATASET_HASH,
      eventRiskAssumption: "NO_EVENT_RISK",
      executionConfig,
      initialCashFen: 100000,
      initialLots: [initialLot],
      planVersionId: PLAN_VERSION_ID,
    });
    const pinCommand = Object.assign(Object.create(inherited) as object, {
      expectedRevision: 2,
      pinned: true,
    });
    const fetchImplementation = vi
      .fn<typeof fetch>()
      .mockImplementationOnce(async (_input, init) => {
        expect(init?.body).toBe(
          JSON.stringify({
            datasetHash: DATASET_HASH,
            eventRiskAssumption: "NO_EVENT_RISK",
            executionConfig: {
              buySlippageBps: "1",
              commissionRate: "0.0003",
              minimumCommissionFen: 500,
              sellSlippageBps: "1",
              stampDutyRate: "0.001",
              transferFeeRate: "0.00001",
            },
            initialCashFen: 100000,
            initialLots: [
              {
                acquiredTradeDate: "2026-07-31",
                bucket: "CORE",
                costBasisFen: 100,
                lotKey: "lot-1",
                quantity: 100,
              },
            ],
            planVersionId: PLAN_VERSION_ID,
          }),
        );
        return jsonResponse(runReceipt(), 202, {
          Location: "/api/v1/backtest-jobs/job-run-001",
          "Retry-After": "2",
        });
      })
      .mockImplementationOnce(async (_input, init) => {
        expect(init?.body).toBe(JSON.stringify({ expectedRevision: 2, pinned: true }));
        return jsonResponse({ ...runView(), pinned: true, revision: 3 });
      });
    const api = createBacktestApi(fetchImplementation);

    await api.submitRun(command as Parameters<typeof api.submitRun>[0], "run-fresh-001");
    await api.pinRun(
      HASH,
      pinCommand as Parameters<typeof api.pinRun>[1],
      "pin-fresh-001",
    );
  });

  it.each([
    ["fill arithmetic", "fills", { ...fillPage(), items: [{ ...fill(), notionalFen: "999" }] }],
    ["fill identity", "fills", { ...fillPage(), items: [{ ...fill(), runId: REPORT_HASH }] }],
    [
      "detail discriminator",
      "details",
      { ...detailPage(), kind: "DECISION", filters: { kind: "DECISION" } },
    ],
    [
      "detail availability",
      "details",
      { ...detailPage(), availability: "EXPIRED" },
    ],
    [
      "equity arithmetic",
      "equity",
      { ...equitySeries(), items: [{ ...equityPoint(), equityFen: "90000" }] },
    ],
    ["equity availability", "equity", { availability: "EXPIRED", items: [equityPoint()] }],
    [
      "decision identity",
      "details",
      {
        ...detailPage(),
        filters: { kind: "DECISION" },
        items: [
          {
            ...decisionDetail(),
            decision: { ...decisionDetail().decision, resultHash: REPORT_HASH },
          },
        ],
        kind: "DECISION",
      },
    ],
    [
      "outcome state",
      "details",
      {
        ...detailPage(),
        filters: { kind: "EXECUTION_OUTCOME" },
        items: [{ ...executionOutcomeDetail(), fillId: null }],
        kind: "EXECUTION_OUTCOME",
      },
    ],
  ])("rejects contradictory %s result pages", async (_name, resource, body) => {
    const api = createBacktestApi(async () => jsonResponse(body));
    const detailKind =
      resource === "details" && "kind" in body
        ? (body.kind as "DECISION" | "SIGNAL" | "EXECUTION_OUTCOME")
        : "SIGNAL";
    const request =
      resource === "fills"
        ? api.listFills(HASH)
        : resource === "details"
          ? api.listDetails(HASH, { kind: detailKind })
          : api.getEquitySeries(HASH);

    await expect(request).rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 200 });
  });

  it("accepts every closed detail discriminator and both unavailable states", async () => {
    const decisionPage = {
      ...detailPage(),
      filters: { kind: "DECISION" as const },
      items: [decisionDetail()],
      kind: "DECISION" as const,
    };
    const outcomePage = {
      ...detailPage(),
      filters: { kind: "EXECUTION_OUTCOME" as const },
      items: [executionOutcomeDetail()],
      kind: "EXECUTION_OUTCOME" as const,
    };
    const unavailable = (kind: "SIGNAL", availability: "EXPIRED" | "NOT_RECORDED") => ({
      availability,
      filters: { kind },
      hasMore: false,
      highWatermark: CURSOR,
      items: [],
      kind,
      limit: 20,
      nextCursor: null,
    });
    const fetchImplementation = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(decisionPage))
      .mockResolvedValueOnce(jsonResponse(outcomePage))
      .mockResolvedValueOnce(jsonResponse(unavailable("SIGNAL", "EXPIRED")))
      .mockResolvedValueOnce(jsonResponse(unavailable("SIGNAL", "NOT_RECORDED")))
      .mockResolvedValueOnce(jsonResponse({ availability: "EXPIRED", items: [] }))
      .mockResolvedValueOnce(jsonResponse({ availability: "NOT_RECORDED", items: [] }));
    const api = createBacktestApi(fetchImplementation);

    const decision = await api.listDetails(HASH, { kind: "DECISION" });
    const outcome = await api.listDetails(HASH, { kind: "EXECUTION_OUTCOME" });
    await expect(api.listDetails(HASH, { kind: "SIGNAL" })).resolves.toMatchObject({
      availability: "EXPIRED",
    });
    await expect(api.listDetails(HASH, { kind: "SIGNAL" })).resolves.toMatchObject({
      availability: "NOT_RECORDED",
    });
    await expect(api.getEquitySeries(HASH)).resolves.toMatchObject({ availability: "EXPIRED" });
    await expect(api.getEquitySeries(HASH)).resolves.toMatchObject({
      availability: "NOT_RECORDED",
    });
    const decisionItem = decision.items[0];
    expect(decisionItem?.kind).toBe("DECISION");
    expect(outcome.items[0]?.kind).toBe("EXECUTION_OUTCOME");
    if (decisionItem?.kind !== "DECISION" || !("decision" in decisionItem)) throw new Error("expected legacy decision detail");
    expect(Object.isFrozen(decisionItem.decision.evidence)).toBe(true);
  });

  it("builds only allowlisted same-origin export hrefs without transport or path input", () => {
    expect(buildBacktestExportHref(HASH, "SUMMARY_JSON")).toBe(
      `/api/v1/backtest-runs/${HASH}/exports/SUMMARY_JSON`,
    );
    expect(buildBacktestExportHref(HASH, "FILLS_CSV")).toBe(
      `/api/v1/backtest-runs/${HASH}/exports/FILLS_CSV`,
    );
    expect(() => buildBacktestExportHref("../private", "SUMMARY_JSON")).toThrowError(
      ApiClientError,
    );
    expect(() => buildBacktestExportHref(HASH, "../../private" as "SUMMARY_JSON")).toThrowError(
      ApiClientError,
    );

    const source = readFileSync(resolve(process.cwd(), "src/api/backtests.ts"), "utf8");
    expect(source).not.toMatch(/\bBlob\b|showSaveFilePicker|FileSystemHandle/);
    expect(source).not.toMatch(/exportPath|reportPath|databasePath/);
  });

  it("rejects invalid run commands, Shanghai filters, detail kinds, and identities before transport", async () => {
    const fetchImplementation = vi.fn<typeof fetch>();
    const api = createBacktestApi(fetchImplementation);
    const validCommand = {
      datasetHash: DATASET_HASH,
      eventRiskAssumption: "NO_EVENT_RISK" as const,
      executionConfig: {
        buySlippageBps: "1",
        commissionRate: "0.0003",
        minimumCommissionFen: 500,
        sellSlippageBps: "1",
        stampDutyRate: "0.001",
        transferFeeRate: "0.00001",
      },
      initialCashFen: 100000,
      initialLots: [],
      planVersionId: PLAN_VERSION_ID,
    };

    await expect(api.submitRun({ ...validCommand, initialCashFen: 0 }, "run-intent-002"))
      .rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 0 });
    await expect(api.listRuns({ completedFrom: "2026-08-28T02:00:00Z" }))
      .rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 0 });
    await expect(api.listDetails(HASH, { kind: "DEBUG_TRACE" as "SIGNAL" }))
      .rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 0 });
    await expect(api.pinRun("../private", { expectedRevision: 2, pinned: true }, "pin-2"))
      .rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 0 });
    expect(fetchImplementation).not.toHaveBeenCalled();
  });

  it("rejects a run receipt bound to a different submitted dataset", async () => {
    const api = createBacktestApi(async () =>
      jsonResponse(
        { ...runReceipt(), datasetHash: REPORT_HASH },
        202,
        {
          Location: "/api/v1/backtest-jobs/job-run-001",
          "Retry-After": "2",
        },
      ),
    );

    await expect(
      api.submitRun(
        {
          datasetHash: DATASET_HASH,
          eventRiskAssumption: "NO_EVENT_RISK",
          executionConfig: {
            buySlippageBps: "1",
            commissionRate: "0.0003",
            minimumCommissionFen: 500,
            sellSlippageBps: "1",
            stampDutyRate: "0.001",
            transferFeeRate: "0.00001",
          },
          initialCashFen: 100000,
          initialLots: [],
          planVersionId: PLAN_VERSION_ID,
        },
        "run-identity-001",
      ),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 202 });
  });
});
