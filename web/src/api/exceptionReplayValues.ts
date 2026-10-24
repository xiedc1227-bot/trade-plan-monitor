import { isShanghaiDateTime } from "./shanghaiTime";
import type { ExceptionReplayProgram } from "./generated";

const record = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const hash = (v: unknown) => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);
export const exceptionProvenance = (v: unknown) => v === "RECORDED_LOCAL" || v === "RESEARCH_SCENARIO";

/** Bounded transport validation; evidence hashes and authority are checked on the server. */
export function exceptionOutcomes(v: unknown): boolean {
  return Array.isArray(v) && v.length <= 10000 && v.every(item => record(item) &&
    item.schema_version === "exception-replay-outcome-v1" && hash(item.envelope_hash) && hash(item.source_event_id) &&
    hash(item.candidate_id) && (item.private_event_id === null || hash(item.private_event_id)) && isShanghaiDateTime(item.at) &&
    exceptionProvenance(item.provenance) && ["APPLIED", "BLOCKED", "VERIFIED"].includes(String(item.status)) &&
    Array.isArray(item.blockers) && item.blockers.length <= 20 && item.blockers.every(v => typeof v === "string") &&
    (item.status === "BLOCKED" ? item.blockers.length > 0 && item.private_event_id === null : item.blockers.length === 0 && hash(item.private_event_id)));
}

export function frozenExceptionEvents(v: unknown): boolean {
  return Array.isArray(v) && v.length <= 10000 && v.every(item => record(item) &&
    item.schema_version === "frozen-exception-event-v1" && exceptionProvenance(item.provenance) &&
    hash(item.plan_hash) && hash(item.envelope_hash) && Number.isSafeInteger(item.order) && Number(item.order) >= 0 &&
    record(item.event) && record(item.candidate) && record(item.decision));
}

export function exceptionProgram(v: unknown): v is ExceptionReplayProgram {
  return record(v) && Object.keys(v).every(k => ["schema_version", "exception_authorization_events", "operations"].includes(k)) &&
    (v.schema_version === undefined || v.schema_version === "exception-replay-program-v1") &&
    frozenExceptionEvents(v.exception_authorization_events ?? []) &&
    (v.operations === undefined || Array.isArray(v.operations) && v.operations.length <= 10000 && v.operations.every(o => record(o) &&
      o.kind === "SIMULATE" && typeof o.operation_id === "string" && isShanghaiDateTime(o.at) &&
      Number.isSafeInteger(o.order) && Number(o.order) >= 0 && typeof o.rule_id === "string" &&
      Number.isSafeInteger(o.occurrence) && Number(o.occurrence) >= 1 && o.risk_kind == null &&
      Number.isSafeInteger(o.quantity) && Number(o.quantity) > 0 && Number(o.quantity) % 100 === 0));
}
