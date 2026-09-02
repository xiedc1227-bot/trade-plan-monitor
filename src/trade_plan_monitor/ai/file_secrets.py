"""Fail-closed loading of one API key from a configured local secret file."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from pydantic import ValidationError

from trade_plan_monitor.ai.secrets import InMemorySecretStore, SecretWrite
from trade_plan_monitor.config import AIConfiguration

MAX_PROJECT_SECRET_FILE_BYTES: Final = 65_536


def create_project_secret_store(
    *,
    config_path: Path,
    settings: AIConfiguration,
) -> InMemorySecretStore:
    """Load only the configured key without consulting process environment variables."""

    store = InMemorySecretStore(environment={})
    provider_config = settings.to_provider_config()
    reference = settings.api_key_ref
    if provider_config is None or reference is None:
        return store
    try:
        secret_value = _read_named_assignment(
            path=_resolve_secret_path(config_path, reference.file),
            key=reference.key,
        )
        store.replace(
            provider_config.secret_ref,
            SecretWrite(value=secret_value),
        )
    except OSError, UnicodeError, ValueError, ValidationError:
        return store
    return store


def _resolve_secret_path(config_path: Path, configured_file: str) -> Path:
    config_directory = config_path.resolve(strict=False).parent
    return (config_directory / configured_file).resolve(strict=True)


def _read_named_assignment(*, path: Path, key: str) -> str:
    if not path.is_file():
        raise ValueError("secret path must identify a file")
    if path.stat().st_size > MAX_PROJECT_SECRET_FILE_BYTES:
        raise ValueError("secret file is too large")
    raw_bytes = path.read_bytes()
    if len(raw_bytes) > MAX_PROJECT_SECRET_FILE_BYTES:
        raise ValueError("secret file is too large")
    text = raw_bytes.decode("utf-8", errors="strict")
    matches: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped.removeprefix("export ").lstrip()
        name, separator, raw_value = stripped.partition("=")
        if separator and name.strip() == key:
            matches.append(_parse_assignment_value(raw_value))
    if len(matches) != 1 or not matches[0].strip():
        raise ValueError("secret key must occur exactly once with a non-empty value")
    return matches[0]


def _parse_assignment_value(raw_value: str) -> str:
    value = raw_value.strip()
    if value.startswith(('"', "'")):
        if len(value) < 2 or value[-1] != value[0]:
            raise ValueError("quoted secret value is incomplete")
        return value[1:-1]
    return value


__all__ = ["MAX_PROJECT_SECRET_FILE_BYTES", "create_project_secret_store"]
