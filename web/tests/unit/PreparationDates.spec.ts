import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import type { CollectionItemView, CollectionPreparationView, PreparationView } from "../../src/api/generated-runtime-status";
import { inspectCollectionReview, inspectPreparationReview } from "../../src/api/preparationReview";
import PlanPreparationSourceForm from "../../src/components/backtests/PlanPreparationSourceForm.vue";
import PlanPreparationProgress from "../../src/components/backtests/PlanPreparationProgress.vue";
import PlanPreparationReview from "../../src/components/backtests/PlanPreparationReview.vue";

const fixture = JSON.parse(readFileSync("tests/fixtures/plan-preparation-review.json", "utf8")) as { candidate: PreparationView };

describe("preloaded plan dates", () => {
  it("does not require authoring or availability when reviewing a dated plan", () => {
    const candidate = structuredClone(fixture.candidate);
    candidate.source.authored_at = null;
    candidate.source.available_at = null;
    expect(inspectPreparationReview(candidate).blockers.some(text => /原文编写时间|可用时间/.test(text))).toBe(false);
  });

  it("distinguishes an unextracted source from an invalid candidate", () => {
    const item: CollectionItemView = { sourceId: "one", sourceRevision: 1, candidateRevision: 0,
      candidateHash: null, evidenceHash: null, baseHash: null, validation: null,
      source: { source_id: "one", text: "生效日期待确认" }, candidate: null,
      status: "DRAFT", effectiveTradeDate: null, attempts: [], attemptCount: 0 };
    const collection: CollectionPreparationView = { schemaVersion: "backtest-preparation-v2",
      preparationId: "prep", revision: 1, status: "DRAFT", itemCount: 1, items: [item],
      currentSourceId: "one", frozen: null, generation: null, workPhase: null, reviewRevision: 0 };
    const result = inspectCollectionReview(collection, [item]);
    expect(result.blockers).toContain("第 1 份原文的生效交易日不明确，请确认日期");
    expect(result.blockers).toContain("第 1 份原文尚未提取计划");
    expect(result.blockers.some(text => /候选仍需修正|历史时间/.test(text))).toBe(false);
    const wrapper = mount(PlanPreparationReview, { props: { collection, items: [item],
      canReview: false, sourceDirty: false, reviewed: false } });
    expect(wrapper.get('[aria-label="计划生效日历"]').text()).toContain("等待提取");
    expect(wrapper.get('[aria-label="计划生效日历"]').text()).not.toContain("待补齐 / 修正");
    wrapper.unmount();
  });

  it.each([1, 6])("offers date confirmation without mandatory timestamps for %i sources", count => {
    const sources = Array.from({ length: count }, (_, i) => ({ source_id: `s-${i}`, text: "计划原文" }));
    const wrapper = mount(PlanPreparationSourceForm, { props: { source: sources[0]!, sources, disabled: false } });
    expect(wrapper.findAll('input[type="datetime-local"]')).toHaveLength(0);
    expect(wrapper.findAll('input[type="date"]')).toHaveLength(count);
    expect(wrapper.text()).toContain("自动识别");
    wrapper.unmount();
  });

  it("asks for a decision when two sources share one effective day", () => {
    const sources = ["first", "second"].map(sourceId => ({
      sourceId, sourceRevision: 1, candidateRevision: 0, candidateHash: null,
      evidenceHash: null, baseHash: null, validation: null, status: "DRAFT" as const,
      effectiveTradeDate: "2026-09-24", attemptCount: 0, attempts: [], candidate: null,
      source: { source_id: sourceId, text: "计划", effective_trade_date: "2026-09-24" },
    }));
    const collection: CollectionPreparationView = { schemaVersion: "backtest-preparation-v2",
      preparationId: "prep", revision: 1, status: "DRAFT", itemCount: 2, items: sources,
      currentSourceId: "first", frozen: null, generation: null, workPhase: null, reviewRevision: 0 };
    expect(inspectCollectionReview(collection, sources).blockers).toContain("2026-09-24 存在多份计划，请确认各份生效交易日");
  });
});

it("shows the input limit reason rather than blaming the source or later waiting items", () => {
  const value = structuredClone(fixture.candidate);
  value.status = "FAILED";
  value.attempts = [{ attempt_id: "attempt", source_revision: 1, source_hash: "a".repeat(64),
    status: "FAILED", started_at: "2026-09-24T09:00:00+08:00", finished_at: "2026-09-24T09:00:01+08:00",
    error_code: "AI_INPUT_TOO_LARGE", retryable: true }];
  const wrapper = mount(PlanPreparationProgress, { props: { preparation: value,
    requestState: "READY", mutationState: "IDLE", canExtract: false, canCancel: false,
    canRecover: false, canRetryMutation: false,
    extractionBlockers: ["第 1 份生效交易日不明确，请先确认日期并保存，再提取计划。"] } });
  expect(wrapper.text()).toContain("尚未发送给 AI");
  expect(wrapper.text()).toContain("AI 输入长度上限");
  expect(wrapper.text()).toContain("请先确认日期并保存");
  expect(wrapper.find('[data-testid="extract-preparation"]').exists()).toBe(false);
  wrapper.unmount();
});
