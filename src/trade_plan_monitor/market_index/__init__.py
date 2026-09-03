"""Board-index identities, data facts, and plan-owned evaluation support."""

from trade_plan_monitor.market_index.identity import (
    MAPPING_VERSION,
    Board,
    MarketIndexCode,
    ReferenceMarketBinding,
    ResolvedMarketIndexIdentity,
    resolve_board_reference,
    validate_reference_market_binding,
)

__all__ = [
    "MAPPING_VERSION",
    "Board",
    "MarketIndexCode",
    "ReferenceMarketBinding",
    "ResolvedMarketIndexIdentity",
    "resolve_board_reference",
    "validate_reference_market_binding",
]
