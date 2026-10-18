import { flushPromises, mount } from "@vue/test-utils";
import { expect, it, vi } from "vitest";
import ResultRuleChanges from "../../src/components/backtests/ResultRuleChanges.vue";
import type { BacktestRuleChangesView, BacktestScheduledRunView } from "../../src/api/generated";
import { createRuleChangesLoader } from "../../src/api/resultRuleChanges";
import { resultValue } from "../../src/components/backtests/ruleChangeFormatting";

const version = { sourceId: "source-1", versionId: "version-1", effectiveTradeDate: "2026-09-24" };
const run = { runId: "a".repeat(64), provenance: { manifestHash: "b".repeat(64) },
  versions: [version, { ...version, sourceId: "source-2", versionId: "version-2", effectiveTradeDate: "2026-09-28" }],
} as BacktestScheduledRunView;
const comparison: BacktestRuleChangesView = { runId: run.runId, manifestHash: run.provenance.manifestHash,
  sourceId: "source-2", versionId: "version-2", previousSourceId: "source-1", previousVersionId: "version-1",
  relationship: "INHERITED", changes: [
    { target: "position", rule_id: null, action: "MODIFY", before: { max_qty: 300 }, after: { max_qty: 500 }, clause_ids: [] },
    { target: "levels", rule_id: null, action: "MODIFY", before: { risk_line_fen: 2599 }, after: { risk_line_fen: null }, clause_ids: [] },
    { target: "alert_rules", rule_id: "keep", action: "RETAIN", before: { reason: "<script>unsafe</script>" }, after: { reason: "<script>unsafe</script>" }, clause_ids: [] },
    { target: "ordinary_rules", rule_id: "buy", action: "ADD", before: null, after: { quantity: 100 }, clause_ids: [] },
    { target: "risk_branches", rule_id: "ORDINARY_TECHNICAL", action: "REVOKE", before: { target_core_qty: 0 }, after: null, clause_ids: [] },
  ] };

it("loads one frozen comparison on request and shows all outcomes and complete before/after values", async () => {
  const load = vi.fn().mockResolvedValue(comparison);
  const wrapper = mount(ResultRuleChanges, { props: { run, load } });
  expect(load).not.toHaveBeenCalled();
  expect(wrapper.text()).toContain("第 2 份");
  await wrapper.get('[data-testid="load-rule-changes-2"]').trigger("click"); await flushPromises();
  const text = wrapper.text();
  for (const expected of ["保留（1）", "修改（2）", "新增（1）", "取消（1）", "上一份", "本份", "300", "500", "25.99 元", "source-1"]) expect(text).toContain(expected);
  expect(text).not.toContain("统一审核");
  expect(wrapper.find("script").exists()).toBe(false);
  wrapper.unmount();
});

it("offers an explicit retry and rejects stale responses after switching runs", async () => {
  let finish!: (value: BacktestRuleChangesView) => void;
  const load = vi.fn().mockRejectedValueOnce(new Error("private error"))
    .mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  const wrapper = mount(ResultRuleChanges, { props: { run, load } });
  await wrapper.get('[data-testid="load-rule-changes-2"]').trigger("click"); await flushPromises();
  expect(wrapper.text()).toContain("重新读取"); expect(wrapper.text()).not.toContain("private error");
  await wrapper.get('[data-testid="load-rule-changes-2"]').trigger("click");
  await wrapper.setProps({ run: { ...run, runId: "c".repeat(64) } });
  finish(comparison); await flushPromises();
  expect(wrapper.text()).not.toContain("修改（2）");
  wrapper.unmount();
});

it("labels independent legacy versions without claiming reviewed inheritance", async () => {
  const load = vi.fn().mockResolvedValue({ ...comparison, relationship: "INDEPENDENT" });
  const wrapper = mount(ResultRuleChanges, { props: { run, load } });
  await wrapper.get('[data-testid="load-rule-changes-2"]').trigger("click"); await flushPromises();
  expect(wrapper.text()).toContain("不表示它关联了上一份审核记录");
  expect(wrapper.text()).not.toContain("已关联上一份已审核计划");
  expect(wrapper.text()).toContain("修改（2）");
  wrapper.unmount();
});

it("binds the response to the requested run, source, predecessor and manifest", async () => {
  for (const changed of [{ runId: "d".repeat(64) }, { manifestHash: "e".repeat(64) },
    { previousSourceId: null }, { previousVersionId: "wrong" }, { versionId: "wrong" }, { relationship: "INITIAL" }]) {
    const load = createRuleChangesLoader(vi.fn().mockResolvedValue(new Response(JSON.stringify({ ...comparison, ...changed }))));
    await expect(load(run, 1, new AbortController().signal)).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  }
  const load = createRuleChangesLoader(vi.fn().mockResolvedValue(new Response(JSON.stringify(comparison))));
  expect(await load(run, 1, new AbortController().signal)).toEqual(comparison);
});

it("formats fixed reference values as yuan without converting non-price counts", () => {
  expect(resultValue("2599", "reference.value", { "reference.unit": "FEN" })).toBe("25.99 元");
  expect(resultValue(100, "quantity", {})).toBe("100");
  expect(resultValue(null, "reference.value", { "reference.unit": "FEN" })).toBe("未设置");
});

it("accepts complete scoped-risk comparisons while rejecting oversized responses", async () => {
  const changes = Array.from({ length: 65 }, (_, index) => ({ ...comparison.changes[0]!, rule_id: `risk-${index}` }));
  const body = { ...comparison, changes };
  const load = createRuleChangesLoader(vi.fn().mockResolvedValue(new Response(JSON.stringify(body))));
  expect((await load(run, 1, new AbortController().signal)).changes).toHaveLength(65);
  const oversized = { ...comparison, changes: Array.from({ length: 193 }, () => comparison.changes[0]) };
  const reject = createRuleChangesLoader(vi.fn().mockResolvedValue(new Response(JSON.stringify(oversized))));
  await expect(reject(run, 1, new AbortController().signal)).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
});

it("shows that narrowing the old stop keeps old holdings protected and excludes new entries", async () => {
  const scoped = { ...comparison, changes: [
    { target: "levels", rule_id: null, action: "RETAIN" as const, before: { risk_line_fen: 2599 },
      after: { risk_line_fen: 2599 }, clause_ids: [] },
    { target: "risk_branches", rule_id: "ORDINARY_TECHNICAL", action: "MODIFY" as const,
      before: { kind: "ORDINARY_TECHNICAL", target_core_qty: 0, target_tactical_qty: 0 },
      after: { kind: "ORDINARY_TECHNICAL", target_core_qty: 0, target_tactical_qty: 0,
        holding_scope: { mode: "BEFORE_TRADE_DATE", trade_date: "2026-10-09" },
        evidence_mode: "TWO_OFFICIAL_CLOSES" }, clause_ids: [] },
  ] };
  const wrapper = mount(ResultRuleChanges, { props: { run, load: vi.fn().mockResolvedValue(scoped) } });
  await wrapper.get('[data-testid="load-rule-changes-2"]').trigger("click"); await flushPromises();
  expect(wrapper.text()).toContain("旧仓保护继续保留");
  expect(wrapper.text()).toContain("2026-10-09 起买入的新仓不适用此规则");
  expect(wrapper.text()).toContain("本份未明确新仓止损");
  expect(wrapper.text()).toContain("25.99 元");
  expect(wrapper.text()).not.toContain("系统表达能力限制");
  wrapper.unmount();
});
