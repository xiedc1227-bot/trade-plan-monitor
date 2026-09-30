import { defineComponent, shallowRef } from "vue";
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, expect, it, vi } from "vitest";
import { useRuntimeRead } from "../../src/runtime-status/useRuntimeRead";

afterEach(() => vi.useRealTimers());
it("aborts an old route read and rejects its late result after symbol replacement", async () => {
  const symbol = shallowRef("003043.SZ");
  const pending: { signal: AbortSignal; resolve: (value: string) => void }[] = [];
  const component = defineComponent({ setup() {
    return useRuntimeRead(signal => new Promise<string>(resolve => pending.push({ signal, resolve })), [() => symbol.value]);
  }, template: '<p>{{ value }}</p>' });
  const wrapper = mount(component);
  symbol.value = "600000.SH"; await flushPromises();
  expect(pending[0]!.signal.aborted).toBe(true);
  pending[1]!.resolve("current"); await flushPromises();
  pending[0]!.resolve("old"); await flushPromises();
  expect(wrapper.text()).toBe("current"); wrapper.unmount();
});

it("bounds a hung route projection and ignores its result after the 20 second deadline", async () => {
  vi.useFakeTimers(); let signal: AbortSignal | undefined; let resolve: ((value: string) => void) | undefined;
  const component = defineComponent({ setup() {
    return useRuntimeRead(current => { signal = current; return new Promise<string>(done => { resolve = done; }); }, []);
  }, template: '<p>{{ value }} {{ error }}</p>' });
  const wrapper = mount(component);
  await vi.advanceTimersByTimeAsync(20_000);
  expect(signal?.aborted).toBe(true); expect(wrapper.text()).toContain("读取超时");
  resolve?.("late"); await flushPromises(); expect(wrapper.text()).not.toContain("late"); wrapper.unmount();
});
