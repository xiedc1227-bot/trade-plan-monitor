<script setup lang="ts">
import { useId } from "vue";
import type { DeepReadonly } from "vue";
import type { ReviewedPlanLibraryItem } from "../../api/generated-runtime-status";
defineProps<{
  items: readonly DeepReadonly<ReviewedPlanLibraryItem>[]; selected: readonly string[];
  baseId: string; creating: boolean; needsBase?: boolean;
  disabled: boolean; loading: boolean; pending: boolean; uncertain: boolean;
  error: string | null; canStart: boolean;
}>();
const emit = defineEmits<{ base: [value: string];
  toggle: [id: string]; compose: []; refresh: []; new: [] }>();
const id = useId();
</script>
<template>
  <section class="plan-library" aria-label="已审核计划库">
    <h2>准备计划</h2>
    <p>一次准备一份，回测组合多份。后续默认关联上一份已审核计划，审核时查看规则的保留、修改、新增和取消；回测持续使用同一个账户。</p>
    <div class="actions">
      <button type="button" :disabled="disabled || loading || pending" @click="emit('refresh')">刷新已审核计划</button>
      <button v-if="!creating" type="button" data-testid="prepare-next-source" :disabled="disabled || pending || loading || !canStart" @click="emit('new')">准备下一份原文</button>
    </div>
    <fieldset v-if="creating && items.length" :disabled="disabled || pending || loading">
      <legend>计划衔接</legend>
        <label :for="`${id}-base`">关联上一份已审核计划</label>
        <select :id="`${id}-base`" :value="needsBase ? '__choose__' : baseId" @change="emit('base', ($event.target as HTMLSelectElement).value)">
          <option value="__choose__" disabled>请选择上一份计划</option>
          <option value="">不关联，开始新的计划链</option>
          <option v-for="item in items" :key="item.preparationId" :value="item.preparationId">{{ item.effectiveTradeDate }} · {{ item.name }} · {{ item.sourceId }}</option>
        </select>
        <p v-if="needsBase" role="status">无法唯一确定上一份计划，请选择要延续的已审核版本，或开始新的计划链。</p>
        <p v-else>{{ baseId ? '已关联前序。保存原文后固定该版本；未明确的继承关系会在审核时集中提示。' : '本份建立新的计划链，原文未明确的信息保持未知。' }}</p>
    </fieldset>
    <p v-if="loading" role="status">正在读取已审核计划…</p>
    <p v-else-if="!items.length">还没有已审核计划。先保存下方的一份原文，提取并审核后即可加入计划库。</p>
    <fieldset v-else :disabled="disabled || pending">
      <legend>选择用于回测的已审核计划</legend>
      <label v-for="item in items" :key="item.preparationId" class="entry">
        <input type="checkbox" :checked="selected.includes(item.preparationId)" @change="emit('toggle', item.preparationId)">
        <span>{{ item.effectiveTradeDate }} · {{ item.name }}（{{ item.symbol }}）<small>{{ item.sourceId }} · {{ item.reviewedBase ? '已关联前序，组合时须包含该版本' : '计划链起点' }}</small></span>
      </label>
      <button type="button" data-testid="compose-reviewed-plans" :disabled="!selected.length || selected.length > 256" @click="emit('compose')">组合所选 {{ selected.length }} 份计划用于回测</button>
    </fieldset>
    <button v-if="uncertain" type="button" :disabled="disabled || pending && !uncertain" @click="emit('compose')">使用同一请求安全重试组合</button>
    <p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>
<style scoped>
.plan-library { min-width: 0; padding: var(--space-4); border: var(--border-technical); }
.plan-library h2 { margin-top: 0; }
.plan-library fieldset { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-3); min-width: 0; margin-top: var(--space-4); border: var(--border-technical); }
.plan-library select { width: 100%; min-width: 0; box-sizing: border-box; }
.actions { display: flex; flex-wrap: wrap; gap: var(--space-3); }
.entry { display: flex; align-items: start; gap: var(--space-3); overflow-wrap: anywhere; }
.entry small { display: block; color: var(--color-text-muted); }
.plan-library button, .plan-library select { min-height: 2.75rem; max-width: 100%; padding: var(--space-2); color: inherit; background: var(--color-surface-raised); border: var(--border-technical); border-radius: var(--radius-control); font: inherit; }
.plan-library input { min-width: 1.25rem; min-height: 1.25rem; }
.plan-library :focus-visible { outline: .1875rem solid var(--color-focus-ring); outline-offset: .1875rem; }
</style>
