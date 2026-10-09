import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";
import type { PreparationView } from "../../src/api/generated-runtime-status";
import { createPreparationApi } from "../../src/api/preparations";
import { buildPreparationReview, inspectPreparationReview, validReviewCandidate } from "../../src/api/preparationReview";

const fixture = JSON.parse(readFileSync("tests/fixtures/plan-preparation-review.json", "utf8")) as {
  candidate: PreparationView; reviewed: PreparationView; choices: { path: string; reason: string }[];
};
const evidence = "逐项核对原文、完整规则、期初实际账户及可用时间，明确确认当前候选。";
const fresh = () => structuredClone(fixture.candidate);
function receipt(body = fixture.reviewed) {
  return new Response(JSON.stringify(body), { headers: {
    Location: `/api/v1/backtest-preparations/${body.preparationId}`, "Cache-Control": "no-store",
  } });
}

describe("exact single preparation review", () => {
  it("accepts real backend extraction and frozen projections with exact original spans", () => {
    expect(validReviewCandidate(fixture.candidate.candidate, fixture.candidate.source.text)).toBe(true);
    expect(validReviewCandidate(fixture.reviewed.candidate, fixture.reviewed.source.text)).toBe(true);
    expect(inspectPreparationReview(fixture.candidate).blockers).toEqual([]);
    expect(inspectPreparationReview(fixture.candidate).supplements.map(item => item.path)).toEqual(fixture.choices.map(item => item.path));
  });
  it("requires explicit supplements for every displayed unbound value without changing the candidate", () => {
    const original = JSON.stringify(fixture.candidate);
    expect(() => buildPreparationReview(fixture.candidate, evidence, [], true)).toThrow();
    const command = buildPreparationReview(fixture.candidate, evidence, fixture.choices, true);
    expect(command.review).toMatchObject({ confirmed: true, expected_revision: fixture.candidate.revision,
      expected_source_revision: fixture.candidate.sourceRevision, expected_candidate_revision: fixture.candidate.candidateRevision,
      candidate_hash: fixture.candidate.candidate!.candidateHash, evidence_hash: fixture.candidate.candidate!.evidenceHash });
    expect(command.review.mapping!.supplements).toHaveLength(fixture.choices.length);
    expect(command.review.mapping!.supplements[0]).toMatchObject({ path: "activation.mode", value: "MANUAL",
      candidate_content_hash: command.review.mapping!.candidate_content_hash });
    expect(JSON.stringify(fixture.candidate)).toBe(original);
    expect(command.review.account).toBeUndefined();
    expect(command.review.draft).toBeUndefined();
  });
  it.each([[], [{ path: "constructor", reason: evidence }], [...fixture.choices, fixture.choices[0]!],
    fixture.choices.map((item, i) => i === 0 ? { ...item, reason: " " } : item)].map(choices => ({ choices })))("rejects absent, orphan, duplicate or blank choices: %o", ({ choices }) => {
    expect(() => buildPreparationReview(fixture.candidate, evidence, choices, true)).toThrow();
  });
  it.each(["", " ", "x".repeat(2001)])("rejects invalid general review evidence", value => {
    expect(() => buildPreparationReview(fixture.candidate, value, fixture.choices, true)).toThrow();
  });
  it("preserves unknown cash separately from zero and requires an explicit unknown acknowledgement", () => {
    const value = fresh();
    if (value.candidate?.kind !== "EXTRACTION") throw new Error("fixture variant");
    value.candidate.openingAccount.cash_fen = null;
    value.candidate.issues.push("LOOP_ACCOUNT_FACT_REQUIRED: opening_account.cash_fen");
    expect(inspectPreparationReview(value).unknownFacts).toContain("opening_account.cash_fen");
    expect(() => buildPreparationReview(value, evidence, fixture.choices, false)).toThrow();
    expect(buildPreparationReview(value, evidence, fixture.choices, true).review.account).toBeUndefined();
    value.candidate.openingAccount.cash_fen = { value: 0, start: 0, end: 1, excerpt: value.source.text[0]! };
    value.candidate.issues = value.candidate.issues.filter(issue => !issue.includes("cash_fen"));
    expect(inspectPreparationReview(value).unknownFacts).not.toContain("opening_account.cash_fen");
  });
  it("blocks missing chronology, missing technical parameters and unresolved source clauses", () => {
    const time = fresh(); time.source.available_at = null;
    expect(inspectPreparationReview(time).blockers.length).toBeGreaterThan(0);
    const parameter = fresh();
    if (parameter.candidate?.kind !== "EXTRACTION") throw new Error("fixture variant");
    parameter.candidate.issues.push("DAILY_SOURCE_BINDING_REQUIRED: ordinary_rules[0].quantity");
    parameter.candidate.draft.ordinary_rules[0]!.quantity = null;
    expect(inspectPreparationReview(parameter).blockers.length).toBeGreaterThan(0);
    const clause = fresh();
    if (clause.candidate?.kind !== "EXTRACTION") throw new Error("fixture variant");
    clause.candidate.mapping.clauses[0]!.disposition = "UNRESOLVED";
    expect(inspectPreparationReview(clause).blockers.length).toBeGreaterThan(0);
  });
  it("rejects malformed evidence rather than rendering trusted account facts", () => {
    const value = fresh();
    if (value.candidate?.kind !== "EXTRACTION") throw new Error("fixture variant");
    value.candidate.openingAccount.lots[0]!.unit_cost_yuan!.excerpt = "伪造成本";
    expect(validReviewCandidate(value.candidate, value.source.text)).toBe(false);
  });
  it("sends the generated review contract with its immutable revision and request key", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(receipt());
    const command = buildPreparationReview(fixture.candidate, evidence, fixture.choices, true);
    const result = await createPreparationApi(fetcher).review(fixture.candidate.preparationId, command, "review-one");
    expect(result.body).toEqual(fixture.reviewed);
    expect(fetcher.mock.calls[0]![0]).toBe(`/api/v1/backtest-preparations/${fixture.candidate.preparationId}/reviews`);
    const init = fetcher.mock.calls[0]![1]!;
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("Idempotency-Key")).toBe("review-one");
    expect(JSON.parse(String(init.body))).toEqual(command);
  });
  it("rejects forged confirmation and unsafe revisions before network access", async () => {
    const fetcher = vi.fn<typeof fetch>();
    const command = buildPreparationReview(fixture.candidate, evidence, fixture.choices, true);
    const malformed = { review: { ...command.review, expected_revision: Number.MAX_SAFE_INTEGER + 1 } };
    await expect(createPreparationApi(fetcher).review(fixture.candidate.preparationId, malformed, "review-one")).rejects.toMatchObject({ code: "VALIDATION_ERROR" });
    expect(fetcher).not.toHaveBeenCalled();
  });
});
