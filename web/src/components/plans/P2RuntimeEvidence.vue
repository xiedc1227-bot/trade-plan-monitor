<script setup lang="ts">
import { shallowRef, watch, useId } from "vue";
import type { FrozenPretrade, EconomicsResult, P2PreviewView } from "../../api/generated";
import P2EconomicsResult from "./P2EconomicsResult.vue";
const props = defineProps<{ evidence: FrozenPretrade; execution?: EconomicsResult | null | undefined;
  planVersionId?: string; current?: boolean; occurrenceId?: string | undefined; manualQuantity?: boolean;
  request?: <T>(url: string, body?: object) => Promise<T> }>();
const id = useId();
const proposed = shallowRef("");
const result = shallowRef<P2PreviewView | null>(null);
const busy = shallowRef(false), error = shallowRef("");
let generation = 0;
watch(() => [props.evidence, props.current, props.planVersionId, props.occurrenceId,
  props.manualQuantity, proposed.value], () => {
  generation++; result.value = null; error.value = ""; busy.value = false;
});
async function preview() {
  if (!props.request || !props.current || !props.planVersionId || busy.value) return;
  const quantity = props.manualQuantity ? Number(proposed.value) : null;
  if (props.manualQuantity && (!Number.isSafeInteger(quantity) || Number(quantity) <= 0 || Number(quantity) % 100 !== 0)) {
    error.value = "请明确填写 100 股整数倍，系统不预填例外数量。"; return;
  }
  const epoch = ++generation;
  busy.value = true; error.value = "";
  try {
    const next = await props.request<P2PreviewView>("/api/v1/plan-economics-previews", {
      planVersionId: props.planVersionId, ruleId: props.evidence.rule_id,
      occurrenceId: props.occurrenceId ?? null, proposedQuantity: quantity,
    });
    if (epoch === generation) result.value = next;
  } catch (cause) {
    if (epoch === generation) error.value = cause instanceof Error ? cause.message : "估算失败，请刷新当前依据";
  } finally { if (epoch === generation) busy.value = false; }
}
</script>
<template>
  <section class="p2-runtime" aria-label="波动数量与费用证据" :aria-busy="busy">
    <h4>波动数量与费用证据 · {{ evidence.rule_id }}</h4>
    <p>确认日 {{ evidence.decision_session }}；ATR14 {{ evidence.sizing.atr_fen ?? '未知' }} 分；收盘 {{ evidence.sizing.close_fen ?? '未知' }} 分。</p>
    <p>命中分档 {{ evidence.sizing.tier_index == null ? '固定数量或数据不足' : evidence.sizing.tier_index + 1 }}；波动后基础量 Q0：{{ evidence.sizing.q0 ?? '未知' }} 股。随后执行大盘减量，确认后的整笔数量冻结。</p>
    <p v-if="evidence.sizing.blocker" role="status">数量限制：{{ evidence.sizing.blocker }}</p>
    <p>费用模式：{{ evidence.policy.economics.mode === 'REQUIRED' ? '明确数值买入门槛' : evidence.policy.economics.mode === 'PREVIEW_ONLY' ? '仅研究估算' : '不计算费用' }}。</p>
    <p v-if="evidence.policy.economics.mode !== 'NONE'">费用版本 {{ evidence.policy.economics.fee_schedule.version }}；有效期 {{ evidence.policy.economics.fee_schedule.effective_from }} 至 {{ evidence.policy.economics.fee_schedule.effective_through }}；来源 {{ evidence.policy.economics.fee_schedule.provenance.source }}。</p>
    <P2EconomicsResult v-if="execution ?? evidence.economics" :result="(execution ?? evidence.economics)!" />
    <template v-if="request && planVersionId">
      <template v-if="manualQuantity"><label :for="id">本次费用估算数量（不代表批准量）</label><input :id="id" v-model="proposed" inputmode="numeric" :disabled="busy || !current" /></template>
      <button type="button" :disabled="busy || !current" @click="preview">按当前依据只读估算</button>
      <p v-if="error" role="alert">{{ error }}</p>
      <P2EconomicsResult v-if="result" :result="result.economics" />
    </template>
    <p>估算不改变持仓，也不授予权限。例外仍需逐次批准和单独确认模拟；风险退出不受买入费用门槛阻断。</p>
  </section>
</template>
<style scoped>
.p2-runtime { display: grid; gap: var(--space-2); border: var(--border-technical); padding: var(--space-3); min-width: 0; overflow-wrap: anywhere; }
.p2-runtime input { box-sizing: border-box; max-width: 100%; }
</style>
