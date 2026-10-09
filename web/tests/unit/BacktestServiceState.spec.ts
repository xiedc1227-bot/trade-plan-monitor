import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent, h, ref } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { BacktestJobView, BacktestServiceRecoveryCommand, BacktestServiceView } from "../../src/api/generated";
import { createBacktestServiceApi, validServiceStatus, type BacktestServiceApi } from "../../src/api/backtestService";
import { createBacktestApi } from "../../src/api/backtests";
import { ApiClientError } from "../../src/api/transport";
import BacktestServiceState from "../../src/components/backtests/BacktestServiceState.vue";
import { useBacktestService } from "../../src/composables/useBacktestService";
import { useBacktestRunForm } from "../../src/composables/useBacktestRunForm";
import { shellConnectionKey } from "../../src/layouts/connection";
import { apiFetchKey } from "../../src/api/context";
import AppShell from "../../src/layouts/AppShell.vue";
import { routes } from "../../src/router";

const epoch = "a".repeat(32);
const status = (change: Partial<BacktestServiceView> = {}): BacktestServiceView => ({ epoch, revision: 0, generation: 0, state: "NOT_INITIALIZED", canRead: false, canSubmit: false, canCancel: false, canExport: false, physicallyDrained: true, authorizedJobIds: [], reason: null, ...change });
const ready = () => status({ state: "READ_READY", canRead: true, canCancel: true, canExport: true });
const failed = () => status({ state: "DEGRADED", reason: "SERVICE_REPAIR_REQUIRED" });
const error = (code: "NETWORK_ERROR" | "SERVICE_UNAVAILABLE", value: number) => new ApiClientError({ code, status: value, message: "private diagnostic" });
function api(value = status()): BacktestServiceApi {
  return { getStatus: vi.fn().mockResolvedValue(value), recover: vi.fn().mockImplementation(async (body: BacktestServiceRecoveryCommand) => ({ accepted: true, action: body.action, epoch, revision: body.expectedRevision + 1 })), stop: vi.fn().mockResolvedValue({ accepted: true, action: "STOP", epoch, revision: 1 }) };
}
function host(options: Parameters<typeof useBacktestService>[0]) {
  let service!: ReturnType<typeof useBacktestService>;
  const wrapper = mount(defineComponent({ setup() { service = useBacktestService(options); return () => h("div"); } }));
  return { wrapper, get service() { return service; } };
}
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("backtest service transport and scoped UI", () => {
  it.each([status(), ready(), status({ state: "READY", canRead: true, canSubmit: true, canCancel: true, canExport: true }), failed(), status({ state: "DISABLED", epoch: null }), status({ state: "STOPPED" })])("accepts an actual closed service state", value => { expect(validServiceStatus(value)).toBe(true); });
  it.each([{ state: "OTHER" }, { epoch: null }, { generation: -1 }, { revision: Number.MAX_SAFE_INTEGER + 1 }, { extra: true }, { authorizedJobIds: ["one", "two"] }, { authorizedJobIds: ["bad/id"] }, { canSubmit: true }, { canRead: true }, { reason: "private error" }])("rejects invalid state or unsupported capability", change => { expect(validServiceStatus({ ...status(), ...change })).toBe(false); });
  it("constructs inert clients and validates accepted control identity/headers", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ accepted: true, action: "RETRY_PREPARATION", epoch, revision: 1 }), { status: 202, headers: { "Location": "/api/v1/backtest-service", "Retry-After": "1" } }));
    const client = createBacktestServiceApi(fetch); expect(fetch).not.toHaveBeenCalled();
    await client.recover({ epoch, expectedRevision: 0, action: "RETRY_PREPARATION", resumeJobIds: [] }, "same-key");
    expect((fetch.mock.calls[0]?.[1] as RequestInit).headers).toMatchObject({ "Idempotency-Key": "same-key" });
    fetch.mockResolvedValueOnce(new Response(JSON.stringify({ accepted: true, action: "STOP", epoch, revision: 1 }), { status: 202, headers: { "Location": "/api/v1/backtest-service", "Retry-After": "1" } }));
    await expect(client.recover({ epoch, expectedRevision: 0, action: "RETRY_PREPARATION", resumeJobIds: [] }, "key")).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    const count = fetch.mock.calls.length;
    await expect(client.recover({ epoch, expectedRevision: 0, action: "RESUME_JOBS", resumeJobIds: ["one", "two"] }, "key")).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    expect(fetch).toHaveBeenCalledTimes(count);
  });
  it("reads only inert status while mounted and stops polling after disposal", async () => {
    vi.useFakeTimers(); const client = api(failed()); const listJobs = vi.fn();
    const { wrapper } = host({ api: client, jobApi: { listJobs } }); await flushPromises();
    await vi.advanceTimersByTimeAsync(30000); await flushPromises();
    expect(client.getStatus).toHaveBeenCalledTimes(2);
    expect(client.recover).not.toHaveBeenCalled(); expect(listJobs).not.toHaveBeenCalled();
    wrapper.unmount(); await vi.advanceTimersByTimeAsync(60000);
    expect(client.getStatus).toHaveBeenCalledTimes(2);
  });
  it("loads pending history only on request and requires explicit one-job confirmation", async () => {
    const client = api(ready());
    const listJobs = vi.fn().mockResolvedValue({ items: [{ jobId: "selected", status: "QUEUED" } satisfies Pick<BacktestJobView, "jobId" | "status">] });
    const wrapper = mount(BacktestServiceState, { props: { api: client, jobApi: { listJobs } } }); await flushPromises();
    expect(listJobs).not.toHaveBeenCalled();
    await wrapper.findAll("button").find(button => button.text() === "查看待恢复任务")!.trigger("click"); await flushPromises();
    expect(listJobs.mock.calls[0]?.[0]).toEqual({ status: ["QUEUED", "RUNNING", "CANCEL_REQUESTED"], limit: 1 });
    const button = wrapper.findAll("button").find(button => button.text() === "恢复已选任务")!;
    expect(button.attributes("disabled")).toBeDefined(); await button.trigger("click"); expect(client.recover).not.toHaveBeenCalled();
    await wrapper.get('input[type="checkbox"]').setValue(true); await button.trigger("click"); await flushPromises();
    expect(client.recover).toHaveBeenCalledTimes(1);
    expect(vi.mocked(client.recover).mock.calls[0]?.[0]).toEqual({ epoch, expectedRevision: 0, action: "RESUME_JOBS", resumeJobIds: ["selected"] }); wrapper.unmount();
  });
  it("replays the same frozen control/key after an unknown result despite new status", async () => {
    const client = api(failed()); vi.mocked(client.recover).mockRejectedValueOnce(error("NETWORK_ERROR", 0));
    const createKey = vi.fn(() => "original-key"); const value = host({ api: client, createKey }); await flushPromises();
    await value.service.retryPreparation(); expect(value.service.uncertain.value).toBe(true);
    vi.mocked(client.getStatus).mockResolvedValue(status({ revision: 1, state: "READ_READY", canRead: true, canCancel: true, canExport: true }));
    await value.service.refresh(); await value.service.retryControl();
    const calls = vi.mocked(client.recover).mock.calls; expect(calls[1]?.slice(0, 2)).toEqual(calls[0]?.slice(0, 2)); expect(createKey).toHaveBeenCalledTimes(1);
    value.wrapper.unmount();
  });
  it("cannot repair while physical work is pending and ignores late disposed reads", async () => {
    const client = api(status({ state: "DEGRADED", reason: "SERVICE_REPAIR_REQUIRED", physicallyDrained: false }));
    const value = host({ api: client }); await flushPromises(); await value.service.retryPreparation(); expect(client.recover).not.toHaveBeenCalled();
    let resolve!: (value: BacktestServiceView) => void;
    vi.mocked(client.getStatus).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    const pending = value.service.refresh(); value.wrapper.unmount(); resolve(ready()); await pending;
    expect(value.service.view.value?.state).toBe("DEGRADED");
  });
  it("preserves run fields and exact request/key across scoped 503", async () => {
    const submitRun = vi.fn().mockRejectedValueOnce(error("SERVICE_UNAVAILABLE", 503)).mockRejectedValueOnce(error("SERVICE_UNAVAILABLE", 503));
    const runApi = { ...createBacktestApi(vi.fn()), submitRun };
    let form!: ReturnType<typeof useBacktestRunForm>;
    const createKey = vi.fn(() => "original-run-key");
    const wrapper = mount(defineComponent({ setup() { form = useBacktestRunForm({ api: runApi, createIdempotencyKey: createKey, onAccepted: () => undefined }); return () => h("div"); } }));
    for (const [field, value] of Object.entries({ planVersionId: "123e4567-e89b-42d3-a456-426614174000", datasetHash: "a".repeat(64), initialCashFen: "10000000", buySlippageBps: "0", sellSlippageBps: "0", commissionRate: "0.0003", minimumCommissionFen: "500", stampDutyRate: "0.0005", transferFeeRate: "0.00001" })) form.updateField(field as Parameters<typeof form.updateField>[0], value);
    await form.submit(); expect(form.submissionState.value).toBe("UNCERTAIN");
    form.updateField("initialCashFen", "1"); expect(form.draft.value.initialCashFen).toBe("10000000");
    await form.retrySubmission(); expect(submitRun).toHaveBeenCalledTimes(2);
    expect(submitRun.mock.calls[1]?.slice(0, 2)).toEqual(submitRun.mock.calls[0]?.slice(0, 2)); expect(createKey).toHaveBeenCalledTimes(1); wrapper.unmount();
  });
  it("keeps route prefetch and monitor navigation free of service requests", async () => {
    const backtest = routes.find(route => route.path === "/backtests/new")!;
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(status()), { headers: { "Cache-Control": "no-store" } }));
    await (backtest.component as () => Promise<unknown>)(); expect(fetch).not.toHaveBeenCalled();
    const router = createRouter({ history: createMemoryHistory(), routes: [
      { path: "/", component: { template: "<h1>监控</h1>" } },
      { path: "/backtests", meta: { section: "backtests" }, component: { template: "<h1>历史</h1>" } },
    ] }); await router.push("/"); await router.isReady();
    const wrapper = mount(AppShell, { global: { plugins: [router], provide: { [apiFetchKey as symbol]: fetch, [shellConnectionKey as symbol]: ref({ code: "LIVE", label: "连接", marker: "●" }) } } }); await flushPromises();
    expect(fetch).not.toHaveBeenCalled(); await router.push("/backtests"); await flushPromises();
    expect(fetch).toHaveBeenCalledTimes(1); expect(fetch.mock.calls[0]?.[0]).toBe("/api/v1/backtest-service");
    await router.push("/"); await flushPromises(); expect(wrapper.find('[data-testid="backtest-service-state"]').exists()).toBe(false); wrapper.unmount();
  });
});
