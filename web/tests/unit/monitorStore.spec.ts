import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClientError, createApiClient } from "../../src/api/client";
import type { DashboardResponse } from "../../src/api/generated";
import { useMonitorStore } from "../../src/stores/monitor";
import type { MonitorEventEnvelope } from "../../src/stores/monitor";

const snapshot: DashboardResponse = {
  connectionStatus: "CONNECTED",
  counts: {
    actionable: 1,
    blocked: 0,
    lowZoneWatch: 1,
    normal: 0,
    risk: 0,
    stale: 0,
  },
  marketIndexes: [],
  observedAt: "2026-08-24T10:30:00+08:00",
  runtimeGeneration: "00000000-0000-4000-8000-000000000001",
  sequence: 7,
  symbols: [
    {
      connected: true,
      decision: {
        dataAgeSeconds: 2,
        dataHealth: {
          dataAgeSeconds: 2,
          fresh: true,
          latestBarEnd: "2026-08-24T10:29:58+08:00",
          requiredDataComplete: true,
          status: "LIVE",
        },
        episodeLowFen: 2010,
        episodeStatus: "ACTIVE",
        evaluatedAt: "2026-08-24T10:30:00+08:00",
        evidence: [],
        marketDataAt: "2026-08-24T10:29:58+08:00",
        nextStep: { code: "WATCH_LOW_ZONE" },
        planHash: "a".repeat(64),
        planId: "plan-1",
        planVersion: 1,
        position: {
          coreQuantity: 0,
          sellableCoreQuantity: 0,
          sellableTacticalQuantity: 0,
          tacticalQuantity: 0,
          totalQuantity: 0,
        },
        priceFen: 2020,
        resultHash: "b".repeat(64),
        riskBreachTradeDate: null,
        riskStatus: "CLEAR",
        signalType: "LOW_ZONE_WATCH",
        symbol: "003043.SZ",
        zone: "LOW_BUY",
      },
      name: "华亚智能",
      observedAt: "2026-08-24T10:30:00+08:00",
      riskDistanceFen: 120,
      satisfiedConditionCount: 1,
      symbol: "003043.SZ",
      totalConditionCount: 3,
    },
  ],
};

function crossDayOfficialRiskBreachSnapshot(): DashboardResponse {
  const value = structuredClone(snapshot);
  const summary = value.symbols?.[0];
  if (summary === undefined) {
    throw new Error("test fixture must contain one symbol");
  }
  value.connectionStatus = "DISCONNECTED";
  value.observedAt = "2026-08-25T10:00:00+08:00";
  summary.connected = false;
  summary.observedAt = value.observedAt;
  summary.riskDistanceFen = -580;
  summary.decision = {
    ...summary.decision,
    dataAgeSeconds: 68_400,
    dataHealth: {
      dataAgeSeconds: null,
      fresh: false,
      latestBarEnd: null,
      requiredDataComplete: true,
      status: "STALE",
    },
    episodeLowFen: null,
    episodeStatus: null,
    evaluatedAt: value.observedAt,
    evidence: [
      {
        children: [],
        code: "OFFICIAL_CLOSE_BELOW_LEVEL",
        facts: [
          { key: "official_close_fen", unit: "FEN", value: 5_500 },
          { key: "risk_line_fen", unit: "FEN", value: 6_080 },
          { key: "official_trade_date", unit: "DATE", value: "2026-08-24" },
        ],
        kind: "CONDITION",
        missingInputs: [],
        outcome: "SATISFIED",
      },
    ],
    marketDataAt: "2026-08-24T15:00:00+08:00",
    nextStep: { code: "WAIT_FOR_NEXT_TRADING_DAY" },
    priceFen: 5_500,
    riskBreachTradeDate: "2026-08-24",
    riskStatus: "BREACHED_PENDING_CONFIRMATION",
    signalType: "RISK_BREACH",
    zone: "BELOW_RISK",
  };
  return value;
}

function event(sequence: number): MonitorEventEnvelope {
  return {
    aggregateId: "003043.SZ",
    eventId: "00000000-0000-0000-0000-000000000001",
    occurredAt: "2026-08-24T10:31:00+08:00",
    payload: {
      entityId: "003043.SZ",
      resultHash: "c".repeat(64),
      symbol: "003043.SZ",
    },
    schemaVersion: 1,
    sequence,
    type: "symbol.snapshot.updated",
  };
}

beforeEach(() => {
  setActivePinia(createPinia());
});

describe("monitor store", () => {
  it("normalizes snapshots behind readonly selectors", () => {
    const store = useMonitorStore();
    store.applySnapshot(snapshot);

    expect(store.sequence).toBe(7);
    expect(store.runtimeGeneration).toBe("00000000-0000-4000-8000-000000000001");
    expect(store.symbolIds).toEqual(["003043.SZ"]);
    expect(store.symbolsById["003043.SZ"]?.name).toBe("华亚智能");
    expect(store.symbols.map((item) => item.symbol)).toEqual(["003043.SZ"]);
    expect(store.connectionState).toEqual({
      code: "CONNECTED",
      label: "实时连接",
      marker: "●",
    });

    const readonlyWarning = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    Reflect.set(store, "sequence", 99);
    expect(store.sequence).toBe(7);
    expect(readonlyWarning).toHaveBeenCalled();
    expect(() => {
      const symbol = store.symbolsById["003043.SZ"];
      if (symbol !== undefined) {
        (symbol as { name: string }).name = "被组件改写";
      }
    }).toThrow(TypeError);
    expect(store.symbolsById["003043.SZ"]?.name).toBe("华亚智能");
  });

  it("applies only the next ordered event and rejects duplicates or older events", () => {
    const store = useMonitorStore();
    store.applySnapshot(snapshot);

    expect(store.applyEvent(event(8))).toEqual({ status: "applied", sequence: 8 });
    expect(store.sequence).toBe(8);
    expect(store.lastInvalidation).toMatchObject({
      entityId: "003043.SZ",
      sequence: 8,
      type: "symbol.snapshot.updated",
    });
    expect(store.lastEvent).toEqual(event(8));
    expect(store.applyEvent(event(8))).toEqual({
      currentSequence: 8,
      receivedSequence: 8,
      reason: "DUPLICATE_OR_OUT_OF_ORDER",
      status: "rejected",
    });
    expect(store.applyEvent(event(7))).toMatchObject({ status: "rejected" });
    expect(store.sequence).toBe(8);
  });

  it("keeps the cursor stable and requests a snapshot when a sequence gap appears", () => {
    const store = useMonitorStore();
    store.applySnapshot(snapshot);

    expect(store.applyEvent(event(9))).toEqual({
      expectedSequence: 8,
      receivedSequence: 9,
      status: "recovery-required",
    });
    expect(store.sequence).toBe(7);
    expect(store.recoveryIntent).toEqual({
      expectedSequence: 8,
      reason: "SEQUENCE_GAP",
      receivedSequence: 9,
    });

    store.requestSnapshotRecovery("SERVER_REQUIRED", 12);
    expect(store.recoveryIntent).toEqual({
      expectedSequence: 8,
      reason: "SERVER_REQUIRED",
      receivedSequence: 12,
    });

    store.applySnapshot({ ...snapshot, sequence: 12 });
    expect(store.sequence).toBe(12);
    expect(store.recoveryIntent).toBeNull();
  });

  it("rejects regressive snapshots without clearing newer event state", () => {
    const store = useMonitorStore();
    store.applySnapshot(snapshot);
    store.applyEvent(event(8));

    expect(() => store.applySnapshot({ ...snapshot, sequence: 3 })).toThrow(RangeError);
    expect(store.sequence).toBe(8);
    expect(store.lastInvalidation?.sequence).toBe(8);
  });

  it("fails closed on malformed next-sequence events", () => {
    const store = useMonitorStore();
    store.applySnapshot(snapshot);
    const malformed = {
      ...event(8),
      eventId: "not-a-uuid",
      payload: { entityId: "" },
      type: "not.a.monitor.event",
    } as unknown as MonitorEventEnvelope;

    expect(store.applyEvent(malformed)).toMatchObject({ status: "recovery-required" });
    expect(store.sequence).toBe(7);
    expect(store.recoveryIntent?.reason).toBe("INVALID_EVENT");
  });

  it("rejects calendar-normalized impossible event dates", () => {
    const store = useMonitorStore();
    store.applySnapshot(snapshot);

    expect(
      store.applyEvent({ ...event(8), occurredAt: "2026-02-30T10:31:00+08:00" }),
    ).toMatchObject({ status: "recovery-required" });
    expect(store.sequence).toBe(7);
    expect(store.recoveryIntent?.reason).toBe("INVALID_EVENT");
  });

  it("accepts canonical Beijing Stock Exchange symbol events", () => {
    const store = useMonitorStore();
    store.applySnapshot(snapshot);
    const source = event(8);

    expect(
      store.applyEvent({
        ...source,
        aggregateId: "430047.BJ",
        payload: {
          ...source.payload,
          entityId: "430047.BJ",
          symbol: "430047.BJ",
        },
      }),
    ).toEqual({ sequence: 8, status: "applied" });
  });

  it("rejects event identities with non-canonical surrounding whitespace", () => {
    const store = useMonitorStore();
    store.applySnapshot(snapshot);

    expect(
      store.applyEvent({
        aggregateId: " provider-1 ",
        eventId: "00000000-0000-0000-0000-000000000002",
        occurredAt: "2026-08-24T10:31:00+08:00",
        payload: { entityId: " provider-1 ", revision: 1 },
        schemaVersion: 1,
        sequence: 8,
        type: "ai.provider.updated",
      }),
    ).toMatchObject({ status: "recovery-required" });
    expect(store.sequence).toBe(7);
    expect(store.recoveryIntent?.reason).toBe("INVALID_EVENT");
  });

  it("rejects event timestamps beyond wire-level microsecond precision", () => {
    const store = useMonitorStore();
    store.applySnapshot(snapshot);

    expect(
      store.applyEvent({ ...event(8), occurredAt: "2026-08-24T10:31:00.1234567+08:00" }),
    ).toMatchObject({ status: "recovery-required" });
    expect(store.sequence).toBe(7);
    expect(store.recoveryIntent?.reason).toBe("INVALID_EVENT");
  });

  it("never derives an unsafe next sequence at the JavaScript integer limit", () => {
    const store = useMonitorStore();
    store.applySnapshot({ ...snapshot, sequence: Number.MAX_SAFE_INTEGER });

    store.requestSnapshotRecovery("SERVER_REQUIRED", Number.MAX_SAFE_INTEGER);

    expect(store.recoveryIntent).toEqual({
      expectedSequence: null,
      reason: "SERVER_REQUIRED",
      receivedSequence: Number.MAX_SAFE_INTEGER,
    });
  });
});

describe("API client", () => {
  it("parses the generated camelCase dashboard contract", async () => {
    const fetchImplementation = vi.fn(async () =>
      new Response(JSON.stringify(snapshot), {
        headers: { "Content-Type": "application/json" },
        status: 200,
      }),
    );
    const client = createApiClient(fetchImplementation);

    await expect(client.getDashboard()).resolves.toEqual(snapshot);
    expect(fetchImplementation).toHaveBeenCalledWith(
      "/api/v1/dashboard",
      expect.objectContaining({ headers: { Accept: "application/json" }, method: "GET" }),
    );
  });

  it("accepts a complete stale official-close risk breach restored on the next day", async () => {
    const restored = crossDayOfficialRiskBreachSnapshot();
    const client = createApiClient(async () =>
      new Response(JSON.stringify(restored), { status: 200 }),
    );

    await expect(client.getDashboard()).resolves.toEqual(restored);
  });

  it.each([
    ["a non-official actionable signal", (value: DashboardResponse) => {
      const decision = value.symbols?.[0]?.decision;
      if (decision !== undefined) decision.signalType = "BUY_CORE_READY";
    }],
    ["incomplete official-close evidence", (value: DashboardResponse) => {
      const decision = value.symbols?.[0]?.decision;
      if (decision?.evidence?.[0] !== undefined) {
        decision.evidence[0].outcome = "UNSATISFIED";
      }
    }],
  ])("rejects stale actionable data for %s", async (_label, mutate) => {
    const invalid = crossDayOfficialRiskBreachSnapshot();
    mutate(invalid);
    const client = createApiClient(async () =>
      new Response(JSON.stringify(invalid), { status: 200 }),
    );

    await expect(client.getDashboard()).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("rejects unavailable envelopes from another endpoint scope", async () => {
    for (const reason of ["NO_ACTIVE_PLAN", "AWAITING_FIRST_EVALUATION_WRONG"] as const) {
      const client = createApiClient(async () =>
        new Response(
          JSON.stringify({
            availability: "UNAVAILABLE",
            observedAt: snapshot.observedAt,
            reason,
            sequence: snapshot.sequence,
            symbol: "003043.SZ",
          }),
          { status: 200 },
        ),
      );

      await expect(client.getDashboard()).rejects.toMatchObject({
        code: "INVALID_RESPONSE",
      });
    }
  });

  it("matches the backend integer-second data-age contract", async () => {
    const fractionalAgeSnapshot = structuredClone(snapshot);
    const decision = fractionalAgeSnapshot.symbols?.[0]?.decision;
    if (decision === undefined) {
      throw new Error("test fixture must contain one decision");
    }
    fractionalAgeSnapshot.observedAt = "2026-08-24T10:30:00.500+08:00";
    const summary = fractionalAgeSnapshot.symbols?.[0];
    if (summary === undefined) {
      throw new Error("test fixture must contain one symbol");
    }
    summary.observedAt = "2026-08-24T10:30:00.500+08:00";
    decision.evaluatedAt = "2026-08-24T10:30:00.500+08:00";
    decision.marketDataAt = "2026-08-24T10:29:58.000+08:00";
    decision.dataHealth.latestBarEnd = "2026-08-24T10:29:58.000+08:00";
    const validClient = createApiClient(async () =>
      new Response(JSON.stringify(fractionalAgeSnapshot), { status: 200 }),
    );

    await expect(validClient.getDashboard()).resolves.toEqual(fractionalAgeSnapshot);

    const negativeAgeSnapshot = structuredClone(fractionalAgeSnapshot);
    const negativeDecision = negativeAgeSnapshot.symbols?.[0]?.decision;
    if (negativeDecision === undefined) {
      throw new Error("test fixture must contain one decision");
    }
    negativeDecision.dataAgeSeconds = 0;
    negativeDecision.marketDataAt = "2026-08-24T10:30:00.500100+08:00";
    const invalidClient = createApiClient(async () =>
      new Response(JSON.stringify(negativeAgeSnapshot), { status: 200 }),
    );

    await expect(invalidClient.getDashboard()).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
    });
  });

  it("rejects microsecond-level observation ordering violations", async () => {
    const invalidSnapshot = structuredClone(snapshot);
    const summary = invalidSnapshot.symbols?.[0];
    if (summary === undefined) {
      throw new Error("test fixture must contain one symbol");
    }
    invalidSnapshot.observedAt = "2026-08-24T10:30:00.001000+08:00";
    summary.observedAt = "2026-08-24T10:30:00.000100+08:00";
    summary.decision.evaluatedAt = "2026-08-24T10:30:00.000900+08:00";
    summary.decision.marketDataAt = "2026-08-24T10:29:58.000900+08:00";
    summary.decision.dataHealth.latestBarEnd = "2026-08-24T10:29:58.000900+08:00";
    const client = createApiClient(async () =>
      new Response(JSON.stringify(invalidSnapshot), { status: 200 }),
    );

    await expect(client.getDashboard()).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("stops reading an oversized streaming response at the byte boundary", async () => {
    let pulls = 0;
    let cancelled = false;
    const stream = new ReadableStream<Uint8Array>({
      cancel() {
        cancelled = true;
      },
      pull(controller) {
        pulls += 1;
        controller.enqueue(new Uint8Array(1024 * 1024).fill(0x20));
        if (pulls === 10) {
          controller.close();
        }
      },
    });
    const client = createApiClient(async () => new Response(stream, { status: 200 }));

    await expect(client.getDashboard()).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    expect(cancelled).toBe(true);
    expect(pulls).toBeLessThan(10);
  });

  it("returns bounded typed errors without exposing malformed response bodies", async () => {
    const typedErrorClient = createApiClient(async () =>
      new Response(
        JSON.stringify({
          error: {
            code: "CONFLICT",
            details: [{ code: "REVISION_CONFLICT", location: ["body", "expectedRevision"], message: "修订冲突" }],
            message: "资源已被更新",
            requestId: "1".repeat(32),
          },
        }),
        { headers: { "Content-Type": "application/json" }, status: 409 },
      ),
    );

    await expect(typedErrorClient.getDashboard()).rejects.toMatchObject({
      code: "CONFLICT",
      message: "请求与当前状态冲突",
      requestId: "1".repeat(32),
      status: 409,
    } satisfies Partial<ApiClientError>);

    const secret = "secret-that-must-not-escape";
    const malformedClient = createApiClient(async () =>
      new Response(JSON.stringify({ error_message: secret }), { status: 500 }),
    );

    try {
      await malformedClient.getDashboard();
      throw new Error("expected getDashboard to reject");
    } catch (error) {
      expect(error).toBeInstanceOf(ApiClientError);
      expect(String(error)).not.toContain(secret);
      expect(error).toMatchObject({ code: "INVALID_RESPONSE", status: 500 });
    }
  });

  it("rejects undeclared sensitive fields and never re-emits raw server error text", async () => {
    const responseSecret = "dashboard-api-key-must-not-escape";
    const unsafeDashboardClient = createApiClient(async () =>
      new Response(
        JSON.stringify({
          ...snapshot,
          decision: { apiKey: responseSecret },
        }),
        { status: 200 },
      ),
    );

    await expect(unsafeDashboardClient.getDashboard()).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
    });

    const errorSecret = "raw-provider-error-must-not-escape";
    const unsafeErrorClient = createApiClient(async () =>
      new Response(
        JSON.stringify({
          error: {
            code: "INTERNAL_ERROR",
            details: [
              {
                authorization: errorSecret,
                code: "PROVIDER_ERROR",
                location: ["provider"],
                message: errorSecret,
              },
            ],
            message: errorSecret,
            requestId: "request-2",
          },
        }),
        { status: 500 },
      ),
    );

    try {
      await unsafeErrorClient.getDashboard();
      throw new Error("expected unsafe error response to reject");
    } catch (error) {
      expect(error).toBeInstanceOf(ApiClientError);
      expect(String(error)).not.toContain(errorSecret);
      expect(JSON.stringify(error)).not.toContain(errorSecret);
      expect(error).toMatchObject({ code: "INVALID_RESPONSE", status: 500 });
    }
  });

  it("rejects secret-bearing request IDs and invalid closed-domain dashboard values", async () => {
    const requestIdSecret = "raw-secret-in-request-id";
    const unsafeRequestIdClient = createApiClient(async () =>
      new Response(
        JSON.stringify({
          error: {
            code: "INTERNAL_ERROR",
            details: [],
            message: "Internal error",
            requestId: requestIdSecret,
          },
        }),
        { status: 500 },
      ),
    );

    try {
      await unsafeRequestIdClient.getDashboard();
      throw new Error("expected unsafe request ID to reject");
    } catch (error) {
      expect(error).toBeInstanceOf(ApiClientError);
      expect(JSON.stringify(error)).not.toContain(requestIdSecret);
      expect(error).toMatchObject({ code: "INVALID_RESPONSE" });
    }

    const invalidSnapshot = structuredClone(snapshot);
    const decision = invalidSnapshot.symbols?.[0]?.decision;
    if (decision === undefined) {
      throw new Error("test fixture must contain one decision");
    }
    decision.riskStatus = "TOTALLY_INVALID" as typeof decision.riskStatus;
    decision.priceFen = -1.5;
    const invalidDomainClient = createApiClient(async () =>
      new Response(JSON.stringify(invalidSnapshot), { status: 200 }),
    );

    await expect(invalidDomainClient.getDashboard()).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
    });
  });

  it("rejects dashboard cross-field and collection-bound violations", async () => {
    const mismatchedSnapshot = structuredClone(snapshot);
    const summary = mismatchedSnapshot.symbols?.[0];
    if (summary === undefined) {
      throw new Error("test fixture must contain one symbol");
    }
    summary.decision.symbol = "600000.SH";
    summary.decision.dataHealth.fresh = false;
    const client = createApiClient(async () =>
      new Response(JSON.stringify(mismatchedSnapshot), { status: 200 }),
    );

    await expect(client.getDashboard()).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("rejects noncanonical market-index identity tuples in shared and plan projections", async () => {
    const sharedMismatch = structuredClone(snapshot);
    sharedMismatch.marketIndexes = [
      {
        board: "BSE",
        closePoints: "1234.56",
        completedBucketAt: "2026-08-24T10:30:00+08:00",
        displayName: "科创50",
        health: "LIVE",
        indexCode: "000688.SH",
        indicatorFacts: [],
        issues: [],
        mappedSymbolCount: 1,
        mappingVersion: "board-index-map-v1",
        observedAt: "2026-08-24T10:30:00+08:00",
        priorClosePoints: "1220.11",
        revision: 1,
        sessionChangeRatio: "0.011843",
        snapshotHash: "c".repeat(64),
      },
    ];
    const planMismatch = structuredClone(snapshot);
    const summary = planMismatch.symbols?.[0];
    if (summary === undefined) throw new Error("test fixture must contain one symbol");
    summary.referenceMarket = {
      board: "BSE",
      conditionProgress: { missing: 0, satisfied: 1, total: 1, unsatisfied: 0 },
      dataAt: "2026-08-24T10:30:00+08:00",
      displayName: "科创50",
      health: "LIVE",
      indexCode: "000688.SH",
      issues: [],
      mappingVersion: "board-index-map-v1",
      snapshotHash: "c".repeat(64),
    };

    for (const body of [sharedMismatch, planMismatch]) {
      const client = createApiClient(async () =>
        new Response(JSON.stringify(body), { status: 200 }),
      );
      await expect(client.getDashboard()).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    }
  });

  it("rejects evidence values outside their generated unit contract", async () => {
    const invalidEvidenceSnapshot = structuredClone(snapshot);
    const decision = invalidEvidenceSnapshot.symbols?.[0]?.decision;
    if (decision === undefined) {
      throw new Error("test fixture must contain one decision");
    }
    decision.evidence = [
      {
        code: "lowercase-forbidden",
        facts: [
          {
            key: "UPPER_FORBIDDEN",
            unit: "FEN",
            value: 1.5,
          },
        ],
        kind: "RULE",
        missingInputs: [],
        outcome: "SATISFIED",
      },
    ];
    const client = createApiClient(async () =>
      new Response(JSON.stringify(invalidEvidenceSnapshot), { status: 200 }),
    );

    await expect(client.getDashboard()).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("rejects hostile decimal evidence in linear time", async () => {
    const hostileSnapshot = structuredClone(snapshot);
    const decision = hostileSnapshot.symbols?.[0]?.decision;
    if (decision === undefined) {
      throw new Error("test fixture must contain one decision");
    }
    decision.evidence = [
      {
        code: "RATIO_EVIDENCE",
        facts: [{ key: "ratio", unit: "RATIO", value: `${"0".repeat(3_000)}x` }],
        kind: "RULE",
        missingInputs: [],
        outcome: "SATISFIED",
      },
    ];
    const client = createApiClient(async () =>
      new Response(JSON.stringify(hostileSnapshot), { status: 200 }),
    );
    const startedAt = performance.now();

    await expect(client.getDashboard()).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    expect(performance.now() - startedAt).toBeLessThan(250);
  }, 10_000);

  it("rejects error locations beyond the frozen 64-character boundary", async () => {
    const client = createApiClient(async () =>
      new Response(
        JSON.stringify({
          error: {
            code: "VALIDATION_ERROR",
            details: [
              {
                code: "INVALID_FIELD",
                location: ["a".repeat(65)],
                message: "Invalid field",
              },
            ],
            message: "Validation failed",
            requestId: "2".repeat(32),
          },
        }),
        { status: 422 },
      ),
    );

    await expect(client.getDashboard()).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("maps deeply nested malformed JSON to a bounded client error", async () => {
    const depth = 12_000;
    const body = `{"unexpected":${'{"next":'.repeat(depth)}null${"}".repeat(depth)}}`;
    const client = createApiClient(async () => new Response(body, { status: 200 }));

    await expect(client.getDashboard()).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
      status: 200,
    });
  });
});

describe("signal-console design tokens", () => {
  it("defines the approved semantic palette without a purple gradient", () => {
    const source = readFileSync(resolve(process.cwd(), "src/assets/tokens.css"), "utf8");
    const shellSource = readFileSync(resolve(process.cwd(), "src/layouts/AppShell.vue"), "utf8");

    expect(source).toMatch(/--color-surface-graphite:/);
    expect(source).toMatch(/--color-signal-watch-amber:/);
    expect(source).toMatch(/--color-signal-live-sea-glass:/);
    expect(source).toMatch(/--color-signal-risk-vermilion:/);
    expect(source).toMatch(/--font-numeric:/);
    expect(source).not.toMatch(/purple|violet|linear-gradient/i);
    expect(shellSource).toMatch(/background:\s*var\(--color-surface-ink\)/);
    expect(shellSource).toMatch(/color:\s*var\(--color-text-mineral\)/);
  });
});
