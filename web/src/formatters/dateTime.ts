const OFFSET_DATE_TIME_PATTERN =
  /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

/**
 * Formats an offset-aware API timestamp for display without timezone conversion.
 * The original value must still be used for API calls, ordering and datetime attributes.
 */
export function formatDisplayDateTime(
  value: string | null | undefined,
  fallback = "—",
): string {
  const match = value?.match(OFFSET_DATE_TIME_PATTERN);
  return match === undefined || match === null ? fallback : `${match[1]} ${match[2]}`;
}

export function formatDisplayFactValue(value: unknown, unit: string): string {
  const text = String(value);
  return unit === "DATETIME" ? formatDisplayDateTime(text, text) : text;
}
