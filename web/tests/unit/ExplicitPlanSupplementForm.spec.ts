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
  it("keeps supplemented trading fields editable while excluding technical contracts", async () => {
    const mapping = structuredClone(plan.mapping!);
    mapping.fieldBindings![0] = {
      ...mapping.fieldBindings![0]!, origin: "USER_SUPPLEMENT", clauseIds: [], supplementId: "previous-quantity",
    };
    mapping.fieldBindings!.push({ path: "version", value: 2, unit: "NONE", origin: "CONTRACT", clauseIds: [] });
    const wrapper = mount(ExplicitPlanSupplementForm, {
      props: { plan: { ...plan, mapping, unresolvedReviewIssues: [] } },
    });
    expect(wrapper.findAll("option").map((option) => option.attributes("value"))).toContain("rules[0].action.quantity");
    expect(wrapper.findAll("option").map((option) => option.attributes("value"))).not.toContain("version");
    await wrapper.get("select").setValue("rules[0].action.quantity");
    await wrapper.get("input").setValue("200");
    await wrapper.get("form").trigger("submit");
    const command = wrapper.emitted("saveDraft")?.[0]?.[0] as PlanDraftCommand;
    expect(command.mapping?.fieldBindings).toContainEqual(expect.objectContaining({
      path: "rules[0].action.quantity", value: 200, origin: "USER_SUPPLEMENT",
    }));
    expect(command.mapping?.fieldBindings).toContainEqual(expect.objectContaining({
      path: "version", value: 2, origin: "CONTRACT",
    }));
  });

  it("edits ALL/ANY and its scalar binding together, preserves children, and supports changing back", async () => {
    const mapping = structuredClone(plan.mapping!);
    mapping.fieldBindings!.push(
      { path: "rules[0].condition", bindingKind: "STRUCTURE", value: "ALL", unit: "NONE", origin: "SOURCE", clauseIds: ["clause-0000000000000001"] },
      { path: "rules[0].condition.type", bindingKind: "VALUE", value: "ALL", unit: "NONE", origin: "SOURCE", clauseIds: ["clause-0000000000000001"] },
    );
    const document = JSON.parse(plan.planJson);
    document.rules[0].condition = { type: "ALL", conditions: [{ type: "COMPLETED_CLOSE_BELOW", price_fen: 950 }, { type: "COMPLETED_CLOSE_BELOW", price_fen: 960 }] };
    const wrapper = mount(ExplicitPlanSupplementForm, {
      props: { plan: { ...plan, mapping, planJson: JSON.stringify(document), unresolvedReviewIssues: [] } },
    });
    for (const [index, operator] of ["ANY", "ALL"].entries()) {
      await wrapper.get("select").setValue("rules[0].condition");
      await wrapper.get("input").setValue(operator);
      await wrapper.get("form").trigger("submit");
      const command = wrapper.emitted("saveDraft")?.[index]?.[0] as PlanDraftCommand;
      expect(JSON.parse(command.planJson).rules[0].condition).toEqual({ ...document.rules[0].condition, type: operator });
      expect(command.sourceText).toBe(plan.sourceText);
      expect(command.mapping?.sourceClauses).toEqual(plan.mapping?.sourceClauses);
      for (const path of ["rules[0].condition", "rules[0].condition.type"]) {
        const bindings = command.mapping?.fieldBindings?.filter((binding) => binding.path === path);
        expect(bindings).toHaveLength(1);
        expect(bindings![0]).toMatchObject({ value: operator, origin: "USER_SUPPLEMENT", clauseIds: [] });
        expect(command.mapping?.userSupplements).toContainEqual(expect.objectContaining({
          path, value: operator, supplementId: bindings![0]!.supplementId,
        }));
      }
      if (!command.mapping) throw new Error("Missing successor mapping");
      await wrapper.setProps({ plan: { ...plan, id: `successor-${index}`, planJson: command.planJson, mapping: command.mapping, unresolvedReviewIssues: [] } });
    }
    await wrapper.get("select").setValue("rules[0].condition");
    await wrapper.get("input").setValue("NOT");
    await wrapper.get("form").trigger("submit");
    expect(wrapper.emitted("saveDraft")).toHaveLength(2);
    expect(wrapper.get('[role="alert"]').text()).toContain("类型一致");
  });

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

  it("turns an edited source-mapped board-lot field into a reviewed user supplement", async () => {
    const wrapper = mount(ExplicitPlanSupplementForm, {
      props: { plan: { ...plan, unresolvedReviewIssues: [] } },
    });
    await wrapper.get("select").setValue("rules[0].action.quantity");
    await wrapper.get('input[aria-label="rules[0].action.quantity 新值"]').setValue("200");
    const form = wrapper.findAll("form")[0];
    expect(form?.get("button").attributes("disabled")).toBeUndefined();
    await form?.trigger("submit");

    const command = wrapper.emitted("saveDraft")?.[0]?.[0] as PlanDraftCommand;
    const document = JSON.parse(command.planJson) as { rules: Array<{ action?: { quantity?: number } }> };
    expect(document.rules[0]?.action?.quantity).toBe(200);
    expect(command.mapping?.fieldBindings).toContainEqual(expect.objectContaining({
      origin: "USER_SUPPLEMENT",
      path: "rules[0].action.quantity",
      unit: "SHARES",
      value: 200,
    }));
    expect(command.mapping?.fieldBindings).not.toContainEqual(expect.objectContaining({
      origin: "SOURCE",
      path: "rules[0].action.quantity",
    }));
  });
});
