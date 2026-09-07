"""Materialize the API key stored directly in application configuration."""

from __future__ import annotations

from trade_plan_monitor.ai.secrets import InMemorySecretStore, SecretWrite
from trade_plan_monitor.config import AIConfiguration


def create_configured_secret_store(
    *,
    settings: AIConfiguration,
) -> InMemorySecretStore:
    """Create one process-local store from the direct configuration value."""

    store = InMemorySecretStore()
    provider_config = settings.to_provider_config()
    if provider_config is None or settings.api_key is None:
        return store
    store.replace(
        provider_config.secret_ref,
        SecretWrite(value=settings.api_key),
    )
    return store


__all__ = ["create_configured_secret_store"]
