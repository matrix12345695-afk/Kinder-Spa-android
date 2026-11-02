"""Reception QR scanner (Telegram Mini App): initData auth and the page itself."""
import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request
import urllib.error

import pytest

from conftest import Client
from kinder.telegram import validate_init_data
from test_telegram import Chat, parent, pool_id, chat  # noqa: F401  (fixture reuse)

TOKEN = '123:TEST'


def init_data(user_id, token=TOKEN, auth_date=None, tamper=False):
    fields = {'auth_date': str(auth_date or int(time.time())), 'query_id': 'AAF',
              'user': json.dumps({'id': user_id, 'first_name': 'Рецепция'}, separators=(',', ':'), ensure_ascii=False)}
    check = '\n'.join(f'{k}={v}' for k, v in sorted(fields.items()))
    secret = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
    fields['hash'] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if tamper:
        fields['user'] = fields['user'].replace(str(user_id), str(user_id + 1))
    return urllib.parse.urlencode(fields)


def tg_call(base, method, path, data, body=None):
    req = urllib.request.Request(base + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json', 'X-Telegram-Init-Data': data})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'null')


def test_validate_init_data():
    assert validate_init_data(init_data(42), TOKEN)['id'] == 42
    assert validate_init_data(init_data(42, tamper=True), TOKEN) is None
    assert validate_init_data(init_data(42, token='999:OTHER'), TOKEN) is None
    assert validate_init_data(init_data(42, auth_date=int(time.time()) - 3 * 86400), TOKEN) is None
    assert validate_init_data('garbage', TOKEN) is None and validate_init_data('', TOKEN) is None


def test_scanner_api_access(owner, chat, server):
    _, staff = owner.post('/api/staff', {'login': 'scanstaff', 'full_name': 'Сканер Ресепшен'}, expect=200)
    chat.login('scanstaff', staff['password'])
    status, me = tg_call(server, 'GET', '/api/me', init_data(chat.id))
    assert status == 200 and me['login'] == 'scanstaff'

    cid, sid, cred = parent(owner, 'Скан Родитель')
    parent_client = Client(server).login(cred['login'], cred['password'])
    code = parent_client.post('/api/my/qr', expect=200)[1]['code']
    status, look = tg_call(server, 'POST', '/api/qr/lookup', init_data(chat.id), {'code': code})
    assert status == 200 and look['client']['id'] == cid
    status, r = tg_call(server, 'POST', '/api/qr/redeem', init_data(chat.id),
                        {'code': code, 'subscription_id': sid, 'service_id': pool_id(owner)})
    assert status == 200 and r['remaining'] == 7
    visits = owner.get(f'/api/subscriptions/{sid}')[1]['visits']
    assert visits[0]['staff_name'] == 'Сканер Ресепшен' and visits[0]['method'] == 'qr'

    # a parent linked to the bot cannot use the scanner; unknown / forged accounts get 401
    parent_chat = Chat(chat.anon, chat.fake)
    parent_chat.login(cred['login'], cred['password'])
    assert tg_call(server, 'POST', '/api/qr/lookup', init_data(parent_chat.id), {'code': code})[0] == 403
    assert tg_call(server, 'GET', '/api/me', init_data(987654321))[0] == 401
    assert tg_call(server, 'GET', '/api/me', init_data(chat.id, tamper=True))[0] == 401
    assert tg_call(server, 'GET', '/api/me', init_data(chat.id, token='1:WRONG'))[0] == 401


STUB = """window.Telegram = {WebApp: {initData: %s, version: '8.0', isVersionAtLeast: () => true,
  ready() {}, expand() {}, HapticFeedback: {notificationOccurred() {}},
  showConfirm(t, cb) { cb(true); },
  showScanQrPopup(p, cb) { window.__scans = (window.__scans || 0) + 1; if (window.__nextCode) { const c = window.__nextCode; window.__nextCode = null; cb(c); } }}};"""


def test_scanner_page_in_browser(owner, chat, server):
    sync_api = pytest.importorskip('playwright.sync_api')
    _, staff = owner.post('/api/staff', {'login': 'scanpage', 'full_name': 'Утренний ресепшен'}, expect=200)
    chat.login('scanpage', staff['password'])
    cid, sid, cred = parent(owner, 'Страница Сканера', child='Лейла')
    code = Client(server).login(cred['login'], cred['password']).post('/api/my/qr', expect=200)[1]['code']
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page(viewport={'width': 390, 'height': 800})
        errors = []
        pg.on('pageerror', lambda e: errors.append(str(e)))
        pg.route('https://telegram.org/**', lambda route: route.fulfill(
            status=200, content_type='application/javascript', body=STUB % json.dumps(init_data(chat.id))))
        pg.add_init_script(f'window.__nextCode = {json.dumps(code)};')
        status = pg.goto(server + '/tg/scan').status
        assert status == 200
        pg.wait_for_selector('h3:has-text("Страница Сканера")')
        pg.click('button:has-text("Списать посещение")')
        pg.wait_for_selector('text=Посещение списано')
        assert 'Осталось: 7' in pg.inner_text('.done')
        pg.wait_for_selector('.visit:has-text("Страница Сканера (Лейла)")')
        pg.screenshot(path='/tmp/kinder-shots/09-tg-scanner.png', full_page=True)
        # opened outside Telegram: no initData -> explanation, no scanner
        pg2 = browser.new_page()
        pg2.route('https://telegram.org/**', lambda route: route.fulfill(status=200, content_type='application/javascript', body=''))
        pg2.goto(server + '/tg/scan')
        pg2.wait_for_selector('text=Откройте сканер из Telegram-бота')
        browser.close()
    assert not errors, errors
