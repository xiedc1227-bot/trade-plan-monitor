"""V2 control frames over the unchanged committed monitor-event stream."""

from pydantic import BaseModel
from pydantic_core import to_json

from trade_plan_monitor.web.runtime_status_models import (
    RuntimeHeartbeatFrame,
    RuntimeSnapshotRequiredFrame,
)
from trade_plan_monitor.web.websocket import CommittedMonitorEventStream


class RuntimeStatusEventStream(CommittedMonitorEventStream):
    monitor_contract_version = 2

    def __init__(self, *, read_service, **kwargs):
        super().__init__(fixed_heartbeat_cadence=True, **kwargs)
        self._read_service = read_service

    def _snapshot_required_frame(self, sequence: int) -> dict[str, object]:
        return RuntimeSnapshotRequiredFrame(
            type="snapshot.required",
            monitor_contract_version=2,
            sequence=sequence,
            reason="REPLAY_UNAVAILABLE",
        ).model_dump(mode="json", by_alias=True)

    async def _current_heartbeat_frame(self, sequence: int) -> dict[str, object]:
        health = await self._read_service.get_health()
        if isinstance(health, BaseModel):
            health = health.model_dump(mode="python", by_alias=True)
        envelope = {
            key: health[key]
            for key in (
                "monitorContractVersion",
                "runtimeGeneration",
                "observedAt",
                "runtimeStatus",
            )
        }
        frame = RuntimeHeartbeatFrame.model_validate_json(
            to_json(
                {
                    **envelope,
                    "type": "heartbeat",
                    "sequence": sequence,
                }
            )
        )
        return frame.model_dump(mode="json", by_alias=True)
