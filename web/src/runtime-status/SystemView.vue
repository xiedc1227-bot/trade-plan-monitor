<script setup lang="ts">
import LegacyPlanInvalidationPanel from "../components/health/LegacyPlanInvalidationPanel.vue";
import PageIntro from "../components/common/PageIntro.vue";
import { useRuntimeContext } from "./context";
import { displayTime } from "./presentation";
import StatusBoard from "./StatusBoard.vue";
import { useRuntimeRead } from "./useRuntimeRead";
const { api, store } = useRuntimeContext();
const { value: health, error, loading } = useRuntimeRead((signal) => api.getHealth(signal), [() => store.observedAt, () => store.snapshot]);
</script>

<template>
  <section class="runtime-page">
    <PageIntro title="系统健康" description="运行是否就绪，数据是否完整。逐项核对每个监控环节。" />
    <p v-if="error" role="status">{{ error }}</p>
    <p v-if="loading" role="status">正在读取系统资源。</p>
    <StatusBoard v-if="store.runtimeStatus" :status="store.runtimeStatus" expanded />
    <template v-if="health">
      <section class="runtime-panel" aria-label="资源状态">
        <h2>资源状态</h2>
        <dl class="runtime-facts">
          <div><dt>进程启动</dt><dd>{{ displayTime(health.startedAt) }}</dd></div>
          <div><dt>最近完成分钟</dt><dd>{{ displayTime(health.lastCompletedMinute) }}</dd></div>
          <div><dt>最近求值</dt><dd>{{ displayTime(health.latestEvaluationAt) }}</dd></div>
          <div><dt>数据库</dt><dd>{{ health.database.status }} · {{ health.database.walStatus }}</dd></div>
          <div><dt>通知渠道</dt><dd>{{ health.delivery.status }}；等待 {{ health.delivery.pendingCount }}；失败 {{ health.delivery.failedCount }}</dd></div>
          <div><dt>执行器</dt><dd>{{ health.executor.activeCount }} / {{ health.executor.maxWorkers }}；等待 {{ health.executor.waitingCount }}</dd></div>
        </dl>
        <ul aria-label="提供方资源"><li v-for="provider in health.providers" :key="provider.capability">{{ provider.capability }} · {{ provider.status }} · {{ provider.errorCode ?? '—' }}</li></ul>
      </section>
    </template>
    <LegacyPlanInvalidationPanel v-if="store.runtimeStatus?.reasonCode === 'LEGACY_PLANS_REQUIRE_REVIEW'" />
  </section>
</template>
