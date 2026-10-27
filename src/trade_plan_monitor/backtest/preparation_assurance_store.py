"""Independent preparation evidence; old candidate documents/hashes stay unchanged."""

import sqlite3
from contextlib import closing
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from pydantic import Field, model_validator

from trade_plan_monitor.ai.source_coverage_models import MAX_PROOF_BYTES, Hash
from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.domain.daily_plan_models import DailyValue, Identifier
from trade_plan_monitor.market_data.models import ShanghaiDatetime
from trade_plan_monitor.state.source_coverage_values import CoverageInputs

ASSURANCE_TABLES = frozenset({
    "backtest_preparation_assurance_metadata", "backtest_preparation_assurance",
})
_BASE_TABLES = frozenset({
    "backtest_preparation_metadata", "backtest_preparation", "backtest_preparation_idempotency",
    "backtest_plan_selection",
})


def _trigger_sql():
    statements = {}
    for table, operations in (
        ("backtest_preparation_assurance", ("update", "delete")),
        ("backtest_preparation_assurance_metadata", ("insert", "update", "delete")),
    ):
        for operation in operations:
            name = "pma_" + table.removeprefix("backtest_") + "_" + operation
            statements[name] = (
                f"CREATE TRIGGER {name} BEFORE {operation.upper()} ON {table} "
                "BEGIN SELECT RAISE(ABORT,'preparation source evidence is immutable'); END"
            )
    return MappingProxyType(statements)


ASSURANCE_TRIGGERS = _trigger_sql()


def _conflict(code):
    from trade_plan_monitor.backtest.preparation_store import PreparationConflictError

    return PreparationConflictError(code)


class PreparationInputEvidence(DailyValue):
    version: Literal["preparation-input-evidence-v1"] = "preparation-input-evidence-v1"
    kind: Literal["INPUT"] = "INPUT"
    preparation_id: Identifier
    item_index: int = Field(strict=True, ge=0, le=511)
    attempt_id: Identifier
    source_binding_hash: Hash
    candidate_hash: Hash
    inputs: CoverageInputs
    created_at: ShanghaiDatetime
    authority_granted: Literal[False] = False
    evidence_key: Hash
    evidence_hash: Hash

    def identity(self):
        return daily_hash("preparation-input-evidence-key-v1", dict(
            preparation_id=self.preparation_id, item_index=self.item_index,
            attempt_id=self.attempt_id,
        ))

    def intent(self):
        return self.model_dump(mode="json", exclude={"created_at", "evidence_hash"})

    @model_validator(mode="after")
    def verify(self):
        payload = self.model_dump(mode="json", exclude={"evidence_hash"})
        if self.evidence_key != self.identity():
            raise ValueError("preparation evidence identity differs")
        if self.source_binding_hash != self.inputs.source_binding_hash:
            raise ValueError("preparation source binding differs from captured input")
        if len(canonical(payload).encode()) > MAX_PROOF_BYTES:
            raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")
        if self.evidence_hash != daily_hash(self.version, payload):
            raise ValueError("preparation source evidence hash differs")
        return self

    @classmethod
    def build(cls, **values):
        unsigned = cls.model_construct(**values, evidence_key="", evidence_hash="")
        unsigned = cls.model_construct(**values, evidence_key=unsigned.identity(), evidence_hash="")
        payload = unsigned.model_dump(mode="json", exclude={"evidence_hash"})
        return cls.model_validate(payload | {
            "evidence_hash": daily_hash(unsigned.version, payload),
        })


def assurance_available(connection):
    """Missing auxiliary tables are unknown; this read never initializes them."""
    present = {row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'",
    )} & ASSURANCE_TABLES
    if not present:
        return False
    try:
        if present != ASSURANCE_TABLES or connection.execute(
            "SELECT singleton,domain,schema_version FROM backtest_preparation_assurance_metadata",
        ).fetchall() != [(1, "preparation-assurance-store-v1", 1)]:
            raise ValueError("auxiliary metadata")
        guards = dict(connection.execute(
            "SELECT name,sql FROM sqlite_master WHERE type='trigger'",
        ).fetchall())
        if any(guards.get(name) != sql for name, sql in ASSURANCE_TRIGGERS.items()):
            raise ValueError("auxiliary protection")
    except (ValueError, TypeError, sqlite3.DatabaseError):
        raise _conflict("SOURCE_COVERAGE_INTEGRITY") from None
    return True


def create_assurance_schema(connection):
    """Only a new owned store or an explicit upgrade calls this mutation."""
    connection.execute(
        "CREATE TABLE backtest_preparation_assurance_metadata "
        "(singleton INTEGER PRIMARY KEY CHECK(singleton=1),domain TEXT NOT NULL,"
        "schema_version INTEGER NOT NULL)",
    )
    connection.execute(
        "INSERT INTO backtest_preparation_assurance_metadata VALUES "
        "(1,'preparation-assurance-store-v1',1)",
    )
    connection.execute(
        "CREATE TABLE backtest_preparation_assurance "
        "(evidence_key TEXT PRIMARY KEY,preparation_id TEXT NOT NULL,item_index INTEGER NOT NULL "
        "CHECK(item_index>=0 AND item_index<=511),attempt_id TEXT NOT NULL,kind TEXT NOT NULL,"
        "source_binding_hash TEXT NOT NULL,candidate_hash TEXT NOT NULL,payload_json TEXT NOT NULL,"
        "evidence_hash TEXT NOT NULL,created_at TEXT NOT NULL,"
        "UNIQUE(preparation_id,attempt_id,kind))",
    )
    for statement in ASSURANCE_TRIGGERS.values():
        connection.execute(statement)


def upgrade_preparation_assurance(path):
    """Explicit additive upgrade; implementation invokes it only on disposable stores."""
    path = Path(path).resolve()
    with closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True)) as connection:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'",
            )}
            base = tables - ASSURANCE_TABLES
            if base not in {_BASE_TABLES, _BASE_TABLES - {"backtest_plan_selection"}}:
                raise _conflict("SOURCE_COVERAGE_INTEGRITY")
            tag = connection.execute(
                "SELECT singleton,domain,schema_version FROM backtest_preparation_metadata",
            ).fetchall()
            if tag not in ([(1, "backtest-preparation-v1", 1)],
                            [(1, "backtest-preparation-v1", 2)]):
                raise _conflict("SOURCE_COVERAGE_INTEGRITY")
            if not assurance_available(connection):
                create_assurance_schema(connection)


def input_evidence(connection, preparation_id, attempt_id):
    if not assurance_available(connection):
        return None
    try:
        row = connection.execute(
            "SELECT evidence_key,preparation_id,item_index,attempt_id,kind,source_binding_hash,"
            "candidate_hash,payload_json,evidence_hash,created_at "
            "FROM backtest_preparation_assurance "
            "WHERE preparation_id=? AND attempt_id=? AND kind='INPUT'",
            (preparation_id, attempt_id),
        ).fetchone()
        if row is None:
            return None
        value = PreparationInputEvidence.model_validate_json(row[7])
        if (canonical(value.model_dump(mode="json")) != row[7]
                or (value.evidence_key, value.preparation_id, value.item_index, value.attempt_id,
                    value.kind, value.source_binding_hash, value.candidate_hash,
                    value.evidence_hash, value.created_at.isoformat()) != (*row[:7], *row[8:])):
            raise ValueError("stored evidence projection")
        return value
    except (ValueError, TypeError, RecursionError, sqlite3.DatabaseError):
        raise _conflict("SOURCE_COVERAGE_INTEGRITY") from None


def save_input_evidence(connection, evidence):
    if not assurance_available(connection):
        raise _conflict("SOURCE_COVERAGE_UPGRADE_REQUIRED")
    evidence = PreparationInputEvidence.model_validate_json(evidence.model_dump_json())
    previous = input_evidence(connection, evidence.preparation_id, evidence.attempt_id)
    if previous is not None:
        if previous.intent() != evidence.intent():
            raise _conflict("SOURCE_COVERAGE_COMMAND_CONFLICT")
        return previous
    connection.execute(
        "INSERT INTO backtest_preparation_assurance VALUES (?,?,?,?,?,?,?,?,?,?)",
        (evidence.evidence_key, evidence.preparation_id, evidence.item_index, evidence.attempt_id,
         evidence.kind, evidence.source_binding_hash, evidence.candidate_hash,
         canonical(evidence.model_dump(mode="json")), evidence.evidence_hash,
         evidence.created_at.isoformat()),
    )
    return evidence
