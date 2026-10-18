import { afterEach, describe, expect, it } from "vitest";
import { mount, type VueWrapper } from "@vue/test-utils";
import type { PreparationConfirmationSummary } from "../../src/api/generated-runtime-status";
import PlanPreparationConfirmations from "../../src/components/backtests/PlanPreparationConfirmations.vue";

const wrappers: VueWrapper[] = [];
afterEach(() => wrappers.splice(0).forEach(wrapper => wrapper.unmount()));

function summary(): PreparationConfirmationSummary {
  return {
    automaticFacts: ["生效交易日：2026-10-09（已确认）", "原文明确当前持仓 0 股", "第一笔 100 股，第二笔 100 股", "低吸观察区暂不启用"],
    questions: [
      { questionId: "cash", category: "BACKTEST_SETTING", message: "请设置本次回测的初始资金。", excerpts: [] },
      { questionId: "volume", category: "SOURCE_AMBIGUOUS", message: "请明确成交量异常的判定口径。", excerpts: ["成交不异常放大"] },
      { questionId: "exit", category: "SOURCE_MISSING", message: "原文没有提供新仓的完整退出规则。", excerpts: [] },
    ],
    processingIssues: ["AI 的 BUY 字段证据映射尚未完成：ordinary_rules[0].side；请重新提取。"],
  };
}

function render(value = summary()) {
  const wrapper = mount(PlanPreparationConfirmations, { props: { summary: value } });
  wrappers.push(wrapper);
  return wrapper;
}

describe("集中确认事项", () => {
  it("separates determined facts, business questions and system processing issues", () => {
    const wrapper = render();
    expect(wrapper.find('section[aria-label="集中确认事项"]').exists()).toBe(true);
    expect(wrapper.findAll("h3").map(heading => heading.text())).toEqual([
      "已从原文和已确认信息中确定", "需要集中确认的事项", "系统处理事项",
    ]);
    expect(wrapper.findAll("ul > li").map(item => item.text())).toEqual(summary().automaticFacts);
    expect(wrapper.findAll("ol > li")).toHaveLength(3);
    expect(wrapper.findAll("ol strong").map(label => label.text())).toEqual([
      "回测设置", "判定口径不明确", "原文未提供",
    ]);
    expect(wrapper.get('aside[role="status"]').text()).toContain(summary().processingIssues[0]);
    expect(wrapper.get("ol").text()).not.toContain("系统处理事项");
    expect(wrapper.get("ol").text()).not.toContain("重新提取");
  });

  it("shows the confirmed effective date once without adding another date question or input", () => {
    const wrapper = render();
    expect(wrapper.text().match(/2026-10-09/g)).toHaveLength(1);
    expect(wrapper.get("ul").text()).toContain("生效交易日：2026-10-09（已确认）");
    expect(wrapper.get("ol").text()).not.toMatch(/日期|交易日|成文|可用时间/);
    expect(wrapper.find('input[type="date"]').exists()).toBe(false);
    expect(wrapper.text()).toContain("已知价格、数量、日期及停用指令无需重复填写");
  });

  it("keeps internal BUY and evidence paths out of the business confirmation requests", () => {
    const wrapper = render();
    expect(wrapper.get("ol").text()).not.toMatch(/BUY|ordinary_rules|证据路径|映射/);
    expect(wrapper.get('aside[role="status"]').text()).toContain("ordinary_rules[0].side");
    expect(wrapper.findAll("input, textarea, select, button, form")).toHaveLength(0);
    expect(wrapper.text()).toContain("AI 对语义的解释仍需在完整候选中整体核对");
  });

  it("renders source excerpts as plain text and never turns them into actions", async () => {
    const value = summary();
    const excerpt = '<button onclick="window.confirm(\'approve\')">确认并执行</button>\n<img src=x onerror="alert(1)">';
    value.questions[1]!.excerpts = [excerpt];
    const original = structuredClone(value);
    const wrapper = render(value);

    expect(wrapper.get("blockquote").text()).toBe(excerpt);
    expect(wrapper.find("blockquote button, blockquote img, script").exists()).toBe(false);
    expect(wrapper.html()).toContain("&lt;button");
    await wrapper.get("blockquote").trigger("click");
    await wrapper.get("blockquote").trigger("keydown", { key: "Enter" });
    for (const event of ["confirm", "review", "execute", "submit", "update:summary"]) {
      expect(wrapper.emitted(event)).toBeUndefined();
    }
    expect(value).toEqual(original);
  });

  it("updates the summary without implicitly approving a candidate when questions are resolved", async () => {
    const wrapper = render();
    await wrapper.setProps({ summary: {
      automaticFacts: ["生效交易日：2026-10-09（已确认）", "初始资金已配置"],
      questions: [], processingIssues: [],
    } });

    expect(wrapper.find("ol").exists()).toBe(false);
    expect(wrapper.find("aside").exists()).toBe(false);
    expect(wrapper.text()).toContain("当前没有额外业务确认项，请核对完整候选后审核");
    expect(wrapper.text()).not.toContain("保存后重新提取");
    expect(wrapper.emitted()).toEqual({});
    expect(wrapper.findAll("button, input, textarea, select")).toHaveLength(0);
  });
});
