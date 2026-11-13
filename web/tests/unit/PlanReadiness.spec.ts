import { createHash, webcrypto } from "node:crypto";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import PlanReadiness from "../../src/components/plans/PlanReadiness.vue";
import PlanWorkbench from "../../src/components/plans/PlanWorkbench.vue";
import { apiFetchKey } from "../../src/api/context";
import { createPlanReadinessApi, type ReadinessContext } from "../../src/api/planReadiness";
import type { AxisReadiness, ReadinessAssessment, ReadinessObservation, RuleReadiness } from "../../src/api/generated-runtime-status";
import type { usePlanWorkspace } from "../../src/composables/usePlanWorkspace";
import type { PlanVersionView, SourceCoverageSummaryView } from "../../src/api/generated";

const A = "00000000-0000-4000-8000-000000000001", B = "00000000-0000-4000-8000-000000000002";
const HASH = "a".repeat(64), SOURCE = "b".repeat(64), RECEIPT = "c".repeat(64);
const NOW = Date.parse("2026-11-14T10:00:00+08:00");
// Synthetic wire projections exercise actual Vue/client ownership, not server policy proofs.
const stamp = (offset = 0) => new Date(NOW + offset).toISOString();
const context = (planVersionId = A, ownerGeneration = 1): ReadinessContext => ({
  planVersionId, contentHash: HASH, sourceHash: SOURCE, reviewReceiptHash: RECEIPT, ownerGeneration,
});
const axes: AxisReadiness["axis"][] = ["SOURCE_COVERAGE", "REVIEW_ACTIVATION", "RUNTIME_OWNERSHIP",
  "DATA_EVALUATION", "INVENTORY_CAPITAL", "NOTIFICATION_DELIVERY"];
function rule(state: RuleReadiness["state"] = "CONDITION_FALSE", ownerId = "buy-one"): RuleReadiness {
  return { state, reason: state === "UNKNOWN" ? "DEPENDENCY_UNVERIFIED" : null, facts: {
    ownerKind: "ORDINARY_RULE", ownerId, side: "BUY", requirements: {}, expectedTarget: null,
    evaluatedTarget: null, evaluatedAt: stamp(), observation: null,
    rootOutcome: state === "CONDITION_FALSE" ? "UNSATISFIED" : null, leaves: [],
  } };
}
function assessment(planVersionId = A): ReadinessAssessment {
  return { contractVersion: "plan-monitor-readiness-v1", authorityGranted: false,
    summary: "READY_FOR_MONITORING", freshUntil: stamp(60_000),
    axes: axes.map(axis => ({ axis, state: "PASS" })), rules: [rule()], snapshot: {
      computedAt: stamp(), scope: "TRADE_RULES", axes: [], rules: [], context: {
        planVersionId, contentHash: HASH, sourceHash: SOURCE, coverageHash: HASH,
        reviewReceiptHash: RECEIPT, activationRevision: 1, runtimeGeneration: A,
      },
    } };
}
function observation(availability: ReadinessObservation["availability"] = "CURRENT"): ReadinessObservation {
  return { availability, asOf: stamp(-60_000), observedAt: stamp(-1000), expiresAt: stamp(30_000),
    context: assessment().snapshot.context, evidenceRefs: [] };
}
function response(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}
const wrappers: VueWrapper[] = [];
function mountReadiness(fetcher: typeof fetch, value: ReadinessContext | null = context()) {
  const wrapper = mount(PlanReadiness, { props: { context: value, locations: { "ORDINARY_RULE:buy-one": "ordinary_rules[0]" } },
    global: { provide: { [apiFetchKey as symbol]: fetcher } } });
  wrappers.push(wrapper); return wrapper;
}
afterEach(() => {
  wrappers.splice(0).forEach(wrapper => wrapper.unmount());
  vi.useRealTimers(); vi.unstubAllGlobals(); document.body.innerHTML = "";
});

describe("readiness wire and actual presentation", () => {
  it("reads the approved resource with cancellation and a 1MiB raw-byte bound", async () => {
    const controller = new AbortController();
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response(assessment()));
    await createPlanReadinessApi(fetcher).get(A, controller.signal);
    expect(fetcher.mock.calls[0]?.[0]).toBe(`/api/v1/plan-versions/${A}/monitor-readiness`);
    expect(fetcher.mock.calls[0]?.[1]).toMatchObject({ method: "GET", signal: controller.signal });
    const oversized = vi.fn<typeof fetch>().mockResolvedValue(new Response(" ".repeat(1024 * 1024 + 1)));
    await expect(createPlanReadinessApi(oversized).get(A)).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it.each(["authority", "version", "axes", "rules", "freshUntil"])("rejects invalid %s without a successful badge", async mutation => {
    const value = assessment();
    if (mutation === "authority") Object.assign(value, { authorityGranted: true });
    if (mutation === "version") value.snapshot.context.planVersionId = B;
    if (mutation === "axes") value.axes[5] = value.axes[0]!;
    if (mutation === "rules") value.rules[0]!.state = "NOT_A_STATE" as RuleReadiness["state"];
    if (mutation === "freshUntil") Reflect.deleteProperty(value, "freshUntil");
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response(value));
    await expect(createPlanReadinessApi(fetcher).get(A)).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("shows the server's six axes and complete FALSE without calling it missing data", async () => {
    vi.useFakeTimers(); vi.setSystemTime(NOW);
    const wrapper = mountReadiness(vi.fn<typeof fetch>().mockResolvedValue(response(assessment())));
    await flushPromises();
    expect(wrapper.get('[aria-label="监控依赖"]').findAll("li")).toHaveLength(6);
    expect(wrapper.text()).toContain("监控已就绪");
    expect(wrapper.text()).toContain("条件未成立（已完成检查）");
    await wrapper.get('[data-action="source"]').trigger("click");
    expect(wrapper.emitted("revealField")?.[0]).toEqual(["ordinary_rules[0]"]);
  });

  it("shows native expected/evaluated targets, original windows and a separate historical notification target", async () => {
    vi.useFakeTimers(); vi.setSystemTime(NOW);
    const value = assessment(), facts = value.rules[0]!.facts; value.summary = "UNKNOWN"; value.freshUntil = null;
    facts.expectedTarget = { kind: "INTRADAY", bucket_end: "2026-11-14T10:05:00+08:00" };
    facts.evaluatedTarget = { kind: "OFFICIAL_CLOSE", trade_date: "2026-11-13" };
    facts.execution = { executionWindow: "NEXT_EXCHANGE_SESSION_ONLY", executionDate: "2026-11-16",
      windowState: "CLOSED", eligible: false, approvedQuantity: 100, observation: observation("PERSISTED_ONLY") };
    facts.notification = { target: { kind: "OFFICIAL_CLOSE", trade_date: "2026-11-12" }, createdAt: stamp(-600_000),
      observation: observation("CACHED"), channels: [{ channel: "IN_APP", eligible: false,
        historicalStatus: "SUPPRESS", historicalUpdatedAt: stamp(-500_000) }] };
    const wrapper = mountReadiness(vi.fn<typeof fetch>().mockResolvedValue(response(value))); await flushPromises();
    expect(wrapper.text()).toContain("预期目标：5分钟确认 · 分段结束 2026-11-14 10:05:00+08:00");
    expect(wrapper.text()).toContain("实际已评估目标：官方收盘 · 交易日期 2026-11-13");
    expect(wrapper.text()).toContain("原执行窗口：仅下一交易日"); expect(wrapper.text()).toContain("原执行日期：2026-11-16");
    expect(wrapper.text()).toContain("历史通知目标：官方收盘 · 交易日期 2026-11-12");
    expect(wrapper.text()).toContain("历史分类更新时间：2026-11-14 01:51:40.000Z");
    expect(wrapper.text()).toContain("当前发送资格：不符合"); expect(wrapper.text()).toContain("执行观察来源：仅有持久化记录");
  });

  it.each([ ["CURRENT", "当前读取"], ["CACHED", "缓存记录"], ["UNAVAILABLE", "当前不可用"],
    ["PERSISTED_ONLY", "仅有持久化记录"] ] as const)("shows %s provenance and original times without promoting it", async (availability, description) => {
    const value = assessment(); value.summary = "UNKNOWN"; value.freshUntil = null;
    value.axes[0]!.observation = observation(availability);
    value.rules[0]!.facts.observation = observation(availability);
    const wrapper = mountReadiness(vi.fn<typeof fetch>().mockResolvedValue(response(value))); await flushPromises();
    expect(wrapper.text()).toContain(`规则观察来源：${description}`);
    expect(wrapper.get('[aria-label="监控依赖"]').text()).toContain(`观察来源：${description}`);
    expect(wrapper.text()).toContain("数据截至：2026-11-14 01:59:00.000Z");
    expect(wrapper.text()).toContain("观察时间：2026-11-14 01:59:59.000Z");
    expect(wrapper.text()).toContain("原有效期至：2026-11-14 02:00:30.000Z");
    expect(wrapper.text()).not.toContain("监控已就绪");
  });

  it("lists only required inventory and money inputs, including when no money verdict exists, and explains missing targets", async () => {
    const value = assessment(), facts = value.rules[0]!.facts; value.summary = "UNKNOWN"; value.freshUntil = null;
    facts.requirements = { inventory: true, sellability: true, quote: true, simulationBook: true,
      costBasis: true, fees: true, economics: true };
    value.rules[0]!.state = "MISSING_INPUT"; value.rules[0]!.reason = "MISSING_DATA";
    const other = rule("CONDITION_FALSE", "no-inputs"); other.facts.requirements = { inventory: false };
    value.rules.push(other);
    const wrapper = mountReadiness(vi.fn<typeof fetch>().mockResolvedValue(response(value))); await flushPromises();
    const rows = wrapper.get('[aria-label="逐规则监控结果"]').findAll(":scope > li");
    expect(rows[0]!.text()).toContain("所需输入：模拟库存、可卖数量、行情报价、模拟账本、持仓成本、费用、收益测算");
    expect(rows[0]!.text()).toContain("预期目标：未提供"); expect(rows[0]!.text()).toContain("实际已评估目标：未提供");
    expect(rows[0]!.text()).toContain("下一步：查看所需输入的数据状态，等待缺失数据补齐后重新读取。");
    expect(rows[1]!.text()).toContain("所需输入：未要求库存或金额输入");
    expect(rows[1]!.text()).not.toContain("下一步");
  });

  it("keeps absent observation expiry explicitly unverified and shows existing evidence/review actions", async () => {
    const value = assessment(), facts = value.rules[0]!.facts; value.summary = "UNKNOWN"; value.freshUntil = null;
    facts.observation = { ...observation("PERSISTED_ONLY"), asOf: null, expiresAt: null };
    value.rules[0]!.reason = "HUMAN_EVIDENCE_REQUIRED";
    value.rules[0]!.facts.leaves = [{ conditionPath: "conditions[0]", state: "UNKNOWN", reason: "SOURCE_REVIEW_REQUIRED" }];
    const wrapper = mountReadiness(vi.fn<typeof fetch>().mockResolvedValue(response(value))); await flushPromises();
    expect(wrapper.text()).toContain("原有效期：未提供，不表示长期有效");
    expect(wrapper.text()).toContain("在现有人工事实录入中填写核验证据与实际结论");
    expect(wrapper.text()).toContain("查看原文核对区及对应来源字段");
  });

  it("keeps confirmation calendar, money inputs and maintenance observations attached to their own facts", async () => {
    const value = assessment(); value.summary = "WAITING_EXPECTED_CONFIRMATION"; value.freshUntil = null;
    const facts = value.rules[0]!.facts; value.rules[0]!.state = "WAITING_OFFICIAL_CONFIRMATION";
    facts.expectedTarget = { kind: "OFFICIAL_CLOSE", trade_date: "2026-11-16" };
    facts.expectedConfirmation = { target: facts.expectedTarget, expectedAt: "2026-11-16T15:00:00+08:00",
      observation: observation(), calendarReference: "calendar-1", priorInputsComplete: true };
    facts.money = { inputs: { axis: "INVENTORY_CAPITAL", state: "UNKNOWN", observation: observation("UNAVAILABLE") } };
    const risk = rule("UNKNOWN", "maintenance-only"); risk.facts.ownerKind = "RISK_BRANCH";
    risk.facts.evaluatedAt = null;
    risk.facts.risk = { current: null, maintenance: { axis: "DATA_EVALUATION", state: "PASS", observation: observation("CACHED") } };
    value.rules.push(risk);
    const wrapper = mountReadiness(vi.fn<typeof fetch>().mockResolvedValue(response(value))); await flushPromises();
    expect(wrapper.text()).toContain("预计确认：2026-11-16 15:00:00+08:00 · 待确认目标：官方收盘 · 交易日期 2026-11-16");
    expect(wrapper.text()).toContain("确认日历观察来源：当前读取");
    expect(wrapper.text()).toContain("金额输入观察来源：当前不可用");
    expect(wrapper.text()).toContain("风险维护观察来源：缓存记录");
    expect(wrapper.text()).toContain("本轮义务维护通过，未作新的条件比较");
    expect(wrapper.text()).not.toContain("监控已就绪");
  });

  it.each(["target-kind", "intraday-time", "close-date", "observation", "observation-time", "requirement",
    "window", "execution-date", "notification-target", "history-time"])("rejects malformed consumed %s details", async mutation => {
    const value = assessment(), facts = value.rules[0]!.facts;
    if (mutation === "target-kind") Object.assign(facts, { expectedTarget: { kind: "UNKNOWN" } });
    if (mutation === "intraday-time") Object.assign(facts, { evaluatedTarget: { kind: "INTRADAY", bucket_end: "10:05" } });
    if (mutation === "close-date") Object.assign(facts, { evaluatedTarget: { kind: "OFFICIAL_CLOSE", trade_date: "2026-02-30" } });
    if (mutation === "observation") Object.assign(value.axes[0]!, { observation: { ...observation(), availability: "READY" } });
    if (mutation === "observation-time") Object.assign(facts, { observation: { ...observation(), observedAt: "yesterday" } });
    if (mutation === "requirement") Object.assign(facts, { requirements: { inventory: "true" } });
    if (mutation === "window") Object.assign(facts, { execution: { executionWindow: "FOREVER" } });
    if (mutation === "execution-date") Object.assign(facts, { execution: { executionDate: "2026-13-01" } });
    if (mutation === "notification-target") Object.assign(facts, { notification: { target: { kind: "INTRADAY", bucket_end: "later" } } });
    if (mutation === "history-time") Object.assign(facts, { notification: { channels: [{ channel: "IN_APP", historicalUpdatedAt: "earlier" }] } });
    await expect(createPlanReadinessApi(vi.fn<typeof fetch>().mockResolvedValue(response(value))).get(A))
      .rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("aborts and discards old A→B→A responses even if fetch ignores abort", async () => {
    vi.useFakeTimers(); vi.setSystemTime(NOW);
    const old = deferred<Response>(), middle = deferred<Response>();
    const fetcher = vi.fn<typeof fetch>().mockImplementationOnce(() => old.promise)
      .mockImplementationOnce(() => middle.promise).mockResolvedValueOnce(response({ ...assessment(), summary: "NEEDS_REVIEW" }));
    const wrapper = mountReadiness(fetcher);
    await wrapper.setProps({ context: context(B, 2) });
    expect(fetcher.mock.calls[0]?.[1]?.signal?.aborted).toBe(true);
    await wrapper.setProps({ context: context(A, 3) }); await flushPromises();
    old.resolve(response(assessment())); middle.resolve(response(assessment(B))); await flushPromises();
    expect(wrapper.text()).toContain("需要核对来源与审核");
    expect(wrapper.text()).not.toContain("监控已就绪");
    await wrapper.setProps({ context: null });
    expect(wrapper.text()).not.toContain("需要核对来源与审核");
    expect(wrapper.text()).toContain("保存当前编辑");
  });

  it.each(["contentHash", "sourceHash", "reviewReceiptHash", "coverageHash"])("rejects mismatched saved %s bindings", async field => {
    const value = assessment(); Object.assign(value.snapshot.context, { [field]: "d".repeat(64) });
    const wrapper = mountReadiness(vi.fn<typeof fetch>().mockResolvedValue(response(value)), { ...context(), coverageHash: HASH });
    await flushPromises(); expect(wrapper.text()).not.toContain("监控已就绪");
    expect(wrapper.text()).toContain("当前保存版本或审核依据已变化");
  });

  it("removes READY at expiry, including a resumed tab with delayed timers", async () => {
    vi.useFakeTimers(); vi.setSystemTime(NOW);
    const wrapper = mountReadiness(vi.fn<typeof fetch>().mockResolvedValue(response(assessment())));
    await flushPromises(); await vi.advanceTimersByTimeAsync(60_000);
    expect(wrapper.text()).not.toContain("监控已就绪"); expect(wrapper.text()).toContain("已过期");
    await wrapper.get('[data-action="refresh"]').trigger("click"); vi.setSystemTime(NOW); await flushPromises();
    // Simulate a sleeping tab: advance the wall clock without running timers.
    vi.setSystemTime(NOW + 120_000); window.dispatchEvent(new Event("pageshow")); await flushPromises();
    expect(wrapper.text()).not.toContain("监控已就绪");
  });

  it("does not retain READY after a failed refresh or claim indefinite freshness", async () => {
    vi.useFakeTimers(); vi.setSystemTime(NOW);
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(response(assessment())).mockRejectedValueOnce(new Error("private error"));
    const wrapper = mountReadiness(fetcher); await flushPromises();
    await wrapper.get('[data-action="refresh"]').trigger("click"); await flushPromises();
    expect(wrapper.text()).not.toContain("监控已就绪"); expect(wrapper.text()).not.toContain("private error");
    const value = assessment(); value.freshUntil = null;
    fetcher.mockResolvedValueOnce(response(value)); await wrapper.get('[data-action="refresh"]').trigger("click"); await flushPromises();
    expect(wrapper.text()).not.toContain("监控已就绪"); expect(wrapper.text()).toContain("新鲜期");
  });

  it("expires on the original elapsed deadline even if the wall clock moves backwards", async () => {
    vi.useFakeTimers(); vi.setSystemTime(NOW);
    const wrapper = mountReadiness(vi.fn<typeof fetch>().mockResolvedValue(response(assessment())));
    await flushPromises(); vi.setSystemTime(NOW - 3_600_000);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(wrapper.text()).not.toContain("监控已就绪"); expect(wrapper.text()).toContain("已过期");
  });

  it.each(["before", "during"])("bounds freshness when the wall clock rolls back %s the request", async when => {
    vi.useFakeTimers(); vi.setSystemTime(when === "before" ? NOW - 3_600_000 : NOW);
    const pending = deferred<Response>();
    const wrapper = mountReadiness(vi.fn<typeof fetch>().mockImplementation(() => pending.promise));
    await vi.advanceTimersByTimeAsync(20_000);
    vi.setSystemTime(NOW - 3_600_000); pending.resolve(response(assessment())); await flushPromises();
    expect(wrapper.text()).toContain("监控已就绪");
    // Resume after the monotonic deadline, while a sleeping tab's timer is delayed.
    vi.spyOn(performance, "now").mockReturnValue(performance.now() + 40_001);
    document.dispatchEvent(new Event("visibilitychange")); await flushPromises();
    expect(wrapper.text()).not.toContain("监控已就绪"); expect(wrapper.text()).toContain("已过期");
  });

  it("keeps normal waits, unknown and first evaluation distinct", async () => {
    const value = assessment(); value.summary = "UNKNOWN"; value.freshUntil = null;
    value.rules = [rule("UNKNOWN"), rule("AWAITING_FIRST_EVALUATION", "first"), rule("WAITING_OFFICIAL_CONFIRMATION", "close")];
    value.rules[2]!.facts.expectedConfirmation = { target: { kind: "OFFICIAL_CLOSE", trade_date: "2026-11-14" },
      expectedAt: stamp(18_000_000), priorInputsComplete: true, calendarReference: "calendar", observation: {
        context: value.snapshot.context, availability: "CURRENT", observedAt: stamp(), asOf: null,
        expiresAt: stamp(18_000_000), evidenceRefs: ["calendar"],
      } };
    const wrapper = mountReadiness(vi.fn<typeof fetch>().mockResolvedValue(response(value))); await flushPromises();
    expect(wrapper.text()).toContain("尚未确定"); expect(wrapper.text()).toContain("等待首次评估");
    expect(wrapper.text()).toContain("正常等待官方确认"); expect(wrapper.text()).toContain("2026-11-14");
  });

  it("separates latched risk maintenance, checked money and historic delivery from current eligibility", async () => {
    const value = assessment(); value.summary = "UNKNOWN"; value.freshUntil = null;
    const risk = rule("UNKNOWN", "original-risk");
    risk.facts.ownerKind = "RISK_BRANCH"; risk.facts.side = "SELL"; risk.facts.evaluatedAt = null;
    risk.facts.risk = { current: null, maintenance: { axis: "DATA_EVALUATION", state: "PASS" },
      obligation: { riskId: "risk-1", revision: 2, kind: "ORDINARY_TECHNICAL", status: "CONFIRMED",
        confirmedTradeDate: "2026-11-13", earliestExecutionDate: "2026-11-14", fulfilledAt: null, blockers: [] } };
    risk.facts.notification = { eventId: B, createdAt: stamp(-1000), channels: [{ channel: "IN_APP", configured: true,
      enabled: true, eligible: false, historicalStatus: "SUPPRESS", historicalUpdatedAt: stamp(), latestAttempt: {
        id: "receipt-1", eventId: B, channel: "IN_APP", attempt: 1, status: "DELIVERED", deliveredAt: stamp(-500),
      } }] };
    value.rules = [risk];
    const money = rule("CONDITION_FALSE", "checked-buy");
    money.facts.execution = { approvedQuantity: 100, eligible: false, windowState: "OPEN" };
    money.facts.money = { inputs: { axis: "INVENTORY_CAPITAL", state: "PASS" }, capital: {
      version: "capital-limit-evidence-v1", mode: "MARKET_VALUE_CAP", phase: "CURRENT", policy_hash: HASH,
      outcome: "FAIL", quantity: 200, price_fen: 1000, total_qty: 100, inventory_revision: 1, book_revision: null,
      cap_fen: 200000, before_fen: 100000, after_fen: 300000, remaining_fen: -100000,
      share_capacity: { mode: "UNBOUNDED" }, buy_debit: null, blockers: ["CAPITAL_LIMIT_EXCEEDED"], evidence_hash: HASH,
    }, economics: { version: "p2-economics-v1", outcome: "FAIL", quantity: 200,
      blockers: ["EXPECTED_REWARD_TOO_LOW"], reason: "EXPECTED_REWARD_TOO_LOW" } };
    value.rules.push(money);
    const wrapper = mountReadiness(vi.fn<typeof fetch>().mockResolvedValue(response(value))); await flushPromises();
    expect(wrapper.text()).toContain("本轮义务维护通过，未作新的条件比较");
    expect(wrapper.text()).toContain("风险义务：已确认"); expect(wrapper.text()).not.toContain("条件已成立");
    expect(wrapper.text()).toContain("当前发送资格：不符合"); expect(wrapper.text()).toContain("历史分类：已抑制");
    expect(wrapper.text()).toContain("历史发送结果：已送达"); expect(wrapper.text()).toContain("原属依据未验证");
    expect(wrapper.text()).toContain("原批准数量：100");
    expect(wrapper.text()).toContain("被检查数量：200（不是批准数量）");
    expect(wrapper.text()).toContain("费用收益检查：未通过");
    await wrapper.get('[data-action="source"]').trigger("click"); expect(wrapper.emitted("revealSource")).toHaveLength(1);
  });
});

describe("actual workbench readiness integration", () => {
  it("uses current coverage receipt bindings and clears during edits, operations and version switches", async () => {
    vi.stubGlobal("crypto", webcrypto); vi.useFakeTimers(); vi.setSystemTime(NOW);
    const hash = (value: string) => createHash("sha256").update(value).digest("hex");
    const source = "最大计划持仓300股。";
    function version(id: string): PlanVersionView {
      const planJson = JSON.stringify({ schema_version: 5, execution_mode: "CONDITION_PLAN", execution_version: "condition-plan-v1",
        plan_id: "wire-plan", version: id === A ? 1 : 2, symbol: "600000.SH", name: "Wire plan", position: { max_qty: 300 },
        ordinary_rules: [{ rule_id: "buy-one" }] });
      const mapping = { mapping_version: "daily-mapping-v1" as const, candidate_content_hash: HASH,
        clauses: [], bindings: [], supplements: [] };
      const saved: PlanVersionView = { id, planId: "wire-plan", version: id === A ? 1 : 2, symbol: "600000.SH", planJson,
        sourceText: source, planHash: hash(planJson), contentHash: HASH, sourceHash: hash(source),
        reviewEvidenceHash: "d".repeat(64), reviewId: B, reviewRevision: 1, dailyMapping: mapping, dailyIssues: [],
        status: "ACTIVE", canActivate: true, revision: 1, createdAt: "2026-11-14T09:59:59+08:00" };
      const summary: SourceCoverageSummaryView = { authorityGranted: false, status: "COMPLETE", coverageComplete: true,
        currentReviewBound: true, canConfirmReview: false, reviewState: "CURRENT", reason: null, sourceHash: saved.sourceHash!,
        candidatePlanHash: saved.planHash, contentHash: HASH, mappingHash: HASH, rulesVersion: "source-coverage-rules-v1",
        coverageEvidenceHash: HASH, coverageRevision: 1, coverageBundleHash: HASH, normalizationHash: null,
        originalReviewEvidenceHash: saved.reviewEvidenceHash!, reviewId: B, reviewRevision: 1, coverageReviewReceiptHash: RECEIPT,
        origin: "HUMAN", automaticFidelityVerified: false, obligationCount: 1, issueCount: 0, normalizationChangeCount: 0, totalRows: 1 };
      saved.sourceCoverage = summary; return saved;
    }
    const records = new Map([A, B].map(id => [id, version(id)]));
    const calls: string[] = [], old = deferred<Response>();
    let hold = false, coverageFail = false;
    let coverageWait: Promise<void> | null = null;
    const fetcher = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input); calls.push(url);
      const id = url.split("/")[4]!, saved = records.get(id);
      if (url.endsWith("/monitor-readiness")) {
        if (hold) { hold = false; return old.promise; }
        const value = assessment(id); value.snapshot.context.sourceHash = saved!.sourceHash!;
        return response(value);
      }
      if (url.includes("/source-coverage?")) {
        if (coverageWait) await coverageWait;
        if (coverageFail) return response({ code: "READ_FAILED" }, 503);
        return response({ authorityGranted: false, planVersionId: id,
        summary: saved!.sourceCoverage, limit: 50, returnedCount: 1, totalRows: 1, nextCursor: null, items: [{ kind: "OBLIGATION", rowIndex: 0,
          obligation: { version: "source-obligation-v1", rulesVersion: "source-coverage-rules-v1", sourceHash: saved!.sourceHash,
            clauseId: "c1", start: 0, end: Array.from(source).length, excerpt: source, kind: "PREDICATE", scope: "PLAN", serverState: "MAPPED",
            semanticsJson: null, groupId: null, relationIds: [], paths: ["position.max_qty"], obligationId: HASH, mappingProposal: null, humanSupplements: [] } }] });
      }
      if (url.endsWith("/plan-editor-schema")) return response({ candidateSchema: { type: "object", properties: {
        position: { type: "object", properties: { max_qty: { type: "integer" } } },
        ordinary_rules: { type: "array", items: { type: "object", properties: { rule_id: { type: "string" } } } },
      } }, operationSchemas: {} });
      if (url.endsWith("/ai-runtime")) return response({ providerId: A, configured: false, enabled: false,
        displayName: "wire", baseUrl: "https://example.test", model: "wire", revision: 0, maxInputChars: 50000, maxOutputTokens: 4096 });
      if (url.endsWith("/plan-review-previews")) {
        const body = JSON.parse(String(init?.body));
        return response({ candidateJson: body.candidateJson, supplementRevision: 0, review: {
          content_hash: HASH, source_hash: hash(body.sourceText), evidence_hash: "d".repeat(64), mapping: body.mapping, issues: [],
        } });
      }
      if (url.includes("/plan-versions?")) return response({ items: [], total: 0, offset: 0, limit: 100 });
      if (url.includes("/plan-versions/")) return response(saved);
      if (url.includes("/plan-activation-states/")) return response({ active: true, planVersionId: A, revision: 1, symbol: "600000.SH", changedAt: "2026-11-14T10:00:00+08:00" });
      throw new Error(`Unexpected request ${url}`);
    });
    const wrapper = mount(PlanWorkbench, { props: { planVersionId: A }, attachTo: document.body,
      global: { provide: { [apiFetchKey as symbol]: fetcher }, stubs: { PlanSimulationPanel: true, PlanSourceExtraction: true } } });
    wrappers.push(wrapper);
    const work = (wrapper.vm as unknown as { work: ReturnType<typeof usePlanWorkspace> }).work;
    for (let i = 0; i < 5; i++) await flushPromises();
    await vi.waitFor(() => expect(wrapper.findComponent(PlanReadiness).text(),
      JSON.stringify({ error: work.error.value, phase: work.sourceCoverage.phase.value,
        coverageError: work.sourceCoverage.safeError.value, calls })).toContain("监控已就绪"));
    expect(calls.filter(url => url.endsWith("/monitor-readiness"))).toHaveLength(1);
    await wrapper.findComponent(PlanReadiness).get('[data-action="source"]').trigger("click");
    expect(document.activeElement).toBe(wrapper.get('[id="daily-.ordinary_rules[0].rule_id"]').element);
    work.sourceCoverage.invalidate(); await flushPromises();
    expect(wrapper.findComponent(PlanReadiness).text()).toContain("已保存版本的来源覆盖依据已失效");
    expect(wrapper.findComponent(PlanReadiness).text()).not.toContain("请先保存");
    const coverageGate = deferred<void>(); coverageWait = coverageGate.promise;
    const coverageRead = work.sourceCoverage.refresh(); await flushPromises();
    expect(wrapper.findComponent(PlanReadiness).text()).toContain("已保存，正在读取匹配的来源覆盖依据");
    expect(calls.filter(url => url.endsWith("/monitor-readiness"))).toHaveLength(1);
    coverageFail = true; coverageGate.resolve(); await coverageRead; await flushPromises();
    expect(wrapper.findComponent(PlanReadiness).text()).toContain("已保存版本的来源覆盖依据读取失败");
    expect(wrapper.findComponent(PlanReadiness).text()).not.toContain("请先保存");
    coverageFail = false; coverageWait = null; await work.sourceCoverage.refresh(); await flushPromises();
    expect(wrapper.findComponent(PlanReadiness).text()).toContain("监控已就绪");
    work.editSource(source + "修改"); await flushPromises();
    expect(wrapper.findComponent(PlanReadiness).text()).not.toContain("监控已就绪");
    await wrapper.setProps({ planVersionId: B });
    await vi.waitFor(() => expect(wrapper.findComponent(PlanReadiness).text()).toContain("监控已就绪"));
    const operation = deferred<void>();
    const pending = work.action(() => operation.promise); await flushPromises();
    expect(wrapper.findComponent(PlanReadiness).text()).not.toContain("监控已就绪");
    operation.resolve(); await pending; for (let i = 0; i < 3; i++) await flushPromises();
    await vi.waitFor(() => expect(wrapper.findComponent(PlanReadiness).text()).toContain("监控已就绪"));
    hold = true;
    await wrapper.findComponent(PlanReadiness).get('[data-action="refresh"]').trigger("click");
    await wrapper.setProps({ planVersionId: A });
    await vi.waitFor(() => expect(wrapper.findComponent(PlanReadiness).text()).toContain("监控已就绪"));
    const stale = assessment(B); stale.summary = "BLOCKED"; stale.snapshot.context.sourceHash = hash(source);
    old.resolve(response(stale)); await flushPromises();
    expect(wrapper.findComponent(PlanReadiness).text()).toContain("监控已就绪");
    expect(wrapper.findComponent(PlanReadiness).text()).not.toContain("存在阻断");
  });
});
