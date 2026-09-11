"""Closed, versioned mapping from validated A-share symbols to board indices."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

MAPPING_VERSION = "board-index-map-v1"
_STOCK_SYMBOL_PATTERN = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")


class Board(StrEnum):
    """Closed board identities supported by the Phase-1 mapping."""

    SSE_MAIN = "SSE_MAIN"
    SZSE_MAIN = "SZSE_MAIN"
    CHINEXT = "CHINEXT"
    STAR_MARKET = "STAR_MARKET"
    BSE = "BSE"


class MarketIndexCode(StrEnum):
    """Closed provider-independent index codes approved for Phase 1."""

    SSE_COMPOSITE = "000001.SH"
    SHENZHEN_COMPONENT = "399001.SZ"
    SHENZHEN_A_SHARE = "399107.SZ"
    CHINEXT = "399006.SZ"
    STAR_50 = "000688.SH"
    BSE_50 = "899050.BJ"


_INDEX_CODE_VALUES = frozenset(item.value for item in MarketIndexCode)


class _IdentityValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReferenceMarketBinding(_IdentityValue):
    """The exact immutable reference-market fields persisted in Schema v2."""

    selection: Literal["AUTO_BOARD"] = "AUTO_BOARD"
    mapping_version: Literal["board-index-map-v1"] = MAPPING_VERSION
    index_code: MarketIndexCode


class ResolvedMarketIndexIdentity(_IdentityValue):
    """One derived board/index identity for projection and validation."""

    symbol: str
    board: Board
    index_code: MarketIndexCode
    display_name: str
    mapping_version: Literal["board-index-map-v1"] = MAPPING_VERSION

    @property
    def binding(self) -> ReferenceMarketBinding:
        return ReferenceMarketBinding(index_code=self.index_code)


_REFERENCE_INDEX_BY_BOARD = {
    Board.SSE_MAIN: MarketIndexCode.SSE_COMPOSITE,
    Board.SZSE_MAIN: MarketIndexCode.SHENZHEN_COMPONENT,
    Board.CHINEXT: MarketIndexCode.CHINEXT,
    Board.STAR_MARKET: MarketIndexCode.STAR_50,
    Board.BSE: MarketIndexCode.BSE_50,
}
_INDEX_METADATA = {
    MarketIndexCode.SSE_COMPOSITE: (Board.SSE_MAIN, "上证指数"),
    MarketIndexCode.SHENZHEN_COMPONENT: (Board.SZSE_MAIN, "深证成指"),
    MarketIndexCode.SHENZHEN_A_SHARE: (Board.SZSE_MAIN, "深证A指"),
    MarketIndexCode.CHINEXT: (Board.CHINEXT, "创业板指"),
    MarketIndexCode.STAR_50: (Board.STAR_MARKET, "科创50"),
    MarketIndexCode.BSE_50: (Board.BSE, "北证50"),
}


def identity_for_index_code(
    index_code: MarketIndexCode,
) -> tuple[Board, str]:
    """Return the closed board/display identity for an approved index code."""

    if not isinstance(index_code, MarketIndexCode):
        raise TypeError("index_code must be a MarketIndexCode")
    return _INDEX_METADATA[index_code]


def _classify_board(symbol: str) -> Board:
    code, exchange = symbol.split(".", maxsplit=1)
    if exchange == "BJ":
        return Board.BSE
    if exchange == "SH":
        return Board.STAR_MARKET if code.startswith(("688", "689")) else Board.SSE_MAIN
    if exchange == "SZ":
        return Board.CHINEXT if code.startswith(("300", "301")) else Board.SZSE_MAIN
    raise ValueError("stock symbol cannot be classified by board-index-map-v1")


def resolve_board_reference(symbol: str) -> ResolvedMarketIndexIdentity:
    """Resolve one canonical stock symbol without I/O, guessing, or fallback."""

    if (
        type(symbol) is not str
        or _STOCK_SYMBOL_PATTERN.fullmatch(symbol) is None
        or symbol in _INDEX_CODE_VALUES
    ):
        raise ValueError("symbol must be a canonical A-share stock code")
    board = _classify_board(symbol)
    index_code = _REFERENCE_INDEX_BY_BOARD[board]
    _identity_board, display_name = _INDEX_METADATA[index_code]
    return ResolvedMarketIndexIdentity(
        symbol=symbol,
        board=board,
        index_code=index_code,
        display_name=display_name,
    )


def validate_reference_market_binding(
    symbol: str,
    binding: ReferenceMarketBinding,
) -> None:
    """Recompute a stored binding and fail closed when any field differs."""

    if not isinstance(binding, ReferenceMarketBinding):
        raise TypeError("binding must be a ReferenceMarketBinding")
    if resolve_board_reference(symbol).binding != binding:
        raise ValueError("reference-market binding does not match the stock symbol")


__all__ = [
    "MAPPING_VERSION",
    "Board",
    "MarketIndexCode",
    "ReferenceMarketBinding",
    "ResolvedMarketIndexIdentity",
    "identity_for_index_code",
    "resolve_board_reference",
    "validate_reference_market_binding",
]
