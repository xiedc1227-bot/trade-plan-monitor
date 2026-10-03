<script setup lang="ts">
import { computed, shallowRef, watch } from "vue";
import PlanFieldEditor from "./PlanFieldEditor.vue";
import { initialValue, type Json, type Schema } from "./planSchema";
const props = defineProps<{ schema: Schema; binding: Record<string, Json>; title: string; description: string; busy: boolean;
  hiddenFields?: string[]; initialValues?: Record<string, Json>; operation?: string; blocked?: boolean }>();
const emit = defineEmits<{ submit: [value: Json] }>();
const value = shallowRef<Json>(null);
watch(() => [props.schema, props.binding] as const, () => {
  const initial = initialValue(props.schema);
  value.value = initial !== null && typeof initial === "object" && !Array.isArray(initial) ? { ...initial, ...props.initialValues, ...props.binding } : initial;
}, { immediate: true });
const definitions = computed(() => props.schema.$defs ?? {});
const invalidPosition = computed(() => props.operation === "POSITION" && (
  value.value === null || typeof value.value !== "object" || Array.isArray(value.value) ||
  [value.value.coreQty, value.value.tacticalQty].some(qty => typeof qty !== "number" || !Number.isSafeInteger(qty) || qty < 0 || qty % 100 !== 0)
));
</script>
<template>
  <form class="daily-operation" @submit.prevent="!blocked && !invalidPosition && emit('submit', value !== null && typeof value === 'object' && !Array.isArray(value) ? { ...value, ...binding } : value)">
    <h3>{{ title }}</h3><p>{{ description }}</p>
    <PlanFieldEditor :schema="schema" :definitions="definitions" path="" :id-prefix="`operation-${operation ?? 'fact'}`" v-model="value" :hidden-fields="hiddenFields ?? []" />
    <p v-if="blocked" role="status">当前绑定尚未就绪，请先刷新当前状态。</p>
    <p v-if="invalidPosition">CORE与TACTICAL都须填写0或100股的整数倍。</p>
    <button type="submit" :disabled="busy || blocked || invalidPosition">确认登记{{ title }}</button>
  </form>
</template>
<style scoped>.daily-operation { display: grid; gap: var(--space-3); }</style>
