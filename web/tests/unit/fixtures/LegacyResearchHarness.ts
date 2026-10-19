// Exercise the retained scripted-research form/API separately from the normal creation page.
import { defineComponent } from "vue";
import { isNavigationFailure, useRouter } from "vue-router";
import type { PropType } from "vue";
import type { BacktestApi } from "../../../src/api/backtests";
import type { PlanApi } from "../../../src/api/plans";
import BacktestRunForm from "../../../src/components/backtests/BacktestRunForm.vue";
import BacktestReferenceMarketCoveragePanel from "../../../src/components/backtests/BacktestReferenceMarketCoveragePanel.vue";
import { useBacktestRunForm } from "../../../src/composables/useBacktestRunForm";
import { useBacktestPlanVersions } from "../../../src/composables/useBacktestPlanVersions";

export default defineComponent({
  components: { BacktestRunForm, BacktestReferenceMarketCoveragePanel },
  props: {
    api: { type: Object as PropType<BacktestApi>, required: true },
    planApi: { type: Object as PropType<PlanApi>, required: true },
    createIdempotencyKey: { type: Function as PropType<() => string>, required: false },
  },
  setup(props) {
    const router = useRouter();
    const plans = useBacktestPlanVersions({ api: props.planApi });
    const form = useBacktestRunForm({ api: props.api,
      ...(props.createIdempotencyKey ? { createIdempotencyKey: props.createIdempotencyKey } : {}),
      onAccepted: async receipt => {
        if (!receipt.runId) return;
        const failure = await router.push({ path: `/backtests/${receipt.runId}`,
          ...(receipt.status === "COMPLETED" ? {} : { query: { jobId: receipt.jobId } }) });
        if (isNavigationFailure(failure)) throw new Error("accepted run navigation failed");
      },
    });
    function select(id: string) { form.updateField("planVersionId", plans.selectVersion(id)?.id ?? ""); }
    return { form, plans, select };
  },
  template: `<div>
    <BacktestRunForm :draft="form.draft.value" :error-revision="form.errorRevision.value" :errors="form.errors.value"
      :plan-version-error="plans.errorMessage.value" :plan-version-page="plans.page.value" :plan-version-state="plans.state.value"
      :selected-plan-version="plans.selectedVersion.value" :submission-state="form.submissionState.value"
      @select-plan-version="select" @next-plan-version-page="plans.nextPage" @previous-plan-version-page="plans.previousPage"
      @retry-plan-versions="plans.retry" @submit="form.submit" @update-field="form.updateField" @add-lot="form.addLot" @remove-lot="form.removeLot" @update-lot="form.updateLot" />
    <BacktestReferenceMarketCoveragePanel :coverage="form.referenceMarketCoverage.value" :error="form.referenceMarketCoverageError.value" :state="form.referenceMarketCoverageState.value" />
    <p v-if="form.submissionErrorMessage.value" role="alert">{{ form.submissionErrorMessage.value }}</p>
    <button v-if="form.submissionState.value === 'UNCERTAIN'" data-testid="retry-run-submission" type="button" @click="form.retrySubmission">使用同一请求安全重试</button>
  </div>`,
});
