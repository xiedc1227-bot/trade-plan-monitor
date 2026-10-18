import type {
  CollectionPreparationView, CollectionItemView, CollectionItemSummary, CollectionItemsPage, CollectionPreparationFrozenView,
  CollectionSourceCommand, CollectionRevisionCommand, CollectionExtractionCommand, CollectionRecoveryCommand, CollectionReviewInput, CollectionItemCorrectionInput,
  PreparationCreateCommand, PreparationRecoveryCommand, PreparationRevisionCommand,
  PreparationSource, PreparationSourceCommand, PreparationView, PreparationReviewInput, PreparationFrozenView,
  SingleSourcePreparationInput,
} from "./generated-runtime-status";
import { resolveApiFetch } from "./context";
import { isCalendarDate, isShanghaiDateTime, shanghaiDateTimeKey } from "./shanghaiTime";
import { ApiClientError, invalidResponse, requestJson } from "./transport";
import { account, validReviewCandidate, validPreparationReviewInput, validPreparationFrozenView, validCollectionFrozen, validCollectionCandidate, validCollectionReviewInput } from "./preparationReview";

export type { PreparationSource, PreparationView } from "./generated-runtime-status";
export type PreparationProgress = PreparationView | CollectionPreparationView;
export interface CollectionItemsQuery { readonly expectedRevision: number; readonly offset?: number; readonly limit?: number; }
export interface CollectionFrozenReceipt { readonly body: CollectionPreparationFrozenView; readonly status: 200; }
export interface PreparationRequestOptions { readonly signal?: AbortSignal; }
export interface PreparationReceipt {
  readonly body: PreparationProgress;
  readonly status: 200 | 201 | 202;
  readonly retryAfterSeconds: number | null;
}
export interface PreparationFrozenReceipt {
  readonly body: PreparationFrozenView;
  readonly status: 200;
}
export interface PreparationApi {
  createSingle?(command: SingleSourcePreparationInput, key: string, options?: PreparationRequestOptions): Promise<PreparationReceipt>;
  create(command: PreparationCreateCommand, key: string, options?: PreparationRequestOptions): Promise<PreparationReceipt>;
  get(id: string, options?: PreparationRequestOptions): Promise<PreparationReceipt>;
  edit(id: string, command: PreparationSourceCommand | CollectionSourceCommand, key: string, options?: PreparationRequestOptions): Promise<PreparationReceipt>;
  extract(id: string, command: PreparationRevisionCommand | CollectionExtractionCommand, key: string, options?: PreparationRequestOptions): Promise<PreparationReceipt>;
  cancel(id: string, command: PreparationRevisionCommand | CollectionRevisionCommand, key: string, options?: PreparationRequestOptions): Promise<PreparationReceipt>;
  recover(id: string, command: PreparationRecoveryCommand | CollectionRecoveryCommand, key: string, options?: PreparationRequestOptions): Promise<PreparationReceipt>;
  items?(id: string, query: CollectionItemsQuery, options?: PreparationRequestOptions): Promise<CollectionItemsPage>;
  reviewCollection?(id: string, command: CollectionReviewInput, key: string, options?: PreparationRequestOptions): Promise<CollectionFrozenReceipt>;
  correct?(id: string, command: CollectionItemCorrectionInput, key: string, options?: PreparationRequestOptions): Promise<PreparationReceipt>;
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

const size = (value: unknown, maximum: number) => new TextEncoder().encode(JSON.stringify(value)).byteLength <= maximum;
export function isCollection(value: PreparationProgress): value is CollectionPreparationView { return "schemaVersion" in value && value.schemaVersion === "backtest-preparation-v2"; }
export function validPreparationSources(sources: readonly PreparationSource[]): boolean {
  return sources.length > 0 && sources.length <= 256 && sources.every(validPreparationSource) &&
    new Set(sources.map(source => source.source_id)).size === sources.length &&
    sources.reduce((sum, source) => sum + new TextEncoder().encode(source.text).byteLength, 0) <= 8 * 1024 * 1024;
}
function validSummary(value: unknown): value is CollectionItemSummary & Record<string, unknown> {
  return record(value) && identifier(value.sourceId) && integer(value.sourceRevision, 1) && integer(value.candidateRevision) &&
    [value.baseHash, value.candidateHash, value.evidenceHash].every(item => item === null || hash(item)) &&
    (value.effectiveTradeDate === null || isCalendarDate(value.effectiveTradeDate)) && integer(value.attemptCount) && value.attemptCount <= 3 &&
    ["WAITING", "DRAFT", "EXTRACTING", "CANCEL_REQUESTED", "CANDIDATE", "FAILED", "CANCELLED"].includes(String(value.status)) &&
    (value.validation === null || ["VALID", "INVALID", "UNRESOLVED"].includes(String(value.validation)));
}
export function validCollectionProgress(value: unknown): value is CollectionPreparationView {
  return record(value) && keys(value, ["workflow", "editableSourceId", "baseAccount", "schemaVersion", "preparationId", "revision", "reviewRevision", "status", "itemCount", "items", "workPhase", "generation", "currentSourceId", "frozen"]) &&
    (value.workflow === undefined || ["LEGACY", "SINGLE", "COMPOSITION"].includes(String(value.workflow))) &&
    (value.editableSourceId == null || identifier(value.editableSourceId)) &&
    (value.baseAccount == null || account(value.baseAccount)) &&
    value.schemaVersion === "backtest-preparation-v2" && identifier(value.preparationId) && integer(value.revision, 1) && integer(value.reviewRevision) &&
    ["DRAFT", "EXTRACTING", "CANCEL_REQUESTED", "CANDIDATE", "REVIEWED", "FAILED", "CANCELLED"].includes(String(value.status)) &&
    integer(value.itemCount, 1) && value.itemCount <= 256 && Array.isArray(value.items) && value.items.length === value.itemCount && value.items.every(validSummary) &&
    new Set(value.items.map(item => item.sourceId)).size === value.itemCount &&
    (value.workPhase === null ? value.generation === null : ["READY", "CALLING", "UNKNOWN", "ENDED"].includes(String(value.workPhase)) && identifier(value.generation)) &&
    (value.currentSourceId === null || value.items.some(item => item.sourceId === value.currentSourceId)) &&
    (value.status === "REVIEWED" ? validCollectionFrozen(value.frozen) && value.frozen.preparationId === value.preparationId && value.frozen.revision === value.revision : value.frozen === null) && size(value, 2 * 1024 * 1024);
}
function validItem(value: unknown): value is CollectionItemView {
  if (!record(value) || !validSummary(value) || !keys(value, ["sourceId", "sourceRevision", "candidateRevision", "baseHash", "candidateHash", "evidenceHash", "validation", "status", "attemptCount", "effectiveTradeDate", "source", "attempts", "candidate"]) ||
      !validPreparationSource(value.source) || value.source.source_id !== value.sourceId || (value.source.effective_trade_date ?? null) !== value.effectiveTradeDate ||
      !Array.isArray(value.attempts) || value.attempts.length !== value.attemptCount || !value.attempts.every(attempt => {
        if (!record(attempt) || !(attempt.base_hash === null || hash(attempt.base_hash))) return false;
        const { base_hash: _base, ...legacy } = attempt; return validAttempt(legacy);
      }) || !validCollectionCandidate(value.candidate, value.source.text)) return false;
  if (value.candidate === null) return value.candidateHash === null && value.evidenceHash === null && value.validation === null;
  if (!record(value.candidate) || value.candidate.candidateHash !== value.candidateHash || value.candidate.evidenceHash !== value.evidenceHash || value.candidate.validation !== value.validation) return false;
  const review = value.candidate.review;
  const available = value.source.available_at ?? (value.source.effective_trade_date
    ? `${value.source.effective_trade_date}T09:30:00+08:00` : null);
  return review == null || record(review) && review.source_id === value.sourceId &&
    (review.available_at === null && available === null ||
      isShanghaiDateTime(review.available_at) && isShanghaiDateTime(available) &&
      shanghaiDateTimeKey(review.available_at) === shanghaiDateTimeKey(available));
}
function validProgress(value: unknown): value is PreparationProgress {
  if (validCollectionProgress(value)) return true;
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
    if (command !== undefined) { if (!size(command, 4 * 1024 * 1024)) throw invalidRequest(); init.body = JSON.stringify(command); }
    const path = suffix === "SINGLE" ? "/api/v1/backtest-plan-library/preparations" : suffix === "CREATE" ? BASE : `${BASE}/${encodeURIComponent(id)}${suffix}`;
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
    async createSingle(command, key, options) {
      if (!identifier(command.preparation_id) || !validPreparationSource(command.source) ||
          command.reviewed_base != null && (!identifier(command.reviewed_base.preparation_id) || !hash(command.reviewed_base.manifest_hash))) throw invalidRequest();
      return request(command.preparation_id, "SINGLE", "POST", [201], command, key, options);
    },
    async create(command, key, options) {
      if (!record(command) || !record(command.input) || !identifier(command.input.preparation_id) ||
          !Array.isArray(command.input.sources) || !validPreparationSources(command.input.sources) ||
          (!("schema_version" in command.input && command.input.schema_version === "backtest-preparation-v2") && command.input.sources.length !== 1)) throw invalidRequest();
      return request(command.input.preparation_id, "CREATE", "POST", [201], command, key, options);
    },
    get: (id, options) => request(id, "", "GET", [200], undefined, undefined, options),
    async edit(id, command, key, options) {
      revisionCommand(command);
      if ("schemaVersion" in command && command.schemaVersion === "backtest-preparation-v2") {
        if (command.source == null && command.sourceOrder == null || command.source != null && !validPreparationSource(command.source) ||
            command.sourceOrder != null && (command.sourceOrder.length < 1 || command.sourceOrder.length > 256 || !command.sourceOrder.every(identifier) || new Set(command.sourceOrder).size !== command.sourceOrder.length)) throw invalidRequest();
      } else if (!validPreparationSource(command.source)) throw invalidRequest();
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
    async items(id, query, options) {
      const offset = query.offset ?? 0, limit = query.limit ?? 20;
      if (!identifier(id) || !integer(query.expectedRevision, 1) || !integer(offset) || offset > 255 || !integer(limit, 1) || limit > 100) throw invalidRequest();
      const init: RequestInit = { method: "GET", headers: { Accept: "application/json" }, cache: "no-store", credentials: "same-origin", redirect: "error" };
      if (options?.signal !== undefined) init.signal = options.signal;
      const result = await requestJson(fetcher, `${BASE}/${encodeURIComponent(id)}/items?expectedRevision=${query.expectedRevision}&offset=${offset}&limit=${limit}`, init);
      const body = result.body;
      if (result.status !== 200 || result.headers.get("Cache-Control") !== "no-store" || !record(body) ||
          !keys(body, ["preparationId", "revision", "offset", "limit", "total", "nextOffset", "items"]) || body.preparationId !== id || body.revision !== query.expectedRevision ||
          body.offset !== offset || body.limit !== limit || !integer(body.total, 1) || body.total > 256 || !Array.isArray(body.items) || body.items.length > limit ||
          !body.items.every(validItem) || new Set(body.items.map(item => item.sourceId)).size !== body.items.length || offset > body.total ||
          (offset < body.total && body.items.length === 0) || offset + body.items.length > body.total ||
          (offset + body.items.length < body.total ? body.nextOffset !== offset + body.items.length : body.nextOffset !== null) || !size(body, 2 * 1024 * 1024)) throw invalidResponse(result.status);
      return body as CollectionItemsPage;
    },
    async correct(id, command, key, options) {
      if (!validCollectionReviewInput(command) || command.kind !== "ITEM_CORRECTION") throw invalidRequest();
      return request(id, "/reviews", "POST", [200], command, key, options);
    },
    async reviewCollection(id, command, key, options) {
      if (!identifier(id) || !identifier(key) || !validCollectionReviewInput(command) || command.kind !== "CHAIN_REVIEW" || !size(command, 4 * 1024 * 1024)) throw invalidRequest();
      const init: RequestInit = { method: "POST", cache: "no-store", credentials: "same-origin", redirect: "error",
        headers: { Accept: "application/json", "Content-Type": "application/json", "Idempotency-Key": key }, body: JSON.stringify(command) };
      if (options?.signal !== undefined) init.signal = options.signal;
      const { body, status, headers } = await requestJson(fetcher, `${BASE}/${encodeURIComponent(id)}/reviews`, init);
      if (status !== 200 || headers.get("Cache-Control") !== "no-store" || headers.get("Retry-After") !== null || !validCollectionFrozen(body) ||
          body.preparationId !== id || body.revision !== command.review.expected_revision + 1 || body.versions.length !== command.review.items.length ||
          body.versions.some((version, index) => { const item = command.review.items[index]!; return version.sourceId !== item.source_id || version.sourceRevision !== item.source_revision || version.candidateRevision !== item.candidate_revision; }) || !size(body, 2 * 1024 * 1024)) throw invalidResponse(status);
      return Object.freeze({ body, status: 200 as const });
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
