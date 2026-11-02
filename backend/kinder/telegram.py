"""Kinder Spa Telegram bot: webhook mode inside the web service (no separate worker).

Parents log in with the login/password issued at reception and get their QR code,
subscriptions, visits and the service catalogue. Staff get a daily digest and a
"today" summary. Notifications go through telegram_outbox (written inside the
business transaction) and are sent after commit or by the daily cron call.
"""
import hashlib
import hmac
import html
import json
import logging
import os
import secrets
import urllib.error
import urllib.request
from datetime import timedelta

from . import security as sec
from .qr import qr_png

log = logging.getLogger('kinder.telegram')

BTN_QR, BTN_SUBS, BTN_VISITS, BTN_SERVICES, BTN_HELP, BTN_LOGOUT = (
    '📱 QR-код', '🎫 Мои абонементы', '🕘 Посещения', '💆 Услуги', '❓ Помощь', '🚪 Выйти')
BTN_TODAY, BTN_ENDING, BTN_SCHEDULE = '📊 Сегодня', '⏳ Заканчиваются', '🗓 Расписание'
BTN_BOOK, BTN_MY_BOOKINGS = '📅 Записаться', '🗓 Мои записи'
CLIENT_MENU = {'keyboard': [[{'text': BTN_QR}], [{'text': BTN_BOOK}, {'text': BTN_MY_BOOKINGS}],
                            [{'text': BTN_SUBS}, {'text': BTN_VISITS}],
                            [{'text': BTN_SERVICES}, {'text': BTN_HELP}], [{'text': BTN_LOGOUT}]],
               'resize_keyboard': True, 'is_persistent': True}
STAFF_MENU = {'keyboard': [[{'text': BTN_TODAY}, {'text': BTN_ENDING}], [{'text': BTN_HELP}, {'text': BTN_LOGOUT}]],
              'resize_keyboard': True, 'is_persistent': True}
NO_MENU = {'remove_keyboard': True}
STATE_NAMES = {'active': 'активен', 'frozen': 'заморожен', 'closed': 'закрыт', 'expired': 'истёк',
               'used_up': 'использован', 'not_started': 'ещё не начался'}
e = html.escape


class TelegramError(Exception):
    def __init__(self, code, description):
        super().__init__(f'{code}: {description}')
        self.code, self.description = code, description


def validate_init_data(init_data, token, max_age=86400, now_ts=None):
    """Validate Telegram Mini App initData; returns the Telegram user dict or None."""
    import time
    from urllib.parse import parse_qsl
    if not init_data or not token or len(init_data) > 4096:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError:
        return None
    received = pairs.pop('hash', '')
    check = '\n'.join(f'{k}={v}' for k, v in sorted(pairs.items()))
    secret = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        return None
    try:
        auth_date = int(pairs.get('auth_date', '0'))
        user = json.loads(pairs.get('user', '{}'))
    except ValueError:
        return None
    if abs((now_ts or time.time()) - auth_date) > max_age or not isinstance(user.get('id'), int):
        return None
    return user


def user_for_tg_id(c, tg_user_id):
    """Kinder user linked to this Telegram account (private chat id == user id)."""
    return c.execute('''SELECT u.id, u.role, u.login, u.full_name FROM telegram_chats tc JOIN users u ON u.id = tc.user_id
        WHERE tc.chat_id = %s AND u.enabled AND tc.cred_version = u.cred_version''', (tg_user_id,)).fetchone()


def webhook_secret(token):
    return hmac.new(token.encode(), b'kinder-spa-webhook', hashlib.sha256).hexdigest()[:48]


class TelegramAPI:
    def __init__(self, token, base=None, timeout=15):
        self.token = token
        self.base = (base or os.environ.get('TELEGRAM_API_BASE') or 'https://api.telegram.org').rstrip('/')
        self.timeout = timeout

    def _request(self, method, body, content_type):
        req = urllib.request.Request(f'{self.base}/bot{self.token}/{method}', data=body, method='POST',
                                     headers={'Content-Type': content_type})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                payload = json.loads(r.read() or b'{}')
        except urllib.error.HTTPError as err:
            try:
                payload = json.loads(err.read() or b'{}')
            except ValueError:
                payload = {'ok': False, 'error_code': err.code, 'description': 'http error'}
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            raise TelegramError(0, f'network: {err}')
        if not payload.get('ok'):
            raise TelegramError(payload.get('error_code', 0), payload.get('description', 'unknown'))
        return payload.get('result')

    def call(self, method, **params):
        params = {k: v for k, v in params.items() if v is not None}
        return self._request(method, json.dumps(params, ensure_ascii=False).encode(), 'application/json')

    def send_photo_bytes(self, chat_id, data, caption=None, reply_markup=None, filename='qr.png'):
        boundary = secrets.token_hex(16)
        parts = []
        fields = {'chat_id': str(chat_id), 'parse_mode': 'HTML'}
        if caption:
            fields['caption'] = caption
        if reply_markup:
            fields['reply_markup'] = json.dumps(reply_markup, ensure_ascii=False)
        for k, v in fields.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="{filename}"\r\n'
                     f'Content-Type: image/png\r\n\r\n'.encode() + data + b'\r\n')
        parts.append(f'--{boundary}--\r\n'.encode())
        return self._request('sendPhoto', b''.join(parts), f'multipart/form-data; boundary={boundary}')

    def send(self, chat_id, text, reply_markup=None):
        return self.call('sendMessage', chat_id=chat_id, text=text, parse_mode='HTML',
                         reply_markup=reply_markup, link_preview_options={'is_disabled': True})


# ------------------------------------------------------------------ helpers

class DbCtx:
    """Minimal stand-in for app.Ctx so the app's query helpers can be reused."""
    def __init__(self, c, user=None):
        self.c, self.user = c, user

    def one(self, sql, args=()):
        return self.c.execute(sql, args).fetchone()

    def all(self, sql, args=()):
        return self.c.execute(sql, args).fetchall()

    def notify_client(self, client_id, text):
        enqueue_for_client(self.c, client_id, text)

    def audit(self, action, entity, entity_id=None, **details):
        self.c.execute('INSERT INTO audit_log(actor_id, action, entity, entity_id, details) VALUES (%s,%s,%s,%s,%s::jsonb)',
                       (self.user['id'] if self.user else None, action, entity, entity_id,
                        json.dumps(details, default=str, ensure_ascii=False)))


def d(value):
    return value.strftime('%d.%m.%Y') if value else '—'


def client_chats(c, client_id):
    rows = c.execute('''SELECT tc.chat_id FROM telegram_chats tc JOIN users u ON u.id = tc.user_id
        JOIN clients cl ON cl.user_id = u.id
        WHERE cl.id = %s AND u.enabled AND tc.cred_version = u.cred_version''', (client_id,)).fetchall()
    return [r['chat_id'] for r in rows]


def staff_chats(c):
    rows = c.execute('''SELECT tc.chat_id FROM telegram_chats tc JOIN users u ON u.id = tc.user_id
        WHERE u.role IN ('admin','superadmin') AND u.enabled AND tc.cred_version = u.cred_version''').fetchall()
    return [r['chat_id'] for r in rows]


def enqueue(c, chat_ids, text):
    for chat_id in chat_ids:
        c.execute('INSERT INTO telegram_outbox(chat_id, text) VALUES (%s,%s)', (chat_id, text))
    return len(chat_ids)


def enqueue_for_client(c, client_id, text):
    """Called inside business transactions. Returns number of queued messages."""
    return enqueue(c, client_chats(c, client_id), text)


def items_text(items):
    return ', '.join(f"{e(i['name_ru'])}: <b>{i['remaining']}</b> из {i['quota']}" for i in items)


# ------------------------------------------------------------------ outbox

def flush_outbox(db, tg, limit=50):
    sent = failed = 0
    with db.conn() as c:
        for _ in range(limit):
            with c.transaction():
                row = c.execute('''SELECT id, chat_id, text FROM telegram_outbox WHERE sent_at IS NULL AND attempts < 5
                    ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED''').fetchone()
                if not row:
                    break
                try:
                    tg.send(row['chat_id'], row['text'])
                    c.execute('UPDATE telegram_outbox SET sent_at=now(), attempts=attempts+1 WHERE id=%s', (row['id'],))
                    sent += 1
                except TelegramError as err:
                    failed += 1
                    final = err.code in (400, 403)  # chat not found / bot blocked: never retry
                    if final:
                        c.execute('UPDATE telegram_outbox SET attempts=99, last_error=%s WHERE id=%s', (str(err)[:500], row['id']))
                    else:
                        c.execute('UPDATE telegram_outbox SET attempts=attempts+1, last_error=%s WHERE id=%s',
                                  (str(err)[:500], row['id']))
                    if err.code == 403:
                        c.execute("UPDATE telegram_chats SET user_id=NULL, cred_version=NULL, state='idle' WHERE chat_id=%s",
                                  (row['chat_id'],))
                    if err.code in (0, 429) or err.code >= 500:
                        break  # Telegram unreachable or rate limiting: try later
    return {'sent': sent, 'failed': failed}


# ------------------------------------------------------------------ daily job

def daily(db, tg):
    from . import app as A
    t = A.today()
    out = {'reminders': 0, 'digests': 0}
    with db.conn() as c, c.transaction():
        x = DbCtx(c)
        ending = A.subscriptions_for(x, "s.status='active' AND s.ends_on BETWEEN %s AND %s", (t, t + timedelta(days=3)))
        for s in ending:
            if s['state'] != 'active':
                continue
            if c.execute("INSERT INTO reminders_sent VALUES (%s,'ends_soon',%s) ON CONFLICT DO NOTHING RETURNING 1",
                         (s['id'], t)).fetchone():
                days = (s['ends_on'] - t).days
                when = 'сегодня' if days == 0 else ('завтра' if days == 1 else f'через {days} дн. ({d(s["ends_on"])})')
                out['reminders'] += enqueue_for_client(c, s['client_id'],
                    f"⏳ Абонемент <b>{e(s['name'])}</b> заканчивается {when}.\nОсталось: {items_text(s['items'])}.\n"
                    'Чтобы продлить, обратитесь на ресепшен.')
        expired = A.subscriptions_for(x, "s.status='active' AND s.ends_on = %s", (t - timedelta(days=1),))
        for s in expired:
            left = sum(i['remaining'] for i in s['items'])
            if left and c.execute("INSERT INTO reminders_sent VALUES (%s,'expired',%s) ON CONFLICT DO NOTHING RETURNING 1",
                                  (s['id'], t)).fetchone():
                out['reminders'] += enqueue_for_client(c, s['client_id'],
                    f"⌛ Срок абонемента <b>{e(s['name'])}</b> истёк, неиспользованных посещений: {left}.\n"
                    'Если нужно продлить, обратитесь на ресепшен.')
        from . import schedule as S
        for b in S.bookings_query(x, "b.status='booked' AND (sl.starts_at AT TIME ZONE 'Asia/Tashkent')::date = %s",
                                  (t + timedelta(days=1),)):
            if c.execute("INSERT INTO reminders_sent VALUES (%s,%s,%s) ON CONFLICT DO NOTHING RETURNING 1",
                         (b['subscription_id'], f"booking:{b['id']}", t)).fetchone():
                who = f" ({e(b['child_name'])})" if b['child_name'] else ''
                out['reminders'] += enqueue_for_client(c, b['client_id'],
                    f"🔔 Напоминаем: завтра <b>{e(b['service_name'])}</b>{who} в {S.local(b['starts_at']).strftime('%H:%M')}.\n"
                    f"Если не получается, отмените запись до 19:00 сегодня: {BTN_MY_BOOKINGS}")
        if c.execute("INSERT INTO job_runs VALUES ('staff_digest', %s) ON CONFLICT DO NOTHING RETURNING 1", (t,)).fetchone():
            out['digests'] = enqueue(c, staff_chats(c), staff_summary(x, t - timedelta(days=1), title='Сводка за вчера'))
        c.execute("DELETE FROM telegram_updates WHERE received_at < now() - interval '7 days'")
    out.update(flush_outbox(db, tg, limit=200))
    return out


def staff_summary(x, day, title='Сегодня'):
    from . import app as A
    vday = "(v.visited_at AT TIME ZONE 'Asia/Tashkent')::date"
    by_service = x.all(f'''SELECT sv.name_ru AS name, count(v.id) AS n FROM services sv
        LEFT JOIN visits v ON v.service_id = sv.id AND v.cancelled_at IS NULL AND {vday} = %s
        GROUP BY sv.id ORDER BY sv.sort, sv.id''', (day,))
    total = sum(r['n'] for r in by_service)
    t = A.today()
    ending = x.one('''SELECT count(*) AS n FROM subscriptions WHERE status='active' AND ends_on BETWEEN %s AND %s''',
                   (t, t + timedelta(days=7)))['n']
    frozen = x.one("SELECT count(*) AS n FROM subscriptions WHERE status='frozen'")['n']
    sold = x.one("""SELECT count(*) AS n, coalesce(sum(price),0) AS sum FROM subscriptions
        WHERE (created_at AT TIME ZONE 'Asia/Tashkent')::date = %s""", (day,))
    lines = [f'📊 <b>{e(title)}, {d(day)}</b>', f'Посещений: <b>{total}</b>']
    lines += [f'• {e(r["name"])}: {r["n"]}' for r in by_service]
    cash = x.all('''SELECT method, sum(amount) AS v FROM payments WHERE voided_at IS NULL
        AND (paid_at AT TIME ZONE 'Asia/Tashkent')::date = %s GROUP BY method ORDER BY 2 DESC''', (day,))
    lines += [f'Касса: <b>{A.fmt_sum(sum(r["v"] for r in cash))}</b>' +
              (' (' + ', '.join(f'{A.PAYMENT_METHODS[r["method"]]} {A.fmt_sum(r["v"])}' for r in cash) + ')' if cash else '')]
    lines += [f'Продано абонементов: {sold["n"]} на {int(sold["sum"]):,} сум'.replace(',', ' '),
              f'Заканчиваются за 7 дней: {ending}', f'Заморожено: {frozen}']
    return '\n'.join(lines)


# ------------------------------------------------------------------ bot

def linked_user(c, chat):
    if not chat or not chat['user_id']:
        return None
    return c.execute('''SELECT id, role, login, full_name, cred_version FROM users
        WHERE id=%s AND enabled AND cred_version=%s''', (chat['user_id'], chat['cred_version'])).fetchone()


def set_state(c, chat_id, state, data=None):
    c.execute('UPDATE telegram_chats SET state=%s, state_data=%s::jsonb, updated_at=now() WHERE chat_id=%s',
              (state, json.dumps(data or {}), chat_id))


BTN_SCAN = '📷 Сканировать QR'
PUBLIC_URL = ''  # set by the app at startup


def staff_menu():
    rows = [[{'text': BTN_TODAY}, {'text': BTN_SCHEDULE}], [{'text': BTN_ENDING}, {'text': BTN_HELP}], [{'text': BTN_LOGOUT}]]
    if PUBLIC_URL.startswith('https://'):
        rows.insert(0, [{'text': BTN_SCAN, 'web_app': {'url': PUBLIC_URL + '/tg/scan'}}])
    return {'keyboard': rows, 'resize_keyboard': True, 'is_persistent': True}


def menu_for(user):
    return staff_menu() if user['role'] in ('admin', 'superadmin') else CLIENT_MENU


HELP_CLIENT = ('Это бот детского центра <b>Kinder Spa</b>.\n\n'
               f'{BTN_QR} — покажите его на ресепшене, код действует 2 минуты.\n'
               f'{BTN_BOOK} — выбрать услугу, день и время.\n'
               f'{BTN_MY_BOOKINGS} — ваши записи и отмена.\n'
               f'{BTN_SUBS} — остаток посещений и срок.\n'
               f'{BTN_VISITS} — история посещений.\n'
               f'{BTN_SERVICES} — массаж, гидромассаж, бассейн.\n\n'
               'После каждого посещения сюда придёт уведомление, а за 3 дня до окончания абонемента — напоминание.')
HELP_STAFF = ('Вы вошли как сотрудник Kinder Spa.\n\n'
              f'{BTN_SCAN} — наведите камеру на QR-код клиента и спишите посещение.\n'
              f'{BTN_TODAY} — посещения и продажи за сегодня.\n'
              f'{BTN_SCHEDULE} — занятия и записи на сегодня.\n'
              f'{BTN_ENDING} — абонементы, которые скоро закончатся.\n'
              'Каждое утро сюда приходит сводка за вчерашний день.')


def handle_update(db, tg, update, public_url=''):
    if not isinstance(update, dict) or not isinstance(update.get('update_id'), int):
        return
    with db.conn() as c:
        if not c.execute('INSERT INTO telegram_updates(update_id) VALUES (%s) ON CONFLICT DO NOTHING RETURNING 1',
                         (update['update_id'],)).fetchone():
            return  # duplicate delivery
        if 'callback_query' in update:
            cq = update['callback_query']
            msg = cq.get('message') or {}
            chat_id = (msg.get('chat') or {}).get('id')
            try:
                tg.call('answerCallbackQuery', callback_query_id=cq.get('id'))
            except TelegramError:
                pass
            data = cq.get('data') or ''
            if chat_id and data == 'qr':
                _dispatch(c, tg, chat_id, BTN_QR, (cq.get('from') or {}).get('first_name', ''), None, public_url)
            elif chat_id and data:
                _booking_callback(c, tg, chat_id, msg.get('message_id'), data)
            return
        msg = update.get('message')
        if not msg or (msg.get('chat') or {}).get('type') != 'private':
            return
        text = (msg.get('text') or '').strip()
        _dispatch(c, tg, msg['chat']['id'], text, (msg.get('from') or {}).get('first_name', ''), msg.get('message_id'), public_url)


def _dispatch(c, tg, chat_id, text, first_name, message_id, public_url):
    c.execute('''INSERT INTO telegram_chats(chat_id, first_name) VALUES (%s,%s)
        ON CONFLICT (chat_id) DO UPDATE SET first_name=EXCLUDED.first_name, updated_at=now()''', (chat_id, first_name[:100]))
    chat = c.execute('SELECT * FROM telegram_chats WHERE chat_id=%s', (chat_id,)).fetchone()
    user = linked_user(c, chat)
    if chat['user_id'] and not user:
        c.execute("UPDATE telegram_chats SET user_id=NULL, cred_version=NULL, state='idle' WHERE chat_id=%s", (chat_id,))
        tg.send(chat_id, 'Доступ изменился (например, сброшен пароль). Войдите заново: /start', NO_MENU)
        return
    command = text.split('@')[0].split()[0].lower() if text.startswith('/') else ''

    if command == '/cancel':
        set_state(c, chat_id, 'idle')
        tg.send(chat_id, 'Отменено.', menu_for(user) if user else NO_MENU)
        return
    if command in ('/logout',) or text == BTN_LOGOUT:
        c.execute("UPDATE telegram_chats SET user_id=NULL, cred_version=NULL, state='idle' WHERE chat_id=%s", (chat_id,))
        tg.send(chat_id, 'Вы вышли. Чтобы войти снова, отправьте /start', NO_MENU)
        return

    if not user:
        return _login_flow(c, tg, chat, text, command, message_id)

    if command == '/start':
        name = user['full_name'] or first_name
        tg.send(chat_id, f'Здравствуйте, {e(name)}! 👋\n\n' + (HELP_STAFF if user['role'] != 'client' else HELP_CLIENT), menu_for(user))
        return
    if command == '/help' or text == BTN_HELP:
        tg.send(chat_id, HELP_STAFF if user['role'] != 'client' else HELP_CLIENT, menu_for(user))
        return
    if user['role'] == 'client':
        return _client_action(c, tg, chat_id, user, text, command, public_url)
    return _staff_action(c, tg, chat_id, user, text, command)


def _login_flow(c, tg, chat, text, command, message_id):
    chat_id = chat['chat_id']
    if command in ('/start', '/login') or chat['state'] not in ('await_login', 'await_password'):
        set_state(c, chat_id, 'await_login')
        tg.send(chat_id, 'Здравствуйте! Это бот детского центра <b>Kinder Spa</b> 🩵\n\n'
                         'Чтобы войти, отправьте <b>логин</b>, который вам выдали на ресепшене.\n'
                         'Отменить: /cancel', NO_MENU)
        return
    if chat['state'] == 'await_login':
        try:
            login = sec.normalize_login(text)
        except ValueError:
            tg.send(chat_id, 'Логин состоит из латинских букв и цифр, например <code>kid12</code>. Попробуйте ещё раз.')
            return
        set_state(c, chat_id, 'await_password', {'login': login})
        tg.send(chat_id, 'Теперь отправьте <b>пароль</b>. Сообщение с паролем я сразу удалю.')
        return
    # await_password
    login = (chat['state_data'] or {}).get('login')
    if message_id:
        try:
            tg.call('deleteMessage', chat_id=chat_id, message_id=message_id)
        except TelegramError:
            pass
    scopes = ['l:' + str(login), f'tg:{chat_id}']
    with c.transaction():
        counts = {r['scope']: r['n'] for r in c.execute('''SELECT scope, count(*) AS n FROM login_attempts
            WHERE scope = ANY(%s) AND at > now() - make_interval(mins => %s) GROUP BY scope''',
                                                         (scopes, sec.THROTTLE_WINDOW_MIN)).fetchall()}
        if max(counts.values(), default=0) >= sec.THROTTLE_MAX:
            set_state(c, chat_id, 'idle')
            tg.send(chat_id, 'Слишком много попыток. Подождите 15 минут и отправьте /start')
            return
        user = c.execute('SELECT id, role, salt, verifier, cred_version, enabled, full_name FROM users WHERE login=%s',
                         (login,)).fetchone()
        ok = bool(user) and user['enabled'] and sec.verify_password(text, user['salt'], user['verifier'])
        if not user:
            sec.verify_password(text, *sec._DUMMY)
        if not ok:
            for s in scopes:
                c.execute('INSERT INTO login_attempts(scope) VALUES (%s)', (s,))
            set_state(c, chat_id, 'await_login')
            tg.send(chat_id, 'Неверный логин или пароль. Отправьте логин ещё раз или /cancel')
            return
        if user['role'] == 'client' and not c.execute('SELECT 1 FROM clients WHERE user_id=%s AND NOT archived', (user['id'],)).fetchone():
            set_state(c, chat_id, 'idle')
            tg.send(chat_id, 'Доступ отключён. Обратитесь на ресепшен.')
            return
        c.execute('''UPDATE telegram_chats SET user_id=%s, cred_version=%s, state='idle', state_data='{}'::jsonb,
            linked_at=now(), updated_at=now() WHERE chat_id=%s''', (user['id'], user['cred_version'], chat_id))
        DbCtx(c, {'id': user['id']}).audit('telegram_link', 'user', user['id'], chat_id=chat_id)
    staff = user['role'] != 'client'
    tg.send(chat_id, f"Готово, {e(user['full_name'] or '')}! ✅\n\n" + (HELP_STAFF if staff else HELP_CLIENT),
            staff_menu() if staff else CLIENT_MENU)


def _client_action(c, tg, chat_id, user, text, command, public_url):
    from . import app as A
    client = c.execute('SELECT id, full_name FROM clients WHERE user_id=%s AND NOT archived', (user['id'],)).fetchone()
    if not client:
        tg.send(chat_id, 'Доступ отключён. Обратитесь на ресепшен.', NO_MENU)
        return
    x = DbCtx(c, user)
    if command == '/qr' or text == BTN_QR:
        token = sec.new_token()
        with c.transaction():
            c.execute('UPDATE qr_tokens SET expires_at=least(expires_at, now()) WHERE client_id=%s AND used_at IS NULL', (client['id'],))
            c.execute('INSERT INTO qr_tokens(token_hash, client_id, expires_at) VALUES (%s,%s,%s)',
                      (sec.token_hash(token), client['id'], A.now() + timedelta(seconds=sec.QR_SECONDS)))
        tg.send_photo_bytes(chat_id, qr_png(A.QR_PREFIX + token),
                            caption='Покажите этот QR-код на ресепшене.\nДействует <b>2 минуты</b> и только один раз.',
                            reply_markup={'inline_keyboard': [[{'text': '🔄 Новый код', 'callback_data': 'qr'}]]})
        return
    if command == '/book' or text == BTN_BOOK:
        return _book_start(c, tg, chat_id, None, x, client['id'])
    if command == '/bookings' or text == BTN_MY_BOOKINGS:
        return _my_bookings(c, tg, chat_id, x, client['id'])
    if command == '/subs' or text == BTN_SUBS:
        subs = [s for s in A.subscriptions_for(x, 's.client_id=%s', (client['id'],), limit=20)
                if s['state'] in ('active', 'frozen', 'not_started', 'used_up') or
                (s['state'] == 'expired' and (A.today() - s['ends_on']).days <= 30)]
        if not subs:
            tg.send(chat_id, 'Активных абонементов нет. Оформить можно на ресепшене.', CLIENT_MENU)
            return
        blocks = []
        for s in subs:
            who = f" ({e(s['child_name'])})" if s['child_name'] else ''
            extra = f"\nЗаморожен с {d(s['frozen_since'])}" if s['frozen_since'] else ''
            debt = f"\n💳 К оплате: {A.fmt_sum(s['debt'])}" if s.get('debt') else ''
            blocks.append(f"🎫 <b>{e(s['name'])}</b>{who}\n{items_text(s['items'])}\n"
                          f"Действует до {d(s['ends_on'])} · {STATE_NAMES.get(s['state'], s['state'])}{extra}{debt}")
        tg.send(chat_id, '\n\n'.join(blocks), CLIENT_MENU)
        return
    if command == '/visits' or text == BTN_VISITS:
        rows = A.visits_query(x, 'sub.client_id=%s', (client['id'],), limit=10)
        if not rows:
            tg.send(chat_id, 'Посещений пока нет.', CLIENT_MENU)
            return
        lines = ['🕘 <b>Последние посещения</b>']
        for v in rows:
            at = v['visited_at'].astimezone(A.ZONE).strftime('%d.%m %H:%M')
            who = f" ({e(v['child_name'])})" if v['child_name'] else ''
            line = f"{at} — {e(v['service_name'])}{who}"
            lines.append(f'<s>{line}</s> отменено' if v['cancelled_at'] else line)
        tg.send(chat_id, '\n'.join(lines), CLIENT_MENU)
        return
    if command == '/services' or text == BTN_SERVICES:
        services = A.services_list(x)
        for s in services:
            spec = ', '.join(p['full_name'] for p in s['specialists'])
            caption = (f"<b>{e(s['name_ru'])}</b> · {s['duration_min']} мин\n{e(s['description_ru'])}"
                       + (f"\nСпециалисты: {e(spec)}" if spec else ''))[:1000]
            if s['photos'] and public_url:
                try:
                    tg.call('sendPhoto', chat_id=chat_id, photo=f"{public_url}/api/photos/{s['photos'][0]}",
                            caption=caption, parse_mode='HTML')
                    continue
                except TelegramError:
                    pass
            tg.send(chat_id, caption)
        tg.send(chat_id, 'Записаться и оформить абонемент можно на ресепшене.', CLIENT_MENU)
        return
    tg.send(chat_id, 'Выберите действие в меню ниже 👇', CLIENT_MENU)


def _staff_action(c, tg, chat_id, user, text, command):
    from . import app as A
    x = DbCtx(c, user)
    if command == '/today' or text == BTN_TODAY:
        tg.send(chat_id, staff_summary(x, A.today()), staff_menu())
        return
    if command == '/schedule' or text == BTN_SCHEDULE:
        tg.send(chat_id, _staff_slots(x, A.today()), staff_menu())
        return
    if command == '/ending' or text == BTN_ENDING:
        t = A.today()
        subs = A.subscriptions_for(x, "s.status='active' AND s.ends_on BETWEEN %s AND %s", (t, t + timedelta(days=7)), limit=30)
        if not subs:
            tg.send(chat_id, 'В ближайшие 7 дней абонементы не заканчиваются.', staff_menu())
            return
        lines = ['⏳ <b>Заканчиваются за 7 дней</b>']
        lines += [f"{d(s['ends_on'])} — {e(s['client_name'])}: {e(s['name'])} ({items_text(s['items'])})" for s in subs]
        tg.send(chat_id, '\n'.join(lines), staff_menu())
        return
    tg.send(chat_id, 'Выберите действие в меню ниже 👇', staff_menu())


BOOKING_ERRORS = {
    'slot_full': 'На это время мест больше нет. Выберите другое.', 'slot_in_past': 'Это время уже прошло.',
    'slot_cancelled': 'Занятие отменено.', 'slot_not_found': 'Занятие не найдено.',
    'already_booked': 'Вы уже записаны на это время.', 'all_visits_reserved': 'Все посещения абонемента уже распределены по записям.',
    'no_subscription_for_booking': 'Нет активного абонемента на эту услугу и дату.', 'choose_child': 'Выберите ребёнка.',
    'booking_not_active': 'Эта запись уже не активна.', 'session_started': 'Занятие уже началось, отменить нельзя.',
    'client_archived': 'Доступ отключён.', 'child_not_of_client': 'Ребёнок не найден.',
}


def _edit(tg, chat_id, message_id, text, markup=None):
    if message_id:
        try:
            tg.call('editMessageText', chat_id=chat_id, message_id=message_id, text=text, parse_mode='HTML', reply_markup=markup)
            return
        except TelegramError:
            pass
    tg.send(chat_id, text, markup)


def _staff_slots(x, t):
    from . import schedule as S
    slots = x.all(f'''SELECT {S.SLOT_COLS} FROM {S.SLOT_FROM}
        WHERE sl.cancelled_at IS NULL AND (sl.starts_at AT TIME ZONE 'Asia/Tashkent')::date = %s ORDER BY sl.starts_at''', (t,))
    if not slots:
        return 'На сегодня занятий в расписании нет.'
    books = S.bookings_query(x, "b.slot_id = ANY(%s) AND b.status IN ('booked','attended','no_show')", ([s['id'] for s in slots],))
    marks = {'booked': '⏳', 'attended': '✅', 'no_show': '❌'}
    lines = [f'🗓 <b>Расписание на {d(t)}</b>']
    for s in slots:
        spec = f" · {e(s['specialist_name'])}" if s['specialist_name'] else ''
        lines.append(f"\n<b>{S.local(s['starts_at']).strftime('%H:%M')} {e(s['service_name'])}</b>{spec} — {s['booked']}/{s['capacity']}")
        for b in [b for b in books if b['slot_id'] == s['id']]:
            who = e(b['client_name']) + (f" ({e(b['child_name'])})" if b['child_name'] else '')
            lines.append(f"{marks[b['status']]} {who}")
    return '\n'.join(lines)[:4000]


def _book_start(c, tg, chat_id, message_id, x, client_id):
    from . import schedule as S
    slots = S.available_slots(x, client_id)
    services = {}
    for s in slots:
        services.setdefault(s['service_id'], s['service_name'])
    if not services:
        _edit(tg, chat_id, message_id, 'Свободного времени по вашим абонементам пока нет. Уточните на ресепшене.')
        return
    kb = [[{'text': name, 'callback_data': f'bs:{sid}'}] for sid, name in services.items()]
    _edit(tg, chat_id, message_id, '📅 <b>Запись</b>\nВыберите услугу:', {'inline_keyboard': kb})


def _my_bookings(c, tg, chat_id, x, client_id):
    from . import schedule as S
    rows = S.bookings_query(x, "b.client_id=%s AND b.status='booked' AND sl.starts_at > now()", (client_id,))
    if not rows:
        tg.send(chat_id, 'Активных записей нет. Записаться: ' + BTN_BOOK, CLIENT_MENU)
        return
    for b in rows[:10]:
        who = f" ({e(b['child_name'])})" if b['child_name'] else ''
        spec = f"\nСпециалист: {e(b['specialist_name'])}" if b['specialist_name'] else ''
        tg.send(chat_id, f"🗓 <b>{e(b['service_name'])}</b>{who}\n{S.when(b['starts_at'])}{spec}",
                {'inline_keyboard': [[{'text': 'Отменить запись', 'callback_data': f"bc:{b['id']}"}]]})


def _booking_callback(c, tg, chat_id, message_id, data):
    from . import app as A
    from . import schedule as S
    chat = c.execute('SELECT * FROM telegram_chats WHERE chat_id=%s', (chat_id,)).fetchone()
    user = linked_user(c, chat)
    if not user or user['role'] != 'client':
        tg.send(chat_id, 'Войдите в бота: /start')
        return
    client = c.execute('SELECT id FROM clients WHERE user_id=%s AND NOT archived', (user['id'],)).fetchone()
    if not client:
        return
    x = DbCtx(c, user)
    kind, _, rest = data.partition(':')
    try:
        if kind == 'bs':
            sid = int(rest)
            days = {}
            for s in S.available_slots(x, client['id'], sid):
                dd = S.local(s['starts_at']).date()
                days[dd] = days.get(dd, 0) + 1
            kb = [[{'text': f"{S.WEEKDAYS[dd.weekday()]} {dd.strftime('%d.%m')} · {n} врем.", 'callback_data': f"bd:{sid}:{dd.strftime('%Y%m%d')}"}]
                  for dd, n in list(days.items())[:10]]
            kb.append([{'text': '← Назад', 'callback_data': 'bb:'}])
            _edit(tg, chat_id, message_id, 'Выберите день:', {'inline_keyboard': kb})
        elif kind == 'bb':
            _book_start(c, tg, chat_id, message_id, x, client['id'])
        elif kind == 'bd':
            sid, ymd = rest.split(':')
            from datetime import datetime as _dt
            target = _dt.strptime(ymd, '%Y%m%d').date()
            slots = [s for s in S.available_slots(x, client['id'], int(sid)) if S.local(s['starts_at']).date() == target]
            kb = []
            for s in slots[:20]:
                spec = f" · {s['specialist_name']}" if s['specialist_name'] else ''
                kb.append([{'text': f"{S.local(s['starts_at']).strftime('%H:%M')}{spec} · мест: {s['capacity'] - s['booked']}",
                            'callback_data': f"bt:{s['id']}"}])
            kb.append([{'text': '← Назад', 'callback_data': f'bs:{sid}'}])
            _edit(tg, chat_id, message_id, f"Время на {d(target)}:", {'inline_keyboard': kb})
        elif kind in ('bt', 'bk'):
            parts = rest.split(':')
            slot_id = int(parts[0])
            child_id = int(parts[1]) if len(parts) > 1 else None
            kids = c.execute('SELECT id, full_name FROM children WHERE client_id=%s AND NOT archived ORDER BY id', (client['id'],)).fetchall()
            try:
                with c.transaction():
                    bid, sl = S.create_booking(x, slot_id, client['id'], child_id)
            except A.ApiError as err:
                if err.code == 'choose_child' and kids:
                    kb = [[{'text': k['full_name'], 'callback_data': f"bk:{slot_id}:{k['id']}"}] for k in kids]
                    _edit(tg, chat_id, message_id, 'Кого записываем?', {'inline_keyboard': kb})
                    return
                raise
            forfeit = c.execute('SELECT late_cancel_forfeit FROM services WHERE id=%s', (sl['service_id'],)).fetchone()['late_cancel_forfeit']
            cutoff = S.late_cutoff(sl['starts_at']).astimezone(A.ZONE)
            note = f"\nБесплатная отмена до {cutoff.strftime('%H:%M %d.%m')}." if forfeit else ''
            spec = f" · {e(sl['specialist_name'])}" if sl['specialist_name'] else ''
            _edit(tg, chat_id, message_id, f"✅ Вы записаны: <b>{e(sl['service_name'])}</b>\n{S.when(sl['starts_at'])}{spec}{note}\n"
                                           f"Накануне пришлю напоминание. Отменить: {BTN_MY_BOOKINGS}")
        elif kind in ('bc', 'bcy'):
            bid = int(rest)
            if not c.execute('SELECT 1 FROM bookings WHERE id=%s AND client_id=%s', (bid, client['id'])).fetchone():
                return
            try:
                with c.transaction():
                    res = S.cancel_booking(x, bid, by_staff=False, confirm_late=(kind == 'bcy'))
            except A.ApiError as err:
                if err.code == 'late_cancel_confirm':
                    _edit(tg, chat_id, message_id, '⚠️ Бесплатная отмена уже недоступна (после 19:00 накануне). '
                                                   'Если отменить, посещение будет списано. Отменить всё равно?',
                          {'inline_keyboard': [[{'text': 'Да, отменить', 'callback_data': f'bcy:{bid}'},
                                                {'text': 'Нет, приду', 'callback_data': 'noop'}]]})
                    return
                raise
            _edit(tg, chat_id, message_id, 'Запись отменена.' + (' Посещение списано по правилам центра.' if res['forfeited'] else ' Посещение не списано.'))
        elif kind == 'noop':
            _edit(tg, chat_id, message_id, 'Хорошо, запись сохранена. Ждём вас!')
    except A.ApiError as err:
        tg.send(chat_id, BOOKING_ERRORS.get(err.code, 'Не получилось. Попробуйте ещё раз или обратитесь на ресепшен.'))
    except (ValueError, IndexError):
        pass


COMMANDS = [{'command': 'start', 'description': 'Начать / меню'}, {'command': 'qr', 'description': 'QR-код для ресепшена'},
            {'command': 'book', 'description': 'Записаться'}, {'command': 'bookings', 'description': 'Мои записи'},
            {'command': 'subs', 'description': 'Мои абонементы'}, {'command': 'visits', 'description': 'История посещений'},
            {'command': 'services', 'description': 'Услуги'}, {'command': 'logout', 'description': 'Выйти'}]


def setup_webhook(tg, public_url):
    url = public_url.rstrip('/') + '/telegram/webhook'
    tg.call('setWebhook', url=url, secret_token=webhook_secret(tg.token),
            allowed_updates=['message', 'callback_query'], max_connections=10)
    tg.call('setMyCommands', commands=COMMANDS)
    tg.call('setMyDescription', description='Бот детского центра Kinder Spa: QR-код для входа, абонементы, посещения и напоминания.')
    return url
