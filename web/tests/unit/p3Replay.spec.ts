import { describe, expect, it } from "vitest";
import { capitalOutcomes, capitalProgram } from "../../src/api/capitalReplayValues";
import { exceptionProgram, frozenExceptionEvents } from "../../src/api/exceptionReplayValues";
import { isResearchInput } from "../../src/api/researchValues";

const at = "2026-10-26T10:00:00+08:00";
const hash = "a".repeat(64);
const opening = () => ({ schema_version: "capital-opening-event-v1", plan_hash: hash, envelope_hash: hash,
  source_event_id: "explicit-source", symbol: "601021.SH", provenance: "RESEARCH_SCENARIO", confirmed: true,
  observed_at: at, received_at: at, available_at: at, order: 0, source: "Synthetic declaration",
  excerpt: "Explicit400shares and450001fen", reason: "Reviewed scenario", recorded_event: null,
  lots: [{ bucket: "TACTICAL", quantity: 400, retained_basis_fen: 450001, source_lot_id: null,
    reference: { kind: "OPENING", lot_key: "opening-lot" } }] });

describe("P3 frozen capital transport", () => {
  it("requires explicit v3 budget input and preserves old exception envelopes", () => {
    const value = { schema_version: "unified-research-input-v3", started_at: at, inventory_known: true,
      review: { confirmed: true, content_hash: hash, reviewed_at: at, evidence: "Explicit review" },
      exception_authorization_events: [], capital_program: { opening_events: [opening()] } };
    expect(isResearchInput(value)).toBe(true);
    expect(isResearchInput({ ...value, capital_program: undefined })).toBe(false);
    const event = { schema_version: "capital-exception-event-v1", provenance: "RESEARCH_SCENARIO",
      plan_hash: hash, envelope_hash: hash, order: 1, event: {}, candidate: {}, decision: {} };
    expect(frozenExceptionEvents([event])).toBe(false);
    expect(exceptionProgram({ schema_version: "capital-exception-program-v1", exception_authorization_events: [event] })).toBe(true);
  });
  it.each([-1, true, 9007199254740992, "450001"])("rejects unsafe or inferred cost %s", cost => {
    const event = opening();
    expect(capitalProgram({ opening_events: [{ ...event, lots: [{ ...event.lots[0], retained_basis_fen: cost }] }] })).toBe(false);
  });
  it("keeps blocked outcomes distinct from applied receipts", () => {
    const value = { schema_version: "capital-replay-outcome-v1", envelope_hash: hash,
      source_event_id: "explicit-source", provenance: "RESEARCH_SCENARIO", at,
      status: "APPLIED", blockers: [], private_event_hash: hash };
    expect(capitalOutcomes([value])).toBe(true);
    expect(capitalOutcomes([{ ...value, private_event_hash: null }])).toBe(false);
    expect(capitalOutcomes([{ ...value, status: "BLOCKED", blockers: ["CAPITAL_LOTS_CHANGED"], private_event_hash: null }])).toBe(true);
  });
});
