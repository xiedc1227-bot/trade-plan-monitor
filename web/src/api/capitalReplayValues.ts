import type { CapitalReplayProgram, PreparedBacktestRunCommand } from "./generated";
import { exceptionProgram, exceptionProvenance } from "./exceptionReplayValues";
import { isShanghaiDateTime } from "./shanghaiTime";

const record = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const hash = (v: unknown) => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);
const safe = (v: unknown) => Number.isSafeInteger(v) && Number(v) >= 0;

export function preparedReplayRecords(v: unknown): v is Pick<PreparedBacktestRunCommand, "capitalProgram" | "exceptionProgram"> {
  return record(v) && Object.keys(v).every(k => ["capitalProgram", "exceptionProgram"].includes(k)) &&
    (v.capitalProgram === undefined || capitalProgram(v.capitalProgram)) &&
    (v.exceptionProgram === undefined || exceptionProgram(v.exceptionProgram));
}

/** Transport bounds only; exact lot bindings, self hashes and authority are server-owned. */
export function capitalProgram(v: unknown): v is CapitalReplayProgram {
  return record(v) && Object.keys(v).every(k => ["schema_version", "opening_events"].includes(k)) &&
    (v.schema_version === undefined || v.schema_version === "capital-replay-program-v1") &&
    (v.opening_events === undefined || Array.isArray(v.opening_events) && v.opening_events.length <= 10000 && v.opening_events.every(e =>
      record(e) && e.schema_version === "capital-opening-event-v1" && hash(e.plan_hash) && hash(e.envelope_hash) &&
      typeof e.source_event_id === "string" && e.source_event_id.length > 0 && e.source_event_id.length <= 128 &&
      typeof e.symbol === "string" && exceptionProvenance(e.provenance) && e.confirmed === true &&
      [e.observed_at, e.received_at, e.available_at].every(isShanghaiDateTime) && safe(e.order) && Number(e.order) <= 10000 &&
      [e.source, e.excerpt, e.reason].every(v => typeof v === "string" && v.length > 0) &&
      (e.provenance === "RECORDED_LOCAL" ? record(e.recorded_event) : e.recorded_event === null) &&
      Array.isArray(e.lots) && e.lots.length <= 500 && e.lots.every(l => record(l) &&
        (l.bucket === "CORE" || l.bucket === "TACTICAL") && safe(l.quantity) && Number(l.quantity) > 0 && Number(l.quantity) % 100 === 0 &&
        safe(l.retained_basis_fen) && (l.source_lot_id === null || typeof l.source_lot_id === "string") && record(l.reference) &&
        (l.reference.kind === "OPENING" ? typeof l.reference.lot_key === "string" && l.reference.lot_key.length > 0
          : l.reference.kind === "BUY_SIGNAL" && hash(l.reference.signal_id)))));
}

export function capitalOutcomes(v: unknown): boolean {
  return Array.isArray(v) && v.length <= 10000 && v.every(e => record(e) &&
    e.schema_version === "capital-replay-outcome-v1" && hash(e.envelope_hash) &&
    typeof e.source_event_id === "string" && exceptionProvenance(e.provenance) && isShanghaiDateTime(e.at) &&
    Array.isArray(e.blockers) && e.blockers.length <= 10 && e.blockers.every(v => typeof v === "string") &&
    (e.status === "APPLIED" ? e.blockers.length === 0 && hash(e.private_event_hash)
      : e.status === "BLOCKED" && e.blockers.length > 0 && e.private_event_hash === null));
}
