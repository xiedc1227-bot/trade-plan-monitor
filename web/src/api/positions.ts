import type {
  PositionInventoryClosureCommand,
  PositionInventoryClosureView,
  PositionInventoryConfirmationCommand,
  PositionInventoryView,
  PositionLotClosureCommand,
  PositionLotClosureView,
  PositionLotCreateCommand,
  PositionLotPage,
  components,
  paths,
} from "./generated";
import { isShanghaiDateTime } from "./shanghaiTime";
import { invalidResponse, requestJson } from "./transport";

export type PositionLot =
  components["schemas"]["trade_plan_monitor__web__routers__positions__PositionLotView"];

type PositionListQuery =
  paths["/api/v1/position-lots"]["get"]["parameters"]["query"];

export type PositionListRequest = PositionListQuery & {
  readonly limit: number;
  readonly offset: number;
};

export interface PositionRequestOptions {
  readonly signal?: AbortSignal;
}

export interface PositionApi {
  closePosition(
    command: PositionLotClosureCommand,
    idempotencyKey: string,
    options?: PositionRequestOptions,
  ): Promise<PositionLotClosureView>;
  createPosition(
    command: PositionLotCreateCommand,
    idempotencyKey: string,
    options?: PositionRequestOptions,
  ): Promise<PositionLot>;
  listPositions(
    request: PositionListRequest,
    options?: PositionRequestOptions,
  ): Promise<PositionLotPage>;
}

export interface PositionInventoryApi {
  closeInventory(
    command: PositionInventoryClosureCommand,
    idempotencyKey: string,
    options?: PositionRequestOptions,
  ): Promise<PositionInventoryClosureView>;
  confirmInventory(
    command: PositionInventoryConfirmationCommand,
    idempotencyKey: string,
    options?: PositionRequestOptions,
  ): Promise<PositionInventoryView>;
  getInventory(
    symbol: string,
    asOfTradeDate: string,
    options?: PositionRequestOptions,
  ): Promise<PositionInventoryView>;
}

const idempotencyKeyPattern = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const uuidPattern =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function createPositionApi(
  fetchImplementation: typeof fetch = globalThis.fetch.bind(globalThis),
): PositionApi & PositionInventoryApi {
  return Object.freeze({
    async getInventory(symbol: string, asOfTradeDate: string, options?: PositionRequestOptions) {
      if (!isShareSymbol(symbol) || !isCalendarDate(asOfTradeDate)) throw invalidResponse(0);
      const search = new URLSearchParams({ asOfTradeDate, symbol });
      const { body, status } = await requestJson(
        fetchImplementation,
        `/api/v1/position-inventory?${search.toString()}`,
        readRequest(options),
      );
      if (!isInventory(body, symbol, asOfTradeDate)) throw invalidResponse(status);
      return body;
    },

    async confirmInventory(command: PositionInventoryConfirmationCommand, idempotencyKey: string, options?: PositionRequestOptions) {
      requireInventoryConfirmation(command);
      const { body, status } = await requestJson(
        fetchImplementation,
        "/api/v1/position-inventory-confirmations",
        mutationRequest(command, idempotencyKey, options),
      );
      if (!isInventory(body, command.symbol, command.asOfTradeDate) ||
        body.inventoryRevision !== command.expectedRevision + 1 ||
        body.status !== "KNOWN" || body.totalQuantity !== command.totalQuantity ||
        body.sellableQuantity !== command.sellableQuantity) throw invalidResponse(status);
      return body;
    },

    async closeInventory(command: PositionInventoryClosureCommand, idempotencyKey: string, options?: PositionRequestOptions) {
      requireInventoryClosure(command);
      const { body, status } = await requestJson(
        fetchImplementation,
        "/api/v1/position-inventory-closures",
        mutationRequest(command, idempotencyKey, options),
      );
      if (!isInventoryClosure(body, command)) throw invalidResponse(status);
      return body;
    },

    async listPositions(
      request: PositionListRequest,
      options?: PositionRequestOptions,
    ) {
      requireListRequest(request);
      const search = new URLSearchParams();
      search.set("symbol", request.symbol);
      search.set("asOfTradeDate", request.asOfTradeDate);
      search.set("offset", String(request.offset));
      search.set("limit", String(request.limit));
      const { body, status } = await requestJson(
        fetchImplementation,
        `/api/v1/position-lots?${search.toString()}`,
        readRequest(options),
      );
      if (!isPositionPage(body, request)) throw invalidResponse(status);
      return body;
    },

    async createPosition(
      command: PositionLotCreateCommand,
      idempotencyKey: string,
      options?: PositionRequestOptions,
    ) {
      requireCreateCommand(command);
      const { body, status } = await requestJson(
        fetchImplementation,
        "/api/v1/position-lots",
        mutationRequest(command, idempotencyKey, options),
      );
      if (!isCreationReceipt(body, command)) throw invalidResponse(status);
      return body;
    },

    async closePosition(
      command: PositionLotClosureCommand,
      idempotencyKey: string,
      options?: PositionRequestOptions,
    ) {
      requireClosureCommand(command);
      const { body, status } = await requestJson(
        fetchImplementation,
        "/api/v1/position-lot-closures",
        mutationRequest(command, idempotencyKey, options),
      );
      if (!isClosureReceipt(body, command)) throw invalidResponse(status);
      return body;
    },
  });
}

function readRequest(options?: PositionRequestOptions): RequestInit {
  return {
    headers: { Accept: "application/json" },
    method: "GET",
    ...(options?.signal === undefined ? {} : { signal: options.signal }),
  };
}

function mutationRequest(
  command: PositionLotCreateCommand | PositionLotClosureCommand | PositionInventoryConfirmationCommand | PositionInventoryClosureCommand,
  idempotencyKey: string,
  options?: PositionRequestOptions,
): RequestInit {
  if (!idempotencyKeyPattern.test(idempotencyKey)) {
    throw new RangeError("idempotency key is invalid");
  }
  return {
    body: JSON.stringify(command),
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    },
    method: "POST",
    ...(options?.signal === undefined ? {} : { signal: options.signal }),
  };
}

function requireInventoryConfirmation(command: PositionInventoryConfirmationCommand): void {
  if (!isShareSymbol(command.symbol) || !isCalendarDate(command.asOfTradeDate) ||
    !isNonnegativeInteger(command.expectedRevision) || !isBoardLotOrZero(command.totalQuantity) ||
    !isBoardLotOrZero(command.sellableQuantity) || command.sellableQuantity > command.totalQuantity ||
    command.completeRegistration !== true ||
    !(command.includedLotIds === undefined || command.includedLotIds.every(isUuid))) {
    throw new RangeError("inventory confirmation command is invalid");
  }
}

function requireInventoryClosure(command: PositionInventoryClosureCommand): void {
  if (!isInventorySourceType(command.sourceType) || typeof command.sourceId !== "string" ||
    command.sourceId.length === 0 || !isBoardLot(command.quantity) ||
    !isCalendarDate(command.tradeDate) || !isNonnegativeInteger(command.expectedRevision)) {
    throw new RangeError("inventory closure command is invalid");
  }
}

function requireListRequest(request: PositionListRequest): void {
  if (
    !isShareSymbol(request.symbol) ||
    !isCalendarDate(request.asOfTradeDate) ||
    !isIntegerBetween(request.offset, 0, 10_000) ||
    !isIntegerBetween(request.limit, 1, 100)
  ) {
    throw new RangeError("position list request is invalid");
  }
}

function requireCreateCommand(command: PositionLotCreateCommand): void {
  if (
    !isShareSymbol(command.symbol) ||
    (command.bucket !== "CORE" && command.bucket !== "TACTICAL") ||
    !isBoardLot(command.quantity) ||
    !isCalendarDate(command.acquiredTradeDate) ||
    !isPositiveInteger(command.costFen) ||
    command.expectedRevision !== 0 ||
    !isNullableUuid(command.relatedAlertId)
  ) {
    throw new RangeError("position creation command is invalid");
  }
}

function requireClosureCommand(command: PositionLotClosureCommand): void {
  if (
    !isUuid(command.lotId) ||
    !isBoardLot(command.quantity) ||
    !isCalendarDate(command.tradeDate) ||
    !isNonnegativeInteger(command.expectedRevision)
  ) {
    throw new RangeError("position closure command is invalid");
  }
}

function isPositionPage(
  value: unknown,
  request: PositionListRequest,
): value is PositionLotPage {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, ["asOfTradeDate", "items", "limit", "offset", "symbol", "total"]) ||
    !hasKeys(value, ["asOfTradeDate", "limit", "offset", "symbol", "total"]) ||
    value.symbol !== request.symbol ||
    value.asOfTradeDate !== request.asOfTradeDate ||
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
    !items.every(
      (item) =>
        isPositionLot(item) &&
        item.symbol === request.symbol &&
        (item.acquiredTradeDate < request.asOfTradeDate || item.sellableQuantity === 0),
    )
  ) {
    return false;
  }
  return new Set(items.map((item) => item.lotId)).size === items.length;
}

function isCreationReceipt(
  value: unknown,
  command: PositionLotCreateCommand,
): value is PositionLot {
  return (
    isPositionLot(value) &&
    value.symbol === command.symbol &&
    value.bucket === command.bucket &&
    value.quantity === command.quantity &&
    value.remainingQuantity === command.quantity &&
    value.acquiredTradeDate === command.acquiredTradeDate &&
    value.costFen === command.costFen &&
    (value.relatedAlertId ?? null) === (command.relatedAlertId ?? null) &&
    (value.closedAt ?? null) === null &&
    value.revision === 0
  );
}

function isClosureReceipt(
  value: unknown,
  command: PositionLotClosureCommand,
): value is PositionLotClosureView {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "afterRemainingQuantity",
      "appliedQuantity",
      "beforeRemainingQuantity",
      "lot",
      "tradeDate",
    ]) ||
    !isPositionLot(value.lot) ||
    value.lot.lotId !== command.lotId ||
    value.tradeDate !== command.tradeDate ||
    value.appliedQuantity !== command.quantity ||
    !isBoardLot(value.beforeRemainingQuantity) ||
    !isBoardLotOrZero(value.afterRemainingQuantity) ||
    value.beforeRemainingQuantity > value.lot.quantity ||
    value.afterRemainingQuantity !== value.lot.remainingQuantity ||
    value.beforeRemainingQuantity - value.afterRemainingQuantity !== command.quantity ||
    value.lot.acquiredTradeDate >= command.tradeDate
  ) {
    return false;
  }
  const beforeRevision =
    (value.lot.quantity - value.beforeRemainingQuantity) / 100;
  return (
    beforeRevision === command.expectedRevision &&
    value.lot.revision === command.expectedRevision + command.quantity / 100
  );
}

function isPositionLot(value: unknown): value is PositionLot {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, [
      "acquiredTradeDate",
      "bucket",
      "closedAt",
      "costFen",
      "lotId",
      "quantity",
      "relatedAlertId",
      "remainingQuantity",
      "revision",
      "sellableQuantity",
      "symbol",
    ]) ||
    !hasKeys(value, [
      "acquiredTradeDate",
      "bucket",
      "costFen",
      "lotId",
      "quantity",
      "remainingQuantity",
      "revision",
      "sellableQuantity",
      "symbol",
    ]) ||
    !isUuid(value.lotId) ||
    !isShareSymbol(value.symbol) ||
    (value.bucket !== "CORE" && value.bucket !== "TACTICAL") ||
    !isBoardLot(value.quantity) ||
    !isBoardLotOrZero(value.remainingQuantity) ||
    value.remainingQuantity > value.quantity ||
    !isBoardLotOrZero(value.sellableQuantity) ||
    value.sellableQuantity > value.remainingQuantity ||
    !isCalendarDate(value.acquiredTradeDate) ||
    !isPositiveInteger(value.costFen) ||
    !isNullableUuid(value.relatedAlertId) ||
    !isNullableShanghaiDateTime(value.closedAt) ||
    !isNonnegativeInteger(value.revision)
  ) {
    return false;
  }
  return (
    (value.remainingQuantity === 0) === ((value.closedAt ?? null) !== null) &&
    value.revision === (value.quantity - value.remainingQuantity) / 100
  );
}

function isInventory(
  value: unknown,
  symbol: string,
  asOfTradeDate: string,
): value is PositionInventoryView {
  if (!isRecord(value) || value.symbol !== symbol || value.asOfTradeDate !== asOfTradeDate ||
    !isNonnegativeInteger(value.inventoryRevision) ||
    (value.status !== "KNOWN" && value.status !== "UNKNOWN") ||
    !isNullableBoardLot(value.totalQuantity) || !isNullableBoardLot(value.sellableQuantity) ||
    (value.totalQuantity !== null && value.sellableQuantity !== null && value.sellableQuantity > value.totalQuantity)) return false;
  return value.status === "KNOWN"
    ? value.totalQuantity !== null && value.confirmedAt !== null
    : value.totalQuantity === null && value.sellableQuantity === null;
}

function isInventoryClosure(
  value: unknown,
  command: PositionInventoryClosureCommand,
): value is PositionInventoryClosureView {
  return isRecord(value) && value.sourceType === command.sourceType && value.sourceId === command.sourceId &&
    value.tradeDate === command.tradeDate && value.appliedQuantity === command.quantity &&
    isBoardLotOrZero(value.beforeRemainingQuantity) && isBoardLotOrZero(value.afterRemainingQuantity) &&
    value.beforeRemainingQuantity - value.afterRemainingQuantity === command.quantity &&
    value.revision === command.expectedRevision + command.quantity / 100;
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

function isCalendarDate(value: unknown): value is string {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value);
}

function isUuid(value: unknown): value is string {
  return typeof value === "string" && uuidPattern.test(value);
}

function isNullableUuid(value: unknown): boolean {
  return value === undefined || value === null || isUuid(value);
}

function isNullableShanghaiDateTime(value: unknown): boolean {
  return value === undefined || value === null || isShanghaiDateTime(value);
}

function isNonnegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isPositiveInteger(value: unknown): value is number {
  return isNonnegativeInteger(value) && value > 0;
}

function isBoardLot(value: unknown): value is number {
  return isPositiveInteger(value) && value % 100 === 0;
}

function isBoardLotOrZero(value: unknown): value is number {
  return isNonnegativeInteger(value) && value % 100 === 0;
}

function isNullableBoardLot(value: unknown): value is number | null {
  return value === null || isBoardLotOrZero(value);
}

function isInventorySourceType(value: unknown): value is "LOT" | "OPENING_BALANCE" {
  return value === "LOT" || value === "OPENING_BALANCE";
}

function isIntegerBetween(value: unknown, minimum: number, maximum: number): value is number {
  return isNonnegativeInteger(value) && value >= minimum && value <= maximum;
}
