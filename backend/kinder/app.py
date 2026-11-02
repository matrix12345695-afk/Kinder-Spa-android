"""Kinder Spa HTTP API and admin panel host (Starlette)."""
import base64
import hmac
import binascii
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import security as sec
from . import telegram as tgbot
from . import i18n
from .db import Database, sqlstate

log = logging.getLogger('kinder')
ZONE = ZoneInfo('Asia/Tashkent')
STATIC = Path(__file__).with_name('static')
QR_PREFIX = 'KSPA1:'
STAFF = ('admin', 'superadmin')
CLOCK = None  # tests may set a callable returning an aware datetime


def now():
    return CLOCK() if CLOCK else datetime.now(timezone.utc)


def today():
    return now().astimezone(ZONE).date()


# ---------------------------------------------------------------- plumbing

class ApiError(Exception):
    def __init__(self, status, code, detail=None):
        super().__init__(code)
        self.status, self.code, self.detail = status, code, detail


def _default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, 'f')
    if isinstance(value, (bytes, memoryview)):
        return None
    raise TypeError(type(value).__name__)


def json_response(data, status=200, headers=None, background=None):
    body = json.dumps(data, default=_default, ensure_ascii=False).encode('utf-8')
    return Response(body, status, headers=headers, media_type='application/json', background=background)


class Ctx:
    def __init__(self, request, body, user, conn):
        self.request, self.body, self.user, self.c = request, body, user, conn
        self.params = request.path_params
        self.query = request.query_params
        self.notify = False

    def notify_client(self, client_id, key, **params):
        """Queue a Telegram message (i18n key) to the parent's linked chats inside the current transaction."""
        if getattr(self.request.app.state, 'tg', None) and tgbot.enqueue_for_client(self.c, client_id, key, **params):
            self.notify = True

    def audit(self, action, entity, entity_id=None, **details):
        self.c.execute('INSERT INTO audit_log(actor_id, action, entity, entity_id, details) VALUES (%s,%s,%s,%s,%s::jsonb)',
                       (self.user['id'] if self.user else None, action, entity, entity_id,
                        json.dumps(details, default=_default, ensure_ascii=False)))

    def one(self, sql, args=()):
        return self.c.execute(sql, args).fetchone()

    def all(self, sql, args=()):
        return self.c.execute(sql, args).fetchall()


ROUTES = []


def api(path, methods=('GET',), roles=STAFF):
    """roles=None means public; otherwise the session user's role must be listed."""
    def wrap(fn):
        async def endpoint(request: Request):
            body = {}
            if request.method in ('POST', 'PUT', 'PATCH'):
                raw = await request.body()
                if len(raw) > 4 * 1024 * 1024:
                    return json_response({'error': 'payload_too_large'}, 413)
                if raw:
                    try:
                        body = json.loads(raw)
                    except ValueError:
                        return json_response({'error': 'invalid_json'}, 400)
                    if not isinstance(body, dict):
                        return json_response({'error': 'invalid_json'}, 400)
            token = request.headers.get('authorization', '')
            token = token[7:].strip() if token.lower().startswith('bearer ') else ''
            init_data = request.headers.get('x-telegram-init-data', '')

            def run():
                with request.app.state.db.conn() as c:
                    user = authenticate(c, token) if token else None
                    if not user and init_data and request.app.state.tg:
                        tg_user = tgbot.validate_init_data(init_data, request.app.state.tg.token)
                        user = tgbot.user_for_tg_id(c, tg_user['id']) if tg_user else None
                    if roles is not None:
                        if not user:
                            raise ApiError(401, 'unauthorized')
                        if user['role'] not in roles:
                            raise ApiError(403, 'forbidden')
                    ctx = Ctx(request, body, user, c)
                    return fn(ctx), ctx.notify
            try:
                result, notify = await run_in_threadpool(run)
            except ApiError as e:
                payload = {'error': e.code}
                if e.detail:
                    payload['detail'] = e.detail
                return json_response(payload, e.status)
            except Exception as e:  # map database constraint errors
                state = sqlstate(e)
                if state == '23505':
                    return json_response({'error': 'already_exists'}, 409)
                if state in ('23503', '23514', '23502', '22P02', '22007', '22008', '22003'):
                    return json_response({'error': 'invalid_data'}, 400)
                if state in ('55P03', '40001', '40P01'):
                    return json_response({'error': 'busy_retry'}, 503)
                log.exception('unhandled error on %s %s', request.method, request.url.path)
                return json_response({'error': 'internal_error'}, 500)
            if isinstance(result, Response):
                return result
            app_state = request.app.state
            background = BackgroundTask(tgbot.flush_outbox, app_state.db, app_state.tg) if notify and app_state.tg else None
            return json_response(result, background=background)
        ROUTES.append(Route('/api' + path, endpoint, methods=list(methods)))
        return fn
    return wrap


# ---------------------------------------------------------------- validation helpers

def text(body, key, *, required=False, max_len=2000, default=''):
    value = body.get(key, None)
    if value is None:
        if required:
            raise ApiError(400, 'field_required', key)
        return default
    if not isinstance(value, str):
        raise ApiError(400, 'invalid_field', key)
    value = value.strip()
    if required and not value:
        raise ApiError(400, 'field_required', key)
    if len(value) > max_len:
        raise ApiError(400, 'field_too_long', key)
    return value


def integer(value, key, *, lo=None, hi=None, required=True):
    if value is None and not required:
        return None
    if isinstance(value, str) and re.fullmatch(r'-?\d{1,12}', value.strip()):
        value = int(value)
    if type(value) is not int or (lo is not None and value < lo) or (hi is not None and value > hi):
        raise ApiError(400, 'invalid_field', key)
    return value


def ident(value, key='id', required=True):
    return integer(value, key, lo=1, required=required)


def day(value, key, required=False):
    if value in (None, ''):
        if required:
            raise ApiError(400, 'field_required', key)
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ApiError(400, 'invalid_field', key)


def money(value, key):
    if value in (None, ''):
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise ApiError(400, 'invalid_field', key)
    if amount < 0 or amount > Decimal('999999999999') or amount != amount.quantize(Decimal('0.01')):
        raise ApiError(400, 'invalid_field', key)
    return amount


def boolean(body, key):
    value = body.get(key)
    if value is not None and not isinstance(value, bool):
        raise ApiError(400, 'invalid_field', key)
    return value


def reason(body):
    value = text(body, 'reason', required=True, max_len=500)
    if len(value) < 3:
        raise ApiError(400, 'reason_required')
    return value


def found(row, what='not_found'):
    if not row:
        raise ApiError(404, what)
    return row


# ---------------------------------------------------------------- auth

def authenticate(c, token):
    row = c.execute('''SELECT u.id, u.role, u.login, u.full_name FROM sessions s JOIN users u ON u.id = s.user_id
        WHERE s.token_hash=%s AND NOT s.revoked AND s.expires_at > now() AND u.enabled
          AND s.cred_version = u.cred_version''', (sec.token_hash(token),)).fetchone()
    return row


def client_ip(request):
    forwarded = request.headers.get('x-forwarded-for', '')
    return (forwarded.split(',')[0].strip() if forwarded else (request.client.host if request.client else '')) or '-'


@api('/login', ('POST',), roles=None)
def login(x):
    password = x.body.get('password')
    try:
        name = sec.normalize_login(x.body.get('login'))
    except ValueError:
        raise ApiError(401, 'invalid_credentials')
    if not isinstance(password, str) or not password or len(password) > 128:
        raise ApiError(401, 'invalid_credentials')
    scopes = ('l:' + name, 'ip:' + client_ip(x.request))
    with x.c.transaction():
        counts = x.all('''SELECT scope, count(*) AS n FROM login_attempts
            WHERE scope = ANY(%s) AND at > now() - make_interval(mins => %s) GROUP BY scope''',
                       (list(scopes), sec.THROTTLE_WINDOW_MIN))
        counts = {r['scope']: r['n'] for r in counts}
        if counts.get(scopes[0], 0) >= sec.THROTTLE_MAX or counts.get(scopes[1], 0) >= sec.THROTTLE_MAX * 5:
            raise ApiError(429, 'too_many_attempts')
        user = x.one('SELECT id, role, salt, verifier, cred_version, enabled, full_name FROM users WHERE login=%s', (name,))
        if user:
            ok = sec.verify_password(password, user['salt'], user['verifier'])
        else:
            sec.verify_password(password, *sec._DUMMY)  # equalise timing for unknown logins
            ok = False
        if not ok or not user['enabled']:
            for s in scopes:
                x.c.execute('INSERT INTO login_attempts(scope) VALUES (%s)', (s,))
            ok = False
        else:
            token = sec.new_token()
            hours = sec.SESSION_HOURS[user['role']]
            expires = now() + timedelta(hours=hours)
            x.c.execute('INSERT INTO sessions(token_hash, user_id, cred_version, expires_at) VALUES (%s,%s,%s,%s)',
                        (sec.token_hash(token), user['id'], user['cred_version'], expires))
            x.c.execute('DELETE FROM login_attempts WHERE at < now() - interval \'1 day\'')
    if not ok:
        raise ApiError(401, 'invalid_credentials')
    return {'token': token, 'expires_at': expires, 'role': user['role'], 'full_name': user['full_name']}


@api('/logout', ('POST',), roles=('superadmin', 'admin', 'client'))
def logout(x):
    token = x.request.headers['authorization'][7:].strip()
    x.c.execute('UPDATE sessions SET revoked=true WHERE token_hash=%s', (sec.token_hash(token),))
    return {'ok': True}


@api('/me', roles=('superadmin', 'admin', 'client'))
def me(x):
    return dict(x.user)


@api('/me/password', ('POST',), roles=('superadmin', 'admin', 'client'))
def change_own_password(x):
    row = x.one('SELECT salt, verifier FROM users WHERE id=%s', (x.user['id'],))
    if not isinstance(x.body.get('current'), str) or not sec.verify_password(x.body['current'], row['salt'], row['verifier']):
        raise ApiError(400, 'wrong_current_password')
    new = x.body.get('new')
    try:
        sec.check_new_password(new)
    except ValueError:
        raise ApiError(400, 'password_length')
    salt, verifier = sec.hash_password(new)
    with x.c.transaction():
        x.c.execute('UPDATE users SET salt=%s, verifier=%s, cred_version=cred_version+1 WHERE id=%s',
                    (salt, verifier, x.user['id']))
        x.audit('change_password', 'user', x.user['id'])
    return {'ok': True, 'relogin': True}


def set_credentials(x, user_id, role, login_name, full_name):
    """Create or reset a login; returns the one-time plaintext password."""
    password = sec.generate_password()
    salt, verifier = sec.hash_password(password)
    if user_id:
        x.c.execute('UPDATE users SET salt=%s, verifier=%s, cred_version=cred_version+1, enabled=true, full_name=%s WHERE id=%s',
                    (salt, verifier, full_name, user_id))
        return user_id, password
    row = x.one('INSERT INTO users(role, login, salt, verifier, full_name) VALUES (%s,%s,%s,%s,%s) RETURNING id',
                (role, login_name, salt, verifier, full_name))
    return row['id'], password


# ---------------------------------------------------------------- staff accounts

@api('/staff', roles=('superadmin',))
def staff_list(x):
    return x.all("SELECT id, role, login, full_name, enabled, created_at FROM users WHERE role IN ('admin','superadmin') ORDER BY id")


@api('/staff', ('POST',), roles=('superadmin',))
def staff_create(x):
    role = x.body.get('role', 'admin')
    if role not in STAFF:
        raise ApiError(400, 'invalid_field', 'role')
    try:
        name = sec.normalize_login(x.body.get('login'))
    except ValueError:
        raise ApiError(400, 'invalid_login')
    full_name = text(x.body, 'full_name', required=True, max_len=200)
    with x.c.transaction():
        uid, password = set_credentials(x, None, role, name, full_name)
        x.audit('create_staff', 'user', uid, login=name, role=role)
    return {'id': uid, 'login': name, 'password': password}


@api('/staff/{id}', ('PATCH',), roles=('superadmin',))
def staff_update(x):
    uid = ident(x.params['id'])
    enabled = boolean(x.body, 'enabled')
    with x.c.transaction():
        u = found(x.one("SELECT id, full_name FROM users WHERE id=%s AND role IN ('admin','superadmin') FOR UPDATE", (uid,)))
        if uid == x.user['id'] and enabled is False:
            raise ApiError(400, 'cannot_disable_self')
        full_name = text(x.body, 'full_name', max_len=200) or u['full_name']
        if enabled is None:
            x.c.execute('UPDATE users SET full_name=%s WHERE id=%s', (full_name, uid))
        else:
            x.c.execute('UPDATE users SET full_name=%s, enabled=%s, cred_version=cred_version + (CASE WHEN %s THEN 0 ELSE 1 END) WHERE id=%s',
                        (full_name, enabled, enabled, uid))
        x.audit('update_staff', 'user', uid, enabled=enabled, full_name=full_name)
    return {'ok': True}


@api('/staff/{id}/reset-password', ('POST',), roles=('superadmin',))
def staff_reset(x):
    uid = ident(x.params['id'])
    with x.c.transaction():
        u = found(x.one("SELECT id, full_name FROM users WHERE id=%s AND role IN ('admin','superadmin') FOR UPDATE", (uid,)))
        _, password = set_credentials(x, uid, None, None, u['full_name'])
        x.audit('reset_password', 'user', uid)
    return {'password': password}


# ---------------------------------------------------------------- clients & children

CLIENT_COLS = 'c.id, c.full_name, c.phone, c.note, c.archived, c.created_at, c.user_id, u.login, u.enabled AS login_enabled'


@api('/clients')
def clients_list(x):
    q = (x.query.get('q') or '').strip()[:100]
    archived = x.query.get('archived') == '1'
    args = [archived]
    where = 'c.archived = %s'
    if q:
        digits = re.sub(r'\D', '', q)
        where += ''' AND (c.full_name ILIKE %s OR EXISTS (SELECT 1 FROM children ch WHERE ch.client_id=c.id AND ch.full_name ILIKE %s)'''
        like = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        args += [like, like]
        if len(digits) >= 3:
            where += " OR regexp_replace(c.phone, '\\D', '', 'g') LIKE %s"
            args.append('%' + digits + '%')
        if q.isdigit():
            where += ' OR c.id = %s'
            args.append(int(q))
        where += ')'
    rows = x.all(f'''SELECT {CLIENT_COLS},
            (SELECT string_agg(ch.full_name, ', ' ORDER BY ch.id) FROM children ch WHERE ch.client_id=c.id AND NOT ch.archived) AS children,
            (SELECT count(*) FROM subscriptions s WHERE s.client_id=c.id AND s.status <> 'closed' AND s.ends_on >= %s) AS active_subscriptions
        FROM clients c LEFT JOIN users u ON u.id=c.user_id WHERE {where} ORDER BY c.full_name LIMIT 200''',
                 [today()] + args)
    return rows


def client_payload(x, cid):
    client = found(x.one(f'SELECT {CLIENT_COLS} FROM clients c LEFT JOIN users u ON u.id=c.user_id WHERE c.id=%s', (cid,)))
    client['children'] = x.all('SELECT id, full_name, birth_date, note, archived FROM children WHERE client_id=%s ORDER BY archived, id', (cid,))
    client['subscriptions'] = subscriptions_for(x, 's.client_id=%s', (cid,))
    client['visits'] = visits_query(x, 'sub.client_id=%s', (cid,), limit=100)
    client['telegram_chats'] = len(tgbot.client_chats(x.c, cid)) if client['user_id'] else 0
    return client


@api('/clients/{id}')
def client_get(x):
    return client_payload(x, ident(x.params['id']))


@api('/clients', ('POST',))
def client_create(x):
    full_name = text(x.body, 'full_name', required=True, max_len=200)
    phone = text(x.body, 'phone', max_len=50)
    note = text(x.body, 'note', max_len=2000)
    with x.c.transaction():
        row = x.one('INSERT INTO clients(full_name, phone, note) VALUES (%s,%s,%s) RETURNING id', (full_name, phone, note))
        for child in (x.body.get('children') or [])[:10]:
            if isinstance(child, dict) and text(child, 'full_name'):
                x.c.execute('INSERT INTO children(client_id, full_name, birth_date) VALUES (%s,%s,%s)',
                            (row['id'], text(child, 'full_name', max_len=200), day(child.get('birth_date'), 'birth_date')))
        x.audit('create_client', 'client', row['id'], full_name=full_name)
    return {'id': row['id']}


@api('/clients/{id}', ('PATCH',))
def client_update(x):
    cid = ident(x.params['id'])
    with x.c.transaction():
        cur = found(x.one('SELECT full_name, phone, note, archived FROM clients WHERE id=%s FOR UPDATE', (cid,)))
        new = {
            'full_name': text(x.body, 'full_name', max_len=200) if 'full_name' in x.body else cur['full_name'],
            'phone': text(x.body, 'phone', max_len=50) if 'phone' in x.body else cur['phone'],
            'note': text(x.body, 'note', max_len=2000) if 'note' in x.body else cur['note'],
            'archived': boolean(x.body, 'archived') if 'archived' in x.body else cur['archived'],
        }
        if len(new['full_name']) < 2:
            raise ApiError(400, 'field_required', 'full_name')
        x.c.execute('UPDATE clients SET full_name=%s, phone=%s, note=%s, archived=%s WHERE id=%s',
                    (new['full_name'], new['phone'], new['note'], new['archived'], cid))
        if new['archived']:
            x.c.execute('UPDATE users SET enabled=false, cred_version=cred_version+1 WHERE id=(SELECT user_id FROM clients WHERE id=%s)', (cid,))
        x.audit('update_client', 'client', cid, **{k: v for k, v in new.items() if v != cur[k]})
    return {'ok': True}


@api('/clients/{id}/credentials', ('POST',))
def client_credentials(x):
    """Issue (or reset) the parent's app login. Returns the password once."""
    cid = ident(x.params['id'])
    with x.c.transaction():
        cl = found(x.one('SELECT id, full_name, user_id, archived FROM clients WHERE id=%s FOR UPDATE', (cid,)))
        if cl['archived']:
            raise ApiError(400, 'client_archived')
        if cl['user_id']:
            login_name = x.one('SELECT login FROM users WHERE id=%s', (cl['user_id'],))['login']
            _, password = set_credentials(x, cl['user_id'], None, None, cl['full_name'])
        else:
            raw = x.body.get('login') or f'kid{cid}'
            try:
                login_name = sec.normalize_login(raw)
            except ValueError:
                raise ApiError(400, 'invalid_login')
            uid, password = set_credentials(x, None, 'client', login_name, cl['full_name'])
            x.c.execute('UPDATE clients SET user_id=%s WHERE id=%s', (uid, cid))
        x.audit('issue_client_login', 'client', cid, login=login_name)
    return {'login': login_name, 'password': password}


@api('/clients/{id}/credentials', ('DELETE',))
def client_credentials_disable(x):
    cid = ident(x.params['id'])
    with x.c.transaction():
        cl = found(x.one('SELECT user_id FROM clients WHERE id=%s FOR UPDATE', (cid,)))
        if cl['user_id']:
            x.c.execute('UPDATE users SET enabled=false, cred_version=cred_version+1 WHERE id=%s', (cl['user_id'],))
        x.audit('disable_client_login', 'client', cid)
    return {'ok': True}


@api('/clients/{id}/children', ('POST',))
def child_create(x):
    cid = ident(x.params['id'])
    full_name = text(x.body, 'full_name', required=True, max_len=200)
    with x.c.transaction():
        found(x.one('SELECT id FROM clients WHERE id=%s', (cid,)))
        row = x.one('INSERT INTO children(client_id, full_name, birth_date, note) VALUES (%s,%s,%s,%s) RETURNING id',
                    (cid, full_name, day(x.body.get('birth_date'), 'birth_date'), text(x.body, 'note', max_len=2000)))
        x.audit('create_child', 'child', row['id'], client_id=cid, full_name=full_name)
    return {'id': row['id']}


@api('/children/{id}', ('PATCH',))
def child_update(x):
    chid = ident(x.params['id'])
    with x.c.transaction():
        cur = found(x.one('SELECT full_name, birth_date, note, archived FROM children WHERE id=%s FOR UPDATE', (chid,)))
        full_name = text(x.body, 'full_name', max_len=200) if 'full_name' in x.body else cur['full_name']
        birth = day(x.body.get('birth_date'), 'birth_date') if 'birth_date' in x.body else cur['birth_date']
        note = text(x.body, 'note', max_len=2000) if 'note' in x.body else cur['note']
        archived = boolean(x.body, 'archived') if 'archived' in x.body else cur['archived']
        x.c.execute('UPDATE children SET full_name=%s, birth_date=%s, note=%s, archived=%s WHERE id=%s',
                    (full_name, birth, note, archived, chid))
        x.audit('update_child', 'child', chid)
    return {'ok': True}


# ---------------------------------------------------------------- catalogue

@api('/services', roles=None)
def services_list(x):
    rows = x.all('SELECT * FROM services ORDER BY sort, id')
    photos = x.all('SELECT id, service_id FROM service_photos ORDER BY id')
    links = x.all('SELECT sp.service_id, s.id, s.full_name FROM specialist_services sp JOIN specialists s ON s.id=sp.specialist_id WHERE s.active ORDER BY s.full_name')
    staff = x.user and x.user['role'] in STAFF
    out = []
    for r in rows:
        if not r['active'] and not staff:
            continue
        r['photos'] = [p['id'] for p in photos if p['service_id'] == r['id']]
        r['specialists'] = [{'id': l['id'], 'full_name': l['full_name']} for l in links if l['service_id'] == r['id']]
        out.append(r)
    return out


def service_fields(body, partial):
    fields = {}
    for key, max_len in (('name_ru', 200), ('name_uz', 200), ('description_ru', 5000), ('description_uz', 5000)):
        if key in body or not partial:
            fields[key] = text(body, key, required=(key == 'name_ru'), max_len=max_len)
    if 'duration_min' in body or not partial:
        fields['duration_min'] = integer(body.get('duration_min'), 'duration_min', lo=5, hi=240)
    if 'sort' in body:
        fields['sort'] = integer(body.get('sort'), 'sort', lo=-1000, hi=1000)
    if 'active' in body:
        fields['active'] = boolean(body, 'active')
    if 'late_cancel_forfeit' in body:
        fields['late_cancel_forfeit'] = boolean(body, 'late_cancel_forfeit')
    return fields


@api('/services', ('POST',))
def service_create(x):
    code = text(x.body, 'code', required=True, max_len=31).lower()
    if not re.fullmatch(r'[a-z][a-z0-9_]{1,30}', code):
        raise ApiError(400, 'invalid_field', 'code')
    f = service_fields(x.body, partial=False)
    with x.c.transaction():
        cols = ['code'] + list(f)
        row = x.one(f'INSERT INTO services({",".join(cols)}) VALUES ({",".join(["%s"] * len(cols))}) RETURNING id',
                    [code] + list(f.values()))
        x.audit('create_service', 'service', row['id'], code=code)
    return {'id': row['id']}


@api('/services/{id}', ('PATCH',))
def service_update(x):
    sid = ident(x.params['id'])
    f = service_fields(x.body, partial=True)
    if not f:
        return {'ok': True}
    with x.c.transaction():
        found(x.one('SELECT id FROM services WHERE id=%s FOR UPDATE', (sid,)))
        x.c.execute(f'UPDATE services SET {", ".join(k + "=%s" for k in f)} WHERE id=%s', list(f.values()) + [sid])
        x.audit('update_service', 'service', sid, fields=sorted(f))
    return {'ok': True}


IMAGE_MAGIC = {'image/jpeg': b'\xff\xd8\xff', 'image/png': b'\x89PNG', 'image/webp': b'RIFF'}


@api('/services/{id}/photos', ('POST',))
def photo_upload(x):
    sid = ident(x.params['id'])
    ctype = x.body.get('content_type')
    if ctype not in IMAGE_MAGIC:
        raise ApiError(400, 'unsupported_image')
    try:
        data = base64.b64decode(x.body.get('data') or '', validate=True)
    except (binascii.Error, ValueError, TypeError):
        raise ApiError(400, 'invalid_image')
    if not data.startswith(IMAGE_MAGIC[ctype]) or (ctype == 'image/webp' and data[8:12] != b'WEBP'):
        raise ApiError(400, 'invalid_image')
    if len(data) > 2 * 1024 * 1024:
        raise ApiError(400, 'image_too_large')
    with x.c.transaction():
        found(x.one('SELECT id FROM services WHERE id=%s', (sid,)))
        if x.one('SELECT count(*) AS n FROM service_photos WHERE service_id=%s', (sid,))['n'] >= 10:
            raise ApiError(400, 'too_many_photos')
        row = x.one('INSERT INTO service_photos(service_id, content_type, data) VALUES (%s,%s,%s) RETURNING id', (sid, ctype, data))
        x.audit('add_photo', 'service', sid, photo_id=row['id'])
    return {'id': row['id']}


@api('/photos/{id}', ('DELETE',))
def photo_delete(x):
    pid = ident(x.params['id'])
    with x.c.transaction():
        row = found(x.one('DELETE FROM service_photos WHERE id=%s RETURNING service_id', (pid,)))
        x.audit('delete_photo', 'service', row['service_id'], photo_id=pid)
    return {'ok': True}


@api('/photos/{id}', roles=None)
def photo_get(x):
    row = found(x.one('SELECT content_type, data FROM service_photos WHERE id=%s', (ident(x.params['id']),)))
    return Response(bytes(row['data']), media_type=row['content_type'],
                    headers={'Cache-Control': 'public, max-age=86400', 'X-Content-Type-Options': 'nosniff'})


@api('/specialists', roles=None)
def specialists_list(x):
    staff = x.user and x.user['role'] in STAFF
    rows = x.all('SELECT id, full_name, phone, bio, active FROM specialists ORDER BY active DESC, full_name')
    links = x.all('SELECT specialist_id, service_id FROM specialist_services')
    out = []
    for r in rows:
        if not staff:
            if not r['active']:
                continue
            r.pop('phone')
        r['service_ids'] = [l['service_id'] for l in links if l['specialist_id'] == r['id']]
        out.append(r)
    return out


def save_specialist(x, sid):
    service_ids = x.body.get('service_ids')
    if service_ids is not None:
        if not isinstance(service_ids, list) or len(service_ids) > 50:
            raise ApiError(400, 'invalid_field', 'service_ids')
        service_ids = sorted({ident(v, 'service_ids') for v in service_ids})
        x.c.execute('DELETE FROM specialist_services WHERE specialist_id=%s', (sid,))
        for v in service_ids:
            x.c.execute('INSERT INTO specialist_services VALUES (%s,%s)', (sid, v))


@api('/specialists', ('POST',))
def specialist_create(x):
    full_name = text(x.body, 'full_name', required=True, max_len=200)
    with x.c.transaction():
        row = x.one('INSERT INTO specialists(full_name, phone, bio) VALUES (%s,%s,%s) RETURNING id',
                    (full_name, text(x.body, 'phone', max_len=50), text(x.body, 'bio', max_len=5000)))
        save_specialist(x, row['id'])
        x.audit('create_specialist', 'specialist', row['id'], full_name=full_name)
    return {'id': row['id']}


@api('/specialists/{id}', ('PATCH',))
def specialist_update(x):
    sid = ident(x.params['id'])
    with x.c.transaction():
        cur = found(x.one('SELECT full_name, phone, bio, active FROM specialists WHERE id=%s FOR UPDATE', (sid,)))
        vals = [text(x.body, k, max_len=5000) if k in x.body else cur[k] for k in ('full_name', 'phone', 'bio')]
        active = boolean(x.body, 'active') if 'active' in x.body else cur['active']
        if len(vals[0]) < 2:
            raise ApiError(400, 'field_required', 'full_name')
        x.c.execute('UPDATE specialists SET full_name=%s, phone=%s, bio=%s, active=%s WHERE id=%s', vals + [active, sid])
        save_specialist(x, sid)
        x.audit('update_specialist', 'specialist', sid)
    return {'ok': True}


def plans_query(x, active_only):
    rows = x.all('SELECT * FROM plans' + (' WHERE active' if active_only else '') + ' ORDER BY active DESC, name')
    items = x.all('''SELECT pi.plan_id, pi.service_id, pi.visits, s.name_ru, s.code FROM plan_items pi
        JOIN services s ON s.id=pi.service_id ORDER BY s.sort, s.id''')
    for r in rows:
        r['items'] = [{k: i[k] for k in ('service_id', 'visits', 'name_ru', 'code')} for i in items if i['plan_id'] == r['id']]
    return rows


@api('/plans', roles=None)
def plans_list(x):
    return plans_query(x, active_only=not (x.user and x.user['role'] in STAFF))


def parse_items(raw):
    if not isinstance(raw, list) or not 1 <= len(raw) <= 10:
        raise ApiError(400, 'items_required')
    items = {}
    for it in raw:
        if not isinstance(it, dict):
            raise ApiError(400, 'invalid_field', 'items')
        sid = ident(it.get('service_id'), 'service_id')
        if sid in items:
            raise ApiError(400, 'duplicate_service')
        items[sid] = integer(it.get('visits'), 'visits', lo=1, hi=500)
    return items


@api('/plans', ('POST',))
def plan_create(x):
    name = text(x.body, 'name', required=True, max_len=200)
    validity = integer(x.body.get('validity_days'), 'validity_days', lo=1, hi=730)
    price = money(x.body.get('price'), 'price') or Decimal('0')
    items = parse_items(x.body.get('items'))
    with x.c.transaction():
        row = x.one('INSERT INTO plans(name, validity_days, price) VALUES (%s,%s,%s) RETURNING id', (name, validity, price))
        for sid, visits in items.items():
            x.c.execute('INSERT INTO plan_items VALUES (%s,%s,%s)', (row['id'], sid, visits))
        x.audit('create_plan', 'plan', row['id'], name=name, price=price, items=items)
    return {'id': row['id']}


@api('/plans/{id}', ('PATCH',))
def plan_update(x):
    pid = ident(x.params['id'])
    with x.c.transaction():
        cur = found(x.one('SELECT * FROM plans WHERE id=%s FOR UPDATE', (pid,)))
        name = text(x.body, 'name', max_len=200) if 'name' in x.body else cur['name']
        validity = integer(x.body.get('validity_days'), 'validity_days', lo=1, hi=730) if 'validity_days' in x.body else cur['validity_days']
        price = money(x.body.get('price'), 'price') if 'price' in x.body else cur['price']
        active = boolean(x.body, 'active') if 'active' in x.body else cur['active']
        x.c.execute('UPDATE plans SET name=%s, validity_days=%s, price=%s, active=%s WHERE id=%s',
                    (name, validity, price if price is not None else cur['price'], active, pid))
        if 'items' in x.body:
            items = parse_items(x.body['items'])
            x.c.execute('DELETE FROM plan_items WHERE plan_id=%s', (pid,))
            for sid, visits in items.items():
                x.c.execute('INSERT INTO plan_items VALUES (%s,%s,%s)', (pid, sid, visits))
        x.audit('update_plan', 'plan', pid)
    return {'ok': True}


# ---------------------------------------------------------------- subscriptions

def subscriptions_for(x, where, args, limit=500):
    rows = x.all(f'''SELECT s.id, s.client_id, c.full_name AS client_name, s.child_id, ch.full_name AS child_name,
            s.plan_id, s.name, s.price, s.status, s.starts_on, s.ends_on, s.frozen_since, s.created_at,
            coalesce((SELECT sum(p.amount) FROM payments p WHERE p.subscription_id=s.id AND p.voided_at IS NULL), 0) AS paid
        FROM subscriptions s JOIN clients c ON c.id=s.client_id LEFT JOIN children ch ON ch.id=s.child_id
        WHERE {where} ORDER BY (s.status='closed'), s.ends_on DESC, s.id DESC LIMIT {int(limit)}''', args)
    if rows:
        items = x.all('''SELECT si.subscription_id, si.service_id, si.quota, si.remaining, sv.name_ru, sv.code
            FROM subscription_items si JOIN services sv ON sv.id=si.service_id
            WHERE si.subscription_id = ANY(%s) ORDER BY sv.sort, sv.id''', ([r['id'] for r in rows],))
        t = today()
        for r in rows:
            r['items'] = [{k: i[k] for k in ('service_id', 'quota', 'remaining', 'name_ru', 'code')}
                          for i in items if i['subscription_id'] == r['id']]
            r['state'] = subscription_state(r, t)
            r['debt'] = max(Decimal('0.00'), r['price'] - r['paid']) if r['status'] != 'closed' else Decimal('0.00')
    return rows


def subscription_state(s, t):
    if s['status'] in ('closed', 'frozen'):
        return s['status']
    if t < s['starts_on']:
        return 'not_started'
    if t > s['ends_on']:
        return 'expired'
    if s.get('items') is not None and all(i['remaining'] == 0 for i in s['items']):
        return 'used_up'
    return 'active'


@api('/subscriptions')
def subscriptions_list(x):
    state = x.query.get('state')
    if state == 'expiring':
        t = today()
        return subscriptions_for(x, '''s.status='active' AND s.ends_on BETWEEN %s AND %s
            OR (s.status='active' AND s.ends_on >= %s AND (SELECT sum(remaining) FROM subscription_items WHERE subscription_id=s.id) <= 1)''',
                                 (t, t + timedelta(days=7), t))
    if state == 'frozen':
        return subscriptions_for(x, "s.status='frozen'", ())
    if state == 'debt':
        return subscriptions_for(x, '''s.status <> 'closed' AND s.price >
            coalesce((SELECT sum(p.amount) FROM payments p WHERE p.subscription_id=s.id AND p.voided_at IS NULL), 0)''', ())
    return subscriptions_for(x, "s.status <> 'closed' AND s.ends_on >= %s", (today(),))


@api('/subscriptions', ('POST',))
def subscription_create(x):
    cid = ident(x.body.get('client_id'), 'client_id')
    child_id = ident(x.body.get('child_id'), 'child_id', required=False)
    starts = day(x.body.get('starts_on'), 'starts_on') or today()
    with x.c.transaction():
        client = found(x.one('SELECT id, archived FROM clients WHERE id=%s FOR SHARE', (cid,)), 'client_not_found')
        if client['archived']:
            raise ApiError(400, 'client_archived')
        if child_id and not x.one('SELECT 1 FROM children WHERE id=%s AND client_id=%s AND NOT archived', (child_id, cid)):
            raise ApiError(400, 'child_not_of_client')
        plan_id = ident(x.body.get('plan_id'), 'plan_id', required=False)
        if plan_id:
            plan = found(x.one('SELECT * FROM plans WHERE id=%s AND active', (plan_id,)), 'plan_not_found')
            items = {r['service_id']: r['visits'] for r in x.all('SELECT service_id, visits FROM plan_items WHERE plan_id=%s', (plan_id,))}
            name, validity, price = plan['name'], plan['validity_days'], plan['price']
        else:
            items = parse_items(x.body.get('items'))
            name = text(x.body, 'name', required=True, max_len=200)
            validity = integer(x.body.get('validity_days'), 'validity_days', lo=1, hi=730)
            price = Decimal('0')
        if x.body.get('price') not in (None, ''):
            price = money(x.body.get('price'), 'price')
        if not items:
            raise ApiError(400, 'items_required')
        ends = starts + timedelta(days=validity - 1)
        row = x.one('''INSERT INTO subscriptions(client_id, child_id, plan_id, name, price, starts_on, ends_on, created_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''', (cid, child_id, plan_id, name, price, starts, ends, x.user['id']))
        for sid, visits in items.items():
            x.c.execute('INSERT INTO subscription_items VALUES (%s,%s,%s,%s)', (row['id'], sid, visits, visits))
        x.audit('create_subscription', 'subscription', row['id'], client_id=cid, child_id=child_id,
                plan_id=plan_id, name=name, price=price, starts_on=starts, ends_on=ends, items=items)
        paid_now = money(x.body.get('paid_amount'), 'paid_amount')
        if paid_now:
            record_payment(x, row['id'], price, Decimal('0'), paid_now, x.body.get('paid_method') or 'cash', '')
        debt = max(Decimal('0'), price - (paid_now or Decimal('0')))
        x.notify_client(cid, 'n_sub_created', name=tgbot.e(name), start=starts.strftime('%d.%m.%Y'), end=ends.strftime('%d.%m.%Y'),
                        debt=i18n.both('n_to_pay', sum=i18n.money(debt)) if debt else '')
    return {'id': row['id']}


def lock_subscription(x, sid):
    return found(x.one('SELECT * FROM subscriptions WHERE id=%s FOR UPDATE', (ident(sid),)), 'subscription_not_found')


@api('/subscriptions/{id}')
def subscription_get(x):
    rows = subscriptions_for(x, 's.id=%s', (ident(x.params['id']),))
    sub = found(rows[0] if rows else None)
    sub['visits'] = visits_query(x, 'v.subscription_id=%s', (sub['id'],), limit=500, include_cancelled=True)
    sub['payments'] = payments_query(x, 'p.subscription_id=%s', (sub['id'],))
    sub['history'] = x.all("SELECT a.at, a.action, a.details, u.full_name AS actor FROM audit_log a LEFT JOIN users u ON u.id=a.actor_id WHERE a.entity='subscription' AND a.entity_id=%s ORDER BY a.id", (sub['id'],))
    return sub


@api('/subscriptions/{id}/freeze', ('POST',))
def subscription_freeze(x):
    why = reason(x.body)
    with x.c.transaction():
        s = lock_subscription(x, x.params['id'])
        if s['status'] != 'active':
            raise ApiError(409, 'not_active')
        if today() > s['ends_on']:
            raise ApiError(409, 'expired')
        x.c.execute("UPDATE subscriptions SET status='frozen', frozen_since=%s WHERE id=%s", (today(), s['id']))
        x.audit('freeze', 'subscription', s['id'], reason=why)
        x.notify_client(s['client_id'], 'n_freeze', name=tgbot.e(s['name']))
    return {'ok': True}


@api('/subscriptions/{id}/unfreeze', ('POST',))
def subscription_unfreeze(x):
    with x.c.transaction():
        s = lock_subscription(x, x.params['id'])
        if s['status'] != 'frozen':
            raise ApiError(409, 'not_frozen')
        days = max(0, (today() - s['frozen_since']).days)
        ends = s['ends_on'] + timedelta(days=days)
        x.c.execute("UPDATE subscriptions SET status='active', frozen_since=NULL, ends_on=%s WHERE id=%s", (ends, s['id']))
        x.audit('unfreeze', 'subscription', s['id'], frozen_days=days, ends_on=ends)
        x.notify_client(s['client_id'], 'n_unfreeze', name=tgbot.e(s['name']), end=ends.strftime('%d.%m.%Y'))
    return {'ok': True, 'frozen_days': days, 'ends_on': ends}


@api('/subscriptions/{id}/extend', ('POST',))
def subscription_extend(x):
    days = integer(x.body.get('days'), 'days', lo=1, hi=365)
    why = reason(x.body)
    with x.c.transaction():
        s = lock_subscription(x, x.params['id'])
        if s['status'] == 'closed':
            raise ApiError(409, 'closed')
        ends = s['ends_on'] + timedelta(days=days)
        x.c.execute('UPDATE subscriptions SET ends_on=%s WHERE id=%s', (ends, s['id']))
        x.audit('extend', 'subscription', s['id'], days=days, ends_on=ends, reason=why)
        x.notify_client(s['client_id'], 'n_extend', name=tgbot.e(s['name']), end=ends.strftime('%d.%m.%Y'))
    return {'ok': True, 'ends_on': ends}


@api('/subscriptions/{id}/adjust', ('POST',))
def subscription_adjust(x):
    service_id = ident(x.body.get('service_id'), 'service_id')
    delta = integer(x.body.get('delta'), 'delta', lo=-500, hi=500)
    if delta == 0:
        raise ApiError(400, 'invalid_field', 'delta')
    why = reason(x.body)
    with x.c.transaction():
        s = lock_subscription(x, x.params['id'])
        if s['status'] == 'closed':
            raise ApiError(409, 'closed')
        item = found(x.one('SELECT quota, remaining FROM subscription_items WHERE subscription_id=%s AND service_id=%s FOR UPDATE',
                           (s['id'], service_id)), 'service_not_in_subscription')
        remaining = item['remaining'] + delta
        if remaining < 0:
            raise ApiError(409, 'not_enough_visits')
        quota = max(item['quota'], remaining)
        x.c.execute('UPDATE subscription_items SET remaining=%s, quota=%s WHERE subscription_id=%s AND service_id=%s',
                    (remaining, quota, s['id'], service_id))
        x.audit('adjust', 'subscription', s['id'], service_id=service_id, delta=delta,
                before=item['remaining'], after=remaining, reason=why)
    return {'ok': True, 'remaining': remaining}


@api('/subscriptions/{id}/close', ('POST',))
def subscription_close(x):
    why = reason(x.body)
    with x.c.transaction():
        s = lock_subscription(x, x.params['id'])
        if s['status'] == 'closed':
            raise ApiError(409, 'closed')
        x.c.execute("UPDATE subscriptions SET status='closed', frozen_since=NULL WHERE id=%s", (s['id'],))
        x.audit('close', 'subscription', s['id'], reason=why)
    return {'ok': True}


# ---------------------------------------------------------------- payments

PAYMENT_METHODS = {'cash': 'наличные', 'card': 'карта', 'click': 'Click', 'payme': 'Payme', 'transfer': 'перевод'}


def fmt_sum(amount):
    return f"{int(amount):,}".replace(',', ' ') + ' сум'


def record_payment(x, sid, price, paid_before, amount, method, note):
    if method not in PAYMENT_METHODS:
        raise ApiError(400, 'invalid_field', 'method')
    if amount is None or amount <= 0:
        raise ApiError(400, 'invalid_field', 'amount')
    if paid_before + amount > price:
        raise ApiError(409, 'overpayment', {'debt': max(Decimal('0'), price - paid_before)})
    row = x.one('''INSERT INTO payments(subscription_id, amount, method, paid_at, staff_id, note)
        VALUES (%s,%s,%s,%s,%s,%s) RETURNING id''', (sid, amount, method, now(), x.user['id'], note))
    x.audit('payment', 'subscription', sid, payment_id=row['id'], amount=amount, method=method, note=note)
    return row['id']


@api('/subscriptions/{id}/payments', ('POST',))
def payment_create(x):
    amount = money(x.body.get('amount'), 'amount')
    method = x.body.get('method') or 'cash'
    note = text(x.body, 'note', max_len=300)
    with x.c.transaction():
        s = lock_subscription(x, x.params['id'])
        if s['status'] == 'closed':
            raise ApiError(409, 'closed')
        paid = x.one('SELECT coalesce(sum(amount),0) AS v FROM payments WHERE subscription_id=%s AND voided_at IS NULL', (s['id'],))['v']
        pid = record_payment(x, s['id'], s['price'], paid, amount, method, note)
        debt = s['price'] - paid - amount
        x.notify_client(s['client_id'], 'n_payment', sum=i18n.money(amount), method={l: i18n.METHODS[l][method] for l in i18n.LANGS},
                        name=tgbot.e(s['name']), rest=i18n.both('n_payment_rest', debt=i18n.money(debt)) if debt > 0 else i18n.both('n_payment_full'))
    return {'id': pid, 'debt': debt}


@api('/payments/{id}/void', ('POST',))
def payment_void(x):
    why = reason(x.body)
    pid = ident(x.params['id'])
    with x.c.transaction():
        pointer = found(x.one('SELECT subscription_id FROM payments WHERE id=%s', (pid,)))
        s = lock_subscription(x, pointer['subscription_id'])
        p = x.one('SELECT * FROM payments WHERE id=%s FOR UPDATE', (pid,))
        if p['voided_at']:
            raise ApiError(409, 'already_voided')
        same_day = p['paid_at'].astimezone(ZONE).date() == today()
        if x.user['role'] != 'superadmin' and not (same_day and p['staff_id'] == x.user['id']):
            raise ApiError(403, 'void_needs_superadmin')
        x.c.execute('UPDATE payments SET voided_at=%s, voided_by=%s, void_reason=%s WHERE id=%s', (now(), x.user['id'], why, pid))
        x.audit('void_payment', 'subscription', s['id'], payment_id=pid, amount=p['amount'], method=p['method'], reason=why)
    return {'ok': True}


def payments_query(x, where, args, limit=2000):
    return x.all(f'''SELECT p.id, p.subscription_id, s.name AS subscription_name, s.client_id, c.full_name AS client_name,
            p.amount, p.method, p.paid_at, p.note, st.full_name AS staff_name, p.staff_id,
            p.voided_at, p.void_reason, vb.full_name AS voided_by_name
        FROM payments p JOIN subscriptions s ON s.id=p.subscription_id JOIN clients c ON c.id=s.client_id
        JOIN users st ON st.id=p.staff_id LEFT JOIN users vb ON vb.id=p.voided_by
        WHERE {where} ORDER BY p.paid_at DESC, p.id DESC LIMIT {int(limit)}''', args)


@api('/payments')
def payments_list(x):
    start = day(x.query.get('from'), 'from') or today()
    end = day(x.query.get('to'), 'to') or start
    if end < start or (end - start).days > 366:
        raise ApiError(400, 'invalid_period')
    rows = payments_query(x, "(p.paid_at AT TIME ZONE 'Asia/Tashkent')::date BETWEEN %s AND %s", (start, end))
    totals = {m: Decimal('0') for m in PAYMENT_METHODS}
    for r in rows:
        if not r['voided_at']:
            totals[r['method']] += r['amount']
    return {'from': start, 'to': end, 'payments': rows, 'by_method': totals, 'total': sum(totals.values())}


# ---------------------------------------------------------------- visits

def visits_query(x, where, args, limit=500, include_cancelled=True):
    cond = where + ('' if include_cancelled else ' AND v.cancelled_at IS NULL')
    return x.all(f'''SELECT v.id, v.subscription_id, sub.name AS subscription_name, sub.client_id, c.full_name AS client_name,
            v.service_id, sv.name_ru AS service_name, v.child_id, ch.full_name AS child_name,
            v.specialist_id, sp.full_name AS specialist_name, v.method, v.visited_at,
            st.full_name AS staff_name, v.cancelled_at, v.cancel_reason
        FROM visits v JOIN subscriptions sub ON sub.id=v.subscription_id JOIN clients c ON c.id=sub.client_id
        JOIN services sv ON sv.id=v.service_id LEFT JOIN children ch ON ch.id=v.child_id
        LEFT JOIN specialists sp ON sp.id=v.specialist_id JOIN users st ON st.id=v.staff_id
        WHERE {cond} ORDER BY v.visited_at DESC, v.id DESC LIMIT {int(limit)}''', args)


def redeem(x, sub, service_id, child_id, specialist_id, method, force=False, booking_id=None):
    """Caller holds the subscription row lock inside a transaction."""
    t = today()
    if sub['status'] == 'frozen':
        raise ApiError(409, 'subscription_frozen')
    if sub['status'] == 'closed':
        raise ApiError(409, 'subscription_closed')
    if t < sub['starts_on']:
        raise ApiError(409, 'subscription_not_started')
    if t > sub['ends_on']:
        raise ApiError(409, 'subscription_expired')
    if sub['child_id']:
        if child_id and child_id != sub['child_id']:
            raise ApiError(409, 'subscription_for_other_child')
        child_id = sub['child_id']
    elif child_id and not x.one('SELECT 1 FROM children WHERE id=%s AND client_id=%s AND NOT archived', (child_id, sub['client_id'])):
        raise ApiError(400, 'child_not_of_client')
    elif not child_id:
        kids = x.all('SELECT id FROM children WHERE client_id=%s AND NOT archived', (sub['client_id'],))
        if len(kids) == 1:  # the only child of the family
            child_id = kids[0]['id']
    if specialist_id and not x.one('SELECT 1 FROM specialists WHERE id=%s AND active', (specialist_id,)):
        raise ApiError(400, 'specialist_not_found')
    item = x.one('SELECT remaining FROM subscription_items WHERE subscription_id=%s AND service_id=%s FOR UPDATE',
                 (sub['id'], service_id))
    if not item:
        raise ApiError(409, 'service_not_in_subscription')
    if item['remaining'] <= 0:
        raise ApiError(409, 'no_visits_left')
    if not force:
        dup = x.one('''SELECT v.id FROM visits v WHERE v.subscription_id=%s AND v.service_id=%s AND v.cancelled_at IS NULL
            AND v.method IN ('qr','manual')
            AND v.child_id IS NOT DISTINCT FROM %s AND (v.visited_at AT TIME ZONE 'Asia/Tashkent')::date = %s''',
                    (sub['id'], service_id, child_id, t))
        if dup:
            raise ApiError(409, 'already_visited_today', {'visit_id': dup['id']})
    x.c.execute('UPDATE subscription_items SET remaining=remaining-1 WHERE subscription_id=%s AND service_id=%s',
                (sub['id'], service_id))
    visit = x.one('''INSERT INTO visits(subscription_id, service_id, child_id, specialist_id, method, visited_at, staff_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id''', (sub['id'], service_id, child_id, specialist_id, method, now(), x.user['id']))
    from . import schedule
    if booking_id:
        x.c.execute("UPDATE bookings SET status='attended', visit_id=%s WHERE id=%s", (visit['id'], booking_id))
    else:
        booking_id = schedule.link_visit_to_booking(x, sub, service_id, child_id, visit['id'])
    x.audit('visit', 'subscription', sub['id'], visit_id=visit['id'], service_id=service_id, child_id=child_id,
            specialist_id=specialist_id, method=method, remaining=item['remaining'] - 1, booking_id=booking_id)
    names = x.one('''SELECT sv.name_ru AS service, sv.name_uz AS service_uz, si.quota, ch.full_name AS child FROM subscription_items si
        JOIN services sv ON sv.id=si.service_id LEFT JOIN children ch ON ch.id=%s
        WHERE si.subscription_id=%s AND si.service_id=%s''', (child_id, sub['id'], service_id))
    left = item['remaining'] - 1
    who = f" ({tgbot.e(names['child'])})" if names['child'] else ''
    tail = i18n.both('n_visit_last') if left == 0 else (i18n.both('n_visit_one') if left == 1 else '')
    x.notify_client(sub['client_id'], 'n_visit', service=i18n.name(tgbot.e(names['service']), tgbot.e(names['service_uz'] or '')),
                    who=who, left=left, quota=names['quota'], ends=sub['ends_on'].strftime('%d.%m.%Y'), tail=tail)
    return {'visit_id': visit['id'], 'remaining': item['remaining'] - 1}


def visit_args(body):
    return (ident(body.get('service_id'), 'service_id'), ident(body.get('child_id'), 'child_id', required=False),
            ident(body.get('specialist_id'), 'specialist_id', required=False), body.get('force') is True)


@api('/visits', ('POST',))
def visit_create(x):
    service_id, child_id, specialist_id, force = visit_args(x.body)
    with x.c.transaction():
        sub = lock_subscription(x, x.body.get('subscription_id'))
        return redeem(x, sub, service_id, child_id, specialist_id, 'manual', force)


@api('/visits')
def visits_list(x):
    start = day(x.query.get('from'), 'from') or today()
    end = day(x.query.get('to'), 'to') or start
    args = [start, end]
    where = "(v.visited_at AT TIME ZONE 'Asia/Tashkent')::date BETWEEN %s AND %s"
    service_id = ident(x.query.get('service_id'), 'service_id', required=False)
    if service_id:
        where += ' AND v.service_id=%s'
        args.append(service_id)
    return visits_query(x, where, args, limit=2000)


@api('/visits/{id}/cancel', ('POST',))
def visit_cancel(x):
    why = reason(x.body)
    vid = ident(x.params['id'])
    with x.c.transaction():
        pointer = found(x.one('SELECT subscription_id FROM visits WHERE id=%s', (vid,)))
        sub = lock_subscription(x, pointer['subscription_id'])
        v = x.one('SELECT * FROM visits WHERE id=%s FOR UPDATE', (vid,))
        if v['cancelled_at']:
            raise ApiError(409, 'already_cancelled')
        x.c.execute('UPDATE visits SET cancelled_at=%s, cancelled_by=%s, cancel_reason=%s WHERE id=%s', (now(), x.user['id'], why, vid))
        x.c.execute('''UPDATE subscription_items SET remaining=remaining+1, quota=greatest(quota, remaining+1)
            WHERE subscription_id=%s AND service_id=%s''', (sub['id'], v['service_id']))
        x.audit('cancel_visit', 'subscription', sub['id'], visit_id=vid, service_id=v['service_id'], reason=why)
        svc = x.one('SELECT name_ru, name_uz FROM services WHERE id=%s', (v['service_id'],))
        x.notify_client(sub['client_id'], 'n_visit_cancel', service=i18n.name(tgbot.e(svc['name_ru']), tgbot.e(svc['name_uz'] or '')),
                        at=v['visited_at'].astimezone(ZONE).strftime('%d.%m %H:%M'))
    return {'ok': True}


# ---------------------------------------------------------------- QR

def parse_qr(code):
    if not isinstance(code, str):
        raise ApiError(400, 'invalid_qr')
    code = code.strip()
    if code.startswith(QR_PREFIX):
        code = code[len(QR_PREFIX):]
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}', code):
        raise ApiError(400, 'invalid_qr')
    return sec.token_hash(code)


def qr_row(x, code, lock=False):
    row = x.one('SELECT * FROM qr_tokens WHERE token_hash=%s' + (' FOR UPDATE' if lock else ''), (parse_qr(code),))
    if not row:
        raise ApiError(404, 'qr_unknown')
    if row['used_at']:
        raise ApiError(409, 'qr_already_used')
    if row['expires_at'] <= now():
        raise ApiError(409, 'qr_expired')
    return row


@api('/qr/lookup', ('POST',))
def qr_lookup(x):
    row = qr_row(x, x.body.get('code'))
    client = client_payload(x, row['client_id'])
    client['visits'] = client['visits'][:10]
    return {'client': client, 'expires_at': row['expires_at']}


@api('/qr/redeem', ('POST',))
def qr_redeem(x):
    service_id, child_id, specialist_id, force = visit_args(x.body)
    with x.c.transaction():
        token = qr_row(x, x.body.get('code'), lock=True)
        sub = lock_subscription(x, x.body.get('subscription_id'))
        if sub['client_id'] != token['client_id']:
            raise ApiError(409, 'qr_other_client')
        result = redeem(x, sub, service_id, child_id, specialist_id, 'qr', force)
        x.c.execute('UPDATE qr_tokens SET used_at=%s WHERE token_hash=%s', (now(), token['token_hash']))
    return result


# ---------------------------------------------------------------- client app (parents)

def my_client(x):
    return found(x.one('SELECT id, full_name, phone FROM clients WHERE user_id=%s AND NOT archived', (x.user['id'],)), 'client_not_found')


@api('/my/profile', roles=('client',))
def my_profile(x):
    cl = my_client(x)
    cl['children'] = x.all('SELECT id, full_name, birth_date FROM children WHERE client_id=%s AND NOT archived ORDER BY id', (cl['id'],))
    return cl


@api('/my/subscriptions', roles=('client',))
def my_subscriptions(x):
    rows = subscriptions_for(x, 's.client_id=%s', (my_client(x)['id'],), limit=100)
    for r in rows:
        r.pop('price', None)
        r.pop('paid', None)
    return rows


@api('/my/visits', roles=('client',))
def my_visits(x):
    rows = visits_query(x, 'sub.client_id=%s', (my_client(x)['id'],), limit=200)
    for r in rows:
        r.pop('staff_name', None)
    return rows


@api('/my/qr', ('POST',), roles=('client',))
def my_qr(x):
    cl = my_client(x)
    token = sec.new_token()
    expires = now() + timedelta(seconds=sec.QR_SECONDS)
    with x.c.transaction():
        x.c.execute('UPDATE qr_tokens SET expires_at=least(expires_at, now()) WHERE client_id=%s AND used_at IS NULL', (cl['id'],))
        x.c.execute('DELETE FROM qr_tokens WHERE expires_at < now() - interval \'30 days\'')
        x.c.execute('INSERT INTO qr_tokens(token_hash, client_id, expires_at) VALUES (%s,%s,%s)', (sec.token_hash(token), cl['id'], expires))
    return {'code': QR_PREFIX + token, 'expires_at': expires, 'ttl_seconds': sec.QR_SECONDS}


@api('/catalog', roles=None)
def catalog(x):
    return {'services': services_list(x), 'specialists': specialists_list(x), 'plans': plans_query(x, True)}


# ---------------------------------------------------------------- reports & audit

@api('/reports')
def reports(x):
    t = today()
    start = day(x.query.get('from'), 'from') or t.replace(day=1)
    end = day(x.query.get('to'), 'to') or t
    if end < start or (end - start).days > 366:
        raise ApiError(400, 'invalid_period')
    vday = "(v.visited_at AT TIME ZONE 'Asia/Tashkent')::date"
    rng = (start, end)
    by_service = x.all(f'''SELECT sv.name_ru AS name, count(v.id) AS visits FROM services sv
        LEFT JOIN visits v ON v.service_id=sv.id AND v.cancelled_at IS NULL AND {vday} BETWEEN %s AND %s
        GROUP BY sv.id ORDER BY sv.sort, sv.id''', rng)
    by_day = x.all(f'''SELECT {vday} AS day, count(*) AS visits FROM visits v WHERE v.cancelled_at IS NULL AND {vday} BETWEEN %s AND %s
        GROUP BY 1 ORDER BY 1''', rng)
    by_specialist = x.all(f'''SELECT coalesce(sp.full_name, 'Не указан') AS name, count(*) AS visits FROM visits v
        LEFT JOIN specialists sp ON sp.id=v.specialist_id WHERE v.cancelled_at IS NULL AND {vday} BETWEEN %s AND %s
        GROUP BY 1 ORDER BY 2 DESC''', rng)
    sold = x.one('''SELECT count(*) AS count, coalesce(sum(price), 0) AS revenue FROM subscriptions
        WHERE (created_at AT TIME ZONE 'Asia/Tashkent')::date BETWEEN %s AND %s''', rng)
    sold_by_plan = x.all('''SELECT name, count(*) AS count, coalesce(sum(price),0) AS revenue FROM subscriptions
        WHERE (created_at AT TIME ZONE 'Asia/Tashkent')::date BETWEEN %s AND %s GROUP BY name ORDER BY 2 DESC''', rng)
    counts = x.one('''SELECT (SELECT count(*) FROM clients WHERE NOT archived) AS clients,
        (SELECT count(*) FROM subscriptions WHERE status='active' AND ends_on >= %s) AS active_subscriptions,
        (SELECT count(*) FROM subscriptions WHERE status='frozen') AS frozen_subscriptions,
        (SELECT count(*) FROM visits v WHERE v.cancelled_at IS NULL AND (v.visited_at AT TIME ZONE 'Asia/Tashkent')::date = %s) AS visits_today''',
                   (t, t))
    pay = x.all('''SELECT method, coalesce(sum(amount),0) AS amount FROM payments
        WHERE voided_at IS NULL AND (paid_at AT TIME ZONE 'Asia/Tashkent')::date BETWEEN %s AND %s GROUP BY method''', rng)
    by_method = {m: Decimal('0') for m in PAYMENT_METHODS}
    for r in pay:
        by_method[r['method']] = r['amount']
    debt = x.one('''SELECT coalesce(sum(greatest(s.price - coalesce((SELECT sum(p.amount) FROM payments p
        WHERE p.subscription_id=s.id AND p.voided_at IS NULL), 0), 0)), 0) AS v FROM subscriptions s WHERE s.status <> 'closed' ''')['v']
    return {'from': start, 'to': end, 'totals': counts, 'by_service': by_service, 'by_day': by_day,
            'by_specialist': by_specialist, 'sold': sold, 'sold_by_plan': sold_by_plan,
            'received': {'by_method': by_method, 'total': sum(by_method.values())}, 'debt_total': debt}


@api('/audit')
def audit(x):
    limit = integer(x.query.get('limit') or 200, 'limit', lo=1, hi=1000)
    return x.all(f'''SELECT a.id, a.at, a.action, a.entity, a.entity_id, a.details, u.full_name AS actor
        FROM audit_log a LEFT JOIN users u ON u.id=a.actor_id ORDER BY a.id DESC LIMIT {limit}''')


# ---------------------------------------------------------------- app

async def health(request):
    def check():
        with request.app.state.db.conn() as c:
            c.execute('SELECT 1').fetchone()
    try:
        await run_in_threadpool(check)
        return json_response({'status': 'ok', 'database': 'ok'})
    except Exception:
        log.exception('health check failed')
        return json_response({'status': 'degraded', 'database': 'unavailable'}, 503)


async def telegram_webhook(request):
    st = request.app.state
    if not st.tg:
        return Response(status_code=404)
    if not hmac.compare_digest(request.headers.get('x-telegram-bot-api-secret-token', ''), tgbot.webhook_secret(st.tg.token)):
        return Response(status_code=403)
    try:
        update = json.loads(await request.body())
    except ValueError:
        return json_response({'ok': True})
    try:
        await run_in_threadpool(tgbot.handle_update, st.db, st.tg, update, st.public_url)
    except Exception:  # never make Telegram retry a poisoned update forever
        log.exception('telegram update failed')
    return json_response({'ok': True}, background=BackgroundTask(tgbot.flush_outbox, st.db, st.tg))


async def cron_daily(request):
    st = request.app.state
    secret = os.environ.get('CRON_SECRET', '')
    authorized = bool(secret) and hmac.compare_digest(request.headers.get('x-cron-secret', ''), secret)
    # The job is idempotent per day, so it may also be triggered without a secret in the morning window
    # (used by the free GitHub Actions schedule). Outside the window a secret is required.
    hour = now().astimezone(ZONE).hour
    if not authorized and not 8 <= hour < 11:
        return Response(status_code=404)
    if not st.tg:
        return json_response({'telegram': 'disabled'})
    result = await run_in_threadpool(tgbot.daily, st.db, st.tg)
    return json_response(result)


TG_CSP = ("default-src 'self'; script-src 'self' https://telegram.org; style-src 'self'; img-src 'self' data:; "
          "connect-src 'self'; frame-ancestors https://web.telegram.org https://*.telegram.org; base-uri 'none'")


async def tg_scan_page(request):
    return FileResponse(STATIC / 'tg' / 'scan.html', headers={'Cache-Control': 'no-cache', 'Content-Security-Policy': TG_CSP})


async def admin_index(request):
    return FileResponse(STATIC / 'index.html', headers={'Cache-Control': 'no-cache'})


SECURITY_HEADERS = [
    (b'x-content-type-options', b'nosniff'),
    (b'referrer-policy', b'no-referrer'),
    (b'x-frame-options', b'DENY'),
    (b'permissions-policy', b'camera=(self), microphone=(), geolocation=()'),
    (b'content-security-policy', b"default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; "
                                 b"connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"),
]


class SecurityHeaders:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        api_path = scope['path'].startswith('/api/')

        async def wrapped(message):
            if message['type'] == 'http.response.start':
                headers = list(message.get('headers', []))
                names = {k.lower() for k, _ in headers}
                skip = {b'x-frame-options'} if scope['path'].startswith('/tg/') else set()
                headers += [h for h in SECURITY_HEADERS if h[0] not in names and h[0] not in skip]
                if scope.get('scheme') == 'https' or os.environ.get('RENDER'):
                    headers.append((b'strict-transport-security', b'max-age=31536000'))
                if api_path and b'cache-control' not in names:
                    headers.append((b'cache-control', b'no-store'))
                message['headers'] = headers
            await send(message)
        await self.app(scope, receive, wrapped)


def bootstrap_superadmin(db, login_name, password, full_name='Администратор'):
    """Create the first superadmin if none exists. Never overwrites an existing account."""
    login_name = sec.normalize_login(login_name)
    sec.check_new_password(password)
    with db.conn() as c, c.transaction():
        c.execute('SELECT pg_advisory_xact_lock(724002)')
        if c.execute("SELECT 1 FROM users WHERE role='superadmin' LIMIT 1").fetchone():
            return False
        salt, verifier = sec.hash_password(password)
        row = c.execute("INSERT INTO users(role, login, salt, verifier, full_name) VALUES ('superadmin',%s,%s,%s,%s) RETURNING id",
                        (login_name, salt, verifier, full_name)).fetchone()
        c.execute("INSERT INTO audit_log(actor_id, action, entity, entity_id) VALUES (NULL, 'bootstrap_superadmin', 'user', %s)", (row['id'],))
        return True


def create_app(database_url=None, connect=None, migrate=True, telegram_api=None):
    url = database_url or os.environ.get('DATABASE_URL') or os.environ.get('KINDER_DATABASE_URL')
    if not url:
        raise SystemExit('DATABASE_URL is not set')
    db = Database(url, connect)
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    tg = telegram_api or (tgbot.TelegramAPI(token) if token else None)
    public_url = (os.environ.get('PUBLIC_URL') or os.environ.get('RENDER_EXTERNAL_URL') or '').rstrip('/')
    tgbot.PUBLIC_URL = public_url

    @asynccontextmanager
    async def lifespan(app):
        await startup()
        yield

    async def startup():
        if migrate:
            await run_in_threadpool(db.migrate)
        if tg and public_url:
            try:
                url = await run_in_threadpool(tgbot.setup_webhook, tg, public_url)
                log.warning('telegram webhook set: %s', url)
            except tgbot.TelegramError as err:
                log.error('telegram webhook setup failed: %s', err)
        login_name, password = os.environ.get('ADMIN_LOGIN'), os.environ.get('ADMIN_PASSWORD')
        if login_name and password:
            created = await run_in_threadpool(bootstrap_superadmin, db, login_name, password)
            log.warning('superadmin bootstrap: %s', 'created' if created else 'skipped (already exists)')

    routes = [Route('/health', health), Route('/', lambda r: RedirectResponse('/admin/')),
              Route('/admin', lambda r: RedirectResponse('/admin/')), Route('/admin/', admin_index),
              Mount('/admin/static', StaticFiles(directory=STATIC), name='static'),
              Route('/telegram/webhook', telegram_webhook, methods=['POST']),
              Route('/tg/scan', tg_scan_page),
              Mount('/tg/static', StaticFiles(directory=STATIC / 'tg'), name='tgstatic'),
              Route('/api/cron/daily', cron_daily, methods=['POST'])] + ROUTES
    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.db = db
    app.state.tg = tg
    app.state.public_url = public_url
    wrapped = SecurityHeaders(app)
    wrapped.state = app.state
    return wrapped


def asgi():
    logging.basicConfig(level=logging.INFO)
    return create_app()


from . import schedule  # noqa: E402,F401  (registers schedule routes)
from . import exports  # noqa: E402,F401  (registers export routes)
