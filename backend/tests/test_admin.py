from io import BytesIO
from pathlib import Path

from auth_fixtures import Fixture
from kinder.api import App


class AdminBoundaryTests(Fixture):
    def configured(self):
        self.app = App(self.factory, clock=lambda:self.now, browser_origin='https://kinder.example')

    def test_same_origin_browser_can_use_authenticated_api(self):
        self.configured()
        token=self.login('admin_fixture')
        self.assertEqual(self.call('GET','/v1/me',token=token,environ={'HTTP_HOST':'kinder.example','HTTP_ORIGIN':'https://kinder.example'})[0],200)

    def test_unconfigured_api_retains_foreign_origin_denial(self):
        self.assertEqual(self.call('GET','/health',environ={'HTTP_ORIGIN':'https://kinder.example'})[0],403)

    def test_foreign_and_null_origin_rejected(self):
        self.configured()
        for origin in ('https://evil.example','null','https://kinder.example.evil','https://kinder.example/'):
            self.assertEqual(self.call('GET','/health',environ={'HTTP_HOST':'kinder.example','HTTP_ORIGIN':origin})[0],403)

    def test_host_fence_does_not_trust_forwarded_host(self):
        self.configured()
        self.assertEqual(self.call('GET','/health',environ={'HTTP_HOST':'other.example','HTTP_X_FORWARDED_HOST':'kinder.example'})[0],421)

    def test_bad_browser_origin_configuration_refused(self):
        for origin in ('http://kinder.example','https://user@kinder.example','https://kinder.example/','https://kinder.example?q=1','https://kinder.example:99999',123):
            with self.assertRaises(ValueError):App(self.factory,browser_origin=origin)

    def test_only_explicit_loopback_test_mode_allows_http_origin(self):
        App(self.factory,require_https=False,browser_origin='http://127.0.0.1:8123')
        with self.assertRaises(ValueError):App(self.factory,require_https=False,browser_origin='http://0.0.0.0:8123')

    def test_fixed_assets_are_served_without_database_with_restrictive_headers(self):
        def forbidden():raise AssertionError('static request opened DB')
        app=App(forbidden,browser_origin='https://kinder.example')
        for path in ('/admin','/admin/','/admin/app.js','/admin/styles.css','/admin/icon.svg'):
            response=[]
            content=b''.join(app({'REQUEST_METHOD':'GET','PATH_INFO':path,'QUERY_STRING':'','HTTP_HOST':'kinder.example','wsgi.url_scheme':'https','CONTENT_LENGTH':'0'},lambda s,h:response.extend((s,dict(h)))))
            self.assertTrue(response[0].startswith('200'))
            self.assertGreater(len(content),100)
            self.assertEqual(response[1]['Cache-Control'],'no-store')
            if path in ('/admin','/admin/'):
                self.assertIn("script-src 'self'",response[1]['Content-Security-Policy'])
                self.assertNotIn('unsafe-inline',response[1]['Content-Security-Policy'])

    def test_static_queries_posts_and_traversal_do_not_expose_files(self):
        self.configured()
        for path,method,extra in (('/admin','POST',{}),('/admin','GET',{'QUERY_STRING':'x=1'}),('/admin/../auth_schema.sql','GET',{})):
            self.assertIn(self.call(method,path,environ={'HTTP_HOST':'kinder.example',**extra})[0],(400,401,404))

    def test_audit_staff_only_and_bound_to_real_outbox(self):
        self.assertEqual(self.call('GET','/v1/audit',token=self.login())[0],403)
        actor=self.admin
        event=self.store._audit(actor,'restore_pool',self.client,self.now,{'reason':'synthetic reason'})
        self.conn.execute("INSERT INTO notification_outbox(event_id,recipient_role,kind,created_at) VALUES(%s,'superadmin','session_restored',%s)",(event,self.now))
        token=self.login('admin_fixture')
        rows=self.call('GET','/v1/audit',token=token)[1]['items']
        record=next(r for r in rows if r['event_id']==event)
        self.assertEqual(record['details']['reason'],'synthetic reason')
        self.assertIs(record['notification_queued'],True)
        self.assertNotIn('delivered',record)

    def test_audit_pagination_returns_disjoint_max50_rows(self):
        for i in range(55):self.store._audit(self.admin,'book',self.client,self.now,{'fixture':i})
        token=self.login('admin_fixture')
        first=self.call('GET','/v1/audit',token=token)[1]['items']
        second=self.call('GET','/v1/audit',token=token,environ={'QUERY_STRING':'after='+str(first[-1]['event_id'])})[1]['items']
        self.assertEqual(len(first),50)
        self.assertTrue(second)
        self.assertTrue(all(r['event_id']>first[-1]['event_id'] for r in second))
