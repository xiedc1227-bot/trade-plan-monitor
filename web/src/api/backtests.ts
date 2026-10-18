import { isResearchDetail, isResearchInput } from "./researchValues";
import { validLoopRun, validLoopRunSummary, validLoopEvent, validLoopFill, validScheduledRun, validScheduledEvent } from "./monitorLoopValues";
import type { ResearchMetricsView, ResearchEquityView } from "./generated";
import type {
  BacktestAssumptionsView,
  BacktestAuthoritativeDecisionView,
  BacktestDataHealthView,
  BacktestDataSyncCommand,
  BacktestDataSyncJobResultView,
  BacktestDatasetCoverageView,
  BacktestDatasetFiltersView,
  BacktestDatasetPage,
  BacktestDatasetScopeInput,
  BacktestDatasetScopeView,
  BacktestDatasetVerificationCommand,
  BacktestDatasetVerificationJobResultView,
  BacktestDatasetView,
  BacktestDecisionEvidenceView,
  BacktestDecisionView,
  BacktestDetailFiltersView,
  BacktestDetailPage,
  BacktestDetailView,
  BacktestEquityPointView,
  BacktestEquitySeries,
  BacktestEvidenceFactView,
  BacktestJobCancellationCommand,
  BacktestJobFiltersView,
  BacktestJobPage,
  BacktestJobProgressView,
  BacktestJobReceipt,
  BacktestJobResultView,
  BacktestJobView,
  BacktestMetricsView,
  BacktestResultAvailabilityView,
  BacktestRunCommand,
  PreparedBacktestRunCommand,
  ScheduledPreparedBacktestRunCommand,
  BacktestRunCoverageView,
  BacktestRunFiltersView,
  BacktestRunJobResultView,
  BacktestRunPage,
  BacktestRunPinCommand,
  BacktestRunSummaryView,
  BacktestRunView,
  BacktestLoopRunView,
  BacktestScheduledRunView,
  BacktestExecutionConfigInput,
  BacktestExecutionConfigView,
  BacktestExecutionOutcomeView,
  BacktestFeeBreakdownView,
  BacktestFillPage,
  BacktestFillView,
  BacktestFormulaVersionsView,
  BacktestInitialLotInput,
  BacktestIndexConditionSummaryView,
  BacktestNextStepView,
  BacktestMarketIndexHealthPointView,
  BacktestMarketIndexPointView,
  BacktestMarketIndexSeriesView,
  BacktestPositionSummaryView,
  BacktestReferenceMarketBindingView,
  BacktestReferenceMarketCoverageView,
  BacktestReferenceMarketView,
  BacktestSignalView,
  paths,
} from "./generated";
import {
  isCalendarDate,
  normalizeShanghaiDateTime,
  parseShanghaiResponseDateTime,
} from "./shanghaiTime";
import { ApiClientError, invalidResponse, requestJson } from "./transport";

export type BacktestJobListQuery = NonNullable<
  paths["/api/v1/backtest-jobs"]["get"]["parameters"]["query"]
>;
export type BacktestDatasetListQuery = NonNullable<
  paths["/api/v1/backtest-datasets"]["get"]["parameters"]["query"]
>;
export type BacktestRunListQuery = NonNullable<
  paths["/api/v1/backtest-runs"]["get"]["parameters"]["query"]
>;
export type BacktestExportKind =
  paths["/api/v1/backtest-runs/{run_id}/exports/{export_kind}"]["get"]["parameters"]["path"]["export_kind"];
export type BacktestFillListQuery = NonNullable<
  paths["/api/v1/backtest-runs/{run_id}/fills"]["get"]["parameters"]["query"]
>;
export type BacktestDetailListQuery =
  paths["/api/v1/backtest-runs/{run_id}/details"]["get"]["parameters"]["query"];
export type BacktestMarketIndexSeriesQuery = NonNullable<
  paths["/api/v1/backtest-runs/{run_id}/market-index-series"]["get"]["parameters"]["query"]
>;

export interface BacktestRequestOptions {
  readonly signal?: AbortSignal;
}
export type BacktestRunResult = BacktestRunView | BacktestLoopRunView | BacktestScheduledRunView;

export interface BacktestMutationResponse<T> {
  readonly body: T;
  readonly location: string | null;
  readonly retryAfterSeconds: number | null;
  readonly status: 200 | 202;
}

export interface BacktestApi {
  cancelJob(
    command: BacktestJobCancellationCommand,
    idempotencyKey: string,
    options?: BacktestRequestOptions,
  ): Promise<BacktestMutationResponse<BacktestJobView>>;
  getDataset(
    datasetHash: string,
    options?: BacktestRequestOptions,
  ): Promise<BacktestDatasetView>;
  getReferenceMarketCoverage(
    datasetHash: string,
    planVersionId: string,
    options?: BacktestRequestOptions,
  ): Promise<BacktestReferenceMarketCoverageView>;
  getJob(jobId: string, options?: BacktestRequestOptions): Promise<BacktestJobView>;
  listDatasets(
    query?: BacktestDatasetListQuery,
    options?: BacktestRequestOptions,
  ): Promise<BacktestDatasetPage>;
  listJobs(
    query?: BacktestJobListQuery,
    options?: BacktestRequestOptions,
  ): Promise<BacktestJobPage>;
  getRun(runId: string, options?: BacktestRequestOptions): Promise<BacktestRunResult>;
  getEquitySeries(
    runId: string,
    options?: BacktestRequestOptions,
  ): Promise<BacktestEquitySeries>;
  getMarketIndexSeries(
    runId: string,
    query?: BacktestMarketIndexSeriesQuery,
    options?: BacktestRequestOptions,
  ): Promise<BacktestMarketIndexSeriesView>;
  listDetails(
    runId: string,
    query: BacktestDetailListQuery,
    options?: BacktestRequestOptions,
  ): Promise<BacktestDetailPage>;
  listFills(
    runId: string,
    query?: BacktestFillListQuery,
    options?: BacktestRequestOptions,
  ): Promise<BacktestFillPage>;
  listRuns(
    query?: BacktestRunListQuery,
    options?: BacktestRequestOptions,
  ): Promise<BacktestRunPage>;
  pinRun(
    runId: string,
    command: BacktestRunPinCommand,
    idempotencyKey: string,
    options?: BacktestRequestOptions,
  ): Promise<BacktestMutationResponse<BacktestRunResult>>;
  submitRun(
    command: BacktestRunCommand | PreparedBacktestRunCommand | ScheduledPreparedBacktestRunCommand,
    idempotencyKey: string,
    options?: BacktestRequestOptions,
  ): Promise<BacktestMutationResponse<BacktestJobReceipt>>;
  syncData(
    command: BacktestDataSyncCommand,
    idempotencyKey: string,
    options?: BacktestRequestOptions,
  ): Promise<BacktestMutationResponse<BacktestJobReceipt>>;
  verifyDataset(
    command: BacktestDatasetVerificationCommand,
    idempotencyKey: string,
    options?: BacktestRequestOptions,
  ): Promise<BacktestMutationResponse<BacktestJobReceipt>>;
}

const MAX_PAGE_ITEMS = 100;
const MAX_ITEM_BYTES = 32 * 1024;
const MAX_PAGE_BYTES = 4 * 1024 * 1024;
const MAX_JOB_ATTEMPT = 3;
const DEFAULT_PAGE_LIMIT = 20;
const RETRY_AFTER_SECONDS = 2;
const MAX_EXACT_TEXT_CHARACTERS = 4_096;
const MAX_INITIAL_LOTS = 200;

const jobKinds = new Set(["DATA_SYNC", "DATASET_VERIFY", "BACKTEST_RUN"] as const);
const jobStatuses = new Set([
  "QUEUED",
  "RUNNING",
  "CANCEL_REQUESTED",
  "COMPLETED",
  "FAILED",
  "CANCELLED",
] as const);
const jobPhases = new Set([
  "QUEUED",
  "VALIDATING_INPUT",
  "SYNCING_DATA",
  "VERIFYING_DATASET",
  "REPLAYING",
  "MATERIALIZING_RESULTS",
  "FINALIZING",
  "TERMINAL",
] as const);
const progressUnits = new Set(["ITEMS", "SYMBOL_DAYS", "EVENTS", "ROWS"] as const);
const artifactAvailability = new Set(["AVAILABLE", "EXPIRED", "NOT_RECORDED"] as const);
const detailKinds = new Set(["DECISION", "SIGNAL", "EXECUTION_OUTCOME"] as const);
const actionableSignalTypes = new Set([
  "BUY_CORE_READY",
  "BUY_TACTICAL_READY",
  "PRESSURE_REDUCE_READY",
  "RISK_BREACH",
  "RISK_EXIT_READY",
  "RISK_EXIT_PENDING_SETTLEMENT",
] as const);
const executionStatuses = new Set(["FILLED", "UNFILLED", "IGNORED"] as const);
const unfilledReasons = new Set([
  "NON_EXECUTABLE_SIGNAL",
  "SUSPENDED",
  "MISSING_NEXT_MINUTE",
  "NO_NEXT_MINUTE",
  "LIMIT_UP_LOCKED",
  "LIMIT_DOWN_LOCKED",
  "INSUFFICIENT_CASH",
  "MAX_POSITION_REACHED",
  "TARGET_POSITION_REACHED",
  "TARGET_LOT_NOT_FOUND",
  "T_PLUS_ONE",
] as const);
const dataHealthStatuses = new Set([
  "STARTING",
  "LIVE",
  "STALE",
  "GAPPED",
  "DEGRADED",
  "BLOCKED",
  "CLOSE_PENDING",
] as const);
const marketIndexHealthStatuses = new Set(["LIVE", "STALE", "GAPPED", "BLOCKED"] as const);
const marketIndexIssueCodes = new Set([
  "MISSING_FIVE_MINUTE_BAR",
  "MISSING_OFFICIAL_DAILY_BAR",
  "INSUFFICIENT_HISTORY",
  "STALE_DATA",
  "DUPLICATE_IDENTITY",
  "GAPPED_SERIES",
  "INDEX_IDENTITY_MISMATCH",
  "FUTURE_DATA",
  "INVALID_TIMESTAMP",
  "NONCANONICAL_DECIMAL",
  "INVALID_OHLC",
  "FORMULA_MISMATCH",
  "PROVIDER_UNAVAILABLE",
] as const);
const indexConditionTypes = new Set([
  "INDEX_CLOSE_GTE_MA",
  "INDEX_CLOSE_LTE_MA",
  "INDEX_MA_NON_DECREASING",
  "INDEX_MA_NON_INCREASING",
  "INDEX_RETURN_GTE",
  "INDEX_RETURN_LTE",
] as const);
const decisionZones = new Set([
  "LOW_BUY",
  "OBSERVATION",
  "PRESSURE",
  "BELOW_RISK",
  "OUTSIDE",
  "UNKNOWN",
] as const);
const decisionSignalTypes = new Set([
  "WAIT",
  "LOW_ZONE_WATCH",
  "BLOCKED_DATA",
  "BLOCKED_RISK",
  "BUY_CORE_READY",
  "BUY_TACTICAL_READY",
  "PRESSURE_REDUCE_READY",
  "RISK_BREACH",
  "RISK_RECOVERED",
  "RISK_EXIT_READY",
  "RISK_EXIT_PENDING_SETTLEMENT",
] as const);
const riskStatuses = new Set([
  "CLEAR",
  "BREACHED_PENDING_CONFIRMATION",
  "EXIT_PENDING_SETTLEMENT",
] as const);
const episodeStatuses = new Set(["ACTIVE", "ALERTED", "CLOSED"] as const);
const nextStepCodes = new Set([
  "WAIT_FOR_COMPLETE_BAR",
  "WAIT_FOR_REQUIRED_DATA",
  "WATCH_LOW_ZONE",
  "WATCH_PRESSURE",
  "REVIEW_BLOCKER",
  "WAIT_FOR_OFFICIAL_CLOSE",
  "WAIT_FOR_NEXT_TRADING_DAY",
  "WAIT_FOR_SETTLEMENT",
  "RECORD_CONFIRMED_FILL",
] as const);
const missingInputCodes = new Set([
  "COMPLETE_MINUTE_BAR",
  "PREVIOUS_MINUTE_BAR",
  "COMPLETE_5M_BAR",
  "PREVIOUS_5M_BAR",
  "COMPLETE_5M_BAR_WINDOW",
  "ROLLING_VOLUME_WINDOW",
  "SESSION_BARS",
  "DAILY_INDICATORS",
  "PROVISIONAL_DAILY_BAR",
  "FIVE_MINUTE_INDICATORS",
  "INDICATOR_VALUE",
  "OFFICIAL_DAILY_CLOSE",
  "TRADING_CALENDAR",
  "DAILY_LIMIT",
  "MANUAL_EVENT_RISK",
  "INDEX_SNAPSHOT",
  "INDEX_IDENTITY",
  "INDEX_CUTOFF",
  "INDEX_HEALTH",
  "INDEX_FACT",
  "INDEX_HISTORY",
  "INDEX_FORMULA",
] as const);
const evidenceKinds = new Set(["CONDITION", "RULE"] as const);
const conditionOutcomes = new Set(["SATISFIED", "UNSATISFIED", "MISSING_INPUT"] as const);
const evidenceUnits = new Set([
  "FEN",
  "SHARES",
  "RATIO",
  "BARS",
  "YUAN",
  "COUNT",
  "BOOLEAN",
  "DATE",
  "DATETIME",
  "CODE",
  "POINTS",
] as const);
const allowedPhases = {
  BACKTEST_RUN: new Set([
    "QUEUED",
    "VALIDATING_INPUT",
    "REPLAYING",
    "MATERIALIZING_RESULTS",
    "FINALIZING",
    "TERMINAL",
  ]),
  DATASET_VERIFY: new Set([
    "QUEUED",
    "VALIDATING_INPUT",
    "VERIFYING_DATASET",
    "FINALIZING",
    "TERMINAL",
  ]),
  DATA_SYNC: new Set([
    "QUEUED",
    "VALIDATING_INPUT",
    "SYNCING_DATA",
    "FINALIZING",
    "TERMINAL",
  ]),
} as const;

const scopeKeyNames = [
  "adjustmentPolicy",
  "end",
  "historicalProfile",
  "start",
  "symbols",
  "warmupStart",
] as const;
const scopeInputKeys = exactKeys<BacktestDatasetScopeInput>()(scopeKeyNames);
const scopeViewKeys = exactKeys<BacktestDatasetScopeView>()(scopeKeyNames);
const syncCommandKeys = exactKeys<BacktestDataSyncCommand>()([
  "allowNetwork",
  "refresh",
  "scope",
]);
const verificationCommandKeys = exactKeys<BacktestDatasetVerificationCommand>()(["scope"]);
const cancellationCommandKeys = exactKeys<BacktestJobCancellationCommand>()(["jobId"]);
const coverageKeys = exactKeys<BacktestDatasetCoverageView>()([
  "blockers",
  "calendarRowCount",
  "dailyBarRowCount",
  "dailyLimitRowCount",
  "minuteBarCount",
  "minuteDayCount",
  "symbolCount",
  "tradingDayCount",
]);
const datasetKeys = exactKeys<BacktestDatasetView>()([
  "coverage",
  "createdAt",
  "datasetHash",
  "schemaVersion",
  "scope",
  "verifiedAt",
]);
const datasetFilterKeys = exactKeys<BacktestDatasetFiltersView>()([
  "adjustmentPolicy",
  "endOnOrBefore",
  "historicalProfile",
  "startOnOrAfter",
  "symbol",
]);
const datasetPageKeys = exactKeys<BacktestDatasetPage>()([
  "filters",
  "hasMore",
  "highWatermark",
  "items",
  "limit",
  "nextCursor",
]);
const progressKeys = exactKeys<BacktestJobProgressView>()([
  "completedUnits",
  "phase",
  "totalUnits",
  "unit",
  "updatedAt",
]);
const receiptKeys = exactKeys<BacktestJobReceipt>()([
  "attempt",
  "datasetHash",
  "jobId",
  "kind",
  "reused",
  "revision",
  "runId",
  "status",
  "submittedAt",
]);
const jobKeys = exactKeys<BacktestJobView>()([
  "attempt",
  "cancelRequestedAt",
  "createdAt",
  "datasetHash",
  "errorCode",
  "errorMessage",
  "finishedAt",
  "jobId",
  "kind",
  "progress",
  "requestHash",
  "result",
  "reused",
  "revision",
  "runId",
  "startedAt",
  "status",
  "updatedAt",
]);
const jobFilterKeys = exactKeys<BacktestJobFiltersView>()([
  "createdFrom",
  "createdTo",
  "datasetHash",
  "kind",
  "runId",
  "status",
]);
const jobPageKeys = exactKeys<BacktestJobPage>()([
  "filters",
  "hasMore",
  "highWatermark",
  "items",
  "limit",
  "nextCursor",
]);
const syncResultKeys = exactKeys<BacktestDataSyncJobResultView>()([
  "calendarRows",
  "dailyBarRows",
  "dailyLimitRows",
  "kind",
  "minuteDays",
  "networkCalls",
]);
const verificationResultKeys = exactKeys<BacktestDatasetVerificationJobResultView>()([
  "blockers",
  "coverage",
  "datasetHash",
  "kind",
  "ready",
]);
const runResultKeys = exactKeys<BacktestRunJobResultView>()([
  "kind",
  "reportHash",
  "reused",
  "runId",
]);
const runCommandKeys = exactKeys<BacktestRunCommand>()([
  "researchInput",
  "datasetHash",
  "eventRiskAssumption",
  "executionConfig",
  "initialCashFen",
  "initialLots",
  "planVersionId",
]);
const executionConfigInputKeys = exactKeys<BacktestExecutionConfigInput>()([
  "buySlippageBps",
  "commissionRate",
  "minimumCommissionFen",
  "sellSlippageBps",
  "stampDutyRate",
  "transferFeeRate",
]);
const initialLotKeys = exactKeys<BacktestInitialLotInput>()([
  "acquiredTradeDate",
  "bucket",
  "costBasisFen",
  "lotKey",
  "quantity",
]);
const runPinKeys = exactKeys<BacktestRunPinCommand>()(["expectedRevision", "pinned"]);
const availabilityKeys = exactKeys<BacktestResultAvailabilityView>()([
  "decisionDetails",
  "equitySeries",
  "executionOutcomeDetails",
  "signalDetails",
]);
const metricsKeys = exactKeys<BacktestMetricsView>()([
  "blockedCount",
  "finalCashFen",
  "finalEquityFen",
  "initialCashFen",
  "initialEquityFen",
  "maximumDrawdown",
  "realizedPnlFen",
  "skippedCount",
  "totalCostFen",
  "totalReturn",
  "tradeCount",
  "turnoverFen",
  "unrealizedPnlFen",
  "winRate",
  "winningSellCount",
]);
const runSummaryKeys = exactKeys<BacktestRunSummaryView>()([
  "availability",
  "completedAt",
  "datasetHash",
  "eventEnd",
  "eventStart",
  "fillCount",
  "metrics",
  "pinned",
  "planHash",
  "planVersionId",
  "reportHash",
  "revision",
  "runId",
  "status",
  "symbol",
]);
const runCoverageKeys = exactKeys<BacktestRunCoverageView>()([
  "decisionCount",
  "equityPointCount",
  "eventEnd",
  "eventStart",
  "fillCount",
  "orderCount",
  "outcomeCount",
  "signalCount",
  "tradingDayCount",
]);
const executionConfigViewKeys = exactKeys<BacktestExecutionConfigView>()([
  "buySlippageBps",
  "commissionRate",
  "minimumCommissionFen",
  "sellSlippageBps",
  "stampDutyRate",
  "transferFeeRate",
]);
const assumptionsKeys = exactKeys<BacktestAssumptionsView>()([
  "eventRiskAssumption",
  "executionConfig",
  "executionConfigHash",
  "historicalProfile",
  "priceAdjustmentPolicy",
]);
const formulaVersionKeys = exactKeys<BacktestFormulaVersionsView>()([
  "executionFormulaVersion",
  "metricFormulaVersion",
  "reportSchemaVersion",
  "runFormulaVersion",
]);
const runViewKeys = exactKeys<BacktestRunView>()([
  ...runSummaryKeys,
  "assumptions",
  "coverage",
  "formulaVersions",
  "initialCashFen",
  "limitations",
  "referenceMarket",
]);
const runFilterKeys = exactKeys<Omit<BacktestRunFiltersView, "eventEndFrom" | "eventEndTo">>()([
  "completedFrom",
  "completedTo",
  "datasetHash",
  "pinned",
  "planVersionId",
  "symbol",
]);
const runPageKeys = exactKeys<BacktestRunPage>()([
  "filters",
  "hasMore",
  "highWatermark",
  "items",
  "limit",
  "nextCursor",
]);
const feeKeys = exactKeys<BacktestFeeBreakdownView>()([
  "commissionFen",
  "stampDutyFen",
  "totalFen",
  "transferFeeFen",
]);
const fillKeys = exactKeys<BacktestFillView>()([
  "bucket",
  "cashDeltaFen",
  "configHash",
  "costBasisReleasedFen",
  "datasetHash",
  "fees",
  "fillId",
  "filledAt",
  "notionalFen",
  "orderId",
  "planHash",
  "priceFen",
  "quantity",
  "realizedPnlFen",
  "requestedQuantity",
  "resultHash",
  "runId",
  "side",
  "signalId",
  "sourceBarId",
  "symbol",
  "targetLotId",
]);
const fillPageKeys = exactKeys<BacktestFillPage>()([
  "filters",
  "hasMore",
  "highWatermark",
  "items",
  "limit",
  "nextCursor",
]);
const detailFilterKeys = exactKeys<BacktestDetailFiltersView>()(["kind"]);
const detailPageKeys = exactKeys<BacktestDetailPage>()([
  "availability",
  "filters",
  "hasMore",
  "highWatermark",
  "items",
  "kind",
  "limit",
  "nextCursor",
]);
const signalKeys = exactKeys<BacktestSignalView>()([
  "bucket",
  "causeId",
  "detailId",
  "eventAt",
  "kind",
  "quantity",
  "resultHash",
  "runId",
  "signalId",
  "signalType",
  "symbol",
  "targetLotId",
]);
const outcomeKeys = exactKeys<BacktestExecutionOutcomeView>()([
  "detailId",
  "eventAt",
  "fillId",
  "kind",
  "orderId",
  "outcomeId",
  "reason",
  "runId",
  "signalId",
  "sourceBarId",
  "status",
]);
const decisionKeys = exactKeys<BacktestDecisionView>()([
  "decision",
  "detailId",
  "eventAt",
  "kind",
  "resultHash",
  "runId",
]);
const equityPointKeys = exactKeys<BacktestEquityPointView>()([
  "cashFen",
  "costBasisFen",
  "equityFen",
  "markPriceFen",
  "markedAt",
  "marketValueFen",
  "positionQuantity",
  "realizedPnlFen",
  "runId",
  "snapshotId",
  "symbol",
  "totalCostFen",
  "unrealizedPnlFen",
]);
const equitySeriesKeys = exactKeys<BacktestEquitySeries>()(["availability", "items"]);
const authoritativeDecisionKeys = exactKeys<BacktestAuthoritativeDecisionView>()([
  "dataAgeSeconds",
  "dataHealth",
  "episodeLowFen",
  "episodeStatus",
  "evaluatedAt",
  "evidence",
  "marketDataAt",
  "nextStep",
  "planHash",
  "planId",
  "planVersion",
  "position",
  "priceFen",
  "referenceMarket",
  "resultHash",
  "riskBreachTradeDate",
  "riskStatus",
  "signalType",
  "symbol",
  "zone",
]);
const authoritativeDecisionWithoutReferenceMarketKeys = authoritativeDecisionKeys.filter(
  (key) => key !== "referenceMarket",
);
const dataHealthKeys = exactKeys<BacktestDataHealthView>()([
  "dataAgeSeconds",
  "fresh",
  "latestBarEnd",
  "requiredDataComplete",
  "status",
]);
const nextStepKeys = exactKeys<BacktestNextStepView>()([
  "code",
  "notBefore",
  "requiredInputs",
]);
const positionKeys = exactKeys<BacktestPositionSummaryView>()([
  "coreQuantity",
  "sellableCoreQuantity",
  "sellableTacticalQuantity",
  "tacticalQuantity",
  "totalQuantity",
]);
const evidenceKeys = exactKeys<BacktestDecisionEvidenceView>()([
  "children",
  "code",
  "facts",
  "kind",
  "missingInputs",
  "outcome",
]);
const factKeys = exactKeys<BacktestEvidenceFactView>()(["key", "unit", "value"]);
const referenceMarketBindingKeys = exactKeys<BacktestReferenceMarketBindingView>()([
  "board",
  "displayName",
  "indexCode",
  "mappingVersion",
  "selection",
]);
const referenceMarketCoverageKeys = exactKeys<BacktestReferenceMarketCoverageView>()([
  "availableFiveMinuteCount",
  "availableOfficialDayCount",
  "binding",
  "blockers",
  "conditionPaths",
  "coverageStatus",
  "datasetHash",
  "formulaDefinitionHash",
  "indexRequirementHash",
  "marketIndexDataHash",
  "planVersionId",
  "required",
  "requiredFiveMinuteCount",
  "requiredOfficialDayCount",
  "warmupEnd",
  "warmupStart",
]);
const referenceMarketKeys = exactKeys<BacktestReferenceMarketView>()([
  "binding",
  "blockers",
  "conditionPaths",
  "conditionSummaries",
  "coverageStatus",
  "datasetHash",
  "formulaDefinitionHash",
  "indexRequirementHash",
  "marketIndexDataHash",
  "required",
  "warmupStart",
]);
const indexConditionSummaryKeys = exactKeys<BacktestIndexConditionSummaryView>()([
  "applicableBranchCount",
  "conditionType",
  "formulaId",
  "missingCount",
  "parameters",
  "planPath",
  "satisfiedCount",
  "unsatisfiedCount",
]);
const marketIndexPointKeys = exactKeys<BacktestMarketIndexPointView>()([
  "closePoints",
  "dataAt",
  "health",
  "indicatorFacts",
  "issues",
  "snapshotHash",
  "tradeDate",
]);
const marketIndexHealthPointKeys = exactKeys<BacktestMarketIndexHealthPointView>()([
  "dataAt",
  "health",
  "issues",
]);
const marketIndexSeriesKeys = exactKeys<BacktestMarketIndexSeriesView>()([
  "conditionSummaries",
  "healthTimeline",
  "items",
  "referenceMarket",
  "runId",
]);
const decisionReferenceMarketKeys = [
  "dataAt",
  "evidence",
  "health",
  "indexCode",
  "snapshotHash",
] as const;
const indexConditionEvidenceKeys = [
  "actualValue",
  "comparisonValue",
  "conditionType",
  "dataCutoff",
  "decisionCutoff",
  "formulaDefinitionHash",
  "formulaId",
  "indexCode",
  "mappingVersion",
  "missingInputs",
  "outcome",
  "parameters",
  "planPath",
  "snapshotHash",
  "unit",
] as const;

export function buildBacktestExportHref(
  runId: string,
  exportKind: BacktestExportKind,
): string {
  if (!isSha256(runId) || (exportKind !== "SUMMARY_JSON" && exportKind !== "FILLS_CSV")) {
    throw invalidRequest();
  }
  return `/api/v1/backtest-runs/${runId}/exports/${exportKind}`;
}

export function createBacktestApi(
  fetchImplementation: typeof fetch = globalThis.fetch.bind(globalThis),
): BacktestApi {
  return Object.freeze({
    async cancelJob(
      command: BacktestJobCancellationCommand,
      idempotencyKey: string,
      options?: BacktestRequestOptions,
    ) {
      const normalizedCommand = normalizeCancellationCommand(command);
      return requestMutation(
        fetchImplementation,
        "/api/v1/backtest-job-cancellations",
        normalizedCommand,
        idempotencyKey,
        options,
        (body, status, headers) =>
          validateCancellation(body, status, headers, normalizedCommand.jobId),
      );
    },

    async getDataset(datasetHash: string, options?: BacktestRequestOptions) {
      if (!isSha256(datasetHash)) {
        throw invalidRequest();
      }
      const { body, status } = await requestJson(
        fetchImplementation,
        `/api/v1/backtest-datasets/${datasetHash}`,
        requestInit("GET", options),
      );
      return validateResponse(status, () => {
        if (status !== 200 || !isDataset(body) || body.datasetHash !== datasetHash) {
          throw invalidResponse(status);
        }
        return body;
      });
    },

    async getReferenceMarketCoverage(
      datasetHash: string,
      planVersionId: string,
      options?: BacktestRequestOptions,
    ) {
      const normalizedPlanVersionId = normalizeUuid(planVersionId);
      if (!isSha256(datasetHash) || normalizedPlanVersionId === null) {
        throw invalidRequest();
      }
      const search = new URLSearchParams();
      appendQuery(search, "planVersionId", normalizedPlanVersionId);
      const { body, status } = await requestJson(
        fetchImplementation,
        withQuery(
          `/api/v1/backtest-datasets/${datasetHash}/reference-market-coverage`,
          search,
        ),
        requestInit("GET", options),
      );
      return validateResponse(status, () => {
        if (
          status !== 200 ||
          !isReferenceMarketCoverage(body) ||
          body.datasetHash !== datasetHash ||
          body.planVersionId !== normalizedPlanVersionId
        ) {
          throw invalidResponse(status);
        }
        return body;
      });
    },

    async getJob(jobId: string, options?: BacktestRequestOptions) {
      if (!isJobId(jobId)) {
        throw invalidRequest();
      }
      const { body, status } = await requestJson(
        fetchImplementation,
        `/api/v1/backtest-jobs/${jobId}`,
        requestInit("GET", options),
      );
      return validateResponse(status, () => {
        if (status !== 200 || !isJob(body) || body.jobId !== jobId) {
          throw invalidResponse(status);
        }
        return body;
      });
    },

    async listDatasets(
      query: BacktestDatasetListQuery = {},
      options?: BacktestRequestOptions,
    ) {
      const normalized = normalizeDatasetQuery(query);
      const { body, status } = await requestJson(
        fetchImplementation,
        withQuery("/api/v1/backtest-datasets", datasetSearch(normalized)),
        requestInit("GET", options),
      );
      return validateResponse(status, () => {
        if (
          status !== 200 ||
          !isDatasetPage(body) ||
          !datasetPageMatchesQuery(body, normalized)
        ) {
          throw invalidResponse(status);
        }
        return body;
      });
    },

    async listJobs(query: BacktestJobListQuery = {}, options?: BacktestRequestOptions) {
      const normalized = normalizeJobQuery(query);
      const { body, status } = await requestJson(
        fetchImplementation,
        withQuery("/api/v1/backtest-jobs", jobSearch(normalized)),
        requestInit("GET", options),
      );
      return validateResponse(status, () => {
        if (status !== 200 || !isJobPage(body) || !jobPageMatchesQuery(body, normalized)) {
          throw invalidResponse(status);
        }
        return body;
      });
    },

    async getRun(runId: string, options?: BacktestRequestOptions) {
      if (!isSha256(runId)) throw invalidRequest();
      const { body, status } = await requestJson(
        fetchImplementation,
        `/api/v1/backtest-runs/${runId}`,
        requestInit("GET", options),
      );
      return validateResponse(status, () => {
        if (status !== 200 || !isRun(body) || body.runId !== runId) {
          throw invalidResponse(status);
        }
        return body;
      });
    },

    async getEquitySeries(runId: string, options?: BacktestRequestOptions) {
      if (!isSha256(runId)) throw invalidRequest();
      const { body, status } = await requestJson(
        fetchImplementation,
        `/api/v1/backtest-runs/${runId}/equity-series`,
        requestInit("GET", options),
      );
      return validateResponse(status, () => {
        if (
          status !== 200 ||
          !isEquitySeries(body) ||
          !body.items.every((item) => item.runId === runId)
        ) {
          throw invalidResponse(status);
        }
        return body;
      });
    },

    async getMarketIndexSeries(
      runId: string,
      query: BacktestMarketIndexSeriesQuery = {},
      options?: BacktestRequestOptions,
    ) {
      if (!isSha256(runId)) throw invalidRequest();
      const normalized = normalizeMarketIndexSeriesQuery(query);
      const { body, status } = await requestJson(
        fetchImplementation,
        withQuery(
          `/api/v1/backtest-runs/${runId}/market-index-series`,
          marketIndexSeriesSearch(normalized),
        ),
        requestInit("GET", options),
      );
      return validateResponse(status, () => {
        if (
          status !== 200 ||
          !isMarketIndexSeries(body) ||
          body.runId !== runId ||
          body.items.length > (normalized.limit ?? 512) ||
          (normalized.startOn !== undefined &&
            normalized.startOn !== null &&
            body.items.some((item) => item.tradeDate < normalized.startOn!)) ||
          (normalized.endOn !== undefined &&
            normalized.endOn !== null &&
            body.items.some((item) => item.tradeDate > normalized.endOn!))
        ) {
          throw invalidResponse(status);
        }
        return body;
      });
    },

    async listDetails(
      runId: string,
      query: BacktestDetailListQuery,
      options?: BacktestRequestOptions,
    ) {
      if (!isSha256(runId)) throw invalidRequest();
      const normalized = normalizeDetailQuery(query);
      const { body, status } = await requestJson(
        fetchImplementation,
        withQuery(`/api/v1/backtest-runs/${runId}/details`, detailSearch(normalized)),
        requestInit("GET", options),
      );
      return validateResponse(status, () => {
        if (
          status !== 200 ||
          !isDetailPage(body) ||
          body.kind !== normalized.kind ||
          body.limit !== (normalized.limit ?? DEFAULT_PAGE_LIMIT) ||
          !body.items.every((item) => item.runId === runId)
        ) {
          throw invalidResponse(status);
        }
        return body;
      });
    },

    async listFills(
      runId: string,
      query: BacktestFillListQuery = {},
      options?: BacktestRequestOptions,
    ) {
      if (!isSha256(runId)) throw invalidRequest();
      const normalized = normalizeResultPageQuery(query);
      const { body, status } = await requestJson(
        fetchImplementation,
        withQuery(`/api/v1/backtest-runs/${runId}/fills`, resultPageSearch(normalized)),
        requestInit("GET", options),
      );
      return validateResponse(status, () => {
        if (
          status !== 200 ||
          !isFillPage(body) ||
          body.limit !== (normalized.limit ?? DEFAULT_PAGE_LIMIT) ||
          !body.items.every((item) => item.runId === runId)
        ) {
          throw invalidResponse(status);
        }
        return body;
      });
    },

    async listRuns(query: BacktestRunListQuery = {}, options?: BacktestRequestOptions) {
      const normalized = normalizeRunQuery(query);
      const { body, status } = await requestJson(
        fetchImplementation,
        withQuery("/api/v1/backtest-runs", runSearch(normalized)),
        requestInit("GET", options),
      );
      return validateResponse(status, () => {
        if (status !== 200 || !isRunPage(body) || !runPageMatchesQuery(body, normalized)) {
          throw invalidResponse(status);
        }
        return body;
      });
    },

    async pinRun(
      runId: string,
      command: BacktestRunPinCommand,
      idempotencyKey: string,
      options?: BacktestRequestOptions,
    ) {
      if (!isSha256(runId)) throw invalidRequest();
      const normalizedCommand = normalizeRunPinCommand(command);
      return requestMutation(
        fetchImplementation,
        `/api/v1/backtest-runs/${runId}`,
        normalizedCommand,
        idempotencyKey,
        options,
        (body, status, headers) =>
          validatePin(body, status, headers, runId, normalizedCommand),
        "PATCH",
      );
    },

    async submitRun(
      command: BacktestRunCommand | PreparedBacktestRunCommand | ScheduledPreparedBacktestRunCommand,
      idempotencyKey: string,
      options?: BacktestRequestOptions,
    ) {
      const normalizedCommand = normalizeRunCommand(command);
      return requestMutation(
        fetchImplementation,
        "/api/v1/backtest-runs",
        normalizedCommand,
        idempotencyKey,
        options,
        (body, status, headers) =>
          validateRunSubmission(
            body,
            status,
            headers,
            "datasetHash" in normalizedCommand ? normalizedCommand.datasetHash : undefined,
          ),
      );
    },

    async syncData(
      command: BacktestDataSyncCommand,
      idempotencyKey: string,
      options?: BacktestRequestOptions,
    ) {
      const normalizedCommand = normalizeDataSyncCommand(command);
      return requestMutation(
        fetchImplementation,
        "/api/v1/backtest-data-syncs",
        normalizedCommand,
        idempotencyKey,
        options,
        (body, status, headers) =>
          validateSubmission(body, status, headers, "DATA_SYNC"),
      );
    },

    async verifyDataset(
      command: BacktestDatasetVerificationCommand,
      idempotencyKey: string,
      options?: BacktestRequestOptions,
    ) {
      const normalizedCommand = normalizeDatasetVerificationCommand(command);
      return requestMutation(
        fetchImplementation,
        "/api/v1/backtest-dataset-verifications",
        normalizedCommand,
        idempotencyKey,
        options,
        (body, status, headers) =>
          validateSubmission(body, status, headers, "DATASET_VERIFY"),
      );
    },
  });
}

async function requestMutation<T>(
  fetchImplementation: typeof fetch,
  path: string,
  command: unknown,
  idempotencyKey: string,
  options: BacktestRequestOptions | undefined,
  validate: (body: unknown, status: number, headers: Headers) => BacktestMutationResponse<T>,
  method: "POST" | "PATCH" = "POST",
): Promise<BacktestMutationResponse<T>> {
  if (!isIdempotencyKey(idempotencyKey)) {
    throw invalidRequest();
  }
  const init = requestInit(method, options);
  init.body = JSON.stringify(command);
  init.headers = {
    Accept: "application/json",
    "Content-Type": "application/json",
    "Idempotency-Key": idempotencyKey,
  };
  const { body, headers, status } = await requestJson(fetchImplementation, path, init);
  return validateResponse(status, () => validate(body, status, headers));
}

function validateSubmission(
  body: unknown,
  status: number,
  headers: Headers,
  expectedKind: "DATA_SYNC" | "DATASET_VERIFY" | "BACKTEST_RUN",
): BacktestMutationResponse<BacktestJobReceipt> {
  if (status !== 202 || !isJobReceipt(body) || body.kind !== expectedKind) {
    throw invalidResponse(status);
  }
  const location = headers.get("Location");
  const expectedLocation = `/api/v1/backtest-jobs/${body.jobId}`;
  const retryAfterSeconds = parseRetryAfter(headers);
  const terminal = isTerminalStatus(body.status);
  if (
    location !== expectedLocation ||
    (terminal && retryAfterSeconds !== null) ||
    (!terminal && retryAfterSeconds !== RETRY_AFTER_SECONDS)
  ) {
    throw invalidResponse(status);
  }
  return Object.freeze({ body, location, retryAfterSeconds, status: 202 });
}

function validateRunSubmission(
  body: unknown,
  status: number,
  headers: Headers,
  expectedDatasetHash: string | undefined,
): BacktestMutationResponse<BacktestJobReceipt> {
  const response = validateSubmission(body, status, headers, "BACKTEST_RUN");
  if (expectedDatasetHash !== undefined && response.body.datasetHash !== expectedDatasetHash) {
    throw invalidResponse(status);
  }
  return response;
}

function validatePin(
  body: unknown,
  status: number,
  headers: Headers,
  expectedRunId: string,
  command: BacktestRunPinCommand,
): BacktestMutationResponse<BacktestRunResult> {
  if (
    status !== 200 ||
    !isRun(body) ||
    body.runId !== expectedRunId ||
    body.pinned !== command.pinned ||
    (body.revision !== command.expectedRevision &&
      body.revision !== command.expectedRevision + 1) ||
    headers.get("Location") !== null ||
    parseRetryAfter(headers) !== null
  ) {
    throw invalidResponse(status);
  }
  return Object.freeze({ body, location: null, retryAfterSeconds: null, status: 200 });
}

function validateCancellation(
  body: unknown,
  status: number,
  headers: Headers,
  expectedJobId: string,
): BacktestMutationResponse<BacktestJobView> {
  if ((status !== 200 && status !== 202) || !isJob(body) || body.jobId !== expectedJobId) {
    throw invalidResponse(status);
  }
  const location = headers.get("Location");
  const retryAfterSeconds = parseRetryAfter(headers);
  if (status === 200) {
    if (body.status !== "CANCELLED" || location !== null || retryAfterSeconds !== null) {
      throw invalidResponse(status);
    }
    return Object.freeze({ body, location: null, retryAfterSeconds: null, status: 200 });
  }
  if (
    body.status !== "CANCEL_REQUESTED" ||
    location !== `/api/v1/backtest-jobs/${body.jobId}` ||
    retryAfterSeconds !== RETRY_AFTER_SECONDS
  ) {
    throw invalidResponse(status);
  }
  return Object.freeze({ body, location, retryAfterSeconds, status: 202 });
}

function isJobReceipt(value: unknown): value is BacktestJobReceipt {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, receiptKeys) ||
    !isJobId(value.jobId) ||
    !isJobKind(value.kind) ||
    !isJobStatus(value.status) ||
    !isNullableSha256(value.runId) ||
    !isNullableSha256(value.datasetHash) ||
    !isAttempt(value.attempt) ||
    !isNonnegativeSafeInteger(value.revision) ||
    typeof value.reused !== "boolean" ||
    !isResponseTime(value.submittedAt)
  ) {
    return false;
  }
  if (value.kind === "BACKTEST_RUN") {
    if (value.runId === null || value.datasetHash === null) return false;
  } else if (value.runId !== null) {
    return false;
  }
  if (value.kind === "DATA_SYNC" && value.datasetHash !== null) return false;
  if (value.status === "QUEUED" && value.attempt !== 0) return false;
  if (
    (value.status === "RUNNING" || value.status === "CANCEL_REQUESTED") &&
    value.attempt === 0
  ) {
    return false;
  }
  if (value.status === "COMPLETED" && value.attempt === 0 && !value.reused) return false;
  return (
    (!value.reused ||
      (value.kind === "BACKTEST_RUN" &&
        value.status === "COMPLETED" &&
        value.attempt === 0 &&
        value.revision === 0)) &&
    isBoundedItem(value)
  );
}

function isJob(value: unknown): value is BacktestJobView {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, jobKeys) ||
    !isJobId(value.jobId) ||
    !isJobKind(value.kind) ||
    !isJobStatus(value.status) ||
    !isSha256(value.requestHash) ||
    !isNullableSha256(value.runId) ||
    !isNullableSha256(value.datasetHash) ||
    !isJobProgress(value.progress) ||
    !(value.result === null || isJobResult(value.result)) ||
    !isAttempt(value.attempt) ||
    !isNonnegativeSafeInteger(value.revision) ||
    !isResponseTime(value.createdAt) ||
    !isNullableResponseTime(value.startedAt) ||
    !isResponseTime(value.updatedAt) ||
    !isNullableResponseTime(value.finishedAt) ||
    !isNullableResponseTime(value.cancelRequestedAt) ||
    typeof value.reused !== "boolean" ||
    !isNullableStableCode(value.errorCode) ||
    !isNullablePublicError(value.errorMessage)
  ) {
    return false;
  }

  const created = timeKey(value.createdAt);
  const progress = timeKey(value.progress.updatedAt);
  const updated = timeKey(value.updatedAt);
  if (created > progress || progress > updated) return false;
  if (
    value.startedAt !== null &&
    (created > timeKey(value.startedAt) || timeKey(value.startedAt) > progress)
  ) {
    return false;
  }
  if (value.finishedAt !== null && timeKey(value.finishedAt) < updated) return false;
  if (value.cancelRequestedAt !== null) {
    const lower = timeKey(value.startedAt ?? value.createdAt);
    const cancelled = timeKey(value.cancelRequestedAt);
    if (cancelled < lower || cancelled > updated) return false;
  }

  const terminal = isTerminalStatus(value.status);
  if (terminal !== (value.finishedAt !== null) || terminal !== (value.progress.phase === "TERMINAL")) {
    return false;
  }
  if ((value.status === "COMPLETED") !== (value.result !== null)) return false;
  if (value.result !== null && value.result.kind !== value.kind) return false;

  const needsError = value.status === "FAILED" || value.status === "CANCELLED";
  const hasError = value.errorCode !== null && value.errorMessage !== null;
  if (needsError !== hasError) return false;
  if (value.errorMessage !== expectedPublicError(value.status)) return false;

  if (value.kind === "BACKTEST_RUN") {
    if (value.runId === null || value.datasetHash === null) return false;
  } else if (value.runId !== null) {
    return false;
  }
  if (value.kind === "DATA_SYNC" && value.datasetHash !== null) return false;
  if (value.result?.kind === "BACKTEST_RUN") {
    if (value.runId !== value.result.runId || value.reused !== value.result.reused) return false;
  }
  if (
    value.result?.kind === "DATASET_VERIFY" &&
    value.datasetHash !== value.result.datasetHash
  ) {
    return false;
  }
  if (!allowedPhases[value.kind].has(value.progress.phase)) return false;

  if (value.status === "QUEUED") {
    if (value.attempt !== 0 || value.startedAt !== null || value.progress.phase !== "QUEUED") {
      return false;
    }
  } else if (value.status === "RUNNING" || value.status === "CANCEL_REQUESTED") {
    if (value.attempt === 0 || value.startedAt === null || value.progress.phase === "QUEUED") {
      return false;
    }
  } else if (
    (value.attempt === 0 && value.startedAt !== null) ||
    (value.attempt > 0 && value.startedAt === null)
  ) {
    return false;
  }

  const cancelling = value.status === "CANCEL_REQUESTED" || value.status === "CANCELLED";
  if (cancelling !== (value.cancelRequestedAt !== null)) return false;
  if (value.status === "COMPLETED" && value.attempt === 0 && !value.reused) return false;
  if (value.status === "FAILED" && value.attempt === 0) return false;
  return !value.reused ||
    (value.kind === "BACKTEST_RUN" &&
      value.status === "COMPLETED" &&
      value.attempt === 0 &&
      value.revision === 0);
}

function isJobProgress(value: unknown): value is BacktestJobProgressView {
  return (
    isRecord(value) &&
    hasExactKeys(value, progressKeys) &&
    isJobPhase(value.phase) &&
    isNonnegativeSafeInteger(value.completedUnits) &&
    (value.totalUnits === null || isNonnegativeSafeInteger(value.totalUnits)) &&
    (value.totalUnits === null || value.completedUnits <= value.totalUnits) &&
    isProgressUnit(value.unit) &&
    isResponseTime(value.updatedAt)
  );
}

function isJobResult(value: unknown): value is BacktestJobResultView {
  if (!isRecord(value) || typeof value.kind !== "string") return false;
  if (value.kind === "DATA_SYNC") {
    return (
      hasExactKeys(value, syncResultKeys) &&
      isNonnegativeSafeInteger(value.calendarRows) &&
      isNonnegativeSafeInteger(value.minuteDays) &&
      isNonnegativeSafeInteger(value.dailyLimitRows) &&
      isNonnegativeSafeInteger(value.dailyBarRows) &&
      isNonnegativeSafeInteger(value.networkCalls)
    );
  }
  if (value.kind === "DATASET_VERIFY") {
    if (
      !hasExactKeys(value, verificationResultKeys) ||
      typeof value.ready !== "boolean" ||
      !isNullableSha256(value.datasetHash) ||
      !isDatasetCoverage(value.coverage) ||
      !isBlockers(value.blockers) ||
      !sameStrings(value.blockers, value.coverage.blockers)
    ) {
      return false;
    }
    return value.ready
      ? value.datasetHash !== null && value.blockers.length === 0
      : value.datasetHash === null && value.blockers.length > 0;
  }
  return (
    value.kind === "BACKTEST_RUN" &&
    hasExactKeys(value, runResultKeys) &&
    isSha256(value.runId) &&
    isSha256(value.reportHash) &&
    typeof value.reused === "boolean"
  );
}

function isDataset(value: unknown): value is BacktestDatasetView {
  return (
    isRecord(value) &&
    hasExactKeys(value, datasetKeys) &&
    isSha256(value.datasetHash) &&
    (value.schemaVersion === "backtest-dataset-v1" ||
      value.schemaVersion === "backtest-dataset-v2") &&
    isDatasetScope(value.scope) &&
    isDatasetCoverage(value.coverage) &&
    value.coverage.symbolCount === value.scope.symbols.length &&
    isResponseTime(value.createdAt) &&
    isResponseTime(value.verifiedAt) &&
    timeKey(value.createdAt) <= timeKey(value.verifiedAt) &&
    isBoundedItem(value)
  );
}

function isReferenceMarketBinding(
  value: unknown,
): value is BacktestReferenceMarketBindingView {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, referenceMarketBindingKeys) ||
    value.selection !== "AUTO_BOARD" ||
    value.mappingVersion !== "board-index-map-v1"
  ) {
    return false;
  }
  const identities: Record<string, readonly [string, string]> = {
    "000001.SH": ["SSE_MAIN", "上证指数"],
    "000688.SH": ["STAR_MARKET", "科创50"],
    "399001.SZ": ["SZSE_MAIN", "深证成指"],
    "399006.SZ": ["CHINEXT", "创业板指"],
    "899050.BJ": ["BSE", "北证50"],
  };
  const identity = typeof value.indexCode === "string" ? identities[value.indexCode] : undefined;
  return identity !== undefined && value.board === identity[0] && value.displayName === identity[1];
}

function isReferenceMarketCoverage(
  value: unknown,
): value is BacktestReferenceMarketCoverageView {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, referenceMarketCoverageKeys) ||
    !isCanonicalUuid(value.planVersionId) ||
    !isSha256(value.datasetHash) ||
    !isReferenceMarketBinding(value.binding) ||
    typeof value.required !== "boolean" ||
    !isOrderedPlanPaths(value.conditionPaths) ||
    !isNonnegativeSafeInteger(value.requiredFiveMinuteCount) ||
    !isNonnegativeSafeInteger(value.availableFiveMinuteCount) ||
    !isNonnegativeSafeInteger(value.requiredOfficialDayCount) ||
    !isNonnegativeSafeInteger(value.availableOfficialDayCount) ||
    !isCalendarDate(value.warmupStart) ||
    !isCalendarDate(value.warmupEnd) ||
    value.warmupStart > value.warmupEnd ||
    !(value.coverageStatus === "AVAILABLE" ||
      value.coverageStatus === "BLOCKED" ||
      value.coverageStatus === "NOT_REQUIRED") ||
    !isBlockers(value.blockers) ||
    !isNullableSha256(value.marketIndexDataHash) ||
    !isSha256(value.indexRequirementHash) ||
    !isSha256(value.formulaDefinitionHash) ||
    value.required !== (value.conditionPaths.length > 0)
  ) {
    return false;
  }
  if (!value.required) {
    return (
      value.coverageStatus === "NOT_REQUIRED" &&
      value.blockers.length === 0 &&
      value.requiredFiveMinuteCount === 0 &&
      value.requiredOfficialDayCount === 0
    );
  }
  if (value.coverageStatus === "NOT_REQUIRED") return false;
  if ((value.coverageStatus === "AVAILABLE") !== (value.blockers.length === 0)) return false;
  return value.coverageStatus !== "AVAILABLE" || value.marketIndexDataHash !== null;
}

function isReferenceMarket(value: unknown): value is BacktestReferenceMarketView {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, referenceMarketKeys) ||
    !isReferenceMarketBinding(value.binding) ||
    value.required !== true ||
    !isOrderedPlanPaths(value.conditionPaths) ||
    value.conditionPaths.length === 0 ||
    !isCalendarDate(value.warmupStart) ||
    !(value.coverageStatus === "AVAILABLE" ||
      value.coverageStatus === "BLOCKED" ||
      value.coverageStatus === "EXPIRED" ||
      value.coverageStatus === "NOT_RECORDED") ||
    !isBlockers(value.blockers) ||
    !isSha256(value.marketIndexDataHash) ||
    !isSha256(value.indexRequirementHash) ||
    !isSha256(value.formulaDefinitionHash) ||
    !isSha256(value.datasetHash) ||
    !Array.isArray(value.conditionSummaries) ||
    value.conditionSummaries.length === 0 ||
    value.conditionSummaries.length > 50 ||
    !value.conditionSummaries.every(isIndexConditionSummary)
  ) {
    return false;
  }
  if (!sameStrings(value.conditionPaths, value.conditionSummaries.map((item) => item.planPath))) {
    return false;
  }
  return (value.coverageStatus === "AVAILABLE") === (value.blockers.length === 0);
}

function isIndexConditionSummary(
  value: unknown,
): value is BacktestIndexConditionSummaryView {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, indexConditionSummaryKeys) ||
    !isPlanPath(value.planPath) ||
    !(typeof value.conditionType === "string" && indexConditionTypes.has(value.conditionType as never)) ||
    !isNonnegativeSafeInteger(value.applicableBranchCount) ||
    !isNonnegativeSafeInteger(value.satisfiedCount) ||
    !isNonnegativeSafeInteger(value.unsatisfiedCount) ||
    !isNonnegativeSafeInteger(value.missingCount) ||
    value.applicableBranchCount !==
      value.satisfiedCount + value.unsatisfiedCount + value.missingCount ||
    !isRecord(value.parameters)
  ) {
    return false;
  }
  if (
    value.conditionType === "INDEX_CLOSE_GTE_MA" ||
    value.conditionType === "INDEX_CLOSE_LTE_MA"
  ) {
    return (
      value.formulaId === "SMA" &&
      hasExactKeys(value.parameters, ["period"]) &&
      isIntegerBetween(value.parameters.period, 2, 250)
    );
  }
  if (
    value.conditionType === "INDEX_MA_NON_DECREASING" ||
    value.conditionType === "INDEX_MA_NON_INCREASING"
  ) {
    return (
      value.formulaId === "SMA_LOOKBACK" &&
      hasExactKeys(value.parameters, ["lookback", "period"]) &&
      isIntegerBetween(value.parameters.period, 2, 250) &&
      isIntegerBetween(value.parameters.lookback, 1, 60)
    );
  }
  return (
    value.formulaId === "RETURN" &&
    hasExactKeys(value.parameters, ["thresholdRatio", "window", "windowSize"]) &&
    isDecimalText(value.parameters.thresholdRatio) &&
    (value.parameters.window === "FIVE_MINUTE_BUCKETS" ||
      value.parameters.window === "OFFICIAL_OPEN_DAYS") &&
    isIntegerBetween(value.parameters.windowSize, 1, 250)
  );
}

function isMarketIndexSeries(value: unknown): value is BacktestMarketIndexSeriesView {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, marketIndexSeriesKeys) ||
    !isSha256(value.runId) ||
    !(value.referenceMarket === null || isReferenceMarket(value.referenceMarket)) ||
    !Array.isArray(value.items) ||
    value.items.length > 512 ||
    !value.items.every(isMarketIndexPoint) ||
    !Array.isArray(value.healthTimeline) ||
    value.healthTimeline.length > 512 ||
    !value.healthTimeline.every(isMarketIndexHealthPoint) ||
    !Array.isArray(value.conditionSummaries) ||
    value.conditionSummaries.length > 50 ||
    !value.conditionSummaries.every(isIndexConditionSummary)
  ) {
    return false;
  }
  if (value.referenceMarket === null) {
    return (
      value.items.length === 0 &&
      value.healthTimeline.length === 0 &&
      value.conditionSummaries.length === 0
    );
  }
  const itemPositions = value.items.map((item) => `${item.tradeDate}\0${item.dataAt}`);
  const healthPositions = value.healthTimeline.map((item) => item.dataAt);
  return (
    isAscendingUnique(itemPositions) &&
    isAscendingUnique(healthPositions) &&
    JSON.stringify(value.conditionSummaries) ===
      JSON.stringify(value.referenceMarket.conditionSummaries) &&
    isBoundedPage(value)
  );
}

function isMarketIndexPoint(value: unknown): value is BacktestMarketIndexPointView {
  return (
    isRecord(value) &&
    hasExactKeys(value, marketIndexPointKeys) &&
    isCalendarDate(value.tradeDate) &&
    isResponseTime(value.dataAt) &&
    value.dataAt.slice(0, 10) === value.tradeDate &&
    isDecimalText(value.closePoints) &&
    compareDecimal(value.closePoints, "0") > 0 &&
    isSha256(value.snapshotHash) &&
    Array.isArray(value.indicatorFacts) &&
    value.indicatorFacts.length <= 50 &&
    value.indicatorFacts.every(isMarketIndexIndicatorFact) &&
    isMarketIndexHealth(value.health) &&
    isMarketIndexIssues(value.issues, value.health)
  );
}

function isMarketIndexHealthPoint(
  value: unknown,
): value is BacktestMarketIndexHealthPointView {
  return (
    isRecord(value) &&
    hasExactKeys(value, marketIndexHealthPointKeys) &&
    isResponseTime(value.dataAt) &&
    isMarketIndexHealth(value.health) &&
    isMarketIndexIssues(value.issues, value.health)
  );
}

function isMarketIndexIndicatorFact(value: unknown): boolean {
  if (
    !isRecord(value) ||
    !isSha256(value.sourceBarHash) ||
    !isSha256(value.formulaDefinitionHash) ||
    !isDecimalText(value.value)
  ) {
    return false;
  }
  if (value.formulaId === "SMA") {
    return (
      hasExactKeys(value, [
        "formulaDefinitionHash",
        "formulaId",
        "period",
        "sourceBarHash",
        "unit",
        "value",
      ]) &&
      value.unit === "POINTS" &&
      isIntegerBetween(value.period, 2, 250)
    );
  }
  if (value.formulaId === "SMA_LOOKBACK") {
    return (
      hasExactKeys(value, [
        "comparisonValue",
        "formulaDefinitionHash",
        "formulaId",
        "lookback",
        "period",
        "sourceBarHash",
        "unit",
        "value",
      ]) &&
      value.unit === "POINTS" &&
      isDecimalText(value.comparisonValue) &&
      isIntegerBetween(value.period, 2, 250) &&
      isIntegerBetween(value.lookback, 1, 60)
    );
  }
  return (
    value.formulaId === "RETURN" &&
    hasExactKeys(value, [
      "formulaDefinitionHash",
      "formulaId",
      "sourceBarHash",
      "unit",
      "value",
      "window",
      "windowSize",
    ]) &&
    value.unit === "RATIO" &&
    (value.window === "FIVE_MINUTE_BUCKETS" || value.window === "OFFICIAL_OPEN_DAYS") &&
    isIntegerBetween(value.windowSize, 1, 250)
  );
}

function isMarketIndexHealth(value: unknown): boolean {
  return typeof value === "string" && marketIndexHealthStatuses.has(value as never);
}

function isMarketIndexIssues(value: unknown, health: unknown): boolean {
  return (
    Array.isArray(value) &&
    value.length <= 16 &&
    value.every(
      (item) => typeof item === "string" && marketIndexIssueCodes.has(item as never),
    ) &&
    new Set(value).size === value.length &&
    ((health === "LIVE" && value.length === 0) || (health !== "LIVE" && value.length > 0))
  );
}

function isDatasetScope(value: unknown): value is BacktestDatasetScopeView {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, scopeViewKeys) ||
    value.adjustmentPolicy !== "NONE" ||
    value.historicalProfile !== "TUSHARE_STK_MINS_241_END_V1" ||
    !isCalendarDate(value.start) ||
    !isCalendarDate(value.end) ||
    !isCalendarDate(value.warmupStart) ||
    !Array.isArray(value.symbols) ||
    value.symbols.length < 1 ||
    value.symbols.length > 10 ||
    !value.symbols.every(isAShareSymbol) ||
    !isSortedUnique(value.symbols)
  ) {
    return false;
  }
  return (
    value.start <= value.end &&
    value.end <= calendarYearsAfter(value.start, 5) &&
    value.warmupStart <= value.start &&
    value.start <= calendarYearsAfter(value.warmupStart, 2)
  );
}

function isDatasetCoverage(value: unknown): value is BacktestDatasetCoverageView {
  return (
    isRecord(value) &&
    hasExactKeys(value, coverageKeys) &&
    isNonnegativeSafeInteger(value.symbolCount) &&
    isNonnegativeSafeInteger(value.tradingDayCount) &&
    isNonnegativeSafeInteger(value.calendarRowCount) &&
    isNonnegativeSafeInteger(value.minuteDayCount) &&
    isNonnegativeSafeInteger(value.minuteBarCount) &&
    isNonnegativeSafeInteger(value.dailyLimitRowCount) &&
    isNonnegativeSafeInteger(value.dailyBarRowCount) &&
    isBlockers(value.blockers)
  );
}

function isDatasetPage(value: unknown): value is BacktestDatasetPage {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, datasetPageKeys) ||
    !isDatasetFilters(value.filters) ||
    !Array.isArray(value.items) ||
    value.items.length > MAX_PAGE_ITEMS ||
    !value.items.every(isDataset) ||
    !isPageFrame(value)
  ) {
    return false;
  }
  const filters = value.filters;
  const positions = value.items.map((item) => `${item.createdAt}\0${item.datasetHash}`);
  if (!isDescendingUnique(positions)) return false;
  return (
    value.items.every((item) => datasetMatchesFilters(item, filters)) && isBoundedPage(value)
  );
}

function isDatasetFilters(value: unknown): value is BacktestDatasetFiltersView {
  return (
    isRecord(value) &&
    hasExactKeys(value, datasetFilterKeys) &&
    (value.symbol === null || isAShareSymbol(value.symbol)) &&
    (value.startOnOrAfter === null || isCalendarDate(value.startOnOrAfter)) &&
    (value.endOnOrBefore === null || isCalendarDate(value.endOnOrBefore)) &&
    (value.startOnOrAfter === null ||
      value.endOnOrBefore === null ||
      value.startOnOrAfter <= value.endOnOrBefore) &&
    (value.historicalProfile === null ||
      value.historicalProfile === "TUSHARE_STK_MINS_241_END_V1") &&
    (value.adjustmentPolicy === null || value.adjustmentPolicy === "NONE")
  );
}

function isJobPage(value: unknown): value is BacktestJobPage {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, jobPageKeys) ||
    !isJobFilters(value.filters) ||
    !Array.isArray(value.items) ||
    value.items.length > MAX_PAGE_ITEMS ||
    !value.items.every((item) => isJob(item) && isBoundedItem(item)) ||
    !isPageFrame(value)
  ) {
    return false;
  }
  const filters = value.filters;
  const positions = value.items.map((item) => `${item.createdAt}\0${item.jobId}`);
  if (!isDescendingUnique(positions)) return false;
  return value.items.every((item) => jobMatchesFilters(item, filters)) && isBoundedPage(value);
}

function isJobFilters(value: unknown): value is BacktestJobFiltersView {
  return (
    isRecord(value) &&
    hasExactKeys(value, jobFilterKeys) &&
    isNullableEnumArray(value.kind, isJobKind, 3) &&
    isNullableEnumArray(value.status, isJobStatus, 6) &&
    isNullableSha256(value.runId) &&
    isNullableSha256(value.datasetHash) &&
    isNullableResponseTime(value.createdFrom) &&
    isNullableResponseTime(value.createdTo) &&
    (value.createdFrom === null ||
      value.createdTo === null ||
      timeKey(value.createdFrom) <= timeKey(value.createdTo))
  );
}

function normalizeJobQuery(query: BacktestJobListQuery): BacktestJobListQuery {
  if (!isRecord(query) || !hasOnlyKeys(query, [
    "createdFrom",
    "createdTo",
    "cursor",
    "datasetHash",
    "kind",
    "limit",
    "runId",
    "status",
  ])) {
    throw invalidRequest();
  }
  const createdFrom = normalizeOptionalRequestTime(query.createdFrom);
  const createdTo = normalizeOptionalRequestTime(query.createdTo);
  if (createdFrom !== null && createdTo !== null && createdFrom > createdTo) {
    throw invalidRequest();
  }
  const kind = normalizeEnumQuery(query.kind, isJobKind, 3);
  const status = normalizeEnumQuery(query.status, isJobStatus, 6);
  if (
    !isOptionalSha256(query.runId) ||
    !isOptionalSha256(query.datasetHash) ||
    !isOptionalLimit(query.limit) ||
    !isOptionalCursor(query.cursor)
  ) {
    throw invalidRequest();
  }
  return {
    ...(createdFrom === null ? {} : { createdFrom }),
    ...(createdTo === null ? {} : { createdTo }),
    ...(query.cursor == null ? {} : { cursor: query.cursor }),
    ...(query.datasetHash == null ? {} : { datasetHash: query.datasetHash }),
    ...(kind === null ? {} : { kind }),
    ...(query.limit === undefined ? {} : { limit: query.limit }),
    ...(query.runId == null ? {} : { runId: query.runId }),
    ...(status === null ? {} : { status }),
  };
}

function normalizeDatasetQuery(query: BacktestDatasetListQuery): BacktestDatasetListQuery {
  if (!isRecord(query) || !hasOnlyKeys(query, [
    "adjustmentPolicy",
    "cursor",
    "endOnOrBefore",
    "historicalProfile",
    "limit",
    "startOnOrAfter",
    "symbol",
  ])) {
    throw invalidRequest();
  }
  if (
    !(query.adjustmentPolicy == null || query.adjustmentPolicy === "NONE") ||
    !(query.historicalProfile == null ||
      query.historicalProfile === "TUSHARE_STK_MINS_241_END_V1") ||
    !(query.symbol == null || isAShareSymbol(query.symbol)) ||
    !(query.startOnOrAfter == null || isCalendarDate(query.startOnOrAfter)) ||
    !(query.endOnOrBefore == null || isCalendarDate(query.endOnOrBefore)) ||
    (query.startOnOrAfter != null &&
      query.endOnOrBefore != null &&
      query.startOnOrAfter > query.endOnOrBefore) ||
    !isOptionalLimit(query.limit) ||
    !isOptionalCursor(query.cursor)
  ) {
    throw invalidRequest();
  }
  return { ...query };
}

function jobSearch(query: BacktestJobListQuery): URLSearchParams {
  const search = new URLSearchParams();
  for (const kind of query.kind ?? []) search.append("kind", kind);
  for (const status of query.status ?? []) search.append("status", status);
  appendQuery(search, "runId", query.runId);
  appendQuery(search, "datasetHash", query.datasetHash);
  appendQuery(search, "createdFrom", query.createdFrom);
  appendQuery(search, "createdTo", query.createdTo);
  appendQuery(search, "limit", query.limit);
  appendQuery(search, "cursor", query.cursor);
  return search;
}

function datasetSearch(query: BacktestDatasetListQuery): URLSearchParams {
  const search = new URLSearchParams();
  appendQuery(search, "symbol", query.symbol);
  appendQuery(search, "startOnOrAfter", query.startOnOrAfter);
  appendQuery(search, "endOnOrBefore", query.endOnOrBefore);
  appendQuery(search, "historicalProfile", query.historicalProfile);
  appendQuery(search, "adjustmentPolicy", query.adjustmentPolicy);
  appendQuery(search, "limit", query.limit);
  appendQuery(search, "cursor", query.cursor);
  return search;
}

function jobPageMatchesQuery(page: BacktestJobPage, query: BacktestJobListQuery): boolean {
  return (
    page.limit === (query.limit ?? DEFAULT_PAGE_LIMIT) &&
    sameNullableStrings(page.filters.kind, query.kind ?? null) &&
    sameNullableStrings(page.filters.status, query.status ?? null) &&
    page.filters.runId === (query.runId ?? null) &&
    page.filters.datasetHash === (query.datasetHash ?? null) &&
    page.filters.createdFrom === (query.createdFrom ?? null) &&
    page.filters.createdTo === (query.createdTo ?? null)
  );
}

function datasetPageMatchesQuery(
  page: BacktestDatasetPage,
  query: BacktestDatasetListQuery,
): boolean {
  return (
    page.limit === (query.limit ?? DEFAULT_PAGE_LIMIT) &&
    page.filters.symbol === (query.symbol ?? null) &&
    page.filters.startOnOrAfter === (query.startOnOrAfter ?? null) &&
    page.filters.endOnOrBefore === (query.endOnOrBefore ?? null) &&
    page.filters.historicalProfile === (query.historicalProfile ?? null) &&
    page.filters.adjustmentPolicy === (query.adjustmentPolicy ?? null)
  );
}

function jobMatchesFilters(job: BacktestJobView, filters: BacktestJobFiltersView): boolean {
  return (
    (filters.kind === null || filters.kind.includes(job.kind)) &&
    (filters.status === null || filters.status.includes(job.status)) &&
    (filters.runId === null || filters.runId === job.runId) &&
    (filters.datasetHash === null || filters.datasetHash === job.datasetHash) &&
    (filters.createdFrom === null || job.createdAt >= filters.createdFrom) &&
    (filters.createdTo === null || job.createdAt <= filters.createdTo)
  );
}

function datasetMatchesFilters(
  item: BacktestDatasetView,
  filters: BacktestDatasetFiltersView,
): boolean {
  return (
    (filters.symbol === null || item.scope.symbols.includes(filters.symbol)) &&
    (filters.startOnOrAfter === null || item.scope.start >= filters.startOnOrAfter) &&
    (filters.endOnOrBefore === null || item.scope.end <= filters.endOnOrBefore) &&
    (filters.historicalProfile === null ||
      item.scope.historicalProfile === filters.historicalProfile) &&
    (filters.adjustmentPolicy === null ||
      item.scope.adjustmentPolicy === filters.adjustmentPolicy)
  );
}

function isRun(value: unknown): value is BacktestRunResult {
  if (isRecord(value) && value.schemaVersion === "monitor-loop-result-v2") return validScheduledRun(value);
  if (isRecord(value) && value.schemaVersion === "monitor-loop-result-v1") return validLoopRun(value);
  if (!isRecord(value) || !hasExactKeys(value, runViewKeys)) return false;
  if (
    !isPositiveFenText(value.initialCashFen) ||
    !isRunCoverage(value.coverage) ||
    !isAssumptions(value.assumptions) ||
    !isFormulaVersions(value.formulaVersions) ||
    !(value.referenceMarket === null || isReferenceMarket(value.referenceMarket)) ||
    !Array.isArray(value.limitations) ||
    value.limitations.length > 32 ||
    !value.limitations.every(isStableToken) ||
    !isSortedUnique(value.limitations)
  ) {
    return false;
  }
  if (!isRunSummary(value)) return false;
  const run = value as unknown as BacktestRunView;
  if (
    run.initialCashFen !== run.metrics.initialCashFen ||
    run.coverage.eventStart !== run.eventStart ||
    run.coverage.eventEnd !== run.eventEnd ||
    run.coverage.fillCount !== run.fillCount
  ) {
    return false;
  }
  const artifactCounts: Array<[number, BacktestResultAvailabilityView[keyof BacktestResultAvailabilityView]]> = [
    [run.coverage.decisionCount, run.availability.decisionDetails],
    [run.coverage.signalCount, run.availability.signalDetails],
    [run.coverage.outcomeCount, run.availability.executionOutcomeDetails],
    [run.coverage.equityPointCount, run.availability.equitySeries],
  ];
  return artifactCounts.every(
    ([count, availability]) => (count === 0) === (availability === "NOT_RECORDED"),
  );
}

function isRunSummary(value: Record<string, unknown>): value is BacktestRunSummaryView {
  if (
    !runSummaryKeys.every((key) => Object.hasOwn(value, key)) ||
    !isSha256(value.runId) ||
    !isSha256(value.reportHash) ||
    !(value.planVersionId === null || isCanonicalUuid(value.planVersionId)) ||
    !isSha256(value.planHash) ||
    !isSha256(value.datasetHash) ||
    !isAShareSymbol(value.symbol) ||
    value.status !== "COMPLETED" ||
    !isCalendarDate(value.eventStart) ||
    !isCalendarDate(value.eventEnd) ||
    value.eventStart > value.eventEnd ||
    !isResponseTime(value.completedAt) ||
    typeof value.pinned !== "boolean" ||
    !isNonnegativeSafeInteger(value.revision) ||
    !isNonnegativeSafeInteger(value.fillCount) ||
    !isMetrics(value.metrics) ||
    !isAvailability(value.availability)
  ) {
    return false;
  }
  return value.fillCount === value.metrics.tradeCount && isBoundedItem(value);
}

function isAvailability(value: unknown): value is BacktestResultAvailabilityView {
  return (
    isRecord(value) &&
    hasExactKeys(value, availabilityKeys) &&
    availabilityKeys.every(
      (key) =>
        typeof value[key] === "string" &&
        artifactAvailability.has(value[key] as BacktestResultAvailabilityView[typeof key]),
    )
  );
}

function isMetrics(value: unknown): value is BacktestMetricsView | ResearchMetricsView {
  if (isRecord(value) && value.schemaVersion === "explicit-simulation-metrics-v1") {
    return hasExactKeys(value, ["schemaVersion", "initialCashFen", "initialEquityFen", "finalCashFen", "finalEquityFen", "totalReturn", "totalCostFen", "tradeCount", "blockedCount", "valuationValid"]) &&
      isPositiveFenText(value.initialCashFen) &&
      (value.initialEquityFen === null || isPositiveFenText(value.initialEquityFen)) &&
      [value.finalCashFen, value.finalEquityFen].every((item) => item === null || isNonnegativeFenText(item)) &&
      (value.totalReturn === null || isDecimalText(value.totalReturn)) && isNonnegativeFenText(value.totalCostFen) &&
      isNonnegativeSafeInteger(value.tradeCount) && isNonnegativeSafeInteger(value.blockedCount) &&
      typeof value.valuationValid === "boolean" && (value.valuationValid || value.totalReturn === null);
  }
  if (
    !isRecord(value) ||
    !hasExactKeys(value, metricsKeys) ||
    !isPositiveFenText(value.initialCashFen) ||
    !isPositiveFenText(value.initialEquityFen) ||
    !isNonnegativeFenText(value.finalCashFen) ||
    !isNonnegativeFenText(value.finalEquityFen) ||
    !isDecimalText(value.totalReturn) ||
    !isDecimalBetween(value.maximumDrawdown, "0", "1") ||
    !isNonnegativeSafeInteger(value.tradeCount) ||
    !isNonnegativeSafeInteger(value.winningSellCount) ||
    value.winningSellCount > value.tradeCount ||
    !isDecimalBetween(value.winRate, "0", "1") ||
    !isNonnegativeFenText(value.turnoverFen) ||
    !isNonnegativeFenText(value.totalCostFen) ||
    !isFenText(value.realizedPnlFen) ||
    !isFenText(value.unrealizedPnlFen) ||
    !isNonnegativeSafeInteger(value.blockedCount) ||
    !isNonnegativeSafeInteger(value.skippedCount)
  ) {
    return false;
  }
  return decimalEqualsContextFraction(
    value.totalReturn,
    BigInt(value.finalEquityFen) - BigInt(value.initialEquityFen),
    BigInt(value.initialEquityFen),
  ) && compareDecimal(value.totalReturn, "-1") >= 0;
}

function isRunCoverage(value: unknown): value is BacktestRunCoverageView {
  return (
    isRecord(value) &&
    hasExactKeys(value, runCoverageKeys) &&
    isCalendarDate(value.eventStart) &&
    isCalendarDate(value.eventEnd) &&
    value.eventStart <= value.eventEnd &&
    [
      value.tradingDayCount,
      value.decisionCount,
      value.signalCount,
      value.orderCount,
      value.fillCount,
      value.outcomeCount,
      value.equityPointCount,
    ].every(isNonnegativeSafeInteger)
  );
}

function isExecutionConfigView(value: unknown): value is BacktestExecutionConfigView {
  return (
    isRecord(value) &&
    hasExactKeys(value, executionConfigViewKeys) &&
    isDecimalBetween(value.commissionRate, "0", "1") &&
    isNonnegativeFenText(value.minimumCommissionFen) &&
    isDecimalBetween(value.stampDutyRate, "0", "1") &&
    isDecimalBetween(value.transferFeeRate, "0", "1") &&
    isDecimalBetween(value.buySlippageBps, "0", "10000", false) &&
    isDecimalBetween(value.sellSlippageBps, "0", "10000", false)
  );
}

function isAssumptions(value: unknown): value is BacktestAssumptionsView {
  return (
    isRecord(value) &&
    hasExactKeys(value, assumptionsKeys) &&
    (value.eventRiskAssumption === "NO_EVENT_RISK" ||
      value.eventRiskAssumption === "MANUAL_EVENT_RISK") &&
    isExecutionConfigView(value.executionConfig) &&
    isSha256(value.executionConfigHash) &&
    value.priceAdjustmentPolicy === "NONE" &&
    value.historicalProfile === "TUSHARE_STK_MINS_241_END_V1"
  );
}

function isFormulaVersions(value: unknown): value is BacktestFormulaVersionsView {
  return (
    isRecord(value) &&
    hasExactKeys(value, formulaVersionKeys) &&
    formulaVersionKeys.every((key) => isStableToken(value[key]))
  );
}

function isRunPage(value: unknown): value is BacktestRunPage {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, runPageKeys) ||
    !isRunFilters(value.filters) ||
    !Array.isArray(value.items) ||
    value.items.length > MAX_PAGE_ITEMS ||
    !value.items.every(
      (item) =>
        validLoopRunSummary(item) || isRecord(item) && hasExactKeys(item, runSummaryKeys) && isRunSummary(item),
    ) ||
    !isPageFrame(value)
  ) {
    return false;
  }
  const positions = value.items.map((item) => `${item.completedAt}\0${item.runId}`);
  return (
    isDescendingUnique(positions) &&
    value.items.every((item) =>
      runMatchesFilters(item, value.filters as BacktestRunFiltersView),
    ) &&
    isBoundedPage(value)
  );
}

function isRunFilters(value: unknown): value is BacktestRunFiltersView {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, [...runFilterKeys, "eventEndFrom", "eventEndTo"]) &&
    runFilterKeys.every(key => Object.hasOwn(value, key)) &&
    (value.eventEndFrom == null || isCalendarDate(value.eventEndFrom)) &&
    (value.eventEndTo == null || isCalendarDate(value.eventEndTo)) &&
    (value.eventEndFrom == null || value.eventEndTo == null || String(value.eventEndFrom) <= String(value.eventEndTo)) &&
    (value.symbol === null || isAShareSymbol(value.symbol)) &&
    (value.planVersionId === null || isCanonicalUuid(value.planVersionId)) &&
    isNullableSha256(value.datasetHash) &&
    isNullableResponseTime(value.completedFrom) &&
    isNullableResponseTime(value.completedTo) &&
    (value.completedFrom === null ||
      value.completedTo === null ||
      timeKey(value.completedFrom) <= timeKey(value.completedTo)) &&
    (value.pinned === null || typeof value.pinned === "boolean")
  );
}

function runMatchesFilters(
  run: BacktestRunPage["items"][number],
  filters: BacktestRunFiltersView,
): boolean {
  return (
    (filters.symbol === null || run.symbol === filters.symbol) &&
    (filters.planVersionId === null || run.planVersionId === filters.planVersionId) &&
    (filters.datasetHash === null || run.datasetHash === filters.datasetHash) &&
    (filters.completedFrom === null || run.completedAt >= filters.completedFrom) &&
    (filters.completedTo === null || run.completedAt <= filters.completedTo) &&
    (filters.eventEndFrom == null || run.eventEnd >= filters.eventEndFrom) &&
    (filters.eventEndTo == null || run.eventEnd <= filters.eventEndTo) &&
    (filters.pinned === null || run.pinned === filters.pinned)
  );
}

function normalizeRunQuery(query: BacktestRunListQuery): BacktestRunListQuery {
  if (
    !isRecord(query) ||
    !hasOnlyKeys(query, [
      "completedFrom",
      "completedTo",
      "eventEndFrom",
      "eventEndTo",
      "cursor",
      "datasetHash",
      "limit",
      "pinned",
      "planVersionId",
      "symbol",
    ])
  ) {
    throw invalidRequest();
  }
  const completedFrom = normalizeOptionalRequestTime(query.completedFrom);
  const completedTo = normalizeOptionalRequestTime(query.completedTo);
  if ((query.eventEndFrom != null && !isCalendarDate(query.eventEndFrom)) ||
      (query.eventEndTo != null && !isCalendarDate(query.eventEndTo)) ||
      (query.eventEndFrom != null && query.eventEndTo != null && query.eventEndFrom > query.eventEndTo)) throw invalidRequest();
  const planVersionId =
    query.planVersionId == null ? null : normalizeUuid(query.planVersionId);
  if (
    (completedFrom !== null && completedTo !== null && completedFrom > completedTo) ||
    !(query.symbol == null || isAShareSymbol(query.symbol)) ||
    !isOptionalSha256(query.datasetHash) ||
    (query.planVersionId != null && planVersionId === null) ||
    !(query.pinned == null || query.pinned === "true" || query.pinned === "false") ||
    !isOptionalLimit(query.limit) ||
    !isOptionalCursor(query.cursor)
  ) {
    throw invalidRequest();
  }
  return {
    ...(completedFrom === null ? {} : { completedFrom }),
    ...(completedTo === null ? {} : { completedTo }),
    ...(query.eventEndFrom == null ? {} : { eventEndFrom: query.eventEndFrom }),
    ...(query.eventEndTo == null ? {} : { eventEndTo: query.eventEndTo }),
    ...(query.cursor == null ? {} : { cursor: query.cursor }),
    ...(query.datasetHash == null ? {} : { datasetHash: query.datasetHash }),
    ...(query.limit === undefined ? {} : { limit: query.limit }),
    ...(query.pinned == null ? {} : { pinned: query.pinned }),
    ...(planVersionId === null ? {} : { planVersionId }),
    ...(query.symbol == null ? {} : { symbol: query.symbol }),
  };
}

function runSearch(query: BacktestRunListQuery): URLSearchParams {
  const search = new URLSearchParams();
  appendQuery(search, "symbol", query.symbol);
  appendQuery(search, "planVersionId", query.planVersionId);
  appendQuery(search, "datasetHash", query.datasetHash);
  appendQuery(search, "completedFrom", query.completedFrom);
  appendQuery(search, "completedTo", query.completedTo);
  appendQuery(search, "eventEndFrom", query.eventEndFrom);
  appendQuery(search, "eventEndTo", query.eventEndTo);
  appendQuery(search, "pinned", query.pinned);
  appendQuery(search, "limit", query.limit);
  appendQuery(search, "cursor", query.cursor);
  return search;
}

function runPageMatchesQuery(page: BacktestRunPage, query: BacktestRunListQuery): boolean {
  return (
    page.limit === (query.limit ?? DEFAULT_PAGE_LIMIT) &&
    page.filters.symbol === (query.symbol ?? null) &&
    page.filters.planVersionId === (query.planVersionId ?? null) &&
    page.filters.datasetHash === (query.datasetHash ?? null) &&
    page.filters.completedFrom === (query.completedFrom ?? null) &&
    page.filters.completedTo === (query.completedTo ?? null) &&
    (page.filters.eventEndFrom ?? null) === (query.eventEndFrom ?? null) &&
    (page.filters.eventEndTo ?? null) === (query.eventEndTo ?? null) &&
    page.filters.pinned ===
      (query.pinned == null ? null : query.pinned === "true")
  );
}

function isFeeBreakdown(value: unknown): value is BacktestFeeBreakdownView {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, feeKeys) ||
    !feeKeys.every((key) => isNonnegativeFenText(value[key]))
  ) {
    return false;
  }
  const fee = value as unknown as BacktestFeeBreakdownView;
  return (
    BigInt(fee.totalFen) ===
    BigInt(fee.commissionFen) + BigInt(fee.stampDutyFen) + BigInt(fee.transferFeeFen)
  );
}

function isFill(value: unknown): value is BacktestFillPage["items"][number] {
  if (isRecord(value) && value.schemaVersion === "monitor-loop-fill-v1") return validLoopFill(value);
  if (
    !isRecord(value) ||
    !hasExactKeys(value, fillKeys) ||
    !isJobId(value.fillId) ||
    !isJobId(value.orderId) ||
    !isJobId(value.signalId) ||
    !isSha256(value.runId) ||
    !isSha256(value.planHash) ||
    !isSha256(value.datasetHash) ||
    !isSha256(value.resultHash) ||
    !isSha256(value.configHash) ||
    !isJobId(value.sourceBarId) ||
    !(value.side === "BUY" || value.side === "SELL") ||
    !isAShareSymbol(value.symbol) ||
    !(value.bucket === "CORE" || value.bucket === "TACTICAL") ||
    !(value.targetLotId === null || isJobId(value.targetLotId)) ||
    !isResponseTime(value.filledAt) ||
    !isPositiveBoardLot(value.requestedQuantity) ||
    !isPositiveBoardLot(value.quantity) ||
    value.quantity > value.requestedQuantity ||
    !isPositiveFenText(value.priceFen) ||
    !isPositiveFenText(value.notionalFen) ||
    !isFeeBreakdown(value.fees) ||
    !isFenText(value.cashDeltaFen) ||
    !isNonnegativeFenText(value.costBasisReleasedFen) ||
    !(value.realizedPnlFen === null || isFenText(value.realizedPnlFen))
  ) {
    return false;
  }
  const notional = BigInt(value.priceFen) * BigInt(value.quantity);
  const fees = BigInt(value.fees.totalFen);
  const cashDelta = BigInt(value.cashDeltaFen);
  const released = BigInt(value.costBasisReleasedFen);
  if (BigInt(value.notionalFen) !== notional) return false;
  if (value.side === "BUY") {
    return (
      cashDelta === -(notional + fees) &&
      released === 0n &&
      value.realizedPnlFen === null &&
      value.targetLotId === null &&
      isBoundedItem(value)
    );
  }
  return (
    cashDelta === notional - fees &&
    value.targetLotId !== null &&
    value.realizedPnlFen !== null &&
    BigInt(value.realizedPnlFen) === cashDelta - released &&
    isBoundedItem(value)
  );
}

function isFillPage(value: unknown): value is BacktestFillPage {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, fillPageKeys) ||
    !isRecord(value.filters) ||
    !hasExactKeys(value.filters, [] as const) ||
    !Array.isArray(value.items) ||
    value.items.length > MAX_PAGE_ITEMS ||
    !value.items.every(isFill) ||
    !isPageFrame(value)
  ) {
    return false;
  }
  const positions = value.items.map((item) => `${item.filledAt}\0${item.fillId}`);
  return isAscendingUnique(positions) && isBoundedPage(value);
}

function isDetailPage(value: unknown): value is BacktestDetailPage {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, detailPageKeys) ||
    !isDetailKind(value.kind) ||
    !isArtifactAvailability(value.availability) ||
    !isRecord(value.filters) ||
    !hasExactKeys(value.filters, detailFilterKeys) ||
    value.filters.kind !== value.kind ||
    !Array.isArray(value.items) ||
    value.items.length > MAX_PAGE_ITEMS ||
    !value.items.every((item) => isDetail(item) && item.kind === value.kind) ||
    !isPageFrame(value)
  ) {
    return false;
  }
  if (value.availability === "AVAILABLE") {
    if (value.items.length === 0) return false;
  } else if (value.items.length > 0 || value.nextCursor !== null || value.hasMore) {
    return false;
  }
  const positions = value.items.map((item) => `${item.eventAt}\0${item.detailId}`);
  return isAscendingUnique(positions) && isBoundedPage(value);
}

function isDetail(value: unknown): value is BacktestDetailView {
  if (isRecord(value) && value.schemaVersion === "monitor-loop-event-v2") return validScheduledEvent(value);
  if (isRecord(value) && value.schemaVersion === "monitor-loop-event-v1") return validLoopEvent(value);
  if (!isRecord(value)) return false;
  if (isResearchDetail(value)) return isDetailBase(value) && isBoundedItem(value);
  if (value.kind === "SIGNAL") return isSignal(value);
  if (value.kind === "EXECUTION_OUTCOME") return isExecutionOutcome(value);
  return value.kind === "DECISION" && isDecision(value);
}

function isDetailBase(value: Record<string, unknown>): boolean {
  return (
    isJobId(value.detailId) && isSha256(value.runId) && isResponseTime(value.eventAt)
  );
}

function isDecision(value: Record<string, unknown>): value is BacktestDecisionView {
  return (
    hasExactKeys(value, decisionKeys) &&
    isDetailBase(value) &&
    value.kind === "DECISION" &&
    isSha256(value.resultHash) &&
    isAuthoritativeDecision(value.decision) &&
    value.resultHash === value.decision.resultHash &&
    value.eventAt === value.decision.evaluatedAt &&
    isBoundedItem(value)
  );
}

function isAuthoritativeDecision(
  value: unknown,
): value is BacktestAuthoritativeDecisionView {
  if (
    !isRecord(value) ||
    !(hasExactKeys(value, authoritativeDecisionKeys) ||
      hasExactKeys(value, authoritativeDecisionWithoutReferenceMarketKeys)) ||
    !isAShareSymbol(value.symbol) ||
    !isSha256(value.resultHash) ||
    !(typeof value.planId === "string" && value.planId.length >= 1 && value.planId.length <= 128) ||
    !isPositiveSafeInteger(value.planVersion) ||
    !isSha256(value.planHash) ||
    !isResponseTime(value.evaluatedAt) ||
    !(value.marketDataAt === null || isResponseTime(value.marketDataAt)) ||
    !(value.dataAgeSeconds === null || isNonnegativeSafeInteger(value.dataAgeSeconds)) ||
    !(value.priceFen === null || isPositiveFenText(value.priceFen)) ||
    !(typeof value.zone === "string" && decisionZones.has(value.zone as never)) ||
    !(typeof value.signalType === "string" && decisionSignalTypes.has(value.signalType as never)) ||
    !isPosition(value.position) ||
    !(value.episodeStatus === null ||
      (typeof value.episodeStatus === "string" && episodeStatuses.has(value.episodeStatus as never))) ||
    !(value.episodeLowFen === null || isPositiveFenText(value.episodeLowFen)) ||
    !(typeof value.riskStatus === "string" && riskStatuses.has(value.riskStatus as never)) ||
    !(value.riskBreachTradeDate === null || isCalendarDate(value.riskBreachTradeDate)) ||
    !isDataHealth(value.dataHealth) ||
    !Array.isArray(value.evidence) ||
    value.evidence.length > 50 ||
    !value.evidence.every((item) => isDecisionEvidence(item)) ||
    !isNextStep(value.nextStep)
  ) {
    return false;
  }
  if (
    Object.hasOwn(value, "referenceMarket") &&
    !(value.referenceMarket === null || isDecisionReferenceMarket(value.referenceMarket))
  ) {
    return false;
  }
  const marketValues = [value.marketDataAt, value.dataAgeSeconds, value.priceFen];
  if (marketValues.some((item) => item === null) && marketValues.some((item) => item !== null)) {
    return false;
  }
  const evaluatedAt = timeKey(value.evaluatedAt);
  if (
    value.marketDataAt !== null &&
    !matchesIntegerSecondAge(evaluatedAt, timeKey(value.marketDataAt), value.dataAgeSeconds as number)
  ) {
    return false;
  }
  if (
    value.dataHealth.latestBarEnd !== null &&
    !matchesIntegerSecondAge(
      evaluatedAt,
      timeKey(value.dataHealth.latestBarEnd),
      value.dataHealth.dataAgeSeconds as number,
    )
  ) {
    return false;
  }
  if ((value.episodeStatus === null) !== (value.episodeLowFen === null)) return false;
  if (
    (value.riskStatus === "CLEAR" && value.riskBreachTradeDate !== null) ||
    (value.riskStatus !== "CLEAR" && value.riskBreachTradeDate === null)
  ) {
    return false;
  }
  if (
    value.riskBreachTradeDate !== null &&
    value.riskBreachTradeDate > value.evaluatedAt.slice(0, 10)
  ) {
    return false;
  }
  return !(
    actionableSignalTypes.has(value.signalType as never) && value.dataHealth.status !== "LIVE"
  );
}

function isDecisionReferenceMarket(value: unknown): boolean {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, decisionReferenceMarketKeys) ||
    !isMarketIndexCode(value.indexCode) ||
    !isNullableSha256(value.snapshotHash) ||
    !isNullableResponseTime(value.dataAt) ||
    !isMarketIndexHealth(value.health) ||
    !Array.isArray(value.evidence) ||
    value.evidence.length < 1 ||
    value.evidence.length > 50 ||
    !value.evidence.every((item) => isIndexConditionEvidence(item, value.indexCode))
  ) {
    return false;
  }
  const paths = value.evidence.map((item) => (item as Record<string, unknown>).planPath as string);
  if (!isSortedUnique(paths)) return false;
  return (
    value.health !== "LIVE" ||
    (value.snapshotHash !== null &&
      value.dataAt !== null &&
      value.evidence.every(
        (item) => (item as Record<string, unknown>).snapshotHash === value.snapshotHash,
      ))
  );
}

function isIndexConditionEvidence(value: unknown, indexCode: unknown): boolean {
  if (
    !isMarketIndexCode(indexCode) ||
    !isRecord(value) ||
    !hasExactKeys(value, indexConditionEvidenceKeys) ||
    !isPlanPath(value.planPath) ||
    !(typeof value.conditionType === "string" && indexConditionTypes.has(value.conditionType as never)) ||
    value.indexCode !== indexCode ||
    value.mappingVersion !== "board-index-map-v1" ||
    !isNullableSha256(value.snapshotHash) ||
    !isResponseTime(value.decisionCutoff) ||
    !isNullableResponseTime(value.dataCutoff) ||
    !(value.formulaId === "SMA" || value.formulaId === "SMA_LOOKBACK" || value.formulaId === "RETURN") ||
    !isNullableSha256(value.formulaDefinitionHash) ||
    !Array.isArray(value.parameters) ||
    value.parameters.length > 8 ||
    !Array.isArray(value.missingInputs) ||
    value.missingInputs.length > 7 ||
    !value.missingInputs.every(
      (item) => typeof item === "string" && missingInputCodes.has(item as never),
    ) ||
    !(value.unit === "POINTS" || value.unit === "RATIO") ||
    !(value.outcome === "SATISFIED" ||
      value.outcome === "UNSATISFIED" ||
      value.outcome === "MISSING_INPUT")
  ) {
    return false;
  }
  const missing = value.outcome === "MISSING_INPUT";
  return missing
    ? value.missingInputs.length > 0 &&
        value.actualValue === null &&
        value.comparisonValue === null
    : value.missingInputs.length === 0 &&
        isDecimalText(value.actualValue) &&
        isDecimalText(value.comparisonValue) &&
        value.snapshotHash !== null &&
        value.dataCutoff !== null &&
        value.formulaDefinitionHash !== null;
}

function isPosition(value: unknown): value is BacktestPositionSummaryView {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, positionKeys) ||
    !positionKeys.every((key) => isNonnegativeSafeInteger(value[key]))
  ) {
    return false;
  }
  const position = value as unknown as BacktestPositionSummaryView;
  return (
    position.totalQuantity === position.coreQuantity + position.tacticalQuantity &&
    position.sellableCoreQuantity <= position.coreQuantity &&
    position.sellableTacticalQuantity <= position.tacticalQuantity
  );
}

function isDataHealth(value: unknown): value is BacktestDataHealthView {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, dataHealthKeys) ||
    !(typeof value.status === "string" && dataHealthStatuses.has(value.status as never)) ||
    !(value.latestBarEnd === null || isResponseTime(value.latestBarEnd)) ||
    !(value.dataAgeSeconds === null || isNonnegativeSafeInteger(value.dataAgeSeconds)) ||
    typeof value.requiredDataComplete !== "boolean" ||
    typeof value.fresh !== "boolean"
  ) {
    return false;
  }
  if ((value.latestBarEnd === null) !== (value.dataAgeSeconds === null)) return false;
  if (value.fresh && value.latestBarEnd === null) return false;
  if (
    value.status === "LIVE" &&
    (!value.fresh || !value.requiredDataComplete || value.latestBarEnd === null)
  ) {
    return false;
  }
  if (value.status === "STALE" && value.fresh) return false;
  return !(
    (value.status === "GAPPED" || value.status === "BLOCKED") &&
    value.requiredDataComplete
  );
}

function isNextStep(value: unknown): value is BacktestNextStepView {
  return (
    isRecord(value) &&
    hasExactKeys(value, nextStepKeys) &&
    typeof value.code === "string" &&
    nextStepCodes.has(value.code as never) &&
    (value.notBefore === null ||
      isCalendarDate(value.notBefore) ||
      isResponseTime(value.notBefore)) &&
    Array.isArray(value.requiredInputs) &&
    value.requiredInputs.length <= 16 &&
    value.requiredInputs.every(
      (item) => typeof item === "string" && missingInputCodes.has(item as never),
    ) &&
    new Set(value.requiredInputs).size === value.requiredInputs.length
  );
}

function isDecisionEvidence(value: unknown, depth = 0): value is BacktestDecisionEvidenceView {
  if (
    depth > 32 ||
    !isRecord(value) ||
    !hasExactKeys(value, evidenceKeys) ||
    !(typeof value.kind === "string" && evidenceKinds.has(value.kind as never)) ||
    !isDecisionCode(value.code) ||
    !(typeof value.outcome === "string" && conditionOutcomes.has(value.outcome as never)) ||
    !Array.isArray(value.facts) ||
    value.facts.length > 512 ||
    !value.facts.every(isEvidenceFact) ||
    !Array.isArray(value.missingInputs) ||
    value.missingInputs.length > 16 ||
    !value.missingInputs.every(
      (item) => typeof item === "string" && missingInputCodes.has(item as never),
    ) ||
    !Array.isArray(value.children) ||
    value.children.length > 50 ||
    !value.children.every((child) => isDecisionEvidence(child, depth + 1))
  ) {
    return false;
  }
  if (
    new Set(value.facts.map((fact) => fact.key)).size !== value.facts.length ||
    new Set(value.missingInputs).size !== value.missingInputs.length
  ) {
    return false;
  }
  if (value.outcome === "MISSING_INPUT") {
    return (
      value.missingInputs.length > 0 ||
      value.children.some((child) => child.outcome === "MISSING_INPUT")
    );
  }
  return value.missingInputs.length === 0;
}

function isEvidenceFact(value: unknown): value is BacktestEvidenceFactView {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, factKeys) ||
    !(typeof value.key === "string" && /^[a-z][a-z0-9_]{0,63}$/.test(value.key)) ||
    !(typeof value.unit === "string" && evidenceUnits.has(value.unit as never))
  ) {
    return false;
  }
  if (value.unit === "BOOLEAN") return typeof value.value === "boolean";
  if (value.unit === "DATE") return isCalendarDate(value.value);
  if (value.unit === "DATETIME") return isResponseTime(value.value);
  if (value.unit === "CODE") return isDecisionCode(value.value);
  if (value.unit === "FEN" || value.unit === "BARS" || value.unit === "COUNT") {
    return typeof value.value === "number" && Number.isSafeInteger(value.value);
  }
  if (value.unit === "RATIO" || value.unit === "YUAN" || value.unit === "POINTS") {
    return isDecimalText(value.value);
  }
  return (
    value.unit === "SHARES" &&
    ((typeof value.value === "number" && Number.isSafeInteger(value.value)) ||
      isDecimalText(value.value))
  );
}

function matchesIntegerSecondAge(
  evaluatedAt: bigint,
  sourceAt: bigint,
  seconds: number,
): boolean {
  const delta = evaluatedAt - sourceAt;
  return delta >= 0n && delta / 1_000_000n === BigInt(seconds);
}

function isSignal(value: Record<string, unknown>): value is BacktestSignalView {
  if (
    !hasExactKeys(value, signalKeys) ||
    !isDetailBase(value) ||
    value.kind !== "SIGNAL" ||
    !isJobId(value.signalId) ||
    !isSha256(value.resultHash) ||
    !isActionableSignalType(value.signalType) ||
    !isAShareSymbol(value.symbol) ||
    !(value.quantity === null || isPositiveBoardLot(value.quantity)) ||
    !(value.bucket === null || value.bucket === "CORE" || value.bucket === "TACTICAL") ||
    !(value.targetLotId === null || isJobId(value.targetLotId)) ||
    !isJobId(value.causeId)
  ) {
    return false;
  }
  if (value.signalType === "RISK_BREACH") {
    return value.quantity === null && value.bucket === null && value.targetLotId === null;
  }
  if (value.quantity === null || value.bucket === null) return false;
  const buy =
    value.signalType === "BUY_CORE_READY" || value.signalType === "BUY_TACTICAL_READY";
  if (buy === (value.targetLotId !== null)) return false;
  if (value.signalType === "BUY_CORE_READY" && value.bucket !== "CORE") return false;
  if (
    (value.signalType === "BUY_TACTICAL_READY" ||
      value.signalType === "PRESSURE_REDUCE_READY") &&
    value.bucket !== "TACTICAL"
  ) {
    return false;
  }
  return isBoundedItem(value);
}

function isExecutionOutcome(
  value: Record<string, unknown>,
): value is BacktestExecutionOutcomeView {
  if (
    !hasExactKeys(value, outcomeKeys) ||
    !isDetailBase(value) ||
    value.kind !== "EXECUTION_OUTCOME" ||
    !isJobId(value.outcomeId) ||
    !isJobId(value.signalId) ||
    !(value.orderId === null || isJobId(value.orderId)) ||
    !(value.sourceBarId === null || isJobId(value.sourceBarId)) ||
    !isExecutionStatus(value.status) ||
    !(value.reason === null || isUnfilledReason(value.reason)) ||
    !(value.fillId === null || isJobId(value.fillId))
  ) {
    return false;
  }
  if (value.status === "FILLED") {
    return (
      value.fillId !== null &&
      value.reason === null &&
      value.orderId !== null &&
      value.sourceBarId !== null &&
      isBoundedItem(value)
    );
  }
  if (value.fillId !== null || value.reason === null) return false;
  if (value.status === "UNFILLED") {
    return (
      value.orderId !== null &&
      ((value.reason === "NO_NEXT_MINUTE") === (value.sourceBarId === null)) &&
      isBoundedItem(value)
    );
  }
  return value.orderId === null && value.sourceBarId === null && isBoundedItem(value);
}

function isEquitySeries(value: unknown): value is BacktestEquitySeries {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, equitySeriesKeys) ||
    !isArtifactAvailability(value.availability) ||
    !Array.isArray(value.items) ||
    value.items.length > 2_000 ||
    !value.items.every(isEquityPoint) ||
    (value.availability === "AVAILABLE") !== (value.items.length > 0)
  ) {
    return false;
  }
  const positions = value.items.map((item) => `${item.markedAt}\0${item.snapshotId}`);
  return isAscendingUnique(positions) && isBoundedPage(value);
}

function isEquityPoint(value: unknown): value is BacktestEquityPointView | ResearchEquityView {
  if (isRecord(value) && value.schemaVersion === "unified-research-equity-v1") {
    return hasExactKeys(value, ["schemaVersion", "snapshotId", "runId", "markedAt", "markPriceFen", "cashFen", "positionQuantity", "marketValueFen", "equityFen", "valuationValid", "blockers"]) &&
      isSha256(value.snapshotId) && isSha256(value.runId) && isResponseTime(value.markedAt) &&
      [value.markPriceFen, value.cashFen, value.marketValueFen, value.equityFen].every((item) => item === null || isNonnegativeFenText(item)) &&
      (value.positionQuantity === null || isNonnegativeSafeInteger(value.positionQuantity)) &&
      typeof value.valuationValid === "boolean" && Array.isArray(value.blockers) && value.blockers.every((item) => typeof item === "string") &&
      (value.valuationValid || value.equityFen === null) && isBoundedItem(value);
  }
  if (
    !isRecord(value) ||
    !hasExactKeys(value, equityPointKeys) ||
    !isJobId(value.snapshotId) ||
    !isSha256(value.runId) ||
    !isAShareSymbol(value.symbol) ||
    !isResponseTime(value.markedAt) ||
    !isPositiveFenText(value.markPriceFen) ||
    !isNonnegativeFenText(value.cashFen) ||
    !isNonnegativeSafeInteger(value.positionQuantity) ||
    value.positionQuantity % 100 !== 0 ||
    !isNonnegativeFenText(value.marketValueFen) ||
    !isNonnegativeFenText(value.costBasisFen) ||
    !isFenText(value.realizedPnlFen) ||
    !isFenText(value.unrealizedPnlFen) ||
    !isNonnegativeFenText(value.totalCostFen) ||
    !isNonnegativeFenText(value.equityFen)
  ) {
    return false;
  }
  const marketValue = BigInt(value.markPriceFen) * BigInt(value.positionQuantity);
  return (
    BigInt(value.marketValueFen) === marketValue &&
    BigInt(value.unrealizedPnlFen) === marketValue - BigInt(value.costBasisFen) &&
    BigInt(value.equityFen) === BigInt(value.cashFen) + marketValue &&
    isBoundedItem(value)
  );
}

function normalizeResultPageQuery(query: BacktestFillListQuery): BacktestFillListQuery {
  if (
    !isRecord(query) ||
    !hasOnlyKeys(query, ["cursor", "limit"]) ||
    !isOptionalLimit(query.limit) ||
    !isOptionalCursor(query.cursor)
  ) {
    throw invalidRequest();
  }
  return { ...query };
}

function normalizeMarketIndexSeriesQuery(
  query: BacktestMarketIndexSeriesQuery,
): BacktestMarketIndexSeriesQuery {
  if (
    !isRecord(query) ||
    !hasOnlyKeys(query, ["endOn", "limit", "startOn"]) ||
    !(query.startOn == null || isCalendarDate(query.startOn)) ||
    !(query.endOn == null || isCalendarDate(query.endOn)) ||
    !(query.limit === undefined || isIntegerBetween(query.limit, 1, 512)) ||
    (query.startOn != null && query.endOn != null && query.startOn > query.endOn)
  ) {
    throw invalidRequest();
  }
  return {
    ...(query.startOn == null ? {} : { startOn: query.startOn }),
    ...(query.endOn == null ? {} : { endOn: query.endOn }),
    ...(query.limit === undefined ? {} : { limit: query.limit }),
  };
}

function normalizeDetailQuery(query: BacktestDetailListQuery): BacktestDetailListQuery {
  if (
    !isRecord(query) ||
    !hasOnlyKeys(query, ["cursor", "kind", "limit"]) ||
    !isDetailKind(query.kind) ||
    !isOptionalLimit(query.limit) ||
    !isOptionalCursor(query.cursor)
  ) {
    throw invalidRequest();
  }
  return {
    ...(query.cursor == null ? {} : { cursor: query.cursor }),
    kind: query.kind,
    ...(query.limit === undefined ? {} : { limit: query.limit }),
  };
}

function resultPageSearch(query: BacktestFillListQuery): URLSearchParams {
  const search = new URLSearchParams();
  appendQuery(search, "limit", query.limit);
  appendQuery(search, "cursor", query.cursor);
  return search;
}

function detailSearch(query: BacktestDetailListQuery): URLSearchParams {
  const search = new URLSearchParams();
  appendQuery(search, "kind", query.kind);
  appendQuery(search, "limit", query.limit);
  appendQuery(search, "cursor", query.cursor);
  return search;
}

function marketIndexSeriesSearch(query: BacktestMarketIndexSeriesQuery): URLSearchParams {
  const search = new URLSearchParams();
  appendQuery(search, "startOn", query.startOn);
  appendQuery(search, "endOn", query.endOn);
  appendQuery(search, "limit", query.limit);
  return search;
}

function normalizeRunCommand(value: unknown): BacktestRunCommand | PreparedBacktestRunCommand | ScheduledPreparedBacktestRunCommand {
  if (isRecord(value) && "preparationId" in value) return normalizePreparedRunCommand(value);
  if (
    !isRecord(value) ||
    !hasExactKeys(value, value.researchInput === undefined ? runCommandKeys.filter((key) => key !== "researchInput") : runCommandKeys) ||
    !(value.researchInput === undefined || isResearchInput(value.researchInput)) ||
    !isSha256(value.datasetHash) ||
    !isPositiveSafeInteger(value.initialCashFen) ||
    !Array.isArray(value.initialLots) ||
    value.initialLots.length > MAX_INITIAL_LOTS ||
    !(value.eventRiskAssumption === "NO_EVENT_RISK" ||
      value.eventRiskAssumption === "MANUAL_EVENT_RISK")
  ) {
    throw invalidRequest();
  }
  const planVersionId = normalizeUuid(value.planVersionId);
  const executionConfig = normalizeExecutionConfig(value.executionConfig);
  const initialLots = value.initialLots.map(normalizeInitialLot);
  if (planVersionId === null || new Set(initialLots.map((lot) => lot.lotKey)).size !== initialLots.length) {
    throw invalidRequest();
  }
  const totalInitialFen = initialLots.reduce(
    (total, lot) => total + BigInt(lot.costBasisFen),
    BigInt(value.initialCashFen),
  );
  if (totalInitialFen > BigInt(Number.MAX_SAFE_INTEGER)) throw invalidRequest();
  initialLots.sort((left, right) => {
    const leftKey = `${left.bucket}\0${left.acquiredTradeDate}\0${left.lotKey}`;
    const rightKey = `${right.bucket}\0${right.acquiredTradeDate}\0${right.lotKey}`;
    return leftKey < rightKey ? -1 : leftKey > rightKey ? 1 : 0;
  });
  return {
    datasetHash: value.datasetHash,
    eventRiskAssumption: value.eventRiskAssumption,
    ...(value.researchInput === undefined ? {} : { researchInput: value.researchInput }),
    executionConfig,
    initialCashFen: value.initialCashFen,
    initialLots,
    planVersionId,
  };
}

function normalizePreparedRunCommand(value: Record<string, unknown>): PreparedBacktestRunCommand | ScheduledPreparedBacktestRunCommand {
  const keys = ["preparationId", "manifestHash", "response", "costs"];
  if (value.schemaVersion === "prepared-loop-plan-v2") keys.push("schemaVersion");
  if (value.endDate !== undefined) keys.push("endDate");
  const response = value.response;
  const costs = value.costs;
  const responseDelaySeconds = isRecord(response) ? response.responseDelaySeconds ?? 0 : null;
  if (!hasExactKeys(value, keys) || !isJobId(value.preparationId) || !isSha256(value.manifestHash) ||
      value.endDate !== undefined && !isCalendarDate(value.endDate) ||
      !isRecord(response) || !hasExactKeys(response, response.responseDelaySeconds === undefined
        ? ["mode"] : ["mode", "responseDelaySeconds"]) ||
      !(response.mode === "FOLLOW_REMINDERS" || response.mode === "OBSERVE_ONLY") ||
      !isNonnegativeSafeInteger(responseDelaySeconds) ||
      !isRecord(costs) || !hasExactKeys(costs, ["commissionRate", "minimumCommissionFen",
        "stampDutyRate", "transferFeeRate", "buySlippageFen", "sellSlippageFen"]) ||
      !isDecimalBetween(costs.commissionRate, "0", "1") ||
      !isDecimalBetween(costs.stampDutyRate, "0", "1") ||
      !isDecimalBetween(costs.transferFeeRate, "0", "1") ||
      !isNonnegativeSafeInteger(costs.minimumCommissionFen) ||
      !isNonnegativeSafeInteger(costs.buySlippageFen) || !isNonnegativeSafeInteger(costs.sellSlippageFen)) {
    throw invalidRequest();
  }
  return {
    ...(value.schemaVersion === "prepared-loop-plan-v2" ? { schemaVersion: "prepared-loop-plan-v2" as const } : {}),
    preparationId: value.preparationId,
    manifestHash: value.manifestHash,
    response: { mode: response.mode, responseDelaySeconds },
    costs: { commissionRate: costs.commissionRate, minimumCommissionFen: costs.minimumCommissionFen,
      stampDutyRate: costs.stampDutyRate, transferFeeRate: costs.transferFeeRate,
      buySlippageFen: costs.buySlippageFen, sellSlippageFen: costs.sellSlippageFen },
    ...(value.endDate === undefined ? {} : { endDate: value.endDate }),
  };
}

function normalizeExecutionConfig(value: unknown): BacktestExecutionConfigInput {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, executionConfigInputKeys) ||
    !isDecimalBetween(value.commissionRate, "0", "1") ||
    !isNonnegativeSafeInteger(value.minimumCommissionFen) ||
    !isDecimalBetween(value.stampDutyRate, "0", "1") ||
    !isDecimalBetween(value.transferFeeRate, "0", "1") ||
    !isDecimalBetween(value.buySlippageBps, "0", "10000", false) ||
    !isDecimalBetween(value.sellSlippageBps, "0", "10000", false)
  ) {
    throw invalidRequest();
  }
  return {
    buySlippageBps: value.buySlippageBps,
    commissionRate: value.commissionRate,
    minimumCommissionFen: value.minimumCommissionFen,
    sellSlippageBps: value.sellSlippageBps,
    stampDutyRate: value.stampDutyRate,
    transferFeeRate: value.transferFeeRate,
  };
}

function normalizeInitialLot(value: unknown): BacktestInitialLotInput {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, initialLotKeys) ||
    !isLotKey(value.lotKey) ||
    !(value.bucket === "CORE" || value.bucket === "TACTICAL") ||
    !isCalendarDate(value.acquiredTradeDate) ||
    !isPositiveBoardLot(value.quantity) ||
    !isPositiveSafeInteger(value.costBasisFen)
  ) {
    throw invalidRequest();
  }
  return {
    acquiredTradeDate: value.acquiredTradeDate,
    bucket: value.bucket,
    costBasisFen: value.costBasisFen,
    lotKey: value.lotKey,
    quantity: value.quantity,
  };
}

function normalizeRunPinCommand(value: unknown): BacktestRunPinCommand {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, runPinKeys) ||
    typeof value.pinned !== "boolean" ||
    !isNonnegativeSafeInteger(value.expectedRevision)
  ) {
    throw invalidRequest();
  }
  return { expectedRevision: value.expectedRevision, pinned: value.pinned };
}

function normalizeDataSyncCommand(value: unknown): BacktestDataSyncCommand {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, syncCommandKeys) ||
    value.allowNetwork !== true ||
    typeof value.refresh !== "boolean"
  ) {
    throw invalidRequest();
  }
  return {
    allowNetwork: true,
    refresh: value.refresh,
    scope: normalizeDatasetScope(value.scope),
  };
}

function normalizeDatasetVerificationCommand(value: unknown): BacktestDatasetVerificationCommand {
  if (!isRecord(value) || !hasExactKeys(value, verificationCommandKeys)) {
    throw invalidRequest();
  }
  return { scope: normalizeDatasetScope(value.scope) };
}

function normalizeDatasetScope(value: unknown): BacktestDatasetScopeInput {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, scopeInputKeys) ||
    value.adjustmentPolicy !== "NONE" ||
    value.historicalProfile !== "TUSHARE_STK_MINS_241_END_V1" ||
    !isCalendarDate(value.start) ||
    !isCalendarDate(value.end) ||
    !isCalendarDate(value.warmupStart) ||
    !Array.isArray(value.symbols) ||
    value.symbols.length < 1 ||
    value.symbols.length > 10 ||
    !value.symbols.every(isAShareSymbol) ||
    new Set(value.symbols).size !== value.symbols.length ||
    value.start > value.end ||
    value.end > calendarYearsAfter(value.start, 5) ||
    value.warmupStart > value.start ||
    value.start > calendarYearsAfter(value.warmupStart, 2)
  ) {
    throw invalidRequest();
  }
  return {
    adjustmentPolicy: "NONE",
    end: value.end,
    historicalProfile: "TUSHARE_STK_MINS_241_END_V1",
    start: value.start,
    symbols: [...value.symbols].sort(),
    warmupStart: value.warmupStart,
  };
}

function normalizeCancellationCommand(value: unknown): BacktestJobCancellationCommand {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, cancellationCommandKeys) ||
    !isJobId(value.jobId)
  ) {
    throw invalidRequest();
  }
  return { jobId: value.jobId };
}

function requestInit(method: "GET" | "POST" | "PATCH", options?: BacktestRequestOptions): RequestInit {
  const init: RequestInit = { headers: { Accept: "application/json" }, method };
  if (options?.signal !== undefined) init.signal = options.signal;
  return init;
}

function validateResponse<T>(status: number, validate: () => T): T {
  try {
    return validate();
  } catch (error) {
    if (error instanceof ApiClientError) throw error;
    throw invalidResponse(status);
  }
}

function parseRetryAfter(headers: Headers): number | null {
  const value = headers.get("Retry-After");
  return value === null ? null : value === String(RETRY_AFTER_SECONDS) ? RETRY_AFTER_SECONDS : NaN;
}

function isPageFrame(value: Record<string, unknown>): boolean {
  return (
    isPageLimit(value.limit) &&
    Array.isArray(value.items) &&
    value.items.length <= value.limit &&
    (value.nextCursor === null || isCursor(value.nextCursor)) &&
    typeof value.hasMore === "boolean" &&
    value.hasMore === (value.nextCursor !== null) &&
    isCursor(value.highWatermark)
  );
}

function expectedPublicError(status: string): string | null {
  if (status === "FAILED") return "The job failed.";
  if (status === "CANCELLED") return "The job was cancelled.";
  return null;
}

function isNullablePublicError(value: unknown): value is string | null {
  return value === null || value === "The job failed." || value === "The job was cancelled.";
}

function isBlockers(value: unknown): value is string[] {
  return (
    Array.isArray(value) &&
    value.length <= 100 &&
    value.every((item) => typeof item === "string" && /^[A-Z][A-Z0-9_]{0,127}$/.test(item)) &&
    isSortedUnique(value)
  );
}

function isNullableEnumArray<T extends string>(
  value: unknown,
  validate: (item: unknown) => item is T,
  maximum: number,
): value is T[] | null {
  return (
    value === null ||
    (Array.isArray(value) &&
      value.length >= 1 &&
      value.length <= maximum &&
      value.every(validate) &&
      isSortedUnique(value))
  );
}

function normalizeEnumQuery<T extends string>(
  value: T[] | null | undefined,
  validate: (item: unknown) => item is T,
  maximum: number,
): T[] | null {
  if (value == null) return null;
  if (!Array.isArray(value) || value.length === 0 || !value.every(validate)) {
    throw invalidRequest();
  }
  const normalized = [...new Set(value)].sort();
  if (normalized.length > maximum) throw invalidRequest();
  return normalized;
}

function normalizeOptionalRequestTime(value: string | null | undefined): string | null {
  if (value == null) return null;
  const normalized = normalizeShanghaiDateTime(value);
  if (normalized === null) throw invalidRequest();
  return normalized;
}

function exactKeys<T>() {
  return <K extends readonly (keyof T)[]>(
    keys: K & (Exclude<keyof T, K[number]> extends never ? unknown : never),
  ): K => keys;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys<T extends string>(
  value: Record<string, unknown>,
  keys: readonly T[],
): boolean {
  return Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key));
}

function hasOnlyKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const allowed = new Set(keys);
  return Object.keys(value).every((key) => allowed.has(key));
}

function isJobKind(value: unknown): value is BacktestJobView["kind"] {
  return typeof value === "string" && jobKinds.has(value as BacktestJobView["kind"]);
}

function isJobStatus(value: unknown): value is BacktestJobView["status"] {
  return typeof value === "string" && jobStatuses.has(value as BacktestJobView["status"]);
}

function isJobPhase(value: unknown): value is BacktestJobProgressView["phase"] {
  return typeof value === "string" && jobPhases.has(value as BacktestJobProgressView["phase"]);
}

function isProgressUnit(value: unknown): value is BacktestJobProgressView["unit"] {
  return typeof value === "string" && progressUnits.has(value as BacktestJobProgressView["unit"]);
}

function isTerminalStatus(value: BacktestJobView["status"]): boolean {
  return value === "COMPLETED" || value === "FAILED" || value === "CANCELLED";
}

function isAttempt(value: unknown): value is number {
  return isNonnegativeSafeInteger(value) && value <= MAX_JOB_ATTEMPT;
}

function isNonnegativeSafeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isPositiveSafeInteger(value: unknown): value is number {
  return isNonnegativeSafeInteger(value) && value > 0;
}

function isIntegerBetween(value: unknown, minimum: number, maximum: number): value is number {
  return (
    typeof value === "number" &&
    Number.isSafeInteger(value) &&
    value >= minimum &&
    value <= maximum
  );
}

function isPositiveBoardLot(value: unknown): value is number {
  return isPositiveSafeInteger(value) && value % 100 === 0;
}

function isPageLimit(value: unknown): value is number {
  return isNonnegativeSafeInteger(value) && value >= 1 && value <= MAX_PAGE_ITEMS;
}

function isOptionalLimit(value: unknown): boolean {
  return value === undefined || isPageLimit(value);
}

function isSha256(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
}

function isNullableSha256(value: unknown): value is string | null {
  return value === null || isSha256(value);
}

function isOptionalSha256(value: unknown): boolean {
  return value === undefined || value === null || isSha256(value);
}

function isJobId(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length >= 1 &&
    value.length <= 128 &&
    /^[A-Za-z0-9][A-Za-z0-9._:-]*$/.test(value)
  );
}

function isIdempotencyKey(value: unknown): value is string {
  return isJobId(value);
}

function isStableCode(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length <= 128 &&
    /^[A-Z][A-Z0-9_]*$/.test(value)
  );
}

function isDecisionCode(value: unknown): value is string {
  return typeof value === "string" && /^[A-Z][A-Z0-9_]{0,63}$/.test(value);
}

function isNullableStableCode(value: unknown): value is string | null {
  return value === null || isStableCode(value);
}

function isAShareSymbol(value: unknown): value is string {
  return typeof value === "string" && /^[0-9]{6}\.(?:SH|SZ)$/.test(value);
}

function isMarketIndexCode(value: unknown): value is string {
  return (
    value === "000001.SH" ||
    value === "399001.SZ" ||
    value === "399006.SZ" ||
    value === "000688.SH" ||
    value === "899050.BJ"
  );
}

function isPlanPath(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length >= 1 &&
    value.length <= 512 &&
    /^(?:entry|reduction|risk|blockers)(?:\.[a-z][A-Za-z0-9]*|\[[0-9]+\])+$/.test(value)
  );
}

function isOrderedPlanPaths(value: unknown): value is string[] {
  return (
    Array.isArray(value) &&
    value.length <= 50 &&
    value.every(isPlanPath) &&
    isSortedUnique(value)
  );
}

function isArtifactAvailability(
  value: unknown,
): value is BacktestResultAvailabilityView[keyof BacktestResultAvailabilityView] {
  return typeof value === "string" && artifactAvailability.has(value as never);
}

function isDetailKind(value: unknown): value is BacktestDetailPage["kind"] {
  return typeof value === "string" && detailKinds.has(value as never);
}

function isActionableSignalType(value: unknown): value is BacktestSignalView["signalType"] {
  return typeof value === "string" && actionableSignalTypes.has(value as never);
}

function isExecutionStatus(
  value: unknown,
): value is BacktestExecutionOutcomeView["status"] {
  return typeof value === "string" && executionStatuses.has(value as never);
}

function isUnfilledReason(
  value: unknown,
): value is NonNullable<BacktestExecutionOutcomeView["reason"]> {
  return typeof value === "string" && unfilledReasons.has(value as never);
}

function isLotKey(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length >= 1 &&
    value.length <= 64 &&
    /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(value)
  );
}

function normalizeUuid(value: unknown): string | null {
  if (
    typeof value !== "string" ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
      value,
    )
  ) {
    return null;
  }
  return value.toLowerCase();
}

function isCanonicalUuid(value: unknown): value is string {
  return typeof value === "string" && normalizeUuid(value) === value;
}

function isStableToken(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length >= 1 &&
    value.length <= 128 &&
    /^[A-Za-z0-9][A-Za-z0-9._:-]*$/.test(value)
  );
}

function isFenText(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length <= MAX_EXACT_TEXT_CHARACTERS &&
    /^(?:0|-?[1-9][0-9]*)$/.test(value)
  );
}

function isNonnegativeFenText(value: unknown): value is string {
  return isFenText(value) && BigInt(value) >= 0n;
}

function isPositiveFenText(value: unknown): value is string {
  return isFenText(value) && BigInt(value) > 0n;
}

interface DecimalFraction {
  readonly denominator: bigint;
  readonly numerator: bigint;
}

function parseDecimalText(value: unknown): DecimalFraction | null {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.length > MAX_EXACT_TEXT_CHARACTERS ||
    !/^(?:0|-?[1-9][0-9]*|-?(?:0|[1-9][0-9]*)\.[0-9]*[1-9])$/.test(value)
  ) {
    return null;
  }
  const negative = value.startsWith("-");
  const unsigned = negative ? value.slice(1) : value;
  const [whole = "0", fraction = ""] = unsigned.split(".");
  const denominator = 10n ** BigInt(fraction.length);
  const magnitude = BigInt(`${whole}${fraction}`);
  return { denominator, numerator: negative ? -magnitude : magnitude };
}

function isDecimalText(value: unknown): value is string {
  return parseDecimalText(value) !== null;
}

function compareDecimal(left: string, right: string): number {
  const parsedLeft = parseDecimalText(left);
  const parsedRight = parseDecimalText(right);
  if (parsedLeft === null || parsedRight === null) throw new RangeError("invalid decimal");
  const difference =
    parsedLeft.numerator * parsedRight.denominator -
    parsedRight.numerator * parsedLeft.denominator;
  return difference === 0n ? 0 : difference < 0n ? -1 : 1;
}

function isDecimalBetween(
  value: unknown,
  minimum: string,
  maximum: string,
  maximumInclusive = true,
): value is string {
  return (
    isDecimalText(value) &&
    compareDecimal(value, minimum) >= 0 &&
    (maximumInclusive
      ? compareDecimal(value, maximum) <= 0
      : compareDecimal(value, maximum) < 0)
  );
}

function decimalEqualsContextFraction(
  value: string,
  numerator: bigint,
  denominator: bigint,
): boolean {
  return denominator !== 0n && value === decimalContextFraction(numerator, denominator, 28);
}

function decimalContextFraction(
  numerator: bigint,
  denominator: bigint,
  precision: number,
): string {
  if (numerator === 0n) return "0";
  const negative = (numerator < 0n) !== (denominator < 0n);
  const absoluteNumerator = numerator < 0n ? -numerator : numerator;
  const absoluteDenominator = denominator < 0n ? -denominator : denominator;
  let exponent =
    absoluteNumerator.toString().length - absoluteDenominator.toString().length;
  if (
    (exponent >= 0 &&
      absoluteNumerator < absoluteDenominator * 10n ** BigInt(exponent)) ||
    (exponent < 0 &&
      absoluteNumerator * 10n ** BigInt(-exponent) < absoluteDenominator)
  ) {
    exponent -= 1;
  }
  const scale = precision - 1 - exponent;
  const dividend =
    scale >= 0 ? absoluteNumerator * 10n ** BigInt(scale) : absoluteNumerator;
  const divisor =
    scale >= 0 ? absoluteDenominator : absoluteDenominator * 10n ** BigInt(-scale);
  let coefficient = dividend / divisor;
  const remainder = dividend % divisor;
  const doubled = remainder * 2n;
  if (doubled > divisor || (doubled === divisor && coefficient % 2n !== 0n)) {
    coefficient += 1n;
  }
  let rendered: string;
  if (scale <= 0) {
    rendered = `${coefficient}${"0".repeat(-scale)}`;
  } else {
    const digits = coefficient.toString().padStart(scale + 1, "0");
    const split = digits.length - scale;
    rendered = `${digits.slice(0, split)}.${digits.slice(split)}`
      .replace(/0+$/, "")
      .replace(/\.$/, "");
  }
  return negative ? `-${rendered}` : rendered;
}

function isCursor(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length >= 3 &&
    value.length <= 512 &&
    /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(value)
  );
}

function isOptionalCursor(value: unknown): boolean {
  return value === undefined || value === null || isCursor(value);
}

function isResponseTime(value: unknown): value is string {
  return parseShanghaiResponseDateTime(value) !== null;
}

function isNullableResponseTime(value: unknown): value is string | null {
  return value === null || isResponseTime(value);
}

function timeKey(value: string): bigint {
  const parsed = parseShanghaiResponseDateTime(value);
  if (parsed === null) throw new RangeError("invalid response time");
  return parsed.epochMicroseconds;
}

function calendarYearsAfter(value: string, years: number): string {
  const [yearText, monthText, dayText] = value.split("-");
  const year = Number(yearText) + years;
  const month = Number(monthText);
  let day = Number(dayText);
  if (month === 2 && day === 29 && !isLeapYear(year)) day = 28;
  return `${year.toString().padStart(4, "0")}-${month.toString().padStart(2, "0")}-${day
    .toString()
    .padStart(2, "0")}`;
}

function isLeapYear(year: number): boolean {
  return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
}

function isSortedUnique<T extends string>(items: readonly T[]): boolean {
  return items.every((item, index) => index === 0 || (items[index - 1] as T) < item);
}

function isDescendingUnique(items: readonly string[]): boolean {
  return items.every((item, index) => index === 0 || (items[index - 1] as string) > item);
}

function isAscendingUnique(items: readonly string[]): boolean {
  return items.every((item, index) => index === 0 || (items[index - 1] as string) < item);
}

function sameStrings(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((item, index) => item === right[index]);
}

function sameNullableStrings(
  left: readonly string[] | null,
  right: readonly string[] | null,
): boolean {
  return left === null ? right === null : right !== null && sameStrings(left, right);
}

function isBoundedItem(value: unknown): boolean {
  return new TextEncoder().encode(JSON.stringify(value)).byteLength <= MAX_ITEM_BYTES;
}

function isBoundedPage(value: unknown): boolean {
  return new TextEncoder().encode(JSON.stringify(value)).byteLength < MAX_PAGE_BYTES;
}

function appendQuery(
  search: URLSearchParams,
  key: string,
  value: string | number | null | undefined,
): void {
  if (value !== undefined && value !== null) search.append(key, String(value));
}

function withQuery(path: string, search: URLSearchParams): string {
  const query = search.toString();
  return query.length === 0 ? path : `${path}?${query}`;
}

function invalidRequest(): ApiClientError {
  return invalidResponse(0);
}
