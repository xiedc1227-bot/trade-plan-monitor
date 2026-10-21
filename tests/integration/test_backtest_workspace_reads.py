"""A summary read verifies recorded evidence without rebuilding audit records."""

import pytest

pytest_plugins = ["tests.integration.test_monitor_loop_result_api"]


def test_diagnostic_read_does_not_rebuild_publication_rows(scheduled_published, monkeypatch):
    from trade_plan_monitor.backtest import loop_publication

    _, _, store, reference, report = scheduled_published

    def unexpected_republication(*args, **kwargs):
        raise AssertionError("reading must validate existing rows without rebuilding them")

    monkeypatch.setattr(loop_publication, "audit_record", unexpected_republication)
    stored, actual, diagnostics = store.get_loop_result(reference.run_id)
    assert actual == report
    assert stored.reference == reference
    assert diagnostics.availability == "AVAILABLE"


def test_recorded_event_decoder_rejects_envelope_changes(scheduled_published):
    from trade_plan_monitor.backtest.loop_publication import decode_audit_record
    from trade_plan_monitor.backtest.results import BacktestDetailKind

    _, _, store, reference, _ = scheduled_published
    rows = store.list_details(reference.run_id, kind=BacktestDetailKind.DECISION)
    record = rows[0]
    event = decode_audit_record(record)
    assert event.run_id == reference.run_id
    with pytest.raises(ValueError, match="identity mismatch"):
        decode_audit_record(record.model_copy(update={"detail_id": "different"}))
