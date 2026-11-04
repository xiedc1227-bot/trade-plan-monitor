"""Daily evidence and isolated simulation records."""

from sqlalchemy import CheckConstraint, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from trade_plan_monitor.state.models import Base

NATIVE_FACT_INDEX_NAME = "ix_daily_fact_trade_date_lookup"


def _fact_json(path, *, kind="extract"):
    return f"CASE WHEN json_valid(payload_json) THEN json_{kind}(payload_json, '$.{path}') END"


def native_fact_time_key_sql(path):
    """Exact fixed-microsecond key for supported native +08:00 strings only."""
    value = f"json_extract(payload_json, '$.{path}')"
    length = f"length({value})"
    digits = "[0-9]"
    pattern = f"{digits * 4}-{digits * 2}-{digits * 2}T{digits * 2}:{digits * 2}:{digits * 2}"
    year = f"CAST(substr({value}, 1, 4) AS INTEGER)"
    month = f"CAST(substr({value}, 6, 2) AS INTEGER)"
    day = f"CAST(substr({value}, 9, 2) AS INTEGER)"
    month_days = (
        f"CASE WHEN {month} IN (4,6,9,11) THEN 30 WHEN {month}=2 THEN "
        f"28 + ({year}%4=0 AND ({year}%100!=0 OR {year}%400=0)) ELSE 31 END"
    )
    fraction = f"CASE WHEN {length}=25 THEN '' ELSE substr({value}, 21, {length}-26) END"
    return (
        "CASE WHEN json_valid(payload_json) THEN CASE WHEN "
        f"json_type(payload_json, '$.{path}')='text' "
        f"AND substr({value}, 1, 19) GLOB '{pattern}' AND substr({value}, -6)='+08:00' "
        f"AND ({length}=25 OR ({length} BETWEEN 27 AND 32 AND substr({value}, 20, 1)='.' "
        f"AND substr({value}, 21, {length}-26) NOT GLOB '*[^0-9]*')) "
        f"AND {year} BETWEEN 1 AND 9999 AND {month} BETWEEN 1 AND 12 "
        f"AND {day} BETWEEN 1 AND ({month_days}) "
        f"AND substr({value}, 12, 2) BETWEEN '00' AND '23' "
        f"AND substr({value}, 15, 2) BETWEEN '00' AND '59' "
        f"AND substr({value}, 18, 2) BETWEEN '00' AND '59' "
        f"THEN substr({value}, 1, 19) || '.' || substr(({fraction}) || '000000', 1, 6) "
        "|| '+08:00' END END"
    )


_AVAILABLE = native_fact_time_key_sql("available_at")
_VERIFIED = native_fact_time_key_sql("verified_at")
NATIVE_FACT_AVAILABLE_SQL = f"CASE WHEN ({_AVAILABLE}) >= ({_VERIFIED}) THEN ({_AVAILABLE}) END"
NATIVE_FACT_TARGET_SQL = (
    "CASE WHEN json_valid(payload_json) THEN CASE "
    "WHEN json_type(payload_json, '$.reviewed_fact_target') IS NULL THEN '' "
    "WHEN json_type(payload_json, '$.reviewed_fact_target')='object' "
    "AND json_type(payload_json, '$.reviewed_fact_target.target_hash')='text' "
    "AND length(json_extract(payload_json, '$.reviewed_fact_target.target_hash'))=64 "
    "AND json_extract(payload_json, '$.reviewed_fact_target.target_hash') NOT GLOB '*[^0-9a-f]*' "
    "THEN json_extract(payload_json, '$.reviewed_fact_target.target_hash') END END"
)
NATIVE_FACT_OBSERVATION_SQL = (
    "CASE WHEN json_valid(payload_json) THEN CASE "
    "WHEN json_type(payload_json, '$.reviewed_fact_observation') IS NULL THEN '' "
    "WHEN json_type(payload_json, '$.reviewed_fact_observation')='object' "
    "AND json_type(payload_json, '$.reviewed_fact_target')='object' "
    "AND json_type(payload_json, '$.reviewed_fact_observation.source_hash')='text' "
    "AND length(json_extract(payload_json, '$.reviewed_fact_observation.source_hash'))=64 "
    "AND json_extract(payload_json, '$.reviewed_fact_observation.source_hash') "
    "NOT GLOB '*[^0-9a-f]*' THEN ("
    + native_fact_time_key_sql("reviewed_fact_observation.bar_end")
    + ") END END"
)
NATIVE_FACT_GROUP_SQL = (
    "symbol",
    _fact_json("plan_version_id"),
    _fact_json("content_hash"),
    _fact_json("kind"),
    _fact_json("trade_date"),
    _fact_json("verified", kind="type"),
    NATIVE_FACT_TARGET_SQL,
    NATIVE_FACT_OBSERVATION_SQL,
    "CASE WHEN "
    + NATIVE_FACT_OBSERVATION_SQL
    + "='' THEN '' ELSE "
    + _fact_json("reviewed_fact_observation.source_hash")
    + " END",
)
NATIVE_FACT_ORDER_SQL = (
    NATIVE_FACT_AVAILABLE_SQL + " DESC",
    _fact_json("available_at") + " DESC",
    _fact_json("verified_at") + " DESC",
    "id",
)


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
        Index(
            "ux_exception_command",
            text("json_extract(payload_json, '$.command_id')"),
            unique=True,
            sqlite_where=text("kind = 'EXCEPTION_EVENT'"),
        ),
        Index(
            NATIVE_FACT_INDEX_NAME,
            *(text(value) for value in (*NATIVE_FACT_GROUP_SQL, *NATIVE_FACT_ORDER_SQL)),
            sqlite_where=text("kind = 'FACT'"),
        ),
    )
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    symbol: Mapped[str] = mapped_column(String(9))
    lineage: Mapped[str] = mapped_column(String(128))
    revision: Mapped[int] = mapped_column(Integer)
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))
