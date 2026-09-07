"""Explicit CLI operations for configured AI connectivity and plan extraction."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import httpx

from trade_plan_monitor.ai.composition import compose_configured_ai_provider
from trade_plan_monitor.ai.configured_secrets import create_configured_secret_store
from trade_plan_monitor.ai.extraction import extract_plan
from trade_plan_monitor.ai.prompts import MAX_SOURCE_TEXT_CHARS
from trade_plan_monitor.config import load_application_config

_MAX_SOURCE_TEXT_BYTES = MAX_SOURCE_TEXT_CHARS * 4


class ConfiguredAICommandService:
    """Run only the AI operation explicitly selected by the local user."""

    def __init__(self, *, config_path: Path) -> None:
        self._config_path = config_path

    async def test_connection(self) -> object:
        settings = load_application_config(self._config_path).ai
        async with _client(settings.timeout_seconds) as client:
            binding = compose_configured_ai_provider(
                settings=settings,
                client=client,
                secret_store=create_configured_secret_store(settings=settings),
            )
            if binding is None:
                raise RuntimeError("AI provider is not configured")
            return await binding.provider.test_connection(binding.config)

    async def extract(self, source: Path) -> object:
        source_text = _read_source_text(source)
        settings = load_application_config(self._config_path).ai
        async with _client(settings.timeout_seconds) as client:
            binding = compose_configured_ai_provider(
                settings=settings,
                client=client,
                secret_store=create_configured_secret_store(settings=settings),
            )
            if binding is None:
                raise RuntimeError("AI provider is not configured")
            return await extract_plan(
                request_id=uuid4(),
                source_text=source_text,
                config=binding.config,
                provider=binding.provider,
            )


def _client(timeout_seconds: int) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        follow_redirects=False,
        timeout=httpx.Timeout(timeout_seconds),
        trust_env=False,
    )


def _read_source_text(path: Path) -> str:
    if not path.is_file():
        raise ValueError("AI source path must identify a file")
    if path.stat().st_size > _MAX_SOURCE_TEXT_BYTES:
        raise ValueError("AI source file is too large")
    source_text = path.read_text(encoding="utf-8", errors="strict")
    if len(source_text) > MAX_SOURCE_TEXT_CHARS:
        raise ValueError("AI source text is too large")
    return source_text


__all__ = ["ConfiguredAICommandService"]
