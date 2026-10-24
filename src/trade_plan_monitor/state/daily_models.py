"""Daily evidence and isolated simulation records."""

from sqlalchemy import CheckConstraint, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from trade_plan_monitor.state.models import Base


class DailyRecord(Base):
    __tablename__ = "daily_plan_record"
    __table_args__ = (
        CheckConstraint("revision >= 0", name="ck_daily_record_revision"),
        CheckConstraint(
            "kind IN "
            "('SIGNAL','RISK','FACT','SIMULATION','REPORT','POSITION','EVALUATION','REVIEW','DRAFT','EXT"
            "RACTION','REASSESSMENT','EXCEPTION_CANDIDATE','EXCEPTION_EVENT','EXCEPTION_PREVIEW')",
            name="ck_daily_record_kind",
        ),
        Index("ix_daily_record_symbol_kind", "symbol", "kind"),
        Index("ix_daily_record_lineage_kind", "lineage", "kind"),
        Index("ux_exception_command", text("json_extract(payload_json, '$.command_id')"),
              unique=True, sqlite_where=text("kind = 'EXCEPTION_EVENT'")),
    )
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    symbol: Mapped[str] = mapped_column(String(9))
    lineage: Mapped[str] = mapped_column(String(128))
    revision: Mapped[int] = mapped_column(Integer)
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))
