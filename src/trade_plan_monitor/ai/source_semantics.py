"""Finite exact declaration equivalence and source-owned relation identities."""

from trade_plan_monitor.ai.source_obligations import MISSING, value_at
from trade_plan_monitor.domain.daily_hash import canonical, daily_hash


def equal_declaration(declaration, values, payload):
    actual = values.get(declaration.path, MISSING)
    if actual is MISSING:
        actual = value_at(payload, declaration.path)
    return actual is not MISSING and canonical(actual) == canonical(declaration.value)


def declared_paths(declaration, values):
    """Only an exact complete container may prove its existing descendant leaves."""
    root = declaration.path
    return tuple(path for path in values if path == root or path.startswith(root + ".")
                 or path.startswith(root + "["))


def relation_groups(declarations, source_hash):
    """ALL/ANY semantics and all descendant predicates share a stable source group.

    Group IDs reference the complete ordered source declarations, never AI paths,
    proposed roles, mutable treatment or runtime observation identities.
    """
    groups = {}
    for declaration in declarations:
        if not isinstance(declaration.value, str) or declaration.value not in {"ALL", "ANY"}:
            continue
        root = declaration.path.removesuffix(".type")
        if ".condition" not in root:
            continue
        members = [row for row in declarations if row.path == root
                   or row.path.startswith(root + ".") or row.path.startswith(root + "[")]
        groups[root] = daily_hash("source-condition-relation-v1", dict(
            source_hash=source_hash, root=root,
            members=[dict(start=row.start, end=row.end, path=row.path, value=row.value)
                     for row in members],
        ))
    return groups


def declaration_relations(declaration, groups):
    root = declaration.path.removesuffix(".type")
    own = groups.get(root)
    parents = tuple(group for path, group in groups.items()
                    if declaration.path.startswith(path + ".")
                    or declaration.path.startswith(path + "["))
    return own, parents
