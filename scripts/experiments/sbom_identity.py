"""Build-only SBOM identity transform invoked before the wheel writer."""

import copy
import json
import os
import re
import sys
from pathlib import Path


def normalize(bom, source_hash):
    if not re.fullmatch("[0-9a-f]{64}", source_hash):
        raise ValueError("invalid source identity")
    result = copy.deepcopy(bom)
    root = result["metadata"]["component"]["bom-ref"]
    if not root.startswith("path+file:///") or "#" not in root:
        raise ValueError("unexpected root identity")
    stable = "urn:tpm:source:" + source_hash + ":" + root.split("#", 1)[1]
    identities = []

    def visit(value, callback):
        if isinstance(value, dict):
            for key, child in value.items():
                callback(value, key, child)
                visit(value[key], callback)
        elif isinstance(value, list):
            for child in value:
                visit(child, callback)

    def collect(parent, key, value):
        if key == "bom-ref":
            identities.append(value)

    visit(result, collect)
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate component identity")
    mapping = {}
    for identity in identities:
        if identity == root:
            mapping[identity] = stable
        elif identity.startswith(root + " bin-target-"):
            suffix = identity[len(root) :]
            if not re.fullmatch(" bin-target-[0-9]+", suffix):
                raise ValueError("unknown target identity")
            mapping[identity] = stable + suffix
        elif identity.startswith("path+"):
            raise ValueError("unqualified external local dependency")
    if len(set(mapping.values()) | (set(identities) - mapping.keys())) != len(identities):
        raise ValueError("identity collision")
    for edge in result.get("dependencies", []):
        for ref in [edge["ref"], *edge.get("dependsOn", []), *edge.get("provides", [])]:
            if ref not in identities:
                raise ValueError("dangling dependency")

    def rewrite(table):
        def change(parent, key, value):
            if key in ("bom-ref", "ref") and isinstance(value, str):
                parent[key] = table.get(value, value)
            elif key in ("dependsOn", "provides"):
                parent[key] = [table.get(v, v) for v in value]

        return change

    visit(result, rewrite(mapping))
    if root in json.dumps(result, ensure_ascii=False):
        raise ValueError("unhandled local reference")
    restored = copy.deepcopy(result)
    visit(restored, rewrite({v: k for k, v in mapping.items()}))
    if restored != bom:
        raise ValueError("provenance graph changed")
    return result


if __name__ == "__main__":
    raw = json.load(sys.stdin)
    value = normalize(raw, os.environ["TPM_SOURCE_SHA256"])
    audit = Path(os.environ["TPM_SBOM_AUDIT_DIR"])
    audit.mkdir(parents=True, exist_ok=False)
    (audit / "raw.json").write_text(json.dumps(raw, sort_keys=True), encoding="utf8")
    (audit / "normalized.json").write_text(json.dumps(value, sort_keys=True), encoding="utf8")
    sys.stdout.write(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
