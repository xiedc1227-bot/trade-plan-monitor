import { afterEach, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { usePlanLibrary } from "../../src/composables/usePlanLibrary";
import { createPlanLibraryApi, type PlanLibraryApi } from "../../src/api/planLibrary";
import { ApiClientError } from "../../src/api/transport";
import ReviewedPlanLibrary from "../../src/components/backtests/ReviewedPlanLibrary.vue";
import type { ReviewedPlanLibraryItem } from "../../src/api/generated-runtime-status";

const entry: ReviewedPlanLibraryItem = { preparationId: "first", manifestHash: "a".repeat(64),
  sourceId: "source-1", effectiveTradeDate: "2026-09-24", name: "测试", symbol: "002240.SZ",
  reviewedBase: null, reviewedAt: "2026-10-16T09:00:00+08:00" };
const page = { items: [entry], offset: 0, limit: 100, total: 1 };
const wrappers: VueWrapper[] = [];
afterEach(() => { wrappers.splice(0).forEach(w => w.unmount()); vi.restoreAllMocks(); });
function setup() {
  const api: PlanLibraryApi = { list: vi.fn().mockResolvedValue(page), compose: vi.fn() };
  let state!: ReturnType<typeof usePlanLibrary>;
  wrappers.push(mount(defineComponent({ setup() { state = usePlanLibrary(api); return () => h("div"); } })));
  return { api, state };
}

it("explains a rejected old risk scope without requesting manual source facts", async () => {
  const { api, state } = setup(); await flushPromises(); state.toggle("first");
  vi.mocked(api.compose).mockRejectedValue(new ApiClientError({ code: "CONFLICT", status: 409,
    message: "Conflict", details: [{ code: "REVIEWED_RISK_SCOPE_RECHECK_REQUIRED", location: ["preparation"], message: "Conflict" }] }));
  await state.compose();
  expect(state.error.value).toContain("风险退出范围需要重新提取核对");
  expect(state.error.value).toContain("无需补填原文已有的信息");
  expect(state.locked.value).toBe(false);
});
it("defaults to the unique latest reviewed entry without a document type", async () => {
  const { api, state } = setup(); await flushPromises();
  expect(state.reviewedBase.value).toEqual({ preparation_id: "first", manifest_hash: entry.manifestHash });
  expect(state.needsBase.value).toBe(false); expect(api.compose).not.toHaveBeenCalled();
});
it("preserves an explicit new chain on refresh and follows the just-reviewed plan for the next source", async () => {
  const { state } = setup(); await flushPromises();
  state.chooseBase(""); await state.refresh();
  expect(state.reviewedBase.value).toBeNull();
  expect(state.needsBase.value).toBe(false);
  await state.prepareNext("first");
  expect(state.reviewedBase.value?.preparation_id).toBe("first");
});
it("does not choose across assets or tied dates, or substitute a missing explicit predecessor", async () => {
  const { api, state } = setup(); await flushPromises();
  vi.mocked(api.list).mockResolvedValue({ ...page, items: [entry, { ...entry, preparationId: "other" }], total: 2 });
  await state.prepareNext(); expect(state.needsBase.value).toBe(true);
  state.chooseBase("first");
  vi.mocked(api.list).mockResolvedValue({ ...page, items: [{ ...entry, preparationId: "other", symbol: "600000.SH" }] });
  await state.refresh(); expect(state.needsBase.value).toBe(true);
  expect(state.reviewedBase.value).toBeNull();
});
it("keeps the exact uncertain composition intent and blocks selection edits", async () => {
  const { api, state } = setup(); await flushPromises();
  vi.mocked(api.compose).mockRejectedValue(new Error("lost reply"));
  state.toggle("first"); await state.compose();
  const first = vi.mocked(api.compose).mock.calls[0]!;
  expect(state.uncertain.value).toBe(true); state.toggle("first");
  expect(state.selected.value).toEqual(["first"]);
  await state.compose();
  expect(vi.mocked(api.compose).mock.calls[1]!.slice(0,2)).toEqual(first.slice(0,2));
  expect(first[0].plans).toEqual([{ preparation_id: "first", manifest_hash: entry.manifestHash }]);
});
it("reports missing dependencies without freezing the selection after definite rejection", async () => {
  const { api, state } = setup(); await flushPromises(); state.toggle("first");
  vi.mocked(api.compose).mockRejectedValue(new ApiClientError({ code: "CONFLICT", status: 409,
    message: "Conflict", details: [{ code: "PREDECESSOR_SELECTION_REQUIRED", location: ["preparation"], message: "Conflict" }] }));
  await state.compose(); expect(state.error.value).toContain("上一份已审核版本");
  expect(state.locked.value).toBe(false); state.toggle("first"); expect(state.selected.value).toEqual([]);
});
it("rejects an incomplete library page", async () => {
  const { api, state } = setup(); await flushPromises();
  vi.mocked(api.list).mockResolvedValue({ ...page, items: [] }); await state.refresh();
  expect(state.error.value).toContain("无法读取"); expect(state.items.value).toEqual([entry]);
});
it("checks library dates, references and no-store before exposing entries", async () => {
  for (const body of [{ ...page, items: [{ ...entry, effectiveTradeDate: "2026-02-30" }] },
    { ...page, items: [{ ...entry, reviewedBase: { preparation_id: "first", manifest_hash: "bad" } }] }]) {
    const api = createPlanLibraryApi(vi.fn().mockResolvedValue(new Response(JSON.stringify(body), {headers:{"Cache-Control":"no-store"}})));
    await expect(api.list()).rejects.toMatchObject({code:"INVALID_RESPONSE"});
  }
});
it("disables new preparation while a composition outcome is unknown", () => {
  const wrapper = mount(ReviewedPlanLibrary,{props:{ items:[entry],selected:["first"],baseId:"",creating:false,
    disabled:false,loading:false,pending:true,uncertain:true,error:null,canStart:true }}); wrappers.push(wrapper);
  expect(wrapper.get('[data-testid="prepare-next-source"]').attributes("disabled")).toBeDefined();
  expect(wrapper.get('fieldset').attributes("disabled")).toBeDefined();
  expect(wrapper.text()).toContain("使用同一请求安全重试组合");
});
it("offers preparation and predecessor selection without plan-type radios", () => {
  const wrapper = mount(ReviewedPlanLibrary,{props:{ items:[entry],selected:[],baseId:"first",creating:true,
    disabled:false,loading:false,pending:false,uncertain:false,error:null,canStart:true }}); wrappers.push(wrapper);
  expect(wrapper.findAll('input[type="radio"]')).toHaveLength(0);
  expect(wrapper.text()).not.toContain("修改型计划");
  expect(wrapper.text()).not.toContain("完整计划");
  expect(wrapper.text()).toContain("准备计划");
  expect(wrapper.get('select').element.value).toBe("first");
});
