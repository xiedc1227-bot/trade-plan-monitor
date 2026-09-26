"""Offline SMP-RED contracts; proof rows never become business market history."""

from dataclasses import FrozenInstanceError
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from trade_plan_monitor.market_data.sessions import SourceTimeLabel
from trade_plan_monitor.market_data.tushare import (
    TushareErrorCode,
    TushareMarketDataProvider,
    TushareProviderError,
)
from trade_plan_monitor.runtime.request_control import RequestNotStartedError

SH = ZoneInfo("Asia/Shanghai")
DAY = date(2026, 9, 25)
SYMBOL = "000001.SZ"
FIELDS = ("ts_code", "time", "open", "close", "high", "low", "vol", "amount")
METHODS = {
    "rt_min": "probe_realtime_minutes_permission",
    "rt_min_daily": "probe_current_day_minutes_permission",
}


def at(time="10:05:05", day=DAY):
    return datetime.fromisoformat(f"{day}T{time}").replace(tzinfo=SH)


def row(time="10:04:00", day=DAY, **changes):
    values = (SYMBOL, f"{day} {time}", "1", "1", "2", "0.50", 0, 0)
    return dict(zip(FIELDS, values, strict=True)) | changes


def frame(rows):
    return pd.DataFrame(rows, columns=FIELDS, dtype=object)


def run_probe(payload, *, operation="rt_min_daily", start=None, received=None,
              label=SourceTimeLabel.END, grace=timedelta(seconds=12), hook=None):
    start = at() if start is None else start
    received = start + timedelta(seconds=3) if received is None else received
    calls = []

    def endpoint(**kwargs):
        calls.append(kwargs)
        return payload

    def no_calendar(_day):
        pytest.fail("worker must not read calendar/database")

    provider = TushareMarketDataProvider(
        SimpleNamespace(**{operation: endpoint}), now=lambda: received,
        is_open_on=no_calendar, source_time_label=label, grace=grace,
    )
    method = getattr(provider, METHODS[operation])
    result = method(SYMBOL, DAY, physical_start=hook or (lambda: start))
    assert len(calls) == 1
    assert calls[0]["ts_code"] == SYMBOL and calls[0]["freq"] == "1MIN"
    return result


def invalid(payload, **kwargs):
    with pytest.raises(TushareProviderError) as caught:
        run_probe(payload, **kwargs)
    assert caught.value.code is TushareErrorCode.INVALID_RESPONSE
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    return caught.value


@pytest.mark.parametrize("operation", METHODS)
@pytest.mark.parametrize("extras,counts", [
    ([], (1, 0, 0)), ([row("09:30:00")], (1, 1, 0)),
    ([row("10:05:00"), row("10:06:00")], (1, 0, 2)),
    ([row("09:30:00"), row("10:05:00"), row("10:06:00")], (1, 1, 2)),
])
def test_complete_mixed_response_returns_immutable_evidence(operation, extras, counts):
    evidence = run_probe(frame(list(reversed([row(), *extras]))), operation=operation)
    assert (evidence.completed_count, evidence.opening_count, evidence.incomplete_count) == counts
    assert (evidence.operation, evidence.symbol, evidence.request_date) == (operation, SYMBOL, DAY)
    assert evidence.source_dates == (DAY,)
    assert evidence.started_at == at() and evidence.received_at == at("10:05:08")
    assert evidence.source_label is SourceTimeLabel.END
    assert not hasattr(evidence, "__dict__")
    with pytest.raises(FrozenInstanceError):
        evidence.completed_count = 99


@pytest.mark.parametrize("rows", [[], [row("09:30:00")], [row("10:05:00")],
                                 [row("09:30:00"), row("10:06:00")]])
def test_structural_no_proof_has_private_typed_distinction(rows):
    error = invalid(frame(rows))
    assert type(error) is not TushareProviderError
    assert "NO_POSITIVE_PROOF" in str(error)
    assert "NO_POSITIVE_PROOF" not in str(invalid(pd.DataFrame()))


@pytest.mark.parametrize("time,expected", [("10:05:00", (1, 0)), ("10:06:00", (0, 1))])
def test_completed_cutoff_uses_frozen_start_not_return(time, expected):
    evidence = run_probe(frame([row("10:04:00"), row(time)]),
                         start=at("10:05:12"), received=at("10:05:27"))
    assert (evidence.completed_count - 1, evidence.incomplete_count) == expected


def test_one_microsecond_before_grace_remains_incomplete_even_if_return_is_later():
    evidence = run_probe(frame([row(), row("10:05:00")]),
                         start=at("10:05:12") - timedelta(microseconds=1),
                         received=at("10:05:20"))
    assert (evidence.completed_count, evidence.incomplete_count) == (1, 1)


def test_end_future_label_is_allowed_when_interval_starts_exactly_at_return():
    evidence = run_probe(frame([row(), row("10:06:00"), row("10:07:00")]),
                         start=at("10:05:55"), received=at("10:06:00"))
    assert evidence.incomplete_count == 2
    invalid(frame([row(), row("10:07:00")]), start=at("10:05:55"),
            received=at("10:06:00") - timedelta(microseconds=1))
    invalid(frame([row(), row("10:05:00"), row("10:06:00"), row("10:07:00")]))


@pytest.mark.parametrize("label,time,valid", [
    (SourceTimeLabel.START, "09:30:00", True),
    (SourceTimeLabel.START, "11:30:00", False),
    (SourceTimeLabel.START, "15:00:00", False),
    (SourceTimeLabel.END, "11:30:00", True),
    (SourceTimeLabel.END, "15:00:00", True),
    (SourceTimeLabel.END, "13:00:00", False),
    (SourceTimeLabel.END, "11:31:00", False),
    (SourceTimeLabel.END, "15:01:00", False),
])
def test_session_mapping_boundaries(label, time, valid):
    payload = frame([row(time)])
    if valid:
        assert run_probe(payload, label=label, start=at("15:00:12")).completed_count == 1
    else:
        invalid(payload, label=label, start=at("15:00:12"))


@pytest.mark.parametrize("day", [DAY, DAY + timedelta(days=1)])
def test_prior_completed_row_cannot_hide_future_opening(day):
    invalid(frame([row(day=DAY - timedelta(days=1)), row("09:30:00", day)]),
            operation="rt_min", start=at("09:20:00"))


def test_opening_at_return_boundary_and_all_source_dates_retained():
    prior = DAY - timedelta(days=1)
    evidence = run_probe(frame([row("09:30:00"), row(day=prior), row("09:30:00", prior)]),
                         operation="rt_min", start=at("09:29:50"), received=at("09:30:00"))
    assert evidence.source_dates == (prior, DAY)
    assert (evidence.completed_count, evidence.opening_count) == (1, 2)


@pytest.mark.parametrize("delta", [-1, 15.000001, 3600 * 24])
def test_invalid_evidence_interval_is_rejected(delta):
    invalid(frame([row()]), received=at() + timedelta(seconds=delta))


@pytest.mark.parametrize("grace,label", [(11, SourceTimeLabel.END), (13, SourceTimeLabel.END),
                                         (12, SourceTimeLabel.UNVERIFIED)])
def test_invalid_configuration_is_rejected_before_start(grace, label):
    def forbidden():
        pytest.fail("must reject before physical_start")
    with pytest.raises(ValueError):
        run_probe(frame([row()]), grace=timedelta(seconds=grace), label=label, hook=forbidden)


def test_request_not_started_callback_keeps_original_exception():
    sentinel = RequestNotStartedError("safe local cancellation")
    def reject():
        raise sentinel
    with pytest.raises(RequestNotStartedError) as caught:
        run_probe(frame([row()]), hook=reject)
    assert caught.value is sentinel


@pytest.mark.parametrize("operation", METHODS)
@pytest.mark.parametrize("freq", [None, "1MIN", "5MIN", True])
def test_explicit_frequency_compatibility(operation, freq):
    payload = frame([row()])
    if freq is not None:
        payload["freq"] = freq
    if freq in (None, "1MIN"):
        assert run_probe(payload, operation=operation).completed_count == 1
    else:
        invalid(payload, operation=operation)


def test_identity_alias_is_supported_only_for_current_day():
    payload = frame([row()]).rename(columns={"ts_code": "code"})
    assert run_probe(payload).completed_count == 1
    invalid(payload, operation="rt_min")
    payload["ts_code"] = SYMBOL
    invalid(payload)


@pytest.mark.parametrize("mutation", ["wide", "unknown", "duplicate", "nonstring", "missing"])
def test_schema_is_checked_before_records_conversion(monkeypatch, mutation):
    payload = frame([row()])
    if mutation == "wide":
        payload = pd.DataFrame([[0] * 100], dtype=object)
    elif mutation == "missing":
        payload = payload.drop(columns="vol")
    else:
        payload.columns = [*FIELDS[:-1], {"unknown": "surprise", "duplicate": "vol",
                                        "nonstring": 1}[mutation]]
    monkeypatch.setattr(pd.DataFrame, "itertuples", lambda *_a, **_k: pytest.fail("early schema"))
    invalid(payload)


@pytest.mark.parametrize("time", ["2026-9-25 10:04:00", "2026-09-25 10:04:01",
                                  "2026-09-25 10:04:00.000", " 2026-09-25 10:04:00",
                                  at(), pd.Timestamp(at()) + pd.Timedelta(1, "ns"), None])
def test_noncanonical_time_rejected(time):
    invalid(frame([row(), row("10:05:00") | {"time": time}]))


class ConversionTrap:
    def __str__(self):
        pytest.fail("arbitrary conversion must not execute")


@pytest.mark.parametrize("kind", ["A", "B", "C"])
@pytest.mark.parametrize("field,value", [
    ("open", True), ("vol", ConversionTrap()), ("amount", ConversionTrap()),
    ("amount", "NaN"), ("open", "Infinity"), ("amount", "-1"), ("vol", "0.1"),
    ("open", "0.001"), ("open", "0"), ("high", "0.5"), ("low", "2"),
    ("amount", "1" * 641), ("amount", Decimal("1" * 641)),
    ("amount", Decimal("1e640")), ("amount", Decimal("1e-639")),
    ("amount", Decimal("0e999999999")), ("amount", Decimal("0e-999999999")),
    ("vol", 10 ** 640), ("amount", float("nan")),
])
def test_all_categories_have_bounded_scalar_validation(kind, field, value):
    time = {"A": "10:03:00", "B": "09:30:00", "C": "10:06:00"}[kind]
    invalid(frame([row(), row(time, **{field: value})]))


@pytest.mark.parametrize("value", ["1" * 640, Decimal("1" * 640), 10 ** 639,
                                  Decimal("1e-638"), Decimal("0e-638")])
def test_amount_accepts_exact_640_boundary_without_decimal_context_dependence(value):
    with localcontext() as context:
        context.prec = 2
        assert run_probe(frame([row(amount=value)])).completed_count == 1


@pytest.mark.parametrize("kind", ["A", "B", "C"])
@pytest.mark.parametrize("conflict", [False, True])
def test_duplicate_rows_never_deduplicate_into_success(kind, conflict):
    item = row({"A": "10:03:00", "B": "09:30:00", "C": "10:06:00"}[kind])
    invalid(frame([row(), item, item | ({"vol": 10} if conflict else {})]))


def day_rows(day):
    return [row("09:30:00", day)] + [
        row((at(begin, day) + timedelta(minutes=i)).strftime("%H:%M:%S"), day)
        for begin in ("09:31:00", "13:01:00") for i in range(120)
    ]


def test_daily_raw_bound_includes_two_incomplete_rows():
    rows = day_rows(DAY)
    evidence = run_probe(frame(rows), start=at("14:59:05"))
    assert (evidence.completed_count, evidence.opening_count, evidence.incomplete_count) == (
        238, 1, 2,
    )
    invalid(frame(rows + [row()]), start=at("15:01:00"))


@pytest.mark.parametrize("count", [242, 1000, 1001])
def test_realtime_bound_can_span_dates(count):
    days = [DAY - timedelta(days=n) for n in (0, 1, 2, 3, 4)]
    rows = [item for day in days for item in day_rows(day)][:count]
    if count <= 1000:
        evidence = run_probe(frame(rows), operation="rt_min", start=at("15:01:00"))
        assert sum((evidence.completed_count, evidence.opening_count,
                    evidence.incomplete_count)) == count
    else:
        invalid(frame(rows), operation="rt_min", start=at("15:01:00"))


def test_realtime_does_not_infer_five_day_age_or_coverage_requirement():
    days = (date(2024, 1, 2), date(2025, 1, 2), *[DAY - timedelta(days=i) for i in range(5)])
    evidence = run_probe(frame([row(day=d) for d in days]), operation="rt_min")
    assert evidence.source_dates == tuple(sorted(days))
    invalid(frame([row(day=DAY - timedelta(days=1))]))


def test_foreign_symbol_is_not_filtered():
    invalid(frame([row(), row("10:03:00", ts_code="600000.SH")]))


def test_receipt_clock_is_frozen_before_parsing_and_read_only_once(monkeypatch):
    current = at("10:05:08")
    reads = []
    payload = frame([row(), row("10:05:00"), row("10:06:00")])
    original_itertuples = pd.DataFrame.itertuples

    def advance_validation(self, *args, **kwargs):
        nonlocal current
        current = at("10:07:00")
        return original_itertuples(self, *args, **kwargs)

    def now():
        reads.append(current)
        return current

    monkeypatch.setattr(pd.DataFrame, "itertuples", advance_validation)
    provider = TushareMarketDataProvider(
        SimpleNamespace(rt_min=lambda **_kwargs: payload), now=now,
        is_open_on=lambda _day: pytest.fail("no calendar"), source_time_label=SourceTimeLabel.END,
    )
    result = provider.probe_realtime_minutes_permission(SYMBOL, DAY, physical_start=lambda: at())
    assert reads == [at("10:05:08")]
    assert result.received_at == at("10:05:08")
    assert (result.completed_count, result.incomplete_count) == (1, 2)


@pytest.mark.parametrize("start", [at().replace(tzinfo=None), at().astimezone(ZoneInfo("UTC")),
                                   at(day=DAY - timedelta(days=1)), None])
def test_bad_start_clock_never_calls_sdk(start):
    provider = TushareMarketDataProvider(
        SimpleNamespace(rt_min=lambda **_kwargs: pytest.fail("bad clock called SDK")),
        now=lambda: at(), is_open_on=lambda _day: pytest.fail("no calendar"),
        source_time_label=SourceTimeLabel.END,
    )
    with pytest.raises(ValueError):
        provider.probe_realtime_minutes_permission(SYMBOL, DAY, physical_start=lambda: start)


@pytest.mark.parametrize("value", [Decimal("0e639"), Decimal("-0e638"), "0" * 640])
def test_zero_resource_boundary_is_valid(value):
    assert run_probe(frame([row(amount=value)])).completed_count == 1


@pytest.mark.parametrize("value", [Decimal("0e640"), Decimal("-0e639"), "0" * 641])
def test_zero_resource_boundary_overflow_is_not_short_circuited(value):
    invalid(frame([row(amount=value)]))


@pytest.mark.parametrize("kind", ["A", "B", "C"])
@pytest.mark.parametrize("base", [int, float])
def test_numeric_subclass_hooks_are_never_executed(kind, base):
    hooks = []

    class IntChild(int):
        def __int__(self):
            hooks.append("int")
            return 1

    class FloatChild(float):
        def __float__(self):
            hooks.append("float")
            return 1.0

    value = IntChild(1) if base is int else FloatChild(1.0)
    time = {"A": "10:03:00", "B": "09:30:00", "C": "10:06:00"}[kind]
    payload = frame([row(), row(time, amount=value)])
    rejected = False
    try:
        run_probe(payload)
    except TushareProviderError as error:
        assert error.code is TushareErrorCode.INVALID_RESPONSE
        rejected = True
    assert hooks == []
    assert rejected


@pytest.mark.parametrize("stage", ["callback", "sdk"])
@pytest.mark.parametrize("replacement", [SourceTimeLabel.END, SourceTimeLabel.UNVERIFIED])
@pytest.mark.parametrize("time,positive", [("10:05:00", False), ("10:04:00", True)])
def test_source_label_is_frozen_before_callback_and_sdk(stage, replacement, time, positive):
    def endpoint(**_kwargs):
        if stage == "sdk":
            provider._source_time_label = replacement
        return frame([row(time)])

    def start():
        if stage == "callback":
            provider._source_time_label = replacement
        return at("10:05:12")

    provider = TushareMarketDataProvider(
        SimpleNamespace(rt_min=endpoint), now=lambda: at("10:05:12"),
        is_open_on=lambda _day: pytest.fail("no calendar"), source_time_label=SourceTimeLabel.START,
    )
    if positive:
        evidence = provider.probe_realtime_minutes_permission(SYMBOL, DAY, physical_start=start)
        assert evidence.source_label is SourceTimeLabel.START
        assert evidence.completed_count == 1
    else:
        with pytest.raises(TushareProviderError, match="NO_POSITIVE_PROOF"):
            provider.probe_realtime_minutes_permission(SYMBOL, DAY, physical_start=start)


def test_builtin_numeric_dataframe_dtypes_remain_accepted():
    payload = pd.DataFrame([row(open=1.0, close=1.0, high=2.0, low=0.5, vol=1, amount=1.5)])
    assert run_probe(payload).completed_count == 1
