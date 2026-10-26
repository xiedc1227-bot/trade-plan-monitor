<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, shallowRef, useId, watch } from "vue";
import type { CapitalBookView, CapitalOpeningReceipt } from "../../api/generated";
const props = defineProps<{ planVersionId: string; symbol: string; costRequired: boolean;
  current: boolean; authorityRevision: number;
  request: <T>(url: string, body?: object, key?: string) => Promise<T> }>();
const emit = defineEmits<{ refresh: [] }>();
const id = useId();
const resource = shallowRef<CapitalBookView | null>(null);
const busy = shallowRef(false), error = shallowRef(""), notice = shallowRef("");
const observed = shallowRef(""), source = shallowRef(""), excerpt = shallowRef(""), reason = shallowRef("");
const confirmed = shallowRef(false);
const bases = reactive<Record<string, string | number>>({});
const keys = new Map<string, string>();
let generation = 0;
const rows = computed(() => resource.value?.inventoryLots ?? []);
const complete = computed(() => rows.value.every(lot => {
  const value = bases[`${lot.bucket}:${lot.lot_id}`];
  return value !== undefined && String(value).trim() !== "" && Number.isSafeInteger(Number(value)) && Number(value) >= 0;
}) && Number.isSafeInteger(rows.value.reduce((sum, lot) => sum + Number(bases[`${lot.bucket}:${lot.lot_id}`]), 0)));
const canSubmit = computed(() => props.current && resource.value?.inventoryKnown && confirmed.value && complete.value
  && observed.value && source.value.trim() && excerpt.value.trim() && reason.value.trim() && !busy.value);
function reset() {
  for (const key of Object.keys(bases)) delete bases[key];
  observed.value = ""; source.value = ""; excerpt.value = ""; reason.value = ""; confirmed.value = false;
}
async function load() {
  const epoch = ++generation;
  resource.value = null; error.value = ""; busy.value = true; reset();
  try {
    const value = await props.request<CapitalBookView>(`/api/v1/simulation-capital-books/${encodeURIComponent(props.symbol)}`);
    if (epoch === generation) resource.value = value;
  } catch (cause) {
    if (epoch === generation) error.value = cause instanceof Error ? cause.message : "当前预算依据不可用";
  } finally { if (epoch === generation) busy.value = false; }
}
watch(() => [props.planVersionId, props.symbol, props.current, props.authorityRevision], () => { void load(); }, { immediate: true });
onBeforeUnmount(() => generation++);
async function submit() {
  if (!canSubmit.value || !resource.value) return;
  const epoch = ++generation;
  const command = { planVersionId: props.planVersionId,
    expectedInventoryRevision: resource.value.inventoryRevision, expectedBookRevision: resource.value.bookRevision ?? 0,
    observedAt: `${observed.value}+08:00`, source: source.value, excerpt: excerpt.value, reason: reason.value,
    confirmed: true, lots: rows.value.map(lot => ({ ...lot, retained_basis_fen: Number(bases[`${lot.bucket}:${lot.lot_id}`]) })) };
  const identity = JSON.stringify(command), key = keys.get(identity) ?? crypto.randomUUID();
  keys.set(identity, key); busy.value = true; error.value = ""; notice.value = "";
  try {
    const receipt = await props.request<CapitalOpeningReceipt>("/api/v1/simulation-capital-openings", command, key);
    if (epoch !== generation) return;
    notice.value = `已确认模拟预算成本，记录时间 ${receipt.event.received_at}。仓位与买入权限未改变。`;
    await load(); emit("refresh");
  } catch (cause) {
    if (epoch === generation) error.value = cause instanceof Error ? cause.message : "确认失败，请刷新当前批次";
  } finally { if (epoch === generation) busy.value = false; }
}
</script>
<template>
  <section class="capital-opening" aria-label="模拟预算与开仓成本" :aria-busy="busy">
    <h3>模拟预算与开仓成本</h3>
    <p v-if="resource">保留成本：{{ resource.retainedBasisFen == null ? '未知，尚无完整成本依据' : `${(resource.retainedBasisFen / 100).toFixed(2)} 元` }}；预算修订 {{ resource.bookRevision ?? '尚未建账' }}。</p>
    <p v-if="!costRequired">当前采用持仓市值上限，买入金额检查不需要开仓成本。</p>
    <p v-else-if="resource?.inventoryKnown && !rows.length">已明确初始化为空仓，保留成本为零；首次明确模拟买入时一并建账。</p>
    <p v-if="resource && !resource.inventoryKnown">模拟库存未知，请先明确初始化模拟仓位。</p>
    <button type="button" :disabled="busy" @click="load">刷新预算与批次</button>
    <form v-if="costRequired && resource?.inventoryKnown && rows.length" @submit.prevent="submit">
      <p>逐项核对全部当前批次。此操作只登记保留成本，不更新仓位，不批准买入；校正会保留之前的审计记录。</p>
      <div v-for="(lot, index) in rows" :key="`${lot.bucket}:${lot.lot_id}`" class="capital-opening__lot">
        <p>{{ lot.bucket }} · {{ lot.quantity }} 股 · {{ lot.lot_id }}</p>
        <label :for="`${id}-lot-${index}`">此批次当前保留成本（分，0须明确填写）</label>
        <input :id="`${id}-lot-${index}`" v-model="bases[`${lot.bucket}:${lot.lot_id}`]" type="number" min="0" step="1" :disabled="busy || !current" />
      </div>
      <label :for="`${id}-observed`">成本依据观察时间（上海时间）</label>
      <input :id="`${id}-observed`" v-model="observed" type="datetime-local" step="1" :disabled="busy || !current" />
      <label :for="`${id}-source`">成本来源</label><input :id="`${id}-source`" v-model="source" :disabled="busy || !current" />
      <label :for="`${id}-excerpt`">对应原句或凭据</label><textarea :id="`${id}-excerpt`" v-model="excerpt" :disabled="busy || !current" />
      <label :for="`${id}-reason`">本次确认或校正理由</label><textarea :id="`${id}-reason`" v-model="reason" :disabled="busy || !current" />
      <label><input v-model="confirmed" type="checkbox" :disabled="busy || !current" />我已核对全部批次数量与保留成本，确认单独登记模拟预算</label>
      <button type="submit" :disabled="!canSubmit">单独确认模拟开仓成本</button>
    </form>
    <p v-if="error" role="alert">{{ error }}</p><p v-if="notice" role="status">{{ notice }}</p>
  </section>
</template>
<style scoped>
.capital-opening, .capital-opening form, .capital-opening__lot { display: grid; gap: var(--space-3); min-width: 0; overflow-wrap: anywhere; }
.capital-opening { border: var(--border-technical); padding: var(--space-3); }
.capital-opening input:not([type="checkbox"]), .capital-opening textarea { box-sizing: border-box; width: 100%; max-width: 100%; }
</style>
