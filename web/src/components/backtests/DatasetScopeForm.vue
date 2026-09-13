<script setup lang="ts">
import { nextTick, shallowRef, useTemplateRef, watch } from "vue";

import type { BacktestDatasetScopeInput } from "../../api/generated";
import { isCalendarDate } from "../../api/shanghaiTime";
import type {
  BacktestDataSubmissionState,
  DatasetUrlFilters,
} from "../../composables/useBacktestData";

interface Props {
  filters: DatasetUrlFilters;
  scope: BacktestDatasetScopeInput | null;
  submissionState: BacktestDataSubmissionState;
}

interface Emits {
  applyFilters: [filters: DatasetUrlFilters];
  applyScope: [scope: BacktestDatasetScopeInput];
  requestSync: [scope: BacktestDatasetScopeInput, refresh: boolean];
  requestVerify: [scope: BacktestDatasetScopeInput];
}

type ScopeField = "symbols" | "warmupStart" | "start" | "end";

const props = defineProps<Props>();
const emit = defineEmits<Emits>();
const errorSummary = useTemplateRef<HTMLHeadingElement>("errorSummary");
const syncTrigger = useTemplateRef<HTMLButtonElement>("syncTrigger");
const confirmSync = useTemplateRef<HTMLButtonElement>("confirmSync");
const dismissSync = useTemplateRef<HTMLButtonElement>("dismissSync");

const symbolsDraft = shallowRef("");
const warmupStartDraft = shallowRef("");
const startDraft = shallowRef("");
const endDraft = shallowRef("");
const filterSymbolDraft = shallowRef("");
const filterStartDraft = shallowRef("");
const filterEndDraft = shallowRef("");
const refreshDraft = shallowRef(false);
const errors = shallowRef<Partial<Record<ScopeField, string>>>({});
const filterError = shallowRef<string | null>(null);
const confirmationOpen = shallowRef(false);
const pendingScope = shallowRef<BacktestDatasetScopeInput | null>(null);

watch(
  () => props.scope,
  (scope) => {
    symbolsDraft.value = scope?.symbols.join(",") ?? "";
    warmupStartDraft.value = scope?.warmupStart ?? "";
    startDraft.value = scope?.start ?? "";
    endDraft.value = scope?.end ?? "";
    errors.value = {};
  },
  { deep: true, immediate: true },
);

watch(
  () => props.filters,
  (filters) => {
    filterSymbolDraft.value = filters.symbol ?? "";
    filterStartDraft.value = filters.startOnOrAfter ?? "";
    filterEndDraft.value = filters.endOnOrBefore ?? "";
    filterError.value = null;
  },
  { deep: true, immediate: true },
);

function calendarYearsAfter(value: string, years: number): string {
  const year = Number(value.slice(0, 4)) + years;
  const monthDay = value.slice(4);
  return `${String(year).padStart(4, "0")}${monthDay}`;
}

function parseSymbols(value: string): readonly string[] | null {
  const symbols = value
    .split(",")
    .map((item) => item.trim().toUpperCase())
    .filter((item) => item.length > 0);
  if (
    symbols.length < 1 ||
    symbols.length > 10 ||
    symbols.some((symbol) => !/^[0-9]{6}\.(?:SH|SZ)$/.test(symbol)) ||
    new Set(symbols).size !== symbols.length
  ) {
    return null;
  }
  return Object.freeze([...symbols].sort());
}

async function focusErrors(): Promise<void> {
  await nextTick();
  errorSummary.value?.focus();
}

function validateScope(): BacktestDatasetScopeInput | null {
  const nextErrors: Partial<Record<ScopeField, string>> = {};
  const symbols = parseSymbols(symbolsDraft.value);
  if (symbols === null) {
    nextErrors.symbols = "请输入 1 至 10 个不重复的 .SH 或 .SZ A 股代码，以逗号分隔";
  }
  if (!isCalendarDate(warmupStartDraft.value)) {
    nextErrors.warmupStart = "预热开始日期必须是有效的 YYYY-MM-DD";
  }
  if (!isCalendarDate(startDraft.value)) {
    nextErrors.start = "回测开始日期必须是有效的 YYYY-MM-DD";
  }
  if (!isCalendarDate(endDraft.value)) {
    nextErrors.end = "回测结束日期必须是有效的 YYYY-MM-DD";
  }
  if (
    nextErrors.warmupStart === undefined &&
    nextErrors.start === undefined &&
    warmupStartDraft.value > startDraft.value
  ) {
    nextErrors.warmupStart = "预热开始日期不得晚于回测开始日期";
  }
  if (
    nextErrors.start === undefined &&
    nextErrors.end === undefined &&
    startDraft.value > endDraft.value
  ) {
    nextErrors.end = "回测结束日期不得早于开始日期";
  }
  if (
    nextErrors.start === undefined &&
    nextErrors.end === undefined &&
    endDraft.value > calendarYearsAfter(startDraft.value, 5)
  ) {
    nextErrors.end = "回测范围最长为五个日历年";
  }
  if (
    nextErrors.warmupStart === undefined &&
    nextErrors.start === undefined &&
    startDraft.value > calendarYearsAfter(warmupStartDraft.value, 2)
  ) {
    nextErrors.warmupStart = "预热范围最长为两个日历年";
  }
  errors.value = nextErrors;
  if (Object.keys(nextErrors).length > 0 || symbols === null) {
    void focusErrors();
    return null;
  }
  return Object.freeze({
    adjustmentPolicy: "NONE",
    end: endDraft.value,
    historicalProfile: "TUSHARE_STK_MINS_241_END_V1",
    start: startDraft.value,
    symbols: [...symbols],
    warmupStart: warmupStartDraft.value,
  });
}

function validateFilters(): DatasetUrlFilters | null {
  const symbol = filterSymbolDraft.value.trim().toUpperCase();
  const start = filterStartDraft.value.trim();
  const end = filterEndDraft.value.trim();
  if (symbol.length > 0 && !/^[0-9]{6}\.(?:SH|SZ)$/.test(symbol)) {
    filterError.value = "筛选代码必须是 .SH 或 .SZ A 股代码";
    return null;
  }
  if ((start.length > 0 && !isCalendarDate(start)) || (end.length > 0 && !isCalendarDate(end))) {
    filterError.value = "筛选日期必须是有效的 YYYY-MM-DD";
    return null;
  }
  if (start.length > 0 && end.length > 0 && start > end) {
    filterError.value = "筛选开始日期不得晚于结束日期";
    return null;
  }
  filterError.value = null;
  return Object.freeze({
    endOnOrBefore: end.length === 0 ? null : end,
    startOnOrAfter: start.length === 0 ? null : start,
    symbol: symbol.length === 0 ? null : symbol,
  });
}

function applyScope(): void {
  const scope = validateScope();
  if (scope !== null) emit("applyScope", scope);
}

function applyFilters(): void {
  const filters = validateFilters();
  if (filters !== null) emit("applyFilters", filters);
}

async function requestSync(): Promise<void> {
  const scope = validateScope();
  if (
    scope === null ||
    props.submissionState === "SUBMITTING" ||
    props.submissionState === "UNCERTAIN"
  ) {
    return;
  }
  pendingScope.value = scope;
  confirmationOpen.value = true;
  await nextTick();
  confirmSync.value?.focus();
}

function requestVerification(): void {
  const scope = validateScope();
  if (
    scope !== null &&
    props.submissionState !== "SUBMITTING" &&
    props.submissionState !== "UNCERTAIN"
  ) {
    emit("requestVerify", scope);
  }
}

async function closeConfirmation(restoreFocus = true): Promise<void> {
  confirmationOpen.value = false;
  pendingScope.value = null;
  if (!restoreFocus) return;
  await nextTick();
  syncTrigger.value?.focus();
}

async function acceptSync(): Promise<void> {
  const scope = pendingScope.value;
  if (scope !== null) emit("requestSync", scope, refreshDraft.value);
  await closeConfirmation();
}

function handleDialogKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape") {
    event.preventDefault();
    void closeConfirmation();
    return;
  }
  if (event.key !== "Tab") return;
  const first = confirmSync.value;
  const last = dismissSync.value;
  if (first === null || last === null) return;
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}
</script>

<template>
  <section class="dataset-scope-form" aria-labelledby="dataset-scope-title">
    <header class="dataset-scope-form__header">
      <div>
        <h2 id="dataset-scope-title">历史数据范围</h2>
      </div>
      <p>仅接受沪深 A 股；数据完整性始终由服务端验证。</p>
    </header>

    <div v-if="Object.keys(errors).length > 0" class="dataset-scope-form__errors" role="alert">
      <h3 ref="errorSummary" tabindex="-1">请修正以下范围输入</h3>
      <ul>
        <li v-for="(message, field) in errors" :key="field">
          <a :href="`#dataset-${field}`">{{ message }}</a>
        </li>
      </ul>
    </div>

    <form class="dataset-scope-form__grid" @submit.prevent="applyScope">
      <div class="dataset-scope-form__field dataset-scope-form__field--wide">
        <label for="dataset-symbols">股票代码 <span>必填，最多 10 个</span></label>
        <input
          id="dataset-symbols"
          v-model="symbolsDraft"
          :aria-invalid="errors.symbols === undefined ? undefined : 'true'"
          :aria-describedby="errors.symbols === undefined ? 'dataset-symbols-help' : 'dataset-symbols-error'"
          autocomplete="off"
          placeholder="000001.SZ,600000.SH"
        />
        <p id="dataset-symbols-help">使用英文逗号分隔；提交前按代码排序。</p>
        <p v-if="errors.symbols" id="dataset-symbols-error" class="dataset-scope-form__field-error">
          {{ errors.symbols }}
        </p>
      </div>

      <div class="dataset-scope-form__field">
        <label for="dataset-warmupStart">预热开始日期 <span>YYYY-MM-DD</span></label>
        <input
          id="dataset-warmupStart"
          v-model="warmupStartDraft"
          type="text"
          inputmode="numeric"
          :aria-invalid="errors.warmupStart === undefined ? undefined : 'true'"
          :aria-describedby="errors.warmupStart === undefined ? undefined : 'dataset-warmupStart-error'"
        />
        <p v-if="errors.warmupStart" id="dataset-warmupStart-error" class="dataset-scope-form__field-error">
          {{ errors.warmupStart }}
        </p>
      </div>

      <div class="dataset-scope-form__field">
        <label for="dataset-start">回测开始日期 <span>YYYY-MM-DD</span></label>
        <input
          id="dataset-start"
          v-model="startDraft"
          type="text"
          inputmode="numeric"
          :aria-invalid="errors.start === undefined ? undefined : 'true'"
          :aria-describedby="errors.start === undefined ? undefined : 'dataset-start-error'"
        />
        <p v-if="errors.start" id="dataset-start-error" class="dataset-scope-form__field-error">
          {{ errors.start }}
        </p>
      </div>

      <div class="dataset-scope-form__field">
        <label for="dataset-end">回测结束日期 <span>YYYY-MM-DD</span></label>
        <input
          id="dataset-end"
          v-model="endDraft"
          type="text"
          inputmode="numeric"
          :aria-invalid="errors.end === undefined ? undefined : 'true'"
          :aria-describedby="errors.end === undefined ? undefined : 'dataset-end-error'"
        />
        <p v-if="errors.end" id="dataset-end-error" class="dataset-scope-form__field-error">
          {{ errors.end }}
        </p>
      </div>

      <div class="dataset-scope-form__actions dataset-scope-form__field--wide">
        <button data-testid="apply-dataset-scope" type="button" @click="applyScope">
          应用到当前 URL
        </button>
        <button
          ref="syncTrigger"
          data-testid="request-dataset-sync"
          type="button"
          :disabled="submissionState === 'SUBMITTING' || submissionState === 'UNCERTAIN'"
          @click="requestSync"
        >
          同步历史数据
        </button>
        <button
          data-testid="request-dataset-verification"
          type="button"
          :disabled="submissionState === 'SUBMITTING' || submissionState === 'UNCERTAIN'"
          @click="requestVerification"
        >
          本地验证数据集
        </button>
        <label class="dataset-scope-form__checkbox">
          <input v-model="refreshDraft" type="checkbox" />
          刷新已缓存表面
        </label>
      </div>
    </form>

    <form class="dataset-scope-form__filters" aria-labelledby="dataset-filter-title" @submit.prevent="applyFilters">
      <h3 id="dataset-filter-title">已验证数据集筛选</h3>
      <div class="dataset-scope-form__filter-grid">
        <label>
          股票代码
          <input v-model="filterSymbolDraft" autocomplete="off" placeholder="000001.SZ" />
        </label>
        <label>
          开始不早于
          <input v-model="filterStartDraft" inputmode="numeric" placeholder="YYYY-MM-DD" />
        </label>
        <label>
          结束不晚于
          <input v-model="filterEndDraft" inputmode="numeric" placeholder="YYYY-MM-DD" />
        </label>
        <button type="submit">应用筛选</button>
      </div>
      <p v-if="filterError" class="dataset-scope-form__field-error" role="alert">
        {{ filterError }}
      </p>
    </form>

    <div
      v-if="confirmationOpen"
      class="dataset-scope-form__dialog-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="dataset-sync-title"
      aria-describedby="dataset-sync-description"
      @keydown="handleDialogKeydown"
    >
      <div class="dataset-scope-form__dialog">
        <h3 id="dataset-sync-title">确认联网同步历史数据</h3>
        <p id="dataset-sync-description">
          此操作会授权后端访问 Tushare。浏览器不会读取或显示 Tushare token；同步之外的验证与列表读取保持本地离线。
        </p>
        <div class="dataset-scope-form__actions">
          <button
            ref="confirmSync"
            data-testid="confirm-dataset-sync"
            type="button"
            @click="acceptSync"
          >
            确认联网同步
          </button>
          <button ref="dismissSync" type="button" @click="closeConfirmation()">返回检查范围</button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.dataset-scope-form {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  min-width: 0;
  gap: var(--space-6);
  padding: var(--space-6);
  border: var(--border-technical);
  background: var(--color-surface-graphite);
}

.dataset-scope-form__header,
.dataset-scope-form__actions,
.dataset-scope-form__filter-grid {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.dataset-scope-form__header h2,
.dataset-scope-form__filters h3,
.dataset-scope-form__dialog h3,
.dataset-scope-form__errors h3,
.dataset-scope-form__header p {
  margin: 0;
}

.dataset-scope-form__grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-4);
}

.dataset-scope-form__field,
.dataset-scope-form__filters,
.dataset-scope-form__filter-grid label {
  display: grid;
  min-width: 0;
  gap: var(--space-2);
}

.dataset-scope-form__field--wide {
  grid-column: 1 / -1;
}

.dataset-scope-form__field label,
.dataset-scope-form__filter-grid label {
  font-weight: 700;
}

.dataset-scope-form__field label span,
.dataset-scope-form__field p,
.dataset-scope-form__filters p {
  color: var(--color-text-muted);
  font-size: 0.875rem;
}

.dataset-scope-form input {
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  min-height: 2.75rem;
  padding: 0 var(--space-3);
  border: var(--border-technical);
  background: var(--color-surface-raised);
  color: var(--color-text-mineral);
}

.dataset-scope-form button {
  min-height: 2.75rem;
  padding: 0 var(--space-4);
  border: var(--border-technical);
  background: var(--color-surface-raised);
  color: var(--color-text-mineral);
  cursor: pointer;
}

.dataset-scope-form button:focus-visible,
.dataset-scope-form input:focus-visible,
.dataset-scope-form__errors h3:focus-visible {
  outline: 3px solid var(--color-focus-ring);
  outline-offset: 2px;
}

.dataset-scope-form button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.dataset-scope-form__checkbox {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 2.75rem;
}

.dataset-scope-form__checkbox input {
  min-height: auto;
}

.dataset-scope-form__errors,
.dataset-scope-form__field-error {
  color: var(--color-signal-risk-vermilion);
}

.dataset-scope-form__errors {
  padding: var(--space-4);
  border-inline-start: 4px solid var(--color-signal-risk-vermilion);
  background: rgb(228 93 67 / 12%);
}

.dataset-scope-form__errors a {
  color: inherit;
}

.dataset-scope-form__dialog-backdrop {
  position: fixed;
  inset: 0;
  z-index: 20;
  display: grid;
  place-items: center;
  padding: var(--space-4);
  background: rgb(11 17 22 / 78%);
}

.dataset-scope-form__dialog {
  width: min(32rem, 100%);
  padding: var(--space-6);
  border: 1px solid var(--color-signal-watch-amber);
  background: var(--color-surface-graphite);
}

@media (max-width: 767px) {
  .dataset-scope-form {
    padding: var(--space-4);
  }

  .dataset-scope-form__grid,
  .dataset-scope-form__filter-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 30rem) {
  .dataset-scope-form {
    padding-inline: var(--space-2);
  }
}
</style>
