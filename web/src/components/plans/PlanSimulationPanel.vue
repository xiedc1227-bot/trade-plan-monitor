<script setup lang="ts">
import { computed, onMounted, shallowRef } from "vue";
import type { DailyStateView, DailyInventoryResource, PlanVersionView, DailySimulationReceipt, DailyRuleReminderState } from "../../api/generated";
import PlanOperationForm from "./PlanOperationForm.vue";
import { type Json, type Schema } from "./planSchema";
const props = defineProps<{ version: PlanVersionView; request: <T>(url: string, body?: object, key?: string) => Promise<T> }>();
const inventory = shallowRef<DailyInventoryResource | null>(null);
const runtime = shallowRef<DailyStateView | null>(null);
const schemas = shallowRef<Record<string, Schema>>({});
const selected = shallowRef("FACT");
const riskKind = shallowRef("SEVERE_TECHNICAL");
const factSignalId = shallowRef("");
const busy = shallowRef(false);
const error = shallowRef("");
const notice = shallowRef("");
const commandNonce = shallowRef(crypto.randomUUID());
const simulationKeys = new Map<string, string>();
const actions = [
  { kind: "FACT", title: "人工核验证据", path: "/plan-facts", description: "逐日技术条件、严重技术结构及量价恶化、当前可交易或全日停牌。可交易与停牌的官方资料需发布时间、核验时间和具体事实；提交后立即重新评估，各规则遵循已审核的确认方式与执行窗口。" },
  { kind: "POSITION", title: "期初模拟仓位", path: "/simulation-position-confirmations", description: "分别填写期初CORE与TACTICAL，均为0或100股的整数倍。期初库存按已结算处理，后续模拟买入由系统按下一交易日计算可卖数量。已有模拟交易后不能覆盖期初库存。" },
  { kind: "REASSESSMENT", title: "独立风险重评", path: "/plan-risk-reassessments", description: "保留原风险审计，核验移除风险的官方证据。目标和涉及CORE范围必须与新审核版本一致。一般已阅或提醒确认不能解除风险。" },
] as const;
const current = computed(() => actions.find(a => a.kind === selected.value) ?? actions[0]);
const reminderOnly = computed(() => {
  try {
    const plan: unknown = JSON.parse(props.version.planJson);
    return plan !== null && typeof plan === "object"
      && "schema_version" in plan && plan.schema_version === 5
      && "ordinary_rules" in plan && Array.isArray(plan.ordinary_rules) && plan.ordinary_rules.length === 0
      && "risk_branches" in plan && Array.isArray(plan.risk_branches) && plan.risk_branches.length === 0
      && "alert_rules" in plan && Array.isArray(plan.alert_rules) && plan.alert_rules.length > 0;
  } catch { return false; }
});
const reminderDraftState = computed(() => reminderOnly.value && props.version.status === "DRAFT"
  ? props.version.reviewId ? "仅提醒草稿：已审核，尚未启用" : "仅提醒草稿：待审核，尚未启用"
  : null);
const reassessedRisk = computed(() => runtime.value?.snapshot?.risks.find(r => r.kind === riskKind.value));
const hiddenFields = computed(() => selected.value === "POSITION" ? ["symbol", "expectedRevision"] : selected.value === "REASSESSMENT" ? ["symbol", "riskId", "planVersionId", "contentHash", "expectedRevision"] : ["planVersionId", "contentHash", "expectedRevision", "factId", "signalId"]);
const stateLabels: Record<string, string> = { CURRENT: "当前评估", AWAITING_EVALUATION: "等待首次评估", INACTIVE: "未启用", UNSUPPORTED: "历史数据不支持模拟", CONFIRMED: "已确认", READY: "可以模拟交易", SIMULATED: "已完成模拟", EXPIRED: "本次权限已过期", INVALIDATED: "信号已失效", CLEAR: "未触发", PENDING: "等待下一收盘确认", OBSERVATION: "继续观察，停止新增", FULFILLED: "风险退出已完成" };
const day = () => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
const binding = computed<Record<string, Json>>(() => selected.value === "FACT" ? {
  planVersionId: props.version.id, contentHash: props.version.contentHash ?? null, expectedRevision: 0,
  factId: `fact-${commandNonce.value}`, signalId: factSignalId.value || null,
} : selected.value === "POSITION" ? { symbol: props.version.symbol,
  expectedRevision: inventory.value?.snapshot?.revision ?? 0,
} : { symbol: props.version.symbol, planVersionId: props.version.id, contentHash: props.version.contentHash ?? null,
  riskId: reassessedRisk.value?.riskId ?? null, expectedRevision: reassessedRisk.value?.revision ?? 0 });
const formBlocked = computed(() => runtime.value?.status === "UNSUPPORTED" || inventory.value === null || (selected.value === "REASSESSMENT" && !reassessedRisk.value));
const riskAction = computed(() => runtime.value?.snapshot?.riskAction);
const reminders = computed<readonly DailyRuleReminderState[]>(() => runtime.value?.snapshot?.alerts ?? []);
const riskQuantity = computed(() => (riskAction.value?.coreQty ?? 0) + (riskAction.value?.tacticalQty ?? 0));
const currentVersion = computed(() => runtime.value?.status === "CURRENT" && runtime.value.snapshot?.planVersionId === props.version.id);
function wholeQuantity(quantity: number) { return Number.isSafeInteger(quantity) && quantity > 0 && quantity % 100 === 0; }
async function refresh() {
  const [actual, state] = await Promise.all([
    props.request<DailyInventoryResource>(`/api/v1/simulation-position-inventory?symbol=${props.version.symbol}&asOfTradeDate=${day()}`),
    props.request<DailyStateView>(`/api/v1/plan-runtime/${props.version.symbol}`),
  ]);
  inventory.value = actual; runtime.value = state;
}
async function refreshCurrent() {
  if (busy.value) return;
  busy.value = true; error.value = "";
  try { await refresh(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "当前状态不可用"; }
  finally { busy.value = false; }
}
async function submit(value: Json) {
  if (value === null || typeof value !== "object" || Array.isArray(value) || busy.value || formBlocked.value) return;
  busy.value = true; error.value = ""; notice.value = "";
  try { await props.request(`/api/v1${current.value.path}`, value, `daily-${selected.value}-${commandNonce.value}`); await refresh(); commandNonce.value = crypto.randomUUID(); notice.value = "已记录并更新当前状态。"; }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "登记失败"; }
  finally { busy.value = false; }
}
async function simulate(causeId: string | null | undefined, revision: number | null | undefined, quantity: number) {
  if (busy.value || !causeId || !currentVersion.value || !inventory.value?.snapshot?.known || !wholeQuantity(quantity) || revision == null) return;
  const command = { planVersionId: props.version.id, causeId, expectedCauseRevision: revision,
    expectedInventoryRevision: inventory.value.snapshot.revision, quantity };
  const identity = JSON.stringify(command);
  const key = simulationKeys.get(identity) ?? crypto.randomUUID();
  simulationKeys.set(identity, key);
  busy.value = true; error.value = ""; notice.value = "";
  try {
    const receipt = await props.request<DailySimulationReceipt>("/api/v1/simulated-trades", command, key);
    await refresh();
    notice.value = `已一次完成模拟${receipt.side === "BUY" ? "买入" : "卖出"}${receipt.quantity}股，模拟价格${(receipt.priceFen / 100).toFixed(2)}元。`;
  } catch (cause) { error.value = cause instanceof Error ? cause.message : "模拟交易失败，请刷新当前状态后重试"; }
  finally { busy.value = false; }
}
onMounted(async () => {
  try { const contract = await props.request<{ operationSchemas: Record<string, Schema> }>("/api/v1/plan-editor-schema"); schemas.value = contract.operationSchemas; await refresh(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "当前状态不可用"; }
});
</script>
<template>
  <section class="daily-operations" aria-labelledby="daily-operations-title">
    <h2 id="daily-operations-title">模拟仓位与技术核验</h2>
    <p>提醒不会改变模拟仓位。只有你确认一次模拟交易，系统才更新仓位；不提交真实订单。</p>
    <p v-if="error" role="alert">{{ error }}</p><p v-if="notice" role="status">{{ notice }}</p>
    <button type="button" :disabled="busy" @click="refreshCurrent">刷新当前状态</button>
    <dl v-if="inventory?.snapshot" class="daily-operations__inventory"><dt>模拟总持仓</dt><dd>{{ inventory.snapshot.totalQty ?? '待初始化' }}股</dd><dt>模拟CORE / TACTICAL</dt>
      <dd>{{ inventory.snapshot.coreQty ?? '待初始化' }} / {{ inventory.snapshot.tacticalQty ?? '待初始化' }}股</dd>
      <dt>可卖CORE / TACTICAL（系统计算T+1）</dt><dd>{{ inventory.snapshot.sellableCore ?? '待初始化' }} / {{ inventory.snapshot.sellableTactical ?? '待初始化' }}股</dd></dl>
    <div v-if="runtime" class="daily-runtime"><h3>{{ reminderDraftState ?? `计划当前状态：${stateLabels[runtime.status] ?? runtime.status}` }}</h3>
      <p v-if="reminderOnly && inventory?.status === 'UNSUPPORTED'" role="status">模拟库存受历史记录或存储结构兼容性限制。仅提醒规则不依赖模拟库存；是否监测仍取决于本版本的人工审核和启用状态。</p>
      <template v-if="runtime.snapshot">
        <ul v-if="runtime.snapshot.dataBlockers.length"><li v-for="blocker in runtime.snapshot.dataBlockers" :key="blocker">{{ blocker }}</li></ul>
        <article v-for="signal in runtime.snapshot.signals" :key="signal.signalId" class="daily-signal">
          <h4>{{ signal.side === 'BUY' ? '计划买入' : '计划卖出' }} · {{ stateLabels[signal.state] ?? signal.state }}</h4>
          <dl class="daily-operations__inventory"><dt>条件确认日期</dt><dd>{{ signal.confirmedTradeDate }}</dd>
            <dt>执行交易日</dt><dd>{{ signal.executionDate ?? '日历待核验' }}（当天收盘过期）</dd>
            <dt>计划数量 / 已模拟</dt><dd>{{ signal.plannedQty }} / {{ signal.simulatedQty }}股</dd>
            <dt>当前可完整模拟</dt><dd>{{ signal.executableQty }}股</dd></dl>
          <p v-if="signal.state === 'SIMULATED'">本笔模拟已完成，同一信号不会因刷新或重启再次增加仓位。</p>
          <p v-else-if="signal.blockers.length">模拟限制：{{ signal.blockers.join('；') }}</p>
          <button v-if="signal.state !== 'SIMULATED'" type="button"
            :disabled="busy || !currentVersion || !inventory?.snapshot?.known || signal.state !== 'READY' || signal.revision == null || signal.executableQty !== signal.plannedQty || !wholeQuantity(signal.plannedQty)"
            @click="simulate(signal.signalId, signal.revision, signal.plannedQty)">确认一次模拟{{ signal.side === 'BUY' ? '买入' : '卖出' }}{{ signal.plannedQty }}股</button>
          <details><summary>查看逐组条件证据</summary><pre class="daily-operations__evidence">{{ JSON.stringify(signal.evidence, null, 2) }}</pre></details>
        </article>
        <article v-for="risk in runtime.snapshot.risks" :key="risk.kind" class="daily-risk">
          <h4>{{ risk.kind === 'ORDINARY_TECHNICAL' ? '普通技术风险' : '严重技术风险' }} · {{ stateLabels[risk.status] ?? risk.status }}</h4>
          <p>保留目标：CORE {{ risk.targetCoreQty }}股 / TACTICAL {{ risk.targetTacticalQty }}股；{{ risk.involvesCore ? '涉及CORE' : '保护CORE' }}。</p>
          <p>最早执行日期：{{ risk.earliestExecutionDate ?? '等待风险确认或交易日历' }}</p>
          <p>{{ risk.scopeEvidence }}</p><p v-if="risk.blockers.length">{{ risk.blockers.join('；') }}</p>
        </article>
        <section v-if="reminders.length" aria-label="仅提醒的独立条件" class="daily-reminders">
          <h4>独立提醒条件</h4>
          <p>这些规则只产生提醒，不创建模拟交易，也不改变模拟仓位。</p>
          <article v-for="reminder in reminders" :key="reminder.rule_id" class="daily-reminder">
            <h5>{{ reminder.alert_kind === 'RISK_ALERT' ? '风险提醒' : '条件提醒' }} {{ reminder.rule_id }} · {{ reminder.outcome === 'SATISFIED' ? '已满足' : reminder.outcome === 'MISSING_INPUT' ? '缺少输入' : '未满足' }}</h5>
            <p>{{ reminder.confirmation_kind === 'COMPLETED_BAR_CLOSE' ? '5分钟完整K线收盘确认' : '官方日线收盘确认' }} · {{ reminder.confirmed_at ?? reminder.confirmed_trade_date ?? '待确认' }}</p>
            <details><summary>查看提醒证据</summary><pre class="daily-operations__evidence">{{ JSON.stringify(reminder.evidence, null, 2) }}</pre></details>
          </article>
        </section>
        <template v-if="riskAction?.status === 'RISK_EXIT'">
          <p>当前可模拟风险减仓：CORE {{ riskAction.coreQty }}股 / TACTICAL {{ riskAction.tacticalQty }}股。</p>
          <p>暂不可模拟减仓：CORE {{ riskAction.unavailableCoreQty }}股 / TACTICAL {{ riskAction.unavailableTacticalQty }}股。买入当日不可卖，等待下一交易日结算与可交易核验。</p>
          <button type="button" :disabled="busy || !currentVersion || !inventory?.snapshot?.known || !riskAction.causeId || riskAction.causeRevision == null || !wholeQuantity(riskQuantity)"
            @click="simulate(riskAction.causeId, riskAction.causeRevision, riskQuantity)">确认一次模拟风险减仓{{ riskQuantity }}股</button>
        </template>
      </template><p v-else-if="reminderDraftState">该版本尚未启用，暂不执行技术提醒监测。</p>
      <p v-else>{{ runtime.status === 'UNSUPPORTED' ? '此历史记录保留用于查看，不能转换为模拟交易。' : '等待首次完整评估' }}</p>
      <section v-if="runtime.status === 'UNSUPPORTED' && runtime.risks?.length" aria-label="保留的技术风险历史">
        <article v-for="risk in runtime.risks" :key="String(risk.kind)" class="daily-risk">
          <h4>{{ risk.kind === 'ORDINARY_TECHNICAL' ? '普通技术风险' : '严重技术风险' }} · {{ stateLabels[String(risk.status)] ?? risk.status }}</h4>
          <p>历史确认日期：{{ risk.confirmedTradeDate ?? '尚未确认' }}</p>
          <p>{{ risk.scopeEvidence }}</p>
        </article>
      </section>
    </div>
    <label for="daily-operation-kind">选择独立操作</label><select id="daily-operation-kind" v-model="selected">
      <option v-for="action in actions" :key="action.kind" :value="action.kind">{{ action.title }}</option></select>
    <template v-if="selected === 'FACT' && runtime?.snapshot?.signals.length">
      <label for="daily-fact-signal">关联现有提醒（新独立结构或信号失效核验）</label><select id="daily-fact-signal" v-model="factSignalId">
        <option value="">技术核验，不关联单笔提醒</option>
        <option v-for="signal in runtime.snapshot.signals" :key="signal.signalId" :value="signal.signalId">{{ signal.side === 'BUY' ? '计划买入' : '计划卖出' }} · {{ signal.confirmedTradeDate }}确认 · {{ stateLabels[signal.state] ?? signal.state }}</option>
      </select>
    </template>
    <template v-if="selected === 'REASSESSMENT'">
      <label for="daily-reassessment-risk">重评技术风险</label><select id="daily-reassessment-risk" v-model="riskKind">
        <option v-for="risk in runtime?.snapshot?.risks ?? []" :key="risk.kind" :value="risk.kind">{{ risk.kind === 'ORDINARY_TECHNICAL' ? '普通技术风险' : '严重技术风险' }}</option>
      </select>
    </template>
    <PlanOperationForm v-if="schemas[selected]" :key="selected" :schema="schemas[selected] ?? {}" :binding="binding"
      :title="current.title" :description="current.description" :busy="busy" :operation="selected" :initial-values="selected === 'FACT' ? { tradeDate: day() } : {}" :hidden-fields="hiddenFields" :blocked="formBlocked" @submit="submit" />
  </section>
</template>
<style scoped>
.daily-operations { display: grid; gap: var(--space-4); }
.daily-operations__inventory { display: grid; grid-template-columns: minmax(10rem, 1fr) 1fr; gap: var(--space-2); }
.daily-operations__evidence { overflow: auto; max-height: 30rem; }
@media (max-width: 48rem) { .daily-operations__inventory { grid-template-columns: 1fr; } }
</style>
