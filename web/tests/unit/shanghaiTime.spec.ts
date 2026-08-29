import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import {
  isCalendarDate,
  isCanonicalShanghaiDateTime,
  isShanghaiDateTime,
  normalizeShanghaiDateTime,
  parseShanghaiDateTime,
  parseShanghaiResponseDateTime,
  shanghaiDateTimeKey,
} from "../../src/api/shanghaiTime";

describe("shared Shanghai time", () => {
  it.each([
    ["2026-08-29T04:05:06+08:00", "2026-08-29T04:05:06.000000+08:00"],
    ["2026-08-29T04:05:06.1+08:00", "2026-08-29T04:05:06.100000+08:00"],
    ["2026-08-29T04:05:06.123456+08:00", "2026-08-29T04:05:06.123456+08:00"],
  ])("normalizes %s to fixed-six Shanghai text", (value, canonical) => {
    expect(normalizeShanghaiDateTime(value)).toBe(canonical);
    expect(parseShanghaiDateTime(value)?.canonical).toBe(canonical);
    expect(isShanghaiDateTime(value)).toBe(true);
  });

  it("requires fixed six digits for response values", () => {
    expect(parseShanghaiResponseDateTime("2026-08-29T04:05:06.123456+08:00")?.canonical).toBe(
      "2026-08-29T04:05:06.123456+08:00",
    );
    expect(isCanonicalShanghaiDateTime("2026-08-29T04:05:06.123456+08:00")).toBe(true);
    expect(parseShanghaiResponseDateTime("2026-08-29T04:05:06+08:00")).toBeNull();
    expect(isCanonicalShanghaiDateTime("2026-08-29T04:05:06+08:00")).toBe(false);
  });

  it.each([
    "2026-08-29T04:05:06Z",
    "2026-08-29T04:05:06",
    "2026-08-29T04:05:06+00:00",
    "2026-08-29T04:05:06+09:00",
    "2026-08-29T04:05:06.1234567+08:00",
    " 2026-08-29T04:05:06+08:00",
  ])("rejects non-contract datetime %s", (value) => {
    expect(parseShanghaiDateTime(value)).toBeNull();
    expect(normalizeShanghaiDateTime(value)).toBeNull();
  });

  it.each([
    "0000-01-01T00:00:00+08:00",
    "1900-02-29T00:00:00+08:00",
    "2026-02-29T00:00:00+08:00",
    "2026-04-31T00:00:00+08:00",
    "2026-01-01T24:00:00+08:00",
    "2026-01-01T23:60:00+08:00",
    "2026-01-01T23:59:60+08:00",
  ])("rejects impossible Gregorian wall time %s", (value) => {
    expect(parseShanghaiDateTime(value)).toBeNull();
  });

  it("accepts real leap days and validates date-only calendar values", () => {
    expect(isShanghaiDateTime("2000-02-29T23:59:59.999999+08:00")).toBe(true);
    expect(isCalendarDate("2000-02-29")).toBe(true);
    expect(isCalendarDate("1900-02-29")).toBe(false);
    expect(isCalendarDate("2026-2-03")).toBe(false);
  });

  it("preserves both the Shanghai wall time and the represented instant", () => {
    const epoch = parseShanghaiDateTime("1970-01-01T08:00:00+08:00");
    const prior = parseShanghaiDateTime("1970-01-01T00:00:00+08:00");
    const nextMicrosecond = parseShanghaiDateTime("1970-01-01T08:00:00.000001+08:00");

    expect(epoch).toMatchObject({
      canonical: "1970-01-01T08:00:00.000000+08:00",
      epochMicroseconds: 0n,
    });
    expect(prior?.epochMicroseconds).toBe(-28_800_000_000n);
    expect(nextMicrosecond?.epochMicroseconds).toBe(1n);
    expect(shanghaiDateTimeKey("1970-01-01T08:00:00.000001+08:00")).toBe(1n);
  });

  it("keeps contract time code independent of Date and the host timezone", () => {
    const helperSource = readFileSync(resolve(process.cwd(), "src/api/shanghaiTime.ts"), "utf8");
    const clientSource = readFileSync(resolve(process.cwd(), "src/api/client.ts"), "utf8");

    expect(helperSource).not.toMatch(/\bDate\b|toISOString/);
    expect(clientSource).toContain('from "./shanghaiTime"');
    expect(clientSource).not.toMatch(/function parseShanghaiDateTime|Date\.toISOString/);
  });
});
