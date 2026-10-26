"""Independent capital sidecar values and metadata; actual holdings are untouched."""

from typing import Literal

from pydantic import Field, JsonValue, model_validator
from sqlalchemy import CheckConstraint, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from trade_plan_monitor.decision.p3_basis import CapitalLot, retained_basis
from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.domain.daily_plan_models import DailyValue, Identifier
from trade_plan_monitor.domain.p2_policy_models import MAX_SAFE, SafeFen
from trade_plan_monitor.domain.plan_codec import MAX_PLAN_DOCUMENT_BYTES
from trade_plan_monitor.market_data.models import AShareSymbol, ShanghaiDatetime
from trade_plan_monitor.state.models import Base


class _BookContent(DailyValue):
    version: Literal["capital-book-v1"] = "capital-book-v1"
    symbol: AShareSymbol
    revision: int = Field(strict=True, gt=0, le=MAX_SAFE)
    inventory_revision: int = Field(strict=True, gt=0, le=MAX_SAFE)
    lots: tuple[CapitalLot, ...] = Field(max_length=500)
    updated_at: ShanghaiDatetime

    @model_validator(mode="after")
    def bounded_lots(self):
        retained_basis(self.lots)
        return self

    @property
    def retained_basis_fen(self):
        return retained_basis(self.lots)


class CapitalBook(_BookContent):
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def build(cls, **values):
        data = _BookContent.model_validate(values).model_dump(mode="json")
        return cls.model_validate(data | {"evidence_hash": daily_hash("capital-book-v1", data)})

    @model_validator(mode="after")
    def verify(self):
        if self.evidence_hash != daily_hash(
            self.version, self.model_dump(mode="json", exclude={"evidence_hash"})
        ):
            raise ValueError("capital book hash mismatch")
        return self


class _EventContent(DailyValue):
    version: Literal["capital-book-event-v1"] = "capital-book-event-v1"
    command_id: Identifier
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: Literal["OPENING", "RECONCILIATION", "BUY", "SELL", "UNKNOWN_CHANGE"]
    before_revision: SafeFen
    before_hash: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    book: CapitalBook
    received_at: ShanghaiDatetime
    details: dict[str, JsonValue] = Field(max_length=50)

    @model_validator(mode="after")
    def coherent(self):
        if (
            self.book.revision != self.before_revision + 1
            or (self.before_hash is None) != (self.before_revision == 0)
            or self.book.updated_at != self.received_at
        ):
            raise ValueError("capital event differs from the atomic book transition")
        if len(canonical(self.model_dump(mode="json")).encode()) > MAX_PLAN_DOCUMENT_BYTES:
            raise ValueError("CAPITAL_PAYLOAD_TOO_LARGE")
        return self


class CapitalBookEvent(_EventContent):
    event_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def build(cls, **values):
        data = _EventContent.model_validate(values).model_dump(mode="json")
        return cls.model_validate(data | {"event_hash": daily_hash("capital-book-event-v1", data)})

    @model_validator(mode="after")
    def verify(self):
        if self.event_hash != daily_hash(
            self.version, self.model_dump(mode="json", exclude={"event_hash"})
        ):
            raise ValueError("capital event hash mismatch")
        return self


class CapitalBookRow(Base):
    __tablename__ = "simulation_capital_book"
    __table_args__ = (
        CheckConstraint("revision > 0", name="ck_capital_book_revision"),
        CheckConstraint("inventory_revision > 0", name="ck_capital_book_inventory"),
    )
    symbol: Mapped[str] = mapped_column(String(9), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)
    inventory_revision: Mapped[int] = mapped_column(Integer)
    payload_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(String(40))


class CapitalEventRow(Base):
    __tablename__ = "simulation_capital_event"
    __table_args__ = (
        CheckConstraint("revision > 0", name="ck_capital_event_revision"),
        Index("ix_capital_event_symbol_time", "symbol", "created_at", "command_id"),
    )
    command_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(9))
    revision: Mapped[int] = mapped_column(Integer)
    request_hash: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))
