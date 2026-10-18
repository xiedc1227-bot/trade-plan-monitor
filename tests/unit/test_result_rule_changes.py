from trade_plan_monitor.web.result_rule_changes import compare_plan_values


def test_full_comparison_can_present_all_64_scoped_risk_variants():
    from trade_plan_monitor.web.result_rule_changes import BacktestRuleChangesView

    changes = compare_plan_values(None, {
        "position": {"max_qty": 300},
        "risk_branches": [
            {"kind": "ORDINARY_TECHNICAL", "rule_id": f"cohort-{index}",
             "holding_scope": {"mode": "FROM_TRADE_DATE", "trade_date": "2026-10-09"}}
            for index in range(64)
        ],
    })
    view = BacktestRuleChangesView(
        run_id="a" * 64, manifest_hash="b" * 64, source_id="source-1",
        version_id="version-1", previous_source_id=None, previous_version_id=None,
        relationship="INITIAL", changes=changes,
    )
    assert len(view.changes) == 65


def test_final_values_classify_all_actions_by_identity_not_list_position():
    before = {
        "position": {"max_qty": 300},
        "ordinary_rules": [{"rule_id": "keep", "quantity": 100},
                           {"rule_id": "change", "quantity": 100},
                           {"rule_id": "remove", "quantity": 100}],
        "risk_branches": [{"kind": "ORDINARY_TECHNICAL", "target_core_qty": 0}],
        "alert_rules": [],
    }
    after = before | {
        "position": {"max_qty": 500},
        "ordinary_rules": [{"rule_id": "change", "quantity": 200},
                           {"rule_id": "keep", "quantity": 100},
                           {"rule_id": "new", "quantity": 100}],
    }
    rows = {(r.target, r.rule_id): r for r in compare_plan_values(before, after)}
    assert rows["ordinary_rules", "keep"].action == "RETAIN"
    assert rows["ordinary_rules", "change"].action == "MODIFY"
    assert rows["ordinary_rules", "remove"].action == "REVOKE"
    assert rows["ordinary_rules", "new"].action == "ADD"
    assert rows["risk_branches", "ORDINARY_TECHNICAL"].action == "RETAIN"
    assert rows["position", None].before == {"max_qty": 300}
    assert rows["position", None].after == {"max_qty": 500}
    assert all(r.action == "ADD" for r in compare_plan_values(None, after))
