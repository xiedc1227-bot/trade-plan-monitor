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
  it("requires explicit stop confirmation and allows keeping the service running", async () => {
    const client = api(ready());
    const wrapper = mount(BacktestServiceState, { props: { api: client, jobApi: { listJobs: vi.fn().mockResolvedValue({ items: [] }) } } });
    await flushPromises();
    await wrapper.get('[data-testid="backtest-service-management-toggle"]').trigger("click");
    const button = (label: string) => wrapper.findAll("button").find(item => item.text() === label)!;
    await button("停止回测服务").trigger("click");
    expect(client.stop).not.toHaveBeenCalled();
    await button("保持服务运行").trigger("click");
    expect(client.stop).not.toHaveBeenCalled();
    await button("停止回测服务").trigger("click");
    await button("确认停止服务").trigger("click"); await flushPromises();
    expect(client.stop).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });
  it("keeps healthy status compact and reveals controls only through service management", async () => {
    const client = api(ready()); const listJobs = vi.fn().mockResolvedValue({ items: [] });
    const wrapper = mount(BacktestServiceState, { props: { api: client, jobApi: { listJobs } } }); await flushPromises();
    const management = wrapper.get('[data-testid="backtest-service-management-toggle"]');
    expect(management.text()).toBe("服务管理"); expect(management.attributes("aria-expanded")).toBe("false");
    expect(wrapper.find('[data-testid="backtest-service-management"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("新的有效操作会准备执行能力");
    expect(listJobs).toHaveBeenCalledTimes(1);
    await management.trigger("click");
    expect(management.attributes("aria-expanded")).toBe("true");
    const panel = wrapper.get('[data-testid="backtest-service-management"]');
    for (const label of ["刷新服务状态", "查看待恢复任务", "停止回测服务"]) expect(panel.text()).toContain(label);
    expect(client.recover).not.toHaveBeenCalled(); expect(client.stop).not.toHaveBeenCalled();
    await management.trigger("click"); expect(management.attributes("aria-expanded")).toBe("false"); wrapper.unmount();
  });
  it("automatically reveals a pending history task but requires explicit one-job confirmation", async () => {
    const client = api(ready());
    const listJobs = vi.fn().mockResolvedValue({ items: [{ jobId: "selected", status: "QUEUED" } satisfies Pick<BacktestJobView, "jobId" | "status">] });
    const wrapper = mount(BacktestServiceState, { props: { api: client, jobApi: { listJobs } } }); await flushPromises();
    expect(listJobs).toHaveBeenCalledTimes(1);
    expect(wrapper.get('[data-testid="backtest-service-management-toggle"]').attributes("aria-expanded")).toBe("true");
    expect(listJobs.mock.calls[0]?.[0]).toEqual({ status: ["QUEUED", "RUNNING", "CANCEL_REQUESTED"], limit: 1 });
    const button = wrapper.findAll("button").find(button => button.text() === "恢复已选任务")!;
    expect(button.attributes("disabled")).toBeDefined(); await button.trigger("click"); expect(client.recover).not.toHaveBeenCalled();
    await wrapper.get('input[type="checkbox"]').setValue(true); await button.trigger("click"); await flushPromises();
    expect(client.recover).toHaveBeenCalledTimes(1);
    expect(vi.mocked(client.recover).mock.calls[0]?.[0]).toEqual({ epoch, expectedRevision: 0, action: "RESUME_JOBS", resumeJobIds: ["selected"] }); wrapper.unmount();
  });
  it("does not call an authorized running task interrupted or load its recovery history", async () => {
    const client = api(status({ state: "READY", canRead: true, canSubmit: true, canCancel: true, canExport: true, authorizedJobIds: ["running"], physicallyDrained: false }));
    const listJobs = vi.fn();
    const wrapper = mount(BacktestServiceState, { props: { api: client, jobApi: { listJobs } } }); await flushPromises();
    expect(listJobs).not.toHaveBeenCalled();
    expect(wrapper.get('[data-testid="backtest-service-management-toggle"]').attributes("aria-expanded")).toBe("false");
    expect(wrapper.text()).not.toContain("正在等待已有工作实际结束"); wrapper.unmount();
  });
  it("checks pending history once per service identity instead of competing with every progress poll", async () => {
    vi.useFakeTimers(); const client = api(ready()); const listJobs = vi.fn().mockResolvedValue({ items: [] });
    const value = host({ api: client, jobApi: { listJobs } }); await flushPromises();
    await vi.advanceTimersByTimeAsync(20000); await flushPromises();
    expect(client.getStatus).toHaveBeenCalledTimes(3); expect(listJobs).toHaveBeenCalledTimes(1);
    vi.mocked(client.getStatus).mockResolvedValue(status({ ...ready(), epoch: "b".repeat(32) }));
    await value.service.refresh(); await flushPromises(); expect(listJobs).toHaveBeenCalledTimes(2); value.wrapper.unmount();
  });
  it.each([failed(), status({ state: "STOPPED" }), status({ state: "DISABLED", epoch: null })])("reveals management when service intervention is needed", async value => {
    const wrapper = mount(BacktestServiceState, { props: { api: api(value) } }); await flushPromises();
    expect(wrapper.get('[data-testid="backtest-service-management-toggle"]').attributes("aria-expanded")).toBe("true");
    expect(wrapper.find('[data-testid="backtest-service-management"]').exists()).toBe(true); wrapper.unmount();
  });
  it("reveals read failures without submitting a repair", async () => {
    const client = api(); vi.mocked(client.getStatus).mockRejectedValueOnce(error("NETWORK_ERROR", 0));
    const wrapper = mount(BacktestServiceState, { props: { api: client } }); await flushPromises();
    expect(wrapper.get('[data-testid="backtest-service-management-toggle"]').attributes("aria-expanded")).toBe("true");
    expect(wrapper.text()).toContain("回测服务状态暂不可用"); expect(client.recover).not.toHaveBeenCalled(); wrapper.unmount();
  });
  it("keeps a background busy response quiet but reports an explicitly requested failed check", async () => {
    const client = api(ready()); const listJobs = vi.fn().mockRejectedValue(error("SERVICE_UNAVAILABLE", 503));
    const wrapper = mount(BacktestServiceState, { props: { api: client, jobApi: { listJobs } } }); await flushPromises();
    const toggle = wrapper.get('[data-testid="backtest-service-management-toggle"]');
    expect(toggle.attributes("aria-expanded")).toBe("false");
    await toggle.trigger("click");
    await wrapper.findAll("button").find(button => button.text() === "查看待恢复任务")!.trigger("click"); await flushPromises();
    expect(wrapper.text()).toContain("待恢复任务暂不可读取"); expect(client.recover).not.toHaveBeenCalled(); wrapper.unmount();
  });
  it("ignores a pending-history read after service identity or authorization changes", async () => {
    let resolve!: (value: { items: BacktestJobView[] }) => void;
    const listJobs = vi.fn().mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    const client = api(ready()); const value = host({ api: client, jobApi: { listJobs } }); await flushPromises();
    vi.mocked(client.getStatus).mockResolvedValue(status({ ...ready(), revision: 1, authorizedJobIds: ["selected"] }));
    await value.service.refresh();
    resolve({ items: [{ jobId: "selected", status: "RUNNING" } as BacktestJobView] }); await flushPromises();
    expect(value.service.pendingJob.value).toBeNull(); expect(client.recover).not.toHaveBeenCalled(); value.wrapper.unmount();
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
