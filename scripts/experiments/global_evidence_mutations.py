"""Test-only process-local negative controls; source files remain intact."""

import sys


def main(mode):
    import pytest
    from scripts.experiments.global_evidence_budget import Lease
    from scripts.experiments.global_evidence_scan import Scan

    target = 'tests/integration/test_global_evidence_admission.py'
    if mode == 'early-release':
        original = Lease.close
        def close(self, cleanup=None):
            if cleanup is not None:
                original(self)
                cleanup()
            else:
                original(self)
        Lease.close = close
        target = 'tests/unit/test_global_evidence_budget.py'
        selection = 'failed_resource_cleanup'
    elif mode == 'missing-sql-lease':
        original = Scan._payload
        def payload(self, group, workspace):
            # Simulate an uncharged scanner while keeping its logical token live.
            self.budget.categories['scan'] = 0
            yield from original(self, group, workspace)
        Scan._payload = payload
        selection = 'real_scan_is_literal'
    elif mode == 'skip-exact':
        from trade_plan_monitor.state.index_evidence import RawIndexCandidate
        RawIndexCandidate.exact = lambda *_: True
        selection = 'changed_snapshot'
    else:
        raise ValueError('unknown mutation')
    result = pytest.main([target, '-k', selection, '-q', '--tb=short',
                          '--basetemp=.pytest_cache/gba-mutant-'+mode])
    if result != 1:
        raise RuntimeError(f'mutation survived or collection failed: {mode}: {result}')
    print('MUTATION_KILLED: '+mode)


if __name__ == '__main__':
    main(sys.argv[1])
