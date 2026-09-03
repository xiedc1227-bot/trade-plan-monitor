from __future__ import annotations

import pytest
from pydantic import ValidationError

from trade_plan_monitor.market_index.identity import (
    MAPPING_VERSION,
    Board,
    MarketIndexCode,
    ReferenceMarketBinding,
    resolve_board_reference,
    validate_reference_market_binding,
)


@pytest.mark.parametrize(
    ("symbol", "board", "index_code", "display_name"),
    [
        ("600000.SH", Board.SSE_MAIN, MarketIndexCode.SSE_COMPOSITE, "上证指数"),
        ("688001.SH", Board.STAR_MARKET, MarketIndexCode.STAR_50, "科创50"),
        ("689009.SH", Board.STAR_MARKET, MarketIndexCode.STAR_50, "科创50"),
        ("000001.SZ", Board.SZSE_MAIN, MarketIndexCode.SHENZHEN_COMPONENT, "深证成指"),
        ("300001.SZ", Board.CHINEXT, MarketIndexCode.CHINEXT, "创业板指"),
        ("301001.SZ", Board.CHINEXT, MarketIndexCode.CHINEXT, "创业板指"),
        ("430001.BJ", Board.BSE, MarketIndexCode.BSE_50, "北证50"),
    ],
)
def test_resolve_board_reference_uses_only_the_fixed_mapping(
    symbol: str,
    board: Board,
    index_code: MarketIndexCode,
    display_name: str,
) -> None:
    identity = resolve_board_reference(symbol)

    assert identity.symbol == symbol
    assert identity.board is board
    assert identity.index_code is index_code
    assert identity.display_name == display_name
    assert identity.mapping_version == MAPPING_VERSION
    assert identity.binding == ReferenceMarketBinding(index_code=index_code)


@pytest.mark.parametrize(
    "symbol",
    [
        "",
        "600000",
        "60000.SH",
        "600000.sh",
        "600000.HK",
        "000001.XX",
        "000001.SH ",
        "000001.SH\n",
        "000001.SH",
        "399001.SZ",
        "399006.SZ",
        "000688.SH",
        "899050.BJ",
        "SSE Composite",
    ],
)
def test_resolve_board_reference_rejects_invalid_input_without_fallback(symbol: str) -> None:
    with pytest.raises(ValueError, match="canonical A-share stock code"):
        resolve_board_reference(symbol)


def test_validate_reference_market_binding_recomputes_the_expected_binding() -> None:
    expected = ReferenceMarketBinding(index_code=MarketIndexCode.CHINEXT)

    assert validate_reference_market_binding("300750.SZ", expected) is None

    mismatched = ReferenceMarketBinding(index_code=MarketIndexCode.SHENZHEN_COMPONENT)
    with pytest.raises(ValueError, match="does not match"):
        validate_reference_market_binding("300750.SZ", mismatched)


def test_reference_market_binding_is_closed_and_immutable() -> None:
    binding = ReferenceMarketBinding.model_validate(
        {
            "selection": "AUTO_BOARD",
            "mapping_version": "board-index-map-v1",
            "index_code": "000688.SH",
        }
    )

    with pytest.raises(ValidationError):
        ReferenceMarketBinding.model_validate(
            {
                "selection": "AUTO_BOARD",
                "mapping_version": "board-index-map-v1",
                "index_code": "000688.SH",
                "industry_index": "000905.SH",
            }
        )

    with pytest.raises(ValidationError):
        binding.index_code = MarketIndexCode.SSE_COMPOSITE  # type: ignore[misc]
