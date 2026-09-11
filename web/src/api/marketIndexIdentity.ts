import type { Board, MarketIndexCode } from "./generated";

export interface CanonicalMarketIndexIdentity {
  readonly board: Board;
  readonly displayName: string;
}

const canonicalMarketIndexIdentities: Readonly<
  Record<MarketIndexCode, CanonicalMarketIndexIdentity>
> = Object.freeze({
  "000001.SH": Object.freeze({ board: "SSE_MAIN", displayName: "上证指数" }),
  "399001.SZ": Object.freeze({ board: "SZSE_MAIN", displayName: "深证成指" }),
  "399107.SZ": Object.freeze({ board: "SZSE_MAIN", displayName: "深证A指" }),
  "399006.SZ": Object.freeze({ board: "CHINEXT", displayName: "创业板指" }),
  "000688.SH": Object.freeze({ board: "STAR_MARKET", displayName: "科创50" }),
  "899050.BJ": Object.freeze({ board: "BSE", displayName: "北证50" }),
});

export const dashboardMarketIndexCodes = Object.freeze([
  "000001.SH",
  "399001.SZ",
  "399006.SZ",
  "000688.SH",
] satisfies readonly MarketIndexCode[]);

export const dashboardMarketIndexIdentities = Object.freeze(
  dashboardMarketIndexCodes.map((indexCode) =>
    Object.freeze({ indexCode, ...canonicalMarketIndexIdentities[indexCode] }),
  ),
);

export function isCanonicalMarketIndexIdentity(value: unknown): boolean {
  if (
    !isRecord(value) ||
    typeof value.indexCode !== "string" ||
    value.mappingVersion !== "board-index-map-v1"
  ) {
    return false;
  }
  const identity = canonicalMarketIndexIdentities[value.indexCode as MarketIndexCode];
  return (
    identity !== undefined &&
    value.board === identity.board &&
    value.displayName === identity.displayName
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
