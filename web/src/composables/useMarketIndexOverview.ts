import { computed, onScopeDispose, shallowReadonly, shallowRef, toValue, watch } from "vue";
import type { MaybeRefOrGetter } from "vue";
import type { ConnectionStatus, MarketIndexOverviewResponse } from "../api/generated";
import type { MarketIndexOverviewApi } from "../api/marketIndexOverview";
import { ApiClientError } from "../api/transport";

interface Options {
  api: MarketIndexOverviewApi;
  connectionStatus: MaybeRefOrGetter<ConnectionStatus>;
  runtimeGeneration: MaybeRefOrGetter<string | null>;
  sequence: MaybeRefOrGetter<number>;
  observedAt: MaybeRefOrGetter<string | null>;
}

export function useMarketIndexOverview(options: Options) {
  const overview = shallowRef<MarketIndexOverviewResponse | null>(null);
  const error = shallowRef<string | null>(null);
  const loading = shallowRef(false);
  const failed = shallowRef(false);
  const cached = computed(() => failed.value || toValue(options.connectionStatus) !== "CONNECTED");
  let version = 0;
  let pending = false;
  let stopped = false;
  let controller: AbortController | null = null;

  async function read(): Promise<void> {
    if (loading.value || stopped || toValue(options.connectionStatus) !== "CONNECTED") return;
    const requestVersion = version;
    pending = false;
    loading.value = true;
    controller = new AbortController();
    try {
      const value = await options.api.getOverview({ signal: controller.signal });
      if (stopped || requestVersion !== version || controller.signal.aborted) return;
      const expectedGeneration = toValue(options.runtimeGeneration);
      if ((expectedGeneration !== null && value.runtimeGeneration !== expectedGeneration)
        || value.sequence < toValue(options.sequence)) throw new Error("Superseded overview");
      if (overview.value?.runtimeGeneration === value.runtimeGeneration && value.sequence < overview.value.sequence) return;
      overview.value = freeze(structuredClone(value));
      failed.value = false;
      error.value = null;
    } catch (cause) {
      if (stopped || requestVersion !== version || controller.signal.aborted) return;
      failed.value = true;
      error.value = cause instanceof ApiClientError && (cause.status === 404 || cause.status === 405)
        ? "指数显示接口版本不匹配，请更新后端并刷新页面"
        : overview.value === null ? "指数行情暂不可用，请重试" : "指数刷新失败，保留已取得行情";
    } finally {
      loading.value = false;
      controller = null;
      if (pending && !stopped) void read();
    }
  }
  function refresh(): void { version += 1; pending = true; void read(); }
  watch(() => [toValue(options.connectionStatus), toValue(options.runtimeGeneration), toValue(options.sequence), sessionObservation(toValue(options.observedAt))],
    () => {
      if (toValue(options.connectionStatus) !== "CONNECTED") { version += 1; controller?.abort(); return; }
      refresh();
    }, { immediate: true });
  onScopeDispose(() => { stopped = true; controller?.abort(); });
  return { overview: shallowReadonly(overview), error: shallowReadonly(error), loading: shallowReadonly(loading), cached, refresh };
}

function sessionObservation(at: string | null): string | null {
  if (at === null) return null;
  const time = at.slice(11, 16);
  return `${at.slice(0, 10)}:${time < "09:30" ? "PREOPEN" : time < "11:30" ? "AM" : time < "13:00" ? "BREAK" : time < "15:00" ? "PM" : "CLOSED"}`;
}
function freeze<T>(value: T): T {
  if (value !== null && typeof value === "object") { Object.values(value).forEach(freeze); Object.freeze(value); }
  return value;
}
