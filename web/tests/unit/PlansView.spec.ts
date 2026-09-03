import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import type {
  ActivePlanView,
  PlanDraftCommand,
  PlanVersionSummary,
  PlanVersionView,
} from "../../src/api/generated";
import PlansView from "../../src/views/PlansView.vue";

const activePlanJson = JSON.stringify({
  schema_version: 1,
  plan_id: "huaya-smart",
  version: 1,
  symbol: "003043.SZ",
  name: "华亚智能旧方案",
  market: "SZSE",
  metadata: { report_at: "2026-08-06T01:16:00+08:00", reference_price_fen: 6660 },
  activation: { mode: "MANUAL" },
  position: { core_target_qty: 100, lot_size: 100, max_qty: 200, tactical_target_qty: 100 },
  levels: {
    low_buy: { high_fen: 6400, include_high: true, include_low: true, low_fen: 6300 },
    pressure: { high_fen: 7000, include_high: true, include_low: true, low_fen: 6880 },
    pressure_reference_fen: 6906,
    risk_line_fen: 6080,
  },
  entry: { condition: { conditions: [], type: "ALL" } },
  reduction: { condition: { conditions: [], type: "ALL" } },
  risk: { condition: { level: "RISK_LINE", type: "OFFICIAL_CLOSE_BELOW_LEVEL" } },
  blockers: { condition: { conditions: [], type: "ALL" } },
  monitoring: { indicator_formula_version: "ta-v1", timeframe_minutes: 5 },
});

const candidatePlanJson = JSON.stringify({
  ...JSON.parse(activePlanJson),
  version: 2,
  name: "华亚智能审核方案",
  levels: {
    ...JSON.parse(activePlanJson).levels,
    low_buy: { high_fen: 6450, include_high: true, include_low: true, low_fen: 6300 },
    pressure: { high_fen: 7020, include_high: true, include_low: true, low_fen: 6880 },
  },
});

function planVersion(overrides: Partial<PlanVersionView> = {}): PlanVersionView {
  return {
    canActivate: true,
    createdAt: "2026-08-24T12:00:00+08:00",
    id: "00000000-0000-0000-0000-000000000402",
    planHash: "b".repeat(64),
    planId: "huaya-smart",
    planJson: candidatePlanJson,
    revision: 5,
    sourceText: "华亚智能交易计划原文",
    status: "DRAFT",
    symbol: "003043.SZ",
    version: 2,
    ...overrides,
  };
}

const activeVersion = planVersion({
  id: "00000000-0000-0000-0000-000000000401",
  planHash: "a".repeat(64),
  planJson: activePlanJson,
  revision: 4,
  status: "ACTIVE",
  version: 1,
});
const candidateVersion = planVersion();
const activeState: ActivePlanView = {
  active: true,
  changedAt: "2026-08-24T12:05:00+08:00",
  planVersionId: activeVersion.id,
  revision: 5,
  symbol: "003043.SZ",
};

function planSummary(plan: PlanVersionSummary): PlanVersionSummary {
  return {
    canActivate: plan.canActivate,
    createdAt: plan.createdAt,
    id: plan.id,
    planHash: plan.planHash,
    planId: plan.planId,
    revision: plan.revision,
    status: plan.status,
    symbol: plan.symbol,
    version: plan.version,
  };
}

function isPlanDetail(plan: PlanVersionSummary): plan is PlanVersionView {
  return "planJson" in plan;
}

function mountView(
  props: Partial<InstanceType<typeof PlansView>["$props"]> = {},
  attachTo?: HTMLElement,
) {
  const suppliedVersions = (props.versions ?? [candidateVersion, activeVersion]) as readonly (
    | PlanVersionSummary
    | PlanVersionView
  )[];
  const resolvedActiveState = Object.hasOwn(props, "activeState")
    ? (props.activeState ?? null)
    : activeState;
  const selectedPlanId = Object.hasOwn(props, "selectedPlanId")
    ? (props.selectedPlanId ?? null)
    : candidateVersion.id;
  const selectedPlan = Object.hasOwn(props, "selectedPlan")
    ? (props.selectedPlan ?? null)
    : (suppliedVersions.find(
        (plan): plan is PlanVersionView =>
          plan.id === selectedPlanId && isPlanDetail(plan),
      ) ?? null);
  const activePlan = Object.hasOwn(props, "activePlan")
    ? (props.activePlan ?? null)
    : (suppliedVersions.find(
        (plan): plan is PlanVersionView =>
          plan.id === resolvedActiveState?.planVersionId && isPlanDetail(plan),
      ) ?? null);
  return mount(PlansView, {
    ...(attachTo === undefined ? {} : { attachTo }),
    props: {
      activePlan,
      activeState: resolvedActiveState,
      busy: props.busy ?? false,
      selectedPlan,
      selectedPlanId,
      versions: suppliedVersions.map(planSummary),
    },
  });
}

describe("PlansView", () => {
  it("edits typed plan sections and emits a revision-guarded draft command", async () => {
    const wrapper = mountView();
    const name = wrapper.get<HTMLInputElement>("#plan-name");
    const levels = wrapper.get<HTMLTextAreaElement>('[data-section="levels"]');

    expect(wrapper.findAll('[data-testid="plan-section"]')).toHaveLength(9);
    await name.setValue("华亚智能人工修订方案");
    await levels.setValue(
      JSON.stringify({
        ...JSON.parse(levels.element.value),
        risk_line_fen: 6100,
      }),
    );
    await wrapper.get('[data-testid="save-draft"]').trigger("click");

    const command = wrapper.emitted("saveDraft")?.[0]?.[0] as PlanDraftCommand;
    expect(command.expectedRevision).toBe(5);
    expect(command.basePlanVersionId).toBe(candidateVersion.id);
    expect(command.sourceText).toBe(candidateVersion.sourceText);
    expect(command.reviewIssues).toEqual([]);
    expect(JSON.parse(command.planJson)).toMatchObject({
      name: "华亚智能人工修订方案",
      levels: { risk_line_fen: 6100 },
    });
    expect(candidateVersion.planJson).toBe(candidatePlanJson);
  });

  it("renders a human-readable executable preview without evaluating rules", () => {
    const wrapper = mountView();

    expect(wrapper.get('[data-testid="executable-preview"]').text()).toContain(
      "低吸区间 63.00–64.50 元",
    );
    expect(wrapper.get('[data-testid="executable-preview"]').text()).toContain(
      "压力区间 68.80–70.20 元",
    );
    expect(wrapper.get('[data-testid="executable-preview"]').text()).toContain(
      "风险线 60.80 元",
    );
    expect(wrapper.get('[data-testid="executable-preview"]').text()).toContain(
      "入场条件 ALL",
    );
  });

  it("shows validation paths and blocks activation for authoritative blockers", () => {
    const blocked = planVersion({
      canActivate: true,
      reviewIssues: [
        { kind: "WARNING", material: true, path: "entry.condition", resolved: false },
      ],
      validationIssues: [
        {
          activationBlocking: true,
          code: "ZONE_OVERLAP",
          message: "价格区间重叠。",
          path: "levels.low_buy",
          severity: "ERROR",
        },
      ],
    });
    const wrapper = mountView({ selectedPlanId: blocked.id, versions: [blocked, activeVersion] });

    expect(wrapper.text()).toContain("levels.low_buy");
    expect(wrapper.text()).toContain("ZONE_OVERLAP");
    expect(wrapper.text()).toContain("entry.condition");
    expect(wrapper.get('[data-testid="request-activation"]').attributes("disabled")).toBeDefined();
  });

  it("rejects an oversized import locally without truncating or emitting it", async () => {
    const wrapper = mountView();
    const oversizedDocument = "数".repeat(256 * 1_024);

    await wrapper.get<HTMLTextAreaElement>("#plan-import-document").setValue(oversizedDocument);
    await wrapper.get('[data-testid="import-plan"]').trigger("submit");

    expect(wrapper.text()).toContain("超过 256 KiB 上限");
    expect(wrapper.get<HTMLTextAreaElement>("#plan-import-document").element.value).toBe("");
    expect(wrapper.emitted("importPlan")).toBeUndefined();
  });

  it("atomically rejects an oversized edited draft before command emission", async () => {
    const wrapper = mountView();
    const originalName = wrapper.get<HTMLInputElement>("#plan-name").element.value;

    await wrapper.get<HTMLInputElement>("#plan-name").setValue("a".repeat(256 * 1_024));

    expect(wrapper.get<HTMLInputElement>("#plan-name").element.value).toBe(originalName);
    expect(wrapper.text()).toContain("计划文档超过 256 KiB 上限");
    expect(wrapper.get('[data-testid="save-draft"]').attributes("disabled")).toBeDefined();
    expect(wrapper.emitted("saveDraft")).toBeUndefined();
  });

  it("emits bounded YAML import and JSON/YAML export intents", async () => {
    const wrapper = mountView();
    const importDocument = "schema_version: 1\nsymbol: 003043.SZ\n";

    await wrapper.get<HTMLSelectElement>("#plan-import-format").setValue("YAML");
    await wrapper.get<HTMLTextAreaElement>("#plan-import-document").setValue(importDocument);
    await wrapper.get('[data-testid="import-plan"]').trigger("submit");
    expect(wrapper.emitted("importPlan")).toEqual([
      [
        {
          document: importDocument,
          expectedRevision: 5,
          format: "YAML",
          symbol: candidateVersion.symbol,
        },
      ],
    ]);
    expect(wrapper.get<HTMLInputElement>("#plan-import-symbol").element.value).toBe(
      candidateVersion.symbol,
    );

    await wrapper.get<HTMLSelectElement>("#plan-export-format").setValue("JSON");
    await wrapper.get('[data-testid="export-plan"]').trigger("click");
    expect(wrapper.emitted("exportPlan")).toEqual([
      [
        {
          format: "JSON",
          planJson: candidateVersion.planJson,
          planVersionId: candidateVersion.id,
        },
      ],
    ]);
  });

  it("preserves local edits on revision conflict and reloads only on explicit recovery", async () => {
    const wrapper = mountView();
    const name = wrapper.get<HTMLInputElement>("#plan-name");
    await name.setValue("本地未保存名称");

    const serverPlan = planVersion({
      planJson: JSON.stringify({ ...JSON.parse(candidatePlanJson), name: "服务器新名称" }),
      revision: 6,
    });
    await wrapper.setProps({
      selectedPlan: serverPlan,
      versions: [planSummary(serverPlan), planSummary(activeVersion)],
    });

    expect(wrapper.get('[data-testid="revision-conflict"]').text()).toContain("修订 6");
    expect(name.element.value).toBe("本地未保存名称");
    await wrapper.get('[data-testid="reload-server-version"]').trigger("click");
    expect(name.element.value).toBe("服务器新名称");
  });

  it("labels active-version changes as a new draft instead of editing in place", async () => {
    const wrapper = mountView({ selectedPlanId: activeVersion.id });

    expect(wrapper.get('[data-testid="save-draft"]').text()).toContain("另存为新草稿");
    await wrapper.get<HTMLInputElement>("#plan-name").setValue("活动方案派生草稿");
    await wrapper.get('[data-testid="save-draft"]').trigger("click");

    const command = wrapper.emitted("saveDraft")?.[0]?.[0] as PlanDraftCommand;
    expect(command.expectedRevision).toBe(activeVersion.revision);
    expect(command.basePlanVersionId).toBe(activeVersion.id);
    expect(activeVersion.status).toBe("ACTIVE");
    expect(JSON.parse(activeVersion.planJson).name).toBe("华亚智能旧方案");
  });

  it("shows before/after differences and requires explicit activation confirmation", async () => {
    const wrapper = mountView();

    await wrapper.get('[data-testid="request-activation"]').trigger("click");
    expect(wrapper.get('[role="dialog"]').text()).toContain("华亚智能旧方案");
    expect(wrapper.get('[role="dialog"]').text()).toContain("华亚智能审核方案");
    expect(wrapper.get('[role="dialog"]').text()).toContain("levels");
    expect(wrapper.get('[data-testid="confirm-plan-action"]').attributes("disabled")).toBeDefined();

    await wrapper.get<HTMLInputElement>("#confirm-plan-action").setValue(true);
    await wrapper.get('[data-testid="confirm-plan-action"]').trigger("click");
    expect(wrapper.emitted("activatePlan")).toEqual([
      [{ expectedRevision: activeState.revision, planVersionId: candidateVersion.id }],
    ]);
  });

  it("requires a separate confirmation before deactivation", async () => {
    const wrapper = mountView({ selectedPlanId: activeVersion.id });

    await wrapper.get('[data-testid="request-deactivation"]').trigger("click");
    expect(wrapper.get('[role="dialog"]').text()).toContain("全部配置（停用）");
    await wrapper.get<HTMLInputElement>("#confirm-plan-action").setValue(true);
    await wrapper.get('[data-testid="confirm-plan-action"]').trigger("click");

    expect(wrapper.emitted("deactivatePlan")).toEqual([
      [{ expectedRevision: activeState.revision, symbol: activeVersion.symbol }],
    ]);
  });

  it("does not allow activation while the selected draft has unsaved edits", async () => {
    const wrapper = mountView();

    await wrapper.get<HTMLInputElement>("#plan-name").setValue("尚未保存的名称");

    expect(wrapper.get('[data-testid="request-activation"]').attributes("disabled")).toBeDefined();
    expect(wrapper.text()).toContain("先保存并重新取得后端校验结果");
  });

  it("does not clear unsaved state when the selected version is clicked again", async () => {
    const wrapper = mountView();
    const name = wrapper.get<HTMLInputElement>("#plan-name");
    await name.setValue("仍未保存的名称");

    await wrapper.get('[aria-current="page"]').trigger("click");

    expect(name.element.value).toBe("仍未保存的名称");
    expect(wrapper.get('[data-testid="request-activation"]').attributes("disabled")).toBeDefined();
  });

  it("requires explicit discard confirmation before switching a dirty editor", async () => {
    const wrapper = mountView();
    const name = wrapper.get<HTMLInputElement>("#plan-name");
    await name.setValue("待确认丢弃的名称");

    const activeButton = wrapper.findAll("nav button").find((button) => button.text().includes("v1"));
    expect(activeButton).toBeDefined();
    await activeButton!.trigger("click");

    expect(wrapper.get<HTMLInputElement>("#plan-name").element.value).toBe("待确认丢弃的名称");
    expect(wrapper.get('[data-testid="discard-selection-change"]').text()).toContain("放弃");
    await wrapper.get('[data-testid="confirm-selection-change"]').trigger("click");
    await wrapper.setProps({
      selectedPlan: activeVersion,
      selectedPlanId: activeVersion.id,
    });
    expect(wrapper.get<HTMLInputElement>("#plan-name").element.value).toBe("华亚智能旧方案");
  });

  it("keeps the dirty editor mounted when its version leaves the refreshed page", async () => {
    const wrapper = mountView();
    await wrapper.get<HTMLInputElement>("#plan-name").setValue("分页刷新前的本地草稿");

    await wrapper.setProps({
      selectedPlan: activeVersion,
      selectedPlanId: activeVersion.id,
      versions: [planSummary(activeVersion)],
    });

    expect(wrapper.get<HTMLInputElement>("#plan-name").element.value).toBe(
      "分页刷新前的本地草稿",
    );
    expect(wrapper.get('[data-testid="discard-selection-change"]').text()).toContain("放弃");
    await wrapper.get('[data-testid="confirm-selection-change"]').trigger("click");
    expect(wrapper.get<HTMLInputElement>("#plan-name").element.value).toBe("华亚智能旧方案");
  });

  it("fails closed when active-plan identity is missing or belongs to another symbol", async () => {
    const missingState = mountView({ activeState: null });
    expect(
      missingState.get('[data-testid="request-activation"]').attributes("disabled"),
    ).toBeDefined();

    const wrongSymbol = mountView({
      activeState: { ...activeState, symbol: "600000.SH" },
    });
    expect(
      wrongSymbol.get('[data-testid="request-activation"]').attributes("disabled"),
    ).toBeDefined();

    const wrongActiveVersion = mountView({
      activeState: { ...activeState, planVersionId: candidateVersion.id },
      selectedPlanId: activeVersion.id,
    });
    expect(
      wrongActiveVersion.get('[data-testid="request-deactivation"]').attributes("disabled"),
    ).toBeDefined();
  });

  it("uses the authoritative inactive revision for first activation", async () => {
    const inactiveState: ActivePlanView = {
      active: false,
      changedAt: "2026-08-24T11:55:00+08:00",
      planVersionId: null,
      revision: 0,
      symbol: candidateVersion.symbol,
    };
    const wrapper = mountView({ activeState: inactiveState, versions: [candidateVersion] });

    expect(
      wrapper.get('[data-testid="request-activation"]').attributes("disabled"),
    ).toBeUndefined();
    await wrapper.get('[data-testid="request-activation"]').trigger("click");
    await wrapper.get<HTMLInputElement>("#confirm-plan-action").setValue(true);
    await wrapper.get('[data-testid="confirm-plan-action"]').trigger("click");

    expect(wrapper.emitted("activatePlan")).toEqual([
      [{ expectedRevision: 0, planVersionId: candidateVersion.id }],
    ]);
  });

  it("invalidates confirmation when the reviewed diff identity changes", async () => {
    const wrapper = mountView();
    await wrapper.get('[data-testid="request-activation"]').trigger("click");
    await wrapper.get<HTMLInputElement>("#confirm-plan-action").setValue(true);
    expect(
      wrapper.get('[data-testid="confirm-plan-action"]').attributes("disabled"),
    ).toBeUndefined();

    const refreshedCandidate = planVersion({
      planHash: "c".repeat(64),
      planJson: JSON.stringify({ ...JSON.parse(candidatePlanJson), name: "刷新后的候选方案" }),
      revision: 6,
    });
    await wrapper.setProps({
      activeState: { ...activeState, revision: 6 },
      selectedPlan: refreshedCandidate,
      versions: [planSummary(refreshedCandidate), planSummary(activeVersion)],
    });

    expect(wrapper.get('[data-testid="confirm-plan-action"]').attributes("disabled")).toBeDefined();
    expect(wrapper.emitted("activatePlan")).toBeUndefined();
  });

  it("closes an open confirmation when authoritative active identity becomes invalid", async () => {
    const wrapper = mountView();
    await wrapper.get('[data-testid="request-activation"]').trigger("click");
    await wrapper.get<HTMLInputElement>("#confirm-plan-action").setValue(true);

    await wrapper.setProps({
      activeState: { ...activeState, symbol: "600000.SH" },
    });

    expect(wrapper.find('[role="dialog"]').exists()).toBe(false);
    expect(wrapper.emitted("activatePlan")).toBeUndefined();
    await wrapper.setProps({ activeState });
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false);
  });

  it("opens activation confirmation as a real modal and moves initial focus", async () => {
    const originalShowModal = Object.getOwnPropertyDescriptor(
      HTMLDialogElement.prototype,
      "showModal",
    );
    const showModal = vi.fn(function (this: HTMLDialogElement) {
      this.setAttribute("open", "");
    });
    Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
      configurable: true,
      value: showModal,
    });
    const host = document.createElement("div");
    document.body.append(host);

    try {
      const wrapper = mountView({}, host);
      const requestButton = wrapper.get<HTMLButtonElement>(
        '[data-testid="request-activation"]',
      );
      requestButton.element.focus();
      await requestButton.trigger("click");

      expect(showModal).toHaveBeenCalledOnce();
      expect(document.activeElement?.textContent).toContain("取消");
      const cancelButton = wrapper
        .get('[role="dialog"]')
        .findAll("button")
        .find((button) => button.text() === "取消");
      expect(cancelButton).toBeDefined();
      await cancelButton!.trigger("click");
      expect(document.activeElement).toBe(requestButton.element);
      wrapper.unmount();
    } finally {
      host.remove();
      if (originalShowModal === undefined) {
        delete (HTMLDialogElement.prototype as { showModal?: unknown }).showModal;
      } else {
        Object.defineProperty(HTMLDialogElement.prototype, "showModal", originalShowModal);
      }
    }
  });

  it("renders imported and server text as inert content", async () => {
    const hostile = '<script>globalThis.compromised=true</script><img src=x onerror=alert(1)>';
    const hostilePlan = planVersion({
      validationIssues: [
        {
          activationBlocking: true,
          code: "INVALID_PLAN",
          message: hostile,
          path: "name",
          severity: "ERROR",
        },
      ],
    });
    const wrapper = mountView({ selectedPlanId: hostilePlan.id, versions: [hostilePlan] });

    expect(wrapper.text()).toContain(hostile);
    expect(wrapper.find("script").exists()).toBe(false);
    expect(wrapper.find("img").exists()).toBe(false);
  });
});
