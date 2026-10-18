import { ApiClientError, requestJson, type JsonTransportResponse } from "./transport";

function waitForReadRetry(signal?: AbortSignal | null): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(new DOMException("Read cancelled", "AbortError")); return; }
    const finish = () => { signal?.removeEventListener("abort", abort); resolve(); };
    const timer = setTimeout(finish, 1000);
    const abort = () => {
      clearTimeout(timer); signal?.removeEventListener("abort", abort);
      reject(new DOMException("Read cancelled", "AbortError"));
    };
    signal?.addEventListener("abort", abort, { once: true });
  });
}

/** Retry only explicit temporary read failures; mutation receipts remain user-controlled. */
export async function requestBacktestJson(
  fetcher: typeof fetch, input: RequestInfo | URL, init?: RequestInit,
): Promise<JsonTransportResponse> {
  const method = (init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
  for (let attempt = 0; ; attempt++) {
    try { return await requestJson(fetcher, input, init); }
    catch (error) {
      if (method !== "GET" || attempt >= 2 || init?.signal?.aborted ||
          !(error instanceof ApiClientError) || error.status !== 503 || error.code !== "SERVICE_UNAVAILABLE") throw error;
      await waitForReadRetry(init?.signal);
    }
  }
}
