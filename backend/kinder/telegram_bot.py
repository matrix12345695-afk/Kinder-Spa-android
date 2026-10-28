"""Private Kinder bot: version-fenced binding, typed actions and durable delivery.

No password login over Telegram, no automatic schema application, no token read.
All customer accounting goes through the existing transactional Store policies.
"""
from datetime import timedelta
import hashlib
import re
import secrets
import uuid

import psycopg
from psycopg.types.json import Jsonb

from .auth import Auth, Denied
from .store import Store, Rejected, token_hash


class Unbound(Exception):
    pass


TEXT = {
    'welcome': ('Kinder Spa 🩵\nАбонементы, записи и посещения.', 'Kinder Spa 🩵\nAbonementlar, yozuvlar va tashriflar.'),
    'connect': ('Для подключения получите одноразовую ссылку у администратора центра. Пароль сюда не отправляйте.', 'Ulanish uchun markaz administratoridan bir martalik havola oling. Parolni bu yerga yubormang.'),
    'denied': ('Запрос не принят. Проверьте привязку и права доступа.', 'So‘rov qabul qilinmadi. Ulanish va ruxsatlarni tekshiring.'),
    'empty': ('Записей нет в загруженной странице.', 'Yuklangan sahifada yozuvlar yo‘q.'),
    'scope': ('Показана одна страница (до 20 записей). Время: Ташкент.', 'Bitta sahifa ko‘rsatilgan (20 tagacha). Vaqt: Toshkent.'),
    'confirm': ('Подтвердите действие. Для бассейна возврат только при отмене строго до 19:00 предыдущего дня по времени Ташкента. Позже сеанс сгорает.', 'Amalni tasdiqlang. Basseyn seansi faqat oldingi kuni Toshkent vaqti bilan 19:00 dan oldin bekor qilinsa qaytariladi. Kechroq seans hisobdan chiqariladi.'),
    'restore': ('Восстановить сеанс? Причина сохранится в журнале; уведомление суперадминистратору будет поставлено в очередь.', 'Seans tiklansinmi? Sabab jurnalga yoziladi; superadministratorga bildirishnoma navbatga qo‘yiladi.'),
    'saved': ('Действие сохранено.', 'Amal saqlandi.'),
    'rejected': ('Действие не выполнено: оно истекло, уже обработано или не разрешено правилами.', 'Amal bajarilmadi: muddati tugagan, qayta ishlangan yoki qoidalarga zid.'),
    'unlink': ('Отключить этот Telegram от учётной записи?', 'Ushbu Telegramni hisobdan uzasizmi?'),
    'unlinked': ('Привязка отключена.', 'Ulanish uzildi.'),
    'cancelled': ('Действие отменено.', 'Amal bekor qilindi.'),
    'qr': ('Одноразовый QR. Действует до %s сек. Сервер проверяет срок и повторное использование. Сообщение может остаться в истории Telegram.', 'Bir martalik QR. %s soniyagacha amal qiladi. Server muddat va takroriy foydalanishni tekshiradi. Xabar Telegram tarixida qolishi mumkin.'),
    'help': ('/subscriptions — абонементы\n/bookings — записи\n/history — история\n/language ru или uz\n/unlink — отключить\nПароли и медицинские данные не отправляйте.', '/subscriptions — abonementlar\n/bookings — yozuvlar\n/history — tarix\n/language ru yoki uz\n/unlink — uzish\nParol va tibbiy ma’lumotlarni yubormang.'),
    'staff': ('\nСотруднику: пришлите фото только QR без людей или /redeem КОД.\n/restore ID причина (без медицинских данных). Ссылка клиенту: /link ID. Статусы доставки: /notifications. Создание клиентов и паролей — в веб-панели.', '\nXodim: faqat QR suratini odamlarsiz yuboring yoki /redeem KOD.\n/restore ID sabab (tibbiy ma’lumotsiz). Mijoz havolasi: /link ID. Yetkazish: /notifications. Mijoz va parollar veb-panelda yaratiladi.'),
}
CATEGORIES = {'pool': ('Бассейн', 'Basseyn'), 'massage': ('Детский массаж', 'Bolalar massaji'), 'hydromassage': ('Гидромассаж', 'Gidromassaj')}
STATES = {'reserved': ('Записан', 'Yozilgan'), 'consumed': ('Посещение учтено', 'Tashrif hisoblangan'),
          'cancelled': ('Отменено с возвратом', 'Qaytarib bekor qilingan'), 'forfeited': ('Сеанс списан', 'Seans hisobdan chiqarilgan'),
          'no_show': ('Неявка', 'Kelmagan'), 'restored': ('Восстановлен', 'Tiklangan')}


def tr(key, language='ru'):
    return TEXT[key][language == 'uz']


def bounded_id(value, *, zero=False):
    if type(value) is not int or not (0 if zero else 1)<=value<2**63:raise Rejected('invalid_identity')
    return value


def limits(conn):
    conn.execute("SET LOCAL lock_timeout TO '3s'")
    conn.execute("SET LOCAL statement_timeout TO '5s'")


def peer_update(update):
    """Telegram user IDs, never usernames, select identity. Groups/forwards denied."""
    if not isinstance(update, dict) or type(update.get('update_id')) is not int or not 0 <= update['update_id'] < 2**63-1:
        return None
    callback = update.get('callback_query')
    message = callback.get('message') if isinstance(callback, dict) else update.get('message')
    sender = callback.get('from') if isinstance(callback, dict) else message.get('from') if isinstance(message, dict) else None
    if not isinstance(message, dict) or not isinstance(sender, dict):
        return None
    chat = message.get('chat', {})
    if not isinstance(chat,dict):return None
    ident = sender.get('id')
    if (type(ident) is not int or not 0 < ident < 2**63-1 or sender.get('is_bot') is not False
            or chat.get('type') != 'private' or type(chat.get('id')) is not int or chat['id'] != ident
            or any(k in message for k in ('forward_origin','forward_from','via_bot','sender_chat'))):
        return None
    text = callback.get('data') if callback else message.get('text')
    if not callback and text is None and isinstance(message.get('photo'),list) and 1<=len(message['photo'])<=10:
        photos=message['photo']
        valid=[p for p in photos if isinstance(p,dict) and type(p.get('width')) is int and type(p.get('height')) is int
               and 50<=p['width']<=2048 and 50<=p['height']<=2048 and p['width']*p['height']<=4000000
               and isinstance(p.get('file_id'),str) and re.fullmatch(r'[A-Za-z0-9_-]{1,256}',p['file_id'])
               and type(p.get('file_size',0)) is int and 0<=p.get('file_size',0)<=2097152]
        if not valid:return None
        text='photo:'+max(valid,key=lambda p:p['width']*p['height'])['file_id']
    if not isinstance(text, str) or not 1 <= len(text) <= (64 if callback else 1024) or '\x00' in text:
        return None
    if callback and (not isinstance(callback.get('id'), str) or not 1 <= len(callback['id']) <= 256):
        return None
    return ident, text.strip(), callback


class Bot:
    def __init__(self, factory, *, clock=None, qr_reader=None):
        self.factory, self.clock, self.qr_reader = factory, clock, qr_reader

    def now(self, conn):
        return Store(conn, clock=self.clock)._now()

    def configure(self, bot_id, username=None):
        if type(bot_id) is not int or not 0 < bot_id < 2**63:
            raise ValueError('invalid_bot_identity')
        if username is not None and (not isinstance(username,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{4,31}',username)):raise ValueError('invalid_bot_username')
        with self.factory() as conn, conn.transaction():
            limits(conn)
            old = conn.execute('SELECT bot_id FROM telegram_runtime WHERE singleton=1 FOR UPDATE').fetchone()[0]
            if old is not None and old != bot_id:
                raise ValueError('different_bot_database')
            conn.execute('UPDATE telegram_runtime SET bot_id=%s,username=COALESCE(%s,username) WHERE singleton=1', (bot_id,username))

    def issue_link(self, token, client_id=None):
        """Trusted HTTPS account flow: self, or staff issuing a CLIENT link only."""
        with self.factory() as conn, conn.transaction():
            limits(conn)
            actor, role = Auth(conn, clock=self.clock).locked(token)
            target = actor if client_id is None else client_id
            if type(target) is not int or not 0 < target < 2**63:
                raise Denied()
            account = conn.execute('SELECT role,enabled FROM accounts WHERE id=%s FOR UPDATE', (target,)).fetchone()
            credential = conn.execute('SELECT version FROM credentials WHERE account_id=%s FOR SHARE', (target,)).fetchone()
            if not account or not account[1] or not credential or (target != actor and (role not in ('admin','superadmin') or account[0] != 'client')):
                raise Denied()
            raw = secrets.token_urlsafe(32)
            expires = self.now(conn)+timedelta(minutes=10)
            conn.execute('UPDATE telegram_link_codes SET revoked=true WHERE account_id=%s AND used_peer IS NULL', (target,))
            conn.execute('INSERT INTO telegram_link_codes(code_hash,account_id,credential_version,expires_at) VALUES(%s,%s,%s,%s)',
                         (token_hash(raw), target, credential[0], expires))
            Store(conn, clock=self.clock)._audit(actor, 'telegram_link_issued', target, self.now(conn), {})
            return self.link_result(conn,raw,expires)

    def link_result(self, conn, raw, expires):
        result={'start_payload':'link_'+raw,'expires_at':expires.isoformat(),'valid_for_seconds':600}
        username=conn.execute('SELECT username FROM telegram_runtime WHERE singleton=1').fetchone()[0]
        if username:result['url']='https://t.me/'+username+'?start=link_'+raw
        return result

    def issue_client_link(self, who, client):
        bounded_id(client)
        with self.factory() as conn,conn.transaction():
            limits(conn);who=self.identity(conn,who['peer'],who['id'])
            if who['role']=='client':raise Unbound()
            account=conn.execute('SELECT role,enabled FROM accounts WHERE id=%s FOR UPDATE',(client,)).fetchone()
            credential=conn.execute('SELECT version FROM credentials WHERE account_id=%s FOR SHARE',(client,)).fetchone()
            if account!=('client',True) or not credential:raise Rejected('client_unavailable')
            if conn.execute('SELECT EXISTS(SELECT 1 FROM telegram_bindings WHERE account_id=%s AND active AND credential_version=%s)',(client,credential[0])).fetchone()[0]:raise Rejected('already_bound')
            raw=secrets.token_urlsafe(32);expires=self.now(conn)+timedelta(minutes=10)
            conn.execute('UPDATE telegram_link_codes SET revoked=true WHERE account_id=%s AND used_peer IS NULL',(client,))
            conn.execute('INSERT INTO telegram_link_codes(code_hash,account_id,credential_version,expires_at) VALUES(%s,%s,%s,%s)',(token_hash(raw),client,credential[0],expires))
            Store(conn,clock=self.clock)._audit(who['account'],'telegram_link_issued',client,self.now(conn),{})
            return self.link_result(conn,raw,expires)

    def identity(self, conn, peer, expected=None):
        pointer = conn.execute('SELECT id,account_id FROM telegram_bindings WHERE peer_id=%s AND active', (peer,)).fetchone()
        if not pointer or (expected is not None and pointer[0] != expected):
            raise Unbound()
        account = conn.execute('SELECT role,enabled FROM accounts WHERE id=%s FOR SHARE', (pointer[1],)).fetchone()
        version = conn.execute('SELECT version FROM credentials WHERE account_id=%s FOR SHARE', (pointer[1],)).fetchone()
        binding = conn.execute('''SELECT id,account_id,credential_version,peer_id,language,active FROM telegram_bindings
            WHERE id=%s FOR SHARE''', (pointer[0],)).fetchone()
        if not account or not account[1] or not version or not binding or not binding[5] or binding[3] != peer or binding[2] != version[0]:
            raise Unbound()
        return {'id':binding[0], 'account':binding[1], 'peer':peer, 'role':account[0], 'language':binding[4]}

    def guard(self, who):
        def authorize(conn, actor):
            current = self.identity(conn, who['peer'], who['id'])
            if actor != current['account']:
                raise Unbound()
        return authorize

    def bind(self, peer, update_id, raw):
        hashed = token_hash(raw)
        with self.factory() as conn, conn.transaction():
            limits(conn)
            pointer = conn.execute('SELECT account_id FROM telegram_link_codes WHERE code_hash=%s', (hashed,)).fetchone()
            if not pointer:
                raise Unbound()
            account = conn.execute('SELECT role,enabled FROM accounts WHERE id=%s FOR UPDATE', (pointer[0],)).fetchone()
            credential = conn.execute('SELECT version FROM credentials WHERE account_id=%s FOR SHARE', (pointer[0],)).fetchone()
            code = conn.execute('SELECT credential_version,expires_at,used_peer,used_update,revoked FROM telegram_link_codes WHERE code_hash=%s FOR UPDATE', (hashed,)).fetchone()
            if not account or not account[1] or not credential or not code or code[4] or code[0] != credential[0]:
                raise Unbound()
            if code[2] is not None:
                if (code[2], code[3]) != (peer, update_id):
                    raise Unbound()
                return self.identity(conn, peer)
            if self.now(conn) >= code[1]:
                raise Unbound()
            existing = conn.execute('SELECT id,account_id,peer_id,credential_version FROM telegram_bindings WHERE active AND (account_id=%s OR peer_id=%s) FOR UPDATE', (pointer[0], peer)).fetchall()
            # No silent takeover of an already active association, including self-rebind.
            for row in existing:
                current_version = conn.execute('SELECT version FROM credentials WHERE account_id=%s', (row[1],)).fetchone()[0]
                if row[3] == current_version:
                    raise Unbound()
                conn.execute('UPDATE telegram_bindings SET active=false WHERE id=%s', (row[0],))
            conn.execute('INSERT INTO telegram_bindings(account_id,credential_version,peer_id,created_at) VALUES(%s,%s,%s,%s)', (pointer[0], credential[0], peer, self.now(conn)))
            conn.execute('UPDATE telegram_link_codes SET used_peer=%s,used_update=%s WHERE code_hash=%s', (peer, update_id, hashed))
            Store(conn, clock=self.clock)._audit(pointer[0], 'telegram_bound', pointer[0], self.now(conn), {})
            return self.identity(conn, peer)

    def enqueue(self, conn, dedup, peer, payload, *, who=None, kind='text', outbox=None):
        payload=dict(payload)
        if who:payload['_role']=who['role']
        conn.execute('''INSERT INTO telegram_jobs(dedup,peer_id,binding_id,outbox_id,kind,payload,next_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(dedup) DO NOTHING''',
                     (dedup, peer, who['id'] if who else None, outbox, kind, Jsonb(payload), self.now(conn)))

    def reply(self, update, peer, text, *, who=None, keyboard=None, kind='text', payload=None):
        value = payload or {'text':text[:3500], 'public':who is None}
        if keyboard:
            value['reply_markup'] = keyboard
        with self.factory() as conn, conn.transaction():
            limits(conn)
            self.enqueue(conn, 'update_'+str(update), peer, value, who=who, kind=kind)

    def menu(self, who):
        uz = who['language'] == 'uz'
        rows=[[{'text':'📘 Abonementlar' if uz else '📘 Абонементы'}, {'text':'🗓 Yozuvlar' if uz else '🗓 Записи'}],
                            [{'text':'📚 Tarix' if uz else '📚 История'}, {'text':'ℹ️ Yordam' if uz else 'ℹ️ Помощь'}],
                            [{'text':'/language ru'}, {'text':'/language uz'}]]
        if who['role']!='client':rows.append([{'text':'🔔 Bildirishnomalar' if uz else '🔔 Уведомления'}])
        return {'keyboard':rows,'resize_keyboard':True}

    def read(self, who, command, after=0):
        bounded_id(after,zero=True)
        from zoneinfo import ZoneInfo
        with self.factory() as conn, conn.transaction():
            limits(conn)
            who=self.identity(conn, who['peer'], who['id'])
            staff = who['role'] != 'client'
            language = who['language']
            buttons = []
            if command == 'subscriptions':
                rows = conn.execute('''SELECT s.id,a.category,a.remaining,a.quota FROM
                    (SELECT id FROM subscriptions WHERE id>%s AND (%s OR client_id=%s) ORDER BY id LIMIT 20) s
                    JOIN allowances a ON a.subscription_id=s.id ORDER BY s.id,a.category''', (after, staff, who['account'])).fetchall()
                lines = [f"№{sub} · {CATEGORIES[cat][language=='uz']}: {remaining}/{quota}" for sub,cat,remaining,quota in rows]
                last = max((r[0] for r in rows), default=0)
                more = len({r[0] for r in rows}) == 20
            else:
                rows = conn.execute('''SELECT b.id,b.category,b.starts_at,b.state FROM bookings b
                    JOIN subscriptions s ON s.id=b.subscription_id WHERE b.id>%s AND (%s OR s.client_id=%s)
                    AND (b.state='reserved')=%s ORDER BY b.id LIMIT 20''', (after, staff, who['account'], command == 'bookings')).fetchall()
                lines = []
                for ident,category,start,state in rows:
                    label = CATEGORIES[category][language=='uz']
                    lines.append(f"№{ident} · {label}\n{start.astimezone(ZoneInfo('Asia/Tashkent')):%d.%m.%Y %H:%M} · {STATES[state][language=='uz']}")
                    if state == 'reserved':
                        row = [{'text':f'QR №{ident}', 'callback_data':'qr:'+str(ident)}]
                        if category == 'pool':
                            row.append({'text':('Bekor qilish' if language=='uz' else 'Отменить')+' №'+str(ident), 'callback_data':'cancel:'+str(ident)})
                        buttons.append(row)
                last = rows[-1][0] if rows else 0
                more = len(rows) == 20
            if more:
                buttons.append([{'text':'Yana' if language=='uz' else 'Дальше', 'callback_data':f'page:{command}:{last}'}])
            text = '\n\n'.join(lines) if lines else tr('empty', language)
            return (text+'\n\n'+tr('scope',language))[:3500], {'inline_keyboard':buttons} if buttons else None

    def ask(self, who, update_id, kind, booking=None, reason=None, qr_hash=None):
        if kind!='unlink':bounded_id(booking)
        if reason is not None:
            try:reason.encode('utf8')
            except (AttributeError,UnicodeError):raise Rejected('invalid_reason') from None
        if kind == 'restore' and (who['role']=='client' or not isinstance(reason,str) or not 5 <= len(reason.strip()) <= 500 or any(ord(c)<32 for c in reason)):
            raise Rejected('invalid_restore')
        with self.factory() as conn, conn.transaction():
            limits(conn)
            who=self.identity(conn,who['peer'],who['id'])
            if kind in ('restore','redeem') and who['role']=='client':raise Rejected('staff_only')
            if kind != 'unlink':
                row = conn.execute('''SELECT b.category,b.state,s.client_id FROM bookings b JOIN subscriptions s ON s.id=b.subscription_id WHERE b.id=%s''', (booking,)).fetchone()
                if (not row or (who['role']=='client' and row[2]!=who['account'])
                        or (kind in ('cancel','restore') and row[0]!='pool') or (kind in ('cancel','redeem') and row[1]!='reserved')
                        or (kind=='restore' and row[1] not in ('forfeited','no_show')) or (kind=='redeem' and who['role']=='client')):
                    raise Rejected('operation_rejected')
            expires=self.now(conn)+timedelta(minutes=5)
            if kind=='redeem':
                if not isinstance(qr_hash,str) or not re.fullmatch('[0-9a-f]{64}',qr_hash):raise Rejected('invalid_qr')
                qr=conn.execute('SELECT expires_at FROM qr_tokens WHERE token_hash=%s AND booking_id=%s AND used_at IS NULL AND NOT revoked',(qr_hash,booking)).fetchone()
                if not qr or self.now(conn)>=qr[0]:raise Rejected('invalid_qr')
                expires=min(expires,qr[0])
            action = uuid.uuid4()
            conn.execute('''INSERT INTO telegram_actions(id,binding_id,update_id,kind,booking_id,reason,qr_hash,expires_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(update_id) DO NOTHING''',
                         (action,who['id'],update_id,kind,booking,reason.strip() if reason else None,qr_hash,expires))
            action = conn.execute('SELECT id FROM telegram_actions WHERE update_id=%s AND binding_id=%s', (update_id,who['id'])).fetchone()[0]
            keyboard={'inline_keyboard':[[{'text':'Tasdiqlash' if who['language']=='uz' else 'Подтвердить','callback_data':'do:'+str(action)},
                                         {'text':'Orqaga' if who['language']=='uz' else 'Назад','callback_data':'no:'+str(action)}]]}
            text = (('Подтвердить учёт посещения?' if who['language']=='ru' else 'Tashrif hisoblansinmi?') if kind=='redeem' else tr('unlink' if kind=='unlink' else 'restore' if kind=='restore' else 'confirm',who['language']))
            if booking:
                text += '\n№'+str(booking)
            self.enqueue(conn,'update_'+str(update_id),who['peer'],{'text':text,'reply_markup':keyboard},who=who)

    def resolve_qr(self, who, raw):
        if who['role']=='client':raise Rejected('staff_only')
        hashed=token_hash(raw)
        with self.factory() as conn,conn.transaction():
            limits(conn);who=self.identity(conn,who['peer'],who['id'])
            if who['role']=='client':raise Rejected('staff_only')
            row=conn.execute('SELECT booking_id FROM qr_tokens WHERE token_hash=%s',(hashed,)).fetchone()
            if not row:raise Rejected('invalid_qr')
            return row[0],hashed

    def confirm(self, who, ident, approved, response_update=None):
        action_id=uuid.UUID(ident)
        lock_key=int.from_bytes(hashlib.sha256(action_id.bytes).digest()[:8],'big')&((1<<63)-1)
        with self.factory() as lock:
            # Session lock spans Store's own transaction; no/yes cannot race.
            if not lock.execute('SELECT pg_try_advisory_lock(%s)',(lock_key,)).fetchone()[0]:
                raise Rejected('action_busy')
            with lock.transaction():
                limits(lock);self.identity(lock,who['peer'],who['id'])
                row=lock.execute('SELECT kind,booking_id,reason,qr_hash,expires_at,state FROM telegram_actions WHERE id=%s AND binding_id=%s FOR UPDATE',(action_id,who['id'])).fetchone()
                if not row:raise Rejected('action_not_pending')
                if row[5]=='applied':return ('unlinked' if row[0]=='unlink' else 'saved'),row[0]=='unlink'
                if row[5]=='rejected':return 'cancelled',False
                if self.now(lock)>=row[4]:raise Rejected('action_expired')
                if not approved:
                    lock.execute("UPDATE telegram_actions SET state='rejected' WHERE id=%s",(action_id,))
                    return 'cancelled',False
                kind,booking,reason,qr_hash=row[:4]
                if kind=='unlink':
                    lock.execute('UPDATE telegram_bindings SET active=false WHERE id=%s',(who['id'],))
                    lock.execute("UPDATE telegram_actions SET state='applied' WHERE id=%s",(action_id,))
                    Store(lock,clock=self.clock)._audit(who['account'],'telegram_unlinked',who['account'],self.now(lock),{})
                    if response_update is not None:self.enqueue(lock,'update_'+str(response_update),who['peer'],{'text':tr('unlinked',who['language']),'public':True})
                    return 'unlinked',True
            bot=self
            class ActionStore(Store):
                def _command(self,actor,operation,key,request,apply,*,staff=False):
                    def atomic(role):
                        result=apply(role)
                        self.conn.execute("UPDATE telegram_actions SET state='applied' WHERE id=%s AND state='pending'",(action_id,))
                        return result
                    return super()._command(actor,operation,key,request,atomic,staff=staff)
            def authorize(conn, actor):
                bot.guard(who)(conn,actor)
                current=conn.execute('SELECT state,expires_at FROM telegram_actions WHERE id=%s FOR SHARE',(action_id,)).fetchone()
                if not current or current[0]!='pending' or bot.now(conn)>=current[1]:raise Rejected('action_expired')
            with self.factory() as conn:
                store=ActionStore(conn,clock=self.clock,authorize=authorize);key='telegram_'+action_id.hex
                if kind=='cancel':store.cancel_pool(who['account'],booking,key)
                elif kind=='restore':store.restore_pool(who['account'],booking,reason,key)
                elif kind=='redeem':store._redeem_hashed(who['account'],booking,qr_hash,key)
                else:raise Rejected('unsupported_action')
            return 'saved',False

    def process(self, update):
        parsed=peer_update(update)
        if not parsed:return False
        peer,text,callback=parsed;uid=update['update_id']
        with self.factory() as conn:
            prior=conn.execute('SELECT peer_id,done FROM telegram_updates WHERE update_id=%s',(uid,)).fetchone()
            if prior:
                if prior[0]!=peer:raise Unbound()
                if prior[1]:return True
            if callback:
                bot_id=conn.execute('SELECT bot_id FROM telegram_runtime WHERE singleton=1').fetchone()[0]
                if callback['message'].get('from',{}).get('id')!=bot_id:return False
        who=None
        try:
            if not callback and re.fullmatch(r'/start link_[A-Za-z0-9_-]{43}',text):
                who=self.bind(peer,uid,text[len('/start link_'):])
                self.reply(uid,peer,tr('welcome',who['language']),who=who,keyboard=self.menu(who))
            else:
                with self.factory() as conn,conn.transaction():
                    limits(conn);who=self.identity(conn,peer)
                language=who['language']
                aliases={'📘 Абонементы':'/subscriptions','📘 Abonementlar':'/subscriptions','🗓 Записи':'/bookings','🗓 Yozuvlar':'/bookings',
                         '📚 История':'/history','📚 Tarix':'/history','ℹ️ Помощь':'/help','ℹ️ Yordam':'/help',
                         '🔔 Уведомления':'/notifications','🔔 Bildirishnomalar':'/notifications'}
                text=aliases.get(text,text)
                if callback and re.fullmatch(r'(do|no):[0-9a-f-]{36}',text):
                    response,public=self.confirm(who,text[3:],text.startswith('do:'),uid)
                    self.reply(uid,peer,tr(response,language),who=None if public else who)
                elif callback and re.fullmatch(r'page:(subscriptions|bookings|history):[1-9][0-9]{0,18}',text):
                    _,command,after=text.split(':');content,keyboard=self.read(who,command,int(after))
                    self.reply(uid,peer,content,who=who,keyboard=keyboard)
                elif (callback and re.fullmatch(r'(qr|cancel):[1-9][0-9]{0,18}',text)) or (not callback and re.fullmatch(r'/(qr|cancel) [1-9][0-9]{0,18}',text)):
                    command,booking=text.replace(':',' ').lstrip('/').split();booking=bounded_id(int(booking))
                    if command=='cancel':self.ask(who,uid,'cancel',booking)
                    else:self.reply(uid,peer,'',who=who,kind='qr',payload={'booking_id':booking})
                elif not callback and (text.startswith('photo:') or text.startswith('/redeem ')):
                    if who['role']=='client':raise Rejected('staff_only')
                    if text.startswith('photo:'):
                        if self.qr_reader is None:raise Rejected('photo_reader_not_configured')
                        raw=self.qr_reader(text[6:])
                    else:raw=text[len('/redeem '):]
                    booking,hashed=self.resolve_qr(who,raw)
                    self.ask(who,uid,'redeem',booking,qr_hash=hashed)
                elif not callback and text.startswith('/link '):
                    if who['role']=='client':raise Rejected('staff_only')
                    client=bounded_id(int(text[len('/link '):]));self.reply(uid,peer,'',who=who,kind='link',payload={'client_id':client})
                elif not callback and text=='/notifications':
                    if who['role']=='client':raise Rejected('staff_only')
                    with self.factory() as conn,conn.transaction():
                        limits(conn);current=self.identity(conn,peer,who['id'])
                        if current['role']=='client':raise Unbound()
                        waiting=conn.execute('SELECT count(*) FROM notification_outbox o WHERE NOT EXISTS (SELECT 1 FROM telegram_notification_batches b WHERE b.outbox_id=o.id)').fetchone()[0]
                        states=conn.execute('SELECT state,count(*) FROM telegram_jobs WHERE outbox_id IS NOT NULL GROUP BY state ORDER BY state').fetchall()
                    labels={'pending':('Ожидают отправки','Yuborishni kutmoqda'),'leased':('Отправляются, подтверждения ещё нет','Yuborilmoqda, tasdiq hali yo‘q'),
                            'delivered':('Telegram подтвердил приём','Telegram qabul qilgan'),'failed':('Нужна проверка ошибки','Xatoni tekshirish kerak'),
                            'blocked':('Нужно проверить привязку и права','Ulanish va ruxsatlarni tekshiring')}
                    text=('Ожидают получателя: ' if language=='ru' else 'Oluvchini kutmoqda: ')+str(waiting)
                    text+='\n'+'\n'.join(labels[state][language=='uz']+': '+str(count) for state,count in states)
                    self.reply(uid,peer,text,who=who)
                elif not callback and text.startswith('/restore '):
                    _,booking,reason=text.split(' ',2);self.ask(who,uid,'restore',int(booking),reason)
                elif not callback and text=='/unlink':self.ask(who,uid,'unlink')
                elif not callback and text in ('/subscriptions','/bookings','/history'):
                    content,keyboard=self.read(who,text[1:]);self.reply(uid,peer,content,who=who,keyboard=keyboard)
                elif not callback and text in ('/language ru','/language uz'):
                    language=text[-2:]
                    with self.factory() as conn,conn.transaction():
                        limits(conn);self.identity(conn,peer,who['id']);conn.execute('UPDATE telegram_bindings SET language=%s WHERE id=%s',(language,who['id']))
                    who['language']=language;self.reply(uid,peer,tr('welcome',language),who=who,keyboard=self.menu(who))
                elif not callback and text in ('/start','/menu','/help','/status'):
                    self.reply(uid,peer,tr('help',language)+(tr('staff',language) if who['role']!='client' else ''),who=who,keyboard=self.menu(who))
                else:raise Rejected('unsupported_command')
        except (Unbound,Denied,Rejected,ValueError,TypeError):
            self.reply(uid,peer,tr('denied' if who else 'connect',who['language'] if who else 'ru'),who=who)
        with self.factory() as conn,conn.transaction():
            limits(conn)
            conn.execute('INSERT INTO telegram_updates(update_id,peer_id) VALUES(%s,%s) ON CONFLICT DO NOTHING',(uid,peer))
        return True

    def fanout(self):
        """Snapshot current credential-valid superadmins, with one durable job per target."""
        made=0
        with self.factory() as conn,conn.transaction():
            limits(conn)
            rows=conn.execute('''SELECT o.id,o.event_id,a.actor_id,a.entity_id,a.details FROM notification_outbox o
                JOIN audit_events a ON a.id=o.event_id WHERE NOT EXISTS
                (SELECT 1 FROM telegram_notification_batches b WHERE b.outbox_id=o.id)
                ORDER BY o.id LIMIT 20 FOR UPDATE OF o SKIP LOCKED''').fetchall()
            for outbox,event,actor,booking,details in rows:
                recipients=conn.execute('''SELECT b.peer_id FROM telegram_bindings b JOIN accounts a ON a.id=b.account_id
                    JOIN credentials c ON c.account_id=a.id WHERE b.active AND a.enabled AND a.role='superadmin'
                    AND b.credential_version=c.version ORDER BY b.id LIMIT 51''').fetchall()
                if not recipients:continue
                if len(recipients)>50:raise Rejected('recipient_limit_requires_review')
                for peer, in recipients:
                    who=self.identity(conn,peer)
                    if who['role']!='superadmin':raise Unbound()
                    text=(f'🔔 Kinder Spa\nСеанс восстановлен\nСобытие №{event} · запись №{booking}\nСотрудник №{actor}\nОсталось: {details["remaining"]}\nПричина сохранена в журнале.\nДоставка не означает одобрение.' if who['language']=='ru' else
                          f'🔔 Kinder Spa\nSeans tiklandi\nHodisa №{event} · yozuv №{booking}\nXodim №{actor}\nQoldiq: {details["remaining"]}\nSabab jurnalda saqlangan.\nYetkazish tasdiqlashni anglatmaydi.')
                    self.enqueue(conn,f'event_{outbox}_binding_{who["id"]}',peer,{'text':text},who=who,outbox=outbox);made+=1
                conn.execute('INSERT INTO telegram_notification_batches VALUES(%s,%s)',(outbox,self.now(conn)))
        return made
