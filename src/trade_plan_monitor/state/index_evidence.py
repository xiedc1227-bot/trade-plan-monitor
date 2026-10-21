"""Immutable literal index inputs, independent of sessions, clocks and owners."""

from dataclasses import dataclass
from sys import getsizeof
from types import SimpleNamespace

HEAD_FIELDS = (
    "mapping_version", "index_code", "decision_cutoff", "request_set_hash",
    "provider_content_revision", "snapshot_hash", "updated_at",
)
PAYLOAD_FIELDS = (
    "snapshot_hash", "mapping_version", "index_code", "decision_cutoff",
    "request_set_hash", "provider_content_revision", "revision", "bar_set_hash",
    "formula_definition_hash", "snapshot_json", "observed_at", "schema_version",
)
_JSON = PAYLOAD_FIELDS.index("snapshot_json")


@dataclass(frozen=True, slots=True)
class RawIndexCandidate:
    head: tuple
    payload: tuple | None
    json_is_text: bool

    @classmethod
    def capture(cls, head, payload):
        values = None if payload is None else tuple(getattr(payload, key) for key in PAYLOAD_FIELDS)
        return cls.from_values(tuple(getattr(head, key) for key in HEAD_FIELDS), values)

    @classmethod
    def from_values(cls, head, values):
        """Capture raw scalar SQL columns without constructing session-bound ORM entities."""
        text = values is not None and type(values[_JSON]) is str
        if text:
            values = (*values[:_JSON], values[_JSON].encode("utf-8"), *values[_JSON + 1:])
        return cls(head, values, text)

    def decoded(self):
        head = SimpleNamespace(**dict(zip(HEAD_FIELDS, self.head, strict=True)))
        if self.payload is None:
            return head, None
        values = self.payload
        if self.json_is_text:
            values = (*values[:_JSON], values[_JSON].decode("utf-8"), *values[_JSON + 1:])
        return head, SimpleNamespace(**dict(zip(PAYLOAD_FIELDS, values, strict=True)))

    def exact(self, other):
        if type(other) is not RawIndexCandidate or self.json_is_text != other.json_is_text:
            return False
        for left, right in ((self.head, other.head), (self.payload, other.payload)):
            if left is None or right is None:
                if left is not right:
                    return False
            elif len(left) != len(right) or any(
                type(a) is not type(b) or a != b for a, b in zip(left, right, strict=True)
            ):
                return False
        return True

    def retained_size(self):
        # Conservatively count repeated scalar references and both collection vectors.
        return getsizeof(self) + 32 + sum(
            getsizeof(values) + sum(getsizeof(value) for value in values)
            for values in (self.head, self.payload) if values is not None
        )
