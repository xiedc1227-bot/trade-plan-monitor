"""Read only the two isolated browser databases and verify durable lineage."""

import json
import sqlite3
from hashlib import sha256
from pathlib import Path

from trade_plan_monitor.decision.explicit_rules import ExplicitEvaluationResult

EVIDENCE = Path(__file__).resolve().parent
REPO = EVIDENCE.parents[2]
SOURCE = json.loads(
    (REPO / "tests/fixtures/ai/explicit-plan-literal-source-v3.json").read_text("utf-8")
)["sourceText"]


def inspect(root, *, corrections):
    database = Path(root) / "monitor.sqlite3"
    assert database.parent.name.startswith("tpm-r12-browser-")
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        sources = connection.execute("SELECT * FROM plan_source").fetchall()
        assert sources and all(row["source_text"] == SOURCE for row in sources)
        assert all(row["source_hash"] == sha256(SOURCE.encode()).hexdigest() for row in sources)
        versions = []
        for row in connection.execute(
            "SELECT p.id,p.version,p.plan_hash,p.status,p.payload_json,r.content_hash,"
            "r.review_id,r.review_evidence_hash,r.mapping_json FROM plan_version p "
            "JOIN plan_review_provenance r ON r.plan_version_id=p.id ORDER BY p.version"
        ):
            plan = json.loads(row["payload_json"])
            mapping = json.loads(row["mapping_json"])
            versions.append(
                {
                    key: row[key]
                    for key in (
                        "id",
                        "version",
                        "plan_hash",
                        "status",
                        "content_hash",
                        "review_id",
                        "review_evidence_hash",
                    )
                }
                | {
                    "operator": plan["rules"][0]["condition"]["type"],
                    "low_fen": plan["rules"][0]["condition"]["conditions"][0]["low_fen"],
                    "quantity": plan["rules"][0]["action"]["quantity"],
                    "logicalBindings": [
                        b
                        for b in mapping["field_bindings"]
                        if b["path"] in ("rules[0].condition", "rules[0].condition.type")
                    ],
                }
            )
        expected = (
            [
                (1, "ALL", 980, 100),
                (2, "ALL", 980, 100),
                (3, "ALL", 981, 100),
                (4, "ALL", 981, 200),
                (5, "ANY", 981, 200),
                (6, "ANY", 982, 200),
                (7, "ANY", 982, 100),
                (8, "ALL", 982, 100),
            ]
            if corrections
            else [(1, "ALL", 980, 100), (2, "ALL", 980, 100)]
        )
        assert [
            (v["version"], v["operator"], v["low_fen"], v["quantity"]) for v in versions
        ] == expected
        assert all(v["review_id"] for v in versions[1:])
        if corrections:
            for v in versions[4:]:
                assert len(v["logicalBindings"]) == 2
                assert all(
                    b["origin"] == "USER_SUPPLEMENT" and b["value"] == v["operator"]
                    for b in v["logicalBindings"]
                )
        results = {}
        for row in connection.execute("SELECT * FROM explicit_evaluation_ledger"):
            validated = ExplicitEvaluationResult.model_validate_json(row["result_json"])
            assert validated.result_hash == row["result_hash"]
            results[
                (
                    row["plan_hash"],
                    row["activation_revision"],
                    validated.target_bucket_end.isoformat(),
                )
            ] = validated
        events = []
        for row in connection.execute("SELECT * FROM alert_event ORDER BY sequence"):
            event = json.loads(row["payload_json"])
            result = results[
                (event["plan_hash"], event["activation_revision"], event["target_bucket_end"])
            ]
            assert any(
                intent.action.type == event["signal_type"] for intent in result.signal_intents
            )
            attempts = [
                dict(item)
                for item in connection.execute(
                    "SELECT channel,attempt,status,error_code FROM delivery_attempt "
                    "WHERE event_id=?",
                    (row["id"],),
                )
            ]
            assert attempts == [
                {"channel": "IN_APP", "attempt": 1, "status": "DELIVERED", "error_code": None}
            ]
            assert row["acknowledged_at"] is not None
            events.append(
                {
                    key: event[key]
                    for key in (
                        "event_id",
                        "plan_version",
                        "plan_hash",
                        "activation_revision",
                        "target_bucket_end",
                        "signal_type",
                        "quantity",
                    )
                }
                | {
                    "resultHash": result.result_hash,
                    "attempts": attempts,
                    "acknowledgedAt": row["acknowledged_at"],
                }
            )
        assert [(e["plan_version"], e["signal_type"], e["quantity"]) for e in events] == (
            [(5, "BUY", 200), (8, "BUY", 100)]
            if corrections
            else [(2, "BUY", 100), (2, "SELL", 100), (2, "RISK_ALERT", None)]
        )
        activation = dict(connection.execute("SELECT * FROM plan_activation_state").fetchone())
        if corrections:
            assert activation["plan_version_id"] == versions[-1]["id"]
            assert activation["revision"] == 3
        return {
            "database": str(database),
            "readOnly": True,
            "sourceTextUnchanged": True,
            "versions": versions,
            "events": events,
            "validatedResultCount": len(results),
            "activation": activation,
        }


if __name__ == "__main__":
    evidence = {
        "corrections": inspect(
            "C:/Users/xiedc/AppData/Local/Temp/tpm-r12-browser-jaw6y27l", corrections=True
        ),
        "originalLiteralALL": inspect(
            "C:/Users/xiedc/AppData/Local/Temp/tpm-r12-browser-_4_jt5sd", corrections=False
        ),
    }
    (EVIDENCE / "sqlite-lineage.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", "utf-8"
    )
    print(
        "Verified 8 correction versions, 2 changed-plan BUY events, and 3 original ALL events; "
        "all 5 IN_APP attempts delivered."
    )
