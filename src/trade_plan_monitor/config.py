"""Typed, non-secret application configuration."""

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

EnvironmentVariableName = Annotated[
    str,
    StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$"),
]


class _ConfigurationModel(BaseModel):
    """Apply strict boundary validation to every configuration section."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )


class EnvironmentSecretReference(_ConfigurationModel):
    """Reference a secret by environment-variable name without storing its value."""

    environment_variable: EnvironmentVariableName


class WebConfiguration(_ConfigurationModel):
    """Local-only Web listener configuration."""

    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)


class TushareConfiguration(_ConfigurationModel):
    """Tushare configuration containing only a token reference."""

    token_ref: EnvironmentSecretReference = Field(
        default_factory=lambda: EnvironmentSecretReference(environment_variable="TUSHARE_TOKEN")
    )


class AIConfiguration(_ConfigurationModel):
    """Optional AI secret reference; provider settings arrive in a later task."""

    api_key_ref: EnvironmentSecretReference | None = None


class ApplicationConfiguration(_ConfigurationModel):
    """Top-level configuration accepted by the local application."""

    web: WebConfiguration = Field(default_factory=WebConfiguration)
    tushare: TushareConfiguration = Field(default_factory=TushareConfiguration)
    ai: AIConfiguration = Field(default_factory=AIConfiguration)


def load_application_config(path: str | Path) -> ApplicationConfiguration:
    """Load one safe YAML document and validate the complete application schema."""

    with Path(path).open(encoding="utf-8") as stream:
        raw_config = yaml.safe_load(stream)

    return ApplicationConfiguration.model_validate({} if raw_config is None else raw_config)


__all__ = [
    "AIConfiguration",
    "ApplicationConfiguration",
    "EnvironmentSecretReference",
    "TushareConfiguration",
    "WebConfiguration",
    "load_application_config",
]
