"""Lossless private storage for repeated source evidence, with bounded expansion."""

from copy import deepcopy

from trade_plan_monitor.ai.extraction import MAX_EXTRACTION_OUTPUT_BYTES
from trade_plan_monitor.backtest.canonical import canonical_json

ENCODING = "source-clause-pool-v2"


def pack_evidence(value):
    result = deepcopy(value)
    pool, indices = [], {}
    for binding in result["review"]["bindings"]:
        references = []
        for clause in binding["clauses"]:
            key = canonical_json(clause)
            if key not in indices:
                indices[key] = len(pool)
                pool.append(clause)
            references.append(indices[key])
        binding["clauses"] = references
    result.update(storage_encoding=ENCODING, clause_pool=pool)
    string_pool, string_indices = [], {}

    def pack_lists(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if (
                    key in {"paths", "clause_ids"}
                    and isinstance(value, list)
                    and all(isinstance(item, str) for item in value)
                ):
                    identity = tuple(value)
                    if identity not in string_indices:
                        string_indices[identity] = len(string_pool)
                        string_pool.append(value)
                    node[key] = {"$strings": string_indices[identity]}
                else:
                    pack_lists(value)
        elif isinstance(node, list):
            for item in node:
                pack_lists(item)

    pack_lists(result)
    result["string_list_pool"] = string_pool
    return result


def unpack_evidence(value):
    if "storage_encoding" not in value:
        return value
    version = value["storage_encoding"]
    allowed = {"schema_version", "extraction", "review", "storage_encoding", "clause_pool"}
    if version == ENCODING:
        allowed.add("string_list_pool")
    if version not in {ENCODING, "source-clause-pool-v1"} or set(value) != allowed:
        raise ValueError("unknown candidate storage encoding")
    result = deepcopy(value)
    if version == ENCODING:
        string_pool = result.pop("string_list_pool")
        if (
            not isinstance(string_pool, list)
            or len(string_pool) > 4000
            or any(
                not isinstance(items, list)
                or len(items) > 2000
                or any(not isinstance(item, str) for item in items)
                for items in string_pool
            )
        ):
            raise ValueError("invalid candidate string pool")
        expanded_size = len(canonical_json(result).encode("utf-8"))
        sizes = [len(canonical_json(items).encode("utf-8")) for items in string_pool]

        def unpack_lists(node):
            nonlocal expanded_size
            if isinstance(node, dict):
                for key, item in node.items():
                    if key in {"paths", "clause_ids"} and isinstance(item, dict):
                        index = item.get("$strings")
                        if (
                            set(item) != {"$strings"}
                            or type(index) is not int
                            or not 0 <= index < len(string_pool)
                        ):
                            raise ValueError("invalid candidate string reference")
                        expanded_size += sizes[index]
                        if expanded_size > MAX_EXTRACTION_OUTPUT_BYTES:
                            raise ValueError("candidate evidence expansion exceeds byte limit")
                        node[key] = list(string_pool[index])
                    else:
                        unpack_lists(item)
            elif isinstance(node, list):
                for item in node:
                    unpack_lists(item)

        unpack_lists(result)
    pool = result.pop("clause_pool")
    result.pop("storage_encoding")
    if not isinstance(pool, list) or len(pool) > 2000:
        raise ValueError("invalid candidate clause pool")
    review = result.get("review")
    bindings = review.get("bindings") if isinstance(review, dict) else None
    if (
        not isinstance(bindings, list)
        or len(bindings) > 2000
        or any(not isinstance(binding, dict) for binding in bindings)
    ):
        raise ValueError("invalid candidate evidence bindings")
    sizes = [len(canonical_json(c).encode("utf-8")) for c in pool]
    expanded_size = len(canonical_json(result).encode("utf-8"))
    for binding in bindings:
        refs = binding.get("clauses")
        if (
            not isinstance(refs, list)
            or len(refs) > 50
            or any(type(i) is not int or not 0 <= i < len(pool) for i in refs)
        ):
            raise ValueError("invalid candidate clause reference")
        expanded_size += sum(sizes[i] for i in refs)
        if expanded_size > MAX_EXTRACTION_OUTPUT_BYTES:
            raise ValueError("candidate evidence expansion exceeds byte limit")
        binding["clauses"] = [pool[i] for i in refs]
    return result
