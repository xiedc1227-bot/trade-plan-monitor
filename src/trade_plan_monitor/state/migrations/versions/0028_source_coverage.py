"""Capture actual historical membership and add independent assurance evidence."""

import json
from datetime import datetime
from hashlib import sha256
from uuid import uuid4
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from alembic import op

revision = "0028_source_coverage"
down_revision = "0027_simulation_capital"
branch_labels = None
depends_on = None


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                      separators=(",", ":"))


def _hash(domain, value):
    return sha256(domain.encode() + b"\0" + _canonical(value).encode()).hexdigest()


def _signed(value):
    return value | {"evidence_hash": _hash(value["version"], value)}


def upgrade():
    op.create_table("source_coverage_installation",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("installation_id", sa.String(36), nullable=False, unique=True),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_coverage_installation_singleton"))
    op.create_table("source_coverage_cutover",
        sa.Column("plan_version_id", sa.String(36), primary_key=True),
        sa.Column("installation_id", sa.String(36), nullable=False),
        sa.Column("plan_hash", sa.String(64), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False))
    op.create_table("source_coverage_input",
        sa.Column("extraction_id", sa.String(36), primary_key=True),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False))
    op.create_table("source_coverage_assessment",
        sa.Column("plan_version_id", sa.String(36), primary_key=True),
        sa.Column("revision", sa.Integer, primary_key=True),
        sa.Column("command_id", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.CheckConstraint("revision > 0", name="ck_coverage_assessment_revision"),
        sa.UniqueConstraint("command_id", name="uq_coverage_assessment_command"))
    op.create_table("source_coverage_review",
        sa.Column("review_id", sa.String(36), primary_key=True),
        sa.Column("plan_version_id", sa.String(36), nullable=False),
        sa.Column("review_revision", sa.Integer, nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.CheckConstraint("review_revision > 0", name="ck_coverage_review_revision"),
        sa.UniqueConstraint("plan_version_id", "review_revision",
                            name="uq_coverage_review_identity"))
    connection = op.get_bind()
    installation_id = str(uuid4())
    members = []
    rows = connection.execute(sa.text(
        "SELECT v.id, v.plan_hash, s.source_hash, v.status, v.revision, "
        "p.review_id, p.review_revision, p.review_evidence_hash, p.confirmed_at, "
        "p.content_hash, p.origin, a.revision AS active_revision, a.activated_at "
        "FROM plan_version v JOIN plan_source s ON s.id=v.source_id "
        "LEFT JOIN plan_review_provenance p ON p.plan_version_id=v.id "
        "LEFT JOIN active_plan a ON a.plan_version_id=v.id ORDER BY v.id"
    )).mappings()
    for row in rows:
        member = _signed(dict(version="source-coverage-cutover-v1",
            installation_id=installation_id, plan_version_id=row["id"],
            plan_hash=row["plan_hash"], source_hash=row["source_hash"],
            legacy_identity={key: row[key] for key in row if key not in {
                "id", "plan_hash", "source_hash"}}))
        members.append([row["id"], row["plan_hash"], row["source_hash"], member["evidence_hash"]])
        connection.execute(sa.text(
            "INSERT INTO source_coverage_cutover VALUES "
            "(:id,:installation,:plan,:source,:json,:hash)"
        ), dict(id=row["id"], installation=installation_id, plan=row["plan_hash"],
                source=row["source_hash"], json=_canonical(member), hash=member["evidence_hash"]))
    marker = _signed(dict(version="source-coverage-installation-v1",
        installation_id=installation_id,
        installed_at=datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(), member_count=len(members),
        membership_hash=_hash("source-coverage-membership-v1", members)))
    connection.execute(sa.text(
        "INSERT INTO source_coverage_installation VALUES (1,:id,:json,:hash)"),
        dict(id=installation_id, json=_canonical(marker), hash=marker["evidence_hash"]))


def downgrade():
    connection = op.get_bind()
    _verify_cutover(connection)
    for table in ("source_coverage_input", "source_coverage_assessment", "source_coverage_review"):
        if connection.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first() is not None:
            raise RuntimeError("0028 refuses to discard source coverage evidence")
    changed = connection.execute(sa.text(
        "SELECT 1 FROM plan_version v JOIN plan_source s ON s.id=v.source_id "
        "LEFT JOIN source_coverage_cutover c ON c.plan_version_id=v.id "
        "WHERE c.plan_version_id IS NULL OR c.plan_hash<>v.plan_hash "
        "OR c.source_hash<>s.source_hash "
        "LIMIT 1"
    )).first()
    if changed is not None:
        raise RuntimeError("0028 refuses to discard post-cutover source coverage authority")
    for table in ("source_coverage_review", "source_coverage_assessment", "source_coverage_input",
                  "source_coverage_cutover", "source_coverage_installation"):
        op.drop_table(table)


def _verify_cutover(connection):
    """A damaged membership cannot reclassify a new version during downgrade."""
    try:
        row = connection.execute(sa.text(
            "SELECT * FROM source_coverage_installation",
        )).mappings().one()
        marker = _verify_payload(row, "source-coverage-installation-v1", {
            "version", "installation_id", "installed_at", "member_count", "membership_hash",
            "evidence_hash",
        })
        if row["id"] != 1 or row["installation_id"] != marker["installation_id"]:
            raise ValueError("installation projection")
        if datetime.fromisoformat(marker["installed_at"]).tzinfo is None:
            raise ValueError("installation time")
        members = []
        for row in connection.execute(sa.text(
            "SELECT * FROM source_coverage_cutover ORDER BY plan_version_id",
        )).mappings():
            member = _verify_payload(row, "source-coverage-cutover-v1", {
                "version", "installation_id", "plan_version_id", "plan_hash", "source_hash",
                "legacy_identity", "evidence_hash",
            })
            if (any(row[key] != member[key] for key in (
                "installation_id", "plan_version_id", "plan_hash", "source_hash",
            )) or row["installation_id"] != marker["installation_id"]
                    or not isinstance(member["legacy_identity"], dict)):
                raise ValueError("membership projection")
            members.append([row["plan_version_id"], row["plan_hash"], row["source_hash"],
                            row["evidence_hash"]])
        if (type(marker["member_count"]) is not int or marker["member_count"] != len(members)
                or marker["membership_hash"] != _hash("source-coverage-membership-v1", members)):
            raise ValueError("membership root")
    except (ValueError, TypeError, KeyError, sa.exc.SQLAlchemyError):
        raise RuntimeError("0028 refuses downgrade of invalid source coverage cutover") from None


def _verify_payload(row, version, keys):
    payload = json.loads(row["payload_json"])
    if (set(payload) != keys or payload["version"] != version
            or _canonical(payload) != row["payload_json"]
            or payload["evidence_hash"] != row["evidence_hash"]
            or row["evidence_hash"] != _hash(version, {
                key: value for key, value in payload.items() if key != "evidence_hash"})):
        raise ValueError("signed payload")
    return payload
