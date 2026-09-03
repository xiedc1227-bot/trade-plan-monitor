import { shallowReadonly, shallowRef, watch } from "vue";
import type { ShallowRef } from "vue";

import type { RuntimeHealthResponse } from "../api/generated";
import type { HealthApi } from "../api/health";

export interface UseSystemHealthOptions {
  api: HealthApi;
}

export interface UseSystemHealthResult {
  error: Readonly<ShallowRef<string | null>>;
  health: Readonly<ShallowRef<RuntimeHealthResponse | null>>;
  loading: Readonly<ShallowRef<boolean>>;
  refresh(): Promise<void>;
}

const safeHealthError = "系统健康刷新失败";

export function useSystemHealth(options: UseSystemHealthOptions): UseSystemHealthResult {
  const health = shallowRef<RuntimeHealthResponse | null>(null);
  const error = shallowRef<string | null>(null);
  const loading = shallowRef(false);
  const refreshTrigger = shallowRef(0);
  let requestGeneration = 0;

  watch(
    refreshTrigger,
    async (_value, _previous, onCleanup) => {
      const generation = ++requestGeneration;
      const controller = new AbortController();
      onCleanup(() => controller.abort());
      loading.value = true;
      error.value = null;

      try {
        const response = await options.api.getHealth({ signal: controller.signal });
        if (generation !== requestGeneration || controller.signal.aborted) {
          return;
        }
        health.value = response;
      } catch {
        if (generation !== requestGeneration || controller.signal.aborted) {
          return;
        }
        error.value = safeHealthError;
      } finally {
        if (generation === requestGeneration && !controller.signal.aborted) {
          loading.value = false;
        }
      }
    },
    { immediate: true },
  );

  async function refresh(): Promise<void> {
    refreshTrigger.value += 1;
  }

  return {
    error: shallowReadonly(error),
    health: shallowReadonly(health),
    loading: shallowReadonly(loading),
    refresh,
  };
}
