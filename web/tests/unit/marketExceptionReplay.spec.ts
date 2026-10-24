import { readFileSync } from "node:fs";
import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import { createBacktestApi } from "../../src/api/backtests";
import type { PreparedBacktestRunCommand } from "../../src/api/generated";
import { validLoopRun } from "../../src/api/monitorLoopValues";
import { validReviewCandidate } from "../../src/api/preparationReview";
import { createPreparationApi } from "../../src/api/preparations";
import MonitorLoopSummary from "../../src/components/backtests/MonitorLoopSummary.vue";

const preparation = () => JSON.parse(readFileSync("tests/fixtures/plan-preparation-review.json", "utf8")).candidate;
const run = () => JSON.parse(readFileSync("tests/fixtures/monitor-loop-results.json", "utf8")).run;
function linked(value: Record<string, unknown>, schema: number) {
  value.schema_version = schema;
  value.execution_version = schema === 7 ? "condition-plan-v3" : "condition-plan-v2";
  value.reference_market = { selection: "AUTO_BOARD", mapping_version: "board-index-map-v1", index_code: "000001.SH" };
}
describe("exception replay transport and provenance", () => {
  it("sends the exact explicit loop program and rejects unsupported programs before sending", async () => {
    const fetcher = vi.fn<typeof fetch>().mockRejectedValue(new TypeError("offline fixture"));
    const api = createBacktestApi(fetcher);
    const command: PreparedBacktestRunCommand = {preparationId: "reviewed-1", manifestHash: "a".repeat(64),
      response: {mode: "FOLLOW_REMINDERS"}, costs: {commissionRate: "0", minimumCommissionFen: 0,
        stampDutyRate: "0", transferFeeRate: "0", buySlippageFen: 0, sellSlippageFen: 0},
      exceptionProgram: {schema_version: "exception-replay-program-v1", exception_authorization_events: [], operations: []}};
    await expect(api.submitRun(command, "explicit-run-1")).rejects.toBeDefined();
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(JSON.parse(String(fetcher.mock.calls[0]![1]!.body)).exceptionProgram).toEqual(command.exceptionProgram);
    fetcher.mockClear();
    await expect(api.submitRun({...command, exceptionProgram: {
      ...command.exceptionProgram, schema_version: "unsupported" as never}}, "invalid-run-1")).rejects.toBeDefined();
    expect(fetcher).not.toHaveBeenCalled();
  });
  it.each([6, 7])("preserves explicit schema %s in preparation and result readers", async schema => {
    const value = preparation(); linked(value.candidate.draft, schema);
    expect(validReviewCandidate(value.candidate, value.source.text)).toBe(true);
    const api = createPreparationApi(async () => new Response(JSON.stringify(value), { headers: {
      "Cache-Control": "no-store", "Location": `/api/v1/backtest-preparations/${value.preparationId}`,
    } }));
    expect((await api.get(value.preparationId)).body).toMatchObject({ candidate: { kind: "EXTRACTION" } });
    const result = run(); linked(result.frozenPlan.snapshot, schema);
    expect(validLoopRun(result)).toBe(true);
    result.frozenPlan.snapshot.execution_version = "condition-plan-v99";
    expect(validLoopRun(result)).toBe(false);
  });
  it("shows hypothetical, recorded and absent authority without converting labels into approval", () => {
    const value = run(); linked(value.frozenPlan.snapshot, 7);
    value.report.exception_outcomes = []; value.report.exception_requests = [];
    for (const [sources, expected] of [[[], "未提供例外授权"], [["RESEARCH_SCENARIO"], "研究假设"], [["RECORDED_LOCAL"], "已记录的本地授权事件"]] as const) {
      value.report.exception_provenance = [...sources];
      expect(validLoopRun(value)).toBe(true);
      const wrapper = mount(MonitorLoopSummary, { props: { run: value } });
      expect(wrapper.text()).toContain(expected);
      expect(wrapper.text()).toContain("批准本身不产生模拟成交");
      expect(wrapper.findAll("button").some(button => button.text().includes("批准"))).toBe(false);
      wrapper.unmount();
    }
    value.report.exception_provenance = ["INFERRED_APPROVAL"];
    expect(validLoopRun(value)).toBe(false);
  });
});
