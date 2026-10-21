<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, useTemplateRef, watch } from "vue";
import {
  isNavigationFailure,
  NavigationFailureType,
  useRoute,
  useRouter,
  type LocationQueryRaw,
} from "vue-router";

import { createBacktestApi, type BacktestApi } from "../api/backtests";
import BacktestReadFeedback from "../components/backtests/BacktestReadFeedback.vue";
import BacktestTaskWorkspace from "../components/backtests/BacktestTaskWorkspace.vue";
import { backtestReturnTarget, rememberBacktestReturn } from "../composables/backtestNavigation";
import BacktestRunFilters from "../components/backtests/BacktestRunFilters.vue";
import BacktestRunTable from "../components/backtests/BacktestRunTable.vue";
import { useBacktestRuns } from "../composables/useBacktestRuns";

interface Props {
  api?: BacktestApi;
}

const props = defineProps<Props>();
const api = props.api ?? createBacktestApi();
const route = useRoute();
const router = useRouter();
const pageTitle = useTemplateRef<HTMLHeadingElement>("pageTitle");
function openResult(runId: string, event: MouseEvent) {
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
  event.preventDefault(); rememberBacktestReturn(route.fullPath, runId);
  void router.push(`/backtests/${runId}`);
}
const previousTitle = document.title;
const tasksView = computed(() => route.query.view === "tasks");

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
  enabled: () => !tasksView.value,
  ...(props.api === undefined ? {} : { api: props.api }),
  pushQuery,
  query: () => route.query,
  replaceQuery,
});

onMounted(async () => {
  document.title = "回测运行记录 · Trade Plan Monitor";
  pageTitle.value?.focus();
  await nextTick();
});

watch(runs.queryState, async state => {
  if (state !== "READY") return;
  await nextTick();
  const target = backtestReturnTarget();
  if (target.path === route.fullPath && /^[a-f0-9]{64}$/.test(target.runId)) {
    document.querySelector<HTMLElement>(`[data-run-id="${target.runId}"]`)?.focus();
    rememberBacktestReturn(target.path, "");
  }
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
        <p>查找回测结果，查看任务进度与记录。</p>
      </div>
      <nav aria-label="回测研究导航">
        <a href="/backtests/new">新建回测</a>

      </nav>
    </header>

    <p class="backtest-runs-view__research">历史模拟，仅供研究，不连接券商、不自动下单。</p>
    <nav class="backtest-runs-view__switch" aria-label="回测记录类型">
      <RouterLink to="/backtests" :aria-current="!tasksView ? 'page' : undefined">结果</RouterLink>
      <RouterLink data-testid="task-workspace-link" to="/backtests?view=tasks" :aria-current="tasksView ? 'page' : undefined">任务</RouterLink>
    </nav>
    <BacktestTaskWorkspace v-if="tasksView" :api="api" />
    <template v-else>
    <BacktestReadFeedback :slow="runs.feedback.slow.value" :timed-out="runs.feedback.timedOut.value" :refreshing="runs.refreshing.value" :last-success="runs.feedback.lastSuccess.value" @retry="runs.refresh" />

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
      :has-previous="runs.hasPrevious.value" :has-filters="runs.hasFilters.value" :refreshing="runs.refreshing.value"
      @previous-page="runs.previousPage" @open="openResult"
      :has-more="runs.hasMore.value"
      :items="runs.items.value"
      :page-number="runs.pageNumber.value"
      :query-state="runs.queryState.value"
      @first-page="runs.firstPage"
      @next-page="runs.nextPage"
      @refresh="runs.refresh"
    />
    </template>
  </div>
</template>

<style scoped>
.backtest-runs-view__research { margin: 0; font-size: .8125rem; color: var(--color-text-muted); }
.backtest-runs-view__switch { display: flex; gap: var(--space-2); }
.backtest-runs-view__switch a { min-height: 44px; display: inline-flex; align-items: center; padding-inline: var(--space-4); color: inherit; border: var(--border-technical); }
.backtest-runs-view__switch a[aria-current] { background: var(--color-surface-raised); border-bottom-color: var(--color-signal-watch-amber); }
.backtest-runs-view {
  display: grid;
  box-sizing: border-box;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--space-3);
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
  padding-block: 0 var(--space-3);
  border-block-end: var(--border-technical);
}

.backtest-runs-view__hero h1,
.backtest-runs-view__hero p,
.backtest-runs-view__announcement {
  margin: 0;
}

.backtest-runs-view__hero h1 {
  font-size: clamp(1.5rem, 2.4vw, 2rem);
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
