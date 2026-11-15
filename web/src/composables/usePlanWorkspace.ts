import { computed, onBeforeUnmount, shallowRef, watch } from "vue";
import type { ActivePlanView, ConfiguredAIRuntimeView, DailyMapping, DailyReviewPreview, DailySupplement,
  PlanExtractionCommand, PlanVersionView, PlanVersionSummary, DailyReviewPreviewCommand, DailySupplementCommand,
  PlanReviewConfirmationCommand, SourceObligationView, BuySuspensionReplacementIntent } from "../api/generated";
import { createConditionPlanApi, isConditionPlanJson } from "../api/conditionPlans";
import { createAIPlanApi } from "../api/ai";
import { resolveApiFetch } from "../api/context";
import { createPlanApi } from "../api/plans";
import { createPlanReadinessApi } from "../api/planReadiness";
import type { ReadinessBuySuspension } from "../api/generated-runtime-status";
import { ApiClientError } from "../api/transport";
import { usePlanDrafting } from "./usePlanDrafting";
import { usePlanWorkspaceOwner, type WorkspaceOperation } from "./usePlanWorkspaceOwner";
import { useSourceCoverage, type SourceCoverageContext } from "./useSourceCoverage";
import { summaryBinding } from "../components/plans/sourceCoveragePresentation";
import type { Json, Schema } from "../components/plans/planSchema";

export function semanticValues(value: Json, path = ""): Record<string, Json> {
  if (Array.isArray(value)) return value.length ? Object.assign({}, ...value.map((v, i) => semanticValues(v, `${path}[${i}]`))) : { [path]: [] };
  if (value !== null && typeof value === "object") {
    const result: Record<string, Json> = {};
    if (value.type === "ALL" || value.type === "ANY") result[path] = value.type;
    for (const [key, child] of Object.entries(value)) {
      if (!path && ["plan_id", "version", "name", "metadata"].includes(key)) continue;
      Object.assign(result, semanticValues(child, path ? `${path}.${key}` : key));
    }
    return result;
  }
  return value === null ? {} : { [path]: value };
}

/** Compare complete JSON values; this does not recompute a server semantic hash. */
function sameJson(left: unknown, right: unknown): boolean {
  const pending: [unknown, unknown][] = [[left, right]];
  try {
    while (pending.length) {
      const [a, b] = pending.pop()!;
      if (a === null || b === null || typeof a !== "object" || typeof b !== "object") {
        if (typeof a === "number" && !Number.isFinite(a) || typeof b === "number" && !Number.isFinite(b) ||
          !["string", "number", "boolean"].includes(typeof a) && a !== null || !Object.is(a, b)) return false;
        continue;
      }
      if (Array.isArray(a) !== Array.isArray(b)) return false;
      if (!Array.isArray(a) && ![Object.prototype, null].includes(Object.getPrototypeOf(a)) ||
        !Array.isArray(b) && ![Object.prototype, null].includes(Object.getPrototypeOf(b))) return false;
      const keys = Object.keys(a), other = Object.keys(b);
      if (keys.length !== other.length || Array.isArray(a) && a.length !== (b as unknown[]).length) return false;
      for (const key of keys) {
        if (!Object.hasOwn(b, key)) return false;
        pending.push([(a as Record<string, unknown>)[key], (b as Record<string, unknown>)[key]]);
      }
    }
    return true;
  } catch { return false; }
}

export function usePlanWorkspace() {
  const versions = shallowRef<PlanVersionSummary[]>([]);
  const providers = shallowRef<ConfiguredAIRuntimeView[]>([]);
  const extractionId = shallowRef<string | null>(null);
  const extractionStatus = shallowRef("");
  const owner = usePlanWorkspaceOwner();
  const extractionGeneration = shallowRef<number | null>(null);
  const fetcher = resolveApiFetch();
  const drafting = usePlanDrafting({ api: createAIPlanApi(fetcher) });
  const extraction = computed(() => extractionGeneration.value === owner.generation.value &&
    !drafting.submitting.value ? drafting.extraction.value : null);
  const historyOnly = shallowRef(false);
  const dirty = shallowRef(false);
  const candidate = shallowRef<Json>(null);
  const source = shallowRef("");
  const provider = shallowRef<ConfiguredAIRuntimeView | null>(null);
  const fixedSchema = shallowRef<Schema>({});
  const linkedSchema = shallowRef<Schema>({});
  const buySuspensionSchema = shallowRef<Schema>({});
  const pretradeSchema = shallowRef<Schema>({});
  const capitalSchema = shallowRef<Schema>({});
  const exceptionSchema = shallowRef<Schema>({});
  const exceptionDefinitions = shallowRef<Record<string, string>>({});
  const linkedDefinitions = shallowRef<Record<string, string>>({});
  const schema = computed(() => candidate.value !== null && typeof candidate.value === "object" &&
    !Array.isArray(candidate.value) ? candidate.value.schema_version === 10 ? buySuspensionSchema.value : candidate.value.schema_version === 9 ? capitalSchema.value : candidate.value.schema_version === 8 ? pretradeSchema.value : candidate.value.schema_version === 7 ? exceptionSchema.value :
      candidate.value.schema_version === 6 ? linkedSchema.value : fixedSchema.value : fixedSchema.value);
  const mapping = shallowRef<DailyMapping | null>(null);
  const preview = shallowRef<DailyReviewPreview | null>(null);
  const saved = shallowRef<PlanVersionView | null>(null);
  const baseVersion = shallowRef<PlanVersionView | null>(null);
  const activated = shallowRef<ActivePlanView | null>(null);
  const buySuspensionObligations = shallowRef<SourceObligationView[]>([]);
  const buySuspensionPredecessor = shallowRef<ReadinessBuySuspension | null>(null);
  let suspensionBinding = "";
  watch(() => [owner.generation.value, candidate.value, source.value], () => {
    buySuspensionObligations.value = []; buySuspensionPredecessor.value = null; suspensionBinding = "";
  }, { flush: "sync" });
  const busy = owner.busy;
  const error = shallowRef("");
  const notice = shallowRef("");
  const controller = new AbortController();
  const values = computed(() => {
    const result = semanticValues(candidate.value);
    const plan = candidate.value;
    if (plan !== null && typeof plan === "object" && !Array.isArray(plan) && [6, 7, 8, 9].includes(Number(plan.schema_version)) && Array.isArray(plan.ordinary_rules)) {
      plan.ordinary_rules.forEach((rule, i) => {
        if (rule !== null && typeof rule === "object" && !Array.isArray(rule) && "market_policy" in rule) {
          for (const [key, value] of Object.entries([7, 8, 9].includes(Number(plan.schema_version)) ? exceptionDefinitions.value : linkedDefinitions.value)) result[`ordinary_rules[${i}].market_policy.expanded.${key}`] = value;
        }
      });
    }
    return result;
  });
  const definitions = computed(() => schema.value.$defs ?? {});
  onBeforeUnmount(() => { controller.abort(); owner.dispose(); });

  const api = createConditionPlanApi(fetcher, controller.signal);
  const reads = createPlanApi(fetcher);
  const request = api.request;
  function coverageContext(): SourceCoverageContext | null {
    const version = saved.value;
    if (!version || dirty.value || historyOnly.value || !isConditionPlanJson(version.planJson) ||
      source.value !== version.sourceText || !version.sourceHash || !version.contentHash ||
      !version.reviewEvidenceHash || version.reviewRevision == null || !mapping.value ||
      !sameJson(mapping.value, version.dailyMapping)) return null;
    try { if (!sameJson(candidate.value, JSON.parse(version.planJson))) return null; }
    catch { return null; }
    return { planVersionId: version.id, sourceHash: version.sourceHash, candidatePlanHash: version.planHash,
      contentHash: version.contentHash, originalReviewEvidenceHash: version.reviewEvidenceHash,
      reviewId: version.reviewId ?? null, reviewRevision: version.reviewRevision,
      sourceText: source.value, ownerGeneration: owner.generation.value,
      ...(version.sourceCoverage ? { expectedSummary: version.sourceCoverage } : {}) };
  }
  const sourceCoverage = useSourceCoverage(coverageContext, { api: reads });
  function confirmationSnapshot() {
    // Re-read shallow state here: direct nested edits must not borrow a cached proof.
    const context = coverageContext(), version = saved.value, proof = sourceCoverage.currentConfirmation.value;
    const summary = sourceCoverage.summary.value;
    if (!context || !version || version.status !== "DRAFT" || version.reviewId ||
      (version.dailyIssues?.length ?? 0) !== 0 || !proof || !summary || !summary.canConfirmReview ||
      sourceCoverage.verifiedSourceHash.value !== context.sourceHash ||
      summary.sourceHash !== context.sourceHash || summary.candidatePlanHash !== context.candidatePlanHash ||
      summary.contentHash !== context.contentHash || summary.originalReviewEvidenceHash !== context.originalReviewEvidenceHash ||
      summary.reviewId !== context.reviewId || summary.reviewRevision !== context.reviewRevision ||
      context.expectedSummary && summaryBinding(summary) !== summaryBinding(context.expectedSummary)) return null;
    return { version, proof: { ...proof }, binding: JSON.stringify([context, summaryBinding(summary)]) };
  }
  const canConfirmSourceReview = computed(() => confirmationSnapshot() !== null);
  async function refreshSourceCoverage() {
    const initial = coverageContext();
    sourceCoverage.invalidate();
    if (!initial) { notice.value = "当前内容尚未保存或已变化，请先保存并重新核对来源。"; return; }
    const expected = JSON.stringify(initial);
    await action(async operation => {
      const current = await reads.getPlanVersion(initial.planVersionId, { signal: controller.signal });
      if (!owner.current(operation)) return;
      const actual = coverageContext();
      if (!actual || JSON.stringify(actual) !== expected) return;
      if (current.sourceText !== source.value || !sameJson(current.dailyMapping, mapping.value) ||
        !sameJson(JSON.parse(current.planJson), candidate.value)) {
        notice.value = "保存版本已变化，请重新打开该版本后核对；当前编辑内容已保留。";
        return;
      }
      // A fresh native seed triggers one first-page read, including after a stale cursor.
      saved.value = current; baseVersion.value = current;
    });
  }
  let previewSequence = 0;
  const copy = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
  function snapshot() {
    return { candidateJson: JSON.stringify(candidate.value), sourceText: source.value,
      mapping: copy(mapping.value), base: copy(baseVersion.value), version: copy(saved.value),
      extractionId: extractionId.value, historyOnly: historyOnly.value, values: copy(values.value) };
  }
  async function refreshVersions(operation: WorkspaceOperation) {
    const page = await reads.listPlanVersions({ offset: 0, limit: 100 });
    if (owner.current(operation)) versions.value = page.items ?? [];
  }
  async function action(run: (operation: WorkspaceOperation) => Promise<void>) {
    const operation = owner.beginAction();
    if (!operation) return;
    error.value = ""; notice.value = "";
    try { await run(operation); } catch (cause) {
      if (owner.current(operation)) error.value = cause instanceof Error ? cause.message : "操作失败，请查看当前状态后重试";
    } finally { owner.finish(operation); }
  }
  async function load(versionId?: string) {
    const operation = owner.beginLoad();
    if (!operation) return;
    candidate.value = null; source.value = ""; mapping.value = null; preview.value = null;
    saved.value = null; baseVersion.value = null; activated.value = null;
    extractionId.value = null; extractionGeneration.value = null;
    historyOnly.value = false; dirty.value = false;
    error.value = ""; notice.value = "";
    try {
      const loadApi = createConditionPlanApi(fetcher, operation.signal);
      const contract = await loadApi.getEditor();
      if (!owner.current(operation)) return;
      const runtime = await loadApi.getRuntime();
      if (!owner.current(operation)) return;
      const page = await reads.listPlanVersions({ offset: 0, limit: 100 }, { signal: operation.signal });
      if (!owner.current(operation)) return;
      const version = versionId ? await reads.getPlanVersion(versionId, { signal: operation.signal }) : null;
      if (!owner.current(operation)) return;
      const historical = version !== null && !isConditionPlanJson(version.planJson);
      const checked = version && !historical ? await loadApi.preview({ candidateJson: version.planJson,
        sourceText: version.sourceText, mapping: version.dailyMapping ?? null }) : null;
      if (!owner.current(operation)) return;
      const active = version ? await reads.getPlanActivationState(version.symbol, { signal: operation.signal }) : null;
      if (!owner.current(operation)) return;
      fixedSchema.value = contract.candidateSchema;
      linkedSchema.value = contract.linkedCandidateSchema ?? {};
      buySuspensionSchema.value = contract.buySuspensionCandidateSchema ?? {};
      linkedDefinitions.value = contract.linkedPolicyDefinitions ?? {};
      pretradeSchema.value = contract.pretradeCandidateSchema ?? {};
      capitalSchema.value = contract.capitalCandidateSchema ?? {};
      exceptionSchema.value = contract.exceptionCandidateSchema ?? {};
      exceptionDefinitions.value = contract.exceptionPolicyDefinitions ?? {};
      providers.value = [runtime, ...(runtime.alternativeProviders ?? [])];
      provider.value = providers.value.find(p => p.enabled && p.configured) ?? runtime;
      versions.value = page.items ?? [];
      if (version) {
        candidate.value = JSON.parse(checked?.candidateJson ?? version.planJson) as Json;
        source.value = version.sourceText;
        mapping.value = checked?.review.mapping ?? version.dailyMapping ?? null;
        historyOnly.value = historical; preview.value = checked;
        saved.value = version;
        baseVersion.value = version;
        activated.value = active;
      }
    } catch (cause) {
      if (owner.current(operation)) error.value = cause instanceof Error ? cause.message : "无法读取当前计划，请重试";
    } finally { owner.finish(operation); }
  }
  async function openVersion(id: string) {
    if (dirty.value && !window.confirm("当前计划有未保存修改。放弃修改并打开此版本？")) return;
    await load(id);
  }
  function previewSnapshot(body: DailyReviewPreviewCommand) {
    return request<DailyReviewPreview>("/api/v1/plan-review-previews", body);
  }
  function applyPreview(checked: DailyReviewPreview) {
    preview.value = checked; candidate.value = JSON.parse(checked.candidateJson) as Json;
    mapping.value = checked.review.mapping; saved.value = null; activated.value = null;
  }
  async function refreshPreview(operation?: WorkspaceOperation) {
    if (candidate.value === null || controller.signal.aborted) return;
    const generation = owner.generation.value, sequence = ++previewSequence;
    const body = snapshot();
    const checked = await previewSnapshot({ candidateJson: body.candidateJson, sourceText: body.sourceText, mapping: body.mapping });
    if (generation !== owner.generation.value || sequence !== previewSequence || controller.signal.aborted ||
      operation && !owner.current(operation)) return;
    applyPreview(checked);
  }
  function stopWaiting(operationId: string) { drafting.stopWaiting(operationId); }
  async function consumeExtraction(operation: WorkspaceOperation, sourceText: string) {
    if (!owner.current(operation)) return;
    const result = copy(drafting.extraction.value);
    if (drafting.errorMessage.value) throw new Error(drafting.errorMessage.value);
    if (result?.status !== "SUCCEEDED") {
      if (drafting.stoppedMessage.value) { notice.value = drafting.stoppedMessage.value; return; }
      throw new Error("提取未通过校验，未创建可执行计划");
    }
    if (!result.draftPlanJson || !result.dailyMapping) throw new Error("未获得有效计划候选");
    const checked = await previewSnapshot({ candidateJson: result.draftPlanJson, sourceText, mapping: result.dailyMapping });
    if (!owner.current(operation)) return;
    extractionId.value = result.id;
    extractionStatus.value = result.status;
    historyOnly.value = false;
    baseVersion.value = null;
    applyPreview(checked);
    dirty.value = true;
    notice.value = "已提取候选。可编辑日线、5分钟或混合条件，并逐项核对来源。";
  }
  async function extract(command: PlanExtractionCommand) {
    if (busy.value) return;
    const submitted = copy(command);
    owner.invalidate();
    await action(async operation => {
      extractionGeneration.value = null; extractionId.value = null; extractionStatus.value = "";
      source.value = submitted.sourceText; candidate.value = null; mapping.value = null;
      preview.value = null; saved.value = null; baseVersion.value = null; activated.value = null;
      historyOnly.value = false; dirty.value = true;
      const pending = drafting.submitExtraction(submitted);
      const started = drafting.submitting.value;
      // The helper retains its previous receipt until the new POST is accepted.
      if (started) extractionGeneration.value = operation.generation;
      await pending;
      if (started) await consumeExtraction(operation, submitted.sourceText);
    });
  }
  async function retryExtraction() {
    if (extractionGeneration.value !== owner.generation.value) return;
    const sourceText = source.value;
    await action(async operation => { await drafting.retryExtraction(); await consumeExtraction(operation, sourceText); });
  }
  function edit(value: Json) { owner.invalidate(); dirty.value = true; candidate.value = value; preview.value = null; saved.value = null; activated.value = null; }
  function editSource(value: string) {
    if (value === source.value) return;
    owner.invalidate();
    dirty.value = true; source.value = value; extractionId.value = null; mapping.value = null; preview.value = null; saved.value = null; activated.value = null;
    notice.value = "原文已修改，请重新检查来源、保存并审核当前内容。";
  }
  async function exclude(clauseId: string, text: string) {
    await action(async operation => {
      const initial = snapshot();
      const clause = initial.mapping?.clauses.find(c => c.clause_id === clauseId);
      if (!clause || !clause.excerpt.includes(text)) throw new Error("排除范围必须与此句原文完全一致");
      // API spans count Unicode code points, while JavaScript string offsets count UTF-16 units.
      const sourcePoints = Array.from(initial.sourceText);
      const clauseText = sourcePoints.slice(clause.start, clause.end).join("");
      const localOffset = clauseText.indexOf(text);
      if (localOffset < 0 || clauseText !== clause.excerpt) throw new Error("排除范围必须与此句原文完全一致");
      const start = clause.start + Array.from(clauseText.slice(0, localOffset)).length;
      const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(initial.sourceText));
      if (!owner.current(operation)) return;
      const source_hash = Array.from(new Uint8Array(hash), b => b.toString(16).padStart(2, "0")).join("");
      const body = { candidateJson: initial.candidateJson, sourceText: initial.sourceText, mapping: initial.mapping,
        scopeSelections: [{ start, end: start + Array.from(text).length, excerpt: text, source_hash,
          origin: "HUMAN_SCOPE_SELECTION", reason: "FUNDAMENTALS_REVIEWED_AT_PLAN_GENERATION" }] };
      const checked = await request<DailyReviewPreview>("/api/v1/plan-review-previews", body);
      if (!owner.current(operation)) return;
      applyPreview(checked);
      notice.value = "已标注非监控背景；技术余文仍需逐项审核。";
    });
  }
  async function supplement(items: { path: string; reason: string }[], reviewedClauses: { id: string; reason: string; paths: string[] }[]) {
    const requested = copy(items), reviewedItems = copy(reviewedClauses);
    await action(async operation => {
      const initial = snapshot();
      if (initial.candidateJson === "null") return;
      const current = await previewSnapshot({ candidateJson: initial.candidateJson, sourceText: initial.sourceText, mapping: initial.mapping });
      if (!owner.current(operation)) return;
      const currentValues = semanticValues(JSON.parse(current.candidateJson) as Json);
      for (const [path, value] of Object.entries(initial.values)) {
        if (path.includes(".market_policy.expanded.")) currentValues[path] = value;
      }
      const additions: DailySupplement[] = requested.map(item => ({ supplement_id: `human-${crypto.randomUUID()}`,
        candidate_content_hash: current.review.content_hash, path: item.path, value: currentValues[item.path] ?? null, reason: item.reason }));
      const replacementPaths = new Set(additions.map(s => s.path));
      const supplements = [...current.review.mapping.supplements.filter(s => !replacementPaths.has(s.path)), ...additions];
      const command: DailySupplementCommand = { candidateJson: current.candidateJson, contentHash: current.review.content_hash,
        expectedRevision: current.supplementRevision, supplements,
        ...(current.buySuspensionReplacementIntent || supplements.some(s => s.source_hash) ? { sourceText: initial.sourceText } : {}),
        ...(current.buySuspensionReplacementIntent ? { buySuspensionReplacementIntent: current.buySuspensionReplacementIntent } : {}) };
      if (additions.length) await request("/api/v1/plan-review-supplements", command);
      if (!owner.current(operation)) return;
      const clauses = current.review.mapping.clauses.map(c => {
        const reviewed = reviewedItems.find(v => v.id === c.clause_id);
        if (!reviewed || c.disposition === "BACKGROUND") return c;
        return { ...c, disposition: "POLICY" as const, paths: reviewed.paths, reason: reviewed.reason,
          remainders: (c.remainders ?? []).map(r => ({ ...r, disposition: "POLICY" as const, paths: reviewed.paths, reason: reviewed.reason })) };
      });
      const checked = await previewSnapshot({ candidateJson: current.candidateJson, sourceText: initial.sourceText,
        mapping: { ...current.review.mapping, clauses } });
      if (!owner.current(operation)) return;
      applyPreview(checked);
      notice.value = "人工补充已独立登记，请保存候选并查看服务端审核结果。";
    });
  }
  function savedSuspensionContext() {
    const version = saved.value;
    if (!version || dirty.value || historyOnly.value || source.value !== version.sourceText ||
        !sameJson(candidate.value, JSON.parse(version.planJson)) ||
        !sameJson(mapping.value, version.dailyMapping) || !version.contentHash || !version.sourceHash ||
        !candidate.value || typeof candidate.value !== "object" || Array.isArray(candidate.value) || candidate.value.schema_version !== 10) {
      throw new Error("请先保存当前Schema10参数与原文，再读取并登记禁买依据。");
    }
    return version;
  }
  const suspensionKey = (v: PlanVersionView) => JSON.stringify([v.id, v.contentHash, v.sourceHash, v.planHash, owner.generation.value]);
  async function loadBuySuspensionObligations() {
    await action(async operation => {
      const version = savedSuspensionContext(), key = suspensionKey(version);
      buySuspensionObligations.value = []; buySuspensionPredecessor.value = null; suspensionBinding = "";
      const obligations: SourceObligationView[] = [];
      let cursor: string | undefined, binding = "", count = 0;
      const cursors = new Set<string>();
      do {
        const page = await reads.getSourceCoverage(version.id, { limit: 100, ...(cursor ? { cursor } : {}) }, { signal: controller.signal });
        if (!owner.current(operation)) return;
        const summary = page.summary, actualBinding = summaryBinding(summary);
        if (summary.sourceHash !== version.sourceHash || summary.contentHash !== version.contentHash ||
            summary.candidatePlanHash !== version.planHash || binding && binding !== actualBinding ||
            page.items[0]?.rowIndex !== count || count + page.returnedCount > page.totalRows) {
          throw new Error("来源覆盖已变化，请重新打开保存版本并读取全部依据。");
        }
        binding = actualBinding; count += page.returnedCount;
        for (const row of page.items) if (row.kind === "OBLIGATION" && row.obligation.semanticsJson) {
          if (JSON.parse(row.obligation.semanticsJson).treatment === "PERSISTENT_BUY_SUSPENSION") obligations.push(row.obligation);
        }
        cursor = page.nextCursor ?? undefined;
        if (cursor && cursors.has(cursor)) throw new Error("来源分页未推进，不能登记澄清。");
        if (cursor) cursors.add(cursor);
      } while (cursor && count <= 14288);
      if (cursor || key !== suspensionKey(savedSuspensionContext())) throw new Error("来源依据未完整读取。");
      const active = await reads.getPlanActivationState(version.symbol);
      if (!owner.current(operation)) return;
      activated.value = active;
      if (active.active && active.planVersionId && active.planVersionId !== version.id) {
        const prior = await createPlanReadinessApi(fetcher).get(active.planVersionId, controller.signal);
        if (!owner.current(operation)) return;
        buySuspensionPredecessor.value = prior.snapshot.buySuspension ?? null;
      }
      buySuspensionObligations.value = obligations; suspensionBinding = key;
      notice.value = "已读取完整原文义务及当前启用状态；登记不代表审核或启用。";
    });
  }
  async function registerSuspension(operation: WorkspaceOperation, additions: DailySupplement[], intent?: BuySuspensionReplacementIntent) {
    const version = savedSuspensionContext(), initial = snapshot();
    const current = await previewSnapshot({ candidateJson: initial.candidateJson, sourceText: initial.sourceText, mapping: initial.mapping });
    if (!owner.current(operation)) return;
    if (current.review.content_hash !== version.contentHash || current.review.source_hash !== version.sourceHash) throw new Error("当前来源或参数已变化，请重新保存。");
    const paths = new Set(additions.map(s => s.path));
    const command: DailySupplementCommand = { candidateJson: current.candidateJson, contentHash: current.review.content_hash,
      sourceText: initial.sourceText, expectedRevision: current.supplementRevision,
      supplements: [...current.review.mapping.supplements.filter(s => !paths.has(s.path)), ...additions],
      ...(intent ? { buySuspensionReplacementIntent: intent } : current.buySuspensionReplacementIntent ? { buySuspensionReplacementIntent: current.buySuspensionReplacementIntent } : {}) };
    await request("/api/v1/plan-review-supplements", command);
    if (!owner.current(operation)) return;
    const checked = await previewSnapshot({ candidateJson: current.candidateJson, sourceText: initial.sourceText, mapping: current.review.mapping });
    if (!owner.current(operation)) return;
    applyPreview(checked); dirty.value = true;
    notice.value = "禁买依据已独立登记；请保存新版本，解决其他原文义务，再独立审核并明确启用。";
  }
  async function registerBuySuspensionClarification(obligationId: string, reason: string) {
    await action(async operation => {
      const version = savedSuspensionContext();
      const obligation = buySuspensionObligations.value.find(o => o.obligationId === obligationId && o.sourceHash === version.sourceHash);
      if (!obligation || suspensionBinding !== suspensionKey(version) || reason.trim().length < 20) throw new Error("请读取全部来源义务，选择本原文的禁买义务并填写具体澄清理由。");
      const paths = ["buy_suspension.condition.type", "buy_suspension.condition.timeframe_minutes", "buy_suspension.condition.price_fen", "buy_suspension.effective_from"];
      if (paths.some(path => values.value[path] == null)) throw new Error("保护条件缺少明确参数或核查起点，请先补全并保存；确认不能代替缺失定义。");
      const additions: DailySupplement[] = paths.map(path => ({ supplement_id: `human-${crypto.randomUUID()}`,
        candidate_content_hash: version.contentHash!, path, value: values.value[path]!, reason: reason.trim(),
        source_hash: version.sourceHash!, obligation_id: obligation.obligationId,
        buy_suspension_clarification: "ALL_PLAN_BUY_REVIEWED_REPLACEMENT_ONLY" }));
      await registerSuspension(operation, additions);
    });
  }
  async function registerBuySuspensionReplacement(input: { excerpt: string; reason: string; strategyStart: string; retire: boolean; acknowledge: boolean }) {
    const submitted = copy(input);
    await action(async operation => {
      const version = savedSuspensionContext(), text = source.value, offset = text.indexOf(submitted.excerpt);
      if (suspensionBinding !== suspensionKey(version) || !submitted.excerpt || offset < 0 || text.indexOf(submitted.excerpt, offset + 1) >= 0 ||
          submitted.reason.trim().length < 20 || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+08:00$/.test(submitted.strategyStart) || !Number.isFinite(Date.parse(submitted.strategyStart))) {
        throw new Error("请先读取当前依据，填写唯一、完整的新原文接替声明、具体理由及明确+08:00策略起点。");
      }
      if (submitted.acknowledge && buySuspensionPredecessor.value?.outcome !== "UNVERIFIED") throw new Error("尚无可核对的前序未核实区间，不能声明已经确认该区间。");
      const start = Array.from(text.slice(0, offset)).length;
      await registerSuspension(operation, [], { source_hash: version.sourceHash!, candidate_content_hash: version.contentHash!,
        source_start: start, source_end: start + Array.from(submitted.excerpt).length, excerpt: submitted.excerpt,
        replacement_reason: submitted.reason.trim(), retire_predecessor_guard: submitted.retire,
        acknowledge_unverified_predecessor: submitted.acknowledge, strategy_effective_from: submitted.strategyStart, authority_granted: false });
    });
  }
  async function save() {
    await action(async operation => {
      const body = snapshot();
      if (body.historyOnly) throw new Error("历史计划只能查看，请从原文重新提取并审核");
      if (body.candidateJson === "null" || !body.mapping) throw new Error("先检查候选参数和来源");
      let raw = JSON.parse(body.candidateJson) as Record<string, Json>;
      const base = body.base;
      if (base && raw.plan_id === base.planId && typeof raw.version === "number" && raw.version <= base.version) {
        raw = { ...raw, version: base.version + 1 };
      }
      const state = await reads.getPlanActivationState(String(raw.symbol));
      if (!owner.current(operation)) return;
      const result = await request<PlanVersionView>("/api/v1/plan-drafts", { planJson: JSON.stringify(raw), sourceText: body.sourceText,
        dailyMapping: body.mapping, expectedRevision: state.revision, extractionId: body.extractionId, basePlanVersionId: base?.id ?? null });
      if (!owner.current(operation)) return;
      candidate.value = JSON.parse(result.planJson) as Json;
      saved.value = result; baseVersion.value = result; activated.value = state;
      dirty.value = false;
      await refreshVersions(operation);
      if (owner.current(operation)) notice.value = "候选已保存。审核与启用是两次独立操作。";
    });
  }
  async function confirm() {
    const initial = confirmationSnapshot();
    if (!initial) {
      sourceCoverage.invalidate(); notice.value = "当前来源证明不可确认，请重新读取并核对当前版本。"; return;
    }
    await action(async operation => {
      const actual = confirmationSnapshot();
      if (!actual || actual.binding !== initial.binding) { sourceCoverage.invalidate(); return; }
      const version = initial.version;
      const body: PlanReviewConfirmationCommand = { planVersionId: version.id, contentHash: version.contentHash!,
        sourceHash: version.sourceHash!, reviewEvidenceHash: version.reviewEvidenceHash!, expectedRevision: version.reviewRevision!,
        resolutions: [], ...initial.proof };
      try { await request("/api/v1/plan-review-confirmations", body); }
      catch (cause) {
        if (owner.current(operation) && cause instanceof ApiClientError && cause.status === 409) {
          sourceCoverage.invalidate(); throw new Error("审核依据已变化，请重新读取来源核对结果，再明确确认。");
        }
        throw cause;
      }
      if (!owner.current(operation)) return;
      const current = await reads.getPlanVersion(version.id);
      if (!owner.current(operation)) return;
      saved.value = current;
      notice.value = "当前版本已审核。可另行启用绑定。";
    });
  }
  async function activate() {
    await action(async operation => {
      const initial = snapshot(), version = initial.version;
      if (version?.status !== "DRAFT" || !version.canActivate || initial.historyOnly || dirty.value) return;
      const state = await reads.getPlanActivationState(version.symbol);
      if (!owner.current(operation)) return;
      const result = await request<ActivePlanView>("/api/v1/plan-activations", { planVersionId: version.id,
        contentHash: version.contentHash, sourceHash: version.sourceHash, reviewEvidenceHash: version.reviewEvidenceHash,
        reviewRevision: version.reviewRevision, reviewId: version.reviewId, expectedRevision: state.revision });
      if (!owner.current(operation)) return;
      const current = await reads.getPlanVersion(version.id);
      if (!owner.current(operation)) return;
      activated.value = result; saved.value = current;
      await refreshVersions(operation);
      if (owner.current(operation)) notice.value = "计划已启用，各规则按审核后的条件、确认方式和窗口监控。";
    });
  }
  async function deactivate() {
    await action(async operation => {
      const initial = snapshot(), version = initial.version;
      if (!version || initial.historyOnly) return;
      const state = await reads.getPlanActivationState(version.symbol);
      if (!owner.current(operation)) return;
      if (!state.active || state.planVersionId !== version.id) {
        activated.value = state;
        throw new Error("当前版本已不再启用，请刷新版本状态");
      }
      const result = await request<ActivePlanView>("/api/v1/plan-deactivations", {
        symbol: version.symbol, expectedRevision: state.revision,
      });
      if (!owner.current(operation)) return;
      const current = await reads.getPlanVersion(version.id);
      if (!owner.current(operation)) return;
      activated.value = result; saved.value = current;
      await refreshVersions(operation);
      if (owner.current(operation)) notice.value = "当前计划已停用，后续提醒和模拟操作不再基于此版本。";
    });
  }
  return { extraction, retryExtraction, stopWaiting, versions, providers, historyOnly, dirty, extractionStatus, openVersion, candidate, source, provider, schema, definitions, mapping, preview, saved, activated, busy, error, notice,
    ownerGeneration: owner.generation, sourceCoverage, canConfirmSourceReview, refreshSourceCoverage,
    buySuspensionObligations, buySuspensionPredecessor, loadBuySuspensionObligations, registerBuySuspensionClarification, registerBuySuspensionReplacement,
    values, request, action, load, extract, edit, editSource, refreshPreview, exclude, supplement, save, confirm, activate, deactivate };
}
