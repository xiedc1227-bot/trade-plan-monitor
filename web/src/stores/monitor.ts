import { defineStore } from "pinia";
import { computed, readonly, shallowRef } from "vue";

import type {
  ConnectionStatus,
  DashboardCounts,
  DashboardProjectionUnavailableResponse,
  DashboardResponse,
  MarketIndexSnapshotView,
  MarketTurnoverSummaryView,
  SymbolSummaryView,
} from "../api/generated";

const MAX_SEQUENCE = Number.MAX_SAFE_INTEGER;

const monitorEventTypes = [
  "symbol.snapshot.updated",
  "symbol.health.updated",
  "alert.created",
  "alert.acknowledged",
  "plan.extraction.updated",
  "plan.activated",
  "plan.deactivated",
  "position.updated",
  "ai.provider.updated",
  "system.health.updated",
  "market.index.updated",
] as const;
const monitorEventTypeSet = new Set<string>(monitorEventTypes);

export type MonitorEventType = (typeof monitorEventTypes)[number];

export interface MonitorEventPayload {
  entityId: string;
  resultHash?: string;
  revision?: number;
  status?: string;
  symbol?: string;
}

export interface MonitorEventEnvelope {
  aggregateId: string;
  eventId: string;
  occurredAt: string;
  payload: MonitorEventPayload;
  schemaVersion: 1;
  sequence: number;
  type: MonitorEventType;
}

export type SnapshotRecoveryReason = "INVALID_EVENT" | "SEQUENCE_GAP" | "SERVER_REQUIRED";

export interface SnapshotRecoveryIntent {
  expectedSequence: number | null;
  reason: SnapshotRecoveryReason;
  receivedSequence: number | null;
}

export interface MonitorInvalidation {
  entityId: string;
  sequence: number;
  type: MonitorEventType;
}

export type EventApplyResult =
  | { sequence: number; status: "applied" }
  | {
      currentSequence: number;
      reason: "DUPLICATE_OR_OUT_OF_ORDER";
      receivedSequence: number;
      status: "rejected";
    }
  | {
      expectedSequence: number | null;
      receivedSequence: number | null;
      status: "recovery-required";
    };

interface ConnectionState {
  code: ConnectionStatus;
  label: string;
  marker: string;
}

const emptyCounts = deepFreeze<DashboardCounts>({
  actionable: 0,
  blocked: 0,
  lowZoneWatch: 0,
  normal: 0,
  risk: 0,
  stale: 0,
});

const connectionStates = deepFreeze<Record<ConnectionStatus, ConnectionState>>({
  CONNECTED: { code: "CONNECTED", label: "实时连接", marker: "●" },
  DISCONNECTED: { code: "DISCONNECTED", label: "连接中断", marker: "×" },
  UNKNOWN: { code: "UNKNOWN", label: "连接未知", marker: "?" },
});

export const useMonitorStore = defineStore("monitor", () => {
  const hasSnapshotState = shallowRef(false);
  const unavailableState = shallowRef<DashboardProjectionUnavailableResponse | null>(null);
  const sequenceState = shallowRef(0);
  const connectionStatusState = shallowRef<ConnectionStatus>("UNKNOWN");
  const countsState = shallowRef<DashboardCounts>(emptyCounts);
  const observedAtState = shallowRef<string | null>(null);
  const runtimeGenerationState = shallowRef<string | null>(null);
  const symbolIdsState = shallowRef<readonly string[]>(Object.freeze([]));
  const symbolsByIdState = shallowRef<Readonly<Record<string, SymbolSummaryView>>>(
    Object.freeze({}),
  );
  const marketIndexesState = shallowRef<readonly MarketIndexSnapshotView[]>(
    Object.freeze([]),
  );
  const marketTurnoverState = shallowRef<MarketTurnoverSummaryView | null>(null);
  const recoveryIntentState = shallowRef<SnapshotRecoveryIntent | null>(null);
  const alertRefreshRevisionState = shallowRef(0);
  const lastInvalidationState = shallowRef<MonitorInvalidation | null>(null);
  const lastEventState = shallowRef<MonitorEventEnvelope | null>(null);

  const symbols = computed<readonly SymbolSummaryView[]>(() =>
    Object.freeze(
      symbolIdsState.value.map((symbol) => {
        const value = symbolsByIdState.value[symbol];
        if (value === undefined) {
          throw new Error("normalized symbol state is inconsistent");
        }
        return value;
      }),
    ),
  );
  const connectionState = computed<ConnectionState>(
    () => connectionStates[connectionStatusState.value],
  );

  function applySnapshot(snapshot: DashboardResponse): void {
    requireSafeSequence(snapshot.sequence, "snapshot sequence");
    if (snapshot.sequence < sequenceState.value) {
      throw new RangeError("snapshot sequence cannot regress the monitor cursor");
    }
    const normalized = normalizeSymbols(snapshot.symbols ?? []);
    const counts = freezeClone(snapshot.counts);
    const marketIndexes = normalizeMarketIndexes(snapshot.marketIndexes);
    const marketTurnover = snapshot.marketTurnover === null || snapshot.marketTurnover === undefined
      ? null
      : freezeClone(snapshot.marketTurnover);

    sequenceState.value = snapshot.sequence;
    connectionStatusState.value = snapshot.connectionStatus;
    countsState.value = counts;
    observedAtState.value = snapshot.observedAt;
    runtimeGenerationState.value = snapshot.runtimeGeneration;
    symbolIdsState.value = normalized.ids;
    symbolsByIdState.value = normalized.byId;
    marketIndexesState.value = marketIndexes;
    marketTurnoverState.value = marketTurnover;
    recoveryIntentState.value = null;
    lastInvalidationState.value = null;
    lastEventState.value = null;
    hasSnapshotState.value = true;
    unavailableState.value = null;
  }

  function applyUnavailable(unavailable: DashboardProjectionUnavailableResponse): void {
    requireSafeSequence(unavailable.sequence, "unavailable sequence");
    if (unavailable.sequence < sequenceState.value) {
      throw new RangeError("unavailable sequence cannot regress the monitor cursor");
    }
    sequenceState.value = unavailable.sequence;
    connectionStatusState.value = "UNKNOWN";
    countsState.value = emptyCounts;
    observedAtState.value = unavailable.observedAt;
    runtimeGenerationState.value = null;
    symbolIdsState.value = Object.freeze([]);
    symbolsByIdState.value = Object.freeze({});
    marketIndexesState.value = Object.freeze([]);
    marketTurnoverState.value = null;
    recoveryIntentState.value = null;
    lastInvalidationState.value = null;
    lastEventState.value = null;
    hasSnapshotState.value = false;
    unavailableState.value = freezeClone(unavailable);
  }

  function applyEvent(event: MonitorEventEnvelope): EventApplyResult {
    if (!isMonitorEventEnvelope(event)) {
      const receivedSequence = isSafeSequence(event?.sequence) ? event.sequence : null;
      requestSnapshotRecovery("INVALID_EVENT", receivedSequence);
      return {
        expectedSequence: nextSequence(sequenceState.value),
        receivedSequence,
        status: "recovery-required",
      };
    }

    if (event.sequence <= sequenceState.value) {
      return {
        currentSequence: sequenceState.value,
        reason: "DUPLICATE_OR_OUT_OF_ORDER",
        receivedSequence: event.sequence,
        status: "rejected",
      };
    }

    const expectedSequence = nextSequence(sequenceState.value);
    if (expectedSequence === null) {
      requestSnapshotRecovery("INVALID_EVENT", event.sequence);
      return { expectedSequence, receivedSequence: event.sequence, status: "recovery-required" };
    }
    if (recoveryIntentState.value !== null) {
      return { expectedSequence, receivedSequence: event.sequence, status: "recovery-required" };
    }
    if (event.sequence !== expectedSequence) {
      requestSnapshotRecovery("SEQUENCE_GAP", event.sequence);
      return {
        expectedSequence,
        receivedSequence: event.sequence,
        status: "recovery-required",
      };
    }

    sequenceState.value = event.sequence;
    lastInvalidationState.value = deepFreeze({
      entityId: event.payload.entityId,
      sequence: event.sequence,
      type: event.type,
    });
    lastEventState.value = freezeClone(event);
    return { sequence: event.sequence, status: "applied" };
  }

  function requestSnapshotRecovery(
    reason: SnapshotRecoveryReason,
    receivedSequence: number | null = null,
  ): void {
    if (receivedSequence !== null) {
      requireSafeSequence(receivedSequence, "recovery sequence");
    }
    recoveryIntentState.value = deepFreeze({
      expectedSequence: nextSequence(sequenceState.value),
      reason,
      receivedSequence,
    });
  }

  function requestAlertRefresh(): void {
    if (alertRefreshRevisionState.value < MAX_SEQUENCE) {
      alertRefreshRevisionState.value += 1;
    }
  }

  return {
    alertRefreshRevision: readonly(alertRefreshRevisionState),
    applyEvent,
    applySnapshot,
    applyUnavailable,
    connectionState,
    connectionStatus: readonly(connectionStatusState),
    counts: readonly(countsState),
    hasSnapshot: readonly(hasSnapshotState),
    lastInvalidation: readonly(lastInvalidationState),
    lastEvent: readonly(lastEventState),
    marketIndexes: readonly(marketIndexesState),
    marketTurnover: readonly(marketTurnoverState),
    observedAt: readonly(observedAtState),
    recoveryIntent: readonly(recoveryIntentState),
    requestSnapshotRecovery,
    requestAlertRefresh,
    runtimeGeneration: readonly(runtimeGenerationState),
    sequence: readonly(sequenceState),
    symbolIds: readonly(symbolIdsState),
    symbols,
    symbolsById: readonly(symbolsByIdState),
    unavailable: readonly(unavailableState),
  };
});

function normalizeSymbols(symbols: readonly SymbolSummaryView[]): {
  byId: Readonly<Record<string, SymbolSummaryView>>;
  ids: readonly string[];
} {
  if (symbols.length > 10) {
    throw new RangeError("snapshot cannot contain more than 10 symbols");
  }
  const byId: Record<string, SymbolSummaryView> = Object.create(null) as Record<
    string,
    SymbolSummaryView
  >;
  const ids: string[] = [];
  for (const source of symbols) {
    if (Object.hasOwn(byId, source.symbol)) {
      throw new RangeError("snapshot contains a duplicate symbol");
    }
    const symbol = freezeClone(source);
    byId[source.symbol] = symbol;
    ids.push(source.symbol);
  }
  return {
    byId: deepFreeze(byId),
    ids: Object.freeze(ids),
  };
}

function normalizeMarketIndexes(
  indexes: readonly MarketIndexSnapshotView[],
): readonly MarketIndexSnapshotView[] {
  if (indexes.length > 5) {
    throw new RangeError("snapshot cannot contain more than five market indexes");
  }
  const identities = indexes.map((item) => item.indexCode);
  if (new Set(identities).size !== identities.length) {
    throw new RangeError("snapshot contains a duplicate market index");
  }
  return Object.freeze(indexes.map((item) => freezeClone(item)));
}

function freezeClone<Value>(value: Value): Value {
  return deepFreeze(structuredClone(value));
}

function deepFreeze<Value>(value: Value): Value {
  if (typeof value !== "object" || value === null || Object.isFrozen(value)) {
    return value;
  }
  for (const child of Object.values(value)) {
    deepFreeze(child);
  }
  return Object.freeze(value);
}

const payloadFields: Record<MonitorEventType, readonly string[]> = {
  "ai.provider.updated": ["entityId", "revision"],
  "alert.acknowledged": ["entityId", "revision", "symbol"],
  "alert.created": ["entityId", "revision", "symbol"],
  "plan.activated": ["entityId", "revision", "symbol"],
  "plan.deactivated": ["entityId", "revision", "symbol"],
  "plan.extraction.updated": ["entityId", "revision", "status"],
  "position.updated": ["entityId", "status", "symbol"],
  "symbol.health.updated": ["entityId", "revision", "status", "symbol"],
  "symbol.snapshot.updated": ["entityId", "resultHash", "symbol"],
  "system.health.updated": ["entityId", "status"],
  "market.index.updated": ["entityId", "revision", "status"],
};

const symbolAggregateEvents = new Set<MonitorEventType>([
  "plan.activated",
  "plan.deactivated",
  "symbol.health.updated",
  "symbol.snapshot.updated",
]);

const entityAggregateEvents = new Set<MonitorEventType>([
  "ai.provider.updated",
  "alert.acknowledged",
  "alert.created",
  "plan.deactivated",
  "plan.extraction.updated",
  "position.updated",
  "symbol.health.updated",
  "symbol.snapshot.updated",
  "system.health.updated",
  "market.index.updated",
]);

function isMonitorEventEnvelope(value: unknown): boolean {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "aggregateId",
      "eventId",
      "occurredAt",
      "payload",
      "schemaVersion",
      "sequence",
      "type",
    ]) ||
    typeof value.type !== "string" ||
    !monitorEventTypeSet.has(value.type) ||
    !isPositiveSequence(value.sequence) ||
    value.schemaVersion !== 1 ||
    !isBoundedText(value.aggregateId, 128) ||
    !isCanonicalUuid(value.eventId) ||
    !isAwareDateTime(value.occurredAt) ||
    !isRecord(value.payload)
  ) {
    return false;
  }

  const type = value.type as MonitorEventType;
  const payload = value.payload;
  if (
    !hasExactKeys(payload, payloadFields[type]) ||
    !isBoundedText(payload.entityId, 128) ||
    (payload.symbol !== undefined && !isShareSymbol(payload.symbol)) ||
    (payload.revision !== undefined && !isSafeSequence(payload.revision)) ||
    (payload.status !== undefined && !isEventStatus(payload.status)) ||
    (payload.resultHash !== undefined && !isSha256(payload.resultHash))
  ) {
    return false;
  }

  if (symbolAggregateEvents.has(type) && value.aggregateId !== payload.symbol) {
    return false;
  }
  if (entityAggregateEvents.has(type) && value.aggregateId !== payload.entityId) {
    return false;
  }
  if (type === "alert.created" || type === "alert.acknowledged") {
    if (!isCanonicalUuid(value.aggregateId)) {
      return false;
    }
    const expectedRevision = type === "alert.created" ? 0 : 1;
    if (payload.revision !== expectedRevision) {
      return false;
    }
  }
  if (type === "alert.created" && value.eventId !== value.aggregateId) {
    return false;
  }
  if (
    (type === "symbol.health.updated" ||
      type === "plan.activated" ||
      type === "plan.deactivated" ||
      type === "market.index.updated") &&
    payload.revision === 0
  ) {
    return false;
  }
  if (
    type === "position.updated" &&
    payload.status !== "OPEN" &&
    payload.status !== "CLOSED"
  ) {
    return false;
  }
  return true;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value);
  return actual.length === keys.length && keys.every((key) => Object.hasOwn(value, key));
}

function isBoundedText(value: unknown, maximum: number): value is string {
  return (
    typeof value === "string" &&
    value.length > 0 &&
    value.length <= maximum &&
    value === value.trim()
  );
}

function isCanonicalUuid(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value)
  );
}

function isAwareDateTime(value: unknown): value is string {
  if (typeof value !== "string") {
    return false;
  }
  const match =
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?\+08:00$/.exec(
      value,
    );
  return (
    match !== null &&
    isGregorianDate(Number(match[1]), Number(match[2]), Number(match[3])) &&
    Number(match[4]) <= 23 &&
    Number(match[5]) <= 59 &&
    Number(match[6]) <= 59
  );
}

function isGregorianDate(year: number, month: number, day: number): boolean {
  if (year < 1 || month < 1 || month > 12 || day < 1) {
    return false;
  }
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return day <= (days[month - 1] ?? 0);
}

function isShareSymbol(value: unknown): value is string {
  return typeof value === "string" && /^\d{6}\.(?:BJ|SH|SZ)$/.test(value);
}

function isEventStatus(value: unknown): value is string {
  return typeof value === "string" && /^[A-Z][A-Z0-9_]{0,63}$/.test(value);
}

function isSha256(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
}

function isPositiveSequence(value: unknown): value is number {
  return isSafeSequence(value) && value >= 1;
}

function nextSequence(value: number): number | null {
  return value < MAX_SEQUENCE ? value + 1 : null;
}

function isSafeSequence(value: unknown): value is number {
  return (
    typeof value === "number" &&
    Number.isSafeInteger(value) &&
    value >= 0 &&
    value <= MAX_SEQUENCE
  );
}

function requireSafeSequence(value: unknown, field: string): asserts value is number {
  if (!isSafeSequence(value)) {
    throw new RangeError(`${field} must be a non-negative safe integer`);
  }
}
