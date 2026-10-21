import { onBeforeUnmount, readonly, shallowRef } from "vue";

/** Deadlines own only a read observer, never a business task or mutation. */
export function useBacktestReadFeedback() {
  const slow = shallowRef(false);
  const timedOut = shallowRef(false);
  const lastSuccess = shallowRef<string | null>(null);
  let generation = 0;
  let active: AbortController | null = null;

  async function read<T>(parent: AbortSignal, load: (signal: AbortSignal) => Promise<T>): Promise<T> {
    active?.abort();
    const current = ++generation;
    const controller = new AbortController();
    active = controller;
    slow.value = false;
    timedOut.value = false;
    let slowTimer: ReturnType<typeof setTimeout>;
    let timeoutTimer: ReturnType<typeof setTimeout>;
    const abort = () => controller.abort();
    let rejectAbort: () => void = () => {};
    const interrupted = new Promise<never>((_, reject) => {
      rejectAbort = () => reject(new DOMException("读取已取消", "AbortError"));
      controller.signal.addEventListener("abort", rejectAbort, { once: true });
      slowTimer = setTimeout(() => { if (current === generation) slow.value = true; }, 10000);
      timeoutTimer = setTimeout(() => {
        if (current === generation) timedOut.value = true;
        reject(new Error("读取超时，请重新读取"));
        controller.abort();
      }, 30000);
    });
    parent.addEventListener("abort", abort, { once: true });
    if (parent.aborted) abort();
    try {
      const value = await Promise.race([interrupted, load(controller.signal)]);
      if (current !== generation || controller.signal.aborted) throw new DOMException("读取已取消", "AbortError");
      lastSuccess.value = new Date().toLocaleTimeString("zh-CN", { hour12: false });
      return value;
    } finally {
      clearTimeout(slowTimer!); clearTimeout(timeoutTimer!);
      parent.removeEventListener("abort", abort);
      controller.signal.removeEventListener("abort", rejectAbort);
      if (active === controller) { active = null; slow.value = false; }
    }
  }
  function reset() { generation += 1; active?.abort(); active = null; slow.value = false; timedOut.value = false; }
  onBeforeUnmount(reset);
  return { read, reset, slow: readonly(slow), timedOut: readonly(timedOut), lastSuccess: readonly(lastSuccess) };
}
