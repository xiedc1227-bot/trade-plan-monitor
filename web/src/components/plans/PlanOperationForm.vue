<script setup lang="ts">
import { computed, shallowRef, watch } from "vue";
import PlanFieldEditor from "./PlanFieldEditor.vue";
import { initialValue, type Json, type Schema } from "./planSchema";
const props = defineProps<{ schema: Schema; binding: Record<string, Json>; title: string; description: string; busy: boolean;
  hiddenFields?: string[]; initialValues?: Record<string, Json>; operation?: string; blocked?: boolean }>();
const emit = defineEmits<{ submit: [value: Json] }>();
const value = shallowRef<Json>(null);
function sameBinding(left: Json | undefined, right: Json | undefined, key: string) {
  return Object.is(left, right) || key === "conditionSelection" && JSON.stringify(left) === JSON.stringify(right);
}
watch(() => [props.schema, props.binding] as const, ([schema, binding], previous) => {
  if (previous?.[0] === schema && previous[1]
    && Object.keys(binding).length === Object.keys(previous[1]).length
    && Object.entries(binding).every(([key, entry]) => Object.hasOwn(previous[1], key) && sameBinding(previous[1][key], entry, key))) return;
  const initial = initialValue(props.schema);
  value.value = initial !== null && typeof initial === "object" && !Array.isArray(initial) ? { ...initial, ...props.initialValues, ...props.binding } : initial;
}, { immediate: true });
const definitions = computed(() => props.schema.$defs ?? {});
const invalidPosition = computed(() => props.operation === "POSITION" && (
  value.value === null || typeof value.value !== "object" || Array.isArray(value.value) ||
  [value.value.coreQty, value.value.tacticalQty].some(qty => typeof qty !== "number" || !Number.isSafeInteger(qty) || qty < 0 || qty % 100 !== 0)
));
const incompleteFact = computed(() => props.operation === "FACT" && props.binding.conditionSelection != null && (
  value.value === null || typeof value.value !== "object" || Array.isArray(value.value) ||
  typeof value.value.satisfied !== "boolean" || typeof value.value.evidence !== "string" ||
  value.value.evidence.trim().length < 20
));
function submit() {
  if (props.busy || props.blocked || invalidPosition.value || incompleteFact.value) return;
  const command = value.value !== null && typeof value.value === "object" && !Array.isArray(value.value)
    ? { ...value.value, ...props.binding } : value.value;
  // The public optional selector rejects explicit null. Preserve any nonempty value.
  if (props.operation === "FACT" && command !== null && typeof command === "object" && !Array.isArray(command)
      && command.conditionSelection === null) delete command.conditionSelection;
  emit("submit", command);
}
</script>
<template>
  <form class="daily-operation" @submit.prevent="submit">
    <h3>{{ title }}</h3><p>{{ description }}</p>
    <PlanFieldEditor :schema="schema" :definitions="definitions" path="" :id-prefix="`operation-${operation ?? 'fact'}`" v-model="value" :hidden-fields="hiddenFields ?? []" />
    <p v-if="blocked" role="status">当前绑定尚未就绪，请先刷新当前状态。</p>
    <p v-if="invalidPosition">CORE与TACTICAL都须填写0或100股的整数倍。</p>
    <p v-if="incompleteFact" role="status">请自行填写实际观察证据，并明确选择满足或不满足。</p>
    <button type="submit" :disabled="busy || blocked || invalidPosition || incompleteFact">确认登记{{ title }}</button>
  </form>
</template>
<style scoped>.daily-operation { display: grid; gap: var(--space-3); }</style>
