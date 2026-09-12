<script setup lang="ts">
import type { ExplicitConditionEvidenceView } from "../../api/generated";
defineProps<{ evidence: ExplicitConditionEvidenceView }>();
</script>

<template>
  <ul class="explicit-condition-evidence">
    <li>
      <span>{{ evidence.code }} · {{ evidence.outcome }}</span>
      <dl v-if="evidence.facts?.length">
        <template v-for="fact in evidence.facts" :key="fact.key">
          <dt>{{ fact.key }}</dt><dd>{{ fact.value }} {{ fact.unit }}</dd>
        </template>
      </dl>
      <p v-if="evidence.missingInputs?.length">缺失：{{ evidence.missingInputs.join("、") }}</p>
      <ExplicitConditionEvidence v-for="child in evidence.children" :key="child.planPath" :evidence="child" />
    </li>
  </ul>
</template>

<style scoped>
.explicit-condition-evidence { overflow-wrap: anywhere; padding-inline-start: 1.2rem; }
dl { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
dd { margin: 0; }
</style>
