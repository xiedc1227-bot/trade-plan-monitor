import type {
  ActivePlanView,
  DraftReviewIssue,
  PlanActivationCommand,
  PlanDeactivationCommand,
  PlanDraftCommand,
  PlanImportCommand,
  PlanReviewConfirmationCommand,
  PlanReviewConfirmationView,
  PlanVersionPage,
  PlanVersionStatus,
  PlanVersionSummary,
  PlanVersionView,
  ValidationIssue,
} from "./generated";
import { isShanghaiDateTime } from "./shanghaiTime";
import { ApiClientError, invalidResponse, requestJson } from "./transport";

export { ApiClientError };

export interface PlanRequestOptions {
  readonly signal?: AbortSignal;
}

export interface PlanVersionListRequest {
  readonly canActivate?: boolean;
  readonly limit: number;
  readonly offset: number;
  readonly status?: PlanVersionStatus;
  readonly symbol?: string;
}

export interface PlanApi {
  activatePlan(
    command: PlanActivationCommand,
    idempotencyKey: string,
    options?: PlanRequestOptions,
  ): Promise<ActivePlanView>;
  deactivatePlan(
    command: PlanDeactivationCommand,
    idempotencyKey: string,
    options?: PlanRequestOptions,
  ): Promise<ActivePlanView>;
  getPlanActivationState(
    symbol: string,
    options?: PlanRequestOptions,
  ): Promise<ActivePlanView>;
  getPlanVersion(
    versionId: string,
    options?: PlanRequestOptions,
  ): Promise<PlanVersionView>;
  importPlan(
    command: PlanImportCommand,
    idempotencyKey: string,
    options?: PlanRequestOptions,
  ): Promise<PlanVersionView>;
  listPlanVersions(
    request: PlanVersionListRequest,
    options?: PlanRequestOptions,
  ): Promise<PlanVersionPage>;
  confirmPlanReview(
    command: PlanReviewConfirmationCommand,
    idempotencyKey: string,
    options?: PlanRequestOptions,
  ): Promise<PlanReviewConfirmationView>;
  savePlanDraft(
    command: PlanDraftCommand,
    idempotencyKey: string,
    options?: PlanRequestOptions,
  ): Promise<PlanVersionView>;
}

export function createPlanApi(
  fetchImplementation: typeof fetch = globalThis.fetch.bind(globalThis),
): PlanApi {
  return Object.freeze({
    async listPlanVersions(
      request: PlanVersionListRequest,
      options?: PlanRequestOptions,
    ) {
      const search = new URLSearchParams();
      search.set("offset", String(request.offset));
      search.set("limit", String(request.limit));
      if (request.symbol !== undefined) search.set("symbol", request.symbol);
      if (request.status !== undefined) search.set("status", request.status);
      if (request.canActivate !== undefined) {
        search.set("canActivate", String(request.canActivate));
      }
      const { body, status } = await requestJson(
        fetchImplementation,
        `/api/v1/plan-versions?${search.toString()}`,
        readRequest(options),
      );
      if (!isPlanVersionPage(body, request)) throw invalidResponse(status);
      return body;
    },

    async getPlanVersion(versionId: string, options?: PlanRequestOptions) {
      if (!isUuid(versionId)) throw invalidResponse(0);
      const { body, status } = await requestJson(
        fetchImplementation,
        `/api/v1/plan-versions/${encodeURIComponent(versionId)}`,
        readRequest(options),
      );
      if (!isPlanVersion(body) || body.id !== versionId) throw invalidResponse(status);
      return body;
    },

    async confirmPlanReview(
      command: PlanReviewConfirmationCommand,
      idempotencyKey: string,
      options?: PlanRequestOptions,
    ) {
      const { body, status } = await requestJson(
        fetchImplementation,
        "/api/v1/plan-review-confirmations",
        mutationRequest(command, idempotencyKey, options),
      );
      if (!isPlanReviewConfirmation(body, command)) throw invalidResponse(status);
      return body;
    },

    async getPlanActivationState(symbol: string, options?: PlanRequestOptions) {
      if (!isShareSymbol(symbol)) throw invalidResponse(0);
      const { body, status } = await requestJson(
        fetchImplementation,
        `/api/v1/plan-activation-states/${encodeURIComponent(symbol)}`,
        readRequest(options),
      );
      if (!isActivePlan(body) || body.symbol !== symbol) throw invalidResponse(status);
      return body;
    },

    async savePlanDraft(
      command: PlanDraftCommand,
      idempotencyKey: string,
      options?: PlanRequestOptions,
    ) {
      const { body, status } = await requestJson(
        fetchImplementation,
        "/api/v1/plan-drafts",
        mutationRequest(command, idempotencyKey, options),
      );
      if (
        !isPlanVersion(body) ||
        body.status !== "DRAFT" ||
        body.sourceText !== command.sourceText ||
        (command.basePlanVersionId !== undefined &&
          body.id === command.basePlanVersionId) ||
        !sameReviewIssues(body.reviewIssues ?? [], command.reviewIssues ?? [])
      ) {
        throw invalidResponse(status);
      }
      return body;
    },

    async importPlan(
      command: PlanImportCommand,
      idempotencyKey: string,
      options?: PlanRequestOptions,
    ) {
      const { body, status } = await requestJson(
        fetchImplementation,
        "/api/v1/plan-imports",
        mutationRequest(command, idempotencyKey, options),
      );
      if (
        !isPlanVersion(body) ||
        body.status !== "DRAFT" ||
        body.symbol !== command.symbol ||
        body.sourceText !== command.document ||
        (body.reviewIssues?.length ?? 0) !== 0
      ) {
        throw invalidResponse(status);
      }
      return body;
    },

    async activatePlan(
      command: PlanActivationCommand,
      idempotencyKey: string,
      options?: PlanRequestOptions,
    ) {
      const { body, status } = await requestJson(
        fetchImplementation,
        "/api/v1/plan-activations",
        mutationRequest(command, idempotencyKey, options),
      );
      if (
        !isActivePlan(body) ||
        !body.active ||
        body.planVersionId !== command.planVersionId ||
        body.revision !== command.expectedRevision + 1
      ) {
        throw invalidResponse(status);
      }
      return body;
    },

    async deactivatePlan(
      command: PlanDeactivationCommand,
      idempotencyKey: string,
      options?: PlanRequestOptions,
    ) {
      const { body, status } = await requestJson(
        fetchImplementation,
        "/api/v1/plan-deactivations",
        mutationRequest(command, idempotencyKey, options),
      );
      if (
        !isActivePlan(body) ||
        body.active ||
        body.symbol !== command.symbol ||
        body.revision !== command.expectedRevision + 1
      ) {
        throw invalidResponse(status);
      }
      return body;
    },
  });
}

function readRequest(options?: PlanRequestOptions): RequestInit {
  const request: RequestInit = {
    headers: { Accept: "application/json" },
    method: "GET",
  };
  if (options?.signal !== undefined) request.signal = options.signal;
  return request;
}

function mutationRequest(
  command: object,
  idempotencyKey: string,
  options?: PlanRequestOptions,
): RequestInit {
  const request: RequestInit = {
    body: JSON.stringify(command),
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    },
    method: "POST",
  };
  if (options?.signal !== undefined) request.signal = options.signal;
  return request;
}

function isPlanVersionPage(
  value: unknown,
  request: PlanVersionListRequest,
): value is PlanVersionPage {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, ["items", "limit", "offset", "total"]) ||
    !hasRequiredKeys(value, ["limit", "offset", "total"]) ||
    !isIntegerWithin(value.limit, 1, 100) ||
    !isIntegerWithin(value.offset, 0, 10_000) ||
    !isIntegerWithin(value.total, 0, 10_000) ||
    value.limit !== request.limit ||
    value.offset !== request.offset ||
    (value.items !== undefined &&
      (!Array.isArray(value.items) ||
        value.items.length > request.limit ||
        !value.items.every(isPlanVersionSummary)))
  ) {
    return false;
  }
  const items = (value.items ?? []) as PlanVersionSummary[];
  return (
    (items.length === 0 || request.offset + items.length <= value.total) &&
    new Set(items.map((item) => item.id)).size === items.length &&
    items.every(
      (item) =>
        (request.symbol === undefined || item.symbol === request.symbol) &&
        (request.status === undefined || item.status === request.status) &&
        (request.canActivate === undefined || item.canActivate === request.canActivate),
    )
  );
}

function isPlanVersionSummary(value: unknown): value is PlanVersionSummary {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      "canActivate",
      "createdAt",
      "id",
      "planHash",
      "planId",
      "revision",
      "status",
      "symbol",
      "version",
    ]) &&
    typeof value.canActivate === "boolean" &&
    isShanghaiDateTime(value.createdAt) &&
    isUuid(value.id) &&
    isSha256(value.planHash) &&
    isBoundedText(value.planId, 128) &&
    isNonnegativeInteger(value.revision) &&
    (value.status === "DRAFT" ||
      value.status === "ACTIVE" ||
      value.status === "SUPERSEDED") &&
    (value.status !== "ACTIVE" || value.canActivate) &&
    isShareSymbol(value.symbol) &&
    isPositiveInteger(value.version)
  );
}

function isPlanVersion(value: unknown): value is PlanVersionView {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, [
      "canActivate",
      "contentHash",
      "createdAt",
      "executionReadiness",
      "id",
      "mapping",
      "planHash",
      "planId",
      "planJson",
      "requiredReviewIssues",
      "resolvedIssueIds",
      "reviewEvidenceHash",
      "reviewId",
      "reviewIssues",
      "reviewRevision",
      "revision",
      "sourceText",
      "sourceHash",
      "status",
      "symbol",
      "unresolvedReviewIssues",
      "validationIssues",
      "version",
    ]) ||
    !hasRequiredKeys(value, [
      "canActivate",
      "createdAt",
      "id",
      "planHash",
      "planId",
      "planJson",
      "revision",
      "sourceText",
      "status",
      "symbol",
      "version",
    ]) ||
    typeof value.canActivate !== "boolean" ||
    !isShanghaiDateTime(value.createdAt) ||
    !isUuid(value.id) ||
    !isSha256(value.planHash) ||
    !isBoundedText(value.planId, 128) ||
    !isBoundedText(value.planJson, 262_144, 2) ||
    (value.reviewIssues !== undefined &&
      (!Array.isArray(value.reviewIssues) ||
        value.reviewIssues.length > 512 ||
        !value.reviewIssues.every(isReviewIssue))) ||
    !isOptionalHash(value.contentHash) ||
    !isOptionalHash(value.sourceHash) ||
    !isOptionalHash(value.reviewEvidenceHash) ||
    !isOptionalUuid(value.reviewId) ||
    !isOptionalNonnegativeInteger(value.reviewRevision) ||
    !(value.executionReadiness === undefined ||
      value.executionReadiness === null ||
      value.executionReadiness === "NOT_EVALUATED") ||
    !(value.mapping === undefined || value.mapping === null || isRecord(value.mapping)) ||
    !(value.requiredReviewIssues === undefined ||
      (Array.isArray(value.requiredReviewIssues) && value.requiredReviewIssues.every(isReviewIssueRecord))) ||
    !(value.resolvedIssueIds === undefined ||
      (Array.isArray(value.resolvedIssueIds) && value.resolvedIssueIds.every((item) => isBoundedText(item, 128)))) ||
    !(value.unresolvedReviewIssues === undefined ||
      (Array.isArray(value.unresolvedReviewIssues) && value.unresolvedReviewIssues.every(isReviewIssueRecord))) ||
    !isNonnegativeInteger(value.revision) ||
    !isBoundedText(value.sourceText, 262_144) ||
    (value.status !== "DRAFT" && value.status !== "ACTIVE" && value.status !== "SUPERSEDED") ||
    !isShareSymbol(value.symbol) ||
    (value.validationIssues !== undefined &&
      (!Array.isArray(value.validationIssues) ||
        value.validationIssues.length > 512 ||
        !value.validationIssues.every(isValidationIssue))) ||
    !isPositiveInteger(value.version)
  ) {
    return false;
  }
  const reviewIssues = (value.reviewIssues ?? []) as DraftReviewIssue[];
  const validationIssues = (value.validationIssues ?? []) as ValidationIssue[];
  const canActivate =
    !reviewIssues.some((issue) => issue.resolved !== true) &&
    !validationIssues.some((issue) => issue.activationBlocking);
  return value.canActivate === canActivate && (value.status !== "ACTIVE" || canActivate);
}

function isPlanReviewConfirmation(
  value: unknown,
  command: PlanReviewConfirmationCommand,
): value is PlanReviewConfirmationView {
  return isRecord(value) &&
    hasOnlyKeys(value, [
      "canActivate",
      "confirmedAt",
      "contentHash",
      "planVersionId",
      "reviewEvidenceHash",
      "reviewId",
      "revision",
      "sourceHash",
      "unresolvedIssues",
    ]) &&
    hasRequiredKeys(value, [
      "canActivate",
      "confirmedAt",
      "contentHash",
      "planVersionId",
      "reviewEvidenceHash",
      "reviewId",
      "revision",
      "sourceHash",
    ]) &&
    typeof value.canActivate === "boolean" &&
    (value.confirmedAt === null || isShanghaiDateTime(value.confirmedAt)) &&
    value.contentHash === command.contentHash &&
    value.planVersionId === command.planVersionId &&
    value.reviewEvidenceHash === command.reviewEvidenceHash &&
    value.sourceHash === command.sourceHash &&
    (value.reviewId === null || isUuid(value.reviewId)) &&
    isNonnegativeInteger(value.revision) &&
    (value.unresolvedIssues === undefined ||
      (Array.isArray(value.unresolvedIssues) && value.unresolvedIssues.every(isReviewIssueRecord)));
}

function isReviewIssueRecord(value: unknown): boolean {
  return isRecord(value) &&
    hasOnlyKeys(value, ["allowedResolutions", "bindingPath", "clauseId", "code", "issueId", "path", "reason"]) &&
    hasRequiredKeys(value, ["allowedResolutions", "code", "issueId", "path", "reason"]) &&
    Array.isArray(value.allowedResolutions) &&
    value.allowedResolutions.every((item) =>
      item === "CONFIRM_MAPPING" || item === "CONFIRM_POLICY" ||
      item === "CONFIRM_SOURCE_TREATMENT" || item === "REPLACED_BY_REVIEWED_CONTENT") &&
    isBoundedText(value.code, 100) && isBoundedText(value.issueId, 128) &&
    isPlanPath(value.path) && isBoundedText(value.reason, 512) &&
    (value.bindingPath === undefined || value.bindingPath === null || isPlanPath(value.bindingPath)) &&
    (value.clauseId === undefined || value.clauseId === null || isBoundedText(value.clauseId, 128));
}

function isOptionalHash(value: unknown): boolean {
  return value === undefined || value === null || isSha256(value);
}

function isOptionalUuid(value: unknown): boolean {
  return value === undefined || value === null || isUuid(value);
}

function isOptionalNonnegativeInteger(value: unknown): boolean {
  return value === undefined || value === null || isNonnegativeInteger(value);
}

function isReviewIssue(value: unknown): value is DraftReviewIssue {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["kind", "material", "path", "resolved"]) &&
    hasRequiredKeys(value, ["kind", "material", "path"]) &&
    (value.kind === "ASSUMPTION" ||
      value.kind === "WARNING" ||
      value.kind === "UNMAPPED_TEXT" ||
      value.kind === "MISSING_EVIDENCE") &&
    typeof value.material === "boolean" &&
    isPlanPath(value.path) &&
    (value.resolved === undefined || typeof value.resolved === "boolean")
  );
}

function isValidationIssue(value: unknown): value is ValidationIssue {
  return (
    isRecord(value) &&
    hasExactKeys(value, ["activationBlocking", "code", "message", "path", "severity"]) &&
    typeof value.activationBlocking === "boolean" &&
    isValidationCode(value.code) &&
    isBoundedText(value.message, 512) &&
    isPlanPath(value.path) &&
    (value.severity === "ERROR" || value.severity === "WARNING")
  );
}

function isActivePlan(value: unknown): value is ActivePlanView {
  return (
    isRecord(value) &&
    hasExactKeys(value, ["active", "changedAt", "planVersionId", "revision", "symbol"]) &&
    typeof value.active === "boolean" &&
    isShanghaiDateTime(value.changedAt) &&
    (value.planVersionId === null || isUuid(value.planVersionId)) &&
    value.active === (value.planVersionId !== null) &&
    isNonnegativeInteger(value.revision) &&
    isShareSymbol(value.symbol)
  );
}

function sameReviewIssues(
  left: readonly DraftReviewIssue[],
  right: readonly DraftReviewIssue[],
): boolean {
  return JSON.stringify(left.map(normalizeReviewIssue)) ===
    JSON.stringify(right.map(normalizeReviewIssue));
}

function normalizeReviewIssue(issue: DraftReviewIssue): Required<DraftReviewIssue> {
  return { ...issue, resolved: issue.resolved ?? false };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key));
}

function hasOnlyKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const allowed = new Set(keys);
  return Object.keys(value).every((key) => allowed.has(key));
}

function hasRequiredKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return keys.every((key) => Object.hasOwn(value, key));
}

function isUuid(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(
      value,
    )
  );
}

function isShareSymbol(value: unknown): value is string {
  return typeof value === "string" && /^\d{6}\.(?:BJ|SH|SZ)$/.test(value);
}

function isSha256(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
}

function isValidationCode(value: unknown): value is string {
  return typeof value === "string" && /^[A-Z][A-Z0-9_]{0,99}$/.test(value);
}

function isPlanPath(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length <= 256 &&
    /^[A-Za-z0-9_.\[\]-]+$/.test(value)
  );
}

function isBoundedText(value: unknown, maximum: number, minimum = 1): value is string {
  return typeof value === "string" && value.length >= minimum && value.length <= maximum;
}

function isNonnegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

function isIntegerWithin(value: unknown, minimum: number, maximum: number): value is number {
  return (
    typeof value === "number" &&
    Number.isSafeInteger(value) &&
    value >= minimum &&
    value <= maximum
  );
}
