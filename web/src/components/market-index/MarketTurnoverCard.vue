<script setup lang="ts">
import { computed } from "vue";

import type { MarketTurnoverSummaryView } from "../../api/generated";

interface Props {
  summary: MarketTurnoverSummaryView | null;
}

const props = defineProps<Props>();

const changeDirection = computed(() => {
  const value = Number(props.summary?.changeAmount);
  if (!Number.isFinite(value) || value === 0) return "flat";
  return value > 0 ? "up" : "down";
});

function formatAmount(value: string | null | undefined, options: { signed?: boolean } = {}): string {
  if (value === null || value === undefined) return "—";
  const amount = Number(value);
  if (!Number.isFinite(amount)) return "—";
  const absolute = Math.abs(amount);
  const sign = options.signed && amount > 0 ? "+" : "";
  if (absolute >= 1_000_000_000_000) {
    return `${sign}${new Intl.NumberFormat("zh-CN", {
      maximumFractionDigits: 2,
      minimumFractionDigits: 2,
    }).format(amount / 1_000_000_000_000)}万亿`;
  }
  return `${sign}${new Intl.NumberFormat("zh-CN", {
    maximumFractionDigits: 0,
    useGrouping: false,
  }).format(amount / 100_000_000)}亿`;
}
</script>

<template>
  <aside
    class="market-turnover-card"
    data-testid="market-turnover-card"
    aria-labelledby="market-turnover-title"
  >
    <h3 id="market-turnover-title">沪深市场成交额</h3>
    <dl>
      <div>
        <dt>今日累计成交额</dt>
        <dd class="market-turnover-card__primary">{{ formatAmount(summary?.currentAmount) }}</dd>
      </div>
      <div>
        <dt>较上一日</dt>
        <dd :data-direction="changeDirection">{{ formatAmount(summary?.changeAmount, { signed: true }) }}</dd>
      </div>
      <div class="market-turnover-card__estimate">
        <dt>预测全天成交额</dt>
        <dd>{{ formatAmount(summary?.estimatedFullDayAmount) }}</dd>
      </div>
    </dl>
    <p v-if="summary === null" class="market-turnover-card__empty">暂无成交额数据</p>
  </aside>
</template>

<style scoped>
.market-turnover-card {
  display: grid;
  align-content: start;
  gap: var(--space-3);
  min-width: 0;
  padding: var(--space-4);
  background: var(--color-surface-raised);
  border-inline-start: var(--border-technical);
}

.market-turnover-card h3,
.market-turnover-card dl,
.market-turnover-card dd,
.market-turnover-card__empty {
  margin: 0;
}

.market-turnover-card dl {
  display: grid;
  gap: var(--space-3);
}

.market-turnover-card dl > div {
  display: grid;
  gap: var(--space-1);
}

.market-turnover-card dt,
.market-turnover-card__empty {
  color: var(--color-text-muted);
}

.market-turnover-card dd {
  color: var(--color-text-mineral);
  font-family: var(--font-numeric);
  font-size: 1.1rem;
  font-weight: 700;
}

.market-turnover-card__primary,
.market-turnover-card__estimate dd {
  font-size: 1.45rem;
}

.market-turnover-card__estimate {
  padding-block-start: var(--space-3);
  border-block-start: var(--border-technical);
}

.market-turnover-card dd[data-direction="up"] {
  color: var(--color-signal-risk-vermilion);
}

.market-turnover-card dd[data-direction="down"] {
  color: var(--color-signal-live-sea-glass);
}

.market-turnover-card dd[data-direction="flat"] {
  color: var(--color-text-mineral);
}

.market-turnover-card__empty {
  font-size: .85rem;
  line-height: 1.5;
}

@media (max-width: 69.999rem) {
  .market-turnover-card {
    border-block-start: var(--border-technical);
    border-inline-start: 0;
  }

  .market-turnover-card dl {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .market-turnover-card__estimate {
    padding-block-start: 0;
    padding-inline-start: var(--space-3);
    border-block-start: 0;
    border-inline-start: var(--border-technical);
  }
}

@media (max-width: 39.999rem) {
  .market-turnover-card dl {
    grid-template-columns: minmax(0, 1fr);
  }

  .market-turnover-card__estimate {
    padding-block-start: var(--space-3);
    padding-inline-start: 0;
    border-block-start: var(--border-technical);
    border-inline-start: 0;
  }
}
</style>
