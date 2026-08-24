<script setup lang="ts">
import { computed, shallowRef, watch } from "vue";

import type {
  PlanDocumentFormat,
  PlanDraftCommand,
  PlanImportCommand,
  PlanVersionView,
} from "../../api/generated";

const MAX_PLAN_DOCUMENT_BYTES = 256 * 1_024;
const MAX_EDITOR_INPUT_BYTES = 4 * 1_024 * 1_024;

const SECTION_DEFINITIONS = [
  { key: "metadata", label: "计划元数据" },
  { key: "activation", label: "激活策略" },
  { key: "position", label: "仓位策略" },
  { key: "levels", label: "价格层级" },
  { key: "entry", label: "入场规则" },
  { key: "reduction", label: "减仓规则" },
  { key: "risk", label: "风险规则" },
  { key: "blockers", label: "阻断条件" },
  { key: "monitoring", label: "监控参数" },
] as const;

type SectionKey = (typeof SECTION_DEFINITIONS)[number]["key"];
type PlanRecord = Record<string, unknown>;
type SectionTexts = Record<SectionKey, string>;

export interface PlanExportIntent {
  format: PlanDocumentFormat;
  planJson: string;
  planVersionId: string;
}

interface Props {
  busy?: boolean;
  plan: PlanVersionView;
}

interface Emits {
  dirtyChange: [dirty: boolean];
  exportDocument: [intent: PlanExportIntent];
  importDocument: [command: PlanImportCommand];
  saveDraft: [command: PlanDraftCommand];
}

const props = withDefaults(defineProps<Props>(), { busy: false });
const emit = defineEmits<Emits>();

const originalDocument = shallowRef<PlanRecord>({});
const planName = shallowRef("");
const sectionTexts = shallowRef<SectionTexts>(emptySectionTexts());
const loadedPlanId = shallowRef("");
const loadedRevision = shallowRef(-1);
const dirty = shallowRef(false);
const conflictRevision = shallowRef<number | null>(null);
const importFormat = shallowRef<PlanDocumentFormat>("JSON");
const importDocument = shallowRef("");
const importError = shallowRef<string | null>(null);
const exportFormat = shallowRef<PlanDocumentFormat>("JSON");
const loadError = shallowRef<string | null>(null);
const editError = shallowRef<string | null>(null);

const assembled = computed(() => assembleDocument());
const preview = computed(() => executablePreview(assembled.value.document));
const assembledWithinLimit = computed(
  () =>
    assembled.value.json !== null &&
    utf8ByteLengthAtMost(assembled.value.json, MAX_PLAN_DOCUMENT_BYTES) !== null,
);
const canSave = computed(
  () =>
    dirty.value &&
    conflictRevision.value === null &&
    loadError.value === null &&
    assembled.value.error === null &&
    assembledWithinLimit.value &&
    !props.busy,
);
const canImport = computed(
  () =>
    !props.busy &&
    importDocument.value.trim().length > 0 &&
    utf8ByteLengthAtMost(importDocument.value, MAX_PLAN_DOCUMENT_BYTES) !== null,
);
const canExport = computed(
  () => !props.busy && loadError.value === null && assembledWithinLimit.value,
);

watch(
  () => [props.plan.id, props.plan.revision, props.plan.planJson] as const,
  ([planId, revision]) => {
    if (
      planId === loadedPlanId.value &&
      revision !== loadedRevision.value &&
      dirty.value
    ) {
      conflictRevision.value = revision;
      return;
    }
    loadPlan(props.plan);
  },
  { immediate: true },
);

function emptySectionTexts(): SectionTexts {
  return Object.fromEntries(
    SECTION_DEFINITIONS.map(({ key }) => [key, "{}"]),
  ) as SectionTexts;
}

function loadPlan(plan: PlanVersionView): void {
  const withinLimit =
    utf8ByteLengthAtMost(plan.planJson, MAX_PLAN_DOCUMENT_BYTES) !== null;
  const parsed = withinLimit ? parseRecord(plan.planJson) : null;
  loadError.value = withinLimit
    ? parsed === null
      ? "服务器计划文档不是有效 JSON 对象，已停止本地编辑。"
      : null
    : "服务器计划文档超过 256 KiB 上限，已停止本地编辑。";
  editError.value = null;
  originalDocument.value = parsed ?? {};
  planName.value = typeof parsed?.name === "string" ? parsed.name : "";
  sectionTexts.value = Object.fromEntries(
    SECTION_DEFINITIONS.map(({ key }) => [
      key,
      JSON.stringify(parsed?.[key] ?? {}, null, 2),
    ]),
  ) as SectionTexts;
  loadedPlanId.value = plan.id;
  loadedRevision.value = plan.revision;
  conflictRevision.value = null;
  setDirty(false);
}

function parseRecord(value: string): PlanRecord | null {
  try {
    const parsed: unknown = JSON.parse(value);
    return isRecord(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function isRecord(value: unknown): value is PlanRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function assembleDocument(
  name = planName.value,
  texts = sectionTexts.value,
): {
  document: PlanRecord | null;
  error: string | null;
  json: string | null;
} {
  const document: PlanRecord = { ...originalDocument.value, name };
  for (const { key, label } of SECTION_DEFINITIONS) {
    const parsed = parseSection(texts[key]);
    if (parsed === null) {
      return { document: null, error: `${label}不是有效 JSON 对象。`, json: null };
    }
    document[key] = parsed;
  }
  return { document, error: null, json: JSON.stringify(document) };
}

function parseSection(value: string): PlanRecord | null {
  try {
    const parsed: unknown = JSON.parse(value);
    return isRecord(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function updateName(event: Event): void {
  const target = event.target;
  if (target instanceof HTMLInputElement) {
    const nextName = target.value;
    if (!acceptsDraftInput(nextName, sectionTexts.value)) {
      target.value = planName.value;
      return;
    }
    planName.value = nextName;
    editError.value = null;
    setDirty(true);
  }
}

function updateSection(key: SectionKey, event: Event): void {
  const target = event.target;
  if (!(target instanceof HTMLTextAreaElement)) {
    return;
  }
  const nextTexts = { ...sectionTexts.value, [key]: target.value };
  if (!acceptsDraftInput(planName.value, nextTexts)) {
    target.value = sectionTexts.value[key];
    return;
  }
  sectionTexts.value = nextTexts;
  editError.value = null;
  setDirty(true);
}

function acceptsDraftInput(name: string, texts: SectionTexts): boolean {
  if (!draftInputsWithinLimit(name, texts)) {
    editError.value = "计划编辑缓冲超过 4 MiB 上限；本次编辑未应用。";
    return false;
  }
  const candidate = assembleDocument(name, texts);
  if (
    candidate.json !== null &&
    utf8ByteLengthAtMost(candidate.json, MAX_PLAN_DOCUMENT_BYTES) === null
  ) {
    editError.value = "计划文档超过 256 KiB 上限；本次编辑未应用。";
    return false;
  }
  return true;
}

function draftInputsWithinLimit(name: string, texts: SectionTexts): boolean {
  let remaining = MAX_EDITOR_INPUT_BYTES;
  for (const value of [name, ...SECTION_DEFINITIONS.map(({ key }) => texts[key])]) {
    const bytes = utf8ByteLengthAtMost(value, remaining);
    if (bytes === null) {
      return false;
    }
    remaining -= bytes;
  }
  return true;
}

function setDirty(value: boolean): void {
  if (dirty.value !== value) {
    dirty.value = value;
    emit("dirtyChange", value);
  }
}

function saveDraft(): void {
  if (
    !canSave.value ||
    assembled.value.json === null ||
    utf8ByteLengthAtMost(assembled.value.json, MAX_PLAN_DOCUMENT_BYTES) === null
  ) {
    return;
  }
  emit("saveDraft", {
    expectedRevision: loadedRevision.value,
    planJson: assembled.value.json,
    reviewIssues: [...(props.plan.reviewIssues ?? [])],
    sourceText: props.plan.sourceText,
  });
}

function submitImport(): void {
  if (!canImport.value) {
    if (importDocument.value.trim().length === 0) {
      importError.value ??= "请粘贴待导入文档。";
    } else if (
      utf8ByteLengthAtMost(importDocument.value, MAX_PLAN_DOCUMENT_BYTES) === null
    ) {
      importError.value = "导入文档超过 256 KiB 上限。";
    }
    return;
  }
  importError.value = null;
  emit("importDocument", {
    document: importDocument.value,
    expectedRevision: props.plan.revision,
    format: importFormat.value,
  });
}

function updateImportDocument(event: Event): void {
  const target = event.target;
  if (!(target instanceof HTMLTextAreaElement)) {
    return;
  }
  if (utf8ByteLengthAtMost(target.value, MAX_PLAN_DOCUMENT_BYTES) === null) {
    importError.value = "导入文档超过 256 KiB 上限；本次编辑未应用。";
    target.value = importDocument.value;
    return;
  }
  importDocument.value = target.value;
  importError.value = null;
}

function requestExport(): void {
  const planJson = assembled.value.json;
  if (
    !canExport.value ||
    planJson === null ||
    utf8ByteLengthAtMost(planJson, MAX_PLAN_DOCUMENT_BYTES) === null
  ) {
    return;
  }
  emit("exportDocument", {
    format: exportFormat.value,
    planJson,
    planVersionId: props.plan.id,
  });
}

function utf8ByteLengthAtMost(value: string, maximum: number): number | null {
  let bytes = 0;
  for (const character of value) {
    const codePoint = character.codePointAt(0);
    if (codePoint === undefined) {
      continue;
    }
    bytes +=
      codePoint <= 0x7f
        ? 1
        : codePoint <= 0x7ff
          ? 2
          : codePoint <= 0xffff
            ? 3
            : 4;
    if (bytes > maximum) {
      return null;
    }
  }
  return bytes;
}

function executablePreview(document: PlanRecord | null): readonly string[] {
  if (document === null) {
    return ["草稿 JSON 无法解析；等待修正后再生成预览。"];
  }
  const levels = recordAt(document, "levels");
  const lowBuy = recordAt(levels, "low_buy");
  const pressure = recordAt(levels, "pressure");
  return [
    `股票 ${stringAt(document, "symbol") ?? "—"} · ${stringAt(document, "name") ?? "未命名"}`,
    zonePreview("低吸区间", lowBuy),
    zonePreview("压力区间", pressure),
    `风险线 ${fenPreview(numberAt(levels, "risk_line_fen"))}`,
    `入场条件 ${conditionType(document, "entry")}`,
    `减仓条件 ${conditionType(document, "reduction")}`,
    `风险条件 ${conditionType(document, "risk")}`,
  ];
}

function recordAt(value: PlanRecord | null, key: string): PlanRecord | null {
  const candidate = value?.[key];
  return isRecord(candidate) ? candidate : null;
}

function stringAt(value: PlanRecord | null, key: string): string | null {
  const candidate = value?.[key];
  return typeof candidate === "string" ? candidate : null;
}

function numberAt(value: PlanRecord | null, key: string): number | null {
  const candidate = value?.[key];
  return typeof candidate === "number" && Number.isFinite(candidate) ? candidate : null;
}

function zonePreview(label: string, zone: PlanRecord | null): string {
  return `${label} ${fenValue(numberAt(zone, "low_fen"))}–${fenValue(numberAt(zone, "high_fen"))} 元`;
}

function fenPreview(value: number | null): string {
  return value === null ? "—" : `${(value / 100).toFixed(2)} 元`;
}

function fenValue(value: number | null): string {
  return value === null ? "—" : (value / 100).toFixed(2);
}

function conditionType(document: PlanRecord, section: SectionKey): string {
  const condition = recordAt(recordAt(document, section), "condition");
  return stringAt(condition, "type") ?? "—";
}
</script>

<template>
  <section class="structured-editor" aria-labelledby="structured-editor-title">
    <header class="structured-editor__header">
      <div>
        <p class="structured-editor__eyebrow">STRUCTURED DRAFT</p>
        <h2 id="structured-editor-title" class="structured-editor__title">结构化计划编辑</h2>
      </div>
      <span class="structured-editor__status">{{ plan.status }} · v{{ plan.version }}</span>
    </header>

    <p class="structured-editor__boundary">
      此处只编辑草稿数据；后端计划模型和确定性校验仍是唯一权威。
    </p>

    <div v-if="conflictRevision !== null" class="structured-editor__conflict" data-testid="revision-conflict" role="alert">
      <p>服务器已更新到修订 {{ conflictRevision }}，本地未保存内容尚未覆盖。</p>
      <button data-testid="reload-server-version" type="button" @click="loadPlan(plan)">
        载入服务器版本
      </button>
    </div>

    <label class="structured-editor__label" for="plan-name">计划名称</label>
    <input
      id="plan-name"
      class="structured-editor__input"
      type="text"
      :disabled="busy"
      :value="planName"
      @input="updateName"
    />

    <div class="structured-editor__sections">
      <article
        v-for="section in SECTION_DEFINITIONS"
        :key="section.key"
        class="structured-editor__section"
        data-testid="plan-section"
      >
        <label class="structured-editor__label" :for="`plan-section-${section.key}`">
          {{ section.label }} · <code>{{ section.key }}</code>
        </label>
        <textarea
          :id="`plan-section-${section.key}`"
          class="structured-editor__textarea"
          :data-section="section.key"
          :disabled="busy"
          rows="8"
          spellcheck="false"
          :value="sectionTexts[section.key]"
          @input="updateSection(section.key, $event)"
        />
      </article>
    </div>

    <p v-if="loadError || editError || assembled.error" class="structured-editor__error" role="alert">
      {{ loadError ?? editError ?? assembled.error }}
    </p>

    <section class="structured-editor__preview" data-testid="executable-preview" aria-labelledby="executable-preview-title">
      <h3 id="executable-preview-title">人类可读执行预览</h3>
      <p>仅用于核对配置，不在浏览器执行或判定条件。</p>
      <ul>
        <li v-for="item in preview" :key="item">{{ item }}</li>
      </ul>
    </section>

    <section class="structured-editor__issues" aria-labelledby="validation-issue-title">
      <h3 id="validation-issue-title">后端校验与审核问题</h3>
      <p v-if="!(plan.validationIssues?.length || plan.reviewIssues?.length)">当前版本未返回问题。</p>
      <article v-for="issue in plan.validationIssues ?? []" :key="`${issue.code}:${issue.path}`">
        <code>{{ issue.path }}</code>
        <strong>{{ issue.code }}</strong>
        <span>{{ issue.message }}</span>
      </article>
      <article v-for="issue in plan.reviewIssues ?? []" :key="`${issue.kind}:${issue.path}`">
        <code>{{ issue.path }}</code>
        <strong>{{ issue.kind }}</strong>
        <span>{{ issue.resolved ? "已处理" : "未处理" }}</span>
      </article>
    </section>

    <div class="structured-editor__actions">
      <button data-testid="save-draft" type="button" :disabled="!canSave" @click="saveDraft">
        {{ plan.status === "ACTIVE" ? "另存为新草稿" : "保存草稿" }}
      </button>
    </div>

    <div class="structured-editor__portable">
      <form data-testid="import-plan" class="structured-editor__portable-panel" @submit.prevent="submitImport">
        <h3>导入 YAML / JSON</h3>
        <label class="structured-editor__label" for="plan-import-format">格式</label>
        <select id="plan-import-format" v-model="importFormat" :disabled="busy">
          <option value="JSON">JSON</option>
          <option value="YAML">YAML</option>
        </select>
        <label class="structured-editor__label" for="plan-import-document">文档</label>
        <textarea
          id="plan-import-document"
          :value="importDocument"
          :disabled="busy"
          rows="8"
          spellcheck="false"
          @input="updateImportDocument"
        />
        <p v-if="importError" role="alert">{{ importError }}</p>
        <button type="submit" :disabled="!canImport">提交后端安全导入</button>
      </form>

      <section class="structured-editor__portable-panel" aria-labelledby="export-plan-title">
        <h3 id="export-plan-title">导出 YAML / JSON</h3>
        <label class="structured-editor__label" for="plan-export-format">格式</label>
        <select id="plan-export-format" v-model="exportFormat" :disabled="busy">
          <option value="JSON">JSON</option>
          <option value="YAML">YAML</option>
        </select>
        <button data-testid="export-plan" type="button" :disabled="!canExport" @click="requestExport">
          请求导出
        </button>
      </section>
    </div>
  </section>
</template>

<style scoped>
.structured-editor {
  display: grid;
  gap: var(--space-5);
  padding: var(--space-6);
  background: var(--color-surface-graphite);
  border: var(--border-technical);
  border-block-start: 0.25rem solid var(--color-signal-info-cyan);
}

.structured-editor__header,
.structured-editor__actions {
  display: flex;
  gap: var(--space-3);
  align-items: center;
  justify-content: space-between;
}

.structured-editor__eyebrow,
.structured-editor__title,
.structured-editor__boundary,
.structured-editor__conflict p {
  margin: 0;
}

.structured-editor__eyebrow,
.structured-editor__status {
  color: var(--color-signal-info-cyan);
  font-family: var(--font-numeric);
}

.structured-editor__title {
  font-size: 1.2rem;
}

.structured-editor__boundary,
.structured-editor__conflict,
.structured-editor__preview,
.structured-editor__issues {
  padding: var(--space-4);
  background: var(--color-surface-raised);
  border-inline-start: 0.25rem solid var(--color-signal-watch-amber);
}

.structured-editor__conflict,
.structured-editor__error {
  color: var(--color-text-mineral);
  border-inline-start-color: var(--color-signal-risk-vermilion);
}

.structured-editor__label {
  font-weight: 700;
}

.structured-editor__input,
.structured-editor__textarea,
.structured-editor__portable select,
.structured-editor__portable textarea {
  width: 100%;
  box-sizing: border-box;
  padding: var(--space-3);
  color: var(--color-text-mineral);
  background: var(--color-surface-ink);
  border: var(--border-technical);
  border-radius: var(--radius-control);
}

.structured-editor__sections {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-4);
}

.structured-editor__section,
.structured-editor__portable-panel {
  display: grid;
  gap: var(--space-2);
}

.structured-editor__issues article {
  display: grid;
  grid-template-columns: minmax(10rem, 1fr) minmax(8rem, auto) 2fr;
  gap: var(--space-3);
  overflow-wrap: anywhere;
}

.structured-editor__portable {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-4);
}

.structured-editor button {
  width: fit-content;
  min-height: 2.75rem;
  padding: var(--space-2) var(--space-4);
  color: var(--color-surface-ink);
  font-weight: 700;
  background: var(--color-signal-info-cyan);
  border: 0;
  border-radius: var(--radius-control);
}

.structured-editor button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

@media (max-width: 63.999rem) {
  .structured-editor__sections,
  .structured-editor__portable {
    grid-template-columns: 1fr;
  }
}
</style>
