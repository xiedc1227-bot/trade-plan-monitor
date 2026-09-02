// This file is generated from openapi.json by scripts/generate_frontend_types.py.
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

export type AIProviderConfigurationCommand = {
  config: components["schemas"]["AIProviderConfiguration"];
  expectedRevision: number;
};

export type AIProviderPage = {
  items?: Array<components["schemas"]["AIProviderView"]>;
  limit: number;
  offset: number;
  total: number;
};

export type AIProviderSecretCommand = {
  expectedRevision: number;
  providerId: string;
  secret: components["schemas"]["SecretWrite"];
};

export type AIProviderTestCommand = {
  expectedRevision: number;
  providerId: string;
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
  items?: Array<components["schemas"]["AlertView"]>;
  limit: number;
  offset: number;
  signalType?: (components["schemas"]["ActionableSignalType"]) | (null);
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
  schemaVersion: "backtest-dataset-v1";
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

export type BacktestDetailView = (components["schemas"]["BacktestDecisionView"]) | (components["schemas"]["BacktestSignalView"]) | (components["schemas"]["BacktestExecutionOutcomeView"]);

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
  items: Array<components["schemas"]["BacktestEquityPointView"]>;
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
  items: Array<components["schemas"]["BacktestFillView"]>;
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

export type BacktestJobResultView = (components["schemas"]["BacktestDataSyncJobResultView"]) | (components["schemas"]["BacktestDatasetVerificationJobResultView"]) | (components["schemas"]["BacktestRunJobResultView"]);

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
  items: Array<components["schemas"]["BacktestRunSummaryView"]>;
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
  metrics: components["schemas"]["BacktestMetricsView"];
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
  metrics: components["schemas"]["BacktestMetricsView"];
  pinned: boolean;
  planHash: string;
  planVersionId: (string) | (null);
  reportHash: string;
  revision: number;
  runId: string;
  status: "COMPLETED";
  symbol: string;
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

export type ConditionOutcome = "SATISFIED" | "UNSATISFIED" | "MISSING_INPUT";

export type ConfiguredAIRuntimeView = {
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

export type ConnectionStatus = "CONNECTED" | "DISCONNECTED" | "UNKNOWN";

export type DashboardCounts = {
  actionable: number;
  blocked: number;
  lowZoneWatch: number;
  normal: number;
  risk: number;
  stale: number;
};

export type DashboardResponse = {
  connectionStatus: components["schemas"]["ConnectionStatus"];
  counts: components["schemas"]["DashboardCounts"];
  dataAgeSeconds: (number) | (null);
  observedAt: string;
  sequence: number;
  symbols?: Array<components["schemas"]["SymbolSummaryView"]>;
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
  evaluationIdentity: (components["schemas"]["IntradayDiagnosticIdentityView"]) | (components["schemas"]["OfficialCloseDiagnosticIdentityView"]);
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

export type EvidenceUnit = "FEN" | "SHARES" | "RATIO" | "BARS" | "YUAN" | "COUNT" | "BOOLEAN" | "DATE" | "DATETIME" | "CODE";

export type ExecutionStatus = "FILLED" | "UNFILLED" | "IGNORED";

export type ExecutorHealthView = {
  activeCount: number;
  maxWorkers: number;
  waitingCount: number;
};

export type ExtractionIssue = {
  material: boolean;
  message: string;
  path: string;
};

export type FieldEvidence = {
  end?: (number) | (null);
  excerpt: string;
  path: string;
  start?: (number) | (null);
};

export type IntradayDiagnosticIdentityView = {
  bucketEnd: string;
  formulaVersion: "ta-v1";
  kind: "INTRADAY";
  planHash: string;
  symbol: string;
};

export type MissingInputCode = "COMPLETE_MINUTE_BAR" | "PREVIOUS_MINUTE_BAR" | "COMPLETE_5M_BAR" | "PREVIOUS_5M_BAR" | "COMPLETE_5M_BAR_WINDOW" | "ROLLING_VOLUME_WINDOW" | "SESSION_BARS" | "DAILY_INDICATORS" | "PROVISIONAL_DAILY_BAR" | "FIVE_MINUTE_INDICATORS" | "INDICATOR_VALUE" | "OFFICIAL_DAILY_CLOSE" | "TRADING_CALENDAR" | "DAILY_LIMIT" | "MANUAL_EVENT_RISK";

export type NextStepCode = "WAIT_FOR_COMPLETE_BAR" | "WAIT_FOR_REQUIRED_DATA" | "WATCH_LOW_ZONE" | "WATCH_PRESSURE" | "REVIEW_BLOCKER" | "WAIT_FOR_OFFICIAL_CLOSE" | "WAIT_FOR_NEXT_TRADING_DAY" | "WAIT_FOR_SETTLEMENT" | "RECORD_CONFIRMED_FILL";

export type NextStepView = {
  code: components["schemas"]["NextStepCode"];
  notBefore?: (string) | (string) | (null);
  requiredInputs?: Array<components["schemas"]["MissingInputCode"]>;
};

export type OfficialCloseDiagnosticIdentityView = {
  formulaVersion: "ta-v1";
  kind: "OFFICIAL_CLOSE";
  officialTradeDate: string;
  planHash: string;
  symbol: string;
};

export type OperationKind = "PLAN_EXTRACTION" | "AI_PROVIDER_TEST";

export type OperationReceipt = {
  kind: components["schemas"]["OperationKind"];
  operationId: string;
  status: "QUEUED";
  submittedAt: string;
};

export type PlanActivationCommand = {
  expectedRevision: number;
  planVersionId: string;
};

export type PlanDeactivationCommand = {
  expectedRevision: number;
  symbol: string;
};

export type PlanDocumentFormat = "JSON" | "YAML";

export type PlanDraftCommand = {
  expectedRevision: number;
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
  draftPlanJson?: (string) | (null);
  evidence?: Array<components["schemas"]["FieldEvidence"]>;
  id: string;
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
};

export type PlanVersionPage = {
  items?: Array<components["schemas"]["PlanVersionView"]>;
  limit: number;
  offset: number;
  total: number;
};

export type PlanVersionStatus = "DRAFT" | "ACTIVE" | "SUPERSEDED";

export type PlanVersionView = {
  canActivate: boolean;
  createdAt: string;
  id: string;
  planHash: string;
  planId: string;
  planJson: string;
  reviewIssues?: Array<components["schemas"]["DraftReviewIssue"]>;
  revision: number;
  sourceText: string;
  status: components["schemas"]["PlanVersionStatus"];
  symbol: string;
  validationIssues?: Array<components["schemas"]["ValidationIssue"]>;
  version: number;
};

export type PositionLotClosureCommand = {
  expectedRevision: number;
  lotId: string;
  quantity: number;
  tradeDate: string;
};

export type PositionLotClosureView = {
  afterRemainingQuantity: number;
  appliedQuantity: number;
  beforeRemainingQuantity: number;
  lot: components["schemas"]["trade_plan_monitor__web__routers__positions__PositionLotView"];
  tradeDate: string;
};

export type PositionLotCreateCommand = {
  acquiredTradeDate: string;
  bucket: "CORE" | "TACTICAL";
  costFen: number;
  expectedRevision: number;
  quantity: number;
  relatedAlertId?: (string) | (null);
  symbol: string;
};

export type PositionLotPage = {
  asOfTradeDate: string;
  items?: Array<components["schemas"]["trade_plan_monitor__web__routers__positions__PositionLotView"]>;
  limit: number;
  offset: number;
  symbol: string;
  total: number;
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

export type ProviderCapabilityStatus = "UNVERIFIED" | "READY" | "BLOCKED_PERMISSION" | "RATE_LIMITED" | "ERROR";

export type ProviderHealthView = {
  capability: string;
  checkedAt: string;
  errorCode: (string) | (null);
  latencyMs: number;
  nextRetryAt: (string) | (null);
  status: components["schemas"]["ProviderCapabilityStatus"];
};

export type ReviewIssueKind = "ASSUMPTION" | "WARNING" | "UNMAPPED_TEXT" | "MISSING_EVIDENCE";

export type RiskStatus = "CLEAR" | "BREACHED_PENDING_CONFIRMATION" | "EXIT_PENDING_SETTLEMENT";

export type RuntimeGapView = {
  barEnd: string;
  symbol: string;
};

export type RuntimeHealthResponse = {
  cooldownUntil: (string) | (null);
  database: components["schemas"]["DatabaseHealthView"];
  delivery: components["schemas"]["DeliveryHealthView"];
  executor: components["schemas"]["ExecutorHealthView"];
  gaps?: Array<components["schemas"]["RuntimeGapView"]>;
  lastCompletedMinute: (string) | (null);
  lastCompletedMinuteAgeSeconds: (number) | (null);
  latestEvaluationAgeSeconds: (number) | (null);
  latestEvaluationAt: (string) | (null);
  nextPollAt: (string) | (null);
  nextRetryAt: (string) | (null);
  observedAt: string;
  providers?: Array<components["schemas"]["ProviderHealthView"]>;
  readOnly: boolean;
  startedAt: string;
  status: components["schemas"]["RuntimeServiceStatus"];
  stoppedAt: (string) | (null);
};

export type RuntimeResourceStatus = "UNVERIFIED" | "READY" | "DEGRADED" | "ERROR" | "STOPPED";

export type RuntimeServiceStatus = "STARTING" | "RUNNING" | "DEGRADED" | "STOPPING" | "STOPPED";

export type SecretReferenceView = {
  environmentVariable?: (string) | (null);
  key: string;
};

export type SecretSource = "NONE" | "STORE" | "ENVIRONMENT";

export type SecretStatusView = {
  configured: boolean;
  generation: number;
  maskedValue: ("********") | (null);
  source: components["schemas"]["SecretSource"];
};

export type SecretWrite = {
  value: string;
};

export type SignalType = "WAIT" | "LOW_ZONE_WATCH" | "BLOCKED_DATA" | "BLOCKED_RISK" | "BUY_CORE_READY" | "BUY_TACTICAL_READY" | "PRESSURE_REDUCE_READY" | "RISK_BREACH" | "RISK_RECOVERED" | "RISK_EXIT_READY" | "RISK_EXIT_PENDING_SETTLEMENT";

export type SymbolDetailResponse = {
  positionLots?: Array<components["schemas"]["trade_plan_monitor__web__routers__symbols__PositionLotView"]>;
  summary: components["schemas"]["SymbolSummaryView"];
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

export type SymbolHealthErrorCode = "INCOMPLETE_BUCKET" | "HISTORY_GAP" | "STALE_DATA" | "PROVIDER_BLOCKED" | "PERSISTENCE_FAILED" | "INVALID_CONTEXT" | "CALENDAR_BLOCKED";

export type SymbolHealthResponse = {
  actionable: boolean;
  consecutiveIncompleteBuckets: number;
  dataAgeSeconds: (number) | (null);
  errorCode: (components["schemas"]["SymbolHealthErrorCode"]) | (null);
  fresh: boolean;
  gaps?: Array<string>;
  latestBarEnd: (string) | (null);
  observedAt: string;
  requiredDataComplete: boolean;
  status: components["schemas"]["DataHealthStatus"];
  symbol: string;
  targetEnd: string;
};

export type SymbolPage = {
  items?: Array<components["schemas"]["SymbolSummaryView"]>;
  limit: number;
  offset: number;
  total: number;
};

export type SymbolSummaryView = {
  connected: boolean;
  decision: components["schemas"]["AuthoritativeDecisionView"];
  name: string;
  observedAt: string;
  riskDistanceFen: (number) | (null);
  satisfiedConditionCount: number;
  symbol: string;
  totalConditionCount: number;
};

export type UnfilledReason = "NON_EXECUTABLE_SIGNAL" | "SUSPENDED" | "MISSING_NEXT_MINUTE" | "NO_NEXT_MINUTE" | "LIMIT_UP_LOCKED" | "LIMIT_DOWN_LOCKED" | "INSUFFICIENT_CASH" | "MAX_POSITION_REACHED" | "TARGET_POSITION_REACHED" | "TARGET_LOT_NOT_FOUND" | "T_PLUS_ONE";

export type UnmappedText = {
  end?: (number) | (null);
  excerpt: string;
  material: boolean;
  path: string;
  reason: string;
  start?: (number) | (null);
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
    AIProviderConfigurationCommand: AIProviderConfigurationCommand;
    AIProviderPage: AIProviderPage;
    AIProviderSecretCommand: AIProviderSecretCommand;
    AIProviderTestCommand: AIProviderTestCommand;
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
    BacktestInitialLotInput: BacktestInitialLotInput;
    BacktestJobCancellationCommand: BacktestJobCancellationCommand;
    BacktestJobFiltersView: BacktestJobFiltersView;
    BacktestJobPage: BacktestJobPage;
    BacktestJobProgressView: BacktestJobProgressView;
    BacktestJobReceipt: BacktestJobReceipt;
    BacktestJobResultView: BacktestJobResultView;
    BacktestJobView: BacktestJobView;
    BacktestMetricsView: BacktestMetricsView;
    BacktestNextStepView: BacktestNextStepView;
    BacktestPositionSummaryView: BacktestPositionSummaryView;
    BacktestResultAvailabilityView: BacktestResultAvailabilityView;
    BacktestRunCommand: BacktestRunCommand;
    BacktestRunCoverageView: BacktestRunCoverageView;
    BacktestRunFiltersView: BacktestRunFiltersView;
    BacktestRunJobResultView: BacktestRunJobResultView;
    BacktestRunPage: BacktestRunPage;
    BacktestRunPinCommand: BacktestRunPinCommand;
    BacktestRunSummaryView: BacktestRunSummaryView;
    BacktestRunView: BacktestRunView;
    BacktestSignalView: BacktestSignalView;
    BarInterval: BarInterval;
    BarPage: BarPage;
    BarView: BarView;
    ConditionOutcome: ConditionOutcome;
    ConfiguredAIRuntimeView: ConfiguredAIRuntimeView;
    ConnectionStatus: ConnectionStatus;
    DashboardCounts: DashboardCounts;
    DashboardResponse: DashboardResponse;
    DataHealthStatus: DataHealthStatus;
    DataHealthView: DataHealthView;
    DatabaseHealthView: DatabaseHealthView;
    DecisionEvidenceView: DecisionEvidenceView;
    DecisionZone: DecisionZone;
    DeliveryHealthView: DeliveryHealthView;
    DiagnosticEvaluationCommand: DiagnosticEvaluationCommand;
    DiagnosticEvaluationView: DiagnosticEvaluationView;
    DraftReviewIssue: DraftReviewIssue;
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
    ExtractionIssue: ExtractionIssue;
    FieldEvidence: FieldEvidence;
    IntradayDiagnosticIdentityView: IntradayDiagnosticIdentityView;
    MissingInputCode: MissingInputCode;
    NextStepCode: NextStepCode;
    NextStepView: NextStepView;
    OfficialCloseDiagnosticIdentityView: OfficialCloseDiagnosticIdentityView;
    OperationKind: OperationKind;
    OperationReceipt: OperationReceipt;
    PlanActivationCommand: PlanActivationCommand;
    PlanDeactivationCommand: PlanDeactivationCommand;
    PlanDocumentFormat: PlanDocumentFormat;
    PlanDraftCommand: PlanDraftCommand;
    PlanExtractionCommand: PlanExtractionCommand;
    PlanExtractionOperationStatus: PlanExtractionOperationStatus;
    PlanExtractionView: PlanExtractionView;
    PlanImportCommand: PlanImportCommand;
    PlanVersionPage: PlanVersionPage;
    PlanVersionStatus: PlanVersionStatus;
    PlanVersionView: PlanVersionView;
    PositionLotClosureCommand: PositionLotClosureCommand;
    PositionLotClosureView: PositionLotClosureView;
    PositionLotCreateCommand: PositionLotCreateCommand;
    PositionLotPage: PositionLotPage;
    PositionPrefillAction: PositionPrefillAction;
    PositionPrefillView: PositionPrefillView;
    PositionSummaryView: PositionSummaryView;
    ProviderCapabilityStatus: ProviderCapabilityStatus;
    ProviderHealthView: ProviderHealthView;
    ReviewIssueKind: ReviewIssueKind;
    RiskStatus: RiskStatus;
    RuntimeGapView: RuntimeGapView;
    RuntimeHealthResponse: RuntimeHealthResponse;
    RuntimeResourceStatus: RuntimeResourceStatus;
    RuntimeServiceStatus: RuntimeServiceStatus;
    SecretReferenceView: SecretReferenceView;
    SecretSource: SecretSource;
    SecretStatusView: SecretStatusView;
    SecretWrite: SecretWrite;
    SignalType: SignalType;
    SymbolDetailResponse: SymbolDetailResponse;
    SymbolEventPage: SymbolEventPage;
    SymbolEventType: SymbolEventType;
    SymbolEventView: SymbolEventView;
    SymbolHealthErrorCode: SymbolHealthErrorCode;
    SymbolHealthResponse: SymbolHealthResponse;
    SymbolPage: SymbolPage;
    SymbolSummaryView: SymbolSummaryView;
    UnfilledReason: UnfilledReason;
    UnmappedText: UnmappedText;
    ValidationIssue: ValidationIssue;
    ValidationSeverity: ValidationSeverity;
    trade_plan_monitor__web__routers__positions__PositionLotView: trade_plan_monitor__web__routers__positions__PositionLotView;
    trade_plan_monitor__web__routers__symbols__PositionLotView: trade_plan_monitor__web__routers__symbols__PositionLotView;
  };
}

export interface paths {
  "/api/v1/ai-provider-secrets": {
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
          "application/json": components["schemas"]["AIProviderSecretCommand"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["AIProviderView"];
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
  "/api/v1/ai-provider-tests": {
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
          "application/json": components["schemas"]["AIProviderTestCommand"];
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
          "application/json": components["schemas"]["AIProviderConfigurationCommand"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["AIProviderView"];
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
  "/api/v1/ai-providers/{provider_id}": {
    patch: {
      parameters: {
        query?: never;
        header: {
          "Idempotency-Key": string;
        };
        path: {
          provider_id: string;
        };
        cookie?: never;
      };
      requestBody: {
        content: {
          "application/json": components["schemas"]["AIProviderConfigurationCommand"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["AIProviderView"];
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
            "application/json": components["schemas"]["AlertView"];
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
          signalType?: (components["schemas"]["ActionableSignalType"]) | (null);
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
          "application/json": components["schemas"]["BacktestRunCommand"];
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
            "application/json": components["schemas"]["BacktestRunView"];
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
            "application/json": components["schemas"]["BacktestRunView"];
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
  "/api/v1/dashboard": {
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
            "application/json": components["schemas"]["DashboardResponse"];
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
        header?: never;
        path?: never;
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["RuntimeHealthResponse"];
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
            "application/json": components["schemas"]["SymbolHealthResponse"];
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
  "/api/v1/plan-deactivations": {
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
  "/api/v1/position-lot-closures": {
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
          "application/json": components["schemas"]["PositionLotClosureCommand"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["PositionLotClosureView"];
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
          "application/json": components["schemas"]["PositionLotCreateCommand"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["trade_plan_monitor__web__routers__positions__PositionLotView"];
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
        header?: never;
        path?: never;
        cookie?: never;
      };
      requestBody?: never;
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["SymbolPage"];
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
            "application/json": components["schemas"]["SymbolDetailResponse"];
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
}
