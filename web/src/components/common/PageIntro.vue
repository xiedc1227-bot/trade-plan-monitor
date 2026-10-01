<script setup lang="ts">
defineProps<{ title: string; titleId?: string; eyebrow: string; description: string }>();
</script>

<template>
  <header class="page-intro">
    <div class="page-intro__copy">
      <p class="page-intro__eyebrow">{{ eyebrow }}</p>
      <h1 :id="titleId">{{ title }}</h1>
      <p class="page-intro__description">{{ description }}</p>
    </div>
    <div v-if="$slots.default" class="page-intro__action"><slot /></div>
  </header>
</template>

<style scoped>
.page-intro { display: flex; justify-content: space-between; align-items: end; gap: var(--space-6); padding-block: var(--space-4) var(--space-7); border-block-end: var(--border-technical); }
.page-intro__copy { min-width: 0; }
.page-intro__eyebrow { margin: 0 0 var(--space-4); color: var(--color-signal-watch-amber); font: 500 .6875rem var(--font-numeric); letter-spacing: .18em; }
.page-intro h1 { margin: 0; }
.page-intro__description { margin: var(--space-3) 0 0; color: var(--color-text-muted); font-size: .875rem; }
.page-intro__action { flex-shrink: 0; }
@media (max-width: 39.999rem) { .page-intro { flex-direction: column; align-items: start; } }
</style>
