"""Corrupt stored enums, quantities and future evidence fail closed."""

import pytest

from trade_plan_monitor.state.daily_state_models import DailyFactState, DailySignalState


def signal_payload():
    return {
        "signal_id": "signal",
        "rule_id": "low-buy",
        "side": "BUY",
        "bucket": "TACTICAL",
        "lineage": "synthetic-daily",
        "state": "READY",
        "planned_qty": 100,
        "simulated_qty": 0,
        "confirmed_trade_date": "2026-09-18",
        "execution_date": "2026-09-22",
        "evidence_fingerprint": "a" * 64,
        "evidence": [],
        "plan_version_id": "synthetic-version",
        "review_id": "synthetic-review",
        "basis_id": "synthetic-basis",
        "executable_qty": 100,
        "blockers": [],
    }


@pytest.mark.parametrize(
    "change",
    [
        {"state": "GUESS_READY"},
        {"simulated_qty": 101},
        {"simulated_qty": True},
        {"remaining_qty": 100},
        {"executable_qty": 101},
    ],
)
def test_signal_record_rejects_corrupt_consumption_and_enum(change):
    with pytest.raises(ValueError):
        DailySignalState.model_validate({**signal_payload(), **change})


def test_fact_verification_time_cannot_precede_publication_or_availability():
    with pytest.raises(ValueError):
        DailyFactState.model_validate(
            {
                "plan_version_id": "version",
                "content_hash": "a" * 64,
                "kind": "TRADABILITY",
                "trade_date": "2026-09-22",
                "signal_id": None,
                "prior_signal_id": None,
                "evidence": "Synthetic official verification evidence",
                "verified": True,
                "verified_at": "2026-09-22T10:00:00+08:00",
                "available_at": "2026-09-22T09:00:00+08:00",
                "official_evidence": {
                    "issuer": "Synthetic exchange",
                    "document_title": "Synthetic document",
                    "document_url": "https://exchange.example.test/notice",
                    "published_at": "2026-09-22T11:00:00+08:00",
                    "verified_at": "2026-09-22T10:00:00+08:00",
                    "applicable_assertion": "Synthetic official thesis invalidation.",
                },
            }
        )
