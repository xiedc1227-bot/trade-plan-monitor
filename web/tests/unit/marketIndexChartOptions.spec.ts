import { describe, expect, it } from "vitest";

import { calculateIndexAxisBounds } from "../../src/components/market-index/marketIndexChartOptions";

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
});
