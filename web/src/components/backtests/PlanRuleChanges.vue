<script setup lang="ts">
import { computed, type DeepReadonly } from "vue";
import type { PlanChange, MarketExceptionPlanDraft, MarketLinkedPlanDraft, UnifiedPlanDraft } from "../../api/generated-runtime-status";
import { fieldLabels, choiceLabels } from "../plans/planSchema";
import { resultFieldLabel, resultValue } from "./ruleChangeFormatting";

type ReviewChange = Readonly<Omit<PlanChange, "clause_ids">> & { readonly clause_ids: readonly string[] };
const props = withDefaults(defineProps<{
  changes?: readonly ReviewChange[];
  initialDraft?: DeepReadonly<UnifiedPlanDraft | MarketLinkedPlanDraft | MarketExceptionPlanDraft> | null;
  clauses?: readonly { clause_id: string; excerpt: string }[];
  unresolved?: boolean;
  resultMode?: boolean;
  businessMode?: boolean;
  referenceDraft?: DeepReadonly<UnifiedPlanDraft | MarketLinkedPlanDraft | MarketExceptionPlanDraft> | null;
}>(), { changes: () => [], initialDraft: null, clauses: () => [], unresolved: false, resultMode: false, businessMode: false, referenceDraft: null });
const titles = { RETAIN: "保留", MODIFY: "修改", ADD: "新增", REVOKE: "取消" } as const;
const sections = ["position", "levels", "activation", "ordinary_rules", "risk_branches", "alert_rules", "monitoring", "execution_policy", "trading_rules"];
const changes = computed<readonly ReviewChange[]>(() => {
  if (!props.initialDraft) return props.changes;
  return sections.flatMap(target => {
    const value = (props.initialDraft as unknown as Record<string, unknown>)[target];
    if (value == null) return [];
    const values = Array.isArray(value) ? value : [value];
    return values.map(after => ({ target, rule_id: null, action: "ADD" as const, before: null, after, clause_ids: [] }));
  });
});
function label(path: string): string {
  if (props.resultMode || props.businessMode) return resultFieldLabel(path);
  const result = path.split(".").map(key => /^\d+$/.test(key) ? `第 ${Number(key) + 1} 项` : fieldLabels[key] ?? key).join(" / ");
  return result;
}
function flatten(value: unknown, prefix = ""): Record<string, unknown> {
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value);
    if (entries.length) return Object.assign({}, ...entries.map(([key, item]) => flatten(item, prefix ? `${prefix}.${key}` : key)));
  }
  return { [prefix]: value };
}
function display(value: unknown): string {
  if (value == null) return "未设置";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (Array.isArray(value) && !value.length) return "无";
  return choiceLabels[String(value)] ?? String(value);
}
function businessValue(value: unknown, path: string, flattened: Record<string, unknown>, side: "before" | "after"): string {
  if (!path.endsWith("prior_rule_id") || typeof value !== "string") return resultValue(value, path, flattened);
  const rules = (props.referenceDraft ?? props.initialDraft)?.ordinary_rules ?? [];
  const related = changes.value.find(change => change.rule_id === value);
  const rule = related?.[side] ?? rules.find(rule => rule.rule_id === value);
  const identifiers = [...new Set([...rules.map(rule => rule.rule_id), ...changes.value.map(change => change.rule_id)].filter(Boolean))];
  const order = identifiers.indexOf(value) + 1;
  if (rule && typeof rule === "object" && "side" in rule && (rule.side === "BUY" || rule.side === "SELL")) {
    const quantity = "quantity" in rule && typeof rule.quantity === "number" ? ` ${rule.quantity} 股` : "";
    return `${rule.side === "BUY" ? "买入" : "卖出"}${quantity}${order ? `（第 ${order} 条规则）` : ""}`;
  }
  return order ? `第 ${order} 条已审核交易规则（详见完整计划）` : `${side === "before" ? "上一份" : "本份"}计划的先决交易规则（详见已审核原文）`;
}
const groups = computed(() => Object.entries(titles).map(([action, title]) => ({
  action, title,
  entries: changes.value.filter(change => change.action === action).map(change => {
    const before = flatten(change.before), after = flatten(change.after);
    const paths = [...new Set([...Object.keys(before), ...Object.keys(after)])];
    const fields = paths.filter(path => path && !["rule_id", "version", "plan_id"].includes(path) &&
      (!props.businessMode || !path.split(".").some(key => /(?:_id|_hash)$/.test(key) && key !== "prior_rule_id" || key === "version")) &&
      (!props.resultMode || !paths.some(child => child.startsWith(`${path}.`))) &&
      (props.resultMode || action !== "MODIFY" || JSON.stringify(before[path]) !== JSON.stringify(after[path])));
    return {
      title: label(change.target),
      ruleId: change.rule_id,
      fullRows: (fields.length ? fields : [""]).map(path => ({ label: path ? label(path) : label(change.target),
        before: action === "ADD" ? '无此规则' : resultValue(before[path], path, before),
        after: action === "REVOKE" ? '已取消' : resultValue(after[path], path, after),
        changed: JSON.stringify(before[path]) !== JSON.stringify(after[path]) })),
      rows: fields.map(path => ({ label: label(path), value: props.businessMode
        ? action === "MODIFY" ? `${businessValue(before[path], path, before, "before")} → ${businessValue(after[path], path, after, "after")}`
          : businessValue(action === "REVOKE" ? before[path] : after[path], path, action === "REVOKE" ? before : after, action === "REVOKE" ? "before" : "after")
        : action === "MODIFY" ? `${display(before[path])} → ${display(after[path])}` : display(action === "REVOKE" ? before[path] : after[path]) })),
      excerpts: props.clauses.filter(clause => change.clause_ids.includes(clause.clause_id)).map(clause => clause.excerpt),
    };
  }),
})));
</script>

<template>
  <section class="rule-changes" :class="{ 'rule-changes--business': businessMode }" :aria-label="businessMode ? '交易条件变化' : resultMode ? '冻结规则对照' : '规则变更审核'" data-testid="plan-rule-changes">
    <h4>{{ businessMode ? initialDraft ? '本次建立的交易条件' : '本次交易条件变化' : resultMode ? '保留／修改／新增／取消' : initialDraft ? '本份建立的规则' : '相对上一份已审核计划的规则变更' }}</h4>
    <p v-if="businessMode">以下为已审核的交易条件，按保留、修改、新增和取消分类。</p>
    <p v-else-if="resultMode">按最终冻结值分类。修改组同时列出未改变的字段；标记“变化”的行为前后不同的内容。保留组可展开查看完整规则。</p>
    <p v-else-if="unresolved" role="status">部分变更含义或目标尚不明确，请核对提示；未提及的规则默认保留。</p>
    <p v-else>以上一份已审核规则为基础，未提及的规则默认保留；核对保留、修改、新增和取消后，统一审核本份计划。</p>
    <details v-for="group in groups" :key="group.action" :open="group.action !== 'RETAIN' && group.entries.length > 0">
      <summary>{{ group.title }}（{{ group.entries.length }}）</summary>
      <p v-if="!group.entries.length">{{ unresolved ? '待范围确认后确定' : '无此类变更' }}</p>
      <article v-for="(entry, index) in group.entries" :key="index">
        <h5>{{ entry.title }}</h5>
        <p v-if="group.action === 'RETAIN'">{{ resultMode ? '本份与上一份冻结值相同。' : '沿用上一份已审核规则及原始依据。' }}</p>
        <div v-if="resultMode" class="comparison-table" role="region" :aria-label="`${entry.title}前后对照`" tabindex="0">
          <table><caption>{{ entry.title }} · {{ entry.ruleId ?? '整体设置' }}</caption>
            <thead><tr><th scope="col">规则字段</th><th scope="col">上一份</th><th scope="col">本份</th></tr></thead>
            <tbody><tr v-for="(row, rowIndex) in entry.fullRows" :key="rowIndex" :class="{ changed: row.changed }">
              <th scope="row">{{ row.label }}<small v-if="row.changed"> · 变化</small></th><td>{{ row.before }}</td><td>{{ row.after }}</td>
            </tr></tbody>
          </table>
        </div>
        <dl v-else><template v-for="(row, rowIndex) in entry.rows" :key="rowIndex"><dt>{{ row.label }}</dt><dd>{{ row.value }}</dd></template></dl>
        <blockquote v-for="(excerpt, excerptIndex) in entry.excerpts" :key="excerptIndex">{{ excerpt }}</blockquote>
      </article>
    </details>
  </section>
</template>

<style scoped>
.rule-changes { min-width: 0; overflow-wrap: anywhere; padding: var(--space-3); border: var(--border-technical); }
.rule-changes summary { cursor: pointer; padding: var(--space-2); }
.rule-changes summary:focus-visible { outline: 2px solid var(--color-focus-ring); }
.rule-changes article { padding: var(--space-2); }
.rule-changes dl { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 2fr); gap: var(--space-2); }
.rule-changes dd { margin: 0; }
.rule-changes blockquote { margin: var(--space-2) 0; padding-left: var(--space-3); border-left: var(--border-technical); }
.rule-changes--business { padding: 0; border: 0; }
.rule-changes--business article, .rule-changes--business summary { padding-inline: 0; }
.comparison-table { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; table-layout: fixed; }
caption { text-align: left; padding: var(--space-2) 0; color: var(--color-text-silt); }
th, td { text-align: left; vertical-align: top; padding: var(--space-2); border-bottom: var(--border-technical); overflow-wrap: anywhere; }
tbody th { font-weight: normal; }
small { color: var(--color-text-primary); }
.changed { background: var(--color-surface-raised); }
@media (max-width: 480px) { .rule-changes dl { grid-template-columns: minmax(0, 1fr); } }
</style>
