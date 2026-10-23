"""P0 failure lifetime experiment; no production integration or reduced leases."""

import gc
from dataclasses import dataclass

from scripts.experiments.fused_c_validator import latest as _verify

from trade_plan_monitor.state.projections import ProjectionError, ProjectionMissingDependencyError


@dataclass(frozen=True, slots=True)
class Failure:
    missing: bool


def _capture(rows, codes, observe, options):
    # Underlying finally blocks finish before this catches anything. Unknown failures,
    # including storage cleanup errors, must propagate with their original semantics.
    try:
        return _verify(rows, codes, observe, **options)
    except ProjectionError as error:
        if type(error) not in (ProjectionError, ProjectionMissingDependencyError):
            raise
        missing = type(error) is ProjectionMissingDependencyError
    return Failure(missing)


def latest(rows, codes, observe=lambda *args: None, **options):
    outcome = _capture(rows, codes, observe, options)
    if isinstance(outcome, Failure):
        # Inner validation exceptions can form cycles through model-validator frames.
        # This synchronous failure-only cost is measured; no physical lease is refunded here.
        gc.collect()
        if outcome.missing:
            raise ProjectionMissingDependencyError("missing immutable snapshot")
        raise ProjectionError("Stored market-index snapshot is invalid")
    return outcome
