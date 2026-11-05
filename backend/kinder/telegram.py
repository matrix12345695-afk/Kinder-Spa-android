"""Kinder Spa Telegram bot: webhook mode inside the web service (no separate worker).

Parents (RU/UZ) log in with the login/password issued at reception and get their QR
code, bookings, subscriptions, visits and the catalogue. Staff (RU) get a QR scanner
Mini App, schedule, a "today" summary and a morning digest. Notifications go through
telegram_outbox (written inside the business transaction, rendered in each chat's
language) and are sent after commit or by the daily cron call.
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

from . import i18n
from . import security as sec
from .i18n import t
from .qr import qr_png

log = logging.getLogger('kinder.telegram')

BTN_TODAY, BTN_ENDING, BTN_SCHEDULE, BTN_HELP, BTN_LOGOUT = '📊 Сегодня', '⏳ Заканчиваются', '🗓 Расписание', '❓ Помощь', '🚪 Выйти'
BTN_SCAN = '📷 Сканировать QR'
# Russian labels kept as module constants for staff code and tests.
BTN_QR, BTN_SUBS, BTN_VISITS, BTN_SERVICES = (i18n.T[k]['ru'] for k in ('btn_qr', 'btn_subs', 'btn_visits', 'btn_services'))
BTN_BOOK, BTN_MY_BOOKINGS = i18n.T['btn_book']['ru'], i18n.T['btn_my_bookings']['ru']
NO_MENU = {'remove_keyboard': True}
PUBLIC_URL = ''  # set by the app at startup
e = html.escape


def client_menu(lang):
    b = lambda k: {'text': t(lang, k)}
    return {'keyboard': [[b('btn_qr')], [b('btn_book'), b('btn_my_bookings')], [b('btn_subs'), b('btn_visits')],
                         [b('btn_services'), b('btn_help')], [b('btn_lang'), b('btn_logout')]],
            'resize_keyboard': True, 'is_persistent': True}


CLIENT_MENU = client_menu('ru')


def staff_menu():
    rows = [[{'text': BTN_TODAY}, {'text': BTN_SCHEDULE}], [{'text': BTN_ENDING}, {'text': BTN_HELP}], [{'text': BTN_LOGOUT}]]
    if PUBLIC_URL.startswith('https://'):
        rows.insert(0, [{'text': BTN_SCAN, 'web_app': {'url': PUBLIC_URL + '/tg/scan'}}])
    return {'keyboard': rows, 'resize_keyboard': True, 'is_persistent': True}


LANG_KB = {'inline_keyboard': [[{'text': '🇷🇺 Русский', 'callback_data': 'lang:ru'}, {'text': "🇺🇿 O'zbekcha", 'callback_data': 'lang:uz'}]]}


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


# ------------------------------------------------------------------ helpers

class DbCtx:
    """Minimal stand-in for app.Ctx so the app's query helpers can be reused."""
    def __init__(self, c, user=None):
        self.c, self.user = c, user

    def one(self, sql, args=()):
        return self.c.execute(sql, args).fetchone()

    def all(self, sql, args=()):
        return self.c.execute(sql, args).fetchall()

    def notify_client(self, client_id, key, **params):
        enqueue_for_client(self.c, client_id, key, **params)

    def audit(self, action, entity, entity_id=None, **details):
        self.c.execute('INSERT INTO audit_log(actor_id, action, entity, entity_id, details) VALUES (%s,%s,%s,%s,%s::jsonb)',
                       (self.user['id'] if self.user else None, action, entity, entity_id,
                        json.dumps(details, default=str, ensure_ascii=False)))


def d(value):
    return value.strftime('%d.%m.%Y') if value else '—'


def client_chats(c, client_id):
    return c.execute('''SELECT tc.chat_id, tc.lang FROM telegram_chats tc JOIN users u ON u.id = tc.user_id
        JOIN clients cl ON cl.user_id = u.id
        WHERE cl.id = %s AND u.enabled AND tc.cred_version = u.cred_version''', (client_id,)).fetchall()


def staff_chats(c):
    rows = c.execute('''SELECT tc.chat_id FROM telegram_chats tc JOIN users u ON u.id = tc.user_id
        WHERE u.role IN ('admin','superadmin') AND u.enabled AND tc.cred_version = u.cred_version''').fetchall()
    return [r['chat_id'] for r in rows]


def enqueue(c, chat_ids, text):
    for chat_id in chat_ids:
        c.execute('INSERT INTO telegram_outbox(chat_id, text) VALUES (%s,%s)', (chat_id, text))
    return len(chat_ids)


def enqueue_for_client(c, client_id, key, **params):
    """Queue a parent notification rendered in each linked chat's language. Called inside business transactions."""
    chats = client_chats(c, client_id)
    for ch in chats:
        c.execute('INSERT INTO telegram_outbox(chat_id, text) VALUES (%s,%s)', (ch['chat_id'], t(ch['lang'], key, **params)))
    return len(chats)


def items_text(items, lang='ru'):
    return ', '.join(t(lang, 'item', name=i18n.name(i['name_ru'], i.get('name_uz')), rem=i['remaining'], quota=i['quota'])
                     for i in items)


def items_both(items):
    return {lang: items_text(items, lang) for lang in i18n.LANGS}


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
    from . import schedule as S
    today = A.today()
    out = {'reminders': 0, 'digests': 0}
    with db.conn() as c, c.transaction():
        x = DbCtx(c)
        ending = A.subscriptions_for(x, "s.status='active' AND s.ends_on BETWEEN %s AND %s", (today, today + timedelta(days=3)))
        for s in ending:
            if s['state'] != 'active':
                continue
            if c.execute("INSERT INTO reminders_sent VALUES (%s,'ends_soon',%s) ON CONFLICT DO NOTHING RETURNING 1",
                         (s['id'], today)).fetchone():
                days = (s['ends_on'] - today).days
                when = i18n.both('today') if days == 0 else (i18n.both('tomorrow') if days == 1 else
                                                              i18n.both('in_days', n=days, date=d(s['ends_on'])))
                out['reminders'] += enqueue_for_client(c, s['client_id'], 'n_ends_soon', name=e(s['name']), when=when,
                                                       items=items_both(s['items']))
        expired = A.subscriptions_for(x, "s.status='active' AND s.ends_on = %s", (today - timedelta(days=1),))
        for s in expired:
            left = sum(i['remaining'] for i in s['items'])
            if left and c.execute("INSERT INTO reminders_sent VALUES (%s,'expired',%s) ON CONFLICT DO NOTHING RETURNING 1",
                                  (s['id'], today)).fetchone():
                out['reminders'] += enqueue_for_client(c, s['client_id'], 'n_expired', name=e(s['name']), left=left)
        for b in S.bookings_query(x, "b.status='booked' AND (sl.starts_at AT TIME ZONE 'Asia/Tashkent')::date = %s",
                                  (today + timedelta(days=1),)):
            if c.execute("INSERT INTO reminders_sent VALUES (%s,%s,%s) ON CONFLICT DO NOTHING RETURNING 1",
                         (b['subscription_id'], f"booking:{b['id']}", today)).fetchone():
                who = f" ({e(b['child_name'])})" if b['child_name'] else ''
                out['reminders'] += enqueue_for_client(
                    c, b['client_id'], 'n_booking_reminder', service=i18n.name(e(b['service_name']), e(b.get('service_name_uz') or '')),
                    who=who, time=S.local(b['starts_at']).strftime('%H:%M'), mine={k: v for k, v in i18n.T['btn_my_bookings'].items()})
        if c.execute("INSERT INTO job_runs VALUES ('staff_digest', %s) ON CONFLICT DO NOTHING RETURNING 1", (today,)).fetchone():
            out['digests'] = enqueue(c, staff_chats(c), staff_summary(x, today - timedelta(days=1), title='Сводка за вчера'))
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


def is_staff(user):
    return user['role'] in ('admin', 'superadmin')


def menu_for(user, lang='ru'):
    return staff_menu() if is_staff(user) else client_menu(lang)


def help_text(user, lang):
    if user and is_staff(user):
        return HELP_STAFF
    b = {k: i18n.T['btn_' + k][lang] for k in ('qr', 'book', 'subs', 'visits', 'services')}
    return t(lang, 'help', mine=i18n.T['btn_my_bookings'][lang], **b)


HELP_STAFF = ('Вы вошли как сотрудник Kinder Spa.\n\n'
              f'{BTN_SCAN} — наведите камеру на QR-код клиента и спишите посещение.\n'
              f'{BTN_TODAY} — посещения, касса и продажи за сегодня.\n'
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
            if not chat_id or not data:
                return
            first_name = (cq.get('from') or {}).get('first_name', '')
            if data.startswith('lang:'):
                return _set_lang(c, tg, chat_id, msg.get('message_id'), data[5:], first_name)
            if data == 'qr':
                return _dispatch(c, tg, chat_id, BTN_QR, first_name, None, public_url)
            return _booking_callback(c, tg, chat_id, msg.get('message_id'), data)
        msg = update.get('message')
        if not msg or (msg.get('chat') or {}).get('type') != 'private':
            return
        text = (msg.get('text') or '').strip()
        _dispatch(c, tg, msg['chat']['id'], text, (msg.get('from') or {}).get('first_name', ''), msg.get('message_id'), public_url)


def send_welcome(tg, chat_id, lang, caption, markup):
    """Branded banner with the greeting as caption; falls back to plain text."""
    if PUBLIC_URL.startswith('https://'):
        caption = caption + '\n\n' + t(lang, 'site', url=f'{PUBLIC_URL}/?lang={lang}')
        try:
            tg.call('sendPhoto', chat_id=chat_id, photo=f'{PUBLIC_URL}/assets/img/welcome-{i18n.norm(lang)}.png',
                    caption=caption[:1024], parse_mode='HTML', reply_markup=markup)
            return
        except TelegramError:
            pass
    tg.send(chat_id, caption, markup)


def _ensure_chat(c, chat_id, first_name):
    c.execute('''INSERT INTO telegram_chats(chat_id, first_name) VALUES (%s,%s)
        ON CONFLICT (chat_id) DO UPDATE SET first_name=EXCLUDED.first_name, updated_at=now()''', (chat_id, first_name[:100]))
    return c.execute('SELECT * FROM telegram_chats WHERE chat_id=%s', (chat_id,)).fetchone()


def _set_lang(c, tg, chat_id, message_id, lang, first_name):
    lang = i18n.norm(lang)
    chat = _ensure_chat(c, chat_id, first_name)
    c.execute('UPDATE telegram_chats SET lang=%s, lang_chosen=true WHERE chat_id=%s', (lang, chat_id))
    user = linked_user(c, chat)
    _edit(tg, chat_id, message_id, t(lang, 'lang_set'))
    if user:
        tg.send(chat_id, help_text(user, lang), menu_for(user, lang))
    else:
        set_state(c, chat_id, 'await_login')
        send_welcome(tg, chat_id, lang, t(lang, 'welcome'), NO_MENU)


def _dispatch(c, tg, chat_id, text, first_name, message_id, public_url):
    chat = _ensure_chat(c, chat_id, first_name)
    lang = chat['lang']
    user = linked_user(c, chat)
    if chat['user_id'] and not user:
        c.execute("UPDATE telegram_chats SET user_id=NULL, cred_version=NULL, state='idle' WHERE chat_id=%s", (chat_id,))
        tg.send(chat_id, t(lang, 'access_changed'), NO_MENU)
        return
    command = text.split('@')[0].split()[0].lower() if text.startswith('/') else ''
    button = i18n.button_key(text)

    if command == '/cancel':
        set_state(c, chat_id, 'idle')
        tg.send(chat_id, t(lang, 'cancelled'), menu_for(user, lang) if user else NO_MENU)
        return
    if command == '/lang' or button == 'btn_lang':
        tg.send(chat_id, t(lang, 'choose_lang'), LANG_KB)
        return
    if command == '/logout' or button == 'btn_logout' or text == BTN_LOGOUT:
        c.execute("UPDATE telegram_chats SET user_id=NULL, cred_version=NULL, state='idle' WHERE chat_id=%s", (chat_id,))
        tg.send(chat_id, t(lang, 'logged_out'), NO_MENU)
        return

    if not user:
        return _login_flow(c, tg, chat, text, command, message_id)

    if command == '/start':
        name = user['full_name'] or first_name
        if is_staff(user):
            tg.send(chat_id, f'Здравствуйте, {e(name)}! 👋\n\n' + HELP_STAFF, staff_menu())
        else:
            send_welcome(tg, chat_id, lang, t(lang, 'hello', name=e(name)) + '\n\n' + help_text(user, lang), client_menu(lang))
        return
    if command == '/help' or button == 'btn_help' or text == BTN_HELP:
        tg.send(chat_id, help_text(user, lang), menu_for(user, lang))
        return
    if is_staff(user):
        return _staff_action(c, tg, chat_id, user, text, command)
    return _client_action(c, tg, chat_id, user, button, command, public_url, lang)


def _login_flow(c, tg, chat, text, command, message_id):
    chat_id, lang = chat['chat_id'], chat['lang']
    if command in ('/start', '/login') or chat['state'] not in ('await_login', 'await_password'):
        if not chat['lang_chosen']:  # offer the language once; login continues in the default language meanwhile
            c.execute('UPDATE telegram_chats SET lang_chosen=true WHERE chat_id=%s', (chat_id,))
            tg.send(chat_id, t(lang, 'choose_lang'), LANG_KB)
        set_state(c, chat_id, 'await_login')
        send_welcome(tg, chat_id, lang, t(lang, 'welcome'), NO_MENU)
        return
    if chat['state'] == 'await_login':
        try:
            login = sec.normalize_login(text)
        except ValueError:
            tg.send(chat_id, t(lang, 'bad_login'))
            return
        set_state(c, chat_id, 'await_password', {'login': login})
        tg.send(chat_id, t(lang, 'ask_password'))
        return
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
            tg.send(chat_id, t(lang, 'too_many'))
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
            tg.send(chat_id, t(lang, 'wrong_creds'))
            return
        if user['role'] == 'client' and not c.execute('SELECT 1 FROM clients WHERE user_id=%s AND NOT archived', (user['id'],)).fetchone():
            set_state(c, chat_id, 'idle')
            tg.send(chat_id, t(lang, 'access_disabled'))
            return
        c.execute('''UPDATE telegram_chats SET user_id=%s, cred_version=%s, state='idle', state_data='{}'::jsonb,
            linked_at=now(), updated_at=now() WHERE chat_id=%s''', (user['id'], user['cred_version'], chat_id))
        DbCtx(c, {'id': user['id']}).audit('telegram_link', 'user', user['id'], chat_id=chat_id)
    if is_staff(user):
        tg.send(chat_id, f"Готово, {e(user['full_name'] or '')}! ✅\n\n" + HELP_STAFF, staff_menu())
    else:
        tg.send(chat_id, t(lang, 'logged_in', name=e(user['full_name'] or '')) + '\n\n' + help_text(user, lang), client_menu(lang))


def _client_action(c, tg, chat_id, user, button, command, public_url, lang):
    from . import app as A
    menu = client_menu(lang)
    client = c.execute('SELECT id, full_name FROM clients WHERE user_id=%s AND NOT archived', (user['id'],)).fetchone()
    if not client:
        tg.send(chat_id, t(lang, 'access_disabled'), NO_MENU)
        return
    x = DbCtx(c, user)
    if command == '/qr' or button == 'btn_qr':
        token = sec.new_token()
        with c.transaction():
            c.execute('UPDATE qr_tokens SET expires_at=least(expires_at, %s) WHERE client_id=%s AND used_at IS NULL', (A.now(), client['id']))
            c.execute('INSERT INTO qr_tokens(token_hash, client_id, expires_at) VALUES (%s,%s,%s)',
                      (sec.token_hash(token), client['id'], A.now() + timedelta(seconds=sec.QR_SECONDS)))
        tg.send_photo_bytes(chat_id, qr_png(A.QR_PREFIX + token), caption=t(lang, 'qr_caption'),
                            reply_markup={'inline_keyboard': [[{'text': t(lang, 'btn_new_code'), 'callback_data': 'qr'}]]})
        return
    if command == '/book' or button == 'btn_book':
        return _book_start(c, tg, chat_id, None, x, client['id'], lang)
    if command == '/bookings' or button == 'btn_my_bookings':
        return _my_bookings(c, tg, chat_id, x, client['id'], lang)
    if command == '/subs' or button == 'btn_subs':
        subs = [s for s in A.subscriptions_for(x, 's.client_id=%s', (client['id'],), limit=20)
                if s['state'] in ('active', 'frozen', 'not_started', 'used_up') or
                (s['state'] == 'expired' and (A.today() - s['ends_on']).days <= 30)]
        if not subs:
            tg.send(chat_id, t(lang, 'no_subs'), menu)
            return
        uz_names = {r['id']: r['name_uz'] for r in c.execute('SELECT id, name_uz FROM services').fetchall()}
        blocks = []
        for s in subs:
            for i in s['items']:
                i['name_uz'] = uz_names.get(i['service_id'])
            who = f" ({e(s['child_name'])})" if s['child_name'] else ''
            lines = [f"🎫 <b>{e(s['name'])}</b>{who}", items_text(s['items'], lang),
                     t(lang, 'sub_valid', date=d(s['ends_on']), state=i18n.STATES[lang].get(s['state'], s['state']))]
            if s['frozen_since']:
                lines.append(t(lang, 'sub_frozen_since', date=d(s['frozen_since'])))
            if s.get('debt'):
                lines.append(t(lang, 'sub_debt', sum=i18n.money(s['debt'])))
            blocks.append('\n'.join(lines))
        tg.send(chat_id, '\n\n'.join(blocks), menu)
        return
    if command == '/visits' or button == 'btn_visits':
        rows = A.visits_query(x, 'sub.client_id=%s', (client['id'],), limit=10)
        if not rows:
            tg.send(chat_id, t(lang, 'no_visits'), menu)
            return
        uz_names = {r['id']: r['name_uz'] for r in c.execute('SELECT id, name_uz FROM services').fetchall()}
        lines = [t(lang, 'visits_title')]
        for v in rows:
            at = v['visited_at'].astimezone(A.ZONE).strftime('%d.%m %H:%M')
            who = f" ({e(v['child_name'])})" if v['child_name'] else ''
            svc = (uz_names.get(v['service_id']) if lang == 'uz' else None) or v['service_name']
            line = f"{at} — {e(svc)}{who}"
            lines.append(f"<s>{line}</s> {t(lang, 'visit_cancelled_mark')}" if v['cancelled_at'] else line)
        tg.send(chat_id, '\n'.join(lines), menu)
        return
    if command == '/services' or button == 'btn_services':
        for s in A.services_list(x):
            name = (s['name_uz'] if lang == 'uz' else '') or s['name_ru']
            desc = (s['description_uz'] if lang == 'uz' else '') or s['description_ru']
            spec = ', '.join(p['full_name'] for p in s['specialists'])
            caption = (t(lang, 'service_card', name=e(name), min=s['duration_min'], desc=e(desc))
                       + ('\n' + t(lang, 'specialists', names=e(spec)) if spec else ''))[:1000]
            if s['photos'] and public_url:
                try:
                    tg.call('sendPhoto', chat_id=chat_id, photo=f"{public_url}/api/photos/{s['photos'][0]}",
                            caption=caption, parse_mode='HTML')
                    continue
                except TelegramError:
                    pass
            tg.send(chat_id, caption)
        tg.send(chat_id, t(lang, 'services_footer', book=t(lang, 'btn_book')), menu)
        return
    tg.send(chat_id, t(lang, 'choose_action'), menu)


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
        today = A.today()
        subs = A.subscriptions_for(x, "s.status='active' AND s.ends_on BETWEEN %s AND %s", (today, today + timedelta(days=7)), limit=30)
        if not subs:
            tg.send(chat_id, 'В ближайшие 7 дней абонементы не заканчиваются.', staff_menu())
            return
        lines = ['⏳ <b>Заканчиваются за 7 дней</b>']
        lines += [f"{d(s['ends_on'])} — {e(s['client_name'])}: {e(s['name'])} ({items_text(s['items'])})" for s in subs]
        tg.send(chat_id, '\n'.join(lines), staff_menu())
        return
    tg.send(chat_id, 'Выберите действие в меню ниже 👇', staff_menu())


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


def _svc_name(c, service_id, lang, fallback):
    if lang != 'uz':
        return fallback
    row = c.execute('SELECT name_uz FROM services WHERE id=%s', (service_id,)).fetchone()
    return (row and row['name_uz']) or fallback


def _book_start(c, tg, chat_id, message_id, x, client_id, lang):
    from . import schedule as S
    services = {}
    for s in S.available_slots(x, client_id):
        services.setdefault(s['service_id'], _svc_name(c, s['service_id'], lang, s['service_name']))
    if not services:
        _edit(tg, chat_id, message_id, t(lang, 'no_slots'))
        return
    kb = [[{'text': name, 'callback_data': f'bs:{sid}'}] for sid, name in services.items()]
    _edit(tg, chat_id, message_id, t(lang, 'book_title'), {'inline_keyboard': kb})


def _my_bookings(c, tg, chat_id, x, client_id, lang):
    from . import schedule as S
    rows = S.bookings_query(x, "b.client_id=%s AND b.status='booked' AND sl.starts_at > now()", (client_id,))
    if not rows:
        tg.send(chat_id, t(lang, 'no_bookings', book=t(lang, 'btn_book')), client_menu(lang))
        return
    for b in rows[:10]:
        who = f" ({e(b['child_name'])})" if b['child_name'] else ''
        spec = '\n' + t(lang, 'specialist', name=e(b['specialist_name'])) if b['specialist_name'] else ''
        when = i18n.resolve(i18n.when(S.local(b['starts_at'])), lang)
        tg.send(chat_id, f"🗓 <b>{e(_svc_name(c, b['service_id'], lang, b['service_name']))}</b>{who}\n{when}{spec}",
                {'inline_keyboard': [[{'text': t(lang, 'btn_cancel_booking'), 'callback_data': f"bc:{b['id']}"}]]})


def _booking_callback(c, tg, chat_id, message_id, data):
    from datetime import datetime as _dt
    from . import app as A
    from . import schedule as S
    chat = c.execute('SELECT * FROM telegram_chats WHERE chat_id=%s', (chat_id,)).fetchone()
    lang = chat['lang'] if chat else 'ru'
    user = linked_user(c, chat)
    if not user or user['role'] != 'client':
        tg.send(chat_id, t(lang, 'login_first'))
        return
    client = c.execute('SELECT id FROM clients WHERE user_id=%s AND NOT archived', (user['id'],)).fetchone()
    if not client:
        return
    x = DbCtx(c, user)
    kind, _, rest = data.partition(':')
    wd = i18n.WEEKDAYS[lang]
    try:
        if kind == 'bs':
            sid = int(rest)
            days = {}
            for s in S.available_slots(x, client['id'], sid):
                dd = S.local(s['starts_at']).date()
                days[dd] = days.get(dd, 0) + 1
            kb = [[{'text': t(lang, 'day_btn', wd=wd[dd.weekday()], date=dd.strftime('%d.%m'), n=n),
                    'callback_data': f"bd:{sid}:{dd.strftime('%Y%m%d')}"}] for dd, n in list(days.items())[:10]]
            kb.append([{'text': t(lang, 'btn_back'), 'callback_data': 'bb:'}])
            _edit(tg, chat_id, message_id, t(lang, 'choose_day'), {'inline_keyboard': kb})
        elif kind == 'bb':
            _book_start(c, tg, chat_id, message_id, x, client['id'], lang)
        elif kind == 'bd':
            sid, ymd = rest.split(':')
            target = _dt.strptime(ymd, '%Y%m%d').date()
            slots = [s for s in S.available_slots(x, client['id'], int(sid)) if S.local(s['starts_at']).date() == target]
            kb = [[{'text': t(lang, 'slot_btn', time=S.local(s['starts_at']).strftime('%H:%M'),
                              spec=f" · {s['specialist_name']}" if s['specialist_name'] else '', n=s['capacity'] - s['booked']),
                    'callback_data': f"bt:{s['id']}"}] for s in slots[:20]]
            kb.append([{'text': t(lang, 'btn_back'), 'callback_data': f'bs:{sid}'}])
            _edit(tg, chat_id, message_id, t(lang, 'times_title', date=d(target)), {'inline_keyboard': kb})
        elif kind in ('bt', 'bk'):
            parts = rest.split(':')
            slot_id = int(parts[0])
            child_id = int(parts[1]) if len(parts) > 1 else None
            try:
                with c.transaction():
                    bid, sl = S.create_booking(x, slot_id, client['id'], child_id)
            except A.ApiError as err:
                kids = c.execute('SELECT id, full_name FROM children WHERE client_id=%s AND NOT archived ORDER BY id', (client['id'],)).fetchall()
                if err.code == 'choose_child' and kids:
                    kb = [[{'text': k['full_name'], 'callback_data': f"bk:{slot_id}:{k['id']}"}] for k in kids]
                    _edit(tg, chat_id, message_id, t(lang, 'who'), {'inline_keyboard': kb})
                    return
                raise
            forfeit = c.execute('SELECT late_cancel_forfeit FROM services WHERE id=%s', (sl['service_id'],)).fetchone()['late_cancel_forfeit']
            cutoff = S.late_cutoff(sl['starts_at']).astimezone(A.ZONE)
            free = t(lang, 'free_cancel_until', time=cutoff.strftime('%H:%M %d.%m')) if forfeit else ''
            spec = f" · {e(sl['specialist_name'])}" if sl['specialist_name'] else ''
            _edit(tg, chat_id, message_id, t(lang, 'booked', service=e(_svc_name(c, sl['service_id'], lang, sl['service_name'])),
                                             when=i18n.when(S.local(sl['starts_at'])), spec=spec, free=free,
                                             mine=t(lang, 'btn_my_bookings')))
        elif kind in ('bc', 'bcy'):
            bid = int(rest)
            if not c.execute('SELECT 1 FROM bookings WHERE id=%s AND client_id=%s', (bid, client['id'])).fetchone():
                return
            try:
                with c.transaction():
                    res = S.cancel_booking(x, bid, by_staff=False, confirm_late=(kind == 'bcy'))
            except A.ApiError as err:
                if err.code == 'late_cancel_confirm':
                    _edit(tg, chat_id, message_id, t(lang, 'late_warn'),
                          {'inline_keyboard': [[{'text': t(lang, 'btn_yes_cancel'), 'callback_data': f'bcy:{bid}'},
                                                {'text': t(lang, 'btn_no_keep'), 'callback_data': 'noop'}]]})
                    return
                raise
            _edit(tg, chat_id, message_id, t(lang, 'booking_cancelled') + t(lang, 'forfeited' if res['forfeited'] else 'not_forfeited'))
        elif kind == 'noop':
            _edit(tg, chat_id, message_id, t(lang, 'booking_kept'))
    except A.ApiError as err:
        key = 'err_' + err.code
        tg.send(chat_id, t(lang, key) if key in i18n.T else t(lang, 'err_generic'))
    except (ValueError, IndexError):
        pass


COMMANDS = [{'command': 'start', 'description': 'Начать / меню'}, {'command': 'qr', 'description': 'QR-код для ресепшена'},
            {'command': 'book', 'description': 'Записаться'}, {'command': 'bookings', 'description': 'Мои записи'},
            {'command': 'subs', 'description': 'Мои абонементы'}, {'command': 'lang', 'description': 'Язык / Til'}, {'command': 'visits', 'description': 'История посещений'},
            {'command': 'services', 'description': 'Услуги'}, {'command': 'logout', 'description': 'Выйти'}]


def setup_webhook(tg, public_url):
    url = public_url.rstrip('/') + '/telegram/webhook'
    tg.call('setWebhook', url=url, secret_token=webhook_secret(tg.token),
            allowed_updates=['message', 'callback_query'], max_connections=10)
    tg.call('setMyCommands', commands=COMMANDS)
    desc = {'ru': ('Kinder Spa ❤️ детский массаж, гидромассаж и бассейн.\n\nЗапись на занятия, QR-код для входа, абонементы, '
                   'история посещений и напоминания — всё в одном боте. Логин и пароль выдают на ресепшене.',
                   'Запись, QR-код и абонементы Kinder Spa ❤️'),
            'uz': ("Kinder Spa ❤️ bolalar massaji, gidromassaj va basseyn.\n\nMashg'ulotlarga yozilish, kirish uchun QR-kod, "
                   'abonementlar, tashriflar tarixi va eslatmalar — barchasi bitta botda. Login va parol qabulxonada beriladi.',
                   'Kinder Spa: yozilish, QR-kod va abonementlar ❤️')}
    for code, (long_d, short_d) in desc.items():
        lang_code = None if code == 'ru' else code
        tg.call('setMyDescription', description=long_d, language_code=lang_code)
        tg.call('setMyShortDescription', short_description=short_d, language_code=lang_code)
    tg.call('setMyCommands', commands=[{'command': 'start', 'description': 'Boshlash / menyu'}, {'command': 'qr', 'description': 'Qabulxona uchun QR-kod'},
                                       {'command': 'book', 'description': 'Yozilish'}, {'command': 'bookings', 'description': 'Yozuvlarim'},
                                       {'command': 'subs', 'description': 'Abonementlarim'}, {'command': 'lang', 'description': 'Til / Язык'},
                                       {'command': 'logout', 'description': 'Chiqish'}], language_code='uz')
    return url
