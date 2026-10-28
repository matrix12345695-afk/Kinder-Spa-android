"""Real PostgreSQL, wire protocol and native QR acceptance; synthetic data only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.request

import psycopg
from PIL import Image

from auth_fixtures import Fixture,PASSWORD
import test_postgres as accounting
from kinder.auth import Denied
from kinder.api import App
from kinder.store import Rejected,token_hash
from kinder.telegram_bot import Bot,Unbound,peer_update,tr
from kinder.telegram_delivery import TelegramAPI,TelegramFailure,Sender,poll_once,qr_png,decode_photo
from kinder.telegram_runner import token_file,connection_factory,verify_identity,main

BOT_ID=123456
TOKEN=str(BOT_ID)+':'+('x'*35)


def update(ident,peer,text):
    return {'update_id':ident,'message':{'from':{'id':peer,'is_bot':False},'chat':{'id':peer,'type':'private'},'text':text}}


def callback(ident,peer,text):
    return {'update_id':ident,'callback_query':{'id':'synthetic_'+str(ident),'from':{'id':peer,'is_bot':False},
            'message':{'from':{'id':BOT_ID,'is_bot':True},'chat':{'id':peer,'type':'private'}},'data':text}}


class FakeAPI:
    def __init__(self):self.sent=[];self.updates=[];self.error=None
    def call(self,method,value,*,photo=None):
        if method=='getUpdates':return self.updates
        if method in ('deleteMessage','answerCallbackQuery'):self.sent.append((method,value,None));return True
        if self.error:raise self.error
        self.sent.append((method,value,photo))
        return {'message_id':len(self.sent)+100,'chat':{'id':value['chat_id']}}


class TelegramTests(Fixture):
    book=accounting.PostgresTests.book
    late=accounting.PostgresTests.late
    qr=accounting.PostgresTests.qr
    def setUp(self):
        super().setUp()
        self.conn.execute((Path(__file__).parents[1]/'telegram_schema.sql').read_text())
        self.conn.execute('INSERT INTO credentials SELECT %s,%s,salt,verifier,1 FROM credentials LIMIT 1',(self.superadmin,'super_fixture'))
        self.bot=Bot(self.factory,clock=lambda:self.now);self.bot.configure(BOT_ID)
        self.api=FakeAPI();self.sender=Sender(self.bot,self.api);self.uid=100

    def uid_next(self):self.uid+=1;return self.uid
    def link(self,name='client_fixture',peer=101):
        value=self.bot.issue_link(self.login(name))
        self.bot.process(update(self.uid_next(),peer,'/start '+value['start_payload']))
        with self.factory() as conn,conn.transaction():return self.bot.identity(conn,peer)
    def command(self,text,peer=101):
        uid=self.uid_next();self.bot.process(update(uid,peer,text));return uid
    def click(self,text,peer=101):return self.bot.process(callback(self.uid_next(),peer,text))
    def action(self):return str(self.conn.execute('SELECT id FROM telegram_actions ORDER BY update_id DESC LIMIT 1').fetchone()[0])
    def drain(self):
        for _ in range(100):
            if not self.sender.send_one():break
    def who(self,peer):
        with self.factory() as conn,conn.transaction():return self.bot.identity(conn,peer)
    def restored(self):
        booking=self.late();self.store.restore_pool(self.admin,booking,'synthetic confidential reason','restore_fixture_key');return booking

    def test_link_hash_only(self):
        value=self.bot.issue_link(self.login());raw=value['start_payload'][5:]
        self.assertEqual(self.conn.execute('SELECT code_hash FROM telegram_link_codes').fetchone()[0],token_hash(raw))
        self.assertNotIn(raw,str(self.conn.execute('SELECT details FROM audit_events').fetchall()))
        self.assertEqual(value['valid_for_seconds'],600)

    def test_link_expiry(self):
        raw=self.bot.issue_link(self.login())['start_payload'][5:];self.now+=timedelta(minutes=10)
        with self.assertRaises(Unbound):self.bot.bind(101,1,raw)

    def test_link_reissue_revokes_previous(self):
        token=self.login();old=self.bot.issue_link(token)['start_payload'][5:];new=self.bot.issue_link(token)['start_payload'][5:]
        with self.assertRaises(Unbound):self.bot.bind(101,1,old)
        self.assertEqual(self.bot.bind(101,2,new)['account'],self.client)

    def test_link_single_use_and_recovery(self):
        raw=self.bot.issue_link(self.login())['start_payload'][5:]
        first=self.bot.bind(101,1,raw);self.assertEqual(self.bot.bind(101,1,raw),first)
        for peer,uid in ((102,1),(101,2)):
            with self.assertRaises(Unbound):self.bot.bind(peer,uid,raw)

    def test_link_invalidated_by_password_change(self):
        raw=self.bot.issue_link(self.login())['start_payload'][5:]
        self.auth.reset_client_password(self.login('admin_fixture'),self.client,'replacement-fixture-password')
        with self.assertRaises(Unbound):self.bot.bind(101,1,raw)

    def test_admin_cannot_issue_other_staff_link(self):
        token=self.login('admin_fixture')
        with self.assertRaises(Denied):self.bot.issue_link(token,self.superadmin)
        self.assertTrue(self.bot.issue_link(token,self.client)['start_payload'].startswith('link_'))

    def test_client_cannot_issue_others_link(self):
        with self.assertRaises(Denied):self.bot.issue_link(self.login(),self.other)

    def test_existing_binding_not_silently_taken_over(self):
        self.link();raw=self.bot.issue_link(self.login())['start_payload'][5:]
        with self.assertRaises(Unbound):self.bot.bind(202,20,raw)
        self.assertEqual(self.who(101)['account'],self.client)

    def test_groups_forwards_and_sender_spoof_rejected(self):
        for mutation in ('group','forward','sender','bot'):
            value=update(10,101,'/start')
            if mutation=='group':value['message']['chat']['type']='group'
            if mutation=='forward':value['message']['forward_origin']={}
            if mutation=='sender':value['message']['from']['id']=202
            if mutation=='bot':value['message']['from']['is_bot']=True
            self.assertFalse(self.bot.process(value))
        self.assertEqual(self.count('telegram_jobs'),0)

    def test_client_reads_only_owned_rows(self):
        who=self.link();other=self.store.issue_subscription(self.admin,self.other,{'pool':12},'other_subscription')['subscription_id']
        text,_=self.bot.read(who,'subscriptions');self.assertIn('3',str(who['account']))
        self.assertIn('4/4',text);self.assertNotIn('12/12',text)
        self.assertNotIn('№'+str(other)+' ·',text)

    def test_language_persists_and_localized_menu(self):
        self.link();uid=self.command('/language uz');self.assertEqual(self.who(101)['language'],'uz')
        row=self.conn.execute('SELECT payload FROM telegram_jobs WHERE dedup=%s',('update_'+str(uid),)).fetchone()[0]
        self.assertIn('Abonementlar',str(row['reply_markup']))

    def test_unbound_help_never_requests_password(self):
        self.command('/start');self.drain();text=self.api.sent[0][1]['text']
        self.assertIn('Пароль сюда не отправляйте',text);self.assertIsNone(self.conn.execute('SELECT binding_id FROM telegram_jobs').fetchone()[0])

    def test_duplicate_updates_create_one_job(self):
        self.link();value=update(300,101,'/subscriptions');self.bot.process(value);self.bot.process(value)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM telegram_jobs WHERE dedup='update_300'").fetchone()[0],1)
        with self.assertRaises(Unbound):self.bot.process(update(300,202,'/subscriptions'))

    def test_cancellation_requires_confirmation(self):
        self.link();booking=self.book();self.command('/cancel '+str(booking));self.assertEqual(self.remaining(),3)
        self.click('do:'+self.action());self.assertEqual(self.remaining(),4)

    def test_repeated_confirmation_cannot_double_refund(self):
        self.link();booking=self.book();self.command('/cancel '+str(booking));action=self.action()
        self.click('do:'+action);self.click('do:'+action)
        self.assertEqual(self.remaining(),4);self.assertEqual(self.conn.execute("SELECT count(*) FROM audit_events WHERE operation='cancel_pool'").fetchone()[0],1)

    def test_declined_confirmation_never_mutates(self):
        self.link();booking=self.book();self.command('/cancel '+str(booking));action=self.action();self.click('no:'+action);self.click('do:'+action)
        self.assertEqual(self.remaining(),3);self.assertEqual(self.conn.execute('SELECT state FROM telegram_actions').fetchone()[0],'rejected')

    def test_expired_confirmation_never_mutates(self):
        self.link();booking=self.book();self.command('/cancel '+str(booking));action=self.action();self.now+=timedelta(minutes=5)
        self.click('do:'+action);self.assertEqual(self.remaining(),3)

    def test_other_client_cannot_cancel_or_confirm(self):
        self.link();self.link('other_fixture',202);booking=self.book();self.command('/cancel '+str(booking),202);self.assertEqual(self.count('telegram_actions'),0)
        self.command('/cancel '+str(booking));self.click('do:'+self.action(),202);self.assertEqual(self.remaining(),3)

    def test_late_cancellation_keeps_existing_forfeit_rule(self):
        self.link();booking=self.book();self.now=accounting.START-timedelta(hours=13);self.command('/cancel '+str(booking));self.click('do:'+self.action())
        self.assertEqual(self.remaining(),3);self.assertEqual(self.conn.execute('SELECT state FROM bookings').fetchone()[0],'forfeited')

    def test_restore_is_staff_only_and_needs_reason(self):
        self.link();booking=self.late();self.command(f'/restore {booking} synthetic reason');self.assertEqual(self.count('telegram_actions'),0)
        self.link('admin_fixture',202);self.command(f'/restore {booking} bad',202);self.assertEqual(self.count('telegram_actions'),0)

    def test_no_recipient_keeps_outbox_waiting(self):
        self.restored();self.assertEqual(self.bot.fanout(),0);self.assertEqual(self.count('notification_outbox'),1)
        self.assertEqual(self.count('telegram_notification_batches'),0)

    def test_restore_creates_real_sender_receipt_without_reason_leak(self):
        self.link('super_fixture',303);self.link('admin_fixture',202);booking=self.late()
        self.command(f'/restore {booking} synthetic confidential reason',202);self.click('do:'+self.action(),202);self.bot.fanout();self.drain()
        row=self.conn.execute('SELECT state,message_id,payload FROM telegram_jobs WHERE outbox_id IS NOT NULL').fetchone()
        self.assertEqual(row[0],'delivered');self.assertIsInstance(row[1],int);self.assertNotIn('confidential',str(row[2]))
        self.assertIn('Причина сохранена',row[2]['text']);self.assertEqual(self.remaining(),4)

    def test_revoked_target_is_blocked_before_network(self):
        self.link('super_fixture',303);self.drain();self.api.sent.clear();self.restored();self.bot.fanout()
        self.conn.execute('UPDATE accounts SET enabled=false WHERE id=%s',(self.superadmin,));self.sender.send_one()
        self.assertFalse(self.api.sent);self.assertEqual(self.conn.execute('SELECT state FROM telegram_jobs WHERE outbox_id IS NOT NULL').fetchone()[0],'blocked')

    def test_fanout_is_one_job_per_snapshot_target(self):
        self.link('super_fixture',303);self.restored();self.assertEqual(self.bot.fanout(),1);self.assertEqual(self.bot.fanout(),0)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM telegram_jobs WHERE outbox_id IS NOT NULL').fetchone()[0],1)

    def test_delivery_retries_are_bounded(self):
        self.command('/start');self.api.error=TelegramFailure(503)
        for _ in range(12):self.sender.send_one();self.now+=timedelta(hours=2)
        row=self.conn.execute('SELECT state,attempts,message_id FROM telegram_jobs').fetchone();self.assertEqual(row,('failed',8,None))

    def test_permanent_failure_does_not_spin(self):
        self.command('/start');self.api.error=TelegramFailure(403);self.sender.send_one();self.now+=timedelta(days=1)
        self.assertFalse(self.sender.send_one());self.assertEqual(self.conn.execute('SELECT attempts FROM telegram_jobs').fetchone()[0],1)

    def test_telegram_retry_after_is_honored(self):
        self.command('/start');self.api.error=TelegramFailure(429,120);self.sender.send_one();self.now+=timedelta(seconds=119)
        self.assertFalse(self.sender.send_one());self.now+=timedelta(seconds=1);self.assertTrue(self.sender.send_one())

    def test_expired_lease_recovers_and_stale_failure_cannot_change_it(self):
        self.command('/start');old=self.sender.claim();self.now+=timedelta(seconds=45);new=self.sender.claim()
        self.assertEqual(old['id'],new['id']);self.assertNotEqual(old['lease'],new['lease']);self.assertFalse(self.sender.fail(old,403))
        self.assertTrue(self.sender.fail(new,503))

    def test_parallel_claims_select_job_once(self):
        self.command('/start');barrier=threading.Barrier(2)
        def claim():barrier.wait(timeout=5);return Sender(self.bot,self.api).claim()
        with ThreadPoolExecutor(max_workers=2) as pool:rows=list(pool.map(lambda _:claim(),range(2)))
        self.assertEqual(sum(r is not None for r in rows),1)

    def test_poll_offset_survives_restart_and_duplicate(self):
        self.api.updates=[update(500,101,'/start')];poll_once(self.bot,self.api,self.sender)
        self.assertEqual(self.conn.execute('SELECT next_offset FROM telegram_runtime').fetchone()[0],501)
        self.assertEqual(self.count('telegram_updates'),1);self.assertEqual(self.count('telegram_jobs'),1)

    def test_malformed_batch_never_advances_cursor(self):
        self.api.updates=[update(20,101,'/start'),update(19,101,'/start')]
        with self.assertRaises(TelegramFailure):poll_once(self.bot,self.api,self.sender)
        self.assertEqual(self.conn.execute('SELECT next_offset FROM telegram_runtime').fetchone()[0],0)

    def test_qr_photo_real_decode_and_cleanup_after_server_expiry(self):
        self.link();self.drain();booking=self.book();self.now=accounting.START;self.command('/qr '+str(booking));self.drain()
        method,value,photo=next(x for x in self.api.sent if x[0]=='sendPhoto');raw=decode_photo(photo)
        self.assertEqual(self.conn.execute('SELECT booking_id FROM qr_tokens WHERE token_hash=%s',(token_hash(raw),)).fetchone()[0],booking)
        self.assertNotIn(raw,str(self.conn.execute('SELECT payload FROM telegram_jobs').fetchall()))
        self.now+=timedelta(seconds=120);self.assertTrue(self.sender.cleanup_one());self.assertEqual(self.api.sent[-1][0],'deleteMessage')

    def test_staff_redeem_requires_confirm_and_is_single_use(self):
        self.link('admin_fixture',202);booking,raw=self.qr();self.command('/redeem '+raw,202)
        self.assertEqual(self.conn.execute('SELECT state FROM bookings').fetchone()[0],'reserved');action=self.action();self.click('do:'+action,202);self.click('do:'+action,202)
        self.assertEqual(self.conn.execute('SELECT state FROM bookings').fetchone()[0],'consumed')
        self.assertEqual(self.conn.execute("SELECT count(*) FROM audit_events WHERE operation='redeem'").fetchone()[0],1)

    def test_staff_photo_reader_produces_confirmation(self):
        self.link('admin_fixture',202);booking,raw=self.qr();png=qr_png(raw);calls=[]
        self.bot.qr_reader=lambda ident:(calls.append(ident) or decode_photo(png))
        value=update(self.uid_next(),202,'unused');value['message'].pop('text');value['message']['photo']=[{'file_id':'photo_fixture','width':328,'height':328,'file_size':len(png)}]
        self.bot.process(value);self.assertEqual(calls,['photo_fixture']);self.click('do:'+self.action(),202)
        self.assertEqual(self.conn.execute('SELECT state FROM bookings WHERE id=%s',(booking,)).fetchone()[0],'consumed')

    def test_client_photo_is_not_downloaded(self):
        self.link();self.bot.qr_reader=lambda _ :self.fail('client must not trigger photo download')
        value=update(self.uid_next(),101,'unused');value['message'].pop('text');value['message']['photo']=[{'file_id':'photo_fixture','width':328,'height':328,'file_size':100}]
        self.bot.process(value);self.assertEqual(self.count('telegram_actions'),0)

    def test_password_reset_revokes_pending_action(self):
        self.link();booking=self.book();self.command('/cancel '+str(booking));action=self.action()
        self.auth.reset_client_password(self.login('admin_fixture'),self.client,'replacement-fixture-password')
        self.click('do:'+action);self.assertEqual(self.remaining(),3)

    def test_unlink_confirmation_blocks_queued_private_replies(self):
        self.link();self.command('/subscriptions');self.command('/unlink');self.click('do:'+self.action());self.drain()
        self.assertEqual(self.conn.execute('SELECT count(*) FROM telegram_bindings WHERE active').fetchone()[0],0)
        self.assertTrue(all(v[1].get('text')==tr('unlinked') for v in self.api.sent))
        self.assertGreater(self.conn.execute("SELECT count(*) FROM telegram_jobs WHERE state='blocked'").fetchone()[0],0)

    def test_ambiguous_telegram_response_never_marks_delivered(self):
        self.command('/start');self.api.call=lambda *a,**k:{'message_id':99,'chat':{'id':999}}
        self.sender.send_one();self.assertEqual(self.conn.execute('SELECT state,message_id FROM telegram_jobs').fetchone(),('pending',None))

    def test_receipt_database_failure_is_recovered_via_lease(self):
        self.command('/start');self.conn.execute("ALTER TABLE telegram_jobs ADD CONSTRAINT fail_receipt CHECK(state!='delivered')")
        with self.assertRaises(psycopg.Error):self.sender.send_one()
        self.assertEqual(self.conn.execute('SELECT state,message_id FROM telegram_jobs').fetchone(),('leased',None))
        self.conn.execute('ALTER TABLE telegram_jobs DROP CONSTRAINT fail_receipt');self.now+=timedelta(seconds=45);self.sender.send_one()
        self.assertEqual(self.conn.execute('SELECT state FROM telegram_jobs').fetchone()[0],'delivered');self.assertEqual(len(self.api.sent),2)

    def test_confirm_decline_race_is_serialized(self):
        who=self.link();booking=self.book();self.command('/cancel '+str(booking));action=self.action();barrier=threading.Barrier(2)
        def run(approved):
            barrier.wait(timeout=5)
            try:return self.bot.confirm(who,action,approved)
            except Rejected:return None
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(run,[True,False]))
        row=self.conn.execute('SELECT state FROM telegram_actions').fetchone()[0]
        self.assertIn(row,('applied','rejected'));self.assertEqual(self.remaining(),4 if row=='applied' else 3)

    def test_api_link_routes_are_opt_in_and_authorized(self):
        token=self.login('admin_fixture');self.assertEqual(self.call('POST','/v1/telegram/link',token=token)[0],404)
        self.app=App(self.factory,clock=lambda:self.now,telegram_enabled=True)
        self.assertEqual(self.call('POST','/v1/telegram/link',token=token)[0],201)
        self.assertEqual(self.call('POST',f'/v1/clients/{self.client}/telegram-link',token=token)[0],201)
        self.assertEqual(self.call('POST',f'/v1/clients/{self.superadmin}/telegram-link',token=token)[0],401)

    def test_qr_pending_action_stores_only_hash(self):
        self.link('admin_fixture',202);_,raw=self.qr();self.command('/redeem '+raw,202)
        rows=str(self.conn.execute('SELECT kind,reason,qr_hash FROM telegram_actions').fetchall())
        self.assertNotIn(raw,rows);self.assertIn(token_hash(raw),rows)

    def test_disabled_account_loses_access(self):
        self.link();self.conn.execute('UPDATE accounts SET enabled=false WHERE id=%s',(self.client,));self.command('/subscriptions');self.drain()
        self.assertFalse(any('4/4' in x[1].get('text','') for x in self.api.sent))

    def test_singleton_poll_lock_is_exclusive(self):
        with self.factory() as one,self.factory() as two:
            self.assertTrue(one.execute('SELECT pg_try_advisory_lock(74192369,%s)',(BOT_ID,)).fetchone()[0])
            self.assertFalse(two.execute('SELECT pg_try_advisory_lock(74192369,%s)',(BOT_ID,)).fetchone()[0])

    def test_wire_update_to_postgres_to_notification_receipt(self):
        token=self.login('admin_fixture');client_link=self.bot.issue_link(token,self.client)['start_payload'];super_link=self.bot.issue_link(self.login('super_fixture'))['start_payload']
        requests=[];items=[];pngs=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*a):pass
            def do_POST(handler):
                method=handler.path.rsplit('/',1)[-1];body=handler.rfile.read(int(handler.headers['Content-Length']));value=json.loads(body) if method!='sendPhoto' else {}
                requests.append((method,value));result=items[:] if method=='getUpdates' else {'message_id':100+len(requests),'chat':{'id':value.get('chat_id')}}
                if method in ('answerCallbackQuery','deleteMessage'):result=True
                raw=json.dumps({'ok':True,'result':result}).encode();handler.send_response(200);handler.send_header('Content-Length',str(len(raw)));handler.end_headers();handler.wfile.write(raw)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        class LocalOpener:
            def open(_,request,timeout):
                self.assertTrue(request.full_url.startswith('https://api.telegram.org/bot'+TOKEN+'/'))
                local=urllib.request.Request(f'http://127.0.0.1:{server.server_port}/'+request.full_url.rsplit('/',1)[-1],data=request.data,headers=dict(request.headers))
                return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(local,timeout=timeout)
        try:
            api=TelegramAPI(TOKEN,opener=LocalOpener());sender=Sender(self.bot,api)
            items[:]=[update(800,101,'/start '+client_link),update(801,303,'/start '+super_link)];poll_once(self.bot,api,sender)
            booking=self.restored();items.clear();poll_once(self.bot,api,sender)
            delivery=self.conn.execute('SELECT state,message_id FROM telegram_jobs WHERE outbox_id IS NOT NULL').fetchone()
            self.assertEqual(delivery[0],'delivered');self.assertGreater(delivery[1],0)
            notification=next(v for m,v in requests if m=='sendMessage' and 'Сеанс восстановлен' in v['text'])
            self.assertEqual(notification['chat_id'],303);self.assertNotIn('confidential',notification['text'])
        finally:server.shutdown();server.server_close();thread.join(timeout=2)

    def test_multiple_superadmin_targets_keep_language(self):
        self.link('super_fixture',303)
        actor=self.conn.execute("INSERT INTO accounts(role) VALUES('superadmin') RETURNING id").fetchone()[0]
        self.conn.execute('INSERT INTO credentials SELECT %s,%s,salt,verifier,1 FROM credentials LIMIT 1',(actor,'second_super_fixture'))
        self.link('second_super_fixture',404);self.command('/language uz',404);self.restored();self.assertEqual(self.bot.fanout(),2)
        rows=self.conn.execute('SELECT peer_id,payload FROM telegram_jobs WHERE outbox_id IS NOT NULL ORDER BY peer_id').fetchall()
        self.assertIn('Сеанс восстановлен',rows[0][1]['text']);self.assertIn('Seans tiklandi',rows[1][1]['text'])

    def test_client_cannot_generate_other_client_qr(self):
        self.link('other_fixture',202);booking=self.book();self.now=accounting.START;uid=self.command('/qr '+str(booking),202);self.drain()
        self.assertEqual(self.count('qr_tokens'),0);self.assertEqual(self.conn.execute('SELECT state FROM telegram_jobs WHERE dedup=%s',('update_'+str(uid),)).fetchone()[0],'failed')

    def test_revocation_serializes_with_inflight_private_send(self):
        self.link();self.drain();uid=self.command('/subscriptions');entered=threading.Event();release=threading.Event()
        original=self.api.call
        def slow(*a,**k):entered.set();release.wait(timeout=3);return original(*a,**k)
        self.api.call=slow
        with ThreadPoolExecutor(max_workers=2) as pool:
            sending=pool.submit(self.sender.send_one);self.assertTrue(entered.wait(timeout=3))
            def revoke():
                with self.factory() as conn,conn.transaction():conn.execute('UPDATE accounts SET enabled=false WHERE id=%s',(self.client,))
            revoking=pool.submit(revoke)
            self.assertFalse(revoking.done());release.set();self.assertTrue(sending.result(timeout=4));revoking.result(timeout=4)
        self.assertEqual(self.conn.execute('SELECT state FROM telegram_jobs WHERE dedup=%s',('update_'+str(uid),)).fetchone()[0],'delivered')

    def test_action_state_and_accounting_commit_are_atomic(self):
        who=self.link();booking=self.book();self.command('/cancel '+str(booking));action=self.action()
        self.conn.execute("ALTER TABLE telegram_actions ADD CONSTRAINT reject_fixture CHECK(state!='applied')")
        with self.assertRaises(psycopg.Error):self.bot.confirm(who,action,True)
        self.assertEqual(self.remaining(),3);self.assertEqual(self.conn.execute('SELECT state FROM telegram_actions').fetchone()[0],'pending')

    def test_role_change_blocks_delayed_staff_reply(self):
        who=self.link('admin_fixture',202);self.drain();self.api.sent.clear();self.command('/subscriptions',202)
        self.conn.execute("UPDATE accounts SET role='client' WHERE id=%s",(self.admin,))
        text,_=self.bot.read(who,'subscriptions');self.assertNotIn('4/4',text)
        self.drain();self.assertFalse(self.api.sent)

    def test_invalid_large_identifiers_do_not_poison_polling(self):
        self.link('admin_fixture',202);self.command('/restore '+('9'*100)+' synthetic reason',202)
        self.command('/link '+('9'*100),202);self.command('/qr '+('9'*100),202)
        self.assertEqual(self.count('telegram_actions'),0)
        self.assertEqual(self.count('telegram_updates'),4)

    def test_admin_issues_client_link_without_plaintext_job_secret(self):
        self.bot.configure(BOT_ID,'kinder_fixture_bot');self.link('admin_fixture',202);self.drain();self.api.sent.clear()
        uid=self.command('/link '+str(self.client),202)
        self.assertNotIn('link_',str(self.conn.execute('SELECT payload FROM telegram_jobs WHERE dedup=%s',('update_'+str(uid),)).fetchone()[0]))
        self.drain();text=self.api.sent[-1][1]['text'];self.assertIn('https://t.me/kinder_fixture_bot?start=link_',text)
        payload=text.split('?start=')[1];self.bot.process(update(self.uid_next(),101,'/start '+payload))
        self.assertEqual(self.who(101)['account'],self.client)

    def test_invalid_qr_returns_private_feedback(self):
        self.link();booking=self.book();uid=self.command('/qr '+str(booking));self.drain()
        self.assertTrue(any(tr('rejected') in v[1].get('text','') for v in self.api.sent))

    def test_bot_database_identity_cannot_be_swapped(self):
        with self.assertRaises(ValueError):self.bot.configure(BOT_ID+1)


class TransportTests(unittest.TestCase):
    class Response(io.BytesIO):
        def getcode(self):return 200
    def api(self,value):
        class Opener:
            def open(_,request,timeout):return TransportTests.Response(value)
        return TelegramAPI(TOKEN,opener=Opener())

    def test_fixed_method_allowlist(self):
        with self.assertRaises(TelegramFailure):self.api(b'{}').call('https://other.example',{})

    def test_redirects_are_not_followed(self):
        from kinder.telegram_delivery import NoRedirect
        self.assertIsNone(NoRedirect().redirect_request(None,None,None,None,None,None))

    def test_errors_do_not_contain_token_url_or_provider_description(self):
        raw=json.dumps({'ok':False,'error_code':403,'description':TOKEN+' provider secret'}).encode()
        with self.assertRaises(TelegramFailure) as caught:self.api(raw).call('getMe',{})
        self.assertNotIn(TOKEN,str(caught.exception));self.assertEqual(caught.exception.code,403)

    def test_invalid_and_oversize_json_rejected(self):
        for value in (b'not-json',b'[]',b'{"ok":1}',b'x'*1048577):
            with self.assertRaises(TelegramFailure):self.api(value).call('getMe',{})

    def test_retry_after_bounds(self):
        self.assertEqual(TelegramFailure(429,999999).retry_after,3600)
        self.assertEqual(TelegramFailure('invalid','invalid').code,0)

    def test_secret_file_permissions_symlinks_and_protected_paths(self):
        with tempfile.TemporaryDirectory(prefix='kinder-token-test-') as folder:
            path=Path(folder)/'telegram.token';path.write_text(TOKEN);path.chmod(0o600);self.assertEqual(token_file(str(path)),TOKEN)
            path.chmod(0o644)
            with self.assertRaises(ValueError):token_file(str(path))
            path.chmod(0o600);link=Path(folder)/'link';link.symlink_to(path)
            with self.assertRaises(ValueError):token_file(str(link))
        for path in ('relative.token','/home/maksim/inventory-bot/.env','/home/maksim/.ultimate-review-data/token'):
            with self.assertRaises(ValueError):token_file(path)

    def test_runner_disabled_before_any_secret_read(self):
        with patch.dict(os.environ,{},clear=True),patch('kinder.telegram_runner.token_file',side_effect=AssertionError('must not read')):
            self.assertEqual(main([]),2)

    def test_foreign_database_or_tls_scope_rejected(self):
        for dsn,db,schema in [('dbname=inventory host=localhost','inventory','public'),('dbname=kinder_spa host=remote.example','kinder_spa','public'),('dbname=kinder_spa host=localhost options=-cfoo=bar','kinder_spa','public'),('dbname=kinder_spa host=localhost','kinder_spa','public,inventory')]:
            with self.assertRaises(ValueError):connection_factory(dsn,db,schema)

    def test_existing_webhook_and_wrong_bot_are_not_changed(self):
        class API:
            def call(_,method,value):return {'id':BOT_ID,'is_bot':True,'username':'kinder_fixture_bot'} if method=='getMe' else {'url':'https://existing.example'}
        with self.assertRaises(ValueError):verify_identity(API(),BOT_ID)
        with self.assertRaises(ValueError):verify_identity(API(),BOT_ID+1)

    def test_decoder_rejects_non_qr_and_oversize_images(self):
        for raw in (b'not-an-image',b'x'*2097153):
            with self.assertRaises(Rejected):decode_photo(raw)
        output=io.BytesIO();Image.new('L',(100,100),255).save(output,format='PNG')
        with self.assertRaises(Rejected):decode_photo(output.getvalue())

    def test_decoder_reads_real_jpeg_and_png(self):
        raw='B'*43;png=qr_png(raw);self.assertEqual(decode_photo(png),raw)
        output=io.BytesIO();Image.open(io.BytesIO(png)).save(output,format='JPEG',quality=90)
        self.assertEqual(decode_photo(output.getvalue()),raw)

    def test_file_path_escape_is_rejected(self):
        value={'ok':True,'result':{'file_id':'fixture','file_size':100,'file_path':'../../other.token'}}
        with self.assertRaises(Rejected):self.api(json.dumps(value).encode()).read_photo_qr('fixture')

    def test_oversize_photo_metadata_rejected_before_download(self):
        value={'ok':True,'result':{'file_id':'fixture','file_size':2097153,'file_path':'photos/file_1.jpg'}}
        with self.assertRaises(Rejected):self.api(json.dumps(value).encode()).read_photo_qr('fixture')

    def test_malformed_update_types_fail_closed(self):
        for value in (None,[],{}, {'update_id':True}, {'update_id':1,'message':'bad'}, {'update_id':1,'message':{'chat':None,'from':{}}}):
            self.assertIsNone(peer_update(value))

    def test_real_wire_file_download_decode_and_multipart_photo(self):
        raw='D'*43;png=qr_png(raw);captured=[]
        from email.parser import BytesParser
        from email.policy import default
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*a):pass
            def do_GET(handler):
                handler.send_response(200);handler.send_header('Content-Length',str(len(png)));handler.end_headers();handler.wfile.write(png)
            def do_POST(handler):
                body=handler.rfile.read(int(handler.headers['Content-Length']))
                if handler.path.endswith('getFile'):result={'file_id':'fixture_photo','file_size':len(png),'file_path':'photos/file_1.png'}
                else:
                    message=BytesParser(policy=default).parsebytes(('Content-Type: '+handler.headers['Content-Type']+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+body)
                    fields={part.get_param('name',header='content-disposition'):part.get_payload(decode=True) for part in message.iter_parts()}
                    captured.append(fields);result={'message_id':171,'chat':{'id':int(fields['chat_id'])}}
                response=json.dumps({'ok':True,'result':result}).encode();handler.send_response(200);handler.send_header('Content-Length',str(len(response)));handler.end_headers();handler.wfile.write(response)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        class Opener:
            def open(_,request,timeout):
                self.assertTrue(request.full_url.startswith(('https://api.telegram.org/bot'+TOKEN+'/','https://api.telegram.org/file/bot'+TOKEN+'/')))
                local=urllib.request.Request(f'http://127.0.0.1:{server.server_port}/'+request.full_url.rsplit('/',1)[-1],data=request.data,headers=dict(request.headers))
                return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(local,timeout=timeout)
        try:
            api=TelegramAPI(TOKEN,opener=Opener());self.assertEqual(api.read_photo_qr('fixture_photo'),raw)
            receipt=api.call('sendPhoto',{'chat_id':101,'caption':'synthetic'},photo=png)
            self.assertEqual(receipt['chat']['id'],101);self.assertEqual(decode_photo(captured[0]['photo']),raw)
        finally:server.shutdown();server.server_close();thread.join(timeout=2)

    def test_png_has_quiet_border_and_bounded_dimensions(self):
        value=qr_png('C'*43)
        with Image.open(io.BytesIO(value)) as image:
            self.assertLessEqual(image.width,512);self.assertEqual(image.getpixel((0,0)),255);self.assertEqual(image.width,image.height)
        self.assertLess(len(value),200000)
