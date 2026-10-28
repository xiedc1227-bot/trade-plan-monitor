"""Complete synthetic API workflow inputs, separate from historical narrative fixtures."""

import json

from tests.integration.preparation_review_current_fixtures import (
    ACCOUNT_FACTS,
    field_source,
    reviewed_mapping,
    single_draft,
)
from tests.unit.test_monitor_loop_extraction import CASES, extract, output_for
from tests.unit.test_monitor_loop_schedule import at

from trade_plan_monitor.ai.loop_plan_extraction import LoopPlanExtractionOutput, OpeningAccountFacts
from trade_plan_monitor.backtest.preparation_models import (
    PreparationSource,
    SinglePlanPreparationInput,
)


def current_api_body():
    """Declare the reviewed 1000-share policy without changing the old 300-share source."""
    source = PreparationSource(source_id="source-1",
        text=field_source(single_draft(), tail=ACCOUNT_FACTS), authored_at=at(),
        available_at=at(), effective_trade_date=at().date())
    return {"input": SinglePlanPreparationInput(preparation_id="one", sources=(source,)).model_dump(
        mode="json")}


def _current_output(text):
    draft = single_draft()
    mapping = reviewed_mapping(draft, text)
    opening = OpeningAccountFacts.model_validate_json(json.dumps(
        output_for(CASES[0] | {"source": text})["opening_account"]))
    return LoopPlanExtractionOutput(schema_version="monitor-loop-extraction-v1", draft=draft,
        clauses=mapping.clauses, bindings=mapping.bindings, opening_account=opening)


def current_api_ai(*, blocked=False):
    """Keep the real API worker/event lifecycle and admit observed local provider JSON."""
    from tests.integration.test_plan_preparation_api import FakeAI

    class CurrentAI(FakeAI):
        def call(self, identity, source, token):
            self.calls.append(identity)
            self.entered.set()
            try:
                assert self.release.wait(5)
                # The real extraction parser captures the raw draft before validation.
                # PreparationWorker then persists its original private INPUT proof.
                result = extract(_current_output(source.text).model_dump(mode="json"), source.text,
                    authored_at=source.authored_at, available_at=source.available_at,
                    effective_trade_date=source.effective_trade_date)
                return result.model_copy(update={"request_id": identity})
            finally:
                self.ended.set()

    return CurrentAI(blocked=blocked)
