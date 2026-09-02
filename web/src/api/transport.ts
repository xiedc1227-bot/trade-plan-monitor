import type {
  ApiErrorCode,
  ErrorDetail,
  ErrorPayload,
  ErrorResponse,
} from "./generated";

const MAX_RESPONSE_BYTES = 4 * 1024 * 1024;
const MAX_ERROR_DETAILS = 100;
const MAX_ERROR_TEXT_CHARACTERS = 256;
const MAX_JSON_DEPTH = 32;
const MAX_JSON_NODES = 50_000;
const safeTokenCountKeys = new Set([
  "completionTokens",
  "maxOutputTokens",
  "promptTokens",
  "totalTokens",
]);

const safeErrorMessages: Record<ApiErrorCode, string> = {
  BAD_REQUEST: "请求格式无效",
  CONFLICT: "请求与当前状态冲突",
  FORBIDDEN: "请求被拒绝",
  INTERNAL_ERROR: "本地监控服务发生内部错误",
  METHOD_NOT_ALLOWED: "请求方法不受支持",
  NOT_FOUND: "请求的资源不存在",
  PAYLOAD_TOO_LARGE: "请求内容过大",
  RATE_LIMITED: "请求过于频繁，请稍后重试",
  SERVICE_UNAVAILABLE: "本地监控服务暂不可用",
  UNAUTHORIZED: "请求未获授权",
  VALIDATION_ERROR: "请求内容未通过校验",
};

const apiErrorCodes = new Set<ApiErrorCode>([
  "BAD_REQUEST",
  "VALIDATION_ERROR",
  "UNAUTHORIZED",
  "FORBIDDEN",
  "NOT_FOUND",
  "METHOD_NOT_ALLOWED",
  "CONFLICT",
  "PAYLOAD_TOO_LARGE",
  "RATE_LIMITED",
  "SERVICE_UNAVAILABLE",
  "INTERNAL_ERROR",
]);

export type ApiClientErrorCode = ApiErrorCode | "INVALID_RESPONSE" | "NETWORK_ERROR";

interface ApiClientErrorOptions {
  code: ApiClientErrorCode;
  details?: readonly ErrorDetail[] | undefined;
  message: string;
  requestId?: string | undefined;
  status: number;
}

export class ApiClientError extends Error {
  readonly code: ApiClientErrorCode;
  readonly details: readonly ErrorDetail[];
  readonly requestId: string | undefined;
  readonly status: number;

  constructor(options: ApiClientErrorOptions) {
    super(options.message);
    this.name = "ApiClientError";
    this.code = options.code;
    this.details = Object.freeze([...(options.details ?? [])]);
    this.requestId = options.requestId;
    this.status = options.status;
  }
}

export interface JsonTransportResponse {
  readonly body: unknown;
  readonly headers: Headers;
  readonly status: number;
}

export async function requestJson(
  fetchImplementation: typeof fetch,
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<JsonTransportResponse> {
  let response: Response;
  try {
    response = await fetchImplementation(input, init);
  } catch {
    throw networkError();
  }

  const body = await readJson(response);
  if (!response.ok) {
    throw parseErrorResponse(body, response.status);
  }
  return Object.freeze({ body, headers: response.headers, status: response.status });
}

export function invalidResponse(status: number): ApiClientError {
  return new ApiClientError({
    code: "INVALID_RESPONSE",
    message: "本地监控服务返回了无效响应",
    status,
  });
}

function networkError(): ApiClientError {
  return new ApiClientError({
    code: "NETWORK_ERROR",
    message: "无法连接本地监控服务",
    status: 0,
  });
}

async function readJson(response: Response): Promise<unknown> {
  const contentLength = response.headers.get("Content-Length");
  if (
    contentLength !== null &&
    /^\d+$/.test(contentLength) &&
    Number(contentLength) > MAX_RESPONSE_BYTES
  ) {
    await response.body?.cancel().catch(() => undefined);
    throw invalidResponse(response.status);
  }

  const stream = response.body;
  if (stream === null) {
    throw invalidResponse(response.status);
  }
  const reader = stream.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  const chunks: string[] = [];
  let receivedBytes = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        chunks.push(decoder.decode());
        break;
      }
      if (value.byteLength > MAX_RESPONSE_BYTES - receivedBytes) {
        await reader.cancel().catch(() => undefined);
        throw invalidResponse(response.status);
      }
      receivedBytes += value.byteLength;
      chunks.push(decoder.decode(value, { stream: true }));
    }
  } catch (error) {
    await reader.cancel().catch(() => undefined);
    if (error instanceof ApiClientError) {
      throw error;
    }
    throw invalidResponse(response.status);
  } finally {
    reader.releaseLock();
  }

  try {
    return validateAndFreezeJson(JSON.parse(chunks.join("")) as unknown, response.status);
  } catch (error) {
    if (error instanceof ApiClientError) {
      throw error;
    }
    throw invalidResponse(response.status);
  }
}

function validateAndFreezeJson(value: unknown, status: number): unknown {
  const pending: Array<{ depth: number; value: unknown }> = [{ depth: 0, value }];
  const containers: object[] = [];
  let scheduledNodes = 1;

  while (pending.length > 0) {
    const current = pending.pop();
    if (current === undefined) {
      break;
    }
    if (Array.isArray(current.value)) {
      containers.push(current.value);
      for (const child of current.value) {
        scheduledNodes += 1;
        const childDepth = current.depth + 1;
        if (scheduledNodes > MAX_JSON_NODES || childDepth > MAX_JSON_DEPTH) {
          throw invalidResponse(status);
        }
        pending.push({ depth: childDepth, value: child });
      }
      continue;
    }
    if (typeof current.value === "number" && !Number.isFinite(current.value)) {
      throw invalidResponse(status);
    }
    if (!isRecord(current.value)) {
      continue;
    }
    containers.push(current.value);
    for (const key in current.value) {
      if (!Object.hasOwn(current.value, key)) {
        continue;
      }
      if (isSensitiveKey(key)) {
        throw invalidResponse(status);
      }
      scheduledNodes += 1;
      const childDepth = current.depth + 1;
      if (scheduledNodes > MAX_JSON_NODES || childDepth > MAX_JSON_DEPTH) {
        throw invalidResponse(status);
      }
      pending.push({ depth: childDepth, value: current.value[key] });
    }
  }

  for (const container of containers) {
    Object.freeze(container);
  }
  return value;
}

function parseErrorResponse(value: unknown, status: number): ApiClientError {
  if (!isErrorResponse(value)) {
    return invalidResponse(status);
  }
  const payload: ErrorPayload = value.error;
  const details = payload.details?.map(redactErrorDetail);
  return new ApiClientError({
    code: payload.code,
    details,
    message: safeErrorMessages[payload.code],
    requestId: payload.requestId,
    status,
  });
}

function redactErrorDetail(detail: ErrorDetail): ErrorDetail {
  const safeDetail: ErrorDetail = {
    code: detail.code,
    location: [...detail.location],
    message: "请求字段无效",
  };
  Object.freeze(safeDetail.location);
  return Object.freeze(safeDetail);
}

function isErrorResponse(value: unknown): value is ErrorResponse {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["error"]) ||
    !isRecord(value.error) ||
    !hasOnlyKeys(value.error, ["code", "details", "message", "requestId"])
  ) {
    return false;
  }
  const error = value.error;
  return (
    typeof error.code === "string" &&
    apiErrorCodes.has(error.code as ApiErrorCode) &&
    isBoundedString(error.message, MAX_ERROR_TEXT_CHARACTERS) &&
    typeof error.requestId === "string" &&
    /^[0-9a-f]{32}$/.test(error.requestId) &&
    (error.details === undefined ||
      (Array.isArray(error.details) &&
        error.details.length <= MAX_ERROR_DETAILS &&
        error.details.every(isErrorDetail)))
  );
}

function isErrorDetail(value: unknown): value is ErrorDetail {
  return (
    isRecord(value) &&
    hasExactKeys(value, ["code", "location", "message"]) &&
    isStableCode(value.code) &&
    Array.isArray(value.location) &&
    value.location.length > 0 &&
    value.location.length <= 16 &&
    value.location.every(
      (part) =>
        (typeof part === "string" && isLocationPart(part)) ||
        (typeof part === "number" && Number.isSafeInteger(part) && part >= 0),
    ) &&
    isBoundedString(value.message, MAX_ERROR_TEXT_CHARACTERS)
  );
}

function isSensitiveKey(key: string): boolean {
  if (safeTokenCountKeys.has(key)) {
    return false;
  }
  const normalized = key.replaceAll(/[^a-z]/gi, "").toLowerCase();
  return /(?:apikey|authorization|credential|password|secret|token)/.test(normalized);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasOnlyKeys(value: Record<string, unknown>, allowed: readonly string[]): boolean {
  const allowedKeys = new Set(allowed);
  return Object.keys(value).every((key) => allowedKeys.has(key));
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return (
    Object.keys(value).length === keys.length &&
    keys.every((key) => Object.hasOwn(value, key))
  );
}

function isStableCode(value: unknown): value is string {
  return typeof value === "string" && /^[A-Z][A-Z0-9_]{0,63}$/.test(value);
}

function isLocationPart(value: string): boolean {
  return /^[A-Za-z][A-Za-z0-9_.-]{0,63}$/.test(value);
}

function isBoundedString(value: unknown, maximum: number): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= maximum;
}
