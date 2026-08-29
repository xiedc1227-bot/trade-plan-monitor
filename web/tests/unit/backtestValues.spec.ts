import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import {
  compareDecimalText,
  formatFenAsYuan,
  isBoardLotQuantity,
  isDecimalText,
  isFenText,
  isJavaScriptSafeInteger,
  isLotKey,
  isPositiveJavaScriptSafeInteger,
  isRateText,
  isSlippageBpsText,
  normalizeRfc4122Uuid,
  parseFenText,
} from "../../src/api/backtestValues";

describe("exact backtest values", () => {
  it.each(["0", "1", "-1", "9".repeat(4_096), `-${"9".repeat(4_095)}`])(
    "accepts canonical bounded FenText %s",
    (value) => {
      expect(isFenText(value)).toBe(true);
    },
  );

  it.each([1, "+1", "01", "-0", "1.0", " 1", "1 ", "9".repeat(4_097)])(
    "rejects non-canonical or oversized FenText %s",
    (value) => {
      expect(isFenText(value)).toBe(false);
    },
  );

  it("parses and formats FenText without losing values above Number.MAX_SAFE_INTEGER", () => {
    const value = "900719925474099312345";

    expect(parseFenText(value)).toBe(900719925474099312345n);
    expect(formatFenAsYuan(value)).toBe("9007199254740993123.45");
    expect(formatFenAsYuan(-1n)).toBe("-0.01");
    expect(formatFenAsYuan("0")).toBe("0.00");
  });

  it.each(["0", "1", "-1", "1.25", "-0.25", "9".repeat(4_096)])(
    "accepts canonical bounded DecimalText %s",
    (value) => {
      expect(isDecimalText(value)).toBe(true);
    },
  );

  it.each([
    0,
    "+1",
    "01",
    "-0",
    "0.0",
    "1.0",
    ".1",
    "1.",
    "1e3",
    " 1",
    "9".repeat(4_097),
  ])("rejects non-canonical or oversized DecimalText %s", (value) => {
    expect(isDecimalText(value)).toBe(false);
  });

  it("compares arbitrarily precise canonical decimals exactly", () => {
    expect(compareDecimalText("9007199254740993.0000000000000001", "9007199254740993")).toBe(
      1,
    );
    expect(compareDecimalText("-0.0000000000000001", "0")).toBe(-1);
    expect(compareDecimalText("999999999999999999999", "999999999999999999999")).toBe(0);
  });

  it("enforces exact rate and slippage domains", () => {
    expect(isRateText("0")).toBe(true);
    expect(isRateText("1")).toBe(true);
    expect(isRateText("0.0000000000000001")).toBe(true);
    expect(isRateText("-0.0000000000000001")).toBe(false);
    expect(isRateText("1.0000000000000001")).toBe(false);

    expect(isSlippageBpsText("0")).toBe(true);
    expect(isSlippageBpsText("9999.9999999999999999")).toBe(true);
    expect(isSlippageBpsText("10000")).toBe(false);
    expect(isSlippageBpsText("-0.1")).toBe(false);
  });

  it("guards JavaScript-safe integer and board-lot inputs", () => {
    expect(isJavaScriptSafeInteger(0)).toBe(true);
    expect(isJavaScriptSafeInteger(9_007_199_254_740_991)).toBe(true);
    expect(isJavaScriptSafeInteger(9_007_199_254_740_992)).toBe(false);
    expect(isJavaScriptSafeInteger(1.5)).toBe(false);
    expect(isPositiveJavaScriptSafeInteger(0)).toBe(false);
    expect(isPositiveJavaScriptSafeInteger(1)).toBe(true);
    expect(isBoardLotQuantity(100)).toBe(true);
    expect(isBoardLotQuantity(200)).toBe(true);
    expect(isBoardLotQuantity(101)).toBe(false);
  });

  it("normalizes only canonical-hyphenated RFC 4122 UUID text to lowercase", () => {
    expect(normalizeRfc4122Uuid("550E8400-E29B-41D4-A716-446655440000")).toBe(
      "550e8400-e29b-41d4-a716-446655440000",
    );
    expect(normalizeRfc4122Uuid("550e8400e29b41d4a716446655440000")).toBeNull();
    expect(normalizeRfc4122Uuid("550e8400-e29b-41d4-7716-446655440000")).toBeNull();
    expect(normalizeRfc4122Uuid("00000000-0000-0000-0000-000000000000")).toBeNull();
  });

  it("guards caller-stable lot keys at the exact 1..64 boundary", () => {
    expect(isLotKey("lot.Core_1-2")).toBe(true);
    expect(isLotKey("a".repeat(64))).toBe(true);
    expect(isLotKey("")).toBe(false);
    expect(isLotKey("a".repeat(65))).toBe(false);
    expect(isLotKey("bad key")).toBe(false);
    expect(isLotKey("-bad-prefix")).toBe(false);
  });

  it("keeps FenText paths free of binary-float conversion", () => {
    const source = readFileSync(resolve(process.cwd(), "src/api/backtestValues.ts"), "utf8");

    expect(source).not.toMatch(/\bNumber\s*\(|\bparseFloat\s*\(|\bparseInt\s*\(/);
  });
});
