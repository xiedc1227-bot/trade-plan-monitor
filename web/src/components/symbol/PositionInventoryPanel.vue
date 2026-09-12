<script setup lang="ts">
import { computed, shallowRef, watch } from "vue";

import type { PositionInventoryView } from "../../api/generated";
import type { PositionInventoryApi } from "../../api/positions";

interface Props {
  api: PositionInventoryApi;
  asOfTradeDate: string | null;
  symbol: string | null;
}

const props = defineProps<Props>();
const inventory = shallowRef<PositionInventoryView | null>(null);
const loading = shallowRef(false);
const error = shallowRef<string | null>(null);
const totalQuantity = shallowRef("");
const sellableQuantity = shallowRef("");
const completeRegistration = shallowRef(false);
const closureSourceId = shallowRef("");
const closureQuantity = shallowRef("");
const closing = shallowRef(false);
let generation = 0;

const canLoad = computed(() => props.symbol !== null && props.asOfTradeDate !== null);
const openingBalances = computed(() => inventory.value?.openingBalances ?? []);
const canConfirm = computed(() => {
  const total = parseBoardLot(totalQuantity.value);
  const sellable = parseBoardLot(sellableQuantity.value);
  return !loading.value && !closing.value && completeRegistration.value && total !== null &&
    sellable !== null && sellable <= total && canLoad.value;
});
const selectedOpeningBalance = computed(
  () => openingBalances.value.find((item) => item.openingBalanceId === closureSourceId.value) ?? null,
);
const canClose = computed(() => {
  const quantity = parseBoardLot(closureQuantity.value);
  return !loading.value && !closing.value && inventory.value?.status === "KNOWN" &&
    selectedOpeningBalance.value !== null && quantity !== null &&
    quantity <= selectedOpeningBalance.value.remainingQuantity && canLoad.value;
});

watch([() => props.symbol, () => props.asOfTradeDate], () => { void load(); }, { immediate: true });

async function load(): Promise<void> {
  const symbol = props.symbol;
  const asOfTradeDate = props.asOfTradeDate;
  const current = ++generation;
  inventory.value = null;
  error.value = null;
  if (symbol === null || asOfTradeDate === null) return;
  loading.value = true;
  try {
    const result = await props.api.getInventory(symbol, asOfTradeDate);
    if (current !== generation) return;
    inventory.value = result;
    totalQuantity.value = result.totalQuantity === null ? "" : String(result.totalQuantity);
    sellableQuantity.value = result.sellableQuantity === null ? "" : String(result.sellableQuantity);
    closureSourceId.value = result.openingBalances?.[0]?.openingBalanceId ?? "";
  } catch {
    if (current === generation) error.value = "独立库存读取失败；不会从提醒或原文推测持仓。";
  } finally {
    if (current === generation) loading.value = false;
  }
}

async function confirm(): Promise<void> {
  const symbol = props.symbol;
  const asOfTradeDate = props.asOfTradeDate;
  const current = inventory.value;
  const total = parseBoardLot(totalQuantity.value);
  const sellable = parseBoardLot(sellableQuantity.value);
  if (symbol === null || asOfTradeDate === null || current === null || total === null || sellable === null || !canConfirm.value) return;
  loading.value = true;
  error.value = null;
  try {
    inventory.value = await props.api.confirmInventory({
      asOfTradeDate,
      completeRegistration: true,
      expectedRevision: current.inventoryRevision,
      includedLotIds: current.includedLotIds ?? [],
      sellableQuantity: sellable,
      symbol,
      totalQuantity: total,
    }, `inventory-confirm-${symbol}-${current.inventoryRevision}`);
    completeRegistration.value = false;
  } catch {
    error.value = "库存登记未确认；请刷新后以当前库存修订重试。";
  } finally {
    loading.value = false;
  }
}

async function closeOpeningBalance(): Promise<void> {
  const current = inventory.value;
  const source = selectedOpeningBalance.value;
  const quantity = parseBoardLot(closureQuantity.value);
  const tradeDate = props.asOfTradeDate;
  if (current === null || source === null || quantity === null || tradeDate === null || !canClose.value) return;
  closing.value = true;
  error.value = null;
  try {
    await props.api.closeInventory({
      expectedRevision: source.revision,
      quantity,
      sourceId: source.openingBalanceId,
      sourceType: "OPENING_BALANCE",
      tradeDate,
    }, `inventory-close-${source.openingBalanceId}-${source.revision}-${quantity}`);
    closureQuantity.value = "";
    await load();
  } catch {
    error.value = "成交减记未确认；提醒已读不会改变库存，请刷新后按当前批次修订重试。";
  } finally {
    closing.value = false;
  }
}

function parseBoardLot(value: string): number | null {
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed >= 0 && parsed % 100 === 0 ? parsed : null;
}
</script>

<template>
  <section class="position-inventory" aria-labelledby="position-inventory-title">
    <header>
      <h2 id="position-inventory-title">独立库存登记与成交减记</h2>
      <p>原文“持仓”只是断言；提醒及已读均不改变库存。登记与成交减记是两个独立、可审计的操作。</p>
    </header>
    <p v-if="loading" role="status">正在读取库存账本。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-if="inventory">
      <dl>
        <div><dt>状态</dt><dd>{{ inventory.status === "KNOWN" ? "已登记" : "未知" }}</dd></div>
        <div><dt>总股数</dt><dd>{{ inventory.totalQuantity ?? "未知" }}</dd></div>
        <div><dt>可卖股数</dt><dd>{{ inventory.sellableQuantity ?? "未知（可能受 T+1 限制）" }}</dd></div>
        <div><dt>库存修订</dt><dd>{{ inventory.inventoryRevision }}</dd></div>
      </dl>
      <form @submit.prevent="confirm">
        <h3>完整登记当前库存</h3>
        <p>登记总数、可卖数和完整性确认；100 股整手约束适用。没有交易日历时，可卖数不会被猜测。</p>
        <label>总股数 <input v-model="totalQuantity" inputmode="numeric" required /></label>
        <label>可卖股数 <input v-model="sellableQuantity" inputmode="numeric" required /></label>
        <label><input v-model="completeRegistration" type="checkbox" /> 我确认已完整登记该股票的当前库存</label>
        <button type="submit" :disabled="!canConfirm">保存独立库存登记</button>
      </form>
      <form v-if="openingBalances.length > 0" @submit.prevent="closeOpeningBalance">
        <h3>登记实际成交减记</h3>
        <p>仅在真实成交已发生时登记。此操作不会由提醒或提醒确认触发。</p>
        <label>来源
          <select v-model="closureSourceId">
            <option v-for="item in openingBalances" :key="item.openingBalanceId" :value="item.openingBalanceId">
              开仓余额 {{ item.remainingQuantity }} 股（可卖自 {{ item.sellableFrom }}）
            </option>
          </select>
        </label>
        <label>实际成交股数 <input v-model="closureQuantity" inputmode="numeric" required /></label>
        <button type="submit" :disabled="!canClose">登记成交减记</button>
      </form>
    </template>
  </section>
</template>

<style scoped>
.position-inventory { display: grid; gap: var(--space-3); padding: var(--space-4); background: var(--color-surface-graphite); border: var(--border-technical); }
.position-inventory dl { display: grid; grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr)); gap: var(--space-2); margin: 0; }
.position-inventory dt { color: var(--color-text-muted); }
.position-inventory dd { margin: var(--space-1) 0 0; font-family: var(--font-numeric); }
.position-inventory form { display: grid; gap: var(--space-2); padding-block-start: var(--space-3); border-block-start: var(--border-technical); }
.position-inventory label { display: grid; gap: var(--space-1); }
.position-inventory input, .position-inventory select, .position-inventory button { min-height: 2.75rem; }
</style>
