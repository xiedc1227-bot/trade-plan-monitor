"""Bind validated application settings to the bounded AI HTTP adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx
from pydantic import SecretStr

from trade_plan_monitor.ai.models import (
    AIProviderConfig,
    AIProviderProfile,
    SecretReference,
)
from trade_plan_monitor.ai.openai_compatible import OpenAICompatibleProvider
from trade_plan_monitor.config import AIConfiguration


class _SecretMaterializer(Protocol):
    def _materialize(self, reference: SecretReference) -> SecretStr: ...


@dataclass(frozen=True, slots=True)
class ConfiguredAIProviderBinding:
    """One non-secret provider configuration and its selected request dialect."""

    profile: AIProviderProfile
    config: AIProviderConfig
    provider: OpenAICompatibleProvider


def compose_configured_ai_provider(
    *,
    settings: AIConfiguration,
    client: httpx.AsyncClient,
    secret_store: _SecretMaterializer,
) -> ConfiguredAIProviderBinding | None:
    """Return no provider until a secret reference is explicitly configured."""

    bindings = compose_configured_ai_providers(
        settings=settings,
        client=client,
        secret_store=secret_store,
    )
    return bindings[0] if bindings else None


def compose_configured_ai_providers(
    *,
    settings: AIConfiguration,
    client: httpx.AsyncClient,
    secret_store: _SecretMaterializer,
) -> tuple[ConfiguredAIProviderBinding, ...]:
    """Bind every configured model to the shared transport and credential store."""

    configs = settings.to_provider_configs()
    if not configs:
        return ()
    provider = OpenAICompatibleProvider(
        client=client,
        secret_store=secret_store,
        profile=settings.profile,
    )
    return tuple(
        ConfiguredAIProviderBinding(
            profile=settings.profile,
            config=config,
            provider=provider,
        )
        for config in configs
    )


__all__ = [
    "ConfiguredAIProviderBinding",
    "compose_configured_ai_provider",
    "compose_configured_ai_providers",
]
