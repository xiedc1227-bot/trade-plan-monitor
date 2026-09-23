<script setup lang="ts">
import type { RecoveryIssueView } from "../../api/generated";
import { formatDisplayDateTime } from "../../formatters/dateTime";

interface Props {
  issues: readonly RecoveryIssueView[];
}

defineProps<Props>();

const descriptions: Readonly<Record<string, string>> = {
  HISTORICAL_EVIDENCE_UNAVAILABLE: "缺少可用的收盘行情",
  HISTORICAL_RECOVERY_FAILED: "恢复过程失败",
  HISTORY_LIMIT: "恢复记录超过当前读取预算",
  INACTIVE_PLAN: "计划已停用",
  INVALID_EVIDENCE: "已保存的恢复记录不一致",
  MISSING_EVIDENCE: "缺少恢复所需记录",
  UNSUPPORTED_PLAN: "计划类型无法按此路径恢复",
  UNSUPPORTED_VERSION: "恢复记录版本暂不兼容",
};

function description(reason: string): string {
  return descriptions[reason] ?? "恢复条件未满足";
}
</script>

<template>
  <section class="recovery-issues" aria-labelledby="recovery-issues-title">
    <h2 id="recovery-issues-title">需要关注的任务恢复</h2>
    <p>以下任务暂不继续判断；其他任务不受影响。提醒不会代表实际成交。</p>
    <ul class="recovery-issues__list">
      <li v-for="issue in issues" :key="issue.symbol" data-testid="recovery-issue">
        <a :href="`/stocks/${encodeURIComponent(issue.symbol)}`">{{ issue.symbol }}</a>
        <span>{{ description(issue.reason) }}（{{ issue.reason }}）</span>
        <span>最早重试：{{ formatDisplayDateTime(issue.nextRetryAt) }}</span>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.recovery-issues {
  padding: var(--space-4);
  border: var(--border-technical);
  border-inline-start: 0.3rem solid var(--color-signal-watch-amber);
  background: var(--color-surface-raised);
}

.recovery-issues h2,
.recovery-issues p { margin: 0; }

.recovery-issues p { margin-block-start: var(--space-2); color: var(--color-text-muted); }

.recovery-issues__list { display: grid; gap: var(--space-3); padding-inline-start: var(--space-5); }

.recovery-issues__list li { display: grid; gap: var(--space-1); }

.recovery-issues__list a { color: var(--color-signal-info-cyan); }

.recovery-issues__list a:focus-visible { outline: 0.1875rem solid var(--color-focus-ring); }
</style>
