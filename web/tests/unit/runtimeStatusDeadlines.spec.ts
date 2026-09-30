import { describe, expect, it } from "vitest";
import { monotonicDeadline } from "../../src/runtime-status/deadlines";

describe("server-authored presentation deadline", () => {
  it("subtracts the entire request elapsed time and anchors to monotonic receipt", () => {
    expect(monotonicDeadline("2026-09-14T10:11:00.000000+08:00", "2026-09-14T10:10:15.000000+08:00", 100, 5100)).toBe(45100);
  });
  it("treats equality and request-exhausted deadlines as expired at receipt", () => {
    expect(monotonicDeadline("2026-09-14T10:10:15.000000+08:00", "2026-09-14T10:10:15.000000+08:00", 100, 5100)).toBe(5100);
    expect(monotonicDeadline("2026-09-14T10:10:16.000000+08:00", "2026-09-14T10:10:15.000000+08:00", 100, 5100)).toBe(5100);
  });
  it("rounds fractional remaining milliseconds down without inventing a grace period", () => {
    expect(monotonicDeadline("2026-09-14T10:10:15.001999+08:00", "2026-09-14T10:10:15.000000+08:00", 10, 10)).toBe(11);
  });
  it("retains null state-risk deadlines without substituting a new expiry class", () => {
    expect(monotonicDeadline(null, "2026-09-14T10:10:15.000000+08:00", 100, 5100)).toBeNull();
  });
  it("fails closed if injected monotonic time reverses", () => {
    expect(monotonicDeadline("2026-09-14T10:11:00.000000+08:00", "2026-09-14T10:10:15.000000+08:00", 5100, 100)).toBe(100);
  });
});
