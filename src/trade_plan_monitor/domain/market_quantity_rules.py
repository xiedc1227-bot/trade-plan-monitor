"""Versioned official A-share auction BUY quantity grids, never account authority."""

from datetime import date
from typing import Literal

from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.daily_plan_models import DailyValue
from trade_plan_monitor.market_index.identity import Board, resolve_board_reference

SSE_RULE_URL = (
    "https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/"
    "c_20260424_10816492.shtml"
)
SZSE_RULE_URL = "https://investor.szse.cn/lawrules/rule/trade/t20260424_620190.html"
BSE_RULE_URL = "https://www.bse.cn/jygl_list/200028217.html"


class MarketQuantityRules(DailyValue):
    version: Literal["cn-equity-buy-grid-2026-07-06"] = "cn-equity-buy-grid-2026-07-06"
    board: Board
    effective_from: date
    published_on: date
    minimum: int
    increment: int
    source_url: str
    article: str

    @property
    def content_hash(self):
        return daily_hash("market-quantity-rules-v1", self.model_dump(mode="json"))


def official_buy_grid(symbol: str, decision_session: date) -> MarketQuantityRules | None:
    """No current rule is backdated into an uncertified historical period.

    This is the minimum/increment grid only. Tradability, special states and
    execution eligibility retain their existing independent verification gates.
    """
    if decision_session < date(2026, 7, 6):
        return None
    code, exchange = symbol.split(".")
    allowed = {
        "SH": ("600", "601", "603", "605", "688"),
        "SZ": ("000", "001", "002", "003", "300", "301"),
        "BJ": ("43", "83", "87", "88", "92"),
    }
    if exchange not in allowed or not code.startswith(allowed[exchange]):
        return None
    board = resolve_board_reference(symbol).board
    minimum = 200 if board == Board.STAR_MARKET else 100
    increment = 1 if board in {Board.STAR_MARKET, Board.BSE} else 100
    url = SSE_RULE_URL if exchange == "SH" else SZSE_RULE_URL if exchange == "SZ" else BSE_RULE_URL
    return MarketQuantityRules(
        board=board,
        effective_from=date(2026, 7, 6),
        published_on=date(2026, 4, 24),
        minimum=minimum,
        increment=increment,
        source_url=url,
        article="6.7" if board == Board.STAR_MARKET else "3.3.8",
    )
