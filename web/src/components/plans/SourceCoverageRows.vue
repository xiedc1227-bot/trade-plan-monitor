<script setup lang="ts">
import type { DeepReadonly } from "vue";
import type { SourceCoveragePage, SourceMappingProposalView, SourceObligationView } from "../../api/generated";
import { sourceObligationStateLabel, type SourceSpan } from "./sourceCoveragePresentation";
defineProps<{ items: DeepReadonly<SourceCoveragePage>["items"]; busy?: boolean }>();
const emit = defineEmits<{ revealField: [path: string]; revealSource: [span: Readonly<SourceSpan>] }>();
type Row = DeepReadonly<SourceCoveragePage>["items"][number];
function rowKey(row: Row) {
  return `${row.kind}:${row.rowIndex}:${row.kind === 'OBLIGATION' ? row.obligation.obligationId
    : row.kind === 'ISSUE' ? row.issue.code + row.issue.path : row.change.evidenceHash + row.change.path}`;
}
function blocked(value: DeepReadonly<SourceObligationView>) {
  return value.scope === "UNKNOWN" || ["UNRESOLVED", "UNSUPPORTED", "CONFLICT"].includes(value.serverState);
}
function proposalLabel(value: SourceMappingProposalView["proposedDisposition"]) {
  return { POLICY: "交易政策（建议）", INVENTORY_ASSERTION: "仓位陈述（建议）", BACKGROUND: "背景（建议）",
    CONTEXT: "上下文（建议）", UNRESOLVED: "尚待明确（建议）", UNSUPPORTED: "暂不支持（建议）" }[value];
}
function reveal(value: DeepReadonly<SourceObligationView>) {
  emit("revealSource", Object.freeze({ start: value.start, end: value.end, excerpt: value.excerpt }));
}
</script>

<template>
  <ol class="source-coverage-rows" aria-label="本页原文核对明细">
    <li v-for="row in items" :key="rowKey(row)" class="source-coverage-row" :value="row.rowIndex + 1">
      <template v-if="row.kind === 'OBLIGATION'">
        <h3>原文义务 · 第 {{ row.rowIndex + 1 }} 项</h3><blockquote>{{ row.obligation.excerpt }}</blockquote>
        <div class="source-coverage-row__comparison">
          <section aria-label="保存的映射建议"><h4>保存的映射建议</h4>
            <template v-if="row.obligation.mappingProposal"><p>{{ proposalLabel(row.obligation.mappingProposal.proposedDisposition) }}</p>
              <p>{{ row.obligation.mappingProposal.reason }}</p>
              <button v-for="(path, index) in row.obligation.mappingProposal.proposedPaths" :key="`${path}:${index}`" type="button" :disabled="busy" @click="emit('revealField', path)">查看建议字段 <code>{{ path }}</code></button>
            </template><p v-else>没有保存的映射建议。</p><small>建议不能替代服务端核对结果。</small>
          </section>
          <section aria-label="服务端核对结果"><h4>服务端核对结果</h4>
            <p :class="{ 'source-coverage-row__blocked': blocked(row.obligation) }">{{ blocked(row.obligation) ? '阻断：' : '' }}{{ sourceObligationStateLabel(row.obligation.serverState) }}</p>
            <p>适用范围：{{ { PLAN: '整份计划', BUY: '买入', SELL: '卖出', RISK: '风险', ALERT: '提醒', UNKNOWN: '尚未明确' }[row.obligation.scope] }}</p>
            <button v-for="(path, index) in row.obligation.paths" :key="`${path}:${index}`" type="button" :disabled="busy" @click="emit('revealField', path)">查看字段 <code>{{ path }}</code></button>
          </section>
        </div>
        <button type="button" :disabled="busy" :aria-label="`定位原文第 ${row.rowIndex + 1} 项`" @click="reveal(row.obligation)">定位原文片段</button>
        <section v-if="row.obligation.humanSupplements.length" aria-label="已登记的人工补充链接"><h4>已登记的人工补充链接</h4>
          <ul><li v-for="(link, index) in row.obligation.humanSupplements" :key="`${link.supplementId}:${link.path}:${index}`">
            <p>补充 ID：<code>{{ link.supplementId }}</code></p>
            <button type="button" :disabled="busy" @click="emit('revealField', link.path)">查看补充字段 <code>{{ link.path }}</code></button>
            <p>对应内容哈希：<code>{{ link.candidateContentHash }}</code></p>
          </li></ul>
        </section><p v-else class="source-coverage-row__muted">本条没有已登记的人工补充链接。</p>
        <details v-if="row.obligation.semanticsJson !== null"><summary>服务端结构化语义</summary><pre tabindex="0" aria-label="服务端结构化语义">{{ row.obligation.semanticsJson }}</pre></details>
      </template>
      <template v-else-if="row.kind === 'ISSUE'">
        <h3>待解决问题 · 第 {{ row.rowIndex + 1 }} 项</h3><p class="source-coverage-row__blocked">{{ row.issue.message }}</p>
        <p v-if="row.issue.start === null">全局问题，没有单独的原文片段。</p>
        <p v-else>原文码点范围：{{ row.issue.start }}–{{ row.issue.end }}</p>
        <button type="button" :disabled="busy" @click="emit('revealField', row.issue.path)">查看问题位置 <code>{{ row.issue.path }}</code></button>
        <details><summary>问题标识</summary><code>{{ row.issue.code }}</code></details>
      </template>
      <template v-else>
        <h3>规范化差异 · 第 {{ row.rowIndex + 1 }} 项</h3>
        <p>{{ row.change.traceRole === 'CURRENT_ASSESSMENT' ? '当前来源的规范化差异' : '历史输入的规范化差异，不代表当前来源证明' }}</p>
        <button type="button" :disabled="busy" @click="emit('revealField', row.change.path)">查看差异字段 <code>{{ row.change.path }}</code></button>
        <div class="source-coverage-row__comparison"><section><h4>规范化前</h4><pre tabindex="0" aria-label="规范化前">{{ row.change.beforeJson }}</pre></section>
          <section><h4>规范化后</h4><pre tabindex="0" aria-label="规范化后">{{ row.change.afterJson }}</pre></section></div>
        <details><summary>差异的来源与证明</summary><p>原因：<code>{{ row.change.reason }}</code></p>
          <p>原文哈希：<code>{{ row.change.sourceHash }}</code></p><p>证明：<code>{{ row.change.evidenceHash }}</code></p></details>
      </template>
    </li>
  </ol>
  <p v-if="!items.length" role="status">本页没有可显示的证明行，请查看整份计划的核对摘要。</p>
</template>

<style scoped>
.source-coverage-rows { display: grid; gap: var(--space-4); min-inline-size: 0; max-inline-size: 100%; margin: 0; padding: 0; list-style: none; }
.source-coverage-row { display: grid; gap: var(--space-3); min-inline-size: 0; max-inline-size: 100%; padding: var(--space-4); border: var(--border-technical); border-radius: var(--radius-control); overflow-wrap: anywhere; }
.source-coverage-row h3, .source-coverage-row h4, .source-coverage-row p, .source-coverage-row blockquote { margin: 0; }
.source-coverage-row blockquote { white-space: pre-wrap; border-inline-start: var(--border-technical); padding-inline-start: var(--space-3); }
.source-coverage-row__comparison { display: grid; gap: var(--space-3); min-inline-size: 0; }
.source-coverage-row section, .source-coverage-row details { display: grid; gap: var(--space-2); min-inline-size: 0; }
.source-coverage-row pre { min-inline-size: 0; max-inline-size: 100%; max-block-size: 16rem; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; padding: var(--space-3); background: var(--color-surface-ink); border: var(--border-technical); border-radius: var(--radius-control); }
.source-coverage-row code, .source-coverage-row button { overflow-wrap: anywhere; }
.source-coverage-row button { min-block-size: 2.75rem; max-inline-size: 100%; white-space: normal; justify-self: start; text-align: start; }
.source-coverage-row__blocked { color: var(--color-signal-risk-vermilion); border-inline-start: .1875rem solid currentColor; padding-inline-start: var(--space-2); }
.source-coverage-row__muted, .source-coverage-row small { color: var(--color-text-muted); }
@media (min-width: 48rem) { .source-coverage-row__comparison { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
