import { describe, expect, it } from "vitest";

import {
  formatDisplayDateTime,
  formatDisplayFactValue,
} from "../../src/formatters/dateTime";

describe("formatDisplayDateTime", () => {
  it("uses a common readable format without changing the source wall-clock time", () => {
    expect(formatDisplayDateTime("2026-09-10T11:20:00+08:00")).toBe("2026-09-10 11:20:00");
    expect(formatDisplayDateTime("2026-09-10T11:20:00.123456+08:00")).toBe(
      "2026-09-10 11:20:00",
    );
    expect(formatDisplayDateTime("2026-09-10T03:20:00Z")).toBe("2026-09-10 03:20:00");
  });

  it("uses the requested fallback for missing or invalid values", () => {
    expect(formatDisplayDateTime(null)).toBe("—");
    expect(formatDisplayDateTime(undefined, "未知")).toBe("未知");
    expect(formatDisplayDateTime("not-a-time", "不可用")).toBe("不可用");
  });

  it("formats structured DATETIME evidence without changing other fact values", () => {
    expect(formatDisplayFactValue("2026-09-10T11:20:00+08:00", "DATETIME")).toBe(
      "2026-09-10 11:20:00",
    );
    expect(formatDisplayFactValue("12.3400", "YUAN")).toBe("12.3400");
  });
});
