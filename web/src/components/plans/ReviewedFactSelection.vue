<script setup lang="ts">
import { computed, useId } from "vue";
import type { ReviewedFactChoice } from "./reviewedFactSelection";

const props = defineProps<{ choices: readonly ReviewedFactChoice[]; disabled?: boolean }>();
const model = defineModel<string>({ required: true });
const id = useId();
const selected = computed(() => props.choices.find(choice => choice.key === model.value));
</script>

<template>
  <div class="reviewed-fact-selection">
    <label :for="id">选择本次实际核验的准确条件</label>
    <select :id="id" v-model="model" data-fact-selection :disabled="disabled || !choices.length">
      <option value="">尚未选择具体条件（使用原有核验方式）</option>
      <option v-for="choice in choices" :key="choice.key" :value="choice.key">{{ choice.selection.ownerId }} · {{ choice.requirement }} · {{ choice.selection.conditionPath }}</option>
    </select>
    <p>此处可选择普通买卖规则中按交易日核验的条件。关联单次信号、重置、提醒和风险条件暂不支持精确选择。</p>
    <p v-if="!choices.length">本计划暂无可精确选择的条件；含大盘联动等扩展计划暂不支持此选择。其他已有核验仍可使用。</p>
    <template v-if="selected"><blockquote>{{ selected.requirement }}</blockquote>
      <p>以上是计划中待核验的要求，不是已核验证据。请按实际观察自行填写证据，明确满足或不满足。</p>
    </template>
  </div>
</template>

<style scoped>
.reviewed-fact-selection { display: grid; gap: var(--space-2); min-width: 0; overflow-wrap: anywhere; }
.reviewed-fact-selection select { width: 100%; min-width: 0; min-height: 2.75rem; padding: var(--space-2); color: var(--color-text-mineral); background: var(--color-surface-graphite); border: var(--border-technical); }
</style>
