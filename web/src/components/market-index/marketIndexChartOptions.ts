import type { MarketIndexBarView } from "../../api/generated";

export interface IndexAxisBounds {
  readonly maximum: number;
  readonly minimum: number;
}

export interface MarketIndexChartPoint {
  readonly at: string;
  readonly value: number;
}

export type MarketIndexDirection = "down" | "flat" | "up";

const directionColors: Readonly<Record<MarketIndexDirection, string>> = Object.freeze({
  down: "#67b7a5",
  flat: "#eef1e8",
  up: "#e45d43",
});

const openingBucketAt = /^(\d{4}-\d{2}-\d{2})T09:35:00(?:\.\d{1,6})?\+08:00$/;

export function buildMarketIndexChartPoints(
  bars: readonly MarketIndexBarView[],
): readonly MarketIndexChartPoint[] {
  const points = bars.flatMap((bar) => {
    const value = Number(bar.closePoints);
    return Number.isFinite(value) ? [{ at: bar.barAt, value }] : [];
  });
  const firstBar = bars[0];
  if (firstBar === undefined || !Number.isFinite(Number(firstBar.closePoints))) {
    return points;
  }
  const openingMatch = openingBucketAt.exec(firstBar.barAt);
  const openingValue = Number(firstBar.openPoints);
  if (openingMatch === null || !Number.isFinite(openingValue)) return points;

  return [
    { at: `${openingMatch[1]}T09:30:00+08:00`, value: openingValue },
    ...points,
  ];
}

export function marketIndexDirection(
  sessionChangeRatio: string | null | undefined,
): MarketIndexDirection {
  return marketIndexValueDirection(sessionChangeRatio, 0);
}

export function marketIndexDirectionColor(
  sessionChangeRatio: string | null | undefined,
): string {
  return directionColors[marketIndexDirection(sessionChangeRatio)];
}

export function marketIndexShowSymbol(pointCount: number): boolean {
  return pointCount === 1;
}

export function marketIndexValueDirection(
  value: string | number | null | undefined,
  reference: string | number | null | undefined,
): MarketIndexDirection {
  if (value === null || value === undefined || reference === null || reference === undefined) {
    return "flat";
  }
  const numericValue = Number(value);
  const numericReference = Number(reference);
  if (!Number.isFinite(numericValue) || !Number.isFinite(numericReference)) return "flat";
  if (numericValue === numericReference) return "flat";
  return numericValue > numericReference ? "up" : "down";
}

export function calculateIndexAxisBounds(
  values: readonly number[],
  priorClose: number | null,
): IndexAxisBounds | null {
  const finiteValues = values.filter(Number.isFinite);
  if (priorClose !== null && Number.isFinite(priorClose)) finiteValues.push(priorClose);
  if (finiteValues.length === 0) return null;

  const minimum = Math.min(...finiteValues);
  const maximum = Math.max(...finiteValues);
  const span = maximum - minimum;
  const reference = Math.max(Math.abs(minimum), Math.abs(maximum), 1);
  const padding = Math.max(span * 0.08, reference * 0.001);

  return Object.freeze({ maximum: maximum + padding, minimum: minimum - padding });
}
