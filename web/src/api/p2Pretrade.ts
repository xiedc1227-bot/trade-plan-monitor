function record(v: unknown): v is Record<string, unknown> { return v !== null && typeof v === "object" && !Array.isArray(v); }
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
export function validP2Economics(v: unknown): boolean {
  if (!record(v) || v.version !== "p2-economics-v1" || !["NONE", "PASS", "FAIL", "UNKNOWN"].includes(String(v.outcome))) return false;
  if (!Array.isArray(v.blockers) || !v.blockers.every(b => typeof b === "string")) return false;
  return ["quantity", "entry_debit_fen", "net_reward_fen", "planned_loss_fen", "total_cost_fen", "spread_numerator", "spread_denominator", "target_proceeds_fen", "risk_proceeds_fen"]
    .every(k => v[k] == null || Number.isSafeInteger(v[k]));
}
export function validP2Preview(v: unknown): boolean {
  return record(v) && v.authorityGranted === false && typeof v.planVersionId === "string" && typeof v.ruleId === "string"
    && typeof v.computedAt === "string" && (v.quantity === null || Number.isSafeInteger(v.quantity) && Number(v.quantity) > 0 && Number(v.quantity) % 100 === 0)
    && validP2Economics(v.economics) && record(v.evidence) && v.evidence.rule_id === v.ruleId
    && v.evidence.version === "p2-pretrade-evidence-v1" && hash(v.evidence.content_hash) && hash(v.evidence.evidence_hash)
    && record(v.evidence.sizing) && record(v.evidence.policy);
}
