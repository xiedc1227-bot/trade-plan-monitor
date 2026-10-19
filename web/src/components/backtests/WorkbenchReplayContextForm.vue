<script setup lang="ts">
import { reactive, shallowRef } from "vue";
import type { WorkbenchReplayContext } from "../../api/generated";
import { isCalendarDate, isShanghaiDateTime, shanghaiDateTimeKey } from "../../api/shanghaiTime";

defineProps<{ disabled: boolean }>();
const emit = defineEmits<{ confirm: [context: WorkbenchReplayContext] }>();
const effective = shallowRef("");
const available = shallowRef("");
const cutoff = shallowRef("");
const snapshot = shallowRef("");
const inventory = shallowRef("UNKNOWN");
const evidence = shallowRef("");
const confirmed = shallowRef(false);
const error = shallowRef("");
let nextLot = 1;
const lots = reactive<{ key: string; bucket: "CORE" | "TACTICAL"; quantity: string; cost: string; acquired: string; sellable: string }[]>([]);
function addLot() {
  if (lots.length < 200) lots.push({ key: `opening-${nextLot++}`, bucket: "TACTICAL", quantity: "", cost: "", acquired: "", sellable: "" });
}
function timestamp(value: string): string {
  const result = `${value.length === 16 ? `${value}:00` : value}+08:00`;
  if (!isShanghaiDateTime(result)) throw new Error("请填写有效的上海时间。");
  return result;
}
function integer(value: string): number {
  if (!/^(0|[1-9][0-9]*)$/.test(value) || !Number.isSafeInteger(Number(value))) throw new Error("持仓数量和可卖数量须为范围内的非负整数。");
  return Number(value);
}
function costFen(value: string): number | null {
  if (!value) return null;
  if (!/^(0|[1-9][0-9]*)(\.[0-9]{1,2})?$/.test(value)) throw new Error("总成本最多保留两位小数，未知时留空。");
  const [whole = "0", fraction = ""] = value.split(".");
  const fen = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0"));
  if (fen > BigInt(Number.MAX_SAFE_INTEGER)) throw new Error("总成本超出支持范围。");
  return Number(fen);
}
function submit() {
  error.value = "";
  try {
    if (!confirmed.value || !evidence.value.trim() || !isCalendarDate(effective.value)) throw new Error("请填写研究起点、核对依据，并明确确认研究信息。");
    if (inventory.value === "KNOWN" && lots.length === 0) throw new Error("有持仓时请填写持仓批次；空仓须选择“已核对为空仓”。");
    const availableAt = available.value ? timestamp(available.value) : null;
    const informationCutoff = timestamp(cutoff.value), snapshotAt = timestamp(snapshot.value);
    const availableKey = shanghaiDateTimeKey(availableAt ?? `${effective.value}T09:30:00+08:00`)!;
    const dayStart = shanghaiDateTimeKey(`${effective.value}T00:00:00+08:00`)!;
    if (shanghaiDateTimeKey(informationCutoff)! > availableKey) throw new Error("信息截止时间不能晚于历史可用时间。");
    if (shanghaiDateTimeKey(snapshotAt)! > (availableKey > dayStart ? availableKey : dayStart)) throw new Error("期初持仓时间不能晚于研究起点。");
    const accountLots = inventory.value === "KNOWN" ? lots.map(lot => {
      const quantity = integer(lot.quantity);
      const sellable = lot.sellable === "" ? null : integer(lot.sellable);
      if (quantity <= 0 || quantity % 100 || sellable !== null && (sellable % 100 || sellable > quantity)) throw new Error("数量须按100股填写，可卖数量不能超过持仓。");
      if (lot.acquired && !isCalendarDate(lot.acquired)) throw new Error("请填写有效取得日期，未知时留空。");
      return { lot_key: lot.key, bucket: lot.bucket, quantity, cost_basis_fen: costFen(lot.cost), acquired_trade_date: lot.acquired || null, sellable_quantity: sellable, evidence: evidence.value.trim() };
    }) : [];
    emit("confirm", {
      effectiveTradeDate: effective.value, availableAt,
      informationCutoff, confirmed: true, evidence: evidence.value.trim(),
      initialAccount: { snapshot_at: snapshotAt, inventory_known: inventory.value !== "UNKNOWN",
        cash: { kind: "POSITION_LIMIT_ONLY" }, lots: accountLots, opening_mark: null, evidence: evidence.value.trim() },
    });
  } catch (cause) { error.value = cause instanceof Error ? cause.message : "研究信息未通过检查。"; }
}
</script>

<template>
  <form class="research-context" @submit.prevent="submit" novalidate>
    <h2>补充研究起点信息</h2>
    <p>直接复用原计划审核。本次只确认历史时间和期初持仓，不改变规则，也不启用实时监控。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <fieldset :disabled="disabled">
      <legend>历史时间（上海时间）</legend>
      <label for="research-effective-date">计划生效交易日</label><input id="research-effective-date" v-model="effective" type="date" required>
      <label for="research-available">历史可用时间（可选）</label><input id="research-available" v-model="available" type="datetime-local">
      <p>留空按生效日09:30开始研究；这是研究假设，不证明原计划当时已发布。</p>
      <label for="research-cutoff">计划依据的信息截止时间</label><input id="research-cutoff" v-model="cutoff" type="datetime-local" required>
      <label for="research-snapshot">期初持仓对应时间</label><input id="research-snapshot" v-model="snapshot" type="datetime-local" required>
      <label for="research-inventory">期初持仓是否已知</label>
      <select id="research-inventory" v-model="inventory"><option value="UNKNOWN">未知，不能据此模拟交易</option><option value="EMPTY">已核对为空仓</option><option value="KNOWN">已知，有持仓</option></select>
      <p>按计划最大持仓执行，无现金预算；不会读取今天的模拟仓位。</p>
      <section v-if="inventory === 'KNOWN'" aria-label="历史持仓批次">
        <fieldset v-for="(lot, index) in lots" :key="lot.key">
          <legend>持仓批次 {{ index + 1 }}</legend>
          <label>分仓<select v-model="lot.bucket"><option value="TACTICAL">机动仓</option><option value="CORE">核心仓</option></select></label>
          <label>持仓股数<input v-model="lot.quantity" inputmode="numeric"></label>
          <label>持仓总成本（元，未知留空）<input v-model="lot.cost" inputmode="decimal"></label>
          <label>取得日期（未知留空）<input v-model="lot.acquired" type="date"></label>
          <label>可卖股数（未知留空）<input v-model="lot.sellable" inputmode="numeric"></label>
          <button type="button" @click="lots.splice(index, 1)">移除此批次</button>
        </fieldset>
        <button type="button" :disabled="lots.length >= 200" @click="addLot">添加持仓批次</button>
      </section>
      <label for="research-evidence">研究信息的核对依据或明确假设</label><textarea id="research-evidence" v-model="evidence" rows="3" maxlength="2000" required />
      <label class="research-context__confirmation"><input id="research-confirmed" v-model="confirmed" type="checkbox">我已核对以上研究信息；未知项保持未知，研究时间不代表历史发布证明。</label>
      <button type="submit">确认研究起点，继续设置回测</button>
    </fieldset>
  </form>
</template>

<style scoped>
.research-context, .research-context fieldset { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-3); min-width: 0; }
.research-context fieldset { margin: 0; padding: var(--space-2); }
.research-context legend { max-width: 100%; white-space: normal; }
.research-context { padding: var(--space-4); border: var(--border-technical); }
.research-context input, .research-context select, .research-context textarea { box-sizing: border-box; width: 100%; max-width: 100%; min-height: 2.75rem; color: inherit; background: var(--color-surface-raised); border: var(--border-technical); padding: var(--space-2); }
.research-context__confirmation { display: flex; gap: var(--space-2); align-items: center; }
.research-context__confirmation input { width: 1.25rem; flex: 0 0 1.25rem; }
.research-context button { min-height: 2.75rem; padding: var(--space-2); color: inherit; background: var(--color-surface-raised); border: var(--border-technical); }
</style>
