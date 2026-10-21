import { mount, flushPromises } from "@vue/test-utils";
import { defineComponent } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useBacktestReadFeedback } from "../../src/composables/useBacktestReadFeedback";

afterEach(() => vi.useRealTimers());
describe("bounded backtest read feedback", () => {
  it("marks slow reads, times out only the read, and rejects late responses", async () => {
    vi.useFakeTimers();
    let state!: ReturnType<typeof useBacktestReadFeedback>;
    const wrapper = mount(defineComponent({ setup() { state = useBacktestReadFeedback(); return () => null; } }));
    const parent = new AbortController();
    let signal!: AbortSignal;
    const pending = state.read(parent.signal, s => { signal = s; return new Promise(() => {}); });
    const rejected = expect(pending).rejects.toThrow("读取超时");
    await vi.advanceTimersByTimeAsync(10000);
    expect(state.slow.value).toBe(true);
    await vi.advanceTimersByTimeAsync(20000);
    await rejected;
    expect(signal.aborted).toBe(true);
    expect(parent.signal.aborted).toBe(false);
    expect(state.timedOut.value).toBe(true);
    wrapper.unmount();
  });
  it("cleans timers after success and parent cancellation", async () => {
    vi.useFakeTimers();
    let state!: ReturnType<typeof useBacktestReadFeedback>;
    const wrapper = mount(defineComponent({ setup() { state = useBacktestReadFeedback(); return () => null; } }));
    expect(await state.read(new AbortController().signal, async () => 7)).toBe(7);
    expect(state.lastSuccess.value).not.toBeNull();
    const parent = new AbortController();
    const pending = state.read(parent.signal, () => new Promise(() => {}));
    const rejected = expect(pending).rejects.toThrow();
    parent.abort(); await rejected; await flushPromises();
    expect(vi.getTimerCount()).toBe(0);
    wrapper.unmount();
  });
});
