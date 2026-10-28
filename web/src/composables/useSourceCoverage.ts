import { computed, onScopeDispose, readonly, shallowRef, toValue, watch,
  type DeepReadonly, type MaybeRefOrGetter } from "vue";
import { createSourceCoverageApi, isSourceCoveragePage, isSourceCoverageSummary,
  type SourceCoverageApi, type SourceCoveragePage, type SourceCoverageSummaryView } from "../api/sourceCoverage";
import { ApiClientError } from "../api/transport";
import { summaryBinding } from "../components/plans/sourceCoveragePresentation";

export interface SourceCoverageContext {
  readonly planVersionId: string;
  readonly sourceHash: string;
  readonly candidatePlanHash: string;
  readonly contentHash: string | null;
  readonly originalReviewEvidenceHash: string | null;
  readonly reviewId: string | null;
  readonly reviewRevision: number;
  readonly sourceText: string;
  readonly ownerGeneration: string | number;
  readonly expectedSummary?: DeepReadonly<SourceCoverageSummaryView>;
}

export interface UseSourceCoverageOptions {
  readonly api?: SourceCoverageApi;
  readonly limit?: number;
}

export type SourceCoveragePhase = "IDLE" | "LOADING" | "CURRENT" | "STALE" | "ERROR";

export interface SourceCoverageReadError {
  readonly code: string;
  readonly message: string;
  readonly requiresFirstPage: boolean;
}

export interface SourceCoverageConfirmation {
  readonly coverageEvidenceHash: string;
  readonly coverageRulesVersion: "source-coverage-rules-v1";
}

interface ReadContext {
  readonly value: SourceCoverageContext;
  readonly key: string;
  readonly api: SourceCoverageApi;
  readonly call: SourceCoverageApi["getSourceCoverage"];
  readonly limit: number;
}

function copyContext(value: SourceCoverageContext): SourceCoverageContext {
  return Object.freeze({ planVersionId: value.planVersionId, sourceHash: value.sourceHash,
    candidatePlanHash: value.candidatePlanHash, contentHash: value.contentHash,
    originalReviewEvidenceHash: value.originalReviewEvidenceHash, reviewId: value.reviewId,
    reviewRevision: value.reviewRevision, sourceText: value.sourceText,
    ownerGeneration: value.ownerGeneration,
    ...(value.expectedSummary ? { expectedSummary: Object.freeze({ ...value.expectedSummary }) } : {}) });
}

function contextKey(value: SourceCoverageContext): string {
  return JSON.stringify([value.planVersionId, value.sourceHash, value.candidatePlanHash,
    value.contentHash, value.originalReviewEvidenceHash, value.reviewId, value.reviewRevision,
    value.sourceText, value.ownerGeneration,
    value.expectedSummary ? summaryBinding(value.expectedSummary) : null]);
}

class CoverageReadFailure extends Error {
  constructor(readonly code: string, message: string, readonly requiresFirstPage = false) { super(message); }
}

function errorView(code: string, message: string, requiresFirstPage = false): SourceCoverageReadError {
  return Object.freeze({ code, message, requiresFirstPage });
}

function peersMatch(value: SourceCoverageSummaryView, context: SourceCoverageContext): boolean {
  return value.sourceHash === context.sourceHash && value.candidatePlanHash === context.candidatePlanHash &&
    value.contentHash === context.contentHash && value.originalReviewEvidenceHash === context.originalReviewEvidenceHash &&
    value.reviewId === context.reviewId && value.reviewRevision === context.reviewRevision;
}

/** Reuse the wire decoder for injected APIs, then bind this exact read chain. */
function coherentPage(page: SourceCoveragePage, context: ReadContext, start: number,
  chain: string | null, cursors: ReadonlySet<string>): boolean {
  if (!isSourceCoveragePage(page, context.value.planVersionId, context.limit, start === 0) ||
    !peersMatch(page.summary, context.value) ||
    (page.items[0]?.rowIndex ?? 0) !== start) return false;
  const binding = summaryBinding(page.summary);
  if (chain !== null && binding !== chain || context.value.expectedSummary &&
    (!isSourceCoverageSummary(context.value.expectedSummary) ||
      binding !== summaryBinding(context.value.expectedSummary))) return false;
  return page.nextCursor === null || !cursors.has(page.nextCursor);
}

export function useSourceCoverage(
  input: MaybeRefOrGetter<SourceCoverageContext | null>,
  options: MaybeRefOrGetter<UseSourceCoverageOptions> = {},
) {
  const defaultApi = createSourceCoverageApi();
  const phase = shallowRef<SourceCoveragePhase>("IDLE");
  const page = shallowRef<DeepReadonly<SourceCoveragePage> | null>(null);
  const safeError = shallowRef<SourceCoverageReadError | null>(null);
  const verifiedSourceHash = shallowRef<string | null>(null);
  const summary = computed(() => page.value?.summary ?? null);
  const currentConfirmation = computed<SourceCoverageConfirmation | null>(() => {
    const value = summary.value;
    return phase.value === "CURRENT" && value?.canConfirmReview && value.coverageEvidenceHash && value.rulesVersion
      ? Object.freeze({ coverageEvidenceHash: value.coverageEvidenceHash, coverageRulesVersion: value.rulesVersion }) : null;
  });
  let generation = 0;
  let stopped = false;
  let controller: AbortController | null = null;
  let chain: string | null = null;
  let acceptedContext: ReadContext | null = null;
  const cursors = new Set<string>();

  function readContext(): ReadContext | null {
    const value = toValue(input);
    const selected = toValue(options);
    if (value === null) return null;
    const snapshot = copyContext(value);
    const api = selected.api ?? defaultApi;
    return { value: snapshot, key: contextKey(snapshot), api, call: api.getSourceCoverage,
      limit: selected.limit ?? 50 };
  }

  function current(context: ReadContext, expected: number, signal: AbortSignal): boolean {
    if (stopped || expected !== generation || signal.aborted) return false;
    const actual = readContext();
    const matches = actual !== null && actual.key === context.key && actual.api === context.api &&
      actual.call === context.call && actual.limit === context.limit;
    if (!matches) {
      invalidate();
      safeError.value = errorView("CONTEXT_CHANGED", "当前计划已变化，请重新读取", true);
    }
    return matches;
  }

  function clear(nextPhase: SourceCoveragePhase) {
    generation++;
    controller?.abort(); controller = null;
    phase.value = nextPhase; page.value = null; verifiedSourceHash.value = null; safeError.value = null;
    acceptedContext = null;
  }

  function invalidate() {
    clear(toValue(input) === null ? "IDLE" : "STALE");
    chain = null; cursors.clear();
  }

  async function load(context: ReadContext, cursor?: string, start = 0) {
    clear("LOADING");
    const expected = generation;
    const active = new AbortController(); controller = active;
    try {
      if (!Number.isSafeInteger(context.limit) || context.limit < 1 || context.limit > 100)
        throw new CoverageReadFailure("INVALID_LIMIT", "每页条数无效，请重新读取");
      if (Array.from(context.value.sourceText).some((character) => {
        const point = character.codePointAt(0)!; return point >= 0xd800 && point <= 0xdfff;
      })) throw new CoverageReadFailure("SOURCE_TEXT_INVALID", "原文包含无法准确定位的字符，请重新读取");
      const bytes = new TextEncoder().encode(context.value.sourceText);
      const result = await crypto.subtle.digest("SHA-256", bytes);
      if (!current(context, expected, active.signal)) return;
      const sourceHash = Array.from(new Uint8Array(result), (value) => value.toString(16).padStart(2, "0")).join("");
      if (sourceHash !== context.value.sourceHash)
        throw new CoverageReadFailure("SOURCE_HASH_MISMATCH", "原文与当前证明不一致，请重新读取", true);
      const response = await context.call.call(context.api, context.value.planVersionId,
        { limit: context.limit, ...(cursor === undefined ? {} : { cursor }) }, { signal: active.signal });
      if (!current(context, expected, active.signal)) return;
      if (!coherentPage(response, context, start, chain, cursors))
        throw new CoverageReadFailure("PAGE_CHANGED", "证明或分页内容已变化，请从第一页重新读取", true);
      // Own the decoded snapshot, including when a caller injects an API for tests.
      page.value = readonly(structuredClone(response));
      chain = summaryBinding(response.summary);
      if (response.nextCursor !== null) cursors.add(response.nextCursor);
      verifiedSourceHash.value = sourceHash;
      acceptedContext = context;
      phase.value = "CURRENT";
    } catch (error) {
      if (!current(context, expected, active.signal)) return;
      chain = null; cursors.clear(); page.value = null; verifiedSourceHash.value = null;
      if (error instanceof ApiClientError && (error.status === 409 || error.status === 422)) {
        safeError.value = errorView("CURSOR_RESTART_REQUIRED", "证明已变化，请从第一页重新读取", true);
      } else if (error instanceof CoverageReadFailure) {
        safeError.value = errorView(error.code, error.message, error.requiresFirstPage);
      } else safeError.value = errorView("READ_FAILED", "暂时无法读取原文核对结果，请重试");
      phase.value = safeError.value.requiresFirstPage ? "STALE" : "ERROR";
    } finally {
      if (current(context, expected, active.signal)) controller = null;
    }
  }

  async function refresh() {
    if (stopped) return;
    chain = null; cursors.clear();
    const context = readContext();
    if (context === null) { clear("IDLE"); return; }
    await load(context);
  }

  async function nextPage() {
    if (phase.value !== "CURRENT" || page.value?.nextCursor === null || !page.value) return;
    const context = readContext();
    const last = page.value.items.at(-1);
    if (!context || !last || !acceptedContext || context.key !== acceptedContext.key ||
      context.api !== acceptedContext.api || context.call !== acceptedContext.call ||
      context.limit !== acceptedContext.limit) { invalidate(); return; }
    await load(context, page.value.nextCursor, last.rowIndex + 1);
  }

  watch(readContext, () => { void refresh(); }, { immediate: true, flush: "sync" });
  onScopeDispose(() => { stopped = true; clear("IDLE"); chain = null; cursors.clear(); });
  return Object.freeze({ phase: readonly(phase), page: readonly(page), safeError: readonly(safeError),
    verifiedSourceHash: readonly(verifiedSourceHash), summary, currentConfirmation,
    refresh, firstPage: refresh, nextPage, invalidate });
}
