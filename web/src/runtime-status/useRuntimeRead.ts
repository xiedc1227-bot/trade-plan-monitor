import { onBeforeUnmount, shallowRef, watch, type WatchSource } from "vue";

/** A route read has a bounded lifetime and cannot replace a later route observation. */
export function useRuntimeRead<T>(loader: (signal: AbortSignal) => Promise<T>, sources: WatchSource[]) {
  const value = shallowRef<T | null>(null);
  const error = shallowRef<string | null>(null);
  const loading = shallowRef(false);
  let revision = 0;
  let pending: AbortController | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  function cancel(): void {
    revision += 1; pending?.abort(); pending = null;
    if (timer !== null) clearTimeout(timer); timer = null;
  }
  async function refresh(): Promise<void> {
    cancel(); const current = revision; const controller = new AbortController(); pending = controller;
    value.value = null; error.value = null; loading.value = true;
    timer = setTimeout(() => { if (current === revision) { controller.abort(); loading.value = false; error.value = "读取超时，等待下次状态观察。"; } }, 20_000);
    try {
      const loaded = await loader(controller.signal);
      if (current === revision && !controller.signal.aborted) value.value = loaded;
    } catch {
      if (current === revision && !controller.signal.aborted) error.value = "当前投影暂不可用；等待下一次权威状态观察。";
    } finally {
      if (current === revision) { loading.value = false; if (timer !== null) clearTimeout(timer); timer = null; pending = null; }
    }
  }
  watch(sources, () => { void refresh(); }, { immediate: true });
  onBeforeUnmount(cancel);
  return { value, error, loading, refresh };
}
