<script setup lang="ts">
import { onBeforeUnmount, shallowRef, useTemplateRef, watch, type DeepReadonly } from "vue";
import type { PlanChange, ReviewedPlanLibraryItem, MarketExceptionPlanDraft, MarketLinkedPlanDraft, UnifiedPlanDraft } from "../../api/generated-runtime-status";
import { createPreparationApi, type PreparationApi } from "../../api/preparations";
import PlanRuleChanges from "./PlanRuleChanges.vue";

const props = defineProps<{
  item: DeepReadonly<ReviewedPlanLibraryItem>; predecessor: string;
  api?: Pick<PreparationApi, "get" | "items">;
}>();
const api = props.api ?? createPreparationApi();
const details = useTemplateRef<HTMLDetailsElement>("details");
const loading = shallowRef(false);
const error = shallowRef(false);
const content = shallowRef<{ draft: DeepReadonly<UnifiedPlanDraft | MarketLinkedPlanDraft | MarketExceptionPlanDraft> | null; referenceDraft: DeepReadonly<UnifiedPlanDraft | MarketLinkedPlanDraft | MarketExceptionPlanDraft> | null; changes: readonly PlanChange[] } | null>(null);
let controller: AbortController | null = null;
let generation = 0;
function reset() { generation++; controller?.abort(); content.value = null; error.value = false; loading.value = false; }
watch([() => props.item.preparationId, () => props.item.manifestHash, () => props.item.sourceId], () => {
  reset(); if (details.value?.open) void load();
});
onBeforeUnmount(reset);
async function load() {
  if (loading.value || content.value) return;
  const item = props.item, request = new AbortController(), current = ++generation;
  controller = request; loading.value = true; error.value = false;
  try {
    const { body } = await api.get(item.preparationId, { signal: request.signal });
    if (current !== generation) return;
    if (!("items" in body) || body.workflow !== "SINGLE" || body.status !== "REVIEWED" ||
        body.preparationId !== item.preparationId || body.frozen?.manifestHash !== item.manifestHash) throw new Error("Plan changed");
    const version = body.frozen.versions.at(-1);
    const offset = body.items.findIndex(value => value.sourceId === item.sourceId);
    if (!version || version.sourceId !== item.sourceId || version.effectiveTradeDate !== item.effectiveTradeDate ||
        item.identity && version.planHash !== item.identity.planHash || offset < 0 || !api.items) throw new Error("Plan unavailable");
    const page = await api.items(item.preparationId, { expectedRevision: body.revision, offset, limit: 1 }, { signal: request.signal });
    if (current !== generation) return;
    const detail = page.items[0], candidate = detail?.candidate, summary = body.items[offset]!;
    const reviewedInitialAccount = candidate?.kind === "INITIAL" && candidate.validation === "UNRESOLVED" &&
      candidate.issues.length === 1 && candidate.issues[0] === "LOOP_ACCOUNT_FACT_REQUIRED: opening_account.cash_fen";
    if (page.preparationId !== item.preparationId || page.revision !== body.revision || page.items.length !== 1 ||
        detail?.sourceId !== item.sourceId || detail.effectiveTradeDate !== item.effectiveTradeDate || detail.sourceRevision !== version.sourceRevision ||
        detail.candidateRevision !== version.candidateRevision || !candidate ||
        detail.sourceRevision !== summary.sourceRevision || detail.candidateRevision !== summary.candidateRevision ||
        detail.baseHash !== summary.baseHash || detail.candidateHash !== summary.candidateHash || detail.evidenceHash !== summary.evidenceHash ||
        candidate.candidateHash !== summary.candidateHash || candidate.evidenceHash !== summary.evidenceHash ||
        candidate.kind !== "INITIAL" && candidate.evidenceHash !== version.evidenceHash ||
        candidate.validation !== "VALID" && !reviewedInitialAccount) throw new Error("Plan changed");
    const approvedDraft = candidate.review?.draft ?? candidate.draft ?? null;
    content.value = { draft: item.reviewedBase ? null : approvedDraft, referenceDraft: approvedDraft,
      changes: candidate.review?.changes ?? [] };
  } catch { if (current === generation) error.value = true; }
  finally { if (current === generation) loading.value = false; }
}
function toggle(event: Event) { if ((event.target as HTMLDetailsElement).open) void load(); }
</script>

<template>
  <details ref="details" @toggle="toggle">
    <summary>查看计划及本次调整</summary>
    <dl><dt>计划日期</dt><dd>{{ item.effectiveTradeDate }}</dd>
      <dt>所属股票</dt><dd>{{ item.name }}（{{ item.symbol }}）</dd>
      <dt>前序关系</dt><dd>{{ predecessor }}</dd></dl>
    <p v-if="loading" role="status">正在读取已审核交易条件…</p>
    <div v-else-if="error" role="alert"><p>暂时无法核对这份计划的交易条件，请重试或查看已审核原文。</p>
      <button type="button" @click="load">重试读取交易条件</button></div>
    <PlanRuleChanges v-else-if="content && (content.draft || content.changes.length)" :initial-draft="content.draft" :reference-draft="content.referenceDraft" :changes="content.changes" business-mode />
    <p v-else-if="content">这份历史计划未记录逐项变化，请查看已审核原文与交易条件。</p>
    <a :href="`/backtests/new?preparationId=${encodeURIComponent(item.preparationId)}&inspect=1`" target="_blank" rel="noopener">查看已审核原文与交易条件（只读，新页面）</a>
  </details>
</template>

<style scoped>
details { min-width: 0; margin-top: var(--space-2); overflow-wrap: anywhere; }
summary { cursor: pointer; padding-block: var(--space-2); }
summary:focus-visible { outline: .1875rem solid var(--color-focus-ring); }
dl { margin-block: var(--space-2); }
dd { margin-inline-start: 0; margin-block-end: var(--space-2); }
button { min-height: 2.75rem; max-width: 100%; padding: var(--space-2); color: inherit; background: var(--color-surface-raised); border: var(--border-technical); font: inherit; }
</style>
