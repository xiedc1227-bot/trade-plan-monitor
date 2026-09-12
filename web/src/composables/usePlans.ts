import {
  computed,
  onBeforeUnmount,
  onMounted,
  shallowReadonly,
  shallowRef,
} from "vue";
import type { ComputedRef, ShallowRef } from "vue";

import { ApiClientError, createPlanApi, type PlanApi } from "../api/plans";
import type {
  ActivePlanView,
  DraftReviewIssue,
  PlanActivationCommand,
  PlanDeactivationCommand,
  PlanDraftCommand,
  PlanImportCommand,
  PlanReviewConfirmationCommand,
  PlanVersionPage,
  PlanVersionSummary,
  PlanVersionView,
} from "../api/generated";

const PAGE_LIMIT = 100;
const IDEMPOTENCY_KEY_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const EMPTY_VERSIONS: readonly PlanVersionSummary[] = Object.freeze([]);

interface PendingMutationIntent {
  readonly fingerprint: string;
  readonly idempotencyKey: string;
}

export interface UsePlansOptions {
  readonly api?: PlanApi;
  readonly createIdempotencyKey?: () => string;
  readonly initialPlanVersionId?: string;
}

export interface ExtractedPlanDraftIntent {
  readonly extractionId: string;
  readonly planJson: string;
  readonly reviewIssues: readonly DraftReviewIssue[];
  readonly sourceText: string;
  readonly symbol: string;
}

export interface UsePlansResult {
  readonly activeState: Readonly<ShallowRef<ActivePlanView | null>>;
  readonly activePlan: Readonly<ShallowRef<PlanVersionView | null>>;
  readonly busy: Readonly<ShallowRef<boolean>>;
  readonly errorMessage: Readonly<ShallowRef<string | null>>;
  readonly loading: Readonly<ShallowRef<boolean>>;
  readonly page: Readonly<ShallowRef<PlanVersionPage | null>>;
  readonly selectedPlanId: Readonly<ShallowRef<string | null>>;
  readonly selectedPlan: Readonly<ShallowRef<PlanVersionView | null>>;
  readonly versions: ComputedRef<readonly PlanVersionSummary[]>;
  activatePlan(command: PlanActivationCommand): Promise<boolean>;
  confirmPlanReview(command: PlanReviewConfirmationCommand): Promise<boolean>;
  deactivatePlan(command: PlanDeactivationCommand): Promise<boolean>;
  importPlan(command: PlanImportCommand): Promise<boolean>;
  openPlan(planVersionId: string | null): Promise<boolean>;
  refresh(): Promise<boolean>;
  saveDraft(command: PlanDraftCommand): Promise<boolean>;
  saveExtractedDraft(intent: ExtractedPlanDraftIntent): Promise<boolean>;
  selectPlan(planVersionId: string): Promise<boolean>;
}

export function usePlans(options: UsePlansOptions = {}): UsePlansResult {
  const api = options.api ?? createPlanApi();
  const page = shallowRef<PlanVersionPage | null>(null);
  const selectedPlanId = shallowRef<string | null>(null);
  const selectedPlan = shallowRef<PlanVersionView | null>(null);
  const activeState = shallowRef<ActivePlanView | null>(null);
  const activePlan = shallowRef<PlanVersionView | null>(null);
  const loading = shallowRef(true);
  const busy = shallowRef(false);
  const errorMessage = shallowRef<string | null>(null);
  let readController: AbortController | null = null;
  let mutationController: AbortController | null = null;
  let readGeneration = 0;
  let pendingMutationIntent: PendingMutationIntent | null = null;

  const versions = computed<readonly PlanVersionSummary[]>(
    () => page.value?.items ?? EMPTY_VERSIONS,
  );

  async function refresh(preferredPlanId = selectedPlanId.value): Promise<boolean> {
    const generation = ++readGeneration;
    readController?.abort();
    const controller = new AbortController();
    readController = controller;
    loading.value = true;
    errorMessage.value = null;
    try {
      const result = await api.listPlanVersions(
        { limit: PAGE_LIMIT, offset: 0 },
        { signal: controller.signal },
      );
      if (!isCurrentRead(controller, generation)) return false;
      page.value = freezePage(result);
      selectedPlanId.value =
        preferredPlanId ?? chooseSelection(page.value.items ?? [], null);
      selectedPlan.value = null;
      activePlan.value = null;
      const selectedPlanVersionId = selectedPlanId.value;
      if (selectedPlanVersionId === null) {
        activeState.value = null;
        return true;
      }
      const detail = await api.getPlanVersion(selectedPlanVersionId, {
        signal: controller.signal,
      });
      if (!isCurrentRead(controller, generation)) return false;
      const summary = page.value.items?.find((item) => item.id === selectedPlanVersionId);
      if (summary !== undefined && detail.symbol !== summary.symbol) {
        throw new Error("plan detail identity mismatch");
      }
      const state = await api.getPlanActivationState(detail.symbol, {
        signal: controller.signal,
      });
      if (!isCurrentRead(controller, generation)) return false;
      const currentActivePlan = await loadActivePlan(state, detail, controller.signal);
      if (!isCurrentRead(controller, generation)) return false;
      selectedPlan.value = freezeVersion(detail);
      activeState.value = Object.freeze({ ...state });
      activePlan.value = currentActivePlan;
      return true;
    } catch {
      if (!isCurrentRead(controller, generation)) return false;
      activeState.value = null;
      activePlan.value = null;
      selectedPlan.value = null;
      errorMessage.value = "计划版本加载失败，请稍后重试。";
      return false;
    } finally {
      if (isCurrentRead(controller, generation)) loading.value = false;
      if (readController === controller) readController = null;
    }
  }

  async function selectPlan(planVersionId: string): Promise<boolean> {
    const summary = versions.value.find((item) => item.id === planVersionId);
    if (summary === undefined) return false;
    selectedPlanId.value = planVersionId;
    selectedPlan.value = null;
    activeState.value = null;
    activePlan.value = null;
    const generation = ++readGeneration;
    readController?.abort();
    const controller = new AbortController();
    readController = controller;
    loading.value = true;
    errorMessage.value = null;
    try {
      const [detail, state] = await Promise.all([
        api.getPlanVersion(summary.id, { signal: controller.signal }),
        api.getPlanActivationState(summary.symbol, { signal: controller.signal }),
      ]);
      if (!isCurrentRead(controller, generation)) return false;
      if (detail.symbol !== summary.symbol) throw new Error("plan detail identity mismatch");
      const currentActivePlan = await loadActivePlan(state, detail, controller.signal);
      if (!isCurrentRead(controller, generation)) return false;
      selectedPlan.value = freezeVersion(detail);
      activeState.value = Object.freeze({ ...state });
      activePlan.value = currentActivePlan;
      errorMessage.value = null;
      return true;
    } catch {
      if (!isCurrentRead(controller, generation)) return false;
      selectedPlan.value = null;
      activeState.value = null;
      activePlan.value = null;
      errorMessage.value = "计划启停状态加载失败，请稍后重试。";
      return false;
    } finally {
      if (isCurrentRead(controller, generation)) loading.value = false;
      if (readController === controller) readController = null;
    }
  }

  async function openPlan(planVersionId: string | null): Promise<boolean> {
    return refresh(planVersionId);
  }

  async function saveDraft(command: PlanDraftCommand): Promise<boolean> {
    const revision = authoritativeMutationRevision();
    if (revision === null) return false;
    const base = selectedPlan.value;
    if (base === null) {
      errorMessage.value = "计划详情尚未确认，无法保存草稿。";
      return false;
    }
    const revisionBoundCommand: PlanDraftCommand = {
      ...command,
      basePlanVersionId: base.id,
      expectedRevision: revision,
    };
    return mutate(
      "SAVE_DRAFT",
      revisionBoundCommand,
      (prepared, key, signal) => api.savePlanDraft(prepared, key, { signal }),
      (saved) => saved.id,
      "计划草稿可能已保存，但无法确认结果；请刷新后核对。",
    );
  }

  async function importPlan(command: PlanImportCommand): Promise<boolean> {
    if (busy.value) return false;
    busy.value = true;
    errorMessage.value = null;
    let revision: number | null;
    try {
      revision = await authoritativeTargetRevision(
        command.symbol,
        "目标股票启停状态无法确认，未提交导入。",
      );
    } finally {
      busy.value = false;
    }
    if (revision === null) return false;
    const revisionBoundCommand: PlanImportCommand = {
      ...command,
      expectedRevision: revision,
    };
    return mutate(
      "IMPORT_PLAN",
      revisionBoundCommand,
      (prepared, key, signal) => api.importPlan(prepared, key, { signal }),
      (imported) => imported.id,
      "计划可能已导入，但无法确认结果；请刷新后核对。",
    );
  }

  async function saveExtractedDraft(
    intent: ExtractedPlanDraftIntent,
  ): Promise<boolean> {
    if (busy.value) return false;
    busy.value = true;
    errorMessage.value = null;
    let revision: number | null;
    try {
      revision = await authoritativeTargetRevision(
        intent.symbol,
        "目标股票启停状态无法确认，未保存 AI 审核草稿。",
      );
    } finally {
      busy.value = false;
    }
    if (revision === null) return false;
    const command: PlanDraftCommand = {
      expectedRevision: revision,
      extractionId: intent.extractionId,
      planJson: intent.planJson,
      reviewIssues: [...intent.reviewIssues],
      sourceText: intent.sourceText,
    };
    return mutate(
      "SAVE_EXTRACTED_DRAFT",
      command,
      (prepared, key, signal) => api.savePlanDraft(prepared, key, { signal }),
      (saved) => saved.id,
      "AI 审核草稿可能已保存，但无法确认结果；请刷新后核对。",
    );
  }

  async function activatePlan(command: PlanActivationCommand): Promise<boolean> {
    return mutate(
      "ACTIVATE_PLAN",
      command,
      (prepared, key, signal) => api.activatePlan(prepared, key, { signal }),
      () => command.planVersionId,
      "计划可能已启用，但无法确认结果；请刷新后核对。",
    );
  }

  async function confirmPlanReview(command: PlanReviewConfirmationCommand): Promise<boolean> {
    return mutate(
      "CONFIRM_PLAN_REVIEW",
      command,
      (prepared, key, signal) => api.confirmPlanReview(prepared, key, { signal }),
      () => command.planVersionId,
      "复核可能已提交，但无法确认结果；请刷新后核对。",
    );
  }

  async function deactivatePlan(command: PlanDeactivationCommand): Promise<boolean> {
    return mutate(
      "DEACTIVATE_PLAN",
      command,
      (prepared, key, signal) => api.deactivatePlan(prepared, key, { signal }),
      () => selectedPlanId.value,
      "计划可能已停用，但无法确认结果；请刷新后核对。",
    );
  }

  async function mutate<TCommand extends object, TResult>(
    operationKind: string,
    command: TCommand,
    operation: (
      command: TCommand,
      idempotencyKey: string,
      signal: AbortSignal,
    ) => Promise<TResult>,
    preferredPlanId: (result: TResult) => string | null,
    uncertainMessage: string,
  ): Promise<boolean> {
    if (busy.value) return false;
    const fingerprint = mutationFingerprint(operationKind, command);
    const idempotencyKey = idempotencyKeyFor(fingerprint);
    if (idempotencyKey === null) {
      errorMessage.value = "无法生成有效的计划请求标识。";
      return false;
    }
    const controller = new AbortController();
    mutationController = controller;
    busy.value = true;
    errorMessage.value = null;
    try {
      const result = await operation(command, idempotencyKey, controller.signal);
      if (controller.signal.aborted) return false;
      const refreshed = await refresh(preferredPlanId(result));
      if (refreshed) {
        clearPendingMutation(fingerprint);
      } else {
        errorMessage.value = uncertainMessage;
      }
      return refreshed;
    } catch (error) {
      if (!controller.signal.aborted) {
        const uncertain = isUncertainMutation(error);
        if (!uncertain) clearPendingMutation(fingerprint);
        await refresh(selectedPlanId.value);
        if (!controller.signal.aborted) {
          errorMessage.value = uncertain
            ? uncertainMessage
            : definitiveMutationMessage(error);
        }
      }
      return false;
    } finally {
      if (mutationController === controller) mutationController = null;
      if (!controller.signal.aborted) busy.value = false;
    }
  }

  function createIdempotencyKey(): string {
    return options.createIdempotencyKey?.() ?? `plan-${globalThis.crypto.randomUUID()}`;
  }

  function idempotencyKeyFor(fingerprint: string): string | null {
    if (pendingMutationIntent?.fingerprint === fingerprint) {
      return pendingMutationIntent.idempotencyKey;
    }
    const idempotencyKey = createIdempotencyKey();
    if (!IDEMPOTENCY_KEY_PATTERN.test(idempotencyKey)) return null;
    pendingMutationIntent = Object.freeze({ fingerprint, idempotencyKey });
    return idempotencyKey;
  }

  function clearPendingMutation(fingerprint: string): void {
    if (pendingMutationIntent?.fingerprint === fingerprint) {
      pendingMutationIntent = null;
    }
  }

  function isCurrentRead(controller: AbortController, generation: number): boolean {
    return (
      !controller.signal.aborted &&
      readController === controller &&
      readGeneration === generation
    );
  }

  function authoritativeMutationRevision(): number | null {
    const loadedPage = page.value;
    if (loadedPage === null) {
      errorMessage.value = "计划状态尚未确认，无法提交变更。";
      return null;
    }
    const selected = selectedPlan.value;
    const state = activeState.value;
    if (selected === null || state === null || state.symbol !== selected.symbol) {
      errorMessage.value = "计划启停状态尚未确认，无法提交变更。";
      return null;
    }
    return state.revision;
  }

  async function authoritativeTargetRevision(
    symbol: string,
    unavailableMessage: string,
  ): Promise<number | null> {
    const loadedPage = page.value;
    if (loadedPage === null) {
      errorMessage.value = "计划状态尚未确认，无法提交变更。";
      return null;
    }
    if (activeState.value?.symbol === symbol) return activeState.value.revision;
    const controller = new AbortController();
    mutationController = controller;
    try {
      const state = await api.getPlanActivationState(symbol, { signal: controller.signal });
      return controller.signal.aborted ? null : state.revision;
    } catch (error) {
      if (controller.signal.aborted) return null;
      if (error instanceof ApiClientError && error.code === "NOT_FOUND") return 0;
      errorMessage.value = unavailableMessage;
      return null;
    } finally {
      if (mutationController === controller) mutationController = null;
    }
  }

  async function loadActivePlan(
    state: ActivePlanView,
    selected: PlanVersionView,
    signal: AbortSignal,
  ): Promise<PlanVersionView | null> {
    if (!state.active || state.planVersionId === null) return null;
    if (state.planVersionId === selected.id) return freezeVersion(selected);
    const current = await api.getPlanVersion(state.planVersionId, { signal });
    if (current.symbol !== state.symbol) throw new Error("active plan identity mismatch");
    return freezeVersion(current);
  }

  onMounted(() => refresh(options.initialPlanVersionId ?? null));
  onBeforeUnmount(() => {
    readController?.abort();
    mutationController?.abort();
  });

  return Object.freeze({
    activeState: shallowReadonly(activeState),
    activePlan: shallowReadonly(activePlan),
    busy: shallowReadonly(busy),
    errorMessage: shallowReadonly(errorMessage),
    loading: shallowReadonly(loading),
    page: shallowReadonly(page),
    selectedPlanId: shallowReadonly(selectedPlanId),
    selectedPlan: shallowReadonly(selectedPlan),
    versions,
    activatePlan,
    confirmPlanReview,
    deactivatePlan,
    importPlan,
    openPlan,
    refresh: () => refresh(),
    saveDraft,
    saveExtractedDraft,
    selectPlan,
  });
}

function freezePage(candidate: PlanVersionPage): PlanVersionPage {
  const items = Object.freeze(
    (candidate.items ?? []).map((item) => Object.freeze({ ...item })),
  );
  return Object.freeze({ ...candidate, items }) as PlanVersionPage;
}

function chooseSelection(
  versions: readonly PlanVersionSummary[],
  preferredPlanId: string | null,
): string | null {
  if (
    preferredPlanId !== null &&
    versions.some((version) => version.id === preferredPlanId)
  ) {
    return preferredPlanId;
  }
  return versions.find((version) => version.status === "DRAFT")?.id ?? versions[0]?.id ?? null;
}

function freezeVersion(candidate: PlanVersionView): PlanVersionView {
  return Object.freeze({
    ...candidate,
    reviewIssues: Object.freeze([...(candidate.reviewIssues ?? [])]),
    validationIssues: Object.freeze([...(candidate.validationIssues ?? [])]),
  }) as PlanVersionView;
}

function mutationFingerprint(operationKind: string, command: object): string {
  return `${operationKind}:${stableJson(command)}`;
}

function stableJson(value: unknown): string {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value) ?? "null";
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableJson(item)).join(",")}]`;
  }
  const record = value as Record<string, unknown>;
  const entries = Object.keys(record)
    .filter((key) => record[key] !== undefined)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${stableJson(record[key])}`);
  return `{${entries.join(",")}}`;
}

function isUncertainMutation(error: unknown): boolean {
  return (
    !(error instanceof ApiClientError) ||
    error.code === "NETWORK_ERROR" ||
    error.code === "INVALID_RESPONSE" ||
    (error.status >= 500 && error.status <= 599)
  );
}

function definitiveMutationMessage(error: unknown): string {
  if (!(error instanceof ApiClientError)) {
    return "计划变更结果无法确认；请刷新后核对。";
  }
  if (error.code === "CONFLICT") {
    return "计划状态已变化，本次变更未应用；请核对刷新后的版本。";
  }
  if (
    error.code === "BAD_REQUEST" ||
    error.code === "VALIDATION_ERROR" ||
    error.code === "PAYLOAD_TOO_LARGE"
  ) {
    return "计划内容未通过后端校验，本次变更未应用。";
  }
  if (error.code === "NOT_FOUND") {
    return "目标计划已不存在，本次变更未应用。";
  }
  return "后端拒绝了本次计划变更；请核对当前状态。";
}
