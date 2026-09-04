<script setup lang="ts">
import { computed, shallowRef } from "vue";

import type { PlanDocumentFormat, PlanImportCommand } from "../../api/generated";

const MAX_PLAN_DOCUMENT_BYTES = 256 * 1_024;

interface Props {
  busy?: boolean;
  expectedRevision?: number;
}

interface Emits {
  importPlan: [command: PlanImportCommand];
}

const props = withDefaults(defineProps<Props>(), {
  busy: false,
  expectedRevision: 0,
});
const emit = defineEmits<Emits>();
const format = shallowRef<PlanDocumentFormat>("JSON");
const symbol = shallowRef("");
const document = shallowRef("");
const errorMessage = shallowRef<string | null>(null);

const canSubmit = computed(
  () =>
    !props.busy &&
    isShareSymbol(symbol.value) &&
    document.value.trim().length > 0 &&
    utf8ByteLengthAtMost(document.value, MAX_PLAN_DOCUMENT_BYTES) !== null,
);

function updateDocument(event: Event): void {
  const target = event.target;
  if (!(target instanceof HTMLTextAreaElement)) return;
  if (utf8ByteLengthAtMost(target.value, MAX_PLAN_DOCUMENT_BYTES) === null) {
    target.value = document.value;
    errorMessage.value = "导入文档超过 256 KiB 上限；本次编辑未应用。";
    return;
  }
  document.value = target.value;
  errorMessage.value = null;
}

function updateSymbol(event: Event): void {
  const target = event.target;
  if (!(target instanceof HTMLInputElement)) return;
  symbol.value = target.value;
  errorMessage.value = null;
}

function submit(): void {
  if (!canSubmit.value) {
    errorMessage.value ??=
      !isShareSymbol(symbol.value)
        ? "请输入规范目标股票代码，例如 003043.SZ。"
        : document.value.trim().length === 0
        ? "请粘贴待导入文档。"
        : "导入文档超过 256 KiB 上限。";
    return;
  }
  errorMessage.value = null;
  emit("importPlan", {
    document: document.value,
    expectedRevision: props.expectedRevision,
    format: format.value,
    symbol: symbol.value,
  });
}

function isShareSymbol(value: string): boolean {
  return /^\d{6}\.(?:BJ|SH|SZ)$/.test(value);
}

function utf8ByteLengthAtMost(value: string, maximum: number): number | null {
  let bytes = 0;
  for (const character of value) {
    const codePoint = character.codePointAt(0);
    if (codePoint === undefined) continue;
    bytes +=
      codePoint <= 0x7f
        ? 1
        : codePoint <= 0x7ff
          ? 2
          : codePoint <= 0xffff
            ? 3
            : 4;
    if (bytes > maximum) return null;
  }
  return bytes;
}
</script>

<template>
  <section class="plan-import" aria-labelledby="portable-plan-import-title">
    <header class="plan-import__header">
      <div>
        <p class="plan-import__eyebrow">DURABLE PLAN IMPORT</p>
        <h2 id="portable-plan-import-title">导入计划版本</h2>
      </div>
      <p class="plan-import__boundary">
        JSON 或 YAML 原文直接交由后端安全解析；浏览器不推断字段或交易规则。
      </p>
    </header>
    <form
      class="plan-import__form"
      data-testid="plan-import-form"
      @submit.prevent="submit"
    >
      <div class="plan-import__fields">
        <div class="plan-import__metadata">
          <div class="plan-import__field">
            <label for="portable-plan-import-format">格式</label>
            <select id="portable-plan-import-format" v-model="format" :disabled="busy">
              <option value="JSON">JSON</option>
              <option value="YAML">YAML</option>
            </select>
          </div>
          <div class="plan-import__field">
            <label for="portable-plan-import-symbol">导入目标股票</label>
            <input
              id="portable-plan-import-symbol"
              autocomplete="off"
              :disabled="busy"
              inputmode="text"
              placeholder="003043.SZ"
              spellcheck="false"
              :value="symbol"
              @input="updateSymbol"
            />
          </div>
          <p class="plan-import__hint">支持 A 股规范代码，例如 003043.SZ。</p>
        </div>
        <div class="plan-import__document">
          <label for="portable-plan-import-document">计划文档</label>
          <textarea
            id="portable-plan-import-document"
            :disabled="busy"
            :value="document"
            rows="7"
            spellcheck="false"
            @input="updateDocument"
          />
        </div>
      </div>
      <div class="plan-import__actions">
        <p v-if="errorMessage" class="plan-import__error" role="alert">
          {{ errorMessage }}
        </p>
        <button type="submit" :disabled="!canSubmit">提交后端安全导入</button>
      </div>
    </form>
  </section>
</template>

<style scoped>
.plan-import {
  display: grid;
  gap: var(--space-4);
  box-sizing: border-box;
  width: min(100%, 90rem);
  margin: 0 auto;
  padding: var(--space-4);
  background: var(--color-surface-graphite);
  border: var(--border-technical);
  border-block-start: 0.25rem solid var(--color-signal-info-cyan);
}

.plan-import__header {
  display: flex;
  gap: var(--space-6);
  align-items: end;
  justify-content: space-between;
}

.plan-import__form,
.plan-import__metadata,
.plan-import__document,
.plan-import__field {
  display: grid;
  gap: var(--space-2);
}

.plan-import__header h2,
.plan-import__header p,
.plan-import__boundary,
.plan-import__hint,
.plan-import__error {
  margin: 0;
}

.plan-import__eyebrow {
  color: var(--color-signal-info-cyan);
  font-family: var(--font-numeric);
  font-size: 0.75rem;
  letter-spacing: 0.08em;
}

.plan-import__boundary {
  max-width: 44rem;
  color: var(--color-text-muted);
  text-align: end;
}

.plan-import__fields {
  display: grid;
  grid-template-columns: minmax(13rem, 18rem) minmax(0, 1fr);
  gap: var(--space-4);
  align-items: start;
}

.plan-import__metadata {
  gap: var(--space-4);
}

.plan-import__hint {
  color: var(--color-text-muted);
  font-size: 0.875rem;
}

.plan-import__form select,
.plan-import__form input,
.plan-import__form textarea {
  width: 100%;
  box-sizing: border-box;
  padding: var(--space-3);
  color: var(--color-text-mineral);
  background: var(--color-surface-ink);
  border: var(--border-technical);
  border-radius: var(--radius-control);
}

.plan-import__form textarea {
  min-height: 10rem;
  resize: vertical;
}

.plan-import__actions {
  display: flex;
  gap: var(--space-4);
  align-items: center;
  justify-content: flex-end;
}

.plan-import__form button {
  width: fit-content;
  min-height: 2.75rem;
  padding: var(--space-2) var(--space-4);
  color: var(--color-surface-ink);
  font-weight: 700;
  background: var(--color-signal-info-cyan);
  border: 0;
  border-radius: var(--radius-control);
}

.plan-import__form button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.plan-import__error {
  flex: 1;
  padding: var(--space-3);
  border-inline-start: 0.25rem solid var(--color-signal-risk-vermilion);
}

@media (max-width: 47.999rem) {
  .plan-import__header,
  .plan-import__actions {
    align-items: stretch;
    flex-direction: column;
  }

  .plan-import__boundary {
    text-align: start;
  }

  .plan-import__fields {
    grid-template-columns: 1fr;
  }

  .plan-import__form button {
    width: 100%;
  }
}
</style>
