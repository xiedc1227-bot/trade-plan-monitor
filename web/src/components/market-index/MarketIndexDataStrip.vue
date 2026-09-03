<script setup lang="ts">
import type {
  MarketIndexHealth,
  MarketIndexSnapshotView,
  ReturnIndicatorFactView,
  SmaIndicatorFactView,
  SmaLookbackIndicatorFactView,
} from "../../api/generated";

interface Props {
  indexes: readonly MarketIndexSnapshotView[];
}

defineProps<Props>();

type IndicatorFact =
  | ReturnIndicatorFactView
  | SmaIndicatorFactView
  | SmaLookbackIndicatorFactView;

const healthLabels: Readonly<Record<MarketIndexHealth, string>> = Object.freeze({
  BLOCKED: "阻断 ×",
  GAPPED: "缺口 !",
  LIVE: "实时 ●",
  STALE: "陈旧 !",
});

function factLabel(fact: IndicatorFact): string {
  if (fact.formulaId === "SMA") {
    return `SMA ${fact.period}`;
  }
  if (fact.formulaId === "SMA_LOOKBACK") {
    return `SMA ${fact.period} / 回看 ${fact.lookback}`;
  }
  return `RETURN ${fact.window} ${fact.windowSize}`;
}
</script>

<template>
  <section class="index-strip" aria-labelledby="market-index-strip-title">
    <header class="index-strip__header">
      <h2 id="market-index-strip-title">参考板块指数：共用数据</h2>
      <p>仅展示后端提供的原始数据与通用指标</p>
    </header>
    <p v-if="indexes.length === 0" class="index-strip__empty">当前没有共用指数快照。</p>
    <div v-else class="index-strip__grid">
      <article
        v-for="item in indexes"
        :key="item.indexCode"
        class="index-strip__card"
        data-testid="market-index-card"
        :data-health="item.health"
      >
        <header>
          <h3>{{ item.displayName }}</h3>
          <code>{{ item.indexCode }}</code>
        </header>
        <strong>{{ healthLabels[item.health] }}</strong>
        <dl>
          <div><dt>最新点位</dt><dd>{{ item.closePoints ?? "—" }}</dd></div>
          <div><dt>昨收点位</dt><dd>{{ item.priorClosePoints ?? "—" }}</dd></div>
          <div><dt>会话涨跌比例</dt><dd>{{ item.sessionChangeRatio ?? "—" }}</dd></div>
          <div><dt>数据截止</dt><dd>{{ item.completedBucketAt ?? "不可用" }}</dd></div>
          <div><dt>映射股票</dt><dd>{{ item.mappedSymbolCount }}</dd></div>
        </dl>
        <ul v-if="(item.indicatorFacts ?? []).length > 0" aria-label="通用指标事实">
          <li v-for="fact in item.indicatorFacts ?? []" :key="JSON.stringify(fact)">
            {{ factLabel(fact) }}：{{ fact.value }} {{ fact.unit }}
          </li>
        </ul>
        <p v-if="(item.issues ?? []).length > 0" class="index-strip__issues">
          问题：{{ (item.issues ?? []).join("、") }}
        </p>
      </article>
    </div>
  </section>
</template>

<style scoped>
.index-strip {
  display: grid;
  gap: var(--space-3);
}

.index-strip__header,
.index-strip__card header {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2) var(--space-4);
  align-items: baseline;
  justify-content: space-between;
}

.index-strip__header p,
.index-strip__empty,
.index-strip__issues {
  margin: 0;
  color: var(--color-text-muted);
}

.index-strip__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 17rem), 1fr));
  gap: var(--space-3);
}

.index-strip__card {
  padding: var(--space-4);
  background: var(--color-surface-graphite);
  border: var(--border-technical);
  border-inline-start: 0.25rem solid var(--color-signal-live-sea-glass);
}

.index-strip__card[data-health="BLOCKED"],
.index-strip__card[data-health="GAPPED"] {
  border-inline-start-color: var(--color-signal-risk-vermilion);
}

.index-strip__card[data-health="STALE"] {
  border-inline-start-color: var(--color-signal-watch-amber);
}

.index-strip__card dl,
.index-strip__card dl div {
  display: grid;
  gap: var(--space-1);
}

.index-strip__card dl {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.index-strip__card dd {
  margin: 0;
  overflow-wrap: anywhere;
  font-family: var(--font-numeric);
}

.index-strip__card ul {
  padding-inline-start: var(--space-4);
}
</style>
