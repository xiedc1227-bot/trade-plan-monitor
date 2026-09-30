import { describe, expect, it, vi } from "vitest";

import type {
  IndexConditionEvidenceView,
  SymbolDetailResponse,
  SymbolReferenceMarketView,
} from "../../src/api/generated";
import { createSymbolApi } from "../../src/api/symbols";

const symbol = "003043.SZ";
const observedAt = "2026-08-24T10:05:05.000000+08:00";
const sha256 = "a".repeat(64);

const referenceMarket: SymbolReferenceMarketView = {
  board: "SZSE_MAIN",
  conditionProgress: { missing: 0, satisfied: 1, total: 2, unsatisfied: 1 },
  dataAt: observedAt,
  displayName: "深证成指",
  health: "LIVE",
  indexCode: "399001.SZ",
  issues: [],
  mappingVersion: "board-index-map-v1",
  snapshotHash: sha256,
};

const evidence: IndexConditionEvidenceView = {
  actualValue: "101.25",
  comparisonValue: "100.00",
  conditionType: "INDEX_CLOSE_GTE_MA",
  dataCutoff: observedAt,
  decisionCutoff: observedAt,
  formulaDefinitionHash: "b".repeat(64),
  formulaId: "SMA",
  indexCode: "399001.SZ",
  mappingVersion: "board-index-map-v1",
  missingInputs: [],
  outcome: "SATISFIED",
  parameters: [{ key: "period", unit: "BARS", value: 20 }],
  planPath: "entry.condition.conditions[0]",
  snapshotHash: sha256,
  unit: "POINTS",
};

const detail = {
  indexConditionEvidence: [evidence],
  positionLots: [],
  referenceMarket,
  summary: {
    connected: false,
    decision: {
      dataAgeSeconds: null,
      dataHealth: {
        dataAgeSeconds: null,
        fresh: false,
        latestBarEnd: null,
        requiredDataComplete: false,
        status: "DEGRADED",
      },
      episodeLowFen: null,
      episodeStatus: null,
      evaluatedAt: observedAt,
      marketDataAt: null,
      nextStep: { code: "WAIT_FOR_REQUIRED_DATA" },
      planHash: "c".repeat(64),
      planId: "plan-1",
      planVersion: 1,
      position: {
        coreQuantity: 0,
        sellableCoreQuantity: 0,
        sellableTacticalQuantity: 0,
        tacticalQuantity: 0,
        totalQuantity: 0,
      },
      priceFen: null,
      resultHash: "d".repeat(64),
      riskBreachTradeDate: null,
      riskStatus: "CLEAR",
      signalType: "WAIT",
      symbol,
      zone: "UNKNOWN",
    },
    name: "华亚智能",
    observedAt,
    referenceMarket,
    riskDistanceFen: null,
    satisfiedConditionCount: 0,
    symbol,
    totalConditionCount: 0,
  },
} satisfies SymbolDetailResponse;

describe("symbol API", () => {
  it("accepts equivalent timestamp precision and deterministic UUID events from the unchanged history contract", async () => {
    const query = { startAt: "2026-08-24T00:00:00+08:00", endAt: "2026-08-24T10:05:05+08:00" };
    const event = { symbol, sequence: 1, eventId: "00000000-0000-5000-8000-000000000001", eventType: "ALERT", occurredAt: observedAt, signalType: null, resultHash: sha256, messageText: null };
    const page = { startAt: "2026-08-24T00:00:00.000000+08:00", endAt: observedAt, offset: 0, limit: 100, total: 1, items: [event] };
    const api = createSymbolApi(vi.fn(async () => jsonResponse(page)) as typeof fetch);
    await expect(api.getEvents(symbol, query)).resolves.toEqual(page);
    await expect(createSymbolApi(vi.fn(async () => jsonResponse({ ...page, endAt: "2026-08-24T10:05:06+08:00" })) as typeof fetch).getEvents(symbol, query)).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    const bars = { ...page, total: 0, items: [] };
    await expect(createSymbolApi(vi.fn(async () => jsonResponse(bars)) as typeof fetch).getBars(symbol, query)).resolves.toEqual(bars);
  });
  it("accepts an exact server-authoritative reference market and sorted index evidence", async () => {
    const api = createSymbolApi(
      vi.fn(async () => jsonResponse(detail)) as typeof fetch,
    );

    await expect(api.getSymbol(symbol)).resolves.toEqual(detail);
  });

  it("accepts only symbol-scoped unavailable reasons and the requested identity", async () => {
    const valid = {
      availability: "UNAVAILABLE",
      observedAt,
      reason: "NO_ACTIVE_PLAN",
      sequence: 1,
      symbol,
    };
    const validApi = createSymbolApi(
      vi.fn(async () => jsonResponse(valid)) as typeof fetch,
    );
    await expect(validApi.getSymbol(symbol)).resolves.toEqual(valid);

    for (const body of [
      { ...valid, reason: "EMPTY_DATABASE" },
      { ...valid, symbol: "600000.SH" },
    ]) {
      const api = createSymbolApi(
        vi.fn(async () => jsonResponse(body)) as typeof fetch,
      );
      await expect(api.getSymbol(symbol)).rejects.toMatchObject({
        code: "INVALID_RESPONSE",
      });
    }
  });

  it("treats absent and null reference-market projections as the same v1 compatibility value", async () => {
    const legacyDetail = {
      ...detail,
      indexConditionEvidence: [],
      referenceMarket: undefined,
      summary: { ...detail.summary, referenceMarket: null },
    };
    const api = createSymbolApi(
      vi.fn(async () => jsonResponse(legacyDetail)) as typeof fetch,
    );

    await expect(api.getSymbol(symbol)).resolves.toEqual(legacyDetail);
  });

  it("accepts OpenAPI-optional empty evidence arrays and authoritative missing-input evidence", async () => {
    const evidenceWithoutDefaultArrays = { ...evidence };
    delete evidenceWithoutDefaultArrays.missingInputs;
    delete evidenceWithoutDefaultArrays.parameters;
    const missingEvidence: IndexConditionEvidenceView = {
      ...evidence,
      actualValue: null,
      comparisonValue: null,
      dataCutoff: null,
      formulaDefinitionHash: null,
      missingInputs: ["INDEX_HISTORY"],
      outcome: "MISSING_INPUT",
      parameters: [],
      snapshotHash: null,
    };
    delete missingEvidence.parameters;

    for (const item of [evidenceWithoutDefaultArrays, missingEvidence]) {
      const body = { ...detail, indexConditionEvidence: [item] };
      const api = createSymbolApi(
        vi.fn(async () => jsonResponse(body)) as typeof fetch,
      );
      await expect(api.getSymbol(symbol)).resolves.toEqual(body);
    }
  });

  it("rejects malformed reference-market and index-evidence projections before exposing them", async () => {
    const missingInputEvidence: IndexConditionEvidenceView = {
      ...evidence,
      actualValue: null,
      comparisonValue: null,
      missingInputs: ["INDEX_HISTORY"],
      outcome: "MISSING_INPUT",
      snapshotHash: null,
      dataCutoff: null,
      formulaDefinitionHash: null,
    };
    const invalidBodies: unknown[] = [
      { ...detail, indexConditionEvidence: null },
      {
        ...detail,
        summary: {
          ...detail.summary,
          decision: { ...detail.summary.decision, planHash: "not-a-sha256" },
        },
      },
      { ...detail, referenceMarket: { ...referenceMarket, snapshotHash: null } },
      {
        ...detail,
        summary: { ...detail.summary, referenceMarket: { ...referenceMarket, health: "STALE" } },
      },
      {
        ...detail,
        referenceMarket: { ...referenceMarket, board: "BSE" },
        summary: {
          ...detail.summary,
          referenceMarket: { ...referenceMarket, board: "BSE" },
        },
      },
      {
        ...detail,
        referenceMarket: {
          ...referenceMarket,
          conditionProgress: { missing: 0, satisfied: 1, total: 3, unsatisfied: 1 },
        },
        summary: {
          ...detail.summary,
          referenceMarket: {
            ...referenceMarket,
            conditionProgress: { missing: 0, satisfied: 1, total: 3, unsatisfied: 1 },
          },
        },
      },
      { ...detail, indexConditionEvidence: [{ ...evidence, planPath: "entry.conditions[0]" }] },
      { ...detail, indexConditionEvidence: [{ ...evidence, actualValue: null }] },
      {
        ...detail,
        indexConditionEvidence: [
          { ...evidence, planPath: "risk.condition.conditions[1]" },
          { ...evidence, planPath: "entry.condition.conditions[0]" },
        ],
      },
      {
        ...detail,
        indexConditionEvidence: [
          missingInputEvidence,
          { ...missingInputEvidence, planPath: "entry.condition.conditions[1]", missingInputs: ["DAILY_INDICATORS"] },
        ],
      },
      {
        ...detail,
        indexConditionEvidence: [
          { ...evidence, indexCode: "000001.SH" },
        ],
      },
      {
        ...detail,
        indexConditionEvidence: [{ ...evidence, snapshotHash: "f".repeat(64) }],
      },
      {
        ...detail,
        indexConditionEvidence: [
          { ...evidence, dataCutoff: "2026-08-24T10:00:00.000000+08:00" },
        ],
      },
      {
        ...detail,
        referenceMarket: null,
        summary: { ...detail.summary, referenceMarket: null },
      },
      {
        ...detail,
        indexConditionEvidence: Array.from({ length: 51 }, (_, index) => ({
          ...evidence,
          planPath: `risk.condition.conditions[${index}]`,
        })),
      },
      {
        ...detail,
        indexConditionEvidence: [
          evidence,
          { ...evidence },
        ],
      },
      {
        ...detail,
        referenceMarket: { ...referenceMarket, unsupported: true },
        summary: { ...detail.summary, referenceMarket: { ...referenceMarket, unsupported: true } },
      },
      {
        ...detail,
        indexConditionEvidence: [{ ...evidence, actualValue: "not-a-decimal" }],
      },
      {
        ...detail,
        indexConditionEvidence: [
          { ...evidence, parameters: [{ key: "period", unit: "BARS", value: "20" }] },
        ],
      },
      { ...detail, indexConditionEvidence: [{ ...evidence, missingInputs: null }] },
      { ...detail, indexConditionEvidence: [{ ...evidence, parameters: null }] },
    ];

    for (const body of invalidBodies) {
      const api = createSymbolApi(
        vi.fn(async () => jsonResponse(body)) as typeof fetch,
      );
      await expect(api.getSymbol(symbol)).rejects.toMatchObject({
        code: "INVALID_RESPONSE",
      });
    }
  });
});

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
    status: 200,
  });
}
