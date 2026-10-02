import { computed, onBeforeUnmount, shallowRef } from "vue";
import type { ActivePlanView, ConfiguredAIRuntimeView, DailyMapping, DailyReviewPreview, DailySupplement,
  PlanExtractionView, PlanVersionView, DailyReviewPreviewCommand, DailySupplementCommand } from "../api/generated";
import { requestJson, invalidResponse } from "../api/transport";
import { resolveApiFetch } from "../api/context";
import type { Json, Schema } from "../components/daily/schema";

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

export function useDailyWorkbench() {
  const fetcher = resolveApiFetch();
  const candidate = shallowRef<Json>(null);
  const source = shallowRef("");
  const provider = shallowRef<ConfiguredAIRuntimeView | null>(null);
  const schema = shallowRef<Schema>({});
  const mapping = shallowRef<DailyMapping | null>(null);
  const preview = shallowRef<DailyReviewPreview | null>(null);
  const saved = shallowRef<PlanVersionView | null>(null);
  const baseVersion = shallowRef<PlanVersionView | null>(null);
  const activated = shallowRef<ActivePlanView | null>(null);
  const busy = shallowRef(false);
  const error = shallowRef("");
  const notice = shallowRef("");
  const controller = new AbortController();
  const values = computed(() => semanticValues(candidate.value));
  const definitions = computed(() => schema.value.$defs ?? {});
  onBeforeUnmount(() => controller.abort());

  async function request<T>(url: string, body?: object, key: string = crypto.randomUUID()): Promise<T> {
    const response = await requestJson(fetcher, url, { method: body ? "POST" : "GET", signal: controller.signal,
      headers: body ? { "Content-Type": "application/json", "Idempotency-Key": key } : {},
      ...(body ? { body: JSON.stringify(body) } : {}) });
    if (response.body === null || typeof response.body !== "object" || Array.isArray(response.body)) throw invalidResponse(response.status);
    return response.body as T;
  }
  async function action(run: () => Promise<void>) {
    if (busy.value) return;
    busy.value = true; error.value = ""; notice.value = "";
    try { await run(); } catch (cause) { error.value = cause instanceof Error ? cause.message : "操作失败，请查看当前状态后重试"; }
    finally { busy.value = false; }
  }
  async function load(versionId?: string) {
    await action(async () => {
      const contract = await request<{ candidateSchema: Schema }>("/api/v1/daily-plan-editor-schema");
      schema.value = contract.candidateSchema;
      provider.value = await request<ConfiguredAIRuntimeView>("/api/v1/ai-runtime");
      if (versionId) {
        const version = await request<PlanVersionView>(`/api/v1/plan-versions/${encodeURIComponent(versionId)}`);
        candidate.value = JSON.parse(version.planJson) as Json;
        source.value = version.sourceText;
        mapping.value = version.dailyMapping ?? null;
        await refreshPreview();
        saved.value = version;
        baseVersion.value = version;
      }
    });
  }
  async function refreshPreview() {
    if (candidate.value === null) return;
    const body: DailyReviewPreviewCommand = { candidateJson: JSON.stringify(candidate.value), sourceText: source.value, mapping: mapping.value };
    preview.value = await request<DailyReviewPreview>("/api/v1/daily-plan-review-previews", body);
    candidate.value = JSON.parse(preview.value.candidateJson) as Json;
    mapping.value = preview.value.review.mapping;
    saved.value = null; activated.value = null;
  }
  async function extract() {
    await action(async () => {
      if (!provider.value?.providerId || !source.value.trim()) throw new Error("请先选择已配置AI并填写原文");
      const receipt = await request<{ operationId: string }>("/api/v1/plan-extractions", {
        providerId: provider.value.providerId, sourceText: source.value, expectedRevision: 0, targetContract: "DAILY_CLOSE_PLAN" });
      for (let count = 0; count < 240 && !controller.signal.aborted; count++) {
        const result = await request<PlanExtractionView>(`/api/v1/plan-extractions/${receipt.operationId}`);
        if (result.status === "SUCCEEDED") {
          if (!result.draftPlanJson || !result.dailyMapping) throw new Error("未获得有效日线候选");
          candidate.value = JSON.parse(result.draftPlanJson) as Json; mapping.value = result.dailyMapping;
          await refreshPreview(); notice.value = "已提取候选。逐项填写缺失定义并单独登记人工补充。"; return;
        }
        if (!["QUEUED", "RUNNING"].includes(result.status)) throw new Error("提取未通过校验，未创建可执行计划");
        await new Promise(resolve => setTimeout(resolve, 500));
      }
      throw new Error("本次等待已结束，请保留原文并查看操作状态");
    });
  }
  function edit(value: Json) { candidate.value = value; preview.value = null; saved.value = null; activated.value = null; }
  function editSource(value: string) {
    if (value === source.value) return;
    source.value = value; mapping.value = null; preview.value = null; saved.value = null; activated.value = null;
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
      preview.value = await request<DailyReviewPreview>("/api/v1/daily-plan-review-previews", body);
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
      if (additions.length) await request("/api/v1/daily-plan-review-supplements", command);
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
      if (!candidate.value || !mapping.value) throw new Error("先检查候选参数和来源");
      let raw = candidate.value as Record<string, Json>;
      const base = baseVersion.value;
      if (base && raw.plan_id === base.planId && typeof raw.version === "number" && raw.version <= base.version) {
        raw = { ...raw, version: base.version + 1 };
        candidate.value = raw;
      }
      const state = await request<ActivePlanView>(`/api/v1/plan-activation-states/${encodeURIComponent(String(raw.symbol))}`);
      saved.value = await request<PlanVersionView>("/api/v1/plan-drafts", { planJson: JSON.stringify(candidate.value), sourceText: source.value,
        dailyMapping: mapping.value, expectedRevision: state.revision, extractionId: null, basePlanVersionId: null });
      baseVersion.value = saved.value;
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
      if (!version?.canActivate) return;
      const state = await request<ActivePlanView>(`/api/v1/plan-activation-states/${version.symbol}`);
      activated.value = await request<ActivePlanView>("/api/v1/plan-activations", { planVersionId: version.id,
        contentHash: version.contentHash, sourceHash: version.sourceHash, reviewEvidenceHash: version.reviewEvidenceHash,
        reviewRevision: version.reviewRevision, reviewId: version.reviewId, expectedRevision: state.revision });
      notice.value = "日线计划已启用，收盘确认后按下一交易日窗口提醒。";
    });
  }
  return { candidate, source, provider, schema, definitions, mapping, preview, saved, activated, busy, error, notice,
    values, request, action, load, extract, edit, editSource, refreshPreview, exclude, supplement, save, confirm, activate };
}
