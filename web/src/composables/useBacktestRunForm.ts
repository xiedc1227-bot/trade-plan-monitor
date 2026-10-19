import { onBeforeUnmount, onMounted, readonly, shallowRef, watch, type DeepReadonly } from "vue";

import type {
  BacktestInitialLotInput,
  BacktestJobReceipt,
  BacktestReferenceMarketCoverageView,
  BacktestRunCommand,
  PreparedBacktestRunCommand,
  ScheduledPreparedBacktestRunCommand,
  CollectionPreparationFrozenView,
  PreparationFrozenView,
} from "../api/generated";
import { isResearchInput } from "../api/researchValues";
import { createBacktestApi, type BacktestApi } from "../api/backtests";
import {
  isBoardLotQuantity,
  isLotKey,
  isRateText,
  isSlippageBpsText,
  normalizeRfc4122Uuid,
} from "../api/backtestValues";
import { isCalendarDate } from "../api/shanghaiTime";
import { ApiClientError } from "../api/transport";
import { useAutomaticBacktestData } from "./useAutomaticBacktestData";

export type BacktestRunSubmissionState =
  | "IDLE"
  | "SUBMITTING"
  | "ACCEPTED"
  | "CONFLICT"
  | "UNCERTAIN"
  | "FAILED";
export type BacktestReferenceMarketCoverageState =
  | "IDLE"
  | "LOADING"
  | "READY"
  | "FAILED";

export type BacktestRunDraftField =
  | "researchInputJson"
  | "buySlippageBps"
  | "commissionRate"
  | "datasetHash"
  | "eventRiskAssumption"
  | "initialCashFen"
  | "minimumCommissionFen"
  | "planVersionId"
  | "sellSlippageBps"
  | "stampDutyRate"
  | "transferFeeRate";
type PreparedRunDraftField = "endDate" | "responseMode" | "responseDelaySeconds" | "buySlippageFen" | "sellSlippageFen";
export type RunDraftField = BacktestRunDraftField | PreparedRunDraftField;

export type BacktestInitialLotDraftField =
  | "acquiredTradeDate"
  | "bucket"
  | "costBasisFen"
  | "lotKey"
  | "quantity";

export interface BacktestInitialLotDraft {
  readonly acquiredTradeDate: string;
  readonly bucket: "CORE" | "TACTICAL";
  readonly costBasisFen: string;
  readonly draftId: string;
  readonly lotKey: string;
  readonly quantity: string;
}

export interface BacktestRunDraft {
  readonly endDate: string;
  readonly responseMode: "FOLLOW_REMINDERS" | "OBSERVE_ONLY";
  readonly responseDelaySeconds: string;
  readonly buySlippageFen: string;
  readonly sellSlippageFen: string;
  readonly researchInputJson: string;
  readonly buySlippageBps: string;
  readonly commissionRate: string;
  readonly datasetHash: string;
  readonly eventRiskAssumption: "NO_EVENT_RISK" | "MANUAL_EVENT_RISK";
  readonly initialCashFen: string;
  readonly initialLots: readonly BacktestInitialLotDraft[];
  readonly minimumCommissionFen: string;
  readonly planVersionId: string;
  readonly sellSlippageBps: string;
  readonly stampDutyRate: string;
  readonly transferFeeRate: string;
}

export type BacktestRunFormErrors = Readonly<Record<string, string>>;
export type PreparedRunSnapshot = PreparationFrozenView | DeepReadonly<PreparationFrozenView> | CollectionPreparationFrozenView | DeepReadonly<CollectionPreparationFrozenView>;

export interface UseBacktestRunFormOptions {
  readonly prepared?: () => PreparedRunSnapshot | null;
  readonly preparedMode?: () => boolean;
  readonly api?: BacktestApi;
  readonly createIdempotencyKey?: () => string;
  readonly onAccepted: (receipt: BacktestJobReceipt) => Promise<unknown> | unknown;
}

interface SubmissionIntent {
  readonly command: BacktestRunCommand | PreparedBacktestRunCommand | ScheduledPreparedBacktestRunCommand;
  readonly key: string;
}

const DATASET_HASH_PATTERN = /^[0-9a-f]{64}$/;
const NONNEGATIVE_INTEGER_PATTERN = /^(?:0|[1-9][0-9]*)$/;
const MAX_SAFE_INTEGER_BIGINT = BigInt(Number.MAX_SAFE_INTEGER);
const MAX_SAFE_INTEGER_TEXT = String(Number.MAX_SAFE_INTEGER);
const MAX_INITIAL_LOTS = 200;

function defaultIdempotencyKey(): string {
  return globalThis.crypto.randomUUID();
}

function emptyDraft(): BacktestRunDraft {
  return Object.freeze({
    endDate: "",
    responseMode: "FOLLOW_REMINDERS",
    responseDelaySeconds: "0",
    buySlippageFen: "0",
    sellSlippageFen: "0",
    researchInputJson: "",
    buySlippageBps: "",
    commissionRate: "",
    datasetHash: "",
    eventRiskAssumption: "NO_EVENT_RISK",
    initialCashFen: "",
    initialLots: Object.freeze([]),
    minimumCommissionFen: "",
    planVersionId: "",
    sellSlippageBps: "",
    stampDutyRate: "",
    transferFeeRate: "",
  });
}

function safeIntegerDraft(value: string, positive: boolean): number | null {
  if (
    value.length === 0 ||
    value.length > MAX_SAFE_INTEGER_TEXT.length ||
    !NONNEGATIVE_INTEGER_PATTERN.test(value) ||
    (value.length === MAX_SAFE_INTEGER_TEXT.length && value > MAX_SAFE_INTEGER_TEXT)
  ) {
    return null;
  }
  const parsed = BigInt(value);
  if (parsed > MAX_SAFE_INTEGER_BIGINT || (positive && parsed === 0n)) return null;
  return Number(parsed);
}

function deepFreeze<Value>(value: Value): Value {
  if (typeof value !== "object" || value === null || Object.isFrozen(value)) return value;
  for (const child of Object.values(value)) deepFreeze(child);
  return Object.freeze(value);
}

function sortedLots(lots: BacktestInitialLotInput[]): BacktestInitialLotInput[] {
  return lots.sort((left, right) => {
    const leftKey = `${left.bucket}\0${left.acquiredTradeDate}\0${left.lotKey}`;
    const rightKey = `${right.bucket}\0${right.acquiredTradeDate}\0${right.lotKey}`;
    return leftKey < rightKey ? -1 : leftKey > rightKey ? 1 : 0;
  });
}

export function useBacktestRunForm(options: UseBacktestRunFormOptions) {
  const api = options.api ?? createBacktestApi();
  const createIdempotencyKey = options.createIdempotencyKey ?? defaultIdempotencyKey;
  const automaticData = useAutomaticBacktestData({ api, createIdempotencyKey });
  let dataReadyIntent: SubmissionIntent | null = null;
  const draft = shallowRef<BacktestRunDraft>(emptyDraft());
  const errors = shallowRef<BacktestRunFormErrors>(Object.freeze({}));
  const errorRevision = shallowRef(0);
  const submissionState = shallowRef<BacktestRunSubmissionState>("IDLE");
  const submissionErrorMessage = shallowRef<string | null>(null);
  const acceptedReceipt = shallowRef<BacktestJobReceipt | null>(null);
  const referenceMarketCoverage = shallowRef<BacktestReferenceMarketCoverageView | null>(null);
  const referenceMarketCoverageState = shallowRef<BacktestReferenceMarketCoverageState>("IDLE");
  const referenceMarketCoverageError = shallowRef<string | null>(null);

  let lotSequence = 0;
  let mounted = false;
  let submissionController: AbortController | null = null;
  let submissionIntent: SubmissionIntent | null = null;
  let coverageController: AbortController | null = null;
  let coverageGeneration = 0;

  function clearReferenceMarketCoverage(): void {
    coverageGeneration += 1;
    coverageController?.abort();
    coverageController = null;
    referenceMarketCoverage.value = null;
    referenceMarketCoverageError.value = null;
    referenceMarketCoverageState.value = "IDLE";
  }

  async function loadReferenceMarketCoverage(): Promise<void> {
    const planVersionId = normalizeRfc4122Uuid(draft.value.planVersionId);
    const datasetHash = draft.value.datasetHash;
    clearReferenceMarketCoverage();
    if (!mounted || planVersionId === null || !DATASET_HASH_PATTERN.test(datasetHash)) return;
    const requestGeneration = coverageGeneration;
    const controller = new AbortController();
    coverageController = controller;
    referenceMarketCoverageState.value = "LOADING";
    try {
      const response = await api.getReferenceMarketCoverage(datasetHash, planVersionId, {
        signal: controller.signal,
      });
      if (
        !mounted ||
        controller.signal.aborted ||
        requestGeneration !== coverageGeneration
      ) {
        return;
      }
      referenceMarketCoverage.value = deepFreeze(structuredClone(response));
      referenceMarketCoverageState.value = "READY";
    } catch {
      if (
        !mounted ||
        controller.signal.aborted ||
        requestGeneration !== coverageGeneration
      ) {
        return;
      }
      referenceMarketCoverageError.value = "参考指数覆盖暂不可用；提交仍由服务端重新校验";
      referenceMarketCoverageState.value = "FAILED";
    } finally {
      if (coverageController === controller) coverageController = null;
    }
  }

  function clearErrors(): void {
    if (Object.keys(errors.value).length > 0) errors.value = Object.freeze({});
  }

  function abandonSettledIntent(): void {
    if (submissionState.value === "SUBMITTING") return;
    submissionIntent = null;
    acceptedReceipt.value = null;
    submissionState.value = "IDLE";
    submissionErrorMessage.value = null;
  }

  function updateField(field: RunDraftField, value: string): void {
    if (
      submissionState.value === "SUBMITTING" ||
      submissionState.value === "UNCERTAIN" ||
      submissionState.value === "ACCEPTED"
    ) {
      return;
    }
    const normalizedValue =
      field === "eventRiskAssumption"
        ? value === "MANUAL_EVENT_RISK"
          ? "MANUAL_EVENT_RISK"
          : "NO_EVENT_RISK"
        : field === "responseMode" ? value === "OBSERVE_ONLY" ? "OBSERVE_ONLY" : "FOLLOW_REMINDERS" : value;
    if (draft.value[field] === normalizedValue) return;
    draft.value = Object.freeze({ ...draft.value, [field]: normalizedValue });
    clearErrors();
    abandonSettledIntent();
  }

  function addLot(): void {
    if (
      submissionState.value === "SUBMITTING" ||
      submissionState.value === "UNCERTAIN" ||
      submissionState.value === "ACCEPTED" ||
      draft.value.initialLots.length >= MAX_INITIAL_LOTS
    ) {
      return;
    }
    lotSequence += 1;
    const lot: BacktestInitialLotDraft = Object.freeze({
      acquiredTradeDate: "",
      bucket: "CORE",
      costBasisFen: "",
      draftId: `lot-${lotSequence}`,
      lotKey: "",
      quantity: "",
    });
    draft.value = Object.freeze({
      ...draft.value,
      initialLots: Object.freeze([...draft.value.initialLots, lot]),
    });
    clearErrors();
    abandonSettledIntent();
  }

  function removeLot(draftId: string): void {
    if (
      submissionState.value === "SUBMITTING" ||
      submissionState.value === "UNCERTAIN" ||
      submissionState.value === "ACCEPTED"
    ) {
      return;
    }
    const initialLots = draft.value.initialLots.filter((lot) => lot.draftId !== draftId);
    if (initialLots.length === draft.value.initialLots.length) return;
    draft.value = Object.freeze({ ...draft.value, initialLots: Object.freeze(initialLots) });
    clearErrors();
    abandonSettledIntent();
  }

  function updateLot(
    draftId: string,
    field: BacktestInitialLotDraftField,
    value: string,
  ): void {
    if (
      submissionState.value === "SUBMITTING" ||
      submissionState.value === "UNCERTAIN" ||
      submissionState.value === "ACCEPTED"
    ) {
      return;
    }
    let changed = false;
    const initialLots = draft.value.initialLots.map((lot) => {
      if (lot.draftId !== draftId) return lot;
      const normalizedValue =
        field === "bucket" ? (value === "TACTICAL" ? "TACTICAL" : "CORE") : value;
      if (lot[field] === normalizedValue) return lot;
      changed = true;
      return Object.freeze({ ...lot, [field]: normalizedValue });
    });
    if (!changed) return;
    draft.value = Object.freeze({ ...draft.value, initialLots: Object.freeze(initialLots) });
    clearErrors();
    abandonSettledIntent();
  }

  function validateDraft(): BacktestRunCommand | null {
    const nextErrors: Record<string, string> = {};
    const current = draft.value;
    const planVersionId = normalizeRfc4122Uuid(current.planVersionId);
    if (planVersionId === null) {
      nextErrors.planVersionId = "计划版本 ID 必须是 RFC 4122 UUID";
    }
    if (!DATASET_HASH_PATTERN.test(current.datasetHash)) {
      nextErrors.datasetHash = "数据集哈希必须是 64 位小写 SHA-256";
    }
    const initialCashFen = safeIntegerDraft(current.initialCashFen, true);
    if (initialCashFen === null) {
      nextErrors.initialCashFen = "初始现金必须是 1 至 9007199254740991 的整数分";
    }
    if (!isRateText(current.commissionRate)) {
      nextErrors.commissionRate = "佣金率必须是 0 到 1 的规范十进制字符串";
    }
    const minimumCommissionFen = safeIntegerDraft(current.minimumCommissionFen, false);
    if (minimumCommissionFen === null) {
      nextErrors.minimumCommissionFen = "最低佣金必须是安全范围内的非负整数分";
    }
    if (!isRateText(current.stampDutyRate)) {
      nextErrors.stampDutyRate = "印花税率必须是 0 到 1 的规范十进制字符串";
    }
    if (!isRateText(current.transferFeeRate)) {
      nextErrors.transferFeeRate = "过户费率必须是 0 到 1 的规范十进制字符串";
    }
    if (!isSlippageBpsText(current.buySlippageBps)) {
      nextErrors.buySlippageBps = "买入滑点必须是 0 到 10000 之间的规范十进制基点";
    }
    if (!isSlippageBpsText(current.sellSlippageBps)) {
      nextErrors.sellSlippageBps = "卖出滑点必须是 0 到 10000 之间的规范十进制基点";
    }
    if (current.initialLots.length > MAX_INITIAL_LOTS) {
      nextErrors.initialLots = "初始持仓最多 200 个 lot";
    }

    const lots: BacktestInitialLotInput[] = [];
    const lotKeyCounts = new Map<string, number>();
    let totalCostBasisFen = 0n;
    for (const lot of current.initialLots) {
      const prefix = `initialLots.${lot.draftId}`;
      if (!isLotKey(lot.lotKey)) {
        nextErrors[`${prefix}.lotKey`] = "lotKey 必须是 1 至 64 位安全标识";
      } else {
        lotKeyCounts.set(lot.lotKey, (lotKeyCounts.get(lot.lotKey) ?? 0) + 1);
      }
      if (!isCalendarDate(lot.acquiredTradeDate)) {
        nextErrors[`${prefix}.acquiredTradeDate`] = "取得交易日必须是有效 YYYY-MM-DD";
      }
      const quantity = safeIntegerDraft(lot.quantity, true);
      if (quantity === null || !isBoardLotQuantity(quantity)) {
        nextErrors[`${prefix}.quantity`] = "数量必须是安全正整数且为 100 股整数倍";
      }
      const costBasisFen = safeIntegerDraft(lot.costBasisFen, true);
      if (costBasisFen === null) {
        nextErrors[`${prefix}.costBasisFen`] = "剩余总成本必须是安全正整数分";
      } else {
        totalCostBasisFen += BigInt(costBasisFen);
      }
      if (
        isLotKey(lot.lotKey) &&
        isCalendarDate(lot.acquiredTradeDate) &&
        quantity !== null &&
        isBoardLotQuantity(quantity) &&
        costBasisFen !== null
      ) {
        lots.push({
          acquiredTradeDate: lot.acquiredTradeDate,
          bucket: lot.bucket,
          costBasisFen,
          lotKey: lot.lotKey,
          quantity,
        });
      }
    }
    for (const lot of current.initialLots) {
      if ((lotKeyCounts.get(lot.lotKey) ?? 0) > 1) {
        nextErrors[`initialLots.${lot.draftId}.lotKey`] = "lotKey 不得重复";
      }
    }
    if (
      initialCashFen !== null &&
      BigInt(initialCashFen) + totalCostBasisFen > MAX_SAFE_INTEGER_BIGINT
    ) {
      nextErrors.initialCashFen = "初始现金与 lot 剩余总成本之和不得超过安全整数上限";
    }

    let researchInput: BacktestRunCommand["researchInput"];
    if (current.researchInputJson.trim()) {
      try {
        const parsed: unknown = JSON.parse(current.researchInputJson);
        if (!isResearchInput(parsed)) throw new Error("invalid research input");
        researchInput = parsed;
      } catch {
        nextErrors.researchInputJson = "请填写完整的研究输入 JSON；服务端将核验审核绑定与证据。";
      }
    }
    errors.value = Object.freeze(nextErrors);
    if (
      Object.keys(nextErrors).length > 0 ||
      planVersionId === null ||
      initialCashFen === null ||
      minimumCommissionFen === null
    ) {
      errorRevision.value += 1;
      return null;
    }
    return deepFreeze({
      ...(researchInput === undefined ? {} : { researchInput }),
      datasetHash: current.datasetHash,
      eventRiskAssumption: current.eventRiskAssumption,
      executionConfig: {
        buySlippageBps: current.buySlippageBps,
        commissionRate: current.commissionRate,
        minimumCommissionFen,
        sellSlippageBps: current.sellSlippageBps,
        stampDutyRate: current.stampDutyRate,
        transferFeeRate: current.transferFeeRate,
      },
      initialCashFen,
      initialLots: sortedLots(lots),
      planVersionId,
    });
  }

  function validatePreparedDraft(): PreparedBacktestRunCommand | ScheduledPreparedBacktestRunCommand | null {
    const prepared = options.prepared?.() ?? null;
    const current = draft.value;
    const nextErrors: Record<string, string> = {};
    if (prepared === null) nextErrors.preparation = "请先完成当前原文的审核，使用已冻结计划";
    for (const field of ["commissionRate", "stampDutyRate", "transferFeeRate"] as const) {
      if (!isRateText(current[field])) nextErrors[field] = "请输入 0 到 1 的精确费率";
    }
    const minimumCommissionFen = safeIntegerDraft(current.minimumCommissionFen, false);
    const buySlippageFen = safeIntegerDraft(current.buySlippageFen, false);
    const sellSlippageFen = safeIntegerDraft(current.sellSlippageFen, false);
    const responseDelaySeconds = safeIntegerDraft(current.responseDelaySeconds, false);
    for (const [field, value] of Object.entries({ minimumCommissionFen, buySlippageFen,
      sellSlippageFen, responseDelaySeconds })) {
      if (value === null) nextErrors[field] = "请输入范围内的非负整数";
    }
    if (current.endDate !== "" && !isCalendarDate(current.endDate)) {
      nextErrors.endDate = "请输入有效的结束日期，或留空使用服务端默认值";
    }
    errors.value = Object.freeze(nextErrors);
    if (Object.keys(nextErrors).length || prepared === null || minimumCommissionFen === null ||
        buySlippageFen === null || sellSlippageFen === null || responseDelaySeconds === null) {
      errorRevision.value += 1;
      return null;
    }
    return deepFreeze({
      ...("schemaVersion" in prepared && prepared.schemaVersion === "prepared-loop-plan-v2" ? { schemaVersion: "prepared-loop-plan-v2" as const } : {}),
      preparationId: prepared.preparationId, manifestHash: prepared.manifestHash,
      response: { mode: current.responseMode, responseDelaySeconds },
      costs: { commissionRate: current.commissionRate, minimumCommissionFen,
        stampDutyRate: current.stampDutyRate, transferFeeRate: current.transferFeeRate,
        buySlippageFen, sellSlippageFen },
      ...(current.endDate === "" ? {} : { endDate: current.endDate }),
    });
  }

  async function performSubmission(intent: SubmissionIntent): Promise<void> {
    const controller = new AbortController();
    submissionController = controller;
    submissionIntent = intent;
    submissionState.value = "SUBMITTING";
    submissionErrorMessage.value = null;
    let receipt: BacktestJobReceipt;
    try {
      if ("preparationId" in intent.command && dataReadyIntent !== intent) {
        await automaticData.prepare(intent.command);
        if (!mounted || controller.signal.aborted || submissionIntent !== intent) return;
        dataReadyIntent = intent;
      }
      const response = await api.submitRun(intent.command, intent.key, {
        signal: controller.signal,
      });
      if (!mounted || controller.signal.aborted || submissionIntent !== intent) return;
      receipt = response.body;
    } catch (error) {
      if (!mounted || controller.signal.aborted || submissionIntent !== intent) return;
      if (
        error instanceof ApiClientError &&
        (error.code === "NETWORK_ERROR" || error.code === "INVALID_RESPONSE" || error.code === "SERVICE_UNAVAILABLE")
      ) {
        submissionState.value = "UNCERTAIN";
        submissionErrorMessage.value = "提交结果尚未确认，请使用同一请求安全重试";
      } else if (error instanceof ApiClientError && error.code === "CONFLICT") {
        submissionIntent = null;
        submissionState.value = "CONFLICT";
        submissionErrorMessage.value = "提交与服务端已有意图冲突，请检查输入后重新发起";
      } else {
        submissionIntent = null;
        submissionState.value = "FAILED";
        submissionErrorMessage.value = "preparationId" in intent.command && error instanceof Error && !(error instanceof ApiClientError)
          ? error.message : "回测提交未被服务端接受，请检查输入后重试";
      }
      return;
    } finally {
      if (submissionController === controller) submissionController = null;
    }
    if (!mounted || submissionIntent !== intent) return;
    acceptedReceipt.value = receipt;
    submissionIntent = null;
    submissionState.value = "ACCEPTED";
    try {
      await options.onAccepted(receipt);
    } catch {
      if (mounted) {
        submissionErrorMessage.value =
          "回测已由服务端接受，但无法打开结果页，请从运行历史查看";
      }
    }
  }

  function submit(): Promise<void> {
    if (
      submissionState.value === "SUBMITTING" ||
      submissionState.value === "UNCERTAIN" ||
      submissionState.value === "ACCEPTED"
    ) {
      return Promise.resolve();
    }
    const command = options.preparedMode?.() ? validatePreparedDraft() : validateDraft();
    if (command === null) return Promise.resolve();
    const intent: SubmissionIntent = Object.freeze({
      command,
      key: createIdempotencyKey(),
    });
    return performSubmission(intent);
  }

  function retrySubmission(): Promise<void> {
    return submissionState.value === "UNCERTAIN" && submissionIntent !== null
      ? performSubmission(submissionIntent)
      : Promise.resolve();
  }

  onMounted(() => {
    mounted = true;
  });

  watch(
    [() => draft.value.planVersionId, () => draft.value.datasetHash],
    () => {
      void loadReferenceMarketCoverage();
    },
  );

  onBeforeUnmount(() => {
    mounted = false;
    submissionController?.abort();
    submissionController = null;
    clearReferenceMarketCoverage();
  });

  return {
    automaticData,
    acceptedReceipt: readonly(acceptedReceipt),
    addLot,
    draft: readonly(draft),
    errorRevision: readonly(errorRevision),
    errors: readonly(errors),
    removeLot,
    referenceMarketCoverage: readonly(referenceMarketCoverage),
    referenceMarketCoverageError: readonly(referenceMarketCoverageError),
    referenceMarketCoverageState: readonly(referenceMarketCoverageState),
    retrySubmission,
    submissionErrorMessage: readonly(submissionErrorMessage),
    submissionState: readonly(submissionState),
    submit,
    updateField,
    updateLot,
  } as const;
}
