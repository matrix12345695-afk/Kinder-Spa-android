import base64
from datetime import datetime, timedelta, timezone

import pytest

from conftest import Client

TZ = timezone(timedelta(hours=5))


def mk_client(owner, name='Иванова Анна', phone='+998 90 123-45-67', children=('Миша',)):
    _, r = owner.post('/api/clients', {'full_name': name, 'phone': phone,
                                       'children': [{'full_name': c} for c in children]}, expect=200)
    _, cl = owner.get(f"/api/clients/{r['id']}", expect=200)
    return cl


def service_id(owner, code):
    _, rows = owner.get('/api/services', expect=200)
    return next(s['id'] for s in rows if s['code'] == code)


def plan_id(owner, name):
    _, rows = owner.get('/api/plans', expect=200)
    return next(p['id'] for p in rows if p['name'] == name)


def mk_sub(owner, client, plan='Массаж — 10 сеансов', **extra):
    body = {'client_id': client['id'], 'plan_id': plan_id(owner, plan), **extra}
    _, r = owner.post('/api/subscriptions', body, expect=200)
    _, sub = owner.get(f"/api/subscriptions/{r['id']}", expect=200)
    return sub


def parent_client(owner, server, cl):
    _, cred = owner.post(f"/api/clients/{cl['id']}/credentials", expect=200)
    return Client(server).login(cred['login'], cred['password']), cred


# ---------------------------------------------------------------- auth

def test_health_and_admin_page(anon):
    assert anon.get('/health', expect=200)[1]['database'] == 'ok'
    status, body, headers = anon.call('GET', '/admin/', raw=True)
    assert status == 200 and b'Kinder Spa' in body
    assert "frame-ancestors 'none'" in headers['content-security-policy']


def test_login_logout_and_roles(anon, server):
    assert anon.post('/api/login', {'login': 'owner', 'password': 'wrong-password'})[0] == 401
    assert anon.post('/api/login', {'login': 'nobody', 'password': 'whatever1'})[0] == 401
    assert anon.get('/api/clients')[0] == 401
    c = Client(server).login('owner', 'owner-pass-123')
    assert c.get('/api/me', expect=200)[1]['role'] == 'superadmin'
    c.post('/api/logout', expect=200)
    assert c.get('/api/me')[0] == 401


def test_login_throttle(server):
    c = Client(server)
    for _ in range(10):
        assert c.post('/api/login', {'login': 'throttled', 'password': 'bad-pass-1'}, token=None)[0] == 401
    assert c.post('/api/login', {'login': 'throttled', 'password': 'bad-pass-1'}, token=None)[0] == 429


def test_staff_management_and_permissions(owner, server):
    _, r = owner.post('/api/staff', {'login': 'reception1', 'full_name': 'Ресепшен', 'role': 'admin'}, expect=200)
    admin = Client(server).login('reception1', r['password'])
    assert admin.get('/api/staff')[0] == 403
    assert admin.get('/api/clients', expect=200)
    assert owner.post('/api/staff', {'login': 'reception1', 'full_name': 'Дубль'})[0] == 409
    # disabling revokes sessions immediately
    owner.patch(f"/api/staff/{r['id']}", {'enabled': False}, expect=200)
    assert admin.get('/api/clients')[0] == 401
    owner.patch(f"/api/staff/{r['id']}", {'enabled': True}, expect=200)
    _, reset = owner.post(f"/api/staff/{r['id']}/reset-password", expect=200)
    Client(server).login('reception1', reset['password'])
    assert anon_post_fails(server, 'reception1', r['password'])


def anon_post_fails(server, login, password):
    return Client(server).post('/api/login', {'login': login, 'password': password}, token=None)[0] == 401


def test_change_own_password(owner, server):
    _, r = owner.post('/api/staff', {'login': 'pwchange', 'full_name': 'Тест'}, expect=200)
    c = Client(server).login('pwchange', r['password'])
    assert c.post('/api/me/password', {'current': 'nope', 'new': 'new-password-1'})[0] == 400
    c.post('/api/me/password', {'current': r['password'], 'new': 'new-password-1'}, expect=200)
    assert c.get('/api/me')[0] == 401
    Client(server).login('pwchange', 'new-password-1')


# ---------------------------------------------------------------- clients

def test_client_crud_and_search(owner):
    cl = mk_client(owner, 'Петрова Ольга', '+998 93 555 11 22', ('Аня', 'Саша'))
    assert [c['full_name'] for c in cl['children']] == ['Аня', 'Саша']
    for q in ('Петрова', 'аня', '5551122', str(cl['id'])):
        _, rows = owner.get('/api/clients?q=' + __import__('urllib.parse').parse.quote(q), expect=200)
        assert any(r['id'] == cl['id'] for r in rows), q
    owner.patch(f"/api/clients/{cl['id']}", {'phone': '+998 99 000 00 00', 'note': 'аллергия на масло'}, expect=200)
    _, cl2 = owner.get(f"/api/clients/{cl['id']}", expect=200)
    assert cl2['note'] == 'аллергия на масло'
    _, ch = owner.post(f"/api/clients/{cl['id']}/children", {'full_name': 'Ваня', 'birth_date': '2021-05-01'}, expect=200)
    owner.patch(f"/api/children/{ch['id']}", {'archived': True}, expect=200)
    assert owner.post('/api/clients', {'full_name': 'x'})[0] == 400
    assert owner.get('/api/clients/999999')[0] == 404


def test_parent_app_login_and_privacy(owner, server):
    a = mk_client(owner, 'Родитель А')
    b = mk_client(owner, 'Родитель Б')
    mk_sub(owner, a)
    mk_sub(owner, b)
    pa, cred = parent_client(owner, server, a)
    assert cred['login'] == f"kid{a['id']}"
    _, prof = pa.get('/api/my/profile', expect=200)
    assert prof['id'] == a['id']
    _, subs = pa.get('/api/my/subscriptions', expect=200)
    assert len(subs) == 1 and subs[0]['client_id'] == a['id'] and 'price' not in subs[0]
    assert pa.get('/api/clients')[0] == 403
    assert pa.get(f"/api/clients/{b['id']}")[0] == 403
    # reissue invalidates the previous password and sessions
    _, cred2 = owner.post(f"/api/clients/{a['id']}/credentials", expect=200)
    assert pa.get('/api/my/profile')[0] == 401
    Client(server).login(cred2['login'], cred2['password'])
    owner.call('DELETE', f"/api/clients/{a['id']}/credentials", expect=200)
    assert Client(server).post('/api/login', {'login': cred2['login'], 'password': cred2['password']}, token=None)[0] == 401


# ---------------------------------------------------------------- subscriptions & visits

def test_subscription_lifecycle(owner, clock):
    clock(datetime(2026, 11, 2, 10, 0, tzinfo=TZ))
    cl = mk_client(owner)
    sub = mk_sub(owner, cl, starts_on='2026-11-02')
    assert sub['ends_on'] == '2026-12-31' and sub['state'] == 'active'
    assert sub['items'][0]['remaining'] == 10
    massage = service_id(owner, 'massage')
    child = cl['children'][0]['id']
    _, v = owner.post('/api/visits', {'subscription_id': sub['id'], 'service_id': massage, 'child_id': child}, expect=200)
    assert v['remaining'] == 9
    # duplicate guard on the same day, override with force
    assert owner.post('/api/visits', {'subscription_id': sub['id'], 'service_id': massage, 'child_id': child})[1]['error'] == 'already_visited_today'
    owner.post('/api/visits', {'subscription_id': sub['id'], 'service_id': massage, 'child_id': child, 'force': True}, expect=200)
    # wrong service
    pool = service_id(owner, 'pool')
    assert owner.post('/api/visits', {'subscription_id': sub['id'], 'service_id': pool})[1]['error'] == 'service_not_in_subscription'
    # cancel restores
    owner.post(f"/api/visits/{v['visit_id']}/cancel", {'reason': 'ошибка отметки'}, expect=200)
    assert owner.post(f"/api/visits/{v['visit_id']}/cancel", {'reason': 'ещё раз'})[0] == 409
    _, sub = owner.get(f"/api/subscriptions/{sub['id']}", expect=200)
    assert sub['items'][0]['remaining'] == 9
    assert {h['action'] for h in sub['history']} >= {'create_subscription', 'visit', 'cancel_visit'}

    # freeze 10 days -> end date moves by 10 days, visits blocked meanwhile
    owner.post(f"/api/subscriptions/{sub['id']}/freeze", {'reason': 'болезнь'}, expect=200)
    assert owner.post('/api/visits', {'subscription_id': sub['id'], 'service_id': massage})[1]['error'] == 'subscription_frozen'
    clock(datetime(2026, 11, 12, 10, 0, tzinfo=TZ))
    _, r = owner.post(f"/api/subscriptions/{sub['id']}/unfreeze", expect=200)
    assert r == {'ok': True, 'frozen_days': 10, 'ends_on': '2027-01-10'}

    _, r = owner.post(f"/api/subscriptions/{sub['id']}/extend", {'days': 5, 'reason': 'подарок'}, expect=200)
    assert r['ends_on'] == '2027-01-15'
    assert owner.post(f"/api/subscriptions/{sub['id']}/extend", {'days': 5})[1]['error'] == 'field_required'

    _, r = owner.post(f"/api/subscriptions/{sub['id']}/adjust", {'service_id': massage, 'delta': -8, 'reason': 'перенос'}, expect=200)
    assert r['remaining'] == 1
    assert owner.post(f"/api/subscriptions/{sub['id']}/adjust", {'service_id': massage, 'delta': -2, 'reason': 'тест'})[1]['error'] == 'not_enough_visits'
    owner.post('/api/visits', {'subscription_id': sub['id'], 'service_id': massage}, expect=200)
    assert owner.post('/api/visits', {'subscription_id': sub['id'], 'service_id': massage, 'force': True})[1]['error'] == 'no_visits_left'

    clock(datetime(2027, 1, 16, 10, 0, tzinfo=TZ))
    owner.post(f"/api/subscriptions/{sub['id']}/adjust", {'service_id': massage, 'delta': 1, 'reason': 'бонус'}, expect=200)
    assert owner.post('/api/visits', {'subscription_id': sub['id'], 'service_id': massage})[1]['error'] == 'subscription_expired'
    owner.post(f"/api/subscriptions/{sub['id']}/close", {'reason': 'завершён'}, expect=200)
    _, sub = owner.get(f"/api/subscriptions/{sub['id']}", expect=200)
    assert sub['state'] == 'closed'


def test_combined_and_child_bound_subscription(owner, clock):
    clock(datetime(2026, 11, 3, 12, 0, tzinfo=TZ))
    cl = mk_client(owner, 'Семья Каримовых', children=('Алия', 'Тимур'))
    alia, timur = (c['id'] for c in cl['children'])
    pool, hydro = service_id(owner, 'pool'), service_id(owner, 'hydromassage')
    _, r = owner.post('/api/subscriptions', {'client_id': cl['id'], 'child_id': alia, 'name': 'Комбо', 'validity_days': 30,
                                             'price': '450000.00', 'items': [{'service_id': pool, 'visits': 8},
                                                                             {'service_id': hydro, 'visits': 4}]}, expect=200)
    sid = r['id']
    assert owner.post('/api/visits', {'subscription_id': sid, 'service_id': pool, 'child_id': timur})[1]['error'] == 'subscription_for_other_child'
    _, v = owner.post('/api/visits', {'subscription_id': sid, 'service_id': pool}, expect=200)
    owner.post('/api/visits', {'subscription_id': sid, 'service_id': hydro}, expect=200)
    _, sub = owner.get(f'/api/subscriptions/{sid}', expect=200)
    assert {i['code']: i['remaining'] for i in sub['items']} == {'hydromassage': 3, 'pool': 7}
    assert sub['visits'][0]['child_name'] == 'Алия' and sub['price'] == '450000.00'
    other = mk_client(owner, 'Чужой')
    assert owner.post('/api/subscriptions', {'client_id': cl['id'], 'child_id': other['children'][0]['id'],
                                             'plan_id': plan_id(owner, 'Бассейн — 4 занятия')})[1]['error'] == 'child_not_of_client'
    assert owner.post('/api/subscriptions', {'client_id': cl['id'], 'name': 'x', 'validity_days': 10, 'items': [
        {'service_id': pool, 'visits': 1}, {'service_id': pool, 'visits': 2}]})[1]['error'] == 'duplicate_service'


# ---------------------------------------------------------------- QR

def test_qr_flow(owner, server, clock):
    t0 = datetime(2026, 11, 4, 9, 30, tzinfo=TZ)
    clock(t0)
    cl = mk_client(owner, 'QR Родитель')
    sub = mk_sub(owner, cl, plan='Бассейн — 8 занятий')
    other = mk_client(owner, 'QR Другой')
    other_sub = mk_sub(owner, other, plan='Бассейн — 8 занятий')
    parent, _ = parent_client(owner, server, cl)
    pool = service_id(owner, 'pool')
    _, qr = parent.post('/api/my/qr', expect=200)
    assert qr['code'].startswith('KSPA1:') and qr['ttl_seconds'] == 120
    _, look = owner.post('/api/qr/lookup', {'code': qr['code']}, expect=200)
    assert look['client']['id'] == cl['id'] and look['client']['subscriptions'][0]['id'] == sub['id']
    assert owner.post('/api/qr/redeem', {'code': qr['code'], 'subscription_id': other_sub['id'], 'service_id': pool})[1]['error'] == 'qr_other_client'
    _, r = owner.post('/api/qr/redeem', {'code': qr['code'], 'subscription_id': sub['id'], 'service_id': pool}, expect=200)
    assert r['remaining'] == 7
    assert owner.post('/api/qr/redeem', {'code': qr['code'], 'subscription_id': sub['id'], 'service_id': pool})[1]['error'] == 'qr_already_used'
    # a new code invalidates the previous unused one; codes expire after 2 minutes
    _, q1 = parent.post('/api/my/qr', expect=200)
    _, q2 = parent.post('/api/my/qr', expect=200)
    assert owner.post('/api/qr/lookup', {'code': q1['code']})[1]['error'] == 'qr_expired'
    clock(t0 + timedelta(minutes=3))
    assert owner.post('/api/qr/lookup', {'code': q2['code']})[1]['error'] == 'qr_expired'
    assert owner.post('/api/qr/lookup', {'code': 'garbage'})[1]['error'] == 'invalid_qr'
    assert parent.post('/api/qr/lookup', {'code': q2['code']})[0] == 403
    _, visits = parent.get('/api/my/visits', expect=200)
    assert visits[0]['method'] == 'qr' and 'staff_name' not in visits[0]


# ---------------------------------------------------------------- catalogue

PNG = base64.b64encode(b'\x89PNG\r\n\x1a\n' + b'\0' * 64).decode()


def test_catalogue_management(owner, anon):
    massage = service_id(owner, 'massage')
    owner.patch(f'/api/services/{massage}', {'description_ru': 'Новое описание', 'duration_min': 40}, expect=200)
    _, ph = owner.post(f'/api/services/{massage}/photos', {'content_type': 'image/png', 'data': PNG}, expect=200)
    assert owner.post(f'/api/services/{massage}/photos', {'content_type': 'image/png', 'data': base64.b64encode(b'GIF89a').decode()})[1]['error'] == 'invalid_image'
    status, body, headers = anon.call('GET', f"/api/photos/{ph['id']}", raw=True)
    assert status == 200 and headers['content-type'] == 'image/png' and body.startswith(b'\x89PNG')
    _, sp = owner.post('/api/specialists', {'full_name': 'Ольга Массажист', 'phone': '+998901112233', 'service_ids': [massage]}, expect=200)
    _, cat = anon.get('/api/catalog', expect=200)
    svc = next(s for s in cat['services'] if s['id'] == massage)
    assert svc['description_ru'] == 'Новое описание' and ph['id'] in svc['photos']
    assert svc['specialists'] == [{'id': sp['id'], 'full_name': 'Ольга Массажист'}]
    assert 'phone' not in cat['specialists'][0]
    _, pl = owner.post('/api/plans', {'name': 'Массаж — 5 сеансов', 'validity_days': 30, 'price': '250000',
                                      'items': [{'service_id': massage, 'visits': 5}]}, expect=200)
    owner.patch(f"/api/plans/{pl['id']}", {'active': False}, expect=200)
    assert all(p['id'] != pl['id'] for p in anon.get('/api/plans', expect=200)[1])
    owner.patch(f'/api/services/{massage}', {'active': False}, expect=200)
    assert all(s['id'] != massage for s in anon.get('/api/services', expect=200)[1])
    owner.patch(f'/api/services/{massage}', {'active': True}, expect=200)
    owner.call('DELETE', f"/api/photos/{ph['id']}", expect=200)
    assert anon.get('/api/clients')[0] == 401


# ---------------------------------------------------------------- reports & audit

def test_reports_and_audit(owner, db, clock):
    clock(datetime(2026, 11, 5, 11, 0, tzinfo=TZ))
    cl = mk_client(owner, 'Отчётный клиент')
    sub = mk_sub(owner, cl, plan='Гидромассаж — 10 сеансов', price='300000')
    owner.post('/api/visits', {'subscription_id': sub['id'], 'service_id': service_id(owner, 'hydromassage')}, expect=200)
    _, rep = owner.get('/api/reports?from=2026-11-05&to=2026-11-05', expect=200)
    assert next(r for r in rep['by_service'] if r['name'] == 'Гидромассаж')['visits'] >= 1
    assert rep['totals']['visits_today'] >= 1
    assert owner.get('/api/reports?from=2026-11-05&to=2026-01-01')[0] == 400
    _, log = owner.get('/api/audit?limit=50', expect=200)
    assert any(e['action'] == 'visit' for e in log)
    with pytest.raises(Exception):
        db.execute('UPDATE audit_log SET action=%s', ('tamper',))
    with pytest.raises(Exception):
        db.execute('DELETE FROM audit_log')


def test_expiring_list(owner, clock):
    clock(datetime(2026, 11, 6, 11, 0, tzinfo=TZ))
    cl = mk_client(owner, 'Скоро истекает')
    _, r = owner.post('/api/subscriptions', {'client_id': cl['id'], 'plan_id': plan_id(owner, 'Бассейн — 4 занятия'),
                                             'starts_on': '2026-10-10'}, expect=200)
    _, rows = owner.get('/api/subscriptions?state=expiring', expect=200)
    assert any(s['id'] == r['id'] for s in rows)


def test_input_validation(owner):
    assert owner.post('/api/subscriptions', {'client_id': 'abc'})[0] == 400
    assert owner.call('POST', '/api/clients', None)[0] in (400,)
    status, payload, _ = owner.call('POST', '/api/clients', raw=True, body=None)
    assert status == 400


def test_public_site_and_settings(owner, anon, server):
    owner.patch('/api/settings', {'phone': '+998 71 200 00 00', 'address': 'Ташкент, ул. Тестовая, 1', 'instagram': '@kinderspa'}, expect=200)
    assert owner.patch('/api/settings', {'map_url': 'javascript:alert(1)'})[0] == 400
    _, st = anon.get('/api/settings', expect=200)
    assert st['instagram'] == 'https://instagram.com/kinderspa' and st['bot_username'] == 'kinder_test_bot'
    for lang, words in (('ru', ['Массаж, гидромассаж и бассейн', 'Записаться в Telegram', 'https://t.me/kinder_test_bot', 'tel:+998712000000']),
                        ('uz', ['Bolalar uchun massaj', 'Telegram orqali yozilish', 'Basseyn'])):
        status, body, headers = anon.call('GET', f'/?lang={lang}', raw=True)
        html = body.decode()
        assert status == 200 and all(w in html for w in words), (lang, [w for w in words if w not in html])
    assert anon.call('GET', '/assets/site.css', raw=True)[0] == 200
    status, _, headers = anon.call('GET', '/assets/fonts/Nunito.ttf', raw=True)
    assert status == 200 and 'max-age' in headers['cache-control']
    assert anon.call('GET', '/assets/img/welcome-ru.png', raw=True)[0] == 200
