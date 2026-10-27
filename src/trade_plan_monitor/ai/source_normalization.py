"""Capture and reconstruct complete normalization images without trusting hashes."""

import json
import re
from copy import deepcopy

from trade_plan_monitor.ai.source_coverage_models import NormalizationChange, NormalizationTrace
from trade_plan_monitor.ai.source_obligations import MISSING, value_at
from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.domain.daily_scope import scope_hash

_PATH = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")


def _image_hash(value):
    return daily_hash("source-normalization-candidate-v1", value)


def _envelope(value):
    return {"present": False} if value is MISSING else {"present": True, "value": value}


def _changes(before, after, path="", *, reason):
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(before.keys() | after.keys()):
            yield from _changes(before.get(key, MISSING), after.get(key, MISSING),
                path + "." + key if path else key, reason=reason)
    elif canonical(_envelope(before)) != canonical(_envelope(after)):
        if _PATH.fullmatch(path) is None:
            raise ValueError("normalization path is outside the registered candidate grammar")
        yield NormalizationChange(path=path, before_json=canonical(_envelope(before)),
            after_json=canonical(_envelope(after)), reason=reason)


def capture_normalization(before, after, source, *, reason="SOURCE_NORMALIZATION"):
    """Lists are atomic changes; absent keys differ from explicit JSON nulls."""
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise ValueError("normalization images must be JSON objects")
    changes = []
    for change in _changes(before, after, reason=reason):
        changes.append(change)
        if len(changes) > 2000:
            raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")
    return NormalizationTrace.build(source_hash=scope_hash(source),
        before_hash=_image_hash(before), after_hash=_image_hash(after), changes=tuple(changes))


def _decode_envelope(document):
    value = json.loads(document)
    if value == {"present": False}:
        return MISSING
    if (isinstance(value, dict) and set(value) == {"present", "value"}
            and value["present"] is True):
        return value["value"]
    raise ValueError("normalization change requires an exact presence envelope")


def validate_normalization(trace, draft, source):
    """Reconstruct the preimage and rederive every ordered change and image hash."""
    trace = NormalizationTrace.model_validate(trace.model_dump(mode="json"))
    after = draft.model_dump(mode="json")
    if trace.source_hash != scope_hash(source) or trace.after_hash != _image_hash(after):
        raise ValueError("normalization source or after-image mismatch")
    paths = [change.path for change in trace.changes]
    if len(paths) != len(set(paths)) or any(
        left != right and right.startswith(left + ".") for left in paths for right in paths
    ):
        raise ValueError("normalization changes overlap or repeat")
    before = deepcopy(after)
    for change in trace.changes:
        if _PATH.fullmatch(change.path) is None:
            raise ValueError("normalization change path is invalid")
        observed = value_at(after, change.path)
        if canonical(_envelope(observed)) != change.after_json:
            raise ValueError("normalization change differs from the actual after-image")
        parent_path, _, key = change.path.rpartition(".")
        parent = value_at(before, parent_path) if parent_path else before
        if not isinstance(parent, dict):
            raise ValueError("normalization parent is absent")
        previous = _decode_envelope(change.before_json)
        _decode_envelope(change.after_json)
        if previous is MISSING:
            parent.pop(key, None)
        else:
            parent[key] = previous
    if trace.before_hash != _image_hash(before):
        raise ValueError("normalization preimage mismatch")
    expected = capture_normalization(before, after, source)
    def shape(changes):
        return [(row.path, row.before_json, row.after_json) for row in changes]

    if shape(trace.changes) != shape(expected.changes):
        raise ValueError("normalization trace is not the complete canonical difference")
    return before


def validate_policy_preservation(trace, draft, source):
    """Raw automatic fidelity cannot be manufactured by repairing policy meaning.

    The historical draft parser owns registered representation/default expansion.
    Display changes are allowed. A changed executable meaning must remain an
    explicit normalization loss until a supported human correction is reviewed.
    No provider mapping is invented for the original candidate.
    """
    from trade_plan_monitor.ai.daily_review import semantic_values
    from trade_plan_monitor.ai.source_obligations import declarations
    from trade_plan_monitor.ai.source_semantics import equal_declaration
    from trade_plan_monitor.domain.daily_plan_validation import load_daily_draft_json

    before = validate_normalization(trace, draft, source)
    original = load_daily_draft_json(canonical(before))
    values = semantic_values(original)
    if canonical(values) != canonical(semantic_values(draft)):
        raise ValueError("normalization changed executable policy meaning")
    for declaration in declarations(source):
        if (declaration.path in {"plan_id", "version", "name"}
                or declaration.path.startswith("metadata.")):
            continue
        if not equal_declaration(declaration, values, original.executable_payload()):
            raise ValueError("original candidate differs from a complete source declaration")
    return before
