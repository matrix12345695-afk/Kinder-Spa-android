import itertools
import re
from datetime import datetime, timedelta, timezone

import pytest

from conftest import Client
from kinder.telegram import webhook_secret, BTN_QR, BTN_SUBS, BTN_VISITS, BTN_SERVICES, BTN_TODAY, BTN_LOGOUT

TZ = timezone(timedelta(hours=5))
SECRET = webhook_secret('123:TEST')
_ids = itertools.count(1000)
_chats = itertools.count(5000)


class Chat:
    def __init__(self, anon, fake):
        self.anon, self.fake, self.id = anon, fake, next(_chats)

    def send(self, text, update_id=None):
        uid = update_id or next(_ids)
        body = {'update_id': uid, 'message': {'message_id': uid, 'chat': {'id': self.id, 'type': 'private'},
                                              'from': {'id': self.id, 'first_name': 'Тест'}, 'text': text}}
        status, _ = self.anon.call('POST', '/telegram/webhook', body, token=None)
        assert status == 200
        return uid

    def press(self, data):
        uid = next(_ids)
        body = {'update_id': uid, 'callback_query': {'id': str(uid), 'data': data, 'from': {'id': self.id, 'first_name': 'Тест'},
                                                      'message': {'message_id': 1, 'chat': {'id': self.id, 'type': 'private'}}}}
        req_status = self.anon.call('POST', '/telegram/webhook', body, token=None)[0]
        assert req_status == 200

    def last(self, method='sendMessage'):
        rows = self.fake.take(method, self.id)
        return rows[-1] if rows else None

    def login(self, login, password):
        self.send('/start')
        self.send(login)
        self.send(password)
        return self.last()


def webhook(anon, body, secret=SECRET):
    import json
    import urllib.request
    import urllib.error
    req = urllib.request.Request(anon.base + '/telegram/webhook', data=json.dumps(body).encode(), method='POST',
                                 headers={'Content-Type': 'application/json', 'X-Telegram-Bot-Api-Secret-Token': secret})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


@pytest.fixture
def chat(anon, fake_telegram, monkeypatch):
    orig = anon.call

    def call(method, path, body=None, token=..., expect=None, raw=False):
        if path == '/telegram/webhook':
            return webhook(anon, body), None
        return orig(method, path, body, token, expect, raw)
    monkeypatch.setattr(anon, 'call', call)
    return Chat(anon, fake_telegram)


def parent(owner, name='Телеграм Родитель', plan='Бассейн — 8 занятий', child='Амир'):
    _, r = owner.post('/api/clients', {'full_name': name, 'children': [{'full_name': child}]}, expect=200)
    _, plans = owner.get('/api/plans')
    pid = next(p['id'] for p in plans if p['name'] == plan)
    _, sub = owner.post('/api/subscriptions', {'client_id': r['id'], 'plan_id': pid}, expect=200)
    _, cred = owner.post(f"/api/clients/{r['id']}/credentials", expect=200)
    return r['id'], sub['id'], cred


def pool_id(owner):
    return next(s['id'] for s in owner.get('/api/services')[1] if s['code'] == 'pool')


def test_webhook_registered_on_startup(server, fake_telegram):
    hooks = fake_telegram.take('setWebhook')
    assert hooks and hooks[0]['url'] == 'https://kinder.test/telegram/webhook' and hooks[0]['secret_token'] == SECRET
    assert fake_telegram.take('setMyCommands')


def test_webhook_rejects_bad_secret(anon):
    assert webhook(anon, {'update_id': 1}, secret='wrong') == 403
    assert webhook(anon, {'update_id': 1}, secret='') == 403


def test_parent_login_qr_and_notifications(owner, chat, fake_telegram):
    cid, sid, cred = parent(owner)
    chat.send('/start')
    assert 'отправьте <b>логин</b>' in chat.last()['text']
    chat.send('НЕ ЛОГИН!')
    assert 'латинских' in chat.last()['text']
    chat.send(cred['login'])
    pw_msg = chat.send(cred['password'])
    assert any(p['message_id'] == pw_msg for p in fake_telegram.take('deleteMessage', chat.id))
    welcome = chat.last()
    assert 'Готово' in welcome['text'] and welcome['reply_markup']['keyboard'][0][0]['text'] == BTN_QR

    # card in admin shows the bot link
    assert owner.get(f'/api/clients/{cid}')[1]['telegram_chats'] == 1

    chat.send(BTN_SUBS)
    assert 'Бассейн: <b>8</b> из 8' in chat.last()['text']

    # QR as a PNG photo; reception can use it
    chat.send(BTN_QR)
    photo = chat.last('sendPhoto')['_multipart']
    assert b'\x89PNG' in photo
    png = photo[photo.index(b'\x89PNG'):photo.rindex(b'IEND') + 8]
    cv2 = pytest.importorskip('cv2')
    import numpy as np
    code, _, _ = cv2.QRCodeDetector().detectAndDecode(cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE))
    assert code.startswith('KSPA1:')
    _, look = owner.post('/api/qr/lookup', {'code': code}, expect=200)
    assert look['client']['id'] == cid
    _, r = owner.post('/api/qr/redeem', {'code': code, 'subscription_id': sid, 'service_id': pool_id(owner)}, expect=200)
    note = fake_telegram.wait('sendMessage', chat.id, 'Посещение отмечено')
    assert 'Осталось: <b>7</b> из 8' in note['text'] and '(Амир)' in note['text']

    # "new code" button issues a fresh QR and invalidates the old one
    before = len(fake_telegram.take('sendPhoto', chat.id))
    chat.press('qr')
    assert len(fake_telegram.take('sendPhoto', chat.id)) == before + 1

    chat.send(BTN_VISITS)
    assert 'Бассейн (Амир)' in chat.last()['text']
    chat.send(BTN_SERVICES)
    assert any('Детский массаж' in p.get('text', '') for p in fake_telegram.take('sendMessage', chat.id))

    # cancellation and freeze are announced too
    visit_id = owner.get(f'/api/subscriptions/{sid}')[1]['visits'][0]['id']
    owner.post(f'/api/visits/{visit_id}/cancel', {'reason': 'ошибка'}, expect=200)
    fake_telegram.wait('sendMessage', chat.id, 'отменено, оно возвращено')
    owner.post(f'/api/subscriptions/{sid}/freeze', {'reason': 'болеем'}, expect=200)
    fake_telegram.wait('sendMessage', chat.id, 'заморожен')

    # duplicate webhook delivery is ignored
    n = len(fake_telegram.take(None, chat.id))
    uid = chat.send(BTN_SUBS)
    chat.send(BTN_SUBS, update_id=uid)
    assert len(fake_telegram.take(None, chat.id)) == n + 1

    # password reset at reception unlinks the chat
    owner.post(f'/api/clients/{cid}/credentials', expect=200)
    chat.send(BTN_SUBS)
    assert 'Доступ изменился' in chat.last()['text']
    chat.send(BTN_QR)
    assert 'отправьте <b>логин</b>' in chat.last()['text']


def test_wrong_password_and_throttle(owner, chat):
    _, _, cred = parent(owner, 'Пароль Неверный')
    msg = chat.login(cred['login'], 'not-the-password')
    assert 'Неверный логин или пароль' in msg['text']
    for _ in range(10):
        chat.send(cred['login'])
        chat.send('bad-again')
    assert 'Слишком много попыток' in chat.last()['text']


def test_logout(owner, chat):
    _, _, cred = parent(owner, 'Выход Тест')
    chat.login(cred['login'], cred['password'])
    chat.send(BTN_LOGOUT)
    assert 'Вы вышли' in chat.last()['text']
    chat.send(BTN_SUBS)
    assert 'отправьте <b>логин</b>' in chat.last()['text']


def test_staff_bot(owner, chat, server):
    _, staff = owner.post('/api/staff', {'login': 'tgstaff', 'full_name': 'Ресепшен Бот'}, expect=200)
    msg = chat.login('tgstaff', staff['password'])
    first = msg['reply_markup']['keyboard'][0][0]
    assert first['text'] == '📷 Сканировать QR' and first['web_app']['url'] == 'https://kinder.test/tg/scan'
    assert msg['reply_markup']['keyboard'][1][0]['text'] == BTN_TODAY
    chat.send(BTN_TODAY)
    assert 'Посещений:' in chat.last()['text']


def test_blocked_bot_unlinks_chat(owner, chat, fake_telegram, db):
    cid, sid, cred = parent(owner, 'Заблокировал Бота')
    chat.login(cred['login'], cred['password'])
    fake_telegram.blocked.add(chat.id)
    try:
        owner.post('/api/visits', {'subscription_id': sid, 'service_id': pool_id(owner)}, expect=200)
        for _ in range(100):
            row = db.execute('SELECT user_id FROM telegram_chats WHERE chat_id=%s', (chat.id,)).fetchone()
            if row['user_id'] is None:
                break
            __import__('time').sleep(0.05)
        assert row['user_id'] is None
        assert db.execute('SELECT attempts FROM telegram_outbox WHERE chat_id=%s ORDER BY id DESC LIMIT 1', (chat.id,)).fetchone()['attempts'] == 99
    finally:
        fake_telegram.blocked.discard(chat.id)


def test_daily_reminders_and_digest(owner, chat, anon, server, fake_telegram, clock):
    clock(datetime(2026, 11, 20, 8, 0, tzinfo=TZ))
    cid, _, cred = parent(owner, 'Напоминание Тест', plan='Бассейн — 4 занятия')
    # starts 2026-10-23, 30 days -> ends 2026-11-21 (tomorrow)
    _, plans = owner.get('/api/plans')
    pid = next(p['id'] for p in plans if p['name'] == 'Бассейн — 4 занятия')
    owner.post('/api/subscriptions', {'client_id': cid, 'plan_id': pid, 'starts_on': '2026-10-23'}, expect=200)
    chat.login(cred['login'], cred['password'])
    staff_chat = Chat(chat.anon, fake_telegram)
    _, staff = owner.post('/api/staff', {'login': 'digeststaff', 'full_name': 'Утро'}, expect=200)
    staff_chat.login('digeststaff', staff['password'])

    clock(datetime(2026, 11, 20, 2, 0, tzinfo=TZ))   # night: secret required
    assert anon.call('POST', '/api/cron/daily', {}, token=None)[0] == 404
    clock(datetime(2026, 11, 20, 8, 0, tzinfo=TZ))
    import json
    import urllib.request
    req = urllib.request.Request(anon.base + '/api/cron/daily', data=b'{}', method='POST', headers={'X-Cron-Secret': 'cron-secret-for-tests'})
    with urllib.request.urlopen(req) as r:
        first = json.loads(r.read())
    assert first['reminders'] >= 1 and first['digests'] >= 1
    msg = fake_telegram.wait('sendMessage', chat.id, 'заканчивается завтра')
    assert 'Бассейн' in msg['text']
    fake_telegram.wait('sendMessage', staff_chat.id, 'Сводка за вчера')
    with urllib.request.urlopen(urllib.request.Request(req.full_url, data=b'{}', method='POST')) as r:  # morning window, no secret
        second = json.loads(r.read())
    assert second['reminders'] == 0 and second['digests'] == 0
