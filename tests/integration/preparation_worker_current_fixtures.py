"""Observed synthetic worker inputs; no review, authority or provider is mocked."""

import json

from tests.unit.test_monitor_loop_schedule import at
from tests.unit.test_unified_replay_input import research_plan

from trade_plan_monitor.ai.loop_plan_extraction import (
    LoopPlanExtractionOutput,
    OpeningAccountFacts,
    OpeningFact,
)
from trade_plan_monitor.ai.source_derivation_replay import expand_update_with_evidence
from trade_plan_monitor.backtest.preparation_models import PreparationSource
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft


def worker_initial_source():
    """Keep the original research policy's strong values in a complete FIELD source."""
    from tests.integration.preparation_review_current_fixtures import field_source, reviewed_mapping

    draft = UnifiedPlanDraft.from_executable(research_plan())
    account = "账户记录：当前持仓0股。"
    text = field_source(draft, tail=(account,))
    source = PreparationSource(source_id="first", text=text, authored_at=at(19),
        available_at=at(19), effective_trade_date=at(19).date())
    mapping = reviewed_mapping(draft, text)
    start = text.index(account)
    output = LoopPlanExtractionOutput(schema_version="monitor-loop-extraction-v1", draft=draft,
        clauses=mapping.clauses, bindings=mapping.bindings,
        opening_account=OpeningAccountFacts(inventory_quantity=OpeningFact(value=0,
            start=start, end=len(text), excerpt=account), lots=(), cash_fen=None, snapshot_at=None))
    return source, output


def recorded_worker_update_result(base, source, output, identity, context):
    """Observe exact full-update wire bytes before the existing result constructor."""
    from tests.integration.test_plan_preparation_worker import collection_update_result

    raw = "\n" + json.dumps(output.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
    admitted, derivation = expand_update_with_evidence(raw, source, context)
    result = collection_update_result(base, source, admitted, identity, context)
    return result.model_copy(update={"source_derivation": derivation})
