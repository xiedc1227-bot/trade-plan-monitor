import { afterEach, expect, it, vi } from "vitest";
import { requestBacktestJson } from "../../src/api/backtestRead";

afterEach(() => vi.useRealTimers());
const unavailable = () => new Response(JSON.stringify({ error: { code: "SERVICE_UNAVAILABLE", message: "Service unavailable", details: [], requestId: "a".repeat(32) } }), { status: 503 });

it("retries a temporary GET failure without overlapping reads", async () => {
  vi.useFakeTimers();
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(unavailable()).mockResolvedValue(new Response("{}"));
  const response = requestBacktestJson(fetcher, "/api/v1/backtest-runs", { method: "GET" });
  await vi.advanceTimersByTimeAsync(999); expect(fetcher).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(1); expect((await response).status).toBe(200);
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it("bounds persistent GET failures and never retries mutations", async () => {
  vi.useFakeTimers();
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async () => unavailable());
  const response = expect(requestBacktestJson(fetcher, "/api/v1/backtest-runs", { method: "GET" })).rejects.toMatchObject({ status: 503 });
  await vi.advanceTimersByTimeAsync(10000); await response;
  expect(fetcher).toHaveBeenCalledTimes(3);
  await expect(requestBacktestJson(fetcher, "/api/v1/backtest-runs", { method: "POST", body: "{}" })).rejects.toMatchObject({ status: 503 });
  expect(fetcher).toHaveBeenCalledTimes(4);
});

it("cancels a delayed retry on navigation without another request", async () => {
  vi.useFakeTimers(); const controller = new AbortController();
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async () => unavailable());
  const response = expect(requestBacktestJson(fetcher, "/api/v1/backtest-runs", { method: "GET", signal: controller.signal })).rejects.toMatchObject({ name: "AbortError" });
  await vi.advanceTimersByTimeAsync(0); controller.abort();
  await vi.advanceTimersByTimeAsync(5000); await response;
  expect(fetcher).toHaveBeenCalledTimes(1);
});
