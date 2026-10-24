<script setup lang="ts">
import { toRef, useId } from "vue";
import type { ExceptionCandidateResource } from "../../api/generated";
import { usePlanException, type ExceptionRequest } from "../../composables/usePlanException";
import { formatDisplayDateTime } from "../../formatters/dateTime";
const props = defineProps<{ resource: ExceptionCandidateResource; current: boolean; authorityRevision: number; request: ExceptionRequest }>();
const emit = defineEmits<{ refresh: [] }>();
const id = useId();
const { proposed, reason, preview, busy, error, notice, candidate, weak, blocked, canPreview, canDecide, generatePreview, decide } = usePlanException(
  toRef(props, "resource"), toRef(props, "authorityRevision"), toRef(props, "current"), props.request, () => emit("refresh"));
const labels = { PENDING: "等待逐次审核", APPROVED: "已批准，数量已冻结", REJECTED: "已拒绝", REVOKED: "已撤销", EXPIRED: "已过期", INVALIDATED: "依据已失效", CONSUMED: "已消耗" };
const blockerLabels: Record<string, string> = {
  EXCEPTION_CALENDAR_CHANGED_OR_UNKNOWN: "交易日历已变化或尚未核实，原执行窗口不可用",
  EXCEPTION_EVIDENCE_CHANGED: "原批准所依据的市场或条件证据已变化",
  EXCEPTION_CURRENT_EVIDENCE_REQUIRED: "必要行情或复权依据暂缺，恢复核验后才能执行",
  EXCEPTION_CURRENT_REVIEW_REQUIRED: "当前计划审核或启用状态需要重新核验",
  EXCEPTION_CURRENT_PLAN_REQUIRED: "当前计划不具备本次例外权限",
  EXCEPTION_CURRENT_EVALUATION_REQUIRED: "需要重新评估当前计划",
  EXCEPTION_CURRENT_FACTS_REQUIRED: "当前事实或持仓与上次评估不一致",
  EXCEPTION_WINDOW_EXPIRED: "原执行窗口已过期，不能延期",
  CAPACITY_INSUFFICIENT: "仓位容量不足，整笔阻断",
  MAX_QUANTITY_CAPACITY: "仓位容量不足，整笔阻断",
  HIGHER_PRIORITY_RISK: "更高优先级风险阻断当前买入",
  RISK_INPUT_UNKNOWN: "风险依据尚未核实",
  POSITION_UNKNOWN: "模拟持仓尚未核实",
};
</script>
<template>
  <section class="exception-approval" :aria-labelledby="`${id}-title`" :aria-busy="busy">
    <h4 :id="`${id}-title`">{{ weak ? '偏弱市场最小量例外' : '破位市场强势例外' }} · {{ labels[candidate.state] }}</h4>
    <p>规则 {{ candidate.binding.rule_id }}；条件确认日 {{ candidate.binding.decision_session }}；执行日 {{ candidate.binding.execution_date }}。</p>
    <p>证据截止：{{ formatDisplayDateTime(candidate.binding.evidence_cutoff) }}；到期：{{ formatDisplayDateTime(candidate.binding.expires_at) }}（上海时间）。</p>
    <p>基础量 {{ candidate.binding.base_quantity }} 股；官方最小量 {{ candidate.binding.minimum }} 股；递增单位 {{ candidate.binding.increment }} 股。仍须符合 100 股整数倍及整笔容量。</p>
    <p v-if="candidate.frozen_quantity !== null">已冻结：{{ candidate.frozen_quantity }} 股。容量不足时整笔阻断，不缩量。</p>
    <p v-if="!current" role="status">当前状态需刷新，暂不可提交决定。</p>
    <p v-if="resource.blockers?.length" role="status">当前限制：{{ resource.blockers.map(code => blockerLabels[code] ?? '当前依据未满足批准要求').join('；') }}。请核对上方市场及条件依据后刷新。</p>
    <p v-if="error" role="alert">{{ error }}</p><p v-if="notice" role="status">{{ notice }}</p>
    <template v-if="candidate.state === 'PENDING'">
      <p v-if="weak">固定申请量：{{ candidate.binding.minimum }} 股；只能恰好申请官方最小量，不能改量。</p>
      <template v-else><label :for="`${id}-quantity`">本次申请数量 Qe（股，不设默认值）</label>
        <input :id="`${id}-quantity`" v-model="proposed" type="number" min="100" step="100" :disabled="busy" />
      </template>
      <button type="button" :disabled="!canPreview" @click="generatePreview">生成本次精确预览</button>
      <div v-if="preview" role="status" class="exception-approval__preview">
        <strong>本次精确批准量：{{ preview.quantity }} 股</strong>
        <p>预览时可用容量：{{ preview.current.capacity }} 股；服务端收到预览请求：{{ formatDisplayDateTime(preview.createdAt) }}。</p>
        <p>只批准本次独立信号，批准不执行模拟交易。数量或依据变化后须重新生成预览。</p>
      </div>
    </template>
    <template v-if="candidate.state === 'PENDING' || candidate.state === 'APPROVED'">
      <label :for="`${id}-reason`">本次决定的具体理由（必填）</label>
      <textarea :id="`${id}-reason`" v-model="reason" :disabled="busy" maxlength="2000" rows="3" />
      <div class="exception-approval__actions">
        <template v-if="candidate.state === 'PENDING'">
          <button v-if="preview" type="button" :disabled="!canDecide || blocked" @click="decide('APPROVE')">批准本次{{ preview.quantity }}股</button>
          <button type="button" :disabled="!canDecide" @click="decide('REJECT')">拒绝本次申请</button>
        </template>
        <button v-else type="button" :disabled="!canDecide" @click="decide('REVOKE')">撤销本次批准</button>
      </div>
    </template>
    <p v-else>本次独立信号已终结，不能重新批准。复制计划或修改日期不会恢复本次机会。</p>
    <details><summary>查看本次绑定与原始条件证据</summary><pre>{{ JSON.stringify({ binding: candidate.binding, evidence: candidate.signal_seed?.evidence ?? [], approvalId: candidate.approval_id }, null, 2) }}</pre></details>
  </section>
</template>
<style scoped>
.exception-approval { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-3); border: var(--border-technical); padding: var(--space-3); min-width: 0; overflow-wrap: anywhere; }
.exception-approval__actions { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.exception-approval input, .exception-approval textarea { width: 100%; box-sizing: border-box; }
.exception-approval pre { white-space: pre-wrap; overflow-wrap: anywhere; }
.exception-approval__preview { border-left: 3px solid currentColor; padding-left: var(--space-3); }
</style>
