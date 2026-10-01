<script setup lang="ts">
import { computed, shallowRef } from "vue";

interface Props {
  busy?: boolean;
  cancellable?: boolean;
  disabled?: boolean;
  maxChars?: number;
  submitDisabled?: boolean;
}

interface Emits {
  cancel: [];
  submit: [];
}

const props = withDefaults(defineProps<Props>(), {
  busy: false,
  cancellable: false,
  disabled: false,
  maxChars: 200_000,
  submitDisabled: false,
});
const emit = defineEmits<Emits>();
const sourceText = defineModel<string>({ required: true });
const sourceInputRejected = shallowRef(false);
const sourceCharacterCount = computed(() =>
  boundedUnicodeCharacterCount(sourceText.value, props.maxChars + 1),
);
const sourceLimitExceeded = computed(
  () => sourceInputRejected.value || sourceCharacterCount.value > props.maxChars,
);

const canSubmit = computed(
  () =>
    !props.busy &&
    !props.disabled &&
    !props.submitDisabled &&
    !sourceLimitExceeded.value &&
    sourceText.value.trim().length > 0 &&
    sourceCharacterCount.value <= props.maxChars,
);

function boundedUnicodeCharacterCount(value: string, stopAt: number): number {
  let count = 0;
  for (const _character of value) {
    count += 1;
    if (count === stopAt) {
      return count;
    }
  }
  return count;
}

function handleSourceInput(event: Event): void {
  const target = event.target;
  if (!(target instanceof HTMLTextAreaElement)) {
    return;
  }
  if (boundedUnicodeCharacterCount(target.value, props.maxChars + 1) > props.maxChars) {
    sourceInputRejected.value = true;
    target.value = sourceText.value;
    return;
  }
  sourceInputRejected.value = false;
  sourceText.value = target.value;
}

function submitSource(): void {
  if (canSubmit.value) {
    emit("submit");
  }
}
</script>

<template>
  <section class="source-editor" aria-labelledby="source-editor-title">
    <div class="source-editor__heading">
      <div>
        <h2 id="source-editor-title" class="source-editor__title">交易计划原文</h2>
      </div>
      <output class="source-editor__count" for="plan-source-text">
        {{ sourceCharacterCount }} / {{ maxChars }}
      </output>
    </div>

    <form class="source-editor__form" data-testid="source-editor" @submit.prevent="submitSource">
      <label class="source-editor__label" for="plan-source-text">粘贴中文计划原文</label>
      <textarea
        id="plan-source-text"
        v-model="sourceText"
        class="source-editor__textarea"
        rows="12"
        :disabled="disabled"
        spellcheck="false"
        @input.capture="handleSourceInput"
      />
      <p class="source-editor__hint">
        原文只作为不可信纯文本发送和展示；AI 提取不会启用计划或参与实时判断。
      </p>
      <p v-if="sourceLimitExceeded" class="source-editor__input-error" role="alert">
        原文不能超过 {{ maxChars }} 个字符；{{ sourceInputRejected ? "本次输入未应用。" : "请缩短原文后再提交。" }}
      </p>
      <div class="source-editor__actions">
        <button class="source-editor__submit" type="submit" :disabled="!canSubmit">
          生成计划草稿
        </button>
        <button
          v-if="busy && cancellable"
          class="source-editor__cancel"
          data-testid="stop-waiting"
          type="button"
          @click="emit('cancel')"
        >
          停止等待
        </button>
      </div>
    </form>
  </section>
</template>

<style scoped>
.source-editor {
  display: grid;
  gap: var(--space-4);
  padding: var(--space-6);
  background: var(--color-surface-graphite);
  border: var(--border-technical);
  border-block-start: 0.25rem solid var(--color-signal-watch-amber);
  border-radius: var(--radius-panel);
}

.source-editor__heading,
.source-editor__actions {
  display: flex;
  gap: var(--space-3);
  align-items: center;
  justify-content: space-between;
}

.source-editor__title,
.source-editor__hint {
  margin: 0;
}

.source-editor__input-error {
  margin: 0;
  color: var(--color-signal-risk-vermilion);
}

.source-editor__count {
  color: var(--color-signal-watch-amber);
  font-family: var(--font-numeric);
  font-size: 0.75rem;
  letter-spacing: 0.06em;
}

.source-editor__title {
  font-size: 1.1rem;
}

.source-editor__form {
  display: grid;
  gap: var(--space-3);
}

.source-editor__label {
  font-weight: 700;
}

.source-editor__textarea {
  width: 100%;
  box-sizing: border-box;
  padding: var(--space-4);
  color: var(--color-text-mineral);
  line-height: 1.65;
  resize: vertical;
  background: var(--color-surface-ink);
  border: var(--border-technical);
  border-radius: var(--radius-control);
}

.source-editor__hint {
  color: var(--color-text-muted);
  font-size: 0.85rem;
}

.source-editor__submit,
.source-editor__cancel {
  min-height: 2.75rem;
  padding: var(--space-2) var(--space-4);
  font-weight: 700;
  border-radius: var(--radius-control);
  cursor: pointer;
}

.source-editor__submit {
  color: var(--color-surface-ink);
  background: var(--color-signal-watch-amber);
  border: 0;
}

.source-editor__cancel {
  color: var(--color-text-mineral);
  background: transparent;
  border: var(--border-technical);
}

.source-editor__submit:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

@media (max-width: 47.999rem) {
  .source-editor__heading,
  .source-editor__actions {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
