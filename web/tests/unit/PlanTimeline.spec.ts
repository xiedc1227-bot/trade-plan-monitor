import { afterEach, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import type { ReviewedPlanLibraryItem } from "../../src/api/generated-runtime-status";
import type { PlanLibraryApi } from "../../src/api/planLibrary";
import { planTimelinePath, planTimelineGroups } from "../../src/components/backtests/planLibraryPresentation";
import { usePlanLibrary } from "../../src/composables/usePlanLibrary";
import ReviewedPlanLibrary from "../../src/components/backtests/ReviewedPlanLibrary.vue";

export function timelineEntries(): ReviewedPlanLibraryItem[] {
  return ["a", "b"].flatMap(chain => [0, 1, 2, 3].map(index => ({
    preparationId: `${chain}-${index}`, manifestHash: (chain + index).repeat(32), sourceId: `source-${index}`,
    symbol: "002240.SZ", name: "测试股票", effectiveTradeDate: ["2026-09-24", "2026-09-28", "2026-09-30", "2026-10-09"][index]!,
    reviewedAt: `2026-10-17T${chain === "a" ? "02" : "11"}:48:03+08:00`,
    reviewedBase: index ? { preparation_id: `${chain}-${index - 1}`, manifest_hash: (chain + (index - 1)).repeat(32) } : null,
  })));
}

it("derives two full paths for eight records without mutating, merging or selecting them", () => {
  const items = timelineEntries(); const original = JSON.stringify(items);
  const groups = planTimelineGroups(items);
  expect(groups).toHaveLength(2);
  expect(groups.map(group => group.paths.map(path => path.endpoint.preparationId))).toEqual([["a-3"], ["b-3"]]);
  expect(planTimelinePath(items, "b-3").items.map(item => item.preparationId)).toEqual(["b-0", "b-1", "b-2", "b-3"]);
  expect(JSON.stringify(items)).toBe(original);
});

it("keeps forked endpoints explicit and never unions their updates", () => {
  const items = timelineEntries().slice(0, 4);
  items.push({ ...items[2]!, preparationId: "fork", manifestHash: "f".repeat(64) });
  const group = planTimelineGroups(items)[0]!;
  expect(group.paths.map(path => path.endpoint.preparationId).sort()).toEqual(["a-3", "fork"]);
  expect(planTimelinePath(items, "fork").items.map(item => item.preparationId)).toEqual(["a-0", "a-1", "fork"]);
});

it("rejects timelines beyond the existing 256-plan limit without truncating", () => {
  const base = timelineEntries()[0]!;
  const items = Array.from({ length: 257 }, (_, index) => ({ ...base, preparationId: `p-${index}`, sourceId: `s-${index}`,
    effectiveTradeDate: new Date(Date.UTC(2025, 0, index + 1)).toISOString().slice(0, 10),
    reviewedBase: index ? { preparation_id: `p-${index - 1}`, manifest_hash: base.manifestHash } : null }));
  expect(planTimelinePath(items, "p-255").items).toHaveLength(256);
  expect(planTimelinePath(items, "p-256").error).toContain("256");
  expect(planTimelinePath(items, "p-256").items).toEqual([]);
});

it.each(["missing", "hash", "cycle", "stock", "date", "source"])("rejects a %s path instead of silently replaying a prefix", kind => {
  const items = timelineEntries().slice(0, 4);
  if (kind === "missing") items.splice(1, 1);
  if (kind === "hash") items[2]!.reviewedBase!.manifest_hash = "f".repeat(64);
  if (kind === "cycle") items[0]!.reviewedBase = { preparation_id: "a-3", manifest_hash: items[3]!.manifestHash };
  if (kind === "stock") items[1]!.symbol = "600000.SH";
  if (kind === "date") items[1]!.effectiveTradeDate = items[0]!.effectiveTradeDate;
  if (kind === "source") items[1]!.sourceId = items[0]!.sourceId;
  const path = planTimelinePath(items, "a-3");
  expect(path.error).toBeTruthy(); expect(path.items).toEqual([]);
});

const wrappers: VueWrapper[] = [];
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks(); });
function setup() {
  const items = timelineEntries();
  const api: PlanLibraryApi = { list: vi.fn().mockResolvedValue({ items, offset: 0, limit: 100, total: 8 }), compose: vi.fn() };
  let state!: ReturnType<typeof usePlanLibrary>;
  wrappers.push(mount(defineComponent({ setup() { state = usePlanLibrary(api); return () => h("div"); } })));
  return { items, api, get state() { return state; } };
}

it("opens a timeline without writes then freezes precisely the selected entire path once", async () => {
  const { state, api } = setup(); await flushPromises();
  expect(state.endpointId.value).toBe("");
  state.chooseEndpoint("b-3"); expect(api.compose).not.toHaveBeenCalled();
  vi.mocked(api.compose).mockResolvedValue({ preparationId: "frozen-run", manifestHash: "f".repeat(64) } as never);
  const first = await state.compose(); const second = await state.compose();
  expect(first).toBe(second); expect(api.compose).toHaveBeenCalledTimes(1);
  expect(vi.mocked(api.compose).mock.calls[0]![0].plans).toEqual(timelineEntries().slice(4).map(item => ({ preparation_id: item.preparationId, manifest_hash: item.manifestHash })));
});

it("retains an uncertain exact path and cannot switch it while retrying", async () => {
  const { state, api } = setup(); await flushPromises(); state.chooseEndpoint("a-3");
  vi.mocked(api.compose).mockRejectedValue(new Error("lost receipt"));
  await state.compose(); const first = vi.mocked(api.compose).mock.calls[0]!;
  state.chooseEndpoint("b-3"); expect(state.endpointId.value).toBe("a-3");
  await state.compose(); expect(vi.mocked(api.compose).mock.calls[1]!.slice(0, 2)).toEqual(first.slice(0, 2));
});

it("does not advance an explicitly chosen endpoint when refresh finds a newer update", async () => {
  const { state, api, items } = setup(); await flushPromises(); state.chooseEndpoint("a-3");
  const next = { ...items[3]!, preparationId: "a-4", manifestHash: "e".repeat(64), sourceId: "source-4", effectiveTradeDate: "2026-10-12",
    reviewedBase: { preparation_id: "a-3", manifest_hash: items[3]!.manifestHash } };
  vi.mocked(api.list).mockResolvedValue({ items: [...items, next], offset: 0, limit: 100, total: 9 });
  await state.refresh(); expect(state.endpointId.value).toBe("a-3"); expect(state.path.value.items).toHaveLength(4);
});

it("loads all pages before resolving the exact predecessor path", async () => {
  const { api, state, items } = setup(); await flushPromises();
  vi.mocked(api.list).mockImplementation(async (offset = 0) => ({ items: items.slice(offset, offset + 3), offset, limit: 100, total: 8 }));
  await state.refresh();
  expect(vi.mocked(api.list).mock.calls.slice(1).map(call => call[0])).toEqual([0, 3, 6]);
  state.chooseEndpoint("b-3"); expect(state.path.value.items).toHaveLength(4); expect(api.compose).not.toHaveBeenCalled();
});

it("replaces member selection with opening one complete timeline and updating its endpoint", async () => {
  const wrapper = mount(ReviewedPlanLibrary, { props: { items: timelineEntries(), endpointId: "b-3",
    disabled: false, loading: false, pending: false, uncertain: false, error: null, canStart: true } });
  wrappers.push(wrapper);
  expect(wrapper.findAll('input[type="checkbox"]')).toHaveLength(0);
  expect(wrapper.findAll("select")).toHaveLength(0);
  expect(wrapper.findAll('[data-testid="open-plan-timeline"]')).toHaveLength(2);
  await wrapper.findAll('[data-testid="open-plan-timeline"]')[0]!.trigger("click");
  expect(wrapper.emitted("open")).toEqual([["a-3"]]); expect(wrapper.emitted("compose")).toBeUndefined();
  await wrapper.get('[data-testid="prepare-next-source"]').trigger("click");
  expect(wrapper.emitted("update")).toEqual([["b-3"]]);
  expect(wrapper.text()).toContain("4 次计划更新");
  const historical = wrapper.findAll("a").find(link => link.attributes("href") === "/backtests/new?preparationId=b-1&inspect=1")!;
  expect(historical.attributes("target")).toBe("_blank");
  expect(historical.attributes("rel")).toContain("noopener");
});

it("allows a first source without picking a stock and locks timeline actions while pending", async () => {
  const wrapper = mount(ReviewedPlanLibrary, { props: { items: [], endpointId: "", disabled: false,
    loading: false, pending: false, uncertain: false, error: null, canStart: true } }); wrappers.push(wrapper);
  await wrapper.get('[data-testid="new-plan-timeline"]').trigger("click");
  expect(wrapper.emitted("new")).toEqual([[]]); expect(wrapper.findAll("select")).toHaveLength(0);
  await wrapper.setProps({ items: timelineEntries(), endpointId: "a-3", pending: true });
  for (const button of wrapper.findAll("button")) expect(button.element.matches(":disabled")).toBe(true);
});
