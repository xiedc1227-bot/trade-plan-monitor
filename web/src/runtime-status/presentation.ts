import type { RuntimeStatusView } from "../api/generated-runtime-status";

export function displayTime(value: string | null): string {
  return value === null ? "—" : value.slice(0, 19).replace("T", " ");
}

const reasons: Readonly<Record<string, string>> = {
  NO_ACTIVE_PLANS: "没有活动计划", AWAITING_FIRST_EVALUATION: "等待首次求值", COVERAGE_INCOMPLETE: "所需数据覆盖未完整",
  NEEDS_RESTART: "配置已变化，需要安全停止后重新启动", LEGACY_PLANS_REQUIRE_REVIEW: "旧计划需要人工核对",
  COORDINATOR_STALLED: "协调器进展已逾期", CREDENTIAL_MISSING: "提供方凭证尚未配置",
};
export function reasonLabel(reason: string | null): string {
  return reason === null ? "—" : reasons[reason] ?? reason;
}
export const modeLabels: Record<RuntimeStatusView["mode"], string> = {
  MONITORING: "监控中", STANDBY: "待机", RECOVERING: "正在恢复所需数据", DEGRADED: "部分范围受影响", BLOCKED: "监控受阻",
};
