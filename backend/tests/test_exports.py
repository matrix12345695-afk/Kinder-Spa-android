import csv
import io
import json

from conftest import Client
from test_api import mk_client, plan_id


def test_csv_exports_and_backup(owner, server):
    cl = mk_client(owner, '=ВЗЛОМ() Экспорт', phone='+998 90 111 22 33')
    _, r = owner.post('/api/subscriptions', {'client_id': cl['id'], 'plan_id': plan_id(owner, 'Бассейн — 8 занятий'),
                                             'price': '400000.50', 'paid_amount': '100000', 'paid_method': 'click'}, expect=200)
    owner.post('/api/visits', {'subscription_id': r['id'], 'service_id': next(
        s['id'] for s in owner.get('/api/services')[1] if s['code'] == 'pool')}, expect=200)

    status, body, headers = owner.call('GET', '/api/export/payments.csv?from=2000-01-01&to=2100-01-01', raw=True)
    assert status == 400   # period longer than a year
    status, body, headers = owner.call('GET', '/api/export/debts.csv', raw=True)
    assert status == 200 and headers['content-type'].startswith('text/csv') and 'attachment' in headers['content-disposition']
    assert body.startswith('﻿'.encode())
    rows = list(csv.reader(io.StringIO(body.decode('utf-8-sig')), delimiter=';'))
    assert rows[0][0] == '№ абонемента'
    mine = next(x for x in rows if x[0] == str(r['id']))
    assert mine[1] == "'=ВЗЛОМ() Экспорт" and mine[2] == '+998 90 111 22 33' and mine[9] == '300000,50' and mine[8] == '100000'

    for name in ('payments', 'visits', 'clients'):
        status, body, _ = owner.call('GET', f'/api/export/{name}.csv', raw=True)
        assert status == 200 and len(body.decode('utf-8-sig').splitlines()) >= 2, name

    _, st = owner.post('/api/staff', {'login': 'exporter', 'full_name': 'Админ'}, expect=200)
    admin = Client(server).login('exporter', st['password'])
    assert admin.call('GET', '/api/export/clients.csv', raw=True)[0] == 200
    assert admin.call('GET', '/api/export/backup.json', raw=True)[0] == 403
    assert Client(server).call('GET', '/api/export/clients.csv', raw=True)[0] == 401

    status, body, _ = owner.call('GET', '/api/export/backup.json', raw=True)
    data = json.loads(body)
    assert status == 200 and data['format'] == 'kinder-spa-backup-v1' and data['schema_version'] >= 5
    assert 'salt' not in data['tables']['users'][0] and 'verifier' not in data['tables']['users'][0]
    assert any(c['id'] == cl['id'] for c in data['tables']['clients'])
    log = owner.get('/api/audit?limit=20')[1]
    assert any(e['action'] == 'export_backup' for e in log) and any(e['action'] == 'export' for e in log)
