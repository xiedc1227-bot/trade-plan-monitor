"""Side-effect-free lifecycle values; readiness never authorizes queue recovery."""

from dataclasses import dataclass
from enum import StrEnum


class BacktestServiceState(StrEnum):
    DISABLED = "DISABLED"
    NOT_INITIALIZED = "NOT_INITIALIZED"
    STARTING = "STARTING"
    READ_READY = "READ_READY"
    READY = "READY"
    RECOVERING = "RECOVERING"
    DEGRADED = "DEGRADED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"


class BacktestCapability(StrEnum):
    METADATA = "METADATA"
    EXECUTION = "EXECUTION"


@dataclass(frozen=True, slots=True)
class BacktestServiceSnapshot:
    """Immutable status only; constructing or reading it acquires no resources."""

    state: BacktestServiceState = BacktestServiceState.NOT_INITIALIZED
    generation: int = 0
    authorized_job_ids: frozenset[str] = frozenset()
    outstanding_work: int = 0
    read_capability_available: bool = False

    def __post_init__(self) -> None:
        if type(self.outstanding_work) is not int or self.outstanding_work < 0:
            raise ValueError("outstanding_work must be a nonnegative integer")
        if type(self.generation) is not int or self.generation < 0:
            raise ValueError("generation must be a nonnegative integer")
        if not isinstance(self.state, BacktestServiceState):
            raise TypeError("state must be a BacktestServiceState")
        if not isinstance(self.authorized_job_ids, frozenset):
            raise TypeError("authorized_job_ids must be immutable")
        if type(self.read_capability_available) is not bool:
            raise TypeError("read_capability_available must be a boolean")

    @property
    def physically_drained(self) -> bool:
        return self.outstanding_work == 0

    def allows(self, capability: BacktestCapability) -> bool:
        if capability is BacktestCapability.METADATA:
            return self.state in (BacktestServiceState.READ_READY, BacktestServiceState.READY) or (
                self.state is BacktestServiceState.DEGRADED and self.read_capability_available
            )
        return (
            capability is BacktestCapability.EXECUTION
            and self.state is BacktestServiceState.READY
        )
