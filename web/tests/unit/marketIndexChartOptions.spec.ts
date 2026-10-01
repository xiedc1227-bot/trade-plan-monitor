import { describe, expect, it } from "vitest";

import type { MarketIndexBarView } from "../../src/api/generated";
import {
  buildMarketIndexChartPoints,
  calculateIndexAxisBounds,
  marketIndexDirection,
  marketIndexDirectionColor,
  marketIndexShowSymbol,
  marketIndexValueDirection,
} from "../../src/components/market-index/marketIndexChartOptions";

const openingBar = Object.freeze({
  amount: "1000",
  barAt: "2026-09-11T09:35:00.000000+08:00",
  closePoints: "3320.25",
  highPoints: "3322.00",
  indexCode: "399006.SZ",
  interval: "FIVE_MINUTE",
  lowPoints: "3310.50",
  observedAt: "2026-09-11T09:35:12.000000+08:00",
  openPoints: "3312.75",
  providerRevision: 1,
  sourceKind: "PROVISIONAL",
  volume: "100",
} satisfies MarketIndexBarView);

describe("market index chart options", () => {
  it("starts an opening five-minute series at 09:30 with the opening price", () => {
    expect(buildMarketIndexChartPoints([openingBar])).toEqual([
      { at: "2026-09-11T09:30:00+08:00", value: 3312.75 },
      { at: "2026-09-11T09:35:00.000000+08:00", value: 3320.25 },
    ]);
  });

  it("does not invent an opening point when the 09:35 bar is unavailable", () => {
    const laterBar = Object.freeze({
      ...openingBar,
      barAt: "2026-09-11T09:40:00.000000+08:00",
    });

    expect(buildMarketIndexChartPoints([laterBar])).toEqual([
      { at: "2026-09-11T09:40:00.000000+08:00", value: 3320.25 },
    ]);
  });

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
    ["0.0123", "up", "#f58b77"],
    ["-0.0123", "down", "#87c6a5"],
    ["0", "flat", "#f0f0e8"],
    [null, "flat", "#f0f0e8"],
    ["invalid", "flat", "#f0f0e8"],
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
