import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type { PlanDraftCommand, PlanVersionView } from "../../src/api/generated";
import ExplicitPlanSupplementForm from "../../src/components/plans/ExplicitPlanSupplementForm.vue";

const plan: PlanVersionView = {
  canActivate: false,
  contentHash: "a".repeat(64),
  createdAt: "2026-09-13T10:00:00.000000+08:00",
  id: "00000000-0000-4000-8000-000000000201",
  mapping: {
    fieldBindings: [{
      bindingKind: "VALUE",
      clauseIds: ["clause-0000000000000001"],
      origin: "SOURCE",
      path: "rules[0].action.quantity",
      unit: "SHARES",
      value: 100,
    }],
    mappingVersion: "plan-mapping-v2",
    sourceClauses: [{
      clauseId: "clause-0000000000000001",
      disposition: "MAPPED",
      end: 6,
      excerpt: "买入100股",
      paths: ["rules[0].action.quantity"],
      start: 0,
    }],
    sourceProcessing: null,
    userSupplements: [],
  },
  planHash: "b".repeat(64),
  planId: "literal-source",
  planJson: JSON.stringify({
    activation: null,
    conflict_policy: null,
    rules: [
      { action: { quantity: 100 }, condition: { conditions: [{}, {}] }, repeat_policy: null },
      { repeat_policy: null },
      { repeat_policy: null },
    ],
  }),
  revision: 3,
  sourceHash: "c".repeat(64),
  sourceText: "003043.SZ 原文",
  status: "DRAFT",
  symbol: "003043.SZ",
  unresolvedReviewIssues: [{
    allowedResolutions: ["CONFIRM_POLICY"],
    code: "MISSING_POLICY",
    issueId: "issue-activation",
    path: "activation",
    reason: "missing activation policy",
  }],
  version: 1,
};

describe("ExplicitPlanSupplementForm", () => {
  it("creates a new durable user-supplement mapping instead of pretending policy came from source", async () => {
    const wrapper = mount(ExplicitPlanSupplementForm, { props: { plan } });
    const inputs = wrapper.findAll<HTMLInputElement>('form input:not([type="checkbox"])');
    expect(inputs).toHaveLength(2);
    const values = [
      "TRADING_DAY",
      "2026-09-14",
    ];
    for (const [index, value] of values.entries()) await inputs[index]?.setValue(value);

    expect(wrapper.get("form button").attributes("disabled")).toBeUndefined();
    await wrapper.get("form").trigger("submit");

    const command = wrapper.emitted("saveDraft")?.[0]?.[0] as PlanDraftCommand;
    expect(command.sourceText).toBe(plan.sourceText);
    expect(command.mapping?.userSupplements).toHaveLength(2);
    expect(command.mapping?.fieldBindings?.filter((item) => item.origin === "USER_SUPPLEMENT")).toHaveLength(2);
    const document = JSON.parse(command.planJson) as Record<string, unknown>;
    expect(document.activation).toEqual({ mode: "TRADING_DAY", trading_day: "2026-09-14" });
  });
});
