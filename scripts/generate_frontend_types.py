"""Freeze the FastAPI OpenAPI document and derive frontend TypeScript contracts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from trade_plan_monitor.web.app import create_app

PROJECT_ROOT: Final = Path(__file__).resolve().parents[1]
OPENAPI_PATH: Final = PROJECT_ROOT / "openapi.json"
TYPESCRIPT_PATH: Final = PROJECT_ROOT / "web" / "src" / "api" / "generated.ts"
_SCHEMA_REF_PREFIX: Final = "#/components/schemas/"
_HTTP_METHODS: Final = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
_TYPESCRIPT_IDENTIFIER = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
_TYPESCRIPT_RESERVED_WORDS: Final = frozenset(
    {
        "abstract",
        "accessor",
        "any",
        "as",
        "asserts",
        "async",
        "await",
        "bigint",
        "boolean",
        "break",
        "case",
        "catch",
        "class",
        "const",
        "constructor",
        "continue",
        "debugger",
        "declare",
        "default",
        "delete",
        "do",
        "else",
        "enum",
        "export",
        "extends",
        "false",
        "finally",
        "for",
        "from",
        "function",
        "get",
        "global",
        "if",
        "implements",
        "import",
        "in",
        "infer",
        "instanceof",
        "interface",
        "intrinsic",
        "is",
        "keyof",
        "let",
        "module",
        "namespace",
        "never",
        "new",
        "null",
        "number",
        "object",
        "of",
        "override",
        "package",
        "private",
        "protected",
        "public",
        "readonly",
        "require",
        "return",
        "satisfies",
        "set",
        "static",
        "string",
        "super",
        "switch",
        "symbol",
        "this",
        "throw",
        "true",
        "try",
        "type",
        "typeof",
        "undefined",
        "unique",
        "unknown",
        "using",
        "var",
        "void",
        "while",
        "with",
        "yield",
    }
)


def build_openapi_document() -> dict[str, object]:
    """Build the public contract from the side-effect-free application factory."""

    document = create_app().openapi()
    return json.loads(json.dumps(document, ensure_ascii=False))


def render_openapi_snapshot(document: Mapping[str, object]) -> str:
    """Serialize OpenAPI with stable ordering, indentation, encoding, and final newline."""

    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


class _TypeScriptRenderer:
    def __init__(self, document: Mapping[str, object]) -> None:
        self._document = document
        components = _mapping(document.get("components"), "components")
        self._schemas = _mapping(components.get("schemas"), "components.schemas")
        self._paths = _mapping(document.get("paths"), "paths")

    def render(self) -> str:
        lines = [
            "// This file is generated from openapi.json by scripts/generate_frontend_types.py.",
            "// Do not edit it by hand; update the FastAPI contract and rerun the generator.",
            "",
        ]
        for name, schema in sorted(self._schemas.items()):
            alias = _typescript_identifier(name)
            lines.append(f"export type {alias} = {self._schema_type(schema)};")
            lines.append("")

        lines.extend(self._render_components())
        lines.append("")
        lines.extend(self._render_paths())
        return "\n".join(lines) + "\n"

    def _render_components(self) -> list[str]:
        lines = ["export interface components {", "  schemas: {"]
        for name in sorted(self._schemas):
            lines.append(f"    {_typescript_key(name)}: {_typescript_identifier(name)};")
        lines.extend(["  };", "}"])
        return lines

    def _render_paths(self) -> list[str]:
        lines = ["export interface paths {"]
        for path, raw_path_item in sorted(self._paths.items()):
            path_item = _mapping(raw_path_item, f"paths.{path}")
            lines.append(f"  {_typescript_key(path)}: {{")
            for method in _HTTP_METHODS:
                if method not in path_item:
                    continue
                operation = _mapping(path_item[method], f"paths.{path}.{method}")
                lines.append(f"    {method}: {{")
                lines.extend(self._render_parameters(operation.get("parameters"), indent=6))
                lines.extend(self._render_request_body(operation.get("requestBody"), indent=6))
                lines.extend(self._render_responses(operation.get("responses"), indent=6))
                lines.append("    };")
            lines.append("  };")
        lines.append("}")
        return lines

    def _render_parameters(self, raw_parameters: object, *, indent: int) -> list[str]:
        grouped: dict[str, list[Mapping[str, object]]] = {
            "query": [],
            "header": [],
            "path": [],
            "cookie": [],
        }
        if raw_parameters is not None:
            for index, raw_parameter in enumerate(
                _sequence(raw_parameters, "operation.parameters")
            ):
                parameter = _mapping(raw_parameter, f"operation.parameters[{index}]")
                location = parameter.get("in")
                if location not in grouped:
                    raise ValueError(f"unsupported OpenAPI parameter location: {location!r}")
                grouped[location].append(parameter)

        pad = " " * indent
        lines = [f"{pad}parameters: {{"]
        for location in ("query", "header", "path", "cookie"):
            parameters = grouped[location]
            optional_group = (
                ""
                if parameters and any(parameter.get("required") is True for parameter in parameters)
                else "?"
            )
            if not parameters:
                lines.append(f"{pad}  {location}?: never;")
                continue
            lines.append(f"{pad}  {location}{optional_group}: {{")
            for parameter in sorted(parameters, key=lambda item: str(item.get("name"))):
                name = parameter.get("name")
                if not isinstance(name, str) or not name:
                    raise ValueError("OpenAPI parameter name must be a non-empty string")
                optional = "" if parameter.get("required") is True else "?"
                schema = _mapping(parameter.get("schema"), f"parameter {name}.schema")
                lines.append(
                    f"{pad}    {_typescript_key(name)}{optional}: {self._schema_type(schema)};"
                )
            lines.append(f"{pad}  }};")
        lines.append(f"{pad}}};")
        return lines

    def _render_request_body(self, raw_request_body: object, *, indent: int) -> list[str]:
        pad = " " * indent
        if raw_request_body is None:
            return [f"{pad}requestBody?: never;"]
        request_body = _mapping(raw_request_body, "operation.requestBody")
        optional = "" if request_body.get("required") is True else "?"
        content = _mapping(request_body.get("content"), "operation.requestBody.content")
        lines = [f"{pad}requestBody{optional}: {{", f"{pad}  content: {{"]
        lines.extend(self._render_content(content, indent=indent + 4))
        lines.extend([f"{pad}  }};", f"{pad}}};"])
        return lines

    def _render_responses(self, raw_responses: object, *, indent: int) -> list[str]:
        responses = _mapping(raw_responses, "operation.responses")
        pad = " " * indent
        lines = [f"{pad}responses: {{"]
        for status_code, raw_response in sorted(responses.items()):
            response = _mapping(raw_response, f"operation.responses.{status_code}")
            content = response.get("content")
            lines.append(f"{pad}  {_typescript_key(status_code)}: {{")
            if content is None:
                lines.append(f"{pad}    content?: never;")
            else:
                lines.append(f"{pad}    content: {{")
                lines.extend(
                    self._render_content(
                        _mapping(content, f"operation.responses.{status_code}.content"),
                        indent=indent + 6,
                    )
                )
                lines.append(f"{pad}    }};")
            lines.append(f"{pad}  }};")
        lines.extend([f"{pad}}};"])
        return lines

    def _render_content(self, content: Mapping[str, object], *, indent: int) -> list[str]:
        pad = " " * indent
        lines: list[str] = []
        for media_type, raw_media in sorted(content.items()):
            media = _mapping(raw_media, f"content.{media_type}")
            schema = _mapping(media.get("schema"), f"content.{media_type}.schema")
            lines.append(f"{pad}{_typescript_key(media_type)}: {self._schema_type(schema)};")
        return lines

    def _schema_type(self, raw_schema: object, *, level: int = 0) -> str:
        schema = _mapping(raw_schema, "schema")
        reference = schema.get("$ref")
        if reference is not None:
            if not isinstance(reference, str) or not reference.startswith(_SCHEMA_REF_PREFIX):
                raise ValueError(f"unsupported OpenAPI schema reference: {reference!r}")
            name = reference.removeprefix(_SCHEMA_REF_PREFIX)
            if name not in self._schemas:
                raise ValueError(f"OpenAPI schema reference is missing: {name}")
            return f'components["schemas"][{json.dumps(name, ensure_ascii=False)}]'

        for keyword, separator in (("oneOf", " | "), ("anyOf", " | "), ("allOf", " & ")):
            if keyword in schema:
                variants = _sequence(schema[keyword], f"schema.{keyword}")
                if not variants:
                    raise ValueError(f"OpenAPI {keyword} must not be empty")
                return separator.join(
                    f"({self._schema_type(variant, level=level)})" for variant in variants
                )

        if "const" in schema:
            return _typescript_literal(schema["const"])
        if "enum" in schema:
            values = _sequence(schema["enum"], "schema.enum")
            if not values:
                return "never"
            return " | ".join(_typescript_literal(value) for value in values)

        schema_type = schema.get("type")
        if isinstance(schema_type, list):
            return " | ".join(
                self._schema_type({**schema, "type": item}, level=level) for item in schema_type
            )
        if schema_type == "string":
            return "string"
        if schema_type in {"integer", "number"}:
            return "number"
        if schema_type == "boolean":
            return "boolean"
        if schema_type == "null":
            return "null"
        if schema_type == "array":
            return f"Array<{self._schema_type(schema.get('items'), level=level + 1)}>"
        if schema_type == "object" or "properties" in schema or "additionalProperties" in schema:
            return self._object_type(schema, level=level)
        if schema_type is None:
            return "unknown"
        raise ValueError(f"unsupported OpenAPI schema type: {schema_type!r}")

    def _object_type(self, schema: Mapping[str, object], *, level: int) -> str:
        properties = _mapping(schema.get("properties", {}), "schema.properties")
        required_values = schema.get("required", [])
        required = set(_string_sequence(required_values, "schema.required"))
        unknown_required = required - set(properties)
        if unknown_required:
            raise ValueError(f"OpenAPI required properties are missing: {sorted(unknown_required)}")

        pad = "  " * level
        child_pad = "  " * (level + 1)
        lines = ["{"]
        for name, property_schema in sorted(properties.items()):
            optional = "" if name in required else "?"
            rendered = self._schema_type(property_schema, level=level + 1)
            lines.append(f"{child_pad}{_typescript_key(name)}{optional}: {rendered};")

        additional = schema.get("additionalProperties")
        if additional is True:
            lines.append(f"{child_pad}[key: string]: unknown;")
        elif isinstance(additional, Mapping):
            lines.append(
                f"{child_pad}[key: string]: {self._schema_type(additional, level=level + 1)};"
            )
        elif additional not in {None, False}:
            raise ValueError(f"unsupported additionalProperties value: {additional!r}")
        lines.append(f"{pad}}}")
        return "\n".join(lines)


def render_typescript_contracts(document: Mapping[str, object]) -> str:
    """Generate frontend payload and operation types directly from OpenAPI."""

    return _TypeScriptRenderer(document).render()


def find_stale_outputs(
    *,
    snapshot: str,
    typescript: str,
    snapshot_path: Path = OPENAPI_PATH,
    typescript_path: Path = TYPESCRIPT_PATH,
) -> tuple[Path, ...]:
    """Return generated files whose exact committed bytes differ from expected output."""

    expected = ((snapshot_path, snapshot), (typescript_path, typescript))
    return tuple(
        path
        for path, content in expected
        if not path.is_file() or path.read_bytes() != content.encode("utf-8")
    )


def _write_generated(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8"))


def _mapping(value: object, location: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"OpenAPI {location} must be an object with string keys")
    return value


def _sequence(value: object, location: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"OpenAPI {location} must be an array")
    return value


def _string_sequence(value: object, location: str) -> tuple[str, ...]:
    values = _sequence(value, location)
    if any(not isinstance(item, str) for item in values):
        raise ValueError(f"OpenAPI {location} must contain only strings")
    return tuple(values)  # type: ignore[arg-type]


def _typescript_identifier(value: str) -> str:
    if not _TYPESCRIPT_IDENTIFIER.fullmatch(value) or value in _TYPESCRIPT_RESERVED_WORDS:
        raise ValueError(f"OpenAPI schema name is not a usable TypeScript identifier: {value!r}")
    return value


def _typescript_key(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError(f"OpenAPI property key must be a string: {value!r}")
    return (
        value if _TYPESCRIPT_IDENTIFIER.fullmatch(value) else json.dumps(value, ensure_ascii=False)
    )


def _typescript_literal(value: object) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return json.dumps(value, ensure_ascii=False, allow_nan=False)
    raise ValueError(f"unsupported OpenAPI literal: {value!r}")


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate the committed OpenAPI snapshot and frontend TypeScript contracts."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail without writing when either generated file differs",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    document = build_openapi_document()
    snapshot = render_openapi_snapshot(document)
    typescript = render_typescript_contracts(document)
    stale = find_stale_outputs(snapshot=snapshot, typescript=typescript)
    if args.check:
        if stale:
            for path in stale:
                print(
                    f"stale generated contract: {path.relative_to(PROJECT_ROOT)}", file=sys.stderr
                )
            return 1
        print("OpenAPI snapshot and frontend types are current")
        return 0

    _write_generated(OPENAPI_PATH, snapshot)
    _write_generated(TYPESCRIPT_PATH, typescript)
    print(f"generated {OPENAPI_PATH.relative_to(PROJECT_ROOT)}")
    print(f"generated {TYPESCRIPT_PATH.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
