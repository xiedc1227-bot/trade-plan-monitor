"""Exact JSON value spans for finite native predicates and ALL/ANY relations."""

import json
from dataclasses import dataclass

from trade_plan_monitor.domain.daily_hash import daily_hash

_PREDICATES = frozenset({
    "DAILY_PRICE_COMPARE", "DAILY_INDICATOR_COMPARE", "DAILY_PRICE_IN_RANGE",
    "DAILY_VOLUME_RATIO", "DAILY_CANDLE_RATIO", "DAILY_CLOSE_SEQUENCE", "DAILY_PRIOR_CLOSE",
    "REVIEWED_FACT", "MINUTE_CLOSE_IN_RANGE", "MINUTE_CLOSE_BELOW", "MINUTE_VOLUME_TO_MEAN_GTE",
})


@dataclass(frozen=True)
class SemanticAtom:
    path: str
    value: object
    start: int
    end: int
    kind: str
    group_id: str
    relation_ids: tuple[str, ...]


def semantic_atoms(source, declaration):
    """Read admitted JSON tokens only; never execute source paths or expressions."""
    decoder = json.JSONDecoder()
    start = source.index("=", declaration.start, declaration.end) + 1

    def skip(position):
        while source[position].isspace():
            position += 1
        return position

    def walk(value, path, position, parents=(), depth=0):
        if depth > 64:
            raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")
        position = skip(position)
        _, end = decoder.raw_decode(source, position)
        group = daily_hash("source-native-atom-v1", dict(
            declaration=declaration.group_id, path=path, start=position, end=end))
        node_type = value.get("type") if isinstance(value, dict) else None
        if not isinstance(node_type, str):
            node_type = None
        relation = node_type in {"ALL", "ANY"}
        if relation and (set(value) != {"type", "conditions"}
                         or not isinstance(value["conditions"], list)
                         or not value["conditions"]):
            raise ValueError("SOURCE_COVERAGE_UNSUPPORTED")
        predicate = node_type in _PREDICATES
        if relation or predicate or not isinstance(value, (dict, list)) or not value:
            meaning = (dict(type=node_type, child_paths=[
                f"{path}.conditions[{index}]" for index in range(len(value["conditions"]))
            ]) if relation else value)
            yield SemanticAtom(path, meaning, position, end,
                "RELATION" if relation else "PREDICATE", group, parents)
            if not relation:
                return
        child_parents = (*parents, group) if relation else parents
        cursor = skip(position + 1)
        if isinstance(value, dict):
            for key, child in value.items():
                actual_key, cursor = decoder.raw_decode(source, cursor)
                if actual_key != key or source[skip(cursor)] != ":":
                    raise ValueError("native JSON source structure changed")
                cursor = skip(skip(cursor) + 1)
                if not relation or key == "conditions":
                    yield from walk(child, path + "." + key, cursor, child_parents, depth + 1)
                _, cursor = decoder.raw_decode(source, cursor)
                cursor = skip(cursor)
                if source[cursor] == ",":
                    cursor = skip(cursor + 1)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from walk(child, f"{path}[{index}]", cursor, child_parents, depth + 1)
                _, cursor = decoder.raw_decode(source, cursor)
                cursor = skip(cursor)
                if source[cursor] == ",":
                    cursor = skip(cursor + 1)

    result = []
    for atom in walk(declaration.value, declaration.path, start):
        result.append(atom)
        if len(result) > 4096:
            raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")
    return tuple(result)
