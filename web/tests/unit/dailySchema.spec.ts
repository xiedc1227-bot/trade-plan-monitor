import { describe, expect, it } from "vitest";
import { initialValue, resolveSchema, schemaChoices } from "../../src/components/daily/schema";

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
