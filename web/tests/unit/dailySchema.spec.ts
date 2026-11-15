import { describe, expect, it } from "vitest";
import { initialValue, resolveSchema, schemaChoices, fieldLabels, choiceLabels } from "../../src/components/plans/planSchema";

describe("daily candidate structured editor", () => {
  it("never fills numeric strategy parameters or endpoints while creating a condition", () => {
    expect(initialValue({ type: "object", properties: { type: { const: "VOLUME_RATIO" },
      threshold: { type: "number", default: 0.8 }, includeLow: { type: "boolean", default: true } } }))
      .toEqual({ type: "VOLUME_RATIO", threshold: null, includeLow: null });
  });
  it("resolves the closed server schema without using source text as executable content", () => {
    expect(resolveSchema({ $ref: "#/$defs/Condition" }, { Condition: { type: "object" } }).type).toBe("object");
  });
  it("exposes discriminated condition choices nested inside a nullable candidate field", () => {
    expect(schemaChoices({ anyOf: [{ oneOf: [{ $ref: "#/$defs/Reviewed" }, { $ref: "#/$defs/All" }] }, { type: "null" }] },
      { Reviewed: { title: "Reviewed", type: "object" }, All: { title: "All", type: "object" } }).map(s => s.title))
      .toEqual(["Reviewed", "All"]);
  });
});

it("labels the persistent BUY guard and keeps explicit timestamp inputs unresolved", () => {
  expect(fieldLabels.buy_suspension).toBe("本计划持续禁买保护");
  expect(choiceLabels.BuySuspensionDraftDefinition).toBe("完整5分钟收盘触发持续禁买");
  expect(initialValue({ type: "object", properties: { effective_from: { type: "string", format: "date-time" } } })).toEqual({ effective_from: null });
});
