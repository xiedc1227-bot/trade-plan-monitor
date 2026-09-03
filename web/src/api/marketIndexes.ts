import type {
  MarketIndexBarPage,
  MarketIndexCode,
  MarketIndexInterval,
} from "./generated";
import { isShanghaiDateTime, shanghaiDateTimeKey } from "./shanghaiTime";
import { ApiClientError, invalidResponse, requestJson } from "./transport";

export interface MarketIndexHistoryQuery {
  cursor?: string;
  endAt: string;
  indexCode: MarketIndexCode;
  interval: MarketIndexInterval;
  limit: number;
  startAt: string;
}

export interface MarketIndexApi {
  getBars(
    query: Readonly<MarketIndexHistoryQuery>,
    options?: { signal?: AbortSignal },
  ): Promise<MarketIndexBarPage>;
}

const indexCodes = new Set<MarketIndexCode>([
  "000001.SH",
  "399001.SZ",
  "399006.SZ",
  "000688.SH",
  "899050.BJ",
]);
const intervals = new Set<MarketIndexInterval>(["FIVE_MINUTE", "OFFICIAL_DAILY"]);

export function createMarketIndexApi(
  fetchImplementation: typeof fetch = globalThis.fetch.bind(globalThis),
): MarketIndexApi {
  return Object.freeze({
    async getBars(
      query: Readonly<MarketIndexHistoryQuery>,
      options?: { signal?: AbortSignal },
    ) {
      requireQuery(query);
      const parameters = new URLSearchParams({
        endAt: query.endAt,
        interval: query.interval,
        limit: String(query.limit),
        startAt: query.startAt,
      });
      if (query.cursor !== undefined) {
        parameters.set("cursor", query.cursor);
      }
      const request: RequestInit = {
        headers: { Accept: "application/json" },
        method: "GET",
      };
      if (options?.signal !== undefined) {
        request.signal = options.signal;
      }
      const { body, status } = await requestJson(
        fetchImplementation,
        `/api/v1/market-indexes/${encodeURIComponent(query.indexCode)}/bars?${parameters.toString()}`,
        request,
      );
      try {
        if (!isMarketIndexBarPage(body, query)) {
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

function requireQuery(query: Readonly<MarketIndexHistoryQuery>): void {
  if (
    !indexCodes.has(query.indexCode) ||
    !intervals.has(query.interval) ||
    !isShanghaiDateTime(query.startAt) ||
    !isShanghaiDateTime(query.endAt) ||
    shanghaiDateTimeKey(query.startAt) > shanghaiDateTimeKey(query.endAt) ||
    !Number.isSafeInteger(query.limit) ||
    query.limit < 1 ||
    query.limit > 2_000 ||
    (query.cursor !== undefined && !isCursor(query.cursor))
  ) {
    throw new RangeError("market-index history query is invalid");
  }
}

function isMarketIndexBarPage(
  value: unknown,
  query: Readonly<MarketIndexHistoryQuery>,
): value is MarketIndexBarPage {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["hasMore", "items", "limit", "nextCursor", "snapshotHash"]) ||
    value.limit !== query.limit ||
    typeof value.hasMore !== "boolean" ||
    !isSha256(value.snapshotHash) ||
    !Array.isArray(value.items) ||
    value.items.length > query.limit ||
    !value.items.every((item) => isMarketIndexBar(item, query)) ||
    !(
      (value.hasMore && isCursor(value.nextCursor)) ||
      (!value.hasMore && value.nextCursor === null)
    )
  ) {
    return false;
  }
  const identities = value.items.map((item) => (item as Record<string, unknown>).barAt);
  return identities.every(
    (identity, index) => index === 0 || String(identities[index - 1]) < String(identity),
  );
}

function isMarketIndexBar(
  value: unknown,
  query: Readonly<MarketIndexHistoryQuery>,
): boolean {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      "amount",
      "barAt",
      "closePoints",
      "highPoints",
      "indexCode",
      "interval",
      "lowPoints",
      "observedAt",
      "openPoints",
      "providerRevision",
      "sourceKind",
      "volume",
    ]) &&
    value.indexCode === query.indexCode &&
    value.interval === query.interval &&
    isShanghaiDateTime(value.barAt) &&
    shanghaiDateTimeKey(value.barAt) >= shanghaiDateTimeKey(query.startAt) &&
    shanghaiDateTimeKey(value.barAt) <= shanghaiDateTimeKey(query.endAt) &&
    isShanghaiDateTime(value.observedAt) &&
    isDecimal(value.openPoints) &&
    isDecimal(value.highPoints) &&
    isDecimal(value.lowPoints) &&
    isDecimal(value.closePoints) &&
    (value.volume === null || isDecimal(value.volume)) &&
    (value.amount === null || isDecimal(value.amount)) &&
    Number.isSafeInteger(value.providerRevision) &&
    typeof value.providerRevision === "number" &&
    value.providerRevision > 0 &&
    (value.sourceKind === "PROVISIONAL" || value.sourceKind === "OFFICIAL")
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key));
}

function isDecimal(value: unknown): value is string {
  return typeof value === "string" && /^[+-]?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(value);
}

function isSha256(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
}

function isCursor(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length <= 512 &&
    /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(value)
  );
}
