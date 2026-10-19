<script setup lang="ts">
import type {
  BacktestDatasetVerificationJobResultView,
  BacktestDatasetView,
} from "../../api/generated";
import type { BacktestDataQueryState } from "../../composables/useBacktestData";
import { formatDisplayDateTime } from "../../formatters/dateTime";

interface Props {
  datasets: readonly BacktestDatasetView[];
  errorMessage?: string | null;
  hasMore: boolean;
  queryState: BacktestDataQueryState;
  verification?: BacktestDatasetVerificationJobResultView | null;
}

interface Emits {
  nextPage: [];
  refresh: [];
}

withDefaults(defineProps<Props>(), {
  errorMessage: null,
  verification: null,
});
const emit = defineEmits<Emits>();

const countLabels: ReadonlyArray<{
  key:
    | "calendarRowCount"
    | "dailyBarRowCount"
    | "dailyLimitRowCount"
    | "minuteBarCount"
    | "minuteDayCount"
    | "symbolCount"
    | "tradingDayCount";
  label: string;
}> = [
  { key: "symbolCount", label: "标的" },
  { key: "tradingDayCount", label: "交易日" },
  { key: "minuteDayCount", label: "分钟交易日" },
  { key: "minuteBarCount", label: "分钟记录" },
  { key: "calendarRowCount", label: "日历记录" },
  { key: "dailyBarRowCount", label: "日线记录" },
  { key: "dailyLimitRowCount", label: "涨跌停记录" },
];
</script>

<template>
  <section class="dataset-coverage" aria-labelledby="dataset-coverage-title">
    <header class="dataset-coverage__header">
      <div>
        <h2 id="dataset-coverage-title">数据覆盖与已验证数据集</h2>
      </div>
      <p>浏览器只展示服务端计数和 blocker，不推断交易日或数据完整性。</p>
    </header>

    <section
      v-if="verification !== null"
      class="dataset-coverage__verification"
      data-testid="verification-result"
      aria-labelledby="verification-result-title"
    >
      <h3 id="verification-result-title">最近一次服务端验证结果</h3>
      <strong>{{ verification.ready ? "服务端判定：可用于回测" : "服务端判定：尚不可用于回测" }}</strong>
      <p>数据集哈希：{{ verification.datasetHash ?? "未生成" }}</p>
      <dl class="dataset-coverage__counts" aria-label="最近一次验证覆盖计数">
        <div v-for="count in countLabels" :key="count.key">
          <dt>{{ count.label }}</dt>
          <dd>{{ verification.coverage[count.key] }}</dd>
        </div>
      </dl>
      <ul v-if="verification.blockers.length > 0">
        <li v-for="blocker in verification.blockers" :key="blocker">{{ blocker }}</li>
      </ul>
    </section>

    <div
      v-if="queryState === 'LOADING'"
      class="dataset-coverage__state"
      data-testid="dataset-loading"
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      正在读取一页已验证数据集
    </div>

    <div v-else-if="queryState === 'FAILED'" class="dataset-coverage__state" role="alert">
      <p>{{ errorMessage ?? "数据集列表暂不可用，请稍后重试" }}</p>
      <button type="button" @click="emit('refresh')">重新读取数据集列表</button>
    </div>

    <p
      v-else-if="queryState === 'EMPTY'"
      class="dataset-coverage__state"
      data-testid="dataset-empty"
    >
      尚无已验证数据集。开始回测时，程序会自动检查、补齐并验证所需数据。
    </p>

    <div v-else-if="datasets.length > 0" class="dataset-coverage__list">
      <article
        v-for="item in datasets"
        :key="item.datasetHash"
        class="dataset-coverage__item"
        data-testid="dataset-card"
      >
        <header class="dataset-coverage__item-header">
          <div>
            <h3>{{ item.scope.symbols.join("、") }}</h3>
            <p>{{ item.scope.warmupStart }} → {{ item.scope.start }} → {{ item.scope.end }}</p>
          </div>
          <p class="dataset-coverage__hash">{{ item.datasetHash }}</p>
        </header>

        <dl class="dataset-coverage__counts">
          <div v-for="count in countLabels" :key="count.key">
            <dt>{{ count.label }}</dt>
            <dd>{{ item.coverage[count.key] }}</dd>
          </div>
        </dl>

        <div class="dataset-coverage__metadata">
          <p>Schema：{{ item.schemaVersion }}</p>
          <p>创建：<time :datetime="item.createdAt">{{ formatDisplayDateTime(item.createdAt) }}</time></p>
          <p>验证：<time :datetime="item.verifiedAt">{{ formatDisplayDateTime(item.verifiedAt) }}</time></p>
        </div>

        <section class="dataset-coverage__blockers" aria-label="服务端阻断项">
          <h4>服务端阻断项</h4>
          <p v-if="item.coverage.blockers.length === 0">无</p>
          <ul v-else>
            <li v-for="blocker in item.coverage.blockers" :key="blocker">{{ blocker }}</li>
          </ul>
        </section>
      </article>
    </div>

    <footer v-if="datasets.length > 0" class="dataset-coverage__footer">
      <p>当前仅保留服务端返回的一页，页面不会累积无界结果。</p>
      <button
        v-if="hasMore"
        data-testid="next-dataset-page"
        type="button"
        aria-label="读取下一页已验证数据集"
        @click="emit('nextPage')"
      >
        下一页
      </button>
    </footer>
  </section>
</template>

<style scoped>
.dataset-coverage {
  display: grid;
  gap: var(--space-6);
}

.dataset-coverage__header,
.dataset-coverage__item-header,
.dataset-coverage__footer {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
}

.dataset-coverage__header h2,
.dataset-coverage__header p,
.dataset-coverage__item h3,
.dataset-coverage__item p,
.dataset-coverage__verification h3,
.dataset-coverage__verification p,
.dataset-coverage__blockers h4,
.dataset-coverage__footer p {
  margin: 0;
}

.dataset-coverage__verification,
.dataset-coverage__state,
.dataset-coverage__item {
  padding: var(--space-4);
  border: var(--border-technical);
  background: var(--color-surface-graphite);
}

.dataset-coverage__verification {
  border-inline-start: 4px solid var(--color-signal-info-cyan);
}

.dataset-coverage__state button,
.dataset-coverage__footer button {
  min-height: 2.75rem;
  padding: 0 var(--space-4);
  border: var(--border-technical);
  background: var(--color-surface-raised);
  color: var(--color-text-mineral);
}

.dataset-coverage__list {
  display: grid;
  gap: var(--space-4);
}

.dataset-coverage__hash {
  max-width: 26rem;
  overflow-wrap: anywhere;
  color: var(--color-text-muted);
  font-family: var(--font-numeric);
  font-size: 0.75rem;
}

.dataset-coverage__counts {
  display: grid;
  grid-template-columns: repeat(7, minmax(5rem, 1fr));
  gap: var(--space-2);
  margin: var(--space-4) 0;
}

.dataset-coverage__counts div {
  padding: var(--space-3);
  border-block-start: 2px solid var(--color-border-quiet);
}

.dataset-coverage__counts dt {
  color: var(--color-text-muted);
  font-size: 0.75rem;
}

.dataset-coverage__counts dd {
  margin: var(--space-1) 0 0;
  font-variant-numeric: tabular-nums;
  font-weight: 700;
}

.dataset-coverage__metadata {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2) var(--space-6);
  color: var(--color-text-muted);
  font-size: 0.875rem;
}

.dataset-coverage__blockers {
  margin-top: var(--space-4);
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-border-quiet);
}

.dataset-coverage button:focus-visible {
  outline: 3px solid var(--color-focus-ring);
  outline-offset: 2px;
}

@media (max-width: 1023px) {
  .dataset-coverage__counts {
    grid-template-columns: repeat(4, minmax(5rem, 1fr));
  }
}

@media (max-width: 767px) {
  .dataset-coverage__header,
  .dataset-coverage__item-header,
  .dataset-coverage__footer {
    flex-direction: column;
  }

  .dataset-coverage__counts {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
