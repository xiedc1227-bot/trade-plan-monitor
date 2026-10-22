"""Snapshot-local metadata sizing and admitted payload queries for the P0 experiment."""

from contextlib import contextmanager
from dataclasses import dataclass
from sys import getsizeof
from time import monotonic

from scripts.experiments.global_evidence_budget import MIB, BudgetUnavailable

from trade_plan_monitor.state.index_evidence import HEAD_FIELDS, PAYLOAD_FIELDS, RawIndexCandidate

COLUMNS = tuple('h.'+key for key in HEAD_FIELDS) + tuple('p.'+key for key in PAYLOAD_FIELDS)
FROM = (' from market_index_snapshot_head h left join market_index_snapshot p'
        ' on h.snapshot_hash=p.snapshot_hash')
ORDER = ' order by h.mapping_version,h.index_code,h.decision_cutoff,h.request_set_hash'
META = ','.join(('h.rowid', 'p.rowid') + tuple(
    expression for col in COLUMNS for expression in (f'typeof({col})', f'octet_length({col})')
))
META_BYTES = 128*1024


@dataclass(frozen=True)
class Shape:
    locator: int
    payload_locator: int | None
    raw: int
    work: int


def shape(values):
    raw = source = 2048
    text = 0
    for i in range(len(COLUMNS)):
        kind, size = values[2+2*i:4+2*i]
        if kind not in ('null', 'integer', 'real', 'text', 'blob'):
            raise BudgetUnavailable('unsupported storage type')
        if kind in ('text', 'blob'):
            if type(size) is not int or size < 0:
                raise BudgetUnavailable('invalid byte size')
            source += 80 + size*(4 if kind == 'text' else 1)
            is_json = i == len(HEAD_FIELDS)+9 and kind == 'text'
            raw += 80 + size*(1 if is_json or kind == 'blob' else 4)
            if is_json:
                text = 80+4*size
        else:
            source += 80
            raw += 80
    # Both old and new generations can overlap across Python iterator/consumer locals.
    return Shape(values[0], values[1], raw, 2*(source+raw+text))


class Scan:
    def __init__(self, connection, budget, mapping, codes, *, cancelled=None, deadline=None):
        self.connection, self.budget = connection, budget
        self.cancelled = cancelled
        self.deadline = monotonic()+15 if deadline is None else deadline
        self.where = (' where h.mapping_version=? and h.index_code in ('
                      + ','.join('?' for _ in codes)+')')
        self.parameters = (mapping, *(c.value for c in codes))
        self.stats = dict(metadataQueries=0, payloadQueries=0, rows=0, actualRawPeak=0)
        self.before_payload = None
        self.metadata_lease = None

    def check(self):
        if monotonic() >= self.deadline or (self.cancelled and self.cancelled.is_set()):
            raise BudgetUnavailable('scan no longer admitted')

    def acquire(self, size, category):
        return self.budget.acquire(size, category, cancelled=self.cancelled, deadline=self.deadline)

    @contextmanager
    def metadata(self):
        with self.acquire(META_BYTES, 'metadata') as lease:
            self.metadata_lease = lease
            try:
                encoding = self.connection.exec_driver_sql('pragma encoding').scalar_one()
                if encoding != 'UTF-8':
                    raise BudgetUnavailable('unsupported database encoding')
                yield
            finally:
                self.metadata_lease = None

    @contextmanager
    def cursor(self, query, parameters, lease):
        if lease is None or lease.closed or lease.failed:
            raise BudgetUnavailable('cursor has no live lease')
        cursor = self.connection.exec_driver_sql(query, parameters)
        try:
            yield cursor
        finally:
            try:
                cursor.close()
            except BaseException:
                lease.failed = True
                self.budget.stop()
                raise

    def shapes(self):
        self.check()
        self.stats['metadataQueries'] += 1
        with self.cursor('select '+META+FROM+self.where+ORDER,
                         self.parameters, self.metadata_lease) as cursor:
            while True:
                self.check()
                page = cursor.fetchmany(32)
                if not page:
                    break
                for values in page:
                    yield shape(values)
                del page, values

    def measure(self):
        raw, maximum, count = 0, 0, 0
        for row in self.shapes():
            raw += row.raw
            maximum = max(maximum, row.work)
            count += 1
        return raw, max(MIB, maximum), count

    def rows(self, workspace):
        if workspace.closed or workspace.failed:
            raise BudgetUnavailable('scan workspace is not owned')
        group, charged = [], 0
        for candidate in self.shapes():
            if candidate.work > workspace.size:
                raise BudgetUnavailable('row exceeds admitted workspace')
            if group and charged+candidate.work > workspace.size:
                yield from self._payload(group, workspace)
                group.clear()
                charged = 0
            group.append(candidate)
            charged += candidate.work
        if group:
            yield from self._payload(group, workspace)
        group.clear()

    def _payload(self, group, workspace):
        self.check()
        if workspace.closed or workspace.failed or sum(s.work for s in group) > workspace.size:
            raise BudgetUnavailable('payload query lacks its allocation lease')
        if self.before_payload:
            self.before_payload()
        placeholders = ','.join('?' for _ in group)
        query = ('select h.rowid,p.rowid,'+','.join(COLUMNS)+FROM+self.where
                 +f' and h.rowid in ({placeholders})'+ORDER+f' limit {len(group)}')
        parameters = self.parameters+tuple(s.locator for s in group)
        self.stats['payloadQueries'] += 1
        count = 0
        with self.cursor(query, parameters, workspace) as cursor:
            for values in cursor:
                self.check()
                expected = group[count]
                if tuple(values[:2]) != (expected.locator, expected.payload_locator):
                    raise BudgetUnavailable('payload order or join differs from metadata')
                head = tuple(values[2:2+len(HEAD_FIELDS)])
                payload = tuple(values[2+len(HEAD_FIELDS):])
                row = RawIndexCandidate.from_values(head, None if values[1] is None else payload)
                actual = row.retained_size()
                self.stats['actualRawPeak'] = max(self.stats['actualRawPeak'], actual)
                if actual > expected.raw:
                    workspace.failed = True
                    self.budget.stop()
                    raise BudgetUnavailable('preallocation bound invalidated')
                # Raw cursor data and encoded row coexist inside this work lease.
                if getsizeof(values) > 2048:
                    workspace.failed = True
                    self.budget.stop()
                    raise BudgetUnavailable('unexpected driver row wrapper')
                count += 1
                self.stats['rows'] += 1
                yield row
                del row, head, payload, values
        if count != len(group):
            raise BudgetUnavailable('incomplete payload page')
