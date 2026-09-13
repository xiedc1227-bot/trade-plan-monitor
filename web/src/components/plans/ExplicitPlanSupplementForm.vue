<script setup lang="ts">
import { computed, ref, shallowRef, watch } from "vue";

import type {
  FieldBindingView,
  PlanDraftCommand,
  PlanMappingView,
  PlanVersionView,
} from "../../api/generated";

interface Props {
  busy?: boolean;
  plan: PlanVersionView;
}

interface Emits {
  saveDraft: [command: PlanDraftCommand];
}

interface PolicyField {
  readonly label: string;
  readonly path: string;
  readonly placeholder: string;
}

const props = withDefaults(defineProps<Props>(), { busy: false });
const emit = defineEmits<Emits>();
const policyValues = ref<Record<string, string>>({});
const selectedBindingPath = shallowRef<string>("");
const editedValue = shallowRef("");
const localError = shallowRef<string | null>(null);

const policyFields: readonly PolicyField[] = Object.freeze([
  { label: "启用方式", path: "activation.mode", placeholder: "TRADING_DAY" },
  { label: "启用交易日", path: "activation.trading_day", placeholder: "2026-09-14" },
  { label: "成交量历史范围", path: "rules[0].condition.conditions[1].history_scope", placeholder: "CONTIGUOUS_TRADING_BARS" },
  { label: "买入重复策略", path: "rules[0].repeat_policy.mode", placeholder: "ONCE_PER_ACTIVATION" },
  { label: "卖出重复策略", path: "rules[1].repeat_policy.mode", placeholder: "ONCE_PER_ACTIVATION" },
  { label: "风险重复策略", path: "rules[2].repeat_policy.mode", placeholder: "ONCE_PER_ACTIVATION" },
  { label: "买卖冲突策略", path: "conflict_policy.trade_conflict", placeholder: "BLOCK_BOTH" },
  { label: "风险冲突策略", path: "conflict_policy.risk_conflict", placeholder: "RISK_ONLY" },
]);

const explicit = computed(
  () => props.plan.contentHash !== null && props.plan.contentHash !== undefined,
);
const mapping = computed(() => props.plan.mapping ?? null);
const editableBindings = computed(() => (mapping.value?.fieldBindings ?? []).filter(
  (item) => (item.origin === "SOURCE" || item.origin === "USER_SUPPLEMENT") &&
    item.path !== "symbol" && !item.path.endsWith(".rule_id") &&
    // The logical node editor owns both STRUCTURE and its scalar type claim.
    !((item.bindingKind ?? "VALUE") === "VALUE" && item.path.endsWith(".type") &&
      (mapping.value?.fieldBindings ?? []).some((parent) =>
        parent.bindingKind === "STRUCTURE" && `${parent.path}.type` === item.path)),
));
const selectedBinding = computed(() => editableBindings.value.find(
  (item) => item.path === selectedBindingPath.value,
) ?? null);
const hasMissingPolicies = computed(() => {
  return activePolicyFields.value.length > 0;
});
const activePolicyFields = computed(() => {
  const paths = new Set((props.plan.unresolvedReviewIssues ?? []).map((issue) => issue.path));
  return policyFields.filter((field) =>
    paths.has(field.path) ||
    (field.path.startsWith("activation.") && paths.has("activation")) ||
    (field.path.startsWith("conflict_policy.") && paths.has("conflict_policy")) ||
    (field.path.endsWith(".mode") && paths.has(field.path.slice(0, -5))),
  );
});
const policyReady = computed(() => activePolicyFields.value.every((field) =>
  (policyValues.value[field.path]?.trim().length ?? 0) > 0,
));

watch(
  () => props.plan.id,
  () => {
    policyValues.value = Object.fromEntries(policyFields.map((field) => [field.path, ""]));
    selectedBindingPath.value = "";
    editedValue.value = "";
    localError.value = null;
  },
  { immediate: true },
);

watch(selectedBinding, (binding) => {
  editedValue.value = binding === null ? "" : displayBindingValue(binding);
});

function displayBindingValue(binding: FieldBindingView): string {
  if (binding.bindingKind === "STRUCTURE") return String(binding.value);
  if (binding.unit === "FEN" && typeof binding.value === "number") return (binding.value / 100).toFixed(2);
  return String(binding.value);
}

function savePolicySupplements(): void {
  if (!policyReady.value || props.busy) return;
  const changes: Array<{
    path: string;
    value: string;
    unit: FieldBindingView["unit"];
    bindingKind: NonNullable<FieldBindingView["bindingKind"]>;
  }> = activePolicyFields.value.map((field) => ({
    path: field.path,
    value: policyValues.value[field.path]?.trim() ?? "",
    unit: "NONE" as const,
    bindingKind: "VALUE" as const,
  }));
  save(changes);
}

function saveBindingEdit(): void {
  const binding = selectedBinding.value;
  if (binding === null || props.busy) return;
  const value = parseEditedValue(binding, editedValue.value);
  if (value === null) {
    localError.value = "请输入与当前字段类型一致的值；价格使用元，股数必须是 100 的倍数。";
    return;
  }
  const change = { path: binding.path, value, unit: binding.unit, bindingKind: binding.bindingKind ?? "VALUE" };
  // Changing ALL/ANY keeps the same ordered children, but both the grouping
  // relationship and its scalar operator now come from this human edit.
  save(binding.bindingKind === "STRUCTURE" ? [
    change,
    { path: `${binding.path}.type`, value, unit: "NONE", bindingKind: "VALUE" },
  ] : [change]);
}

function parseEditedValue(binding: FieldBindingView, raw: string): boolean | number | string | null {
  const value = raw.trim();
  if (binding.bindingKind === "STRUCTURE") return value === "ALL" || value === "ANY" ? value : null;
  if (typeof binding.value === "boolean") return value === "true" ? true : value === "false" ? false : null;
  if (typeof binding.value === "number") {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return null;
    const normalized = binding.unit === "FEN" ? Math.round(parsed * 100) : parsed;
    if (!Number.isSafeInteger(normalized)) return null;
    if (binding.unit === "SHARES" && (normalized <= 0 || normalized % 100 !== 0)) return null;
    return normalized;
  }
  return value.length > 0 ? value : null;
}

function save(changes: readonly {
  path: string;
  value: boolean | number | string;
  unit: FieldBindingView["unit"];
  bindingKind: NonNullable<FieldBindingView["bindingKind"]>;
}[]): void {
  const sourceMapping = mapping.value;
  if (!explicit.value || sourceMapping === null) {
    localError.value = "当前版本缺少服务端映射，不能生成可审核的补充版本。";
    return;
  }
  try {
    const document = JSON.parse(props.plan.planJson) as Record<string, unknown>;
    const nextMapping = cloneMapping(sourceMapping);
    for (const [index, change] of changes.entries()) {
      setPlanValue(document, change.path, change.value, change.bindingKind);
      const supplementId = `user-supplement-${Date.now()}-${index}`;
      nextMapping.userSupplements = [
        ...(nextMapping.userSupplements ?? []).filter((item) => item.path !== change.path),
        {
          label: "human_confirmed_supplement",
          path: change.path,
          supplementId,
          suppliedAt: props.plan.createdAt,
          unit: change.unit,
          value: change.value,
        },
      ];
      nextMapping.fieldBindings = [
        ...(nextMapping.fieldBindings ?? []).filter(
          (item) => !(item.path === change.path && (item.bindingKind ?? "VALUE") === change.bindingKind),
        ),
        {
          bindingKind: change.bindingKind,
          clauseIds: [],
          origin: "USER_SUPPLEMENT",
          path: change.path,
          supplementId,
          unit: change.unit,
          value: change.value,
        },
      ];
    }
    emit("saveDraft", {
      expectedRevision: props.plan.revision,
      mapping: nextMapping,
      planJson: JSON.stringify(document),
      reviewIssues: [],
      sourceText: props.plan.sourceText,
    });
    localError.value = null;
  } catch {
    localError.value = "无法生成完整的下一版本；当前计划未被修改。";
  }
}

function cloneMapping(source: PlanMappingView): PlanMappingView {
  return JSON.parse(JSON.stringify(source)) as PlanMappingView;
}

function setPlanValue(
  document: Record<string, unknown>,
  path: string,
  value: boolean | number | string,
  bindingKind: string,
): void {
  const segments = path.replace(/\[(\d+)\]/g, ".$1").split(".");
  if (bindingKind === "STRUCTURE") segments.push("type");
  let cursor: Record<string, unknown> | unknown[] = document;
  for (let index = 0; index < segments.length - 1; index += 1) {
    const segment = segments[index];
    const next = segments[index + 1];
    if (segment === undefined || next === undefined) throw new Error("invalid path");
    const existing = readChild(cursor, segment);
    if (typeof existing !== "object" || existing === null) {
      writeChild(cursor, segment, /^\d+$/.test(next) ? [] : {});
    }
    cursor = readChild(cursor, segment) as Record<string, unknown> | unknown[];
  }
  const finalSegment = segments.at(-1);
  if (finalSegment === undefined) throw new Error("invalid path");
  writeChild(cursor, finalSegment, value);
}

function readChild(cursor: Record<string, unknown> | unknown[], key: string): unknown {
  return Array.isArray(cursor) ? cursor[Number(key)] : cursor[key];
}

function writeChild(
  cursor: Record<string, unknown> | unknown[],
  key: string,
  value: unknown,
): void {
  if (Array.isArray(cursor)) cursor[Number(key)] = value;
  else cursor[key] = value;
}
</script>

<template>
  <section v-if="explicit" class="explicit-supplement" aria-labelledby="explicit-supplement-title">
    <h2 id="explicit-supplement-title">普通政策补充与规则修订</h2>
    <p>补充会保存为新的不可变版本和 `USER_SUPPLEMENT` 证据；保存后必须重新读取服务端问题并逐项复核。</p>
    <p v-if="localError" role="alert">{{ localError }}</p>
    <form v-if="hasMissingPolicies" @submit.prevent="savePolicySupplements">
      <h3>缺失的普通政策</h3>
      <p>这些选项不从自然语言原文猜测。请按您的实际策略填写；每一项会作为人工补充持久保存。</p>
      <label v-for="field in activePolicyFields" :key="field.path">
        {{ field.label }}
        <input v-model="policyValues[field.path]" :placeholder="field.placeholder" required />
      </label>
      <button type="submit" :disabled="busy || !policyReady">保存补充并重新审核</button>
    </form>
    <form v-if="editableBindings.length > 0" @submit.prevent="saveBindingEdit">
      <h3>修订当前明确字段</h3>
      <p>可修改价格（元）、股数、包含边界和 ALL/ANY 父条件。修改原文映射值时，新的值会改为人工补充，不会伪称来自原文。</p>
      <label>字段
        <select v-model="selectedBindingPath">
          <option disabled value="">选择字段</option>
          <option v-for="binding in editableBindings" :key="`${binding.bindingKind}-${binding.path}`" :value="binding.path">
            {{ binding.path }} · {{ binding.unit }}
          </option>
        </select>
      </label>
      <label v-if="selectedBinding">新值
        <input v-model="editedValue" :aria-label="`${selectedBinding.path} 新值`" required />
      </label>
      <p v-if="selectedBinding" aria-live="polite">
        当前值 {{ displayBindingValue(selectedBinding) }}（{{ selectedBinding.origin }}）
        → 新值 {{ editedValue }}（人工补充 USER_SUPPLEMENT）。
        <span v-if="selectedBinding.bindingKind === 'STRUCTURE'">
          ALL 表示所有子条件都需满足；ANY 表示任一子条件满足即可。子条件及其顺序保持不变。
        </span>
      </p>
      <button type="submit" :disabled="busy || selectedBinding === null">保存字段修订并重新审核</button>
    </form>
  </section>
</template>

<style scoped>
.explicit-supplement { display: grid; gap: var(--space-3); padding: var(--space-4); background: var(--color-surface-graphite); border: var(--border-technical); }
.explicit-supplement form { display: grid; gap: var(--space-2); padding-block-start: var(--space-3); border-block-start: var(--border-technical); }
.explicit-supplement label { display: grid; gap: var(--space-1); }
.explicit-supplement input, .explicit-supplement select, .explicit-supplement button { min-height: 2.75rem; }
</style>
