const SHANGHAI_DATETIME_PATTERN =
  /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?\+08:00$/;
const FIXED_SHANGHAI_DATETIME_PATTERN =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+08:00$/;
const CALENDAR_DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;
const EPOCH_ORDINAL_DAY = 719_162n;
const SHANGHAI_OFFSET_HOURS = 8;
const MICROSECONDS_PER_SECOND = 1_000_000n;

export interface ParsedShanghaiDateTime {
  readonly canonical: string;
  readonly epochMicroseconds: bigint;
}

export function parseShanghaiDateTime(value: unknown): ParsedShanghaiDateTime | null {
  if (typeof value !== "string") {
    return null;
  }
  const match = SHANGHAI_DATETIME_PATTERN.exec(value);
  if (match === null) {
    return null;
  }
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6]);
  if (
    !isGregorianDate(year, month, day) ||
    hour > 23 ||
    minute > 59 ||
    second > 59
  ) {
    return null;
  }

  const fraction = (match[7] ?? "").padEnd(6, "0");
  const ordinalDay = daysBeforeYear(year) + BigInt(daysBeforeMonth(year, month) + day - 1);
  const epochSeconds =
    (((ordinalDay - EPOCH_ORDINAL_DAY) * 24n + BigInt(hour - SHANGHAI_OFFSET_HOURS)) *
      60n +
      BigInt(minute)) *
      60n +
    BigInt(second);
  return Object.freeze({
    canonical: `${match[1]}-${match[2]}-${match[3]}T${match[4]}:${match[5]}:${match[6]}.${fraction}+08:00`,
    epochMicroseconds: epochSeconds * MICROSECONDS_PER_SECOND + BigInt(fraction),
  });
}

export function parseShanghaiResponseDateTime(
  value: unknown,
): ParsedShanghaiDateTime | null {
  if (typeof value !== "string" || !FIXED_SHANGHAI_DATETIME_PATTERN.test(value)) {
    return null;
  }
  return parseShanghaiDateTime(value);
}

export function normalizeShanghaiDateTime(value: unknown): string | null {
  return parseShanghaiDateTime(value)?.canonical ?? null;
}

export function isShanghaiDateTime(value: unknown): value is string {
  return parseShanghaiDateTime(value) !== null;
}

export function isCanonicalShanghaiDateTime(value: unknown): value is string {
  return parseShanghaiResponseDateTime(value) !== null;
}

export function shanghaiDateTimeKey(value: unknown): bigint {
  const parsed = parseShanghaiDateTime(value);
  if (parsed === null) {
    throw new RangeError("invalid Shanghai datetime");
  }
  return parsed.epochMicroseconds;
}

export function isCalendarDate(value: unknown): value is string {
  if (typeof value !== "string") {
    return false;
  }
  const match = CALENDAR_DATE_PATTERN.exec(value);
  return (
    match !== null &&
    isGregorianDate(Number(match[1]), Number(match[2]), Number(match[3]))
  );
}

function isGregorianDate(year: number, month: number, day: number): boolean {
  if (year < 1 || month < 1 || month > 12 || day < 1) {
    return false;
  }
  const days = [31, isLeapYear(year) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return day <= (days[month - 1] ?? 0);
}

function isLeapYear(year: number): boolean {
  return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
}

function daysBeforeYear(year: number): bigint {
  const priorYear = BigInt(year - 1);
  return 365n * priorYear + priorYear / 4n - priorYear / 100n + priorYear / 400n;
}

function daysBeforeMonth(year: number, month: number): number {
  const days = [
    0,
    31,
    isLeapYear(year) ? 60 : 59,
    isLeapYear(year) ? 91 : 90,
    isLeapYear(year) ? 121 : 120,
    isLeapYear(year) ? 152 : 151,
    isLeapYear(year) ? 182 : 181,
    isLeapYear(year) ? 213 : 212,
    isLeapYear(year) ? 244 : 243,
    isLeapYear(year) ? 274 : 273,
    isLeapYear(year) ? 305 : 304,
    isLeapYear(year) ? 335 : 334,
  ];
  return days[month - 1] ?? 0;
}
