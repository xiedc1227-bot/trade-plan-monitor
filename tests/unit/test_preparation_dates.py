"""Only unambiguous plan applicability in the supplied text can select a day."""

from datetime import date

import pytest

from trade_plan_monitor.backtest.preparation_dates import infer_effective_trade_date


@pytest.mark.parametrize("text", [
    "生效交易日：2026-09-24\n复盘2026-09-23行情，下一交易日满足条件才买入。",
    "计划适用日期：2026年9月24日",
    "# 2026/9/24 交易计划\n等待确认。",
    "2026年9月23日复盘。9月24日若继续在支撑区运行，先不买。",
    "生效日期：**2026-09-24**",
    "Effective trade date: 2026-09-24",
    "生效交易日为2026年9月24日。",
    "# 2026-09-24 盛新锂能交易计划",
    "# 盛新锂能交易计划（2026-09-24）",
])
def test_extracts_applicability_not_market_analysis_date(text):
    assert infer_effective_trade_date(text) == date(2026, 9, 24)


@pytest.mark.parametrize("text", [
    "9月24日若继续在支撑区运行，先不买。",  # No year in this document.
    "2026-09-23收盘下跌，继续等待。",  # Market observation only.
    "2026年9月23日复盘，明日开始执行。",  # No inferred trading calendar.
    "生效交易日：2026-02-30",  # Invalid calendar date.
    "生效交易日：2026-09-24或2026-09-25",  # Alternatives.
    "生效日期：2026-09-24\n生效日期：2026-09-25",
    "2025年和2026年对比。9月24日执行交易计划。",  # Ambiguous year.
    "如果2026-09-24收盘企稳，下一交易日买入100股。",  # Rule event date.
    "生效日期：待定\n2026-09-24交易计划参考案例。",
    "文件名中的日期和当前时间均不可作为原文证据。",
    "2026-09-23交易计划复盘，未指定新计划生效日。",
    "2026-09-24交易计划示例，不代表本次计划。",
])
def test_ambiguous_missing_invalid_and_event_dates_require_confirmation(text):
    assert infer_effective_trade_date(text) is None
