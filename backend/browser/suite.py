"""Actual Chromium -> local WSGI -> disposable PostgreSQL18. No production/stubs.

Fault tests deliberately abort or delay one real HTTP response; ordinary business
flows use the actual API, credential checks, accounting transactions and outbox.
"""
from datetime import timedelta
import json
import os
from pathlib import Path
import threading
import time
import unittest
from wsgiref.simple_server import make_server, WSGIRequestHandler
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer

from playwright.sync_api import sync_playwright, expect
from auth_fixtures import Fixture, PASSWORD
from kinder.api import App
import test_postgres as accounting

OUTPUT=Path(__file__).resolve().parents[2]/'admin-evidence'
BROWSER_VERSION=None
SHOTS=[]


class ThreadServer(ThreadingMixIn,WSGIServer):
    daemon_threads=True


class Quiet(WSGIRequestHandler):
    def log_message(self,*args):pass


class BrowserTests(Fixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        global BROWSER_VERSION
        cls.playwright=sync_playwright().start()
        opts={'headless':True,'args':['--disable-background-networking']}
        if os.environ.get('KINDER_TEST_CHROMIUM'):opts['executable_path']=os.environ['KINDER_TEST_CHROMIUM']
        cls.browser=cls.playwright.chromium.launch(**opts)
        BROWSER_VERSION=cls.browser.version

    @classmethod
    def tearDownClass(cls):
        cls.browser.close();cls.playwright.stop()

    def setUp(self):
        super().setUp()
        self.server=make_server('127.0.0.1',0,lambda e,s:[],server_class=ThreadServer,handler_class=Quiet)
        self.origin='http://127.0.0.1:'+str(self.server.server_port)
        self.server.set_app(App(self.factory,require_https=False,clock=lambda:self.now,browser_origin=self.origin))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.context=self.browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce',service_workers='block',accept_downloads=False)
        self.errors=[];self.denied=[]
        def network(route):
            if not route.request.url.startswith(self.origin+'/'):
                self.denied.append('external request');return route.abort()
            route.continue_()
        self.context.route('**/*',network)
        self.context.route_web_socket('**',lambda ws:(self.denied.append('websocket'),ws.close()))
        self.page=self.context.new_page();self.page.on('pageerror',lambda e:self.errors.append(type(e).__name__))
        self.page.clock.install(time=self.now)
        self.page.goto(self.origin+'/admin')

    def tearDown(self):
        try:
            self.assertEqual(self.errors,[])
            self.assertEqual(self.denied,[])
        finally:
            self.context.close();self.server.shutdown();self.server.server_close();self.thread.join(timeout=5)
            super().tearDown()

    def sign_in(self,login='admin_fixture'):
        self.page.locator('#login-form [name=login]').fill(login)
        self.page.locator('#login-form [name=password]').fill(PASSWORD)
        self.page.locator('#login-form button').click()
        if login=='admin_fixture':expect(self.page.locator('#workspace')).to_be_visible()

    def nav(self,name):self.page.locator('[data-tab='+name+']').click()

    def loaded(self):expect(self.page.locator('#count-clients')).to_have_text('2')

    def screenshot(self,name):
        OUTPUT.mkdir(exist_ok=True)
        self.page.screenshot(path=str(OUTPUT/name),full_page=True)
        SHOTS.append(name)

    def test_login_logout_and_no_persistent_credentials(self):
        self.sign_in();self.loaded()
        storage=self.page.evaluate('({local:localStorage.length,session:sessionStorage.length,cookie:document.cookie})')
        self.assertEqual(storage,{'local':0,'session':0,'cookie':''})
        expect(self.page.locator('#login-form [name=password]')).to_have_value('')
        self.page.locator('#logout').click();expect(self.page.locator('#login-page')).to_be_visible()
        expect(self.page.locator('#clients-list')).to_be_empty()
        expect(self.page.locator('#identity')).to_be_empty()
        expect(self.page.locator('#subscription-form [name=client_id] option')).to_have_count(0)
        expect(self.page.locator('#count-clients')).to_have_text('—')

    def test_client_role_cannot_enter_panel(self):
        self.sign_in('client_fixture')
        expect(self.page.locator('#login-message')).to_have_text('Эта панель доступна только администраторам.')
        expect(self.page.locator('#workspace')).to_be_hidden()

    def test_invalid_credentials_have_no_sensitive_error(self):
        self.page.locator('#login-form [name=login]').fill('missing_fixture')
        self.page.locator('#login-form [name=password]').fill(PASSWORD)
        self.page.locator('#login-form button').click()
        expect(self.page.locator('#login-message')).to_contain_text('Проверьте логин')
        expect(self.page.locator('#workspace')).to_be_hidden()

    def test_language_switch_covers_login_and_workspace(self):
        self.page.locator('[data-lang=uz]').click()
        expect(self.page.locator('html')).to_have_attribute('lang','uz')
        expect(self.page.locator('#login-form button')).to_have_text('Panelga kirish →')
        self.sign_in();self.loaded();self.nav('subscriptions')
        expect(self.page.locator('#page-title')).to_have_text('Abonementlar')
        self.page.locator('[data-lang=ru]').click()
        expect(self.page.locator('#page-title')).to_have_text('Абонементы')

    def test_create_client_through_actual_ui_and_database(self):
        self.sign_in();self.loaded();self.nav('clients')
        self.page.locator('#client-form [name=login]').fill('new_browser_fixture')
        self.page.locator('#client-form [name=password]').fill(PASSWORD)
        self.page.locator('#client-form button').click()
        expect(self.page.locator('#clients-list')).to_contain_text('new_browser_fixture')
        self.assertEqual(self.conn.execute("SELECT count(*) FROM credentials WHERE login='new_browser_fixture'").fetchone()[0],1)
        expect(self.page.locator('#client-form [name=password]')).to_have_value('')

    def test_issue_package_and_create_pool_booking(self):
        self.sign_in();self.loaded();self.nav('subscriptions')
        self.page.locator('#subscription-form [name=client_id]').select_option(str(self.other))
        self.page.locator('#subscription-form [name=quota]').select_option('8')
        self.page.locator('#subscription-form button').click()
        expect(self.page.locator('#subscriptions-list')).to_contain_text('8 / 8')
        self.nav('bookings')
        self.page.locator('#booking-form [name=allowance]').select_option(str(self.subscription)+':pool')
        expect(self.page.locator('#booking-form [name=minutes]')).to_have_value('45')
        self.page.locator('#booking-form [name=starts_at]').fill('2026-11-02T09:00')
        self.page.locator('#booking-form button').click()
        expect(self.page.locator('#bookings-list')).to_contain_text('02.11.2026')
        self.assertEqual(self.remaining(),3)

    def test_service_quotas_do_not_offer_unapproved_packages(self):
        self.sign_in();self.loaded();self.nav('subscriptions')
        for category,expected in (('pool',['4','8','12']),('massage',['10']),('hydromassage',['10'])):
            self.page.locator('#subscription-form [name=category]').select_option(category)
            self.assertEqual(self.page.locator('#subscription-form [name=quota] option').all_text_contents(),expected)

    def test_pool_cancel_restore_reason_and_audit_are_actual_transactions(self):
        booking=self.store.book(self.client,self.subscription,'pool',accounting.START,45,'browser_cancel')['booking_id']
        self.now=accounting.START-timedelta(hours=14);self.page.clock.set_fixed_time(self.now)
        self.sign_in();self.loaded();self.nav('bookings')
        self.page.get_by_role('button',name='Отменить запись',exact=True).click();self.page.locator('#confirm-action').click()
        expect(self.page.locator('#bookings-list')).to_contain_text('Сеанс списан')
        self.page.get_by_role('button',name='Восстановить',exact=True).click()
        self.page.locator('#confirm-action').click();expect(self.page.locator('#action-dialog')).to_be_visible()
        self.assertEqual(self.remaining(),3)
        self.page.locator('#action-input').fill('critical synthetic situation')
        self.page.locator('#confirm-action').click()
        expect(self.page.locator('#bookings-list')).to_contain_text('Сеанс восстановлен')
        self.assertEqual(self.remaining(),4);self.assertEqual(self.count('notification_outbox'),1)
        self.nav('audit');expect(self.page.locator('#audit-list')).to_contain_text('critical synthetic situation')
        expect(self.page.locator('#audit-list')).to_contain_text('доставка ещё не подтверждена')

    def test_redemption_uses_real_one_time_qr(self):
        booking=self.store.book(self.client,self.subscription,'pool',accounting.START,45,'browser_redeem')['booking_id']
        self.now=accounting.START;self.page.clock.set_fixed_time(self.now)
        qr=self.store.issue_qr(self.client,booking)['token']
        self.sign_in();self.loaded();self.nav('bookings')
        self.page.get_by_role('button',name='Отметить визит').click();self.page.locator('#action-input').fill(qr);self.page.locator('#confirm-action').click()
        expect(self.page.locator('#bookings-list')).to_contain_text('Посещение учтено')
        self.assertEqual(self.conn.execute('SELECT state FROM bookings WHERE id=%s',(booking,)).fetchone()[0],'consumed')

    def test_staff_camera_scan_fills_qr_without_auto_redeeming(self):
        booking = self.store.book(self.client, self.subscription, 'pool',
                                  accounting.START, 45, 'browser_cam_book')['booking_id']
        self.now = accounting.START
        self.page.clock.set_fixed_time(self.now)
        qr = self.store.issue_qr(self.client, booking)['token']
        self.sign_in()
        self.loaded()
        self.nav('bookings')
        self.page.evaluate("""token => {
          window.__cameraToken = token;
          window.__cameraStopped = 0;
          const stream = new MediaStream();
          Object.defineProperty(stream, 'getTracks', {value: () => [
            {stop: () => {window.__cameraStopped++;}}
          ]});
          Object.defineProperty(navigator, 'mediaDevices', {
            configurable: true, value: {getUserMedia: async () => stream}
          });
          Object.defineProperty(window, 'BarcodeDetector', {
            configurable: true, value: class {
              async detect() {return [{rawValue: window.__cameraToken}];}
            }
          });
          HTMLMediaElement.prototype.play = async function() {};
        }""", qr)
        self.page.get_by_role('button', name='Отметить визит', exact=True).click()
        expect(self.page.locator('#start-qr-scan')).to_be_visible()
        self.page.locator('#start-qr-scan').click()
        expect(self.page.locator('#action-input')).to_have_value(qr)
        expect(self.page.locator('#qr-scan-status')).to_have_text(
            'QR-код считан. Подтвердите посещение.')
        self.assertEqual(self.page.evaluate('window.__cameraStopped'), 1)
        self.assertTrue(self.page.evaluate(
            'document.getElementById("qr-scan-video").srcObject === null'))
        self.assertEqual(self.conn.execute(
            'SELECT state FROM bookings WHERE id=%s', (booking,)).fetchone()[0], 'reserved')
        self.page.locator('#confirm-action').click()
        expect(self.page.locator('#bookings-list')).to_contain_text('Посещение учтено')

    def test_late_camera_permission_cannot_restart_after_dialog_close(self):
        self.sign_in()
        self.loaded()
        self.nav('bookings')
        self.page.evaluate("""() => {
          window.__cameraStopped = 0;
          window.__cameraPending = null;
          Object.defineProperty(navigator, 'mediaDevices', {
            configurable: true,
            value: {getUserMedia: () => new Promise(resolve => {
              window.__cameraPending = resolve;
            })}
          });
          Object.defineProperty(window, 'BarcodeDetector', {
            configurable: true, value: class {async detect() {return [];}}
          });
        }""")
        self.page.get_by_role('button', name='Отметить визит', exact=True).click()
        self.page.locator('#start-qr-scan').click()
        expect(self.page.locator('#start-qr-scan')).to_be_disabled()
        self.page.locator('#cancel-dialog').click()
        expect(self.page.locator('#action-dialog')).to_be_hidden()
        self.page.evaluate("""() => {
          const stream = new MediaStream();
          Object.defineProperty(stream, 'getTracks', {value: () => [
            {stop: () => {window.__cameraStopped++;}}
          ]});
          window.__cameraPending(stream);
        }""")
        expect.poll(lambda: self.page.evaluate('window.__cameraStopped')).to_be(1)
        self.assertTrue(self.page.evaluate(
            'document.getElementById("qr-scan-video").srcObject === null'))

    def test_password_reset_revokes_existing_client_session(self):
        old=self.login();self.sign_in();self.loaded();self.nav('clients')
        self.page.locator('#clients-list .record').filter(has_text='client_fixture').get_by_role('button',name='Сбросить пароль').click()
        self.page.locator('#action-input').fill('new-synthetic-browser-password')
        self.page.locator('#confirm-action').click();expect(self.page.locator('#action-dialog')).to_be_hidden()
        from kinder.auth import Denied
        with self.assertRaises(Denied):self.auth.identify(old)

    def test_audit_text_cannot_execute_html(self):
        payload='<img src=x onerror="window.fixtureXss=1">'
        self.store._audit(self.admin,'restore_pool',self.client,self.now,{'reason':payload})
        self.sign_in();self.loaded();self.nav('audit')
        expect(self.page.locator('#audit-list')).to_contain_text(payload)
        self.assertIsNone(self.page.evaluate('window.fixtureXss'))
        expect(self.page.locator('#audit-list img')).to_have_count(0)

    def test_response_loss_retries_exact_same_accounting_key(self):
        self.sign_in();self.loaded();self.nav('subscriptions')
        self.page.locator('#subscription-form [name=client_id]').select_option(str(self.other))
        requests=[]
        def lose_once(route):
            if route.request.method!='POST':return route.continue_()
            requests.append(route.request.post_data_json)
            response=route.fetch()
            if len(requests)==1:return route.abort()
            route.fulfill(response=response)
        self.page.route('**/v1/subscriptions',lose_once)
        self.page.locator('#subscription-form button').click()
        expect(self.page.locator('#notice')).to_contain_text('Ответ не получен')
        self.page.locator('#subscription-form button').click()
        expect(self.page.locator('#notice')).to_have_text('Абонемент выдан.')
        self.assertEqual(len(requests),2);self.assertEqual(requests[0],requests[1])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM subscriptions WHERE client_id=%s',(self.other,)).fetchone()[0],1)

    def test_unknown_client_creation_blocks_blind_retry_and_clears_password(self):
        self.sign_in();self.loaded();self.nav('clients')
        def lose(route):
            if route.request.method!='POST':return route.continue_()
            route.fetch();route.abort()
        self.page.route('**/v1/clients',lose)
        self.page.locator('#client-form [name=login]').fill('uncertain_fixture')
        self.page.locator('#client-form [name=password]').fill(PASSWORD)
        self.page.locator('#client-form button').click()
        expect(self.page.locator('#notice')).to_contain_text('Результат неизвестен')
        expect(self.page.locator('#client-form button')).to_be_disabled()
        expect(self.page.locator('#client-form [name=password]')).to_have_value('')
        self.assertEqual(self.conn.execute("SELECT count(*) FROM credentials WHERE login='uncertain_fixture'").fetchone()[0],1)

    def test_expired_session_clears_data_and_returns_to_login(self):
        self.sign_in();self.loaded();self.now+=timedelta(hours=8)
        self.page.locator('#refresh').click()
        expect(self.page.locator('#login-page')).to_be_visible()
        expect(self.page.locator('#clients-list')).to_be_empty()
        expect(self.page.locator('#login-message')).to_contain_text('Сессия завершена')

    def test_refresh_does_not_claim_zero_after_network_failure(self):
        self.sign_in();self.loaded()
        self.page.route('**/v1/clients',lambda route:route.abort())
        self.page.locator('#refresh').click()
        expect(self.page.locator('#count-clients')).to_have_text('—')
        expect(self.page.locator('#notice')).to_contain_text('Не удалось загрузить')

    def test_paginated_clients_can_load_past_first50(self):
        salt,verifier=self.conn.execute('SELECT salt,verifier FROM credentials LIMIT 1').fetchone()
        for i in range(51):
            actor=self.conn.execute("INSERT INTO accounts(role) VALUES('client') RETURNING id").fetchone()[0]
            self.conn.execute('INSERT INTO credentials(account_id,login,salt,verifier) VALUES(%s,%s,%s,%s)',(actor,'page_fixture_'+str(i),salt,verifier))
        self.sign_in();expect(self.page.locator('#count-clients')).to_have_text('50');self.nav('clients')
        self.page.locator('[data-more=clients]').click()
        expect(self.page.locator('#clients-list .record')).to_have_count(53)
        expect(self.page.locator('[data-more=clients]')).to_be_hidden()

    def test_mobile_layout_language_and_logout_control(self):
        self.page.set_viewport_size({'width':360,'height':800})
        self.page.locator('[data-lang=uz]').click();self.screenshot('login-mobile-uz.png')
        self.sign_in();self.loaded();expect(self.page.locator('#logout')).to_be_visible()
        self.screenshot('overview-mobile-uz.png');self.nav('subscriptions')
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),360)
        self.screenshot('subscriptions-mobile-uz.png')

    def test_desktop_layout_and_synthetic_screenshots(self):
        self.screenshot('login-desktop-ru.png');self.sign_in();self.loaded()
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),1440)
        self.screenshot('overview-desktop-ru.png');self.nav('clients');self.screenshot('clients-desktop-ru.png')

    def test_keyboard_login_and_dialog_escape(self):
        self.page.locator('#login-form [name=login]').focus();self.page.keyboard.type('admin_fixture');self.page.keyboard.press('Tab');self.page.keyboard.type(PASSWORD);self.page.keyboard.press('Enter')
        expect(self.page.locator('#workspace')).to_be_visible();self.loaded();self.nav('clients')
        self.page.locator('#clients-list button').first.click();expect(self.page.locator('#action-dialog')).to_be_visible()
        self.page.locator('#action-input').fill('synthetic-dialog-secret')
        self.page.keyboard.press('Escape');expect(self.page.locator('#action-dialog')).to_be_hidden()
        expect(self.page.locator('#action-input')).to_have_value('')

    def test_browser_default_does_not_reuse_session_after_reload(self):
        self.sign_in();self.loaded();self.page.reload()
        expect(self.page.locator('#login-page')).to_be_visible()
        expect(self.page.locator('#workspace')).to_be_hidden()

    def test_double_click_cannot_issue_two_subscriptions(self):
        self.sign_in();self.loaded();self.nav('subscriptions')
        self.page.locator('#subscription-form [name=client_id]').select_option(str(self.other))
        self.page.locator('#subscription-form button').dblclick()
        expect(self.page.locator('#notice')).to_have_text('Абонемент выдан.')
        self.assertEqual(self.conn.execute('SELECT count(*) FROM subscriptions WHERE client_id=%s',(self.other,)).fetchone()[0],1)

    def test_delayed_read_after_logout_cannot_repopulate_private_data(self):
        self.sign_in();self.loaded()
        held=[]
        def delay(route):held.append((route,route.fetch()))
        self.page.route('**/v1/clients',delay)
        self.page.locator('#refresh').click()
        expect(self.page.locator('#refresh')).to_be_visible()
        # Poll Python-side routing state; do not require unsafe-eval in page CSP.
        deadline=time.monotonic()+5
        while not held and time.monotonic()<deadline:self.page.wait_for_timeout(25)
        self.assertTrue(held)
        self.page.locator('#logout').click();expect(self.page.locator('#login-page')).to_be_visible()
        with self.page.expect_response(lambda r:r.url.endswith('/v1/clients')):
            held[0][0].fulfill(response=held[0][1])
        self.page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
        expect(self.page.locator('#clients-list')).to_be_empty()
        expect(self.page.locator('#workspace')).to_be_hidden()

    def test_no_javascript_fallback_never_puts_password_in_url(self):
        context=self.browser.new_context(java_script_enabled=False)
        try:
            page=context.new_page();page.goto(self.origin+'/admin')
            page.locator('#login-form [name=login]').fill('admin_fixture')
            page.locator('#login-form [name=password]').fill(PASSWORD)
            with page.expect_response(lambda r:r.request.method=='POST') as response:
                page.locator('#login-form button').click()
            # Referrer-Policy may turn a native form POST Origin into "null";
            # either the Origin gate or non-JSON asset gate must reject it.
            self.assertIn(response.value.status,(400,403))
            self.assertEqual(response.value.url,self.origin+'/admin')
            self.assertNotIn(PASSWORD,page.url)
            self.assertNotIn('password=',page.url)
        finally:context.close()

    def test_saved_operation_reports_refresh_failure_without_inventing_zero(self):
        self.sign_in();self.loaded();self.nav('subscriptions')
        self.page.locator('#subscription-form [name=client_id]').select_option(str(self.other))
        def fail_read(route):
            if route.request.method=='GET':return route.abort()
            route.continue_()
        self.page.route('**/v1/subscriptions',fail_read)
        self.page.locator('#subscription-form button').click()
        expect(self.page.locator('#notice')).to_contain_text('Изменение сохранено, но обновить списки не удалось')
        expect(self.page.locator('#count-subscriptions')).to_have_text('—')
        self.assertEqual(self.conn.execute('SELECT count(*) FROM subscriptions WHERE client_id=%s',(self.other,)).fetchone()[0],1)
