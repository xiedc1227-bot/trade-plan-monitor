<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useId, watch } from "vue";
import { MAX_PREPARATION_SOURCE_CHARACTERS, validPreparationSource, validPreparationSources, type PreparationSource } from "../../api/preparations";

const props = withDefaults(defineProps<{
  source: PreparationSource;
  sources?: readonly PreparationSource[];
  disabled: boolean;
  errorMessage?: string | null;
  submitLabel?: string;
}>(), { errorMessage: null, submitLabel: "保存原文" });
const emit = defineEmits<{ "update:source": [source: PreparationSource]; "update:sources": [sources: PreparationSource[]]; submit: [] }>();
const id = useId();
const localError = ref<string | null>(null);
const fileLoading = ref(false);
const error = computed(() => localError.value ?? props.errorMessage);
const characterCount = computed(() => Array.from(props.source.text).length);
let fileGeneration = 0;
let disposed = false;

function invalidateFile(): void { fileGeneration += 1; fileLoading.value = false; }
watch(() => [props.disabled, props.source, props.sources], invalidateFile);
onBeforeUnmount(() => { disposed = true; invalidateFile(); });

function update(field: keyof PreparationSource, value: string | null): void {
  if (props.disabled) return;
  invalidateFile(); localError.value = null;
  emit("update:source", { ...props.source, [field]: value,
    ...(field === "text" && props.source.effective_trade_date ? { effective_trade_date: null } : {}) });
}
function inputValue(event: Event): string { return (event.target as HTMLInputElement).value; }
function submit(): void {
  if (props.disabled || fileLoading.value) return;
  const values = props.sources;
  if (values && values.reduce((sum, source) => sum + new TextEncoder().encode(source.text).byteLength, 0) > 8 * 1024 * 1024) {
    localError.value = "全部原文的 UTF-8 总量不能超过 8 MiB。"; return;
  }
  if (values !== undefined && (!validPreparationSources(values) || new TextEncoder().encode(JSON.stringify({ input: { schema_version: "backtest-preparation-v2", preparation_id: "pending", sources: values } })).byteLength > 4 * 1024 * 1024)) {
    localError.value = "请保留 1–256 份独立原文，检查日期与重复来源；本次提交不能超过 4 MiB。"; return;
  }
  if (values === undefined && !validPreparationSource(props.source)) {
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
  if (props.sources !== undefined) { await readBatch(files); return; }
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
    emit("update:source", { ...props.source, text,
      ...(props.source.effective_trade_date ? { effective_trade_date: null } : {}) });
  } catch {
    if (!disposed && !props.disabled && generation === fileGeneration) {
      localError.value = "无法读取文件，请检查 UTF-8 编码，或直接粘贴完整原文。";
    }
  } finally {
    if (generation === fileGeneration) fileLoading.value = false;
  }
}
function emitSources(values: PreparationSource[]): void {
  if (props.disabled) return;
  invalidateFile(); localError.value = null; emit("update:sources", values);
}
function updateItem(index: number, field: keyof PreparationSource, value: string | null): void {
  emitSources((props.sources ?? []).map((source, position) => position === index
    ? { ...source, [field]: value, ...(field === "text" && source.effective_trade_date ? { effective_trade_date: null } : {}) }
    : { ...source }));
}
function addSource(): void {
  if ((props.sources?.length ?? 0) >= 256) return;
  emitSources([...(props.sources ?? []), { source_id: globalThis.crypto.randomUUID(), text: "" }]);
}
function removeSource(index: number): void {
  if ((props.sources?.length ?? 0) <= 1) return;
  emitSources((props.sources ?? []).filter((_, position) => position !== index));
}
function moveSource(index: number, direction: number): void {
  const values = [...(props.sources ?? [])], next = index + direction;
  if (next < 0 || next >= values.length) return;
  [values[index], values[next]] = [values[next]!, values[index]!]; emitSources(values);
}
async function readBatch(files: File[]): Promise<void> {
  if (files.some(file => !/\.(txt|md)$/i.test(file.name) || file.size > 600_000)) { localError.value = "每份文件须为 UTF-8 的 .txt 或 .md，且不超过 600000 字节。"; return; }
  const current = props.sources ?? [];
  const first = current[0];
  const existing = current.length === 1 && first?.text === "" &&
    !first.authored_at && !first.available_at && !first.effective_trade_date ? [] : [...current];
  if (existing.length + files.length > 256 || files.reduce((sum, file) => sum + file.size, 0) > 4 * 1024 * 1024) { localError.value = "最多 256 份原文，本次提交不能超过 4 MiB。"; return; }
  const generation = fileGeneration; fileLoading.value = true;
  try {
    const added: PreparationSource[] = [];
    for (const file of files) {
      const bytes = await file.arrayBuffer();
      if (disposed || props.disabled || generation !== fileGeneration) return;
      const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
      if (!text.trim() || Array.from(text).length > MAX_PREPARATION_SOURCE_CHARACTERS) throw new Error("source size");
      added.push({ source_id: globalThis.crypto.randomUUID(), text });
    }
    emitSources([...existing, ...added]);
  } catch { if (!disposed && !props.disabled && generation === fileGeneration) localError.value = "文件读取失败，请检查编码和原文长度；已有原文已保留。"; }
  finally { if (generation === fileGeneration) fileLoading.value = false; }
}
</script>

<template>
  <form class="source-form" novalidate @submit.prevent="submit">
    <fieldset :disabled="disabled">
      <legend>{{ sources === undefined ? '单份计划原文' : '按日分组录入原文' }}</legend>
      <template v-if="sources !== undefined">
        <p class="hint">可导入 1–256 份计划原文。第一份是完整计划，后续为按日期排列的跟踪原文。保存时自动识别生效交易日，只有日期不明确时才需确认；无需填写成文时间和历史可用时间。</p>
        <fieldset v-for="(item, index) in sources" :key="item.source_id" class="source-item" :data-testid="`source-item-${item.source_id}`">
          <legend>第 {{ index + 1 }} 份 · {{ index === 0 ? '初始完整计划' : '后续跟踪' }}</legend>
          <label :for="`${id}-${index}-text`">第 {{ index + 1 }} 份完整原文</label>
          <textarea :id="`${id}-${index}-text`" :value="item.text" rows="7" required @input="updateItem(index, 'text', inputValue($event))" />
          <p class="hint count">{{ Array.from(item.text).length }} / 150000 字符</p>
          <div class="dates">
            <div><label :for="`${id}-${index}-effective`">生效交易日（留空自动识别，必要时确认）</label><input :id="`${id}-${index}-effective`" type="date" :value="item.effective_trade_date ?? ''" @input="updateItem(index, 'effective_trade_date', inputValue($event) || null)" /></div>
          </div>
          <div class="source-actions">
            <button type="button" :data-testid="`source-up-${item.source_id}`" :disabled="index === 0" @click="moveSource(index, -1)">上移第 {{ index + 1 }} 份</button>
            <button type="button" :data-testid="`source-down-${item.source_id}`" :disabled="index === sources.length - 1" @click="moveSource(index, 1)">下移第 {{ index + 1 }} 份</button>
            <button type="button" :data-testid="`source-remove-${item.source_id}`" :disabled="sources.length <= 1" @click="removeSource(index)">移除第 {{ index + 1 }} 份</button>
          </div>
        </fieldset>
        <button type="button" data-testid="source-add" :disabled="sources.length >= 256" @click="addSource">增加一份跟踪原文</button>
        <label :for="`${id}-files`">一次选择多份文本文件（每份保留独立边界）</label>
        <input :id="`${id}-files`" type="file" multiple accept=".txt,.md,text/plain,text/markdown" :disabled="fileLoading" @change="readFile" />
        <p v-if="fileLoading" role="status">正在读取全部原文…</p>
        <button type="submit" :disabled="fileLoading">保存全部原文</button>
      </template>
      <template v-else>
      <p :id="`${id}-help`" class="hint">粘贴完整原文，或读取一份文本文件。修改原文后，请先保存，再重新提取和审核。</p>
      <p class="hint">提取会将原文和已审核前序规则发送给当前 AI；自动纠正时还会发送上一轮候选及校验诊断，最多纠正两次。未提及规则默认保留，真正不明确的内容集中确认。</p>
      <label :for="`${id}-text`">完整原文</label>
      <textarea :id="`${id}-text`" :value="source.text" rows="10" required
        :aria-describedby="`${id}-help ${id}-count${error ? ` ${id}-error` : ''}`"
        @input="update('text', inputValue($event))" />
      <p :id="`${id}-count`" class="hint count">{{ characterCount }} / 150000 字符</p>
      <label :for="`${id}-file`">从文件读取（UTF-8 的 .txt 或 .md）</label>
      <input :id="`${id}-file`" type="file" accept=".txt,.md,text/plain,text/markdown" :disabled="fileLoading" @change="readFile" />
      <p v-if="fileLoading" role="status" class="hint">正在读取原文…</p>
      <div class="date-confirmation">
        <p class="hint">保存时从原文自动识别生效交易日；无法确定时请在此确认日期。未声明历史可用时间的计划，从生效日开盘起执行。</p>
        <div class="dates">
          <div><label :for="`${id}-effective`">生效交易日（留空自动识别，必要时确认）</label>
            <input :id="`${id}-effective`" type="date" :value="source.effective_trade_date ?? ''" @input="update('effective_trade_date', inputValue($event) || null)" /></div>
        </div>
      </div>
      <button type="submit" :disabled="fileLoading">{{ submitLabel }}</button>
      </template>
    </fieldset>
    <p v-if="disabled" class="hint">当前操作完成前，原文暂不可修改。</p>
    <p v-if="error" :id="`${id}-error`" role="alert" class="error">{{ error }}</p>
  </form>
</template>

<style scoped>
.source-item { border: var(--border-technical); padding: var(--space-4); margin-bottom: var(--space-3); }
.source-actions { display: flex; flex-wrap: wrap; gap: var(--space-2); }
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
