"""Shared extraction constraints for every current linked-plan entry point."""

import json


def linkage_prompt_contract():
    from trade_plan_monitor.domain.market_linkage_definitions import (
        EXPANDED_EXCEPTION_POLICY,
        EXPANDED_LINKAGE_POLICY,
    )

    return (
        "\nOpt-in market linkage: use schema_version=6/condition-plan-v2 ONLY when source "
        "explicitly defines daily BUY market linkage without enabling exception review. "
        "Use schema_version=7/condition-plan-v3 only for source-defined per-occurrence "
        "exception review. Otherwise retain schema_version=5. "
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
        "Schema 6 exceptions remain BLOCK_P1. Schema 7 uses market-linkage-v2, "
        "REVIEW_PER_OCCURRENCE and required exception_routes.weak_minimum/broken_strong "
        "(DISABLED or PER_OCCURRENCE); missing permission stays null/unresolved. "
        "Plan permission is not occurrence approval. AI never creates approval IDs/events, "
        "approved quantities or human authority; BROKEN_STRONG quantity is entered later "
        "by the user, never inferred or added to the plan. Schema 6 expanded definitions: "
        + json.dumps(EXPANDED_LINKAGE_POLICY, ensure_ascii=False)
        + "\nSchema 7 retains those definitions except these replacements/additions: "
        + json.dumps({k: v for k, v in EXPANDED_EXCEPTION_POLICY.items()
                      if EXPANDED_LINKAGE_POLICY.get(k) != v}, ensure_ascii=False)
        + "\n"
    )
