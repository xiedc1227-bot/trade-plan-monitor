import type {
  ApiErrorCode,
  DashboardResponse,
  ErrorDetail,
  ErrorPayload,
  ErrorResponse,
} from "./generated";

const MAX_RESPONSE_BYTES = 4 * 1024 * 1024;
const MAX_ERROR_DETAILS = 100;
const MAX_ERROR_TEXT_CHARACTERS = 256;
const MAX_SEQUENCE = Number.MAX_SAFE_INTEGER;
const MAX_VALIDATION_DEPTH = 32;
const MAX_VALIDATION_NODES = 50_000;

const safeErrorMessages: Record<ApiErrorCode, string> = {
  BAD_REQUEST: "请求格式无效",
  CONFLICT: "请求与当前状态冲突",
  FORBIDDEN: "请求被拒绝",
  INTERNAL_ERROR: "本地监控服务发生内部错误",
  METHOD_NOT_ALLOWED: "请求方法不受支持",
  NOT_FOUND: "请求的资源不存在",
  PAYLOAD_TOO_LARGE: "请求内容过大",
  RATE_LIMITED: "请求过于频繁，请稍后重试",
  SERVICE_UNAVAILABLE: "本地监控服务暂不可用",
  UNAUTHORIZED: "请求未获授权",
  VALIDATION_ERROR: "请求内容未通过校验",
};

const apiErrorCodes = new Set<ApiErrorCode>([
  "BAD_REQUEST",
  "VALIDATION_ERROR",
  "UNAUTHORIZED",
  "FORBIDDEN",
  "NOT_FOUND",
  "METHOD_NOT_ALLOWED",
  "CONFLICT",
  "PAYLOAD_TOO_LARGE",
  "RATE_LIMITED",
  "SERVICE_UNAVAILABLE",
  "INTERNAL_ERROR",
]);

const dataHealthStatuses = new Set([
  "STARTING",
  "LIVE",
  "STALE",
  "GAPPED",
  "DEGRADED",
  "BLOCKED",
  "CLOSE_PENDING",
]);
const decisionZones = new Set([
  "LOW_BUY",
  "OBSERVATION",
  "PRESSURE",
  "BELOW_RISK",
  "OUTSIDE",
  "UNKNOWN",
]);
const signalTypes = new Set([
  "WAIT",
  "LOW_ZONE_WATCH",
  "BLOCKED_DATA",
  "BLOCKED_RISK",
  "BUY_CORE_READY",
  "BUY_TACTICAL_READY",
  "PRESSURE_REDUCE_READY",
  "RISK_BREACH",
  "RISK_RECOVERED",
  "RISK_EXIT_READY",
  "RISK_EXIT_PENDING_SETTLEMENT",
]);
const actionableSignalTypes = new Set([
  "BUY_CORE_READY",
  "BUY_TACTICAL_READY",
  "PRESSURE_REDUCE_READY",
  "RISK_BREACH",
  "RISK_EXIT_READY",
  "RISK_EXIT_PENDING_SETTLEMENT",
]);
const riskStatuses = new Set([
  "CLEAR",
  "BREACHED_PENDING_CONFIRMATION",
  "EXIT_PENDING_SETTLEMENT",
]);
const nextStepCodes = new Set([
  "WAIT_FOR_COMPLETE_BAR",
  "WAIT_FOR_REQUIRED_DATA",
  "WATCH_LOW_ZONE",
  "WATCH_PRESSURE",
  "REVIEW_BLOCKER",
  "WAIT_FOR_OFFICIAL_CLOSE",
  "WAIT_FOR_NEXT_TRADING_DAY",
  "WAIT_FOR_SETTLEMENT",
  "RECORD_CONFIRMED_FILL",
]);
const missingInputCodes = new Set([
  "COMPLETE_MINUTE_BAR",
  "PREVIOUS_MINUTE_BAR",
  "COMPLETE_5M_BAR",
  "PREVIOUS_5M_BAR",
  "COMPLETE_5M_BAR_WINDOW",
  "ROLLING_VOLUME_WINDOW",
  "SESSION_BARS",
  "DAILY_INDICATORS",
  "PROVISIONAL_DAILY_BAR",
  "FIVE_MINUTE_INDICATORS",
  "INDICATOR_VALUE",
  "OFFICIAL_DAILY_CLOSE",
  "TRADING_CALENDAR",
  "DAILY_LIMIT",
  "MANUAL_EVENT_RISK",
]);
const evidenceKinds = new Set(["CONDITION", "RULE"]);
const conditionOutcomes = new Set(["SATISFIED", "UNSATISFIED", "MISSING_INPUT"]);
const evidenceUnits = new Set([
  "FEN",
  "SHARES",
  "RATIO",
  "BARS",
  "YUAN",
  "COUNT",
  "BOOLEAN",
  "DATE",
  "DATETIME",
  "CODE",
]);

export type ApiClientErrorCode = ApiErrorCode | "INVALID_RESPONSE" | "NETWORK_ERROR";

interface ApiClientErrorOptions {
  code: ApiClientErrorCode;
  details?: readonly ErrorDetail[] | undefined;
  message: string;
  requestId?: string | undefined;
  status: number;
}

export class ApiClientError extends Error {
  readonly code: ApiClientErrorCode;
  readonly details: readonly ErrorDetail[];
  readonly requestId: string | undefined;
  readonly status: number;

  constructor(options: ApiClientErrorOptions) {
    super(options.message);
    this.name = "ApiClientError";
    this.code = options.code;
    this.details = Object.freeze([...(options.details ?? [])]);
    this.requestId = options.requestId;
    this.status = options.status;
  }
}

export interface ApiClient {
  getDashboard(options?: { signal?: AbortSignal }): Promise<DashboardResponse>;
}

export function createApiClient(
  fetchImplementation: typeof fetch = globalThis.fetch.bind(globalThis),
): ApiClient {
  return Object.freeze({
    async getDashboard(options?: { signal?: AbortSignal }) {
      const request: RequestInit = {
        headers: { Accept: "application/json" },
        method: "GET",
      };
      if (options?.signal !== undefined) {
        request.signal = options.signal;
      }

      let response: Response;
      try {
        response = await fetchImplementation("/api/v1/dashboard", request);
      } catch {
        throw new ApiClientError({
          code: "NETWORK_ERROR",
          message: "无法连接本地监控服务",
          status: 0,
        });
      }

      const body = await readJson(response);
      if (!response.ok) {
        throw parseErrorResponse(body, response.status);
      }
      try {
        if (!isDashboardResponse(body)) {
          throw invalidResponse(response.status);
        }
        return deepFreeze(body);
      } catch (error) {
        if (error instanceof ApiClientError) {
          throw error;
        }
        throw invalidResponse(response.status);
      }
    },
  });
}

async function readJson(response: Response): Promise<unknown> {
  const contentLength = response.headers.get("Content-Length");
  if (
    contentLength !== null &&
    /^\d+$/.test(contentLength) &&
    Number(contentLength) > MAX_RESPONSE_BYTES
  ) {
    await response.body?.cancel().catch(() => undefined);
    throw invalidResponse(response.status);
  }

  const stream = response.body;
  if (stream === null) {
    throw invalidResponse(response.status);
  }
  const reader = stream.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let body = "";
  let receivedBytes = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        body += decoder.decode();
        break;
      }
      if (value.byteLength > MAX_RESPONSE_BYTES - receivedBytes) {
        await reader.cancel().catch(() => undefined);
        throw invalidResponse(response.status);
      }
      receivedBytes += value.byteLength;
      body += decoder.decode(value, { stream: true });
    }
  } catch (error) {
    await reader.cancel().catch(() => undefined);
    if (error instanceof ApiClientError) {
      throw error;
    }
    throw invalidResponse(response.status);
  } finally {
    reader.releaseLock();
  }
  try {
    return JSON.parse(body) as unknown;
  } catch {
    throw invalidResponse(response.status);
  }
}

function parseErrorResponse(value: unknown, status: number): ApiClientError {
  if (!isErrorResponse(value)) {
    return invalidResponse(status);
  }
  const payload: ErrorPayload = value.error;
  const details = payload.details?.map((detail) =>
    deepFreeze({
      code: detail.code,
      location: [...detail.location],
      message: "请求字段无效",
    }),
  );
  return new ApiClientError({
    code: payload.code,
    details,
    message: safeErrorMessages[payload.code],
    requestId: payload.requestId,
    status,
  });
}

function invalidResponse(status: number): ApiClientError {
  return new ApiClientError({
    code: "INVALID_RESPONSE",
    message: "本地监控服务返回了无效响应",
    status,
  });
}

function isDashboardResponse(value: unknown): value is DashboardResponse {
  if (
    !isRecord(value) ||
    containsSensitiveKey(value) ||
    !hasOnlyKeys(value, [
      "connectionStatus",
      "counts",
      "dataAgeSeconds",
      "observedAt",
      "sequence",
      "symbols",
    ])
  ) {
    return false;
  }
  const counts = value.counts;
  const symbols = value.symbols;
  return (
    (value.connectionStatus === "CONNECTED" ||
      value.connectionStatus === "DISCONNECTED" ||
      value.connectionStatus === "UNKNOWN") &&
    isNullableNonnegativeInteger(value.dataAgeSeconds) &&
    isShanghaiDateTime(value.observedAt) &&
    isSafeSequence(value.sequence) &&
    isDashboardCounts(counts) &&
    isDashboardSymbols(symbols, value.connectionStatus, value.observedAt)
  );
}

function isDashboardCounts(value: unknown): boolean {
  const keys = ["actionable", "blocked", "lowZoneWatch", "normal", "risk", "stale"];
  if (!isRecord(value) || !hasExactKeys(value, keys)) {
    return false;
  }
  return keys.every((key) => isNonnegativeInteger(value[key]));
}

function isSymbolSummary(value: unknown): boolean {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "connected",
      "decision",
      "name",
      "observedAt",
      "riskDistanceFen",
      "satisfiedConditionCount",
      "symbol",
      "totalConditionCount",
    ]) ||
    typeof value.connected !== "boolean" ||
    !isAuthoritativeDecision(value.decision) ||
    !isBoundedString(value.name, 128) ||
    !isShanghaiDateTime(value.observedAt) ||
    !isNullableInteger(value.riskDistanceFen) ||
    !isNonnegativeInteger(value.satisfiedConditionCount) ||
    !isShareSymbol(value.symbol) ||
    !isNonnegativeInteger(value.totalConditionCount)
  ) {
    return false;
  }
  const decision = value.decision as Record<string, unknown>;
  return (
    decision.symbol === value.symbol &&
    (value.satisfiedConditionCount as number) <= (value.totalConditionCount as number) &&
    shanghaiDateTimeKey(value.observedAt) >=
      shanghaiDateTimeKey(decision.evaluatedAt as string) &&
    (value.connected || (decision.dataHealth as Record<string, unknown>).status !== "LIVE")
  );
}

function isErrorResponse(value: unknown): value is ErrorResponse {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["error"]) ||
    !isRecord(value.error) ||
    !hasOnlyKeys(value.error, ["code", "details", "message", "requestId"])
  ) {
    return false;
  }
  const error = value.error;
  return (
    typeof error.code === "string" &&
    apiErrorCodes.has(error.code as ApiErrorCode) &&
    isBoundedString(error.message, MAX_ERROR_TEXT_CHARACTERS) &&
    typeof error.requestId === "string" &&
    /^[0-9a-f]{32}$/.test(error.requestId) &&
    (error.details === undefined ||
      (Array.isArray(error.details) &&
        error.details.length <= MAX_ERROR_DETAILS &&
        error.details.every(isErrorDetail)))
  );
}

function isErrorDetail(value: unknown): value is ErrorDetail {
  return (
    isRecord(value) &&
    hasExactKeys(value, ["code", "location", "message"]) &&
    isStableCode(value.code) &&
    Array.isArray(value.location) &&
    value.location.length > 0 &&
    value.location.length <= 16 &&
    value.location.every(
      (part) =>
        (typeof part === "string" && isLocationPart(part)) ||
        (typeof part === "number" && Number.isSafeInteger(part) && part >= 0),
    ) &&
    isBoundedString(value.message, MAX_ERROR_TEXT_CHARACTERS)
  );
}

function isAuthoritativeDecision(value: unknown): boolean {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, [
      "dataAgeSeconds",
      "dataHealth",
      "episodeLowFen",
      "episodeStatus",
      "evaluatedAt",
      "evidence",
      "marketDataAt",
      "nextStep",
      "planHash",
      "planId",
      "planVersion",
      "position",
      "priceFen",
      "resultHash",
      "riskBreachTradeDate",
      "riskStatus",
      "signalType",
      "symbol",
      "zone",
    ])
  ) {
    return false;
  }
  const required = [
    "dataAgeSeconds",
    "dataHealth",
    "episodeLowFen",
    "episodeStatus",
    "evaluatedAt",
    "marketDataAt",
    "nextStep",
    "planHash",
    "planId",
    "planVersion",
    "position",
    "priceFen",
    "resultHash",
    "riskBreachTradeDate",
    "riskStatus",
    "signalType",
    "symbol",
    "zone",
  ];
  return (
    hasKeys(value, required) &&
    isNullableNonnegativeInteger(value.dataAgeSeconds) &&
    isDataHealth(value.dataHealth) &&
    isNullablePositiveInteger(value.episodeLowFen) &&
    (value.episodeStatus === null ||
      value.episodeStatus === "ACTIVE" ||
      value.episodeStatus === "ALERTED" ||
      value.episodeStatus === "CLOSED") &&
    isShanghaiDateTime(value.evaluatedAt) &&
    (value.evidence === undefined ||
      (Array.isArray(value.evidence) &&
        value.evidence.length <= 50 &&
        value.evidence.every((item) => isDecisionEvidence(item)))) &&
    (value.marketDataAt === null || isShanghaiDateTime(value.marketDataAt)) &&
    isNextStep(value.nextStep) &&
    isSha256(value.planHash) &&
    isBoundedString(value.planId, 128) &&
    isPositiveInteger(value.planVersion) &&
    isPositionSummary(value.position) &&
    isNullablePositiveInteger(value.priceFen) &&
    isSha256(value.resultHash) &&
    (value.riskBreachTradeDate === null || isCalendarDate(value.riskBreachTradeDate)) &&
    typeof value.riskStatus === "string" &&
    riskStatuses.has(value.riskStatus) &&
    typeof value.signalType === "string" &&
    signalTypes.has(value.signalType) &&
    isShareSymbol(value.symbol) &&
    typeof value.zone === "string" &&
    decisionZones.has(value.zone) &&
    validateDecisionRelationships(value)
  );
}

function isDataHealth(value: unknown): boolean {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "dataAgeSeconds",
      "fresh",
      "latestBarEnd",
      "requiredDataComplete",
      "status",
    ]) ||
    !isNullableNonnegativeInteger(value.dataAgeSeconds) ||
    typeof value.fresh !== "boolean" ||
    !(value.latestBarEnd === null || isShanghaiDateTime(value.latestBarEnd)) ||
    typeof value.requiredDataComplete !== "boolean" ||
    typeof value.status !== "string" ||
    !dataHealthStatuses.has(value.status)
  ) {
    return false;
  }
  if ((value.latestBarEnd === null) !== (value.dataAgeSeconds === null)) {
    return false;
  }
  if (value.fresh && value.latestBarEnd === null) {
    return false;
  }
  if (
    value.status === "LIVE" &&
    (!value.fresh || !value.requiredDataComplete || value.latestBarEnd === null)
  ) {
    return false;
  }
  if (value.status === "STALE" && value.fresh) {
    return false;
  }
  return !(
    (value.status === "GAPPED" || value.status === "BLOCKED") &&
    value.requiredDataComplete
  );
}

function isNextStep(value: unknown): boolean {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["code", "notBefore", "requiredInputs"]) &&
    hasKeys(value, ["code"]) &&
    typeof value.code === "string" &&
    nextStepCodes.has(value.code) &&
    (value.notBefore === undefined ||
      value.notBefore === null ||
      isCalendarDate(value.notBefore) ||
      isShanghaiDateTime(value.notBefore)) &&
    (value.requiredInputs === undefined ||
      (Array.isArray(value.requiredInputs) &&
        value.requiredInputs.length <= 16 &&
        new Set(value.requiredInputs).size === value.requiredInputs.length &&
        value.requiredInputs.every(
          (item) => typeof item === "string" && missingInputCodes.has(item),
        )))
  );
}

function isPositionSummary(value: unknown): boolean {
  const keys = [
    "coreQuantity",
    "sellableCoreQuantity",
    "sellableTacticalQuantity",
    "tacticalQuantity",
    "totalQuantity",
  ];
  if (!isRecord(value) || !hasExactKeys(value, keys) || !keys.every((key) => isNonnegativeInteger(value[key]))) {
    return false;
  }
  const coreQuantity = value.coreQuantity as number;
  const tacticalQuantity = value.tacticalQuantity as number;
  return (
    value.totalQuantity === coreQuantity + tacticalQuantity &&
    (value.sellableCoreQuantity as number) <= coreQuantity &&
    (value.sellableTacticalQuantity as number) <= tacticalQuantity
  );
}

function isDecisionEvidence(value: unknown, depth = 0): boolean {
  if (depth > MAX_VALIDATION_DEPTH) {
    return false;
  }
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["children", "code", "facts", "kind", "missingInputs", "outcome"]) &&
    hasKeys(value, ["code", "kind", "outcome"]) &&
    isStableCode(value.code) &&
    typeof value.kind === "string" &&
    evidenceKinds.has(value.kind) &&
    typeof value.outcome === "string" &&
    conditionOutcomes.has(value.outcome) &&
    (value.children === undefined ||
      (Array.isArray(value.children) &&
        value.children.length <= 50 &&
        value.children.every((child) => isDecisionEvidence(child, depth + 1)))) &&
    (value.facts === undefined ||
      (Array.isArray(value.facts) && value.facts.length <= 512 && value.facts.every(isEvidenceFact))) &&
    (value.missingInputs === undefined ||
      (Array.isArray(value.missingInputs) &&
        value.missingInputs.length <= 16 &&
        value.missingInputs.every(
          (item) => typeof item === "string" && missingInputCodes.has(item),
        )))
  ) && validateEvidenceRelationships(value);
}

function isEvidenceFact(value: unknown): boolean {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["key", "unit", "value"]) ||
    !isEvidenceKey(value.key) ||
    typeof value.unit !== "string" ||
    !evidenceUnits.has(value.unit)
  ) {
    return false;
  }
  if (value.unit === "BOOLEAN") {
    return typeof value.value === "boolean";
  }
  if (value.unit === "DATE") {
    return isCalendarDate(value.value);
  }
  if (value.unit === "DATETIME") {
    return isShanghaiDateTime(value.value);
  }
  if (value.unit === "CODE") {
    return isStableCode(value.value);
  }
  if (value.unit === "FEN" || value.unit === "BARS" || value.unit === "COUNT") {
    return typeof value.value === "number" && Number.isSafeInteger(value.value);
  }
  if (value.unit === "RATIO" || value.unit === "YUAN") {
    return isDecimalString(value.value);
  }
  return (
    value.unit === "SHARES" &&
    ((typeof value.value === "number" && Number.isSafeInteger(value.value)) ||
      isDecimalString(value.value))
  );
}

function validateEvidenceRelationships(value: Record<string, unknown>): boolean {
  const facts = Array.isArray(value.facts) ? value.facts : [];
  const missingInputs = Array.isArray(value.missingInputs) ? value.missingInputs : [];
  const children = Array.isArray(value.children) ? value.children : [];
  if (
    new Set(facts.map((fact) => (fact as Record<string, unknown>).key)).size !== facts.length ||
    new Set(missingInputs).size !== missingInputs.length
  ) {
    return false;
  }
  if (value.outcome === "MISSING_INPUT") {
    return (
      missingInputs.length > 0 ||
      children.some(
        (child) => (child as Record<string, unknown>).outcome === "MISSING_INPUT",
      )
    );
  }
  return missingInputs.length === 0;
}

function isDashboardSymbols(
  value: unknown,
  connectionStatus: unknown,
  observedAt: unknown,
): boolean {
  if (value === undefined) {
    return true;
  }
  if (
    !Array.isArray(value) ||
    value.length > 10 ||
    !value.every(isSymbolSummary) ||
    typeof observedAt !== "string"
  ) {
    return false;
  }
  const symbols = value as Array<Record<string, unknown>>;
  if (new Set(symbols.map((item) => item.symbol)).size !== symbols.length) {
    return false;
  }
  return symbols.every(
    (item) =>
      shanghaiDateTimeKey(item.observedAt as string) <= shanghaiDateTimeKey(observedAt) &&
      !(
        connectionStatus === "DISCONNECTED" &&
        ((item.decision as Record<string, unknown>).dataHealth as Record<string, unknown>)
          .status === "LIVE"
      ),
  );
}

function validateDecisionRelationships(value: Record<string, unknown>): boolean {
  const marketValues = [value.marketDataAt, value.dataAgeSeconds, value.priceFen];
  if (marketValues.some((item) => item === null) && marketValues.some((item) => item !== null)) {
    return false;
  }
  if ((value.episodeStatus === null) !== (value.episodeLowFen === null)) {
    return false;
  }
  if (
    (value.riskStatus === "CLEAR" && value.riskBreachTradeDate !== null) ||
    (value.riskStatus !== "CLEAR" && value.riskBreachTradeDate === null)
  ) {
    return false;
  }
  const dataHealth = value.dataHealth as Record<string, unknown>;
  if (actionableSignalTypes.has(value.signalType as string) && dataHealth.status !== "LIVE") {
    return false;
  }
  const evaluatedAt = shanghaiDateTimeKey(value.evaluatedAt as string);
  if (
    value.marketDataAt !== null &&
    !matchesIntegerSecondAge(
      evaluatedAt,
      shanghaiDateTimeKey(value.marketDataAt as string),
      value.dataAgeSeconds as number,
    )
  ) {
    return false;
  }
  if (
    dataHealth.latestBarEnd !== null &&
    !matchesIntegerSecondAge(
      evaluatedAt,
      shanghaiDateTimeKey(dataHealth.latestBarEnd as string),
      dataHealth.dataAgeSeconds as number,
    )
  ) {
    return false;
  }
  if (
    value.riskBreachTradeDate !== null &&
    (value.riskBreachTradeDate as string) > (value.evaluatedAt as string).slice(0, 10)
  ) {
    return false;
  }
  return true;
}

function matchesIntegerSecondAge(
  evaluatedAt: bigint,
  marketDataAt: bigint,
  dataAgeSeconds: number,
): boolean {
  const deltaMicroseconds = evaluatedAt - marketDataAt;
  return (
    deltaMicroseconds >= 0n && deltaMicroseconds / 1_000_000n === BigInt(dataAgeSeconds)
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasOnlyKeys(value: Record<string, unknown>, allowed: readonly string[]): boolean {
  const allowedKeys = new Set(allowed);
  return Object.keys(value).every((key) => allowedKeys.has(key));
}

function hasKeys(value: Record<string, unknown>, required: readonly string[]): boolean {
  return required.every((key) => Object.hasOwn(value, key));
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(value).length === keys.length && hasKeys(value, keys);
}

function containsSensitiveKey(value: unknown): boolean {
  const pending: Array<{ depth: number; value: unknown }> = [{ depth: 0, value }];
  let visited = 0;
  while (pending.length > 0) {
    const current = pending.pop();
    if (current === undefined) {
      break;
    }
    visited += 1;
    if (visited > MAX_VALIDATION_NODES || current.depth > MAX_VALIDATION_DEPTH) {
      return true;
    }
    if (Array.isArray(current.value)) {
      for (const child of current.value) {
        pending.push({ depth: current.depth + 1, value: child });
      }
      continue;
    }
    if (!isRecord(current.value)) {
      continue;
    }
    for (const [key, child] of Object.entries(current.value)) {
      const normalized = key.replaceAll(/[^a-z]/gi, "").toLowerCase();
      if (/(?:apikey|authorization|credential|password|secret|token)/.test(normalized)) {
        return true;
      }
      pending.push({ depth: current.depth + 1, value: child });
    }
  }
  return false;
}

function isStableCode(value: unknown): value is string {
  return typeof value === "string" && /^[A-Z][A-Z0-9_]{0,63}$/.test(value);
}

function isEvidenceKey(value: unknown): value is string {
  return typeof value === "string" && /^[a-z][a-z0-9_]{0,63}$/.test(value);
}

function isDecimalString(value: unknown): value is string {
  if (typeof value !== "string" || value.length === 0 || value.length > 10_000) {
    return false;
  }
  let index = value[0] === "+" || value[0] === "-" ? 1 : 0;
  let digits = 0;
  let decimalPointSeen = false;
  for (; index < value.length; index += 1) {
    const character = value[index];
    if (character === "." && !decimalPointSeen) {
      decimalPointSeen = true;
      continue;
    }
    if (character === undefined || character < "0" || character > "9") {
      return false;
    }
    digits += 1;
  }
  return digits > 0;
}

function isLocationPart(value: string): boolean {
  return /^[A-Za-z][A-Za-z0-9_.-]{0,63}$/.test(value);
}

function isSha256(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
}

function isBoundedString(value: unknown, maximum: number): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= maximum;
}

function isNonnegativeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && typeof value === "number" && value >= 0;
}

function isPositiveInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && typeof value === "number" && value > 0;
}

function isNullableNonnegativeInteger(value: unknown): boolean {
  return value === null || isNonnegativeInteger(value);
}

function isNullablePositiveInteger(value: unknown): boolean {
  return value === null || isPositiveInteger(value);
}

function isNullableInteger(value: unknown): boolean {
  return value === null || (typeof value === "number" && Number.isSafeInteger(value));
}

function isShareSymbol(value: unknown): value is string {
  return typeof value === "string" && /^\d{6}\.(?:BJ|SH|SZ)$/.test(value);
}

function isCalendarDate(value: unknown): value is string {
  if (typeof value !== "string") {
    return false;
  }
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  return match !== null && isGregorianDate(Number(match[1]), Number(match[2]), Number(match[3]));
}

function isShanghaiDateTime(value: unknown): value is string {
  return parseShanghaiDateTime(value) !== null;
}

function parseShanghaiDateTime(value: unknown): bigint | null {
  if (typeof value !== "string") {
    return null;
  }
  const match =
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?\+08:00$/.exec(
      value,
    );
  if (match === null) {
    return null;
  }
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6]);
  if (
    !isGregorianDate(year, month, day) ||
    hour > 23 ||
    minute > 59 ||
    second > 59
  ) {
    return null;
  }
  const priorYear = BigInt(year - 1);
  const daysBeforeYear =
    365n * priorYear + priorYear / 4n - priorYear / 100n + priorYear / 400n;
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const daysBeforeMonth = [0, 31, leap ? 60 : 59, leap ? 91 : 90, leap ? 121 : 120, leap ? 152 : 151, leap ? 182 : 181, leap ? 213 : 212, leap ? 244 : 243, leap ? 274 : 273, leap ? 305 : 304, leap ? 335 : 334];
  const ordinalDay = daysBeforeYear + BigInt((daysBeforeMonth[month - 1] ?? 0) + day - 1);
  const wholeSeconds =
    ((ordinalDay * 24n + BigInt(hour)) * 60n + BigInt(minute)) * 60n + BigInt(second);
  const microseconds = BigInt((match[7] ?? "").padEnd(6, "0") || "0");
  return wholeSeconds * 1_000_000n + microseconds;
}

function shanghaiDateTimeKey(value: unknown): bigint {
  const parsed = parseShanghaiDateTime(value);
  if (parsed === null) {
    throw new RangeError("invalid Shanghai datetime");
  }
  return parsed;
}

function isGregorianDate(year: number, month: number, day: number): boolean {
  if (year < 1 || month < 1 || month > 12 || day < 1) {
    return false;
  }
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return day <= (days[month - 1] ?? 0);
}

function isSafeSequence(value: unknown): value is number {
  return isNonnegativeInteger(value) && value <= MAX_SEQUENCE;
}

function deepFreeze<Value>(value: Value): Value {
  const pending: object[] = [];
  if (typeof value === "object" && value !== null) {
    pending.push(value);
  }
  const visited = new Set<object>();
  while (pending.length > 0) {
    const current = pending.pop();
    if (current === undefined || visited.has(current)) {
      continue;
    }
    visited.add(current);
    if (visited.size > MAX_VALIDATION_NODES) {
      throw new RangeError("response contains too many values");
    }
    for (const child of Object.values(current)) {
      if (typeof child === "object" && child !== null) {
        pending.push(child);
      }
    }
    Object.freeze(current);
  }
  return value;
}
