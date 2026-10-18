"""A typed source scope change narrows existing rules without manual facts."""

from datetime import date

import pytest
from tests.unit.test_plan_delta_wire import delta
from tests.unit.test_risk_withdrawal_scope import baseline

from trade_plan_monitor.ai.plan_delta_wire import expand_delta_output
from trade_plan_monitor.ai.preparation_wire import expand_compact_output
from trade_plan_monitor.ai.update_review import build_update_review, context_from_review
from trade_plan_monitor.backtest.preparation_models import PreparationSource


def _scoped_review(text, action):
    base = baseline()
    _, wire = delta(text, target='risk_branches', rule_id='ORDINARY_TECHNICAL', action=action)
    wire = wire.model_copy(update={'schema_version': 'monitor-loop-delta-wire-v5',
        'operations': tuple(op.model_copy(update={'scope_assessment': 'PARTIAL_RULE',
            'scope_change': 'EXISTING_POSITIONS_ONLY', 'intent': 'CONTEXT'})
            for op in wire.operations)})
    source = PreparationSource(source_id='scoped', text=text,
                               effective_trade_date=date(2026, 10, 9))
    context = context_from_review(base, 'a' * 64)
    output = expand_compact_output(expand_delta_output(wire, context), source, context=context)
    return base, build_update_review(base, source, output)


@pytest.mark.parametrize('text', [
    '这条止损不再用于后来新开的仓位，旧持仓的处理办法维持。',
    '新增批次不适用此前风控线；既有批次仍按原规则处理。',
    'The previous exit continues for existing lots; exclude future entries.',
])
@pytest.mark.parametrize('action', ['RETAIN', 'REVOKE'])
def test_clear_exclusion_automatically_materializes_an_executable_old_holding_scope(text, action):
    base, review = _scoped_review(text, action)
    assert not review.issues
    assert review.to_preparation_candidate().policy_ready
    risk = review.draft.risk_branches[0]
    assert risk.holding_scope.mode == 'BEFORE_TRADE_DATE'
    assert risk.holding_scope.trade_date == date(2026, 10, 9)
    assert review.draft.levels.risk_line_fen == 2599
    assert risk.target_core_qty == risk.target_tactical_qty == 0
    assert risk.suspension_confirmation_policy == 'RESUME_FIRST_CLOSE'
    assert review.changes[0].action == 'MODIFY'
    prior = next(b for b in base.bindings if b.path == 'risk_branches[0].target_core_qty')
    assert next(b for b in review.bindings if b.path == prior.path) == prior


def test_unmentioned_later_plan_preserves_the_original_cohort_cutoff():
    _, base = _scoped_review('旧仓止损保留，新仓排除。', 'RETAIN')
    _, wire = delta('最大持仓保持300股。', action='RETAIN')
    source = PreparationSource(source_id='later', text='最大持仓保持300股。',
                               effective_trade_date=date(2026, 10, 12))
    context = context_from_review(base, 'b' * 64)
    output = expand_compact_output(expand_delta_output(wire, context), source, context=context)
    review = build_update_review(base, source, output)
    assert not review.issues
    assert review.draft.risk_branches[0].holding_scope == base.draft.risk_branches[0].holding_scope
