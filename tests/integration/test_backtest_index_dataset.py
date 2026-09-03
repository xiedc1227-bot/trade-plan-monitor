from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from tests.integration.test_backtest_market_store import (
    TRADE_DATE,
    _seed_complete,
)
from tests.integration.test_backtest_market_store import (
    _scope as stock_scope,
)

from trade_plan_monitor.backtest.dataset import (
    DatasetManifest,
    DatasetScope,
)
from trade_plan_monitor.backtest.index_data import IndexArtifactMembership
from trade_plan_monitor.backtest.market_store import BacktestMarketStore
from trade_plan_monitor.backtest.models import ExecutionConfig
from trade_plan_monitor.backtest.run_input import BacktestRunInput
from trade_plan_monitor.domain.plan_codec import load_plan_yaml
from trade_plan_monitor.domain.plan_models import TradePlan
from trade_plan_monitor.domain.plan_validation import migrate_trade_plan_to_schema_v2
from trade_plan_monitor.market_data.historical_provider import HistoricalMinuteProfile
from trade_plan_monitor.market_index.models import (
    MarketIndexBar,
    MarketIndexInterval,
    MarketIndexSourceKind,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _plan(*, with_index: bool) -> TradePlan:
    document = Path("config/plans/003043.SZ.sample.yaml").read_text(encoding="utf-8")
    plan = migrate_trade_plan_to_schema_v2(
        load_plan_yaml(document),
        new_version=2,
    )
    if not with_index:
        return plan
    payload = plan.model_dump(mode="python", round_trip=True)
    payload["entry"] = {
        "condition": {
            "type": "INDEX_CLOSE_GTE_MA",
            "index_role": "BOARD_REFERENCE",
            "period": 2,
        }
    }
    return TradePlan.model_validate(payload)


def _scope() -> DatasetScope:
    return DatasetScope(
        symbols=("003043.SZ",),
        start=date(2026, 9, 1),
        end=date(2026, 9, 2),
        warmup_start=date(2026, 8, 1),
        historical_profile=HistoricalMinuteProfile.TUSHARE_STK_MINS_241_END_V1,
    )


def _index_bar(*, close: str, revision: int = 1) -> MarketIndexBar:
    points = Decimal(close)
    return MarketIndexBar(
        index_code="399001.SZ",
        interval=MarketIndexInterval.OFFICIAL_DAILY,
        bar_at=datetime(2026, 8, 31, 15, 0, tzinfo=SHANGHAI),
        open_points=points,
        high_points=points,
        low_points=points,
        close_points=points,
        volume=Decimal("0"),
        amount=Decimal("0"),
        observed_at=datetime(2026, 8, 31, 15, 0, tzinfo=SHANGHAI),
        source_kind=MarketIndexSourceKind.OFFICIAL,
        provider_revision=revision,
    )


def _config() -> ExecutionConfig:
    return ExecutionConfig(
        commission_rate=Decimal("0.0003"),
        minimum_commission_fen=500,
        stamp_duty_rate=Decimal("0.0005"),
        transfer_fee_rate=Decimal("0.00001"),
        buy_slippage_bps=Decimal("1"),
        sell_slippage_bps=Decimal("1"),
    )


def test_v2_dataset_derives_binding_and_changes_on_index_correction() -> None:
    first = DatasetManifest.build_v2(
        scope=_scope(),
        stock_items=(),
        index_items=(IndexArtifactMembership.from_bar(_index_bar(close="100")),),
    )
    corrected = DatasetManifest.build_v2(
        scope=_scope(),
        stock_items=(),
        index_items=(IndexArtifactMembership.from_bar(_index_bar(close="101", revision=2)),),
    )

    assert first.schema_version == "backtest-dataset-v2"
    assert first.reference_market_bindings[0].symbol == "003043.SZ"
    assert first.reference_market_bindings[0].index_code.value == "399001.SZ"
    assert first.reference_market_bindings[0].display_name == "深证成指"
    assert first.dataset_hash != corrected.dataset_hash
    assert first.market_index_data_hash != corrected.market_index_data_hash


def test_index_plan_uses_run_v3_and_binds_all_approved_hashes() -> None:
    manifest = DatasetManifest.build_v2(
        scope=_scope(),
        stock_items=(),
        index_items=(IndexArtifactMembership.from_bar(_index_bar(close="100")),),
    )

    run_input = BacktestRunInput.create(
        plan=_plan(with_index=True),
        manifest=manifest,
        initial_cash_fen=1_000_000,
        initial_lots=(),
        execution_config=_config(),
        manual_event_risk=False,
    )

    assert run_input.run_formula_version == "backtest-run-v3"
    assert run_input.reference_market_binding is not None
    assert run_input.market_index_data_hash == manifest.market_index_data_hash
    assert run_input.formula_definition_hash == manifest.formula_definition_hash
    assert run_input.index_requirement_hash is not None


def test_schema_v2_plan_without_index_leaf_retains_original_run_formula() -> None:
    legacy_manifest = DatasetManifest(
        dataset_hash="a" * 64,
        scope=_scope(),
        items=(),
    )

    run_input = BacktestRunInput.create(
        plan=_plan(with_index=False),
        manifest=legacy_manifest,
        initial_cash_fen=1_000_000,
        initial_lots=(),
        execution_config=_config(),
        manual_event_risk=False,
    )

    assert run_input.run_formula_version == "backtest-run-v1"
    assert run_input.reference_market_binding is None
    assert run_input.market_index_data_hash is None
    dumped = run_input.model_dump(mode="python", round_trip=True)
    assert "reference_market_binding" not in dumped
    assert "market_index_data_hash" not in dumped


def test_index_correction_changes_v3_run_identity() -> None:
    plan = _plan(with_index=True)
    manifests = tuple(
        DatasetManifest.build_v2(
            scope=_scope(),
            stock_items=(),
            index_items=(IndexArtifactMembership.from_bar(_index_bar(close=value)),),
        )
        for value in ("100", "101")
    )
    run_ids = tuple(
        BacktestRunInput.create(
            plan=plan,
            manifest=manifest,
            initial_cash_fen=1_000_000,
            initial_lots=(),
            execution_config=_config(),
            manual_event_risk=False,
        ).run_id
        for manifest in manifests
    )

    assert run_ids[0] != run_ids[1]


def test_index_store_appends_corrections_and_keeps_one_current_head(tmp_path: Path) -> None:
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    first_bar = _index_bar(close="100")
    corrected_bar = _index_bar(close="101", revision=2)

    first_hash = store.record_index_bars((first_bar,))[0]
    duplicate_hash = store.record_index_bars((first_bar,))[0]
    corrected_hash = store.record_index_bars((corrected_bar,))[0]

    natural_key = IndexArtifactMembership.from_bar(first_bar).natural_key
    assert first_hash == duplicate_hash
    assert corrected_hash != first_hash
    assert store.index_head_revision(natural_key) == 2
    assert store.current_index_bars(
        index_codes=(first_bar.index_code,),
        start_on=date(2026, 8, 31),
        end_on=date(2026, 8, 31),
    ) == (corrected_bar,)
    assert store.index_bar_revisions(natural_key) == (first_bar, corrected_bar)


def test_v2_freeze_and_reader_bind_exact_persisted_index_membership(tmp_path: Path) -> None:
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    _seed_complete(store)
    at = datetime(2026, 8, 24, 15, 0, tzinfo=SHANGHAI)
    bars = tuple(
        MarketIndexBar(
            index_code="000001.SH",
            interval=interval,
            bar_at=at,
            open_points=Decimal("3500"),
            high_points=Decimal("3500"),
            low_points=Decimal("3500"),
            close_points=Decimal("3500"),
            volume=Decimal("0"),
            amount=Decimal("0"),
            observed_at=at,
            source_kind=(
                MarketIndexSourceKind.OFFICIAL
                if interval is MarketIndexInterval.OFFICIAL_DAILY
                else MarketIndexSourceKind.PROVISIONAL
            ),
            provider_revision=1,
        )
        for interval in (
            MarketIndexInterval.FIVE_MINUTE,
            MarketIndexInterval.OFFICIAL_DAILY,
        )
    )
    store.record_index_bars(bars)

    frozen = store.freeze_dataset_v2(stock_scope())

    assert frozen.ready is True
    assert frozen.dataset_hash is not None
    manifest = store.dataset_manifest(frozen.dataset_hash)
    assert manifest.schema_version == "backtest-dataset-v2"
    assert tuple(item.index_code.value for item in manifest.index_items) == (
        "000001.SH",
        "000001.SH",
    )
    with store.open_frozen_dataset(frozen.dataset_hash) as reader:
        assert reader.manifest == manifest
        assert reader.market_index_bars(bars[0].index_code) == bars
        assert reader.dataset_revision >= 1
    assert manifest.scope.start == TRADE_DATE
