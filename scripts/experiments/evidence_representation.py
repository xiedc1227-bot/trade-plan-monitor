"""P0 typed byte capture and ordered scan; no production imports this module."""
from dataclasses import replace

from scripts.experiments.global_evidence_budget import MIB, BudgetUnavailable
from scripts.experiments.global_evidence_scan import COLUMNS, FROM, ORDER, Scan, shape

from trade_plan_monitor.state.index_evidence import HEAD_FIELDS, RawIndexCandidate

JSON_COLUMN = len(HEAD_FIELDS)+9
BYTE_COLUMNS = list(COLUMNS)
BYTE_COLUMNS[JSON_COLUMN] = (
    "case when typeof(p.snapshot_json)='text' then cast(p.snapshot_json as blob)"
    " else p.snapshot_json end"
)
SELECT = 'select h.rowid,p.rowid,'+','.join(BYTE_COLUMNS)+',typeof(p.snapshot_json)'


class ByteScan(Scan):
    def _byte_shape(self, values):
        bound = shape(values)
        kind, size = values[2+2*JSON_COLUMN:4+2*JSON_COLUMN]
        # Replace only driver Unicode storage (4N) with bytes (N).
        # Keep both generations and full worst-case validator decoding.
        return replace(bound, work=bound.work-6*size) if kind == 'text' else bound

    def shapes(self):
        from scripts.experiments.global_evidence_scan import META
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
                    yield self._byte_shape(values)
                del page, values

    def measure(self):
        raw = maximum = count = raw_max = 0
        for item in self.shapes():
            raw += item.raw
            maximum = max(maximum, item.work)
            raw_max = max(raw_max, item.raw)
            count += 1
        self.preflight = raw, max(MIB, maximum), count, raw_max
        return self.preflight[:3]

    def _read(self, query, parameters, workspace, expected=None):
        self.check()
        if workspace.closed or workspace.failed:
            raise BudgetUnavailable('payload has no workspace')
        if self.before_payload:
            self.before_payload()
        self.stats['payloadQueries'] += 1
        count = 0
        with self.cursor(query, parameters, workspace) as cursor:
            for values in cursor:
                self.check()
                if expected is not None:
                    item = expected[count]
                    if tuple(values[:2]) != (item.locator, item.payload_locator):
                        raise BudgetUnavailable('literal locator sequence changed')
                    raw_bound = item.raw
                else:
                    raw_bound = self.preflight[3]
                head = tuple(values[2:2+len(HEAD_FIELDS)])
                payload = None if values[1] is None else tuple(values[2+len(HEAD_FIELDS):-1])
                row = RawIndexCandidate(head, payload, values[-1] == 'text')
                actual = row.retained_size()
                if actual > raw_bound:
                    workspace.failed = True
                    self.budget.stop()
                    raise BudgetUnavailable('raw bound invalidated')
                self.stats['actualRawPeak'] = max(self.stats['actualRawPeak'], actual)
                self.stats['rows'] += 1
                count += 1
                yield row
                del row, head, payload, values
        if count != (len(expected) if expected is not None else self.preflight[2]):
            raise BudgetUnavailable('payload cardinality changed')

    def _payload(self, group, workspace):
        if sum(s.work for s in group) > workspace.size:
            raise BudgetUnavailable('page exceeds workspace')
        query = SELECT+FROM+self.where+' and h.rowid in ('
        query += ','.join('?' for _ in group)+')'+ORDER+f' limit {len(group)}'
        yield from self._read(query, self.parameters+tuple(s.locator for s in group),
                              workspace, group)


class OrderedScan(ByteScan):
    def rows(self, workspace):
        if workspace.size < self.preflight[1]:
            raise BudgetUnavailable('ordered cursor lacks maximum workspace')
        yield from self._read(SELECT+FROM+self.where+ORDER, self.parameters, workspace)
