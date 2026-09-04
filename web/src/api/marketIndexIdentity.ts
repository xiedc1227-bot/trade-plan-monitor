import type { Board, MarketIndexCode } from "./generated";

interface CanonicalMarketIndexIdentity {
  readonly board: Board;
  readonly displayName: string;
}

const canonicalMarketIndexIdentities: Readonly<
  Record<MarketIndexCode, CanonicalMarketIndexIdentity>
> = Object.freeze({
  "000001.SH": Object.freeze({ board: "SSE_MAIN", displayName: "上证指数" }),
  "399001.SZ": Object.freeze({ board: "SZSE_MAIN", displayName: "深证成指" }),
  "399006.SZ": Object.freeze({ board: "CHINEXT", displayName: "创业板指" }),
  "000688.SH": Object.freeze({ board: "STAR_MARKET", displayName: "科创50" }),
  "899050.BJ": Object.freeze({ board: "BSE", displayName: "北证50" }),
});

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
