import { readFileSync } from "node:fs";
import { afterEach, expect, it, vi } from "vitest";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import type { PlanChange, ReviewedPlanLibraryItem, UnifiedPlanDraft } from "../../src/api/generated-runtime-status";
import ReviewedPlanDetails from "../../src/components/backtests/ReviewedPlanDetails.vue";

const fixture = JSON.parse(readFileSync("tests/fixtures/plan-preparation-review.json", "utf8")) as { candidate: { candidate: { draft: UnifiedPlanDraft } } };
const draft = fixture.candidate.candidate.draft;
const entry: ReviewedPlanLibraryItem = { preparationId: "reviewed-update", manifestHash: "a".repeat(64),
  sourceId: "second-source", name: "测试股票", symbol: "002240.SZ", effectiveTradeDate: "2026-09-28",
  reviewedAt: "2026-10-17T11:00:00+08:00", reviewedBase: { preparation_id: "first", manifest_hash: "b".repeat(64) } };
const changes: PlanChange[] = [
  { action: "MODIFY", target: "levels", rule_id: "private-risk", before: { risk_line_fen: 2500 }, after: { risk_line_fen: 2599 }, clause_ids: [] },
  { action: "ADD", target: "ordinary_rules", rule_id: "private-buy", before: null, after: { quantity: 200 }, clause_ids: [] },
  { action: "REVOKE", target: "ordinary_rules", rule_id: "private-sell", before: { quantity: 100 }, after: null, clause_ids: [] },
  { action: "RETAIN", target: "position", rule_id: null, before: { max_qty: 1000 }, after: { max_qty: 1000 }, clause_ids: [] },
];
const wrappers: VueWrapper[] = [];
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); });
function setup(item = entry) {
  const version = { sourceId: item.sourceId, sourceRevision: 2, candidateRevision: 3,
    effectiveTradeDate: item.effectiveTradeDate, evidenceHash: "c".repeat(64), planHash: "d".repeat(64) };
  const candidateHash = "9".repeat(64), evidenceHash = item.reviewedBase ? version.evidenceHash : "e".repeat(64);
  const detail = { sourceId: item.sourceId, effectiveTradeDate: item.effectiveTradeDate, sourceRevision: 2, candidateRevision: 3,
    candidateHash, evidenceHash, baseHash: item.reviewedBase?.manifest_hash ?? null,
    candidate: { candidateHash, evidenceHash, validation: "VALID", issues: [] as string[], kind: item.reviewedBase ? "MATERIALIZED" : "INITIAL",
      draft, review: item.reviewedBase ? { draft, changes } : null } };
  const { candidate: _candidate, ...summary } = detail;
  const body = { preparationId: item.preparationId, workflow: "SINGLE", status: "REVIEWED", revision: 7,
    frozen: { manifestHash: item.manifestHash, versions: [version] },
    items: [{ ...summary, sourceId: "previous-source" }, summary] };
  const page = { preparationId: item.preparationId, revision: 7, items: [detail] };
  const api = { get: vi.fn().mockResolvedValue({ body }), items: vi.fn().mockResolvedValue(page) };
  const wrapper = mount(ReviewedPlanDetails, { props: { item, predecessor: "前序：2026-09-24 · 测试股票（002240.SZ）", api } });
  wrappers.push(wrapper);
  async function open() { wrapper.get("details").element.open = true;
    await new Promise(done => setTimeout(done, 0)); await flushPromises(); }
  return { wrapper, api, body, detail, page, open };
}

it("loads only an expanded reviewed item using two reads and shows concrete retained, changed, added and cancelled conditions", async () => {
  const { wrapper, api, open } = setup();
  expect(api.get).not.toHaveBeenCalled(); expect(api.items).not.toHaveBeenCalled();
  await open();
  expect(api.get).toHaveBeenCalledWith(entry.preparationId, { signal: expect.any(AbortSignal) });
  expect(api.items).toHaveBeenCalledWith(entry.preparationId, { expectedRevision: 7, offset: 1, limit: 1 }, { signal: expect.any(AbortSignal) });
  expect(wrapper.text()).toContain("25.00 元 → 25.99 元");
  for (const title of ["保留（1）", "修改（1）", "新增（1）", "取消（1）"]) expect(wrapper.text()).toContain(title);
  expect(wrapper.text()).toContain("200"); expect(wrapper.text()).toContain("1000");
  expect(wrapper.text()).not.toContain("private-"); expect(wrapper.text()).not.toContain(entry.manifestHash);
  expect(wrapper.findAll("button")).toHaveLength(0); expect(wrapper.emitted()).toEqual({});
  await open(); expect(api.get).toHaveBeenCalledTimes(1); expect(api.items).toHaveBeenCalledTimes(1);
});

it("keeps an expanded verified view when refreshing metadata for the same exact plan", async () => {
  const value = setup(); await value.open();
  await value.wrapper.setProps({ item: { ...entry } }); await flushPromises();
  expect(value.wrapper.text()).toContain("25.00 元 → 25.99 元");
  expect(value.api.get).toHaveBeenCalledTimes(1);
});

it.each(["manifest", "plan", "source", "date", "revision", "evidence", "candidateRevision", "candidateHash", "base"])("rejects a mismatched %s without presenting another approved version", async kind => {
  const value = setup({ ...entry, identity: { sourceHash: "e".repeat(64), planHash: "d".repeat(64),
    reviewedVersionHash: "f".repeat(64), planVersionId: "internal-version" } });
  if (kind === "manifest") value.body.frozen.manifestHash = "f".repeat(64);
  if (kind === "plan") value.body.frozen.versions[0]!.planHash = "f".repeat(64);
  if (kind === "source") value.detail.sourceId = "another-source";
  if (kind === "date") value.body.frozen.versions[0]!.effectiveTradeDate = "2026-10-09";
  if (kind === "revision") value.page.revision++;
  if (kind === "evidence") value.detail.candidate.evidenceHash = "f".repeat(64);
  if (kind === "candidateRevision") value.detail.candidateRevision++;
  if (kind === "candidateHash") value.detail.candidateHash = "f".repeat(64);
  if (kind === "base") value.detail.baseHash = "f".repeat(64);
  await value.open();
  expect(value.wrapper.get('[role="alert"]').text()).toContain("暂时无法核对");
  expect(value.wrapper.find('[data-testid="plan-rule-changes"]').exists()).toBe(false);
});

it("retries a failed read and never exposes raw server errors or changes the selected endpoint", async () => {
  const value = setup(); value.api.get.mockRejectedValueOnce(new Error("private-server-id"));
  await value.open(); expect(value.wrapper.text()).not.toContain("private-server-id");
  await value.wrapper.get("button").trigger("click"); await flushPromises();
  expect(value.wrapper.text()).toContain("25.99 元");
  expect(value.api.get).toHaveBeenCalledTimes(2); expect(value.api.items).toHaveBeenCalledTimes(1);
  expect(value.wrapper.emitted("update")).toBeUndefined(); expect(value.wrapper.emitted("compose")).toBeUndefined();
});

it("discards a late response after switching the inspected item and aborts its read", async () => {
  const value = setup(); let resolve!: (result: { body: typeof value.body }) => void;
  value.api.get.mockReturnValueOnce(new Promise(done => { resolve = done; }));
  await value.open(); const signal = value.api.get.mock.calls[0]![1].signal as AbortSignal;
  value.api.get.mockReturnValueOnce(new Promise(() => {}));
  await value.wrapper.setProps({ item: { ...entry, preparationId: "another-plan", manifestHash: "f".repeat(64) } });
  expect(signal.aborted).toBe(true); resolve({ body: value.body }); await flushPromises();
  expect(value.api.get).toHaveBeenCalledTimes(2);
  expect(value.api.get.mock.calls[1]![0]).toBe("another-plan");
  expect(value.wrapper.find('[data-testid="plan-rule-changes"]').exists()).toBe(false);
  expect(value.wrapper.find('[role="alert"]').exists()).toBe(false);
});

it("shows an already reviewed initial plan whose account was confirmed separately", async () => {
  const value = setup({ ...entry, reviewedBase: null });
  value.detail.candidate.validation = "UNRESOLVED";
  value.detail.candidate.issues = ["LOOP_ACCOUNT_FACT_REQUIRED: opening_account.cash_fen"];
  await value.open();
  expect(value.wrapper.text()).toContain("本次建立的交易条件");
  expect(value.wrapper.find('[role="alert"]').exists()).toBe(false);
});

it.each([{ issues: [] }, { issues: ["RULE_SCOPE_UNRESOLVED"] },
  { issues: ["LOOP_ACCOUNT_FACT_REQUIRED: opening_account.cash_fen", "RULE_SCOPE_UNRESOLVED"] }])("rejects an initial candidate with other unresolved issues: $issues", async ({ issues }) => {
  const value = setup({ ...entry, reviewedBase: null });
  value.detail.candidate.validation = "UNRESOLVED"; value.detail.candidate.issues = issues;
  await value.open();
  expect(value.wrapper.find('[role="alert"]').exists()).toBe(true);
  expect(value.wrapper.find('[data-testid="plan-rule-changes"]').exists()).toBe(false);
});

it("shows the initial approved conditions and keeps older missing change evidence explicit", async () => {
  const first = setup({ ...entry, reviewedBase: null }); await first.open();
  expect(first.wrapper.text()).toContain("本次建立的交易条件");
  const old = setup(); old.detail.candidate.review!.changes = []; await old.open();
  expect(old.wrapper.text()).toContain("未记录逐项变化");
  expect(old.wrapper.text()).not.toContain("无此类变更");
  expect(old.wrapper.get("a").attributes()).toMatchObject({ href: `/backtests/new?preparationId=${entry.preparationId}&inspect=1`, target: "_blank", rel: "noopener" });
});
