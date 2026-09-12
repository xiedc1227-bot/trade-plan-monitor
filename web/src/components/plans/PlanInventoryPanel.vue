<script setup lang="ts">
import { shallowRef } from "vue";
import { createPositionApi } from "../../api/positions";
import PositionInventoryPanel from "../symbol/PositionInventoryPanel.vue";

defineProps<{ symbol: string }>();
const date = shallowRef("");
const api = createPositionApi();
</script>

<template>
  <section aria-label="计划独立库存">
    <label>库存登记交易日 <input v-model="date" type="date" /></label>
    <p>请先选择登记日期，再核对实际总股数与当日可卖股数。</p>
    <PositionInventoryPanel v-if="date" :key="`${symbol}-${date}`" :api="api" :symbol="symbol" :as-of-trade-date="date" />
  </section>
</template>
