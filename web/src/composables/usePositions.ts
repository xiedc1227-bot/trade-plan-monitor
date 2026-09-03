import { computed, shallowReadonly, shallowRef, toRef, toValue, watch } from "vue";
import type { ComputedRef, MaybeRefOrGetter, ShallowRef } from "vue";

import type {
  PositionLotClosureCommand,
  PositionLotClosureView,
  PositionLotCreateCommand,
  PositionLotPage,
  PositionPrefillView,
  components,
} from "../api/generated";

export type PositionLot =
  components["schemas"]["trade_plan_monitor__web__routers__positions__PositionLotView"];
export type PositionSummaryLot =
  components["schemas"]["trade_plan_monitor__web__routers__symbols__PositionLotView"];

export interface PositionCreateDraft {
  acquiredTradeDate: string;
  bucket: PositionLotCreateCommand["bucket"];
  costFen: number;
  quantity: number;
  relatedAlertId: string | null;
}

export interface PositionReductionDraft {
  expectedRevision: number;
  lotId: string;
  quantity: number;
}

export interface PositionMutationRequest<TCommand> {
  command: TCommand;
  idempotencyKey: string;
}

export interface PositionListRequest {
  asOfTradeDate: string;
  limit: number;
  offset: number;
  symbol: string;
}

interface PositionContext {
  asOfTradeDate: string;
  symbol: string;
}

interface RetainedMutationIntent {
  identity: string;
  key: string;
}

export interface PositionOperations {
  closePosition(
    request: PositionMutationRequest<PositionLotClosureCommand>,
  ): Promise<PositionLotClosureView>;
  createPosition(request: PositionMutationRequest<PositionLotCreateCommand>): Promise<PositionLot>;
  listPositions(request: PositionListRequest): Promise<PositionLotPage>;
}

export interface DisplayPositionLot {
  acquiredTradeDate: string;
  bucket: PositionLot["bucket"];
  closedAt: string | null;
  costFen: number;
  lotId: string;
  quantity: number;
  relatedAlertId: string | null;
  remainingQuantity: number;
  revision: number | null;
  sellableQuantity: number;
  symbol: string;
}

interface UsePositionsOptions {
  asOfTradeDate: MaybeRefOrGetter<string>;
  createIdempotencyKey?: () => string;
  initialPage: MaybeRefOrGetter<PositionLotPage | null>;
  operations: MaybeRefOrGetter<PositionOperations | null>;
  prefill: MaybeRefOrGetter<PositionPrefillView | null>;
  summaryLots: MaybeRefOrGetter<readonly PositionSummaryLot[]>;
  symbol: MaybeRefOrGetter<string>;
}

interface UsePositionsResult {
  busy: Readonly<ShallowRef<boolean>>;
  error: Readonly<ShallowRef<string | null>>;
  lots: ComputedRef<readonly DisplayPositionLot[]>;
  page: Readonly<ShallowRef<PositionLotPage | null>>;
  prefill: Readonly<ShallowRef<PositionPrefillView | null>>;
  recordPosition(draft: PositionCreateDraft): Promise<boolean>;
  reducePosition(draft: PositionReductionDraft): Promise<boolean>;
  refresh(): Promise<boolean>;
  validateCreation(draft: PositionCreateDraft): readonly string[];
  validateReduction(draft: PositionReductionDraft): readonly string[];
}

const boardLot = 100;
const pageLimit = 100;
const idempotencyKeyPattern = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const deterministicClientRejectionStatuses = new Set([
  400, 401, 403, 404, 405, 409, 413, 422, 429,
]);

export function usePositions(options: UsePositionsOptions): UsePositionsResult {
  const symbol = toRef(options.symbol);
  const asOfTradeDate = toRef(options.asOfTradeDate);
  const initialPage = toRef(options.initialPage);
  const incomingPrefill = toRef(options.prefill);
  const page = shallowRef<PositionLotPage | null>(null);
  const prefill = shallowRef<PositionPrefillView | null>(null);
  const busy = shallowRef(false);
  const error = shallowRef<string | null>(null);
  let pageGeneration = 0;
  let retainedMutationIntent: RetainedMutationIntent | null = null;

  watch(
    [symbol, asOfTradeDate, initialPage],
    () => {
      pageGeneration += 1;
      const candidate = toValue(options.initialPage);
      if (candidate === null) {
        page.value = null;
        error.value = null;
        return;
      }
      const accepted = freezePage(candidate, currentContext());
      page.value = accepted;
      error.value =
        accepted === null ? "持仓响应与当前股票或日期不一致，请重新刷新" : null;
    },
    { immediate: true },
  );

  watch(
    [symbol, incomingPrefill],
    () => {
      const candidate = toValue(options.prefill);
      prefill.value =
        candidate !== null && candidate.symbol === currentSymbol()
          ? Object.freeze({ ...candidate })
          : null;
    },
    { immediate: true },
  );

  const lots = computed<readonly DisplayPositionLot[]>(() => {
    if (page.value !== null) {
      return Object.freeze(
        (page.value.items ?? []).map((lot) =>
          Object.freeze({
            ...lot,
            closedAt: lot.closedAt ?? null,
            relatedAlertId: lot.relatedAlertId ?? null,
          }),
        ),
      );
    }
    return Object.freeze(
      toValue(options.summaryLots).map((lot) =>
        Object.freeze({
          ...lot,
          closedAt: null,
          relatedAlertId: null,
          revision: null,
          symbol: currentSymbol(),
        }),
      ),
    );
  });

  function currentSymbol(): string {
    return toValue(options.symbol);
  }

  function currentDate(): string {
    return toValue(options.asOfTradeDate);
  }

  function freezePage(
    candidate: PositionLotPage,
    context: PositionContext,
  ): PositionLotPage | null {
    const items = candidate.items ?? [];
    if (
      candidate.symbol !== context.symbol ||
      candidate.asOfTradeDate !== context.asOfTradeDate ||
      items.some((lot) => lot.symbol !== context.symbol)
    ) {
      return null;
    }
    return Object.freeze({
      ...candidate,
      items: Object.freeze(items.map((lot) => Object.freeze({ ...lot }))),
    }) as unknown as PositionLotPage;
  }

  function validateCreation(draft: PositionCreateDraft): readonly string[] {
    const issues: string[] = [];
    if (!isDate(draft.acquiredTradeDate)) {
      issues.push("请选择有效的建仓交易日");
    }
    if (!isBoardLot(draft.quantity)) {
      issues.push("建仓数量必须是正数且为 100 股整手");
    }
    if (!Number.isSafeInteger(draft.costFen) || draft.costFen <= 0) {
      issues.push("成本价必须是正整数分");
    }
    return Object.freeze(issues);
  }

  function validateReduction(draft: PositionReductionDraft): readonly string[] {
    const issues: string[] = [];
    const lot = operationLot(draft.lotId);
    if (lot === null) {
      issues.push("请选择可操作的权威持仓批次");
      return Object.freeze(issues);
    }
    if (draft.expectedRevision !== lot.revision) {
      issues.push("持仓批次已更新，请重新复核减仓");
    }
    if (!isBoardLot(draft.quantity)) {
      issues.push("减仓数量必须是正数且为 100 股整手");
    }
    return Object.freeze(issues);
  }

  async function refresh(): Promise<boolean> {
    const operations = toValue(options.operations);
    if (operations === null) {
      error.value = "当前未配置持仓操作通道";
      return false;
    }
    const result = await refreshWith(operations, currentContext(), "持仓刷新失败，请稍后重试");
    return result === "applied";
  }

  async function recordPosition(draft: PositionCreateDraft): Promise<boolean> {
    const issues = validateCreation(draft);
    if (issues.length > 0) {
      error.value = issues[0] ?? "建仓输入无效";
      return false;
    }
    const operations = toValue(options.operations);
    if (operations === null || busy.value) {
      error.value = operations === null ? "当前未配置持仓操作通道" : "持仓操作正在处理中";
      return false;
    }
    const context = currentContext();
    const command: PositionLotCreateCommand = {
      acquiredTradeDate: draft.acquiredTradeDate,
      bucket: draft.bucket,
      costFen: draft.costFen,
      expectedRevision: 0,
      quantity: draft.quantity,
      relatedAlertId: draft.relatedAlertId,
      symbol: context.symbol,
    };
    const intentIdentity = mutationIdentity("CREATE", command);
    const idempotencyKey = idempotencyKeyFor(intentIdentity);
    if (!idempotencyKeyPattern.test(idempotencyKey)) {
      error.value = "无法生成有效的持仓请求标识";
      return false;
    }
    busy.value = true;
    error.value = null;
    try {
      const receipt = await operations.createPosition({
        command,
        idempotencyKey,
      });
      if (!isCurrentContext(context)) {
        error.value = "页面已切换；持仓操作可能已成功，请在原股票页面重新加载核对";
        return false;
      }
      if (!creationReceiptMatches(receipt, command)) {
        await refreshAfterReceiptMismatch(context, operations);
        error.value = "建仓操作可能已成功，但回执不一致，请重新加载核对";
        return false;
      }
      const confirmed = await refreshAfterMutation(context, operations, (candidate) =>
        pageContainsLot(candidate, receipt),
      );
      if (confirmed) releaseMutationIntent(intentIdentity);
      return confirmed;
    } catch (caught: unknown) {
      if (isDeterministicClientRejection(errorStatus(caught))) {
        releaseMutationIntent(intentIdentity);
      }
      await handleMutationFailure(caught, operations, context);
      return false;
    } finally {
      busy.value = false;
    }
  }

  async function reducePosition(draft: PositionReductionDraft): Promise<boolean> {
    const issues = validateReduction(draft);
    if (issues.length > 0) {
      error.value = issues[0] ?? "减仓输入无效";
      return false;
    }
    const operations = toValue(options.operations);
    const lot = operationLot(draft.lotId);
    if (operations === null || lot === null || busy.value) {
      error.value = operations === null ? "当前未配置持仓操作通道" : "持仓操作正在处理中";
      return false;
    }
    const context = currentContext();
    const command: PositionLotClosureCommand = {
      expectedRevision: draft.expectedRevision,
      lotId: lot.lotId,
      quantity: draft.quantity,
      tradeDate: context.asOfTradeDate,
    };
    const intentIdentity = mutationIdentity("CLOSE", command);
    const idempotencyKey = idempotencyKeyFor(intentIdentity);
    if (!idempotencyKeyPattern.test(idempotencyKey)) {
      error.value = "无法生成有效的持仓请求标识";
      return false;
    }
    busy.value = true;
    error.value = null;
    try {
      const receipt = await operations.closePosition({
        command,
        idempotencyKey,
      });
      if (!isCurrentContext(context)) {
        error.value = "页面已切换；持仓操作可能已成功，请在原股票页面重新加载核对";
        return false;
      }
      if (!closureReceiptMatches(receipt, command, lot)) {
        await refreshAfterReceiptMismatch(context, operations);
        error.value = "减仓操作可能已成功，但回执不一致，请重新加载核对";
        return false;
      }
      const confirmed = await refreshAfterMutation(context, operations, (candidate) =>
        pageContainsLot(candidate, receipt.lot),
      );
      if (confirmed) releaseMutationIntent(intentIdentity);
      return confirmed;
    } catch (caught: unknown) {
      if (isDeterministicClientRejection(errorStatus(caught))) {
        releaseMutationIntent(intentIdentity);
      }
      await handleMutationFailure(caught, operations, context);
      return false;
    } finally {
      busy.value = false;
    }
  }

  function operationLot(lotId: string): PositionLot | null {
    return (page.value?.items ?? []).find((lot) => lot.lotId === lotId) ?? null;
  }

  function currentContext(): PositionContext {
    return { asOfTradeDate: currentDate(), symbol: currentSymbol() };
  }

  function listRequest(context: PositionContext): PositionListRequest {
    return {
      asOfTradeDate: context.asOfTradeDate,
      limit: pageLimit,
      offset: 0,
      symbol: context.symbol,
    };
  }

  type RefreshResult = "applied" | "failed" | "invalid" | "stale";

  async function refreshWith(
    operations: PositionOperations,
    context: PositionContext,
    failureMessage: string,
  ): Promise<RefreshResult> {
    const generation = ++pageGeneration;
    try {
      const refreshed = await operations.listPositions(listRequest(context));
      if (generation !== pageGeneration || !isCurrentContext(context)) {
        return "stale";
      }
      const accepted = freezePage(refreshed, context);
      page.value = accepted;
      if (accepted === null) {
        error.value = "持仓响应与当前股票或日期不一致，请重新刷新";
        return "invalid";
      }
      error.value = null;
      return "applied";
    } catch {
      if (generation !== pageGeneration || !isCurrentContext(context)) {
        return "stale";
      }
      error.value = failureMessage;
      return "failed";
    }
  }

  async function refreshAfterMutation(
    context: PositionContext,
    operations: PositionOperations,
    confirmsMutation: (candidate: PositionLotPage) => boolean,
  ): Promise<boolean> {
    if (!isCurrentContext(context)) {
      error.value = "页面已切换；持仓操作可能已成功，请在原股票页面重新加载核对";
      return false;
    }
    const result = await refreshWith(
      operations,
      context,
      "持仓操作可能已成功，但刷新失败，请重新加载核对",
    );
    if (result === "applied" && page.value !== null) {
      if (confirmsMutation(page.value)) {
        return true;
      }
      error.value = "持仓操作可能已成功，但刷新结果未确认该变更，请重新加载核对";
      return false;
    }
    if (result === "invalid") {
      error.value = "持仓操作可能已成功，但响应身份不一致，请重新加载核对";
      return false;
    }
    if (result === "stale") {
      error.value = isCurrentContext(context)
        ? "持仓操作可能已成功，但页面已有较新状态，请重新核对"
        : "页面已切换；持仓操作可能已成功，请在原股票页面重新加载核对";
      return false;
    }
    if (result === "failed") {
      error.value = "持仓操作可能已成功，但刷新失败，请重新加载核对";
    }
    return false;
  }

  function isCurrentContext(context: PositionContext): boolean {
    return context.symbol === currentSymbol() && context.asOfTradeDate === currentDate();
  }

  async function refreshAfterReceiptMismatch(
    context: PositionContext,
    operations: PositionOperations,
  ): Promise<void> {
    if (!isCurrentContext(context)) {
      return;
    }
    await refreshWith(operations, context, "持仓刷新失败，请重新加载核对");
  }

  async function handleMutationFailure(
    caught: unknown,
    operations: PositionOperations,
    context: PositionContext,
  ): Promise<void> {
    if (errorStatus(caught) === 409) {
      if (!isCurrentContext(context)) {
        error.value = "页面已切换；原股票持仓发生冲突，请在原股票页面重新加载核对";
        return;
      }
      const result = await refreshWith(
        operations,
        context,
        "持仓冲突后未能刷新权威批次，请重新加载后核对",
      );
      if (result === "applied") {
        error.value = "后端拒绝了持仓操作，请核对最新批次和计划规则后重试";
        return;
      }
      if (result === "failed") {
        page.value = null;
        error.value = "持仓冲突后未能刷新权威批次，请重新加载后核对";
        return;
      }
      if (result === "invalid") {
        page.value = null;
        error.value = "持仓冲突后的刷新身份不一致，请重新加载后核对";
        return;
      }
      error.value = isCurrentContext(context)
        ? "持仓已发生变化，页面已有较新状态，请重新复核"
        : "页面已切换；原股票持仓发生冲突，请在原股票页面重新加载核对";
      return;
    }
    error.value = "持仓操作失败，请核对输入后重试";
  }

  function createIdempotencyKey(): string {
    if (options.createIdempotencyKey !== undefined) {
      return options.createIdempotencyKey();
    }
    return `position-${crypto.randomUUID()}`;
  }

  function idempotencyKeyFor(identity: string): string {
    if (retainedMutationIntent?.identity === identity) {
      return retainedMutationIntent.key;
    }
    const key = createIdempotencyKey();
    retainedMutationIntent = idempotencyKeyPattern.test(key)
      ? Object.freeze({ identity, key })
      : null;
    return key;
  }

  function releaseMutationIntent(identity: string): void {
    if (retainedMutationIntent?.identity === identity) {
      retainedMutationIntent = null;
    }
  }

  return {
    busy: shallowReadonly(busy),
    error: shallowReadonly(error),
    lots,
    page: shallowReadonly(page),
    prefill: shallowReadonly(prefill),
    recordPosition,
    reducePosition,
    refresh,
    validateCreation,
    validateReduction,
  };
}

function isBoardLot(quantity: number): boolean {
  return Number.isSafeInteger(quantity) && quantity > 0 && quantity % boardLot === 0;
}

function isDate(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(value);
}

function creationReceiptMatches(
  receipt: PositionLot,
  command: PositionLotCreateCommand,
): boolean {
  return (
    receipt.symbol === command.symbol &&
    receipt.acquiredTradeDate === command.acquiredTradeDate &&
    receipt.bucket === command.bucket &&
    receipt.costFen === command.costFen &&
    receipt.quantity === command.quantity &&
    receipt.remainingQuantity === command.quantity &&
    receipt.revision === 0 &&
    (receipt.closedAt ?? null) === null &&
    (receipt.relatedAlertId ?? null) === (command.relatedAlertId ?? null)
  );
}

function closureReceiptMatches(
  receipt: PositionLotClosureView,
  command: PositionLotClosureCommand,
  before: PositionLot,
): boolean {
  return (
    receipt.tradeDate === command.tradeDate &&
    receipt.appliedQuantity === command.quantity &&
    receipt.beforeRemainingQuantity === before.remainingQuantity &&
    receipt.afterRemainingQuantity === before.remainingQuantity - command.quantity &&
    receipt.lot.lotId === command.lotId &&
    receipt.lot.symbol === before.symbol &&
    receipt.lot.revision === command.expectedRevision + command.quantity / boardLot &&
    receipt.lot.remainingQuantity === receipt.afterRemainingQuantity &&
    receipt.lot.acquiredTradeDate === before.acquiredTradeDate &&
    receipt.lot.bucket === before.bucket &&
    receipt.lot.costFen === before.costFen &&
    receipt.lot.quantity === before.quantity &&
    (receipt.lot.relatedAlertId ?? null) === (before.relatedAlertId ?? null)
  );
}

function pageContainsLot(candidate: PositionLotPage, expected: PositionLot): boolean {
  const actual = (candidate.items ?? []).find((lot) => lot.lotId === expected.lotId);
  return (
    actual !== undefined &&
    actual.symbol === expected.symbol &&
    actual.revision === expected.revision &&
    actual.remainingQuantity === expected.remainingQuantity &&
    actual.sellableQuantity === expected.sellableQuantity &&
    actual.acquiredTradeDate === expected.acquiredTradeDate &&
    actual.bucket === expected.bucket &&
    actual.costFen === expected.costFen &&
    actual.quantity === expected.quantity &&
    (actual.closedAt ?? null) === (expected.closedAt ?? null) &&
    (actual.relatedAlertId ?? null) === (expected.relatedAlertId ?? null)
  );
}

function errorStatus(caught: unknown): number | null {
  try {
    if (typeof caught !== "object" || caught === null || !("status" in caught)) {
      return null;
    }
    return typeof caught.status === "number" ? caught.status : null;
  } catch {
    return null;
  }
}

function isDeterministicClientRejection(status: number | null): boolean {
  return status !== null && deterministicClientRejectionStatuses.has(status);
}

function mutationIdentity(
  operation: "CLOSE" | "CREATE",
  command: PositionLotClosureCommand | PositionLotCreateCommand,
): string {
  return `${operation}:${JSON.stringify(command)}`;
}
