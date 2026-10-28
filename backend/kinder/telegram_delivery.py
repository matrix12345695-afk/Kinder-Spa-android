"""Leased, bounded Telegram delivery; private authority is rechecked at send time."""
from datetime import datetime,timedelta
import binascii
import hashlib
import io
import json
import re
import struct
import os
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
import zlib

from .store import Store, Rejected
from .telegram_bot import Unbound, limits, tr


class TelegramFailure(Exception):
    def __init__(self, code=0, retry_after=0):
        super().__init__('telegram_request_failed')
        self.code = code if type(code) is int and 0 <= code <= 599 else 0
        self.retry_after = min(max(retry_after, 0), 3600) if type(retry_after) is int else 0


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class TelegramAPI:
    """Fixed HTTPS host/method allowlist; exceptions never include token-bearing URLs."""
    def __init__(self, token, *, opener=None):
        if not isinstance(token,str) or not re.fullmatch(r'[1-9][0-9]{4,19}:[A-Za-z0-9_-]{30,100}', token):
            raise ValueError('invalid_telegram_token')
        self._base = 'https://api.telegram.org/bot'+token+'/'
        self._file_base = 'https://api.telegram.org/file/bot'+token+'/'
        self._opener = opener or urllib.request.build_opener(NoRedirect())

    def call(self, method, value, *, photo=None):
        if method not in ('getMe','getWebhookInfo','getUpdates','getFile','sendMessage','sendPhoto','deleteMessage','answerCallbackQuery'):
            raise TelegramFailure()
        if photo is None:
            raw=json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()
            content_type='application/json'
        else:
            if method!='sendPhoto' or not isinstance(photo,bytes) or len(photo)>200000:
                raise TelegramFailure()
            boundary='kinder_'+uuid.uuid4().hex
            blocks=[]
            for key,item in value.items():
                if not re.fullmatch('[a-z_]+',key):raise TelegramFailure()
                blocks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{item}\r\n'.encode())
            blocks.extend([f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="visit-qr.png"\r\nContent-Type: image/png\r\n\r\n'.encode(),photo,f'\r\n--{boundary}--\r\n'.encode()])
            raw=b''.join(blocks);content_type='multipart/form-data; boundary='+boundary
        if len(raw)>262144:raise TelegramFailure()
        request=urllib.request.Request(self._base+method,data=raw,headers={'Content-Type':content_type,'Accept':'application/json'})
        try:
            try:
                response=self._opener.open(request,timeout=15 if method=='getUpdates' else 8)
            except urllib.error.HTTPError as error:
                response=error
            with response:
                code=response.getcode()
                if code is not None and 300<=code<400:raise TelegramFailure(code)
                raw=response.read(1024*1024+1)
                if len(raw)>1024*1024:raise TelegramFailure()
            data=json.loads(raw)
            if not isinstance(data,dict) or type(data.get('ok')) is not bool:raise TelegramFailure()
            if not data['ok']:
                raise TelegramFailure(data.get('error_code',0),data.get('parameters',{}).get('retry_after',0))
            if code!=200 or 'result' not in data:raise TelegramFailure()
            return data['result']
        except TelegramFailure:raise
        except Exception:raise TelegramFailure() from None

    def read_photo_qr(self, file_id):
        if not isinstance(file_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,256}',file_id):raise Rejected('invalid_photo')
        info=self.call('getFile',{'file_id':file_id})
        if (not isinstance(info,dict) or info.get('file_id')!=file_id or type(info.get('file_size')) is not int
                or not 0<info['file_size']<=2097152 or not isinstance(info.get('file_path'),str)
                or not re.fullmatch(r'photos/[A-Za-z0-9_-]+\.(jpg|jpeg|png)',info['file_path'])):raise Rejected('invalid_photo')
        try:
            with self._opener.open(urllib.request.Request(self._file_base+info['file_path']),timeout=8) as response:
                if response.getcode()!=200:raise TelegramFailure()
                raw=response.read(2097153)
            if len(raw)>2097152 or len(raw)!=info['file_size']:raise Rejected('invalid_photo')
        except Rejected:raise
        except Exception:raise TelegramFailure() from None
        return decode_photo(raw)


def decode_photo(raw):
    if not isinstance(raw,bytes) or len(raw)>2097152:raise Rejected('invalid_photo')
    # The child receives neither the bot token nor the DSN/environment secrets.
    env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONPATH':str(Path(__file__).resolve().parents[1])}
    try:
        result=subprocess.run([sys.executable,'-m','kinder.qr_decode'],input=raw,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                              timeout=4,env=env,check=False)
        value=result.stdout.decode('ascii')
        if result.returncode!=0 or not re.fullmatch(r'[A-Za-z0-9_-]{43}',value):raise Rejected('invalid_photo')
        return value
    except Rejected:raise
    except Exception:raise Rejected('invalid_photo') from None


def qr_png(token):
    """QR matrix by pinned BSD-licensed qrcode; bounded PNG encoding uses stdlib."""
    import qrcode
    if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):
        raise Rejected('invalid_qr')
    qr=qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,border=4,box_size=8)
    qr.add_data(token);qr.make(fit=True);matrix=qr.get_matrix();scale=8
    side=len(matrix)*scale
    if side>512:raise Rejected('qr_oversize')
    rows=[]
    for row in matrix:
        expanded=b''.join((b'\0' if cell else b'\xff')*scale for cell in row)
        rows.extend([b'\0'+expanded]*scale)
    def chunk(kind,value):
        return struct.pack('!I',len(value))+kind+value+struct.pack('!I',binascii.crc32(kind+value)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!IIBBBBB',side,side,8,0,0,0,0))+chunk(b'IDAT',zlib.compress(b''.join(rows)))+chunk(b'IEND',b'')


class Sender:
    def __init__(self, bot, api):
        self.bot,self.api=bot,api

    def claim(self):
        with self.bot.factory() as conn,conn.transaction():
            limits(conn);now=self.bot.now(conn)
            conn.execute("UPDATE telegram_jobs SET state='failed',error_code=408 WHERE state='leased' AND lease_until<=%s AND attempts>=8",(now,))
            row=conn.execute('''SELECT id,peer_id,binding_id,outbox_id,kind,payload FROM telegram_jobs
                WHERE attempts<8 AND ((state='pending' AND next_at<=%s) OR (state='leased' AND lease_until<=%s))
                ORDER BY CASE WHEN outbox_id IS NULL THEN 1 ELSE 0 END,id LIMIT 1 FOR UPDATE SKIP LOCKED''',(now,now)).fetchone()
            if not row:return None
            lease=uuid.uuid4()
            conn.execute("UPDATE telegram_jobs SET state='leased',attempts=attempts+1,lease_id=%s,lease_until=%s WHERE id=%s",(lease,now+timedelta(seconds=45),row[0]))
            return dict(zip(('id','peer','binding','outbox','kind','payload'),row))|{'lease':lease}

    def fail(self, job, code, retry_after=0, *, blocked=False):
        with self.bot.factory() as conn,conn.transaction():
            limits(conn)
            row=conn.execute('SELECT attempts FROM telegram_jobs WHERE id=%s AND lease_id=%s AND state=\'leased\' FOR UPDATE',(job['id'],job['lease'])).fetchone()
            if not row:return False
            terminal=blocked or code in (400,401,403,404,409) or row[0]>=8
            state='blocked' if blocked else 'failed' if terminal else 'pending'
            delay=max(retry_after,min(3600,2**min(row[0],10)*5))
            conn.execute('UPDATE telegram_jobs SET state=%s,error_code=%s,next_at=%s,lease_until=NULL WHERE id=%s',
                         (state,code,self.bot.now(conn)+timedelta(seconds=delay),job['id']))
            return True

    def send_one(self):
        job=self.claim()
        if not job:return False
        try:
            photo=None;seconds=0;expiry=None;link_text=None
            if job['kind']=='link':
                with self.bot.factory() as conn,conn.transaction():
                    limits(conn);who=self.bot.identity(conn,job['peer'],job['binding'])
                    if who['role']!=job['payload'].get('_role'):raise Unbound()
                result=self.bot.issue_client_link(who,job['payload']['client_id'])
                link_text=('Одноразовая ссылка клиенту (10 минут):\n' if who['language']=='ru' else 'Mijoz uchun bir martalik havola (10 daqiqa):\n')+(result.get('url') or '/start '+result['start_payload'])
            if job['kind']=='qr':
                with self.bot.factory() as conn,conn.transaction():
                    limits(conn);who=self.bot.identity(conn,job['peer'],job['binding'])
                    if who['role']!=job['payload'].get('_role'):raise Unbound()
                with self.bot.factory() as conn:
                    result=Store(conn,clock=self.bot.clock,authorize=self.bot.guard(who)).issue_qr(who['account'],job['payload']['booking_id'])
                photo=qr_png(result.pop('token'));seconds=result['valid_for_seconds'];expiry=datetime.fromisoformat(result['expires_at'])
                if seconds<=1:raise Rejected('qr_expired')
            with self.bot.factory() as conn,conn.transaction():
                limits(conn)
                # Fence the lease and hold account/credential/binding authority through
                # bounded HTTP, so revocation cannot commit before a private send.
                conn.execute("SET LOCAL idle_in_transaction_session_timeout TO '12s'")
                active=conn.execute("SELECT id FROM telegram_jobs WHERE id=%s AND lease_id=%s AND state='leased' AND lease_until>%s FOR UPDATE",
                                    (job['id'],job['lease'],self.bot.now(conn))).fetchone()
                if not active:return True
                who=self.bot.identity(conn,job['peer'],job['binding']) if job['binding'] is not None else None
                if who and who['role']!=job['payload'].get('_role'):raise Unbound()
                if job['outbox'] is not None and (not who or who['role']!='superadmin'):raise Unbound()
                if photo:
                    response=self.api.call('sendPhoto',{'chat_id':job['peer'],'caption':tr('qr',who['language'])%seconds,'protect_content':'true'},photo=photo)
                else:
                    value={'chat_id':job['peer'],'text':link_text or job['payload']['text'],'protect_content':True}
                    if 'reply_markup' in job['payload']:value['reply_markup']=job['payload']['reply_markup']
                    response=self.api.call('sendMessage',value)
                if (not isinstance(response,dict) or type(response.get('message_id')) is not int or response['message_id']<=0
                        or response.get('chat',{}).get('id')!=job['peer']):raise TelegramFailure()
                conn.execute("UPDATE telegram_jobs SET state='delivered',message_id=%s,error_code=NULL,lease_until=NULL WHERE id=%s",(response['message_id'],job['id']))
                if photo:
                    conn.execute('INSERT INTO telegram_qr_cleanup VALUES(%s,%s,%s,0,false) ON CONFLICT DO NOTHING',
                                 (job['peer'],response['message_id'],expiry))
            return True
        except Unbound:self.fail(job,403,blocked=True)
        except (Rejected,KeyError,ValueError):
            self.fail(job,409)
            if job['kind'] in ('qr','link'):
                with self.bot.factory() as conn,conn.transaction():
                    limits(conn)
                    try:current=self.bot.identity(conn,job['peer'],job['binding'])
                    except Unbound:return True
                    self.bot.enqueue(conn,'qr_error_'+str(job['id']),job['peer'],{'text':tr('rejected',current['language'])},who=current)
        except TelegramFailure as error:self.fail(job,error.code,error.retry_after)
        # Unexpected database failures propagate: lease expiry recovers the job;
        # unconfirmed network success can duplicate delivery, never imply approval.
        return True

    def cleanup_one(self):
        with self.bot.factory() as conn,conn.transaction():
            limits(conn);now=self.bot.now(conn)
            row=conn.execute('''SELECT peer_id,message_id,attempts FROM telegram_qr_cleanup WHERE NOT done
                AND attempts<8 AND delete_at<=%s ORDER BY delete_at LIMIT 1 FOR UPDATE SKIP LOCKED''',(now,)).fetchone()
            if not row:return False
            try:
                if self.api.call('deleteMessage',{'chat_id':row[0],'message_id':row[1]}) is not True:raise TelegramFailure()
                conn.execute('UPDATE telegram_qr_cleanup SET done=true,attempts=attempts+1 WHERE peer_id=%s AND message_id=%s',row[:2])
            except TelegramFailure as error:
                conn.execute('UPDATE telegram_qr_cleanup SET attempts=attempts+1,delete_at=%s WHERE peer_id=%s AND message_id=%s',
                             (now+timedelta(seconds=max(error.retry_after,60)),row[0],row[1]))
            return True


def poll_once(bot, api, sender):
    """One admitted polling cycle. Production runner additionally holds a DB lock."""
    with bot.factory() as conn:
        offset=conn.execute('SELECT next_offset FROM telegram_runtime WHERE singleton=1').fetchone()[0]
    updates=api.call('getUpdates',{'offset':offset,'limit':20,'timeout':10,'allowed_updates':['message','callback_query']})
    if not isinstance(updates,list) or len(updates)>20:raise TelegramFailure()
    previous=offset-1
    for update in updates:
        if not isinstance(update,dict) or type(update.get('update_id')) is not int or not previous<update['update_id']<2**63-1:raise TelegramFailure()
        previous=update['update_id']
    for update in updates:
        bot.process(update)
        callback=update.get('callback_query')
        if isinstance(callback,dict) and isinstance(callback.get('id'),str) and len(callback['id'])<=256:
            try:api.call('answerCallbackQuery',{'callback_query_id':callback['id']})
            except TelegramFailure:pass
        with bot.factory() as conn,conn.transaction():
            limits(conn);conn.execute('UPDATE telegram_runtime SET next_offset=GREATEST(next_offset,%s) WHERE singleton=1',(update['update_id']+1,))
    bot.fanout()
    for _ in range(10):
        if not sender.send_one():break
    for _ in range(10):
        if not sender.cleanup_one():break
    return len(updates)
