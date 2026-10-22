"""Process-local negative controls; never mutate repository source."""
import sys

import pytest


def main(mode):
    if mode == 'no-funding':
        from scripts.experiments.evidence_cohort import Flights
        Flights.fund = lambda *_: None
        selection = 'funded_collection_cohort'
    elif mode == 'lost-type':
        from scripts.experiments import evidence_representation
        original = evidence_representation.RawIndexCandidate
        evidence_representation.RawIndexCandidate = (
            lambda head, payload, text: original(head, payload, False)
        )
        selection = 'literal_types'
    else:
        raise ValueError(mode)
    code = pytest.main(['tests/integration/test_evidence_representation.py', '-k', selection,
                       '-q', '--tb=short', '--basetemp=.pytest_cache/ers-mutant-'+mode])
    if code != 1:
        raise RuntimeError(f'mutation survived or runner failed: {code}')
    print('MUTATION_KILLED: '+mode)


if __name__ == '__main__':
    main(sys.argv[1])
