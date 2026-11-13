import type { DailyFactCommand, DailyFactConditionSelection, PlanVersionView } from "../../api/generated";

export interface ReviewedFactChoice {
  readonly key: string;
  readonly requirement: string;
  readonly kind: DailyFactCommand["kind"];
  readonly selection: Readonly<DailyFactConditionSelection>;
}
const kinds = ["PRICE_STRUCTURE", "VOLUME_OR_CANDLE", "TECHNICAL", "TRADE_VIABILITY",
  "SEVERE_STRUCTURE", "SEVERE_DETERIORATION"] as const;
function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/** Display choices only; the existing registration endpoint authenticates the leaf. */
export function reviewedFactChoices(version: PlanVersionView): readonly ReviewedFactChoice[] {
  if (!version.contentHash || !/^[a-f0-9]{64}$/.test(version.contentHash) ||
      !version.planJson || version.planJson.length > 262_144) return [];
  try {
    const plan: unknown = JSON.parse(version.planJson);
    if (!object(plan) || plan.schema_version !== 5 || plan.execution_mode !== "CONDITION_PLAN" ||
        !Array.isArray(plan.ordinary_rules) || plan.ordinary_rules.length > 2) return [];
    const choices: ReviewedFactChoice[] = [], owners = new Set<string>();
    let leaves = 0;
    function walk(node: unknown, ownerId: string, path: string, depth: number) {
      if (!object(node) || depth > 4) throw new Error("Invalid native condition tree");
      if (node.type === "ALL" || node.type === "ANY") {
        if (!Array.isArray(node.conditions) || !node.conditions.length) throw new Error("Invalid native group");
        node.conditions.forEach((child, index) => walk(child, ownerId, `${path}.conditions[${index}]`, depth + 1));
        return;
      }
      if (++leaves > 50) throw new Error("Native condition limit exceeded");
      const kind = kinds.find(value => value === node.fact_kind);
      if (node.type !== "REVIEWED_FACT" || node.validity_scope !== "TRADE_DATE" || !kind ||
          typeof node.evidence_requirement !== "string" || !node.evidence_requirement.trim()) return;
      choices.push(Object.freeze({ key: JSON.stringify([version.id, version.contentHash, ownerId, path]),
        requirement: node.evidence_requirement, kind,
        selection: Object.freeze({ ownerKind: "ORDINARY_RULE", ownerId, conditionPath: path }) }));
    }
    for (const rule of plan.ordinary_rules) {
      if (!object(rule) || rule.status !== "ENABLED") continue;
      if (typeof rule.rule_id !== "string" || !rule.rule_id || owners.has(rule.rule_id)) return [];
      owners.add(rule.rule_id); walk(rule.condition, rule.rule_id, "condition", 1);
    }
    return Object.freeze(choices);
  } catch { return []; }
}
