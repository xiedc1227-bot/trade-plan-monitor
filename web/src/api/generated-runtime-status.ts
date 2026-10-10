// This file is generated from openapi.runtime-status.json by scripts/generate_frontend_types.py.
// Canonical installed monitor contract v2.
// Do not edit it by hand; update the FastAPI contract and rerun the generator.

export type AIProviderConfiguration = {
  allowRedirects?: false;
  baseUrl: string;
  displayName: string;
  enabled?: boolean;
  maxInputChars?: number;
  maxOutputTokens?: number;
  maxRetries?: number;
  model: string;
  promptVersion?: string;
  providerId: string;
  providerType?: components["schemas"]["AIProviderType"];
  secretReference: components["schemas"]["SecretReferenceView"];
  temperature?: number;
  timeoutSeconds?: number;
};

export type AIProviderPage = {
  items?: Array<components["schemas"]["AIProviderView"]>;
  limit: number;
  offset: number;
  total: number;
};

export type AIProviderType = "OPENAI_COMPATIBLE";

export type AIProviderView = {
  config: components["schemas"]["AIProviderConfiguration"];
  createdAt: string;
  revision: number;
  secretStatus: components["schemas"]["SecretStatusView"];
  updatedAt: string;
};

export type AIUsageView = {
  completionTokens: number;
  promptTokens: number;
  totalTokens: number;
};

export type ActionableSignalType = "BUY_CORE_READY" | "BUY_TACTICAL_READY" | "PRESSURE_REDUCE_READY" | "RISK_BREACH" | "RISK_EXIT_READY" | "RISK_EXIT_PENDING_SETTLEMENT";

export type ActivePlanView = {
  active: boolean;
  changedAt: string;
  planVersionId: (string) | (null);
  revision: number;
  symbol: string;
};

export type AlertAcknowledgementCommand = {
  alertId: string;
  expectedRevision: number;
};

export type AlertPage = {
  acknowledged?: (boolean) | (null);
  endAt?: (string) | (null);
  items?: Array<(components["schemas"]["AlertView"]) | (components["schemas"]["ExplicitAlertView"]) | (components["schemas"]["DailyAlertCenterView"]) | (components["schemas"]["ObsoleteDailyAlertView"])>;
  limit: number;
  offset: number;
  signalType?: (components["schemas"]["ActionableSignalType"]) | ("BUY" | "SELL" | "RISK_ALERT" | "RISK_EXIT") | (null);
  startAt?: (string) | (null);
  symbol?: (string) | (null);
  total: number;
};

export type AlertPriceZoneView = {
  highFen: number;
  includeHigh: boolean;
  includeLow: boolean;
  lowFen: number;
  zone: "LOW_BUY" | "PRESSURE";
};

export type AlertSeverity = "INFO" | "ACTION" | "RISK" | "CRITICAL";

export type AlertView = {
  acknowledgedAt?: (string) | (null);
  blockers?: Array<components["schemas"]["DecisionEvidenceView"]>;
  bucket: ("CORE" | "TACTICAL") | (null);
  causeId: string;
  createdAt: string;
  currentActionable: boolean;
  dataAgeSeconds: (number) | (null);
  dedupKey: string;
  evaluatedAt: string;
  eventId: string;
  marketDataAt: (string) | (null);
  matchedConditions: Array<components["schemas"]["DecisionEvidenceView"]>;
  messageText: string;
  name: string;
  nextStep: components["schemas"]["NextStepView"];
  planHash: string;
  planId: string;
  planVersion: number;
  positionPrefill?: (components["schemas"]["PositionPrefillView"]) | (null);
  priceFen: (number) | (null);
  quantity: (number) | (null);
  relevantZone: (components["schemas"]["AlertPriceZoneView"]) | (null);
  revision: number;
  riskLineFen: (number) | (null);
  satisfiedConditions?: Array<components["schemas"]["DecisionEvidenceView"]>;
  sequence: number;
  severity: components["schemas"]["AlertSeverity"];
  signalType: components["schemas"]["ActionableSignalType"];
  symbol: string;
  targetLotId?: (string) | (null);
  tradingDate: string;
  unmetConditions?: Array<components["schemas"]["DecisionEvidenceView"]>;
  zone: components["schemas"]["DecisionZone"];
};

export type ApiErrorCode = "BAD_REQUEST" | "VALIDATION_ERROR" | "UNAUTHORIZED" | "FORBIDDEN" | "NOT_FOUND" | "METHOD_NOT_ALLOWED" | "CONFLICT" | "PAYLOAD_TOO_LARGE" | "RATE_LIMITED" | "SERVICE_UNAVAILABLE" | "INTERNAL_ERROR";

export type AuthoritativeDecisionView = {
  dataAgeSeconds: (number) | (null);
  dataHealth: components["schemas"]["DataHealthView"];
  episodeLowFen: (number) | (null);
  episodeStatus: (components["schemas"]["EpisodeStatus"]) | (null);
  evaluatedAt: string;
  evidence?: Array<components["schemas"]["DecisionEvidenceView"]>;
  marketDataAt: (string) | (null);
  nextStep: components["schemas"]["NextStepView"];
  planHash: string;
  planId: string;
  planVersion: number;
  position: components["schemas"]["PositionSummaryView"];
  priceFen: (number) | (null);
  resultHash: string;
  riskBreachTradeDate: (string) | (null);
  riskStatus: components["schemas"]["RiskStatus"];
  signalType: components["schemas"]["SignalType"];
  symbol: string;
  zone: components["schemas"]["DecisionZone"];
};

export type BacktestAssumptionsView = {
  eventRiskAssumption: "NO_EVENT_RISK" | "MANUAL_EVENT_RISK";
  executionConfig: components["schemas"]["BacktestExecutionConfigView"];
  executionConfigHash: string;
  historicalProfile: "TUSHARE_STK_MINS_241_END_V1";
  priceAdjustmentPolicy: "NONE";
};

export type BacktestAuthoritativeDecisionView = {
  dataAgeSeconds: (number) | (null);
  dataHealth: components["schemas"]["BacktestDataHealthView"];
  episodeLowFen: (string) | (null);
  episodeStatus: (components["schemas"]["EpisodeStatus"]) | (null);
  evaluatedAt: string;
  evidence: Array<components["schemas"]["BacktestDecisionEvidenceView"]>;
  marketDataAt: (string) | (null);
  nextStep: components["schemas"]["BacktestNextStepView"];
  planHash: string;
  planId: string;
  planVersion: number;
  position: components["schemas"]["BacktestPositionSummaryView"];
  priceFen: (string) | (null);
  referenceMarket?: (components["schemas"]["BacktestDecisionReferenceMarketView"]) | (null);
  resultHash: string;
  riskBreachTradeDate: (string) | (null);
  riskStatus: components["schemas"]["RiskStatus"];
  signalType: components["schemas"]["SignalType"];
  symbol: string;
  zone: components["schemas"]["DecisionZone"];
};

export type BacktestDataHealthView = {
  dataAgeSeconds: (number) | (null);
  fresh: boolean;
  latestBarEnd: (string) | (null);
  requiredDataComplete: boolean;
  status: components["schemas"]["DataHealthStatus"];
};

export type BacktestDataSyncCommand = {
  allowNetwork: true;
  refresh: boolean;
  scope: components["schemas"]["BacktestDatasetScopeInput"];
};

export type BacktestDataSyncJobResultView = {
  calendarRows: number;
  dailyBarRows: number;
  dailyLimitRows: number;
  kind: "DATA_SYNC";
  minuteDays: number;
  networkCalls: number;
};

export type BacktestDatasetCoverageView = {
  blockers: Array<string>;
  calendarRowCount: number;
  dailyBarRowCount: number;
  dailyLimitRowCount: number;
  minuteBarCount: number;
  minuteDayCount: number;
  symbolCount: number;
  tradingDayCount: number;
};

export type BacktestDatasetFiltersView = {
  adjustmentPolicy: ("NONE") | (null);
  endOnOrBefore: (string) | (null);
  historicalProfile: ("TUSHARE_STK_MINS_241_END_V1") | (null);
  startOnOrAfter: (string) | (null);
  symbol: (string) | (null);
};

export type BacktestDatasetPage = {
  filters: components["schemas"]["BacktestDatasetFiltersView"];
  hasMore: boolean;
  highWatermark: string;
  items: Array<components["schemas"]["BacktestDatasetView"]>;
  limit: number;
  nextCursor: (string) | (null);
};

export type BacktestDatasetScopeInput = {
  adjustmentPolicy: "NONE";
  end: string;
  historicalProfile: "TUSHARE_STK_MINS_241_END_V1";
  start: string;
  symbols: Array<string>;
  warmupStart: string;
};

export type BacktestDatasetScopeView = {
  adjustmentPolicy: "NONE";
  end: string;
  historicalProfile: "TUSHARE_STK_MINS_241_END_V1";
  start: string;
  symbols: Array<string>;
  warmupStart: string;
};

export type BacktestDatasetVerificationCommand = {
  scope: components["schemas"]["BacktestDatasetScopeInput"];
};

export type BacktestDatasetVerificationJobResultView = {
  blockers: Array<string>;
  coverage: components["schemas"]["BacktestDatasetCoverageView"];
  datasetHash: (string) | (null);
  kind: "DATASET_VERIFY";
  ready: boolean;
};

export type BacktestDatasetView = {
  coverage: components["schemas"]["BacktestDatasetCoverageView"];
  createdAt: string;
  datasetHash: string;
  schemaVersion: "backtest-dataset-v1" | "backtest-dataset-v2";
  scope: components["schemas"]["BacktestDatasetScopeView"];
  verifiedAt: string;
};

export type BacktestDecisionEvidenceView = {
  children: Array<components["schemas"]["BacktestDecisionEvidenceView"]>;
  code: string;
  facts: Array<components["schemas"]["BacktestEvidenceFactView"]>;
  kind: "CONDITION" | "RULE";
  missingInputs: Array<components["schemas"]["MissingInputCode"]>;
  outcome: components["schemas"]["ConditionOutcome"];
};

export type BacktestDecisionReferenceMarketView = {
  dataAt: (string) | (null);
  evidence: Array<components["schemas"]["IndexConditionEvidenceView"]>;
  health: components["schemas"]["MarketIndexHealth"];
  indexCode: components["schemas"]["MarketIndexCode"];
  snapshotHash: (string) | (null);
};

export type BacktestDecisionView = {
  decision: components["schemas"]["BacktestAuthoritativeDecisionView"];
  detailId: string;
  eventAt: string;
  kind: "DECISION";
  resultHash: string;
  runId: string;
};

export type BacktestDetailFiltersView = {
  kind: "DECISION" | "SIGNAL" | "EXECUTION_OUTCOME";
};

export type BacktestDetailPage = {
  availability: "AVAILABLE" | "EXPIRED" | "NOT_RECORDED";
  filters: components["schemas"]["BacktestDetailFiltersView"];
  hasMore: boolean;
  highWatermark: string;
  items: Array<components["schemas"]["BacktestDetailView"]>;
  kind: "DECISION" | "SIGNAL" | "EXECUTION_OUTCOME";
  limit: number;
  nextCursor: (string) | (null);
};

export type BacktestDetailView = (components["schemas"]["BacktestDecisionView"]) | (components["schemas"]["BacktestSignalView"]) | (components["schemas"]["BacktestExecutionOutcomeView"]) | (components["schemas"]["ResearchDecisionView"]) | (components["schemas"]["ResearchOperationView"]) | (components["schemas"]["BacktestLoopEventView"]);

export type BacktestEquityPointView = {
  cashFen: string;
  costBasisFen: string;
  equityFen: string;
  markPriceFen: string;
  markedAt: string;
  marketValueFen: string;
  positionQuantity: number;
  realizedPnlFen: string;
  runId: string;
  snapshotId: string;
  symbol: string;
  totalCostFen: string;
  unrealizedPnlFen: string;
};

export type BacktestEquitySeries = {
  availability: "AVAILABLE" | "EXPIRED" | "NOT_RECORDED";
  items: Array<(components["schemas"]["BacktestEquityPointView"]) | (components["schemas"]["ResearchEquityView"])>;
};

export type BacktestEvidenceFactView = {
  key: string;
  unit: components["schemas"]["EvidenceUnit"];
  value: components["schemas"]["BacktestEvidenceScalar"];
};

export type BacktestEvidenceScalar = (boolean) | (number) | (string) | (string) | (string) | (string);

export type BacktestExecutionConfigInput = {
  buySlippageBps: string;
  commissionRate: string;
  minimumCommissionFen: number;
  sellSlippageBps: string;
  stampDutyRate: string;
  transferFeeRate: string;
};

export type BacktestExecutionConfigView = {
  buySlippageBps: string;
  commissionRate: string;
  minimumCommissionFen: string;
  sellSlippageBps: string;
  stampDutyRate: string;
  transferFeeRate: string;
};

export type BacktestExecutionOutcomeView = {
  detailId: string;
  eventAt: string;
  fillId: (string) | (null);
  kind: "EXECUTION_OUTCOME";
  orderId: (string) | (null);
  outcomeId: string;
  reason: (components["schemas"]["UnfilledReason"]) | (null);
  runId: string;
  signalId: string;
  sourceBarId: (string) | (null);
  status: components["schemas"]["ExecutionStatus"];
};

export type BacktestFeeBreakdownView = {
  commissionFen: string;
  stampDutyFen: string;
  totalFen: string;
  transferFeeFen: string;
};

export type BacktestFillFiltersView = {
};

export type BacktestFillPage = {
  filters: components["schemas"]["BacktestFillFiltersView"];
  hasMore: boolean;
  highWatermark: string;
  items: Array<(components["schemas"]["BacktestFillView"]) | (components["schemas"]["BacktestLoopFillView"])>;
  limit: number;
  nextCursor: (string) | (null);
};

export type BacktestFillView = {
  bucket: "CORE" | "TACTICAL";
  cashDeltaFen: string;
  configHash: string;
  costBasisReleasedFen: string;
  datasetHash: string;
  fees: components["schemas"]["BacktestFeeBreakdownView"];
  fillId: string;
  filledAt: string;
  notionalFen: string;
  orderId: string;
  planHash: string;
  priceFen: string;
  quantity: number;
  realizedPnlFen: (string) | (null);
  requestedQuantity: number;
  resultHash: string;
  runId: string;
  side: "BUY" | "SELL";
  signalId: string;
  sourceBarId: string;
  symbol: string;
  targetLotId: (string) | (null);
};

export type BacktestFormulaVersionsView = {
  executionFormulaVersion: string;
  metricFormulaVersion: string;
  reportSchemaVersion: string;
  runFormulaVersion: string;
};

export type BacktestIndexConditionSummaryView = {
  applicableBranchCount: number;
  conditionType: "INDEX_CLOSE_GTE_MA" | "INDEX_CLOSE_LTE_MA" | "INDEX_MA_NON_DECREASING" | "INDEX_MA_NON_INCREASING" | "INDEX_RETURN_GTE" | "INDEX_RETURN_LTE";
  formulaId: "SMA" | "SMA_LOOKBACK" | "RETURN";
  missingCount: number;
  parameters: (components["schemas"]["BacktestIndexMaParametersView"]) | (components["schemas"]["BacktestIndexMaLookbackParametersView"]) | (components["schemas"]["BacktestIndexReturnParametersView"]);
  planPath: string;
  satisfiedCount: number;
  unsatisfiedCount: number;
};

export type BacktestIndexMaLookbackParametersView = {
  lookback: number;
  period: number;
};

export type BacktestIndexMaParametersView = {
  period: number;
};

export type BacktestIndexReturnParametersView = {
  thresholdRatio: string;
  window: components["schemas"]["ReturnWindow"];
  windowSize: number;
};

export type BacktestInitialLotInput = {
  acquiredTradeDate: string;
  bucket: "CORE" | "TACTICAL";
  costBasisFen: number;
  lotKey: string;
  quantity: number;
};

export type BacktestJobCancellationCommand = {
  jobId: string;
};

export type BacktestJobFiltersView = {
  createdFrom: (string) | (null);
  createdTo: (string) | (null);
  datasetHash: (string) | (null);
  kind: (Array<"DATA_SYNC" | "DATASET_VERIFY" | "BACKTEST_RUN">) | (null);
  runId: (string) | (null);
  status: (Array<"QUEUED" | "RUNNING" | "CANCEL_REQUESTED" | "COMPLETED" | "FAILED" | "CANCELLED">) | (null);
};

export type BacktestJobPage = {
  filters: components["schemas"]["BacktestJobFiltersView"];
  hasMore: boolean;
  highWatermark: string;
  items: Array<components["schemas"]["BacktestJobView"]>;
  limit: number;
  nextCursor: (string) | (null);
};

export type BacktestJobProgressView = {
  completedUnits: number;
  phase: "QUEUED" | "VALIDATING_INPUT" | "SYNCING_DATA" | "VERIFYING_DATASET" | "REPLAYING" | "MATERIALIZING_RESULTS" | "FINALIZING" | "TERMINAL";
  totalUnits: (number) | (null);
  unit: "ITEMS" | "SYMBOL_DAYS" | "EVENTS" | "ROWS";
  updatedAt: string;
};

export type BacktestJobReceipt = {
  attempt: number;
  datasetHash: (string) | (null);
  jobId: string;
  kind: "DATA_SYNC" | "DATASET_VERIFY" | "BACKTEST_RUN";
  reused: boolean;
  revision: number;
  runId: (string) | (null);
  status: "QUEUED" | "RUNNING" | "CANCEL_REQUESTED" | "COMPLETED" | "FAILED" | "CANCELLED";
  submittedAt: string;
};

export type BacktestJobResultView = (components["schemas"]["BacktestDataSyncJobResultView"] & { kind: "DATA_SYNC" }) | (components["schemas"]["BacktestDatasetVerificationJobResultView"] & { kind: "DATASET_VERIFY" }) | (components["schemas"]["BacktestRunJobResultView"] & { kind: "BACKTEST_RUN" });

export type BacktestJobView = {
  attempt: number;
  cancelRequestedAt: (string) | (null);
  createdAt: string;
  datasetHash: (string) | (null);
  errorCode: (string) | (null);
  errorMessage: (string) | (null);
  finishedAt: (string) | (null);
  jobId: string;
  kind: "DATA_SYNC" | "DATASET_VERIFY" | "BACKTEST_RUN";
  progress: components["schemas"]["BacktestJobProgressView"];
  requestHash: string;
  result: (components["schemas"]["BacktestJobResultView"]) | (null);
  reused: boolean;
  revision: number;
  runId: (string) | (null);
  startedAt: (string) | (null);
  status: "QUEUED" | "RUNNING" | "CANCEL_REQUESTED" | "COMPLETED" | "FAILED" | "CANCELLED";
  updatedAt: string;
};

export type BacktestLoopCostsInput = {
  buySlippageFen: number;
  commissionRate: string;
  minimumCommissionFen: number;
  sellSlippageFen: number;
  stampDutyRate: string;
  transferFeeRate: string;
};

export type BacktestLoopEventView = {
  detailId: string;
  event: components["schemas"]["LoopAuditEvent"];
  eventAt: string;
  kind: "DECISION";
  runId: string;
  schemaVersion: "monitor-loop-event-v1";
};

export type BacktestLoopFillView = {
  eventId: string;
  fillId: string;
  filledAt: string;
  receipt: components["schemas"]["LoopAccountReceipt"];
  runId: string;
  schemaVersion: "monitor-loop-fill-v1";
};

export type BacktestLoopProvenanceView = {
  candidateHash: string;
  candidateRevision: number;
  inputHash: string;
  manifestHash: string;
  preparationId: string;
  sourceRevision: number;
};

export type BacktestLoopResponseInput = {
  mode: "FOLLOW_REMINDERS" | "OBSERVE_ONLY";
  responseDelaySeconds?: number;
};

export type BacktestLoopRunSummaryView = {
  availability: components["schemas"]["BacktestResultAvailabilityView"];
  completedAt: string;
  datasetHash: string;
  eventEnd: string;
  eventStart: string;
  fillCount: number;
  metrics: components["schemas"]["LoopMetrics"];
  pinned: boolean;
  planHash: string;
  planVersionId: null;
  reportHash: string;
  revision: number;
  runId: string;
  schemaVersion: "monitor-loop-result-v1";
  status: "COMPLETED";
  symbol: string;
};

export type BacktestLoopRunView = {
  availability: components["schemas"]["BacktestResultAvailabilityView"];
  completedAt: string;
  costs: components["schemas"]["LoopCosts"];
  datasetHash: string;
  eventEnd: string;
  eventStart: string;
  fillCount: number;
  frozenPlan: components["schemas"]["LoopPlanVersion"];
  metrics: components["schemas"]["LoopMetrics"];
  openingAccount: components["schemas"]["LoopAccountInput"];
  pinned: boolean;
  planHash: string;
  planVersionId: null;
  provenance: components["schemas"]["BacktestLoopProvenanceView"];
  report: components["schemas"]["MonitorLoopReport"];
  reportHash: string;
  response: components["schemas"]["LoopResponsePolicy"];
  revision: number;
  runId: string;
  schemaVersion: "monitor-loop-result-v1";
  status: "COMPLETED";
  symbol: string;
};

export type BacktestMarketIndexHealthPointView = {
  dataAt: string;
  health: components["schemas"]["MarketIndexHealth"];
  issues: Array<components["schemas"]["MarketIndexIssueCode"]>;
};

export type BacktestMarketIndexPointView = {
  closePoints: string;
  dataAt: string;
  health: components["schemas"]["MarketIndexHealth"];
  indicatorFacts: Array<(components["schemas"]["SmaIndicatorFactView"] & { formulaId: "SMA" }) | (components["schemas"]["SmaLookbackIndicatorFactView"] & { formulaId: "SMA_LOOKBACK" }) | (components["schemas"]["ReturnIndicatorFactView"] & { formulaId: "RETURN" })>;
  issues: Array<components["schemas"]["MarketIndexIssueCode"]>;
  snapshotHash: string;
  tradeDate: string;
};

export type BacktestMarketIndexSeriesView = {
  conditionSummaries: Array<components["schemas"]["BacktestIndexConditionSummaryView"]>;
  healthTimeline: Array<components["schemas"]["BacktestMarketIndexHealthPointView"]>;
  items: Array<components["schemas"]["BacktestMarketIndexPointView"]>;
  referenceMarket: (components["schemas"]["BacktestReferenceMarketView"]) | (null);
  runId: string;
};

export type BacktestMetricsView = {
  blockedCount: number;
  finalCashFen: string;
  finalEquityFen: string;
  initialCashFen: string;
  initialEquityFen: string;
  maximumDrawdown: string;
  realizedPnlFen: string;
  skippedCount: number;
  totalCostFen: string;
  totalReturn: string;
  tradeCount: number;
  turnoverFen: string;
  unrealizedPnlFen: string;
  winRate: string;
  winningSellCount: number;
};

export type BacktestNextStepView = {
  code: components["schemas"]["NextStepCode"];
  notBefore: (string) | (string) | (null);
  requiredInputs: Array<components["schemas"]["MissingInputCode"]>;
};

export type BacktestPositionSummaryView = {
  coreQuantity: number;
  sellableCoreQuantity: number;
  sellableTacticalQuantity: number;
  tacticalQuantity: number;
  totalQuantity: number;
};

export type BacktestReferenceMarketBindingView = {
  board: components["schemas"]["Board"];
  displayName: string;
  indexCode: components["schemas"]["MarketIndexCode"];
  mappingVersion: "board-index-map-v1";
  selection: "AUTO_BOARD";
};

export type BacktestReferenceMarketCoverageView = {
  availableFiveMinuteCount: number;
  availableOfficialDayCount: number;
  binding: components["schemas"]["BacktestReferenceMarketBindingView"];
  blockers: Array<string>;
  conditionPaths: Array<string>;
  coverageStatus: "AVAILABLE" | "BLOCKED" | "NOT_REQUIRED";
  datasetHash: string;
  formulaDefinitionHash: string;
  indexRequirementHash: string;
  marketIndexDataHash: (string) | (null);
  planVersionId: string;
  required: boolean;
  requiredFiveMinuteCount: number;
  requiredOfficialDayCount: number;
  warmupEnd: string;
  warmupStart: string;
};

export type BacktestReferenceMarketView = {
  binding: components["schemas"]["BacktestReferenceMarketBindingView"];
  blockers: Array<string>;
  conditionPaths: Array<string>;
  conditionSummaries: Array<components["schemas"]["BacktestIndexConditionSummaryView"]>;
  coverageStatus: "AVAILABLE" | "BLOCKED" | "EXPIRED" | "NOT_RECORDED";
  datasetHash: string;
  formulaDefinitionHash: string;
  indexRequirementHash: string;
  marketIndexDataHash: string;
  required: true;
  warmupStart: string;
};

export type BacktestResultAvailabilityView = {
  decisionDetails: "AVAILABLE" | "EXPIRED" | "NOT_RECORDED";
  equitySeries: "AVAILABLE" | "EXPIRED" | "NOT_RECORDED";
  executionOutcomeDetails: "AVAILABLE" | "EXPIRED" | "NOT_RECORDED";
  signalDetails: "AVAILABLE" | "EXPIRED" | "NOT_RECORDED";
};

export type BacktestRunCommand = {
  datasetHash: string;
  eventRiskAssumption: "NO_EVENT_RISK" | "MANUAL_EVENT_RISK";
  executionConfig: components["schemas"]["BacktestExecutionConfigInput"];
  initialCashFen: number;
  initialLots: Array<components["schemas"]["BacktestInitialLotInput"]>;
  planVersionId: string;
  researchInput?: (components["schemas"]["UnifiedResearchInput"]) | (null);
};

export type BacktestRunCoverageView = {
  decisionCount: number;
  equityPointCount: number;
  eventEnd: string;
  eventStart: string;
  fillCount: number;
  orderCount: number;
  outcomeCount: number;
  signalCount: number;
  tradingDayCount: number;
};

export type BacktestRunFiltersView = {
  completedFrom: (string) | (null);
  completedTo: (string) | (null);
  datasetHash: (string) | (null);
  pinned: (boolean) | (null);
  planVersionId: (string) | (null);
  symbol: (string) | (null);
};

export type BacktestRunJobResultView = {
  kind: "BACKTEST_RUN";
  reportHash: string;
  reused: boolean;
  runId: string;
};

export type BacktestRunPage = {
  filters: components["schemas"]["BacktestRunFiltersView"];
  hasMore: boolean;
  highWatermark: string;
  items: Array<(components["schemas"]["BacktestRunSummaryView"]) | (components["schemas"]["BacktestLoopRunSummaryView"])>;
  limit: number;
  nextCursor: (string) | (null);
};

export type BacktestRunPinCommand = {
  expectedRevision: number;
  pinned: boolean;
};

export type BacktestRunSummaryView = {
  availability: components["schemas"]["BacktestResultAvailabilityView"];
  completedAt: string;
  datasetHash: string;
  eventEnd: string;
  eventStart: string;
  fillCount: number;
  metrics: (components["schemas"]["BacktestMetricsView"]) | (components["schemas"]["ResearchMetricsView"]);
  pinned: boolean;
  planHash: string;
  planVersionId: (string) | (null);
  reportHash: string;
  revision: number;
  runId: string;
  status: "COMPLETED";
  symbol: string;
};

export type BacktestRunView = {
  assumptions: components["schemas"]["BacktestAssumptionsView"];
  availability: components["schemas"]["BacktestResultAvailabilityView"];
  completedAt: string;
  coverage: components["schemas"]["BacktestRunCoverageView"];
  datasetHash: string;
  eventEnd: string;
  eventStart: string;
  fillCount: number;
  formulaVersions: components["schemas"]["BacktestFormulaVersionsView"];
  initialCashFen: string;
  limitations: Array<string>;
  metrics: (components["schemas"]["BacktestMetricsView"]) | (components["schemas"]["ResearchMetricsView"]);
  pinned: boolean;
  planHash: string;
  planVersionId: (string) | (null);
  referenceMarket?: (components["schemas"]["BacktestReferenceMarketView"]) | (null);
  reportHash: string;
  revision: number;
  runId: string;
  status: "COMPLETED";
  symbol: string;
};

export type BacktestServiceControlReceipt = {
  accepted?: true;
  action: "STOP" | "RETRY_PREPARATION" | "RESUME_JOBS";
  epoch: string;
  revision: number;
};

export type BacktestServiceRecoveryCommand = {
  action: "RETRY_PREPARATION" | "RESUME_JOBS";
  epoch: string;
  expectedRevision: number;
  resumeJobIds: Array<string>;
};

export type BacktestServiceState = "DISABLED" | "NOT_INITIALIZED" | "STARTING" | "READ_READY" | "READY" | "RECOVERING" | "DEGRADED" | "STOPPING" | "STOPPED";

export type BacktestServiceStopCommand = {
  epoch: string;
  expectedRevision: number;
};

export type BacktestServiceView = {
  authorizedJobIds: Array<string>;
  canCancel: boolean;
  canExport: boolean;
  canRead: boolean;
  canSubmit: boolean;
  epoch: (string) | (null);
  generation: number;
  physicallyDrained: boolean;
  reason: ("SERVICE_REPAIR_REQUIRED") | (null);
  revision: number;
  state: components["schemas"]["BacktestServiceState"];
};

export type BacktestSignalView = {
  bucket: ("CORE" | "TACTICAL") | (null);
  causeId: string;
  detailId: string;
  eventAt: string;
  kind: "SIGNAL";
  quantity: (number) | (null);
  resultHash: string;
  runId: string;
  signalId: string;
  signalType: components["schemas"]["ActionableSignalType"];
  symbol: string;
  targetLotId: (string) | (null);
};

export type BarInterval = "ONE_MINUTE" | "FIVE_MINUTES";

export type BarPage = {
  endAt: string;
  items?: Array<components["schemas"]["BarView"]>;
  limit: number;
  offset: number;
  startAt: string;
  total: number;
};

export type BarView = {
  amountYuan: string;
  barEnd: string;
  closeFen: number;
  formulaVersion: (string) | (null);
  highFen: number;
  interval: components["schemas"]["BarInterval"];
  lowFen: number;
  openFen: number;
  receivedAt: string;
  symbol: string;
  volumeShares: number;
};

export type BindingKind = "VALUE" | "STRUCTURE";

export type BindingOrigin = "SOURCE" | "USER_SUPPLEMENT" | "CONTRACT";

export type BindingUnit = "FEN" | "SHARES" | "BARS" | "MINUTES" | "RATIO" | "NONE";

export type Board = "SSE_MAIN" | "SZSE_MAIN" | "CHINEXT" | "STAR_MARKET" | "BSE";

export type CalendarScopeView = {
  dataCutoff: (string) | (null);
  kind: "CALENDAR";
  nextRetryAt: (string) | (null);
  progress: components["schemas"]["ScopeProgressView"];
  reasonCode: ("RUNTIME_STARTING" | "RUNTIME_STOPPING" | "RUNTIME_STOPPED" | "RUNTIME_FAULT" | "COORDINATOR_STALLED" | "STORAGE_UNAVAILABLE" | "BEFORE_FIRST_MINUTE" | "SESSION_BREAK" | "SESSION_CLOSED" | "NO_ACTIVE_PLANS" | "AWAITING_FIRST_EVALUATION" | "CALENDAR_UNKNOWN" | "REFERENCE_PENDING" | "COVERAGE_INCOMPLETE" | "CLOSE_PENDING" | "PUBLICATION_PENDING" | "PROVIDER_UNAVAILABLE" | "RATE_LIMITED" | "CREDENTIAL_MISSING" | "PERMISSION_DENIED" | "SEMANTICS_INCOMPATIBLE" | "CONFIGURATION_INVALID" | "HISTORY_UNAVAILABLE" | "STATE_UNAVAILABLE" | "GENERATION_CHANGED" | "NEEDS_RESTART" | "LEGACY_PLANS_REQUIRE_REVIEW" | "SCOPED_DEPENDENCY_FAILURE") | (null);
  requiredTarget: ((components["schemas"]["IntradayTargetView"] & { kind: "INTRADAY" }) | (components["schemas"]["OfficialCloseTargetView"] & { kind: "OFFICIAL_CLOSE" })) | (null);
  scopeKey: string;
  status: "WAITING" | "RECOVERING" | "READY" | "BLOCKED";
};

export type CapturedReminder = {
  captured_at: string;
  cause_revision: (number) | (null);
  event: components["schemas"]["DailyAlertEvent"];
  inventory_revision: number;
  sequence: number;
  status: "CAPTURED" | "SUPPRESSED";
};

export type CertifiedDailyBar = {
  adjustment_as_of: string;
  available_at: string;
  bar_id: string;
  basis_id: string;
  close: string;
  high: string;
  low: string;
  official: true;
  open: string;
  price_basis?: "QFQ";
  provider: string;
  received_at: string;
  symbol: string;
  trade_date: string;
  volume_shares: number;
};

export type ClauseDisposition = "MAPPED" | "UNRESOLVED" | "UNSUPPORTED";

export type CompletedMinuteConfirmation = {
  kind: "COMPLETED_BAR_CLOSE";
  timeframe_minutes: 5;
};

export type ConditionOutcome = "SATISFIED" | "UNSATISFIED" | "MISSING_INPUT";

export type ConditionPlanEntryView = {
  activationRevision: number;
  availability: "CURRENT" | "CACHED";
  currentActionable: boolean;
  name: string;
  observedAt: string;
  planFamily: "CONDITION_PLAN";
  planHash: string;
  planRuntime: components["schemas"]["DailyEvaluationApiView"];
  planVersionId: string;
  scope: components["schemas"]["PlanScopeView"];
  symbol: string;
};

export type ConfiguredAIProviderRuntimeView = {
  baseUrl: string;
  configured: boolean;
  displayName: string;
  enabled: boolean;
  maxInputChars: number;
  maxOutputTokens: number;
  model: string;
  providerId: string;
  revision?: 0;
};

export type ConfiguredAIRuntimeView = {
  alternativeProviders?: (Array<components["schemas"]["ConfiguredAIProviderRuntimeView"]>) | (null);
  baseUrl: string;
  configured: boolean;
  displayName: string;
  enabled: boolean;
  maxInputChars: number;
  maxOutputTokens: number;
  model: string;
  providerId: string;
  revision?: 0;
};

export type CoordinatorStatusView = {
  progressDueAt: (string) | (null);
  state: "STARTING" | "SCHEDULED" | "WORKING" | "STALLED" | "STOPPED";
};

export type DailyAlertCenterView = {
  acknowledgedAt?: (string) | (null);
  activationRevision: number;
  alertKind?: ("RISK_ALERT") | (null);
  causeId: string;
  confirmedTradeDate: (string) | (null);
  createdAt: string;
  currentActionable: boolean;
  dedupKey: string;
  evaluatedAt: string;
  eventId: string;
  evidence: Array<{
      [key: string]: unknown;
    }>;
  executionDate: (string) | (null);
  messageText: string;
  name: string;
  nextStep: "CONFIRM_SIMULATED_TRADE" | "REVIEW_RISK_EXIT" | "REVIEW_ALERT";
  payloadSchemaVersion?: "daily-simulation-alert-v1";
  planHash: string;
  planId: string;
  planVersion: number;
  planVersionId: string;
  quantity: (number) | (null);
  reviewId: string;
  revision: number;
  riskScope: ({
    [key: string]: unknown;
  }) | (null);
  ruleId?: (string) | (null);
  sequence: number;
  severity: "ACTION" | "RISK" | "INFO";
  signalType: "BUY" | "SELL" | "RISK_EXIT" | "REMINDER";
  simulatedQty: number;
  symbol: string;
  tradingDate: string;
};

export type DailyAlertEvent = {
  acknowledged_at?: (string) | (null);
  activation_revision: number;
  alert_kind?: ("RISK_ALERT") | (null);
  cause_id: string;
  confirmed_trade_date: (string) | (null);
  created_at: string;
  dedup_key: string;
  evaluated_at: string;
  event_id: string;
  evidence: Array<{
      [key: string]: unknown;
    }>;
  execution_date: (string) | (null);
  message_text: string;
  name: string;
  next_step: "CONFIRM_SIMULATED_TRADE" | "REVIEW_RISK_EXIT" | "REVIEW_ALERT";
  payload_schema_version?: "daily-simulation-alert-v1";
  plan_hash: string;
  plan_id: string;
  plan_version: number;
  plan_version_id: string;
  quantity: (number) | (null);
  review_id: string;
  risk_scope: ({
    [key: string]: unknown;
  }) | (null);
  rule_id?: (string) | (null);
  sequence: number;
  severity: "ACTION" | "RISK" | "INFO";
  signal_type: "BUY" | "SELL" | "RISK_EXIT" | "REMINDER";
  simulated_qty: number;
  symbol: string;
  trading_date: string;
};

export type DailyAll = {
  conditions: Array<(components["schemas"]["DailyPriceCompare"] & { type: "DAILY_PRICE_COMPARE" }) | (components["schemas"]["DailyPriceInRange"] & { type: "DAILY_PRICE_IN_RANGE" }) | (components["schemas"]["DailyVolumeRatio"] & { type: "DAILY_VOLUME_RATIO" }) | (components["schemas"]["DailyCandleRatio"] & { type: "DAILY_CANDLE_RATIO" }) | (components["schemas"]["DailyIndicatorCompare"] & { type: "DAILY_INDICATOR_COMPARE" }) | (components["schemas"]["DailyCloseSequence"] & { type: "DAILY_CLOSE_SEQUENCE" }) | (components["schemas"]["ReviewedDailyFact"] & { type: "REVIEWED_FACT" }) | (components["schemas"]["DailyAll"] & { type: "ALL" }) | (components["schemas"]["DailyAny"] & { type: "ANY" })>;
  type: "ALL";
};

export type DailyAny = {
  conditions: Array<(components["schemas"]["DailyPriceCompare"] & { type: "DAILY_PRICE_COMPARE" }) | (components["schemas"]["DailyPriceInRange"] & { type: "DAILY_PRICE_IN_RANGE" }) | (components["schemas"]["DailyVolumeRatio"] & { type: "DAILY_VOLUME_RATIO" }) | (components["schemas"]["DailyCandleRatio"] & { type: "DAILY_CANDLE_RATIO" }) | (components["schemas"]["DailyIndicatorCompare"] & { type: "DAILY_INDICATOR_COMPARE" }) | (components["schemas"]["DailyCloseSequence"] & { type: "DAILY_CLOSE_SEQUENCE" }) | (components["schemas"]["ReviewedDailyFact"] & { type: "REVIEWED_FACT" }) | (components["schemas"]["DailyAll"] & { type: "ALL" }) | (components["schemas"]["DailyAny"] & { type: "ANY" })>;
  type: "ANY";
};

export type DailyCandleRatio = {
  comparator: "LT" | "LTE" | "EQ" | "GTE" | "GT";
  component: "LOWER_WICK" | "UPPER_WICK" | "BODY";
  offset: number;
  ratio: string;
  type: "DAILY_CANDLE_RATIO";
};

export type DailyCandleRatioInput = {
  comparator: "LT" | "LTE" | "EQ" | "GTE" | "GT";
  component: "LOWER_WICK" | "UPPER_WICK" | "BODY";
  offset: number;
  ratio: (number) | (string);
  type: "DAILY_CANDLE_RATIO";
};

export type DailyClause = {
  clause_id: string;
  disposition: "POLICY" | "INVENTORY_ASSERTION" | "BACKGROUND" | "UNRESOLVED" | "UNSUPPORTED";
  end: number;
  excerpt: string;
  exclusions?: Array<components["schemas"]["DailySourceExclusion"]>;
  paths: Array<string>;
  reason: string;
  remainders?: Array<components["schemas"]["DailyTechnicalRemainder"]>;
  start: number;
};

export type DailyCloseSequence = {
  comparator: ("LT" | "LTE" | "EQ" | "GTE" | "GT") | (null);
  mode: "PAIRWISE_NONDECREASING" | "COMPARE_REFERENCE";
  offset: number;
  reference: ((components["schemas"]["FixedDailyReference"] & { mode: "FIXED" }) | (components["schemas"]["DynamicDailyReference"] & { mode: "DYNAMIC" })) | (null);
  sessions: number;
  type: "DAILY_CLOSE_SEQUENCE";
};

export type DailyCloseSequenceInput = {
  comparator: ("LT" | "LTE" | "EQ" | "GTE" | "GT") | (null);
  mode: "PAIRWISE_NONDECREASING" | "COMPARE_REFERENCE";
  offset: number;
  reference: ((components["schemas"]["FixedDailyReferenceInput"] & { mode: "FIXED" }) | (components["schemas"]["DynamicDailyReference"] & { mode: "DYNAMIC" })) | (null);
  sessions: number;
  type: "DAILY_CLOSE_SEQUENCE";
};

export type DailyConditionEvidence = {
  bar_ids?: Array<string>;
  basis_id?: (string) | (null);
  children?: Array<components["schemas"]["DailyConditionEvidence"]>;
  condition: (components["schemas"]["DailyPriceCompare"] & { type: "DAILY_PRICE_COMPARE" }) | (components["schemas"]["DailyPriceInRange"] & { type: "DAILY_PRICE_IN_RANGE" }) | (components["schemas"]["DailyVolumeRatio"] & { type: "DAILY_VOLUME_RATIO" }) | (components["schemas"]["DailyCandleRatio"] & { type: "DAILY_CANDLE_RATIO" }) | (components["schemas"]["DailyIndicatorCompare"] & { type: "DAILY_INDICATOR_COMPARE" }) | (components["schemas"]["DailyCloseSequence"] & { type: "DAILY_CLOSE_SEQUENCE" }) | (components["schemas"]["ReviewedDailyFact"] & { type: "REVIEWED_FACT" }) | (components["schemas"]["DailyAll"] & { type: "ALL" }) | (components["schemas"]["DailyAny"] & { type: "ANY" });
  fact_ids?: Array<string>;
  operands?: Array<string>;
  outcome: "SATISFIED" | "UNSATISFIED" | "MISSING_INPUT";
  reason?: (string) | (null);
  session_dates?: Array<string>;
};

export type DailyDayActivation = {
  mode: "TRADING_DAY";
  trading_day: string;
};

export type DailyDraftLevels = {
  low_buy: components["schemas"]["DailyDraftZone"];
  pressure: components["schemas"]["DailyDraftZone"];
  risk_comparison: ("LT" | "LTE") | (null);
  risk_line_fen: (number) | (null);
};

export type DailyDraftZone = {
  high_fen: (number) | (null);
  include_high: (boolean) | (null);
  include_low: (boolean) | (null);
  low_fen: (number) | (null);
};

export type DailyEditorSchemaView = {
  candidateSchema: {
    [key: string]: unknown;
  };
  operationSchemas: {
    [key: string]: unknown;
  };
  schemaVersion?: 5;
};

export type DailyEvaluationApiView = {
  activationRevision: number;
  alerts?: Array<components["schemas"]["DailyRuleReminderState"]>;
  contentHash: string;
  dailyEvidence: (components["schemas"]["DailySeries"]) | (null);
  dataBlockers: Array<string>;
  evaluatedAt: string;
  factRevisions: Array<components["schemas"]["DailyFactRevision"]>;
  fiveMinuteBars?: Array<components["schemas"]["FiveMinuteBar"]>;
  inventory: components["schemas"]["DailyInventoryApiView"];
  minutePrefix?: Array<components["schemas"]["MinuteBar"]>;
  minuteTarget?: (string) | (null);
  nextAction: "REVIEW_RISK_EXIT" | "CONFIRM_SIMULATED_TRADE" | "WAIT_FOR_VERIFIED_INPUT_OR_NEXT_SESSION";
  officialTradeDate: (string) | (null);
  planHash: string;
  planVersionId: string;
  quote: (components["schemas"]["DailyExecutionQuote"]) | (null);
  reviewId: string;
  riskAction: components["schemas"]["DailyRiskActionApiView"];
  riskInputKnown?: (boolean) | (null);
  risks: Array<components["schemas"]["DailyRiskApiView"]>;
  runtimeGeneration?: (string) | (null);
  signals: Array<components["schemas"]["DailySignalApiView"]>;
  symbol: string;
};

export type DailyExecutionQuote = {
  available_at: string;
  evaluated_at: string;
  liquidity_available: boolean;
  price_fen: number;
  quote_at: string;
  special_state_verified: boolean;
  symbol: string;
  tradable: boolean;
};

export type DailyFactCommand = {
  contentHash: string;
  evidence: string;
  expectedRevision: number;
  factId: string;
  kind: "PRICE_STRUCTURE" | "VOLUME_OR_CANDLE" | "TECHNICAL" | "TRADE_VIABILITY" | "SIGNAL_INVALIDATION" | "INDEPENDENT_EVENT" | "SEVERE_STRUCTURE" | "SEVERE_DETERIORATION" | "TRADABILITY" | "FULL_SESSION_SUSPENSION";
  officialEvidence?: (components["schemas"]["DailyOfficialEvidence"]) | (null);
  planVersionId: string;
  satisfied?: boolean;
  signalId?: (string) | (null);
  tradeDate: string;
};

export type DailyFactRevision = {
  id: string;
  revision: number;
};

export type DailyFieldBinding = {
  clause_ids: Array<string>;
  origin: "SOURCE" | "HUMAN_SUPPLEMENT" | "PRODUCT_CONTRACT";
  path: string;
  supplement_id: (string) | (null);
  unit: "JSON" | "FEN_FROM_YUAN" | "SHARES" | "RATIO" | "TEXT" | "STRUCTURE";
  value: components["schemas"]["JsonValue"];
};

export type DailyIndependentEvent = {
  evidence_requirement: string;
  mode: "REVIEWED_INDEPENDENT_EVENT";
};

export type DailyIndicatorCompare = {
  comparator: "LT" | "LTE" | "EQ" | "GTE" | "GT";
  formula_version: "daily-ta-v2";
  indicator: "MA20" | "MA60" | "MACD_DIF" | "MACD_DEA" | "MACD_HIST" | "RSI14" | "ATR14" | "BOLL_LOWER" | "BOLL_MIDDLE" | "BOLL_UPPER" | "BOLL_BANDWIDTH";
  offset: number;
  parameters: {
    [key: string]: number;
  };
  reference: (components["schemas"]["FixedDailyReference"] & { mode: "FIXED" }) | (components["schemas"]["DynamicDailyReference"] & { mode: "DYNAMIC" });
  type: "DAILY_INDICATOR_COMPARE";
};

export type DailyIndicatorCompareInput = {
  comparator: "LT" | "LTE" | "EQ" | "GTE" | "GT";
  formula_version: "daily-ta-v2";
  indicator: "MA20" | "MA60" | "MACD_DIF" | "MACD_DEA" | "MACD_HIST" | "RSI14" | "ATR14" | "BOLL_LOWER" | "BOLL_MIDDLE" | "BOLL_UPPER" | "BOLL_BANDWIDTH";
  offset: number;
  parameters: {
    [key: string]: number;
  };
  reference: (components["schemas"]["FixedDailyReferenceInput"] & { mode: "FIXED" }) | (components["schemas"]["DynamicDailyReference"] & { mode: "DYNAMIC" });
  type: "DAILY_INDICATOR_COMPARE";
};

export type DailyInventoryApiView = {
  coreQty: (number) | (null);
  known: boolean;
  revision: number;
  sellableCore: (number) | (null);
  sellableTactical: (number) | (null);
  symbol: string;
  tacticalQty: (number) | (null);
  totalQty: (number) | (null);
};

export type DailyInventoryResource = {
  evaluatedAt: string;
  reason?: (string) | (null);
  snapshot: (components["schemas"]["DailyInventoryApiView"]) | (null);
  status: "CURRENT" | "UNSUPPORTED";
  symbol: string;
};

export type DailyInventoryView = {
  core_qty: (number) | (null);
  known: boolean;
  revision: number;
  sellable_core: (number) | (null);
  sellable_tactical: (number) | (null);
  symbol: string;
  tactical_qty: (number) | (null);
  total_qty: (number) | (null);
};

export type DailyLevels = {
  low_buy: components["schemas"]["DailyZone"];
  pressure: components["schemas"]["DailyZone"];
  risk_comparison: "LT" | "LTE";
  risk_line_fen: number;
};

export type DailyManualActivation = {
  mode: "MANUAL";
};

export type DailyMapping = {
  bindings: Array<components["schemas"]["DailyFieldBinding"]>;
  candidate_content_hash: string;
  clauses: Array<components["schemas"]["DailyClause"]>;
  mapping_version: "daily-mapping-v1";
  supplements: Array<components["schemas"]["DailySupplement"]>;
};

export type DailyMetadata = {
  reference_price_fen?: (number) | (null);
  report_at?: (string) | (null);
};

export type DailyMutationReceipt = {
  id: string;
  recordedAt: string;
  revision: number;
};

export type DailyObsoleteRiskApiView = {
  confirmedTradeDate: (string) | (null);
  kind: "ORDINARY_TECHNICAL" | "SEVERE_TECHNICAL";
  riskId: (string) | (null);
  scopeEvidence: string;
  status: "CLEAR" | "PENDING" | "OBSERVATION" | "CONFIRMED" | "FULFILLED";
};

export type DailyOfficialEvidence = {
  applicableAssertion: string;
  documentTitle: string;
  documentUrl: string;
  issuer: string;
  publishedAt: string;
  verifiedAt: string;
};

export type DailyOfficialProof = {
  applicable_assertion: string;
  document_title: string;
  document_url: string;
  issuer: string;
  published_at: string;
  verified_at: string;
};

export type DailyPositionCommand = {
  coreQty: number;
  expectedRevision: number;
  symbol: string;
  tacticalQty: number;
};

export type DailyPriceCompare = {
  comparator: "LT" | "LTE" | "EQ" | "GTE" | "GT";
  field: "open" | "high" | "low" | "close";
  offset: number;
  reference: (components["schemas"]["FixedDailyReference"] & { mode: "FIXED" }) | (components["schemas"]["DynamicDailyReference"] & { mode: "DYNAMIC" });
  type: "DAILY_PRICE_COMPARE";
};

export type DailyPriceCompareInput = {
  comparator: "LT" | "LTE" | "EQ" | "GTE" | "GT";
  field: "open" | "high" | "low" | "close";
  offset: number;
  reference: (components["schemas"]["FixedDailyReferenceInput"] & { mode: "FIXED" }) | (components["schemas"]["DynamicDailyReference"] & { mode: "DYNAMIC" });
  type: "DAILY_PRICE_COMPARE";
};

export type DailyPriceInRange = {
  field: "open" | "high" | "low" | "close";
  offset: number;
  range: components["schemas"]["DailyZone"];
  type: "DAILY_PRICE_IN_RANGE";
};

export type DailyRangeActivation = {
  end_date: string;
  mode: "DATE_RANGE";
  start_date: string;
};

export type DailyReviewIssue = {
  code: string;
  issue_id: string;
  path: string;
  reason: string;
};

export type DailyReviewPreview = {
  candidateJson: string;
  review: components["schemas"]["DailyReviewSnapshot"];
  supplementRevision: number;
};

export type DailyReviewPreviewCommand = {
  candidateJson: string;
  mapping?: (components["schemas"]["DailyMapping"]) | (null);
  scopeSelections?: Array<components["schemas"]["DailySourceExclusion"]>;
  sourceText: string;
};

export type DailyReviewSnapshot = {
  content_hash: string;
  evidence_hash: string;
  issues: Array<components["schemas"]["DailyReviewIssue"]>;
  mapping: components["schemas"]["DailyMapping"];
  source_hash: string;
};

export type DailyRiskAction = {
  blockers: Array<string>;
  branch?: ("ORDINARY_TECHNICAL" | "SEVERE_TECHNICAL") | (null);
  cause_id?: (string) | (null);
  cause_revision?: (number) | (null);
  core_qty: (number) | (null);
  status: "WAITING" | "NONE" | "RISK_EXIT";
  tactical_qty: (number) | (null);
  target_core_qty?: (number) | (null);
  target_tactical_qty?: (number) | (null);
  unavailable_core_qty: (number) | (null);
  unavailable_tactical_qty: (number) | (null);
};

export type DailyRiskActionApiView = {
  blockers: Array<string>;
  branch?: ("ORDINARY_TECHNICAL" | "SEVERE_TECHNICAL") | (null);
  causeId?: (string) | (null);
  causeRevision?: (number) | (null);
  coreQty: (number) | (null);
  status: "WAITING" | "NONE" | "RISK_EXIT";
  tacticalQty: (number) | (null);
  targetCoreQty?: (number) | (null);
  targetTacticalQty?: (number) | (null);
  unavailableCoreQty: (number) | (null);
  unavailableTacticalQty: (number) | (null);
};

export type DailyRiskApiView = {
  basisId?: (string) | (null);
  blockers: Array<string>;
  breachTradeDate?: (string) | (null);
  causeCutoverAt?: (string) | (null);
  causeCutoverDate?: (string) | (null);
  confirmedTradeDate?: (string) | (null);
  consumedEvidenceIds?: Array<string>;
  earliestExecutionDate: (string) | (null);
  evidenceIds: Array<string>;
  fulfilledAt?: (string) | (null);
  involvesCore: boolean;
  kind: "ORDINARY_TECHNICAL" | "SEVERE_TECHNICAL";
  priority: number;
  reassessmentId?: (string) | (null);
  revision?: (number) | (null);
  riskComparison?: ("LT" | "LTE") | (null);
  riskId?: (string) | (null);
  riskLineFen?: (number) | (null);
  scopeEvidence: string;
  secondCloseDate?: (string) | (null);
  status: "CLEAR" | "PENDING" | "OBSERVATION" | "CONFIRMED" | "FULFILLED";
  suspensionConfirmationPolicy?: ("RESUME_FIRST_CLOSE" | "RESTART_ADJACENT_PAIR") | (null);
  targetCoreQty: number;
  targetTacticalQty: number;
  technicalEvidence?: Array<components["schemas"]["UnifiedConditionEvidence"]>;
  verifiedAt?: (string) | (null);
};

export type DailyRiskReassessmentCommand = {
  contentHash: string;
  expectedRevision: number;
  involvesCore: boolean;
  planVersionId: string;
  removalEvidence: string;
  riskId: string;
  scopeEvidence: string;
  symbol: string;
  targetCoreQty: number;
  targetTacticalQty: number;
};

export type DailyRiskState = {
  basis_id?: (string) | (null);
  blockers: Array<string>;
  breach_trade_date?: (string) | (null);
  cause_cutover_at?: (string) | (null);
  cause_cutover_date?: (string) | (null);
  confirmed_trade_date?: (string) | (null);
  consumed_evidence_ids?: Array<string>;
  earliest_execution_date: (string) | (null);
  evidence_ids: Array<string>;
  fulfilled_at?: (string) | (null);
  involves_core: boolean;
  kind: "ORDINARY_TECHNICAL" | "SEVERE_TECHNICAL";
  priority: number;
  reassessment_id?: (string) | (null);
  revision?: (number) | (null);
  risk_comparison?: ("LT" | "LTE") | (null);
  risk_id?: (string) | (null);
  risk_line_fen?: (number) | (null);
  scope_evidence: string;
  second_close_date?: (string) | (null);
  status: "CLEAR" | "PENDING" | "OBSERVATION" | "CONFIRMED" | "FULFILLED";
  suspension_confirmation_policy?: ("RESUME_FIRST_CLOSE" | "RESTART_ADJACENT_PAIR") | (null);
  target_core_qty: number;
  target_tactical_qty: number;
  technical_evidence?: Array<components["schemas"]["UnifiedConditionEvidence"]>;
  verified_at?: (string) | (null);
};

export type DailyRuleReminderState = {
  alert_kind: "RISK_ALERT";
  cause_id: (string) | (null);
  confirmation_kind: "OFFICIAL_DAILY_CLOSE" | "COMPLETED_BAR_CLOSE";
  confirmed_at: (string) | (null);
  confirmed_trade_date: (string) | (null);
  evidence: Array<{
      [key: string]: unknown;
    }>;
  outcome: "SATISFIED" | "UNSATISFIED" | "MISSING_INPUT";
  rule_id: string;
};

export type DailySeries = {
  adjustment_as_of: string;
  bars: Array<components["schemas"]["CertifiedDailyBar"]>;
  basis_id: string;
  cutoff: string;
  provider: string;
  quote_comparable: true;
  session_dates: Array<string>;
  suspended_dates: Array<string>;
  symbol: string;
};

export type DailySignalApiView = {
  basisId: string;
  blockers: Array<string>;
  bucket: "TACTICAL";
  confirmationKind?: "OFFICIAL_DAILY_CLOSE" | "COMPLETED_BAR_CLOSE";
  confirmedAt?: (string) | (null);
  confirmedTradeDate: string;
  evidence: Array<(components["schemas"]["DailyConditionEvidence"]) | (components["schemas"]["UnifiedConditionEvidence"])>;
  evidenceFingerprint: string;
  executableQty: number;
  executionDate: (string) | (null);
  executionWindow?: "NEXT_EXCHANGE_SESSION_ONLY" | "CURRENT_SESSION";
  lineage: string;
  planVersionId: string;
  plannedQty: number;
  resetTradeDate?: (string) | (null);
  reviewId: string;
  revision?: (number) | (null);
  riskInvalidated?: boolean;
  ruleId: string;
  side: "BUY" | "SELL";
  signalId: string;
  simulatedQty: number;
  state: "CONFIRMED" | "READY" | "EXPIRED" | "INVALIDATED" | "SIMULATED";
};

export type DailySignalState = {
  basis_id: string;
  blockers: Array<string>;
  bucket: "TACTICAL";
  confirmation_kind?: "OFFICIAL_DAILY_CLOSE" | "COMPLETED_BAR_CLOSE";
  confirmed_at?: (string) | (null);
  confirmed_trade_date: string;
  evidence: Array<(components["schemas"]["DailyConditionEvidence"]) | (components["schemas"]["UnifiedConditionEvidence"])>;
  evidence_fingerprint: string;
  executable_qty: number;
  execution_date: (string) | (null);
  execution_window?: "NEXT_EXCHANGE_SESSION_ONLY" | "CURRENT_SESSION";
  lineage: string;
  plan_version_id: string;
  planned_qty: number;
  reset_trade_date?: (string) | (null);
  review_id: string;
  revision?: (number) | (null);
  risk_invalidated?: boolean;
  rule_id: string;
  side: "BUY" | "SELL";
  signal_id: string;
  simulated_qty: number;
  state: "CONFIRMED" | "READY" | "EXPIRED" | "INVALIDATED" | "SIMULATED";
};

export type DailySimulationCommand = {
  causeId: string;
  expectedCauseRevision: number;
  expectedInventoryRevision: number;
  planVersionId: string;
  quantity: number;
};

export type DailySimulationReceipt = {
  inventory: components["schemas"]["DailyInventoryApiView"];
  inventoryRevision: number;
  priceFen: number;
  quantity: number;
  side: "BUY" | "SELL";
  signalId: (string) | (null);
  simulatedAt: string;
  simulationId: string;
};

export type DailySourceExclusion = {
  end: number;
  excerpt: string;
  origin?: "REGISTERED_FRAGMENT" | "HUMAN_SCOPE_SELECTION";
  reason: "FUNDAMENTALS_REVIEWED_AT_PLAN_GENERATION";
  source_hash: string;
  start: number;
};

export type DailyStateView = {
  evaluatedAt: (string) | (null);
  reason?: (string) | (null);
  risks?: Array<components["schemas"]["DailyObsoleteRiskApiView"]>;
  snapshot: (components["schemas"]["DailyEvaluationApiView"]) | (null);
  status: "CURRENT" | "AWAITING_EVALUATION" | "INACTIVE" | "UNSUPPORTED";
  symbol: string;
};

export type DailySupplement = {
  candidate_content_hash: string;
  path: string;
  reason: string;
  supplement_id: string;
  value: components["schemas"]["JsonValue"];
};

export type DailySupplementCommand = {
  candidateJson: string;
  contentHash: string;
  expectedRevision: number;
  supplements: Array<components["schemas"]["DailySupplement"]>;
};

export type DailyTechnicalRemainder = {
  disposition: "POLICY" | "UNRESOLVED" | "UNSUPPORTED";
  end: number;
  excerpt: string;
  paths: Array<string>;
  reason: string;
  start: number;
};

export type DailyTradingRules = {
  settlement?: "NEXT_EXCHANGE_SESSION";
  special_state_restrictions?: "BLOCK_UNVERIFIED";
  tick_size_fen?: 1;
};

export type DailyValidity = {
  end_date: string;
  mode?: "DATE_RANGE";
  start_date: string;
};

export type DailyVolumeRatio = {
  baseline: "PREVIOUS" | "MEAN";
  comparator: "LT" | "LTE" | "EQ" | "GTE" | "GT";
  offset: number;
  ratio: string;
  type: "DAILY_VOLUME_RATIO";
  window: number;
};

export type DailyVolumeRatioInput = {
  baseline: "PREVIOUS" | "MEAN";
  comparator: "LT" | "LTE" | "EQ" | "GTE" | "GT";
  offset: number;
  ratio: (number) | (string);
  type: "DAILY_VOLUME_RATIO";
  window: number;
};

export type DailyZone = {
  high_fen: number;
  include_high: boolean;
  include_low: boolean;
  low_fen: number;
};

export type DashboardCounts = {
  actionable: number;
  blocked: number;
  lowZoneWatch: number;
  normal: number;
  risk: number;
  stale: number;
};

export type DataHealthStatus = "STARTING" | "LIVE" | "STALE" | "GAPPED" | "DEGRADED" | "BLOCKED" | "CLOSE_PENDING";

export type DataHealthView = {
  dataAgeSeconds: (number) | (null);
  fresh: boolean;
  latestBarEnd: (string) | (null);
  requiredDataComplete: boolean;
  status: components["schemas"]["DataHealthStatus"];
};

export type DatabaseHealthView = {
  errorCode: (string) | (null);
  lastBackupAt: (string) | (null);
  lastCheckpointAt: (string) | (null);
  status: components["schemas"]["RuntimeResourceStatus"];
  walStatus: components["schemas"]["RuntimeResourceStatus"];
};

export type DecisionEvidenceView = {
  children?: Array<components["schemas"]["DecisionEvidenceView"]>;
  code: string;
  facts?: Array<components["schemas"]["EvidenceFactView"]>;
  kind: components["schemas"]["EvidenceKind"];
  missingInputs?: Array<components["schemas"]["MissingInputCode"]>;
  outcome: components["schemas"]["ConditionOutcome"];
};

export type DecisionZone = "LOW_BUY" | "OBSERVATION" | "PRESSURE" | "BELOW_RISK" | "OUTSIDE" | "UNKNOWN";

export type DeliveryHealthView = {
  errorCode: (string) | (null);
  failedCount: number;
  lastDeliveredAt: (string) | (null);
  nextRetryAt: (string) | (null);
  pendingCount: number;
  status: components["schemas"]["RuntimeResourceStatus"];
};

export type DiagnosticEvaluationCommand = {
  bucketEnd?: (string) | (null);
  evaluationKind: components["schemas"]["EvaluationKind"];
  expectedRevision: number;
  officialTradeDate?: (string) | (null);
  symbol: string;
};

export type DiagnosticEvaluationView = {
  alertEnqueued: false;
  audited: boolean;
  decision: components["schemas"]["AuthoritativeDecisionView"];
  evaluationIdentity: (components["schemas"]["IntradayDiagnosticIdentityView"] & { kind: "INTRADAY" }) | (components["schemas"]["OfficialCloseDiagnosticIdentityView"] & { kind: "OFFICIAL_CLOSE" });
  positionChanged: false;
  sourceRevision: number;
  stateMutationApplied: false;
};

export type DraftReviewIssue = {
  kind: components["schemas"]["ReviewIssueKind"];
  material: boolean;
  path: string;
  resolved?: boolean;
};

export type DynamicDailyReference = {
  formula_version: "daily-ta-v2";
  indicator: "MA20" | "MA60" | "MACD_DIF" | "MACD_DEA" | "MACD_HIST" | "RSI14" | "ATR14" | "BOLL_LOWER" | "BOLL_MIDDLE" | "BOLL_UPPER" | "BOLL_BANDWIDTH";
  mode: "DYNAMIC";
  offset: number;
  parameters: {
    [key: string]: number;
  };
};

export type EpisodeStatus = "ACTIVE" | "ALERTED" | "CLOSED";

export type ErrorDetail = {
  code: string;
  location: Array<(string) | (number)>;
  message: string;
};

export type ErrorPayload = {
  code: components["schemas"]["ApiErrorCode"];
  details?: Array<components["schemas"]["ErrorDetail"]>;
  message: string;
  requestId: string;
};

export type ErrorResponse = {
  error: components["schemas"]["ErrorPayload"];
};

export type EvaluationKind = "INTRADAY" | "OFFICIAL_CLOSE";

export type EvidenceFactView = {
  key: string;
  unit: components["schemas"]["EvidenceUnit"];
  value: (boolean) | (number) | (string) | (string) | (string) | (string);
};

export type EvidenceKind = "CONDITION" | "RULE";

export type EvidenceUnit = "FEN" | "SHARES" | "RATIO" | "BARS" | "YUAN" | "COUNT" | "BOOLEAN" | "DATE" | "DATETIME" | "CODE" | "POINTS";

export type ExecutionStatus = "FILLED" | "UNFILLED" | "IGNORED";

export type ExecutorHealthView = {
  activeCount: number;
  maxWorkers: number;
  waitingCount: number;
};

export type ExplicitAlertView = {
  acknowledgedAt?: (string) | (null);
  activationRevision: number;
  causeId: string;
  conditionEvidence: components["schemas"]["ExplicitConditionEvidenceView"];
  createdAt: string;
  currentActionable: boolean;
  dedupKey: string;
  evaluatedAt: string;
  eventId: string;
  messageText: string;
  name: string;
  nextStep: "REVIEW_BUY_REMINDER" | "REVIEW_SELL_REMINDER" | "REVIEW_RISK_REMINDER";
  payloadSchemaVersion: "explicit-rule-alert-v1";
  planHash: string;
  planId: string;
  planVersion: number;
  quantity: (number) | (null);
  revision: number;
  ruleId: string;
  safetyEvidence: (components["schemas"]["ExplicitConditionEvidenceView"]) | (null);
  sequence: number;
  severity: "ACTION" | "RISK";
  signalType: "BUY" | "SELL" | "RISK_ALERT" | "RISK_EXIT";
  symbol: string;
  targetBucketEnd: string;
  tradingDate: string;
};

export type ExplicitConditionEvidenceView = {
  barEnds?: Array<string>;
  children?: Array<components["schemas"]["ExplicitConditionEvidenceView"]>;
  code: string;
  facts?: Array<components["schemas"]["EvidenceFactView"]>;
  missingInputs?: Array<string>;
  outcome: string;
  planPath: string;
};

export type ExplicitPlanCapabilityView = {
  executionMode?: "CONDITION_PLAN";
  executionVersion?: "condition-plan-v1";
  isolatedTrustedReviewOnly?: false;
  pendingRequirements?: Array<string>;
  publicActivationAvailable?: true;
  schemaVersion?: 5;
  supportedActions?: Array<"BUY" | "SELL" | "RISK_ALERT">;
};

export type ExplicitPlanEntryView = {
  actionableRuleIds: Array<string>;
  activationRevision: number;
  availability: "CURRENT" | "CACHED";
  currentActionable: boolean;
  explicitRuntime: components["schemas"]["ExplicitPlanRuntimeView"];
  name: string;
  observedAt: string;
  planFamily: "EXPLICIT_RULES";
  planHash: string;
  planVersionId: string;
  resultHash: string;
  ruleEligibility: Array<components["schemas"]["RuleEligibilityView"]>;
  scope: components["schemas"]["PlanScopeView"];
  symbol: string;
};

export type ExplicitPlanRuntimeView = {
  activationRevision: number;
  evaluatedAt: (string) | (null);
  planHash: string;
  planVersionId: string;
  ruleOutcomes: Array<components["schemas"]["ExplicitRuleOutcomeView"]>;
  status: "AWAITING_EVALUATION" | "CURRENT";
  symbol: string;
  targetBucketEnd: (string) | (null);
};

export type ExplicitRuleOutcomeView = {
  action: "BUY" | "SELL" | "RISK_ALERT";
  blockers?: Array<string>;
  conditionCode: string;
  conditionEvidence?: (components["schemas"]["ExplicitConditionEvidenceView"]) | (null);
  missingInputs?: Array<string>;
  outcome: "SATISFIED" | "UNSATISFIED" | "MISSING_INPUT";
  ruleId: string;
  suppressionReason: ("ONCE_ALREADY_EMITTED" | "TARGET_ALREADY_EMITTED") | (null);
};

export type ExtractionIssue = {
  material: boolean;
  message: string;
  path: string;
};

export type FieldBindingView = {
  bindingKind?: components["schemas"]["BindingKind"];
  clauseIds?: Array<string>;
  contractId?: (string) | (null);
  origin: components["schemas"]["BindingOrigin"];
  path: string;
  supplementId?: (string) | (null);
  unit: components["schemas"]["BindingUnit"];
  value: (boolean) | (number) | (string) | (null);
};

export type FieldEvidence = {
  end?: (number) | (null);
  excerpt: string;
  path: string;
  start?: (number) | (null);
};

export type FiveMinuteBar = {
  amount_yuan: string;
  bar_end: string;
  close_fen: number;
  formula_version?: "ta-v1";
  high_fen: number;
  low_fen: number;
  open_fen: number;
  symbol: string;
  volume_shares: number;
};

export type FixedDailyReference = {
  as_of: string;
  mode: "FIXED";
  source: string;
  unit: "FEN" | "INDICATOR";
  value: string;
};

export type FixedDailyReferenceInput = {
  as_of: string;
  mode: "FIXED";
  source: string;
  unit: "FEN" | "INDICATOR";
  value: (number) | (string);
};

export type IndexConditionEvidenceView = {
  actualValue: (string) | (null);
  comparisonValue: (string) | (null);
  conditionType: "INDEX_CLOSE_GTE_MA" | "INDEX_CLOSE_LTE_MA" | "INDEX_MA_NON_DECREASING" | "INDEX_MA_NON_INCREASING" | "INDEX_RETURN_GTE" | "INDEX_RETURN_LTE";
  dataCutoff: (string) | (null);
  decisionCutoff: string;
  formulaDefinitionHash: (string) | (null);
  formulaId: "SMA" | "SMA_LOOKBACK" | "RETURN";
  indexCode: components["schemas"]["MarketIndexCode"];
  mappingVersion: "board-index-map-v1";
  missingInputs?: Array<components["schemas"]["MissingInputCode"]>;
  outcome: components["schemas"]["ConditionOutcome"];
  parameters?: Array<components["schemas"]["EvidenceFactView"]>;
  planPath: string;
  snapshotHash: (string) | (null);
  unit: components["schemas"]["MarketIndexFactUnit"];
};

export type IndexConditionProgressView = {
  missing: number;
  satisfied: number;
  total: number;
  unsatisfied: number;
};

export type IndexScopeView = {
  dataCutoff: (string) | (null);
  indexCode: components["schemas"]["MarketIndexCode"];
  kind: "INDEX";
  nextRetryAt: (string) | (null);
  progress: components["schemas"]["ScopeProgressView"];
  reasonCode: ("RUNTIME_STARTING" | "RUNTIME_STOPPING" | "RUNTIME_STOPPED" | "RUNTIME_FAULT" | "COORDINATOR_STALLED" | "STORAGE_UNAVAILABLE" | "BEFORE_FIRST_MINUTE" | "SESSION_BREAK" | "SESSION_CLOSED" | "NO_ACTIVE_PLANS" | "AWAITING_FIRST_EVALUATION" | "CALENDAR_UNKNOWN" | "REFERENCE_PENDING" | "COVERAGE_INCOMPLETE" | "CLOSE_PENDING" | "PUBLICATION_PENDING" | "PROVIDER_UNAVAILABLE" | "RATE_LIMITED" | "CREDENTIAL_MISSING" | "PERMISSION_DENIED" | "SEMANTICS_INCOMPATIBLE" | "CONFIGURATION_INVALID" | "HISTORY_UNAVAILABLE" | "STATE_UNAVAILABLE" | "GENERATION_CHANGED" | "NEEDS_RESTART" | "LEGACY_PLANS_REQUIRE_REVIEW" | "SCOPED_DEPENDENCY_FAILURE") | (null);
  requiredTarget: ((components["schemas"]["IntradayTargetView"] & { kind: "INTRADAY" }) | (components["schemas"]["OfficialCloseTargetView"] & { kind: "OFFICIAL_CLOSE" })) | (null);
  scopeKey: string;
  status: "WAITING" | "RECOVERING" | "READY" | "BLOCKED";
};

export type IntradayDiagnosticIdentityView = {
  bucketEnd: string;
  formulaVersion: "ta-v1";
  kind: "INTRADAY";
  planHash: string;
  symbol: string;
};

export type IntradayTargetView = {
  kind: "INTRADAY";
  targetEnd: string;
};

export type InventorySourceTreatmentView = {
  contractId: "independent-inventory-v1";
  kind: "INVENTORY_ASSERTION";
  ledgerEffect: "NONE_REQUIRES_INDEPENDENT_CONFIRMATION";
  requiredOperation: "/api/v1/position-inventory-confirmations";
  sellableQuantity: number;
  settlementBasis: "HELD_BEFORE_TEST_DATE_ALL_SELLABLE";
  spans: Array<components["schemas"]["SourceSpanView"]>;
  symbol: string;
  symbolSpan: components["schemas"]["SourceSpanView"];
  totalQuantity: number;
  treatmentId: string;
};

export type JsonValue = unknown;

export type KnownLoopCash = {
  balance_fen: number;
  kind?: "KNOWN";
};

export type LegacyPlanEntryView = {
  actionableUntil: (string) | (null);
  activationRevision: number;
  availability: "CURRENT" | "CACHED";
  currentActionable: boolean;
  decision: components["schemas"]["AuthoritativeDecisionView"];
  name: string;
  observedAt: string;
  planFamily: "LEGACY_LOW_BUY";
  planHash: string;
  planVersionId: string;
  referenceMarket: (components["schemas"]["SymbolReferenceMarketView"]) | (null);
  riskDistanceFen: (number) | (null);
  satisfiedConditionCount: number;
  scope: components["schemas"]["PlanScopeView"];
  symbol: string;
  totalConditionCount: number;
};

export type LegacyPlanInvalidateCommand = {
  confirmation: "INVALIDATE_LEGACY_PLANS";
  fingerprint: string;
};

export type LegacyPlanInvalidateResult = {
  restartRequired?: true;
  symbols: Array<string>;
};

export type LegacyPlanItemView = {
  planVersionId: string;
  revision: number;
  symbol: string;
};

export type LegacyPlanPreviewResponse = {
  available: boolean;
  fingerprint?: (string) | (null);
  plans?: Array<components["schemas"]["LegacyPlanItemView"]>;
};

export type LoopAccountInput = {
  cash: (components["schemas"]["KnownLoopCash"] & { kind: "KNOWN" }) | (components["schemas"]["UnknownLoopCash"] & { kind: "UNKNOWN" });
  evidence: string;
  inventory_known: boolean;
  lots: Array<components["schemas"]["LoopInitialLot"]>;
  opening_mark: (components["schemas"]["LoopOpeningMark"]) | (null);
  snapshot_at: string;
};

export type LoopAccountReceipt = {
  account: components["schemas"]["LoopAccountState"];
  authority_receipt: components["schemas"]["SimulationReceipt"];
  command: components["schemas"]["SimulationCommand"];
  costs: components["schemas"]["LoopCosts"];
  released_cost_fen: (number) | (null);
  request_key: string;
  settlement: components["schemas"]["LoopFillCosts"];
};

export type LoopAccountState = {
  cash: (components["schemas"]["KnownLoopCash"]) | (components["schemas"]["UnknownLoopCash"]);
  inventory_known: boolean;
  lots: Array<components["schemas"]["LoopLedgerLot"]>;
  paid_fees_fen: number;
  realized_pnl_fen: (number) | (null);
  revision: number;
};

export type LoopAttempt = {
  at: string;
  cause_id: string;
  intent_id: string;
  minute: components["schemas"]["MinuteBar"];
  reason: (string) | (null);
  receipt?: (components["schemas"]["LoopAccountReceipt"]) | (null);
  status: "FILLED" | "BLOCKED" | "CLOSED";
};

export type LoopAuditEvent = {
  at: string;
  cause_event_id: (string) | (null);
  event_id: string;
  payload: components["schemas"]["LoopAuditPayload"];
  run_id: string;
  schema_version?: "monitor-loop-event-v1";
  sequence: number;
};

export type LoopAuditPayload = (components["schemas"]["LoopEvaluation"] & { kind: "EVALUATED" }) | (components["schemas"]["LoopReminder"] & { kind: "REMINDED" }) | (components["schemas"]["LoopRequest"] & { kind: "REQUESTED" }) | (components["schemas"]["LoopExecution"] & { kind: "EXECUTED" }) | (components["schemas"]["LoopResultingState"] & { kind: "STATE" }) | (components["schemas"]["LoopValuationEvent"] & { kind: "VALUATION" });

export type LoopCosts = {
  buy_slippage_fen: number;
  commission_rate: string;
  formula_version?: "monitor-loop-costs-v1";
  minimum_commission_fen: number;
  sell_slippage_fen: number;
  stamp_duty_rate: string;
  transfer_fee_rate: string;
};

export type LoopCycleSummary = {
  attempts: number;
  evaluations: number;
  fills: number;
  intents: number;
  unfilled_intents: number;
};

export type LoopEndBoundary = {
  evidence_cutoff: string;
  origin: "EXPLICIT" | "DEFAULTED";
  requested_end_date: (string) | (null);
  resolved_end_date: string;
  started_at: string;
  submitted_at: string;
};

export type LoopEvaluation = {
  alerts: Array<components["schemas"]["ResearchReminder"]>;
  blockers: Array<string>;
  conditions: Array<components["schemas"]["ResearchRuleEvidence"]>;
  duplicate: boolean;
  evaluation_id: (string) | (null);
  inventory: components["schemas"]["DailyInventoryView"];
  kind?: "EVALUATED";
  minute_target: (string) | (null);
  official_trade_date: (string) | (null);
  risk_action: components["schemas"]["DailyRiskAction"];
  risks: Array<components["schemas"]["DailyRiskState"]>;
  signals: Array<components["schemas"]["DailySignalState"]>;
};

export type LoopExecution = {
  attempt: components["schemas"]["LoopAttempt"];
  kind?: "EXECUTED";
};

export type LoopFillCosts = {
  commission_fen: number;
  fill_price_fen: number;
  notional_fen: number;
  quantity: number;
  quote_fen: number;
  side: "BUY" | "SELL";
  stamp_duty_fen: number;
  total_fees_fen: number;
  transfer_fee_fen: number;
};

export type LoopInitialLot = {
  acquired_trade_date: (string) | (null);
  bucket: "CORE" | "TACTICAL";
  cost_basis_fen: (number) | (null);
  evidence: string;
  lot_key: string;
  quantity: number;
  sellable_quantity: (number) | (null);
};

export type LoopLedgerLot = {
  acquired_trade_date: (string) | (null);
  bucket: "CORE" | "TACTICAL";
  cost_basis_fen: (number) | (null);
  lot_key: string;
  quantity: number;
};

export type LoopMetrics = {
  blockers: Array<string>;
  cost_pnl_fen: (number) | (null);
  equity_change_fen: (number) | (null);
  final_equity_fen: (number) | (null);
  initial_equity_fen: (number) | (null);
  interval_return: (string) | (null);
  maximum_drawdown: (string) | (null);
  paid_fees_fen: number;
  realized_pnl_fen: (number) | (null);
  slippage_fen: number;
  turnover: (string) | (null);
  unrealized_pnl_fen: (number) | (null);
  valuation_valid: boolean;
};

export type LoopOpeningMark = {
  available_at: string;
  evidence: string;
  price_at: string;
  price_fen: number;
};

export type LoopPlanReview = {
  confirmed: true;
  content_hash: string;
  evidence: string;
  evidence_hash: string;
  reviewed_at: string;
  source_hashes: Array<string>;
};

export type LoopPlanVersion = {
  authored_at?: (string) | (null);
  authored_date?: (string) | (null);
  available_at: string;
  evidence_hash: string;
  information_cutoff: string;
  plan_hash: string;
  review: components["schemas"]["LoopPlanReview"];
  snapshot: components["schemas"]["UnifiedTradePlan"];
  source_hashes: Array<string>;
  version_id: string;
};

export type LoopReminder = {
  kind?: "REMINDED";
  reminder: components["schemas"]["CapturedReminder"];
};

export type LoopRequest = {
  cause_id: string;
  intent_id: string;
  kind?: "REQUESTED";
  ready_at: string;
};

export type LoopResponsePolicy = {
  fill_model?: "NEXT_ELIGIBLE_MINUTE_CLOSE";
  mode: "FOLLOW_REMINDERS" | "OBSERVE_ONLY" | "RECORDED_ACTIONS";
  response_delay_seconds?: number;
};

export type LoopResultingState = {
  account: components["schemas"]["LoopAccountState"];
  inventory: components["schemas"]["DailyInventoryView"];
  kind?: "STATE";
};

export type LoopValuation = {
  account_revision: number;
  accounting_cost_fen: (number) | (null);
  at: string;
  available_at: (string) | (null);
  blockers: Array<string>;
  cash_fen: (number) | (null);
  cost_pnl_fen: (number) | (null);
  equity_fen: (number) | (null);
  market_value_fen: (number) | (null);
  position_quantity: (number) | (null);
  price_at: (string) | (null);
  price_fen: (number) | (null);
  realized_pnl_fen: (number) | (null);
  unrealized_pnl_fen: (number) | (null);
  valuation_valid: boolean;
};

export type LoopValuationEvent = {
  kind?: "VALUATION";
  valuation: components["schemas"]["LoopValuation"];
};

export type ManualEventRiskUnknownReason = "NO_ACTIVE_PLAN" | "MISSING_CONFIRMATION" | "PLAN_CHANGED" | "EXPIRED";

export type ManualEventRiskView = {
  confirmedAt?: (string) | (null);
  expiresOn?: (string) | (null);
  planVersionId?: (string) | (null);
  reason?: (components["schemas"]["ManualEventRiskUnknownReason"]) | (null);
  revision: number;
  status: components["schemas"]["ManualEventRiskViewStatus"];
  symbol: string;
};

export type ManualEventRiskViewStatus = "UNKNOWN" | "CLEAR" | "RISK_PRESENT";

export type MarketIndexBarPage = {
  hasMore: boolean;
  items?: Array<components["schemas"]["MarketIndexBarView"]>;
  limit: number;
  nextCursor: (string) | (null);
  snapshotHash: string;
};

export type MarketIndexBarView = {
  amount: (string) | (null);
  barAt: string;
  closePoints: string;
  highPoints: string;
  indexCode: components["schemas"]["MarketIndexCode"];
  interval: components["schemas"]["MarketIndexInterval"];
  lowPoints: string;
  observedAt: string;
  openPoints: string;
  providerRevision: number;
  sourceKind: components["schemas"]["MarketIndexSourceKind"];
  volume: (string) | (null);
};

export type MarketIndexCode = "000001.SH" | "399001.SZ" | "399107.SZ" | "399006.SZ" | "000688.SH" | "899050.BJ";

export type MarketIndexFactUnit = "POINTS" | "RATIO";

export type MarketIndexHealth = "LIVE" | "STALE" | "GAPPED" | "BLOCKED";

export type MarketIndexInterval = "FIVE_MINUTE" | "OFFICIAL_DAILY";

export type MarketIndexIssueCode = "MISSING_FIVE_MINUTE_BAR" | "MISSING_OFFICIAL_DAILY_BAR" | "INSUFFICIENT_HISTORY" | "STALE_DATA" | "DUPLICATE_IDENTITY" | "GAPPED_SERIES" | "INDEX_IDENTITY_MISMATCH" | "FUTURE_DATA" | "INVALID_TIMESTAMP" | "NONCANONICAL_DECIMAL" | "INVALID_OHLC" | "FORMULA_MISMATCH" | "PROVIDER_UNAVAILABLE";

export type MarketIndexLatestAcquisition = {
  decisionCutoff: string;
  health: components["schemas"]["MarketIndexHealth"];
  issues: Array<components["schemas"]["MarketIndexIssueCode"]>;
  nextRetryAt: (string) | (null);
  observedAt: string;
};

export type MarketIndexOverviewData = {
  amount: (string) | (null);
  bars: Array<components["schemas"]["MarketIndexBarView"]>;
  closePoints: string;
  completedBucketAt: string;
  highPoints: string;
  lowPoints: string;
  observedAt: string;
  priorClosePoints: (string) | (null);
  sessionChangeRatio: (string) | (null);
  snapshotHash: string;
  sourceKind: components["schemas"]["MarketIndexSourceKind"];
};

export type MarketIndexOverviewItem = {
  board: components["schemas"]["Board"];
  data: (components["schemas"]["MarketIndexOverviewData"]) | (null);
  dataStatus: "CURRENT" | "INCOMPLETE" | "CACHED" | "EMPTY" | "UNVERIFIED";
  displayName: string;
  indexCode: components["schemas"]["MarketIndexCode"];
  latestAcquisition: (components["schemas"]["MarketIndexLatestAcquisition"]) | (null);
};

export type MarketIndexOverviewResponse = {
  indexes: Array<components["schemas"]["MarketIndexOverviewItem"]>;
  marketSession: components["schemas"]["MarketSessionView"];
  marketTurnover: (components["schemas"]["MarketTurnoverSummaryView"]) | (null);
  observedAt: string;
  runtimeGeneration: (string) | (null);
  schemaVersion?: 1;
  sequence: number;
};

export type MarketIndexSnapshotView = {
  board: components["schemas"]["Board"];
  closePoints: (string) | (null);
  completedBucketAt: (string) | (null);
  displayName: string;
  health: components["schemas"]["MarketIndexHealth"];
  indexCode: components["schemas"]["MarketIndexCode"];
  indicatorFacts: Array<(components["schemas"]["SmaIndicatorFactView"] & { formulaId: "SMA" }) | (components["schemas"]["SmaLookbackIndicatorFactView"] & { formulaId: "SMA_LOOKBACK" }) | (components["schemas"]["ReturnIndicatorFactView"] & { formulaId: "RETURN" })>;
  issues: Array<components["schemas"]["MarketIndexIssueCode"]>;
  mappedSymbolCount: number;
  mappingVersion: "board-index-map-v1";
  nextRetryAt?: (string) | (null);
  observedAt: string;
  priorClosePoints: (string) | (null);
  recoveryAttempts?: (number) | (null);
  revision: number;
  sessionChangeRatio: (string) | (null);
  snapshotHash: string;
};

export type MarketIndexSourceKind = "PROVISIONAL" | "OFFICIAL";

export type MarketSessionView = {
  calendarStatus: "KNOWN" | "UNKNOWN";
  displayTradeDate: (string) | (null);
  expectedBucketAt: (string) | (null);
  phase: "PREOPEN" | "OPEN" | "BREAK" | "CLOSED" | "UNKNOWN";
  sessionDate: string;
};

export type MarketTurnoverSummaryView = {
  benchmarkCodes: Array<components["schemas"]["MarketIndexCode"]>;
  changeAmount: string;
  completedBucketAt: string;
  currentAmount: string;
  estimateMethod: "LINEAR_COMPLETED_FIVE_MINUTE_BUCKETS";
  estimatedFullDayAmount: string;
  previousAmount: string;
};

export type MinuteBar = {
  amount_yuan: string;
  bar_end: string;
  close_fen: number;
  high_fen: number;
  low_fen: number;
  open_fen: number;
  received_at: string;
  symbol: string;
  volume_shares: number;
};

export type MinuteCloseBelow = {
  price_fen: number;
  timeframe_minutes: 5;
  type: "MINUTE_CLOSE_BELOW";
};

export type MinuteCloseInRange = {
  high_fen: number;
  include_high: boolean;
  include_low: boolean;
  low_fen: number;
  timeframe_minutes: 5;
  type: "MINUTE_CLOSE_IN_RANGE";
};

export type MinuteVolumeToMeanGte = {
  history_scope: "CONTIGUOUS_TRADING_BARS";
  minimum_ratio: string;
  timeframe_minutes: 5;
  type: "MINUTE_VOLUME_TO_MEAN_GTE";
  window_bars: number;
};

export type MinuteVolumeToMeanGteInput = {
  history_scope: "CONTIGUOUS_TRADING_BARS";
  minimum_ratio: (number) | (string);
  timeframe_minutes: 5;
  type: "MINUTE_VOLUME_TO_MEAN_GTE";
  window_bars: number;
};

export type MissingInputCode = "COMPLETE_MINUTE_BAR" | "PREVIOUS_MINUTE_BAR" | "COMPLETE_5M_BAR" | "PREVIOUS_5M_BAR" | "COMPLETE_5M_BAR_WINDOW" | "ROLLING_VOLUME_WINDOW" | "SESSION_BARS" | "DAILY_INDICATORS" | "PROVISIONAL_DAILY_BAR" | "FIVE_MINUTE_INDICATORS" | "INDICATOR_VALUE" | "OFFICIAL_DAILY_CLOSE" | "TRADING_CALENDAR" | "DAILY_LIMIT" | "MANUAL_EVENT_RISK" | "INDEX_SNAPSHOT" | "INDEX_IDENTITY" | "INDEX_CUTOFF" | "INDEX_HEALTH" | "INDEX_FACT" | "INDEX_HISTORY" | "INDEX_FORMULA";

export type MonitorLoopReport = {
  authority_id: string;
  boundary: components["schemas"]["LoopEndBoundary"];
  cycle: components["schemas"]["LoopCycleSummary"];
  dataset_hash: string;
  event_count: number;
  event_set_hash: string;
  final_account: components["schemas"]["LoopAccountState"];
  final_inventory: components["schemas"]["DailyInventoryView"];
  final_valuation: components["schemas"]["LoopValuation"];
  input_hash: string;
  last_evidence_at: (string) | (null);
  last_valuation_at: string;
  metrics: components["schemas"]["LoopMetrics"];
  opening_valuation: components["schemas"]["LoopValuation"];
  plan_hash: string;
  report_hash: string;
  run_id: string;
  schema_version?: "backtest-report-v4";
  symbol: string;
};

export type NextStepCode = "WAIT_FOR_COMPLETE_BAR" | "WAIT_FOR_REQUIRED_DATA" | "WATCH_LOW_ZONE" | "WATCH_PRESSURE" | "REVIEW_BLOCKER" | "WAIT_FOR_OFFICIAL_CLOSE" | "WAIT_FOR_NEXT_TRADING_DAY" | "WAIT_FOR_SETTLEMENT" | "RECORD_CONFIRMED_FILL";

export type NextStepView = {
  code: components["schemas"]["NextStepCode"];
  notBefore?: (string) | (string) | (null);
  requiredInputs?: Array<components["schemas"]["MissingInputCode"]>;
};

export type ObsoleteDailyAlertView = {
  acknowledgedAt: (string) | (null);
  createdAt: string;
  currentActionable?: false;
  dedupKey: string;
  evaluatedAt: string;
  eventId: string;
  messageText: string;
  name: string;
  payloadSchemaVersion?: "daily-plan-alert-v1";
  planHash: string;
  planId: string;
  planVersion: number;
  reason?: "DAILY_SIMULATION_LEGACY_DATA_UNSUPPORTED";
  revision: number;
  sequence: number;
  signalType: "BUY" | "SELL" | "RISK_EXIT";
  status?: "UNSUPPORTED";
  symbol: string;
  tradingDate: string;
};

export type OfficialCloseDiagnosticIdentityView = {
  formulaVersion: "ta-v1";
  kind: "OFFICIAL_CLOSE";
  officialTradeDate: string;
  planHash: string;
  symbol: string;
};

export type OfficialCloseTargetView = {
  kind: "OFFICIAL_CLOSE";
  tradeDate: string;
};

export type OfficialDailyConfirmation = {
  kind: "OFFICIAL_DAILY_CLOSE";
};

export type OpeningAccountFacts = {
  cash_fen: (components["schemas"]["OpeningFact_Annotated_int__FieldInfo_annotation_NoneType__required_True__metadata__Ge_ge_0___Le_le_9007199254740991_____"]) | (null);
  inventory_quantity: (components["schemas"]["OpeningFact_Annotated_int__FieldInfo_annotation_NoneType__required_True__metadata__Ge_ge_0___Le_le_9007199254740991___MultipleOf_multiple_of_100_____"]) | (null);
  lots: Array<components["schemas"]["OpeningLotFacts"]>;
  snapshot_at: (components["schemas"]["OpeningFact_Annotated_datetime__BeforeValidator__AfterValidator__"]) | (null);
};

export type OpeningFact_Annotated_Decimal__BeforeValidator__FieldInfo_annotation_NoneType__required_True__metadata__Ge_ge_0___Le_le_9007199254740991____PydanticGeneralMetadata_allow_inf_nan_False_____ = {
  end: number;
  excerpt: string;
  start: number;
  value: string;
};

export type OpeningFact_Annotated_datetime__BeforeValidator__AfterValidator__ = {
  end: number;
  excerpt: string;
  start: number;
  value: string;
};

export type OpeningFact_Annotated_int__FieldInfo_annotation_NoneType__required_True__metadata__Ge_ge_0___Le_le_9007199254740991___MultipleOf_multiple_of_100_____ = {
  end: number;
  excerpt: string;
  start: number;
  value: number;
};

export type OpeningFact_Annotated_int__FieldInfo_annotation_NoneType__required_True__metadata__Ge_ge_0___Le_le_9007199254740991_____ = {
  end: number;
  excerpt: string;
  start: number;
  value: number;
};

export type OpeningFact_Annotated_int__FieldInfo_annotation_NoneType__required_True__metadata__Gt_gt_0___Le_le_9007199254740991___MultipleOf_multiple_of_100_____ = {
  end: number;
  excerpt: string;
  start: number;
  value: number;
};

export type OpeningFact_Literal__CORE____TACTICAL___ = {
  end: number;
  excerpt: string;
  start: number;
  value: "CORE" | "TACTICAL";
};

export type OpeningFact_date_ = {
  end: number;
  excerpt: string;
  start: number;
  value: string;
};

export type OpeningLotFacts = {
  acquired_trade_date: (components["schemas"]["OpeningFact_date_"]) | (null);
  bucket: (components["schemas"]["OpeningFact_Literal__CORE____TACTICAL___"]) | (null);
  lot_key: string;
  quantity: components["schemas"]["OpeningFact_Annotated_int__FieldInfo_annotation_NoneType__required_True__metadata__Gt_gt_0___Le_le_9007199254740991___MultipleOf_multiple_of_100_____"];
  sellable_quantity: (components["schemas"]["OpeningFact_Annotated_int__FieldInfo_annotation_NoneType__required_True__metadata__Ge_ge_0___Le_le_9007199254740991___MultipleOf_multiple_of_100_____"]) | (null);
  unit_cost_yuan: (components["schemas"]["OpeningFact_Annotated_Decimal__BeforeValidator__FieldInfo_annotation_NoneType__required_True__metadata__Ge_ge_0___Le_le_9007199254740991____PydanticGeneralMetadata_allow_inf_nan_False_____"]) | (null);
};

export type OperationKind = "PLAN_EXTRACTION" | "AI_PROVIDER_TEST";

export type OperationReceipt = {
  kind: components["schemas"]["OperationKind"];
  operationId: string;
  status: "QUEUED";
  submittedAt: string;
};

export type PlanActivationCommand = {
  contentHash?: (string) | (null);
  expectedRevision: number;
  planVersionId: string;
  reviewEvidenceHash?: (string) | (null);
  reviewId?: (string) | (null);
  reviewRevision?: (number) | (null);
  sourceHash?: (string) | (null);
};

export type PlanActiveValidity = {
  mode: "PLAN_ACTIVE";
};

export type PlanDeactivationCommand = {
  expectedRevision: number;
  symbol: string;
};

export type PlanDocumentFormat = "JSON" | "YAML";

export type PlanDraftCommand = {
  basePlanVersionId?: (string) | (null);
  dailyMapping?: (components["schemas"]["DailyMapping"]) | (null);
  expectedRevision: number;
  extractionId?: (string) | (null);
  mapping?: (components["schemas"]["PlanMappingView"]) | (null);
  planJson: string;
  reviewIssues?: Array<components["schemas"]["DraftReviewIssue"]>;
  sourceText: string;
};

export type PlanExtractionCommand = {
  expectedRevision: number;
  providerId: string;
  sourceText: string;
};

export type PlanExtractionOperationStatus = "QUEUED" | "RUNNING" | "SUCCEEDED" | "INVALID_OUTPUT" | "PROVIDER_ERROR" | "CANCELLED";

export type PlanExtractionView = {
  assumptions?: Array<components["schemas"]["ExtractionIssue"]>;
  completedAt?: (string) | (null);
  dailyMapping?: (components["schemas"]["DailyMapping"]) | (null);
  diagnosticStatus?: ("RECORDED" | "WRITE_FAILED") | (null);
  draftPlanJson?: (string) | (null);
  evidence?: Array<components["schemas"]["FieldEvidence"]>;
  id: string;
  mapping?: (components["schemas"]["PlanMappingView"]) | (null);
  model?: (string) | (null);
  promptVersion?: (string) | (null);
  providerId: string;
  sourceTextSha256?: (string) | (null);
  startedAt?: (string) | (null);
  status: components["schemas"]["PlanExtractionOperationStatus"];
  submittedAt: string;
  unmappedText?: Array<components["schemas"]["UnmappedText"]>;
  usage?: (components["schemas"]["AIUsageView"]) | (null);
  validationIssues?: Array<components["schemas"]["ValidationIssue"]>;
  warnings?: Array<components["schemas"]["ExtractionIssue"]>;
};

export type PlanImportCommand = {
  document: string;
  expectedRevision: number;
  format: components["schemas"]["PlanDocumentFormat"];
  symbol: string;
};

export type PlanMappingView = {
  fieldBindings?: Array<components["schemas"]["FieldBindingView"]>;
  mappingVersion?: "plan-mapping-v1" | "plan-mapping-v2";
  sourceClauses: Array<components["schemas"]["SourceClauseView"]>;
  sourceProcessing?: (components["schemas"]["SourceProcessingView"]) | (null);
  userSupplements?: Array<components["schemas"]["UserSupplementView"]>;
};

export type PlanReviewConfirmationCommand = {
  contentHash: string;
  expectedRevision: number;
  planVersionId: string;
  resolutions?: Array<components["schemas"]["PlanReviewResolution"]>;
  reviewEvidenceHash: string;
  sourceHash: string;
};

export type PlanReviewConfirmationView = {
  canActivate: boolean;
  confirmedAt: (string) | (null);
  contentHash: string;
  planVersionId: string;
  reviewEvidenceHash: string;
  reviewId: (string) | (null);
  revision: number;
  sourceHash: string;
  unresolvedIssues?: Array<components["schemas"]["RequiredReviewIssueView"]>;
};

export type PlanReviewResolution = {
  bindingPath?: (string) | (null);
  issueId: string;
  resolution: components["schemas"]["ReviewResolutionKind"];
  supplementId?: (string) | (null);
};

export type PlanScopeView = {
  activationRevision: number;
  dataCutoff: (string) | (null);
  kind: "PLAN";
  nextRetryAt: (string) | (null);
  planFamily: "LEGACY_LOW_BUY" | "EXPLICIT_RULES" | "CONDITION_PLAN";
  planHash: string;
  planVersionId: string;
  progress: components["schemas"]["ScopeProgressView"];
  readOnly: boolean;
  reasonCode: ("RUNTIME_STARTING" | "RUNTIME_STOPPING" | "RUNTIME_STOPPED" | "RUNTIME_FAULT" | "COORDINATOR_STALLED" | "STORAGE_UNAVAILABLE" | "BEFORE_FIRST_MINUTE" | "SESSION_BREAK" | "SESSION_CLOSED" | "NO_ACTIVE_PLANS" | "AWAITING_FIRST_EVALUATION" | "CALENDAR_UNKNOWN" | "REFERENCE_PENDING" | "COVERAGE_INCOMPLETE" | "CLOSE_PENDING" | "PUBLICATION_PENDING" | "PROVIDER_UNAVAILABLE" | "RATE_LIMITED" | "CREDENTIAL_MISSING" | "PERMISSION_DENIED" | "SEMANTICS_INCOMPATIBLE" | "CONFIGURATION_INVALID" | "HISTORY_UNAVAILABLE" | "STATE_UNAVAILABLE" | "GENERATION_CHANGED" | "NEEDS_RESTART" | "LEGACY_PLANS_REQUIRE_REVIEW" | "SCOPED_DEPENDENCY_FAILURE") | (null);
  requiredTarget: ((components["schemas"]["IntradayTargetView"] & { kind: "INTRADAY" }) | (components["schemas"]["OfficialCloseTargetView"] & { kind: "OFFICIAL_CLOSE" })) | (null);
  scopeKey: string;
  status: "WAITING" | "RECOVERING" | "READY" | "BLOCKED";
  symbol: string;
};

export type PlanVersionPage = {
  items?: Array<components["schemas"]["PlanVersionSummary"]>;
  limit: number;
  offset: number;
  total: number;
};

export type PlanVersionStatus = "DRAFT" | "ACTIVE" | "SUPERSEDED";

export type PlanVersionSummary = {
  canActivate: boolean;
  createdAt: string;
  id: string;
  obsoleteReason?: ("DAILY_DRAFT_OBSOLETE" | "LEGACY_PLANS_REQUIRE_REVIEW") | (null);
  planHash: string;
  planId: string;
  revision: number;
  status: components["schemas"]["PlanVersionStatus"];
  symbol: string;
  version: number;
};

export type PlanVersionView = {
  canActivate: boolean;
  contentHash?: (string) | (null);
  createdAt: string;
  dailyIssues?: Array<components["schemas"]["DailyReviewIssue"]>;
  dailyMapping?: (components["schemas"]["DailyMapping"]) | (null);
  executionReadiness?: ("NOT_EVALUATED") | (null);
  id: string;
  mapping?: (components["schemas"]["PlanMappingView"]) | (null);
  obsoleteReason?: ("DAILY_DRAFT_OBSOLETE" | "LEGACY_PLANS_REQUIRE_REVIEW") | (null);
  planHash: string;
  planId: string;
  planJson: string;
  requiredReviewIssues?: Array<components["schemas"]["RequiredReviewIssueView"]>;
  resolvedIssueIds?: Array<string>;
  reviewEvidenceHash?: (string) | (null);
  reviewId?: (string) | (null);
  reviewIssues?: Array<components["schemas"]["DraftReviewIssue"]>;
  reviewRevision?: (number) | (null);
  revision: number;
  sourceHash?: (string) | (null);
  sourceText: string;
  status: components["schemas"]["PlanVersionStatus"];
  symbol: string;
  unresolvedReviewIssues?: Array<components["schemas"]["RequiredReviewIssueView"]>;
  validationIssues?: Array<components["schemas"]["ValidationIssue"]>;
  version: number;
};

export type PositionInventoryView = {
  asOfTradeDate: string;
  confirmationId?: (string) | (null);
  confirmedAt: (string) | (null);
  cutoff: string;
  includedLotIds?: Array<string>;
  inventoryRevision: number;
  missingReasons?: Array<"POSITION_UNKNOWN" | "SELLABLE_QUANTITY_UNKNOWN">;
  openingBalances?: Array<components["schemas"]["PositionOpeningBalanceView"]>;
  sellableQuantity: (number) | (null);
  status: "KNOWN" | "UNKNOWN";
  symbol: string;
  totalQuantity: (number) | (null);
};

export type PositionLotPage = {
  asOfTradeDate: string;
  items?: Array<components["schemas"]["trade_plan_monitor__web__routers__positions__PositionLotView"]>;
  limit: number;
  offset: number;
  symbol: string;
  total: number;
};

export type PositionOpeningBalanceView = {
  openingBalanceId: string;
  originalQuantity: number;
  remainingQuantity: number;
  revision: number;
  sellableFrom: string;
  symbol: string;
};

export type PositionPrefillAction = "BUY" | "CLOSE";

export type PositionPrefillView = {
  action: components["schemas"]["PositionPrefillAction"];
  bucket: "CORE" | "TACTICAL";
  quantity: number;
  relatedAlertId: string;
  symbol: string;
  targetLotId?: (string) | (null);
};

export type PositionSummaryView = {
  coreQuantity: number;
  sellableCoreQuantity: number;
  sellableTacticalQuantity: number;
  tacticalQuantity: number;
  totalQuantity: number;
};

export type PreparationAttemptView = {
  attempt_id: string;
  error_code?: (string) | (null);
  finished_at?: (string) | (null);
  retryable?: boolean;
  source_hash: string;
  source_revision: number;
  started_at: string;
  status: "RUNNING" | "CANCEL_REQUESTED" | "SUCCEEDED" | "FAILED" | "CANCELLED";
};

export type PreparationCreateCommand = {
  input: components["schemas"]["SinglePlanPreparationInput"];
};

export type PreparationExtractionCandidate = {
  candidateHash: string;
  draft: components["schemas"]["UnifiedPlanDraft"];
  evidenceHash: string;
  frozen?: null;
  issues: Array<string>;
  kind: "EXTRACTION";
  mapping: components["schemas"]["DailyMapping"];
  openingAccount: components["schemas"]["OpeningAccountFacts"];
  validation: "VALID" | "INVALID" | "UNRESOLVED";
};

export type PreparationFrozenCandidate = {
  candidateHash: string;
  draft?: null;
  evidenceHash: string;
  frozen: components["schemas"]["PreparationFrozenManifest"];
  issues: Array<string>;
  kind: "FROZEN";
  mapping?: null;
  openingAccount?: null;
  validation: "VALID" | "INVALID" | "UNRESOLVED";
};

export type PreparationFrozenManifest = {
  account: components["schemas"]["LoopAccountInput"];
  account_origin: "SOURCE" | "HUMAN_REVIEW";
  extraction_candidate_hash: string;
  extraction_candidate_revision: number;
  extraction_evidence_hash: string;
  mapping: components["schemas"]["DailyMapping"];
  opening_evidence: components["schemas"]["OpeningAccountFacts"];
  preparation_id: string;
  schema_version?: "prepared-loop-plan-v1";
  source: components["schemas"]["PreparationSource"];
  source_revision: number;
  version: components["schemas"]["LoopPlanVersion"];
};

export type PreparationFrozenView = {
  frozen: components["schemas"]["PreparationFrozenManifest"];
  manifestHash: string;
  preparationId: string;
};

export type PreparationRecoveryCommand = {
  confirmedEnded: true;
  expectedRevision: number;
  generation: string;
};

export type PreparationReviewDeclaration = {
  account?: (components["schemas"]["LoopAccountInput"]) | (null);
  candidate_hash: string;
  confirmed: true;
  draft?: (components["schemas"]["UnifiedPlanDraftInput"]) | (null);
  evidence: string;
  evidence_hash: string;
  expected_candidate_revision: number;
  expected_revision: number;
  expected_source_revision: number;
  mapping?: (components["schemas"]["DailyMapping"]) | (null);
};

export type PreparationReviewInput = {
  review: components["schemas"]["PreparationReviewDeclaration"];
};

export type PreparationRevisionCommand = {
  expectedRevision: number;
};

export type PreparationSource = {
  authored_at?: (string) | (null);
  available_at?: (string) | (null);
  effective_trade_date?: (string) | (null);
  source_id: string;
  text: string;
};

export type PreparationSourceCommand = {
  expectedRevision: number;
  source: components["schemas"]["PreparationSource"];
};

export type PreparationUnavailableCandidate = {
  candidateHash: string;
  draft?: null;
  evidenceHash: string;
  frozen?: null;
  issues: Array<string>;
  kind: "UNAVAILABLE";
  mapping?: null;
  openingAccount?: null;
  validation: "INVALID";
};

export type PreparationView = {
  attempts: Array<components["schemas"]["PreparationAttemptView"]>;
  candidate: ((components["schemas"]["PreparationExtractionCandidate"] & { kind: "EXTRACTION" }) | (components["schemas"]["PreparationFrozenCandidate"] & { kind: "FROZEN" }) | (components["schemas"]["PreparationUnavailableCandidate"] & { kind: "UNAVAILABLE" })) | (null);
  candidateRevision: number;
  generation: (string) | (null);
  preparationId: string;
  reviewRevision: number;
  revision: number;
  source: components["schemas"]["PreparationSource"];
  sourceEditPending: boolean;
  sourceRevision: number;
  status: "DRAFT" | "EXTRACTING" | "CANCEL_REQUESTED" | "CANDIDATE" | "REVIEWED" | "FAILED" | "CANCELLED";
  workPhase: ("READY" | "CALLING" | "UNKNOWN" | "ENDED") | (null);
};

export type PreparedBacktestRunCommand = {
  costs: components["schemas"]["BacktestLoopCostsInput"];
  endDate?: (string) | (null);
  manifestHash: string;
  preparationId: string;
  response: components["schemas"]["BacktestLoopResponseInput"];
};

export type ProductSourceTreatmentView = {
  contractId: "alert-position-isolation-v1";
  guarantee: "ALERTS_AND_ACKNOWLEDGEMENTS_DO_NOT_CHANGE_POSITIONS";
  kind: "PRODUCT_GUARANTEE";
  spans: Array<components["schemas"]["SourceSpanView"]>;
  treatmentId: string;
};

export type ProviderCapabilityStatus = "UNVERIFIED" | "READY" | "BLOCKED_PERMISSION" | "RATE_LIMITED" | "ERROR";

export type ProviderHealthView = {
  capability: string;
  checkedAt: string;
  errorCode: (string) | (null);
  latencyMs: number;
  nextRetryAt: (string) | (null);
  status: components["schemas"]["ProviderCapabilityStatus"];
};

export type ProviderScopeView = {
  dataCutoff: (string) | (null);
  kind: "PROVIDER";
  nextRetryAt: (string) | (null);
  progress: components["schemas"]["ScopeProgressView"];
  reasonCode: ("RUNTIME_STARTING" | "RUNTIME_STOPPING" | "RUNTIME_STOPPED" | "RUNTIME_FAULT" | "COORDINATOR_STALLED" | "STORAGE_UNAVAILABLE" | "BEFORE_FIRST_MINUTE" | "SESSION_BREAK" | "SESSION_CLOSED" | "NO_ACTIVE_PLANS" | "AWAITING_FIRST_EVALUATION" | "CALENDAR_UNKNOWN" | "REFERENCE_PENDING" | "COVERAGE_INCOMPLETE" | "CLOSE_PENDING" | "PUBLICATION_PENDING" | "PROVIDER_UNAVAILABLE" | "RATE_LIMITED" | "CREDENTIAL_MISSING" | "PERMISSION_DENIED" | "SEMANTICS_INCOMPATIBLE" | "CONFIGURATION_INVALID" | "HISTORY_UNAVAILABLE" | "STATE_UNAVAILABLE" | "GENERATION_CHANGED" | "NEEDS_RESTART" | "LEGACY_PLANS_REQUIRE_REVIEW" | "SCOPED_DEPENDENCY_FAILURE") | (null);
  requiredTarget: ((components["schemas"]["IntradayTargetView"] & { kind: "INTRADAY" }) | (components["schemas"]["OfficialCloseTargetView"] & { kind: "OFFICIAL_CLOSE" })) | (null);
  scopeKey: string;
  status: "WAITING" | "RECOVERING" | "READY" | "BLOCKED";
};

export type RequiredReviewIssueView = {
  allowedResolutions: Array<components["schemas"]["ReviewResolutionKind"]>;
  bindingPath?: (string) | (null);
  clauseId?: (string) | (null);
  code: string;
  issueId: string;
  path: string;
  reason: string;
};

export type ResearchAdjustmentProof = {
  adjustment_as_of: string;
  available_at: string;
  dataset_hash: string;
  evidence: string;
  factors: Array<components["schemas"]["ResearchFactor"]>;
  proof_id: string;
  provider: "TUSHARE";
  quote_basis_factor: (number) | (string);
  received_at: string;
  symbol: string;
};

export type ResearchConditionEvidence = {
  bar_ids?: Array<string>;
  basis_id?: (string) | (null);
  children?: Array<components["schemas"]["ResearchConditionEvidence"]>;
  condition: (components["schemas"]["DailyPriceCompare"] & { type: "DAILY_PRICE_COMPARE" }) | (components["schemas"]["DailyPriceInRange"] & { type: "DAILY_PRICE_IN_RANGE" }) | (components["schemas"]["DailyVolumeRatio"] & { type: "DAILY_VOLUME_RATIO" }) | (components["schemas"]["DailyCandleRatio"] & { type: "DAILY_CANDLE_RATIO" }) | (components["schemas"]["DailyIndicatorCompare"] & { type: "DAILY_INDICATOR_COMPARE" }) | (components["schemas"]["DailyCloseSequence"] & { type: "DAILY_CLOSE_SEQUENCE" }) | (components["schemas"]["ReviewedDailyFact"] & { type: "REVIEWED_FACT" }) | (components["schemas"]["MinuteCloseInRange"] & { type: "MINUTE_CLOSE_IN_RANGE" }) | (components["schemas"]["MinuteCloseBelow"] & { type: "MINUTE_CLOSE_BELOW" }) | (components["schemas"]["MinuteVolumeToMeanGte"] & { type: "MINUTE_VOLUME_TO_MEAN_GTE" }) | (components["schemas"]["UnifiedAll"] & { type: "ALL" }) | (components["schemas"]["UnifiedAny"] & { type: "ANY" });
  fact_ids?: Array<string>;
  operands?: Array<string>;
  outcome: "SATISFIED" | "UNSATISFIED" | "MISSING_INPUT";
  reason?: (string) | (null);
  session_dates?: Array<string>;
};

export type ResearchDeactivate = {
  at: string;
  kind: "DEACTIVATE";
  operation_id: string;
  order: number;
};

export type ResearchDecisionEvent = {
  alerts: Array<components["schemas"]["ResearchReminder"]>;
  at: string;
  blockers: Array<string>;
  conditions: Array<components["schemas"]["ResearchRuleEvidence"]>;
  evaluation_id: (string) | (null);
  event_id: string;
  inventory_after: components["schemas"]["DailyInventoryView"];
  inventory_before: components["schemas"]["DailyInventoryView"];
  minute_target: (string) | (null);
  official_trade_date: (string) | (null);
  resulting_risks: Array<components["schemas"]["DailyRiskState"]>;
  resulting_signals: Array<components["schemas"]["DailySignalState"]>;
  risk_action: components["schemas"]["DailyRiskAction"];
  risks: Array<components["schemas"]["DailyRiskState"]>;
  schema_version?: "unified-research-decision-v1";
  signals: Array<components["schemas"]["DailySignalState"]>;
};

export type ResearchDecisionView = {
  detailId: string;
  eventAt: string;
  kind: "DECISION";
  researchDecision: components["schemas"]["ResearchDecisionEvent"];
  runId: string;
};

export type ResearchEquityView = {
  blockers: Array<string>;
  cashFen: (string) | (null);
  equityFen: (string) | (null);
  markPriceFen: (string) | (null);
  markedAt: string;
  marketValueFen: (string) | (null);
  positionQuantity: (number) | (null);
  runId: string;
  schemaVersion: "unified-research-equity-v1";
  snapshotId: string;
  valuationValid: boolean;
};

export type ResearchFact = {
  at: string;
  evidence: string;
  fact_id: string;
  fact_kind: "PRICE_STRUCTURE" | "VOLUME_OR_CANDLE" | "TECHNICAL" | "TRADE_VIABILITY" | "SIGNAL_INVALIDATION" | "INDEPENDENT_EVENT" | "SEVERE_STRUCTURE" | "SEVERE_DETERIORATION" | "TRADABILITY" | "FULL_SESSION_SUSPENSION";
  kind: "FACT";
  occurrence?: (number) | (null);
  official_evidence?: (components["schemas"]["DailyOfficialProof"]) | (null);
  operation_id: string;
  order: number;
  rule_id?: (string) | (null);
  satisfied: boolean;
  trade_date: string;
};

export type ResearchFactor = {
  factor: (number) | (string);
  trade_date: string;
};

export type ResearchMetricsView = {
  blockedCount: number;
  finalCashFen: (string) | (null);
  finalEquityFen: (string) | (null);
  initialCashFen: string;
  initialEquityFen: (string) | (null);
  schemaVersion: "explicit-simulation-metrics-v1";
  totalCostFen: string;
  totalReturn: (string) | (null);
  tradeCount: number;
  valuationValid: boolean;
};

export type ResearchOperationOutcome = {
  at: string;
  blockers: Array<string>;
  cause_id?: (string) | (null);
  inventory_after: components["schemas"]["DailyInventoryView"];
  inventory_before: components["schemas"]["DailyInventoryView"];
  kind: "FACT" | "DEACTIVATE" | "REPLACE" | "SIMULATE" | "REASSESS";
  monitor_price_fen?: (number) | (null);
  operation_id: string;
  quantity?: (number) | (null);
  schema_version?: "unified-research-operation-v1";
  side?: ("BUY" | "SELL") | (null);
  simulation_id?: (string) | (null);
  status: "APPLIED" | "BLOCKED" | "REPLAYED";
  valuation?: (components["schemas"]["ResearchOperationValuation"]) | (null);
};

export type ResearchOperationValuation = {
  blockers: Array<string>;
  cash_after_fen: (number) | (null);
  cash_delta_fen: number;
  fees_fen: number;
  notional_fen: number;
  research_price_fen: number;
  schema_version?: "explicit-simulation-valuation-v1";
  status: "PROJECTED" | "BLOCKED";
};

export type ResearchOperationView = {
  detailId: string;
  eventAt: string;
  kind: "EXECUTION_OUTCOME";
  researchOperation: components["schemas"]["ResearchOperationOutcome"];
  runId: string;
};

export type ResearchReassessment = {
  at: string;
  kind: "REASSESS";
  operation_id: string;
  order: number;
  removal_evidence: string;
  risk_kind: "ORDINARY_TECHNICAL" | "SEVERE_TECHNICAL";
};

export type ResearchReminder = {
  alert_kind: "RISK_ALERT";
  cause_id: (string) | (null);
  confirmation_kind: "OFFICIAL_DAILY_CLOSE" | "COMPLETED_BAR_CLOSE";
  confirmed_at: (string) | (null);
  confirmed_trade_date: (string) | (null);
  evidence: Array<components["schemas"]["ResearchConditionEvidence"]>;
  outcome: "SATISFIED" | "UNSATISFIED" | "MISSING_INPUT";
  rule_id: string;
};

export type ResearchReplace = {
  at: string;
  kind: "REPLACE";
  operation_id: string;
  order: number;
  replacement_plan_hash: string;
  replacement_review: components["schemas"]["ResearchReview"];
  replacement_version_id: string;
};

export type ResearchReview = {
  confirmed: true;
  content_hash: string;
  evidence: string;
  reviewed_at: string;
};

export type ResearchRuleEvidence = {
  evidence: components["schemas"]["ResearchConditionEvidence"];
  rule_id: string;
};

export type ResearchSimulation = {
  at: string;
  kind: "SIMULATE";
  occurrence?: (number) | (null);
  operation_id: string;
  order: number;
  quantity: number;
  risk_kind?: ("ORDINARY_TECHNICAL" | "SEVERE_TECHNICAL") | (null);
  rule_id?: (string) | (null);
};

export type ReturnIndicatorFactView = {
  formulaDefinitionHash: string;
  formulaId: "RETURN";
  sourceBarHash: string;
  unit: "RATIO";
  value: string;
  window: components["schemas"]["ReturnWindow"];
  windowSize: number;
};

export type ReturnWindow = "FIVE_MINUTE_BUCKETS" | "OFFICIAL_OPEN_DAYS";

export type ReviewIssueKind = "ASSUMPTION" | "WARNING" | "UNMAPPED_TEXT" | "MISSING_EVIDENCE";

export type ReviewResolutionKind = "CONFIRM_MAPPING" | "CONFIRM_POLICY" | "CONFIRM_SOURCE_TREATMENT" | "REPLACED_BY_REVIEWED_CONTENT";

export type ReviewedDailyFact = {
  evidence_requirement: string;
  fact_kind: "PRICE_STRUCTURE" | "VOLUME_OR_CANDLE" | "TECHNICAL" | "TRADE_VIABILITY" | "SIGNAL_INVALIDATION" | "INDEPENDENT_EVENT" | "SEVERE_STRUCTURE" | "SEVERE_DETERIORATION" | "TRADABILITY" | "FULL_SESSION_SUSPENSION";
  type: "REVIEWED_FACT";
  validity_scope: "TRADE_DATE" | "SIGNAL";
};

export type RiskStatus = "CLEAR" | "BREACHED_PENDING_CONFIRMATION" | "EXIT_PENDING_SETTLEMENT";

export type RuleEligibilityView = {
  action: "BUY" | "SELL" | "RISK_ALERT";
  actionableUntil: (string) | (null);
  currentActionable: boolean;
  reasonCode: ("NO_CURRENT_SIGNAL" | "INTRADAY_EXPIRED" | "RECOVERY_HOLD" | "RISK_NO_LONGER_VALID" | "CURRENT_STATE_UNVERIFIED" | "CACHED_RESULT") | (null);
  ruleId: string;
  sourceAlert: (components["schemas"]["SourceAlertView"]) | (null);
};

export type RuntimeDashboardResponse = {
  counts: components["schemas"]["DashboardCounts"];
  marketIndexes: Array<components["schemas"]["MarketIndexSnapshotView"]>;
  marketTurnover: (components["schemas"]["MarketTurnoverSummaryView"]) | (null);
  monitorContractVersion: 2;
  observedAt: string;
  runtimeGeneration: (string) | (null);
  runtimeStatus: components["schemas"]["RuntimeStatusView"];
  sequence: number;
  symbols: Array<(components["schemas"]["UnavailablePlanEntryView"]) | (components["schemas"]["LegacyPlanEntryView"]) | (components["schemas"]["ExplicitPlanEntryView"]) | (components["schemas"]["ConditionPlanEntryView"])>;
};

export type RuntimeGapView = {
  barEnd: string;
  symbol: string;
};

export type RuntimeHealthV2Response = {
  cooldownUntil: (string) | (null);
  database: components["schemas"]["DatabaseHealthView"];
  delivery: components["schemas"]["DeliveryHealthView"];
  executor: components["schemas"]["ExecutorHealthView"];
  gaps: Array<components["schemas"]["RuntimeGapView"]>;
  lastCompletedMinute: (string) | (null);
  lastCompletedMinuteAgeSeconds: (number) | (null);
  latestEvaluationAgeSeconds: (number) | (null);
  latestEvaluationAt: (string) | (null);
  monitorContractVersion: 2;
  observedAt: string;
  providers: Array<components["schemas"]["ProviderHealthView"]>;
  runtimeGeneration: (string) | (null);
  runtimeStatus: components["schemas"]["RuntimeStatusView"];
  startedAt: (string) | (null);
  stoppedAt: (string) | (null);
};

export type RuntimeHeartbeatFrame = {
  monitorContractVersion: 2;
  observedAt: string;
  runtimeGeneration: (string) | (null);
  runtimeStatus: components["schemas"]["RuntimeStatusView"];
  sequence: number;
  type: "heartbeat";
};

export type RuntimeInactiveSymbolResponse = {
  availability: "UNAVAILABLE";
  monitorContractVersion: 2;
  observedAt: string;
  reasonCode: "NO_ACTIVE_PLAN";
  runtimeGeneration: (string) | (null);
  runtimeStatus: components["schemas"]["RuntimeStatusView"];
  sequence: number;
  symbol: string;
};

export type RuntimeLegacyDetailsView = {
  indexConditionEvidence: Array<components["schemas"]["IndexConditionEvidenceView"]>;
  positionLots: Array<components["schemas"]["trade_plan_monitor__web__routers__symbols__PositionLotView"]>;
  referenceMarket: (components["schemas"]["SymbolReferenceMarketView"]) | (null);
};

export type RuntimeResourceStatus = "UNVERIFIED" | "READY" | "DEGRADED" | "ERROR" | "STOPPED";

export type RuntimeSnapshotRequiredFrame = {
  monitorContractVersion: 2;
  reason: "REPLAY_UNAVAILABLE";
  sequence: number;
  type: "snapshot.required";
};

export type RuntimeStatusView = {
  coordinator: components["schemas"]["CoordinatorStatusView"];
  lastProgressAt: (string) | (null);
  lifecycle: "STARTING" | "RUNNING" | "STOPPING" | "STOPPED";
  mode: "RECOVERING" | "MONITORING" | "STANDBY" | "DEGRADED" | "BLOCKED";
  nextRetryAt: (string) | (null);
  nextWakeAt: (string) | (null);
  reasonCode: ("RUNTIME_STARTING" | "RUNTIME_STOPPING" | "RUNTIME_STOPPED" | "RUNTIME_FAULT" | "COORDINATOR_STALLED" | "STORAGE_UNAVAILABLE" | "BEFORE_FIRST_MINUTE" | "SESSION_BREAK" | "SESSION_CLOSED" | "NO_ACTIVE_PLANS" | "AWAITING_FIRST_EVALUATION" | "CALENDAR_UNKNOWN" | "REFERENCE_PENDING" | "COVERAGE_INCOMPLETE" | "CLOSE_PENDING" | "PUBLICATION_PENDING" | "PROVIDER_UNAVAILABLE" | "RATE_LIMITED" | "CREDENTIAL_MISSING" | "PERMISSION_DENIED" | "SEMANTICS_INCOMPATIBLE" | "CONFIGURATION_INVALID" | "HISTORY_UNAVAILABLE" | "STATE_UNAVAILABLE" | "GENERATION_CHANGED" | "NEEDS_RESTART" | "LEGACY_PLANS_REQUIRE_REVIEW" | "SCOPED_DEPENDENCY_FAILURE") | (null);
  scopes: Array<(components["schemas"]["PlanScopeView"] & { kind: "PLAN" }) | (components["schemas"]["IndexScopeView"] & { kind: "INDEX" }) | (components["schemas"]["ProviderScopeView"] & { kind: "PROVIDER" }) | (components["schemas"]["CalendarScopeView"] & { kind: "CALENDAR" })>;
};

export type RuntimeSymbolCollectionResponse = {
  items: Array<(components["schemas"]["UnavailablePlanEntryView"]) | (components["schemas"]["LegacyPlanEntryView"]) | (components["schemas"]["ExplicitPlanEntryView"]) | (components["schemas"]["ConditionPlanEntryView"])>;
  limit: number;
  monitorContractVersion: 2;
  observedAt: string;
  offset: number;
  runtimeGeneration: (string) | (null);
  runtimeStatus: components["schemas"]["RuntimeStatusView"];
  sequence: number;
  total: number;
};

export type RuntimeSymbolDetailResponse = {
  legacyDetails: (components["schemas"]["RuntimeLegacyDetailsView"]) | (null);
  monitorContractVersion: 2;
  observedAt: string;
  runtimeGeneration: (string) | (null);
  runtimeStatus: components["schemas"]["RuntimeStatusView"];
  sequence: number;
  summary: (components["schemas"]["UnavailablePlanEntryView"]) | (components["schemas"]["LegacyPlanEntryView"]) | (components["schemas"]["ExplicitPlanEntryView"]) | (components["schemas"]["ConditionPlanEntryView"]);
};

export type RuntimeSymbolHealthResponse = {
  monitorContractVersion: 2;
  observedAt: string;
  runtimeGeneration: (string) | (null);
  runtimeStatus: components["schemas"]["RuntimeStatusView"];
  scope: components["schemas"]["PlanScopeView"];
};

export type ScopeProgressView = {
  completedCount: (number) | (null);
  requiredCount: (number) | (null);
};

export type SecretReferenceView = {
  key: string;
};

export type SecretSource = "NONE" | "STORE";

export type SecretStatusView = {
  configured: boolean;
  generation: number;
  maskedValue: ("********") | (null);
  source: components["schemas"]["SecretSource"];
};

export type SignalType = "WAIT" | "LOW_ZONE_WATCH" | "BLOCKED_DATA" | "BLOCKED_RISK" | "BUY_CORE_READY" | "BUY_TACTICAL_READY" | "PRESSURE_REDUCE_READY" | "RISK_BREACH" | "RISK_RECOVERED" | "RISK_EXIT_READY" | "RISK_EXIT_PENDING_SETTLEMENT";

export type SimulationCommand = {
  cause_id: string;
  expected_cause_revision: number;
  expected_inventory_revision: number;
  plan_version_id: string;
  quantity: number;
};

export type SimulationReceipt = {
  inventory: components["schemas"]["DailyInventoryView"];
  inventory_revision: number;
  price_fen: number;
  quantity: number;
  side: "BUY" | "SELL";
  signal_id: (string) | (null);
  simulated_at: string;
  simulation_id: string;
};

export type SinglePlanPreparationInput = {
  preparation_id: string;
  sources: Array<components["schemas"]["PreparationSource"]>;
};

export type SmaIndicatorFactView = {
  formulaDefinitionHash: string;
  formulaId: "SMA";
  period: number;
  sourceBarHash: string;
  unit: "POINTS";
  value: string;
};

export type SmaLookbackIndicatorFactView = {
  comparisonValue: string;
  formulaDefinitionHash: string;
  formulaId: "SMA_LOOKBACK";
  lookback: number;
  period: number;
  sourceBarHash: string;
  unit: "POINTS";
  value: string;
};

export type SourceAlertView = {
  dataCutoff: string;
  evaluatedAt: string;
  eventId: string;
  resultHash: string;
};

export type SourceClauseView = {
  clauseId: string;
  disposition: components["schemas"]["ClauseDisposition"];
  end: number;
  excerpt: string;
  paths?: Array<string>;
  start: number;
};

export type SourceProcessingView = {
  treatments: Array<(components["schemas"]["InventorySourceTreatmentView"] & { kind: "INVENTORY_ASSERTION" }) | (components["schemas"]["ProductSourceTreatmentView"] & { kind: "PRODUCT_GUARANTEE" })>;
  version: "source-processing-v1";
};

export type SourceSpanView = {
  clauseId: string;
  end: number;
  excerpt: string;
  start: number;
};

export type SymbolEventPage = {
  endAt: string;
  items?: Array<components["schemas"]["SymbolEventView"]>;
  limit: number;
  offset: number;
  startAt: string;
  total: number;
};

export type SymbolEventType = "DECISION" | "EPISODE" | "RISK" | "ALERT" | "HEALTH";

export type SymbolEventView = {
  eventId: string;
  eventType: components["schemas"]["SymbolEventType"];
  messageText: (string) | (null);
  occurredAt: string;
  resultHash: (string) | (null);
  sequence: number;
  signalType: (components["schemas"]["SignalType"]) | (null);
  symbol: string;
};

export type SymbolReferenceMarketView = {
  board: components["schemas"]["Board"];
  conditionProgress: components["schemas"]["IndexConditionProgressView"];
  dataAt: (string) | (null);
  displayName: string;
  health: components["schemas"]["MarketIndexHealth"];
  indexCode: components["schemas"]["MarketIndexCode"];
  issues: Array<components["schemas"]["MarketIndexIssueCode"]>;
  mappingVersion: "board-index-map-v1";
  snapshotHash: (string) | (null);
};

export type TradingDay = {
  cal_date: string;
  exchange: "SSE" | "SZSE" | "BSE";
  is_open: boolean;
  previous_trade_date: string;
};

export type UnavailablePlanEntryView = {
  activationRevision: number;
  availability: "UNAVAILABLE";
  currentActionable: false;
  name: string;
  observedAt: string;
  planFamily: "LEGACY_LOW_BUY" | "EXPLICIT_RULES" | "CONDITION_PLAN";
  planHash: string;
  planVersionId: string;
  projectionState: "WAITING" | "RECOVERING" | "BLOCKED";
  reasonCode: "RUNTIME_STARTING" | "RUNTIME_STOPPING" | "RUNTIME_STOPPED" | "RUNTIME_FAULT" | "COORDINATOR_STALLED" | "STORAGE_UNAVAILABLE" | "BEFORE_FIRST_MINUTE" | "SESSION_BREAK" | "SESSION_CLOSED" | "NO_ACTIVE_PLANS" | "AWAITING_FIRST_EVALUATION" | "CALENDAR_UNKNOWN" | "REFERENCE_PENDING" | "COVERAGE_INCOMPLETE" | "CLOSE_PENDING" | "PUBLICATION_PENDING" | "PROVIDER_UNAVAILABLE" | "RATE_LIMITED" | "CREDENTIAL_MISSING" | "PERMISSION_DENIED" | "SEMANTICS_INCOMPATIBLE" | "CONFIGURATION_INVALID" | "HISTORY_UNAVAILABLE" | "STATE_UNAVAILABLE" | "GENERATION_CHANGED" | "NEEDS_RESTART" | "LEGACY_PLANS_REQUIRE_REVIEW" | "SCOPED_DEPENDENCY_FAILURE";
  scope: components["schemas"]["PlanScopeView"];
  symbol: string;
};

export type UnfilledReason = "NON_EXECUTABLE_SIGNAL" | "SUSPENDED" | "MISSING_NEXT_MINUTE" | "NO_NEXT_MINUTE" | "LIMIT_UP_LOCKED" | "LIMIT_DOWN_LOCKED" | "INSUFFICIENT_CASH" | "MAX_POSITION_REACHED" | "TARGET_POSITION_REACHED" | "TARGET_LOT_NOT_FOUND" | "T_PLUS_ONE";

export type UnifiedAlertRule = {
  condition: (components["schemas"]["DailyPriceCompare"] & { type: "DAILY_PRICE_COMPARE" }) | (components["schemas"]["DailyPriceInRange"] & { type: "DAILY_PRICE_IN_RANGE" }) | (components["schemas"]["DailyVolumeRatio"] & { type: "DAILY_VOLUME_RATIO" }) | (components["schemas"]["DailyCandleRatio"] & { type: "DAILY_CANDLE_RATIO" }) | (components["schemas"]["DailyIndicatorCompare"] & { type: "DAILY_INDICATOR_COMPARE" }) | (components["schemas"]["DailyCloseSequence"] & { type: "DAILY_CLOSE_SEQUENCE" }) | (components["schemas"]["ReviewedDailyFact"] & { type: "REVIEWED_FACT" }) | (components["schemas"]["MinuteCloseInRange"] & { type: "MINUTE_CLOSE_IN_RANGE" }) | (components["schemas"]["MinuteCloseBelow"] & { type: "MINUTE_CLOSE_BELOW" }) | (components["schemas"]["MinuteVolumeToMeanGte"] & { type: "MINUTE_VOLUME_TO_MEAN_GTE" }) | (components["schemas"]["UnifiedAll"] & { type: "ALL" }) | (components["schemas"]["UnifiedAny"] & { type: "ANY" });
  confirmation: (components["schemas"]["OfficialDailyConfirmation"] & { kind: "OFFICIAL_DAILY_CLOSE" }) | (components["schemas"]["CompletedMinuteConfirmation"] & { kind: "COMPLETED_BAR_CLOSE" });
  kind: "RISK_ALERT";
  rule_id: string;
};

export type UnifiedAll = {
  conditions: Array<(components["schemas"]["DailyPriceCompare"] & { type: "DAILY_PRICE_COMPARE" }) | (components["schemas"]["DailyPriceInRange"] & { type: "DAILY_PRICE_IN_RANGE" }) | (components["schemas"]["DailyVolumeRatio"] & { type: "DAILY_VOLUME_RATIO" }) | (components["schemas"]["DailyCandleRatio"] & { type: "DAILY_CANDLE_RATIO" }) | (components["schemas"]["DailyIndicatorCompare"] & { type: "DAILY_INDICATOR_COMPARE" }) | (components["schemas"]["DailyCloseSequence"] & { type: "DAILY_CLOSE_SEQUENCE" }) | (components["schemas"]["ReviewedDailyFact"] & { type: "REVIEWED_FACT" }) | (components["schemas"]["MinuteCloseInRange"] & { type: "MINUTE_CLOSE_IN_RANGE" }) | (components["schemas"]["MinuteCloseBelow"] & { type: "MINUTE_CLOSE_BELOW" }) | (components["schemas"]["MinuteVolumeToMeanGte"] & { type: "MINUTE_VOLUME_TO_MEAN_GTE" }) | (components["schemas"]["UnifiedAll"] & { type: "ALL" }) | (components["schemas"]["UnifiedAny"] & { type: "ANY" })>;
  type: "ALL";
};

export type UnifiedAllInput = {
  conditions: Array<(components["schemas"]["DailyPriceCompareInput"] & { type: "DAILY_PRICE_COMPARE" }) | (components["schemas"]["DailyPriceInRange"] & { type: "DAILY_PRICE_IN_RANGE" }) | (components["schemas"]["DailyVolumeRatioInput"] & { type: "DAILY_VOLUME_RATIO" }) | (components["schemas"]["DailyCandleRatioInput"] & { type: "DAILY_CANDLE_RATIO" }) | (components["schemas"]["DailyIndicatorCompareInput"] & { type: "DAILY_INDICATOR_COMPARE" }) | (components["schemas"]["DailyCloseSequenceInput"] & { type: "DAILY_CLOSE_SEQUENCE" }) | (components["schemas"]["ReviewedDailyFact"] & { type: "REVIEWED_FACT" }) | (components["schemas"]["MinuteCloseInRange"] & { type: "MINUTE_CLOSE_IN_RANGE" }) | (components["schemas"]["MinuteCloseBelow"] & { type: "MINUTE_CLOSE_BELOW" }) | (components["schemas"]["MinuteVolumeToMeanGteInput"] & { type: "MINUTE_VOLUME_TO_MEAN_GTE" }) | (components["schemas"]["UnifiedAllInput"] & { type: "ALL" }) | (components["schemas"]["UnifiedAnyInput"] & { type: "ANY" })>;
  type: "ALL";
};

export type UnifiedAny = {
  conditions: Array<(components["schemas"]["DailyPriceCompare"] & { type: "DAILY_PRICE_COMPARE" }) | (components["schemas"]["DailyPriceInRange"] & { type: "DAILY_PRICE_IN_RANGE" }) | (components["schemas"]["DailyVolumeRatio"] & { type: "DAILY_VOLUME_RATIO" }) | (components["schemas"]["DailyCandleRatio"] & { type: "DAILY_CANDLE_RATIO" }) | (components["schemas"]["DailyIndicatorCompare"] & { type: "DAILY_INDICATOR_COMPARE" }) | (components["schemas"]["DailyCloseSequence"] & { type: "DAILY_CLOSE_SEQUENCE" }) | (components["schemas"]["ReviewedDailyFact"] & { type: "REVIEWED_FACT" }) | (components["schemas"]["MinuteCloseInRange"] & { type: "MINUTE_CLOSE_IN_RANGE" }) | (components["schemas"]["MinuteCloseBelow"] & { type: "MINUTE_CLOSE_BELOW" }) | (components["schemas"]["MinuteVolumeToMeanGte"] & { type: "MINUTE_VOLUME_TO_MEAN_GTE" }) | (components["schemas"]["UnifiedAll"] & { type: "ALL" }) | (components["schemas"]["UnifiedAny"] & { type: "ANY" })>;
  type: "ANY";
};

export type UnifiedAnyInput = {
  conditions: Array<(components["schemas"]["DailyPriceCompareInput"] & { type: "DAILY_PRICE_COMPARE" }) | (components["schemas"]["DailyPriceInRange"] & { type: "DAILY_PRICE_IN_RANGE" }) | (components["schemas"]["DailyVolumeRatioInput"] & { type: "DAILY_VOLUME_RATIO" }) | (components["schemas"]["DailyCandleRatioInput"] & { type: "DAILY_CANDLE_RATIO" }) | (components["schemas"]["DailyIndicatorCompareInput"] & { type: "DAILY_INDICATOR_COMPARE" }) | (components["schemas"]["DailyCloseSequenceInput"] & { type: "DAILY_CLOSE_SEQUENCE" }) | (components["schemas"]["ReviewedDailyFact"] & { type: "REVIEWED_FACT" }) | (components["schemas"]["MinuteCloseInRange"] & { type: "MINUTE_CLOSE_IN_RANGE" }) | (components["schemas"]["MinuteCloseBelow"] & { type: "MINUTE_CLOSE_BELOW" }) | (components["schemas"]["MinuteVolumeToMeanGteInput"] & { type: "MINUTE_VOLUME_TO_MEAN_GTE" }) | (components["schemas"]["UnifiedAllInput"] & { type: "ALL" }) | (components["schemas"]["UnifiedAnyInput"] & { type: "ANY" })>;
  type: "ANY";
};

export type UnifiedConditionEvidence = {
  bar_ids?: Array<string>;
  basis_id?: (string) | (null);
  children?: Array<components["schemas"]["UnifiedConditionEvidence"]>;
  condition: (components["schemas"]["DailyPriceCompare"] & { type: "DAILY_PRICE_COMPARE" }) | (components["schemas"]["DailyPriceInRange"] & { type: "DAILY_PRICE_IN_RANGE" }) | (components["schemas"]["DailyVolumeRatio"] & { type: "DAILY_VOLUME_RATIO" }) | (components["schemas"]["DailyCandleRatio"] & { type: "DAILY_CANDLE_RATIO" }) | (components["schemas"]["DailyIndicatorCompare"] & { type: "DAILY_INDICATOR_COMPARE" }) | (components["schemas"]["DailyCloseSequence"] & { type: "DAILY_CLOSE_SEQUENCE" }) | (components["schemas"]["ReviewedDailyFact"] & { type: "REVIEWED_FACT" }) | (components["schemas"]["MinuteCloseInRange"] & { type: "MINUTE_CLOSE_IN_RANGE" }) | (components["schemas"]["MinuteCloseBelow"] & { type: "MINUTE_CLOSE_BELOW" }) | (components["schemas"]["MinuteVolumeToMeanGte"] & { type: "MINUTE_VOLUME_TO_MEAN_GTE" }) | (components["schemas"]["UnifiedAll"] & { type: "ALL" }) | (components["schemas"]["UnifiedAny"] & { type: "ANY" });
  fact_ids?: Array<string>;
  operands?: Array<string>;
  outcome: "SATISFIED" | "UNSATISFIED" | "MISSING_INPUT";
  reason?: (string) | (null);
  session_dates?: Array<unknown>;
};

export type UnifiedDraftAlertRule = {
  condition: ((components["schemas"]["DailyPriceCompare"] & { type: "DAILY_PRICE_COMPARE" }) | (components["schemas"]["DailyPriceInRange"] & { type: "DAILY_PRICE_IN_RANGE" }) | (components["schemas"]["DailyVolumeRatio"] & { type: "DAILY_VOLUME_RATIO" }) | (components["schemas"]["DailyCandleRatio"] & { type: "DAILY_CANDLE_RATIO" }) | (components["schemas"]["DailyIndicatorCompare"] & { type: "DAILY_INDICATOR_COMPARE" }) | (components["schemas"]["DailyCloseSequence"] & { type: "DAILY_CLOSE_SEQUENCE" }) | (components["schemas"]["ReviewedDailyFact"] & { type: "REVIEWED_FACT" }) | (components["schemas"]["MinuteCloseInRange"] & { type: "MINUTE_CLOSE_IN_RANGE" }) | (components["schemas"]["MinuteCloseBelow"] & { type: "MINUTE_CLOSE_BELOW" }) | (components["schemas"]["MinuteVolumeToMeanGte"] & { type: "MINUTE_VOLUME_TO_MEAN_GTE" }) | (components["schemas"]["UnifiedAll"] & { type: "ALL" }) | (components["schemas"]["UnifiedAny"] & { type: "ANY" })) | (null);
  confirmation: ((components["schemas"]["OfficialDailyConfirmation"] & { kind: "OFFICIAL_DAILY_CLOSE" }) | (components["schemas"]["CompletedMinuteConfirmation"] & { kind: "COMPLETED_BAR_CLOSE" })) | (null);
  kind: ("RISK_ALERT") | (null);
  rule_id: (string) | (null);
};

export type UnifiedDraftAlertRuleInput = {
  condition: ((components["schemas"]["DailyPriceCompareInput"] & { type: "DAILY_PRICE_COMPARE" }) | (components["schemas"]["DailyPriceInRange"] & { type: "DAILY_PRICE_IN_RANGE" }) | (components["schemas"]["DailyVolumeRatioInput"] & { type: "DAILY_VOLUME_RATIO" }) | (components["schemas"]["DailyCandleRatioInput"] & { type: "DAILY_CANDLE_RATIO" }) | (components["schemas"]["DailyIndicatorCompareInput"] & { type: "DAILY_INDICATOR_COMPARE" }) | (components["schemas"]["DailyCloseSequenceInput"] & { type: "DAILY_CLOSE_SEQUENCE" }) | (components["schemas"]["ReviewedDailyFact"] & { type: "REVIEWED_FACT" }) | (components["schemas"]["MinuteCloseInRange"] & { type: "MINUTE_CLOSE_IN_RANGE" }) | (components["schemas"]["MinuteCloseBelow"] & { type: "MINUTE_CLOSE_BELOW" }) | (components["schemas"]["MinuteVolumeToMeanGteInput"] & { type: "MINUTE_VOLUME_TO_MEAN_GTE" }) | (components["schemas"]["UnifiedAllInput"] & { type: "ALL" }) | (components["schemas"]["UnifiedAnyInput"] & { type: "ANY" })) | (null);
  confirmation: ((components["schemas"]["OfficialDailyConfirmation"] & { kind: "OFFICIAL_DAILY_CLOSE" }) | (components["schemas"]["CompletedMinuteConfirmation"] & { kind: "COMPLETED_BAR_CLOSE" })) | (null);
  kind: ("RISK_ALERT") | (null);
  rule_id: (string) | (null);
};

export type UnifiedDraftPosition = {
  allocation_evidence?: (string) | (null);
  allocation_provenance?: ("EXISTING_CONFIRMED" | "PROPOSED") | (null);
  core_target_qty?: (number) | (null);
  max_qty: (number) | (null);
  tactical_target_qty?: (number) | (null);
};

export type UnifiedDraftRisk = {
  condition: ((components["schemas"]["DailyPriceCompare"] & { type: "DAILY_PRICE_COMPARE" }) | (components["schemas"]["DailyPriceInRange"] & { type: "DAILY_PRICE_IN_RANGE" }) | (components["schemas"]["DailyVolumeRatio"] & { type: "DAILY_VOLUME_RATIO" }) | (components["schemas"]["DailyCandleRatio"] & { type: "DAILY_CANDLE_RATIO" }) | (components["schemas"]["DailyIndicatorCompare"] & { type: "DAILY_INDICATOR_COMPARE" }) | (components["schemas"]["DailyCloseSequence"] & { type: "DAILY_CLOSE_SEQUENCE" }) | (components["schemas"]["ReviewedDailyFact"] & { type: "REVIEWED_FACT" }) | (components["schemas"]["MinuteCloseInRange"] & { type: "MINUTE_CLOSE_IN_RANGE" }) | (components["schemas"]["MinuteCloseBelow"] & { type: "MINUTE_CLOSE_BELOW" }) | (components["schemas"]["MinuteVolumeToMeanGte"] & { type: "MINUTE_VOLUME_TO_MEAN_GTE" }) | (components["schemas"]["UnifiedAll"] & { type: "ALL" }) | (components["schemas"]["UnifiedAny"] & { type: "ANY" })) | (null);
  evidence_mode: ("TWO_OFFICIAL_CLOSES" | "STRUCTURE_AND_DETERIORATION") | (null);
  involves_core: (boolean) | (null);
  kind: "ORDINARY_TECHNICAL" | "SEVERE_TECHNICAL";
  priority: (number) | (null);
  scope_evidence: (string) | (null);
  suspension_confirmation_policy: ("RESUME_FIRST_CLOSE" | "RESTART_ADJACENT_PAIR") | (null);
  target_core_qty: (number) | (null);
  target_tactical_qty: (number) | (null);
};

export type UnifiedDraftRiskInput = {
  condition: ((components["schemas"]["DailyPriceCompareInput"] & { type: "DAILY_PRICE_COMPARE" }) | (components["schemas"]["DailyPriceInRange"] & { type: "DAILY_PRICE_IN_RANGE" }) | (components["schemas"]["DailyVolumeRatioInput"] & { type: "DAILY_VOLUME_RATIO" }) | (components["schemas"]["DailyCandleRatioInput"] & { type: "DAILY_CANDLE_RATIO" }) | (components["schemas"]["DailyIndicatorCompareInput"] & { type: "DAILY_INDICATOR_COMPARE" }) | (components["schemas"]["DailyCloseSequenceInput"] & { type: "DAILY_CLOSE_SEQUENCE" }) | (components["schemas"]["ReviewedDailyFact"] & { type: "REVIEWED_FACT" }) | (components["schemas"]["MinuteCloseInRange"] & { type: "MINUTE_CLOSE_IN_RANGE" }) | (components["schemas"]["MinuteCloseBelow"] & { type: "MINUTE_CLOSE_BELOW" }) | (components["schemas"]["MinuteVolumeToMeanGteInput"] & { type: "MINUTE_VOLUME_TO_MEAN_GTE" }) | (components["schemas"]["UnifiedAllInput"] & { type: "ALL" }) | (components["schemas"]["UnifiedAnyInput"] & { type: "ANY" })) | (null);
  evidence_mode: ("TWO_OFFICIAL_CLOSES" | "STRUCTURE_AND_DETERIORATION") | (null);
  involves_core: (boolean) | (null);
  kind: "ORDINARY_TECHNICAL" | "SEVERE_TECHNICAL";
  priority: (number) | (null);
  scope_evidence: (string) | (null);
  suspension_confirmation_policy: ("RESUME_FIRST_CLOSE" | "RESTART_ADJACENT_PAIR") | (null);
  target_core_qty: (number) | (null);
  target_tactical_qty: (number) | (null);
};

export type UnifiedDraftRule = {
  bucket: ("TACTICAL") | (null);
  condition: ((components["schemas"]["DailyPriceCompare"] & { type: "DAILY_PRICE_COMPARE" }) | (components["schemas"]["DailyPriceInRange"] & { type: "DAILY_PRICE_IN_RANGE" }) | (components["schemas"]["DailyVolumeRatio"] & { type: "DAILY_VOLUME_RATIO" }) | (components["schemas"]["DailyCandleRatio"] & { type: "DAILY_CANDLE_RATIO" }) | (components["schemas"]["DailyIndicatorCompare"] & { type: "DAILY_INDICATOR_COMPARE" }) | (components["schemas"]["DailyCloseSequence"] & { type: "DAILY_CLOSE_SEQUENCE" }) | (components["schemas"]["ReviewedDailyFact"] & { type: "REVIEWED_FACT" }) | (components["schemas"]["MinuteCloseInRange"] & { type: "MINUTE_CLOSE_IN_RANGE" }) | (components["schemas"]["MinuteCloseBelow"] & { type: "MINUTE_CLOSE_BELOW" }) | (components["schemas"]["MinuteVolumeToMeanGte"] & { type: "MINUTE_VOLUME_TO_MEAN_GTE" }) | (components["schemas"]["UnifiedAll"] & { type: "ALL" }) | (components["schemas"]["UnifiedAny"] & { type: "ANY" })) | (null);
  confirmation: ((components["schemas"]["OfficialDailyConfirmation"] & { kind: "OFFICIAL_DAILY_CLOSE" }) | (components["schemas"]["CompletedMinuteConfirmation"] & { kind: "COMPLETED_BAR_CLOSE" })) | (null);
  execution_window: ("NEXT_EXCHANGE_SESSION_ONLY" | "CURRENT_SESSION") | (null);
  independent_signal: ((components["schemas"]["DailyIndependentEvent"] & { mode: "REVIEWED_INDEPENDENT_EVENT" }) | (components["schemas"]["UnifiedResetPolicy"] & { mode: "LATER_CLOSE_RESET_THEN_CONFIRM" })) | (null);
  invalidation: ("RISK_OR_REVIEWED_INVALIDATION") | (null);
  quantity: (number) | (null);
  rule_id: (string) | (null);
  side: "BUY" | "SELL";
  status: ("ENABLED") | (null);
  validity: (components["schemas"]["PlanActiveValidity"]) | (components["schemas"]["DailyValidity"]) | (null);
  zone: ("LOW_BUY" | "PRESSURE") | (null);
};

export type UnifiedDraftRuleInput = {
  bucket: ("TACTICAL") | (null);
  condition: ((components["schemas"]["DailyPriceCompareInput"] & { type: "DAILY_PRICE_COMPARE" }) | (components["schemas"]["DailyPriceInRange"] & { type: "DAILY_PRICE_IN_RANGE" }) | (components["schemas"]["DailyVolumeRatioInput"] & { type: "DAILY_VOLUME_RATIO" }) | (components["schemas"]["DailyCandleRatioInput"] & { type: "DAILY_CANDLE_RATIO" }) | (components["schemas"]["DailyIndicatorCompareInput"] & { type: "DAILY_INDICATOR_COMPARE" }) | (components["schemas"]["DailyCloseSequenceInput"] & { type: "DAILY_CLOSE_SEQUENCE" }) | (components["schemas"]["ReviewedDailyFact"] & { type: "REVIEWED_FACT" }) | (components["schemas"]["MinuteCloseInRange"] & { type: "MINUTE_CLOSE_IN_RANGE" }) | (components["schemas"]["MinuteCloseBelow"] & { type: "MINUTE_CLOSE_BELOW" }) | (components["schemas"]["MinuteVolumeToMeanGteInput"] & { type: "MINUTE_VOLUME_TO_MEAN_GTE" }) | (components["schemas"]["UnifiedAllInput"] & { type: "ALL" }) | (components["schemas"]["UnifiedAnyInput"] & { type: "ANY" })) | (null);
  confirmation: ((components["schemas"]["OfficialDailyConfirmation"] & { kind: "OFFICIAL_DAILY_CLOSE" }) | (components["schemas"]["CompletedMinuteConfirmation"] & { kind: "COMPLETED_BAR_CLOSE" })) | (null);
  execution_window: ("NEXT_EXCHANGE_SESSION_ONLY" | "CURRENT_SESSION") | (null);
  independent_signal: ((components["schemas"]["DailyIndependentEvent"] & { mode: "REVIEWED_INDEPENDENT_EVENT" }) | (components["schemas"]["UnifiedResetPolicyInput"] & { mode: "LATER_CLOSE_RESET_THEN_CONFIRM" })) | (null);
  invalidation: ("RISK_OR_REVIEWED_INVALIDATION") | (null);
  quantity: (number) | (null);
  rule_id: (string) | (null);
  side: "BUY" | "SELL";
  status: ("ENABLED") | (null);
  validity: (components["schemas"]["PlanActiveValidity"]) | (components["schemas"]["DailyValidity"]) | (null);
  zone: ("LOW_BUY" | "PRESSURE") | (null);
};

export type UnifiedExecutionPolicy = {
  ordinary_conflict: "BLOCK_BOTH";
  risk_priority: "SEVERE_THEN_ORDINARY";
  same_signal: "ONE_PLANNED_QUANTITY";
};

export type UnifiedMonitoring = {
  comparability_requirement: "CURRENT_QUOTE_BASIS";
  indicator_formula_version: "daily-ta-v2";
  macd_min_observations: number;
  price_basis: "QFQ";
  source_requirement: "ONE_VERIFIED_PROVIDER";
};

export type UnifiedPlanDraft = {
  activation: ((components["schemas"]["DailyManualActivation"] & { mode: "MANUAL" }) | (components["schemas"]["DailyDayActivation"] & { mode: "TRADING_DAY" }) | (components["schemas"]["DailyRangeActivation"] & { mode: "DATE_RANGE" })) | (null);
  alert_rules?: Array<components["schemas"]["UnifiedDraftAlertRule"]>;
  execution_mode?: "CONDITION_PLAN";
  execution_policy: (components["schemas"]["UnifiedExecutionPolicy"]) | (null);
  execution_version?: "condition-plan-v1";
  levels: (components["schemas"]["DailyDraftLevels"]) | (null);
  market: "SSE" | "SZSE" | "BSE";
  metadata: components["schemas"]["DailyMetadata"];
  monitoring: (components["schemas"]["UnifiedMonitoring"]) | (null);
  name: string;
  ordinary_rules: Array<components["schemas"]["UnifiedDraftRule"]>;
  plan_id: string;
  position: components["schemas"]["UnifiedDraftPosition"];
  risk_branches: Array<components["schemas"]["UnifiedDraftRisk"]>;
  schema_version?: 5;
  symbol: string;
  trading_rules?: components["schemas"]["DailyTradingRules"];
  version: number;
};

export type UnifiedPlanDraftInput = {
  activation: ((components["schemas"]["DailyManualActivation"] & { mode: "MANUAL" }) | (components["schemas"]["DailyDayActivation"] & { mode: "TRADING_DAY" }) | (components["schemas"]["DailyRangeActivation"] & { mode: "DATE_RANGE" })) | (null);
  alert_rules?: Array<components["schemas"]["UnifiedDraftAlertRuleInput"]>;
  execution_mode?: "CONDITION_PLAN";
  execution_policy: (components["schemas"]["UnifiedExecutionPolicy"]) | (null);
  execution_version?: "condition-plan-v1";
  levels: (components["schemas"]["DailyDraftLevels"]) | (null);
  market: "SSE" | "SZSE" | "BSE";
  metadata: components["schemas"]["DailyMetadata"];
  monitoring: (components["schemas"]["UnifiedMonitoring"]) | (null);
  name: string;
  ordinary_rules: Array<components["schemas"]["UnifiedDraftRuleInput"]>;
  plan_id: string;
  position: components["schemas"]["UnifiedDraftPosition"];
  risk_branches: Array<components["schemas"]["UnifiedDraftRiskInput"]>;
  schema_version?: 5;
  symbol: string;
  trading_rules?: components["schemas"]["DailyTradingRules"];
  version: number;
};

export type UnifiedPositionPolicy = {
  allocation_evidence?: (string) | (null);
  allocation_provenance?: ("EXISTING_CONFIRMED" | "PROPOSED") | (null);
  core_target_qty?: (number) | (null);
  max_qty: number;
  tactical_target_qty?: (number) | (null);
};

export type UnifiedResearchInput = {
  adjustment_proofs?: Array<components["schemas"]["ResearchAdjustmentProof"]>;
  calendar_extension?: Array<components["schemas"]["TradingDay"]>;
  inventory_known: boolean;
  operations?: Array<(components["schemas"]["ResearchFact"] & { kind: "FACT" }) | (components["schemas"]["ResearchDeactivate"] & { kind: "DEACTIVATE" }) | (components["schemas"]["ResearchReplace"] & { kind: "REPLACE" }) | (components["schemas"]["ResearchSimulation"] & { kind: "SIMULATE" }) | (components["schemas"]["ResearchReassessment"] & { kind: "REASSESS" })>;
  review: components["schemas"]["ResearchReview"];
  schema_version?: "unified-research-input-v1";
  started_at: string;
};

export type UnifiedResetPolicy = {
  mode: "LATER_CLOSE_RESET_THEN_CONFIRM";
  reset_condition: (components["schemas"]["DailyPriceCompare"] & { type: "DAILY_PRICE_COMPARE" }) | (components["schemas"]["DailyPriceInRange"] & { type: "DAILY_PRICE_IN_RANGE" }) | (components["schemas"]["DailyVolumeRatio"] & { type: "DAILY_VOLUME_RATIO" }) | (components["schemas"]["DailyCandleRatio"] & { type: "DAILY_CANDLE_RATIO" }) | (components["schemas"]["DailyIndicatorCompare"] & { type: "DAILY_INDICATOR_COMPARE" }) | (components["schemas"]["DailyCloseSequence"] & { type: "DAILY_CLOSE_SEQUENCE" }) | (components["schemas"]["ReviewedDailyFact"] & { type: "REVIEWED_FACT" }) | (components["schemas"]["MinuteCloseInRange"] & { type: "MINUTE_CLOSE_IN_RANGE" }) | (components["schemas"]["MinuteCloseBelow"] & { type: "MINUTE_CLOSE_BELOW" }) | (components["schemas"]["MinuteVolumeToMeanGte"] & { type: "MINUTE_VOLUME_TO_MEAN_GTE" }) | (components["schemas"]["UnifiedAll"] & { type: "ALL" }) | (components["schemas"]["UnifiedAny"] & { type: "ANY" });
};

export type UnifiedResetPolicyInput = {
  mode: "LATER_CLOSE_RESET_THEN_CONFIRM";
  reset_condition: (components["schemas"]["DailyPriceCompareInput"] & { type: "DAILY_PRICE_COMPARE" }) | (components["schemas"]["DailyPriceInRange"] & { type: "DAILY_PRICE_IN_RANGE" }) | (components["schemas"]["DailyVolumeRatioInput"] & { type: "DAILY_VOLUME_RATIO" }) | (components["schemas"]["DailyCandleRatioInput"] & { type: "DAILY_CANDLE_RATIO" }) | (components["schemas"]["DailyIndicatorCompareInput"] & { type: "DAILY_INDICATOR_COMPARE" }) | (components["schemas"]["DailyCloseSequenceInput"] & { type: "DAILY_CLOSE_SEQUENCE" }) | (components["schemas"]["ReviewedDailyFact"] & { type: "REVIEWED_FACT" }) | (components["schemas"]["MinuteCloseInRange"] & { type: "MINUTE_CLOSE_IN_RANGE" }) | (components["schemas"]["MinuteCloseBelow"] & { type: "MINUTE_CLOSE_BELOW" }) | (components["schemas"]["MinuteVolumeToMeanGteInput"] & { type: "MINUTE_VOLUME_TO_MEAN_GTE" }) | (components["schemas"]["UnifiedAllInput"] & { type: "ALL" }) | (components["schemas"]["UnifiedAnyInput"] & { type: "ANY" });
};

export type UnifiedRiskBranch = {
  condition: ((components["schemas"]["DailyPriceCompare"] & { type: "DAILY_PRICE_COMPARE" }) | (components["schemas"]["DailyPriceInRange"] & { type: "DAILY_PRICE_IN_RANGE" }) | (components["schemas"]["DailyVolumeRatio"] & { type: "DAILY_VOLUME_RATIO" }) | (components["schemas"]["DailyCandleRatio"] & { type: "DAILY_CANDLE_RATIO" }) | (components["schemas"]["DailyIndicatorCompare"] & { type: "DAILY_INDICATOR_COMPARE" }) | (components["schemas"]["DailyCloseSequence"] & { type: "DAILY_CLOSE_SEQUENCE" }) | (components["schemas"]["ReviewedDailyFact"] & { type: "REVIEWED_FACT" }) | (components["schemas"]["MinuteCloseInRange"] & { type: "MINUTE_CLOSE_IN_RANGE" }) | (components["schemas"]["MinuteCloseBelow"] & { type: "MINUTE_CLOSE_BELOW" }) | (components["schemas"]["MinuteVolumeToMeanGte"] & { type: "MINUTE_VOLUME_TO_MEAN_GTE" }) | (components["schemas"]["UnifiedAll"] & { type: "ALL" }) | (components["schemas"]["UnifiedAny"] & { type: "ANY" })) | (null);
  evidence_mode: "TWO_OFFICIAL_CLOSES" | "STRUCTURE_AND_DETERIORATION";
  involves_core: boolean;
  kind: "ORDINARY_TECHNICAL" | "SEVERE_TECHNICAL";
  priority: number;
  scope_evidence: string;
  suspension_confirmation_policy?: ("RESUME_FIRST_CLOSE" | "RESTART_ADJACENT_PAIR") | (null);
  target_core_qty: number;
  target_tactical_qty: number;
};

export type UnifiedRule = {
  bucket: "TACTICAL";
  condition: (components["schemas"]["DailyPriceCompare"] & { type: "DAILY_PRICE_COMPARE" }) | (components["schemas"]["DailyPriceInRange"] & { type: "DAILY_PRICE_IN_RANGE" }) | (components["schemas"]["DailyVolumeRatio"] & { type: "DAILY_VOLUME_RATIO" }) | (components["schemas"]["DailyCandleRatio"] & { type: "DAILY_CANDLE_RATIO" }) | (components["schemas"]["DailyIndicatorCompare"] & { type: "DAILY_INDICATOR_COMPARE" }) | (components["schemas"]["DailyCloseSequence"] & { type: "DAILY_CLOSE_SEQUENCE" }) | (components["schemas"]["ReviewedDailyFact"] & { type: "REVIEWED_FACT" }) | (components["schemas"]["MinuteCloseInRange"] & { type: "MINUTE_CLOSE_IN_RANGE" }) | (components["schemas"]["MinuteCloseBelow"] & { type: "MINUTE_CLOSE_BELOW" }) | (components["schemas"]["MinuteVolumeToMeanGte"] & { type: "MINUTE_VOLUME_TO_MEAN_GTE" }) | (components["schemas"]["UnifiedAll"] & { type: "ALL" }) | (components["schemas"]["UnifiedAny"] & { type: "ANY" });
  confirmation: (components["schemas"]["OfficialDailyConfirmation"] & { kind: "OFFICIAL_DAILY_CLOSE" }) | (components["schemas"]["CompletedMinuteConfirmation"] & { kind: "COMPLETED_BAR_CLOSE" });
  execution_window: "NEXT_EXCHANGE_SESSION_ONLY" | "CURRENT_SESSION";
  independent_signal: (components["schemas"]["DailyIndependentEvent"] & { mode: "REVIEWED_INDEPENDENT_EVENT" }) | (components["schemas"]["UnifiedResetPolicy"] & { mode: "LATER_CLOSE_RESET_THEN_CONFIRM" });
  invalidation: "RISK_OR_REVIEWED_INVALIDATION";
  quantity: number;
  rule_id: string;
  side: "BUY" | "SELL";
  status: "ENABLED";
  validity: (components["schemas"]["PlanActiveValidity"]) | (components["schemas"]["DailyValidity"]);
  zone: ("LOW_BUY" | "PRESSURE") | (null);
};

export type UnifiedTradePlan = {
  activation: (components["schemas"]["DailyManualActivation"] & { mode: "MANUAL" }) | (components["schemas"]["DailyDayActivation"] & { mode: "TRADING_DAY" }) | (components["schemas"]["DailyRangeActivation"] & { mode: "DATE_RANGE" });
  alert_rules?: Array<components["schemas"]["UnifiedAlertRule"]>;
  execution_mode?: "CONDITION_PLAN";
  execution_policy: components["schemas"]["UnifiedExecutionPolicy"];
  execution_version?: "condition-plan-v1";
  levels: (components["schemas"]["DailyLevels"]) | (null);
  market: "SSE" | "SZSE" | "BSE";
  metadata: components["schemas"]["DailyMetadata"];
  monitoring: (components["schemas"]["UnifiedMonitoring"]) | (null);
  name: string;
  ordinary_rules: Array<components["schemas"]["UnifiedRule"]>;
  plan_id: string;
  position: components["schemas"]["UnifiedPositionPolicy"];
  risk_branches: Array<components["schemas"]["UnifiedRiskBranch"]>;
  schema_version?: 5;
  symbol: string;
  trading_rules: components["schemas"]["DailyTradingRules"];
  version: number;
};

export type UnknownLoopCash = {
  kind?: "UNKNOWN";
};

export type UnmappedText = {
  end?: (number) | (null);
  excerpt: string;
  material: boolean;
  path: string;
  reason: string;
  start?: (number) | (null);
};

export type UserSupplementView = {
  label: "human_confirmed_test_supplement" | "human_confirmed_supplement";
  path: string;
  supplementId: string;
  suppliedAt: string;
  unit: components["schemas"]["BindingUnit"];
  value: (boolean) | (number) | (string) | (null);
};

export type ValidationIssue = {
  activationBlocking: boolean;
  code: string;
  message: string;
  path: string;
  severity: components["schemas"]["ValidationSeverity"];
};

export type ValidationSeverity = "ERROR" | "WARNING";

export type trade_plan_monitor__web__routers__positions__PositionLotView = {
  acquiredTradeDate: string;
  bucket: "CORE" | "TACTICAL";
  closedAt?: (string) | (null);
  costFen: number;
  lotId: string;
  quantity: number;
  relatedAlertId?: (string) | (null);
  remainingQuantity: number;
  revision: number;
  sellableQuantity: number;
  symbol: string;
};

export type trade_plan_monitor__web__routers__symbols__PositionLotView = {
  acquiredTradeDate: string;
  bucket: "CORE" | "TACTICAL";
  costFen: number;
  lotId: string;
  quantity: number;
  remainingQuantity: number;
  sellableQuantity: number;
};

export interface components {
  schemas: {
    AIProviderConfiguration: AIProviderConfiguration;
    AIProviderPage: AIProviderPage;
    AIProviderType: AIProviderType;
    AIProviderView: AIProviderView;
    AIUsageView: AIUsageView;
    ActionableSignalType: ActionableSignalType;
    ActivePlanView: ActivePlanView;
    AlertAcknowledgementCommand: AlertAcknowledgementCommand;
    AlertPage: AlertPage;
    AlertPriceZoneView: AlertPriceZoneView;
    AlertSeverity: AlertSeverity;
    AlertView: AlertView;
    ApiErrorCode: ApiErrorCode;
    AuthoritativeDecisionView: AuthoritativeDecisionView;
    BacktestAssumptionsView: BacktestAssumptionsView;
    BacktestAuthoritativeDecisionView: BacktestAuthoritativeDecisionView;
    BacktestDataHealthView: BacktestDataHealthView;
    BacktestDataSyncCommand: BacktestDataSyncCommand;
    BacktestDataSyncJobResultView: BacktestDataSyncJobResultView;
    BacktestDatasetCoverageView: BacktestDatasetCoverageView;
    BacktestDatasetFiltersView: BacktestDatasetFiltersView;
    BacktestDatasetPage: BacktestDatasetPage;
    BacktestDatasetScopeInput: BacktestDatasetScopeInput;
    BacktestDatasetScopeView: BacktestDatasetScopeView;
    BacktestDatasetVerificationCommand: BacktestDatasetVerificationCommand;
    BacktestDatasetVerificationJobResultView: BacktestDatasetVerificationJobResultView;
    BacktestDatasetView: BacktestDatasetView;
    BacktestDecisionEvidenceView: BacktestDecisionEvidenceView;
    BacktestDecisionReferenceMarketView: BacktestDecisionReferenceMarketView;
    BacktestDecisionView: BacktestDecisionView;
    BacktestDetailFiltersView: BacktestDetailFiltersView;
    BacktestDetailPage: BacktestDetailPage;
    BacktestDetailView: BacktestDetailView;
    BacktestEquityPointView: BacktestEquityPointView;
    BacktestEquitySeries: BacktestEquitySeries;
    BacktestEvidenceFactView: BacktestEvidenceFactView;
    BacktestEvidenceScalar: BacktestEvidenceScalar;
    BacktestExecutionConfigInput: BacktestExecutionConfigInput;
    BacktestExecutionConfigView: BacktestExecutionConfigView;
    BacktestExecutionOutcomeView: BacktestExecutionOutcomeView;
    BacktestFeeBreakdownView: BacktestFeeBreakdownView;
    BacktestFillFiltersView: BacktestFillFiltersView;
    BacktestFillPage: BacktestFillPage;
    BacktestFillView: BacktestFillView;
    BacktestFormulaVersionsView: BacktestFormulaVersionsView;
    BacktestIndexConditionSummaryView: BacktestIndexConditionSummaryView;
    BacktestIndexMaLookbackParametersView: BacktestIndexMaLookbackParametersView;
    BacktestIndexMaParametersView: BacktestIndexMaParametersView;
    BacktestIndexReturnParametersView: BacktestIndexReturnParametersView;
    BacktestInitialLotInput: BacktestInitialLotInput;
    BacktestJobCancellationCommand: BacktestJobCancellationCommand;
    BacktestJobFiltersView: BacktestJobFiltersView;
    BacktestJobPage: BacktestJobPage;
    BacktestJobProgressView: BacktestJobProgressView;
    BacktestJobReceipt: BacktestJobReceipt;
    BacktestJobResultView: BacktestJobResultView;
    BacktestJobView: BacktestJobView;
    BacktestLoopCostsInput: BacktestLoopCostsInput;
    BacktestLoopEventView: BacktestLoopEventView;
    BacktestLoopFillView: BacktestLoopFillView;
    BacktestLoopProvenanceView: BacktestLoopProvenanceView;
    BacktestLoopResponseInput: BacktestLoopResponseInput;
    BacktestLoopRunSummaryView: BacktestLoopRunSummaryView;
    BacktestLoopRunView: BacktestLoopRunView;
    BacktestMarketIndexHealthPointView: BacktestMarketIndexHealthPointView;
    BacktestMarketIndexPointView: BacktestMarketIndexPointView;
    BacktestMarketIndexSeriesView: BacktestMarketIndexSeriesView;
    BacktestMetricsView: BacktestMetricsView;
    BacktestNextStepView: BacktestNextStepView;
    BacktestPositionSummaryView: BacktestPositionSummaryView;
    BacktestReferenceMarketBindingView: BacktestReferenceMarketBindingView;
    BacktestReferenceMarketCoverageView: BacktestReferenceMarketCoverageView;
    BacktestReferenceMarketView: BacktestReferenceMarketView;
    BacktestResultAvailabilityView: BacktestResultAvailabilityView;
    BacktestRunCommand: BacktestRunCommand;
    BacktestRunCoverageView: BacktestRunCoverageView;
    BacktestRunFiltersView: BacktestRunFiltersView;
    BacktestRunJobResultView: BacktestRunJobResultView;
    BacktestRunPage: BacktestRunPage;
    BacktestRunPinCommand: BacktestRunPinCommand;
    BacktestRunSummaryView: BacktestRunSummaryView;
    BacktestRunView: BacktestRunView;
    BacktestServiceControlReceipt: BacktestServiceControlReceipt;
    BacktestServiceRecoveryCommand: BacktestServiceRecoveryCommand;
    BacktestServiceState: BacktestServiceState;
    BacktestServiceStopCommand: BacktestServiceStopCommand;
    BacktestServiceView: BacktestServiceView;
    BacktestSignalView: BacktestSignalView;
    BarInterval: BarInterval;
    BarPage: BarPage;
    BarView: BarView;
    BindingKind: BindingKind;
    BindingOrigin: BindingOrigin;
    BindingUnit: BindingUnit;
    Board: Board;
    CalendarScopeView: CalendarScopeView;
    CapturedReminder: CapturedReminder;
    CertifiedDailyBar: CertifiedDailyBar;
    ClauseDisposition: ClauseDisposition;
    CompletedMinuteConfirmation: CompletedMinuteConfirmation;
    ConditionOutcome: ConditionOutcome;
    ConditionPlanEntryView: ConditionPlanEntryView;
    ConfiguredAIProviderRuntimeView: ConfiguredAIProviderRuntimeView;
    ConfiguredAIRuntimeView: ConfiguredAIRuntimeView;
    CoordinatorStatusView: CoordinatorStatusView;
    DailyAlertCenterView: DailyAlertCenterView;
    DailyAlertEvent: DailyAlertEvent;
    DailyAll: DailyAll;
    DailyAny: DailyAny;
    DailyCandleRatio: DailyCandleRatio;
    DailyCandleRatioInput: DailyCandleRatioInput;
    DailyClause: DailyClause;
    DailyCloseSequence: DailyCloseSequence;
    DailyCloseSequenceInput: DailyCloseSequenceInput;
    DailyConditionEvidence: DailyConditionEvidence;
    DailyDayActivation: DailyDayActivation;
    DailyDraftLevels: DailyDraftLevels;
    DailyDraftZone: DailyDraftZone;
    DailyEditorSchemaView: DailyEditorSchemaView;
    DailyEvaluationApiView: DailyEvaluationApiView;
    DailyExecutionQuote: DailyExecutionQuote;
    DailyFactCommand: DailyFactCommand;
    DailyFactRevision: DailyFactRevision;
    DailyFieldBinding: DailyFieldBinding;
    DailyIndependentEvent: DailyIndependentEvent;
    DailyIndicatorCompare: DailyIndicatorCompare;
    DailyIndicatorCompareInput: DailyIndicatorCompareInput;
    DailyInventoryApiView: DailyInventoryApiView;
    DailyInventoryResource: DailyInventoryResource;
    DailyInventoryView: DailyInventoryView;
    DailyLevels: DailyLevels;
    DailyManualActivation: DailyManualActivation;
    DailyMapping: DailyMapping;
    DailyMetadata: DailyMetadata;
    DailyMutationReceipt: DailyMutationReceipt;
    DailyObsoleteRiskApiView: DailyObsoleteRiskApiView;
    DailyOfficialEvidence: DailyOfficialEvidence;
    DailyOfficialProof: DailyOfficialProof;
    DailyPositionCommand: DailyPositionCommand;
    DailyPriceCompare: DailyPriceCompare;
    DailyPriceCompareInput: DailyPriceCompareInput;
    DailyPriceInRange: DailyPriceInRange;
    DailyRangeActivation: DailyRangeActivation;
    DailyReviewIssue: DailyReviewIssue;
    DailyReviewPreview: DailyReviewPreview;
    DailyReviewPreviewCommand: DailyReviewPreviewCommand;
    DailyReviewSnapshot: DailyReviewSnapshot;
    DailyRiskAction: DailyRiskAction;
    DailyRiskActionApiView: DailyRiskActionApiView;
    DailyRiskApiView: DailyRiskApiView;
    DailyRiskReassessmentCommand: DailyRiskReassessmentCommand;
    DailyRiskState: DailyRiskState;
    DailyRuleReminderState: DailyRuleReminderState;
    DailySeries: DailySeries;
    DailySignalApiView: DailySignalApiView;
    DailySignalState: DailySignalState;
    DailySimulationCommand: DailySimulationCommand;
    DailySimulationReceipt: DailySimulationReceipt;
    DailySourceExclusion: DailySourceExclusion;
    DailyStateView: DailyStateView;
    DailySupplement: DailySupplement;
    DailySupplementCommand: DailySupplementCommand;
    DailyTechnicalRemainder: DailyTechnicalRemainder;
    DailyTradingRules: DailyTradingRules;
    DailyValidity: DailyValidity;
    DailyVolumeRatio: DailyVolumeRatio;
    DailyVolumeRatioInput: DailyVolumeRatioInput;
    DailyZone: DailyZone;
    DashboardCounts: DashboardCounts;
    DataHealthStatus: DataHealthStatus;
    DataHealthView: DataHealthView;
    DatabaseHealthView: DatabaseHealthView;
    DecisionEvidenceView: DecisionEvidenceView;
    DecisionZone: DecisionZone;
    DeliveryHealthView: DeliveryHealthView;
    DiagnosticEvaluationCommand: DiagnosticEvaluationCommand;
    DiagnosticEvaluationView: DiagnosticEvaluationView;
    DraftReviewIssue: DraftReviewIssue;
    DynamicDailyReference: DynamicDailyReference;
    EpisodeStatus: EpisodeStatus;
    ErrorDetail: ErrorDetail;
    ErrorPayload: ErrorPayload;
    ErrorResponse: ErrorResponse;
    EvaluationKind: EvaluationKind;
    EvidenceFactView: EvidenceFactView;
    EvidenceKind: EvidenceKind;
    EvidenceUnit: EvidenceUnit;
    ExecutionStatus: ExecutionStatus;
    ExecutorHealthView: ExecutorHealthView;
    ExplicitAlertView: ExplicitAlertView;
    ExplicitConditionEvidenceView: ExplicitConditionEvidenceView;
    ExplicitPlanCapabilityView: ExplicitPlanCapabilityView;
    ExplicitPlanEntryView: ExplicitPlanEntryView;
    ExplicitPlanRuntimeView: ExplicitPlanRuntimeView;
    ExplicitRuleOutcomeView: ExplicitRuleOutcomeView;
    ExtractionIssue: ExtractionIssue;
    FieldBindingView: FieldBindingView;
    FieldEvidence: FieldEvidence;
    FiveMinuteBar: FiveMinuteBar;
    FixedDailyReference: FixedDailyReference;
    FixedDailyReferenceInput: FixedDailyReferenceInput;
    IndexConditionEvidenceView: IndexConditionEvidenceView;
    IndexConditionProgressView: IndexConditionProgressView;
    IndexScopeView: IndexScopeView;
    IntradayDiagnosticIdentityView: IntradayDiagnosticIdentityView;
    IntradayTargetView: IntradayTargetView;
    InventorySourceTreatmentView: InventorySourceTreatmentView;
    JsonValue: JsonValue;
    KnownLoopCash: KnownLoopCash;
    LegacyPlanEntryView: LegacyPlanEntryView;
    LegacyPlanInvalidateCommand: LegacyPlanInvalidateCommand;
    LegacyPlanInvalidateResult: LegacyPlanInvalidateResult;
    LegacyPlanItemView: LegacyPlanItemView;
    LegacyPlanPreviewResponse: LegacyPlanPreviewResponse;
    LoopAccountInput: LoopAccountInput;
    LoopAccountReceipt: LoopAccountReceipt;
    LoopAccountState: LoopAccountState;
    LoopAttempt: LoopAttempt;
    LoopAuditEvent: LoopAuditEvent;
    LoopAuditPayload: LoopAuditPayload;
    LoopCosts: LoopCosts;
    LoopCycleSummary: LoopCycleSummary;
    LoopEndBoundary: LoopEndBoundary;
    LoopEvaluation: LoopEvaluation;
    LoopExecution: LoopExecution;
    LoopFillCosts: LoopFillCosts;
    LoopInitialLot: LoopInitialLot;
    LoopLedgerLot: LoopLedgerLot;
    LoopMetrics: LoopMetrics;
    LoopOpeningMark: LoopOpeningMark;
    LoopPlanReview: LoopPlanReview;
    LoopPlanVersion: LoopPlanVersion;
    LoopReminder: LoopReminder;
    LoopRequest: LoopRequest;
    LoopResponsePolicy: LoopResponsePolicy;
    LoopResultingState: LoopResultingState;
    LoopValuation: LoopValuation;
    LoopValuationEvent: LoopValuationEvent;
    ManualEventRiskUnknownReason: ManualEventRiskUnknownReason;
    ManualEventRiskView: ManualEventRiskView;
    ManualEventRiskViewStatus: ManualEventRiskViewStatus;
    MarketIndexBarPage: MarketIndexBarPage;
    MarketIndexBarView: MarketIndexBarView;
    MarketIndexCode: MarketIndexCode;
    MarketIndexFactUnit: MarketIndexFactUnit;
    MarketIndexHealth: MarketIndexHealth;
    MarketIndexInterval: MarketIndexInterval;
    MarketIndexIssueCode: MarketIndexIssueCode;
    MarketIndexLatestAcquisition: MarketIndexLatestAcquisition;
    MarketIndexOverviewData: MarketIndexOverviewData;
    MarketIndexOverviewItem: MarketIndexOverviewItem;
    MarketIndexOverviewResponse: MarketIndexOverviewResponse;
    MarketIndexSnapshotView: MarketIndexSnapshotView;
    MarketIndexSourceKind: MarketIndexSourceKind;
    MarketSessionView: MarketSessionView;
    MarketTurnoverSummaryView: MarketTurnoverSummaryView;
    MinuteBar: MinuteBar;
    MinuteCloseBelow: MinuteCloseBelow;
    MinuteCloseInRange: MinuteCloseInRange;
    MinuteVolumeToMeanGte: MinuteVolumeToMeanGte;
    MinuteVolumeToMeanGteInput: MinuteVolumeToMeanGteInput;
    MissingInputCode: MissingInputCode;
    MonitorLoopReport: MonitorLoopReport;
    NextStepCode: NextStepCode;
    NextStepView: NextStepView;
    ObsoleteDailyAlertView: ObsoleteDailyAlertView;
    OfficialCloseDiagnosticIdentityView: OfficialCloseDiagnosticIdentityView;
    OfficialCloseTargetView: OfficialCloseTargetView;
    OfficialDailyConfirmation: OfficialDailyConfirmation;
    OpeningAccountFacts: OpeningAccountFacts;
    OpeningFact_Annotated_Decimal__BeforeValidator__FieldInfo_annotation_NoneType__required_True__metadata__Ge_ge_0___Le_le_9007199254740991____PydanticGeneralMetadata_allow_inf_nan_False_____: OpeningFact_Annotated_Decimal__BeforeValidator__FieldInfo_annotation_NoneType__required_True__metadata__Ge_ge_0___Le_le_9007199254740991____PydanticGeneralMetadata_allow_inf_nan_False_____;
    OpeningFact_Annotated_datetime__BeforeValidator__AfterValidator__: OpeningFact_Annotated_datetime__BeforeValidator__AfterValidator__;
    OpeningFact_Annotated_int__FieldInfo_annotation_NoneType__required_True__metadata__Ge_ge_0___Le_le_9007199254740991___MultipleOf_multiple_of_100_____: OpeningFact_Annotated_int__FieldInfo_annotation_NoneType__required_True__metadata__Ge_ge_0___Le_le_9007199254740991___MultipleOf_multiple_of_100_____;
    OpeningFact_Annotated_int__FieldInfo_annotation_NoneType__required_True__metadata__Ge_ge_0___Le_le_9007199254740991_____: OpeningFact_Annotated_int__FieldInfo_annotation_NoneType__required_True__metadata__Ge_ge_0___Le_le_9007199254740991_____;
    OpeningFact_Annotated_int__FieldInfo_annotation_NoneType__required_True__metadata__Gt_gt_0___Le_le_9007199254740991___MultipleOf_multiple_of_100_____: OpeningFact_Annotated_int__FieldInfo_annotation_NoneType__required_True__metadata__Gt_gt_0___Le_le_9007199254740991___MultipleOf_multiple_of_100_____;
    OpeningFact_Literal__CORE____TACTICAL___: OpeningFact_Literal__CORE____TACTICAL___;
    OpeningFact_date_: OpeningFact_date_;
    OpeningLotFacts: OpeningLotFacts;
    OperationKind: OperationKind;
    OperationReceipt: OperationReceipt;
    PlanActivationCommand: PlanActivationCommand;
    PlanActiveValidity: PlanActiveValidity;
    PlanDeactivationCommand: PlanDeactivationCommand;
    PlanDocumentFormat: PlanDocumentFormat;
    PlanDraftCommand: PlanDraftCommand;
    PlanExtractionCommand: PlanExtractionCommand;
    PlanExtractionOperationStatus: PlanExtractionOperationStatus;
    PlanExtractionView: PlanExtractionView;
    PlanImportCommand: PlanImportCommand;
    PlanMappingView: PlanMappingView;
    PlanReviewConfirmationCommand: PlanReviewConfirmationCommand;
    PlanReviewConfirmationView: PlanReviewConfirmationView;
    PlanReviewResolution: PlanReviewResolution;
    PlanScopeView: PlanScopeView;
    PlanVersionPage: PlanVersionPage;
    PlanVersionStatus: PlanVersionStatus;
    PlanVersionSummary: PlanVersionSummary;
    PlanVersionView: PlanVersionView;
    PositionInventoryView: PositionInventoryView;
    PositionLotPage: PositionLotPage;
    PositionOpeningBalanceView: PositionOpeningBalanceView;
    PositionPrefillAction: PositionPrefillAction;
    PositionPrefillView: PositionPrefillView;
    PositionSummaryView: PositionSummaryView;
    PreparationAttemptView: PreparationAttemptView;
    PreparationCreateCommand: PreparationCreateCommand;
    PreparationExtractionCandidate: PreparationExtractionCandidate;
    PreparationFrozenCandidate: PreparationFrozenCandidate;
    PreparationFrozenManifest: PreparationFrozenManifest;
    PreparationFrozenView: PreparationFrozenView;
    PreparationRecoveryCommand: PreparationRecoveryCommand;
    PreparationReviewDeclaration: PreparationReviewDeclaration;
    PreparationReviewInput: PreparationReviewInput;
    PreparationRevisionCommand: PreparationRevisionCommand;
    PreparationSource: PreparationSource;
    PreparationSourceCommand: PreparationSourceCommand;
    PreparationUnavailableCandidate: PreparationUnavailableCandidate;
    PreparationView: PreparationView;
    PreparedBacktestRunCommand: PreparedBacktestRunCommand;
    ProductSourceTreatmentView: ProductSourceTreatmentView;
    ProviderCapabilityStatus: ProviderCapabilityStatus;
    ProviderHealthView: ProviderHealthView;
    ProviderScopeView: ProviderScopeView;
    RequiredReviewIssueView: RequiredReviewIssueView;
    ResearchAdjustmentProof: ResearchAdjustmentProof;
    ResearchConditionEvidence: ResearchConditionEvidence;
    ResearchDeactivate: ResearchDeactivate;
    ResearchDecisionEvent: ResearchDecisionEvent;
    ResearchDecisionView: ResearchDecisionView;
    ResearchEquityView: ResearchEquityView;
    ResearchFact: ResearchFact;
    ResearchFactor: ResearchFactor;
    ResearchMetricsView: ResearchMetricsView;
    ResearchOperationOutcome: ResearchOperationOutcome;
    ResearchOperationValuation: ResearchOperationValuation;
    ResearchOperationView: ResearchOperationView;
    ResearchReassessment: ResearchReassessment;
    ResearchReminder: ResearchReminder;
    ResearchReplace: ResearchReplace;
    ResearchReview: ResearchReview;
    ResearchRuleEvidence: ResearchRuleEvidence;
    ResearchSimulation: ResearchSimulation;
    ReturnIndicatorFactView: ReturnIndicatorFactView;
    ReturnWindow: ReturnWindow;
    ReviewIssueKind: ReviewIssueKind;
    ReviewResolutionKind: ReviewResolutionKind;
    ReviewedDailyFact: ReviewedDailyFact;
    RiskStatus: RiskStatus;
    RuleEligibilityView: RuleEligibilityView;
    RuntimeDashboardResponse: RuntimeDashboardResponse;
    RuntimeGapView: RuntimeGapView;
    RuntimeHealthV2Response: RuntimeHealthV2Response;
    RuntimeHeartbeatFrame: RuntimeHeartbeatFrame;
    RuntimeInactiveSymbolResponse: RuntimeInactiveSymbolResponse;
    RuntimeLegacyDetailsView: RuntimeLegacyDetailsView;
    RuntimeResourceStatus: RuntimeResourceStatus;
    RuntimeSnapshotRequiredFrame: RuntimeSnapshotRequiredFrame;
    RuntimeStatusView: RuntimeStatusView;
    RuntimeSymbolCollectionResponse: RuntimeSymbolCollectionResponse;
    RuntimeSymbolDetailResponse: RuntimeSymbolDetailResponse;
    RuntimeSymbolHealthResponse: RuntimeSymbolHealthResponse;
    ScopeProgressView: ScopeProgressView;
    SecretReferenceView: SecretReferenceView;
    SecretSource: SecretSource;
    SecretStatusView: SecretStatusView;
    SignalType: SignalType;
    SimulationCommand: SimulationCommand;
    SimulationReceipt: SimulationReceipt;
    SinglePlanPreparationInput: SinglePlanPreparationInput;
    SmaIndicatorFactView: SmaIndicatorFactView;
    SmaLookbackIndicatorFactView: SmaLookbackIndicatorFactView;
    SourceAlertView: SourceAlertView;
    SourceClauseView: SourceClauseView;
    SourceProcessingView: SourceProcessingView;
    SourceSpanView: SourceSpanView;
    SymbolEventPage: SymbolEventPage;
    SymbolEventType: SymbolEventType;
    SymbolEventView: SymbolEventView;
    SymbolReferenceMarketView: SymbolReferenceMarketView;
    TradingDay: TradingDay;
    UnavailablePlanEntryView: UnavailablePlanEntryView;
    UnfilledReason: UnfilledReason;
    UnifiedAlertRule: UnifiedAlertRule;
    UnifiedAll: UnifiedAll;
    UnifiedAllInput: UnifiedAllInput;
    UnifiedAny: UnifiedAny;
    UnifiedAnyInput: UnifiedAnyInput;
    UnifiedConditionEvidence: UnifiedConditionEvidence;
    UnifiedDraftAlertRule: UnifiedDraftAlertRule;
    UnifiedDraftAlertRuleInput: UnifiedDraftAlertRuleInput;
    UnifiedDraftPosition: UnifiedDraftPosition;
    UnifiedDraftRisk: UnifiedDraftRisk;
    UnifiedDraftRiskInput: UnifiedDraftRiskInput;
    UnifiedDraftRule: UnifiedDraftRule;
    UnifiedDraftRuleInput: UnifiedDraftRuleInput;
    UnifiedExecutionPolicy: UnifiedExecutionPolicy;
    UnifiedMonitoring: UnifiedMonitoring;
    UnifiedPlanDraft: UnifiedPlanDraft;
    UnifiedPlanDraftInput: UnifiedPlanDraftInput;
    UnifiedPositionPolicy: UnifiedPositionPolicy;
    UnifiedResearchInput: UnifiedResearchInput;
    UnifiedResetPolicy: UnifiedResetPolicy;
    UnifiedResetPolicyInput: UnifiedResetPolicyInput;
    UnifiedRiskBranch: UnifiedRiskBranch;
    UnifiedRule: UnifiedRule;
    UnifiedTradePlan: UnifiedTradePlan;
    UnknownLoopCash: UnknownLoopCash;
    UnmappedText: UnmappedText;
    UserSupplementView: UserSupplementView;
    ValidationIssue: ValidationIssue;
    ValidationSeverity: ValidationSeverity;
    trade_plan_monitor__web__routers__positions__PositionLotView: trade_plan_monitor__web__routers__positions__PositionLotView;
    trade_plan_monitor__web__routers__symbols__PositionLotView: trade_plan_monitor__web__routers__symbols__PositionLotView;
  };
}

export interface paths {
  "/api/v1/ai-providers": {
    get: {
      parameters: {
        query?: {
          limit?: number;
          offset?: number;
        };
        header?: never;
        path?: never;
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["AIProviderPage"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/ai-runtime": {
    get: {
      parameters: {
        query?: never;
        header?: never;
        path?: never;
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["ConfiguredAIRuntimeView"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/alert-acknowledgements": {
    post: {
      parameters: {
        query?: never;
        header: {
          "Idempotency-Key": string;
          "X-Monitor-Contract-Version": "2";
        };
        path?: never;
        cookie?: never;
      };
      requestBody: {
        content: {
          "application/json": components["schemas"]["AlertAcknowledgementCommand"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": (components["schemas"]["AlertView"]) | (components["schemas"]["ExplicitAlertView"]) | (components["schemas"]["DailyAlertCenterView"]) | (components["schemas"]["ObsoleteDailyAlertView"]);
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/alerts": {
    get: {
      parameters: {
        query?: {
          acknowledged?: (boolean) | (null);
          endAt?: (string) | (null);
          limit?: number;
          offset?: number;
          signalType?: (components["schemas"]["ActionableSignalType"]) | ("BUY" | "SELL" | "RISK_ALERT" | "RISK_EXIT") | (null);
          startAt?: (string) | (null);
          symbol?: (string) | (null);
        };
        header?: never;
        path?: never;
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["AlertPage"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/backtest-data-syncs": {
    post: {
      parameters: {
        query?: never;
        header: {
          "Idempotency-Key": string;
        };
        path?: never;
        cookie?: never;
      };
      requestBody: {
        content: {
          "application/json": components["schemas"]["BacktestDataSyncCommand"];
        };
      };
      responses: {
        "202": {
          content: {
            "application/json": components["schemas"]["BacktestJobReceipt"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/backtest-dataset-verifications": {
    post: {
      parameters: {
        query?: never;
        header: {
          "Idempotency-Key": string;
        };
        path?: never;
        cookie?: never;
      };
      requestBody: {
        content: {
          "application/json": components["schemas"]["BacktestDatasetVerificationCommand"];
        };
      };
      responses: {
        "202": {
          content: {
            "application/json": components["schemas"]["BacktestJobReceipt"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/backtest-datasets": {
    get: {
      parameters: {
        query?: {
          adjustmentPolicy?: ("NONE") | (null);
          cursor?: (string) | (null);
          endOnOrBefore?: (string) | (null);
          historicalProfile?: ("TUSHARE_STK_MINS_241_END_V1") | (null);
          limit?: number;
          startOnOrAfter?: (string) | (null);
          symbol?: (string) | (null);
        };
        header?: never;
        path?: never;
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["BacktestDatasetPage"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/backtest-datasets/{dataset_hash}": {
    get: {
      parameters: {
        query?: never;
        header?: never;
        path: {
          dataset_hash: string;
        };
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["BacktestDatasetView"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/backtest-datasets/{dataset_hash}/reference-market-coverage": {
    get: {
      parameters: {
        query: {
          planVersionId: string;
        };
        header?: never;
        path: {
          dataset_hash: string;
        };
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["BacktestReferenceMarketCoverageView"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/backtest-job-cancellations": {
    post: {
      parameters: {
        query?: never;
        header: {
          "Idempotency-Key": string;
        };
        path?: never;
        cookie?: never;
      };
      requestBody: {
        content: {
          "application/json": components["schemas"]["BacktestJobCancellationCommand"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["BacktestJobView"];
          };
        };
        "202": {
          content: {
            "application/json": components["schemas"]["BacktestJobView"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/backtest-jobs": {
    get: {
      parameters: {
        query?: {
          createdFrom?: (string) | (null);
          createdTo?: (string) | (null);
          cursor?: (string) | (null);
          datasetHash?: (string) | (null);
          kind?: (Array<"DATA_SYNC" | "DATASET_VERIFY" | "BACKTEST_RUN">) | (null);
          limit?: number;
          runId?: (string) | (null);
          status?: (Array<"QUEUED" | "RUNNING" | "CANCEL_REQUESTED" | "COMPLETED" | "FAILED" | "CANCELLED">) | (null);
        };
        header?: never;
        path?: never;
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["BacktestJobPage"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/backtest-jobs/{job_id}": {
    get: {
      parameters: {
        query?: never;
        header?: never;
        path: {
          job_id: string;
        };
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["BacktestJobView"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/backtest-preparations": {
    post: {
      parameters: {
        query?: never;
        header: {
          "Idempotency-Key": string;
        };
        path?: never;
        cookie?: never;
      };
      requestBody: {
        content: {
          "application/json": components["schemas"]["PreparationCreateCommand"];
        };
      };
      responses: {
        "201": {
          content: {
            "application/json": components["schemas"]["PreparationView"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/backtest-preparations/{preparation_id}": {
    get: {
      parameters: {
        query?: never;
        header?: never;
        path: {
          preparation_id: string;
        };
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["PreparationView"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/backtest-preparations/{preparation_id}/cancellations": {
    post: {
      parameters: {
        query?: never;
        header: {
          "Idempotency-Key": string;
        };
        path: {
          preparation_id: string;
        };
        cookie?: never;
      };
      requestBody: {
        content: {
          "application/json": components["schemas"]["PreparationRevisionCommand"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["PreparationView"];
          };
        };
        "202": {
          content: {
            "application/json": components["schemas"]["PreparationView"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/backtest-preparations/{preparation_id}/extractions": {
    post: {
      parameters: {
        query?: never;
        header: {
          "Idempotency-Key": string;
        };
        path: {
          preparation_id: string;
        };
        cookie?: never;
      };
      requestBody: {
        content: {
          "application/json": components["schemas"]["PreparationRevisionCommand"];
        };
      };
      responses: {
        "202": {
          content: {
            "application/json": components["schemas"]["PreparationView"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/backtest-preparations/{preparation_id}/recoveries": {
    post: {
      parameters: {
        query?: never;
        header: {
          "Idempotency-Key": string;
        };
        path: {
          preparation_id: string;
        };
        cookie?: never;
      };
      requestBody: {
        content: {
          "application/json": components["schemas"]["PreparationRecoveryCommand"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["PreparationView"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/backtest-preparations/{preparation_id}/reviews": {
    post: {
      parameters: {
        query?: never;
        header: {
          "Idempotency-Key": string;
        };
        path: {
          preparation_id: string;
        };
        cookie?: never;
      };
      requestBody: {
        content: {
          "application/json": components["schemas"]["PreparationReviewInput"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["PreparationFrozenView"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/backtest-preparations/{preparation_id}/source": {
    put: {
      parameters: {
        query?: never;
        header: {
          "Idempotency-Key": string;
        };
        path: {
          preparation_id: string;
        };
        cookie?: never;
      };
      requestBody: {
        content: {
          "application/json": components["schemas"]["PreparationSourceCommand"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["PreparationView"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/backtest-runs": {
    get: {
      parameters: {
        query?: {
          completedFrom?: (string) | (null);
          completedTo?: (string) | (null);
          cursor?: (string) | (null);
          datasetHash?: (string) | (null);
          limit?: number;
          pinned?: ("true" | "false") | (null);
          planVersionId?: (string) | (null);
          symbol?: (string) | (null);
        };
        header?: never;
        path?: never;
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["BacktestRunPage"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
    post: {
      parameters: {
        query?: never;
        header: {
          "Idempotency-Key": string;
        };
        path?: never;
        cookie?: never;
      };
      requestBody: {
        content: {
          "application/json": (components["schemas"]["BacktestRunCommand"]) | (components["schemas"]["PreparedBacktestRunCommand"]);
        };
      };
      responses: {
        "202": {
          content: {
            "application/json": components["schemas"]["BacktestJobReceipt"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/backtest-runs/{run_id}": {
    get: {
      parameters: {
        query?: never;
        header?: never;
        path: {
          run_id: string;
        };
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": (components["schemas"]["BacktestRunView"]) | (components["schemas"]["BacktestLoopRunView"]);
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
    patch: {
      parameters: {
        query?: never;
        header: {
          "Idempotency-Key": string;
        };
        path: {
          run_id: string;
        };
        cookie?: never;
      };
      requestBody: {
        content: {
          "application/json": components["schemas"]["BacktestRunPinCommand"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": (components["schemas"]["BacktestRunView"]) | (components["schemas"]["BacktestLoopRunView"]);
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/backtest-runs/{run_id}/details": {
    get: {
      parameters: {
        query: {
          cursor?: (string) | (null);
          kind: "DECISION" | "SIGNAL" | "EXECUTION_OUTCOME";
          limit?: number;
        };
        header?: never;
        path: {
          run_id: string;
        };
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["BacktestDetailPage"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/backtest-runs/{run_id}/equity-series": {
    get: {
      parameters: {
        query?: never;
        header?: never;
        path: {
          run_id: string;
        };
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["BacktestEquitySeries"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/backtest-runs/{run_id}/exports/{export_kind}": {
    get: {
      parameters: {
        query?: never;
        header?: never;
        path: {
          export_kind: "SUMMARY_JSON" | "FILLS_CSV";
          run_id: string;
        };
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": string;
            "text/csv": string;
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/backtest-runs/{run_id}/fills": {
    get: {
      parameters: {
        query?: {
          cursor?: (string) | (null);
          limit?: number;
        };
        header?: never;
        path: {
          run_id: string;
        };
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["BacktestFillPage"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/backtest-runs/{run_id}/market-index-series": {
    get: {
      parameters: {
        query?: {
          endOn?: (string) | (null);
          limit?: number;
          startOn?: (string) | (null);
        };
        header?: never;
        path: {
          run_id: string;
        };
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["BacktestMarketIndexSeriesView"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/backtest-service": {
    get: {
      parameters: {
        query?: never;
        header?: never;
        path?: never;
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["BacktestServiceView"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/backtest-service/recovery-requests": {
    post: {
      parameters: {
        query?: never;
        header: {
          "Idempotency-Key": string;
        };
        path?: never;
        cookie?: never;
      };
      requestBody: {
        content: {
          "application/json": components["schemas"]["BacktestServiceRecoveryCommand"];
        };
      };
      responses: {
        "202": {
          content: {
            "application/json": components["schemas"]["BacktestServiceControlReceipt"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/backtest-service/stop-requests": {
    post: {
      parameters: {
        query?: never;
        header: {
          "Idempotency-Key": string;
        };
        path?: never;
        cookie?: never;
      };
      requestBody: {
        content: {
          "application/json": components["schemas"]["BacktestServiceStopCommand"];
        };
      };
      responses: {
        "202": {
          content: {
            "application/json": components["schemas"]["BacktestServiceControlReceipt"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/dashboard": {
    get: {
      parameters: {
        query?: never;
        header: {
          "X-Monitor-Contract-Version": "2";
        };
        path?: never;
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["RuntimeDashboardResponse"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/diagnostic-evaluations": {
    post: {
      parameters: {
        query?: never;
        header: {
          "Idempotency-Key": string;
          "X-Monitor-Contract-Version": "2";
        };
        path?: never;
        cookie?: never;
      };
      requestBody: {
        content: {
          "application/json": components["schemas"]["DiagnosticEvaluationCommand"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["DiagnosticEvaluationView"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/health": {
    get: {
      parameters: {
        query?: never;
        header: {
          "X-Monitor-Contract-Version": "2";
        };
        path?: never;
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["RuntimeHealthV2Response"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/health/symbols/{symbol}": {
    get: {
      parameters: {
        query?: never;
        header: {
          "X-Monitor-Contract-Version": "2";
        };
        path: {
          symbol: string;
        };
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["RuntimeSymbolHealthResponse"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/manual-event-risk": {
    get: {
      parameters: {
        query: {
          symbol: string;
        };
        header?: never;
        path?: never;
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["ManualEventRiskView"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/market-indexes/overview": {
    get: {
      parameters: {
        query?: never;
        header?: never;
        path?: never;
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["MarketIndexOverviewResponse"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/market-indexes/{indexCode}/bars": {
    get: {
      parameters: {
        query: {
          cursor?: (string) | (null);
          endAt: string;
          interval: components["schemas"]["MarketIndexInterval"];
          limit: number;
          startAt: string;
        };
        header?: never;
        path: {
          indexCode: components["schemas"]["MarketIndexCode"];
        };
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["MarketIndexBarPage"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/plan-activation-states/{symbol}": {
    get: {
      parameters: {
        query?: never;
        header?: never;
        path: {
          symbol: string;
        };
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["ActivePlanView"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/plan-activations": {
    post: {
      parameters: {
        query?: never;
        header: {
          "Idempotency-Key": string;
          "X-Monitor-Contract-Version": "2";
        };
        path?: never;
        cookie?: never;
      };
      requestBody: {
        content: {
          "application/json": components["schemas"]["PlanActivationCommand"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["ActivePlanView"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/plan-capabilities": {
    get: {
      parameters: {
        query?: never;
        header?: never;
        path?: never;
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["ExplicitPlanCapabilityView"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/plan-deactivations": {
    post: {
      parameters: {
        query?: never;
        header: {
          "Idempotency-Key": string;
          "X-Monitor-Contract-Version": "2";
        };
        path?: never;
        cookie?: never;
      };
      requestBody: {
        content: {
          "application/json": components["schemas"]["PlanDeactivationCommand"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["ActivePlanView"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/plan-drafts": {
    post: {
      parameters: {
        query?: never;
        header: {
          "Idempotency-Key": string;
        };
        path?: never;
        cookie?: never;
      };
      requestBody: {
        content: {
          "application/json": components["schemas"]["PlanDraftCommand"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["PlanVersionView"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/plan-editor-schema": {
    get: {
      parameters: {
        query?: never;
        header?: never;
        path?: never;
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["DailyEditorSchemaView"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/plan-extractions": {
    post: {
      parameters: {
        query?: never;
        header: {
          "Idempotency-Key": string;
        };
        path?: never;
        cookie?: never;
      };
      requestBody: {
        content: {
          "application/json": components["schemas"]["PlanExtractionCommand"];
        };
      };
      responses: {
        "202": {
          content: {
            "application/json": components["schemas"]["OperationReceipt"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/plan-extractions/{operation_id}": {
    get: {
      parameters: {
        query?: never;
        header?: never;
        path: {
          operation_id: string;
        };
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["PlanExtractionView"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/plan-facts": {
    post: {
      parameters: {
        query?: never;
        header: {
          "Idempotency-Key": string;
        };
        path?: never;
        cookie?: never;
      };
      requestBody: {
        content: {
          "application/json": components["schemas"]["DailyFactCommand"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["DailyMutationReceipt"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/plan-imports": {
    post: {
      parameters: {
        query?: never;
        header: {
          "Idempotency-Key": string;
        };
        path?: never;
        cookie?: never;
      };
      requestBody: {
        content: {
          "application/json": components["schemas"]["PlanImportCommand"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["PlanVersionView"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/plan-review-confirmations": {
    post: {
      parameters: {
        query?: never;
        header: {
          "Idempotency-Key": string;
        };
        path?: never;
        cookie?: never;
      };
      requestBody: {
        content: {
          "application/json": components["schemas"]["PlanReviewConfirmationCommand"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["PlanReviewConfirmationView"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/plan-review-previews": {
    post: {
      parameters: {
        query?: never;
        header: {
          "Idempotency-Key": string;
        };
        path?: never;
        cookie?: never;
      };
      requestBody: {
        content: {
          "application/json": components["schemas"]["DailyReviewPreviewCommand"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["DailyReviewPreview"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/plan-review-supplements": {
    post: {
      parameters: {
        query?: never;
        header: {
          "Idempotency-Key": string;
        };
        path?: never;
        cookie?: never;
      };
      requestBody: {
        content: {
          "application/json": components["schemas"]["DailySupplementCommand"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["DailyMutationReceipt"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/plan-risk-reassessments": {
    post: {
      parameters: {
        query?: never;
        header: {
          "Idempotency-Key": string;
        };
        path?: never;
        cookie?: never;
      };
      requestBody: {
        content: {
          "application/json": components["schemas"]["DailyRiskReassessmentCommand"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["DailyMutationReceipt"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/plan-runtime/{symbol}": {
    get: {
      parameters: {
        query?: never;
        header?: never;
        path: {
          symbol: string;
        };
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["DailyStateView"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/plan-versions": {
    get: {
      parameters: {
        query?: {
          canActivate?: ("true" | "false") | (null);
          limit?: number;
          offset?: number;
          status?: (components["schemas"]["PlanVersionStatus"]) | (null);
          symbol?: (string) | (null);
        };
        header?: never;
        path?: never;
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["PlanVersionPage"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/plan-versions/{version_id}": {
    get: {
      parameters: {
        query?: never;
        header?: never;
        path: {
          version_id: string;
        };
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["PlanVersionView"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/position-inventory": {
    get: {
      parameters: {
        query: {
          asOfTradeDate: string;
          symbol: string;
        };
        header?: never;
        path?: never;
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["PositionInventoryView"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/position-lots": {
    get: {
      parameters: {
        query: {
          asOfTradeDate: string;
          limit?: number;
          offset?: number;
          symbol: string;
        };
        header?: never;
        path?: never;
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["PositionLotPage"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/simulated-trades": {
    post: {
      parameters: {
        query?: never;
        header: {
          "Idempotency-Key": string;
        };
        path?: never;
        cookie?: never;
      };
      requestBody: {
        content: {
          "application/json": components["schemas"]["DailySimulationCommand"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["DailySimulationReceipt"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/simulation-position-confirmations": {
    post: {
      parameters: {
        query?: never;
        header: {
          "Idempotency-Key": string;
        };
        path?: never;
        cookie?: never;
      };
      requestBody: {
        content: {
          "application/json": components["schemas"]["DailyPositionCommand"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["DailyMutationReceipt"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/simulation-position-inventory": {
    get: {
      parameters: {
        query: {
          asOfTradeDate: string;
          symbol: string;
        };
        header?: never;
        path?: never;
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["DailyInventoryResource"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/symbols": {
    get: {
      parameters: {
        query?: {
          limit?: number;
          offset?: number;
        };
        header: {
          "X-Monitor-Contract-Version": "2";
        };
        path?: never;
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["RuntimeSymbolCollectionResponse"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/symbols/{symbol}": {
    get: {
      parameters: {
        query?: never;
        header: {
          "X-Monitor-Contract-Version": "2";
        };
        path: {
          symbol: string;
        };
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": (components["schemas"]["RuntimeSymbolDetailResponse"]) | (components["schemas"]["RuntimeInactiveSymbolResponse"]);
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/symbols/{symbol}/bars": {
    get: {
      parameters: {
        query: {
          endAt: string;
          interval?: components["schemas"]["BarInterval"];
          limit?: number;
          offset?: number;
          startAt: string;
        };
        header?: never;
        path: {
          symbol: string;
        };
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["BarPage"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/symbols/{symbol}/events": {
    get: {
      parameters: {
        query: {
          endAt: string;
          limit?: number;
          offset?: number;
          startAt: string;
        };
        header?: never;
        path: {
          symbol: string;
        };
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["SymbolEventPage"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/v1/system/legacy-plan-invalidation": {
    get: {
      parameters: {
        query?: never;
        header?: never;
        path?: never;
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["LegacyPlanPreviewResponse"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
    post: {
      parameters: {
        query?: never;
        header: {
          "X-Monitor-Contract-Version": "2";
        };
        path?: never;
        cookie?: never;
      };
      requestBody: {
        content: {
          "application/json": components["schemas"]["LegacyPlanInvalidateCommand"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["LegacyPlanInvalidateResult"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "405": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "422": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
}
