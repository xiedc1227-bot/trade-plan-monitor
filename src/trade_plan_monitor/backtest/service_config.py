"""Finite observation budgets for owned threads, without backtest resource I/O."""

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class BacktestServiceConfig:
    """Timeouts report incomplete work; they never promise thread termination."""

    request_wait_seconds: float = 1.0
    initialization_watchdog_seconds: float = 5.0
    shutdown_wait_seconds: float = 5.0
    max_resume_jobs: int = 1
    recovery_delays_seconds: tuple[int, ...] = (1, 5, 15)

    def __post_init__(self) -> None:
        for name in (
            "request_wait_seconds", "initialization_watchdog_seconds", "shutdown_wait_seconds",
        ):
            value = getattr(self, name)
            if type(value) not in (int, float) or not isfinite(value) or not 0 < value <= 5:
                raise ValueError(f"{name} must be finite and between 0 and 5 seconds")
        if type(self.max_resume_jobs) is not int or self.max_resume_jobs != 1:
            raise ValueError("max_resume_jobs must be 1")
        if self.recovery_delays_seconds != (1, 5, 15):
            raise ValueError("recovery delays must preserve the bounded incident policy")
