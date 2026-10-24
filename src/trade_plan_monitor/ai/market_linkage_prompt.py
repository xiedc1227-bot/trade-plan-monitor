"""Shared extraction constraints for every current linked-plan entry point."""

import json


def linkage_prompt_contract():
    from trade_plan_monitor.domain.market_linkage_definitions import EXPANDED_LINKAGE_POLICY

    return (
        "\nOpt-in market linkage: use schema_version=6/condition-plan-v2 ONLY when source "
        "explicitly defines daily BUY market linkage. Otherwise retain schema_version=5. "
        "For follow-up changes preserve the reviewed predecessor's schema and unmentioned "
        "linked policies; an unrelated update never downgrades a linked predecessor. "
        "Linked BUY uses quantity_policy and market_policy, never quantity. Preserve complete "
        "S0 as condition; missing Q0/condition is null and UNRESOLVED. Derive reference_market "
        "using board-index-map-v1 (SH main 000001.SH, SZ main 399001.SZ, ChiNext 399006.SZ, "
        "STAR 000688.SH, BSE 899050.BJ); no benchmark substitution. Server revalidates mapping. "
        "Each linked rule additionally requires source bindings at "
        "ordinary_rules[i].market_policy.expanded.<key> with the following exact values. "
        "These are virtual review paths, not extra JSON plan fields. Bind complete definitions "
        "to their actual source clauses; a label alone is UNRESOLVED, never PRODUCT_CONTRACT. "
        "Do not silently import only S0 when the source requires unsupported linkage. "
        "P1 exceptions always remain blocked; AI cannot create human exception authority. "
        + json.dumps(EXPANDED_LINKAGE_POLICY, ensure_ascii=False)
        + "\n"
    )
