import { describe, expect, it } from "vitest";

import {
  calculateIndexAxisBounds,
  marketIndexDirection,
  marketIndexDirectionColor,
  marketIndexShowSymbol,
  marketIndexValueDirection,
} from "../../src/components/market-index/marketIndexChartOptions";

describe("market index chart options", () => {
  it("keeps a prior close above the intraday range inside the visible y-axis", () => {
    const bounds = calculateIndexAxisBounds([3931.4, 3948.015, 3934.375], 3951.5068);

    expect(bounds?.minimum).toBeLessThan(3931.4);
    expect(bounds?.maximum).toBeGreaterThan(3951.5068);
  });

  it("keeps a flat series legible with a non-zero padded range", () => {
    const bounds = calculateIndexAxisBounds([3000, 3000], 3000);

    expect(bounds?.minimum).toBeLessThan(3000);
    expect(bounds?.maximum).toBeGreaterThan(3000);
  });

  it("shows the only point in a one-bar series without cluttering longer trends", () => {
    expect(marketIndexShowSymbol(0)).toBe(false);
    expect(marketIndexShowSymbol(1)).toBe(true);
    expect(marketIndexShowSymbol(2)).toBe(false);
  });

  it.each([
    ["0.0123", "up", "#e45d43"],
    ["-0.0123", "down", "#67b7a5"],
    ["0", "flat", "#eef1e8"],
    [null, "flat", "#eef1e8"],
    ["invalid", "flat", "#eef1e8"],
  ] as const)("maps session change %s to %s and its market color", (ratio, direction, color) => {
    expect(marketIndexDirection(ratio)).toBe(direction);
    expect(marketIndexDirectionColor(ratio)).toBe(color);
  });

  it.each([
    ["99", "100", "down"],
    ["101", "100", "up"],
    ["100", "100", "flat"],
    [null, "100", "flat"],
    ["101", null, "flat"],
  ] as const)("compares point %s directly with prior close %s", (value, priorClose, direction) => {
    expect(marketIndexValueDirection(value, priorClose)).toBe(direction);
  });
});
