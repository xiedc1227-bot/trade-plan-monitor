"""Source validation cannot enlarge or reorder the runtime's actual risk frame."""

from types import SimpleNamespace

import pytest
from tests.integration.test_source_action_cutover import legacy as legacy

from trade_plan_monitor.runtime.daily_service import _risk_sources
from trade_plan_monitor.state.source_action_authority import require_source_action_authority


@pytest.mark.parametrize("protocol", ["LIVE", "REPLAY_OBSERVATION"])
@pytest.mark.parametrize("frame_kind", ["single", "full"])
def test_verified_global_risks_only_validate_ids_in_the_original_single_pass_frame(
    legacy, protocol, frame_kind
):
    case = legacy(parallel_risks=True)
    with case.work() as work:
        stored = work.daily.list(symbol=case.draft.symbol, kind="RISK")
        assert [row["payload"]["rule_id"] for row in stored] == ["plan-second", "plan-first"]
        by_rule = {row["payload"]["rule_id"]: row for row in stored}
        first, second = (by_rule[rule] for rule in ("plan-first", "plan-second"))
        real = require_source_action_authority(work, case.id, cause_id=first["id"])
        assert {row["id"] for row in real.risk_rows} == {first["id"], second["id"]}
        frame = (first,) if frame_kind == "single" else (first, second)
        consumed = []

        def one_pass_frame():
            for row in frame:
                consumed.append(row["id"])
                yield row

        def reader(actual_work, version_id, *, cause_id):
            # This is the existing private protocol boundary, not a substitute
            # for the separately verified frozen-session capability adapter.
            assert actual_work is work and version_id == case.id and cause_id in by_id
            return SimpleNamespace(basis="REPLAY_OBSERVATION", plan_version_id=case.id,
                activation_revision=1, risk_rows=stored)

        by_id = {row["id"]: row for row in stored}
        verified, generations, blockers = _risk_sources(work, case.id, one_pass_frame(),
            reader=reader if protocol == "REPLAY_OBSERVATION" else None,
            activation_revision=1)
        assert not blockers and generations
        assert consumed == [row["id"] for row in frame]
        assert verified == frame, (
            "Only source-verified original frame rows may contribute, in original order; "
            f"frame={[row['payload']['rule_id'] for row in frame]!r}, "
            f"returned={[row['payload']['rule_id'] for row in verified]!r}"
        )
