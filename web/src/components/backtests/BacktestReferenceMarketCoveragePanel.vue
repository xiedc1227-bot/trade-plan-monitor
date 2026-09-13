<script setup lang="ts">
import type { BacktestReferenceMarketCoverageView } from "../../api/generated";
import type { BacktestReferenceMarketCoverageState } from "../../composables/useBacktestRunForm";
import type { DeepReadonly } from "vue";

interface Props {
  coverage: DeepReadonly<BacktestReferenceMarketCoverageView> | null;
  error: string | null;
  state: BacktestReferenceMarketCoverageState;
}

defineProps<Props>();
</script>

<template>
  <section
    class="coverage-panel"
    data-testid="reference-market-coverage"
    aria-labelledby="reference-market-coverage-title"
  >
    <div>
      <h2 id="reference-market-coverage-title">参考指数覆盖预览</h2>
    </div>
    <p v-if="state === 'IDLE'" role="status">选择计划版本并填写规范数据集哈希后由后端解析。</p>
    <p v-else-if="state === 'LOADING'" role="status" aria-live="polite" aria-busy="true">
      正在校验参考指数覆盖…
    </p>
    <p v-else-if="state === 'FAILED'" role="status" aria-live="polite">{{ error }}</p>
    <template v-else-if="coverage !== null">
      <p v-if="coverage.coverageStatus === 'NOT_REQUIRED'" role="status">
        计划未使用指数条件；指数数据缺失不会改变本计划判断。
      </p>
      <template v-else>
        <dl class="coverage-panel__facts">
          <div><dt>后端绑定</dt><dd>{{ coverage.binding.displayName }}（{{ coverage.binding.indexCode }}）</dd></div>
          <div><dt>板块</dt><dd>{{ coverage.binding.board }}</dd></div>
          <div><dt>映射版本</dt><dd><code>{{ coverage.binding.mappingVersion }}</code></dd></div>
          <div><dt>覆盖状态</dt><dd>{{ coverage.coverageStatus }}</dd></div>
          <div><dt>预热区间</dt><dd>{{ coverage.warmupStart }} 至 {{ coverage.warmupEnd }}</dd></div>
          <div><dt>五分钟数量（需 / 有）</dt><dd>{{ coverage.requiredFiveMinuteCount }} / {{ coverage.availableFiveMinuteCount }}</dd></div>
          <div><dt>官方日线数量（需 / 有）</dt><dd>{{ coverage.requiredOfficialDayCount }} / {{ coverage.availableOfficialDayCount }}</dd></div>
        </dl>
        <section aria-labelledby="reference-market-condition-paths-title">
          <h3 id="reference-market-condition-paths-title">计划指数条件路径</h3>
          <ul>
            <li v-for="path in coverage.conditionPaths" :key="path"><code>{{ path }}</code></li>
          </ul>
        </section>
        <p v-if="coverage.blockers.length > 0" role="alert">
          阻断：{{ coverage.blockers.join("、") }}
        </p>
      </template>
      <p class="coverage-panel__boundary">
        此处只显示后端生成的绑定、预热与覆盖；提交时服务端会再次校验。
      </p>
    </template>
  </section>
</template>

<style scoped>
.coverage-panel {
  display: grid;
  gap: var(--space-4);
  padding: var(--space-6);
  border: var(--border-technical);
  background: var(--color-surface-graphite);
}

.coverage-panel h2,
.coverage-panel h3,
.coverage-panel p {
  margin: 0;
}

.coverage-panel__facts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 15rem), 1fr));
  gap: var(--space-3);
}

.coverage-panel__facts dt {
  color: var(--color-text-muted);
}

.coverage-panel__facts dd {
  margin: var(--space-1) 0 0;
  overflow-wrap: anywhere;
}

.coverage-panel__boundary {
  color: var(--color-text-muted);
}

code {
  font-family: var(--font-numeric);
  overflow-wrap: anywhere;
}
</style>
