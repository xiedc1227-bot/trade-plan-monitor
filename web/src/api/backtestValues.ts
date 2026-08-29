const MAX_EXACT_TEXT_CHARACTERS = 4_096;
const FEN_TEXT_PATTERN = /^(?:0|-?[1-9][0-9]*)$/;
const DECIMAL_TEXT_PATTERN = /^(?:0|-?[1-9][0-9]*|-?(?:0|[1-9][0-9]*)\.[0-9]*[1-9])$/;
const RFC_4122_UUID_PATTERN =
  /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$/;
const LOT_KEY_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

type Comparison = -1 | 0 | 1;

interface DecimalParts {
  readonly fraction: string;
  readonly integer: string;
  readonly negative: boolean;
}

export function isFenText(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length <= MAX_EXACT_TEXT_CHARACTERS &&
    FEN_TEXT_PATTERN.test(value)
  );
}

export function parseFenText(value: unknown): bigint | null {
  return isFenText(value) ? BigInt(value) : null;
}

export function formatFenAsYuan(value: string | bigint): string {
  const parsed = typeof value === "bigint" ? value : parseFenText(value);
  if (parsed === null) {
    throw new RangeError("invalid FenText");
  }
  const negative = parsed < 0n;
  const magnitude = negative ? -parsed : parsed;
  const yuan = magnitude / 100n;
  const fen = (magnitude % 100n).toString().padStart(2, "0");
  return `${negative ? "-" : ""}${yuan.toString()}.${fen}`;
}

export function isDecimalText(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length <= MAX_EXACT_TEXT_CHARACTERS &&
    DECIMAL_TEXT_PATTERN.test(value)
  );
}

export function compareDecimalText(left: string, right: string): Comparison {
  if (!isDecimalText(left) || !isDecimalText(right)) {
    throw new RangeError("invalid DecimalText");
  }
  const leftParts = splitDecimal(left);
  const rightParts = splitDecimal(right);
  if (leftParts.negative !== rightParts.negative) {
    return leftParts.negative ? -1 : 1;
  }
  const magnitude = compareDecimalMagnitude(leftParts, rightParts);
  return leftParts.negative ? invertComparison(magnitude) : magnitude;
}

export function isRateText(value: unknown): value is string {
  return (
    isDecimalText(value) &&
    compareDecimalText(value, "0") >= 0 &&
    compareDecimalText(value, "1") <= 0
  );
}

export function isSlippageBpsText(value: unknown): value is string {
  return (
    isDecimalText(value) &&
    compareDecimalText(value, "0") >= 0 &&
    compareDecimalText(value, "10000") < 0
  );
}

export function isJavaScriptSafeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

export function isPositiveJavaScriptSafeInteger(value: unknown): value is number {
  return isJavaScriptSafeInteger(value) && value > 0;
}

export function isBoardLotQuantity(value: unknown): value is number {
  return isPositiveJavaScriptSafeInteger(value) && value % 100 === 0;
}

export function normalizeRfc4122Uuid(value: unknown): string | null {
  return typeof value === "string" && RFC_4122_UUID_PATTERN.test(value)
    ? value.toLowerCase()
    : null;
}

export function isLotKey(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length >= 1 &&
    value.length <= 64 &&
    LOT_KEY_PATTERN.test(value)
  );
}

function splitDecimal(value: string): DecimalParts {
  const negative = value.startsWith("-");
  const unsigned = negative ? value.slice(1) : value;
  const point = unsigned.indexOf(".");
  return {
    fraction: point === -1 ? "" : unsigned.slice(point + 1),
    integer: point === -1 ? unsigned : unsigned.slice(0, point),
    negative,
  };
}

function compareDecimalMagnitude(left: DecimalParts, right: DecimalParts): Comparison {
  if (left.integer.length !== right.integer.length) {
    return left.integer.length < right.integer.length ? -1 : 1;
  }
  if (left.integer !== right.integer) {
    return left.integer < right.integer ? -1 : 1;
  }
  const width = Math.max(left.fraction.length, right.fraction.length);
  const leftFraction = left.fraction.padEnd(width, "0");
  const rightFraction = right.fraction.padEnd(width, "0");
  if (leftFraction === rightFraction) {
    return 0;
  }
  return leftFraction < rightFraction ? -1 : 1;
}

function invertComparison(value: Comparison): Comparison {
  return value === 0 ? 0 : value === 1 ? -1 : 1;
}
