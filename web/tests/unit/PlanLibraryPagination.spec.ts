import { afterEach, expect, it } from "vitest";
import { mount, type VueWrapper } from "@vue/test-utils";
import type { ReviewedPlanLibraryItem } from "../../src/api/generated-runtime-status";
import ReviewedPlanLibrary from "../../src/components/backtests/ReviewedPlanLibrary.vue";

const wrappers: VueWrapper[] = [];
afterEach(() => wrappers.splice(0).forEach(wrapper => wrapper.unmount()));
function entries(count = 30): ReviewedPlanLibraryItem[] {
  return Array.from({ length: count }, (_, chain) => [0, 1, 2, 3].map(index => ({
    preparationId: `page-${chain}-${index}`, manifestHash: (chain * 4 + index + 1).toString(16).padStart(64, "0"),
    sourceId: `source-${index}`, symbol: "002240.SZ", name: `测试时间线${chain + 1}`,
    effectiveTradeDate: ["2026-09-24", "2026-09-28", "2026-09-30", "2026-10-09"][index]!,
    reviewedAt: "2026-10-17T11:48:03+08:00",
    reviewedBase: index ? { preparation_id: `page-${chain}-${index - 1}`,
      manifest_hash: (chain * 4 + index).toString(16).padStart(64, "0") } : null,
  }))).flat();
}
function setup(count = 30) {
  const items = entries(count);
  const wrapper = mount(ReviewedPlanLibrary, { props: { items, endpointId: "page-25-3", disabled: false,
    loading: false, pending: false, uncertain: false, error: null, canStart: true } });
  wrappers.push(wrapper); return { wrapper, items };
}
function button(wrapper: VueWrapper, text: string) { return wrapper.findAll("button").find(node => node.text() === text)!; }

it("pages 30 complete timelines by ten with collapsed records and stable selected identity", async () => {
  const { wrapper, items } = setup(); const original = JSON.stringify(items);
  expect(wrapper.findAll('[data-testid="plan-library-chain"]')).toHaveLength(10);
  expect(wrapper.findAll('[data-testid="open-plan-timeline"]')).toHaveLength(10);
  expect(wrapper.text()).toContain("第 1 / 3 页");
  expect(wrapper.text()).toContain("当前已选：测试时间线26");
  expect(wrapper.findAll('[data-testid="timeline-updates"]').every(node => !(node.element as HTMLDetailsElement).open)).toBe(true);
  await button(wrapper, "下一页").trigger("click");
  expect(wrapper.text()).toContain("第 2 / 3 页");
  expect(wrapper.get('[data-testid="plan-library-chain"]').text()).toContain("时间线 11");
  await button(wrapper, "定位已选时间线").trigger("click");
  expect(wrapper.text()).toContain("第 3 / 3 页");
  const selected = wrapper.get('[data-chain-id="page-25-0"]');
  expect(selected.findAll(".plan-library__record")).toHaveLength(4);
  expect(selected.get('[data-endpoint-id="page-25-3"]').attributes("aria-pressed")).toBe("true");
  await selected.get('[data-testid="prepare-next-source"]').trigger("click");
  expect(wrapper.emitted("update")).toEqual([["page-25-3"]]);
  await button(wrapper, "上一页").trigger("click");
  expect(wrapper.props("endpointId")).toBe("page-25-3");
  expect(wrapper.emitted("open")).toBeUndefined(); expect(wrapper.emitted("compose")).toBeUndefined();
  expect(wrapper.emitted("refresh")).toBeUndefined(); expect(JSON.stringify(items)).toBe(original);
});

it("keeps final partial pages and clamps a shortened library without changing selection", async () => {
  const { wrapper } = setup(21);
  await button(wrapper, "下一页").trigger("click"); await button(wrapper, "下一页").trigger("click");
  expect(wrapper.findAll('[data-testid="plan-library-chain"]')).toHaveLength(1);
  expect(button(wrapper, "下一页").element.matches(":disabled")).toBe(true);
  await wrapper.setProps({ items: entries(11) });
  expect(wrapper.text()).toContain("第 2 / 2 页");
  expect(wrapper.findAll('[data-testid="plan-library-chain"]')).toHaveLength(1);
  expect(wrapper.emitted("open")).toBeUndefined();
  await wrapper.setProps({ pending: true });
  expect(button(wrapper, "上一页").element.matches(":disabled")).toBe(true);
});

it("keeps forked endpoints together on the same page", () => {
  const { wrapper, items } = setup(11);
  const branch = { ...items[2]!, preparationId: "alternative", manifestHash: "f".repeat(64) };
  return wrapper.setProps({ items: [...items, branch] }).then(() => {
    const first = wrapper.get('[data-chain-id="page-0-0"]');
    expect(first.findAll('[data-testid="open-plan-timeline"]')).toHaveLength(2);
    expect(first.findAll(".plan-library__record")).toHaveLength(5);
  });
});
