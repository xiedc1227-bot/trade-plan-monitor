"""Strict, sanitized evidence profiles produced by live certification children."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from trade_plan_monitor.market_data.models import (
    ProviderCapabilities,
    ProviderCapabilityStatus,
)
from trade_plan_monitor.market_data.sessions import SourceTimeLabel
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.tushare import (
    LIVE_TUSHARE_INDEX_CODES,
    TushareMarketIndexCapabilityStatus,
    TushareMarketIndexSourceTimeLabel,
)

CERTIFICATION_MAX_AGE = timedelta(days=7)
_MAX_PROFILE_BYTES = 65_536
_SDK_VERSION = "1.4.29"
_STOCK_PROFILE_ID = "tushare-stock-live-v1"
_INDEX_PROFILE_ID = "tushare-board-index-live-v1"
_SHA256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.title() for part in rest)


class _LiveCertification(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        strict=True,
    )

    schema_version: Literal[1] = 1
    observed_at: AwareDatetime
    valid_until: AwareDatetime
    endpoint_url: str
    sdk_version: Literal["1.4.29"] = _SDK_VERSION
    evidence_hash: _SHA256

    @model_validator(mode="after")
    def validate_evidence_window(self) -> Self:
        if self.observed_at.utcoffset() != timedelta(hours=8):
            raise ValueError("certification timestamp must use Asia/Shanghai")
        if self.valid_until != self.observed_at + CERTIFICATION_MAX_AGE:
            raise ValueError("certification freshness window is invalid")
        if (
            not self.endpoint_url.startswith("https://")
            or self.endpoint_url != self.endpoint_url.rstrip("/")
            or "?" in self.endpoint_url
            or "#" in self.endpoint_url
            or "@" in self.endpoint_url
        ):
            raise ValueError("certification endpoint is invalid")
        return self

    def calculated_hash(self) -> str:
        payload = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"evidence_hash"},
        )
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class StockLiveCertification(_LiveCertification):
    surface: Literal["STOCK"] = "STOCK"
    profile_id: Literal["tushare-stock-live-v1"] = _STOCK_PROFILE_ID
    capabilities: ProviderCapabilities
    source_time_label: SourceTimeLabel

    @property
    def ready(self) -> bool:
        statuses = self.capabilities.model_dump(mode="python").values()
        return self.source_time_label is not SourceTimeLabel.UNVERIFIED and all(
            status is ProviderCapabilityStatus.READY for status in statuses
        )


class IndexLiveCertification(_LiveCertification):
    surface: Literal["BOARD_INDEX"] = "BOARD_INDEX"
    profile_id: Literal["tushare-board-index-live-v1"] = _INDEX_PROFILE_ID
    capabilities: Mapping[MarketIndexCode, TushareMarketIndexCapabilityStatus]
    source_time_label: TushareMarketIndexSourceTimeLabel
    five_minute_endpoint: Literal["idx_mins"] = "idx_mins"
    realtime_five_minute_endpoint: Literal["rt_idx_min_daily"] = "rt_idx_min_daily"
    official_daily_endpoint: Literal["index_daily"] = "index_daily"

    @model_validator(mode="after")
    def validate_capability_set(self) -> Self:
        missing = set(MarketIndexCode) - set(self.capabilities)
        if set(self.capabilities) - set(MarketIndexCode) or missing - {
            MarketIndexCode.SHENZHEN_A_SHARE
        }:
            raise ValueError("index certification must classify every known index")
        if any(
            self.capabilities[code] is TushareMarketIndexCapabilityStatus.READY
            for code in set(MarketIndexCode) - set(LIVE_TUSHARE_INDEX_CODES)
        ):
            raise ValueError("BSE 50 live index is deferred")
        return self

    @property
    def ready_indexes(self) -> frozenset[MarketIndexCode]:
        if self.source_time_label is TushareMarketIndexSourceTimeLabel.UNVERIFIED:
            return frozenset()
        return frozenset(
            code
            for code, status in self.capabilities.items()
            if status is TushareMarketIndexCapabilityStatus.READY
        )


def _finish[CertificationT: _LiveCertification](profile: CertificationT) -> CertificationT:
    return type(profile).model_validate(
        {
            **profile.model_dump(mode="python", round_trip=True),
            "evidence_hash": profile.calculated_hash(),
        }
    )


def create_stock_certification(
    *,
    observed_at: datetime,
    endpoint_url: str,
    capabilities: ProviderCapabilities,
    source_time_label: SourceTimeLabel,
) -> StockLiveCertification:
    profile = StockLiveCertification(
        observed_at=observed_at,
        valid_until=observed_at + CERTIFICATION_MAX_AGE,
        endpoint_url=endpoint_url.rstrip("/"),
        capabilities=capabilities,
        source_time_label=source_time_label,
        evidence_hash="0" * 64,
    )
    return _finish(profile)


def create_index_certification(
    *,
    observed_at: datetime,
    endpoint_url: str,
    capabilities: Mapping[MarketIndexCode, TushareMarketIndexCapabilityStatus],
    source_time_label: TushareMarketIndexSourceTimeLabel,
) -> IndexLiveCertification:
    profile = IndexLiveCertification(
        observed_at=observed_at,
        valid_until=observed_at + CERTIFICATION_MAX_AGE,
        endpoint_url=endpoint_url.rstrip("/"),
        capabilities=capabilities,
        source_time_label=source_time_label,
        evidence_hash="0" * 64,
    )
    return _finish(profile)


def write_live_certification(path: Path, profile: _LiveCertification) -> None:
    if not isinstance(path, Path):
        raise TypeError("path must be a Path")
    if not isinstance(profile, _LiveCertification):
        raise TypeError("profile must be a live certification")
    if profile.evidence_hash != profile.calculated_hash():
        raise ValueError("certification hash is invalid")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    document = profile.model_dump_json(by_alias=True, indent=2) + "\n"
    try:
        temporary.write_text(document, encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def load_stock_certification(
    path: Path,
    *,
    now: datetime,
    endpoint_url: str,
) -> StockLiveCertification | None:
    return _load_profile(path, StockLiveCertification, now=now, endpoint_url=endpoint_url)


def load_index_certification(
    path: Path,
    *,
    now: datetime,
    endpoint_url: str,
) -> IndexLiveCertification | None:
    return _load_profile(path, IndexLiveCertification, now=now, endpoint_url=endpoint_url)


def _load_profile[CertificationT: _LiveCertification](
    path: Path,
    profile_type: type[CertificationT],
    *,
    now: datetime,
    endpoint_url: str,
) -> CertificationT | None:
    if not isinstance(path, Path):
        raise TypeError("path must be a Path")
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise TypeError("now must be timezone-aware")
    try:
        if not path.is_file() or path.stat().st_size > _MAX_PROFILE_BYTES:
            return None
        document = path.read_text(encoding="utf-8", errors="strict")
        if len(document.encode("utf-8")) > _MAX_PROFILE_BYTES:
            return None
        profile = profile_type.model_validate_json(document)
    except OSError, UnicodeError, ValueError:
        return None
    if (
        profile.evidence_hash != profile.calculated_hash()
        or profile.endpoint_url != endpoint_url.rstrip("/")
        or now < profile.observed_at
        or now > profile.valid_until
    ):
        return None
    return profile


__all__ = [
    "CERTIFICATION_MAX_AGE",
    "IndexLiveCertification",
    "StockLiveCertification",
    "create_index_certification",
    "create_stock_certification",
    "load_index_certification",
    "load_stock_certification",
    "write_live_certification",
]
