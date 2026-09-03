import type {
  BarInterval,
  BarPage,
  SymbolDetailResponse,
  SymbolEventPage,
} from "./generated";
import { isShanghaiDateTime, shanghaiDateTimeKey } from "./shanghaiTime";
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
  getSymbol(symbol: string, options?: { signal?: AbortSignal }): Promise<SymbolDetailResponse>;
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
      if (!isSymbolDetail(body, symbol)) throw invalidResponse(status);
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
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["indexConditionEvidence", "positionLots", "referenceMarket", "summary"]) &&
    hasKeys(value, ["summary"]) &&
    isSymbolSummary(value.summary, symbol) &&
    (value.positionLots === undefined ||
      (Array.isArray(value.positionLots) &&
        value.positionLots.length <= 200 &&
        value.positionLots.every(isPositionLot))) &&
    (value.indexConditionEvidence === undefined ||
      (Array.isArray(value.indexConditionEvidence) && value.indexConditionEvidence.length <= 50))
  );
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
    value.decision.symbol === symbol
  );
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
