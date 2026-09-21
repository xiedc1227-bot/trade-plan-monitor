"""Durable interpretation imported from evidence, separate from operational health.

This module performs only local file operations. Importing a contract never grants
present permission or READY health, and is not wired into production composition.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from datetime import datetime, timedelta
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from trade_plan_monitor.live_profiles import (
    CERTIFICATION_MAX_AGE,
    IndexLiveCertification,
    StockLiveCertification,
    read_index_certification_history,
    read_stock_certification_history,
)
from trade_plan_monitor.market_data.models import ProviderCapabilities
from trade_plan_monitor.market_index.tushare import LIVE_TUSHARE_INDEX_CODES

_SHA256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
_MAX_RECORD_BYTES = 65_536
_STOCK_ADAPTER = "tushare-stock-1min-v1"
_INDEX_ADAPTER = "tushare-board-index-5min-v1"
# Explicitly reviewed mappings; a new installed SDK never inherits compatibility.
_COMPATIBLE_SDKS = {_STOCK_ADAPTER: frozenset({"1.4.29"}), _INDEX_ADAPTER: frozenset({"1.4.29"})}
_STOCK_SCOPE = tuple(sorted(ProviderCapabilities.model_fields))
_STOCK_INTERFACES = ("daily", "rt_min", "rt_min_daily", "stk_limit", "trade_cal")
_INDEX_INTERFACES = ("idx_mins", "index_daily", "rt_idx_min_daily")


def _hash(payload: dict) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _endpoint(value: str) -> str:
    normalized = value.rstrip("/")
    parts = urlsplit(normalized)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or any(character.isspace() for character in normalized)
    ):
        raise ValueError("semantic endpoint is invalid")
    return normalized


def _installed_sdk_version() -> str | None:
    try:
        return version("tushare")
    except PackageNotFoundError:
        return None


class _Value(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid", frozen=True, strict=True
    )


class EvidenceProvenance(_Value):
    """Original audit identity; this checksum is not a security signature."""

    kind: Literal["live-certification-v1"] = "live-certification-v1"
    schema_version: Literal[1] = 1
    evidence_hash: _SHA256
    observed_at: AwareDatetime
    valid_until: AwareDatetime
    sdk_version: Literal["1.4.29"] = "1.4.29"

    @model_validator(mode="after")
    def validate_original_window(self) -> Self:
        if self.observed_at.utcoffset() != timedelta(hours=8):
            raise ValueError("provenance must use Asia/Shanghai")
        if self.valid_until != self.observed_at + CERTIFICATION_MAX_AGE:
            raise ValueError("provenance evidence window is invalid")
        return self


class ProviderSemanticContract(_Value):
    """Interpretation-only contract; no current capability observations are stored."""

    schema_version: Literal[1] = 1
    surface: Literal["STOCK", "BOARD_INDEX"]
    endpoint_url: str
    profile_id: Literal["tushare-stock-live-v1", "tushare-board-index-live-v1"]
    capability_scope: tuple[str, ...]
    interface_scope: tuple[str, ...]
    interval: Literal["1min", "5min"]
    source_time_label: Literal["START", "END"]
    adapter_compatibility_id: Literal["tushare-stock-1min-v1", "tushare-board-index-5min-v1"]
    verified_at: AwareDatetime
    provenance: EvidenceProvenance
    semantic_revision: _SHA256
    record_hash: _SHA256

    @model_validator(mode="after")
    def validate_semantics(self) -> Self:
        if self.endpoint_url != _endpoint(self.endpoint_url):
            raise ValueError("semantic endpoint must be normalized")
        if self.verified_at != self.provenance.observed_at:
            raise ValueError("verification must retain the original observation")
        if not self.capability_scope or tuple(sorted(set(self.capability_scope))) != (
            self.capability_scope
        ):
            raise ValueError("capability scope must be nonempty, unique and sorted")
        if self.surface == "STOCK":
            expected = ("tushare-stock-live-v1", "1min", _STOCK_ADAPTER, _STOCK_INTERFACES)
            if self.capability_scope != _STOCK_SCOPE:
                raise ValueError("stock certification scope must be complete")
        else:
            expected = ("tushare-board-index-live-v1", "5min", _INDEX_ADAPTER, _INDEX_INTERFACES)
            if set(self.capability_scope) - {code.value for code in LIVE_TUSHARE_INDEX_CODES}:
                raise ValueError("unknown or deferred index scope")
        if (
            self.profile_id,
            self.interval,
            self.adapter_compatibility_id,
            self.interface_scope,
        ) != expected:
            raise ValueError("unsupported semantic adapter mapping")
        return self

    def calculated_revision(self) -> str:
        return _hash(
            self.model_dump(
                mode="json",
                by_alias=True,
                exclude={
                    "verified_at",
                    "provenance",
                    "semantic_revision",
                    "record_hash",
                },
            )
        )

    def calculated_hash(self) -> str:
        return _hash(self.model_dump(mode="json", by_alias=True, exclude={"record_hash"}))


def load_semantic_contract(
    path: Path,
    *,
    now: datetime,
    endpoint_url: str,
    installed_sdk_version: Callable[[], str | None] = _installed_sdk_version,
) -> ProviderSemanticContract | None:
    """Validate a durable contract against the actual installed adapter, without expiry."""
    _validate_inputs(path, now)
    try:
        if not path.is_file() or path.stat().st_size > _MAX_RECORD_BYTES:
            return None
        document = path.read_bytes()
        if len(document) > _MAX_RECORD_BYTES:
            return None
        contract = ProviderSemanticContract.model_validate_json(document)
        if (
            contract.endpoint_url != _endpoint(endpoint_url)
            or contract.verified_at > now
            or contract.semantic_revision != contract.calculated_revision()
            or contract.record_hash != contract.calculated_hash()
            or installed_sdk_version() not in _COMPATIBLE_SDKS[contract.adapter_compatibility_id]
        ):
            return None
        return contract
    except OSError, UnicodeError, ValueError:
        return None


def import_stock_semantic_contract(
    source: Path,
    sidecar: Path,
    *,
    now: datetime,
    endpoint_url: str,
    installed_sdk_version: Callable[[], str | None] = _installed_sdk_version,
) -> ProviderSemanticContract | None:
    """Import complete verified stock interpretation; do not import READY health."""
    _validate_paths(source, sidecar, now)
    profile = read_stock_certification_history(source, now=now, endpoint_url=endpoint_url)
    if profile is None or not profile.ready:
        return None
    return _import(profile, sidecar, now, installed_sdk_version)


def import_index_semantic_contract(
    source: Path,
    sidecar: Path,
    *,
    now: datetime,
    endpoint_url: str,
    installed_sdk_version: Callable[[], str | None] = _installed_sdk_version,
) -> ProviderSemanticContract | None:
    """Import only evidenced indexes, independently of stock and deferred indexes."""
    _validate_paths(source, sidecar, now)
    profile = read_index_certification_history(source, now=now, endpoint_url=endpoint_url)
    if profile is None or not profile.ready_indexes:
        return None
    return _import(profile, sidecar, now, installed_sdk_version)


def _validate_inputs(path: Path, now: datetime) -> None:
    if not isinstance(path, Path):
        raise TypeError("path must be a Path")
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise TypeError("now must be timezone-aware")


def _validate_paths(source: Path, sidecar: Path, now: datetime) -> None:
    _validate_inputs(source, now)
    _validate_inputs(sidecar, now)
    if source.resolve() == sidecar.resolve():
        raise ValueError("source and sidecar must be distinct")


def _import(
    profile: StockLiveCertification | IndexLiveCertification,
    sidecar: Path,
    now: datetime,
    installed_sdk_version: Callable[[], str | None],
) -> ProviderSemanticContract | None:
    stock = isinstance(profile, StockLiveCertification)
    adapter = _STOCK_ADAPTER if stock else _INDEX_ADAPTER
    installed = installed_sdk_version()
    if installed not in _COMPATIBLE_SDKS[adapter]:
        return None
    try:
        contract = ProviderSemanticContract(
            surface=profile.surface,
            endpoint_url=_endpoint(profile.endpoint_url),
            profile_id=profile.profile_id,
            capability_scope=_STOCK_SCOPE
            if stock
            else tuple(sorted(code.value for code in profile.ready_indexes)),
            interface_scope=_STOCK_INTERFACES if stock else _INDEX_INTERFACES,
            interval="1min" if stock else "5min",
            source_time_label=profile.source_time_label.value,
            adapter_compatibility_id=adapter,
            verified_at=profile.observed_at,
            provenance=EvidenceProvenance(
                evidence_hash=profile.evidence_hash,
                observed_at=profile.observed_at,
                valid_until=profile.valid_until,
                sdk_version=profile.sdk_version,
            ),
            semantic_revision="0" * 64,
            record_hash="0" * 64,
        )
    except ValueError:
        return None
    contract = contract.model_copy(update={"semantic_revision": contract.calculated_revision()})
    contract = contract.model_copy(update={"record_hash": contract.calculated_hash()})

    def existing_contract() -> ProviderSemanticContract | None:
        existing = load_semantic_contract(
            sidecar,
            now=now,
            endpoint_url=contract.endpoint_url,
            installed_sdk_version=lambda: installed,
        )
        if existing is None or existing.semantic_revision != contract.semantic_revision:
            return None
        return existing

    if sidecar.exists():
        return existing_contract()
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{sidecar.name}.", suffix=".tmp", dir=sidecar.parent
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(contract.model_dump_json(by_alias=True, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            # Publish a complete file without replacing another importer's record.
            # Filesystems without atomic hard links fail closed; no overwrite fallback.
            os.link(temporary, sidecar)
        except FileExistsError:
            return existing_contract()
    finally:
        temporary.unlink(missing_ok=True)
    return contract
