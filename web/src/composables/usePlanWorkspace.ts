import { computed, onBeforeUnmount, shallowRef } from "vue";
import type { ActivePlanView, ConfiguredAIRuntimeView, DailyMapping, DailyReviewPreview, DailySupplement,
  PlanExtractionCommand, PlanVersionView, PlanVersionPage, PlanVersionSummary, DailyReviewPreviewCommand, DailySupplementCommand } from "../api/generated";
import { createConditionPlanApi, isConditionPlanJson } from "../api/conditionPlans";
import type { PlanEditorContract } from "../api/conditionPlans";
import { createAIPlanApi } from "../api/ai";
import { resolveApiFetch } from "../api/context";
import { usePlanDrafting } from "./usePlanDrafting";
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

export function usePlanWorkspace() {
  const versions = shallowRef<PlanVersionSummary[]>([]);
  const providers = shallowRef<ConfiguredAIRuntimeView[]>([]);
  const extractionId = shallowRef<string | null>(null);
  const extractionStatus = shallowRef("");
  const drafting = usePlanDrafting({ api: createAIPlanApi(resolveApiFetch()) });
  const extraction = drafting.extraction;
  const historyOnly = shallowRef(false);
  const dirty = shallowRef(false);
  const candidate = shallowRef<Json>(null);
  const source = shallowRef("");
  const provider = shallowRef<ConfiguredAIRuntimeView | null>(null);
  const fixedSchema = shallowRef<Schema>({});
  const linkedSchema = shallowRef<Schema>({});
  const exceptionSchema = shallowRef<Schema>({});
  const exceptionDefinitions = shallowRef<Record<string, string>>({});
  const linkedDefinitions = shallowRef<Record<string, string>>({});
  const schema = computed(() => candidate.value !== null && typeof candidate.value === "object" &&
    !Array.isArray(candidate.value) ? candidate.value.schema_version === 7 ? exceptionSchema.value :
      candidate.value.schema_version === 6 ? linkedSchema.value : fixedSchema.value : fixedSchema.value);
  const mapping = shallowRef<DailyMapping | null>(null);
  const preview = shallowRef<DailyReviewPreview | null>(null);
  const saved = shallowRef<PlanVersionView | null>(null);
  const baseVersion = shallowRef<PlanVersionView | null>(null);
  const activated = shallowRef<ActivePlanView | null>(null);
  const busy = shallowRef(false);
  const error = shallowRef("");
  const notice = shallowRef("");
  const controller = new AbortController();
  const values = computed(() => {
    const result = semanticValues(candidate.value);
    const plan = candidate.value;
    if (plan !== null && typeof plan === "object" && !Array.isArray(plan) && [6, 7].includes(Number(plan.schema_version)) && Array.isArray(plan.ordinary_rules)) {
      plan.ordinary_rules.forEach((rule, i) => {
        if (rule !== null && typeof rule === "object" && !Array.isArray(rule) && "market_policy" in rule) {
          for (const [key, value] of Object.entries(plan.schema_version === 7 ? exceptionDefinitions.value : linkedDefinitions.value)) result[`ordinary_rules[${i}].market_policy.expanded.${key}`] = value;
        }
      });
    }
    return result;
  });
  const definitions = computed(() => schema.value.$defs ?? {});
  onBeforeUnmount(() => controller.abort());

  const api = createConditionPlanApi(undefined, controller.signal);
  const request = api.request;
  async function refreshVersions() {
    const page = await request<PlanVersionPage>("/api/v1/plan-versions?offset=0&limit=100");
    versions.value = page.items ?? [];
  }
  async function action(run: () => Promise<void>) {
    if (busy.value) return;
    busy.value = true; error.value = ""; notice.value = "";
    try { await run(); } catch (cause) { error.value = cause instanceof Error ? cause.message : "操作失败，请查看当前状态后重试"; }
    finally { busy.value = false; }
  }
  async function load(versionId?: string) {
    await action(async () => {
      const contract = await request<PlanEditorContract>("/api/v1/plan-editor-schema");
      fixedSchema.value = contract.candidateSchema;
      linkedSchema.value = contract.linkedCandidateSchema ?? {};
      linkedDefinitions.value = contract.linkedPolicyDefinitions ?? {};
      exceptionSchema.value = contract.exceptionCandidateSchema ?? {};
      exceptionDefinitions.value = contract.exceptionPolicyDefinitions ?? {};
      const runtime = await api.getRuntime();
      providers.value = [runtime, ...(runtime.alternativeProviders ?? [])];
      provider.value = providers.value.find(p => p.enabled && p.configured) ?? runtime;
      await refreshVersions();
      if (versionId) {
        const version = await request<PlanVersionView>(`/api/v1/plan-versions/${encodeURIComponent(versionId)}`);
        candidate.value = JSON.parse(version.planJson) as Json;
        source.value = version.sourceText;
        mapping.value = version.dailyMapping ?? null;
        historyOnly.value = !isConditionPlanJson(version.planJson);
        if (!historyOnly.value) await refreshPreview();
        dirty.value = false;
        saved.value = version;
        baseVersion.value = version;
        activated.value = await request<ActivePlanView>(`/api/v1/plan-activation-states/${encodeURIComponent(version.symbol)}`);
      }
    });
  }
  async function openVersion(id: string) {
    if (dirty.value && !window.confirm("当前计划有未保存修改。放弃修改并打开此版本？")) return;
    await load(id);
  }
  async function refreshPreview() {
    if (candidate.value === null) return;
    const body: DailyReviewPreviewCommand = { candidateJson: JSON.stringify(candidate.value), sourceText: source.value, mapping: mapping.value };
    preview.value = await request<DailyReviewPreview>("/api/v1/plan-review-previews", body);
    candidate.value = JSON.parse(preview.value.candidateJson) as Json;
    mapping.value = preview.value.review.mapping;
    saved.value = null; activated.value = null;
  }
  function stopWaiting(operationId: string) { drafting.stopWaiting(operationId); }
  async function consumeExtraction() {
    const result = drafting.extraction.value;
    if (drafting.errorMessage.value) throw new Error(drafting.errorMessage.value);
    if (result?.status !== "SUCCEEDED") {
      if (drafting.stoppedMessage.value) { notice.value = drafting.stoppedMessage.value; return; }
      throw new Error("提取未通过校验，未创建可执行计划");
    }
    if (!result.draftPlanJson || !result.dailyMapping) throw new Error("未获得有效计划候选");
    extractionId.value = result.id;
    extractionStatus.value = result.status;
    historyOnly.value = false;
    baseVersion.value = null;
    candidate.value = JSON.parse(result.draftPlanJson) as Json;
    mapping.value = result.dailyMapping;
    dirty.value = true;
    await refreshPreview();
    notice.value = "已提取候选。可编辑日线、5分钟或混合条件，并逐项核对来源。";
  }
  async function extract(command: PlanExtractionCommand) {
    await action(async () => {
      source.value = command.sourceText;
      await drafting.submitExtraction(command);
      await consumeExtraction();
    });
  }
  async function retryExtraction() {
    await action(async () => { await drafting.retryExtraction(); await consumeExtraction(); });
  }
  function edit(value: Json) { dirty.value = true; candidate.value = value; preview.value = null; saved.value = null; activated.value = null; }
  function editSource(value: string) {
    if (value === source.value) return;
    dirty.value = true; source.value = value; extractionId.value = null; mapping.value = null; preview.value = null; saved.value = null; activated.value = null;
    notice.value = "原文已修改，请重新检查来源、保存并审核当前内容。";
  }
  async function exclude(clauseId: string, text: string) {
    await action(async () => {
      const clause = mapping.value?.clauses.find(c => c.clause_id === clauseId);
      if (!clause || !clause.excerpt.includes(text)) throw new Error("排除范围必须与此句原文完全一致");
      // API spans count Unicode code points, while JavaScript string offsets count UTF-16 units.
      const sourcePoints = Array.from(source.value);
      const localOffset = sourcePoints.slice(clause.start, clause.end).join("").indexOf(text);
      const clauseText = sourcePoints.slice(clause.start, clause.end).join("");
      const start = clause.start + Array.from(clauseText.slice(0, localOffset)).length;
      const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(source.value));
      const source_hash = Array.from(new Uint8Array(hash), b => b.toString(16).padStart(2, "0")).join("");
      const body = { candidateJson: JSON.stringify(candidate.value), sourceText: source.value, mapping: mapping.value,
        scopeSelections: [{ start, end: start + Array.from(text).length, excerpt: text, source_hash,
          origin: "HUMAN_SCOPE_SELECTION", reason: "FUNDAMENTALS_REVIEWED_AT_PLAN_GENERATION" }] };
      preview.value = await request<DailyReviewPreview>("/api/v1/plan-review-previews", body);
      mapping.value = preview.value.review.mapping; saved.value = null; activated.value = null;
      notice.value = "已标注非监控背景；技术余文仍需逐项审核。";
    });
  }
  async function supplement(items: { path: string; reason: string }[], reviewedClauses: { id: string; reason: string; paths: string[] }[]) {
    await action(async () => {
      await refreshPreview();
      const current = preview.value;
      if (!current) return;
      const additions: DailySupplement[] = items.map(item => ({ supplement_id: `human-${crypto.randomUUID()}`,
        candidate_content_hash: current.review.content_hash, path: item.path, value: values.value[item.path] ?? null, reason: item.reason }));
      const replacementPaths = new Set(additions.map(s => s.path));
      const supplements = [...current.review.mapping.supplements.filter(s => !replacementPaths.has(s.path)), ...additions];
      const command: DailySupplementCommand = { candidateJson: current.candidateJson, contentHash: current.review.content_hash,
        expectedRevision: current.supplementRevision, supplements };
      if (additions.length) await request("/api/v1/plan-review-supplements", command);
      const clauses = current.review.mapping.clauses.map(c => {
        const reviewed = reviewedClauses.find(v => v.id === c.clause_id);
        if (!reviewed || c.disposition === "BACKGROUND") return c;
        return { ...c, disposition: "POLICY" as const, paths: reviewed.paths, reason: reviewed.reason,
          remainders: (c.remainders ?? []).map(r => ({ ...r, disposition: "POLICY" as const, paths: reviewed.paths, reason: reviewed.reason })) };
      });
      mapping.value = { ...current.review.mapping, clauses };
      await refreshPreview();
      notice.value = "人工补充已独立登记，请保存候选并查看服务端审核结果。";
    });
  }
  async function save() {
    await action(async () => {
      if (historyOnly.value) throw new Error("历史计划只能查看，请从原文重新提取并审核");
      if (!candidate.value || !mapping.value) throw new Error("先检查候选参数和来源");
      let raw = candidate.value as Record<string, Json>;
      const base = baseVersion.value;
      if (base && raw.plan_id === base.planId && typeof raw.version === "number" && raw.version <= base.version) {
        raw = { ...raw, version: base.version + 1 };
        candidate.value = raw;
      }
      const state = await request<ActivePlanView>(`/api/v1/plan-activation-states/${encodeURIComponent(String(raw.symbol))}`);
      saved.value = await request<PlanVersionView>("/api/v1/plan-drafts", { planJson: JSON.stringify(candidate.value), sourceText: source.value,
        dailyMapping: mapping.value, expectedRevision: state.revision, extractionId: extractionId.value, basePlanVersionId: base?.id ?? null });
      baseVersion.value = saved.value;
      dirty.value = false;
      await refreshVersions();
      notice.value = "候选已保存。审核与启用是两次独立操作。";
    });
  }
  async function confirm() {
    await action(async () => {
      const version = saved.value;
      if (!version) return;
      await request("/api/v1/plan-review-confirmations", { planVersionId: version.id, contentHash: version.contentHash,
        sourceHash: version.sourceHash, reviewEvidenceHash: version.reviewEvidenceHash, expectedRevision: version.reviewRevision, resolutions: [] });
      saved.value = await request<PlanVersionView>(`/api/v1/plan-versions/${version.id}`);
      notice.value = "当前版本已审核。可另行启用绑定。";
    });
  }
  async function activate() {
    await action(async () => {
      const version = saved.value;
      if (version?.status !== "DRAFT" || !version.canActivate || historyOnly.value || dirty.value) return;
      const state = await request<ActivePlanView>(`/api/v1/plan-activation-states/${version.symbol}`);
      activated.value = await request<ActivePlanView>("/api/v1/plan-activations", { planVersionId: version.id,
        contentHash: version.contentHash, sourceHash: version.sourceHash, reviewEvidenceHash: version.reviewEvidenceHash,
        reviewRevision: version.reviewRevision, reviewId: version.reviewId, expectedRevision: state.revision });
      saved.value = await api.getVersion(version.id);
      await refreshVersions();
      notice.value = "计划已启用，各规则按审核后的条件、确认方式和窗口监控。";
    });
  }
  async function deactivate() {
    await action(async () => {
      const version = saved.value;
      if (!version || historyOnly.value) return;
      const state = await request<ActivePlanView>(`/api/v1/plan-activation-states/${encodeURIComponent(version.symbol)}`);
      if (!state.active || state.planVersionId !== version.id) {
        activated.value = state;
        throw new Error("当前版本已不再启用，请刷新版本状态");
      }
      activated.value = await request<ActivePlanView>("/api/v1/plan-deactivations", {
        symbol: version.symbol, expectedRevision: state.revision,
      });
      saved.value = await api.getVersion(version.id);
      await refreshVersions();
      notice.value = "当前计划已停用，后续提醒和模拟操作不再基于此版本。";
    });
  }
  return { extraction, retryExtraction, stopWaiting, versions, providers, historyOnly, dirty, extractionStatus, openVersion, candidate, source, provider, schema, definitions, mapping, preview, saved, activated, busy, error, notice,
    values, request, action, load, extract, edit, editSource, refreshPreview, exclude, supplement, save, confirm, activate, deactivate };
}
