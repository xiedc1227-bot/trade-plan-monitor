"""Domain-separated canonical identities for daily contracts."""

import json
from hashlib import sha256


def canonical(value) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")
    )


def daily_hash(domain: str, value) -> str:
    return sha256(domain.encode() + b"\x00" + canonical(value).encode()).hexdigest()
