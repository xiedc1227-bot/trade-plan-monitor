"""Server-owned P3 exception inputs distinguish unbounded from unknown shares."""

from datetime import date

from trade_plan_monitor.decision.p3_capital import ShareCapacity, assess_capital
from trade_plan_monitor.domain.daily_plan_models import DailyValue, Qty
from trade_plan_monitor.domain.p2_policy_models import PositiveFen, SafeFen
from trade_plan_monitor.domain.p3_policy_models import P3Position
from trade_plan_monitor.state.market_exception_models import Digest
from trade_plan_monitor.state.p2_authority import P2EconomicsContext


class CapitalAuthorityContext(DailyValue):
    binding_hash: Digest
    inventory_revision: Qty
    evaluation_revision: Qty
    authority_hash: Digest
    share_capacity: ShareCapacity
    blockers: tuple[str, ...]
    pretrade: P2EconomicsContext
    position: P3Position
    total_qty: Qty | None
    retained_basis_fen: SafeFen | None
    book_revision: SafeFen | None
    price_fen: PositiveFen | None
    symbol: str
    session: date


def assess_exception_capital(context, quantity):
    return assess_capital(context.position, quantity=quantity, price_fen=context.price_fen,
        total_qty=context.total_qty, retained_basis_fen=context.retained_basis_fen,
        symbol=context.symbol, session=context.session,
        inventory_revision=context.inventory_revision, book_revision=context.book_revision,
        phase="CURRENT")
