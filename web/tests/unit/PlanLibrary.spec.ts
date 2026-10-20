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

it("does not report an empty history when the library read failed", () => {
  const wrapper = mount(ReviewedPlanLibrary, { props: { items: [], endpointId: "",
    disabled: false, loading: false, pending: false, uncertain: false,
    error: "无法读取已审核计划", canStart: true } });
  wrappers.push(wrapper);
  expect(wrapper.text()).not.toContain("还没有计划时间线");
  expect(wrapper.get('[role="status"]').text()).toContain("暂时无法确认");
  expect(wrapper.get('[role="alert"]').text()).toContain("无法读取");
  expect(wrapper.get('[data-testid="new-plan-timeline"]').attributes("disabled")).toBeDefined();
});

it("shows a genuine empty library only after a successful read and hides old errors during retry", async () => {
  const wrapper = mount(ReviewedPlanLibrary, { props: { items: [], endpointId: "",
    disabled: false, loading: true, pending: false, uncertain: false,
    error: "无法读取已审核计划", canStart: true } });
  wrappers.push(wrapper);
  expect(wrapper.get('[role="status"]').text()).toContain("正在读取");
  expect(wrapper.find('[role="alert"]').exists()).toBe(false);
  expect(wrapper.text()).not.toContain("还没有计划时间线");
  await wrapper.setProps({ loading: false, error: null });
  expect(wrapper.text()).toContain("还没有计划时间线");
  expect(wrapper.get('[data-testid="new-plan-timeline"]').attributes("disabled")).toBeUndefined();
});

it("explains unavailable reads, preserves loaded history, and clears the error after retry", async () => {
  const { api, state } = setup(); await flushPromises(); state.chooseEndpoint("first");
  vi.mocked(api.list).mockRejectedValueOnce(new ApiClientError({ code: "SERVICE_UNAVAILABLE",
    status: 503, message: "Service unavailable" }));
  await state.refresh();
  expect(state.error.value).toContain("服务管理");
  expect(state.items.value).toEqual([entry]);
  expect(state.endpointId.value).toBe("first");
  const wrapper = mount(ReviewedPlanLibrary, { props: { items: state.items.value, endpointId: "first",
    disabled: false, loading: false, pending: false, uncertain: false,
    error: state.error.value, canStart: true } });
  wrappers.push(wrapper);
  expect(wrapper.text()).toContain("上次成功读取");
  expect(wrapper.findAll('[data-testid="plan-library-chain"]')).toHaveLength(1);
  await state.refresh();
  expect(state.error.value).toBeNull();
  expect(state.endpointId.value).toBe("first");
});

it("explains a rejected old risk scope without requesting manual source facts", async () => {
  const { api, state } = setup(); await flushPromises(); state.chooseEndpoint("first");
  vi.mocked(api.compose).mockRejectedValue(new ApiClientError({ code: "CONFLICT", status: 409,
    message: "Conflict", details: [{ code: "REVIEWED_RISK_SCOPE_RECHECK_REQUIRED", location: ["preparation"], message: "Conflict" }] }));
  await state.compose();
  expect(state.error.value).toContain("风险退出范围需要重新提取核对");
  expect(state.error.value).toContain("无需补填原文已有的信息");
  expect(state.locked.value).toBe(false);
});
it("starts a first source without auto-selecting a reviewed timeline", async () => {
  const { api, state } = setup(); await flushPromises();
  expect(state.reviewedBase.value).toBeNull(); expect(state.endpointId.value).toBe("");
  expect(state.needsBase.value).toBe(false); expect(api.compose).not.toHaveBeenCalled();
});
it("preserves an explicit new chain on refresh and follows the just-reviewed plan for the next source", async () => {
  const { state } = setup(); await flushPromises();
  state.chooseEndpoint(""); await state.refresh();
  expect(state.reviewedBase.value).toBeNull();
  expect(state.needsBase.value).toBe(false);
  state.chooseEndpoint("first");
  expect(state.reviewedBase.value?.preparation_id).toBe("first");
});
it("does not choose across assets or tied dates, or substitute a missing explicit predecessor", async () => {
  const { api, state } = setup(); await flushPromises();
  vi.mocked(api.list).mockResolvedValue({ ...page, items: [entry, { ...entry, preparationId: "other" }], total: 2 });
  state.chooseEndpoint(""); expect(state.endpointId.value).toBe("");
  state.chooseEndpoint("first");
  vi.mocked(api.list).mockResolvedValue({ ...page, items: [{ ...entry, preparationId: "other", symbol: "600000.SH" }] });
  await state.refresh(); expect(state.needsBase.value).toBe(true);
  expect(state.reviewedBase.value).toBeNull();
});
it("keeps the exact uncertain composition intent and blocks selection edits", async () => {
  const { api, state } = setup(); await flushPromises();
  vi.mocked(api.compose).mockRejectedValue(new Error("lost reply"));
  state.chooseEndpoint("first"); await state.compose();
  const first = vi.mocked(api.compose).mock.calls[0]!;
  expect(state.uncertain.value).toBe(true); state.chooseEndpoint("first");
  expect(state.endpointId.value).toBe("first");
  await state.compose();
  expect(vi.mocked(api.compose).mock.calls[1]!.slice(0,2)).toEqual(first.slice(0,2));
  expect(first[0].plans).toEqual([{ preparation_id: "first", manifest_hash: entry.manifestHash }]);
});
it("reports missing dependencies without freezing the selection after definite rejection", async () => {
  const { api, state } = setup(); await flushPromises(); state.chooseEndpoint("first");
  vi.mocked(api.compose).mockRejectedValue(new ApiClientError({ code: "CONFLICT", status: 409,
    message: "Conflict", details: [{ code: "PREDECESSOR_SELECTION_REQUIRED", location: ["preparation"], message: "Conflict" }] }));
  await state.compose(); expect(state.error.value).toContain("上一份已审核版本");
  expect(state.locked.value).toBe(false); state.chooseEndpoint(""); expect(state.endpointId.value).toBe("");
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
  const wrapper = mount(ReviewedPlanLibrary,{props:{ items:[entry],endpointId:"first",
    disabled:false,loading:false,pending:true,uncertain:true,error:null,canStart:true }}); wrappers.push(wrapper);
  expect(wrapper.get('[data-testid="prepare-next-source"]').attributes("disabled")).toBeDefined();
  expect(wrapper.get('fieldset').attributes("disabled")).toBeDefined();
  expect(wrapper.text()).toContain("回测准备结果尚未确认");
});
it("offers timeline creation and endpoint updates without stock or predecessor selectors", () => {
  const wrapper = mount(ReviewedPlanLibrary,{props:{ items:[entry],endpointId:"first",
    disabled:false,loading:false,pending:false,uncertain:false,error:null,canStart:true }}); wrappers.push(wrapper);
  expect(wrapper.findAll('input[type="radio"]')).toHaveLength(0);
  expect(wrapper.text()).not.toContain("修改型计划");
  expect(wrapper.text()).not.toContain("完整计划");
  expect(wrapper.text()).toContain("计划更新时间线");
  expect(wrapper.findAll("select")).toHaveLength(0);
});

function twoChains(): ReviewedPlanLibraryItem[] {
  return ["a", "b"].flatMap(chain => [0, 1, 2, 3].map(index => ({
    ...entry, preparationId: `${chain}-${index}`, manifestHash: (chain + index).repeat(32),
    sourceId: `source-${index}`, effectiveTradeDate: ["2026-09-24", "2026-09-28", "2026-09-30", "2026-10-09"][index]!,
    reviewedAt: `2026-10-17T${chain === "a" ? "02" : "11"}:48:03+08:00`,
    reviewedBase: index ? { preparation_id: `${chain}-${index - 1}`, manifest_hash: (chain + (index - 1)).repeat(32) } : null,
    identity: { sourceHash: String(index + 1).repeat(64), planHash: chain.repeat(64),
      planVersionId: `prepared-${chain}-${index}`, reviewedVersionHash: (chain + index).repeat(32) },
  })));
}

function library(items: ReviewedPlanLibraryItem[]) {
  const wrapper = mount(ReviewedPlanLibrary, { props: { items, endpointId: "b-3",
    disabled: false, loading: false, pending: false, uncertain: false, error: null, canStart: true } });
  wrappers.push(wrapper); return wrapper;
}

it("shows business dates, stocks and predecessors without exposing internal identifiers", () => {
  const items = twoChains();
  const wrapper = library(items);
  expect(wrapper.text()).toContain("2026-09-24");
  expect(wrapper.text()).toContain("测试（002240.SZ）");
  expect(wrapper.text()).toContain("前序：2026-09-30");
  expect(wrapper.findAll("summary").map(item => item.text())).toContain("查看计划及本次调整");
  for (const item of items) {
    for (const value of [item.preparationId, item.manifestHash, item.sourceId,
      item.identity!.planVersionId, item.identity!.reviewedVersionHash,
      item.identity!.sourceHash, item.identity!.planHash]) expect(wrapper.text()).not.toContain(value);
  }
  for (const label of ["审核清单标识", "原冻结版本标识", "完整审核版本标识", "原文核对标识", "计划内容核对标识"])
    expect(wrapper.text()).not.toContain(label);
  expect(wrapper.get('[data-endpoint-id="b-3"]').attributes("aria-pressed")).toBe("true");
});

it("distinguishes two four-plan timelines while retaining exact endpoint identities", async () => {
  const wrapper = library(twoChains());
  expect(wrapper.findAll('[data-testid="plan-library-chain"]')).toHaveLength(2);
  expect(wrapper.findAll('[data-testid="open-plan-timeline"]')).toHaveLength(2);
  expect(wrapper.findAll('input[type="checkbox"]')).toHaveLength(0);
  expect(wrapper.findAll(".plan-library__record")).toHaveLength(8);
  expect(wrapper.get('[data-endpoint-id="b-3"]').attributes("aria-pressed")).toBe("true");
  const a = wrapper.get('[data-chain-id="a-0"]');
  expect(a.text()).toContain("02:48:03");
  expect(a.text()).toContain("前序：2026-09-30");
  expect(a.text()).toContain("同原文，计划内容不同");
  expect(a.text()).not.toContain("prepared-b-2");
  await wrapper.get('[data-endpoint-id="b-3"]').trigger("click");
  expect(wrapper.emitted("open")).toEqual([["b-3"]]);
  expect(wrapper.emitted("compose")).toBeUndefined();
  expect(wrapper.get('[data-endpoint-id="a-3"]').attributes("aria-pressed")).toBe("false");
});

it("does not call equal rules a duplicate approval or silently bind a stale predecessor", () => {
  const items = twoChains();
  items[4]!.identity!.planHash = items[0]!.identity!.planHash;
  items[6]!.reviewedBase!.manifest_hash = "f".repeat(64);
  const wrapper = library(items);
  expect(wrapper.text()).toContain("同原文，计划内容一致，审核版本不同");
  expect(wrapper.text()).toContain("前序版本与当前记录不匹配");
  expect(wrapper.text()).not.toContain("相同审核版本的重复准备");
});

it("keeps independent preparations separate when their content-based version IDs coincide", () => {
  const items = twoChains();
  for (let index = 0; index < 4; index++) {
    items[index + 4]!.identity!.planVersionId = items[index]!.identity!.planVersionId;
    items[index + 4]!.identity!.planHash = items[index]!.identity!.planHash;
  }
  const wrapper = library(items);
  expect(wrapper.findAll('[data-testid="plan-library-chain"]')).toHaveLength(2);
  expect(wrapper.get('[data-chain-id="a-0"]').text()).toContain("02:48:03");
  expect(wrapper.get('[data-chain-id="b-0"]').text()).toContain("11:48:03");
  expect(wrapper.text()).toContain("同原文，计划内容一致，审核版本不同");
  expect(wrapper.text()).not.toContain("相同审核快照的重复准备");
});

it("keeps truly repeated approvals and old payloads explicit instead of dropping records", () => {
  const repeated = { ...entry, preparationId: "repeated", identity: twoChains()[0]!.identity! };
  const wrapper = library([twoChains()[0]!, repeated, { ...entry, preparationId: "legacy" }]);
  expect(wrapper.findAll(".plan-library__record")).toHaveLength(3);
  expect(wrapper.text()).toContain("相同审核快照的重复准备");
  expect(wrapper.text()).toContain("历史计划，可查看已审核原文与交易条件");
});

it("rejects malformed optional identity metadata while accepting existing library payloads", async () => {
  const fetcher = (body: unknown) => vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { headers: { "Cache-Control": "no-store" } }));
  await expect(createPlanLibraryApi(fetcher(page)).list()).resolves.toEqual(page);
  for (const identity of [{ sourceHash: "bad" }, { ...twoChains()[0]!.identity, planHash: "bad" }]) {
    await expect(createPlanLibraryApi(fetcher({ ...page, items: [{ ...entry, identity }] })).list()).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  }
});
