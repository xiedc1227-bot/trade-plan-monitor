<script setup lang="ts">
import DailyWorkbench from "../components/daily/DailyWorkbench.vue";
defineProps<{ versionId?: string }>();
</script>
<template><DailyWorkbench :version-id="versionId" /></template>
