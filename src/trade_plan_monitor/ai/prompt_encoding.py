"""Compact prompt representations without changing source evidence or validation."""

import json

from trade_plan_monitor.ai.review import server_source_clauses


def schema_outline(schema: dict) -> str:
    """Readable named types; the runtime still validates the complete schema."""
    def render(node):
        if "$ref" in node:
            return node["$ref"].rsplit("/", 1)[-1]
        if "const" in node:
            return json.dumps(node["const"], ensure_ascii=False)
        if "enum" in node:
            return "|".join(json.dumps(v, ensure_ascii=False) for v in node["enum"])
        if "anyOf" in node or "oneOf" in node:
            return "(" + "|".join(render(v) for v in node.get("anyOf", node.get("oneOf"))) + ")"
        if node.get("type") == "object":
            required = node.get("required", ())
            value = "{" + ",".join(
                key + ("" if key in required else "?") + ":" + render(child)
                for key, child in node.get("properties", {}).items()) + "}"
            if node.get("additionalProperties") is False:
                value += " (no extra fields)"
        elif node.get("type") == "array":
            value = "Array<" + render(node.get("items", {})) + ">"
        else:
            value = str(node.get("type", "JSON"))
        constraints = {k: node[k] for k in (
            "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
            "minLength", "maxLength", "minItems", "maxItems", "pattern", "format",
        ) if k in node}
        return value + (json.dumps(constraints, ensure_ascii=False, separators=(",", ":"))
                        if constraints else "")

    return "Root=" + render(schema) + "\n" + "\n".join(
        key + "=" + render(value) for key, value in schema.get("$defs", {}).items())


def compact_schema(schema: dict) -> str:
    """Omit titles and redundant union dispatch hints; retain every validation constraint.

    JSON Schema oneOf/const still define each union. The OpenAPI discriminator
    annotation repeats those tags and is not a JSON Schema validation keyword.
    Literal values and property names are deliberately not traversed as schemas.
    """

    def visit(node):
        if not isinstance(node, dict):
            return node
        result = {
            key: value for key, value in node.items() if key not in {"title", "discriminator"}
        }
        for key in ("$defs", "definitions", "properties", "patternProperties", "dependentSchemas"):
            if key in result:
                result[key] = {name: visit(value) for name, value in result[key].items()}
        for key in ("items", "additionalProperties", "contains", "not", "if", "then", "else"):
            if key in result:
                result[key] = visit(result[key])
        for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
            if key in result:
                result[key] = [visit(value) for value in result[key]]
        return result

    return json.dumps(visit(schema), ensure_ascii=False, separators=(",", ":"))


def source_clause_evidence(text: str) -> list[dict]:
    """Send exact identities/spans/excerpts, without empty output classification placeholders."""
    return [
        clause.model_dump(mode="json", include={"clause_id", "start", "end", "excerpt"})
        for clause in server_source_clauses(text)
    ]


def compact_previous_proposal(value, predecessor):
    """Summarize redundant unapproved context, never trim authoritative source data."""
    draft = value.get("draft", {})
    changes = {key: child for key, child in draft.items() if child != predecessor.get(key)}
    groups = {}
    for group in value.get("clause_groups", ()):
        key = group["meaning"], group["disposition"]
        groups.setdefault(key, []).extend(group["clause_ids"])
    return {"draft_changes_from_predecessor": changes,
        "operations": value.get("operations", []),
        "clause_groups": [dict(meaning=key[0], disposition=key[1],
                               clause_ids=list(dict.fromkeys(ids)))
                          for key, ids in groups.items()],
        "classification_reasons_omitted": True}
