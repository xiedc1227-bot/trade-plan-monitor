<script setup lang="ts">
import { useTemplateRef } from "vue";

export type PlanCreationMode = "AI" | "IMPORT";

const mode = defineModel<PlanCreationMode>({ required: true });
const importTab = useTemplateRef<HTMLButtonElement>("importTab");
const aiTab = useTemplateRef<HTMLButtonElement>("aiTab");

function selectMode(nextMode: PlanCreationMode): void {
  mode.value = nextMode;
}

function selectModeFromKeyboard(event: KeyboardEvent): void {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  const nextMode = event.key === "ArrowLeft" || event.key === "Home" ? "AI" : "IMPORT";
  mode.value = nextMode;
  (nextMode === "IMPORT" ? importTab.value : aiTab.value)?.focus();
}
</script>

<template>
  <section class="creation-switcher" aria-label="创建计划版本">
    <div class="creation-switcher__intro">
      <div>
        <p class="creation-switcher__eyebrow">NEW PLAN VERSION</p>
        <p class="creation-switcher__title">选择创建方式</p>
      </div>
      <p class="creation-switcher__description">
        导入适合已有结构化文档；AI 提取适合从中文原文生成待审核草稿。
      </p>
    </div>

    <div
      class="creation-switcher__tabs"
      role="tablist"
      aria-label="计划版本创建方式"
      @keydown="selectModeFromKeyboard"
    >
      <button
        id="plan-creation-ai-tab"
        ref="aiTab"
        class="creation-switcher__tab"
        data-testid="creation-mode-ai"
        type="button"
        role="tab"
        aria-controls="plan-creation-ai-panel"
        :aria-selected="mode === 'AI'"
        :tabindex="mode === 'AI' ? 0 : -1"
        @click="selectMode('AI')"
      >
        <span>从原文 AI 提取</span>
        <small>生成隔离草稿，人工审核后再保存</small>
      </button>
      <button
        id="plan-creation-import-tab"
        ref="importTab"
        class="creation-switcher__tab"
        data-testid="creation-mode-import"
        type="button"
        role="tab"
        aria-controls="plan-creation-import-panel"
        :aria-selected="mode === 'IMPORT'"
        :tabindex="mode === 'IMPORT' ? 0 : -1"
        @click="selectMode('IMPORT')"
      >
        <span>导入 JSON / YAML</span>
        <small>迁移、备份或直接创建 Schema v1 版本</small>
      </button>
    </div>

    <div
      id="plan-creation-import-panel"
      class="creation-switcher__panel"
      data-testid="creation-panel-import"
      role="tabpanel"
      aria-labelledby="plan-creation-import-tab"
      v-show="mode === 'IMPORT'"
    >
      <slot name="import" />
    </div>
    <div
      id="plan-creation-ai-panel"
      class="creation-switcher__panel"
      data-testid="creation-panel-ai"
      role="tabpanel"
      aria-labelledby="plan-creation-ai-tab"
      v-show="mode === 'AI'"
    >
      <slot name="ai" />
    </div>
  </section>
</template>

<style scoped>
.creation-switcher {
  display: grid;
  gap: var(--space-4);
  box-sizing: border-box;
  width: min(100%, 90rem);
  margin: 0 auto;
}

.creation-switcher__intro {
  display: flex;
  gap: var(--space-6);
  align-items: end;
  justify-content: space-between;
}

.creation-switcher__eyebrow,
.creation-switcher__title,
.creation-switcher__description {
  margin: 0;
}

.creation-switcher__eyebrow {
  color: var(--color-signal-info-cyan);
  font-family: var(--font-numeric);
  font-size: 0.75rem;
  letter-spacing: 0.08em;
}

.creation-switcher__title {
  font-size: 1.25rem;
  font-weight: 700;
}

.creation-switcher__description {
  max-width: 42rem;
  color: var(--color-text-muted);
  text-align: end;
}

.creation-switcher__tabs {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-2);
  padding: var(--space-2);
  background: var(--color-surface-graphite);
  border: var(--border-technical);
}

.creation-switcher__tab {
  display: grid;
  gap: var(--space-1);
  min-width: 0;
  padding: var(--space-3) var(--space-4);
  color: var(--color-text-muted);
  text-align: start;
  background: transparent;
  border: 0;
  border-inline-start: 0.25rem solid transparent;
}

.creation-switcher__tab span {
  color: var(--color-text-mineral);
  font-weight: 700;
}

.creation-switcher__tab small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.creation-switcher__tab[aria-selected="true"] {
  background: var(--color-surface-raised);
  border-inline-start-color: var(--color-signal-info-cyan);
}

.creation-switcher__panel {
  min-width: 0;
}

@media (max-width: 47.999rem) {
  .creation-switcher__intro {
    align-items: start;
    flex-direction: column;
    gap: var(--space-2);
  }

  .creation-switcher__description {
    text-align: start;
  }

  .creation-switcher__tabs {
    grid-template-columns: 1fr;
  }

  .creation-switcher__tab small {
    white-space: normal;
  }
}
</style>
