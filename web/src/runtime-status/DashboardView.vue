<script setup lang="ts">
import MarketTurnoverCard from "../components/market-index/MarketTurnoverCard.vue";
import { useRuntimeContext } from "./context";
import StatusBoard from "./StatusBoard.vue";
import PlanRow from "./PlanRow.vue";
import { displayTime } from "./presentation";
const { store } = useRuntimeContext();
const counts = { actionable: "当前提醒", blocked: "受阻", stale: "陈旧", risk: "风险", lowZoneWatch: "低吸观察", normal: "正常" };
</script>

<template>
  <section class="runtime-page">
    <h1>监控总览</h1>
    <p v-if="store.error" role="status">{{ store.error }}</p>
    <StatusBoard v-if="store.runtimeStatus" :status="store.runtimeStatus" />
    <p v-if="!store.snapshot" role="status">正在读取监控快照。</p>
    <template v-else>
      <dl class="runtime-counts" aria-label="后端快照统计">
        <div v-for="(label, key) in counts" :key="key"><dt>{{ label }}</dt><dd>{{ store.snapshot.counts[key] }}</dd></div>
      </dl>
      <section v-if="store.snapshot.marketIndexes.length" class="runtime-panel" aria-label="指数快照">
        <h2>指数快照</h2>
        <ul><li v-for="index in store.snapshot.marketIndexes" :key="index.indexCode">{{ index.displayName }} · {{ index.health }} · {{ index.closePoints ?? '—' }} · 截止 {{ displayTime(index.completedBucketAt) }}</li></ul>
      </section>
      <MarketTurnoverCard v-if="store.snapshot.marketTurnover" :summary="store.snapshot.marketTurnover" />
      <p v-if="!store.snapshot.symbols.length">没有活动计划。可前往计划工作台核对并启用计划。</p>
      <PlanRow v-for="row in store.snapshot.symbols" :key="`${row.symbol}:${row.activationRevision}`" :row="row" />
    </template>
  </section>
</template>
