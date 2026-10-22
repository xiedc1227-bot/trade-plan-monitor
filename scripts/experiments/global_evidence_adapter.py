"""Temporary experiment-only projection adapter; caller owns the shared ledger."""

from contextlib import contextmanager

from scripts.experiments.global_evidence_scan import Scan

from trade_plan_monitor.state.projections import ProjectionRepository


@contextmanager
def install(flights, scans):
    original = ProjectionRepository.list_latest_market_index_snapshots

    class Adapter:
        def __init__(self, repository):
            self.repository = repository

        def run(self, scope, unused_scan, verify, *, cancelled=None, deadline=None):
            reader = Scan(self.repository._session.connection(), flights.budget,
                          scope[1], scope[2], cancelled=cancelled, deadline=deadline)
            try:
                return flights.run(scope, reader, verify, scope[2])
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
