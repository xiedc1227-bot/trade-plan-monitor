<script lang="ts">
import type {
  AlertAcknowledgementCommand,
  AlertPage,
} from "../api/generated";
import { matchesAlertSignalFilter, type PublicAlertSignalType, type PublicAlertView } from "../api/alerts";

export interface AlertQuery {
  acknowledged: boolean | null;
  endAt: string | null;
  limit: number;
  offset: number;
  signalType: PublicAlertSignalType | null;
  startAt: string | null;
  symbol: string | null;
}

export interface AlertOperations {
  acknowledgeAlert(request: {
    command: AlertAcknowledgementCommand;
    idempotencyKey: string;
  }): Promise<PublicAlertView>;
  listAlerts(query: AlertQuery): Promise<AlertPage>;
}
</script>

<script setup lang="ts">
import { computed, nextTick, shallowRef, useTemplateRef, watch } from "vue";

import AlertRail from "../components/alerts/AlertRail.vue";
import PageIntro from "../components/common/PageIntro.vue";
import AlertTable from "../components/alerts/AlertTable.vue";
import type { MonitorEventEnvelope } from "../stores/monitor";

interface Props {
  alertRefreshRevision?: number;
  createIdempotencyKey?: () => string;
  initialLoading?: boolean;
  initialPage: AlertPage | null;
  liveEvents?: readonly MonitorEventEnvelope[];
  operations: AlertOperations;
}

const props = withDefaults(defineProps<Props>(), {
  alertRefreshRevision: 0,
  createIdempotencyKey: () => crypto.randomUUID(),
  initialLoading: false,
  liveEvents: () => [],
});

const initialQuery = queryFromPage(props.initialPage);
const query = shallowRef<AlertQuery>(initialQuery);
const requestedQuery = shallowRef<AlertQuery>(initialQuery);
const page = shallowRef<AlertPage | null>(null);
const busy = shallowRef(false);
const error = shallowRef<string | null>(null);
const submittingAcknowledgements = shallowRef<ReadonlySet<string>>(new Set());
const acknowledgementsAwaitingRefresh = shallowRef<ReadonlySet<string>>(new Set());

type AcknowledgementOutcome =
  | "CONFLICT"
  | "INVALID_RECEIPT"
  | "UNKNOWN_ERROR"
  | "VALID_RECEIPT";

interface AcknowledgementContext {
  hadFocus: boolean;
  original: PublicAlertView;
  outcome: AcknowledgementOutcome;
}

const acknowledgementContexts = new Map<string, AcknowledgementContext>();
const MAX_PENDING_ACKNOWLEDGEMENTS = 256;
const pendingAcknowledgements = computed<ReadonlySet<string>>(
  () =>
    new Set([
      ...submittingAcknowledgements.value,
      ...acknowledgementsAwaitingRefresh.value,
    ]),
);
const liveUpdateCount = shallowRef(0);
const operationStatus = shallowRef("");
const operationStatusElement = useTemplateRef<HTMLElement>("operationStatus");
const MAX_LIVE_IDENTITIES = 2_048;
const seenLiveIds = new Map<string, number>();
const seenLiveSequences = new Map<number, string>();
const seenLiveOrder: Array<{ eventId: string; sequence: number }> = [];
const pendingLiveIds = new Map<string, number>();
const pendingLiveSequences = new Map<number, string>();
let pendingLiveOverflowCount = 0;
let liveSyncing = false;
let requestGeneration = 0;
let latestRefreshCompletion: Promise<boolean> | null = null;

applyAuthoritativePage(props.initialPage, initialQuery);

watch(
  () => props.initialPage,
  (nextPage) => {
    const nextQuery = queryFromPage(nextPage);
    requestGeneration += 1;
    busy.value = false;
    query.value = nextQuery;
    requestedQuery.value = nextQuery;
    error.value = null;
    const coverage = snapshotPendingLiveCoverage();
    if (applyAuthoritativePage(nextPage, nextQuery)) {
      commitLiveCoverage(coverage);
      settleAcknowledgementContexts();
    }
  },
);

watch(
  () => props.liveEvents,
  (events) => {
    for (const event of events) {
      if (event.type !== "alert.created" && event.type !== "alert.acknowledged") {
        continue;
      }
      const priorSequence = seenLiveIds.get(event.eventId) ?? pendingLiveIds.get(event.eventId);
      const priorEventId =
        seenLiveSequences.get(event.sequence) ?? pendingLiveSequences.get(event.sequence);
      if (
        (priorSequence !== undefined && priorSequence !== event.sequence) ||
        (priorEventId !== undefined && priorEventId !== event.eventId)
      ) {
        error.value = "实时提醒事件无效，请重新加载。";
        continue;
      }
      if (priorSequence !== undefined || priorEventId !== undefined) {
        continue;
      }
      if (pendingLiveIds.size >= MAX_LIVE_IDENTITIES) {
        pendingLiveOverflowCount = Math.min(
          MAX_LIVE_IDENTITIES,
          pendingLiveOverflowCount + 1,
        );
        continue;
      }
      pendingLiveIds.set(event.eventId, event.sequence);
      pendingLiveSequences.set(event.sequence, event.eventId);
    }
    if (hasPendingLiveEvents()) {
      void synchronizeLiveEvents();
    }
  },
  { immediate: true },
);

watch(
  () => props.alertRefreshRevision,
  () => {
    void refreshAndResumeLive(requestedQuery.value);
  },
);

function refresh(nextQuery: AlertQuery): Promise<boolean> {
  const completion = performRefresh(nextQuery);
  latestRefreshCompletion = completion;
  return completion;
}

async function performRefresh(nextQuery: AlertQuery): Promise<boolean> {
  const generation = ++requestGeneration;
  const liveCoverage = snapshotPendingLiveCoverage();
  busy.value = true;
  error.value = null;
  try {
    const result = await props.operations.listAlerts(nextQuery);
    if (generation !== requestGeneration) {
      return false;
    }
    if (!applyAuthoritativePage(result, nextQuery)) {
      return false;
    }
    query.value = freezeClone(nextQuery);
    settleAcknowledgementContexts();
    commitLiveCoverage(liveCoverage);
    return true;
  } catch {
    if (generation === requestGeneration) {
      error.value = "提醒加载失败，请稍后重试。";
    }
    return false;
  } finally {
    if (generation === requestGeneration) {
      busy.value = false;
    }
  }
}

function applyFilters(nextQuery: AlertQuery): void {
  requestedQuery.value = freezeClone(nextQuery);
  void refreshAndResumeLive(nextQuery);
}

function changePage(offset: number): void {
  const nextQuery = { ...requestedQuery.value, offset };
  requestedQuery.value = freezeClone(nextQuery);
  void refreshAndResumeLive(nextQuery);
}

async function acknowledge(item: PublicAlertView): Promise<void> {
  if (pendingAcknowledgements.value.has(item.eventId)) {
    return;
  }
  if (pendingAcknowledgements.value.size >= MAX_PENDING_ACKNOWLEDGEMENTS) {
    error.value = "待确认状态过多，请先重新加载权威提醒。";
    operationStatus.value = error.value;
    return;
  }
  requestGeneration += 1;
  busy.value = false;
  const acknowledgementHadFocus = acknowledgementOwnsFocus(item.eventId);
  submittingAcknowledgements.value = withIdentity(
    submittingAcknowledgements.value,
    item.eventId,
    true,
  );
  error.value = null;
  operationStatus.value = "正在确认提醒并刷新权威状态。";
  let outcome: AcknowledgementOutcome;
  try {
    const result = await props.operations.acknowledgeAlert({
      command: { alertId: item.eventId, expectedRevision: item.revision },
      idempotencyKey: props.createIdempotencyKey(),
    });
    outcome =
      result.eventId !== item.eventId ||
      result.sequence !== item.sequence ||
      result.symbol !== item.symbol ||
      result.revision !== 1 ||
      result.acknowledgedAt === null ||
      result.acknowledgedAt === undefined
        ? "INVALID_RECEIPT"
        : "VALID_RECEIPT";
  } catch (caught: unknown) {
    outcome = isConflict(caught) ? "CONFLICT" : "UNKNOWN_ERROR";
  }
  acknowledgementContexts.set(item.eventId, {
    hadFocus: acknowledgementHadFocus,
    original: item,
    outcome,
  });
  acknowledgementsAwaitingRefresh.value = withIdentity(
    acknowledgementsAwaitingRefresh.value,
    item.eventId,
    true,
  );
  try {
    const authoritative = await followLatestRefresh(refresh(requestedQuery.value));
    if (!authoritative && acknowledgementContexts.has(item.eventId)) {
      operationStatus.value = "提醒权威状态尚未同步，请重试加载。";
    }
  } finally {
    submittingAcknowledgements.value = withIdentity(
      submittingAcknowledgements.value,
      item.eventId,
      false,
    );
  }
}

async function followLatestRefresh(initial: Promise<boolean>): Promise<boolean> {
  let current = initial;
  while (true) {
    if (await current) {
      return true;
    }
    const latest = latestRefreshCompletion;
    if (latest === null || latest === current) {
      return false;
    }
    current = latest;
  }
}

async function refreshAndResumeLive(nextQuery: AlertQuery): Promise<void> {
  const refreshed = await refresh(nextQuery);
  if (refreshed && hasPendingLiveEvents()) {
    void synchronizeLiveEvents();
  }
}

async function retryAlerts(): Promise<void> {
  if (hasPendingLiveEvents()) {
    await synchronizeLiveEvents();
    return;
  }
  const refreshed = await refresh(requestedQuery.value);
  if (refreshed) {
    settleAcknowledgementContexts();
  }
}

async function synchronizeLiveEvents(): Promise<void> {
  if (liveSyncing) {
    return;
  }
  liveSyncing = true;
  try {
    while (hasPendingLiveEvents()) {
      const refreshed = await refresh(requestedQuery.value);
      if (!refreshed) {
        break;
      }
    }
  } finally {
    liveSyncing = false;
  }
}

function acknowledgementOwnsFocus(eventId: string): boolean {
  if (typeof document === "undefined") {
    return false;
  }
  const active = document.activeElement;
  return active instanceof HTMLElement && active.dataset.acknowledge === eventId;
}

async function restoreAcknowledgementFocus(hadFocus: boolean): Promise<void> {
  if (!hadFocus || typeof document === "undefined") {
    return;
  }
  await nextTick();
  const active = document.activeElement;
  if (active === null || active === document.body || !document.contains(active)) {
    operationStatusElement.value?.focus();
  }
}

interface LiveCoverage {
  identities: readonly { eventId: string; sequence: number }[];
  overflowCount: number;
}

function hasPendingLiveEvents(): boolean {
  return pendingLiveIds.size > 0 || pendingLiveOverflowCount > 0;
}

function snapshotPendingLiveCoverage(): LiveCoverage {
  return {
    identities: [...pendingLiveIds.entries()].map(([eventId, sequence]) => ({
      eventId,
      sequence,
    })),
    overflowCount: pendingLiveOverflowCount,
  };
}

function commitLiveCoverage(coverage: LiveCoverage): void {
  let committed = 0;
  for (const identity of coverage.identities) {
    if (pendingLiveIds.get(identity.eventId) !== identity.sequence) {
      continue;
    }
    pendingLiveIds.delete(identity.eventId);
    pendingLiveSequences.delete(identity.sequence);
    rememberLiveIdentity(identity.eventId, identity.sequence);
    committed += 1;
  }
  const committedOverflow = Math.min(coverage.overflowCount, pendingLiveOverflowCount);
  pendingLiveOverflowCount -= committedOverflow;
  liveUpdateCount.value = Math.min(
    Number.MAX_SAFE_INTEGER,
    liveUpdateCount.value + committed + committedOverflow,
  );
}

function rememberLiveIdentity(eventId: string, sequence: number): void {
  seenLiveIds.set(eventId, sequence);
  seenLiveSequences.set(sequence, eventId);
  seenLiveOrder.push({ eventId, sequence });
  while (seenLiveOrder.length > MAX_LIVE_IDENTITIES) {
    const oldest = seenLiveOrder.shift();
    if (oldest !== undefined) {
      seenLiveIds.delete(oldest.eventId);
      seenLiveSequences.delete(oldest.sequence);
    }
  }
}

function settleAcknowledgementContexts(): void {
  const current = page.value;
  if (current === null || acknowledgementContexts.size === 0) {
    return;
  }
  for (const [identity, context] of [...acknowledgementContexts.entries()]) {
    const authoritative = (current.items ?? []).find(
      (candidate) => candidate.eventId === identity,
    );
    const acknowledged =
      authoritative !== undefined &&
      authoritative.revision === 1 &&
      authoritative.acknowledgedAt !== null &&
      authoritative.acknowledgedAt !== undefined;
    if (acknowledged || (authoritative === undefined && context.outcome === "VALID_RECEIPT")) {
      finishAcknowledgement(identity);
      error.value =
        context.outcome === "INVALID_RECEIPT"
          ? "提醒确认回执无效；权威状态显示提醒已确认。"
          : context.outcome === "CONFLICT"
            ? "提醒状态已更新，请核对最新状态。"
            : null;
      operationStatus.value = "提醒已确认；确认提醒不代表成交，也不会修改持仓。";
      void restoreAcknowledgementFocus(context.hadFocus);
      continue;
    }
    if (authoritative !== undefined) {
      if (context.outcome === "VALID_RECEIPT") {
        error.value = "提醒确认回执与权威分页不一致，请重试加载。";
        operationStatus.value = error.value;
        void restoreAcknowledgementFocus(context.hadFocus);
        continue;
      }
      finishAcknowledgement(identity);
      error.value = acknowledgementFailureMessage(context.outcome);
      operationStatus.value = error.value;
      void restoreAcknowledgementFocus(context.hadFocus);
      continue;
    }
    error.value = acknowledgementFailureMessage(context.outcome);
    operationStatus.value = error.value;
    void restoreAcknowledgementFocus(context.hadFocus);
  }
}

function finishAcknowledgement(identity: string): void {
  acknowledgementContexts.delete(identity);
  acknowledgementsAwaitingRefresh.value = withIdentity(
    acknowledgementsAwaitingRefresh.value,
    identity,
    false,
  );
}

function acknowledgementFailureMessage(outcome: AcknowledgementOutcome): string {
  if (outcome === "INVALID_RECEIPT") {
    return "提醒确认回执无效；已重新加载权威状态。";
  }
  if (outcome === "CONFLICT") {
    return "权威状态仍为未确认，请重试确认。";
  }
  if (outcome === "VALID_RECEIPT") {
    return "提醒确认后的权威状态尚未同步，请重试加载。";
  }
  return "提醒确认失败，请稍后重试。";
}

function applyAuthoritativePage(candidate: AlertPage | null, expected: AlertQuery): boolean {
  try {
    if (candidate === null) {
      page.value = null;
      return true;
    }
    if (!isValidPage(candidate, expected)) {
      page.value = null;
      error.value = "提醒数据无效，请重新加载。";
      restorePendingAcknowledgementFocus();
      return false;
    }
    page.value = freezeClone(candidate);
    return true;
  } catch {
    page.value = null;
    error.value = "提醒数据无效，请重新加载。";
    restorePendingAcknowledgementFocus();
    return false;
  }
}

function restorePendingAcknowledgementFocus(): void {
  if (acknowledgementContexts.size === 0) {
    return;
  }
  operationStatus.value = "提醒数据无效，确认状态尚未同步。";
  for (const context of acknowledgementContexts.values()) {
    void restoreAcknowledgementFocus(context.hadFocus);
  }
}

function isValidPage(candidate: AlertPage, expected: AlertQuery): boolean {
  const items = candidate.items ?? [];
  const eventIds = new Set<string>();
  const sequences = new Set<number>();
  if (
    candidate.offset !== expected.offset ||
    candidate.limit !== expected.limit ||
    (candidate.symbol ?? null) !== expected.symbol ||
    (candidate.signalType ?? null) !== expected.signalType ||
    (candidate.acknowledged ?? null) !== expected.acknowledged ||
    (candidate.startAt ?? null) !== expected.startAt ||
    (candidate.endAt ?? null) !== expected.endAt ||
    items.length > candidate.limit ||
    (items.length > 0 && candidate.offset + items.length > candidate.total)
  ) {
    return false;
  }
  for (const item of items) {
    const acknowledged = item.acknowledgedAt !== null && item.acknowledgedAt !== undefined;
    if (
      eventIds.has(item.eventId) ||
      sequences.has(item.sequence) ||
      (expected.symbol !== null && item.symbol !== expected.symbol) ||
      !matchesAlertSignalFilter(item, expected.signalType) ||
      (expected.acknowledged !== null && acknowledged !== expected.acknowledged) ||
      (expected.startAt !== null && item.createdAt < expected.startAt) ||
      (expected.endAt !== null && item.createdAt > expected.endAt) ||
      (acknowledged ? item.revision !== 1 : item.revision !== 0)
    ) {
      return false;
    }
    eventIds.add(item.eventId);
    sequences.add(item.sequence);
  }
  return true;
}

function withIdentity(
  source: ReadonlySet<string>,
  identity: string,
  include: boolean,
): ReadonlySet<string> {
  const next = new Set(source);
  if (include) {
    next.add(identity);
  } else {
    next.delete(identity);
  }
  return next;
}

function queryFromPage(value: AlertPage | null): AlertQuery {
  return freezeClone({
    acknowledged: value?.acknowledged ?? null,
    endAt: value?.endAt ?? null,
    limit: value?.limit ?? 20,
    offset: value?.offset ?? 0,
    signalType: value?.signalType ?? null,
    startAt: value?.startAt ?? null,
    symbol: value?.symbol ?? null,
  });
}

function freezeClone<Value>(value: Value): Value {
  return deepFreeze(clonePlain(value));
}

function clonePlain<Value>(value: Value): Value {
  if (Array.isArray(value)) {
    return value.map((item) => clonePlain(item)) as Value;
  }
  if (typeof value === "object" && value !== null) {
    const cloned: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value)) {
      cloned[key] = clonePlain(item);
    }
    return cloned as Value;
  }
  return value;
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

function isConflict(value: unknown): boolean {
  try {
    return typeof value === "object" && value !== null && Reflect.get(value, "status") === 409;
  } catch {
    return false;
  }
}
</script>

<template>
  <section class="alerts-view" aria-labelledby="alerts-title">
    <PageIntro title="文字提醒中心" title-id="alerts-title" eyebrow="03 / ALERT CENTER" description="关注需要行动的时刻。提醒、确认与人工成交是彼此独立的操作。" />

    <p v-if="error !== null" class="alerts-view__error" role="alert">{{ error }}</p>
    <p
      ref="operationStatus"
      v-show="operationStatus !== ''"
      class="alerts-view__operation-status"
      role="status"
      aria-live="polite"
      aria-atomic="true"
      tabindex="-1"
    >{{ operationStatus }}</p>
    <button
      v-if="error !== null || page === null"
      type="button"
      data-retry-alerts="true"
      :disabled="busy || initialLoading"
      @click="retryAlerts"
    >重新加载提醒</button>

    <div class="alerts-view__layout">
      <AlertTable
        :busy="busy || initialLoading"
        :page="page"
        :pending-acknowledgements="pendingAcknowledgements"
        :query="query"
        @acknowledge="acknowledge"
        @apply-filters="applyFilters"
        @page-change="changePage"
      />
      <AlertRail :busy="busy || initialLoading" :live-update-count="liveUpdateCount" />
    </div>
  </section>
</template>

<style scoped>
.alerts-view {
  display: grid;
  gap: var(--space-7);
}

.alerts-view__error,
.alerts-view__operation-status {
  padding: var(--space-4);
  background: var(--color-surface-graphite);
  border: var(--border-technical);
}

.alerts-view__error {
  margin: 0;
  color: var(--color-signal-risk-vermilion);
}

.alerts-view__layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(14rem, 20rem);
  gap: var(--space-6);
  align-items: start;
}

@media (max-width: 64rem) {
  .alerts-view__layout {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
