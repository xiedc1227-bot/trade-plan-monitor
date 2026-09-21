"""Historical evidence establishes interpretation, not present provider health."""

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from trade_plan_monitor.live_profiles import (
    create_index_certification,
    create_stock_certification,
    write_live_certification,
)
from trade_plan_monitor.market_data.models import ProviderCapabilities, ProviderCapabilityStatus
from trade_plan_monitor.market_data.sessions import SourceTimeLabel
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.tushare import (
    TushareMarketIndexCapabilityStatus as IndexStatus,
)
from trade_plan_monitor.market_index.tushare import (
    TushareMarketIndexSourceTimeLabel as IndexLabel,
)
from trade_plan_monitor.runtime.provider_contract import (
    import_index_semantic_contract,
    import_stock_semantic_contract,
    load_semantic_contract,
)

OBSERVED = datetime(2026, 9, 7, 10, 15, tzinfo=ZoneInfo("Asia/Shanghai"))
NOW = OBSERVED + timedelta(days=30)
ENDPOINT = "https://provider.example"


def _stock(path, *, observed=OBSERVED, label=SourceTimeLabel.END):
    profile = create_stock_certification(
        observed_at=observed,
        endpoint_url=ENDPOINT,
        source_time_label=label,
        capabilities=ProviderCapabilities(
            **{field: ProviderCapabilityStatus.READY for field in ProviderCapabilities.model_fields}
        ),
    )
    write_live_certification(path, profile)
    return profile


def _import_stock(source, sidecar, **kwargs):
    return import_stock_semantic_contract(
        source,
        sidecar,
        now=NOW,
        endpoint_url=ENDPOINT,
        installed_sdk_version=lambda: "1.4.29",
        **kwargs,
    )


def test_old_stock_import_is_atomic_idempotent_and_preserves_original(tmp_path):
    source, sidecar = tmp_path / "old.json", tmp_path / "semantic.json"
    original = _stock(source)
    original_bytes = source.read_bytes()
    contract = _import_stock(source, sidecar)
    assert contract is not None
    assert contract.provenance.evidence_hash == original.evidence_hash
    assert contract.verified_at == OBSERVED
    assert contract.interval == "1min"
    assert contract.source_time_label == SourceTimeLabel.END
    assert contract.capability_scope == tuple(sorted(ProviderCapabilities.model_fields))
    assert "READY" not in sidecar.read_text()
    stamp = sidecar.stat().st_mtime_ns
    assert _import_stock(source, sidecar) == contract
    assert sidecar.stat().st_mtime_ns == stamp
    assert source.read_bytes() == original_bytes
    assert list(tmp_path.glob("*.tmp")) == []
    assert (
        load_semantic_contract(
            sidecar,
            now=NOW + timedelta(days=400),
            endpoint_url=ENDPOINT + "/",
            installed_sdk_version=lambda: "1.4.29",
        )
        == contract
    )


def test_observation_refresh_preserves_semantic_revision(tmp_path):
    source = tmp_path / "old.json"
    _stock(source)
    first = _import_stock(source, tmp_path / "first.json")
    _stock(source, observed=OBSERVED + timedelta(days=1))
    second = _import_stock(source, tmp_path / "second.json")
    assert first is not None and second is not None
    assert first.semantic_revision == second.semantic_revision
    assert first.record_hash != second.record_hash
    _stock(source, label=SourceTimeLabel.START)
    changed = _import_stock(source, tmp_path / "third.json")
    assert changed is not None and changed.semantic_revision != first.semantic_revision


@pytest.mark.parametrize("version", ["1.4.28", "1.4.30", "", None])
def test_import_checks_actual_installed_sdk(tmp_path, version):
    source, sidecar = tmp_path / "old.json", tmp_path / "semantic.json"
    _stock(source)
    assert (
        import_stock_semantic_contract(
            source,
            sidecar,
            now=NOW,
            endpoint_url=ENDPOINT,
            installed_sdk_version=lambda: version,
        )
        is None
    )
    assert not sidecar.exists()


@pytest.mark.parametrize("mutation", ["hash", "future", "endpoint", "label", "profile", "schema"])
def test_bad_source_blocks_only_import_without_sidecar(tmp_path, mutation):
    source, sidecar = tmp_path / "old.json", tmp_path / "semantic.json"
    _stock(
        source,
        observed=NOW + timedelta(seconds=1) if mutation == "future" else OBSERVED,
        label=SourceTimeLabel.UNVERIFIED if mutation == "label" else SourceTimeLabel.END,
    )
    payload = json.loads(source.read_text())
    if mutation == "hash":
        payload["evidenceHash"] = "0" * 64
    elif mutation == "endpoint":
        payload["endpointUrl"] = "https://elsewhere.example"
    elif mutation == "profile":
        payload["profileId"] = "unknown"
    elif mutation == "schema":
        payload["schemaVersion"] = 2
    source.write_text(json.dumps(payload))
    assert _import_stock(source, sidecar) is None
    assert not sidecar.exists()


def test_partial_indexes_preserve_verified_hidden_turnover_without_promoting_others(tmp_path):
    source, sidecar = tmp_path / "index.json", tmp_path / "semantic.json"
    supported = {MarketIndexCode.SHENZHEN_A_SHARE, MarketIndexCode.SSE_COMPOSITE}
    write_live_certification(
        source,
        create_index_certification(
            observed_at=OBSERVED,
            endpoint_url=ENDPOINT,
            source_time_label=IndexLabel.END,
            capabilities={
                code: IndexStatus.READY if code in supported else IndexStatus.DEFERRED
                for code in MarketIndexCode
            },
        ),
    )
    result = import_index_semantic_contract(
        source,
        sidecar,
        now=NOW,
        endpoint_url=ENDPOINT,
        installed_sdk_version=lambda: "1.4.29",
    )
    assert result is not None
    assert set(result.capability_scope) == {code.value for code in supported}
    assert result.interval == "5min"
    assert result.source_time_label == IndexLabel.END
    assert _import_stock(source, tmp_path / "wrong.json") is None


def test_existing_bad_or_different_sidecar_is_not_silently_replaced(tmp_path):
    source, sidecar = tmp_path / "old.json", tmp_path / "semantic.json"
    _stock(source)
    _import_stock(source, sidecar)
    original = sidecar.read_bytes()
    _stock(source, label=SourceTimeLabel.START)
    assert _import_stock(source, sidecar) is None
    assert sidecar.read_bytes() == original
    sidecar.write_text("{}")
    assert _import_stock(source, sidecar) is None
    assert sidecar.read_text() == "{}"


def test_cannot_overwrite_source_and_interrupted_write_has_no_partial_sidecar(
    tmp_path, monkeypatch
):
    source, sidecar = tmp_path / "old.json", tmp_path / "semantic.json"
    _stock(source)
    original = source.read_bytes()
    with pytest.raises(ValueError, match="distinct"):
        _import_stock(source, source)

    def fail_publish(*args):
        raise OSError("simulated interruption")

    monkeypatch.setattr("trade_plan_monitor.runtime.provider_contract.os.link", fail_publish)
    with pytest.raises(OSError, match="simulated"):
        _import_stock(source, sidecar)
    assert not sidecar.exists()
    assert source.read_bytes() == original
    assert sorted(p.name for p in tmp_path.iterdir()) == ["old.json"]


def test_sidecar_corruption_and_installed_sdk_change_fail_closed(tmp_path):
    source, sidecar = tmp_path / "old.json", tmp_path / "semantic.json"
    _stock(source)
    _import_stock(source, sidecar)
    assert (
        load_semantic_contract(
            sidecar, now=NOW, endpoint_url=ENDPOINT, installed_sdk_version=lambda: "1.4.30"
        )
        is None
    )
    payload = json.loads(sidecar.read_text())
    payload["provenance"]["evidenceHash"] = "0" * 64
    sidecar.write_text(json.dumps(payload))
    assert (
        load_semantic_contract(
            sidecar, now=NOW, endpoint_url=ENDPOINT, installed_sdk_version=lambda: "1.4.29"
        )
        is None
    )


def test_default_version_check_queries_installed_distribution(tmp_path, monkeypatch):
    source, sidecar = tmp_path / "old.json", tmp_path / "semantic.json"
    _stock(source)
    packages = []

    def installed_version(package):
        packages.append(package)
        return "1.4.30"

    monkeypatch.setattr("trade_plan_monitor.runtime.provider_contract.version", installed_version)
    assert (
        import_stock_semantic_contract(
            source,
            sidecar,
            now=NOW,
            endpoint_url=ENDPOINT,
        )
        is None
    )
    assert packages == ["tushare"]


def test_incomplete_stock_cannot_promote_unverified_capabilities(tmp_path):
    source, sidecar = tmp_path / "old.json", tmp_path / "semantic.json"
    write_live_certification(
        source,
        create_stock_certification(
            observed_at=OBSERVED,
            endpoint_url=ENDPOINT,
            source_time_label=SourceTimeLabel.END,
            capabilities=ProviderCapabilities(realtime_minutes=ProviderCapabilityStatus.READY),
        ),
    )
    assert _import_stock(source, sidecar) is None
    assert not sidecar.exists()


def test_legacy_index_does_not_invent_missing_399107_scope(tmp_path):
    source, sidecar = tmp_path / "index.json", tmp_path / "semantic.json"
    write_live_certification(
        source,
        create_index_certification(
            observed_at=OBSERVED,
            endpoint_url=ENDPOINT,
            source_time_label=IndexLabel.END,
            capabilities={
                code: IndexStatus.DEFERRED if code is MarketIndexCode.BSE_50 else IndexStatus.READY
                for code in MarketIndexCode
                if code is not MarketIndexCode.SHENZHEN_A_SHARE
            },
        ),
    )
    result = import_index_semantic_contract(
        source,
        sidecar,
        now=NOW,
        endpoint_url=ENDPOINT,
        installed_sdk_version=lambda: "1.4.29",
    )
    assert result is not None
    assert "399107.SZ" not in result.capability_scope
    assert "899050.BJ" not in result.capability_scope


@pytest.mark.parametrize(
    "field,value",
    [
        ("adapterCompatibilityId", "unknown"),
        ("sourceTimeLabel", "UNVERIFIED"),
        ("capabilityScope", ["899050.BJ"]),
        ("schemaVersion", 2),
        ("interval", "5min"),
        ("endpointUrl", "https://elsewhere.example"),
        ("provenance", {}),
    ],
)
def test_invalid_contract_fields_never_load(tmp_path, field, value):
    source, sidecar = tmp_path / "old.json", tmp_path / "semantic.json"
    _stock(source)
    _import_stock(source, sidecar)
    payload = json.loads(sidecar.read_text())
    payload[field] = value
    sidecar.write_text(json.dumps(payload))
    assert (
        load_semantic_contract(
            sidecar, now=NOW, endpoint_url=ENDPOINT, installed_sdk_version=lambda: "1.4.29"
        )
        is None
    )


def test_valid_sidecar_cannot_mask_damaged_or_replaced_source_during_import(tmp_path):
    source, sidecar = tmp_path / "old.json", tmp_path / "semantic.json"
    _stock(source)
    original = _import_stock(source, sidecar)
    sidecar_bytes = sidecar.read_bytes()
    source.write_text("{}")
    assert _import_stock(source, sidecar) is None
    _stock(source, label=SourceTimeLabel.START)
    assert _import_stock(source, sidecar) is None
    assert sidecar.read_bytes() == sidecar_bytes
    # A durable semantic record is self-contained; the audit source is not health.
    assert (
        load_semantic_contract(
            sidecar, now=NOW, endpoint_url=ENDPOINT, installed_sdk_version=lambda: "1.4.29"
        )
        == original
    )


def test_rehashed_invalid_scope_is_rejected_and_provenance_grants_no_health(tmp_path):
    from hashlib import sha256

    source, sidecar = tmp_path / "old.json", tmp_path / "semantic.json"
    _stock(source)
    contract = _import_stock(source, sidecar)
    assert contract is not None
    payload = json.loads(sidecar.read_text())
    payload["capabilityScope"] = ["899050.BJ"]
    semantic = {
        key: value
        for key, value in payload.items()
        if key not in {"recordHash", "semanticRevision", "verifiedAt", "provenance"}
    }
    payload["semanticRevision"] = sha256(
        json.dumps(semantic, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    payload["recordHash"] = sha256(
        json.dumps(
            {key: value for key, value in payload.items() if key != "recordHash"},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    sidecar.write_text(json.dumps(payload))
    assert (
        load_semantic_contract(
            sidecar, now=NOW, endpoint_url=ENDPOINT, installed_sdk_version=lambda: "1.4.29"
        )
        is None
    )
    assert not hasattr(contract, "capabilities")
    assert not hasattr(contract, "ready")
    assert all(
        status is ProviderCapabilityStatus.UNVERIFIED
        for status in ProviderCapabilities().model_dump().values()
    )


def test_missing_sdk_distribution_blocks_import(tmp_path, monkeypatch):
    from importlib.metadata import PackageNotFoundError

    source, sidecar = tmp_path / "old.json", tmp_path / "semantic.json"
    _stock(source)

    def missing_version(package):
        raise PackageNotFoundError(package)

    monkeypatch.setattr("trade_plan_monitor.runtime.provider_contract.version", missing_version)
    assert import_stock_semantic_contract(source, sidecar, now=NOW, endpoint_url=ENDPOINT) is None
    assert not sidecar.exists()


@pytest.mark.parametrize("winner", ["matching", "different", "corrupt"])
def test_concurrent_first_import_never_overwrites_an_existing_winner(tmp_path, monkeypatch, winner):
    import os

    source, sidecar = tmp_path / "old.json", tmp_path / "semantic.json"
    _stock(source, label=SourceTimeLabel.END if winner == "matching" else SourceTimeLabel.START)
    other_path = tmp_path / "other.json"
    other = _import_stock(source, other_path)
    assert other is not None
    winner_bytes = other_path.read_bytes() if winner != "corrupt" else b"{}"
    _stock(source)
    original_link = os.link
    original_replace = os.replace

    def concurrent_publish(temporary, destination):
        destination.write_bytes(winner_bytes)
        return original_link(temporary, destination)

    monkeypatch.setattr("trade_plan_monitor.runtime.provider_contract.os.link", concurrent_publish)

    def concurrent_replace(temporary, destination):
        destination.write_bytes(winner_bytes)
        return original_replace(temporary, destination)

    monkeypatch.setattr(
        "trade_plan_monitor.runtime.provider_contract.os.replace", concurrent_replace
    )
    result = _import_stock(source, sidecar)
    assert sidecar.read_bytes() == winner_bytes
    assert result == (other if winner == "matching" else None)
    assert not tuple(tmp_path.glob(".*.tmp"))
