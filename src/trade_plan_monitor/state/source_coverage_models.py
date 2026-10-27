"""Additive assurance metadata; historical payloads and receipts keep their owners."""

from sqlalchemy import CheckConstraint, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from trade_plan_monitor.state.models import Base


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
