<script setup lang="ts">
import type { DeepReadonly } from "vue";
import type { PreparationConfirmationSummary } from "../../api/generated-runtime-status";

defineProps<{ summary: DeepReadonly<PreparationConfirmationSummary> }>();
const categoryLabels: Record<string, string> = {
  BACKTEST_SETTING: "回测设置", SOURCE_MISSING: "原文未提供", SOURCE_AMBIGUOUS: "判定口径不明确",
};
</script>

<template>
  <section class="confirmation-summary" aria-label="集中确认事项" data-testid="preparation-confirmations">
    <h3>已从原文和已确认信息中确定</h3>
    <ul><li v-for="fact in summary.automaticFacts" :key="fact">{{ fact }}</li></ul>
    <h3>需要集中确认的事项</h3>
    <p>只需补充以下业务口径。已知价格、数量、日期及停用指令无需重复填写；AI 对语义的解释仍需在完整候选中整体核对。</p>
    <ol v-if="summary.questions.length">
      <li v-for="question in summary.questions" :key="question.questionId">
        <strong>{{ categoryLabels[question.category] ?? question.category }}</strong>：{{ question.message }}
        <blockquote v-for="excerpt in question.excerpts" :key="excerpt">{{ excerpt }}</blockquote>
      </li>
    </ol>
    <p v-else>当前没有额外业务确认项，请核对完整候选后审核。</p>
    <p v-if="summary.questions.some(question => question.category !== 'BACKTEST_SETTING')">可将明确后的口径补充到上方原文，保存后重新提取。保留未知不会自动产生交易。</p>
    <aside v-if="summary.processingIssues.length" role="status">
      <h3>系统处理事项</h3>
      <p v-for="issue in summary.processingIssues" :key="issue">{{ issue }}</p>
    </aside>
  </section>
</template>

<style scoped>
.confirmation-summary { padding: 1rem; border: 1px solid var(--color-border, #cad5e2); border-radius: .5rem; }
li + li { margin-top: .6rem; }
blockquote { margin: .5rem 0 .75rem; padding-left: .75rem; border-left: 3px solid #cad5e2; white-space: pre-wrap; }
aside { margin-top: 1rem; }
</style>
