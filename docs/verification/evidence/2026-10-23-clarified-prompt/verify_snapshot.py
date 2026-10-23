"""Read-only local preservation snapshots; never invoke application mutations."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path('D:/Workspace/Projects/ai-quant-pilot/trade-plan-monitor')
OUT = Path(__file__).parent
VERSION = 'daa0387c-26b2-4e5f-8ea1-b4ea142ecedb'

def digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode()).hexdigest()

def rows(connection, query, args=()):
    result = [dict(row) for row in connection.execute(query, args)]
    result.sort(key=lambda row: json.dumps(row, sort_keys=True, ensure_ascii=False))
    return {'count': len(result), 'sha256': digest(result)}

with sqlite3.connect((ROOT / 'data/monitor.sqlite3').as_uri() + '?mode=ro', uri=True) as db:
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    db.execute('BEGIN')
    tables = ['active_plan', 'plan_activation_state', 'position_lot',
              'position_inventory_state', 'position_opening_balance',
              'position_inventory_confirmation', 'risk_state', 'manual_event_risk']
    protected = {name: rows(db, 'SELECT * FROM ' + name) for name in tables}
    protected['daily_records'] = rows(db, 'SELECT * FROM daily_plan_record WHERE symbol=?',
                                      ('605296.SH',))
    protected['draft_bytes'] = rows(db, 'SELECT * FROM plan_version WHERE id=?', (VERSION,))
    protected['review_bytes'] = rows(db, 'SELECT * FROM plan_review_provenance WHERE plan_version_id=?', (VERSION,))
    protected['storage_constraint'] = rows(db, "SELECT sql FROM sqlite_master WHERE name='daily_plan_record'")
    record = db.execute('SELECT * FROM plan_version WHERE id=?', (VERSION,)).fetchone()
    provenance = db.execute('SELECT * FROM plan_review_provenance WHERE plan_version_id=?', (VERSION,)).fetchone()
    plan = json.loads(record['payload_json'])
    draft = {k: record[k] for k in ['id', 'plan_id', 'version', 'status', 'plan_hash']}
    draft.update({k: provenance[k] for k in ['confirmed_at', 'review_id', 'review_revision']})
    draft.update(technical_alerts=len(plan['alert_rules']), ordinary_rules=len(plan['ordinary_rules']),
                 risk_branches=len(plan['risk_branches']))
    assert draft['status'] == 'DRAFT' and draft['review_id'] is None
    assert draft['confirmed_at'] is None and draft['review_revision'] == 0
    assert (draft['technical_alerts'], draft['ordinary_rules'], draft['risk_branches']) == (1, 0, 0)
    assert protected['active_plan']['count'] == protected['plan_activation_state']['count'] == 0
    db.rollback()

snapshot = {'draft': draft, 'protected': protected,
            'config_sha256': hashlib.sha256((ROOT / 'config/app.yaml').read_bytes()).hexdigest()}
mode = sys.argv[1]
if mode == 'after':
    assert snapshot == json.loads((OUT / 'protected-before.json').read_text(encoding='utf-8'))
(OUT / ('protected-' + mode + '.json')).write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'snapshot': mode, 'draft': draft,
                  'all_protected_records_match': mode == 'after'}, ensure_ascii=False))
