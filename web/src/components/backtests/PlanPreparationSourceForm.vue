<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useId, watch } from "vue";
import { MAX_PREPARATION_SOURCE_CHARACTERS, validPreparationSource, type PreparationSource } from "../../api/preparations";
import { normalizeShanghaiDateTime } from "../../api/shanghaiTime";

const props = withDefaults(defineProps<{
  source: PreparationSource;
  disabled: boolean;
  errorMessage?: string | null;
  submitLabel?: string;
}>(), { errorMessage: null, submitLabel: "保存原文" });
const emit = defineEmits<{ "update:source": [source: PreparationSource]; submit: [] }>();
const id = useId();
const localError = ref<string | null>(null);
const fileLoading = ref(false);
const error = computed(() => localError.value ?? props.errorMessage);
const characterCount = computed(() => Array.from(props.source.text).length);
let fileGeneration = 0;
let disposed = false;

function invalidateFile(): void { fileGeneration += 1; fileLoading.value = false; }
watch(() => [props.disabled, props.source], invalidateFile);
onBeforeUnmount(() => { disposed = true; invalidateFile(); });

function update(field: keyof PreparationSource, value: string | null): void {
  if (props.disabled) return;
  invalidateFile(); localError.value = null;
  emit("update:source", { ...props.source, [field]: value });
}
function inputValue(event: Event): string { return (event.target as HTMLInputElement).value; }
function updateTime(field: "authored_at" | "available_at", event: Event): void {
  const value = inputValue(event);
  const shanghai = value.length === 16 ? `${value}:00+08:00` : `${value}+08:00`;
  update(field, value ? normalizeShanghaiDateTime(shanghai) ?? shanghai : null);
}
function submit(): void {
  if (props.disabled || fileLoading.value) return;
  if (!validPreparationSource(props.source)) {
    localError.value = "请填写完整原文（最多 150000 字符），并检查日期；原文成文时间不能晚于可用时间。";
    return;
  }
  localError.value = null; emit("submit");
}
async function readFile(event: Event): Promise<void> {
  if (props.disabled) return;
  const input = event.target as HTMLInputElement;
  const files = Array.from(input.files ?? []);
  input.value = "";
  invalidateFile(); localError.value = null;
  if (files.length === 0) return;
  if (files.length !== 1 || !/\.(txt|md)$/i.test(files[0]!.name) || files[0]!.size > 600_000) {
    localError.value = "请选择一份 UTF-8 编码的 .txt 或 .md 文件，文件不能超过 600000 字节。";
    return;
  }
  const generation = fileGeneration;
  fileLoading.value = true;
  try {
    const bytes = await files[0]!.arrayBuffer();
    if (disposed || props.disabled || generation !== fileGeneration) return;
    const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    if (!text.trim() || Array.from(text).length > MAX_PREPARATION_SOURCE_CHARACTERS) {
      localError.value = "文件原文不能为空，且不能超过 150000 字符。";
      return;
    }
    emit("update:source", { ...props.source, text });
  } catch {
    if (!disposed && !props.disabled && generation === fileGeneration) {
      localError.value = "无法读取文件，请检查 UTF-8 编码，或直接粘贴完整原文。";
    }
  } finally {
    if (generation === fileGeneration) fileLoading.value = false;
  }
}
</script>

<template>
  <form class="source-form" novalidate @submit.prevent="submit">
    <fieldset :disabled="disabled">
      <legend>单份计划原文</legend>
      <p :id="`${id}-help`" class="hint">粘贴完整原文，或读取一份文本文件。修改原文后，请先保存，再重新提取和审核。</p>
      <label :for="`${id}-text`">完整原文</label>
      <textarea :id="`${id}-text`" :value="source.text" rows="10" required
        :aria-describedby="`${id}-help ${id}-count${error ? ` ${id}-error` : ''}`"
        @input="update('text', inputValue($event))" />
      <p :id="`${id}-count`" class="hint count">{{ characterCount }} / 150000 字符</p>
      <label :for="`${id}-file`">从文件读取（UTF-8 的 .txt 或 .md）</label>
      <input :id="`${id}-file`" type="file" accept=".txt,.md,text/plain,text/markdown" :disabled="fileLoading" @change="readFile" />
      <p v-if="fileLoading" role="status" class="hint">正在读取原文…</p>
      <details>
        <summary>补充原文日期（可选）</summary>
        <p class="hint">日期时间按上海时区记录；未明确的信息请留空。</p>
        <div class="dates">
          <div><label :for="`${id}-authored`">原文成文时间</label>
            <input :id="`${id}-authored`" type="datetime-local" step="1" :value="source.authored_at?.slice(0, 19) ?? ''" @input="updateTime('authored_at', $event)" /></div>
          <div><label :for="`${id}-available`">原文可用时间</label>
            <input :id="`${id}-available`" type="datetime-local" step="1" :value="source.available_at?.slice(0, 19) ?? ''" @input="updateTime('available_at', $event)" /></div>
          <div><label :for="`${id}-effective`">计划交易日</label>
            <input :id="`${id}-effective`" type="date" :value="source.effective_trade_date ?? ''" @input="update('effective_trade_date', inputValue($event) || null)" /></div>
        </div>
      </details>
      <button type="submit" :disabled="fileLoading">{{ submitLabel }}</button>
    </fieldset>
    <p v-if="disabled" class="hint">当前操作完成前，原文暂不可修改。</p>
    <p v-if="error" :id="`${id}-error`" role="alert" class="error">{{ error }}</p>
  </form>
</template>

<style scoped>
.source-form { min-width: 0; }
fieldset { margin: 0; padding: 0; border: 0; min-width: 0; display: grid; gap: var(--space-3); }
legend { font-size: 1.125rem; font-weight: 600; padding: 0; margin-bottom: var(--space-3); }
label { display: block; }
textarea, input { width: 100%; min-width: 0; }
textarea { resize: vertical; }
.hint { color: var(--color-text-muted); font-size: .875rem; margin: 0; }
.count { text-align: right; font-variant-numeric: tabular-nums; }
details { border-top: var(--border-technical); padding-top: var(--space-2); }
summary { cursor: pointer; }
.dates { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 16rem), 1fr)); gap: var(--space-4); margin-top: var(--space-3); }
.dates label { margin-bottom: var(--space-2); }
button { justify-self: start; margin-top: var(--space-2); }
.error { color: var(--color-signal-risk-vermilion); overflow-wrap: anywhere; }
</style>
