import type {
  BarInterval,
  BarPage,
  IndexConditionEvidenceView,
  SymbolDetailResponse,
  SymbolDetailUnavailableResponse,
  SymbolEventPage,
  SymbolReferenceMarketView,
} from "./generated";
import { isAuthoritativeDecision } from "./client";
import { isCanonicalMarketIndexIdentity } from "./marketIndexIdentity";
import {
  isCalendarDate as isValidCalendarDate,
  isShanghaiDateTime,
  shanghaiDateTimeKey,
} from "./shanghaiTime";
import { invalidResponse, requestJson } from "./transport";

export interface SymbolHistoryQuery {
  readonly endAt: string;
  readonly interval?: BarInterval;
  readonly limit?: number;
  readonly offset?: number;
  readonly startAt: string;
}

export interface SymbolApi {
  getBars(
    symbol: string,
    query: Readonly<SymbolHistoryQuery>,
    options?: { signal?: AbortSignal },
  ): Promise<BarPage>;
  getEvents(
    symbol: string,
    query: Readonly<Omit<SymbolHistoryQuery, "interval">>,
    options?: { signal?: AbortSignal },
  ): Promise<SymbolEventPage>;
  getSymbol(
    symbol: string,
    options?: { signal?: AbortSignal },
  ): Promise<SymbolDetailResponse | SymbolDetailUnavailableResponse>;
}

const intervals = new Set<BarInterval>(["ONE_MINUTE", "FIVE_MINUTES"]);
const eventTypes = new Set(["DECISION", "EPISODE", "RISK", "ALERT", "HEALTH"]);
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
const indexConditionTypes = new Set([
  "INDEX_CLOSE_GTE_MA",
  "INDEX_CLOSE_LTE_MA",
  "INDEX_MA_NON_DECREASING",
  "INDEX_MA_NON_INCREASING",
  "INDEX_RETURN_GTE",
  "INDEX_RETURN_LTE",
]);
const indexMissingInputs = new Set([
  "INDEX_SNAPSHOT",
  "INDEX_IDENTITY",
  "INDEX_CUTOFF",
  "INDEX_HEALTH",
  "INDEX_FACT",
  "INDEX_HISTORY",
  "INDEX_FORMULA",
]);
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
export function createSymbolApi(
  fetchImplementation: typeof fetch = globalThis.fetch.bind(globalThis),
): SymbolApi {
  return Object.freeze({
    async getSymbol(symbol: string, options?: { signal?: AbortSignal }) {
      requireSymbol(symbol);
      const { body, status } = await requestJson(
        fetchImplementation,
        `/api/v1/symbols/${encodeURIComponent(symbol)}`,
        requestOptions(options),
      );
      if (!isSymbolDetail(body, symbol) && !isSymbolDetailUnavailableResponse(body, symbol)) {
        throw invalidResponse(status);
      }
      return body;
    },

    async getBars(symbol: string, query: Readonly<SymbolHistoryQuery>, options?: { signal?: AbortSignal }) {
      requireSymbol(symbol);
      const normalized = normalizeBarsQuery(query);
      const { body, status } = await requestJson(
        fetchImplementation,
        `/api/v1/symbols/${encodeURIComponent(symbol)}/bars?${historySearch(normalized).toString()}`,
        requestOptions(options),
      );
      if (!isBarPage(body, symbol, normalized)) throw invalidResponse(status);
      return body;
    },

    async getEvents(
      symbol: string,
      query: Readonly<Omit<SymbolHistoryQuery, "interval">>,
      options?: { signal?: AbortSignal },
    ) {
      requireSymbol(symbol);
      const normalized = normalizeEventsQuery(query);
      const { body, status } = await requestJson(
        fetchImplementation,
        `/api/v1/symbols/${encodeURIComponent(symbol)}/events?${historySearch(normalized).toString()}`,
        requestOptions(options),
      );
      if (!isEventPage(body, symbol, normalized)) throw invalidResponse(status);
      return body;
    },
  });
}

export function isSymbolDetailUnavailableResponse(
  value: unknown,
  symbol: string,
): value is SymbolDetailUnavailableResponse {
  return (
    isRecord(value) &&
    hasExactKeys(value, ["availability", "observedAt", "reason", "sequence", "symbol"]) &&
    value.availability === "UNAVAILABLE" &&
    isShanghaiDateTime(value.observedAt) &&
    isNonnegativeInteger(value.sequence) &&
    value.symbol === symbol &&
    (value.reason === "NO_ACTIVE_PLAN" || value.reason === "AWAITING_FIRST_EVALUATION")
  );
}

function requestOptions(options?: { signal?: AbortSignal }): RequestInit {
  return {
    headers: { Accept: "application/json" },
    method: "GET",
    ...(options?.signal === undefined ? {} : { signal: options.signal }),
  };
}

function normalizeBarsQuery(query: Readonly<SymbolHistoryQuery>): Required<SymbolHistoryQuery> {
  const normalized = {
    endAt: query.endAt,
    interval: query.interval ?? "FIVE_MINUTES",
    limit: query.limit ?? 100,
    offset: query.offset ?? 0,
    startAt: query.startAt,
  };
  requireHistoryQuery(normalized);
  return Object.freeze(normalized);
}

function normalizeEventsQuery(
  query: Readonly<Omit<SymbolHistoryQuery, "interval">>,
): Required<Omit<SymbolHistoryQuery, "interval">> {
  const normalized = {
    endAt: query.endAt,
    limit: query.limit ?? 100,
    offset: query.offset ?? 0,
    startAt: query.startAt,
  };
  requireHistoryQuery(normalized);
  return Object.freeze(normalized);
}

function historySearch(query: Readonly<Record<string, string | number>>): URLSearchParams {
  const search = new URLSearchParams();
  for (const key of ["startAt", "endAt", "interval", "offset", "limit"] as const) {
    const value = query[key];
    if (value !== undefined) search.set(key, String(value));
  }
  return search;
}

function requireSymbol(symbol: string): void {
  if (!isShareSymbol(symbol)) throw new RangeError("symbol is invalid");
}

function requireHistoryQuery(query: Readonly<Record<string, unknown>>): void {
  if (
    !isShanghaiDateTime(query.startAt) ||
    !isShanghaiDateTime(query.endAt) ||
    shanghaiDateTimeKey(query.startAt) > shanghaiDateTimeKey(query.endAt) ||
    !isPageOffset(query.offset) ||
    !isPageLimit(query.limit) ||
    (query.interval !== undefined && !intervals.has(query.interval as BarInterval))
  ) {
    throw new RangeError("symbol history query is invalid");
  }
}

function isSymbolDetail(value: unknown, symbol: string): value is SymbolDetailResponse {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, ["indexConditionEvidence", "positionLots", "referenceMarket", "summary"]) ||
    !hasKeys(value, ["summary"]) ||
    !isSymbolSummary(value.summary, symbol) ||
    !(value.positionLots === undefined ||
      (Array.isArray(value.positionLots) &&
        value.positionLots.length <= 200 &&
        value.positionLots.every(isPositionLot)))
  ) {
    return false;
  }

  const referenceMarket = value.referenceMarket ?? null;
  const summaryReferenceMarket = value.summary.referenceMarket ?? null;
  if (
    !(referenceMarket === null || isSymbolReferenceMarket(referenceMarket)) ||
    !sameReferenceMarket(referenceMarket, summaryReferenceMarket)
  ) {
    return false;
  }

  const evidence = value.indexConditionEvidence === undefined ? [] : value.indexConditionEvidence;
  if (
    !Array.isArray(evidence) ||
    evidence.length > 50 ||
    !evidence.every((item) => isIndexConditionEvidence(item, referenceMarket))
  ) {
    return false;
  }
  return isSortedUnique(evidence.map((item) => item.planPath));
}

function isSymbolSummary(value: unknown, symbol: string): boolean {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, [
      "connected",
      "decision",
      "name",
      "observedAt",
      "referenceMarket",
      "riskDistanceFen",
      "satisfiedConditionCount",
      "symbol",
      "totalConditionCount",
    ]) &&
    hasKeys(value, ["connected", "decision", "name", "observedAt", "symbol"]) &&
    value.symbol === symbol &&
    typeof value.connected === "boolean" &&
    typeof value.name === "string" &&
    value.name.length <= 128 &&
    isShanghaiDateTime(value.observedAt) &&
    isRecord(value.decision) &&
    isAuthoritativeDecision(value.decision) &&
    value.decision.symbol === symbol &&
    (value.referenceMarket === undefined ||
      value.referenceMarket === null ||
      isSymbolReferenceMarket(value.referenceMarket))
  );
}

function isSymbolReferenceMarket(value: unknown): value is SymbolReferenceMarketView {
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
    value.mappingVersion !== "board-index-map-v1" ||
    !(value.snapshotHash === null || isSha256(value.snapshotHash)) ||
    !(value.dataAt === null || isShanghaiDateTime(value.dataAt)) ||
    (value.snapshotHash === null) !== (value.dataAt === null) ||
    !(typeof value.health === "string" && marketIndexHealth.has(value.health)) ||
    !Array.isArray(value.issues) ||
    value.issues.length > 16 ||
    new Set(value.issues).size !== value.issues.length ||
    !value.issues.every((issue) => typeof issue === "string" && marketIndexIssues.has(issue))
  ) {
    return false;
  }
  return isIndexConditionProgress(value.conditionProgress);
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
  return BigInt(value.satisfied) + BigInt(value.unsatisfied) + BigInt(value.missing) === BigInt(value.total);
}

function sameReferenceMarket(left: unknown, right: unknown): boolean {
  if (left === null || right === null) return left === right;
  if (!isSymbolReferenceMarket(left) || !isSymbolReferenceMarket(right)) return false;
  return (
    left.indexCode === right.indexCode &&
    left.displayName === right.displayName &&
    left.board === right.board &&
    left.mappingVersion === right.mappingVersion &&
    left.snapshotHash === right.snapshotHash &&
    left.dataAt === right.dataAt &&
    left.health === right.health &&
    left.issues.length === right.issues.length &&
    left.issues.every((issue, index) => issue === right.issues[index]) &&
    left.conditionProgress.satisfied === right.conditionProgress.satisfied &&
    left.conditionProgress.unsatisfied === right.conditionProgress.unsatisfied &&
    left.conditionProgress.missing === right.conditionProgress.missing &&
    left.conditionProgress.total === right.conditionProgress.total
  );
}

function isIndexConditionEvidence(
  value: unknown,
  referenceMarket: SymbolReferenceMarketView | null,
): value is IndexConditionEvidenceView {
  if (
    referenceMarket === null ||
    !isRecord(value) ||
    !hasOnlyKeys(value, [
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
    ]) ||
    !hasKeys(value, [
      "actualValue",
      "comparisonValue",
      "conditionType",
      "dataCutoff",
      "decisionCutoff",
      "formulaDefinitionHash",
      "formulaId",
      "indexCode",
      "mappingVersion",
      "outcome",
      "planPath",
      "snapshotHash",
      "unit",
    ])
  ) {
    return false;
  }
  const parameters = value.parameters === undefined ? [] : value.parameters;
  const missingInputs = value.missingInputs === undefined ? [] : value.missingInputs;
  if (
    !isIndexPlanPath(value.planPath) ||
    !(typeof value.conditionType === "string" && indexConditionTypes.has(value.conditionType)) ||
    value.indexCode !== referenceMarket.indexCode ||
    value.mappingVersion !== referenceMarket.mappingVersion ||
    !(value.snapshotHash === null || isSha256(value.snapshotHash)) ||
    (value.snapshotHash !== null && value.snapshotHash !== referenceMarket.snapshotHash) ||
    !isShanghaiDateTime(value.decisionCutoff) ||
    !(value.dataCutoff === null || isShanghaiDateTime(value.dataCutoff)) ||
    (value.dataCutoff !== null && value.dataCutoff !== referenceMarket.dataAt) ||
    !(value.formulaId === "SMA" || value.formulaId === "SMA_LOOKBACK" || value.formulaId === "RETURN") ||
    !(value.formulaDefinitionHash === null || isSha256(value.formulaDefinitionHash)) ||
    !Array.isArray(parameters) ||
    parameters.length > 8 ||
    new Set(parameters.map((parameter) => isRecord(parameter) ? parameter.key : parameter)).size !==
      parameters.length ||
    !parameters.every(isIndexEvidenceParameter) ||
    !Array.isArray(missingInputs) ||
    missingInputs.length > 7 ||
    new Set(missingInputs).size !== missingInputs.length ||
    !missingInputs.every(
      (item) => typeof item === "string" && indexMissingInputs.has(item),
    ) ||
    !(value.unit === "POINTS" || value.unit === "RATIO") ||
    !(value.outcome === "SATISFIED" || value.outcome === "UNSATISFIED" || value.outcome === "MISSING_INPUT")
  ) {
    return false;
  }
  if (value.outcome === "MISSING_INPUT") {
    return missingInputs.length > 0 && value.actualValue === null && value.comparisonValue === null;
  }
  return (
    missingInputs.length === 0 &&
    isDecimal(value.actualValue) &&
    isDecimal(value.comparisonValue) &&
    value.snapshotHash !== null &&
    value.dataCutoff !== null &&
    value.formulaDefinitionHash !== null
  );
}

function isIndexEvidenceParameter(value: unknown): boolean {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["key", "unit", "value"]) ||
    typeof value.key !== "string" ||
    !/^[a-z][a-z0-9_]{0,63}$/.test(value.key) ||
    typeof value.unit !== "string" ||
    !evidenceUnits.has(value.unit)
  ) {
    return false;
  }
  if (value.unit === "BOOLEAN") return typeof value.value === "boolean";
  if (value.unit === "DATE") return isValidCalendarDate(value.value);
  if (value.unit === "DATETIME") return isShanghaiDateTime(value.value);
  if (value.unit === "CODE") return isStableCode(value.value);
  if (value.unit === "FEN" || value.unit === "BARS" || value.unit === "COUNT") {
    return typeof value.value === "number" && Number.isSafeInteger(value.value);
  }
  if (value.unit === "SHARES") {
    return (
      (typeof value.value === "number" && Number.isSafeInteger(value.value)) ||
      isDecimal(value.value)
    );
  }
  return isDecimal(value.value);
}

function isIndexPlanPath(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length >= 15 &&
    value.length <= 256 &&
    /^(?:entry|reduction|risk|blockers)\.condition(?:\.conditions\[[0-9]+\])*$/.test(value)
  );
}

function isSortedUnique(values: readonly string[]): boolean {
  return values.every((value, index) => {
    const previous = index === 0 ? undefined : values[index - 1];
    return previous === undefined || previous < value;
  });
}

function isPositionLot(value: unknown): boolean {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      "acquiredTradeDate",
      "bucket",
      "costFen",
      "lotId",
      "quantity",
      "remainingQuantity",
      "sellableQuantity",
    ]) &&
    typeof value.lotId === "string" &&
    value.lotId.length > 0 &&
    value.lotId.length <= 36 &&
    (value.bucket === "CORE" || value.bucket === "TACTICAL") &&
    isCalendarDate(value.acquiredTradeDate) &&
    isPositiveInteger(value.costFen) &&
    isBoardLot(value.quantity) &&
    isNonnegativeInteger(value.remainingQuantity) &&
    value.remainingQuantity <= value.quantity &&
    isNonnegativeInteger(value.sellableQuantity) &&
    value.sellableQuantity <= value.remainingQuantity
  );
}

function isBarPage(
  value: unknown,
  symbol: string,
  query: Readonly<Required<SymbolHistoryQuery>>,
): value is BarPage {
  return (
    isRecord(value) &&
    hasExactKeys(value, ["endAt", "items", "limit", "offset", "startAt", "total"]) &&
    value.startAt === query.startAt &&
    value.endAt === query.endAt &&
    value.offset === query.offset &&
    value.limit === query.limit &&
    isPageTotal(value.total) &&
    Array.isArray(value.items) &&
    value.items.length <= value.limit &&
    value.items.every((item) => isBar(item, symbol, query))
  );
}

function isBar(value: unknown, symbol: string, query: Readonly<Required<SymbolHistoryQuery>>): boolean {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      "amountYuan",
      "barEnd",
      "closeFen",
      "formulaVersion",
      "highFen",
      "interval",
      "lowFen",
      "openFen",
      "receivedAt",
      "symbol",
      "volumeShares",
    ]) &&
    value.symbol === symbol &&
    value.interval === query.interval &&
    isShanghaiDateTime(value.barEnd) &&
    shanghaiDateTimeKey(value.barEnd) >= shanghaiDateTimeKey(query.startAt) &&
    shanghaiDateTimeKey(value.barEnd) <= shanghaiDateTimeKey(query.endAt) &&
    isShanghaiDateTime(value.receivedAt) &&
    shanghaiDateTimeKey(value.receivedAt) >= shanghaiDateTimeKey(value.barEnd) &&
    isPositiveInteger(value.openFen) &&
    isPositiveInteger(value.highFen) &&
    isPositiveInteger(value.lowFen) &&
    isPositiveInteger(value.closeFen) &&
    value.lowFen <= value.openFen &&
    value.lowFen <= value.closeFen &&
    value.highFen >= value.openFen &&
    value.highFen >= value.closeFen &&
    isNonnegativeInteger(value.volumeShares) &&
    isDecimal(value.amountYuan) &&
    (value.formulaVersion === null ||
      (typeof value.formulaVersion === "string" && value.formulaVersion.length <= 64))
  );
}

function isEventPage(
  value: unknown,
  symbol: string,
  query: Readonly<Required<Omit<SymbolHistoryQuery, "interval">>>,
): value is SymbolEventPage {
  return (
    isRecord(value) &&
    hasExactKeys(value, ["endAt", "items", "limit", "offset", "startAt", "total"]) &&
    value.startAt === query.startAt &&
    value.endAt === query.endAt &&
    value.offset === query.offset &&
    value.limit === query.limit &&
    isPageTotal(value.total) &&
    Array.isArray(value.items) &&
    value.items.length <= value.limit &&
    value.items.every((item) => isEvent(item, symbol, query))
  );
}

function isEvent(
  value: unknown,
  symbol: string,
  query: Readonly<Required<Omit<SymbolHistoryQuery, "interval">>>,
): boolean {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      "eventId",
      "eventType",
      "messageText",
      "occurredAt",
      "resultHash",
      "sequence",
      "signalType",
      "symbol",
    ]) &&
    value.symbol === symbol &&
    typeof value.eventId === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(value.eventId) &&
    typeof value.eventType === "string" &&
    eventTypes.has(value.eventType) &&
    isShanghaiDateTime(value.occurredAt) &&
    shanghaiDateTimeKey(value.occurredAt) >= shanghaiDateTimeKey(query.startAt) &&
    shanghaiDateTimeKey(value.occurredAt) <= shanghaiDateTimeKey(query.endAt) &&
    isNonnegativeInteger(value.sequence) &&
    (value.messageText === null ||
      (typeof value.messageText === "string" && value.messageText.length > 0 && value.messageText.length <= 2_000)) &&
    (value.resultHash === null || isSha256(value.resultHash)) &&
    (value.signalType === null || (typeof value.signalType === "string" && signalTypes.has(value.signalType)))
  );
}

function isRecord(value: unknown): value is Record<string, any> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return keys.every((key) => Object.hasOwn(value, key));
}

function hasOnlyKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(value).every((key) => keys.includes(key));
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(value).length === keys.length && hasKeys(value, keys);
}

function isShareSymbol(value: unknown): value is string {
  return typeof value === "string" && /^\d{6}\.(?:BJ|SH|SZ)$/.test(value);
}

function isCalendarDate(value: unknown): boolean {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value);
}

function isDecimal(value: unknown): boolean {
  return typeof value === "string" && /^[+-]?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(value);
}

function isSha256(value: unknown): boolean {
  return typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
}

function isStableCode(value: unknown): value is string {
  return typeof value === "string" && /^[A-Z][A-Z0-9_]{0,63}$/.test(value);
}

function isNonnegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isPositiveInteger(value: unknown): value is number {
  return isNonnegativeInteger(value) && value > 0;
}

function isBoardLot(value: unknown): value is number {
  return isPositiveInteger(value) && value % 100 === 0;
}

function isPageOffset(value: unknown): value is number {
  return isNonnegativeInteger(value) && value <= 10_000;
}

function isPageLimit(value: unknown): value is number {
  return isPositiveInteger(value) && value <= 100;
}

function isPageTotal(value: unknown): value is number {
  return isNonnegativeInteger(value) && value <= 10_000;
}
