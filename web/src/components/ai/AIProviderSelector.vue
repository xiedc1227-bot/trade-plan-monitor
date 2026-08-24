<script setup lang="ts">
import { computed, shallowRef, watch } from "vue";

import type {
  AIProviderSecretCommand,
  AIProviderTestCommand,
  AIProviderView,
  OperationReceipt,
} from "../../api/generated";

const MAX_SECRET_CHARACTERS = 8_192;

interface Props {
  disabled?: boolean;
  providerTestProviderId?: string | null;
  providerTestReceipt?: OperationReceipt | null;
  providers: readonly AIProviderView[];
  selectedProviderId: string | null;
  testing?: boolean;
}

interface Emits {
  replaceSecret: [command: AIProviderSecretCommand];
  select: [providerId: string];
  test: [command: AIProviderTestCommand];
}

const props = withDefaults(defineProps<Props>(), {
  disabled: false,
  providerTestProviderId: null,
  providerTestReceipt: null,
  testing: false,
});
const emit = defineEmits<Emits>();

const secretValue = shallowRef("");
const secretInputRejected = shallowRef(false);
const secretProviderId = shallowRef<string | null>(null);
const testingProviderId = shallowRef<string | null>(null);
const secretCharacterCount = computed(() =>
  boundedUnicodeCharacterCount(secretValue.value, MAX_SECRET_CHARACTERS + 1),
);
const selectedProvider = computed(() =>
  props.providers.find((provider) => provider.config.providerId === props.selectedProviderId),
);
const canManageSecret = computed(
  () => selectedProvider.value !== undefined && !props.disabled,
);
const matchingProviderTestReceipt = computed(
  () =>
    props.providerTestReceipt?.kind === "AI_PROVIDER_TEST" &&
    props.providerTestProviderId === props.selectedProviderId,
);
const canTest = computed(
  () =>
    canManageSecret.value &&
    selectedProvider.value?.config.enabled !== false &&
    !props.testing &&
    testingProviderId.value !== props.selectedProviderId &&
    !matchingProviderTestReceipt.value,
);

watch(
  () => props.selectedProviderId,
  () => {
    secretValue.value = "";
    secretInputRejected.value = false;
    secretProviderId.value = null;
  },
  { flush: "sync" },
);

watch(
  secretValue,
  (value) => {
    secretProviderId.value = value.length === 0 ? null : props.selectedProviderId;
  },
  { flush: "sync" },
);

watch(
  () => [props.providerTestReceipt, props.providerTestProviderId] as const,
  ([receipt, providerId]) => {
    if (
      receipt?.kind === "AI_PROVIDER_TEST" &&
      providerId === testingProviderId.value
    ) {
      testingProviderId.value = null;
    }
  },
);

watch(
  () => props.testing,
  (testing, wasTesting) => {
    if (wasTesting && !testing) {
      testingProviderId.value = null;
    }
  },
);

function handleSelect(event: Event): void {
  const target = event.target;
  if (target instanceof HTMLSelectElement && target.value !== "") {
    emit("select", target.value);
  }
}

function testProvider(): void {
  const provider = selectedProvider.value;
  if (provider === undefined || !canTest.value) {
    return;
  }
  testingProviderId.value = provider.config.providerId;
  emit("test", {
    expectedRevision: provider.revision,
    providerId: provider.config.providerId,
  });
}

function handleSecretInput(event: Event): void {
  const target = event.target;
  if (!(target instanceof HTMLInputElement)) {
    return;
  }
  if (
    boundedUnicodeCharacterCount(target.value, MAX_SECRET_CHARACTERS + 1) >
    MAX_SECRET_CHARACTERS
  ) {
    secretInputRejected.value = true;
    target.value = secretValue.value;
    return;
  }
  secretInputRejected.value = false;
  secretValue.value = target.value;
}

function replaceSecret(): void {
  const provider = selectedProvider.value;
  if (
    provider === undefined ||
    props.disabled ||
    secretInputRejected.value ||
    secretValue.value.trim().length === 0 ||
    secretProviderId.value !== provider.config.providerId ||
    secretCharacterCount.value > MAX_SECRET_CHARACTERS
  ) {
    return;
  }
  const secret = secretValue.value;
  secretValue.value = "";
  secretInputRejected.value = false;
  secretProviderId.value = null;
  emit("replaceSecret", {
    expectedRevision: provider.revision,
    providerId: provider.config.providerId,
    secret: { value: secret },
  });
}

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

</script>

<template>
  <section class="provider-selector" aria-labelledby="provider-selector-title">
    <div class="provider-selector__heading">
      <div>
        <p class="provider-selector__eyebrow">AI PROVIDER</p>
        <h2 id="provider-selector-title" class="provider-selector__title">供应商与密钥状态</h2>
      </div>
      <span class="provider-selector__boundary">只写密钥</span>
    </div>

    <label class="provider-selector__label" for="ai-provider">已配置供应商</label>
    <select
      id="ai-provider"
      class="provider-selector__control"
      :disabled="disabled || providers.length === 0"
      :value="selectedProviderId ?? ''"
      @change="handleSelect"
    >
      <option v-if="providers.length === 0" value="">尚无可用供应商</option>
      <option
        v-for="provider in providers"
        :key="provider.config.providerId"
        :value="provider.config.providerId"
      >
        {{ provider.config.displayName }} · {{ provider.config.model }}{{
          provider.config.enabled === false ? " · 已禁用" : ""
        }}
      </option>
    </select>

    <dl v-if="selectedProvider" class="provider-selector__facts">
      <div>
        <dt>模型</dt>
        <dd>{{ selectedProvider.config.model }}</dd>
      </div>
      <div>
        <dt>服务地址</dt>
        <dd>{{ selectedProvider.config.baseUrl }}</dd>
      </div>
      <div>
        <dt>提示词版本</dt>
        <dd>{{ selectedProvider.config.promptVersion ?? "plan-extract-v1" }}</dd>
      </div>
      <div>
        <dt>密钥状态</dt>
        <dd>
          {{ selectedProvider.secretStatus.maskedValue ?? "未配置" }}
          <span>（{{ selectedProvider.secretStatus.source }}）</span>
        </dd>
      </div>
    </dl>

    <div class="provider-selector__actions">
      <button
        class="provider-selector__button"
        data-testid="test-provider"
        type="button"
        :disabled="!canTest"
        @click="testProvider"
      >
        测试连接
      </button>
      <p
        v-if="matchingProviderTestReceipt"
        class="provider-selector__status"
        role="status"
        aria-live="polite"
      >
        连接测试已排队 · {{ providerTestReceipt?.operationId }}
      </p>
    </div>

    <form
      class="provider-selector__secret-form"
      data-testid="replace-secret"
      @submit.prevent="replaceSecret"
    >
      <label class="provider-selector__label" for="provider-secret">替换 API 密钥</label>
      <div class="provider-selector__secret-row">
        <input
          id="provider-secret"
          v-model="secretValue"
          class="provider-selector__control"
          type="password"
          autocomplete="off"
          spellcheck="false"
          :disabled="!canManageSecret"
          @input.capture="handleSecretInput"
        />
        <button
          class="provider-selector__button provider-selector__button--secondary"
          type="submit"
          :disabled="
            !canManageSecret ||
            secretInputRejected ||
            secretValue.trim().length === 0 ||
            secretCharacterCount > MAX_SECRET_CHARACTERS
          "
        >
          写入替换
        </button>
      </div>
      <p v-if="secretInputRejected" class="provider-selector__input-error" role="alert">
        密钥不能超过 8192 个字符；本次输入未应用。
      </p>
      <p class="provider-selector__hint">提交后输入会立即清空，界面只保留固定掩码状态。</p>
    </form>
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
}

.provider-selector__heading,
.provider-selector__secret-row,
.provider-selector__actions {
  display: flex;
  gap: var(--space-3);
  align-items: center;
  justify-content: space-between;
}

.provider-selector__eyebrow,
.provider-selector__title,
.provider-selector__hint,
.provider-selector__status,
.provider-selector__facts dd {
  margin: 0;
}

.provider-selector__eyebrow,
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

.provider-selector__button {
  min-height: 2.75rem;
  padding: var(--space-2) var(--space-4);
  color: var(--color-surface-ink);
  font-weight: 700;
  background: var(--color-signal-info-cyan);
  border: 0;
  border-radius: var(--radius-control);
  cursor: pointer;
}

.provider-selector__button--secondary {
  color: var(--color-text-mineral);
  background: var(--color-surface-raised);
  border: var(--border-technical);
}

.provider-selector__button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.provider-selector__status {
  color: var(--color-signal-watch-amber);
}

.provider-selector__secret-form {
  display: grid;
  gap: var(--space-2);
}

.provider-selector__secret-row .provider-selector__control {
  flex: 1;
}

.provider-selector__hint {
  color: var(--color-text-muted);
  font-size: 0.85rem;
}

.provider-selector__input-error {
  margin: 0;
  color: var(--color-signal-risk-vermilion);
}

@media (max-width: 47.999rem) {
  .provider-selector__heading,
  .provider-selector__secret-row,
  .provider-selector__actions {
    align-items: stretch;
    flex-direction: column;
  }

  .provider-selector__facts {
    grid-template-columns: 1fr;
  }
}
</style>
