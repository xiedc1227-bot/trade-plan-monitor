import type {
  DashboardProjectionUnavailableResponse,
  DashboardResponse,
} from "./generated";
import {
  isCalendarDate,
  isShanghaiDateTime,
  shanghaiDateTimeKey,
} from "./shanghaiTime";
import { isCanonicalMarketIndexIdentity } from "./marketIndexIdentity";
import { ApiClientError, invalidResponse, requestJson } from "./transport";

export { ApiClientError };
export type { ApiClientErrorCode } from "./transport";

const MAX_SEQUENCE = Number.MAX_SAFE_INTEGER;
const MAX_VALIDATION_DEPTH = 32;

const marketIndexHealth = new Set(["LIVE", "STALE", "GAPPED", "BLOCKED"]);
const marketIndexIssues = new Set([
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
]);

const dataHealthStatuses = new Set([
  "STARTING",
  "LIVE",
  "STALE",
  "GAPPED",
  "DEGRADED",
  "BLOCKED",
  "CLOSE_PENDING",
]);
const decisionZones = new Set([
  "LOW_BUY",
  "OBSERVATION",
  "PRESSURE",
  "BELOW_RISK",
  "OUTSIDE",
  "UNKNOWN",
]);
const signalTypes = new Set([
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
]);
const actionableSignalTypes = new Set([
  "BUY_CORE_READY",
  "BUY_TACTICAL_READY",
  "PRESSURE_REDUCE_READY",
  "RISK_BREACH",
  "RISK_EXIT_READY",
  "RISK_EXIT_PENDING_SETTLEMENT",
]);
const riskStatuses = new Set([
  "CLEAR",
  "BREACHED_PENDING_CONFIRMATION",
  "EXIT_PENDING_SETTLEMENT",
]);
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
]);
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
]);
const evidenceKinds = new Set(["CONDITION", "RULE"]);
const conditionOutcomes = new Set(["SATISFIED", "UNSATISFIED", "MISSING_INPUT"]);
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
]);
const dashboardUnavailableReasons = new Set([
  "EMPTY_DATABASE",
  "NO_ACTIVE_PLANS",
  "AWAITING_FIRST_EVALUATION",
]);

export type DashboardProjectionResponse =
  | DashboardResponse
  | DashboardProjectionUnavailableResponse;

export interface ApiClient {
  getDashboard(options?: { signal?: AbortSignal }): Promise<DashboardProjectionResponse>;
}

export function createApiClient(
  fetchImplementation: typeof fetch = globalThis.fetch.bind(globalThis),
): ApiClient {
  return Object.freeze({
    async getDashboard(options?: { signal?: AbortSignal }) {
      const request: RequestInit = {
        headers: { Accept: "application/json" },
        method: "GET",
      };
      if (options?.signal !== undefined) {
        request.signal = options.signal;
      }

      const { body, status } = await requestJson(
        fetchImplementation,
        "/api/v1/dashboard",
        request,
      );
      try {
        if (!isDashboardProjectionResponse(body)) {
          throw invalidResponse(status);
        }
        return body;
      } catch (error) {
        if (error instanceof ApiClientError) {
          throw error;
        }
        throw invalidResponse(status);
      }
    },
  });
}

function isDashboardProjectionResponse(value: unknown): value is DashboardProjectionResponse {
  return isDashboardResponse(value) || isDashboardProjectionUnavailableResponse(value);
}

export function isDashboardProjectionUnavailableResponse(
  value: unknown,
): value is DashboardProjectionUnavailableResponse {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["availability", "observedAt", "reason", "sequence"]) &&
    hasKeys(value, ["availability", "observedAt", "reason", "sequence"]) &&
    value.availability === "UNAVAILABLE" &&
    isShanghaiDateTime(value.observedAt) &&
    isSafeSequence(value.sequence) &&
    typeof value.reason === "string" &&
    dashboardUnavailableReasons.has(value.reason)
  );
}

function isDashboardResponse(value: unknown): value is DashboardResponse {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, [
      "connectionStatus",
      "counts",
      "dataAgeSeconds",
      "marketIndexes",
      "observedAt",
      "runtimeGeneration",
      "sequence",
      "symbols",
    ])
  ) {
    return false;
  }
  if (!hasKeys(value, ["marketIndexes"])) {
    return false;
  }
  const counts = value.counts;
  const marketIndexes = value.marketIndexes;
  const symbols = value.symbols;
  return (
    (value.connectionStatus === "CONNECTED" ||
      value.connectionStatus === "DISCONNECTED" ||
      value.connectionStatus === "UNKNOWN") &&
    isNullableNonnegativeInteger(value.dataAgeSeconds) &&
    isShanghaiDateTime(value.observedAt) &&
    (value.runtimeGeneration === null || isUuidV4(value.runtimeGeneration)) &&
    isSafeSequence(value.sequence) &&
    isDashboardCounts(counts) &&
    isDashboardMarketIndexes(marketIndexes, value.observedAt) &&
    isDashboardSymbols(symbols, value.connectionStatus, value.observedAt)
  );
}

function isDashboardCounts(value: unknown): boolean {
  const keys = ["actionable", "blocked", "lowZoneWatch", "normal", "risk", "stale"];
  if (!isRecord(value) || !hasExactKeys(value, keys)) {
    return false;
  }
  return keys.every((key) => isNonnegativeInteger(value[key]));
}

function isSymbolSummary(value: unknown): boolean {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, [
      "connected",
      "decision",
      "name",
      "observedAt",
      "referenceMarket",
      "riskDistanceFen",
      "satisfiedConditionCount",
      "symbol",
      "totalConditionCount",
    ]) ||
    !hasKeys(value, [
      "connected",
      "decision",
      "name",
      "observedAt",
      "riskDistanceFen",
      "satisfiedConditionCount",
      "symbol",
      "totalConditionCount",
    ]) ||
    typeof value.connected !== "boolean" ||
    !isAuthoritativeDecision(value.decision) ||
    !isBoundedString(value.name, 128) ||
    !isShanghaiDateTime(value.observedAt) ||
    !isNullableInteger(value.riskDistanceFen) ||
    !isNonnegativeInteger(value.satisfiedConditionCount) ||
    !isShareSymbol(value.symbol) ||
    !isNonnegativeInteger(value.totalConditionCount)
  ) {
    return false;
  }
  if (
    value.referenceMarket !== undefined &&
    value.referenceMarket !== null &&
    !isSymbolReferenceMarket(value.referenceMarket)
  ) {
    return false;
  }
  const decision = value.decision as Record<string, unknown>;
  return (
    decision.symbol === value.symbol &&
    (value.satisfiedConditionCount as number) <= (value.totalConditionCount as number) &&
    shanghaiDateTimeKey(value.observedAt) >=
      shanghaiDateTimeKey(decision.evaluatedAt as string)
  );
}

export function isAuthoritativeDecision(value: unknown): boolean {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, [
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
      "resultHash",
      "riskBreachTradeDate",
      "riskStatus",
      "signalType",
      "symbol",
      "zone",
    ])
  ) {
    return false;
  }
  const required = [
    "dataAgeSeconds",
    "dataHealth",
    "episodeLowFen",
    "episodeStatus",
    "evaluatedAt",
    "marketDataAt",
    "nextStep",
    "planHash",
    "planId",
    "planVersion",
    "position",
    "priceFen",
    "resultHash",
    "riskBreachTradeDate",
    "riskStatus",
    "signalType",
    "symbol",
    "zone",
  ];
  return (
    hasKeys(value, required) &&
    isNullableNonnegativeInteger(value.dataAgeSeconds) &&
    isDataHealth(value.dataHealth) &&
    isNullablePositiveInteger(value.episodeLowFen) &&
    (value.episodeStatus === null ||
      value.episodeStatus === "ACTIVE" ||
      value.episodeStatus === "ALERTED" ||
      value.episodeStatus === "CLOSED") &&
    isShanghaiDateTime(value.evaluatedAt) &&
    (value.evidence === undefined ||
      (Array.isArray(value.evidence) &&
        value.evidence.length <= 50 &&
        value.evidence.every((item) => isDecisionEvidence(item)))) &&
    (value.marketDataAt === null || isShanghaiDateTime(value.marketDataAt)) &&
    isNextStep(value.nextStep) &&
    isSha256(value.planHash) &&
    isBoundedString(value.planId, 128) &&
    isPositiveInteger(value.planVersion) &&
    isPositionSummary(value.position) &&
    isNullablePositiveInteger(value.priceFen) &&
    isSha256(value.resultHash) &&
    (value.riskBreachTradeDate === null || isCalendarDate(value.riskBreachTradeDate)) &&
    typeof value.riskStatus === "string" &&
    riskStatuses.has(value.riskStatus) &&
    typeof value.signalType === "string" &&
    signalTypes.has(value.signalType) &&
    isShareSymbol(value.symbol) &&
    typeof value.zone === "string" &&
    decisionZones.has(value.zone) &&
    validateDecisionRelationships(value)
  );
}

function isDataHealth(value: unknown): boolean {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "dataAgeSeconds",
      "fresh",
      "latestBarEnd",
      "requiredDataComplete",
      "status",
    ]) ||
    !isNullableNonnegativeInteger(value.dataAgeSeconds) ||
    typeof value.fresh !== "boolean" ||
    !(value.latestBarEnd === null || isShanghaiDateTime(value.latestBarEnd)) ||
    typeof value.requiredDataComplete !== "boolean" ||
    typeof value.status !== "string" ||
    !dataHealthStatuses.has(value.status)
  ) {
    return false;
  }
  if ((value.latestBarEnd === null) !== (value.dataAgeSeconds === null)) {
    return false;
  }
  if (value.fresh && value.latestBarEnd === null) {
    return false;
  }
  if (
    value.status === "LIVE" &&
    (!value.fresh || !value.requiredDataComplete || value.latestBarEnd === null)
  ) {
    return false;
  }
  if (value.status === "STALE" && value.fresh) {
    return false;
  }
  return !(
    (value.status === "GAPPED" || value.status === "BLOCKED") &&
    value.requiredDataComplete
  );
}

function isNextStep(value: unknown): boolean {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["code", "notBefore", "requiredInputs"]) &&
    hasKeys(value, ["code"]) &&
    typeof value.code === "string" &&
    nextStepCodes.has(value.code) &&
    (value.notBefore === undefined ||
      value.notBefore === null ||
      isCalendarDate(value.notBefore) ||
      isShanghaiDateTime(value.notBefore)) &&
    (value.requiredInputs === undefined ||
      (Array.isArray(value.requiredInputs) &&
        value.requiredInputs.length <= 16 &&
        new Set(value.requiredInputs).size === value.requiredInputs.length &&
        value.requiredInputs.every(
          (item) => typeof item === "string" && missingInputCodes.has(item),
        )))
  );
}

function isPositionSummary(value: unknown): boolean {
  const keys = [
    "coreQuantity",
    "sellableCoreQuantity",
    "sellableTacticalQuantity",
    "tacticalQuantity",
    "totalQuantity",
  ];
  if (!isRecord(value) || !hasExactKeys(value, keys) || !keys.every((key) => isNonnegativeInteger(value[key]))) {
    return false;
  }
  const coreQuantity = value.coreQuantity as number;
  const tacticalQuantity = value.tacticalQuantity as number;
  return (
    value.totalQuantity === coreQuantity + tacticalQuantity &&
    (value.sellableCoreQuantity as number) <= coreQuantity &&
    (value.sellableTacticalQuantity as number) <= tacticalQuantity
  );
}

function isDecisionEvidence(value: unknown, depth = 0): boolean {
  if (depth > MAX_VALIDATION_DEPTH) {
    return false;
  }
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["children", "code", "facts", "kind", "missingInputs", "outcome"]) &&
    hasKeys(value, ["code", "kind", "outcome"]) &&
    isStableCode(value.code) &&
    typeof value.kind === "string" &&
    evidenceKinds.has(value.kind) &&
    typeof value.outcome === "string" &&
    conditionOutcomes.has(value.outcome) &&
    (value.children === undefined ||
      (Array.isArray(value.children) &&
        value.children.length <= 50 &&
        value.children.every((child) => isDecisionEvidence(child, depth + 1)))) &&
    (value.facts === undefined ||
      (Array.isArray(value.facts) && value.facts.length <= 512 && value.facts.every(isEvidenceFact))) &&
    (value.missingInputs === undefined ||
      (Array.isArray(value.missingInputs) &&
        value.missingInputs.length <= 16 &&
        value.missingInputs.every(
          (item) => typeof item === "string" && missingInputCodes.has(item),
        )))
  ) && validateEvidenceRelationships(value);
}

function isEvidenceFact(value: unknown): boolean {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["key", "unit", "value"]) ||
    !isEvidenceKey(value.key) ||
    typeof value.unit !== "string" ||
    !evidenceUnits.has(value.unit)
  ) {
    return false;
  }
  if (value.unit === "BOOLEAN") {
    return typeof value.value === "boolean";
  }
  if (value.unit === "DATE") {
    return isCalendarDate(value.value);
  }
  if (value.unit === "DATETIME") {
    return isShanghaiDateTime(value.value);
  }
  if (value.unit === "CODE") {
    return isStableCode(value.value);
  }
  if (value.unit === "FEN" || value.unit === "BARS" || value.unit === "COUNT") {
    return typeof value.value === "number" && Number.isSafeInteger(value.value);
  }
  if (value.unit === "RATIO" || value.unit === "YUAN" || value.unit === "POINTS") {
    return isDecimalString(value.value);
  }
  return (
    value.unit === "SHARES" &&
    ((typeof value.value === "number" && Number.isSafeInteger(value.value)) ||
      isDecimalString(value.value))
  );
}

function isDashboardMarketIndexes(value: unknown, observedAt: unknown): boolean {
  if (
    !Array.isArray(value) ||
    value.length > 5 ||
    typeof observedAt !== "string" ||
    !value.every(isMarketIndexSnapshot)
  ) {
    return false;
  }
  const indexes = value as Array<Record<string, unknown>>;
  const codes = indexes.map((item) => item.indexCode);
  return (
    new Set(codes).size === codes.length &&
    codes.every((code, index) => index === 0 || String(codes[index - 1]) < String(code)) &&
    indexes.every(
      (item) =>
        shanghaiDateTimeKey(item.observedAt as string) <= shanghaiDateTimeKey(observedAt),
    )
  );
}

function isMarketIndexSnapshot(value: unknown): boolean {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "board",
      "closePoints",
      "completedBucketAt",
      "displayName",
      "health",
      "indexCode",
      "indicatorFacts",
      "issues",
      "mappedSymbolCount",
      "mappingVersion",
      "observedAt",
      "priorClosePoints",
      "revision",
      "sessionChangeRatio",
      "snapshotHash",
    ]) ||
    !isCanonicalMarketIndexIdentity(value) ||
    typeof value.health !== "string" ||
    !marketIndexHealth.has(value.health) ||
    !isShanghaiDateTime(value.observedAt) ||
    !isPositiveInteger(value.revision) ||
    !isSha256(value.snapshotHash) ||
    !isNonnegativeInteger(value.mappedSymbolCount) ||
    value.mappedSymbolCount > 10 ||
    !Array.isArray(value.issues) ||
    value.issues.length > 16 ||
    new Set(value.issues).size !== value.issues.length ||
    !value.issues.every((issue) => typeof issue === "string" && marketIndexIssues.has(issue)) ||
    !Array.isArray(value.indicatorFacts) ||
    value.indicatorFacts.length > 50 ||
    !value.indicatorFacts.every(isMarketIndexIndicatorFact)
  ) {
    return false;
  }
  const headline = [
    value.closePoints,
    value.priorClosePoints,
    value.sessionChangeRatio,
    value.completedBucketAt,
  ];
  if (headline.some((item) => item === null) !== headline.every((item) => item === null)) {
    return false;
  }
  if (
    headline[0] !== null &&
    (!isDecimalString(headline[0]) ||
      !isDecimalString(headline[1]) ||
      !isDecimalString(headline[2]) ||
      !isShanghaiDateTime(headline[3]))
  ) {
    return false;
  }
  return !(
    value.completedBucketAt !== null &&
    shanghaiDateTimeKey(value.observedAt) < shanghaiDateTimeKey(value.completedBucketAt)
  );
}

function isMarketIndexIndicatorFact(value: unknown): boolean {
  if (!isRecord(value) || typeof value.formulaId !== "string") {
    return false;
  }
  const common =
    isDecimalString(value.value) &&
    isSha256(value.sourceBarHash) &&
    isSha256(value.formulaDefinitionHash);
  if (!common) {
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
      isDecimalString(value.comparisonValue) &&
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

function isSymbolReferenceMarket(value: unknown): boolean {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "board",
      "conditionProgress",
      "dataAt",
      "displayName",
      "health",
      "indexCode",
      "issues",
      "mappingVersion",
      "snapshotHash",
    ]) ||
    !isCanonicalMarketIndexIdentity(value) ||
    typeof value.health !== "string" ||
    !marketIndexHealth.has(value.health) ||
    !Array.isArray(value.issues) ||
    value.issues.length > 16 ||
    new Set(value.issues).size !== value.issues.length ||
    !value.issues.every((issue) => typeof issue === "string" && marketIndexIssues.has(issue)) ||
    !isIndexConditionProgress(value.conditionProgress)
  ) {
    return false;
  }
  return (
    (value.snapshotHash === null && value.dataAt === null) ||
    (isSha256(value.snapshotHash) && isShanghaiDateTime(value.dataAt))
  );
}

function isIndexConditionProgress(value: unknown): boolean {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["missing", "satisfied", "total", "unsatisfied"]) ||
    !isNonnegativeInteger(value.missing) ||
    !isNonnegativeInteger(value.satisfied) ||
    !isNonnegativeInteger(value.total) ||
    !isNonnegativeInteger(value.unsatisfied)
  ) {
    return false;
  }
  return value.missing + value.satisfied + value.unsatisfied === value.total;
}

function validateEvidenceRelationships(value: Record<string, unknown>): boolean {
  const facts = Array.isArray(value.facts) ? value.facts : [];
  const missingInputs = Array.isArray(value.missingInputs) ? value.missingInputs : [];
  const children = Array.isArray(value.children) ? value.children : [];
  if (
    new Set(facts.map((fact) => (fact as Record<string, unknown>).key)).size !== facts.length ||
    new Set(missingInputs).size !== missingInputs.length
  ) {
    return false;
  }
  if (value.outcome === "MISSING_INPUT") {
    return (
      missingInputs.length > 0 ||
      children.some(
        (child) => (child as Record<string, unknown>).outcome === "MISSING_INPUT",
      )
    );
  }
  return missingInputs.length === 0;
}

function isDashboardSymbols(
  value: unknown,
  connectionStatus: unknown,
  observedAt: unknown,
): boolean {
  if (value === undefined) {
    return true;
  }
  if (
    !Array.isArray(value) ||
    value.length > 10 ||
    !value.every(isSymbolSummary) ||
    typeof observedAt !== "string"
  ) {
    return false;
  }
  const symbols = value as Array<Record<string, unknown>>;
  if (new Set(symbols.map((item) => item.symbol)).size !== symbols.length) {
    return false;
  }
  return symbols.every(
    (item) =>
      shanghaiDateTimeKey(item.observedAt as string) <= shanghaiDateTimeKey(observedAt) &&
      !(
        connectionStatus === "DISCONNECTED" &&
        ((item.decision as Record<string, unknown>).dataHealth as Record<string, unknown>)
          .status === "LIVE"
      ),
  );
}

function validateDecisionRelationships(value: Record<string, unknown>): boolean {
  const marketValues = [value.marketDataAt, value.dataAgeSeconds, value.priceFen];
  if (marketValues.some((item) => item === null) && marketValues.some((item) => item !== null)) {
    return false;
  }
  if ((value.episodeStatus === null) !== (value.episodeLowFen === null)) {
    return false;
  }
  if (
    (value.riskStatus === "CLEAR" && value.riskBreachTradeDate !== null) ||
    (value.riskStatus !== "CLEAR" && value.riskBreachTradeDate === null)
  ) {
    return false;
  }
  const dataHealth = value.dataHealth as Record<string, unknown>;
  if (actionableSignalTypes.has(value.signalType as string) && dataHealth.status !== "LIVE") {
    return false;
  }
  const evaluatedAt = shanghaiDateTimeKey(value.evaluatedAt as string);
  if (
    value.marketDataAt !== null &&
    !matchesIntegerSecondAge(
      evaluatedAt,
      shanghaiDateTimeKey(value.marketDataAt as string),
      value.dataAgeSeconds as number,
    )
  ) {
    return false;
  }
  if (
    dataHealth.latestBarEnd !== null &&
    !matchesIntegerSecondAge(
      evaluatedAt,
      shanghaiDateTimeKey(dataHealth.latestBarEnd as string),
      dataHealth.dataAgeSeconds as number,
    )
  ) {
    return false;
  }
  if (
    value.riskBreachTradeDate !== null &&
    (value.riskBreachTradeDate as string) > (value.evaluatedAt as string).slice(0, 10)
  ) {
    return false;
  }
  return true;
}

function matchesIntegerSecondAge(
  evaluatedAt: bigint,
  marketDataAt: bigint,
  dataAgeSeconds: number,
): boolean {
  const deltaMicroseconds = evaluatedAt - marketDataAt;
  return (
    deltaMicroseconds >= 0n && deltaMicroseconds / 1_000_000n === BigInt(dataAgeSeconds)
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasOnlyKeys(value: Record<string, unknown>, allowed: readonly string[]): boolean {
  const allowedKeys = new Set(allowed);
  return Object.keys(value).every((key) => allowedKeys.has(key));
}

function hasKeys(value: Record<string, unknown>, required: readonly string[]): boolean {
  return required.every((key) => Object.hasOwn(value, key));
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(value).length === keys.length && hasKeys(value, keys);
}

function isStableCode(value: unknown): value is string {
  return typeof value === "string" && /^[A-Z][A-Z0-9_]{0,63}$/.test(value);
}

function isEvidenceKey(value: unknown): value is string {
  return typeof value === "string" && /^[a-z][a-z0-9_]{0,63}$/.test(value);
}

function isDecimalString(value: unknown): value is string {
  if (typeof value !== "string" || value.length === 0 || value.length > 10_000) {
    return false;
  }
  let index = value[0] === "+" || value[0] === "-" ? 1 : 0;
  let digits = 0;
  let decimalPointSeen = false;
  for (; index < value.length; index += 1) {
    const character = value[index];
    if (character === "." && !decimalPointSeen) {
      decimalPointSeen = true;
      continue;
    }
    if (character === undefined || character < "0" || character > "9") {
      return false;
    }
    digits += 1;
  }
  return digits > 0;
}

function isSha256(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
}

function isUuidV4(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(
      value,
    )
  );
}

function isBoundedString(value: unknown, maximum: number): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= maximum;
}

function isNonnegativeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && typeof value === "number" && value >= 0;
}

function isPositiveInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && typeof value === "number" && value > 0;
}

function isIntegerBetween(value: unknown, minimum: number, maximum: number): value is number {
  return (
    typeof value === "number" &&
    Number.isSafeInteger(value) &&
    value >= minimum &&
    value <= maximum
  );
}

function isNullableNonnegativeInteger(value: unknown): boolean {
  return value === null || isNonnegativeInteger(value);
}

function isNullablePositiveInteger(value: unknown): boolean {
  return value === null || isPositiveInteger(value);
}

function isNullableInteger(value: unknown): boolean {
  return value === null || (typeof value === "number" && Number.isSafeInteger(value));
}

function isShareSymbol(value: unknown): value is string {
  return typeof value === "string" && /^\d{6}\.(?:BJ|SH|SZ)$/.test(value);
}

function isSafeSequence(value: unknown): value is number {
  return isNonnegativeInteger(value) && value <= MAX_SEQUENCE;
}
