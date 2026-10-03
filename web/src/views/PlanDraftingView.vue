<script setup lang="ts">
import PlanWorkbench from "../components/plans/PlanWorkbench.vue";
defineProps<{ planVersionId?: string }>();
</script>

<template><PlanWorkbench :plan-version-id="planVersionId" /></template>
