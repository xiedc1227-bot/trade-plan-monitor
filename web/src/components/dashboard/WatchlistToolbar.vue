<script setup lang="ts">
export type WatchlistFilter =
  | "ALL"
  | "ACTIONABLE"
  | "WATCH"
  | "BLOCKED"
  | "RISK"
  | "STALE"
  | "NORMAL";
export type WatchlistSort = "SYMBOL" | "PRICE" | "RISK_DISTANCE" | "MARKET_TIME" | "HEALTH";
export type SortDirection = "ASC" | "DESC";
export type WatchlistViewMode = "COMPACT" | "COMFORTABLE";

const query = defineModel<string>("query", { required: true });
const filter = defineModel<WatchlistFilter>("filter", { required: true });
const sort = defineModel<WatchlistSort>("sort", { required: true });
const sortDirection = defineModel<SortDirection>("sortDirection", { required: true });
const viewMode = defineModel<WatchlistViewMode>("viewMode", { required: true });
const searchQueryLimit = 128;

function updateQuery(event: Event): void {
  const target = event.currentTarget as HTMLInputElement;
  const bounded = takeCodePoints(target.value, searchQueryLimit);
  query.value = bounded;
  if (target.value !== bounded) {
    target.value = bounded;
  }
}

function takeCodePoints(value: string, limit: number): string {
  let bounded = "";
  let count = 0;
  for (const character of value) {
    if (count === limit) {
      break;
    }
    bounded += character;
    count += 1;
  }
  return bounded;
}

function toggleSortDirection(): void {
  sortDirection.value = sortDirection.value === "ASC" ? "DESC" : "ASC";
}

function toggleViewMode(): void {
  viewMode.value = viewMode.value === "COMPACT" ? "COMFORTABLE" : "COMPACT";
}
</script>

<template>
  <form class="watchlist-toolbar" role="search" @submit.prevent>
    <div class="watchlist-toolbar__field watchlist-toolbar__field--search">
      <label class="watchlist-toolbar__label" for="watchlist-search">搜索股票</label>
      <input
        id="watchlist-search"
        class="watchlist-toolbar__control"
        type="search"
        autocomplete="off"
        maxlength="128"
        placeholder="代码或名称"
        :value="query"
        @input="updateQuery"
      />
    </div>

    <div class="watchlist-toolbar__field">
      <label class="watchlist-toolbar__label" for="watchlist-filter">筛选状态</label>
      <select id="watchlist-filter" v-model="filter" class="watchlist-toolbar__control">
        <option value="ALL">全部</option>
        <option value="ACTIONABLE">可执行</option>
        <option value="WATCH">低吸观察</option>
        <option value="BLOCKED">阻断</option>
        <option value="RISK">风险</option>
        <option value="STALE">陈旧 / 降级</option>
        <option value="NORMAL">正常</option>
      </select>
    </div>

    <div class="watchlist-toolbar__field">
      <label class="watchlist-toolbar__label" for="watchlist-sort">排序字段</label>
      <select id="watchlist-sort" v-model="sort" class="watchlist-toolbar__control">
        <option value="SYMBOL">股票代码</option>
        <option value="PRICE">最新价格</option>
        <option value="RISK_DISTANCE">风险距离</option>
        <option value="MARKET_TIME">行情时间</option>
        <option value="HEALTH">健康状态</option>
      </select>
    </div>

    <div class="watchlist-toolbar__actions">
      <button
        class="watchlist-toolbar__button"
        data-testid="toggle-sort-direction"
        type="button"
        :aria-label="sortDirection === 'ASC' ? '切换为降序' : '切换为升序'"
        @click="toggleSortDirection"
      >
        {{ sortDirection === "ASC" ? "升序 ↑" : "降序 ↓" }}
      </button>
      <button
        class="watchlist-toolbar__button"
        data-testid="toggle-view-mode"
        type="button"
        @click="toggleViewMode"
      >
        {{ viewMode === "COMPACT" ? "舒适视图" : "紧凑视图" }}
      </button>
    </div>
  </form>
</template>

<style scoped>
.watchlist-toolbar {
  display: grid;
  grid-template-columns: minmax(12rem, 2fr) repeat(2, minmax(10rem, 1fr)) auto;
  gap: var(--space-3);
  align-items: end;
  padding: var(--space-4);
  background: var(--color-surface-graphite);
  border: var(--border-technical);
}

.watchlist-toolbar__field {
  display: grid;
  gap: var(--space-1);
}

.watchlist-toolbar__label {
  font-size: 0.8rem;
  font-weight: 700;
}

.watchlist-toolbar__control,
.watchlist-toolbar__button {
  min-height: 2.75rem;
  box-sizing: border-box;
  padding: var(--space-2) var(--space-3);
  color: var(--color-text-mineral);
  background: var(--color-surface-raised);
  border: var(--border-technical);
  border-radius: var(--radius-control);
}

.watchlist-toolbar__actions {
  display: flex;
  gap: var(--space-2);
}

@media (max-width: 63.999rem) {
  .watchlist-toolbar {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .watchlist-toolbar__field--search,
  .watchlist-toolbar__actions {
    grid-column: 1 / -1;
  }
}

@media (max-width: 39.999rem) {
  .watchlist-toolbar {
    grid-template-columns: 1fr;
  }

  .watchlist-toolbar__field--search,
  .watchlist-toolbar__actions {
    grid-column: auto;
  }

  .watchlist-toolbar__actions {
    flex-wrap: wrap;
  }
}
</style>
