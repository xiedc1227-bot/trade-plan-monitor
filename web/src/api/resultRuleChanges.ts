import type { DeepReadonly } from "vue";
import type { BacktestRuleChangesView, BacktestScheduledRunView } from "./generated";
import { invalidResponse, requestJson } from "./transport";

export type RuleChangesLoader = (run: DeepReadonly<BacktestScheduledRunView>, index: number,
  signal: AbortSignal) => Promise<BacktestRuleChangesView>;
const record = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const exact = (v: Record<string, unknown>, keys: string[]) => Object.keys(v).length === keys.length && keys.every(k => Object.hasOwn(v, k));

export function createRuleChangesLoader(fetcher: typeof fetch = fetch): RuleChangesLoader {
  return async (run, index, signal) => {
    const version = run.versions[index];
    if (!version) throw invalidResponse(0);
    const { body, status } = await requestJson(fetcher,
      `/api/v1/backtest-runs/${encodeURIComponent(run.runId)}/rule-changes/${encodeURIComponent(version.sourceId)}`,
      { method: "GET", signal });
    const previous = run.versions[index - 1];
    if (status !== 200 || !record(body) || !exact(body, ["runId", "manifestHash", "sourceId", "versionId",
      "previousSourceId", "previousVersionId", "relationship", "changes"]) ||
      body.runId !== run.runId || body.manifestHash !== run.provenance.manifestHash ||
      body.sourceId !== version.sourceId || body.versionId !== version.versionId ||
      body.previousSourceId !== (previous?.sourceId ?? null) || body.previousVersionId !== (previous?.versionId ?? null) ||
      (index === 0 ? body.relationship !== "INITIAL" : !["INHERITED", "INDEPENDENT"].includes(String(body.relationship))) ||
      !Array.isArray(body.changes) || body.changes.length > 192 || !body.changes.every(change =>
        record(change) && exact(change, ["target", "rule_id", "action", "before", "after", "clause_ids"]) &&
        typeof change.target === "string" && change.target.length > 0 && change.target.length <= 64 &&
        (change.rule_id === null || typeof change.rule_id === "string") &&
        ["RETAIN", "MODIFY", "ADD", "REVOKE"].includes(String(change.action)) &&
        Array.isArray(change.clause_ids) && change.clause_ids.length <= 50 && change.clause_ids.every(c => typeof c === "string") &&
        (change.action === "ADD" ? change.before === null && change.after !== null :
          change.action === "REVOKE" ? change.before !== null && change.after === null : change.before !== null && change.after !== null)
      )) throw invalidResponse(status);
    return body as unknown as BacktestRuleChangesView;
  };
}
