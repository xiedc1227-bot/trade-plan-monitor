"""Read only recorded synthetic browser databases; preserve compact fresh evidence."""

import importlib.util
import json
import re
import shutil
import sqlite3
from hashlib import sha256
from pathlib import Path

from trade_plan_monitor.decision.explicit_rules import ExplicitEvaluationResult
from trade_plan_monitor.notifications.models import ExplicitAlertPayload

OUT = Path(__file__).resolve().parent
REPO = OUT.parents[2]
SOURCE_PATH = REPO / "tests/fixtures/ai/explicit-plan-literal-source-v3.json"
SOURCE = json.loads(SOURCE_PATH.read_text("utf-8"))["sourceText"]


def inspect_restart(root, transition):
    database = Path(root) / "monitor.sqlite3"
    assert database.parent.name.startswith("tpm-r12-browser-")
    record = json.loads((Path(root) / f"restart-{transition}.json").read_text("utf-8"))
    processes = [r["process"] for r in record["records"] if "process" in r]
    assert len(processes) == 2 and processes[0]["pid"] != processes[1]["pid"]
    assert processes[0]["database"] == processes[1]["database"] == str(database)
    assert any(r.get("offlineProbe") == "ECONNREFUSED" for r in record["records"])
    assert len([r for r in record["records"] if r.get("serverExited")]) == 2
    assert not record["consoleErrors"] and not record["externalRequests"]
    final = next(r for r in record["records"] if "finalAlerts" in r)
    assert final["finalInventory"]["totalQuantity"] == 100
    assert final["finalInventory"]["sellableQuantity"] == 100
    assert final["finalInventory"]["inventoryRevision"] == 1
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        sources = connection.execute("SELECT source_text,source_hash FROM plan_source").fetchall()
        assert sources and all(r["source_text"] == SOURCE for r in sources)
        assert all(r["source_hash"] == sha256(SOURCE.encode()).hexdigest() for r in sources)
        versions = {}
        for row in connection.execute(
            "SELECT p.id,p.version,p.plan_hash,p.status,p.payload_json,r.review_id "
            "FROM plan_version p JOIN plan_review_provenance r ON r.plan_version_id=p.id"
        ):
            if row["version"] == 1:
                continue
            plan = json.loads(row["payload_json"])
            assert row["review_id"]
            assert all(r["repeat_policy"]["mode"] == "EACH_QUALIFYING_BAR" for r in plan["rules"])
            versions[row["plan_hash"]] = {k: row[k] for k in row.keys() if k != "payload_json"}
        results = {}
        for row in connection.execute("SELECT * FROM explicit_evaluation_ledger"):
            result = ExplicitEvaluationResult.model_validate_json(row["result_json"])
            assert result.result_hash == row["result_hash"]
            key = (
                result.plan_hash,
                result.activation_revision,
                result.target_bucket_end.isoformat(),
            )
            assert key not in results
            results[key] = result
        events = []
        for row in connection.execute("SELECT * FROM alert_event ORDER BY sequence"):
            event = ExplicitAlertPayload.model_validate_json(row["payload_json"])
            result = results[
                (event.plan_hash, event.activation_revision, event.target_bucket_end.isoformat())
            ]
            assert event.plan_version == versions[event.plan_hash]["version"]
            assert any(
                s.action.type == event.signal_type and s.rule_id == event.rule_id
                for s in result.signal_intents
            )
            attempts = [
                dict(r)
                for r in connection.execute(
                    "SELECT channel,attempt,status,error_code FROM delivery_attempt "
                    "WHERE event_id=?",
                    (row["id"],),
                )
            ]
            assert attempts == [
                {"channel": "IN_APP", "attempt": 1, "status": "DELIVERED", "error_code": None}
            ]
            events.append(
                {
                    "eventId": str(event.event_id),
                    "planVersion": event.plan_version,
                    "planHash": event.plan_hash,
                    "activationRevision": event.activation_revision,
                    "cutoff": event.target_bucket_end.isoformat(),
                    "resultHash": result.result_hash,
                    "action": event.signal_type,
                    "quantity": event.quantity,
                    "acknowledgedAt": row["acknowledged_at"],
                    "attempts": attempts,
                }
            )
        assert len(events) == {"active": 4, "replace": 2, "disable": 1, "expire": 1}[transition]
        assert events[0]["acknowledgedAt"] is not None
        if transition == "active":
            buys = [e for e in events if e["action"] == "BUY"]
            assert len(buys) == 2 and buys[0]["planHash"] == buys[1]["planHash"]
            assert [e["cutoff"][11:16] for e in buys] == ["10:10", "10:30"]
            assert all(e["acknowledgedAt"] for e in events)
        elif transition == "replace":
            assert [(e["planVersion"], e["action"]) for e in events] == [(2, "BUY"), (3, "SELL")]
        balances = [dict(r) for r in connection.execute("SELECT * FROM position_opening_balance")]
        assert len(balances) == 1 and balances[0]["remaining_qty"] == 100
        states = [
            dict(r) for r in connection.execute("SELECT * FROM explicit_rule_occurrence_state")
        ]
    return {
        "database": str(database),
        "readOnly": True,
        "transition": transition,
        "processIds": [p["pid"] for p in processes],
        "sourceTextUnchanged": True,
        "versions": list(versions.values()),
        "events": events,
        "ruleStates": states,
        "validatedResultCount": len(results),
        "inventory": final["finalInventory"],
        "activation": final["finalActivation"],
        "consoleErrors": [],
        "externalRequests": [],
        "offlineProbe": "ECONNREFUSED",
        "stopMode": "forced owned OS process exit",
    }


def collect():
    log = (OUT / "final-browser.log").read_text("utf-8")
    patterns = {
        "originalLiteralALL": r"R12 browser evidence: ([^\r\n]+)",
        "corrections": r"R13 correction evidence: ([^\r\n]+)",
        "faults": r"R13 fault evidence: ([^\r\n]+)",
        "stream": r"R13 stream evidence: ([^\r\n]+)",
    }
    roots = {name: re.findall(pattern, log)[-1] for name, pattern in patterns.items()}
    roots.update(
        {
            f"restart-{name}": re.findall(rf"R13 OS {name} evidence: ([^\r\n]+)", log)[-1]
            for name in ("active", "replace", "disable", "expire")
        }
    )
    spec = importlib.util.spec_from_file_location(
        "prior_lineage_checker", OUT.parent / "R13-N02/verify_sqlite.py"
    )
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    lineage = {
        "originalLiteralALL": helper.inspect(roots["originalLiteralALL"], corrections=False),
        "corrections": helper.inspect(roots["corrections"], corrections=True),
    }
    lineage.update(
        {
            f"restart-{name}": inspect_restart(roots[f"restart-{name}"], name)
            for name in ("active", "replace", "disable", "expire")
        }
    )
    for name, root in roots.items():
        target = OUT / "final-journeys" / name
        target.mkdir(parents=True, exist_ok=True)
        for item in Path(root).iterdir():
            if item.is_file() and item.suffix in {".png", ".json"}:
                shutil.copy2(item, target / item.name)
    (OUT / "final-browser-roots.json").write_text(json.dumps(roots, indent=2) + "\n", "utf-8")
    (OUT / "final-sqlite-lineage.json").write_text(
        json.dumps(lineage, ensure_ascii=False, indent=2) + "\n", "utf-8"
    )
    print(
        "Verified final ALL/correction and four OS-restart databases; 13 first-attempt deliveries."
    )


if __name__ == "__main__":
    collect()
