import type { MarketIndexOverviewResponse } from "../../src/api/generated";
import { dashboardMarketIndexIdentities } from "../../src/api/marketIndexIdentity";

export function overviewFixture(): MarketIndexOverviewResponse {
  const day = "2026-10-09";
  const observedAt = `${day}T15:20:02+08:00`;
  return {
    schemaVersion: 1, observedAt: `${day}T16:00:00+08:00`, runtimeGeneration: null, sequence: 3,
    marketSession: { phase: "CLOSED", calendarStatus: "KNOWN", sessionDate: day, displayTradeDate: day, expectedBucketAt: `${day}T15:00:00+08:00` },
    indexes: dashboardMarketIndexIdentities.map(identity => ({ ...identity,
      dataStatus: "CURRENT", latestAcquisition: { decisionCutoff: `${day}T15:00:00+08:00`, observedAt: `${day}T16:00:00+08:00`, health: "BLOCKED", issues: ["PROVIDER_UNAVAILABLE"], nextRetryAt: null },
      data: { snapshotHash: "a".repeat(64), observedAt, completedBucketAt: `${day}T15:00:00+08:00`, sourceKind: "PROVISIONAL",
        closePoints: "3813.791", priorClosePoints: "3811.9043", sessionChangeRatio: "0.000494", highPoints: "3824.71", lowPoints: "3754.14", amount: "865500000000",
        bars: Array.from({ length: 48 }, (_, i) => {
          const minutes = (i < 24 ? 575 : 785) + (i % 24) * 5;
          const at = `${day}T${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}:00+08:00`;
          return { indexCode: identity.indexCode, interval: "FIVE_MINUTE", barAt: at, observedAt, sourceKind: "PROVISIONAL", providerRevision: 1, openPoints: "3810", highPoints: "3824.71", lowPoints: "3754.14", closePoints: "3813.791", amount: "18031250000", volume: "100" };
        }),
      },
    })), marketTurnover: null,
  };
}
