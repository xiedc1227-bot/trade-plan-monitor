<script setup lang="ts">
import { onBeforeUnmount, shallowRef, useId, watch } from "vue";
import type { FrozenPretrade, CapitalPreviewView } from "../../api/generated";
import P3CapitalAssessment from "./P3CapitalAssessment.vue";
const props = defineProps<{ evidence: FrozenPretrade; planVersionId: string; current: boolean;
  authorityRevision: number; occurrenceId?: string | undefined; manualQuantity?: boolean;
  request: <T>(url: string, body?: object) => Promise<T> }>();
const id = useId();
const proposed = shallowRef<string | number>("");
const result = shallowRef<CapitalPreviewView | null>(null);
const busy = shallowRef(false), error = shallowRef("");
let generation = 0;
watch(() => [props.evidence, props.planVersionId, props.current, props.authorityRevision,
  props.occurrenceId, props.manualQuantity, proposed.value], () => {
  generation++; result.value = null; busy.value = false; error.value = "";
});
onBeforeUnmount(() => generation++);
async function preview() {
  if (!props.current || busy.value) return;
  const quantity = props.manualQuantity ? Number(proposed.value) : null;
  if (props.manualQuantity && (!Number.isSafeInteger(quantity) || Number(quantity) <= 0 || Number(quantity) % 100)) {
    error.value = "请明确填写100股整数倍；系统不预填破位例外数量。"; return;
  }
  const epoch = ++generation;
  busy.value = true; error.value = "";
  try {
    const next = await props.request<CapitalPreviewView>("/api/v1/plan-capital-previews", {
      planVersionId: props.planVersionId, ruleId: props.evidence.rule_id,
      occurrenceId: props.occurrenceId ?? null, proposedQuantity: quantity,
    });
    if (epoch !== generation) return;
    if (next.planVersionId !== props.planVersionId || next.ruleId !== props.evidence.rule_id ||
        next.evidence.content_hash !== props.evidence.content_hash || next.authorityGranted !== false ||
        props.manualQuantity && next.quantity !== quantity) throw new Error("预览与当前审核版本或数量不一致，请刷新。");
    result.value = next;
  } catch (cause) {
    if (epoch === generation) error.value = cause instanceof Error ? cause.message : "当前金额预览不可用";
  } finally { if (epoch === generation) busy.value = false; }
}
</script>
<template>
  <section class="capital-runtime" aria-label="当前金额预览" :aria-busy="busy">
    <h4>当前金额预览 · {{ evidence.rule_id }}</h4>
    <template v-if="manualQuantity"><label :for="id">本次金额预览数量（不代表批准量）</label>
      <input :id="id" v-model="proposed" type="number" min="100" step="100" :disabled="busy || !current" /></template>
    <button type="button" :disabled="busy || !current" @click="preview">按当前预算只读预览</button>
    <p v-if="error" role="alert">{{ error }}</p>
    <P3CapitalAssessment v-if="result" :assessment="result.assessment" />
    <p>确认日基础量 Q0 为 {{ evidence.sizing.q0 ?? '未知' }} 股；已确认或批准的整笔数量不会随预算变化重新计算。批准后还需单独确认模拟交易。</p>
  </section>
</template>
<style scoped>
.capital-runtime { display: grid; gap: var(--space-2); min-width: 0; overflow-wrap: anywhere; }
.capital-runtime input { box-sizing: border-box; width: 100%; max-width: 100%; }
</style>
