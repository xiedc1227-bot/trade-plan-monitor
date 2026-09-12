import type {
  ManualEventRiskConfirmationCommand,
  ManualEventRiskView,
} from "./generated";
import { isShanghaiDateTime } from "./shanghaiTime";
import { invalidResponse, requestJson } from "./transport";

const idempotencyKeyPattern = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const symbolPattern = /^\d{6}\.(?:BJ|SH|SZ)$/;
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export interface ManualEventRiskApi {
  confirm(command: ManualEventRiskConfirmationCommand, idempotencyKey: string): Promise<ManualEventRiskView>;
  get(symbol: string): Promise<ManualEventRiskView>;
}

export function createManualEventRiskApi(
  fetchImplementation: typeof fetch = globalThis.fetch.bind(globalThis),
): ManualEventRiskApi {
  return Object.freeze({
    async get(symbol: string) {
      if (!symbolPattern.test(symbol)) throw new RangeError("manual risk symbol is invalid");
      const { body, status } = await requestJson(
        fetchImplementation,
        `/api/v1/manual-event-risk?${new URLSearchParams({ symbol }).toString()}`,
        { headers: { Accept: "application/json" }, method: "GET" },
      );
      if (!isManualEventRiskView(body, symbol)) throw invalidResponse(status);
      return body;
    },

    async confirm(command: ManualEventRiskConfirmationCommand, idempotencyKey: string) {
      if (!isConfirmationCommand(command) || !idempotencyKeyPattern.test(idempotencyKey)) {
        throw new RangeError("manual risk confirmation is invalid");
      }
      const { body, status } = await requestJson(
        fetchImplementation,
        "/api/v1/manual-event-risk-confirmations",
        {
          body: JSON.stringify(command),
          headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
            "Idempotency-Key": idempotencyKey,
          },
          method: "POST",
        },
      );
      if (
        !isManualEventRiskView(body, command.symbol) ||
        body.status !== command.status ||
        body.expiresOn !== command.expiresOn ||
        body.revision !== command.expectedRevision + 1
      ) {
        throw invalidResponse(status);
      }
      return body;
    },
  });
}

function isConfirmationCommand(value: ManualEventRiskConfirmationCommand): boolean {
  return (
    symbolPattern.test(value.symbol) &&
    (value.status === "CLEAR" || value.status === "RISK_PRESENT") &&
    isCalendarDate(value.expiresOn) &&
    Number.isSafeInteger(value.expectedRevision) &&
    value.expectedRevision >= 0
  );
}

function isManualEventRiskView(value: unknown, symbol: string): value is ManualEventRiskView {
  if (!isRecord(value) || !hasExactKeys(value, [
    "confirmedAt", "expiresOn", "planVersionId", "reason", "revision", "status", "symbol",
  ])) return false;
  if (
    value.symbol !== symbol ||
    !isNullableUuid(value.planVersionId) ||
    !isNullableCalendarDate(value.expiresOn) ||
    !isNullableShanghaiDateTime(value.confirmedAt) ||
    !isNonnegativeInteger(value.revision) ||
    !(value.status === "UNKNOWN" || value.status === "CLEAR" || value.status === "RISK_PRESENT") ||
    !(value.reason === null || value.reason === "NO_ACTIVE_PLAN" || value.reason === "MISSING_CONFIRMATION" || value.reason === "PLAN_CHANGED" || value.reason === "EXPIRED")
  ) return false;
  const unknown = value.status === "UNKNOWN";
  if (unknown !== (value.reason !== null)) return false;
  if (value.planVersionId === null) {
    return value.status === "UNKNOWN" && value.reason === "NO_ACTIVE_PLAN" &&
      value.expiresOn === null && value.confirmedAt === null && value.revision === 0;
  }
  return (value.expiresOn === null) === (value.confirmedAt === null);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key));
}

function isCalendarDate(value: unknown): value is string {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value);
}

function isNullableCalendarDate(value: unknown): boolean {
  return value === null || isCalendarDate(value);
}

function isNullableShanghaiDateTime(value: unknown): boolean {
  return value === null || (typeof value === "string" && isShanghaiDateTime(value));
}

function isNullableUuid(value: unknown): boolean {
  return value === null || (typeof value === "string" && uuidPattern.test(value));
}

function isNonnegativeInteger(value: unknown): boolean {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}
