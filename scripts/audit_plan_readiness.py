"""Explicit DB-only installation evidence; never a current readiness evaluator.

No application composition, configuration loading, migration or service client.
Only an existing SQLite file is opened. All SQL identifiers below are owned
constants; persisted free text, payloads and endpoints are never emitted.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from time import monotonic
from uuid import UUID
from zoneinfo import ZoneInfo

from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.plan_codec import MAX_PLAN_DOCUMENT_BYTES, load_plan_json
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.notifications.channels import DeliveryChannel
from trade_plan_monitor.notifications.dispatcher import DeliveryAttemptStatus
from trade_plan_monitor.state.models import PlanVersionStatus
from trade_plan_monitor.state.source_coverage_models import COVERAGE_TRIGGER_SQL
from trade_plan_monitor.state.source_coverage_values import CoverageInstallation

MAX_ROWS = 100
MAX_OUTPUT_BYTES = 1024 * 1024
_KNOWN_MIGRATIONS = frozenset(path.stem for path in (
    Path(__file__).resolve().parents[1] / "src/trade_plan_monitor/state/migrations/versions"
).glob("[0-9]*.py"))
_COLUMNS = {
    "alembic_version": ("version_num",),
    "plan_version": ("id", "status", "payload_json", "created_at"),
    "plan_review_provenance": ("plan_version_id", "confirmed_at", "review_revision"),
    "active_plan": ("plan_version_id", "activated_at", "revision"),
    "plan_activation_state": ("plan_version_id", "changed_at", "revision"),
    "daily_plan_record": ("kind", "symbol", "created_at", "updated_at"),
    "evaluation_result": ("evaluation_kind", "evaluated_at", "source_at"),
    "runtime_liveness": ("last_alive_at",),
    "delivery_attempt": ("channel", "status", "delivered_at", "next_retry_at"),
    "source_coverage_installation": (
        "id", "installation_id", "payload_json", "evidence_hash"),
    "source_coverage_cutover": ("plan_version_id",),
    "source_coverage_input": ("extraction_id",),
    "source_coverage_assessment": ("plan_version_id", "revision", "created_at"),
    "source_coverage_review": ("plan_version_id", "review_revision"),
}


def _time(value):
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.isoformat() if parsed.utcoffset() is not None else None
    except ValueError:
        return None


def _id(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        return "INVALID"


def _enum(value, values):
    return value if value in values else "INVALID"


def _revision(value):
    return value if type(value) is int and 0 <= value <= 9_007_199_254_740_991 else None


def _rows(connection, report, table, *, where="", columns=None, section=None):
    """Fixed catalog only; one bounded sample, explicitly never a complete history."""
    if report["schema"][table] != "AVAILABLE":
        return []
    fields = columns or ",".join(_COLUMNS[table])
    order = ",".join(name for name in _COLUMNS[table] if name != "payload_json")
    owner_key = ("id" if table == "plan_version" else "plan_version_id"
                 if "plan_version_id" in _COLUMNS[table] else None)
    if owner_key and table not in {"active_plan", "plan_activation_state"} and (
            report["schema"]["active_plan"] == "AVAILABLE"):
        order = (f"CASE WHEN {owner_key} IN (SELECT plan_version_id FROM active_plan "
                 f"ORDER BY plan_version_id LIMIT 10) THEN 0 ELSE 1 END,{order}")
    row_limit = 10 if table == "active_plan" else MAX_ROWS
    rows = connection.execute(
        f'SELECT {fields} FROM "{table}" {where} ORDER BY {order} LIMIT ?', (row_limit + 1,)
    ).fetchall()
    if len(rows) > row_limit:
        report["limitedSections"].append(section or table)
    return rows[:row_limit]


def _marker(connection, report):
    if report["schema"]["source_coverage_installation"] != "AVAILABLE":
        return {"state": "MISSING"}
    rows = _rows(connection, report, "source_coverage_installation", columns=(
        "id,installation_id,CASE WHEN length(CAST(payload_json AS BLOB)) <= 1048576 "
        "THEN payload_json END,evidence_hash"))
    try:
        if len(rows) != 1:
            raise ValueError
        row = rows[0]
        marker = CoverageInstallation.model_validate_json(row[2])
        if (row[0] != 1 or str(marker.installation_id) != row[1]
                or marker.evidence_hash != row[3]
                or canonical(marker.model_dump(mode="json")) != row[2]):
            raise ValueError
        for name, expected in COVERAGE_TRIGGER_SQL.items():
            trigger = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (name,)
            ).fetchone()
            if trigger is None or trigger[0] != expected:
                raise ValueError
        return {"state": "VALID_PERSISTED_MARKER", "installedAt": marker.installed_at.isoformat()}
    except (ValueError, TypeError, RecursionError):
        return {"state": "INVALID_PERSISTED_MARKER"}


def _collect(connection, report):
    for table, required in _COLUMNS.items():
        columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
        report["schema"][table] = (
            "MISSING" if not columns else "AVAILABLE" if set(required) <= columns
            else "INCOMPATIBLE")
    report["migration"] = [
        value if value in _KNOWN_MIGRATIONS
        else "INVALID" for (value,) in _rows(connection, report, "alembic_version")]
    report["coverageInstallation"] = _marker(connection, report)
    plan_columns = (
        "id,status,CASE WHEN length(CAST(payload_json AS BLOB)) <= "
        f"{MAX_PLAN_DOCUMENT_BYTES} THEN payload_json END,created_at")
    for identity, status, payload, created in _rows(
            connection, report, "plan_version", columns=plan_columns, section="plans"):
        entry = {"versionId": _id(identity), "status": _enum(status, PlanVersionStatus),
                 "createdAt": _time(created), "scope": "UNKNOWN"}
        try:
            if payload is None:
                raise ValueError
            plan = load_plan_json(payload)
            if isinstance(plan, UnifiedTradePlan):
                ordinary, risk, alerts = (len(plan.ordinary_rules), len(plan.risk_branches),
                                          len(plan.alert_rules))
                entry.update(scope="MIXED" if alerts and (ordinary or risk) else
                             "TRADE_RULES" if ordinary or risk else "ALERT_ONLY" if alerts
                             else "UNKNOWN", ordinaryRules=ordinary, riskBranches=risk,
                             alertRules=alerts, schemaVersion=plan.schema_version)
        except (ValueError, TypeError, RecursionError):
            entry["payloadState"] = "INVALID_OR_UNSUPPORTED_OR_OVER_LIMIT"
        report["plans"].append(entry)
    for identity, confirmed, revision in _rows(connection, report, "plan_review_provenance"):
        report["reviews"].append({"versionId": _id(identity), "confirmedAt": _time(confirmed),
                                  "revision": _revision(revision), "binding": "NOT_REVALIDATED"})
    for table, section in (("active_plan", "activePlans"),
                           ("plan_activation_state", "activationStates")):
        for identity, at, revision in _rows(connection, report, table, section=section):
            report[section].append({"versionId": None if identity is None else _id(identity),
                                    "at": _time(at), "revision": _revision(revision)})
    for _, symbol, created, updated in _rows(connection, report, "daily_plan_record",
            where="WHERE kind='EVALUATION'", section="evaluations"):
        report["evaluations"].append({"symbol": symbol if isinstance(symbol, str)
            and re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", symbol) else "INVALID",
            "createdAt": _time(created), "updatedAt": _time(updated),
            "binding": "NOT_REVALIDATED"})
    for channel, status, delivered, retry in _rows(
            connection, report, "delivery_attempt", section="deliveryAttempts"):
        report["deliveryAttempts"].append({"channel": _enum(channel, DeliveryChannel),
            "status": _enum(status, DeliveryAttemptStatus), "deliveredAt": _time(delivered),
            "nextRetryAt": _time(retry), "binding": "NOT_REVALIDATED"})
    report["legacyEvaluations"] = [
        {"kind": _enum(kind, {"INTRADAY", "OFFICIAL_CLOSE"}),
         "evaluatedAt": _time(at), "sourceAt": _time(source), "binding": "NOT_REVALIDATED"}
        for kind, at, source in _rows(connection, report, "evaluation_result")]
    report["persistedLiveness"] = [
        {"lastAliveAt": _time(at), "authority": "UNKNOWN"}
        for (at,) in _rows(connection, report, "runtime_liveness")]
    report["coverageRecords"] = [
        {"versionId": _id(identity), "revision": _revision(revision), "createdAt": _time(at)}
        for identity, revision, at in _rows(connection, report, "source_coverage_assessment")]
    report["coverageReviews"] = [
        {"versionId": _id(identity), "revision": _revision(revision)}
        for identity, revision in _rows(connection, report, "source_coverage_review")]
    plan_ids = {row["versionId"] for row in report["plans"]}
    review_ids = {row["versionId"] for row in report["reviews"]}
    report["activeReferenceGaps"] = [
        {"versionId": row["versionId"], "missingPlan": row["versionId"] not in plan_ids,
         "missingReview": row["versionId"] not in review_ids}
        for row in report["activePlans"]
        if row["versionId"] not in plan_ids or row["versionId"] not in review_ids]


def audit_database(database: Path) -> dict:
    """Return redacted bounded persisted facts, never current approval or readiness."""
    report = {"auditVersion": "plan-readiness-installation-v1",
        "computedAt": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "provenance": "PERSISTED_ONLY", "authorityGranted": False,
        "installationStatus": "NOT_READY", "runtimeOwnership": "UNKNOWN",
        "notificationConfiguration": "UNKNOWN", "database": "MISSING",
        "schema": {}, "migration": [], "coverageInstallation": {"state": "UNKNOWN"},
        "plans": [], "reviews": [], "activePlans": [], "activationStates": [],
        "evaluations": [], "deliveryAttempts": [], "coverageRecords": [], "coverageReviews": [],
        "legacyEvaluations": [], "persistedLiveness": [],
        "activeReferenceGaps": [],
        "limitedSections": [],
        "samplePolicy": "ACTIVE_REFERENCES_FIRST_THEN_SORTED_SAMPLE_100_ACTIVE_LIMIT_10",
        "missingEvidence": ["CURRENT_OWNER_SNAPSHOT", "CURRENT_NOTIFICATION_CONFIGURATION",
                            "CURRENT_DATA_EVALUATION_AND_EXACT_BINDINGS"]}
    try:
        path = Path(database).expanduser().resolve(strict=True)
        if not path.is_file():
            return report
        with path.open("rb") as stream:
            header = stream.read(20)
        if header[18:20] == b"\x02\x02" and not all(
                Path(str(path) + suffix).is_file() for suffix in ("-wal", "-shm")):
            report["database"] = "WAL_SIDECARS_UNAVAILABLE"
            return report
        with closing(sqlite3.connect(
                path.as_uri() + "?mode=ro", uri=True, timeout=1)) as connection:
            # Bound SQLite values too, including hostile catalog/metadata cells.
            connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_OUTPUT_BYTES)
            deadline, steps = monotonic() + 5, 0

            def budget():
                nonlocal steps
                steps += 1000
                return int(steps > 1_000_000 or monotonic() > deadline)

            connection.set_progress_handler(budget, 1000)
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            _collect(connection, report)
            report["database"] = "READABLE"
    except FileNotFoundError:
        pass
    except (OSError, sqlite3.Error, ValueError, RecursionError):
        report["database"] = "UNAVAILABLE_OR_BUDGET_EXCEEDED"
    if len(json.dumps(report, ensure_ascii=True).encode()) > MAX_OUTPUT_BYTES:
        # Keep no partial record set that could be mistaken for a complete audit.
        return {key: value for key, value in report.items() if key in {
            "auditVersion", "computedAt", "provenance", "authorityGranted", "installationStatus",
            "runtimeOwnership", "notificationConfiguration", "missingEvidence"}} | {
                "database": "OUTPUT_LIMIT_EXCEEDED"}
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--read-only", action="store_true", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    report = audit_database(args.database)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    destination = args.output_dir / "audit.json"
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(report, ensure_ascii=True, indent=2) + "\n")
    print("PERSISTED_ONLY NOT_READY")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
