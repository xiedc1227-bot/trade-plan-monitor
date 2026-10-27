"""Additive assurance metadata; historical payloads and receipts keep their owners."""

from sqlalchemy import CheckConstraint, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from trade_plan_monitor.state.models import Base


def _coverage_triggers():
    result = {}
    for table in ("source_coverage_installation", "source_coverage_cutover",
                  "source_coverage_input", "source_coverage_assessment", "source_coverage_review"):
        for operation in ("update", "delete"):
            name = f"pma_seal_{table}_{operation}"
            result[name] = (
                f"CREATE TRIGGER {name} BEFORE {operation.upper()} ON {table} "
                "BEGIN SELECT RAISE(ABORT,'source coverage evidence is immutable'); END"
            )
    for table in ("source_coverage_installation", "source_coverage_cutover"):
        name = f"pma_seal_{table}_insert"
        result[name] = (
            f"CREATE TRIGGER {name} BEFORE INSERT ON {table} "
            "BEGIN SELECT RAISE(ABORT,'source coverage cutover is immutable'); END"
        )
    name = "pma_seal_source_coverage_assessment_insert"
    result[name] = (
        f"CREATE TRIGGER {name} BEFORE INSERT ON source_coverage_assessment "
        "WHEN NEW.revision != COALESCE((SELECT MAX(revision) FROM source_coverage_assessment "
        "WHERE plan_version_id=NEW.plan_version_id),0)+1 "
        "BEGIN SELECT RAISE(ABORT,'source coverage revision is not consecutive'); END"
    )
    return result


COVERAGE_TRIGGER_SQL = _coverage_triggers()


class CoverageInstallationRow(Base):
    __tablename__ = "source_coverage_installation"
    __table_args__ = (CheckConstraint("id = 1", name="ck_coverage_installation_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    installation_id: Mapped[str] = mapped_column(String(36), unique=True)
    payload_json: Mapped[str] = mapped_column(Text)
    evidence_hash: Mapped[str] = mapped_column(String(64))


class CoverageCutoverRow(Base):
    __tablename__ = "source_coverage_cutover"

    plan_version_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    installation_id: Mapped[str] = mapped_column(String(36))
    plan_hash: Mapped[str] = mapped_column(String(64))
    source_hash: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[str] = mapped_column(Text)
    evidence_hash: Mapped[str] = mapped_column(String(64))


class CoverageInputRow(Base):
    __tablename__ = "source_coverage_input"

    extraction_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_hash: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[str] = mapped_column(Text)
    evidence_hash: Mapped[str] = mapped_column(String(64))


class CoverageAssessmentRow(Base):
    __tablename__ = "source_coverage_assessment"
    __table_args__ = (
        CheckConstraint("revision > 0", name="ck_coverage_assessment_revision"),
        UniqueConstraint("command_id", name="uq_coverage_assessment_command"),
    )

    plan_version_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    command_id: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[str] = mapped_column(Text)
    evidence_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(40))


class CoverageReviewRow(Base):
    __tablename__ = "source_coverage_review"
    __table_args__ = (
        CheckConstraint("review_revision > 0", name="ck_coverage_review_revision"),
        UniqueConstraint("plan_version_id", "review_revision", name="uq_coverage_review_identity"),
    )

    review_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    plan_version_id: Mapped[str] = mapped_column(String(36))
    review_revision: Mapped[int] = mapped_column(Integer)
    payload_json: Mapped[str] = mapped_column(Text)
    evidence_hash: Mapped[str] = mapped_column(String(64))
