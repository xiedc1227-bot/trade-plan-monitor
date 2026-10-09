import type {
  PreparationCreateCommand, PreparationRecoveryCommand, PreparationRevisionCommand,
  PreparationSource, PreparationSourceCommand, PreparationView, PreparationReviewInput, PreparationFrozenView,
} from "./generated-runtime-status";
import { resolveApiFetch } from "./context";
import { isCalendarDate, isShanghaiDateTime, shanghaiDateTimeKey } from "./shanghaiTime";
import { ApiClientError, invalidResponse, requestJson } from "./transport";
import { validReviewCandidate, validPreparationReviewInput, validPreparationFrozenView } from "./preparationReview";

export type { PreparationSource, PreparationView } from "./generated-runtime-status";
export interface PreparationRequestOptions { readonly signal?: AbortSignal; }
export interface PreparationReceipt {
  readonly body: PreparationView;
  readonly status: 200 | 201 | 202;
  readonly retryAfterSeconds: number | null;
}
export interface PreparationFrozenReceipt {
  readonly body: PreparationFrozenView;
  readonly status: 200;
}
export interface PreparationApi {
  create(command: PreparationCreateCommand, key: string, options?: PreparationRequestOptions): Promise<PreparationReceipt>;
  get(id: string, options?: PreparationRequestOptions): Promise<PreparationReceipt>;
  edit(id: string, command: PreparationSourceCommand, key: string, options?: PreparationRequestOptions): Promise<PreparationReceipt>;
  extract(id: string, command: PreparationRevisionCommand, key: string, options?: PreparationRequestOptions): Promise<PreparationReceipt>;
  cancel(id: string, command: PreparationRevisionCommand, key: string, options?: PreparationRequestOptions): Promise<PreparationReceipt>;
  recover(id: string, command: PreparationRecoveryCommand, key: string, options?: PreparationRequestOptions): Promise<PreparationReceipt>;
  review(id: string, command: PreparationReviewInput, key: string, options?: PreparationRequestOptions): Promise<PreparationFrozenReceipt>;
}
const BASE = "/api/v1/backtest-preparations";
export const MAX_PREPARATION_SOURCE_CHARACTERS = 150_000;
const identifier = (value: unknown): value is string => typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value);
const hash = (value: unknown) => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
const integer = (value: unknown, minimum = 0): value is number => typeof value === "number" && Number.isSafeInteger(value) && value >= minimum;
const record = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const keys = (value: Record<string, unknown>, allowed: readonly string[]) => Object.keys(value).every(key => allowed.includes(key));

export function validPreparationSource(value: unknown): value is PreparationSource {
  if (!record(value) || !keys(value, ["source_id", "text", "authored_at", "available_at", "effective_trade_date"]) ||
      !identifier(value.source_id) || typeof value.text !== "string" || !value.text.trim() ||
      value.text.length > MAX_PREPARATION_SOURCE_CHARACTERS * 2 || Array.from(value.text).length > MAX_PREPARATION_SOURCE_CHARACTERS) return false;
  if ([value.authored_at, value.available_at].some(time => time != null && !isShanghaiDateTime(time)) ||
      value.effective_trade_date != null && !isCalendarDate(value.effective_trade_date)) return false;
  return value.authored_at == null || value.available_at == null ||
    shanghaiDateTimeKey(value.authored_at) <= shanghaiDateTimeKey(value.available_at);
}

function validAttempt(value: unknown): boolean {
  if (!record(value) || !keys(value, ["attempt_id", "error_code", "finished_at", "retryable", "source_hash", "source_revision", "started_at", "status"]) ||
      !identifier(value.attempt_id) || !hash(value.source_hash) || !integer(value.source_revision, 1) ||
      !isShanghaiDateTime(value.started_at) || typeof value.retryable !== "boolean" ||
      !["RUNNING", "CANCEL_REQUESTED", "SUCCEEDED", "FAILED", "CANCELLED"].includes(String(value.status))) return false;
  const active = value.status === "RUNNING" || value.status === "CANCEL_REQUESTED";
  return (active ? value.finished_at === null : isShanghaiDateTime(value.finished_at)) &&
    (value.status === "FAILED" ? typeof value.error_code === "string" && /^[A-Z][A-Z0-9_]{0,127}$/.test(value.error_code) : value.error_code === null) &&
    (!value.retryable || value.status === "FAILED");
}

function validCandidate(value: unknown): boolean {
  if (value === null) return true;
  if (!record(value) || !keys(value, ["kind", "candidateHash", "evidenceHash", "validation", "issues", "draft", "mapping", "openingAccount", "frozen"]) ||
      !hash(value.candidateHash) || !hash(value.evidenceHash) ||
      !["VALID", "INVALID", "UNRESOLVED"].includes(String(value.validation)) ||
      !Array.isArray(value.issues) || value.issues.length > 128 ||
      !value.issues.every(issue => typeof issue === "string" && Array.from(issue).length <= 512)) return false;
  if (value.kind === "EXTRACTION") return value.frozen == null && record(value.draft) &&
    value.draft.schema_version === 5 && value.draft.execution_mode === "CONDITION_PLAN" &&
    record(value.mapping) && value.mapping.mapping_version === "daily-mapping-v1" &&
    record(value.openingAccount) && Array.isArray(value.openingAccount.lots);
  if (value.kind === "FROZEN") return value.draft == null && value.mapping == null && value.openingAccount == null &&
    record(value.frozen) && value.frozen.schema_version === "prepared-loop-plan-v1" &&
    integer(value.frozen.source_revision, 1) && integer(value.frozen.extraction_candidate_revision, 1) &&
    record(value.frozen.version) && record(value.frozen.account);
  return value.kind === "UNAVAILABLE" && value.validation === "INVALID" &&
    [value.draft, value.mapping, value.openingAccount, value.frozen].every(payload => payload == null);
}

function validProgress(value: unknown): value is PreparationView {
  return record(value) && Object.keys(value).length === 12 &&
    keys(value, ["preparationId", "revision", "sourceRevision", "candidateRevision", "reviewRevision", "status", "source", "sourceEditPending", "attempts", "workPhase", "generation", "candidate"]) &&
    identifier(value.preparationId) && integer(value.revision, 1) && integer(value.sourceRevision, 1) &&
    integer(value.candidateRevision) && integer(value.reviewRevision) &&
    ["DRAFT", "EXTRACTING", "CANCEL_REQUESTED", "CANDIDATE", "REVIEWED", "FAILED", "CANCELLED"].includes(String(value.status)) &&
    validPreparationSource(value.source) && typeof value.sourceEditPending === "boolean" &&
    Array.isArray(value.attempts) && value.attempts.length <= 3 && value.attempts.every(validAttempt) &&
    (value.workPhase === null ? value.generation === null :
      ["READY", "CALLING", "UNKNOWN", "ENDED"].includes(String(value.workPhase)) && identifier(value.generation)) &&
    validCandidate(value.candidate) && (value.candidate === null || validReviewCandidate(value.candidate, value.source.text)) &&
    new TextEncoder().encode(JSON.stringify(value)).byteLength <= 2 * 1024 * 1024;
}

function invalidRequest(): ApiClientError {
  return new ApiClientError({ code: "VALIDATION_ERROR", status: 0, message: "原文或请求参数无效，请修正后重试" });
}

/** Only the preparation envelope is used for progress; semantic review stays server-owned. */
export function createPreparationApi(fetcher: typeof fetch = resolveApiFetch()): PreparationApi {
  async function request(id: string, suffix: string, method: "GET" | "POST" | "PUT", statuses: readonly number[], command?: object, key?: string, options?: PreparationRequestOptions): Promise<PreparationReceipt> {
    if (!identifier(id) || method !== "GET" && !identifier(key)) throw invalidRequest();
    const headers: Record<string, string> = { Accept: "application/json" };
    if (key !== undefined) { headers["Idempotency-Key"] = key; headers["Content-Type"] = "application/json"; }
    const init: RequestInit = { method, headers, cache: "no-store", credentials: "same-origin", redirect: "error" };
    if (options?.signal !== undefined) init.signal = options.signal;
    if (command !== undefined) init.body = JSON.stringify(command);
    const path = suffix === "CREATE" ? BASE : `${BASE}/${encodeURIComponent(id)}${suffix}`;
    const response = await requestJson(fetcher, path, init);
    const { body, status } = response;
    const retry = response.headers.get("Retry-After");
    if (!statuses.includes(status) || !validProgress(body) || body.preparationId !== id ||
        response.headers.get("Location") !== `${BASE}/${id}` || response.headers.get("Cache-Control") !== "no-store" ||
        (status === 202 ? retry !== "2" : retry !== null)) throw invalidResponse(status);
    // The allowed status set above makes this conversion closed and checked.
    return Object.freeze({ body, status: status as 200 | 201 | 202, retryAfterSeconds: status === 202 ? 2 : null });
  }
  function revisionCommand(command: PreparationRevisionCommand): void {
    if (!record(command) || !integer(command.expectedRevision, 1)) throw invalidRequest();
  }
  return Object.freeze<PreparationApi>({
    async create(command, key, options) {
      if (!record(command) || !record(command.input) || !identifier(command.input.preparation_id) ||
          !Array.isArray(command.input.sources) || command.input.sources.length !== 1 || !validPreparationSource(command.input.sources[0])) throw invalidRequest();
      return request(command.input.preparation_id, "CREATE", "POST", [201], command, key, options);
    },
    get: (id, options) => request(id, "", "GET", [200], undefined, undefined, options),
    async edit(id, command, key, options) {
      revisionCommand(command);
      if (!validPreparationSource(command.source)) throw invalidRequest();
      return request(id, "/source", "PUT", [200], command, key, options);
    },
    async extract(id, command, key, options) {
      revisionCommand(command);
      return request(id, "/extractions", "POST", [202], command, key, options);
    },
    async cancel(id, command, key, options) {
      revisionCommand(command);
      return request(id, "/cancellations", "POST", [200, 202], command, key, options);
    },
    async recover(id, command, key, options) {
      revisionCommand(command);
      if (command.confirmedEnded !== true || !identifier(command.generation)) throw invalidRequest();
      return request(id, "/recoveries", "POST", [200], command, key, options);
    },
    async review(id, command, key, options) {
      if (!identifier(id) || !identifier(key) || !validPreparationReviewInput(command)) throw invalidRequest();
      const init: RequestInit = { method: "POST", cache: "no-store", credentials: "same-origin", redirect: "error",
        headers: { Accept: "application/json", "Content-Type": "application/json", "Idempotency-Key": key }, body: JSON.stringify(command) };
      if (options?.signal !== undefined) init.signal = options.signal;
      const response = await requestJson(fetcher, `${BASE}/${encodeURIComponent(id)}/reviews`, init);
      const { body, status, headers } = response;
      if (status !== 200 || headers.get("Cache-Control") !== "no-store" || headers.get("Retry-After") !== null ||
          !validPreparationFrozenView(body) || !validPreparationSource(body.frozen.source) || body.preparationId !== id ||
          body.frozen.source_revision !== command.review.expected_source_revision ||
          body.frozen.extraction_candidate_revision !== command.review.expected_candidate_revision ||
          body.frozen.extraction_candidate_hash !== command.review.candidate_hash ||
          body.frozen.extraction_evidence_hash !== command.review.evidence_hash ||
          new TextEncoder().encode(JSON.stringify(body)).byteLength > 2 * 1024 * 1024) throw invalidResponse(status);
      return Object.freeze({ body, status: 200 as const });
    },
  });
}
