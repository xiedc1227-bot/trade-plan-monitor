import type {
  ActionableSignalType,
  AlertAcknowledgementCommand,
  AlertPage,
  AlertView,
  ExplicitAlertView,
  EvidenceFactView,
  NextStepView,
  PositionPrefillView,
  paths,
} from "./generated";
import {
  isCalendarDate,
  isShanghaiDateTime,
  shanghaiDateTimeKey,
} from "./shanghaiTime";
import { invalidResponse, requestJson } from "./transport";

type AlertListQuery = paths["/api/v1/alerts"]["get"]["parameters"]["query"];
export type PublicAlertSignalType = Exclude<AlertPage["signalType"], null | undefined>;
export type PublicAlertView = AlertView | ExplicitAlertView;

export type AlertListRequest = AlertListQuery & {
  readonly acknowledged: boolean | null;
  readonly endAt: string | null;
  readonly limit: number;
  readonly offset: number;
  readonly signalType: PublicAlertSignalType | null;
  readonly startAt: string | null;
  readonly symbol: string | null;
};

export interface AlertRequestOptions {
  readonly signal?: AbortSignal;
}

export interface AlertApi {
  acknowledgeAlert(
    command: AlertAcknowledgementCommand,
    idempotencyKey: string,
    options?: AlertRequestOptions,
  ): Promise<PublicAlertView>;
  listAlerts(
    request: AlertListRequest,
    options?: AlertRequestOptions,
  ): Promise<AlertPage>;
}

const MAX_SAFE_REVISION = Number.MAX_SAFE_INTEGER - 1;
const MAX_EVIDENCE_DEPTH = 32;
const MAX_EVIDENCE_NODES = 250;
const MAX_EVIDENCE_FACTS = 512;
const idempotencyKeyPattern = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const actionableSignals = new Set<ActionableSignalType>([
  "BUY_CORE_READY",
  "BUY_TACTICAL_READY",
  "PRESSURE_REDUCE_READY",
  "RISK_BREACH",
  "RISK_EXIT_READY",
  "RISK_EXIT_PENDING_SETTLEMENT",
]);
const explicitSignals = new Set<ExplicitAlertView["signalType"]>([
  "BUY",
  "SELL",
  "RISK_ALERT",
]);
const decisionZones = new Set([
  "LOW_BUY",
  "OBSERVATION",
  "PRESSURE",
  "BELOW_RISK",
  "OUTSIDE",
  "UNKNOWN",
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
  "INDEX_SNAPSHOT",
  "INDEX_IDENTITY",
  "INDEX_CUTOFF",
  "INDEX_HEALTH",
  "INDEX_FACT",
  "INDEX_HISTORY",
  "INDEX_FORMULA",
]);
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
  "POINTS",
]);
const severityBySignal = Object.freeze<Record<ActionableSignalType, AlertView["severity"]>>({
  BUY_CORE_READY: "ACTION",
  BUY_TACTICAL_READY: "ACTION",
  PRESSURE_REDUCE_READY: "RISK",
  RISK_BREACH: "RISK",
  RISK_EXIT_PENDING_SETTLEMENT: "CRITICAL",
  RISK_EXIT_READY: "CRITICAL",
});
const nextStepBySignal = Object.freeze<Record<ActionableSignalType, string>>({
  BUY_CORE_READY: "RECORD_CONFIRMED_FILL",
  BUY_TACTICAL_READY: "RECORD_CONFIRMED_FILL",
  PRESSURE_REDUCE_READY: "RECORD_CONFIRMED_FILL",
  RISK_BREACH: "WAIT_FOR_NEXT_TRADING_DAY",
  RISK_EXIT_PENDING_SETTLEMENT: "WAIT_FOR_SETTLEMENT",
  RISK_EXIT_READY: "RECORD_CONFIRMED_FILL",
});

export function createAlertApi(
  fetchImplementation: typeof fetch = globalThis.fetch.bind(globalThis),
): AlertApi {
  return Object.freeze({
    async listAlerts(request: AlertListRequest, options?: AlertRequestOptions) {
      requireListRequest(request);
      const search = new URLSearchParams();
      if (request.symbol !== null) search.set("symbol", request.symbol);
      if (request.signalType !== null) search.set("signalType", request.signalType);
      if (request.acknowledged !== null) {
        search.set("acknowledged", String(request.acknowledged));
      }
      if (request.startAt !== null && request.endAt !== null) {
        search.set("startAt", request.startAt);
        search.set("endAt", request.endAt);
      }
      search.set("offset", String(request.offset));
      search.set("limit", String(request.limit));
      const { body, status } = await requestJson(
        fetchImplementation,
        `/api/v1/alerts?${search.toString()}`,
        readRequest(options),
      );
      if (!isAlertPage(body, request)) throw invalidResponse(status);
      return body;
    },

    async acknowledgeAlert(
      command: AlertAcknowledgementCommand,
      idempotencyKey: string,
      options?: AlertRequestOptions,
    ) {
      requireAcknowledgementCommand(command);
      if (!idempotencyKeyPattern.test(idempotencyKey)) {
        throw new RangeError("idempotency key is invalid");
      }
      const { body, status } = await requestJson(
        fetchImplementation,
        "/api/v1/alert-acknowledgements",
        {
          body: JSON.stringify(command),
          headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
            "Idempotency-Key": idempotencyKey,
          },
          method: "POST",
          ...(options?.signal === undefined ? {} : { signal: options.signal }),
        },
      );
      if (
        !isAlert(body) ||
        body.eventId !== command.alertId ||
        body.revision !== 1 ||
        body.acknowledgedAt === null ||
        body.acknowledgedAt === undefined
      ) {
        throw invalidResponse(status);
      }
      return body;
    },
  });
}

function readRequest(options?: AlertRequestOptions): RequestInit {
  return {
    headers: { Accept: "application/json" },
    method: "GET",
    ...(options?.signal === undefined ? {} : { signal: options.signal }),
  };
}

function requireListRequest(request: AlertListRequest): void {
  const hasRange = request.startAt !== null && request.endAt !== null;
  if (
    !(request.symbol === null || isShareSymbol(request.symbol)) ||
    !(request.signalType === null || isPublicSignal(request.signalType)) ||
    !(request.acknowledged === null || typeof request.acknowledged === "boolean") ||
    (request.startAt === null) !== (request.endAt === null) ||
    (hasRange &&
      (!isShanghaiDateTime(request.startAt) ||
        !isShanghaiDateTime(request.endAt) ||
        shanghaiDateTimeKey(request.startAt) > shanghaiDateTimeKey(request.endAt))) ||
    !isIntegerBetween(request.offset, 0, 10_000) ||
    !isIntegerBetween(request.limit, 1, 100)
  ) {
    throw new RangeError("alert list request is invalid");
  }
}

function requireAcknowledgementCommand(command: AlertAcknowledgementCommand): void {
  if (
    !isUuid(command.alertId) ||
    !isIntegerBetween(command.expectedRevision, 0, MAX_SAFE_REVISION) ||
    (command.expectedRevision !== 0 && command.expectedRevision !== 1)
  ) {
    throw new RangeError("alert acknowledgement command is invalid");
  }
}

function isAlertPage(value: unknown, request: AlertListRequest): value is AlertPage {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, [
      "acknowledged",
      "endAt",
      "items",
      "limit",
      "offset",
      "signalType",
      "startAt",
      "symbol",
      "total",
    ]) ||
    !hasKeys(value, ["limit", "offset", "total"]) ||
    (value.symbol ?? null) !== request.symbol ||
    (value.signalType ?? null) !== request.signalType ||
    (value.acknowledged ?? null) !== request.acknowledged ||
    (value.startAt ?? null) !== request.startAt ||
    (value.endAt ?? null) !== request.endAt ||
    value.offset !== request.offset ||
    value.limit !== request.limit ||
    !isIntegerBetween(value.total, 0, 10_000)
  ) {
    return false;
  }
  const items = value.items ?? [];
  if (
    !Array.isArray(items) ||
    items.length > request.limit ||
    (items.length > 0 && request.offset + items.length > value.total) ||
    !items.every((item) => isAlert(item) && matchesQuery(item, request))
  ) {
    return false;
  }
  return (
    new Set(items.map((item) => item.eventId)).size === items.length &&
    new Set(items.map((item) => item.sequence)).size === items.length
  );
}

function matchesQuery(item: PublicAlertView, request: AlertListRequest): boolean {
  const acknowledged = item.acknowledgedAt !== null && item.acknowledgedAt !== undefined;
  return (
    (request.symbol === null || item.symbol === request.symbol) &&
    (request.signalType === null || item.signalType === request.signalType) &&
    (request.acknowledged === null || acknowledged === request.acknowledged) &&
    (request.startAt === null ||
      shanghaiDateTimeKey(item.createdAt) >= shanghaiDateTimeKey(request.startAt)) &&
    (request.endAt === null ||
      shanghaiDateTimeKey(item.createdAt) <= shanghaiDateTimeKey(request.endAt))
  );
}

function isAlert(value: unknown): value is PublicAlertView {
  return isLegacyAlert(value) || isExplicitAlert(value);
}

function isPublicSignal(value: PublicAlertSignalType): boolean {
  if (value === "BUY" || value === "SELL" || value === "RISK_ALERT") {
    return explicitSignals.has(value);
  }
  return actionableSignals.has(value);
}

function isLegacyAlert(value: unknown): value is AlertView {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, [
      "acknowledgedAt",
      "blockers",
      "bucket",
      "causeId",
      "createdAt",
      "currentActionable",
      "dataAgeSeconds",
      "dedupKey",
      "evaluatedAt",
      "eventId",
      "marketDataAt",
      "matchedConditions",
      "messageText",
      "name",
      "nextStep",
      "planHash",
      "planId",
      "planVersion",
      "positionPrefill",
      "priceFen",
      "quantity",
      "relevantZone",
      "revision",
      "riskLineFen",
      "satisfiedConditions",
      "sequence",
      "severity",
      "signalType",
      "symbol",
      "targetLotId",
      "tradingDate",
      "unmetConditions",
      "zone",
    ]) ||
    !hasKeys(value, [
      "bucket",
      "causeId",
      "createdAt",
      "currentActionable",
      "dataAgeSeconds",
      "dedupKey",
      "evaluatedAt",
      "eventId",
      "marketDataAt",
      "matchedConditions",
      "messageText",
      "name",
      "nextStep",
      "planHash",
      "planId",
      "planVersion",
      "priceFen",
      "quantity",
      "relevantZone",
      "revision",
      "riskLineFen",
      "sequence",
      "severity",
      "signalType",
      "symbol",
      "tradingDate",
      "zone",
    ]) ||
    !isUuid(value.eventId) ||
    !isPositiveInteger(value.sequence) ||
    !isSha256(value.dedupKey) ||
    !isBoundedText(value.planId, 128) ||
    !isPositiveInteger(value.planVersion) ||
    !isSha256(value.planHash) ||
    !isShareSymbol(value.symbol) ||
    !isBoundedText(value.name, 100) ||
    typeof value.currentActionable !== "boolean" ||
    typeof value.signalType !== "string" ||
    !actionableSignals.has(value.signalType as ActionableSignalType) ||
    !isCalendarDate(value.tradingDate) ||
    !isBoundedText(value.causeId, 128) ||
    !isShanghaiDateTime(value.evaluatedAt) ||
    !(value.marketDataAt === null || isShanghaiDateTime(value.marketDataAt)) ||
    !isNullableNonnegativeInteger(value.dataAgeSeconds) ||
    !isNullablePositiveInteger(value.priceFen) ||
    !isNullableBoardLot(value.quantity) ||
    !(value.bucket === null || value.bucket === "CORE" || value.bucket === "TACTICAL") ||
    !(value.targetLotId === undefined || value.targetLotId === null || isBoundedText(value.targetLotId, 128)) ||
    !isEvidencePartitions(value) ||
    typeof value.zone !== "string" ||
    !decisionZones.has(value.zone) ||
    !isRelevantZone(value.relevantZone) ||
    !isNullablePositiveInteger(value.riskLineFen) ||
    !isNextStep(value.nextStep) ||
    !isBoundedText(value.messageText, 16_384) ||
    !isShanghaiDateTime(value.createdAt) ||
    !(value.acknowledgedAt === undefined ||
      value.acknowledgedAt === null ||
      isShanghaiDateTime(value.acknowledgedAt)) ||
    !isIntegerBetween(value.revision, 0, 1) ||
    !(value.positionPrefill === undefined ||
      value.positionPrefill === null ||
      isPositionPrefill(value.positionPrefill))
  ) {
    return false;
  }

  const item = value as unknown as AlertView;
  const signal = item.signalType;
  const acknowledged = item.acknowledgedAt !== null && item.acknowledgedAt !== undefined;
  const hasMarket = item.marketDataAt !== null;
  if (
    item.severity !== severityBySignal[signal] ||
    item.nextStep.code !== nextStepBySignal[signal] ||
    item.revision !== (acknowledged ? 1 : 0) ||
    (item.dataAgeSeconds !== null) !== hasMarket ||
    (item.priceFen !== null) !== hasMarket ||
    shanghaiDateTimeKey(item.createdAt) < shanghaiDateTimeKey(item.evaluatedAt) ||
    (acknowledged &&
      shanghaiDateTimeKey(item.acknowledgedAt as string) <
        shanghaiDateTimeKey(item.createdAt))
  ) {
    return false;
  }
  if (
    hasMarket &&
    (shanghaiDateTimeKey(item.evaluatedAt) - shanghaiDateTimeKey(item.marketDataAt as string)) /
      1_000_000n !==
      BigInt(item.dataAgeSeconds as number)
  ) {
    return false;
  }
  return validateSignalRelationships(item);
}

function isExplicitAlert(value: unknown): value is ExplicitAlertView {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, [
      "acknowledgedAt",
      "activationRevision",
      "causeId",
      "conditionEvidence",
      "createdAt",
      "currentActionable",
      "dedupKey",
      "evaluatedAt",
      "eventId",
      "messageText",
      "name",
      "nextStep",
      "payloadSchemaVersion",
      "planHash",
      "planId",
      "planVersion",
      "quantity",
      "revision",
      "ruleId",
      "safetyEvidence",
      "sequence",
      "severity",
      "signalType",
      "symbol",
      "targetBucketEnd",
      "tradingDate",
    ]) ||
    !hasKeys(value, [
      "activationRevision",
      "causeId",
      "conditionEvidence",
      "createdAt",
      "currentActionable",
      "dedupKey",
      "evaluatedAt",
      "eventId",
      "messageText",
      "name",
      "nextStep",
      "payloadSchemaVersion",
      "planHash",
      "planId",
      "planVersion",
      "quantity",
      "revision",
      "ruleId",
      "safetyEvidence",
      "sequence",
      "severity",
      "signalType",
      "symbol",
      "targetBucketEnd",
      "tradingDate",
    ]) ||
    value.payloadSchemaVersion !== "explicit-rule-alert-v1" ||
    !isUuid(value.eventId) ||
    !isPositiveInteger(value.sequence) ||
    !isSha256(value.dedupKey) ||
    !isBoundedText(value.planId, 128) ||
    !isPositiveInteger(value.planVersion) ||
    !isSha256(value.planHash) ||
    !isIntegerBetween(value.activationRevision, 0, MAX_SAFE_REVISION) ||
    !isShareSymbol(value.symbol) ||
    !isBoundedText(value.name, 100) ||
    !isCalendarDate(value.tradingDate) ||
    !isBoundedText(value.causeId, 128) ||
    value.causeId !== value.ruleId ||
    !isBoundedText(value.ruleId, 128) ||
    !isShanghaiDateTime(value.targetBucketEnd) ||
    !isShanghaiDateTime(value.evaluatedAt) ||
    !isShanghaiDateTime(value.createdAt) ||
    !isNullableBoardLot(value.quantity) ||
    !isExplicitEvidence(value.conditionEvidence) ||
    !(value.safetyEvidence === null || isExplicitEvidence(value.safetyEvidence)) ||
    !isBoundedText(value.messageText, 16_384) ||
    !(value.acknowledgedAt === undefined ||
      value.acknowledgedAt === null ||
      isShanghaiDateTime(value.acknowledgedAt)) ||
    !isIntegerBetween(value.revision, 0, 1) ||
    typeof value.currentActionable !== "boolean"
  ) {
    return false;
  }
  const expected = value.signalType === "BUY"
    ? ["ACTION", "REVIEW_BUY_REMINDER", false]
    : value.signalType === "SELL"
      ? ["ACTION", "REVIEW_SELL_REMINDER", false]
      : value.signalType === "RISK_ALERT"
        ? ["RISK", "REVIEW_RISK_REMINDER", true]
        : null;
  return expected !== null &&
    value.severity === expected[0] &&
    value.nextStep === expected[1] &&
    (value.quantity === null) === expected[2] &&
    value.revision === (value.acknowledgedAt === null || value.acknowledgedAt === undefined ? 0 : 1) &&
    value.tradingDate === value.targetBucketEnd.slice(0, 10) &&
    (value.safetyEvidence === null || value.signalType !== "RISK_ALERT");
}

function isExplicitEvidence(value: unknown): boolean {
  if (!isRecord(value) || !hasOnlyKeys(value, ["barEnds", "children", "code", "facts", "missingInputs", "outcome", "planPath"])) {
    return false;
  }
  return hasKeys(value, ["code", "outcome", "planPath"]) &&
    isBoundedText(value.planPath, 512) && /^[A-Za-z0-9_.\[\]-]+$/.test(value.planPath) &&
    isStableCode(value.code) &&
    isBoundedText(value.outcome, 32) &&
    (value.facts === undefined || (Array.isArray(value.facts) && value.facts.length <= 16 && value.facts.every(isEvidenceFact))) &&
    (value.missingInputs === undefined || (Array.isArray(value.missingInputs) && value.missingInputs.length <= 4 && value.missingInputs.every((item) => isStableCode(item)))) &&
    (value.barEnds === undefined || (Array.isArray(value.barEnds) && value.barEnds.length <= 501 && value.barEnds.every((item) => isShanghaiDateTime(item)))) &&
    (value.children === undefined || (Array.isArray(value.children) && value.children.length <= 50 && value.children.every(isExplicitEvidence)));
}

function validateSignalRelationships(item: AlertView): boolean {
  const prefill = item.positionPrefill ?? null;
  if (prefill !== null && !prefillMatchesAlert(prefill, item)) return false;
  if (!item.currentActionable) {
    if (prefill !== null) return false;
    if (item.signalType === "BUY_CORE_READY" || item.signalType === "BUY_TACTICAL_READY") {
      return item.zone === "LOW_BUY" && item.relevantZone?.zone === "LOW_BUY";
    }
    if (item.signalType === "PRESSURE_REDUCE_READY") {
      return item.zone === "PRESSURE" && item.relevantZone?.zone === "PRESSURE";
    }
    return item.relevantZone === null;
  }
  if (item.signalType === "BUY_CORE_READY" || item.signalType === "BUY_TACTICAL_READY") {
    return (
      item.zone === "LOW_BUY" &&
      item.relevantZone?.zone === "LOW_BUY" &&
      prefill?.action === "BUY"
    );
  }
  if (item.signalType === "PRESSURE_REDUCE_READY") {
    return (
      item.zone === "PRESSURE" &&
      item.relevantZone?.zone === "PRESSURE" &&
      prefill?.action === "CLOSE"
    );
  }
  if (item.signalType === "RISK_EXIT_READY") {
    return item.relevantZone === null && prefill?.action === "CLOSE";
  }
  return item.relevantZone === null && prefill === null;
}

function prefillMatchesAlert(prefill: PositionPrefillView, item: AlertView): boolean {
  return (
    prefill.symbol === item.symbol &&
    prefill.quantity === item.quantity &&
    prefill.bucket === item.bucket &&
    (prefill.targetLotId ?? null) === (item.targetLotId ?? null) &&
    prefill.relatedAlertId === item.eventId
  );
}

function isPositionPrefill(value: unknown): value is PositionPrefillView {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["action", "bucket", "quantity", "relatedAlertId", "symbol", "targetLotId"]) &&
    hasKeys(value, ["action", "bucket", "quantity", "relatedAlertId", "symbol"]) &&
    (value.action === "BUY" || value.action === "CLOSE") &&
    (value.bucket === "CORE" || value.bucket === "TACTICAL") &&
    isBoardLot(value.quantity) &&
    isUuid(value.relatedAlertId) &&
    isShareSymbol(value.symbol) &&
    (value.targetLotId === undefined || value.targetLotId === null || isBoundedText(value.targetLotId, 128)) &&
    ((value.action === "BUY" && (value.targetLotId === undefined || value.targetLotId === null)) ||
      (value.action === "CLOSE" && isBoundedText(value.targetLotId, 128)))
  );
}

function isRelevantZone(value: unknown): boolean {
  return (
    value === null ||
    (isRecord(value) &&
      hasExactKeys(value, ["highFen", "includeHigh", "includeLow", "lowFen", "zone"]) &&
      isPositiveInteger(value.lowFen) &&
      isPositiveInteger(value.highFen) &&
      value.lowFen <= value.highFen &&
      typeof value.includeHigh === "boolean" &&
      typeof value.includeLow === "boolean" &&
      (value.zone === "LOW_BUY" || value.zone === "PRESSURE"))
  );
}

function isEvidencePartitions(value: Record<string, unknown>): boolean {
  const matched = value.matchedConditions;
  const resultPartitions = [
    value.satisfiedConditions ?? [],
    value.unmetConditions ?? [],
    value.blockers ?? [],
  ];
  if (
    !Array.isArray(matched) ||
    matched.length < 1 ||
    matched.length > 50 ||
    resultPartitions.some((partition) => !Array.isArray(partition) || partition.length > 50)
  ) {
    return false;
  }
  if (
    !matched.every((evidence) =>
      isEvidence(evidence, 0, { facts: 0, nodes: 0 }).valid,
    )
  ) {
    return false;
  }
  let nodes = 0;
  let facts = 0;
  return resultPartitions.every((partition) =>
    (partition as unknown[]).every((evidence) => {
      const result = isEvidence(evidence, 0, { facts, nodes });
      facts = result.facts;
      nodes = result.nodes;
      return result.valid && facts <= MAX_EVIDENCE_FACTS && nodes <= MAX_EVIDENCE_NODES;
    }),
  );
}

function isEvidence(
  value: unknown,
  depth: number,
  budget: { facts: number; nodes: number },
): { facts: number; nodes: number; valid: boolean } {
  const next = { facts: budget.facts, nodes: budget.nodes + 1, valid: false };
  if (
    depth > MAX_EVIDENCE_DEPTH ||
    next.nodes > MAX_EVIDENCE_NODES ||
    !isRecord(value) ||
    !hasOnlyKeys(value, ["children", "code", "facts", "kind", "missingInputs", "outcome"]) ||
    !hasKeys(value, ["code", "kind", "outcome"]) ||
    !isStableCode(value.code) ||
    (value.kind !== "CONDITION" && value.kind !== "RULE") ||
    (value.outcome !== "SATISFIED" &&
      value.outcome !== "UNSATISFIED" &&
      value.outcome !== "MISSING_INPUT") ||
    !(value.facts === undefined ||
      (Array.isArray(value.facts) && value.facts.length <= MAX_EVIDENCE_FACTS && value.facts.every(isEvidenceFact))) ||
    !(value.missingInputs === undefined ||
      (Array.isArray(value.missingInputs) &&
        value.missingInputs.length <= 16 &&
        new Set(value.missingInputs).size === value.missingInputs.length &&
        value.missingInputs.every((item) => typeof item === "string" && missingInputCodes.has(item)))) ||
    !(value.children === undefined || (Array.isArray(value.children) && value.children.length <= 50))
  ) {
    return next;
  }
  next.facts += value.facts?.length ?? 0;
  for (const child of value.children ?? []) {
    const childResult = isEvidence(child, depth + 1, next);
    next.facts = childResult.facts;
    next.nodes = childResult.nodes;
    if (!childResult.valid) return next;
  }
  next.valid = true;
  return next;
}

function isEvidenceFact(value: unknown): value is EvidenceFactView {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["key", "unit", "value"]) ||
    typeof value.key !== "string" ||
    !/^[a-z][a-z0-9_]{0,63}$/.test(value.key) ||
    typeof value.unit !== "string" ||
    !evidenceUnits.has(value.unit)
  ) {
    return false;
  }
  if (value.unit === "BOOLEAN") return typeof value.value === "boolean";
  if (value.unit === "DATE") return isCalendarDate(value.value);
  if (value.unit === "DATETIME") return isShanghaiDateTime(value.value);
  if (value.unit === "CODE") return isStableCode(value.value) || isBoundedText(value.value, 256);
  if (value.unit === "FEN" || value.unit === "BARS" || value.unit === "COUNT") {
    return typeof value.value === "number" && Number.isSafeInteger(value.value);
  }
  if (value.unit === "SHARES") {
    return (
      (typeof value.value === "number" && Number.isSafeInteger(value.value)) ||
      isDecimalString(value.value)
    );
  }
  return isDecimalString(value.value);
}

function isNextStep(value: unknown): value is NextStepView {
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
        value.requiredInputs.every((item) => typeof item === "string" && missingInputCodes.has(item))))
  );
}

function isRecord(value: unknown): value is Record<string, any> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return keys.every((key) => Object.hasOwn(value, key));
}

function hasOnlyKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(value).every((key) => keys.includes(key));
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(value).length === keys.length && hasKeys(value, keys);
}

function isShareSymbol(value: unknown): value is string {
  return typeof value === "string" && /^\d{6}\.(?:BJ|SH|SZ)$/.test(value);
}

function isUuid(value: unknown): value is string {
  return typeof value === "string" && uuidPattern.test(value);
}

function isSha256(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
}

function isStableCode(value: unknown): value is string {
  return typeof value === "string" && /^[A-Z][A-Z0-9_]{0,63}$/.test(value);
}

function isBoundedText(value: unknown, maximum: number): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= maximum;
}

function isDecimalString(value: unknown): value is string {
  return typeof value === "string" && /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(value) && value.length <= 10_000;
}

function isIntegerBetween(value: unknown, minimum: number, maximum: number): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= minimum && value <= maximum;
}

function isPositiveInteger(value: unknown): value is number {
  return isIntegerBetween(value, 1, Number.MAX_SAFE_INTEGER);
}

function isNullablePositiveInteger(value: unknown): boolean {
  return value === null || isPositiveInteger(value);
}

function isNullableNonnegativeInteger(value: unknown): boolean {
  return value === null || isIntegerBetween(value, 0, Number.MAX_SAFE_INTEGER);
}

function isBoardLot(value: unknown): value is number {
  return isPositiveInteger(value) && value % 100 === 0;
}

function isNullableBoardLot(value: unknown): boolean {
  return value === null || isBoardLot(value);
}
