export interface IndexAxisBounds {
  readonly maximum: number;
  readonly minimum: number;
}

export type MarketIndexDirection = "down" | "flat" | "up";

const directionColors: Readonly<Record<MarketIndexDirection, string>> = Object.freeze({
  down: "#67b7a5",
  flat: "#eef1e8",
  up: "#e45d43",
});

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
