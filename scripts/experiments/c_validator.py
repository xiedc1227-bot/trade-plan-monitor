"""Private copy of the prior proof namespace; no process-global monkeypatch.

Reuse its complete validation policy, replacing only normalization and encoding.
This experiment is not installed in a production repository or SQL scanner.
"""

import runpy
from contextvars import ContextVar
from pathlib import Path
from types import SimpleNamespace

from scripts.experiments import validator_scan
from scripts.experiments.bounded_c_producer import Producer, normalize
from scripts.experiments.global_evidence_budget import Budget

from trade_plan_monitor.market_index import canonical

_private = runpy.run_path(str(Path(validator_scan.__file__)))
_namespace = _private["latest"].__globals__
_namespace["canonical"] = SimpleNamespace(**{**vars(canonical), "canonical_value": normalize})
_producer = ContextVar("experimental_c_producer")
_namespace["pieces"] = lambda value: _producer.get().pieces(value)


def latest(rows, codes, observe=lambda *args: None, *, budget=None, **options):
    producer = Producer(budget if budget is not None else Budget(), **options)
    token = _producer.set(producer)
    try:
        return _private["latest"](rows, codes, observe)
    finally:
        _producer.reset(token)
