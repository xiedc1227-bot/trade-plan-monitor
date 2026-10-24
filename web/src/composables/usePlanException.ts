import { computed, shallowRef, watch, type Ref } from "vue";
import type { ExceptionCandidateResource, ExceptionDecisionApiCommand, ExceptionPreviewApiCommand, ExceptionPreviewApiView, ExceptionReceiptApiView, ExceptionRevocationApiCommand } from "../api/generated";

export type ExceptionRequest = <T>(url: string, body?: object, key?: string) => Promise<T>;
export function usePlanException(resource: Ref<ExceptionCandidateResource>, authorityRevision: Ref<number>, current: Ref<boolean>, request: ExceptionRequest, refresh: () => void) {
  const proposed = shallowRef<string | number>("");
  const reason = shallowRef("");
  const preview = shallowRef<ExceptionPreviewApiView | null>(null);
  const receipt = shallowRef<ExceptionReceiptApiView | null>(null);
  const busy = shallowRef(false), error = shallowRef(""), notice = shallowRef("");
  const commands = new Map<string, string>();
  let generation = 0;
  const candidate = computed(() => receipt.value?.candidate ?? resource.value.candidate);
  const weak = computed(() => candidate.value.binding.route === "WEAK_MINIMUM");
  const blocked = computed(() => !current.value || Boolean(resource.value.blockers?.length));
  const enteredQuantity = computed(() => String(proposed.value).trim() === "" ? null : Number(proposed.value));
  const canPreview = computed(() => !busy.value && !blocked.value && candidate.value.state === "PENDING" &&
    (weak.value || enteredQuantity.value !== null && Number.isSafeInteger(enteredQuantity.value) && enteredQuantity.value > 0 && enteredQuantity.value % 100 === 0));
  const canDecide = computed(() => !busy.value && current.value && reason.value.trim().length > 0 && ["PENDING", "APPROVED"].includes(candidate.value.state));
  function clearPreview() { generation++; preview.value = null; notice.value = "当前输入或依据已变化，请重新生成预览。"; }
  watch(proposed, clearPreview);
  watch(() => [resource.value.candidate.projection_hash, resource.value.revision, authorityRevision.value, current.value], () => {
    clearPreview(); receipt.value = null;
  });
  watch(() => resource.value.candidate.candidate_id, () => { proposed.value = ""; reason.value = ""; commands.clear(); error.value = ""; });
  function commandKey(identity: string) {
    const key = commands.get(identity) ?? crypto.randomUUID(); commands.set(identity, key); return key;
  }
  async function generatePreview() {
    if (!canPreview.value) return;
    const command: ExceptionPreviewApiCommand = { candidateId: candidate.value.candidate_id, expectedRevision: resource.value.revision,
      proposedQuantity: weak.value ? null : enteredQuantity.value };
    const identity = `preview:${generation}:${JSON.stringify(command)}`, key = commandKey(identity), turn = generation;
    busy.value = true; error.value = ""; notice.value = "";
    try {
      const result = await request<ExceptionPreviewApiView>("/api/v1/plan-exception-previews", command, key);
      if (turn !== generation) return;
      if (result.candidateId !== candidate.value.candidate_id || result.bindingHash !== candidate.value.binding_hash || result.expectedRevision !== resource.value.revision
        || result.quantity !== (weak.value ? candidate.value.binding.minimum : enteredQuantity.value)) throw new Error("预览与当前候选不一致，请刷新状态。");
      preview.value = result;
      commands.delete(identity);
    } catch (cause) { if (turn === generation) { preview.value = null; error.value = cause instanceof Error ? cause.message : "预览暂不可用，请刷新后重试。"; } }
    finally { busy.value = false; }
  }
  async function decide(action: "APPROVE" | "REJECT" | "REVOKE") {
    if (!canDecide.value || action === "APPROVE" && (!preview.value || blocked.value) ||
      action === "REVOKE" && candidate.value.state !== "APPROVED" || action !== "REVOKE" && candidate.value.state !== "PENDING") return;
    const command = action === "REVOKE"
      ? { approvalId: candidate.value.approval_id!, expectedRevision: receipt.value?.revision ?? resource.value.revision, reason: reason.value.trim() }
      : { candidateId: candidate.value.candidate_id, expectedRevision: resource.value.revision, decision: action, reason: reason.value.trim(),
        ...(action === "APPROVE" ? { previewId: preview.value!.previewId, previewHash: preview.value!.previewHash } : {}) };
    const key = commandKey(`${action}:${JSON.stringify(command)}`);
    const body: ExceptionDecisionApiCommand | ExceptionRevocationApiCommand = { ...command, commandId: key };
    const turn = generation;
    busy.value = true; error.value = ""; notice.value = "";
    try {
      const result = await request<ExceptionReceiptApiView>(action === "REVOKE" ? "/api/v1/plan-exception-revocations" : "/api/v1/plan-exception-decisions", body, key);
      if (turn !== generation) { refresh(); return; }
      if (result.candidate.candidate_id !== candidate.value.candidate_id) throw new Error("回执与当前候选不一致，请刷新状态。");
      receipt.value = result; preview.value = null;
      notice.value = action === "APPROVE" ? "已批准并冻结整笔数量。尚未执行模拟交易，请在执行日单独确认。" : action === "REJECT" ? "已拒绝，本次机会不能重新批准。" : "已撤销，本次机会不能重新批准。";
      refresh();
    } catch (cause) { error.value = cause instanceof Error ? cause.message : "服务暂不可用，可重试原命令或刷新当前状态。"; }
    finally { busy.value = false; }
  }
  return { proposed, reason, preview, busy, error, notice, candidate, weak, blocked, canPreview, canDecide, generatePreview, decide };
}
