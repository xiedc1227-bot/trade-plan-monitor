<script setup lang="ts">
import { computed } from "vue";
import { choiceLabels, fieldLabels, initialValue, resolveSchema, schemaChoices, type Json, type Schema } from "./planSchema";

const props = defineProps<{ schema: Schema; definitions: Record<string, Schema>; path: string; modelValue: Json;
  hiddenFields?: string[]; labels?: Record<string, string>; idPrefix?: string }>();
const emit = defineEmits<{ "update:modelValue": [value: Json] }>();
const resolved = computed(() => resolveSchema(props.schema, props.definitions));
const choices = computed(() => resolved.value.anyOf || resolved.value.oneOf ? schemaChoices(resolved.value, props.definitions) : []);
const selected = computed(() => {
  if (!choices.value.length) return resolved.value;
  if (props.modelValue !== null && typeof props.modelValue === "object" && !Array.isArray(props.modelValue)) {
    const data = props.modelValue;
    if (choices.value.some(s => s.properties?.market_policy)) {
      const quantityKind = "market_policy" in data ? "market_policy" : "quantity";
      return choices.value.find(s => s.properties?.[quantityKind]) ?? {};
    }
    for (const key of ["type", "kind", "mode", "status", "side"]) {
      const match = choices.value.find(s => s.properties?.[key]?.const !== undefined && s.properties[key]?.const === data[key]);
      if (match) return match;
    }
    return choices.value[0] ?? {};
  }
  return choices.value[0] ?? {};
});
const fieldId = computed(() => `${props.idPrefix ?? "daily"}-${props.path}`);
const choiceId = computed(() => selected.value.properties || selected.value.type === "array"
  ? fieldId.value : `${fieldId.value}-choice`);
const nullable = computed(() => (props.schema.anyOf ?? props.schema.oneOf ?? []).some(s => s.type === "null"));
const label = computed(() => props.labels?.[props.path.split(".").at(-1) ?? ""] ?? fieldLabels[props.path.split(".").at(-1) ?? ""] ?? props.path.split(".").at(-1));
const visibleProperties = computed(() => Object.fromEntries(Object.entries(selected.value.properties ?? {})
  .filter(([key]) => props.path !== "" || !props.hiddenFields?.includes(key))));
const objectValue = computed(() => props.modelValue !== null && typeof props.modelValue === "object" && !Array.isArray(props.modelValue) ? props.modelValue : {});
const arrayValue = computed(() => Array.isArray(props.modelValue) ? props.modelValue : []);
const scalarChoices = computed(() => selected.value.enum ?? (selected.value.type === "boolean" ? [true, false] : []));
function changeField(key: string, value: Json) { emit("update:modelValue", { ...objectValue.value, [key]: value }); }
function changeItem(index: number, value: Json) { emit("update:modelValue", arrayValue.value.map((v, i) => i === index ? value : v)); }
function changeChoice(event: Event) {
  const choice = choices.value[Number((event.target as HTMLSelectElement).value)];
  if (choice) emit("update:modelValue", initialValue(choice));
}
function scalar(event: Event) {
  const value = (event.target as HTMLInputElement).value;
  emit("update:modelValue", value === "" ? null : selected.value.format === "date-time" ? `${value}+08:00` : ["integer", "number"].includes(selected.value.type ?? "") ? Number(value) : value);
}
</script>

<template>
  <div class="daily-field">
    <label :for="fieldId" class="daily-field__label">{{ label }}</label>
    <select v-if="choices.length > 1" :id="choiceId" aria-label="选择明确条件或模式" :value="modelValue === null ? '' : choices.indexOf(selected)" @change="changeChoice">
      <option value="" disabled>请选择，保持未知直到人工定义</option>
      <option v-for="(choice, index) in choices" :key="index" :value="index">{{ choiceLabels[choice.title ?? ''] ?? choice.title ?? choice.type }}</option>
    </select>
    <template v-if="modelValue !== null && selected.properties">
      <fieldset class="daily-field__group">
        <legend>{{ label }}</legend>
        <PlanFieldEditor v-for="(child, key) in visibleProperties" :key="key" :schema="child" :definitions="definitions" :labels="labels ?? {}" :id-prefix="idPrefix ?? 'daily'"
          :path="`${path}.${key}`" :model-value="objectValue[key] ?? null" @update:model-value="changeField(key, $event)" />
      </fieldset>
    </template>
    <template v-else-if="modelValue !== null && selected.type === 'array'">
      <div v-for="(item, index) in arrayValue" :key="index" class="daily-field__item">
        <PlanFieldEditor :schema="selected.items ?? {}" :definitions="definitions" :id-prefix="idPrefix ?? 'daily'"
          :path="`${path}[${index}]`" :model-value="item" @update:model-value="changeItem(index, $event)" />
        <button type="button" :disabled="arrayValue.length <= (selected.minItems ?? 0)" @click="emit('update:modelValue', arrayValue.filter((_, i) => i !== index))">移除此{{ label }}</button>
      </div>
      <button type="button" :disabled="arrayValue.length >= (selected.maxItems ?? 50)"
        @click="emit('update:modelValue', [...arrayValue, initialValue(resolveSchema(selected.items ?? {}, definitions))])">添加{{ label }}</button>
    </template>
    <template v-else-if="selected.properties || selected.type === 'array'">
      <button type="button" @click="emit('update:modelValue', initialValue(selected))">填写{{ label }}</button>
      <small>待人工定义</small>
    </template>
    <input v-else-if="selected.const !== undefined" :id="fieldId" :value="String(selected.const)" readonly />
    <select v-else-if="scalarChoices.length" :id="fieldId" :value="modelValue === null ? '' : scalarChoices.indexOf(modelValue)"
      @change="emit('update:modelValue', scalarChoices[Number(($event.target as HTMLSelectElement).value)] ?? null)">
      <option value="" disabled>待确认</option><option v-for="(value, index) in scalarChoices" :key="index" :value="index">{{ value === true ? '是' : value === false ? '否' : choiceLabels[String(value)] ?? value }}</option>
    </select>
    <input v-else :id="fieldId" :value="selected.format === 'date-time' && typeof modelValue === 'string' ? modelValue.replace(/\+08:00$/, '') : modelValue ?? ''" :type="selected.format === 'date' ? 'date' : selected.format === 'date-time' ? 'datetime-local' : ['integer','number'].includes(selected.type ?? '') ? 'number' : 'text'"
      :step="selected.multipleOf ?? (selected.type === 'integer' || selected.format === 'date-time' ? '1' : 'any')" :min="selected.minimum" placeholder="待确认，填写明确参数" @input="scalar" />
    <button v-if="nullable && modelValue !== null" type="button" @click="emit('update:modelValue', null)">清除可选{{ label }}</button>
  </div>
</template>

<style scoped>
.daily-field { display: grid; gap: var(--space-2); min-width: 0; }
.daily-field__label { font-weight: 500; overflow-wrap: anywhere; }
.daily-field input, .daily-field select { box-sizing: border-box; width: 100%; min-width: 0; max-width: 100%; padding: var(--space-2); color: var(--color-text-mineral); background: var(--color-surface-graphite); border: var(--border-technical); }
.daily-field__item { min-width: 0; }
.daily-field__group { display: grid; gap: var(--space-3); min-width: 0; padding: var(--space-4); border: var(--border-technical); }
</style>
