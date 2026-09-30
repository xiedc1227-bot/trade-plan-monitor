import { inject, type InjectionKey } from "vue";
import type { RuntimeApi } from "./client";
import type { createRuntimeMonitor } from "./stream";
import type { useRuntimeMonitorStore } from "./store";

export interface RuntimeContext {
  api: RuntimeApi;
  store: ReturnType<typeof useRuntimeMonitorStore>;
  monitor: ReturnType<typeof createRuntimeMonitor>;
}
export const runtimeContextKey: InjectionKey<RuntimeContext> = Symbol("runtime-monitor-context");
export function useRuntimeContext(): RuntimeContext {
  const context = inject(runtimeContextKey);
  if (!context) throw new Error("Runtime monitor context is required");
  return context;
}
