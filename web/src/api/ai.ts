import type {
  ConfiguredAIRuntimeView,
  ExtractionIssue,
  FieldEvidence,
  OperationReceipt,
  PlanExtractionCommand,
  PlanExtractionView,
  UnmappedText,
  ValidationIssue,
} from "./generated";
import { isShanghaiDateTime } from "./shanghaiTime";
import { ApiClientError, invalidResponse, requestJson } from "./transport";

export interface AIRequestOptions {
  readonly signal?: AbortSignal;
}

export interface AIPlanApi {
  getExtraction(
    operationId: string,
    options?: AIRequestOptions,
  ): Promise<PlanExtractionView>;
  getRuntime(options?: AIRequestOptions): Promise<ConfiguredAIRuntimeView>;
  submitExtraction(
    command: PlanExtractionCommand,
    idempotencyKey: string,
    options?: AIRequestOptions,
  ): Promise<OperationReceipt>;
}

const extractionStatuses = new Set([
  "QUEUED",
  "RUNNING",
  "SUCCEEDED",
  "INVALID_OUTPUT",
  "PROVIDER_ERROR",
  "CANCELLED",
]);
const validationSeverities = new Set(["ERROR", "WARNING"]);

export function createAIPlanApi(
  fetchImplementation: typeof fetch = globalThis.fetch.bind(globalThis),
): AIPlanApi {
  return Object.freeze({
    async getRuntime(options?: AIRequestOptions) {
      const { body, status } = await requestJson(
        fetchImplementation,
        "/api/v1/ai-runtime",
        requestOptions("GET", options),
      );
      if (!isConfiguredRuntime(body)) {
        throw invalidResponse(status);
      }
      return body;
    },

    async submitExtraction(
      command: PlanExtractionCommand,
      idempotencyKey: string,
      options?: AIRequestOptions,
    ) {
      const { body, status } = await requestJson(
        fetchImplementation,
        "/api/v1/plan-extractions",
        requestOptions("POST", options, {
          body: JSON.stringify(command),
          idempotencyKey,
        }),
      );
      if (status !== 202 || !isOperationReceipt(body)) {
        throw invalidResponse(status);
      }
      return body;
    },

    async getExtraction(operationId: string, options?: AIRequestOptions) {
      if (!isUuid(operationId)) {
        throw invalidResponse(0);
      }
      const { body, status } = await requestJson(
        fetchImplementation,
        `/api/v1/plan-extractions/${encodeURIComponent(operationId)}`,
        requestOptions("GET", options),
      );
      if (!isPlanExtraction(body) || body.id !== operationId) {
        throw invalidResponse(status);
      }
      return body;
    },
  });
}

function requestOptions(
  method: "GET" | "POST",
  options?: AIRequestOptions,
  mutation?: { body: string; idempotencyKey: string },
): RequestInit {
  const headers: Record<string, string> = { Accept: "application/json" };
  const request: RequestInit = { headers, method };
  if (mutation !== undefined) {
    headers["Content-Type"] = "application/json";
    headers["Idempotency-Key"] = mutation.idempotencyKey;
    request.body = mutation.body;
  }
  if (options?.signal !== undefined) {
    request.signal = options.signal;
  }
  return request;
}

function isConfiguredRuntime(value: unknown): value is ConfiguredAIRuntimeView {
  if (
    !isRecord(value) ||
    !hasKeys(value, [
      "baseUrl",
      "configured",
      "displayName",
      "enabled",
      "maxInputChars",
      "maxOutputTokens",
      "model",
      "providerId",
      "revision",
    ]) ||
    !hasOnlyKeys(value, [
      "alternativeProviders",
      "baseUrl",
      "configured",
      "displayName",
      "enabled",
      "maxInputChars",
      "maxOutputTokens",
      "model",
      "providerId",
      "revision",
    ])
  ) {
    return false;
  }
  return (
    hasConfiguredRuntimeFields(value) &&
    isAlternativeProviders(value.alternativeProviders, String(value.providerId))
  );
}

function isConfiguredRuntimeProvider(value: unknown): boolean {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      "baseUrl",
      "configured",
      "displayName",
      "enabled",
      "maxInputChars",
      "maxOutputTokens",
      "model",
      "providerId",
      "revision",
    ]) &&
    hasConfiguredRuntimeFields(value)
  );
}

function hasConfiguredRuntimeFields(value: Record<string, unknown>): boolean {
  return (
    isSafeBaseUrl(value.baseUrl) &&
    typeof value.configured === "boolean" &&
    isBoundedText(value.displayName, 100) &&
    typeof value.enabled === "boolean" &&
    isBoundedInteger(value.maxInputChars, 1, 200_000) &&
    isBoundedInteger(value.maxOutputTokens, 1, 16_384) &&
    isBoundedToken(value.model, 200) &&
    isUuid(value.providerId) &&
    value.revision === 0
  );
}

function isAlternativeProviders(value: unknown, primaryProviderId: string): boolean {
  if (value === undefined || value === null) return true;
  if (
    !Array.isArray(value) ||
    value.length > 9 ||
    !value.every(isConfiguredRuntimeProvider)
  ) {
    return false;
  }
  const identities = new Set([primaryProviderId]);
  for (const provider of value) {
    identities.add(String(provider.providerId));
  }
  return identities.size === value.length + 1;
}

function isOperationReceipt(value: unknown): value is OperationReceipt {
  return (
    isRecord(value) &&
    hasExactKeys(value, ["kind", "operationId", "status", "submittedAt"]) &&
    value.kind === "PLAN_EXTRACTION" &&
    isUuid(value.operationId) &&
    value.status === "QUEUED" &&
    isShanghaiDateTime(value.submittedAt)
  );
}

function isPlanExtraction(value: unknown): value is PlanExtractionView {
  if (
    !isRecord(value) ||
    !hasKeys(value, ["id", "providerId", "status", "submittedAt"]) ||
    !hasOnlyKeys(value, [
      "assumptions",
      "completedAt",
      "diagnosticStatus",
      "dailyMapping",
      "draftPlanJson",
      "evidence",
      "id",
      "model",
      "mapping",
      "promptVersion",
      "providerId",
      "sourceTextSha256",
      "startedAt",
      "status",
      "submittedAt",
      "unmappedText",
      "usage",
      "validationIssues",
      "warnings",
    ]) ||
    !(value.dailyMapping == null || (isRecord(value.dailyMapping) && value.dailyMapping.mapping_version === "daily-mapping-v1" && Array.isArray(value.dailyMapping.clauses) && Array.isArray(value.dailyMapping.bindings) && Array.isArray(value.dailyMapping.supplements))) ||
    !isUuid(value.id) ||
    !isUuid(value.providerId) ||
    typeof value.status !== "string" ||
    !extractionStatuses.has(value.status) ||
    !isShanghaiDateTime(value.submittedAt) ||
    !isNullableOptionalShanghaiDateTime(value.startedAt) ||
    !isNullableOptionalShanghaiDateTime(value.completedAt) ||
    !(value.diagnosticStatus == null ||
      value.diagnosticStatus === "RECORDED" || value.diagnosticStatus === "WRITE_FAILED") ||
    !isOptionalArray(value.evidence, 10_000, isFieldEvidence) ||
    !isOptionalArray(value.assumptions, 256, isExtractionIssue) ||
    !isOptionalArray(value.warnings, 256, isExtractionIssue) ||
    !isOptionalArray(value.unmappedText, 256, isUnmappedText) ||
    !isOptionalArray(value.validationIssues, 512, isValidationIssue) ||
    !isOptionalUsage(value.usage)
  ) {
    return false;
  }
  const succeeded = value.status === "SUCCEEDED";
  if (succeeded) {
    return (
      isSha256(value.sourceTextSha256) &&
      isBoundedToken(value.model, 200) &&
      isBoundedToken(value.promptVersion, 64) &&
      isBoundedText(value.draftPlanJson, 4 * 1024 * 1024) &&
      Array.isArray(value.evidence) &&
      (["plan-extract-v8", "plan-extract-v9", "plan-extract-v10"].includes(value.promptVersion)
        ? value.evidence.length === 0 && isRecord(value.dailyMapping) && value.mapping == null
        : ["plan-extract-v4", "plan-extract-v5", "plan-extract-v6"].includes(value.promptVersion)
        ? value.evidence.length === 0 && isExtractionMapping(value.mapping)
        : value.evidence.length > 0 && value.mapping == null) &&
      value.startedAt !== null &&
      value.startedAt !== undefined &&
      value.completedAt !== null &&
      value.completedAt !== undefined
    );
  }
  if (value.status === "QUEUED") {
    return value.startedAt == null && value.completedAt == null && hasNoResultPayload(value);
  }
  if (value.status === "RUNNING") {
    return value.startedAt != null && value.completedAt == null && hasNoResultPayload(value);
  }
  return value.completedAt != null && hasNoResultPayload(value);
}

function hasNoResultPayload(value: Record<string, unknown>): boolean {
  return (
    value.draftPlanJson == null &&
    value.mapping == null &&
    isAbsentOrEmptyArray(value.evidence) &&
    isAbsentOrEmptyArray(value.assumptions) &&
    isAbsentOrEmptyArray(value.warnings) &&
    isAbsentOrEmptyArray(value.unmappedText) &&
    value.model == null &&
    value.promptVersion == null &&
    value.sourceTextSha256 == null &&
    value.usage == null
  );
}

function isExtractionMapping(value: unknown): boolean {
  return isRecord(value) &&
    ["plan-mapping-v1", "plan-mapping-v2"].includes(String(value.mappingVersion)) &&
    Array.isArray(value.sourceClauses) && value.sourceClauses.length > 0 &&
    value.sourceClauses.length <= 512 && value.sourceClauses.every((clause) =>
      isRecord(clause) && typeof clause.clauseId === "string" && typeof clause.excerpt === "string" &&
      Number.isSafeInteger(clause.start) && Number.isSafeInteger(clause.end)) &&
    Array.isArray(value.fieldBindings) &&
    value.fieldBindings.length <= 10_000 && value.fieldBindings.every((binding) =>
      isRecord(binding) && typeof binding.path === "string" && typeof binding.unit === "string" &&
      ["SOURCE", "CONTRACT", "USER_SUPPLEMENT"].includes(String(binding.origin)));
}

function isAbsentOrEmptyArray(value: unknown): boolean {
  return value === undefined || (Array.isArray(value) && value.length === 0);
}

function isFieldEvidence(value: unknown): value is FieldEvidence {
  return (
    isRecord(value) &&
    hasKeys(value, ["excerpt", "path"]) &&
    hasOnlyKeys(value, ["end", "excerpt", "path", "start"]) &&
    isBoundedText(value.excerpt, 512) &&
    isBoundedText(value.path, 256) &&
    isNullableOptionalNonnegativeInteger(value.start) &&
    isNullableOptionalPositiveInteger(value.end)
  );
}

function isExtractionIssue(value: unknown): value is ExtractionIssue {
  return (
    isRecord(value) &&
    hasExactKeys(value, ["material", "message", "path"]) &&
    typeof value.material === "boolean" &&
    isBoundedText(value.message, 512) &&
    isBoundedText(value.path, 256)
  );
}

function isUnmappedText(value: unknown): value is UnmappedText {
  return (
    isRecord(value) &&
    hasKeys(value, ["excerpt", "material", "path", "reason"]) &&
    hasOnlyKeys(value, ["end", "excerpt", "material", "path", "reason", "start"]) &&
    isBoundedText(value.excerpt, 512) &&
    typeof value.material === "boolean" &&
    isBoundedText(value.path, 256) &&
    isBoundedText(value.reason, 512) &&
    isNullableOptionalNonnegativeInteger(value.start) &&
    isNullableOptionalPositiveInteger(value.end)
  );
}

function isValidationIssue(value: unknown): value is ValidationIssue {
  return (
    isRecord(value) &&
    hasExactKeys(value, ["activationBlocking", "code", "message", "path", "severity"]) &&
    typeof value.activationBlocking === "boolean" &&
    isBoundedToken(value.code, 64) &&
    isBoundedText(value.message, 512) &&
    isBoundedText(value.path, 256) &&
    typeof value.severity === "string" &&
    validationSeverities.has(value.severity)
  );
}

function isOptionalUsage(value: unknown): boolean {
  return (
    value === undefined ||
    value === null ||
    (isRecord(value) &&
      hasExactKeys(value, ["completionTokens", "promptTokens", "totalTokens"]) &&
      isBoundedInteger(value.completionTokens, 0, Number.MAX_SAFE_INTEGER) &&
      isBoundedInteger(value.promptTokens, 0, Number.MAX_SAFE_INTEGER) &&
      isBoundedInteger(value.totalTokens, 0, Number.MAX_SAFE_INTEGER) &&
      value.totalTokens >= value.completionTokens + value.promptTokens)
  );
}

function isOptionalArray<T>(
  value: unknown,
  maximum: number,
  predicate: (item: unknown) => item is T,
): boolean {
  return value === undefined || (Array.isArray(value) && value.length <= maximum && value.every(predicate));
}

function isSafeBaseUrl(value: unknown): boolean {
  if (typeof value !== "string" || value.length > 2_048) {
    return false;
  }
  try {
    const parsed = new URL(value);
    return (
      (parsed.protocol === "https:" || parsed.protocol === "http:") &&
      parsed.username === "" &&
      parsed.password === "" &&
      parsed.search === "" &&
      parsed.hash === ""
    );
  } catch {
    return false;
  }
}

function isNullableOptionalShanghaiDateTime(value: unknown): boolean {
  return value === undefined || value === null || isShanghaiDateTime(value);
}

function isNullableOptionalNonnegativeInteger(value: unknown): boolean {
  return value === undefined || value === null || isBoundedInteger(value, 0, Number.MAX_SAFE_INTEGER);
}

function isNullableOptionalPositiveInteger(value: unknown): boolean {
  return value === undefined || value === null || isBoundedInteger(value, 1, Number.MAX_SAFE_INTEGER);
}

function isBoundedInteger(value: unknown, minimum: number, maximum: number): value is number {
  return (
    typeof value === "number" &&
    Number.isSafeInteger(value) &&
    value >= minimum &&
    value <= maximum
  );
}

function isUuid(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(
      value,
    )
  );
}

function isSha256(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
}

function isBoundedText(value: unknown, maximum: number): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= maximum;
}

function isBoundedToken(value: unknown, maximum: number): value is string {
  return isBoundedText(value, maximum) && !/[\s\u0000-\u001f\u007f]/.test(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasKeys(value: Record<string, unknown>, required: readonly string[]): boolean {
  return required.every((key) => Object.hasOwn(value, key));
}

function hasOnlyKeys(value: Record<string, unknown>, allowed: readonly string[]): boolean {
  const allowedKeys = new Set(allowed);
  return Object.keys(value).every((key) => allowedKeys.has(key));
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(value).length === keys.length && hasKeys(value, keys);
}

export { ApiClientError };
