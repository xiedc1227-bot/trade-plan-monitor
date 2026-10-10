import type { MarketIndexOverviewResponse, MarketIndexCode, MarketIndexOverviewItem, MarketIndexSnapshotView } from "./generated";
import { dashboardMarketIndexIdentities } from "./marketIndexIdentity";
import { isMarketIndexBar } from "./marketIndexes";
import { isShanghaiDateTime } from "./shanghaiTime";
import { invalidResponse, requestJson } from "./transport";

export interface MarketIndexOverviewApi {
  getOverview(options?: { signal?: AbortSignal }): Promise<MarketIndexOverviewResponse>;
}

export function overviewItemSnapshot(item: MarketIndexOverviewItem | null): MarketIndexSnapshotView | null {
  if (!item?.data) return null;
  return { board: item.board, indexCode: item.indexCode, displayName: item.displayName,
    mappingVersion: "board-index-map-v1", snapshotHash: item.data.snapshotHash,
    observedAt: item.data.observedAt, completedBucketAt: item.data.completedBucketAt,
    closePoints: item.data.closePoints, priorClosePoints: item.data.priorClosePoints,
    sessionChangeRatio: item.data.sessionChangeRatio, revision: 1, mappedSymbolCount: 0,
    indicatorFacts: [], issues: [], health: item.dataStatus === "CURRENT" ? "LIVE" : "STALE" };
}

export function createMarketIndexOverviewApi(fetchImplementation: typeof fetch): MarketIndexOverviewApi {
  return { async getOverview(options) {
    const { body, status } = await requestJson(fetchImplementation, "/api/v1/market-indexes/overview", {
      method: "GET", headers: { Accept: "application/json" }, cache: "no-store",
      ...(options?.signal ? { signal: options.signal } : {}),
    });
    if (!isMarketIndexOverview(body) || new TextEncoder().encode(JSON.stringify(body)).length > 512 * 1024) throw invalidResponse(status);
    return body;
  } };
}

const issues = new Set(["MISSING_FIVE_MINUTE_BAR", "MISSING_OFFICIAL_DAILY_BAR", "INSUFFICIENT_HISTORY", "STALE_DATA", "DUPLICATE_IDENTITY", "GAPPED_SERIES", "INDEX_IDENTITY_MISMATCH", "FUTURE_DATA", "INVALID_TIMESTAMP", "NONCANONICAL_DECIMAL", "INVALID_OHLC", "FORMULA_MISMATCH", "PROVIDER_UNAVAILABLE"]);
function record(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null && !Array.isArray(value); }
function keys(value: Record<string, unknown>, expected: string[]): boolean { return Object.keys(value).length === expected.length && expected.every(key => Object.hasOwn(value, key)); }
function decimal(value: unknown): value is string { return typeof value === "string" && /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(value) && Number.isFinite(Number(value)); }
function date(value: unknown): boolean { return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) && isShanghaiDateTime(`${value}T00:00:00+08:00`); }
function nullableAt(value: unknown): boolean { return value === null || isShanghaiDateTime(value); }

export function isMarketIndexOverview(value: unknown): value is MarketIndexOverviewResponse {
  if (!record(value) || !keys(value, ["schemaVersion", "observedAt", "runtimeGeneration", "sequence", "marketSession", "indexes", "marketTurnover"])
    || value.schemaVersion !== 1 || !isShanghaiDateTime(value.observedAt)
    || !(value.runtimeGeneration === null || typeof value.runtimeGeneration === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value.runtimeGeneration))
    || typeof value.sequence !== "number" || !Number.isSafeInteger(value.sequence) || value.sequence < 0
    || !record(value.marketSession) || !Array.isArray(value.indexes) || value.indexes.length !== 4) return false;
  const session = value.marketSession;
  if (!keys(session, ["phase", "calendarStatus", "sessionDate", "displayTradeDate", "expectedBucketAt"])
    || !["PREOPEN", "OPEN", "BREAK", "CLOSED", "UNKNOWN"].includes(String(session.phase))
    || !["KNOWN", "UNKNOWN"].includes(String(session.calendarStatus)) || !date(session.sessionDate)
    || !(session.displayTradeDate === null || date(session.displayTradeDate)) || !nullableAt(session.expectedBucketAt)) return false;
  for (const [i, item] of value.indexes.entries()) {
    const identity = dashboardMarketIndexIdentities[i];
    if (!identity || !record(item) || !keys(item, ["indexCode", "displayName", "board", "dataStatus", "data", "latestAcquisition"])
      || item.indexCode !== identity.indexCode || item.displayName !== identity.displayName || item.board !== identity.board
      || !["CURRENT", "INCOMPLETE", "CACHED", "EMPTY", "UNVERIFIED"].includes(String(item.dataStatus))) return false;
    const data = item.data;
    if (data === null) { if (item.dataStatus !== "EMPTY") return false; }
    else {
      if (!record(data) || !keys(data, ["snapshotHash", "observedAt", "completedBucketAt", "sourceKind", "closePoints", "priorClosePoints", "sessionChangeRatio", "highPoints", "lowPoints", "amount", "bars"])
        || typeof data.snapshotHash !== "string" || !/^[0-9a-f]{64}$/.test(data.snapshotHash)
        || !isShanghaiDateTime(data.observedAt) || !isShanghaiDateTime(data.completedBucketAt)
        || !["PROVISIONAL", "OFFICIAL"].includes(String(data.sourceKind))
        || ![data.closePoints, data.highPoints, data.lowPoints].every(v => decimal(v) && Number(v) > 0)
        || !(data.priorClosePoints === null || decimal(data.priorClosePoints) && Number(data.priorClosePoints) > 0)
        || !(data.sessionChangeRatio === null || decimal(data.sessionChangeRatio)) || !(data.amount === null || decimal(data.amount) && Number(data.amount) >= 0)
        || !Array.isArray(data.bars) || data.bars.length < 1 || data.bars.length > 48) return false;
      const query = { indexCode: item.indexCode as MarketIndexCode, interval: "FIVE_MINUTE" as const, startAt: `${session.displayTradeDate}T09:35:00+08:00`, endAt: `${session.displayTradeDate}T15:00:00+08:00`, limit: 48 };
      if (!data.bars.every(bar => isMarketIndexBar(bar, query))) return false;
      const bars = data.bars as Record<string, unknown>[];
      if (!bars.every((bar, n) => n === 0 || String(bars[n - 1]?.barAt) < String(bar.barAt))
        || bars.at(-1)?.barAt !== data.completedBucketAt || bars.at(-1)?.closePoints !== data.closePoints) return false;
    }
    const acquisition = item.latestAcquisition;
    if (acquisition !== null && (!record(acquisition) || !keys(acquisition, ["decisionCutoff", "observedAt", "health", "issues", "nextRetryAt"])
      || !isShanghaiDateTime(acquisition.decisionCutoff) || !isShanghaiDateTime(acquisition.observedAt) || !nullableAt(acquisition.nextRetryAt)
      || !["LIVE", "STALE", "GAPPED", "BLOCKED"].includes(String(acquisition.health)) || !Array.isArray(acquisition.issues)
      || acquisition.issues.length > 16 || !acquisition.issues.every(issue => issues.has(String(issue))))) return false;
  }
  const turnover = value.marketTurnover;
  if (turnover !== null && (!record(turnover) || !keys(turnover, ["currentAmount", "previousAmount", "changeAmount", "estimatedFullDayAmount", "completedBucketAt", "estimateMethod", "benchmarkCodes"])
    || ![turnover.currentAmount, turnover.previousAmount, turnover.changeAmount, turnover.estimatedFullDayAmount].every(decimal)
    || !isShanghaiDateTime(turnover.completedBucketAt) || turnover.estimateMethod !== "LINEAR_COMPLETED_FIVE_MINUTE_BUCKETS"
    || JSON.stringify(turnover.benchmarkCodes) !== '["000001.SH","399107.SZ"]')) return false;
  return true;
}
