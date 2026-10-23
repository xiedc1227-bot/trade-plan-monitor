import { afterEach, expect, it, vi } from "vitest";
import { createInitialResultStartup } from "../../src/runtime-status/initialResultStartup";
afterEach(() => vi.useRealTimers());
it("waits for settlement and starts exactly once", () => {
 vi.useFakeTimers(); const start=vi.fn(); const gate=createInitialResultStartup(start);
 gate.mount(); gate.route("/result", true); vi.advanceTimersByTime(4999); expect(start).not.toHaveBeenCalled();
 gate.settled("/result"); expect(start).toHaveBeenCalledTimes(1); vi.runAllTimers(); gate.settled("/result"); expect(start).toHaveBeenCalledTimes(1);
});
it("caps waiting even without route resolution or a result", () => {
 vi.useFakeTimers(); const start=vi.fn(); const gate=createInitialResultStartup(start); gate.mount();
 vi.advanceTimersByTime(5000); expect(start).toHaveBeenCalledTimes(1); gate.route("/result",true); expect(start).toHaveBeenCalledTimes(1);
});
it("releases other routes and navigation without pausing an established monitor", () => {
 vi.useFakeTimers(); const start=vi.fn(); const gate=createInitialResultStartup(start); gate.mount(); gate.route("/result",true);
 gate.route("/other",true); expect(start).toHaveBeenCalledTimes(1); gate.route("/result",true); expect(vi.getTimerCount()).toBe(0);
});
it("accepts early settlement but ignores a different identity", () => {
 vi.useFakeTimers(); const start=vi.fn(); const gate=createInitialResultStartup(start);
 gate.settled("/old"); gate.mount(); gate.route("/result",true); expect(start).not.toHaveBeenCalled(); gate.settled("/result"); expect(start).toHaveBeenCalledOnce();
});
it("cannot start after unmount, including late route and result callbacks", () => {
 vi.useFakeTimers(); const start=vi.fn(); const gate=createInitialResultStartup(start); gate.mount(); gate.route("/result",true); gate.dispose();
 gate.settled("/result"); gate.route("/",false); gate.mount(); vi.runAllTimers(); expect(start).not.toHaveBeenCalled(); expect(vi.getTimerCount()).toBe(0);
});
it("starts immediately on an ordinary route", () => {
 vi.useFakeTimers(); const start=vi.fn(); const gate=createInitialResultStartup(start); gate.mount(); gate.route("/",false); expect(start).toHaveBeenCalledOnce();
});
