<script setup lang="ts">
import type {
  AuthoritativeDecisionView,
  EvidenceFactView,
  IndexConditionEvidenceView,
  SymbolReferenceMarketView,
} from "../../api/generated";
import IndexConditionProgress from "./IndexConditionProgress.vue";
import { formatDisplayDateTime, formatDisplayFactValue } from "../../formatters/dateTime";

interface Props {
  evidence?: readonly IndexConditionEvidenceView[];
  plan: Readonly<Pick<AuthoritativeDecisionView, "planHash" | "planId" | "planVersion">>;
  reference: Readonly<SymbolReferenceMarketView> | null;
}

withDefaults(defineProps<Props>(), { evidence: () => [] });

function formatFact(fact: EvidenceFactView): string {
  return `${fact.key}=${formatDisplayFactValue(fact.value, fact.unit)} ${fact.unit}`;
}
</script>

<template>
  <section class="reference-market" aria-label="股票参考指数与计划条件">
    <section class="reference-market__panel" aria-labelledby="reference-market-data-title">
      <h2 id="reference-market-data-title">参考指数数据</h2>
      <template v-if="reference !== null">
        <dl>
          <div><dt>指数</dt><dd>{{ reference.displayName }}（{{ reference.indexCode }}）</dd></div>
          <div><dt>板块</dt><dd>{{ reference.board }}</dd></div>
          <div><dt>映射版本</dt><dd>{{ reference.mappingVersion }}</dd></div>
          <div><dt>快照哈希</dt><dd>{{ reference.snapshotHash ?? "不可用" }}</dd></div>
          <div><dt>数据截止</dt><dd>{{ formatDisplayDateTime(reference.dataAt, "不可用") }}</dd></div>
          <div><dt>健康</dt><dd>{{ reference.health }}</dd></div>
        </dl>
        <p v-if="reference.issues.length > 0">
          问题：{{ reference.issues.join("、") }}
        </p>
      </template>
      <p v-else>Schema v1 计划未配置参考指数；原有判断保持不变。</p>
    </section>

    <section class="reference-market__panel" aria-labelledby="reference-market-plan-title">
      <h2 id="reference-market-plan-title">计划指数条件</h2>
      <p class="reference-market__plan-identity">
        当前计划 {{ plan.planId }} · v{{ plan.planVersion }}
      </p>
      <dl>
        <div><dt>计划哈希</dt><dd>{{ plan.planHash }}</dd></div>
      </dl>
      <IndexConditionProgress
        v-if="reference !== null"
        :progress="reference.conditionProgress"
      />
      <p v-else>计划未使用</p>
      <p v-if="reference !== null && evidence.length === 0 && reference.conditionProgress.total > 0">
        当前条件证据不可用；不在浏览器补算。
      </p>
      <div
        v-if="reference !== null && evidence.length > 0"
        class="reference-market__table-scroller"
        tabindex="0"
      >
        <table>
          <caption>后端生成的计划路径级指数条件证据</caption>
          <thead>
            <tr><th scope="col">计划路径</th><th scope="col">条件</th><th scope="col">结果</th><th scope="col">输入</th><th scope="col">比较</th><th scope="col">缺失</th></tr>
          </thead>
          <tbody>
            <tr v-for="item in evidence" :key="item.planPath">
              <th scope="row">{{ item.planPath }}</th>
              <td>{{ item.conditionType }}</td>
              <td>{{ item.outcome }}</td>
              <td>
                <span v-for="fact in item.parameters ?? []" :key="fact.key">
                  {{ formatFact(fact) }}
                </span>
              </td>
              <td>{{ item.actualValue ?? "—" }} / {{ item.comparisonValue ?? "—" }} {{ item.unit }}</td>
              <td>{{ (item.missingInputs ?? []).join("、") || "—" }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </section>
</template>

<style scoped>
.reference-market {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-4);
}

.reference-market__panel {
  min-width: 0;
  padding: var(--space-4);
  background: var(--color-surface-graphite);
  border: var(--border-technical);
}

.reference-market dl,
.reference-market dl div {
  display: grid;
  gap: var(--space-1);
}

.reference-market dd {
  margin: 0;
  overflow-wrap: anywhere;
  font-family: var(--font-numeric);
}

.reference-market__plan-identity {
  font-family: var(--font-numeric);
  font-weight: 700;
}

.reference-market__table-scroller {
  margin-block-start: var(--space-3);
  overflow-x: auto;
}

.reference-market table {
  width: 100%;
  min-width: 54rem;
  border-collapse: collapse;
}

.reference-market th,
.reference-market td {
  padding: var(--space-2);
  text-align: start;
  vertical-align: top;
  border-block-end: var(--border-technical);
}

.reference-market td span {
  display: block;
}

@media (max-width: 63.999rem) {
  .reference-market {
    grid-template-columns: 1fr;
  }
}
</style>
