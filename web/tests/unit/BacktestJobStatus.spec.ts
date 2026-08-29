import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { mount } from "@vue/test-utils";
import { afterEach, describe, expect, it } from "vitest";

import type { BacktestJobView } from "../../src/api/generated";
import BacktestJobStatus from "../../src/components/backtests/BacktestJobStatus.vue";

const TIME = "2026-08-29T10:00:00.000000+08:00";

function job(
  status: BacktestJobView["status"] = "RUNNING",
  overrides: Partial<BacktestJobView> = {},
): BacktestJobView {
  const terminal = status === "COMPLETED" || status === "FAILED" || status === "CANCELLED";
  const failed = status === "FAILED" || status === "CANCELLED";
  return Object.freeze({
    attempt: status === "QUEUED" ? 0 : 1,
    cancelRequestedAt:
      status === "CANCEL_REQUESTED" || status === "CANCELLED" ? TIME : null,
    createdAt: TIME,
    datasetHash: null,
    errorCode: failed ? `${status}_SAFE` : null,
    errorMessage: failed ? "服务端安全诊断" : null,
    finishedAt: terminal ? TIME : null,
    jobId: "job-status-001",
    kind: "DATA_SYNC",
    progress: Object.freeze({
      completedUnits: terminal ? 4 : 2,
      phase: terminal ? "TERMINAL" : status === "QUEUED" ? "QUEUED" : "SYNCING_DATA",
      totalUnits: 4,
      unit: "ITEMS",
      updatedAt: TIME,
    }),
    requestHash: "a".repeat(64),
    result: null,
    reused: false,
    revision: 1,
    runId: null,
    startedAt: status === "QUEUED" ? null : TIME,
    status,
    updatedAt: TIME,
    ...overrides,
  });
}

function mountStatus(
  props: Partial<InstanceType<typeof BacktestJobStatus>["$props"]> = {},
) {
  return mount(BacktestJobStatus, {
    attachTo: document.body,
    props: {
      cancellationState: "IDLE",
      job: job(),
      requestState: "READY",
      ...props,
    },
  });
}

afterEach(() => {
  document.body.replaceChildren();
});

describe("BacktestJobStatus", () => {
  it("renders authoritative phase, known progress, identity, and research-only copy", () => {
    const wrapper = mountStatus();

    expect(wrapper.get('[data-testid="backtest-job-status"]').attributes("data-status")).toBe(
      "RUNNING",
    );
    expect(wrapper.text()).toContain("运行中");
    expect(wrapper.text()).toContain("正在同步历史数据");
    expect(wrapper.text()).toContain("job-status-001");
    expect(wrapper.text()).toContain("2 / 4 项");
    expect(wrapper.text()).toContain("仅供研究，不会自动下单");
    expect(wrapper.get("progress").attributes()).toMatchObject({ max: "4", value: "2" });
  });

  it("uses phase text without inventing a percentage when total progress is unknown", () => {
    const wrapper = mountStatus({
      job: job("RUNNING", {
        progress: Object.freeze({
          ...job().progress,
          completedUnits: 7,
          totalUnits: null,
        }),
      }),
    });

    expect(wrapper.find("progress").exists()).toBe(false);
    expect(wrapper.text()).toContain("已处理 7 项，总量待服务端确认");
    expect(wrapper.text()).not.toContain("%");
  });

  it("confirms cancellation, supports Escape, and restores focus to the trigger", async () => {
    const wrapper = mountStatus({ job: job("QUEUED") });
    const trigger = wrapper.get<HTMLButtonElement>('[data-testid="request-job-cancel"]');
    trigger.element.focus();
    await trigger.trigger("click");

    const dialog = wrapper.get('[role="dialog"]');
    expect(dialog.attributes("aria-modal")).toBe("true");
    expect(document.activeElement).toBe(
      wrapper.get<HTMLButtonElement>('[data-testid="confirm-job-cancel"]').element,
    );

    await dialog.trigger("keydown", { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(
      wrapper.get<HTMLButtonElement>('[data-testid="dismiss-job-cancel"]').element,
    );
    await dialog.trigger("keydown", { key: "Tab" });
    expect(document.activeElement).toBe(
      wrapper.get<HTMLButtonElement>('[data-testid="confirm-job-cancel"]').element,
    );

    await dialog.trigger("keydown", { key: "Escape" });
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false);
    expect(document.activeElement).toBe(trigger.element);

    await trigger.trigger("click");
    await wrapper.get('[data-testid="confirm-job-cancel"]').trigger("click");
    expect(wrapper.emitted("cancel")).toHaveLength(1);
  });

  it("keeps cancel-requested authoritative and offers no duplicate cancel action", () => {
    const wrapper = mountStatus({ job: job("CANCEL_REQUESTED") });

    expect(wrapper.text()).toContain("取消已请求，等待服务端确认");
    expect(wrapper.find('[data-testid="request-job-cancel"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("已取消");
  });

  it("offers same-intent retry for uncertain cancellation without exposing raw errors", async () => {
    const wrapper = mountStatus({
      cancellationState: "UNCERTAIN",
      errorMessage: "取消结果尚未确认，请查询任务状态或安全重试",
    });

    expect(wrapper.get('[role="alert"]').text()).toContain("取消结果尚未确认");
    expect(wrapper.text()).not.toContain("private");
    await wrapper.get('[data-testid="retry-job-cancel"]').trigger("click");
    expect(wrapper.emitted("retryCancellation")).toHaveLength(1);
  });

  it("does not reopen cancellation from a stale running snapshot after conflict", () => {
    const wrapper = mountStatus({
      cancellationState: "CONFLICT",
      errorMessage: "任务已进入不可取消状态，最新状态暂不可用",
      job: job("RUNNING"),
      requestState: "FAILED",
    });

    expect(wrapper.find('[data-testid="request-job-cancel"]').exists()).toBe(false);
    expect(wrapper.get('[role="alert"]').text()).toContain("不可取消");
  });

  it("allows an explicit new cancellation intent after a deterministic failure", async () => {
    const wrapper = mountStatus({
      cancellationState: "FAILED",
      errorMessage: "取消请求未被服务端接受",
      job: job("RUNNING"),
    });

    expect(wrapper.get('[role="alert"]').text()).toContain("未被服务端接受");
    await wrapper.get('[data-testid="request-job-cancel"]').trigger("click");
    await wrapper.get('[data-testid="confirm-job-cancel"]').trigger("click");
    expect(wrapper.emitted("cancel")).toHaveLength(1);
  });

  it("renders terminal diagnostics only from the authoritative job and escapes hostile text", () => {
    const hostile = '<img src=x onerror="globalThis.compromised=true">';
    const wrapper = mountStatus({
      job: job("FAILED", { errorCode: "RUN_FAILED", errorMessage: hostile }),
    });

    expect(wrapper.get('[data-testid="job-diagnostic"]').text()).toContain("RUN_FAILED");
    expect(wrapper.get('[data-testid="job-diagnostic"]').text()).toContain(hostile);
    expect(wrapper.find("img").exists()).toBe(false);
    expect(wrapper.find('[data-testid="request-job-cancel"]').exists()).toBe(false);
  });

  it("labels cached data during refresh/failure and emits an explicit refresh intent", async () => {
    const refreshing = mountStatus({ requestState: "REFRESHING" });
    expect(refreshing.text()).toContain("正在刷新，当前显示上一次权威状态");
    refreshing.unmount();

    const failed = mountStatus({
      errorMessage: "任务状态暂不可用",
      requestState: "FAILED",
    });
    expect(failed.get('[role="alert"]').text()).toContain("任务状态暂不可用");
    await failed.get('[data-testid="refresh-job-status"]').trigger("click");
    expect(failed.emitted("refresh")).toHaveLength(1);
  });

  it("announces status transitions but not unchanged polling progress", async () => {
    const wrapper = mountStatus();
    const live = wrapper.get('[data-testid="job-status-announcement"]');
    const initialAnnouncement = live.text();

    await wrapper.setProps({
      job: job("RUNNING", {
        progress: Object.freeze({ ...job().progress, completedUnits: 3 }),
        revision: 2,
      }),
    });
    expect(live.text()).toBe(initialAnnouncement);

    await wrapper.setProps({ job: job("COMPLETED") });
    expect(live.text()).toContain("任务已完成");
  });

  it("does not poll-spam the live region across repeated refresh failures", async () => {
    const wrapper = mountStatus({
      errorMessage: "任务状态暂不可用",
      requestState: "FAILED",
    });
    const live = wrapper.get('[data-testid="job-status-announcement"]');
    const firstFailure = live.text();
    expect(firstFailure).toBe("任务状态刷新失败");

    await wrapper.setProps({ errorMessage: null, requestState: "REFRESHING" });
    expect(live.text()).toBe(firstFailure);
    await wrapper.setProps({
      errorMessage: "任务状态暂不可用",
      requestState: "FAILED",
    });
    expect(live.text()).toBe(firstFailure);
  });

  it("contains no unescaped HTML directive or path/file picker surface", () => {
    const source = readFileSync(
      resolve(process.cwd(), "src/components/backtests/BacktestJobStatus.vue"),
      "utf8",
    );

    expect(source).not.toContain("v-html");
    expect(source).not.toContain("showOpenFilePicker");
    expect(source).not.toContain("showSaveFilePicker");
    expect(source).not.toMatch(/monitorStore|useMonitorStore/);
  });
});
