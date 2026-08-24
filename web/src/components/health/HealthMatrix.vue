<script setup lang="ts">
import type {
  ProviderCapabilityStatus,
  RuntimeHealthResponse,
  RuntimeResourceStatus,
} from "../../api/generated";

interface Props {
  health: RuntimeHealthResponse;
}

interface Emits {
  selectSymbol: [symbol: string];
}

interface StatusPresentation {
  label: string;
  marker: string;
}

const props = defineProps<Props>();
const emit = defineEmits<Emits>();

const providerStatuses: Readonly<Record<ProviderCapabilityStatus, StatusPresentation>> = {
  BLOCKED_PERMISSION: { label: "权限阻断", marker: "■" },
  ERROR: { label: "错误", marker: "×" },
  RATE_LIMITED: { label: "限流", marker: "◆" },
  READY: { label: "就绪", marker: "●" },
  UNVERIFIED: { label: "未验证", marker: "◇" },
};

const resourceStatuses: Readonly<Record<RuntimeResourceStatus, StatusPresentation>> = {
  DEGRADED: { label: "降级", marker: "▲" },
  ERROR: { label: "错误", marker: "×" },
  READY: { label: "就绪", marker: "●" },
  STOPPED: { label: "已停止", marker: "■" },
  UNVERIFIED: { label: "未验证", marker: "◇" },
};

function providerStatus(status: ProviderCapabilityStatus) {
  return providerStatuses[status];
}

function resourceStatus(status: RuntimeResourceStatus) {
  return resourceStatuses[status];
}

function safeCapability(value: string) {
  return /^[A-Za-z][A-Za-z0-9_.:-]{0,63}$/.test(value) ? value : "未识别能力";
}

function safeErrorCode(value: string | null) {
  if (value === null) {
    return "—";
  }
  return /^[A-Z][A-Z0-9_]{0,63}$/.test(value) ? value : "已脱敏";
}

function optionalTime(value: string | null) {
  return value ?? "—";
}
</script>

<template>
  <section
    class="health-matrix"
    data-testid="health-matrix"
    aria-labelledby="health-matrix-title"
  >
    <h2 id="health-matrix-title" class="health-matrix__title">运行资源矩阵</h2>

    <section class="health-matrix__section" aria-labelledby="provider-health-title">
      <h3 id="provider-health-title" class="health-matrix__section-title">Tushare 能力</h3>
      <p
        v-if="(props.health.providers?.length ?? 0) === 0"
        class="health-matrix__empty"
        data-testid="providers-empty"
      >
        尚无能力探测结果。
      </p>
      <div
        v-else
        class="health-matrix__table-scroll"
        data-testid="provider-table-scroll"
        tabindex="0"
        aria-label="横向滚动能力健康表"
      >
        <table class="health-matrix__table">
          <caption>Tushare 能力健康</caption>
          <thead>
            <tr>
              <th scope="col">能力</th>
              <th scope="col">状态</th>
              <th scope="col">延迟</th>
              <th scope="col">检查时间</th>
              <th scope="col">错误码</th>
              <th scope="col">下次重试</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="provider in props.health.providers"
              :key="provider.capability"
              data-testid="provider-health-row"
              :data-status="provider.status"
            >
              <th scope="row">{{ safeCapability(provider.capability) }}</th>
              <td>
                <span
                  class="health-matrix__marker"
                  :data-status="provider.status"
                  aria-hidden="true"
                >
                  {{ providerStatus(provider.status).marker }}
                </span>
                {{ providerStatus(provider.status).label }}
              </td>
              <td class="numeric-data">{{ provider.latencyMs }} 毫秒</td>
              <td class="numeric-data">{{ provider.checkedAt }}</td>
              <td class="numeric-data">{{ safeErrorCode(provider.errorCode) }}</td>
              <td class="numeric-data">{{ optionalTime(provider.nextRetryAt) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <div class="health-matrix__resources">
      <article class="health-matrix__resource" data-testid="executor-health">
        <h3 class="health-matrix__section-title">执行器</h3>
        <dl class="health-matrix__definition-list">
          <div>
            <dt>工作线程</dt>
            <dd class="numeric-data">
              活动 {{ props.health.executor.activeCount }} / {{ props.health.executor.maxWorkers }}
            </dd>
          </div>
          <div>
            <dt>排队请求</dt>
            <dd class="numeric-data">等待 {{ props.health.executor.waitingCount }}</dd>
          </div>
        </dl>
      </article>

      <article
        class="health-matrix__resource"
        data-testid="database-health"
        :data-status="props.health.database.status"
      >
        <h3 class="health-matrix__section-title">数据库与备份</h3>
        <dl class="health-matrix__definition-list">
          <div>
            <dt>数据库</dt>
            <dd>
              <span
                class="health-matrix__marker"
                data-testid="database-status-marker"
                :data-status="props.health.database.status"
                aria-hidden="true"
              >
                {{ resourceStatus(props.health.database.status).marker }}
              </span>
              数据库 {{ resourceStatus(props.health.database.status).label }}
            </dd>
          </div>
          <div>
            <dt>WAL</dt>
            <dd>
              <span
                class="health-matrix__marker"
                data-testid="wal-status-marker"
                :data-status="props.health.database.walStatus"
                aria-hidden="true"
              >
                {{ resourceStatus(props.health.database.walStatus).marker }}
              </span>
              WAL {{ resourceStatus(props.health.database.walStatus).label }}
            </dd>
          </div>
          <div>
            <dt>最后检查点</dt>
            <dd class="numeric-data">{{ optionalTime(props.health.database.lastCheckpointAt) }}</dd>
          </div>
          <div>
            <dt>最后备份</dt>
            <dd class="numeric-data">{{ optionalTime(props.health.database.lastBackupAt) }}</dd>
          </div>
          <div>
            <dt>错误码</dt>
            <dd class="numeric-data">{{ safeErrorCode(props.health.database.errorCode) }}</dd>
          </div>
        </dl>
      </article>

      <article
        class="health-matrix__resource"
        data-testid="delivery-health"
        :data-status="props.health.delivery.status"
      >
        <h3 class="health-matrix__section-title">提醒投递</h3>
        <p class="health-matrix__resource-status">
          <span
            class="health-matrix__marker"
            :data-status="props.health.delivery.status"
            aria-hidden="true"
          >
            {{ resourceStatus(props.health.delivery.status).marker }}
          </span>
          {{ resourceStatus(props.health.delivery.status).label }}
        </p>
        <dl class="health-matrix__definition-list">
          <div>
            <dt>队列</dt>
            <dd class="numeric-data">
              待投递 {{ props.health.delivery.pendingCount }}；失败
              {{ props.health.delivery.failedCount }}
            </dd>
          </div>
          <div>
            <dt>最后投递</dt>
            <dd class="numeric-data">{{ optionalTime(props.health.delivery.lastDeliveredAt) }}</dd>
          </div>
          <div>
            <dt>下次重试</dt>
            <dd class="numeric-data">{{ optionalTime(props.health.delivery.nextRetryAt) }}</dd>
          </div>
          <div>
            <dt>错误码</dt>
            <dd class="numeric-data">{{ safeErrorCode(props.health.delivery.errorCode) }}</dd>
          </div>
        </dl>
      </article>
    </div>

    <section class="health-matrix__section" aria-labelledby="gap-health-title">
      <h3 id="gap-health-title" class="health-matrix__section-title">分钟数据缺口</h3>
      <p
        v-if="(props.health.gaps?.length ?? 0) === 0"
        class="health-matrix__empty"
        data-testid="gaps-empty"
      >
        未报告分钟缺口。
      </p>
      <div
        v-else
        class="health-matrix__table-scroll"
        data-testid="gap-table-scroll"
        tabindex="0"
        aria-label="横向滚动分钟缺口表"
      >
        <table class="health-matrix__table health-matrix__table--gaps">
          <caption>分钟数据缺口</caption>
          <thead>
            <tr>
              <th scope="col">股票</th>
              <th scope="col">缺口分钟</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="gap in props.health.gaps" :key="`${gap.symbol}:${gap.barEnd}`">
              <th scope="row">
                <a
                  class="health-matrix__gap-link"
                  data-testid="health-gap-link"
                  :href="`/stocks/${gap.symbol}`"
                  @click.prevent="emit('selectSymbol', gap.symbol)"
                >
                  {{ gap.symbol }}
                  <span class="health-matrix__visually-hidden">查看股票健康</span>
                </a>
              </th>
              <td class="numeric-data">{{ gap.barEnd }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </section>
</template>

<style scoped>
.health-matrix,
.health-matrix__section,
.health-matrix__resources {
  display: grid;
  gap: var(--space-4);
  min-width: 0;
}

.health-matrix__title,
.health-matrix__section-title,
.health-matrix__empty,
.health-matrix__resource-status,
.health-matrix__definition-list,
.health-matrix__definition-list dd {
  margin: 0;
}

.health-matrix__title {
  font-size: 1.25rem;
}

.health-matrix__section,
.health-matrix__resource {
  min-width: 0;
  padding: var(--space-4);
  color: var(--color-text-mineral);
  background: var(--color-surface-graphite);
  border: var(--border-technical);
}

.health-matrix__section-title {
  font-size: 1rem;
}

.health-matrix__empty,
.health-matrix__definition-list dt {
  color: var(--color-text-muted);
}

.health-matrix__table-scroll {
  max-width: 100%;
  overflow-x: auto;
}

.health-matrix__table-scroll:focus-visible,
.health-matrix__gap-link:focus-visible {
  outline: 0.1875rem solid var(--color-focus-ring);
  outline-offset: 0.1875rem;
}

.health-matrix__table {
  width: 100%;
  min-width: 48rem;
  border-collapse: collapse;
}

.health-matrix__table--gaps {
  min-width: 30rem;
}

.health-matrix__table caption {
  padding-block-end: var(--space-2);
  font-weight: 700;
  text-align: start;
}

.health-matrix__table th,
.health-matrix__table td {
  padding: var(--space-2);
  overflow-wrap: anywhere;
  text-align: start;
  vertical-align: top;
  border-block-end: var(--border-technical);
}

.health-matrix__table thead th {
  color: var(--color-text-muted);
}

.health-matrix__marker {
  color: var(--color-signal-watch-amber);
  font-family: var(--font-numeric);
  font-weight: 700;
}

.health-matrix__marker[data-status="READY"] {
  color: var(--color-signal-live-sea-glass);
}

.health-matrix__marker[data-status="ERROR"],
.health-matrix__marker[data-status="BLOCKED_PERMISSION"] {
  color: var(--color-signal-risk-vermilion);
}

.health-matrix__resource-status {
  margin-block-start: var(--space-2);
}

.health-matrix__definition-list {
  display: grid;
  gap: var(--space-3);
  margin-block-start: var(--space-3);
}

.health-matrix__definition-list dd {
  margin-block-start: 0.15rem;
  overflow-wrap: anywhere;
}

.health-matrix__gap-link {
  color: var(--color-signal-info-cyan);
  text-underline-offset: 0.2em;
}

.health-matrix__visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

@media (min-width: 48rem) {
  .health-matrix__resources {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (min-width: 64rem) {
  .health-matrix__resources {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
</style>
