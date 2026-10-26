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
        "exception review. If source defines volatility sizing or pretrade economics, use "
        "schema_version=8/condition-plan-v4 and pretrade-policy-v1. Otherwise retain "
        "schema_version=5. Schema 8 inherits Schema 7 market and exception permissions; "
        "never infer those permissions from volatility or fee language. "
        "P2 executable requirements come only from section A; section B is background. "
        "ATR_RATIO_TIERS requires explicit ATR14_OVER_CLOSE, base_qty and contiguous "
        "[lower,upper) tiers from zero to null infinity, with nonincreasing multipliers. "
        "Use DERIVED_MARKET_FACTOR without base_quantity; FIXED_Q0 keeps MARKET_FACTOR "
        "and explicit base_quantity. All decimal rates/bounds are JSON strings. "
        "economics mode NONE means no fee calculation; PREVIEW_ONLY is an estimate, "
        "never a gate. REQUIRED needs explicit min_net_reward_fen and/or "
        "min_reward_risk_ratio; never invent either threshold or a default fee schedule. "
        "Fee schedule requires version, exact securities, effective dates, ESTIMATE "
        "provenance, commission/minimum, component inclusion and buy/sell slippage. "
        "Target and risk levels require PRICE_STRUCTURE plus an independent dimension; "
        "MA20 and BOLL_MIDDLE both count as TREND, never two dimensions. "
        "Missing fields remain unresolved and block review; do not drop an unsupported "
        "policy or downgrade to an older schema. AI creates no human attestations, "
        "occurrence approval, frozen Q0, exception quantity or simulation receipts. "
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
