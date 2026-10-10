<script setup lang="ts">
import { onBeforeUnmount, onMounted, useTemplateRef } from "vue";
import {
  isNavigationFailure,
  NavigationFailureType,
  useRoute,
  useRouter,
  type LocationQueryRaw,
} from "vue-router";

import type { BacktestApi } from "../api/backtests";
import BacktestRunFilters from "../components/backtests/BacktestRunFilters.vue";
import BacktestRunTable from "../components/backtests/BacktestRunTable.vue";
import { useBacktestRuns } from "../composables/useBacktestRuns";

interface Props {
  api?: BacktestApi;
}

const props = defineProps<Props>();
const route = useRoute();
const router = useRouter();
const pageTitle = useTemplateRef<HTMLHeadingElement>("pageTitle");
const previousTitle = document.title;

async function replaceQuery(query: LocationQueryRaw): Promise<void> {
  const failure = await router.replace({ path: route.path, query });
  if (
    isNavigationFailure(failure) &&
    !isNavigationFailure(failure, NavigationFailureType.duplicated)
  ) {
    throw new Error("run-list replace navigation failed");
  }
}

async function pushQuery(query: LocationQueryRaw): Promise<void> {
  const failure = await router.push({ path: route.path, query });
  if (
    isNavigationFailure(failure) &&
    !isNavigationFailure(failure, NavigationFailureType.duplicated)
  ) {
    throw new Error("run-list push navigation failed");
  }
}

const runs = useBacktestRuns({
  ...(props.api === undefined ? {} : { api: props.api }),
  pushQuery,
  query: () => route.query,
  replaceQuery,
});

onMounted(() => {
  document.title = "回测运行记录 · Trade Plan Monitor";
  pageTitle.value?.focus();
});

onBeforeUnmount(() => {
  document.title = previousTitle;
});
</script>

<template>
  <div class="backtest-runs-view">
    <header class="backtest-runs-view__hero">
      <div>
        <h1 ref="pageTitle" tabindex="-1">回测运行记录</h1>
        <p>用历史检验规则。查看已完成的回测结果，核对每一次研究运行。</p>
      </div>
      <nav aria-label="回测研究导航">
        <a href="/backtests/new">新建回测</a>
        <a href="/backtests/data">历史数据</a>
      </nav>
    </header>

    <aside class="backtest-runs-view__boundary" aria-label="研究边界">
      所有记录均为历史模拟，仅供研究；不连接券商、不自动下单，也不复用实时监控状态。
    </aside>

    <p
      v-if="runs.announcement.value !== null"
      class="backtest-runs-view__announcement"
      data-testid="run-list-announcement"
      role="status"
      aria-live="polite"
    >
      {{ runs.announcement.value }}
    </p>

    <BacktestRunFilters
      :filters="runs.filters.value"
      :sort="runs.sort.value"
      @apply="runs.applyFilters"
    />

    <BacktestRunTable
      :error-message="runs.errorMessage.value"
      :has-more="runs.hasMore.value"
      :items="runs.items.value"
      :page-number="runs.pageNumber.value"
      :query-state="runs.queryState.value"
      @first-page="runs.firstPage"
      @next-page="runs.nextPage"
      @refresh="runs.refresh"
    />
  </div>
</template>

<style scoped>
.backtest-runs-view {
  display: grid;
  box-sizing: border-box;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--space-6);
  width: min(100%, 90rem);
  margin-inline: auto;
  padding: 0;
  color: var(--color-text-mineral);
}

.backtest-runs-view__hero {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-4);
  padding-block: var(--space-4) var(--space-7);
  border-block-end: var(--border-technical);
}

.backtest-runs-view__hero h1,
.backtest-runs-view__hero p,
.backtest-runs-view__announcement {
  margin: 0;
}

.backtest-runs-view__hero h1 {
  font-size: clamp(1.875rem, 3vw, 2.75rem);
  line-height: 1.3;
}

.backtest-runs-view__hero nav {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.backtest-runs-view__hero a {
  min-height: 2.75rem;
  padding: var(--space-2) var(--space-4);
  border: var(--border-technical);
  background: var(--color-surface-raised);
  color: var(--color-text-mineral);
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  border-radius: var(--radius-control);
}

.backtest-runs-view__boundary,
.backtest-runs-view__announcement {
  padding: var(--space-4);
  border: var(--border-technical);
  background: var(--color-surface-graphite);
  border-radius: var(--radius-control);
  font-size: .8125rem;
}

.backtest-runs-view__boundary {
  border-inline-start: 0.3rem solid var(--color-signal-watch-amber);
}

.backtest-runs-view__announcement {
  border-inline-start: 0.3rem solid var(--color-signal-info-cyan);
}

.backtest-runs-view :focus-visible {
  outline: 0.1875rem solid var(--color-focus-ring);
  outline-offset: 0.1875rem;
}

@media (max-width: 47.9375rem) {
  .backtest-runs-view {
    padding: 0;
  }

  .backtest-runs-view__hero {
    flex-direction: column;
  }
}

@media (max-width: 30rem) {
  .backtest-runs-view {
    padding-inline: 0;
  }
}
</style>
