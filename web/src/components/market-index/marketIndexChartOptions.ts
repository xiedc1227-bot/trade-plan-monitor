export interface IndexAxisBounds {
  readonly maximum: number;
  readonly minimum: number;
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
