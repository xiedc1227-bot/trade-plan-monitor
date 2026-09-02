import { onBeforeUnmount, onMounted, shallowReadonly, shallowRef } from "vue";

import { createAIPlanApi, type AIPlanApi } from "../api/ai";
import type {
  ConfiguredAIRuntimeView,
  PlanExtractionCommand,
  PlanExtractionView,
} from "../api/generated";

export interface UsePlanDraftingOptions {
  readonly api?: AIPlanApi;
  readonly createIdempotencyKey?: () => string;
  readonly pollIntervalMs?: number;
}

const TERMINAL_STATUSES = new Set<PlanExtractionView["status"]>([
  "CANCELLED",
  "INVALID_OUTPUT",
  "PROVIDER_ERROR",
  "SUCCEEDED",
]);

function defaultIdempotencyKey(): string {
  return globalThis.crypto.randomUUID();
}

export function usePlanDrafting(options: UsePlanDraftingOptions = {}) {
  const api = options.api ?? createAIPlanApi();
  const createIdempotencyKey = options.createIdempotencyKey ?? defaultIdempotencyKey;
  const pollIntervalMs = options.pollIntervalMs ?? 500;
  const runtime = shallowRef<ConfiguredAIRuntimeView | null>(null);
  const extraction = shallowRef<PlanExtractionView | null>(null);
  const loading = shallowRef(true);
  const submitting = shallowRef(false);
  const errorMessage = shallowRef<string | null>(null);
  const stoppedMessage = shallowRef<string | null>(null);
  let runtimeController: AbortController | null = null;
  let extractionController: AbortController | null = null;

  async function loadRuntime(): Promise<void> {
    runtimeController?.abort();
    const controller = new AbortController();
    runtimeController = controller;
    loading.value = true;
    errorMessage.value = null;
    try {
      const value = await api.getRuntime({ signal: controller.signal });
      if (!controller.signal.aborted) runtime.value = Object.freeze(value);
    } catch {
      if (!controller.signal.aborted) {
        runtime.value = null;
        errorMessage.value = "AI 配置加载失败，请检查 config/app.yaml 和项目 .env 后重启 Web 服务。";
      }
    } finally {
      if (!controller.signal.aborted) loading.value = false;
      if (runtimeController === controller) runtimeController = null;
    }
  }

  async function submitExtraction(command: PlanExtractionCommand): Promise<void> {
    if (submitting.value || extractionController !== null) return;
    const controller = new AbortController();
    extractionController = controller;
    submitting.value = true;
    errorMessage.value = null;
    stoppedMessage.value = null;
    let acceptedByServer = false;
    try {
      const receipt = await api.submitExtraction(command, createIdempotencyKey(), {
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      acceptedByServer = true;
      extraction.value = Object.freeze({
        id: receipt.operationId,
        providerId: command.providerId,
        status: receipt.status,
        submittedAt: receipt.submittedAt,
      });
      submitting.value = false;
      await pollExtraction(receipt.operationId, controller);
    } catch {
      if (!controller.signal.aborted) {
        extraction.value = null;
        errorMessage.value = acceptedByServer
          ? "无法确认 AI 提取状态；服务端任务可能仍会继续，请稍后重试查询或重新提交。"
          : "AI 提取请求失败，未生成计划草稿。请稍后重试。";
      }
    } finally {
      if (!controller.signal.aborted) submitting.value = false;
      if (extractionController === controller) extractionController = null;
    }
  }

  async function pollExtraction(
    operationId: string,
    controller: AbortController,
  ): Promise<void> {
    while (!controller.signal.aborted) {
      const value = await api.getExtraction(operationId, { signal: controller.signal });
      if (controller.signal.aborted) return;
      extraction.value = Object.freeze(value);
      if (TERMINAL_STATUSES.has(value.status)) return;
      await waitForPoll(pollIntervalMs, controller.signal);
    }
  }

  function stopWaiting(operationId: string): void {
    if (extraction.value?.id !== operationId || extractionController === null) return;
    extractionController.abort();
    extractionController = null;
    submitting.value = false;
    extraction.value = null;
    stoppedMessage.value = "已停止在本页等待；服务端已接收的任务可能仍会继续执行。";
  }

  onMounted(loadRuntime);
  onBeforeUnmount(() => {
    runtimeController?.abort();
    extractionController?.abort();
  });

  return Object.freeze({
    errorMessage: shallowReadonly(errorMessage),
    extraction: shallowReadonly(extraction),
    loading: shallowReadonly(loading),
    runtime: shallowReadonly(runtime),
    stoppedMessage: shallowReadonly(stoppedMessage),
    submitting: shallowReadonly(submitting),
    stopWaiting,
    submitExtraction,
  });
}

function waitForPoll(milliseconds: number, signal: AbortSignal): Promise<void> {
  if (milliseconds <= 0 || signal.aborted) return Promise.resolve();
  return new Promise((resolve) => {
    const timeoutId = globalThis.setTimeout(finish, milliseconds);
    signal.addEventListener("abort", finish, { once: true });
    function finish(): void {
      globalThis.clearTimeout(timeoutId);
      signal.removeEventListener("abort", finish);
      resolve();
    }
  });
}
