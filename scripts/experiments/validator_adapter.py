"""Temporary experiment-only projection adapter; caller owns the shared ledger."""

from contextlib import contextmanager

from scripts.experiments.evidence_representation import OrderedScan
from scripts.experiments.validator_scan import LimitedScan, ScanGate, latest

from trade_plan_monitor.state.projections import ProjectionRepository


@contextmanager
def install(flights, scans, variant="ordered"):
    gate = ScanGate(1 if variant.endswith("1") else 2)
    limited = variant.startswith(("slots", "combined"))
    scanner = (lambda *a, **k: LimitedScan(*a, gate=gate, **k)) if limited else OrderedScan
    original = ProjectionRepository.list_latest_market_index_snapshots

    class Adapter:
        def __init__(self, repository):
            self.repository = repository

        def run(self, scope, unused_scan, verify, *, cancelled=None, deadline=None):
            reader = scanner(
                self.repository._session.connection(),
                flights.budget,
                scope[1],
                scope[2],
                cancelled=cancelled,
                deadline=deadline,
            )
            try:
                proof = (
                    (lambda rows: latest(rows, scope[2]))
                    if variant.startswith(("validator", "combined"))
                    else verify
                )
                return flights.run(scope, reader, proof, scope[2])
            finally:
                scans.append(dict(reader.stats))

    def projected(repository, **kwargs):
        previous = repository._index_verifier
        repository._index_verifier = Adapter(repository)
        try:
            # Preserve original argument normalization and scope construction.
            return original(repository, **kwargs)
        finally:
            repository._index_verifier = previous

    ProjectionRepository.list_latest_market_index_snapshots = projected
    try:
        yield
    finally:
        ProjectionRepository.list_latest_market_index_snapshots = original
