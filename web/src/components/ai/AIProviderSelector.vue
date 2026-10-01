<script setup lang="ts">
import { computed } from "vue";

import type { ConfiguredAIRuntimeView } from "../../api/generated";

interface Props {
  disabled?: boolean;
  loading?: boolean;
  providers: readonly ConfiguredAIRuntimeView[];
  selectedProviderId: string | null;
}

interface Emits {
  select: [providerId: string];
}

const props = withDefaults(defineProps<Props>(), {
  disabled: false,
  loading: false,
});
const emit = defineEmits<Emits>();

const selectedProvider = computed(() =>
  props.providers.find((provider) => provider.providerId === props.selectedProviderId),
);

function handleSelect(event: Event): void {
  const target = event.target;
  if (target instanceof HTMLSelectElement && target.value !== "") {
    emit("select", target.value);
  }
}

</script>

<template>
  <section class="provider-selector" aria-labelledby="provider-selector-title">
    <div class="provider-selector__heading">
      <div>
        <h2 id="provider-selector-title" class="provider-selector__title">当前 AI 配置</h2>
      </div>
      <span class="provider-selector__boundary">配置文件只读</span>
    </div>

    <label class="provider-selector__label" for="ai-provider">已配置供应商</label>
    <select
      id="ai-provider"
      class="provider-selector__control"
      :disabled="disabled || loading || providers.length === 0"
      :value="selectedProviderId ?? ''"
      @change="handleSelect"
    >
      <option v-if="providers.length === 0" value="">{{ loading ? "正在读取 AI 配置" : "尚无可用供应商" }}</option>
      <option
        v-for="provider in providers"
        :key="provider.providerId"
        :value="provider.providerId"
      >
        {{ provider.displayName }} · {{ provider.model }}{{
          provider.enabled === false ? " · 已禁用" : ""
        }}
      </option>
    </select>

    <p v-if="loading" class="provider-selector__hint" role="status">
      正在读取 AI 配置，可先填写计划原文。
    </p>

    <dl v-if="selectedProvider" class="provider-selector__facts">
      <div>
        <dt>模型</dt>
        <dd>{{ selectedProvider.model }}</dd>
      </div>
      <div>
        <dt>服务地址</dt>
        <dd>{{ selectedProvider.baseUrl }}</dd>
      </div>
      <div>
        <dt>原文长度上限</dt>
        <dd>{{ selectedProvider.maxInputChars }} 个字符</dd>
      </div>
      <div>
        <dt>密钥状态</dt>
        <dd>
          {{ selectedProvider.configured ? "已配置" : "未配置" }}
        </dd>
      </div>
    </dl>

    <p class="provider-selector__hint">
      修改 config/app.yaml 后需要重启 Web 服务；页面不会读取或写入密钥原值。
    </p>
  </section>
</template>

<style scoped>
.provider-selector {
  display: grid;
  gap: var(--space-4);
  padding: var(--space-6);
  background: var(--color-surface-graphite);
  border: var(--border-technical);
  border-block-start: 0.25rem solid var(--color-signal-info-cyan);
  border-radius: var(--radius-panel);
}

.provider-selector__heading {
  display: flex;
  gap: var(--space-3);
  align-items: center;
  justify-content: space-between;
}

.provider-selector__title,
.provider-selector__hint,
.provider-selector__facts dd {
  margin: 0;
}

.provider-selector__boundary {
  color: var(--color-signal-info-cyan);
  font-family: var(--font-numeric);
  font-size: 0.75rem;
  letter-spacing: 0.08em;
}

.provider-selector__title {
  font-size: 1.1rem;
}

.provider-selector__boundary {
  padding: var(--space-1) var(--space-2);
  border: var(--border-technical);
}

.provider-selector__label {
  color: var(--color-text-mineral);
  font-weight: 700;
}

.provider-selector__control {
  width: 100%;
  min-height: 2.75rem;
  padding: var(--space-2) var(--space-3);
  color: var(--color-text-mineral);
  background: var(--color-surface-ink);
  border: var(--border-technical);
  border-radius: var(--radius-control);
}

.provider-selector__facts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
  margin: 0;
}

.provider-selector__facts div {
  min-width: 0;
  padding: var(--space-3);
  background: var(--color-surface-raised);
  border-inline-start: 0.1875rem solid var(--color-border-quiet);
}

.provider-selector__facts dt {
  color: var(--color-text-muted);
  font-size: 0.75rem;
}

.provider-selector__facts dd {
  overflow-wrap: anywhere;
}

.provider-selector__hint {
  color: var(--color-text-muted);
  font-size: 0.85rem;
}

@media (max-width: 47.999rem) {
  .provider-selector__heading {
    align-items: stretch;
    flex-direction: column;
  }

  .provider-selector__facts {
    grid-template-columns: 1fr;
  }
}
</style>
