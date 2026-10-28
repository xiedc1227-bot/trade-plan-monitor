import type {
  SourceCoverageIssueView, SourceCoveragePage, SourceCoverageSummaryView,
  SourceHumanSupplementLinkView, SourceMappingProposalView,
  SourceNormalizationChangeView, SourceObligationView,
} from "./generated";
import { resolveApiFetch } from "./context";
import { invalidResponse, requestJson } from "./transport";

export type { SourceCoveragePage, SourceCoverageSummaryView } from "./generated";

export interface SourceCoverageRequest {
  readonly limit?: number;
  readonly cursor?: string;
}

export interface SourceCoverageRequestOptions {
  readonly signal?: AbortSignal;
}

export interface SourceCoverageApi {
  getSourceCoverage(versionId: string, request?: SourceCoverageRequest,
    options?: SourceCoverageRequestOptions): Promise<SourceCoveragePage>;
}

export function createSourceCoverageApi(fetchImplementation: typeof fetch = resolveApiFetch()): SourceCoverageApi {
  return Object.freeze({
    async getSourceCoverage(versionId: string, request: SourceCoverageRequest = {},
      options?: SourceCoverageRequestOptions) {
      if (!uuid(versionId) || !record(request) ||
        !Object.keys(request).every((key) => key === "limit" || key === "cursor")) throw invalidResponse(0);
      const limit = request.limit === undefined ? 50 : request.limit;
      const requestCursor = request.cursor;
      if (!integer(limit, 1, 100) || (requestCursor !== undefined && !cursor(requestCursor)))
        throw invalidResponse(0);
      const query = new URLSearchParams({ limit: String(limit) });
      if (requestCursor !== undefined) query.set("cursor", requestCursor);
      const init: RequestInit = { method: "GET", headers: { Accept: "application/json" } };
      if (options?.signal !== undefined) init.signal = options.signal;
      const { body, status } = await requestJson(fetchImplementation,
        `/api/v1/plan-versions/${encodeURIComponent(versionId)}/source-coverage?${query}`, init,
        { maxResponseBytes: 1_048_576 });
      if (!isSourceCoveragePage(body, versionId, limit, requestCursor === undefined)) throw invalidResponse(status);
      return body;
    },
  });
}

const SUMMARY_KEYS = ["authorityGranted", "status", "coverageComplete", "currentReviewBound",
  "canConfirmReview", "reviewState", "reason", "sourceHash", "candidatePlanHash", "contentHash",
  "mappingHash", "rulesVersion", "coverageEvidenceHash", "coverageRevision", "coverageBundleHash",
  "normalizationHash", "originalReviewEvidenceHash", "reviewId", "reviewRevision",
  "coverageReviewReceiptHash", "origin", "automaticFidelityVerified", "obligationCount",
  "issueCount", "normalizationChangeCount", "totalRows"];

export function isSourceCoverageSummary(value: unknown): value is SourceCoverageSummaryView {
  if (!record(value) || !keys(value, SUMMARY_KEYS) || value.authorityGranted !== false ||
    !oneOf(value.status, ["COMPLETE", "BLOCKED", "LEGACY_UNASSESSED", "UNKNOWN"]) ||
    typeof value.coverageComplete !== "boolean" || typeof value.currentReviewBound !== "boolean" ||
    typeof value.canConfirmReview !== "boolean" || typeof value.automaticFidelityVerified !== "boolean" ||
    !oneOf(value.reviewState, ["UNCONFIRMED", "CURRENT", "NEEDS_REVIEW", "UNKNOWN"]) ||
    !(value.reason === null || oneOf(value.reason, ["SOURCE_COVERAGE_REQUIRED", "SOURCE_COVERAGE_STALE",
      "SOURCE_COVERAGE_UPGRADE_REQUIRED", "SOURCE_COVERAGE_LIMIT_EXCEEDED"])) ||
    !digest(value.sourceHash) || !digest(value.candidatePlanHash) ||
    ![value.contentHash, value.mappingHash, value.coverageEvidenceHash, value.coverageBundleHash,
      value.normalizationHash, value.originalReviewEvidenceHash, value.coverageReviewReceiptHash].every(nullableDigest) ||
    !(value.rulesVersion === null || value.rulesVersion === "source-coverage-rules-v1") ||
    !(value.reviewId === null || uuid(value.reviewId)) || !integer(value.reviewRevision) ||
    !(value.coverageRevision === null || integer(value.coverageRevision, 1)) ||
    !(value.origin === null || oneOf(value.origin, ["AI_NEW", "AI_HISTORICAL", "HUMAN"])) ||
    !integer(value.obligationCount, 0, 4096) || !integer(value.issueCount, 0, 8192) ||
    !integer(value.normalizationChangeCount, 0, 2000) || !integer(value.totalRows, 0, 14288)) return false;
  const proofPresent = [value.contentHash, value.mappingHash, value.rulesVersion,
    value.coverageEvidenceHash, value.originalReviewEvidenceHash].every((item) => item !== null);
  return value.coverageComplete === (value.status === "COMPLETE") &&
    (value.reviewState === "CURRENT") === value.currentReviewBound &&
    (!value.currentReviewBound || (value.coverageComplete && value.reviewId !== null &&
      value.reviewRevision > 0 && value.coverageReviewReceiptHash !== null &&
      value.coverageRevision !== null && value.coverageBundleHash !== null && proofPresent && value.reason === null)) &&
    (!value.canConfirmReview || (value.coverageComplete && value.reviewId === null &&
      value.reviewRevision === 0 && !value.currentReviewBound && value.reviewState === "UNCONFIRMED" &&
      proofPresent && value.coverageRevision !== null && value.coverageBundleHash !== null && value.reason === null)) &&
    (!value.automaticFidelityVerified || (value.origin === "AI_NEW" && value.coverageComplete && value.normalizationHash !== null)) &&
    (!value.coverageComplete || (value.obligationCount > 0 && value.issueCount === 0)) &&
    value.totalRows === value.obligationCount + value.issueCount + value.normalizationChangeCount;
}

type CoverageRow = SourceCoveragePage["items"][number];

function isSourceCoveragePage(value: unknown, versionId: string, limit: number, firstPage: boolean): value is SourceCoveragePage {
  if (!record(value) || !keys(value, ["authorityGranted", "planVersionId", "summary", "items", "limit",
    "returnedCount", "totalRows", "nextCursor"]) || value.authorityGranted !== false ||
    value.planVersionId !== versionId || value.limit !== limit || !isSourceCoverageSummary(value.summary) ||
    !array(value.items, 100, isRow) || !integer(value.returnedCount, 0, limit) ||
    value.returnedCount !== value.items.length || value.totalRows !== value.summary.totalRows ||
    !(value.nextCursor === null || cursor(value.nextCursor))) return false;
  if (!value.items.length) return firstPage && value.totalRows === 0 && value.nextCursor === null;
  const summary = value.summary;
  const start = value.items[0]?.rowIndex;
  if (start === undefined || (firstPage ? start !== 0 : start <= 0) ||
    start + value.items.length > value.totalRows ||
    (value.nextCursor !== null) !== (start + value.items.length < value.totalRows)) return false;
  return value.items.every((row, index) => {
    if (row.rowIndex !== start + index) return false;
    const expected = row.rowIndex < summary.obligationCount ? "OBLIGATION" :
      row.rowIndex < summary.obligationCount + summary.issueCount ? "ISSUE" : "NORMALIZATION_CHANGE";
    if (row.kind !== expected) return false;
    if (row.kind === "OBLIGATION") {
      const obligation = row.obligation;
      return obligation.sourceHash === summary.sourceHash && obligation.rulesVersion === summary.rulesVersion &&
        (!summary.coverageComplete || obligation.scope !== "UNKNOWN" && oneOf(obligation.serverState,
          ["MAPPED", "MAPPED_WITH_REGISTERED_SUPPLEMENT", "CONTEXT_VERIFIED", "SCOPE_EXCLUDED"])) &&
        obligation.humanSupplements.every((link) => obligation.serverState === "MAPPED_WITH_REGISTERED_SUPPLEMENT" &&
          link.candidateContentHash === summary.contentHash && obligation.paths.includes(link.path));
    }
    if (row.kind === "NORMALIZATION_CHANGE" && row.change.traceRole === "CURRENT_ASSESSMENT")
      return row.change.sourceHash === summary.sourceHash && row.change.evidenceHash === summary.normalizationHash;
    // Historical input traces are explicitly separate from the current source frame.
    return true;
  });
}

function isRow(value: unknown): value is CoverageRow {
  if (!record(value) || !integer(value.rowIndex)) return false;
  if (value.kind === "OBLIGATION") return keys(value, ["kind", "rowIndex", "obligation"]) && isObligation(value.obligation);
  if (value.kind === "ISSUE") return keys(value, ["kind", "rowIndex", "issue"]) && isIssue(value.issue);
  return value.kind === "NORMALIZATION_CHANGE" && keys(value, ["kind", "rowIndex", "change"]) && isChange(value.change);
}

function isObligation(value: unknown): value is SourceObligationView {
  return record(value) && keys(value, ["version", "rulesVersion", "sourceHash", "clauseId", "start", "end", "excerpt",
    "kind", "scope", "serverState", "semanticsJson", "groupId", "relationIds", "paths", "obligationId",
    "mappingProposal", "humanSupplements"]) && value.version === "source-obligation-v1" &&
    value.rulesVersion === "source-coverage-rules-v1" && digest(value.sourceHash) && text(value.clauseId, 128) &&
    integer(value.start, 0, 150000) && integer(value.end, 1, 150000) && value.start < value.end &&
    text(value.excerpt, 512) && Array.from(value.excerpt).length === value.end - value.start &&
    oneOf(value.kind, ["DECLARATION", "PREDICATE", "RELATION", "CONTEXT", "SCOPE_EXCLUSION", "UNKNOWN"]) &&
    oneOf(value.scope, ["PLAN", "BUY", "SELL", "RISK", "ALERT", "UNKNOWN"]) &&
    oneOf(value.serverState, ["MAPPED", "MAPPED_WITH_REGISTERED_SUPPLEMENT", "CONTEXT_VERIFIED", "SCOPE_EXCLUDED",
      "UNRESOLVED", "UNSUPPORTED", "CONFLICT"]) &&
    (value.semanticsJson === null || text(value.semanticsJson, 8192, 0)) && nullableDigest(value.groupId) &&
    array(value.relationIds, 64, digest) && array(value.paths, 512, path) && digest(value.obligationId) &&
    (value.mappingProposal === null || isProposal(value.mappingProposal)) && array(value.humanSupplements, 2000, isSupplement);
}

function isProposal(value: unknown): value is SourceMappingProposalView {
  return record(value) && keys(value, ["proposedDisposition", "semanticRole", "reason", "proposedPaths"]) &&
    oneOf(value.proposedDisposition, ["POLICY", "INVENTORY_ASSERTION", "BACKGROUND", "CONTEXT", "UNRESOLVED", "UNSUPPORTED"]) &&
    (value.semanticRole === null || oneOf(value.semanticRole, ["DIRECTIVE", "HISTORICAL", "ACCOUNT", "COMMENTARY", "AMBIGUOUS"])) &&
    text(value.reason, 2000) && array(value.proposedPaths, 512, (item): item is string => typeof item === "string");
}

function isSupplement(value: unknown): value is SourceHumanSupplementLinkView {
  return record(value) && keys(value, ["supplementId", "path", "candidateContentHash"]) &&
    text(value.supplementId, 128) && path(value.path) && digest(value.candidateContentHash);
}

function isIssue(value: unknown): value is SourceCoverageIssueView {
  return record(value) && keys(value, ["code", "path", "start", "end", "message"]) &&
    typeof value.code === "string" && /^[A-Z][A-Z0-9_]{0,127}$/.test(value.code) && path(value.path) && text(value.message, 512) &&
    ((value.start === null && value.end === null) || (integer(value.start, 0, 150000) &&
      integer(value.end, 1, 150000) && value.start < value.end));
}

function isChange(value: unknown): value is SourceNormalizationChangeView {
  return record(value) && keys(value, ["path", "beforeJson", "afterJson", "reason", "traceRole", "sourceHash",
    "beforeHash", "afterHash", "evidenceHash"]) && path(value.path) && text(value.beforeJson, 8192, 0) &&
    text(value.afterJson, 8192, 0) && text(value.reason, 128) &&
    oneOf(value.traceRole, ["CURRENT_ASSESSMENT", "HISTORICAL_INPUT"]) &&
    [value.sourceHash, value.beforeHash, value.afterHash, value.evidenceHash].every(digest);
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function keys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  return Object.keys(value).length === expected.length && expected.every((key) => Object.hasOwn(value, key));
}
function integer(value: unknown, minimum = 0, maximum = Number.MAX_SAFE_INTEGER): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= minimum && value <= maximum;
}
function digest(value: unknown): value is string { return typeof value === "string" && /^[0-9a-f]{64}$/.test(value); }
function nullableDigest(value: unknown): boolean { return value === null || digest(value); }
function uuid(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(value);
}
function cursor(value: unknown): value is string { return typeof value === "string" && /^[\x00-\x7f]{1,512}$/.test(value); }
function oneOf(value: unknown, allowed: readonly string[]): boolean { return typeof value === "string" && allowed.includes(value); }
function path(value: unknown): value is string { return text(value, 512); }
function text(value: unknown, maximum: number, minimum = 1): value is string {
  if (typeof value !== "string") return false;
  let count = 0;
  for (const character of value) {
    const point = character.codePointAt(0);
    if (point === undefined || point >= 0xd800 && point <= 0xdfff || ++count > maximum) return false;
  }
  return count >= minimum;
}
function array<T>(value: unknown, maximum: number, validate: (item: unknown) => item is T): value is T[] {
  return Array.isArray(value) && value.length <= maximum && value.every(validate);
}
