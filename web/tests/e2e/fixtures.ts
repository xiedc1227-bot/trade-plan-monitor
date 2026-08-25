import { expect, test as base } from "@playwright/test";
import { createServer } from "vite";

import type {
  AIProviderPage,
  AIProviderSecretCommand,
  AIProviderTestCommand,
  AIProviderView,
  ActivePlanView,
  AlertAcknowledgementCommand,
  AlertPage,
  AlertView,
  BarPage,
  OperationReceipt,
  PlanActivationCommand,
  PlanDraftCommand,
  PlanExtractionCommand,
  PlanExtractionView,
  PlanVersionView,
  PositionLotCreateCommand,
  PositionLotPage,
  SymbolDetailResponse,
  SymbolEventPage,
  components,
} from "../../src/api/generated";

type PositionLot =
  components["schemas"]["trade_plan_monitor__web__routers__positions__PositionLotView"];

interface RequestRecord {
  idempotencyKeyPresent: boolean;
  jsonContentTypePresent: boolean;
  method: string;
  path: string;
}

export interface JourneySnapshot {
  acknowledged: boolean;
  alertCount: number;
  mutations: readonly RequestRecord[];
  positionCount: number;
}

export interface JourneyFixture {
  baseUrl: string;
  snapshot(): JourneySnapshot;
}

interface JourneyState {
  activePlan: ActivePlanView;
  alert: AlertView;
  extraction: PlanExtractionView;
  positionLots: PositionLot[];
  provider: AIProviderView;
  replayReady: boolean;
  requests: RequestRecord[];
  version: PlanVersionView | null;
}

const symbol = "003043.SZ";
const providerId = "00000000-0000-4000-8000-000000000001";
const extractionId = "00000000-0000-4000-8000-000000000002";
const versionId = "00000000-0000-4000-8000-000000000003";
const alertId = "00000000-0000-4000-8000-000000000004";
const lotId = "00000000-0000-4000-8000-000000000005";
const marketTime = "2026-08-24T10:05:00+08:00";
const observedAt = "2026-08-24T10:05:05+08:00";

export const reviewedPlanJson = JSON.stringify({
  activation: { mode: "MANUAL" },
  blockers: { condition: { conditions: [], type: "ALL" } },
  entry: { condition: { conditions: [], type: "ALL" } },
  levels: {
    low_buy: { high_fen: 6450, include_high: true, include_low: true, low_fen: 6300 },
    pressure: { high_fen: 7020, include_high: true, include_low: true, low_fen: 6880 },
    pressure_reference_fen: 6906,
    risk_line_fen: 6080,
  },
  market: "SZSE",
  metadata: { reference_price_fen: 6660, report_at: "2026-08-24T09:00:00+08:00" },
  monitoring: { indicator_formula_version: "ta-v1", timeframe_minutes: 5 },
  name: "华亚智能浏览器旅程方案",
  plan_id: "huaya-smart-e2e",
  position: {
    core_target_qty: 100,
    lot_size: 100,
    max_qty: 200,
    tactical_target_qty: 100,
  },
  reduction: { condition: { conditions: [], type: "ALL" } },
  risk: { condition: { level: "RISK_LINE", type: "OFFICIAL_CLOSE_BELOW_LEVEL" } },
  schema_version: 1,
  symbol,
  version: 1,
});

const initialProvider: AIProviderView = {
  config: {
    baseUrl: "https://fake-ai.example.test/v1",
    displayName: "确定性假 AI",
    model: "fake-review-model-v1",
    providerId,
    secretReference: { key: "ai/provider/e2e" },
  },
  createdAt: "2026-08-24T09:00:00+08:00",
  revision: 0,
  secretStatus: {
    configured: false,
    generation: 0,
    maskedValue: null,
    source: "NONE",
  },
  updatedAt: "2026-08-24T09:00:00+08:00",
};

const extraction: PlanExtractionView = {
  assumptions: [],
  completedAt: "2026-08-24T09:02:01+08:00",
  draftPlanJson: reviewedPlanJson,
  evidence: [
    {
      end: 21,
      excerpt: "华亚智能 6300 至 6450 分批关注",
      path: "levels.low_buy",
      start: 0,
    },
  ],
  id: extractionId,
  model: "fake-review-model-v1",
  promptVersion: "plan-extract-v1",
  providerId,
  sourceTextSha256: "a".repeat(64),
  startedAt: "2026-08-24T09:02:00+08:00",
  status: "SUCCEEDED",
  submittedAt: "2026-08-24T09:01:59+08:00",
  unmappedText: [],
  usage: { completionTokens: 80, promptTokens: 160, totalTokens: 240 },
  validationIssues: [],
  warnings: [
    {
      material: true,
      message: "报告时间由人工核对后确认。",
      path: "metadata.report_at",
    },
  ],
};

const initialActivePlan: ActivePlanView = {
  active: false,
  changedAt: "2026-08-24T09:00:00+08:00",
  planVersionId: null,
  revision: 0,
  symbol,
};

const initialAlert: AlertView = {
  acknowledgedAt: null,
  blockers: [],
  bucket: "CORE",
  causeId: "episode-e2e-1",
  createdAt: observedAt,
  dataAgeSeconds: 5,
  dedupKey: "b".repeat(64),
  evaluatedAt: marketTime,
  eventId: alertId,
  marketDataAt: marketTime,
  matchedConditions: [
    {
      children: [],
      code: "PRICE_IN_ZONE",
      facts: [{ key: "current_price_fen", unit: "FEN", value: 6420 }],
      kind: "CONDITION",
      missingInputs: [],
      outcome: "SATISFIED",
    },
  ],
  messageText: "价格进入底仓关注区，等待人工确认真实成交。",
  name: "华亚智能",
  nextStep: { code: "RECORD_CONFIRMED_FILL", requiredInputs: [] },
  planHash: "c".repeat(64),
  planId: "huaya-smart-e2e",
  planVersion: 1,
  positionPrefill: {
    action: "BUY",
    bucket: "CORE",
    quantity: 100,
    relatedAlertId: alertId,
    symbol,
    targetLotId: null,
  },
  priceFen: 6420,
  quantity: 100,
  relevantZone: {
    highFen: 6450,
    includeHigh: true,
    includeLow: true,
    lowFen: 6300,
    zone: "LOW_BUY",
  },
  revision: 0,
  riskLineFen: 6080,
  satisfiedConditions: [],
  sequence: 1,
  severity: "ACTION",
  signalType: "BUY_CORE_READY",
  symbol,
  targetLotId: null,
  tradingDate: "2026-08-24",
  unmetConditions: [],
  zone: "LOW_BUY",
};

const symbolDetail: SymbolDetailResponse = {
  positionLots: [],
  summary: {
    connected: true,
    decision: {
      dataAgeSeconds: 5,
      dataHealth: {
        dataAgeSeconds: 5,
        fresh: true,
        latestBarEnd: marketTime,
        requiredDataComplete: true,
        status: "LIVE",
      },
      episodeLowFen: 6320,
      episodeStatus: "ALERTED",
      evaluatedAt: observedAt,
      evidence: initialAlert.matchedConditions,
      marketDataAt: marketTime,
      nextStep: initialAlert.nextStep,
      planHash: initialAlert.planHash,
      planId: initialAlert.planId,
      planVersion: initialAlert.planVersion,
      position: {
        coreQuantity: 0,
        sellableCoreQuantity: 0,
        sellableTacticalQuantity: 0,
        tacticalQuantity: 0,
        totalQuantity: 0,
      },
      priceFen: 6420,
      resultHash: "d".repeat(64),
      riskBreachTradeDate: null,
      riskStatus: "CLEAR",
      signalType: "BUY_CORE_READY",
      symbol,
      zone: "LOW_BUY",
    },
    name: "华亚智能",
    observedAt,
    riskDistanceFen: 340,
    satisfiedConditionCount: 1,
    symbol,
    totalConditionCount: 1,
  },
};

const barPage: BarPage = {
  endAt: marketTime,
  items: [
    {
      amountYuan: "642000.00",
      barEnd: marketTime,
      closeFen: 6420,
      formulaVersion: "ta-v1",
      highFen: 6440,
      interval: "FIVE_MINUTES",
      lowFen: 6380,
      openFen: 6400,
      receivedAt: observedAt,
      symbol,
      volumeShares: 10000,
    },
  ],
  limit: 100,
  offset: 0,
  startAt: "2026-08-24T09:30:00+08:00",
  total: 1,
};

const eventPage: SymbolEventPage = {
  endAt: observedAt,
  items: [
    {
      eventId: alertId,
      eventType: "ALERT",
      messageText: initialAlert.messageText,
      occurredAt: observedAt,
      resultHash: symbolDetail.summary.decision.resultHash,
      sequence: 1,
      signalType: "BUY_CORE_READY",
      symbol,
    },
  ],
  limit: 100,
  offset: 0,
  startAt: "2026-08-24T09:30:00+08:00",
  total: 1,
};

export const test = base.extend<{ journey: JourneyFixture }>({
  journey: async ({}, use) => {
    const state: JourneyState = {
      activePlan: structuredClone(initialActivePlan),
      alert: structuredClone(initialAlert),
      extraction: structuredClone(extraction),
      positionLots: [],
      provider: structuredClone(initialProvider),
      replayReady: false,
      requests: [],
      version: null,
    };
    const server = await createServer({
      clearScreen: false,
      logLevel: "silent",
      plugins: [
        {
          configureServer(viteServer) {
            viteServer.middlewares.use(async (request, response, next) => {
              const requestUrl = new URL(request.url ?? "/", "http://127.0.0.1");
              if (!requestUrl.pathname.startsWith("/api/v1/")) {
                next();
                return;
              }
              const method = request.method ?? "GET";
              const contentType = headerValue(request.headers["content-type"]);
              const idempotencyKey = headerValue(request.headers["idempotency-key"]);
              const record: RequestRecord = {
                idempotencyKeyPresent:
                  idempotencyKey !== null &&
                  /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(idempotencyKey),
                jsonContentTypePresent: contentType?.split(";", 1)[0] === "application/json",
                method,
                path: requestUrl.pathname,
              };
              state.requests.push(record);
              try {
                const result = await handleApiRequest(
                  state,
                  requestUrl,
                  method,
                  request,
                  record,
                );
                sendJson(response, result.status, result.body);
              } catch (caught: unknown) {
                sendJson(response, 400, {
                  error: {
                    code: "BAD_REQUEST",
                    details: [],
                    message: caught instanceof Error ? caught.message : "invalid fixture request",
                    requestId: "t055-fixture",
                  },
                });
              }
            });
          },
          name: "t055-api-fixture",
        },
      ],
      root: process.cwd(),
      server: { host: "127.0.0.1", port: 0 },
    });
    await server.listen();
    const address = server.httpServer?.address();
    if (address === null || address === undefined || typeof address === "string") {
      await server.close();
      throw new Error("T055 journey fixture did not expose a local port");
    }
    try {
      await use({
        baseUrl: `http://127.0.0.1:${address.port}`,
        snapshot: () => ({
          acknowledged: state.alert.acknowledgedAt !== null,
          alertCount: state.replayReady ? 1 : 0,
          mutations: state.requests.filter((request) => request.method === "POST"),
          positionCount: state.positionLots.length,
        }),
      });
    } finally {
      await server.close();
    }
  },
});

export { expect };

async function handleApiRequest(
  state: JourneyState,
  requestUrl: URL,
  method: string,
  request: NodeJS.ReadableStream,
  record: RequestRecord,
): Promise<{ body: unknown; status: number }> {
  const path = requestUrl.pathname;
  if (method === "GET" && path === "/api/v1/ai-providers") {
    const page: AIProviderPage = { items: [state.provider], limit: 20, offset: 0, total: 1 };
    return ok(page);
  }
  if (method === "POST" && path === "/api/v1/ai-provider-secrets") {
    requireMutationHeaders(record);
    const command = await readJson<AIProviderSecretCommand>(request);
    invariant(command.providerId === providerId, "secret provider mismatch");
    invariant(command.expectedRevision === state.provider.revision, "secret revision mismatch");
    invariant(command.secret.value === "sk-fake-e2e", "unexpected fake secret");
    state.provider = {
      ...state.provider,
      revision: state.provider.revision + 1,
      secretStatus: {
        configured: true,
        generation: 1,
        maskedValue: "********",
        source: "STORE",
      },
      updatedAt: "2026-08-24T09:01:00+08:00",
    };
    return ok(state.provider);
  }
  if (method === "POST" && path === "/api/v1/ai-provider-tests") {
    requireMutationHeaders(record);
    const command = await readJson<AIProviderTestCommand>(request);
    invariant(command.providerId === providerId, "test provider mismatch");
    invariant(command.expectedRevision === state.provider.revision, "test revision mismatch");
    const receipt: OperationReceipt = {
      kind: "AI_PROVIDER_TEST",
      operationId: "00000000-0000-4000-8000-000000000006",
      status: "QUEUED",
      submittedAt: "2026-08-24T09:01:30+08:00",
    };
    return { body: receipt, status: 202 };
  }
  if (method === "POST" && path === "/api/v1/plan-extractions") {
    requireMutationHeaders(record);
    const command = await readJson<PlanExtractionCommand>(request);
    invariant(command.expectedRevision === 0, "extraction revision mismatch");
    invariant(command.providerId === providerId, "extraction provider mismatch");
    invariant(command.sourceText.includes("华亚智能"), "source text mismatch");
    const receipt: OperationReceipt = {
      kind: "PLAN_EXTRACTION",
      operationId: extractionId,
      status: "QUEUED",
      submittedAt: state.extraction.submittedAt,
    };
    return { body: receipt, status: 202 };
  }
  if (method === "GET" && path === `/api/v1/plan-extractions/${extractionId}`) {
    return ok(state.extraction);
  }
  if (method === "POST" && path === "/api/v1/plan-drafts") {
    requireMutationHeaders(record);
    const command = await readJson<PlanDraftCommand>(request);
    invariant(command.expectedRevision === 0, "draft revision mismatch");
    invariant(command.planJson === reviewedPlanJson, "draft plan mismatch");
    invariant(command.sourceText.includes("华亚智能"), "draft source mismatch");
    invariant(
      command.reviewIssues?.some(
        (issue) =>
          issue.kind === "WARNING" &&
          issue.path === "metadata.report_at" &&
          issue.material &&
          issue.resolved === true,
      ) === true,
      "material warning was not resolved",
    );
    state.version = {
      canActivate: true,
      createdAt: "2026-08-24T09:03:00+08:00",
      id: versionId,
      planHash: "c".repeat(64),
      planId: "huaya-smart-e2e",
      planJson: command.planJson,
      reviewIssues: command.reviewIssues,
      revision: 1,
      sourceText: command.sourceText,
      status: "DRAFT",
      symbol,
      validationIssues: [],
      version: 1,
    };
    return ok(state.version);
  }
  if (method === "POST" && path === "/api/v1/plan-activations") {
    requireMutationHeaders(record);
    const command = await readJson<PlanActivationCommand>(request);
    invariant(
      command.expectedRevision === state.activePlan.revision,
      "activation revision mismatch",
    );
    invariant(command.planVersionId === state.version?.id, "activation plan mismatch");
    state.activePlan = {
      active: true,
      changedAt: "2026-08-24T09:04:00+08:00",
      planVersionId: command.planVersionId,
      revision: state.activePlan.revision + 1,
      symbol,
    };
    return ok(state.activePlan);
  }
  if (method === "GET" && path === `/api/v1/symbols/${symbol}`) {
    requireActivePlan(state);
    return ok(symbolDetail);
  }
  if (method === "GET" && path === `/api/v1/symbols/${symbol}/bars`) {
    requireActivePlan(state);
    invariant(requestUrl.searchParams.get("interval") === "FIVE_MINUTES", "bar interval mismatch");
    state.replayReady = true;
    return ok(barPage);
  }
  if (method === "GET" && path === `/api/v1/symbols/${symbol}/events`) {
    invariant(state.replayReady, "events requested before market replay");
    return ok(eventPage);
  }
  if (method === "GET" && path === "/api/v1/alerts") {
    invariant(state.replayReady, "alerts requested before market replay");
    return ok(alertPage(state));
  }
  if (method === "POST" && path === "/api/v1/alert-acknowledgements") {
    requireMutationHeaders(record);
    const command = await readJson<AlertAcknowledgementCommand>(request);
    invariant(command.alertId === alertId, "acknowledgement alert mismatch");
    invariant(
      command.expectedRevision === state.alert.revision,
      "acknowledgement revision mismatch",
    );
    state.alert = {
      ...state.alert,
      acknowledgedAt: "2026-08-24T10:06:00+08:00",
      revision: 1,
    };
    return ok(state.alert);
  }
  if (method === "GET" && path === "/api/v1/position-lots") {
    invariant(requestUrl.searchParams.get("symbol") === symbol, "position symbol mismatch");
    invariant(
      requestUrl.searchParams.get("asOfTradeDate") === "2026-08-24",
      "position trade date mismatch",
    );
    return ok(positionPage(state));
  }
  if (method === "POST" && path === "/api/v1/position-lots") {
    requireMutationHeaders(record);
    const command = await readJson<PositionLotCreateCommand>(request);
    invariant(state.alert.acknowledgedAt !== null, "position created before alert acknowledgement");
    invariant(command.expectedRevision === 0, "position revision mismatch");
    invariant(command.symbol === symbol, "position symbol mismatch");
    invariant(command.bucket === "CORE", "position bucket mismatch");
    invariant(command.quantity === 100, "position quantity mismatch");
    invariant(command.costFen === 6420, "position cost mismatch");
    invariant(command.acquiredTradeDate === "2026-08-24", "position date mismatch");
    invariant(command.relatedAlertId === alertId, "position alert relation mismatch");
    const lot: PositionLot = {
      acquiredTradeDate: command.acquiredTradeDate,
      bucket: command.bucket,
      closedAt: null,
      costFen: command.costFen,
      lotId,
      quantity: command.quantity,
      relatedAlertId: command.relatedAlertId,
      remainingQuantity: command.quantity,
      revision: 0,
      sellableQuantity: 0,
      symbol,
    };
    state.positionLots.push(lot);
    return ok(lot);
  }
  throw new Error(`unsupported API request: ${method} ${path}`);
}

function alertPage(state: JourneyState): AlertPage {
  return {
    acknowledged: null,
    endAt: null,
    items: [state.alert],
    limit: 20,
    offset: 0,
    signalType: null,
    startAt: null,
    symbol: null,
    total: 1,
  };
}

function positionPage(state: JourneyState): PositionLotPage {
  return {
    asOfTradeDate: "2026-08-24",
    items: structuredClone(state.positionLots),
    limit: 100,
    offset: 0,
    symbol,
    total: state.positionLots.length,
  };
}

function requireActivePlan(state: JourneyState): void {
  invariant(state.activePlan.active, "market data requested before plan activation");
}

function requireMutationHeaders(record: RequestRecord): void {
  invariant(record.idempotencyKeyPresent, `missing Idempotency-Key for ${record.path}`);
  invariant(record.jsonContentTypePresent, `missing JSON Content-Type for ${record.path}`);
}

function headerValue(value: string | readonly string[] | undefined): string | null {
  return typeof value === "string" ? value : null;
}

function invariant(condition: boolean, message: string): asserts condition {
  if (!condition) {
    throw new Error(message);
  }
}

function ok<Value>(body: Value): { body: Value; status: number } {
  return { body, status: 200 };
}

async function readJson<Value>(request: NodeJS.ReadableStream): Promise<Value> {
  const chunks: Buffer[] = [];
  for await (const chunk of request) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8")) as Value;
}

function sendJson(
  response: {
    end(body: string): void;
    setHeader(name: string, value: string): void;
    statusCode: number;
  },
  status: number,
  body: unknown,
): void {
  response.statusCode = status;
  response.setHeader("Content-Type", "application/json; charset=utf-8");
  response.end(JSON.stringify(body));
}
